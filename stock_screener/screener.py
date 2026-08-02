"""NSE bullish setup screener. Top of the funnel:

    stock_screener -> watchlist_analyser -> stock_analyser -> stock_planner

Scans a universe with the SAME scoring engine the other skills use, then applies
six setup predicates to the results. It never emits a BUY -- it emits candidates.
"""
import sys
from concurrent.futures import ThreadPoolExecutor

import setups
from engine import A, W
from universe import DEFAULT_UNIVERSE, load_universe

NIFTY = "^NSEI"
SCAN_CATALYST = 5.0     # a WebSearch per name is impossible across 500; every
                        # score in this skill is therefore catalyst-neutral.


def index_returns():
    """Nifty 50 baseline for relative strength. Degrades to None on failure --
    a missing benchmark blanks the RS columns; it must not kill the scan."""
    try:
        rows, _ = A.fetch(NIFTY, "2y", "1d", suffix="")
        closes = [r["c"] for r in rows]
        return {"1m": A.pct_return(closes, 21), "3m": A.pct_return(closes, 63)}
    except BaseException as e:                    # noqa: BLE001 - report, don't abort
        print(f"WARNING: Nifty baseline unavailable ({e}); relative strength "
              f"will be blank.", file=sys.stderr)
        return {"1m": None, "3m": None}


def scan(pairs, strict=False, min_turnover=3.0, workers=16):
    """Score every symbol and evaluate all six setups against the results.

    Each worker catches BaseException: analyze.fetch() raises SystemExit on an
    unresolvable ticker, which `except Exception` does NOT catch, and one dead
    symbol would otherwise abort a 500-name scan.
    """
    idx = index_returns()

    def run(pair):
        sym, sector = pair
        try:
            o = A.compute(sym, catalyst=SCAN_CATALYST)
            rs = {k: (o["returns"][k] - idx[k])
                  if o["returns"].get(k) is not None and idx.get(k) is not None
                  else None
                  for k in ("1m", "3m")}
            # One dict per symbol, filled inside this worker and merged after
            # the pool closes: no lock, and no shared counter for 16 threads to
            # race on. It rides inside the existing scoring pass.
            diag = {}
            matched = setups.evaluate(o, rs, strict=strict,
                                      min_turnover=min_turnover, diag=diag)
            # evaluate() returns None for an illiquid name and {} for a liquid
            # one that matched nothing. Record which happened, then normalise to
            # a dict so no downstream `name in row["matched"]` sees a None.
            return {"symbol": sym, "sector": sector, "o": o, "rs": rs,
                    "illiquid": matched is None, "diag": diag,
                    "matched": {} if matched is None else matched}, None
        except BaseException as e:                # noqa: BLE001 - report, don't abort
            return None, (sym, str(e) or type(e).__name__)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(run, pairs))

    rows = [r for r, _ in results if r]
    failed = [f for _, f in results if f]
    return rows, failed


# ------------------------------------------------------- actions and ranking

MAX_TOP = 20
DEFAULT_TOP = 15

# watchlist_analyser defines these inside main() as a closure that cannot be
# imported, and spec section 11 forbids modifying that file. Restated here with
# the constants pinned by a test -- the single intentional duplication.
REPAIR_MIN_TOTAL = 6.0
REPAIR_MIN_RR = 2.0

# Setups ranked by what happens IF the trigger fires, rather than by today's
# score: the whole point of a coiled base or a fresh cross is the projection.
TRIGGER_RANKED = ("COILED", "TURN")


def repairs(proj):
    """Does the trigger actually repair the setup? Some names break out into a
    worse location than they occupy now."""
    return bool(proj and proj.get("rr") and proj["rr"] >= REPAIR_MIN_RR
                and proj["total"] >= REPAIR_MIN_TOTAL)


def _map_action(act, proj):
    if act.startswith("BUY"):
        return act
    if act.startswith("WAIT"):
        return "ALERT" if repairs(proj) else "WATCH"
    return "LATENT" if repairs(proj) else "WATCH"


def screener_action(o, proj):
    act, _ = W.action_for(o, proj)
    return _map_action(act, proj)


def clamp_top(n):
    if n > MAX_TOP:
        return MAX_TOP, True
    return max(1, n), False


