"""CSV export for a scan. Long format: one row per (symbol, setup) pair.

A stock matching three setups produces three rows. The schema is therefore
stable: adding a seventh setup later costs zero new columns, and a reader can
group by `setup_name` or filter on it without a wide table of mostly-empty
fields.

THE NAMING RULE, which every column added after this one must follow:

    A HEADER MUST CONVEY WHAT THE NUMBER IS AND IN WHAT UNIT, WITHOUT THE
    READER CONSULTING THE KEY.

The file is opened in Excel a month later by someone who does not have this
skill's documentation beside them. `ud_20` told that reader nothing: not what
was counted, not over how many bars, not whether high is good. `rs_3m` did not
say whether 11.4 was a percent, a ratio or a rank, nor what it was measured
against. `stop` did not say where the stop came from. So the headers are long
and dull on purpose -- `up_down_volume_ratio_20d`,
`relative_strength_3month_vs_nifty50_pct_points`,
`stop_price_1p5_atr_below_last` -- and a header that needs a glossary entry to
be understood is the bug, not the length that avoids it.

Two mechanical constraints on that rule:

* Valid snake_case identifiers: no spaces, no punctuation beyond `_`, never
  leading with a digit. `pandas` attribute access and spreadsheet formulas both
  stay comfortable, so the verbosity costs a reader nothing at the keyboard.
  A decimal point in a name becomes `p` -- `1p5_atr`, not `1.5_atr`.
* Names stay unique. Two columns whose names overlap or collide is the failure
  the length is supposed to prevent, not one it excuses.

Two further rules the schema depends on:

* `all_setups_matched` and `setups_matched_count` are on EVERY row, not only
  CONFLUENCE, so a COILED row shows the stock is also a LEADER without a join
  back to the file.
* Every value is a raw number -- `6.217`, not `"6.2%"`; `4.106`, not `"4.11x"`;
  `pos_in_base` as `0.982`, not `"98%"`. A CSV that needs string-stripping before
  a column can be sorted is broken. The percent signs and multipliers live in
  screener.EVIDENCE_COLUMNS, which renders for a human reading a terminal.
  The rule above is about the HEADER; this one is about the CELL, and they
  reinforce each other: the unit lives in the name so it need not live in the
  value.

This module owns row building and file I/O only. The scan, the ranking and the
terminal rendering stay in screener.py; the CSV is an additive output path that
reuses screener.build_result_row and screener.rank rather than restating either.
"""
import csv
import datetime as dt
import os

import setups

# Thirty-one columns, in this order. The order is the schema -- a reader keying
# on position sees every value to the right of a moved column shift -- so new
# columns go where they belong semantically and the whole list is asserted, not
# sampled.
COLUMNS = ["scan_date", "last_closed_bar_date", "universe_name",
           "threshold_mode",
           "symbol", "sector",
           "setup_name", "rank_within_setup", "setup_fit_score_0_to_10",
           "score_now_catalyst_neutral_0_to_10",
           "score_if_trigger_fires_0_to_10",
           "risk_reward_ratio_vs_1p5_atr_stop", "risk_reward_veto_applied",
           "action_bucket",
           "last_price", "trigger_price_that_repairs_setup",
           "stop_price_1p5_atr_below_last",
           "relative_strength_1month_vs_nifty50_pct_points",
           "relative_strength_3month_vs_nifty50_pct_points",
           "up_down_volume_ratio_50d", "close_weighted_volume_ratio_50d",
           "up_down_volume_ratio_20d",
           "volume_signal_reading", "accumulation_trend_reading",
           "all_setups_matched", "setups_matched_count",
           "evidence_1_metric_name", "evidence_1_metric_value",
           "evidence_2_metric_name", "evidence_2_metric_value",
           "warning_flags"]

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
# fit, which the all_setups_matched and setup_fit_score_0_to_10 columns already
# carry.
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
# The rows kept are the TOP of the ranking, so `rank_within_setup` stays
# contiguous 1..20 and a reader can still reproduce any terminal table from the
# file.
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
    volume_signal_reading, which sorts and filters as though it were a label of
    its own and reads, to anyone opening the file, like a fifth signal the key
    never defines. An empty cell is the honest form of "no value here".

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


def per_setup_path(base_path, setup):
    """`scans/scan_2026-08-02.csv` + COILED -> `scans/scan_2026-08-02_COILED.csv`.

    The setup goes before the extension, not after it: `scan.csv_COILED` is not
    a CSV to any spreadsheet, file manager or glob, and the whole point of the
    split is a file the reader can double-click.

    The extension is whatever the base carried, copied verbatim rather than
    forced to `.csv`. `--csv out.txt --csv-per-setup` gives `out_COILED.txt`:
    the user named the format they wanted and the per-setup files are the same
    format, so inventing a different suffix for them would be the surprise.
    A base with no extension at all yields none, for the same reason.
    """
    stem, ext = os.path.splitext(base_path)
    return "%s_%s%s" % (stem, setup, ext)


