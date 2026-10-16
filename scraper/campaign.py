"""Campaign trail: where candidates are showing up, plus recent headlines.

1. Mobilize (api.mobilize.us) - the public event API used by Democratic campaigns,
   county parties and allied groups. Gives exact venue + coordinates.
2. Google News RSS, filtered to an allow-list of established news outlets
   (wire services, major Texas papers, public radio, national networks on both sides).
   Headlines that describe a rally / town hall / visit are geocoded to the Texas
   city they mention and shown as "reported" stops.
Republican campaigns don't publish on a public event API, so their stops come
mainly from news reports; the site labels which source each pin came from.
"""
import re, time, html, json, hashlib, datetime as dt
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus, urlparse
from email.utils import parsedate_to_datetime
from common import fetch, SESSION, now_iso, save, load, STATIC

RELIABLE = {
    # wires / national
    "apnews.com", "reuters.com", "npr.org", "nytimes.com", "washingtonpost.com", "wsj.com", "bloomberg.com",
    "politico.com", "axios.com", "thehill.com", "cnn.com", "nbcnews.com", "abcnews.go.com", "cbsnews.com",
    "foxnews.com", "usatoday.com", "pbs.org", "nationalreview.com", "theatlantic.com", "newsweek.com",
    # Texas statewide / metro papers
    "texastribune.org", "houstonchronicle.com", "chron.com", "dallasnews.com", "statesman.com",
    "expressnews.com", "mysanantonio.com", "star-telegram.com", "elpasotimes.com", "texasmonthly.com",
    "caller.com", "lubbockonline.com", "mrt.com", "wacotrib.com", "myrgv.com", "tylerpaper.com",
    "beaumontenterprise.com", "chron.com", "reporternews.com", "gosanangelo.com", "amarillo.com",
    "timesrecordnews.com", "victoriaadvocate.com", "theeagle.com", "kdhnews.com", "dentonrc.com",
    "communityimpact.com", "sanantonioreport.org", "houstonlanding.org", "elpasomatters.org", "borderreport.com",
    # public radio / TV
    "kut.org", "keranews.org", "texasstandard.org", "tpr.org", "houstonpublicmedia.org", "marfapublicradio.org",
    "click2houston.com", "khou.com", "abc13.com", "fox26houston.com", "wfaa.com", "nbcdfw.com", "fox4news.com",
    "cbsnews.com", "kxan.com", "kvue.com", "fox7austin.com", "ksat.com", "kens5.com", "news4sa.com",
    "kfoxtv.com", "ktsm.com", "kwtx.com", "kcentv.com", "krgv.com", "valleycentral.com", "kiiitv.com",
    "kcbd.com", "everythinglubbock.com", "newswest9.com", "cbs7.com", "kltv.com", "cbs19.tv", "kbtx.com",
    "kxxv.com", "12newsnow.com", "kfdx.com", "ktab.com",
}
EVENT_WORDS = re.compile(r"\b(rall(y|ies)|town ?hall|campaign(s|ed)? (stop|in|through|across)|stump(s|ed)?|visit(s|ed)?|tour(s|ed)?|"
                         r"speaks?|spoke|addresse[sd]|meet[- ]and[- ]greet|block walk|barnstorm|swing through|crowd|supporters in|debate)\b", re.I)
SCANDAL = re.compile(r"\b(scandal|indict(ed|ment)?|investigat(ion|ed|ing)|probe|allegation|alleged|accus(ed|es|ation)|lawsuit|sued|ethics|complaint|subpoena|charged|arrest(ed)?|fraud|bribe(ry)?|impeach(ed|ment)?|misconduct|whistleblower|misled|false claim|controversy|controversial|under fire|backlash|apologi[sz]es)\b", re.I)
SAID = re.compile(r"\b(debate[sd]?|town ?hall|forum|interview|says|said|vows?|pledges?|promises?|argues?|calls for|slams|hits|attacks?|responds?|speech|remarks|op-ed|on the issues)\b", re.I)
NOT_EVENT = re.compile(r"\b(not scheduled|not joining|won.t attend|skips?|skipping|cancel+ed|cancels|postponed|correction|poll|polls|ad\b|ads\b|lawsuit|sues|ruling)\b", re.I)
LANDMARKS = {"the Alamo": "San Antonio", "Alamo Plaza": "San Antonio", "Texas Capitol": "Austin",
             "the Riverwalk": "San Antonio", "Rice University": "Houston", "UT Austin": "Austin", "Texas A&M": "College Station",
             "SMU": "Dallas", "TCU": "Fort Worth", "Baylor": "Waco", "UTEP": "El Paso", "UTSA": "San Antonio", "UTRGV": "Edinburg"}
