import json, os, time, random, datetime as dt
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
LIVE = os.path.join(DATA, "live")
STATIC = os.path.join(DATA, "static")
os.makedirs(LIVE, exist_ok=True)

UA = "TexasMidtermTracker/1.0 (https://github.com/Absinthe-007/Texas-Midterm-Tracker; personal nonprofit project)"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})

ELECTION_DAY = "2026-11-03"


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def fetch(url, tries=6, base_sleep=15, **kw):
    """GET with polite retry/backoff on 429/5xx. Returns Response or raises."""
    last = None
    for i in range(tries):
        try:
            r = SESSION.get(url, timeout=60, **kw)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}"
            if r.status_code in (429, 500, 502, 503, 504):
                wait = int(r.headers.get("Retry-After", 0) or 0) or base_sleep * (i + 1) + random.randint(0, 5)
                print(f"  {last} on {url[:90]} - waiting {wait}s")
                time.sleep(min(wait, 120))
                continue
            break
        except requests.RequestException as e:
            last = str(e)
            time.sleep(base_sleep)
    raise RuntimeError(f"fetch failed {url}: {last}")


def load(name, default=None, folder=LIVE):
    p = os.path.join(folder, name)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return default


def save(name, obj, folder=LIVE):
    p = os.path.join(folder, name)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    os.replace(tmp, p)