def build_result_row(row, setup):
    """Flatten one scanned symbol into a renderable row for one setup."""
    o, hit = row["o"], row["matched"][setup]
    proj = W.score_at_trigger(o)
    act = screener_action(o, proj)
    if act.startswith("BUY"):
        proj = None            # a buyable name has no trigger to wait for
    rr = o["entry_gate"]["rr_at_current_price"]
    atr_d = o["atr"]["daily"]
    return {"symbol": row["symbol"], "sector": row["sector"],
            "price": o["price"], "fit": hit["fit"], "evidence": hit["evidence"],
            "total": o["score"]["total"],
            "trigger_total": proj["total"] if proj else None,
            "trigger_price": proj["trigger"] if proj else None,
            "stop": o["price"] - 1.5 * atr_d if atr_d else None,
            "rr": rr, "rs_1m": row["rs"]["1m"], "rs_3m": row["rs"]["3m"],
            "vetoed": rr is not None and rr < 1.5,
            "action": act,
            # A property of the SYMBOL, like Risk:Reward and relative strength,
            # not of the setup it matched -- so it sits on the row rather than
            # in a per-setup evidence slot, and every table including CONFLUENCE
            # prints the same column.
            #
            # `hit["ud_ratio"]`, not `hit["evidence"].get(...)`: setups.evaluate
            # puts the ratio at the top level of every matched entry beside
            # `fit` and `evidence`, CONFLUENCE included, precisely so one key
            # reads the same on every setup. A `.get` with a default would turn
            # a producer that stopped emitting it into a table of dashes -- a
            # silent claim that the market has no volume data. None still
            # survives as None: a name with no down-volume in 50 sessions has no
            # ratio, and the column must print a dash rather than invent a
            # neutral 1.00.
            "ud_ratio": hit["ud_ratio"],
            # The same contract, and the same subscript-not-`.get` reasoning,
            # for the four fields that read the volume picture rather than
            # merely counting it. ud_weighted is the 50-bar ratio weighted by
            # where each bar CLOSED in its range, ud_20 the plain ratio over the
            # last 20 bars; volume_signal and accumulation_trend are the labels
            # setups.evaluate derives from them. All four sit at the top level
            # of every matched entry, CONFLUENCE included.
            #
            # A `.get(..., "unknown")` here would be strictly worse than a
            # KeyError: "unknown" is itself a real label meaning "not enough
            # volume history to say", so a producer that stopped emitting the
            # key would be indistinguishable from a market with no history --
            # in every row of every table, silently.
            "ud_weighted": hit["ud_weighted"],
            "ud_20": hit["ud_20"],
            "volume_signal": hit["volume_signal"],
            "accumulation_trend": hit["accumulation_trend"],
            "match_count": hit["evidence"].get("count", 1),
            "o": o}


def rank(rows, setup):
    """Vetoed names always sort below clean ones (spec section 3.7), then by the
    metric appropriate to the setup's stage, then by 3-month relative strength."""
    def key(r):
        primary = (r.get("trigger_total") if setup in TRIGGER_RANKED else None)
        if primary is None:
            primary = r.get("total") or 0.0
        count = r.get("match_count", 1) if setup == "CONFLUENCE" else 0
        return (1 if r.get("vetoed") else 0,
                -count,
                -(r.get("fit") or 0.0) if setup == "CONFLUENCE" else 0.0,
                -primary,
                -(r.get("rs_3m") if r.get("rs_3m") is not None else -999))
    return sorted(rows, key=key)


# ------------------------------------------------------------------ rendering

def _n(v, fmt="{:.2f}", dash="-"):
    return fmt.format(v) if v is not None else dash


# Two per setup -- the pair that makes this a screener rather than a score dump.
EVIDENCE_COLUMNS = {
    "COILED": [("Contraction", lambda r: _n(r["evidence"]["contraction"], "{:.2f}")),
               ("Position in Base", lambda r: _n(r["evidence"]["pos_in_base"] * 100, "{:.0f}%"))],
    "BREAKOUT": [("Volume (multiple of average 20-day)",
                  lambda r: _n(r["evidence"]["vol_mult"], "{:.2f}x")
                  + (" light" if r["evidence"].get("volume_light") else "")),
                 ("Percent Above Base High",
                  lambda r: _n(r["evidence"]["pct_above_base"], "{:.1f}%"))],
    "LEADER": [("Percent From 52-Week High",
                lambda r: _n(r["evidence"]["pct_from_high"], "{:.1f}%")),
               ("Relative Strength (1-month)", lambda r: _n(r["rs_1m"], "{:+.1f}"))],
    # The pair that now CARRIES the signal. Distance to an average and RSI both
    # sat inside the entry gate already, and neither could tell a stock that had
    # turned at support from one still falling into it: NH matched at 22% of its
    # daily range and MARICO at 13%, both with unremarkable distances and RSIs.
    "PULLBACK": [("Close Position in Reversal Bar",
                  lambda r: _n(r["evidence"]["close_position"], "{:.0%}")),
                 ("Percent Below Recent Swing High",
                  lambda r: _n(r["evidence"]["retrace_pct"], "{:.1f}%"))],
    "TURN": [("Bars Since Cross",
              lambda r: _n(r["evidence"]["bars_since_cross"], "{:.0f}")),
             ("Moving Average Convergence Divergence Histogram",
              lambda r: _n(r["evidence"]["macd_hist"], "{:+.2f}"))],
    "CONFLUENCE": [("Setups Matched", lambda r: r["evidence"]["label"]),
                   ("Mean Setup Fit", lambda r: _n(r["evidence"]["mean_fit"]))],
}

