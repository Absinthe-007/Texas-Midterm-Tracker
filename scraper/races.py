"""Scrape race info, nominees, ratings, fundraising and polls from Wikipedia's
2026 Texas race pages. Wikipedia poll tables are compiled by editors and every
row links back to the original pollster release, so each poll keeps its source link.
"""
import re, time, datetime as dt
from urllib.parse import unquote
from bs4 import BeautifulSoup
from common import fetch, now_iso, save, load

WIKI = "https://en.wikipedia.org/api/rest_v1/page/html/"

STATEWIDE = [
    ("senate", "U.S. Senate", "2026_United_States_Senate_election_in_Texas"),
    ("governor", "Governor", "2026_Texas_gubernatorial_election"),
    ("ltgov", "Lieutenant Governor", "2026_Texas_lieutenant_gubernatorial_election"),
    ("ag", "Attorney General", "2026_Texas_Attorney_General_election"),
    ("comptroller", "Comptroller", "2026_Texas_Comptroller_of_Public_Accounts_election"),
    ("land", "Land Commissioner", "2026_Texas_Land_Commissioner_election"),
    ("agriculture", "Agriculture Commissioner", "2026_Texas_Commissioner_of_Agriculture_election"),
    ("railroad", "Railroad Commissioner", "2026_Texas_Railroad_Commissioner_election"),
]
HOUSE_PAGE = "2026_United_States_House_of_Representatives_elections_in_Texas"

PARTY = {"republican": "R", "democratic": "D", "libertarian": "L", "green": "G", "independent": "I"}
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def clean(t):
    t = re.sub(r"\[\s*[^\]]{1,6}\s*\]", "", t or "")
    return re.sub(r"\s+", " ", t).strip()


def grid(table):
    """Expand a table into a 2D list of cells, honoring rowspan/colspan."""
    rows, spans = [], {}
    for tr in table.find_all("tr"):
        row, col = [], 0
        cells = tr.find_all(["th", "td"], recursive=False)
        ci = 0
        while ci < len(cells) or col in spans:
            if col in spans:
                cell, left = spans[col]
                row.append(cell)
                if left <= 1: del spans[col]
                else: spans[col] = (cell, left - 1)
                col += 1
                continue
            c = cells[ci]; ci += 1
            rs = int(re.sub(r"\D", "", c.get("rowspan", "1")) or 1)
            cs = int(re.sub(r"\D", "", c.get("colspan", "1")) or 1)
            for _ in range(cs):
                row.append(c)
                if rs > 1: spans[col] = (c, rs - 1)
                col += 1
        rows.append(row)
    return rows


def pct(s):
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", s or "")
    return float(m.group(1)) if m else None


def parse_date(s):
    """'Sep 28 – Oct 5, 2026' -> ('2026-09-28','2026-10-05')"""
    s = clean(s).replace("–", "-").replace("—", "-").replace(",", "")
    yrs = re.findall(r"(20\d\d)", s)
    year = int(yrs[-1]) if yrs else dt.date.today().year
    toks = re.findall(r"([A-Za-z]{3,})\.?\s*(\d{1,2})?", s)
    parts = []
    cur_m = None
    for mname, day in toks:
        k = mname[:3].lower()
        if k in MONTHS:
            cur_m = MONTHS[k]
            if day: parts.append((cur_m, int(day)))
    # handle "Sep 28-30 2026"
    m = re.search(r"([A-Za-z]{3,})\.?\s*(\d{1,2})\s*-\s*(\d{1,2})\b", s)
    if m and len(parts) == 1 and m.group(1)[:3].lower() in MONTHS:
        parts.append((MONTHS[m.group(1)[:3].lower()], int(m.group(3))))
    if not parts:
        return None, None
    try:
        start = dt.date(year if parts[0][0] <= parts[-1][0] else year - 1, *parts[0])
        end = dt.date(year, *parts[-1])
        return start.isoformat(), end.isoformat()
    except ValueError:
        return None, None


def cite_link(cell, soup):
    """Return the external URL of the first reference cited in a cell."""
    ref = cell.find("sup", class_="reference") if cell else None
    if ref and ref.find("a"):
        rid = ref.find("a").get("href", "").split("#")[-1]
        li = soup.find(id=rid)
        if li:
            ext = li.find("a", class_=re.compile("external"), href=True)
            if ext: return ext["href"]
    a = cell.find("a", class_=re.compile("external"), href=True) if cell else None
    return a["href"] if a else None


