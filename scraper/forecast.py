"""TX '26 forecast: a small, transparent model. Not a crystal ball.

Each race's projected margin (Dem minus GOP, in points) blends:
  1. Polls        - the race's polling average (more polls -> more weight)
  2. Fundamentals - the 2024 result in that place, shifted by today's statewide
                    environment (generic congressional ballot), plus an incumbency bump
  3. Experts      - the consensus rating from Cook, Sabato, Inside Elections, etc.
Uncertainty is a normal distribution sized from historical polling misses. 20,000
simulations share a common statewide error, so if polls miss in one race they tend
to miss the same way everywhere (that's what makes the seat-count range realistic).
"""
import re, math, json, datetime as dt
import numpy as np
from common import load, save, now_iso, STATIC

N_SIMS = 20000
SHARED_SD = 3.5        # statewide polling error shared by every race
STATEWIDE_SD = 4.5     # total error for a well-polled statewide race ~3 weeks out
DISTRICT_SD = 6.5      # total error for a House district
INCUMBENCY = 2.5
RATING_MARGIN = {0: 0, 1: 2, 2: 5, 3: 10, 4: 20}  # tilt / lean / likely / safe -> rough margin
RATING_WEIGHT = 0.3


def rating_score(r):
    r = (r or "").lower()
    s = 0 if "toss" in r else 1 if "tilt" in r else 2 if "lean" in r else 3 if "likely" in r else 4 if ("safe" in r or "solid" in r) else None
    if s is None: return None
    return 0 if s == 0 else (s if re.search(r"\bd\b|dem", r) else -s)


def consensus(ratings):
    s = [rating_score(x["rating"]) for x in ratings or []]
    s = [x for x in s if x is not None]
    if not s: return None
    m = sum(s) / len(s)
    return math.copysign(RATING_MARGIN[min(4, round(abs(m)))], m) if round(abs(m)) else 0.0


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def run(races, generic):
    dres = json.load(open(f"{STATIC}/district_results.json"))
    st = dres["STATE"]
    days = max(0, (dt.date(2026, 11, 3) - dt.date.today()).days)
    time_sd = 0.10 * days  # extra uncertainty the further out we are
    env = generic["average"]["margin"] if generic and generic.get("average") else None
    # statewide shift vs 2024 Senate result (Cruz +8.5); damped because districts don't all move together
    swing = 0.8 * (env - st["sen24"]["margin"]) if env is not None else 0.0
    out = {}
    for k, r in races.items():
        noms = {n["party"]: n for n in r.get("nominees", []) if n["party"] in ("D", "R")}
        if r.get("type") not in ("statewide", "house"): continue
        if len(noms) < 2:
            p = 1.0 if "D" in noms else 0.0
            out[k] = {"p_dem": p, "mean": None, "uncontested": True}
            continue
        avg, npolls = (r.get("average") or {}).get("margin"), (r.get("average") or {}).get("n_polls", 0)
        inc = next((n["party"] for n in noms.values() if n.get("incumbent")), None)
        if r["type"] == "statewide":
            fund = 0.5 * (env if env is not None else st["sen24"]["margin"]) + 0.5 * st["sen24"]["margin"]
            if inc: fund += INCUMBENCY if inc == "D" else -INCUMBENCY
            w_poll = min(0.85, npolls / (npolls + 2)) if avg is not None else 0
            base_sd = STATEWIDE_SD + (1.5 if npolls < 5 else 0)
        else:
            d = dres.get(r["district"], {})
            base = d.get("sen24", d.get("pres24", {})).get("margin")
            fund = (base or 0) + swing
            if inc: fund += INCUMBENCY if inc == "D" else -INCUMBENCY
            w_poll = min(0.6, npolls / (npolls + 3)) if avg is not None else 0
            base_sd = DISTRICT_SD
        rating = consensus(r.get("ratings"))
        w_rate = RATING_WEIGHT if rating is not None else 0
        w_fund = max(0.0, 1 - w_poll - w_rate)
        mean = (w_poll * (avg or 0) + w_fund * fund + w_rate * (rating or 0)) / (w_poll + w_fund + w_rate)
        sd = math.sqrt(base_sd ** 2 + time_sd ** 2)
        out[k] = {"mean": round(mean, 1), "sd": round(sd, 1), "p_dem": round(ncdf(mean / sd), 3),
                  "lo": round(mean - 1.28 * sd, 1), "hi": round(mean + 1.28 * sd, 1),
                  "inputs": {"polls": avg, "n_polls": npolls, "fundamentals": round(fund, 1), "experts": rating,
                             "weights": {"polls": round(w_poll, 2), "fundamentals": round(w_fund, 2), "experts": round(w_rate, 2)}}}

    # correlated simulation for the House delegation
    rng = np.random.default_rng(2026)
    shared = rng.normal(0, SHARED_SD, N_SIMS)
    house = [k for k in out if races[k]["type"] == "house"]
    dem_seats = np.zeros(N_SIMS, dtype=int)
    for k in house:
        f = out[k]
        if f.get("uncontested"):
            dem_seats += int(f["p_dem"] == 1.0); continue
        own = math.sqrt(max(0.5, f["sd"] ** 2 - SHARED_SD ** 2))
        sims = f["mean"] + shared + rng.normal(0, own, N_SIMS)
        f["p_dem_sim"] = round(float((sims > 0).mean()), 3)
        dem_seats += (sims > 0).astype(int)
    hist = np.bincount(dem_seats, minlength=len(house) + 1).tolist()
    base_d = sum(1 for k in house if dres.get(races[k]["district"], {}).get("pres24", {}).get("margin", -1) > 0)
    for k in out:  # statewide sims with the same shared error, for consistency
        f = out[k]
        if races[k]["type"] == "statewide" and not f.get("uncontested"):
            own = math.sqrt(max(0.5, f["sd"] ** 2 - SHARED_SD ** 2))
            f["p_dem_sim"] = round(float(((f["mean"] + shared + rng.normal(0, own, N_SIMS)) > 0).mean()), 3)
    res = {"updated": now_iso(), "days_to_election": days, "environment": {"generic_ballot": env, "district_swing": round(swing, 1)},
           "races": out,
           "house": {"seats": len(house), "dem_mean": round(float(dem_seats.mean()), 1),
                     "dem_median": int(np.median(dem_seats)), "dem_lo80": int(np.percentile(dem_seats, 10)),
                     "dem_hi80": int(np.percentile(dem_seats, 90)), "hist": hist, "harris_won_districts": base_d}}
    save("forecast.json", res)
    sw = {k: (v["mean"], v["p_dem"]) for k, v in out.items() if races[k]["type"] == "statewide"}
    print(f"  Forecast: House D seats {res['house']['dem_median']} ({res['house']['dem_lo80']}-{res['house']['dem_hi80']}); statewide {sw}")
    return res


if __name__ == "__main__":
    d = load("races.json")
    run(d["races"], d.get("generic"))