# The three volume columns are BASE columns, not evidence slots: they are
# universal metrics like Risk:Reward -- one number or label meaning one thing
# for every name -- rather than the two setup-specific facts EVIDENCE_COLUMNS
# carries. Every table prints all three, CONFLUENCE included.
BASE_COLUMNS = ["Rank", "Symbol", "Sector", "Price", "Setup Fit",
                "Score Now (catalyst-neutral)", "Score at Trigger",
                "Risk:Reward", "Relative Strength (3-month)",
                # Full words, like "Average True Range" and unlike "ATR": a
                # "U/D Vol" header needs the key to decode it, and they sit
                # NEXT TO relative strength because all four are cross-sectional
                # measures of the same thing -- who has been buying this name.
                # Kept as one adjacent block for that reason; a Volume Signal
                # parked away from the ratio it reads reads as an unrelated
                # verdict rather than as the ratio's interpretation.
                #
                # The table is wide and gets wider here. That is the trade: the
                # ratio alone cannot tell a name being accumulated from one
                # being distributed INTO strength, and dropping a column to pay
                # for these would make the table narrower and harder to read,
                # not easier.
                "Up/Down Volume Ratio",
                "Volume Signal",
                "Accumulation Trend"]
TAIL_COLUMNS = ["Trigger Price", "Stop (1.5x Average True Range)", "Action"]


def render_table(rows, setup, shown, total):
    ev_cols = EVIDENCE_COLUMNS[setup]
    headers = BASE_COLUMNS + [h for h, _ in ev_cols] + TAIL_COLUMNS
    lines = [f"### {setup}"]
    if total > shown:
        lines.append(f"showing top {shown} of {total}")
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "---|" * len(headers))
    for i, r in enumerate(rows, 1):
        cells = [str(i), r["symbol"], r["sector"], _n(r["price"]),
                 _n(r["fit"]), _n(r["total"]) + ("*" if r["vetoed"] else ""),
                 _n(r["trigger_total"], "{:.2f}", "none"),
                 _n(r["rr"], "{:.2f}:1"), _n(r["rs_3m"], "{:+.1f}"),
                 # r["ud_ratio"], not r.get(...): build_result_row always sets
                 # it, so a missing key is a bug and must raise rather than
                 # quietly print a dash in every row of every table.
                 _n(r["ud_ratio"], "{:.2f}"),
                 # The labels go through _n too, on "{}": subscript so a missing
                 # key still raises, and a None label prints the same `-` every
                 # other unmeasurable cell prints rather than the word "None".
                 # (A label that could not be derived arrives as "unknown", not
                 # None -- the dash is the honest rendering of the third case,
                 # a row whose producer had nothing at all to say.)
                 _n(r["volume_signal"], "{}"),
                 _n(r["accumulation_trend"], "{}")]
        cells += [fmt(r) for _, fmt in ev_cols]
        cells += [_n(r["trigger_price"], "{:.2f}", "none"), _n(r["stop"]), r["action"]]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_key(setup):
    return (
        "**Key** — Setup Fit is 0-10 and setup-relative: an 8 for COILED and an 8 for "
        "PULLBACK are different measurements and must not be compared across tables. "
        "Score Now is the weighted 6-factor total out of 10 with catalyst held at the "
        "neutral 5.0, because a news search per name is impossible across a 500-name "
        "universe — it will differ from watchlist_analyser's score once real catalysts "
        "are set. `*` marks a Risk:Reward veto (below 1.5:1 against a 1.5x Average True "
        "Range stop); vetoed names are kept but sorted below every clean name. Score at "
        "Trigger is the projected total if the breakout trigger fires, and reads `none` "
        "for names already passing the gate, which have no trigger to wait for. Relative "
        "Strength is return minus the Nifty 50 over the same window, in percentage "
        "points. Risk:Reward is reward to the nearest real resistance divided by risk to "
        "a 1.5x Average True Range stop. Up/Down Volume Ratio is volume on up-closes "
        "divided by volume on down-closes over the last 50 sessions, so above 1.0 means "
        "net accumulation and below 1.0 net distribution; it reads `-` when the stock had "
        "no down-closes to divide by. Volume Signal reads that ratio together with "
        "where price went and where each bar closed in its own range, because the same "
        "1.4 means different things in different tapes: `accumulation` is price rising "
        "and closing strong, genuine buying; `distribution-into-strength` is a name "
        "whose up/down ratio looks healthy while sellers control every close — price "
        "drifts up, but institutional supply is being distributed into that strength, "
        "and it is the case a strong ratio alone would hide; `supported` is price soft "
        "while buyers defend every dip, often a base forming; `distribution` is "
        "distribution, unambiguously; `unknown` means there was not enough volume "
        "history to say. Accumulation Trend compares the up/down ratio over the last 20 "
        "sessions against the same 50-session number, so `strengthening` means the "
        "buying is picking up, `steady` means it is unchanged, `flattening` and `fading` "
        "mean it is losing force, `reversed` means the recent 20 sessions point the "
        "opposite way from the 50, and `unknown` means one of the two could not be "
        "measured. The CSV export carries the two raw numbers these labels are read "
        "from — the close-weighted 50-session ratio and the plain 20-session ratio — "
        "beside the labels themselves. Action follows watchlist_analyser's buckets: "
        "BUY NOW, BUY HALF, ALERT (vetoed today but the trigger repairs it), LATENT "
        "(below the bands today, but a breakout would qualify it), WATCH (matches the "
        "setup, neither buyable nor repaired by its trigger)."
    )


