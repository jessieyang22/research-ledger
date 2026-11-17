"""Earnings-night report: compare a real release with expectations frozen BEFORE it was published.

  python live/earnings_night/earnings_night.py freeze                 # once, before the print
  python live/earnings_night/earnings_night.py extract INVH          # fetch the newest release, propose values
  python live/earnings_night/earnings_night.py report INVH [--confirm "Your Name"]

Rules taken from the method: the prior is frozen and hashed; the report refuses to run if the prior changed; extracted
numbers are candidates until a person confirms them; every report ends REVIEW_REQUIRED and contains deltas, not a
rewrite of the prior view. No trading output.
"""
import argparse, hashlib, json, re, sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from as_of.core import EstimateRecord  # noqa: E402
from as_of.estimate_ledger import EstimateLedger  # noqa: E402
from as_of.reported_vs_expected_bridge import build_bridge  # noqa: E402

EXP = HERE / "expectations.json"
FROZEN = HERE / "FROZEN.json"
OUT = HERE / "output"


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def freeze():
    if FROZEN.exists():
        print("already frozen:", FROZEN.read_text())
        return 1
    rec = {"frozen_at": datetime.now(timezone.utc).isoformat(), "file": EXP.name, "sha256": _sha(EXP)}
    FROZEN.write_text(json.dumps(rec, indent=2))
    print("frozen", rec)
    return 0


def _verify_frozen():
    if not FROZEN.exists():
        raise SystemExit("not frozen: run `freeze` before the print")
    f = json.loads(FROZEN.read_text())
    if _sha(EXP) != f["sha256"]:
        raise SystemExit("expectations.json changed after freeze (hash mismatch). Restore it or create a new dated state.")
    return f


# ---- extraction (candidates only) -------------------------------------------------
def _rng_pairs(text):
    return [(float(a), float(b)) for a, b in re.findall(r"(-?\d+\.?\d*)\s*%\s*[-–]\s*(-?\d+\.?\d*)\s*%", text)]


def extract_candidates(text, ticker):
    c, snip = {}, {}
    def put(k, v, m):
        c[k] = v
        snip[k] = text[max(0, m.start() - 40): m.end() + 60]
    m = re.search(r"Core FFO per share(?: for Q\d \d{4})? (?:increased|decreased) [\d.]+% to \$(\d\.\d{2})", text) \
        or re.search(r"Core FFO[^$]{0,200}?\$(\d\.\d{2}) per FFO share", text)
    if m:
        put("core_ffo_q", float(m.group(1)), m)
    # full-year Core FFO guidance
    m = re.search(r"Core FFO per share \S* diluted \$(\d\.\d{2}) - \$(\d\.\d{2}) \$(\d\.\d{2}) \$(\d\.\d{2})", text)  # INVH: range, new mid, prior mid
    if m:
        put("core_ffo_fy26_low", float(m.group(1)), m); c["core_ffo_fy26_high"] = float(m.group(2)); c["core_ffo_fy26_mid"] = float(m.group(3))
    m = re.search(r"Core FFO attributable to common share and unit holders \$(\d\.\d{2}) - \$(\d\.\d{2}) \$(\d\.\d{2}) - \$(\d\.\d{2})", text)  # AMH: previous, current
    if m and "core_ffo_fy26_low" not in c:
        put("core_ffo_fy26_low", float(m.group(3)), m); c["core_ffo_fy26_high"] = float(m.group(4))
        c["core_ffo_fy26_mid"] = round((c["core_ffo_fy26_low"] + c["core_ffo_fy26_high"]) / 2, 3)
    # same-store guidance ranges. AMH tables list previous then current; INVH lists current first.
    for label, key, who in (("Same[- ]Home Core revenues growth", "ss_rev_fy26", "AMH"), ("Core NOI growth", "ss_noi_fy26", "AMH"),
                            ("Same Store Core Revenues growth", "ss_rev_fy26", "INVH"), ("Same Store NOI growth", "ss_noi_fy26", "INVH")):
        if ticker != who:
            continue
        for m in re.finditer(label, text):
            pairs = _rng_pairs(text[m.end(): m.end() + 70])
            if pairs:
                lo, hi = pairs[1] if (who == "AMH" and len(pairs) > 1) else pairs[0]
                put(key + "_low", lo, m); c[key + "_high"] = hi; c[key + "_mid"] = round((lo + hi) / 2, 3)
                break
    return c, snip