def group_by_setup(rows):
    """Built rows -> [(setup, its rows)], in the order the setups first appear.

    Grouped off the ROWS, never off setups.SETUPS or the `chosen` list: a setup
    that matched nothing has no rows here and therefore no entry, which is what
    makes "no matches writes no file" fall out of the data rather than out of a
    branch someone can forget. The ordering is the combined file's own, so the
    listing of per-setup files reads down in the same order as the file they
    were split from.
    """
    groups = {}
    order = []
    for row in rows:
        name = row["setup_name"]
        if name not in groups:
            groups[name] = []
            order.append(name)
        groups[name].append(row)
    return [(name, groups[name]) for name in order]


def write_per_setup(base_path, rows, append=False):
    """One file per setup PRESENT IN `rows`. Returns [(path, row count)].

    Additional to the combined file, never a replacement: the caller writes
    both. A reader who wants the whole scan opens one file; a reader working a
    single setup opens theirs, and neither has to filter the other's.

    A setup with no matches gets NO FILE, not a header-only one. An empty
    `scan_2026-08-02_TURN.csv` sitting in the directory reads as "the scan
    produced nothing" to anyone who opens it, when what happened is that TURN
    matched nothing while COILED matched eleven. Absence is the honest form of
    that, and it is legible next to the sibling files that do exist.

    This is also why the combined file is written unconditionally and this one
    is not: the combined file is the scan's record, and a scan that matched
    nothing anywhere is a finding that needs a headed, parseable file to say so.
    A per-setup file is a slice, and a slice with nothing in it is not a
    finding, it is an absence.

    `append` is threaded through to match the combined file: one flag governs
    the run, so a --append scan cannot leave the combined file growing while its
    per-setup siblings are silently truncated.
    """
    return [(per_setup_path(base_path, name),
             write_csv(per_setup_path(base_path, name), group, append=append))
            for name, group in group_by_setup(rows)]


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
    FULL -- never sliced to --top. The rank_within_setup column preserves the
    terminal's ordering because the list is literally the one the terminal
    ranked, so `rank_within_setup <= 15` reproduces the on-screen table exactly.
    --top governs terminal readability alone and never reaches this function;
    the file's own ceiling is
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
            # The keys are the verbose COLUMNS names; the values come off the
            # terse INTERNAL keys build_result_row publishes. The two
            # vocabularies are deliberately separate: `r["rs_3m"]` is a field on
            # an in-memory row that screener.py also ranks and renders from, and
            # renaming it would reach into analyze.py's shape. Only the FILE's
            # headers are verbose, because only the file is read cold.
            out.append({
                # Formatted here and not by the caller: main() passes the same
                # ISO scan_date to resolve_path, which must keep it ISO.
                "scan_date": date_cell(scan_date),
                "last_closed_bar_date": date_cell(last_closed_bar),
                "universe_name": universe,
                "threshold_mode": mode,
                "symbol": r["symbol"],
                "sector": r["sector"],
                "setup_name": name,
                "rank_within_setup": rank,
                "setup_fit_score_0_to_10": num(r["fit"]),
                "score_now_catalyst_neutral_0_to_10": num(r["total"]),
                "score_if_trigger_fires_0_to_10": num(r["trigger_total"]),
                "risk_reward_ratio_vs_1p5_atr_stop": num(r["rr"]),
                "risk_reward_veto_applied": int(bool(r["vetoed"])),
                "action_bucket": r["action"],
                "last_price": num(r["price"]),
                "trigger_price_that_repairs_setup": num(r["trigger_price"]),
                "stop_price_1p5_atr_below_last": num(r["stop"]),
                "relative_strength_1month_vs_nifty50_pct_points":
                    num(r["rs_1m"], RS_PLACES),
                "relative_strength_3month_vs_nifty50_pct_points":
                    num(r["rs_3m"], RS_PLACES),
                # A dedicated column immediately after the 3-month relative
                # strength, not an evidence slot: it means the same thing on
                # every row of every setup, including CONFLUENCE. num() leaves
                # an unmeasurable ratio as an empty cell rather than writing a
                # neutral 1.0.
                #
                # Subscript, not `.get`: build_result_row sets the key on every
                # row it builds, so a row without it is a caller bug. `.get`
                # would write an empty cell for the whole file and read as "the
                # market has no volume data" instead of raising.
                "up_down_volume_ratio_50d": num(r["ud_ratio"], UD_PLACES),
                # The same block, in the order a reader works through it: the
                # two remaining raw ratios first, at the 50-day ratio's own two
                # places for the same reason, then the two labels derived from
                # them. Subscript throughout, for the reason above.
                "close_weighted_volume_ratio_50d": num(r["ud_weighted"],
                                                       UD_PLACES),
                "up_down_volume_ratio_20d": num(r["ud_20"], UD_PLACES),
                "volume_signal_reading": text(r["volume_signal"]),
                "accumulation_trend_reading": text(r["accumulation_trend"]),
                "all_setups_matched": "|".join(matched),
                "setups_matched_count": len(matched),
                "evidence_1_metric_name": e1_label,
                "evidence_1_metric_value": e1_value,
                "evidence_2_metric_name": e2_label,
                "evidence_2_metric_value": e2_value,
                "warning_flags": _flags(ev),
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