def render_header(scan_date, closed_bar, universe_name, n_universe, strict,
                  n_scored, failed, n_illiquid, counts):
    mode = "strict" if strict else "loosened"
    lines = [f"SCAN {scan_date} (last closed bar {closed_bar}) · universe "
             f"{universe_name} ({n_universe}) · {mode}"]
    names = ", ".join(s for s, _ in failed[:6]) + ("..." if len(failed) > 6 else "")
    lines.append(f"scored {n_scored} · FAILED {len(failed)}"
                 + (f" ({names})" if failed else "")
                 + f" · below turnover floor {n_illiquid}")
    lines.append("matches  " + " · ".join(f"{k} {counts.get(k, 0)}"
                                          for k in list(setups.SETUPS) + ["CONFLUENCE"]))
    return "\n".join(lines)


# A sector observation is a claim about the whole screen, so it is made from
# the whole match set and needs BOTH of these. The proportion alone let a
# 2-of-3 plurality read as market structure; the absolute floor alone would let
# 5 of 60 do the same. `n * 2 >= len(rows)` is the 50% share in integers, so no
# float boundary decides whether a sentence prints.
SECTOR_MIN_NAMES = 5


def render_breadth(counts, rows_by_setup, sector_filtered=False):
    """What the match counts and sector spread themselves say about the market.

    `rows_by_setup` must be the FULL match set per setup, not the truncated
    display rows: a conclusion drawn from the top 5 of 56 contradicts the count
    printed directly above it.

    `sector_filtered` is True when --sector was used. The sector observation is
    then suppressed outright -- the user chose the sector, so "5 of 5 LEADER
    names are Financial Services" restates their own argument back at them as
    though the screen had discovered it.
    """
    parts = []
    lead, brk = counts.get("LEADER", 0), counts.get("BREAKOUT", 0)
    coil = counts.get("COILED", 0)
    if lead > 2 * max(brk, 1):
        parts.append(f"{lead} leaders against {brk} breakouts — a trending, "
                     f"already-extended market where most strength is priced in.")
    elif coil > 2 * max(lead, 1):
        parts.append(f"{coil} coiled bases against {lead} leaders — the market is "
                     f"compressing rather than trending; expect resolution, not chase.")
    else:
        parts.append(f"{brk} breakouts, {coil} coiled, {lead} leaders — a mixed tape "
                     f"with no single stage dominating.")

    if sector_filtered:
        return " ".join(parts)

    for setup, rows in rows_by_setup.items():
        if not rows:
            continue          # max() over an empty tally raises; a setup that
                              # matched nothing says nothing about sectors
        tally = {}
        for r in rows:
            tally[r["sector"]] = tally.get(r["sector"], 0) + 1
        sector, n = max(tally.items(), key=lambda kv: kv[1])
        if n >= SECTOR_MIN_NAMES and n * 2 >= len(rows):
            parts.append(f"{n} of {len(rows)} {setup} names are {sector} — the screen is "
                         f"a sector call as much as a stock call.")
    return " ".join(parts)