def section_tables(sec, title):
    for s in sec.find_all("section"):
        h = s.find(["h3", "h4"], recursive=False)
        if h and clean(h.get_text()).lower().startswith(title):
            return s.find_all("table")
    return []


def partisan_of(name):
    tags = set(re.findall(r"\(([RD])\)", name))
    return tags.pop() if len(tags) == 1 else None  # joint D/R polls (e.g. Fox's Beacon/Shaw) count as nonpartisan


def parse_polls(table, soup, nominees):
    g = grid(table)
    if len(g) < 2: return None
    hdr = [clean(c.get_text(" ")) for c in g[0]]
    if not hdr or "poll source" not in hdr[0].lower(): return None
    cand_cols = {}
    for j, h in enumerate(hdr):
        m = re.match(r"(.+?)\s*\(([A-Z])\)$", h)
        if m: cand_cols[j] = (m.group(1).strip(), m.group(2))
    if len(cand_cols) < 2: return None
    names = {n for n, _ in cand_cols.values()}
    if nominees and not names <= set(nominees): return None  # hypothetical matchup
    polls = []
    for row in g[1:]:
        txt = [clean(c.get_text(" ")) for c in row]
        if len(txt) < len(hdr) or not txt[0] or txt[0].lower().startswith(("source", "poll")): continue
        start, end = parse_date(txt[1])
        if not end: continue
        sm = re.search(r"([\d,]+)\s*\((\w+)\)", txt[2])
        p = {
            "pollster": re.sub(r"\s*/\s*", "/", re.sub(r"\s*\(([RD])\)", "", txt[0])).strip(),
            "partisan": partisan_of(txt[0]),
            "start": start, "end": end,
            "n": int(sm.group(1).replace(",", "")) if sm else None,
            "pop": sm.group(2) if sm else (re.search(r"\((\w+)\)", txt[2]) or [None, None])[1],
            "moe": pct(txt[3]) if len(txt) > 3 else None,
            "url": cite_link(row[0], soup),
            "results": {},
        }
        for j, (nm, party) in cand_cols.items():
            v = pct(txt[j])
            if v is not None: p["results"][party] = v
        for j, h in enumerate(hdr):
            if h.lower() in ("other", "undecided"):
                v = pct(txt[j])
                if v is not None: p[h.lower()] = v
        if "D" in p["results"] and "R" in p["results"]:
            p["margin"] = round(p["results"]["D"] - p["results"]["R"], 1)
            polls.append(p)
    # de-dupe identical rows (same poll, several variants) keeping first (usually LV / full field)
    seen, out = set(), []
    for p in polls:
        k = (p["pollster"], p["end"], p["pop"])
        if k in seen: continue
        seen.add(k); out.append(p)
    return {"candidates": {party: nm for nm, party in cand_cols.values()}, "polls": out}


def average(polls, days=30, today=None):
    """Simple, transparent average: newest poll per pollster in the last `days` days
    (falls back to the 8 newest polls), likely-voter versions preferred."""
    today = today or dt.date.today()
    recent = [p for p in polls if (today - dt.date.fromisoformat(p["end"])).days <= days]
    if len(recent) < 3:
        recent = sorted(polls, key=lambda p: p["end"], reverse=True)[:8]
    best = {}
    for p in sorted(recent, key=lambda p: (p["end"], p.get("pop") == "LV"), reverse=True):
        best.setdefault(p["pollster"], p)
    use = list(best.values())
    if not use: return None
    d = sum(p["results"]["D"] for p in use) / len(use)
    r = sum(p["results"]["R"] for p in use) / len(use)
    return {"D": round(d, 1), "R": round(r, 1), "margin": round(d - r, 1), "n_polls": len(use),
            "window_days": days, "from": min(p["end"] for p in use), "to": max(p["end"] for p in use)}


def trend(polls):
    """30-day trailing average at each poll end date (for the chart)."""
    pts = []
    for d in sorted({p["end"] for p in polls}):
        day = dt.date.fromisoformat(d)
        win = [p for p in polls if 0 <= (day - dt.date.fromisoformat(p["end"])).days <= 30]
        a = average(win, days=30, today=day)
        if a: pts.append({"date": d, "D": a["D"], "R": a["R"]})
    return pts