MOBILIZE = "https://api.mobilize.us/v1/events?state=TX&per_page=100&timeslot_start=gte_{start}&timeslot_start=lt_{end}"
SPEAKING_TYPES = {"RALLY", "TOWN_HALL", "MEET_GREET", "COMMUNITY", "DEBATE_WATCH_PARTY", "FUNDRAISER", "SOCIAL_MEDIA_CAMPAIGN",
                  "OTHER", "SIGNATURE_GATHERING", "ADVOCACY_CALL", "LEADERSHIP", "WORKSHOP", "MEETING", "VOTER_REG"}


def candidates_from_races(races):
    out = []
    for k, r in races.items():
        for n in r.get("nominees", []):
            if n["party"] in ("D", "R"):
                parts = n["name"].replace(".", "").split()
                out.append({"name": n["name"], "party": n["party"], "race": k, "race_label": r["label"], "incumbent": n.get("incumbent"),
                            "first": parts[0], "last": parts[-1] if parts[-1].lower() not in ("jr", "sr", "ii", "iii") else parts[-2]})
    return out


def cand_id(c):
    return re.sub(r"[^a-z0-9]+", "-", c["name"].lower()).strip("-")


# ---------------------------------------------------------------- Mobilize
def mobilize_events(cands):
    now = int(time.time())
    end_ts = int(dt.datetime(2026, 11, 4, 6, tzinfo=dt.timezone.utc).timestamp())
    raw = []
    # page through in 4-day windows so we never hit the API's 1000-result cap
    t = now
    while t < max(end_ts, now + 86400 * 7):
        url = MOBILIZE.format(start=t, end=t + 86400 * 4)
        while url:
            d = SESSION.get(url, timeout=60).json()
            raw += d.get("data", [])
            url = d.get("next")
            time.sleep(0.3)
        t += 86400 * 4
    seen, events = set(), []
    for e in raw:
        if e["id"] in seen or e.get("visibility") != "PUBLIC": continue
        seen.add(e["id"])
        sp = e.get("sponsor") or {}
        title = e.get("title") or ""
        text = title + " " + (e.get("summary") or "")
        hits = []
        for c in cands:
            full = f"{c['first']} {c['last']}"
            own = sp.get("org_type") == "CAMPAIGN" and c["last"].lower() in (sp.get("name") or "").lower() and (
                c["first"].lower() in (sp.get("name") or "").lower() or len(c["last"]) >= 6 and c["last"].lower() not in ("garcia", "martinez", "hernandez", "gonzalez", "johnson", "williams"))
            if own or re.search(re.escape(full), text, re.I) or re.search(re.escape(c["name"]), text, re.I):
                hits.append(cand_id(c))
        if not hits: continue
        loc = e.get("location") or {}
        ll = (loc.get("location") or {})
        slots = [s for s in e.get("timeslots", []) if s["end_date"] >= now]
        if not slots: continue
        s0 = min(slots, key=lambda s: s["start_date"])
        events.append({
            "id": f"mob-{e['id']}", "source": "Mobilize", "kind": "scheduled",
            "title": title.strip(), "type": e.get("event_type"), "candidates": sorted(set(hits)),
            "host": sp.get("name"), "start": dt.datetime.fromtimestamp(s0["start_date"], dt.timezone.utc).isoformat(),
            "end": dt.datetime.fromtimestamp(s0["end_date"], dt.timezone.utc).isoformat(), "more_times": len(slots) - 1,
            "venue": loc.get("venue"), "address": ", ".join(x for x in (loc.get("address_lines") or []) if x),
            "city": loc.get("locality"), "zip": loc.get("postal_code"),
            "lat": ll.get("latitude"), "lng": ll.get("longitude"), "virtual": bool(e.get("is_virtual")),
            "url": e.get("browser_url"), "image": e.get("featured_image_url"),
        })
    print(f"  Mobilize: {len(raw)} TX events scanned, {len(events)} tied to nominees")
    return events


# ---------------------------------------------------------------- News
PLACES = None


def find_city(text, cand):
    global PLACES
    if PLACES is None:
        PLACES = json.load(open(f"{STATIC}/tx_places.json"))
    for lm, city in LANDMARKS.items():
        if lm in text and city in PLACES:
            return city, PLACES[city]
    skip = {"Alamo", cand["first"], cand["last"], "Texas", "Senate", "House", "Capitol", "Republican", "Democrat", "Democratic", "Governor"}
    pats = [r"\b([A-Z][a-zA-Z.'-]+(?:\s[A-Z][a-zA-Z.'-]+){0,2}),\s*(?:Texas|Tex\.|TX)\b",
            r"\b(?:in|at|to|visits?|visited|toured?|across|through|stop in|rally in)\s+(?:the\s+)?(?:city of\s+)?([A-Z][a-zA-Z.'-]+(?:\s[A-Z][a-zA-Z.'-]+){0,2})"]
    for p in pats:
        for m in re.finditer(p, text):
            name = m.group(1).strip()
            words = name.split()
            for k in range(len(words), 0, -1):  # longest match first: "Corpus Christi" before "Corpus"
                nm = " ".join(words[:k])
                if nm in PLACES and nm not in skip:
                    return nm, PLACES[nm]
    return None, None