def extract(ticker):
    import fetch_release
    p = fetch_release.fetch_latest(ticker, 0)
    raw = Path(p).read_text()
    text = raw.split("\n\n", 1)[1]
    c, snip = extract_candidates(text, ticker)
    meta = dict(re.findall(r"^(SOURCE_URL|FILED): (.*)$", raw, re.M))
    out = {"ticker": ticker, "source_url": meta.get("SOURCE_URL"), "filed": meta.get("FILED"), "candidates": c, "snippets": snip,
           "confirmed_by": None, "status": "UNCONFIRMED_EXTRACTION"}
    dest = HERE / "data" / ("reported_%s.json" % ticker)
    dest.write_text(json.dumps(out, indent=2))
    print(json.dumps(out["candidates"], indent=2)); print("saved", dest, "| verify against the release text, then run report --confirm NAME")
    return 0


# ---- report ----------------------------------------------------------------------
def build_report(ticker, reported, reported_at, frozen, confirmed_by=None):
    exp = json.loads(EXP.read_text())
    knowledge_at = datetime.fromisoformat(frozen["frozen_at"])
    led = EstimateLedger()
    for i, it in enumerate(x for x in exp["items"] if x["ticker"] == ticker):
        led.append(EstimateRecord("%s-%s-%d" % (ticker, it["metric"], i), ticker, it["metric"], it["period"], it["analyst_id"],
                                  float(it["value"]), knowledge_at, it["source"]))
    mapping = {  # expectation metric -> reported candidate key
        "core_ffo_fy26_guidance_mid": "core_ffo_fy26_mid", "core_ffo_fy26_consensus": "core_ffo_fy26_mid",
        "ss_noi_fy26_guidance_mid": "ss_noi_fy26_mid", "ss_rev_fy26_guidance_mid": "ss_rev_fy26_mid"}
    rows, notes = [], []
    for it in (x for x in exp["items"] if x["ticker"] == ticker):
        key = mapping[it["metric"]]
        if key not in reported:
            rows.append((it["metric"], it["value"], None, None, None, "NOT FOUND IN RELEASE")); continue
        b = build_bridge(led, ticker, it["metric"], it["period"], reported[key], reported_at)
        rows.append((it["metric"], b["expected"], b["reported"], b["surprise_abs"], b["surprise_pct"],
                     "up" if (b["surprise_abs"] or 0) > 1e-9 else "down" if (b["surprise_abs"] or 0) < -1e-9 else "unchanged"))
    if "core_ffo_q" in reported:
        notes.append("Q3 Core FFO per share reported: %.2f. No quarterly expectation on file, so no surprise is computed." % reported["core_ffo_q"])
    status = "REVIEW_REQUIRED" + ("" if confirmed_by else " (values UNCONFIRMED: not yet checked by a person)")
    lines = ["# Earnings-night report: %s" % ticker, "", "Status: **%s**" % status,
             "Prior frozen at: %s (sha256 %s...)" % (frozen["frozen_at"], frozen["sha256"][:12]),
             "Reported at (UTC): %s" % reported_at.isoformat(), "Confirmed by: %s" % (confirmed_by or "nobody yet"), "",
             "| Metric | Expected (prior) | Reported | Delta | Delta % | Direction |", "|---|---|---|---|---|---|"]
    for m, e, r, d, p, dirn in rows:
        f = lambda v: "n/a" if v is None else ("%.4g" % v)
        lines.append("| %s | %s | %s | %s | %s | %s |" % (m, f(e), f(r), f(d), "n/a" if p is None else "%.2f%%" % (100 * p), dirn))
    lines += [""] + ["- " + n for n in notes] + ["", "Gaps carried from the prior: " + "; ".join(exp["gaps"]), "",
              "This report states what changed against the frozen prior. It does not say what it means for the stock or any trade."]
    return "\n".join(lines)


def report(ticker, confirm=None):
    frozen = _verify_frozen()
    p = HERE / "data" / ("reported_%s.json" % ticker)
    if not p.exists():
        raise SystemExit("run `extract %s` first" % ticker)
    j = json.loads(p.read_text())
    if confirm:
        j["confirmed_by"], j["status"] = confirm, "CONFIRMED"
        p.write_text(json.dumps(j, indent=2))
    reported_at = datetime.fromisoformat(j["filed"] + "T21:00:00+00:00") if j.get("filed") else datetime.now(timezone.utc)
    txt = build_report(ticker, j["candidates"], reported_at, frozen, j.get("confirmed_by"))
    OUT.mkdir(exist_ok=True)
    dest = OUT / ("%s_%s.md" % (ticker, j["filed"]))
    dest.write_text(txt)
    print(txt); print("\nsaved", dest)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["freeze", "extract", "report"])
    ap.add_argument("ticker", nargs="?")
    ap.add_argument("--confirm")
    a = ap.parse_args()
    sys.exit(freeze() if a.cmd == "freeze" else extract(a.ticker.upper()) if a.cmd == "extract" else report(a.ticker.upper(), a.confirm))