def parse_ratings(tables):
    for t in tables:
        g = grid(t)
        if g and clean(g[0][0].get_text()).lower() == "source" and len(g[0]) >= 2:
            out = []
            for row in g[1:]:
                tx = [clean(c.get_text(" ")) for c in row]
                if len(tx) >= 2 and tx[0]:
                    out.append({"source": tx[0], "rating": tx[1], "as_of": tx[2] if len(tx) > 2 else None})
            return out
    return []


def parse_finance(tables):
    for t in tables:
        g = grid(t)
        if g and "campaign finance" in clean(g[0][0].get_text()).lower():
            asof = clean(g[0][0].get_text())
            out = {}
            for row in g[2:]:
                tx = [clean(c.get_text(" ")) for c in row]
                m = re.match(r"(.+?)\s*\(([A-Z])\)", tx[0]) if tx else None
                if m and len(tx) >= 4:
                    num = lambda s: int(re.sub(r"[^\d]", "", s) or 0) if "$" in s else None
                    out[m.group(1).strip()] = {"raised": num(tx[1]), "spent": num(tx[2]), "cash": num(tx[3])}
            return {"as_of": asof, "candidates": out}
    return None


def parse_nominees(tables):
    """Candidates from the general-election results box (Party | Candidate | Votes ...)."""
    for t in reversed(tables):
        g = grid(t)
        if not g: continue
        hdr = [clean(c.get_text()).lower() for c in g[0]]
        if "candidate" in hdr and "party" in hdr:
            out = []
            for tr in t.find_all("tr")[1:]:
                tds = tr.find_all(["td", "th"])
                txt = [clean(c.get_text(" ")) for c in tds]
                party = next((PARTY[x.lower()] for x in txt if x.lower() in PARTY), None)
                if not party: continue
                cell = next((c for c in tds if c.find("a") and clean(c.get_text()).lower() not in PARTY), None)
                name_cell = tds[2] if len(tds) > 2 else cell
                name = clean(name_cell.get_text(" ")) if name_cell else None
                if not name or name.lower() in PARTY: continue
                inc = "(incumbent)" in name
                name = name.replace("(incumbent)", "").strip()
                a = name_cell.find("a", href=True)
                wiki = unquote(a["href"][2:]) if a and a["href"].startswith("./") and "redlink" not in a.get("class", []) and "new" not in a.get("class", []) else None
                out.append({"name": name, "party": party, "incumbent": inc, "wiki": wiki})
            if out: return out
    return []


def parse_general(sec, soup, label):
    tables = sec.find_all("table")
    nominees = parse_nominees(section_tables(sec, "results") or tables)
    names = [n["name"] for n in nominees]
    polls = None
    for t in tables:
        p = parse_polls(t, soup, names)
        if p and p["polls"] and set(p["candidates"]) >= {"D", "R"}:
            polls = p; break
    race = {"label": label, "nominees": nominees,
            "ratings": parse_ratings(section_tables(sec, "prediction") or tables),
            "finance": parse_finance(section_tables(sec, "fundrais") or tables)}
    if polls:
        race["polls"] = sorted(polls["polls"], key=lambda p: p["end"], reverse=True)
        race["average"] = average(race["polls"])
        race["trend"] = trend(race["polls"])
    return race


def parse_debates(container, soup):
    """Debate/forum tables: No. | Date | Host | Moderator | Link | Participants (P = present, A = absent, I/N = not invited)."""
    out = []
    for t in container.find_all("table"):
        g = grid(t)
        hdr_i = next((i for i, r in enumerate(g[:4]) if {"date", "host"} <= {clean(c.get_text()).lower() for c in r}), None)
        if hdr_i is None: continue
        hdr = [clean(c.get_text()).lower() for c in g[hdr_i]]
        # participant names are on the first row below the header that has no date
        names_row = next((r for r in g[hdr_i + 1:hdr_i + 5] if len(r) and not any(clean(c.get_text()).startswith("P Participant") for c in r)
                          and not re.search(r"20\d\d", " ".join(clean(c.get_text()) for c in r))), None)
        pcols = [j for j, h in enumerate(hdr) if h.startswith("participant")]
        names = [clean(c.get_text()) for c in names_row] if names_row else []
        for r in g[hdr_i + 1:]:
            txt = [clean(c.get_text(" ")) for c in r]
            if len(txt) < 5 or not re.search(r"20\d\d", " ".join(txt[:3])): continue
            row = dict(zip(hdr, txt))
            link_cell = r[hdr.index("link")] if "link" in hdr else None
            url = None
            if link_cell is not None:
                a = link_cell.find("a", class_=re.compile("external"), href=True)
                url = a["href"] if a else cite_link(link_cell, soup)
            present = []
            if pcols and names:
                flags = txt[pcols[0]:]
                present = [n for n, f in zip(names, flags) if f.strip().upper().startswith("P")]
            out.append({"date": row.get("date"), "host": row.get("host"), "moderator": row.get("moderator"),
                        "link_text": row.get("link"), "url": url, "participants": present})
    return out


