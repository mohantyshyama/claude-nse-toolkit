"""CSV export for a scan. Long format: one row per (symbol, setup) pair.

A stock matching three setups produces three rows. The schema is therefore
stable: adding a seventh setup later costs zero new columns, and a reader can
group by `setup` or filter on it without a wide table of mostly-empty fields.

Two rules the schema depends on:

* `setups_matched` and `match_count` are on EVERY row, not only CONFLUENCE, so a
  COILED row shows the stock is also a LEADER without a join back to the file.
* Every value is a raw number -- `6.217`, not `"6.2%"`; `4.106`, not `"4.11x"`;
  `pos_in_base` as `0.982`, not `"98%"`. A CSV that needs string-stripping before
  a column can be sorted is broken. The percent signs and multipliers live in
  screener.EVIDENCE_COLUMNS, which renders for a human reading a terminal.

This module owns row building and file I/O only. The scan, the ranking and the
terminal rendering stay in screener.py; the CSV is an additive output path that
reuses screener.build_result_row and screener.rank rather than restating either.
"""
import csv
import datetime as dt
import os

import setups

COLUMNS = ["scan_date", "last_closed_bar", "universe", "mode",
           "symbol", "sector",
           "setup", "rank", "setup_fit",
           "score_now", "score_at_trigger", "risk_reward", "vetoed", "action",
           "price", "trigger_price", "stop",
           "rs_1m", "rs_3m", "ud_ratio", "ud_weighted", "ud_20",
           "volume_signal", "accumulation_trend",
           "setups_matched", "match_count",
           "evidence_1_label", "evidence_1_value",
           "evidence_2_label", "evidence_2_value",
           "flags"]

# (column label, evidence key) x2 per setup. Mirrors screener.EVIDENCE_COLUMNS
# in intent -- the pair that makes this a screener rather than a score dump --
# but emits raw numbers under stable snake_case keys.
#
# LEADER's second pair is the MA stack, NOT rs_1m: rs_1m already has a column of
# its own, and emitting it twice at two different roundings gives the file two
# columns claiming the same number. Stack completeness is a real input to
# fit_leader (25% of it) and appears nowhere else in the row.
#
# CONFLUENCE has no pair at all. Its evidence is the list of setups and the mean
# fit, which the setups_matched and setup_fit columns already carry.
EVIDENCE = {
    "COILED":     [("contraction", "contraction"),
                   ("pos_in_base", "pos_in_base")],
    "BREAKOUT":   [("vol_mult", "vol_mult"),
                   ("pct_above_base", "pct_above_base")],
    "LEADER":     [("pct_from_high", "pct_from_high"),
                   ("ma_stack_full", "full_stack")],
    # close_position stays a 0..1 fraction here, like pos_in_base: the terminal
    # renders it as a percentage, the file keeps the raw number.
    #
    # retrace_pct is the percent below a recent SWING HIGH -- the gate's own
    # number -- not the share of the 52-week range fit_pullback scores. The
    # evidence dict carries both under separate keys for exactly that reason.
    "PULLBACK":   [("close_position", "close_position"),
                   ("retrace_pct", "retrace_pct")],
    "TURN":       [("bars_since_cross", "bars_since_cross"),
                   ("macd_hist", "macd_hist")],
    "CONFLUENCE": [],
}

# Places by kind of number, not one global setting. Scores are published to 2 by
# the engine itself; relative strength is a percentage-point spread where the
# first decimal is already generous; evidence keeps 3 because pos_in_base lives
# in 0..1 and 2 places would collapse 0.982 and 0.984 into one number. Four
# places on an RSI (52.9579) is false precision the input data cannot support.
SCORE_PLACES = 2
RS_PLACES = 1
EVIDENCE_PLACES = 3
# All three up/down volume ratios -- the 50-bar ratio, its close-weighted twin
# and the 20-bar ratio -- are published to the SAME two places the terminal
# column prints, and deliberately not to EVIDENCE_PLACES: it is not evidence
# living in 0..1 where the third decimal separates two names, it is a ratio
# around 1.0 built from 50 bars of volume, and 1.472 vs 1.473 is noise the
# input cannot support. Two places also means the file and the screen never
# show a reader two different numbers for the same measurement.
UD_PLACES = 2

# Rows the FILE keeps per setup, ranked. Six setups therefore write at most 120
# rows for a full scan.
#
# It is a SEPARATE limit from --top, not the same one applied twice. --top is
# terminal readability and clamps at 20 for a different reason: a shortlist a
# human reads. This is the file's own ceiling, and it exists because the ranking
# below the twentieth name is not a finding -- a 45-name LEADER table's fortieth
# row is a name that cleared the gate and nothing more. Keeping it made the file
# look like a data set when it is a shortlist, and invited exactly the sorting
# and re-ranking downstream that screener.rank exists to prevent.
#
# The rows kept are the TOP of the ranking, so `rank` stays contiguous 1..20 and
# a reader can still reproduce any terminal table from the file.
MAX_ROWS_PER_SETUP = 20

