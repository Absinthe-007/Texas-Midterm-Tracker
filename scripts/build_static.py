"""One-time builder for static reference data (maps + past results).

Run locally or via the workflow's manual "rebuild_static" input. Outputs go to data/static/.

Sources (all official / widely used):
  * Congressional districts PLANC2333 (2025 map used in 2026) + district-level
    past election results (Red-206 reports) - Texas Legislative Council,
    https://data.capitol.texas.gov/dataset/planc2333
  * County presidential results 2016/2020/2024 - tonmcg/US_County_Level_Election_Results_08-24
    (compiled from official county canvass / AP data)
  * County boundaries - US Census (via plotly/datasets geojson-counties-fips)
  * Places gazetteer (city -> lat/lng for geocoding news events) - US Census 2025 Gazetteer
"""
import io, json, os, re, sys, zipfile, tempfile
import requests
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "static")
os.makedirs(OUT, exist_ok=True)
UA = {"User-Agent": "TexasMidtermTracker/1.0 (https://github.com/Absinthe-007/Texas-Midterm-Tracker)"}

PLAN_ZIP = ("https://data.capitol.texas.gov/dataset/748c952b-e926-4f44-8d01-a738884b3ec8/resource/"
            "f34a2ca9-e4de-4bb3-a2f2-884076d5a166/download/planc2333_all_files_20260911.zip")
COUNTY_GEO = "https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json"
COUNTY_RES = "https://raw.githubusercontent.com/tonmcg/US_County_Level_Election_Results_08-24/master/{y}_US_County_Level_Presidential_Results.csv"
GAZ = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer/2025_gaz_place_48.txt"


def get(url):
    r = requests.get(url, headers=UA, timeout=180)
    r.raise_for_status()
    return r.content


def r206_results(xls_bytes, races):
    """Parse a TLC Red-206 'Election Analysis' xls (Sheet2) -> {district: {race: {cand: votes}}}."""
    x = pd.read_excel(io.BytesIO(xls_bytes), header=None, sheet_name=None)
    out = {}
    for name, df in x.items():
        hdr_row = None
        for i in range(min(20, len(df))):
            vals = [str(v) for v in df.iloc[i].tolist()]
            if any("District" in v for v in vals) and any(r in " ".join(vals) for r in ("PRESIDENT", "U.S. SEN", "GOVERNOR")):
                hdr_row = i
                break
        if hdr_row is None:
            continue
        cand_row = df.iloc[hdr_row + 1].tolist()
        race_row = df.iloc[hdr_row].tolist()
        # map columns -> (race, candidate)
        cols = {}
        cur_race = None
        for j, c in enumerate(cand_row):
            rr = race_row[j] if j < len(race_row) else None
            if isinstance(rr, str) and rr.strip() and "District" not in rr:
                cur_race = rr.strip()
            if isinstance(c, str) and re.search(r"-[A-Z]\s*$", c.strip()):
                cols[j] = (cur_race, c.strip())
        # race header cells may be positioned left of their first candidate; realign by scanning
        race_cols = [(j, str(v).strip()) for j, v in enumerate(race_row) if isinstance(v, str) and v.strip() and "District" not in v]
        def race_for(j):
            best = None
            for rj, rn in race_cols:
                if rj <= j + 1:
                    best = rn
            return best
        for i in range(hdr_row + 2, len(df)):
            row = df.iloc[i].tolist()
            dist = None
            for v in row[:3]:
                if isinstance(v, (int, float)) and not pd.isna(v):
                    dist = str(int(v)); break
                if isinstance(v, str) and v.strip() in ("STATE",):
                    dist = "STATE"; break
                if isinstance(v, str) and v.strip().isdigit():
                    dist = v.strip(); break
            if dist is None:
                continue
            d = out.setdefault(dist, {})
            for j, (_, cand) in cols.items():
                rn = race_for(j)
                if rn not in races:
                    continue
                v = row[j] if j < len(row) else None
                if isinstance(v, (int, float)) and not pd.isna(v):
                    d.setdefault(races[rn], {})[cand] = int(v)
    return out


def dem_margin(cands):
    d = sum(v for k, v in cands.items() if k.endswith("-D"))
    r = sum(v for k, v in cands.items() if k.endswith("-R"))
    tot = sum(cands.values())
    if not tot:
        return None
    return round((d - r) / tot * 100, 2)