def parse_generic(soup):
    sec = general_section(soup, "Statewide polling")
    if not sec: return None
    for t in sec.find_all("table"):
        g = grid(t)
        hdr = [clean(c.get_text(" ")).lower() for c in g[0]]
        if "republican" in hdr and "democratic" in hdr:
            ri, di = hdr.index("republican"), hdr.index("democratic")
            polls = []
            for row in g[1:]:
                txt = [clean(c.get_text(" ")) for c in row]
                if len(txt) < len(hdr): continue
                start, end = parse_date(txt[1])
                if not end or pct(txt[ri]) is None or pct(txt[di]) is None: continue
                polls.append({"pollster": re.sub(r"\s*/\s*", "/", txt[0]), "end": end, "start": start, "pop": (re.search(r"\((\w+)\)", txt[2]) or [None, None])[1],
                              "partisan": partisan_of(txt[0]), "results": {"D": pct(txt[di]), "R": pct(txt[ri])}, "url": cite_link(row[0], soup)})
            for p in polls: p["margin"] = round(p["results"]["D"] - p["results"]["R"], 1)
            return {"polls": polls, "average": average(polls)} if polls else None
    return None


def general_section(soup, top_title="General election"):
    for sec in soup.find_all("section"):
        h = sec.find("h2", recursive=False)
        if h and clean(h.get_text()).lower() == top_title.lower():
            return sec
    return None


def scrape_statewide():
    races = {}
    for key, label, page in STATEWIDE:
        try:
            soup = BeautifulSoup(fetch(WIKI + page).text, "lxml")
            sec = general_section(soup)
            if not sec:
                print("  no general section:", page); continue
            r = parse_general(sec, soup, label)
            r.update({"key": key, "type": "statewide", "source": "https://en.wikipedia.org/wiki/" + page})
            r["debates"] = [d for d in parse_debates(soup, soup) if (d["date"] or "").find("2026") >= 0 or "2026" in str(d)]
            races[key] = r
            print(f"  {label}: {[n['name'] for n in r['nominees']]} polls={len(r.get('polls', []))}")
        except Exception as e:
            print("  ERROR", page, e)
        time.sleep(3)
    return races


def scrape_house():
    races = {}
    soup = BeautifulSoup(fetch(WIKI + HOUSE_PAGE).text, "lxml")
    for sec in soup.find_all("section"):
        h = sec.find("h2", recursive=False)
        if not h: continue
        m = re.match(r"District (\d+)$", clean(h.get_text()))
        if not m: continue
        d = m.group(1)
        gen = None
        for s in sec.find_all("section"):
            hh = s.find("h3", recursive=False)
            if hh and clean(hh.get_text()).lower() == "general election":
                gen = s; break
        if not gen: continue
        r = parse_general(gen, soup, f"TX-{d}")
        r["debates"] = parse_debates(sec, soup)
        r.update({"key": f"tx{d}", "type": "house", "district": d,
                  "source": "https://en.wikipedia.org/wiki/" + HOUSE_PAGE + f"#District_{d}"})
        races[r["key"]] = r
    print(f"  House: {len(races)} districts, {sum(1 for r in races.values() if r.get('polls'))} with polls")
    g = parse_generic(soup)
    if g: races["_generic"] = g
    return races


def run():
    old = load("races.json", {}) or {}
    races = dict(old.get("races", {}))
    sw = scrape_statewide()
    time.sleep(3)
    try:
        hs = scrape_house()
    except Exception as e:
        print("  ERROR house", e); hs = {}
    # only overwrite races we successfully parsed with nominees (keeps last good data on failure)
    generic = hs.pop("_generic", None) or old.get("generic")
    for k, v in {**sw, **hs}.items():
        if v.get("nominees"):
            races[k] = v
    save("races.json", {"updated": now_iso(), "races": races, "generic": generic})
    return races


if __name__ == "__main__":
    run()
