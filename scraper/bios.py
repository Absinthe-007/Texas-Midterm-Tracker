"""Candidate bios + photos from Wikipedia page summaries (cached, refreshed every few days)."""
import re, time, datetime as dt
from urllib.parse import quote
from bs4 import BeautifulSoup
from common import fetch, load, save, now_iso

API = "https://en.wikipedia.org/api/rest_v1/page/summary/"
HTML = "https://en.wikipedia.org/api/rest_v1/page/html/"
# Section titles that hold controversies, investigations or legal trouble. Same rule for every candidate.
SCRUTINY = re.compile(r"controvers|scandal|investigat|indict|impeach|allegation|ethics? (complaint|investigation|violation|probe)|criminal|legal (issue|trouble|history)|fraud|misconduct|arrest|censure|complaint|conflict of interest|whistleblower|bribery|plagiar", re.I)


def scrutiny_sections(title):
    soup = BeautifulSoup(fetch(HTML + quote(title, safe=""), tries=3, base_sleep=10).text, "lxml")
    out, seen = [], set()
    for sec in soup.find_all("section"):
        h = sec.find(["h2", "h3", "h4"], recursive=False)
        if not h: continue
        name = h.get_text(" ", strip=True)
        if not SCRUTINY.search(name): continue
        p = next((p for p in sec.find_all("p") if len(p.get_text(strip=True)) > 60), None)
        txt = re.sub(r"\[\s*[^\]]{1,8}\s*\]", "", p.get_text(" ", strip=True)) if p else ""
        txt = re.sub(r"\s+", " ", txt).strip()
        m = re.match(r"(.{40,320}?[.!?])(\s|$)", txt)
        summ = m.group(1) if m else txt[:300]
        if summ in seen: summ = ""
        seen.add(summ)
        out.append({"title": name, "summary": summ,
                    "url": "https://en.wikipedia.org/wiki/" + quote(title) + "#" + quote(h.get("id") or name.replace(" ", "_"))})
    return out[:6]


def run(races, max_fetch=40, max_age_days=3):
    cache = (load("bios.json", {}) or {}).get("bios", {})
    todo = []
    for r in races.values():
        for n in r.get("nominees", []):
            w = n.get("wiki")
            if not w: continue
            c = cache.get(w)
            if not c or (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(c["fetched"])).days >= max_age_days:
                todo.append(w)
    # statewide first (more visible), then the rest
    todo = sorted(set(todo), key=lambda w: 0 if any(w == n.get("wiki") for r in races.values() if r["type"] == "statewide" for n in r["nominees"]) else 1)
    done = 0
    for w in todo[:max_fetch]:
        try:
            d = fetch(API + quote(w, safe=""), tries=3, base_sleep=10).json()
            cache[w] = {"title": d.get("title"), "description": d.get("description"), "extract": d.get("extract"),
                        "photo": (d.get("thumbnail") or {}).get("source"),
                        "url": (d.get("content_urls") or {}).get("desktop", {}).get("page"), "fetched": now_iso()}
            time.sleep(1.5)
            try:
                cache[w]["scrutiny"] = scrutiny_sections(w)
            except Exception as e:
                print("  scrutiny error", w, e)
            done += 1
        except Exception as e:
            print("  bio error", w, e)
        time.sleep(1.5)
    print(f"  Bios: fetched {done}, cached {len(cache)}")
    save("bios.json", {"updated": now_iso(), "bios": cache})
    return cache
