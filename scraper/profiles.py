"""Candidate platforms ("what they promise") and voting records from Ballotpedia.

Ballotpedia is a nonpartisan, nonprofit encyclopedia. For each nominee we pull:
  * key messages from Ballotpedia's Candidate Connection survey (the candidate's own answers)
  * campaign-website issue positions, which Ballotpedia quotes from the campaign's site
  * for members of Congress, Ballotpedia's "Key votes" table (how they voted on marquee bills)
Everything keeps the candidate's own wording; the site shows short excerpts and links to the full page.
"""
import re, time, datetime as dt
from bs4 import BeautifulSoup
from common import fetch, load, save, now_iso

BP = "https://ballotpedia.org/"
HDR = {"User-Agent": "Mozilla/5.0 (compatible; TexasMidtermTracker/1.0; +https://github.com/Absinthe-007/Texas-Midterm-Tracker)"}
INDEX_PAGES = [
    "United_States_Senate_election_in_Texas,_2026",
    "United_States_House_of_Representatives_elections_in_Texas,_2026",
    "Texas_state_executive_official_elections,_2026",
    "Texas_Railroad_Commission_election,_2026",
]
VOTE_WORDS = {"yea", "nay", "not voting", "present", "aye", "no", "yes"}
AGAINST = re.compile(r"^(oppose|opposes|opposing|end|ending|stop|stopping|repeal|ban|eliminate|eliminating|block|fight against|reject|abolish|prevent|cut off|reverse|defund|no more)\b", re.I)


def clean(t):
    t = re.sub(r"\[\d+\]", "", t or "")
    return re.sub(r"\s+", " ", t).strip()


def short(t, n=220):
    t = clean(t)
    if len(t) <= n:
        return t
    m = re.match(r"(.{60,%d}?[.!?])(\s|$)" % n, t)
    return m.group(1) if m else t[:n].rsplit(" ", 1)[0] + "…"


def find_links(names):
    links = {}
    for p in INDEX_PAGES:
        try:
            soup = BeautifulSoup(fetch(BP + p, tries=3, base_sleep=10, headers=HDR).text, "lxml")
        except Exception as e:
            print("  bp index error", p, e); continue
        for a in soup.find_all("a", href=True):
            t = a.get_text(strip=True)
            if t in names and t not in links:
                h = a["href"]
                links[t] = h if h.startswith("http") else BP + h.lstrip("/")
        time.sleep(2)
    return links


def section(soup, h2_title):
    h = next((x for x in soup.find_all("h2") if clean(x.get_text()) == h2_title), None)
    if not h: return []
    out, el = [], h
    while True:
        el = el.find_next_sibling()
        if el is None or el.name == "h2": break
        out.append(el)
    return out


def themes_2026(soup):
    """Return the elements inside Campaign themes > 2026."""
    els = section(soup, "Campaign themes")
    out, on = [], False
    for el in els:
        if el.name == "h3":
            on = clean(el.get_text()) == "2026"
            continue
        if on: out.append(el)
    return out


def survey(els):
    msgs, passions = [], None
    for el in els:
        for trig in el.find_all(class_=re.compile("bp-collapsible-trigger|panel-heading|survey-question")):
            q = clean(trig.get_text()).lower()
            cid = trig.get("data-controls")
            body = el.find(id=cid) if cid else trig.find_next(class_=re.compile("bp-collapsible-content|panel-collapse|survey-response"))
            if not body: continue
            if "key messages" in q and not msgs:
                lis = [clean(li.get_text(" ")) for li in body.find_all("li")]
                if not lis:
                    lis = [clean(p.get_text(" ")) for p in body.find_all(["p", "div"]) if len(clean(p.get_text())) > 30 and not p.find(["p", "div"])]
                msgs = [short(x, 260) for x in lis if x][:4]
            elif "passionate" in q and not passions:
                passions = short(body.get_text(" "), 300)
    return msgs, passions


def website(els):
    """Issue headings + bullet points from the quoted campaign website."""
    box = None
    for i, el in enumerate(els):
        if "campaign website stated the following" in el.get_text():
            # the quote is usually the next block (div/blockquote), sometimes inside the same div
            box = el if len(el.get_text()) > 400 else (els[i + 1] if i + 1 < len(els) else None)
            break
    if box is None: return []
    issues, cur = [], None
    for node in box.find_all(["h2", "h3", "h4", "h5", "h6", "p", "li", "dt", "dd"]):
        if node.find(["p", "li"]): continue
        txt = clean(node.get_text(" "))
        if not txt or "campaign website stated the following" in txt or txt.lower().startswith("—"): continue
        bold = node.name.startswith("h") or node.name == "dt" or (node.find(["b", "strong"]) and len(clean(node.find(["b", "strong"]).get_text())) >= len(txt) - 2)
        if txt.lower() in ("campaign website", "campaign themes"): continue
        if bold and len(txt) < 90 and not (txt.endswith(".") and len(txt.split()) > 7):
            cur = {"issue": txt.rstrip(":"), "points": []}
            issues.append(cur)
        else:
            if cur is None:
                cur = {"issue": "Priorities", "points": []}; issues.append(cur)
            if len(cur["points"]) < 3:
                cur["points"].append(short(txt))
    issues = [x for x in issues if x["points"]]
    return issues[:8]


