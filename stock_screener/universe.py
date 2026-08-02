"""The scan universe: a tab-separated SYMBOL<TAB>SECTOR file.

Sector drives the Sector column, the --sector filter, and the concentration
observation in the breadth read ("7 of 9 breakouts are PSU banks" is a very
different message from seven breakouts across seven sectors).
"""
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_UNIVERSE = os.path.join(_HERE, "nifty500.txt")


def load_universe(path=None, sectors=None):
    """Parse the universe file into ordered, deduplicated (symbol, sector) pairs.

    A missing or empty file is a hard error. Scanning an empty list would print
    a clean "no matches" report that looks like a market finding rather than a
    broken install.
    """
    path = path or DEFAULT_UNIVERSE
    if not os.path.exists(path):
        raise SystemExit(f"ERROR: universe file not found: {path}")

    seen, out = set(), []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            sym = parts[0].strip().upper()
            if sym.endswith(".NS"):
                sym = sym[:-3]
            sector = parts[1].strip() if len(parts) > 1 and parts[1].strip() else "Unknown"
            if not sym or sym in seen:
                continue
            seen.add(sym)
            out.append((sym, sector))

    if not out:
        raise SystemExit(f"ERROR: universe file is empty: {path}")

    if sectors:
        wanted = [s.strip().lower() for s in sectors if s.strip()]
        out = [(s, sec) for s, sec in out
               if any(w in sec.lower() for w in wanted)]
        if not out:
            raise SystemExit(
                f"ERROR: no symbols in {os.path.basename(path)} match sector "
                f"filter {sectors!r}.")
    return out


import csv
import io
import urllib.request

NSE_CSV_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
_NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/csv,*/*",
    "Referer": "https://www.nseindia.com/",
}


def parse_nse_csv(text):
    """Extract (SYMBOL, Industry) from NSE's index constituent CSV.

    Uses csv.DictReader rather than splitting on commas: company names contain
    commas inside quotes and a naive split silently shifts every later column.
    """
    reader = csv.DictReader(io.StringIO(text))
    cols = {c.strip().lower(): c for c in (reader.fieldnames or [])}
    if "symbol" not in cols or "industry" not in cols:
        raise SystemExit(
            f"ERROR: NSE CSV is missing required columns; got "
            f"{reader.fieldnames}. Expected 'Symbol' and 'Industry'.")
    out = []
    for r in reader:
        sym = (r.get(cols["symbol"]) or "").strip().upper()
        sector = (r.get(cols["industry"]) or "").strip() or "Unknown"
        if sym:
            out.append((sym, sector))
    if not out:
        raise SystemExit("ERROR: NSE CSV contained no rows.")
    return out


def _fetch_nse_csv(url):
    req = urllib.request.Request(url, headers=_NSE_HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def refresh_universe(path=None):
    """Re-pull the constituent list. Returns a process exit code.

    On failure the existing file is left untouched: a stale universe beats an
    empty one, and index reshuffles happen only twice a year.
    """
    path = path or DEFAULT_UNIVERSE
    try:
        rows = parse_nse_csv(_fetch_nse_csv(NSE_CSV_URL))
    except SystemExit:
        raise
    except BaseException as e:                    # noqa: BLE001 - report, don't abort
        print(f"ERROR: could not refresh from NSE ({e}).\n"
              f"NSE blocks plain scripted HTTP without browser cookies. Fetch\n"
              f"  {NSE_CSV_URL}\n"
              f"in a browser and save it, then re-run with the saved file, or edit\n"
              f"  {path}\n"
              f"by hand. The existing universe file was NOT modified.")
        return 1

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# Nifty 500 scan universe -- SYMBOL<TAB>SECTOR\n")
        fh.write("# Refresh with: python3 screener.py --refresh-universe\n")
        for sym, sector in rows:
            fh.write(f"{sym}\t{sector}\n")
    print(f"Universe refreshed: {len(rows)} symbols written to {path}")
    return 0