def build_districts():
    print("Downloading TLC PLANC2333 package...")
    z = zipfile.ZipFile(io.BytesIO(get(PLAN_ZIP)))
    elections = {
        "24G": {"PRESIDENT": "pres24", "U.S. SEN": "sen24"},
        "22G": {"GOVERNOR": "gov22", "LT. GOVERNOR": "ltgov22", "ATTORNEY GEN": "ag22"},
        "20G": {"PRESIDENT": "pres20", "U.S. SEN": "sen20"},
        "18G": {"U.S. SEN": "sen18", "GOVERNOR": "gov18"},
    }
    results = {}
    for e, races in elections.items():
        fn = f"PLANC2333_r206_Election{e}.xls"
        res = r206_results(z.read(fn), races)
        for dist, rr in res.items():
            for race, cands in rr.items():
                results.setdefault(dist, {})[race] = {"margin": dem_margin(cands), "votes": cands}
    json.dump(results, open(os.path.join(OUT, "district_results.json"), "w"), separators=(",", ":"))
    print("districts:", len(results), "sample TX-28:", {k: v["margin"] for k, v in results.get("28", {}).items()})

    # shapes
    import geopandas as gpd
    with tempfile.TemporaryDirectory() as td:
        inner = zipfile.ZipFile(io.BytesIO(z.read("PLANC2333.zip")))
        inner.extractall(td)
        shp = [os.path.join(dp, f) for dp, _, fs in os.walk(td) for f in fs if f.endswith(".shp")][0]
        g = gpd.read_file(shp).to_crs(4326)
        col = [c for c in g.columns if c.lower() in ("district", "dist", "district_n")][0]
        g["district"] = g[col].astype(int).astype(str)
        g["geometry"] = g.geometry.simplify(0.004, preserve_topology=True)
        g[["district", "geometry"]].to_file(os.path.join(OUT, "tx_cd2025.geojson"), driver="GeoJSON", COORDINATE_PRECISION=4)
    print("wrote district shapes")


def build_counties():
    gj = json.loads(get(COUNTY_GEO))
    feats = [f for f in gj["features"] if f["id"].startswith("48")]
    for f in feats:
        f["properties"] = {"fips": f["id"], "name": f["properties"].get("NAME")}
        def rnd(c):
            return [rnd(x) for x in c] if isinstance(c[0], list) else [round(c[0], 4), round(c[1], 4)]
        f["geometry"]["coordinates"] = rnd(f["geometry"]["coordinates"])
    json.dump({"type": "FeatureCollection", "features": feats}, open(os.path.join(OUT, "tx_counties.geojson"), "w"), separators=(",", ":"))
    print("counties:", len(feats))

    res = {}
    for y in (2016, 2020, 2024):
        df = pd.read_csv(io.BytesIO(get(COUNTY_RES.format(y=y))), dtype={"county_fips": str, "combined_fips": str})
        if "state_name" not in df.columns:  # 2016 file uses a different layout
            df = df[df["state_abbr"] == "TX"].rename(columns={"combined_fips": "county_fips"})
        else:
            df = df[df["state_name"] == "Texas"]
        for _, r in df.iterrows():
            fips = str(r["county_fips"]).zfill(5)
            tot = r["total_votes"]
            res.setdefault(fips, {"name": r["county_name"].replace(" County", "")})[f"pres{str(y)[2:]}"] = {
                "margin": round((r["votes_dem"] - r["votes_gop"]) / tot * 100, 2),
                "dem": int(r["votes_dem"]), "rep": int(r["votes_gop"]), "total": int(tot)}
    json.dump(res, open(os.path.join(OUT, "county_results.json"), "w"), separators=(",", ":"))
    print("county results:", len(res))


def build_places():
    txt = get(GAZ).decode("utf-8", "ignore")
    df = pd.read_csv(io.StringIO(txt), sep="|")
    df.columns = [c.strip() for c in df.columns]
    places = {}
    for _, r in df.iterrows():
        nm = re.sub(r"\s+(city|town|village|CDP)$", "", str(r["NAME"]).strip())
        if nm not in places or r["ALAND"] > places[nm][2]:
            places[nm] = [round(float(r["INTPTLAT"]), 4), round(float(str(r["INTPTLONG"]).strip()), 4), int(r["ALAND"])]
    places = {k: v[:2] for k, v in places.items()}
    json.dump(places, open(os.path.join(OUT, "tx_places.json"), "w"), separators=(",", ":"))
    print("places:", len(places))


if __name__ == "__main__":
    which = sys.argv[1:] or ["districts", "counties", "places"]
    if "counties" in which: build_counties()
    if "places" in which: build_places()
    if "districts" in which: build_districts()
