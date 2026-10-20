"""One-time builder: early-voting turnout by county, day by day, for the 2022 and 2024
November general elections (Texas Secretary of State early voting rosters).

Output: data/static/ev_history.json
  {"2022": {"label": ..., "days": ["2022-10-24", ...], "counties": {"HARRIS": {"reg": n, "cum": [day1, day2, ...]}}}, ...}
"cum" = cumulative in-person + mail early votes at the end of each in-person early voting day.
"""
import json, os, re, time
import requests
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "static", "ev_history.json")
BASE = "https://earlyvoting.texas-election.com/Elections/"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/129.0 Safari/537.36 TexasMidtermTracker/1.0"}
ELECTIONS = {
    "2022": (47009, "2022 midterm", ["2022-10-24", "2022-10-25", "2022-10-26", "2022-10-27", "2022-10-28", "2022-10-29",
                                     "2022-10-30", "2022-10-31", "2022-11-01", "2022-11-02", "2022-11-03", "2022-11-04"]),
    "2024": (49664, "2024 presidential", ["2024-10-21", "2024-10-22", "2024-10-23", "2024-10-24", "2024-10-25", "2024-10-26",
                                          "2024-10-27", "2024-10-28", "2024-10-29", "2024-10-30", "2024-10-31", "2024-11-01"]),
}
num = lambda s: int(re.sub(r"[^\d]", "", s) or 0)


def day_table(sess, eid, day):
    r = sess.post(BASE + "getEVDetails.do", headers=UA, timeout=90, data={
        "idElection": eid, "selectedDate": f"{day} 00:00:00.0", "electionDate": "", "idGroupedElection": "",
        "webPageSyncDate": "true", "downloadElectionFileCSVFlag": "false"})
    r.raise_for_status()
    t = BeautifulSoup(r.text, "lxml").find("table")
    rows = {}
    for tr in t.find_all("tr")[1:]:
        c = [x.get_text(" ", strip=True) for x in tr.find_all(["td", "th"])]
        if len(c) < 7 or not c[0] or c[0].upper().startswith("TOTAL"): continue
        rows[c[0].upper()] = {"reg": num(c[1]), "cum": num(c[6])}  # cumulative in-person + mail
    return rows


def main():
    out = {}
    sess = requests.Session()
    for year, (eid, label, days) in ELECTIONS.items():
        counties = {}
        for i, d in enumerate(days):
            rows = day_table(sess, eid, d)
            for name, v in rows.items():
                c = counties.setdefault(name, {"reg": v["reg"], "cum": [None] * len(days)})
                c["cum"][i] = v["cum"]
                c["reg"] = v["reg"] or c["reg"]
            print(year, d, len(rows), sum(v["cum"] for v in rows.values()))
            time.sleep(1.5)
        out[year] = {"label": label, "days": days, "counties": counties}
    json.dump(out, open(OUT, "w"), separators=(",", ":"))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