DEFAULT_DIR = "scans"


class _DefaultPath:
    """Sentinel for a bare `--csv`, distinguishing it from `--csv PATH`.

    An object rather than a magic string: a user whose file really is called
    `__default__` must still get the file they asked for.
    """

    def __repr__(self):                     # pragma: no cover - debug aid only
        return "<default csv path>"


DEFAULT_PATH = _DefaultPath()


def num(v, places=SCORE_PLACES):
    """Raw numeric for the file: no %, no x, no thousands separator.

    None becomes the empty string, never the text "None" and never nan -- both
    of those force every consumer to clean the column before it can be summed.
    """
    if v is None:
        return ""
    if isinstance(v, bool):
        # Must precede the int arm: bool IS an int in Python, and `full_stack`
        # has to leave here as 1/0 rather than True/False.
        return int(v)
    if isinstance(v, int):
        return v
    v = float(v)
    if v != v:                              # nan: unmeasurable, same as None
        return ""
    return round(v, places)


def text(v):
    """A label cell: the label verbatim, and an empty cell for no label.

    The same contract num() keeps for numbers, for the columns whose values are
    words. `str(v)` alone would write the four characters "None" into
    volume_signal, which sorts and filters as though it were a label of its own
    and reads, to anyone opening the file, like a fifth signal the key never
    defines. An empty cell is the honest form of "no value here".

    Note this is NOT the same case as the "unknown" label: "unknown" is a real
    finding -- too little volume history to classify the name -- and arrives as
    that word, so it is written out as that word.
    """
    return "" if v is None else str(v)


# The two date COLUMNS. `02-Aug-2026`, never `2026-08-02`.
#
# Excel parses an ISO date on import, converts it to its internal serial and
# renders the cell as a bare number: the user opens the file and reads 46236
# where a date should be. An alphabetic month cannot be mistaken for arithmetic,
# and it is unambiguous in a way `02-08-2026` is not.
#
# The FILENAME deliberately stays ISO -- scans/scan_2026-08-02.csv. That is not
# an oversight or a missed case: a directory of scans has to list in date order,
# and `02-Aug-2026` sorts next to `02-Sep-2025`. The split is the point. The two
# formats serve a spreadsheet cell and a directory listing respectively, and
# neither format is right for both jobs. See default_path, which is unchanged.
DATE_FORMAT = "%d-%b-%Y"


def date_cell(value):
    """An ISO date string or date object -> `02-Aug-2026`.

    Anything that is not an ISO date is passed through verbatim rather than
    dropped: `n/a` is what screener.main stamps when a scan produced no rows at
    all, and blanking it would turn "we could not tell" into "there was none".

    Mutation note: a `datetime.date` needs no branch of its own, and neither
    does the empty string. `str(date(2026, 8, 2))` IS "2026-08-02" and
    `str(datetime(...))` starts with it, so both take the ISO path and land on
    the same answer; "" fails the parse and falls through to itself. Both
    special cases were written and both were equivalent mutants -- no test could
    tell them from their absence -- so they are gone rather than sitting here
    looking load-bearing. The None guard is NOT equivalent: without it `str(None)`
    is the text "None", which is exactly the cell num() exists to prevent.
    """
    if value is None:
        return ""
    text = str(value)
    try:
        return dt.datetime.strptime(text[:10], "%Y-%m-%d").strftime(DATE_FORMAT)
    except ValueError:
        return text


def universe_label(path):
    """`/x/y/nifty500.txt` -> `nifty500`. The universe, not the file it lives in."""
    return os.path.splitext(os.path.basename(path))[0]


def mode_label(strict):
    """The same two words render_header prints, so the file and the terminal
    cannot disagree about which thresholds produced the rows."""
    return "strict" if strict else "loosened"


def default_path(scan_date, base="."):
    return os.path.join(base, DEFAULT_DIR, "scan_%s.csv" % scan_date)


def resolve_path(value, scan_date, base="."):
    """`--csv` -> ./scans/scan_<date>.csv; `--csv PATH` -> exactly PATH."""
    if value is DEFAULT_PATH:
        return default_path(scan_date, base)
    return value


def _flags(evidence):
    """Pipe-delimited caveats on the row itself.

    Only volume_light today. Only match_breakout ever emits the key, so no
    setup-name test is needed here: it is a BREAKOUT on 1.5-2.0x average volume,
    under stock_analyser's 2x definition of a trigger. Dropping it on export
    would republish a near-miss as a confirmed breakout.
    """
    flags = []
    if evidence.get("volume_light"):
        flags.append("volume_light")
    return "|".join(flags)