def merge_funnel(rows, setup):
    """Add up one setup's first-failure counts across every scanned symbol.

    Each row carries the per-symbol dict evaluate() filled in, so the merge runs
    once on the main thread after the pool has closed.
    """
    gates = {}
    for r in rows:
        for label, (step, n) in ((r.get("diag") or {}).get(setup, {})).items():
            _, total = gates.get(label, (step, 0))
            gates[label] = (step, total + n)
    return gates


def funnel_stages(gates, screened):
    """Ordered [(condition, reached, failed)] for one setup.

    A predicate stops at the first condition a name fails, so every name is
    counted exactly once and the number that REACHED a condition is the screened
    count minus everyone who fell before it. Ordered by the predicate's own
    sequence, not by size: a funnel read out of order is not a funnel.
    """
    stages, reached = [], screened
    for label, (_, failed) in sorted(gates.items(), key=lambda kv: kv[1][0]):
        stages.append((label, reached, failed))
        reached -= failed
    return stages


def render_empty(setup, stages, screened):
    """A failing screen describes what the market is doing. Never pad the list.

    Spec section 5.4: name the condition that did the rejecting. "No names
    matched, N passed the liquidity pass" names nothing -- it is what let a
    BREAKOUT predicate that could not match on any day read as a market finding
    for the life of the project.
    """
    lines = [f"### {setup}", f"No names matched. {screened} names were screened."]
    live = [s for s in stages if s[1] > 0]
    if live:
        lines.append("Where they fell, in the order the setup tests: "
                     + "; ".join(f"{reached} reached {label}, {failed} failed"
                                 for label, reached, failed in live)
                     + ".")
        label, reached, failed = max(live, key=lambda s: s[2])
        if failed:
            lines.append(f"The binding condition is {label} — it rejected {failed} "
                         f"of the {reached} names that reached it.")
    return ("\n".join(lines) + " Nothing in this universe is set up this way "
            "today — that is the finding, not a gap to fill.")


def render_handoff(symbols):
    if not symbols:
        return ""
    return ("Next: adjudicate these with real catalysts set per name —\n"
            "```\n"
            f'python3 ~/.claude/skills/watchlist_analyser/watchlist.py "{",".join(symbols)}"\n'
            "```")


# ------------------------------------------------------------------------ CLI

import argparse       # noqa: E402 - kept beside the CLI it serves
import datetime as dt  # noqa: E402
import json            # noqa: E402
import os              # noqa: E402

import csv_export      # noqa: E402 - row building and file I/O live there

ALL_SETUPS = list(setups.SETUPS) + ["CONFLUENCE"]


def parse_args(argv):
    p = argparse.ArgumentParser(
        prog="screener.py",
        description="Scan an NSE universe for six named bullish setups.")
    p.add_argument("--setup", default="all",
                   help="comma list of " + ",".join(s.lower() for s in ALL_SETUPS)
                        + ", or 'all' (default)")
    p.add_argument("--universe", default=DEFAULT_UNIVERSE)
    p.add_argument("--sector", default=None,
                   help="comma list; case-insensitive substring match")
    p.add_argument("--top", type=int, default=DEFAULT_TOP)
    p.add_argument("--strict", action="store_true")
    p.add_argument("--min-turnover", type=float, default=3.0,
                   dest="min_turnover", help="rupees crore, median over 50 days")
    p.add_argument("--workers", type=int, default=16)
    p.add_argument("--json", action="store_true")
    # nargs="?" with a sentinel const, so a bare --csv and --csv PATH arrive
    # distinguishable: not passed at all is None, bare is the sentinel.
    p.add_argument("--csv", nargs="?", const=csv_export.DEFAULT_PATH,
                   default=None, metavar="PATH",
                   help="write every match to a CSV; bare flag uses "
                        "./%s/scan_<date>.csv" % csv_export.DEFAULT_DIR)
    p.add_argument("--append", action="store_true",
                   help="append to the CSV instead of overwriting it")
    p.add_argument("--refresh-universe", action="store_true", dest="refresh")
    return p.parse_args(argv)


