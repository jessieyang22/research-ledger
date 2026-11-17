"""FRED / ALFRED loader with point-in-time ("as of") reads.

Public data. Key: FRED_API_KEY in the environment or in <repo>/.env (never commit it).
as_of_series(series_id, cutoff) returns the observations exactly as FRED published them on the cutoff date,
so later revisions cannot leak into a backtest (ALFRED real-time period = the cutoff).
Results are cached under live/data/fred/ (git-ignored).
"""
import json, os, time, warnings
from datetime import date
from pathlib import Path

import requests

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "live" / "data" / "fred"
BASE = "https://api.stlouisfed.org/fred"


def _key():
    k = os.environ.get("FRED_API_KEY")
    if k:
        return k
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("FRED_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError("FRED_API_KEY not found in environment or .env")


def _get(path, **params):
    p = dict(params, api_key=_key(), file_type="json")
    time.sleep(0.1)
    r = requests.get("%s/%s" % (BASE, path), params=p, timeout=40)
    if r.status_code != 200:
        raise RuntimeError("FRED %s failed (%s): %s" % (path, r.status_code, r.text[:200]))
    return r.json()


def _cached(name, fn):
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / name
    if p.exists():
        return json.loads(p.read_text())
    out = fn()
    p.write_text(json.dumps(out))
    return out


def as_of_series(series_id, cutoff, start=None):
    """Observations as published on `cutoff` (a date or YYYY-MM-DD). Missing values are dropped, never zero-filled."""
    c = cutoff.isoformat() if isinstance(cutoff, date) else str(cutoff)
    if c > date.today().isoformat():
        raise ValueError("cutoff is in the future")
    def fetch():
        kw = dict(series_id=series_id, realtime_start=c, realtime_end=c)
        if start:
            kw["observation_start"] = start
        return _get("series/observations", **kw)["observations"]
    obs = _cached("%s_asof_%s_%s.json" % (series_id, c, start or "all"), fetch)
    return [(o["date"], float(o["value"])) for o in obs if o["value"] not in (".", "")]


def vintage_dates(series_id):
    """Dates on which the series' history was revised or extended (ALFRED vintages)."""
    return _cached("%s_vintages.json" % series_id,
                   lambda: _get("series/vintagedates", series_id=series_id, limit=10000)["vintage_dates"])


def value_as_of(series_id, obs_date, cutoff):
    """The value for observation `obs_date` as known on `cutoff`, or None if it was not yet published then."""
    for d, v in as_of_series(series_id, cutoff, start=obs_date):
        if d == obs_date:
            return v
    return None


def revision_table(series_id, obs_date, cutoffs):
    """How one observation's value changed across several cutoffs: [(cutoff, value or None), ...]."""
    return [(c, value_as_of(series_id, obs_date, c)) for c in cutoffs]


if __name__ == "__main__":
    import sys
    sid, obs = sys.argv[1], sys.argv[2]
    cuts = sys.argv[3:] or [date.today().isoformat()]
    for c, v in revision_table(sid, obs, cuts):
        print(c, v)