def key_votes(soup):
    votes = []
    for t in soup.find_all("table"):
        cap = t.find("caption")
        if not cap or "Key votes" not in cap.get_text(): continue
        congress = clean(cap.get_text()).replace("Key votes:", "").strip()
        body = t.find("tbody") or t
        for tr in body.find_all("tr", recursive=False):
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 2: continue
            vote = clean(tds[0].get_text())
            if vote.lower() not in VOTE_WORDS: continue
            cell = tds[1]
            title_el = cell.find("th") or cell.find(["b", "strong", "a"])
            title = clean(title_el.get_text()) if title_el else ""
            desc_el = next((td for td in cell.find_all("td") if len(clean(td.get_text())) > 60), None)
            desc = clean(desc_el.get_text(" ")) if desc_el else clean(cell.get_text(" ")).replace(title, "", 1)
            m = re.search(r"\(([HS]\.\s?(?:R|Con\.\s?Res|J\.\s?Res|Res)\.?\s?\d+)\)", desc)
            # a friendlier name: "One Big Beautiful Bill Act" etc. when the description says "also known as"
            aka = re.search(r"(?:also known as|or the) (?:the )?([A-Z][\w' -]{3,60}?(?:Act|Bill)(?: \([A-Z]+ Act\))?)", desc)
            name = aka.group(1) if aka else (title if len(title) < 90 else short(title, 90))
            votes.append({"vote": vote.title() if vote.lower() != "not voting" else "Not Voting", "bill": name,
                          "number": m.group(1) if m else None, "summary": short(desc, 240),
                          "status": clean(tds[2].get_text()) if len(tds) > 2 else None, "congress": congress})
    return votes[:24]


def noteworthy(soup, url):
    """Ballotpedia 'Noteworthy events' subsection titles (e.g. investigations, impeachment, indictments)."""
    out = []
    for el in section(soup, "Noteworthy events"):
        if el.name in ("h3", "h4"):
            hid = (el.find(class_="mw-headline") or el).get("id")
            out.append({"title": clean(el.get_text()), "url": url + ("#" + hid if hid else ""), "summary": None})
        elif el.name == "p" and out and not out[-1]["summary"] and len(clean(el.get_text())) > 60:
            out[-1]["summary"] = short(el.get_text(" "), 300)
    return out[:6]


def campaign_site(soup):
    for a in soup.find_all("a", href=True):
        if clean(a.get_text()).lower() == "campaign website" and a["href"].startswith("http") and "ballotpedia" not in a["href"]:
            return a["href"]
    return None


def parse_profile(html, url):
    soup = BeautifulSoup(html, "lxml")
    els = themes_2026(soup)
    msgs, passion = survey(els)
    issues = website(els)
    against = [p for i in issues for p in i["points"] if AGAINST.match(p)][:6]
    return {"url": url, "key_messages": msgs, "passions": passion, "issues": issues,
            "against": against, "key_votes": key_votes(soup), "noteworthy": noteworthy(soup, url),
            "website": campaign_site(soup), "fetched": now_iso()}


def run(races, max_fetch=100, max_age_days=2):
    cache = (load("profiles.json", {}) or {}).get("profiles", {})
    noms = {n["name"]: k for k, r in races.items() for n in r.get("nominees", []) if n["party"] in ("D", "R")}
    need = [n for n in noms if n not in cache or
            (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(cache[n]["fetched"])).days >= max_age_days]
    if not need:
        print("  Profiles: all fresh"); return cache
    links = find_links(set(need))
    # statewide first, then competitive order is fine
    need.sort(key=lambda n: 0 if not noms[n].startswith("tx") else 1)
    done = 0
    for name in need[:max_fetch]:
        url = links.get(name) or BP + name.replace(" ", "_")
        try:
            html = fetch(url, tries=3, base_sleep=10, headers=HDR).text
            if "2026" not in html or "Texas" not in html:
                print("  profile page doesn't look right:", name, url); continue
            cache[name] = parse_profile(html, url)
            done += 1
        except Exception as e:
            print("  profile error", name, e)
        time.sleep(2)
    with_votes = sum(1 for p in cache.values() if p["key_votes"])
    print(f"  Profiles: fetched {done}, cached {len(cache)}, {with_votes} with congressional key votes")
    save("profiles.json", {"updated": now_iso(), "source": "Ballotpedia", "profiles": cache})
    return cache