def resolve_setups(spec):
    if spec.strip().lower() == "all":
        return list(ALL_SETUPS)
    wanted = {s.strip().upper() for s in spec.split(",") if s.strip()}
    unknown = wanted - set(ALL_SETUPS)
    if unknown:
        raise SystemExit(f"ERROR: unknown setup(s) {sorted(unknown)}. "
                         f"Valid: {', '.join(ALL_SETUPS)}")
    return [s for s in ALL_SETUPS if s in wanted]


def main(argv=None):
    a = parse_args(argv if argv is not None else sys.argv[1:])
    if a.refresh:
        from universe import refresh_universe
        return refresh_universe(a.universe)

    chosen = resolve_setups(a.setup)
    top, clamped = clamp_top(a.top)
    pairs = load_universe(a.universe,
                          sectors=a.sector.split(",") if a.sector else None)

    rows, failed = scan(pairs, strict=a.strict, min_turnover=a.min_turnover,
                        workers=a.workers)

    by_setup, counts = {}, {}
    for name in ALL_SETUPS:
        hits = [build_result_row(r, name) for r in rows if name in r["matched"]]
        counts[name] = len(hits)
        by_setup[name] = rank(hits, name)

    # Only the liquidity gate counts as "below turnover floor". A liquid name
    # that matched no setup is the ordinary case and must not inflate this.
    n_illiquid = sum(1 for r in rows if r["illiquid"])
    n_screened = len(rows) - n_illiquid
    closed = rows[0]["o"]["last_closed_bar"]["t"] if rows else "n/a"
    scan_date = dt.date.today().isoformat()

    # Before the --json return: the two output paths are independent and both
    # may be asked for in one run. by_setup goes in whole -- `top` truncates the
    # terminal, never the file.
    if a.csv is not None:
        path = csv_export.resolve_path(a.csv, scan_date)
        written = csv_export.write_csv(
            path,
            csv_export.build_rows(rows, by_setup, chosen, scan_date, closed,
                                  csv_export.universe_label(a.universe),
                                  csv_export.mode_label(a.strict)),
            append=a.append)
        # stderr, so --json --csv together still emits parseable JSON on stdout.
        print("wrote %d rows to %s" % (written, path), file=sys.stderr)

    if a.json:
        print(json.dumps({
            "scan": {"date": scan_date, "last_closed_bar": closed,
                     "universe": os.path.basename(a.universe),
                     "universe_size": len(pairs), "scored": len(rows),
                     "strict": a.strict, "top": top, "counts": counts},
            "setups": {n: [{k: v for k, v in r.items() if k != "o"}
                           for r in by_setup[n][:top]] for n in chosen},
            "failed": [{"symbol": s, "reason": r} for s, r in failed],
        }, indent=2, default=str))
        return 0

    if clamped:
        print(f"NOTE: --top clamped to the {MAX_TOP}-name cap; a list longer than "
              f"that is not a shortlist.\n")
    print(render_header(scan_date, closed, os.path.basename(a.universe),
                        len(pairs), a.strict, len(rows), failed, n_illiquid, counts))

    shortlist = []
    for name in chosen:
        print()
        hits = by_setup[name]
        if not hits:
            # n_screened, not len(rows): a name the gate rejected never reached
            # a predicate, so claiming it "passed the liquidity pass" is the
            # same lie the header used to tell.
            #
            # CONFLUENCE has no predicate of its own -- it is two or more of the
            # others agreeing -- so its funnel is the setups themselves, and the
            # per-setup counts are already in the header.
            stages = ([] if name == "CONFLUENCE"
                      else funnel_stages(merge_funnel(rows, name), n_screened))
            print(render_empty(name, stages, n_screened))
            continue
        shown = hits[:top]
        print(render_table(shown, name, len(shown), len(hits)))
        print()
        print(render_key(name))
        shortlist += [r["symbol"] for r in shown
                      if r["action"] in ("BUY NOW", "BUY HALF", "ALERT")]

    print()
    # The FULL match set per setup, not the `top` rows the table showed: the
    # breadth read is a statement about the screen, and the header two lines
    # above it already told the reader how many names that is.
    print(render_breadth(counts, {n: by_setup[n] for n in chosen},
                         sector_filtered=bool(a.sector)))
    seen, ordered = set(), []
    for s in shortlist:
        if s not in seen:
            seen.add(s)
            ordered.append(s)
    hand = render_handoff(ordered[:10])
    if hand:
        print()
        print(hand)
    print("\nMechanical framework output, not personalised investment advice.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
