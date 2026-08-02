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
import os

import setups

COLUMNS = ["scan_date", "last_closed_bar", "universe", "mode",
           "symbol", "sector",
           "setup", "rank", "setup_fit",
           "score_now", "score_at_trigger", "risk_reward", "vetoed", "action",
           "price", "trigger_price", "stop",
           "rs_1m", "rs_3m",
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
    "PULLBACK":   [("dist_to_ma_pct", "dist_to_ma_pct"),
                   ("rsi", "rsi")],
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
    `rank <= 15` reproduces the on-screen table exactly while the file keeps
    every match. --top governs terminal readability; it must not decide what a
    downstream tool is allowed to see.

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
        for rank, r in enumerate(by_setup.get(name) or [], 1):
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
                "scan_date": scan_date,
                "last_closed_bar": last_closed_bar,
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