def google_news(query):
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
    r = fetch(url, tries=3, base_sleep=10)
    items = []
    for it in ET.fromstring(r.content).iter("item"):
        src = it.find("source")
        dom = urlparse(src.get("url", "")).netloc.lower().replace("www.", "") if src is not None else ""
        if not any(dom == d or dom.endswith("." + d) for d in RELIABLE):
            continue
        title = html.unescape(it.findtext("title") or "")
        outlet = src.text if src is not None else dom
        title = re.sub(r"\s+-\s+" + re.escape(outlet or "") + r"$", "", title)
        try:
            pub = parsedate_to_datetime(it.findtext("pubDate")).astimezone(dt.timezone.utc).isoformat()
        except Exception:
            pub = None
        desc = re.sub("<[^>]+>", " ", html.unescape(it.findtext("description") or ""))
        items.append({"title": title, "url": it.findtext("link"), "outlet": outlet, "domain": dom, "published": pub, "desc": desc})
    return items


def news_and_reported_events(cands, competitive):
    news, events = {}, []
    for c in cands:
        cid = cand_id(c)
        statewide = not c["race"].startswith("tx")
        q = f'"{c["name"]}" when:14d' if statewide else f'"{c["name"]}" Texas when:14d'
        try:
            items = google_news(q)
        except Exception as e:
            print("  news error", c["name"], e); items = []
        time.sleep(1.2)
        if statewide:
            try:
                items += google_news(f'"{c["name"]}" (rally OR "town hall" OR visits OR tour OR "campaign stop") when:21d')
            except Exception:
                pass
            time.sleep(1.2)
        extra = []
        if statewide or c["race"] in competitive or c.get("incumbent"):
            for q2 in (f'"{c["name"]}" (debate OR "town hall" OR forum OR interview) when:60d',
                       f'"{c["name"]}" (scandal OR indicted OR investigation OR allegations OR lawsuit OR ethics OR controversy) when:365d'):
                try:
                    extra += google_news(q2)
                except Exception:
                    pass
                time.sleep(1.2)
        uniq = {}
        for it in items + extra:
            uniq.setdefault(it["title"], it)
        items = sorted(uniq.values(), key=lambda x: x["published"] or "", reverse=True)
        about = [it for it in items if c["last"].lower() in (it["title"] + " " + it["desc"]).lower()]
        pick = lambda xs, n: [{k: it[k] for k in ("title", "url", "outlet", "published")} for it in xs[:n]]
        news[cid] = {"latest": pick([it for it in about if not SCANDAL.search(it["title"])] or about, 8),
                     "said": pick([it for it in about if SAID.search(it["title"]) and not SCANDAL.search(it["title"])], 8),
                     "scrutiny": pick([it for it in about if SCANDAL.search(it["title"]) and c["last"].lower() in it["title"].lower()], 8)}
        for it in items:
            text = it["title"] + " " + it["desc"]
            if not EVENT_WORDS.search(it["title"]): continue
            if c["last"].lower() not in it["title"].lower(): continue  # must be about this candidate
            if NOT_EVENT.search(it["title"]): continue
            city, ll = find_city(text, c)
            if not city: continue
            events.append({"id": "news-" + hashlib.md5(it["url"].encode()).hexdigest()[:12], "source": it["outlet"], "kind": "reported",
                           "title": it["title"], "candidates": [cid], "start": it["published"], "city": city,
                           "lat": ll[0], "lng": ll[1], "url": it["url"], "virtual": False})
    print(f"  News: {sum(len(v['latest']) for v in news.values())} headlines, {sum(len(v['said']) for v in news.values())} 'said', {sum(len(v['scrutiny']) for v in news.values())} scrutiny, {len(events)} reported stops")
    return news, events


def run(races):
    cands = candidates_from_races(races)
    competitive = {k for k, r in races.items() if r.get("type") == "house" and any(
        re.search(r"toss|lean|tilt", x["rating"], re.I) for x in r.get("ratings", []))}
    old_ev = load("events.json", {}) or {}
    try:
        mob = mobilize_events(cands)
    except Exception as e:
        print("  Mobilize error", e)
        mob = [e for e in old_ev.get("events", []) if e["source"] == "Mobilize"]
    news, reported = news_and_reported_events(cands, competitive)
    # keep reported stops from the last 21 days (merge with previous runs)
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=21)).isoformat()
    prev = [e for e in old_ev.get("events", []) if e["kind"] == "reported" and (e.get("start") or "") >= cutoff]
    rep = {e["id"]: e for e in prev + reported}
    events = mob + sorted(rep.values(), key=lambda e: e.get("start") or "", reverse=True)
    save("events.json", {"updated": now_iso(), "events": events})
    old_news = (load("news.json", {}) or {}).get("news", {})
    for k, v in news.items():
        if any(v.values()) or k not in old_news or isinstance(old_news[k], list):
            old_news[k] = v
    save("news.json", {"updated": now_iso(), "news": old_news})
    return events, news
