"""Earnings study for a pair: past earnings dates, each leg's reaction, and the spread move around the print.

python live/earnings_night/pair_earnings_study.py LEN DHI
Public price data (yfinance). Reaction = close-to-close return from the last close before the release to the
close of the first session that can reflect it. Release timing (before open / after close) is taken from the
timestamp yfinance gives; where the hour is missing it is treated as after close and flagged.
"""
import sys, warnings
import numpy as np, pandas as pd, yfinance as yf

warnings.filterwarnings("ignore")


def earnings_dates(tk, n=40):
    t = yf.Ticker(tk)
    d = t.get_earnings_dates(limit=n)
    d = d.reset_index()
    col = [c for c in d.columns if "Earnings Date" in c][0]
    d["dt"] = pd.to_datetime(d[col])
    return d


def reaction(px, dt):
    """First session whose close reflects the release, and the return over it."""
    day = pd.Timestamp(dt.date())
    after_close = dt.hour >= 15 or dt.hour == 0  # midnight stamps are treated as after close (flagged by caller)
    idx = px.index.searchsorted(day)
    if idx >= len(px):
        return None
    first = idx + 1 if after_close else idx
    if first >= len(px) or first < 1:
        return None
    return float(px.iloc[first] / px.iloc[first - 1] - 1), px.index[first]


def study(a, b):
    px = yf.download([a, b, "SPY"], start="2015-01-01", progress=False)["Close"].dropna()
    rets = px.pct_change()
    rows = []
    for tk in (a, b):
        d = earnings_dates(tk)
        d = d[d["Reported EPS"].notna()]
        for _, r in d.iterrows():
            dt = r["dt"].tz_localize(None) if r["dt"].tzinfo is None else r["dt"].tz_convert("America/New_York").tz_localize(None)
            res = reaction(px[tk], dt)
            if res is None:
                continue
            ret, sess = res
            # abnormal vs SPY on the same session, and vs the other leg
            other = b if tk == a else a
            ab = ret - float(rets["SPY"].loc[sess])
            rel = ret - float(rets[other].loc[sess])
            rows.append(dict(reporter=tk, date=dt.date(), session=sess.date(), ret=ret, abn_spy=ab, rel_other=rel,
                             surprise=r.get("Surprise(%)")))
    return pd.DataFrame(rows)


def upcoming(tk):
    t = yf.Ticker(tk)
    d = t.get_earnings_dates(limit=12).reset_index()
    col = [c for c in d.columns if "Earnings Date" in c][0]
    d["dt"] = pd.to_datetime(d[col])
    now = pd.Timestamp.now(tz=d["dt"].dt.tz)
    f = d[d["Reported EPS"].isna() & (d["dt"] >= now)]
    return None if f.empty else f.sort_values("dt").iloc[0]["dt"]


if __name__ == "__main__":
    a, b = sys.argv[1].upper(), sys.argv[2].upper()
    df = study(a, b)
    print("pair", a, b, "events", len(df))
    for tk in (a, b):
        s = df[df.reporter == tk]
        other = b if tk == a else a
        print("\n%s reports: n=%d | own reaction mean %+.2f%% sd %.2f%% | vs SPY mean %+.2f%% | vs %s mean %+.2f%% (t %.1f)"
              % (tk, len(s), 100 * s.ret.mean(), 100 * s.ret.std(), 100 * s.abn_spy.mean(), other,
                 100 * s.rel_other.mean(), s.rel_other.mean() / (s.rel_other.std() / np.sqrt(len(s))) if len(s) > 2 else float("nan")))
        print("  abs reaction mean %.2f%%; positive-surprise events: %d, negative: %d" % (
            100 * s.ret.abs().mean(), int((s.surprise > 0).sum()), int((s.surprise < 0).sum())))
        print("  last 4:", ", ".join("%s %+.1f%%" % (r.date, 100 * r.ret) for r in s.sort_values("date").tail(4).itertuples()))
    print("\nupcoming:", {tk: str(upcoming(tk)) for tk in (a, b)})
    df.to_csv("live/earnings_night/data/study_%s_%s.csv" % (a, b), index=False)