def build_rows(scan_rows, by_setup, chosen, scan_date, last_closed_bar,
               universe, mode):
    """One dict per (symbol, setup), in `chosen` order and then in rank order.

    `by_setup` is screener.main's already-ranked {setup: [result rows]} map, in
    FULL -- never sliced to --top. The rank column preserves the terminal's
    ordering because the list is literally the one the terminal ranked, so
    `rank <= 15` reproduces the on-screen table exactly. --top governs terminal
    readability alone and never reaches this function; the file's own ceiling is
    MAX_ROWS_PER_SETUP, applied here to the top of each ranking.

    `scan_rows` is scan()'s output, used only to answer "what else did this
    symbol match" -- which is asked of the whole scan, not of the chosen subset:
    a --setup coiled export still reports that a name is also a LEADER.
    """
    matched_by_symbol = {
        r["symbol"]: [n for n in setups.SETUPS if n in r["matched"]]
        for r in scan_rows
    }
    out = []
    for name in chosen:
        ranked = (by_setup.get(name) or [])[:MAX_ROWS_PER_SETUP]
        for rank, r in enumerate(ranked, 1):
            pairs = EVIDENCE[name]
            ev = r["evidence"]
            e1_label, e1_value = ((pairs[0][0],
                                   num(ev.get(pairs[0][1]), EVIDENCE_PLACES))
                                  if pairs else ("", ""))
            e2_label, e2_value = ((pairs[1][0],
                                   num(ev.get(pairs[1][1]), EVIDENCE_PLACES))
                                  if pairs else ("", ""))
            # Every ranked row is built from a scanned row, so the default is
            # unreachable in practice; it is here so a caller mismatch degrades
            # to a thinner row rather than losing a finished scan to a KeyError.
            matched = matched_by_symbol.get(r["symbol"], [])
            out.append({
                # Formatted here and not by the caller: main() passes the same
                # ISO scan_date to resolve_path, which must keep it ISO.
                "scan_date": date_cell(scan_date),
                "last_closed_bar": date_cell(last_closed_bar),
                "universe": universe,
                "mode": mode,
                "symbol": r["symbol"],
                "sector": r["sector"],
                "setup": name,
                "rank": rank,
                "setup_fit": num(r["fit"]),
                "score_now": num(r["total"]),
                "score_at_trigger": num(r["trigger_total"]),
                "risk_reward": num(r["rr"]),
                "vetoed": int(bool(r["vetoed"])),
                "action": r["action"],
                "price": num(r["price"]),
                "trigger_price": num(r["trigger_price"]),
                "stop": num(r["stop"]),
                "rs_1m": num(r["rs_1m"], RS_PLACES),
                "rs_3m": num(r["rs_3m"], RS_PLACES),
                # A dedicated column immediately after rs_3m, not an evidence
                # slot: it means the same thing on every row of every setup,
                # including CONFLUENCE. num() leaves an unmeasurable ratio as an
                # empty cell rather than writing a neutral 1.0.
                #
                # Subscript, not `.get`: build_result_row sets the key on every
                # row it builds, so a row without it is a caller bug. `.get`
                # would write an empty cell for the whole file and read as "the
                # market has no volume data" instead of raising.
                "ud_ratio": num(r["ud_ratio"], UD_PLACES),
                # The same block, in the order a reader works through it: the
                # two remaining raw ratios first, at ud_ratio's own two places
                # for the same reason, then the two labels derived from them.
                # Subscript throughout, for the reason above.
                "ud_weighted": num(r["ud_weighted"], UD_PLACES),
                "ud_20": num(r["ud_20"], UD_PLACES),
                "volume_signal": text(r["volume_signal"]),
                "accumulation_trend": text(r["accumulation_trend"]),
                "setups_matched": "|".join(matched),
                "match_count": len(matched),
                "evidence_1_label": e1_label,
                "evidence_1_value": e1_value,
                "evidence_2_label": e2_label,
                "evidence_2_value": e2_value,
                "flags": _flags(ev),
            })
    return out


def write_csv(path, rows, append=False):
    """Write `rows` to `path` and return how many data rows were written.

    The header goes in only when the file is new or empty. Appending a second
    header mid-file turns one table into two and breaks every reader; omitting
    it from a fresh file leaves the columns unnamed. Both cases are the same
    test -- is there already content here -- and it is asked of the file on
    disk, not of the flag.
    """
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    has_content = (append and os.path.exists(path)
                   and os.path.getsize(path) > 0)
    with open(path, "a" if append else "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        if not has_content:
            writer.writeheader()
        writer.writerows(rows)
    return len(rows)
