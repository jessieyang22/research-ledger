"""Fetch an issuer's latest earnings-release exhibit (8-K Item 2.02, Ex. 99.1) from SEC EDGAR.

Public data only. SEC requires a contact in the User-Agent: set SEC_USER_AGENT="Name email".
Writes the plain text of the release to live/earnings_night/data/<TICKER>_<accession>.txt and returns its path.
Nothing here decides what a number means; extract.py proposes candidates and a person confirms them.
"""
import html as _html, os, re, sys, time, warnings
from pathlib import Path

import requests

warnings.filterwarnings("ignore")

HERE = Path(__file__).parent
DATA = HERE / "data"
UA = os.environ.get("SEC_USER_AGENT", "research-student contact@example.com")
H = {"User-Agent": UA}
CIKS = {"AMH": "0001562401", "INVH": "0001687229"}  # sec.gov company_tickers.json, checked at build time


def _get(url):
    time.sleep(0.2)  # stay well under SEC's request-rate limit
    r = requests.get(url, headers=H, timeout=40)
    r.raise_for_status()
    return r


def earnings_filings(ticker, n=3):
    """Return up to n recent 8-K filings that carry Item 2.02: [(accession, filing_date), ...]."""
    j = _get("https://data.sec.gov/submissions/CIK%s.json" % CIKS[ticker]).json()["filings"]["recent"]
    out = []
    for acc, form, d, items in zip(j["accessionNumber"], j["form"], j["filingDate"], j["items"]):
        if form == "8-K" and "2.02" in (items or ""):
            out.append((acc, d))
            if len(out) >= n:
                break
    return out


def exhibit_text(ticker, accession):
    """Pull the EX-99.1 press release out of the full submission text file (works when the index lacks the exhibit)."""
    cik = int(CIKS[ticker])
    url = "https://www.sec.gov/Archives/edgar/data/%d/%s.txt" % (cik, accession)
    raw = _get(url).text
    docs = re.findall(r"(?is)<DOCUMENT>(.*?)</DOCUMENT>", raw)
    pick = [d for d in docs if re.search(r"(?i)<TYPE>\s*EX-99\.1", d)]
    if not pick:
        raise RuntimeError("no EX-99.1 found in %s" % url)
    html = pick[0]
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = _html.unescape(text).replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip(), url


def fetch_latest(ticker, which=0):
    DATA.mkdir(parents=True, exist_ok=True)
    acc, filed = earnings_filings(ticker, which + 1)[which]
    text, url = exhibit_text(ticker, acc)
    p = DATA / ("%s_%s.txt" % (ticker, acc))
    p.write_text("SOURCE_URL: %s\nFILED: %s\n\n%s" % (url, filed, text))
    return p


if __name__ == "__main__":
    t = sys.argv[1].upper()
    w = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    print(fetch_latest(t, w))
