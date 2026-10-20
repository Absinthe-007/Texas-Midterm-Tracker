"""2026 early-voting turnout by county, day by day (Texas Secretary of State).

Source: the SOS early voting roster app (goelect.txelections.civixapps.com), which serves
each day's county table as base64-encoded JSON. Saves data/live/turnout.json in the same
shape as data/static/ev_history.json so the site can compare day N of 2026 with day N of
2022 (last midterm) and 2024 (last presidential).
"""
import base64, json, time, datetime as dt
from zoneinfo import ZoneInfo
from common import SESSION, load, save, now_iso

API = "https://goelect.txelections.civixapps.com/api-ivis-system/api/v1/getFile"
HDR = {"User-Agent": "Mozilla/5.0 (compatible; TexasMidtermTracker/1.0; +https://github.com/Absinthe-007/Texas-Midterm-Tracker)"}
ELECTION_ID = 53815            # 2026 November General Election
FIRST_IN_PERSON_DAY = "2026-10-19"


def _get(params):
    r = SESSION.get(API, params=params, headers=HDR, timeout=60)
    r.raise_for_status()
    return json.loads(base64.b64decode(r.json()["upload"]))


def run():
    old = load("turnout.json", {}) or {}
    elections = _get({"type": "EVR_ELECTION"})["elections"]
    e = next(x for x in elections if x["id"] == ELECTION_ID)
    today = dt.datetime.now(ZoneInfo("America/Chicago")).date().isoformat()  # Texas time, not the runner's UTC
    days = [dt.datetime.strptime(d["date"], "%m/%d/%Y").date().isoformat() for d in e["early_voting_dates"]]
    days = [d for d in days if d >= FIRST_IN_PERSON_DAY]
    counties = {k: dict(v) for k, v in (old.get("counties") or {}).items()}
    for c in counties.values():
        c["cum"] = (c.get("cum") or []) + [None] * (len(days) - len(c.get("cum") or []))
    fetched = []
    for i, d in enumerate(days):
        if d > today: break
        # past days only change rarely; refresh today and the two days before it every run
        if d < (dt.date.fromisoformat(today) - dt.timedelta(days=2)).isoformat() and any(c["cum"][i] for c in counties.values()):
            continue
        y, m, dd = d.split("-")
        t = _get({"type": "EVR_EARLYVOTING", "electionId": ELECTION_ID, "electionDate": f"{m}/{dd}/{y}"})
        for row in t.get("turnout_by_county", []):
            name = row["name"].upper()
            c = counties.setdefault(name, {"reg": 0, "cum": [None] * len(days)})
            c["reg"] = row.get("registered_voters") or c["reg"]
            total = (row.get("total_in_person_votes_for_election") or 0) + (row.get("total_mail_votes_for_election") or 0)
            c["cum"][i] = total
            c.setdefault("in_person_today", {})[d] = row.get("in_person_votes_on_date") or 0
        fetched.append(d)
        time.sleep(0.5)
    # a day is "complete" once the next day's numbers exist (counties post overnight)
    reported = [i for i, d in enumerate(days) if any((c["cum"][i] or 0) > 0 for c in counties.values())]
    out = {"updated": now_iso(), "label": "2026 midterm", "days": days, "counties": counties,
           "latest_day": (max(reported) + 1) if reported else 0,
           "partial": bool(reported) and days[max(reported)] == today,  # today's polls still open
           "source": "https://goelect.txelections.civixapps.com/ivis-evr-ui/evr"}
    save("turnout.json", out)
    tot = sum((c["cum"][out["latest_day"] - 1] or 0) for c in counties.values()) if out["latest_day"] else 0
    print(f"  Turnout: fetched {fetched}, day {out['latest_day']} statewide early votes {tot:,}")
    return out


if __name__ == "__main__":
    run()
