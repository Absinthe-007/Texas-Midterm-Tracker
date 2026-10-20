"""Entry point used by the GitHub Action every 6 hours."""
import sys, traceback
from common import save, now_iso, load
import races as races_mod, bios as bios_mod, campaign as campaign_mod, profiles as profiles_mod, forecast as forecast_mod, turnout as turnout_mod

status = {}


def step(name, fn, *a):
    print(f"== {name}")
    try:
        out = fn(*a)
        status[name] = "ok"
        return out
    except Exception as e:
        traceback.print_exc()
        status[name] = f"error: {e}"
        return None


races = step("races", races_mod.run) or (load("races.json", {}) or {}).get("races", {})
step("bios", bios_mod.run, races)
step("profiles", profiles_mod.run, races)
step("campaign", campaign_mod.run, races)
step("turnout", turnout_mod.run)
step("forecast", forecast_mod.run, races, (load("races.json", {}) or {}).get("generic"))
save("meta.json", {"updated": now_iso(), "status": status,
                   "election_day": "2026-11-03", "early_voting": ["2026-10-19", "2026-10-30"],
                   "mail_ballot_deadline": "2026-10-23"})
print(status)
if all(v != "ok" for v in status.values()):
    sys.exit(1)
