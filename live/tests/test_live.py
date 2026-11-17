import json, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "live" / "earnings_night"))
import earnings_night as en  # noqa: E402
from live import fred_loader  # noqa: E402

INVH_SAMPLE = ("Core FFO per share increased 5.0% to $0.51 ... Core FFO per share — diluted $1.92 - $1.98 $1.95 $1.94 $0.01 "
               "AFFO per share x Same Store Core Revenues growth (1) 1.5% - 2.3% 1.9% 1.9% Same Store NOI growth (2) 0.4% - 1.9% 1.15% 1.15%")
AMH_SAMPLE = ("Core FFO attributable to common share and unit holders increased 5.2% year-over-year to $0.49 per FFO share and unit Core FFO attributable to common share and unit holders $1.89 - $1.95 $1.93 - $1.97 "
              "Same-Home Core revenues growth 1.25% - 3.25% 1.50% - 3.00% Core NOI growth 1.00% - 3.00% 1.40% - 3.40%")


def test_extract_invh_and_amh():
    c, _ = en.extract_candidates(INVH_SAMPLE, "INVH")
    assert c["core_ffo_q"] == 0.51 and c["core_ffo_fy26_mid"] == 1.95 and c["ss_noi_fy26_mid"] == 1.15
    c, _ = en.extract_candidates(AMH_SAMPLE, "AMH")
    assert c["core_ffo_q"] == 0.49 and c["core_ffo_fy26_low"] == 1.93 and c["ss_rev_fy26_mid"] == 2.25 and c["ss_noi_fy26_mid"] == 2.4


def _frozen(now):
    return {"frozen_at": now.isoformat(), "file": "expectations.json", "sha256": "0" * 64}


def test_report_shows_deltas_and_never_ends_without_review():
    now = datetime.now(timezone.utc)
    txt = en.build_report("INVH", {"core_ffo_fy26_mid": 1.96, "ss_noi_fy26_mid": 1.15, "ss_rev_fy26_mid": 1.9}, now + timedelta(hours=1), _frozen(now))
    assert "REVIEW_REQUIRED" in txt and "UNCONFIRMED" in txt
    assert "core_ffo_fy26_guidance_mid" in txt and "up" in txt  # 1.95 -> 1.96
    assert "unchanged" in txt  # same-store midpoint held


def test_report_cannot_see_prior_published_after_release():
    now = datetime.now(timezone.utc)
    txt = en.build_report("AMH", {"core_ffo_fy26_mid": 1.95}, now - timedelta(days=30), _frozen(now))
    # the prior was frozen after this release time, so no expectation is visible: no delta may be invented
    assert "n/a" in txt


def test_hash_mismatch_refuses(tmp_path, monkeypatch):
    f = tmp_path / "FROZEN.json"
    f.write_text(json.dumps({"frozen_at": "2026-10-28T00:00:00+00:00", "file": "expectations.json", "sha256": "bad"}))
    monkeypatch.setattr(en, "FROZEN", f)
    with pytest.raises(SystemExit):
        en._verify_frozen()


def test_fred_asof_drops_missing_and_blocks_future(monkeypatch, tmp_path):
    monkeypatch.setattr(fred_loader, "CACHE", tmp_path)
    monkeypatch.setattr(fred_loader, "_get", lambda path, **kw: {"observations": [{"date": "2024-01-01", "value": "1.5"}, {"date": "2024-02-01", "value": "."}]})
    assert fred_loader.as_of_series("X", "2025-01-01") == [("2024-01-01", 1.5)]
    assert fred_loader.value_as_of("X", "2024-02-01", "2025-01-01") is None
    with pytest.raises(ValueError):
        fred_loader.as_of_series("X", "2999-01-01")
