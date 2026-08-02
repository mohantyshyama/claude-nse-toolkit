"""CSV export: schema, row building, file semantics and the CLI that drives it.

The file is a machine-readable output, so the assertions are about the exact
bytes on disk -- column order, raw numbers, blank cells -- not about a dict that
happens to look right in memory.
"""
import csv as csvmod
import contextlib
import datetime as dt
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import csv_export
import screener
import setups


# Spelt out in full and asserted as a whole list, never as a set of "is this
# name in there" checks: two columns accidentally given the SAME verbose name,
# or one given a name that merely contains another's, is exactly the failure
# self-describing headers are supposed to prevent, and only an exact ordered
# comparison catches it.
EXPECTED_COLUMNS = [
    "scan_date", "last_closed_bar_date", "universe_name", "threshold_mode",
    "symbol", "sector",
    "setup_name", "rank_within_setup", "setup_fit_score_0_to_10",
    "score_now_catalyst_neutral_0_to_10", "score_if_trigger_fires_0_to_10",
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
    "warning_flags",
]

# The internal build_result_row key -> the FILE's header, for the columns whose
# names differ. Deliberately not used to GENERATE the assertions below -- a test
# that derived its expectation from this map would agree with any rename that
# went through the map, including a wrong one. It exists so a reader can see the
# two vocabularies side by side, and so the two-way pinning test can prove the
# file's names and the in-memory names really are separate sets.
INTERNAL_TO_COLUMN = {
    "last_closed_bar": "last_closed_bar_date",
    "universe": "universe_name",
    "mode": "threshold_mode",
    "setup": "setup_name",
    "rank": "rank_within_setup",
    "setup_fit": "setup_fit_score_0_to_10",
    "score_now": "score_now_catalyst_neutral_0_to_10",
    "score_at_trigger": "score_if_trigger_fires_0_to_10",
    "risk_reward": "risk_reward_ratio_vs_1p5_atr_stop",
    "vetoed": "risk_reward_veto_applied",
    "action": "action_bucket",
    "price": "last_price",
    "trigger_price": "trigger_price_that_repairs_setup",
    "stop": "stop_price_1p5_atr_below_last",
    "rs_1m": "relative_strength_1month_vs_nifty50_pct_points",
    "rs_3m": "relative_strength_3month_vs_nifty50_pct_points",
    "ud_ratio": "up_down_volume_ratio_50d",
    "ud_weighted": "close_weighted_volume_ratio_50d",
    "ud_20": "up_down_volume_ratio_20d",
    "volume_signal": "volume_signal_reading",
    "accumulation_trend": "accumulation_trend_reading",
    "setups_matched": "all_setups_matched",
    "match_count": "setups_matched_count",
    "evidence_1_label": "evidence_1_metric_name",
    "evidence_1_value": "evidence_1_metric_value",
    "evidence_2_label": "evidence_2_metric_name",
    "evidence_2_value": "evidence_2_metric_value",
    "flags": "warning_flags",
}

# Shorthands for the longest names, so the assertions below stay readable
# without any of them losing the exact string they are checking. Each is used
# where the OLD terse name used to appear, so the diff is a rename and nothing
# else.
C_SCORE_NOW = "score_now_catalyst_neutral_0_to_10"
C_SCORE_TRIG = "score_if_trigger_fires_0_to_10"
C_RR = "risk_reward_ratio_vs_1p5_atr_stop"
C_FIT = "setup_fit_score_0_to_10"
C_STOP = "stop_price_1p5_atr_below_last"
C_TRIGGER_PX = "trigger_price_that_repairs_setup"
C_RS_1M = "relative_strength_1month_vs_nifty50_pct_points"
C_RS_3M = "relative_strength_3month_vs_nifty50_pct_points"
C_UD_50 = "up_down_volume_ratio_50d"
C_UD_W = "close_weighted_volume_ratio_50d"
C_UD_20 = "up_down_volume_ratio_20d"

LEADER_EV = {"pct_from_high": 3.5, "rs_1m": 6.2, "rs_3m": 11.4,
             "full_stack": True}
COILED_EV = {"contraction": 0.61, "pos_in_base": 0.82}
BREAKOUT_EV = {"vol_mult": 2.4, "pct_above_base": 1.9, "base_bars": 40,
               "tightness": 5.0, "volume_light": False}

# The five volume fields. Every default differs from every other, and the two
# label vocabularies are disjoint, so a column reading a neighbouring field --
# ud_weighted written from ud_ratio, the two labels transposed -- shows up as a
# wrong value rather than passing on a fixture that repeats itself.
VOLUME_FIELDS = ("ud_ratio", "ud_weighted", "ud_20", "volume_signal",
                 "accumulation_trend")


def volume(ud_ratio=1.47, ud_weighted=0.63, ud_20=2.85,
           volume_signal="accumulation",
           accumulation_trend="strengthening"):
    """The five volume fields evaluate() puts at the top level of every matched
    entry, CONFLUENCE included -- the shape build_result_row reads."""
    return {"ud_ratio": ud_ratio, "ud_weighted": ud_weighted, "ud_20": ud_20,
            "volume_signal": volume_signal,
            "accumulation_trend": accumulation_trend}


def result(symbol="TCS", **over):
    """One row in build_result_row's shape -- what rank() sorts and the CSV
    consumes."""
    r = {"symbol": symbol, "sector": "Information Technology",
         "price": 200.0, "fit": 8.1, "evidence": dict(LEADER_EV),
         "total": 6.2, "trigger_total": 7.0, "trigger_price": 210.0,
         "stop": 185.0, "rr": 2.4, "rs_1m": 3.0, "rs_3m": 11.0,
         "vetoed": False, "action": "ALERT", "match_count": 1}
    r.update(volume(ud_ratio=1.472, ud_weighted=0.638, ud_20=2.854))
    r.update(over)
    return r


def scanned(symbol="TCS", matched=("LEADER",), sector="Information Technology"):
    """A scan() row, trimmed to what build_rows reads off it: the symbol and
    which setups it matched."""
    return {"symbol": symbol, "sector": sector,
            "matched": {n: {"fit": 8.0, "evidence": {}} for n in matched}}


def build(scan_rows, by_setup, chosen, scan_date="2026-08-02",
          last_closed_bar="2026-07-31", universe="nifty500", mode="loosened"):
    return csv_export.build_rows(scan_rows, by_setup, chosen, scan_date,
                                 last_closed_bar, universe, mode)


def read_back(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csvmod.DictReader(fh))


def raw_lines(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read().splitlines()


@contextlib.contextmanager
def tmpdir():
    d = tempfile.mkdtemp(prefix="csvexport")
    try:
        yield d
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


@contextlib.contextmanager
def chdir(path):
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


# --------------------------------------------------------------------- schema

class TestUpDownRatioColumn(unittest.TestCase):
    """The CSV half of the dedicated up/down volume column."""

    def test_the_value_is_written_for_every_setup_including_confluence(self):
        """A DIFFERENT ratio per setup row: one value repeated down the column
        would pass just as well if build_rows wrote a constant, or read the
        ratio off the first row and reused it for the rest."""
        rows = build([scanned(matched=("COILED", "LEADER"))],
                     {"COILED": [result(ud_ratio=1.11)],
                      "LEADER": [result(ud_ratio=2.22)],
                      "CONFLUENCE": [result(ud_ratio=3.33,
                                            evidence={"count": 2,
                                                      "label": "COILED+LEADER",
                                                      "mean_fit": 8.0,
                                                      "matched": ["COILED",
                                                                  "LEADER"]})]},
                     ["COILED", "LEADER", "CONFLUENCE"])
        self.assertEqual(len(rows), 3)
        self.assertEqual({r["setup_name"]: r[C_UD_50] for r in rows},
                         {"COILED": 1.11, "LEADER": 2.22, "CONFLUENCE": 3.33})

    def test_it_is_the_raw_ratio_not_a_formatted_string(self):
        """House rule for this file: raw sortable numbers, never `"1.47x"`."""
        r = build([scanned()], {"LEADER": [result()]}, ["LEADER"])[0]
        self.assertIsInstance(r[C_UD_50], float)

    def test_it_is_rounded_to_two_places_like_the_terminal_column(self):
        """Two places, not three: the ratio is built from 50 bars of volume and
        the third decimal is noise the input cannot support. It is also what the
        terminal prints, and the file and the screen must not show a reader two
        different numbers for one measurement. The asserts below fail on a
        four-place, a three-place and a whole-number rounding alike."""
        r = build([scanned()], {"LEADER": [result(ud_ratio=1.4728394)]},
                  ["LEADER"])[0]
        self.assertEqual(r[C_UD_50], 1.47)
        with tmpdir() as d:
            path = os.path.join(d, "s.csv")
            csv_export.write_csv(path, [r])
            self.assertEqual(read_back(path)[0][C_UD_50], "1.47")

    def test_a_row_without_the_key_raises_rather_than_writing_a_blank(self):
        """The sibling arm of the None case. None is a ratio that could not be
        formed and is a blank cell honestly; a MISSING key is a caller that
        never built the row build_result_row promises, and `.get` would blank
        the whole column instead -- indistinguishable, in the file, from a
        universe with no volume data."""
        r = result()
        del r["ud_ratio"]
        with self.assertRaises(KeyError):
            build([scanned()], {"LEADER": [r]}, ["LEADER"])

    def test_an_unmeasurable_ratio_is_an_empty_cell_not_a_neutral_one(self):
        """None means the stock had no down-closes. Writing 1.0 would state a
        measurement that was never made, and it would sort among real values."""
        rows = build([scanned()], {"LEADER": [result(ud_ratio=None)]}, ["LEADER"])
        self.assertEqual(rows[0][C_UD_50], "")
        with tmpdir() as d:
            path = os.path.join(d, "s.csv")
            csv_export.write_csv(path, rows)
            self.assertEqual(read_back(path)[0][C_UD_50], "")

    def test_a_measured_zero_is_written_as_zero_not_left_blank(self):
        """0.0 is a measured finding -- no up-volume at all -- and must be
        distinguishable from a missing one. `if v is None`, never `if not v`."""
        rows = build([scanned()], {"LEADER": [result(ud_ratio=0.0)]}, ["LEADER"])
        self.assertEqual(rows[0][C_UD_50], 0.0)
        with tmpdir() as d:
            path = os.path.join(d, "s.csv")
            csv_export.write_csv(path, rows)
            self.assertEqual(read_back(path)[0][C_UD_50], "0.0")


class TestVolumeColumns(unittest.TestCase):
    """The four columns that join ud_ratio: two more raw ratios and two labels.

    ud_ratio alone cannot separate a name being accumulated from one being
    distributed into strength -- both read above 1.0 -- so the file carries the
    close-weighted ratio, the 20-bar ratio, and the two labels derived from
    them, all as universal per-row columns rather than evidence slots.
    """

    # (build_result_row's key, the FILE's column). The pair is carried
    # explicitly rather than reusing one string for both, because they are no
    # longer the same word: `result(ud_20=...)` sets an in-memory field and
    # `row["up_down_volume_ratio_20d"]` reads the file's column, and a test that
    # used one name for both could not tell a row dict keyed on the internal
    # names from one keyed on the file's.
    NEW = (("ud_weighted", C_UD_W), ("ud_20", C_UD_20),
           ("volume_signal", "volume_signal_reading"),
           ("accumulation_trend", "accumulation_trend_reading"))
    RATIOS = (("ud_ratio", C_UD_50), ("ud_weighted", C_UD_W),
              ("ud_20", C_UD_20))
    LABELS = (("volume_signal", "volume_signal_reading"),
              ("accumulation_trend", "accumulation_trend_reading"))

    def one(self, **over):
        return build([scanned()], {"LEADER": [result(**over)]}, ["LEADER"])[0]

    def on_disk(self, **over):
        row = self.one(**over)
        with tmpdir() as d:
            path = os.path.join(d, "s.csv")
            csv_export.write_csv(path, [row])
            return read_back(path)[0]

    def test_every_new_field_reaches_its_own_column(self):
        """Five distinct values, five distinct columns. Any pair of them crossed
        -- ud_weighted from ud_ratio, ud_20 from ud_weighted, the two labels
        transposed -- lands a visibly wrong value rather than a plausible one."""
        row = self.one(ud_ratio=1.47, ud_weighted=0.63, ud_20=2.85,
                       volume_signal="distribution-into-strength",
                       accumulation_trend="fading")
        self.assertEqual(row[C_UD_50], 1.47)
        self.assertEqual(row[C_UD_W], 0.63)
        self.assertEqual(row[C_UD_20], 2.85)
        self.assertEqual(row["volume_signal_reading"],
                         "distribution-into-strength")
        self.assertEqual(row["accumulation_trend_reading"], "fading")

    def test_the_written_cells_match_the_written_header_positionally(self):
        """Read back by POSITION, not by name: DictReader keyed on the header
        would agree with itself even if the value order were wrong. This is the
        assertion a column emitted one slot late fails."""
        row = self.one(ud_ratio=1.47, ud_weighted=0.63, ud_20=2.85,
                       volume_signal="supported",
                       accumulation_trend="reversed")
        with tmpdir() as d:
            path = os.path.join(d, "s.csv")
            csv_export.write_csv(path, [row])
            header, values = [l.split(",") for l in raw_lines(path)]
        cells = dict(zip(header, values))
        self.assertEqual(header, csv_export.COLUMNS)
        self.assertEqual(cells[C_UD_50], "1.47")
        self.assertEqual(cells[C_UD_W], "0.63")
        self.assertEqual(cells[C_UD_20], "2.85")
        self.assertEqual(cells["volume_signal_reading"], "supported")
        self.assertEqual(cells["accumulation_trend_reading"], "reversed")

    def test_the_two_new_ratios_are_raw_numbers_not_formatted_strings(self):
        row = self.one()
        self.assertIsInstance(row[C_UD_W], float)
        self.assertIsInstance(row[C_UD_20], float)

    def test_the_two_new_ratios_are_rounded_to_two_places_like_ud_ratio(self):
        """The same convention, for the same reason: they are ratios built from
        20 or 50 bars of volume, and the third decimal is noise the input cannot
        support. The asserts fail on a three-place and a whole-number rounding
        alike."""
        row = self.one(ud_weighted=0.6349281, ud_20=2.8551749)
        self.assertEqual(row[C_UD_W], 0.63)
        self.assertEqual(row[C_UD_20], 2.86)
        disk = self.on_disk(ud_weighted=0.6349281, ud_20=2.8551749)
        self.assertEqual(disk[C_UD_W], "0.63")
        self.assertEqual(disk[C_UD_20], "2.86")

    def test_the_weighted_ratio_is_not_written_from_the_plain_one(self):
        """The pair a copy-paste most easily crosses, and the one case where
        crossing them inverts the finding: a plain ratio well above 1.0 beside a
        weighted ratio below it IS distribution into strength."""
        row = self.one(ud_ratio=1.90, ud_weighted=0.71)
        self.assertEqual(row[C_UD_50], 1.90)
        self.assertEqual(row[C_UD_W], 0.71)

    def test_the_twenty_bar_ratio_is_not_written_from_the_fifty_bar_one(self):
        row = self.one(ud_ratio=1.10, ud_20=2.40)
        self.assertEqual(row[C_UD_50], 1.10)
        self.assertEqual(row[C_UD_20], 2.40)

    def test_the_labels_are_written_verbatim_including_the_hyphens(self):
        """Nothing is title-cased, truncated or re-spelled on the way to the
        file: these are the same words the terminal key defines, so a reader can
        filter the file on the label the screen showed them."""
        for signal in ("accumulation", "distribution-into-strength",
                       "supported", "distribution", "unknown"):
            self.assertEqual(
                self.on_disk(volume_signal=signal)["volume_signal_reading"],
                signal)
        for trend in ("strengthening", "steady", "flattening", "fading",
                      "reversed", "unknown"):
            self.assertEqual(
                self.on_disk(
                    accumulation_trend=trend)["accumulation_trend_reading"],
                trend)

    def test_the_two_labels_are_not_transposed(self):
        """Disjoint vocabularies: no signal is ever `steady`, no trend is ever
        `supported`, so a swap cannot pass as a plausible row."""
        disk = self.on_disk(volume_signal="supported",
                            accumulation_trend="steady")
        self.assertEqual(disk["volume_signal_reading"], "supported")
        self.assertEqual(disk["accumulation_trend_reading"], "steady")

    def test_a_missing_value_is_an_empty_cell_and_never_the_word_none(self):
        """One field at a time, so no assertion is satisfied by a row that
        blanked the whole block. `str(None)` would write the four characters
        `None`, which sorts and filters as if it were a label of its own -- and
        for the ratios it would break every consumer that sums the column."""
        for field, column in self.RATIOS + self.LABELS:
            with self.subTest(field=field):
                row = self.one(**{field: None})
                self.assertEqual(row[column], "")
                disk = self.on_disk(**{field: None})
                self.assertEqual(disk[column], "")
                self.assertNotIn("None", list(disk.values()))
                for other_field, other_column in self.RATIOS + self.LABELS:
                    if other_field != field:
                        self.assertNotEqual(disk[other_column], "",
                                            other_column)

    def test_a_measured_zero_ratio_is_written_as_zero_not_left_blank(self):
        """0.0 on the weighted ratio is a name whose every up-bar closed at its
        low -- measured, not missing. `if v is None`, never `if not v`."""
        for field, column in (("ud_weighted", C_UD_W), ("ud_20", C_UD_20)):
            with self.subTest(field=field):
                self.assertEqual(self.one(**{field: 0.0})[column], 0.0)
                self.assertEqual(self.on_disk(**{field: 0.0})[column], "0.0")

    def test_an_empty_label_string_is_kept_rather_than_becoming_none(self):
        """The sibling arm of the None case: `""` is not None, so text() must
        leave it alone rather than routing it through the same branch."""
        self.assertEqual(self.one(volume_signal="")["volume_signal_reading"],
                         "")

    def test_a_row_missing_any_new_field_raises_rather_than_writing_a_blank(self):
        """The sibling arm of the None case. None is a value that could not be
        formed and is a blank cell honestly; a MISSING key is a caller that never
        built the row build_result_row promises, and `.get` would blank -- or,
        on a label, invent the real word `unknown` for -- the whole column."""
        for field, _column in self.NEW:
            with self.subTest(field=field):
                r = result()
                del r[field]
                with self.assertRaises(KeyError):
                    build([scanned()], {"LEADER": [r]}, ["LEADER"])

    def test_every_setup_including_confluence_carries_all_four(self):
        """A DIFFERENT value per setup row: one value repeated down a column
        would pass just as well if build_rows read the first row and reused it."""
        rows = build([scanned(matched=("COILED", "LEADER"))],
                     {"COILED": [result(ud_weighted=0.11, ud_20=1.11,
                                        volume_signal="accumulation",
                                        accumulation_trend="strengthening")],
                      "LEADER": [result(ud_weighted=0.22, ud_20=2.22,
                                        volume_signal="supported",
                                        accumulation_trend="fading")],
                      "CONFLUENCE": [result(ud_weighted=0.33, ud_20=3.33,
                                            volume_signal="distribution",
                                            accumulation_trend="reversed",
                                            evidence={"count": 2,
                                                      "label": "COILED+LEADER",
                                                      "mean_fit": 8.0,
                                                      "matched": ["COILED",
                                                                  "LEADER"]})]},
                     ["COILED", "LEADER", "CONFLUENCE"])
        by_setup = {r["setup_name"]: r for r in rows}
        self.assertEqual(sorted(by_setup), ["COILED", "CONFLUENCE", "LEADER"])
        self.assertEqual({k: v[C_UD_W] for k, v in by_setup.items()},
                         {"COILED": 0.11, "LEADER": 0.22, "CONFLUENCE": 0.33})
        self.assertEqual({k: v[C_UD_20] for k, v in by_setup.items()},
                         {"COILED": 1.11, "LEADER": 2.22, "CONFLUENCE": 3.33})
        self.assertEqual({k: v["volume_signal_reading"]
                          for k, v in by_setup.items()},
                         {"COILED": "accumulation", "LEADER": "supported",
                          "CONFLUENCE": "distribution"})
        self.assertEqual({k: v["accumulation_trend_reading"]
                          for k, v in by_setup.items()},
                         {"COILED": "strengthening", "LEADER": "fading",
                          "CONFLUENCE": "reversed"})


class TestSchema(unittest.TestCase):
    def test_columns_are_the_agreed_thirty_one_in_order(self):
        self.assertEqual(csv_export.COLUMNS, EXPECTED_COLUMNS)
        self.assertEqual(len(csv_export.COLUMNS), 31)

    def test_the_up_down_ratio_sits_beside_relative_strength(self):
        """A universal metric, not an evidence slot: it means the same thing on
        every row of every setup, so it lives with the two relative-strength
        columns and the risk:reward one rather than in the per-setup evidence
        pair."""
        cols = csv_export.COLUMNS
        self.assertEqual(cols[cols.index(C_RS_3M) + 1], C_UD_50)
        self.assertNotIn(C_UD_50, [k for pair in csv_export.EVIDENCE.values()
                                   for k, _ in pair])

    def test_the_four_new_volume_columns_follow_ud_ratio_in_order(self):
        """Asserted as a contiguous slice, not four `in COLUMNS` checks: order
        is the schema. A column emitted one position late shifts every value to
        its right in a file whose reader keys on position."""
        cols = csv_export.COLUMNS
        start = cols.index(C_UD_50)
        self.assertEqual(cols[start:start + 5],
                         [C_UD_50, C_UD_W, C_UD_20, "volume_signal_reading",
                          "accumulation_trend_reading"])
        self.assertEqual(cols[start + 5], "all_setups_matched")

    def test_the_new_volume_columns_are_not_evidence_slots(self):
        """Like the 50-day ratio: they mean the same thing on every row of every
        setup, including CONFLUENCE, whose two evidence slots are already spoken
        for."""
        evidence_keys = [k for pair in csv_export.EVIDENCE.values()
                         for k, _ in pair]
        for name in (C_UD_W, C_UD_20, "volume_signal_reading",
                     "accumulation_trend_reading"):
            self.assertNotIn(name, evidence_keys)

    def test_no_column_name_is_repeated(self):
        self.assertEqual(len(set(csv_export.COLUMNS)), len(csv_export.COLUMNS))


class TestSelfDescribingHeaders(unittest.TestCase):
    """The naming rule itself: a header states what the number is and in what
    unit, so the file is readable without the key beside it.

    These assertions exist because the rule is the point of the schema, not a
    formatting preference. A future column that reverts to `ud_5` or `rs_6m`
    has to fail something.
    """

    def test_no_terse_legacy_name_survives_anywhere_in_the_schema(self):
        """The exact names the rename replaced. Asserted as absent from the
        COLUMNS list AND from a built row's keys, so a rename applied to only
        one of the two is caught here rather than in a reader's spreadsheet."""
        row = build([scanned()], {"LEADER": [result()]}, ["LEADER"])[0]
        for old in INTERNAL_TO_COLUMN:
            with self.subTest(old=old):
                self.assertNotIn(old, csv_export.COLUMNS)
                self.assertNotIn(old, row)

    def test_the_renamed_columns_are_exactly_the_agreed_mapping(self):
        """Every internal key maps to the column the schema actually publishes,
        and the six unchanged names are unchanged. This is the assertion that a
        rename to a merely PLAUSIBLE new name fails."""
        unchanged = ["scan_date", "symbol", "sector"]
        self.assertEqual(sorted(csv_export.COLUMNS),
                         sorted(list(INTERNAL_TO_COLUMN.values()) + unchanged))
        for name in unchanged:
            self.assertIn(name, csv_export.COLUMNS)

    def test_a_built_rows_keys_are_the_file_names_not_the_internal_ones(self):
        """The two vocabularies are disjoint apart from the three names that
        were already self-describing. A row dict that leaked build_result_row's
        keys straight through would satisfy neither half of this."""
        row = build([scanned()], {"LEADER": [result()]}, ["LEADER"])[0]
        internal = result()
        shared = set(row) & set(internal)
        self.assertEqual(shared, {"symbol", "sector"})

    def test_every_header_is_a_valid_snake_case_identifier(self):
        """No spaces, no punctuation beyond `_`, never leading with a digit --
        so `pandas` attribute access and spreadsheet formulas both work. The
        verbosity is free at the keyboard only if this holds."""
        import keyword
        import re
        for name in csv_export.COLUMNS:
            with self.subTest(column=name):
                self.assertTrue(name.isidentifier(), name)
                self.assertFalse(keyword.iskeyword(name), name)
                self.assertRegex(name, r"^[a-z][a-z0-9_]*$", name)
                self.assertNotIn("__", name)
                self.assertFalse(name.endswith("_"), name)

    def test_no_header_is_a_substring_of_another(self):
        """The failure two overlapping verbose names would cause, pinned
        directly: a reader grepping for `up_down_volume_ratio_20d` must not also
        hit a longer column that contains it, and a substring-matching test
        elsewhere must not be able to confuse the two."""
        for a in csv_export.COLUMNS:
            for b in csv_export.COLUMNS:
                if a is not b:
                    self.assertNotIn(a, b, "%s inside %s" % (a, b))

    def test_every_measurement_column_carries_its_unit_or_scale(self):
        """The rule in the form a future column has to satisfy: the columns
        holding a NUMBER say what scale it is on. Bare identity columns --
        symbol, sector, the two dates, the setup name -- are self-describing
        already and are exempt by name, not by pattern, so a new numeric column
        cannot slip in by being short.
        """
        exempt = {"scan_date", "last_closed_bar_date", "universe_name",
                  "threshold_mode", "symbol", "sector", "setup_name",
                  "rank_within_setup", "action_bucket",
                  "risk_reward_veto_applied",
                  "volume_signal_reading", "accumulation_trend_reading",
                  "all_setups_matched", "setups_matched_count",
                  "evidence_1_metric_name", "evidence_1_metric_value",
                  "evidence_2_metric_name", "evidence_2_metric_value",
                  "warning_flags"}
        units = ("_0_to_10", "_pct_points", "_ratio_", "ratio_50d",
                 "ratio_20d", "price", "_atr_")
        for name in csv_export.COLUMNS:
            if name in exempt:
                continue
            with self.subTest(column=name):
                self.assertTrue(any(u in name for u in units),
                                "%s states no unit or scale" % name)

    def test_the_module_records_the_rule_for_the_next_column(self):
        """The rule lives in csv_export's own docstring, where someone adding a
        column reads it, not only in SKILL.md."""
        doc = csv_export.__doc__
        self.assertIn("WITHOUT THE", doc.upper())
        self.assertIn("READER CONSULTING THE KEY", doc.upper())
        self.assertIn("UNIT", doc.upper())

    def test_a_built_row_carries_exactly_the_schema_keys(self):
        rows = build([scanned()], {"LEADER": [result()]}, ["LEADER"])
        self.assertEqual(sorted(rows[0]), sorted(csv_export.COLUMNS))

    def test_the_written_header_is_the_column_order(self):
        with tmpdir() as d:
            path = os.path.join(d, "out.csv")
            csv_export.write_csv(path, build([scanned()],
                                             {"LEADER": [result()]}, ["LEADER"]))
            self.assertEqual(raw_lines(path)[0], ",".join(EXPECTED_COLUMNS))

    def test_every_setup_the_screener_can_emit_has_an_evidence_entry(self):
        """A seventh setup added to setups.SETUPS must not KeyError the export."""
        self.assertEqual(sorted(csv_export.EVIDENCE),
                         sorted(list(setups.SETUPS) + ["CONFLUENCE"]))

    def test_evidence_pairs_are_two_per_setup_except_confluence(self):
        for name, pairs in csv_export.EVIDENCE.items():
            self.assertEqual(len(pairs), 0 if name == "CONFLUENCE" else 2, name)


# ------------------------------------------------------------------- num()

class TestNum(unittest.TestCase):
    def test_none_becomes_an_empty_string_not_the_word_none(self):
        self.assertEqual(csv_export.num(None), "")

    def test_nan_becomes_an_empty_string_too(self):
        self.assertEqual(csv_export.num(float("nan")), "")

    def test_true_becomes_one_and_is_no_longer_a_bool(self):
        got = csv_export.num(True)
        self.assertEqual(got, 1)
        self.assertNotIsInstance(got, bool)

    def test_false_becomes_zero_rather_than_being_dropped(self):
        got = csv_export.num(False)
        self.assertEqual(got, 0)
        self.assertNotIsInstance(got, bool)

    def test_an_int_passes_through_untouched(self):
        self.assertEqual(csv_export.num(1234567), 1234567)

    def test_a_float_rounds_to_the_places_asked_for(self):
        self.assertEqual(csv_export.num(0.98172, 3), 0.982)
        self.assertEqual(csv_export.num(0.98172, 2), 0.98)
        self.assertEqual(csv_export.num(0.98172, 1), 1.0)

    def test_the_default_rounding_is_two_places(self):
        self.assertEqual(csv_export.num(6.2149), 6.21)

    def test_a_numeric_string_is_still_rounded_not_passed_through(self):
        self.assertEqual(csv_export.num("6.2149"), 6.21)

    def test_zero_survives_as_zero_rather_than_reading_as_missing(self):
        self.assertEqual(csv_export.num(0.0), 0.0)
        self.assertNotEqual(csv_export.num(0.0), "")


class TestLabels(unittest.TestCase):
    def test_universe_label_drops_the_directory_and_the_extension(self):
        self.assertEqual(csv_export.universe_label("/a/b/nifty500.txt"),
                         "nifty500")

    def test_universe_label_leaves_a_bare_name_alone(self):
        self.assertEqual(csv_export.universe_label("nifty500"), "nifty500")

    def test_mode_label_has_both_arms(self):
        self.assertEqual(csv_export.mode_label(True), "strict")
        self.assertEqual(csv_export.mode_label(False), "loosened")

    def test_mode_label_matches_the_words_the_header_prints(self):
        """The file and the terminal must not disagree about the thresholds."""
        for strict in (True, False):
            header = screener.render_header("2026-08-02", "2026-07-31", "u.txt",
                                            10, strict, 10, [], 0, {})
            self.assertIn(csv_export.mode_label(strict), header.split("\n")[0])


# ---------------------------------------------------------------- build_rows

class TestBuildRows(unittest.TestCase):
    def test_scan_metadata_is_stamped_on_every_row(self):
        rows = build([scanned()], {"LEADER": [result()]}, ["LEADER"],
                     scan_date="2026-08-02", last_closed_bar="2026-07-31",
                     universe="nifty500", mode="strict")
        self.assertEqual(rows[0]["scan_date"], "02-Aug-2026")
        self.assertEqual(rows[0]["last_closed_bar_date"], "31-Jul-2026")
        self.assertEqual(rows[0]["universe_name"], "nifty500")
        self.assertEqual(rows[0]["threshold_mode"], "strict")


class TestDateCells(unittest.TestCase):
    """Dates in the file are `02-Aug-2026`, not `2026-08-02`.

    Excel converts an ISO date to its internal serial on import and renders the
    cell as a bare number -- 46236 -- so the column the user opens has no date
    in it at all.
    """

    def test_an_iso_string_becomes_day_month_year(self):
        self.assertEqual(csv_export.date_cell("2026-08-02"), "02-Aug-2026")

    def test_the_day_is_zero_padded_and_the_month_is_alphabetic(self):
        """`2-8-2026` would be ambiguous and `02-08-2026` reads as 8 February
        in half the world. The month has to be letters."""
        got = csv_export.date_cell("2026-02-08")
        self.assertEqual(got, "08-Feb-2026")
        self.assertNotIn("02", got.split("-")[1])

    def test_a_date_object_is_formatted_too(self):
        """screener passes o["last_closed_bar"]["t"], which analyze.fetch may
        hand back as a datetime.date rather than a string."""
        self.assertEqual(csv_export.date_cell(dt.date(2026, 8, 2)),
                         "02-Aug-2026")
        self.assertEqual(csv_export.date_cell(dt.datetime(2026, 8, 2, 15, 30)),
                         "02-Aug-2026")

    def test_a_timestamped_iso_string_keeps_only_the_date(self):
        self.assertEqual(csv_export.date_cell("2026-08-02 15:30:00"),
                         "02-Aug-2026")

    def test_a_non_date_is_passed_through_rather_than_blanked(self):
        """`n/a` is what main() stamps when a scan produced no rows at all.
        Blanking it would turn "we could not tell" into "there was none"."""
        self.assertEqual(csv_export.date_cell("n/a"), "n/a")

    def test_empty_and_missing_stay_empty(self):
        self.assertEqual(csv_export.date_cell(None), "")
        self.assertEqual(csv_export.date_cell(""), "")

    def test_every_month_round_trips(self):
        """Twelve months, so no single-month fixture can hide a format that
        only works for August."""
        for m in range(1, 13):
            d = dt.date(2026, m, 15)
            self.assertEqual(csv_export.date_cell(d.isoformat()),
                             d.strftime("%d-%b-%Y"), str(m))

    def test_the_column_no_longer_parses_as_an_iso_date(self):
        """The failure mode itself: a cell Excel would turn into a serial."""
        with self.assertRaises(ValueError):
            dt.datetime.strptime(csv_export.date_cell("2026-08-02"),
                                 "%Y-%m-%d")

    def test_the_default_filename_stays_iso_so_a_directory_sorts_by_date(self):
        """The deliberate split. `scans/scan_02-Aug-2026.csv` would sort next
        to `scan_02-Sep-2025.csv`, which is the whole reason the filename is
        not given the same treatment as the columns."""
        path = csv_export.default_path("2026-08-02")
        self.assertIn("scan_2026-08-02.csv", path)
        self.assertNotIn("Aug", path)
        names = sorted(csv_export.default_path(d) for d in
                       ("2026-08-02", "2025-09-02", "2026-01-15"))
        self.assertEqual([os.path.basename(n) for n in names],
                         ["scan_2025-09-02.csv", "scan_2026-01-15.csv",
                          "scan_2026-08-02.csv"])

    def test_the_file_and_the_filename_disagree_on_purpose(self):
        """Pinned together so neither can be "fixed" into the other by someone
        who sees only one of them."""
        rows = build([scanned()], {"LEADER": [result()]}, ["LEADER"],
                     scan_date="2026-08-02")
        self.assertEqual(rows[0]["scan_date"], "02-Aug-2026")
        self.assertIn("2026-08-02",
                      csv_export.resolve_path(csv_export.DEFAULT_PATH,
                                              "2026-08-02"))

    def test_the_formatted_date_survives_into_the_file_unquoted(self):
        with tmpdir() as d:
            path = os.path.join(d, "out.csv")
            csv_export.write_csv(path, build([scanned()],
                                             {"LEADER": [result()]}, ["LEADER"],
                                             scan_date="2026-08-02",
                                             last_closed_bar="2026-07-31"))
            body = raw_lines(path)[1]
            self.assertTrue(body.startswith("02-Aug-2026,31-Jul-2026,"), body)
            back = read_back(path)[0]
            self.assertEqual(back["scan_date"], "02-Aug-2026")
            self.assertEqual(back["last_closed_bar_date"], "31-Jul-2026")

    def test_one_row_per_symbol_setup_pair(self):
        scan_rows = [scanned("TCS", ("COILED", "LEADER"))]
        by_setup = {"COILED": [result("TCS", evidence=dict(COILED_EV))],
                    "LEADER": [result("TCS")],
                    "CONFLUENCE": [result("TCS", evidence={"matched": ["COILED", "LEADER"],
                                                           "count": 2,
                                                           "label": "COILED+LEADER",
                                                           "mean_fit": 8.0})]}
        rows = build(scan_rows, by_setup, ["COILED", "LEADER", "CONFLUENCE"])
        self.assertEqual([r["setup_name"] for r in rows],
                         ["COILED", "LEADER", "CONFLUENCE"])
        self.assertEqual({r["symbol"] for r in rows}, {"TCS"})

    def test_setups_matched_is_identical_on_every_row_of_that_symbol(self):
        scan_rows = [scanned("TCS", ("COILED", "LEADER"))]
        by_setup = {"COILED": [result("TCS", evidence=dict(COILED_EV))],
                    "LEADER": [result("TCS")]}
        rows = build(scan_rows, by_setup, ["COILED", "LEADER"])
        for r in rows:
            self.assertEqual(r["all_setups_matched"], "COILED|LEADER")
            self.assertEqual(r["setups_matched_count"], 2)

    def test_setups_matched_reports_setups_this_export_did_not_ask_for(self):
        """--setup coiled still says the name is also a LEADER: the question is
        about the stock, not about the slice being exported."""
        rows = build([scanned("TCS", ("COILED", "LEADER"))],
                     {"COILED": [result("TCS", evidence=dict(COILED_EV))]},
                     ["COILED"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["all_setups_matched"], "COILED|LEADER")
        self.assertEqual(rows[0]["setups_matched_count"], 2)

    def test_setups_matched_is_life_cycle_ordered_not_alphabetical(self):
        rows = build([scanned("TCS", ("TURN", "COILED", "BREAKOUT"))],
                     {"LEADER": [result("TCS")]}, ["LEADER"])
        self.assertEqual(rows[0]["all_setups_matched"], "COILED|BREAKOUT|TURN")

    def test_confluence_is_not_counted_as_a_matched_setup(self):
        scan_rows = [scanned("TCS", ("COILED", "LEADER"))]
        scan_rows[0]["matched"]["CONFLUENCE"] = {"fit": 8.0, "evidence": {}}
        rows = build(scan_rows, {"LEADER": [result("TCS")]}, ["LEADER"])
        self.assertEqual(rows[0]["all_setups_matched"], "COILED|LEADER")
        self.assertEqual(rows[0]["setups_matched_count"], 2)

    def test_a_single_setup_name_still_gets_the_pair_of_columns(self):
        rows = build([scanned("TCS", ("LEADER",))],
                     {"LEADER": [result("TCS")]}, ["LEADER"])
        self.assertEqual(rows[0]["all_setups_matched"], "LEADER")
        self.assertEqual(rows[0]["setups_matched_count"], 1)

    def test_a_row_whose_symbol_never_scanned_degrades_instead_of_crashing(self):
        rows = build([scanned("TCS")], {"LEADER": [result("GHOST")]}, ["LEADER"])
        self.assertEqual(rows[0]["all_setups_matched"], "")
        self.assertEqual(rows[0]["setups_matched_count"], 0)

    def test_rank_is_one_based_and_follows_the_given_order(self):
        by_setup = {"LEADER": [result("A"), result("B"), result("C")]}
        rows = build([scanned("A"), scanned("B"), scanned("C")],
                     by_setup, ["LEADER"])
        self.assertEqual([(r["symbol"], r["rank_within_setup"]) for r in rows],
                         [("A", 1), ("B", 2), ("C", 3)])

    def test_rank_restarts_at_one_for_each_setup(self):
        by_setup = {"COILED": [result("A", evidence=dict(COILED_EV)),
                               result("B", evidence=dict(COILED_EV))],
                    "LEADER": [result("C")]}
        rows = build([scanned("A"), scanned("B"), scanned("C")],
                     by_setup, ["COILED", "LEADER"])
        self.assertEqual([(r["setup_name"], r["rank_within_setup"])
                          for r in rows],
                         [("COILED", 1), ("COILED", 2), ("LEADER", 1)])

    def test_setups_are_emitted_in_the_chosen_order(self):
        by_setup = {"COILED": [result("A", evidence=dict(COILED_EV))],
                    "LEADER": [result("B")]}
        rows = build([scanned("A"), scanned("B")], by_setup,
                     ["LEADER", "COILED"])
        self.assertEqual([r["setup_name"] for r in rows], ["LEADER", "COILED"])

    def test_a_chosen_setup_with_no_matches_contributes_no_rows(self):
        rows = build([scanned("A")], {"LEADER": [result("A")], "TURN": []},
                     ["LEADER", "TURN"])
        self.assertEqual([r["setup_name"] for r in rows], ["LEADER"])

    def test_the_cap_is_enforced_where_the_rows_are_built(self):
        """Not only through main(): any caller of build_rows gets the cap, so a
        second export path cannot reintroduce an uncapped file."""
        syms = ["S%02d" % i for i in range(30)]
        rows = build([scanned(s) for s in syms],
                     {"LEADER": [result(s) for s in syms]}, ["LEADER"])
        self.assertEqual(len(rows), csv_export.MAX_ROWS_PER_SETUP)
        self.assertEqual([r["symbol"] for r in rows],
                         syms[:csv_export.MAX_ROWS_PER_SETUP])
        self.assertEqual([r["rank_within_setup"] for r in rows],
                         list(range(1, csv_export.MAX_ROWS_PER_SETUP + 1)))

    def test_a_setup_at_exactly_the_cap_keeps_every_row(self):
        """The `<=` edge of the slice: 20 in, 20 out, nothing dropped."""
        syms = ["S%02d" % i for i in range(csv_export.MAX_ROWS_PER_SETUP)]
        rows = build([scanned(s) for s in syms],
                     {"LEADER": [result(s) for s in syms]}, ["LEADER"])
        self.assertEqual([r["symbol"] for r in rows], syms)

    def test_a_chosen_setup_absent_from_the_map_contributes_no_rows(self):
        rows = build([scanned("A")], {"LEADER": [result("A")]},
                     ["LEADER", "PULLBACK"])
        self.assertEqual([r["setup_name"] for r in rows], ["LEADER"])


class TestEvidenceColumns(unittest.TestCase):
    def _row(self, setup, evidence, symbol="TCS"):
        return build([scanned(symbol, (setup,) if setup != "CONFLUENCE"
                              else ("COILED", "LEADER"))],
                     {setup: [result(symbol, evidence=evidence)]}, [setup])[0]

    def test_coiled_emits_contraction_and_position_in_base(self):
        r = self._row("COILED", {"contraction": 0.61, "pos_in_base": 0.98172})
        self.assertEqual(r["evidence_1_metric_name"], "contraction")
        self.assertEqual(r["evidence_1_metric_value"], 0.61)
        self.assertEqual(r["evidence_2_metric_name"], "pos_in_base")
        self.assertEqual(r["evidence_2_metric_value"], 0.982)

    def test_position_in_base_stays_a_fraction_rather_than_a_percent_string(self):
        r = self._row("COILED", {"contraction": 0.61, "pos_in_base": 0.982})
        self.assertNotIsInstance(r["evidence_2_metric_value"], str)
        self.assertLess(r["evidence_2_metric_value"], 1.0)

    def test_breakout_emits_volume_multiple_and_extension_as_bare_numbers(self):
        r = self._row("BREAKOUT", {"vol_mult": 4.1064, "pct_above_base": 6.2171,
                                   "volume_light": False})
        self.assertEqual((r["evidence_1_metric_name"], r["evidence_1_metric_value"]),
                         ("vol_mult", 4.106))
        self.assertEqual((r["evidence_2_metric_name"], r["evidence_2_metric_value"]),
                         ("pct_above_base", 6.217))

    def test_leader_emits_stack_completeness_not_a_second_copy_of_rs_1m(self):
        """rs_1m already has a column; two columns claiming the same number at
        two roundings is the bug this replaces. full_stack is a real input to
        fit_leader and appears nowhere else in the row."""
        r = self._row("LEADER", {"pct_from_high": 3.4567, "rs_1m": 6.2178,
                                 "full_stack": True})
        self.assertEqual((r["evidence_1_metric_name"], r["evidence_1_metric_value"]),
                         ("pct_from_high", 3.457))
        self.assertEqual(r["evidence_2_metric_name"], "ma_stack_full")
        self.assertEqual(r["evidence_2_metric_value"], 1)
        self.assertNotIn("rs_1m", (r["evidence_1_metric_name"], r["evidence_2_metric_name"]))

    def test_an_incomplete_stack_is_zero_rather_than_blank(self):
        r = self._row("LEADER", {"pct_from_high": 3.4, "full_stack": False})
        self.assertEqual(r["evidence_2_metric_value"], 0)

    def test_leader_evidence_keys_exist_on_the_real_predicates_output(self):
        """Pins the export to match_leader's actual evidence dict, so renaming
        full_stack there cannot silently blank a column here."""
        import inspect
        src = inspect.getsource(setups.match_leader)
        self.assertIn('"full_stack"', src)
        self.assertIn('"pct_from_high"', src)

    def test_pullback_emits_the_reversal_bar_and_the_swing_retracement(self):
        """The pair that carries the signal since the reversal gate landed.

        Distance to an average and RSI both sat inside the entry gate already
        and neither could separate a stock that turned at support from one still
        falling into it.
        """
        r = self._row("PULLBACK", {"dist_to_ma_pct": 1.23456, "rsi": 52.9579,
                                   "close_position": 0.73578,
                                   "retrace_pct": 17.0567,
                                   "retrace_of_52w_range_pct": 33.0})
        self.assertEqual((r["evidence_1_metric_name"], r["evidence_1_metric_value"]),
                         ("close_position", 0.736))
        self.assertEqual((r["evidence_2_metric_name"], r["evidence_2_metric_value"]),
                         ("retrace_pct", 17.057))

    def test_pullback_close_position_stays_a_fraction_in_the_file(self):
        """The terminal prints 74%; the file keeps 0.736, like pos_in_base."""
        r = self._row("PULLBACK", {"close_position": 0.73578,
                                   "retrace_pct": 17.0567})
        self.assertNotIsInstance(r["evidence_1_metric_value"], str)
        self.assertLess(r["evidence_1_metric_value"], 1.0)

    def test_pullback_publishes_the_swing_retracement_not_the_range_share(self):
        """The two are different numbers on different scales and the file must
        carry the one the gate uses. 17.06% under a swing high and 33% of the
        52-week range are both true of the same name."""
        r = self._row("PULLBACK", {"close_position": 0.74,
                                   "retrace_pct": 17.0567,
                                   "retrace_of_52w_range_pct": 33.0})
        self.assertEqual(r["evidence_2_metric_value"], 17.057)

    def test_pullback_evidence_keys_exist_on_the_real_predicates_output(self):
        """Pins the export to match_pullback's actual evidence dict, so renaming
        a key there cannot silently blank a column here."""
        import inspect
        src = inspect.getsource(setups.match_pullback)
        self.assertIn('"close_position"', src)
        self.assertIn('"retrace_pct"', src)

    def test_turn_emits_bars_since_cross_and_the_macd_histogram(self):
        r = self._row("TURN", {"bars_since_cross": 12, "macd_hist": 1.23456})
        self.assertEqual((r["evidence_1_metric_name"], r["evidence_1_metric_value"]),
                         ("bars_since_cross", 12))
        self.assertEqual((r["evidence_2_metric_name"], r["evidence_2_metric_value"]),
                         ("macd_hist", 1.235))

    def test_confluence_leaves_both_evidence_pairs_blank(self):
        """Its evidence is setups_matched plus setup_fit, already in the row."""
        r = self._row("CONFLUENCE", {"matched": ["COILED", "LEADER"],
                                     "count": 2, "label": "COILED+LEADER",
                                     "mean_fit": 8.0})
        self.assertEqual(r["evidence_1_metric_name"], "")
        self.assertEqual(r["evidence_1_metric_value"], "")
        self.assertEqual(r["evidence_2_metric_name"], "")
        self.assertEqual(r["evidence_2_metric_value"], "")
        self.assertEqual(r["all_setups_matched"], "COILED|LEADER")

    def test_a_missing_evidence_key_blanks_the_value_but_keeps_the_label(self):
        r = self._row("COILED", {"contraction": 0.61})
        self.assertEqual(r["evidence_2_metric_name"], "pos_in_base")
        self.assertEqual(r["evidence_2_metric_value"], "")


class TestFlags(unittest.TestCase):
    def _flags(self, evidence, setup="BREAKOUT"):
        return build([scanned("TCS", (setup,))],
                     {setup: [result("TCS", evidence=evidence)]},
                     [setup])[0]["warning_flags"]

    def test_a_light_volume_breakout_carries_the_flag(self):
        self.assertEqual(self._flags({"vol_mult": 1.7, "pct_above_base": 2.0,
                                      "volume_light": True}),
                         "volume_light")

    def test_a_confirmed_breakout_carries_no_flag(self):
        self.assertEqual(self._flags({"vol_mult": 2.6, "pct_above_base": 2.0,
                                      "volume_light": False}),
                         "")

    def test_a_setup_that_never_measures_volume_carries_no_flag(self):
        self.assertEqual(self._flags(dict(LEADER_EV), setup="LEADER"), "")

    def test_the_flag_survives_all_the_way_into_the_file(self):
        with tmpdir() as d:
            path = os.path.join(d, "out.csv")
            csv_export.write_csv(path, build(
                [scanned("TCS", ("BREAKOUT",))],
                {"BREAKOUT": [result("TCS", evidence={"vol_mult": 1.7,
                                                      "pct_above_base": 2.0,
                                                      "volume_light": True})]},
                ["BREAKOUT"]))
            self.assertEqual(read_back(path)[0]["warning_flags"], "volume_light")

    def test_the_flag_matches_the_threshold_stock_analyser_defines(self):
        """1.5-2.0x is the near-miss band; 2x is a confirmed trigger."""
        self.assertEqual(setups.CONFIRMED_VOL_MULT, 2.0)


class TestValueTypes(unittest.TestCase):
    def test_scores_round_to_two_places_and_relative_strength_to_one(self):
        rows = build([scanned()],
                     {"LEADER": [result(fit=8.1251, total=6.2149,
                                        trigger_total=7.1749, rr=2.4449,
                                        rs_1m=6.2178, rs_3m=-3.26)]},
                     ["LEADER"])
        r = rows[0]
        self.assertEqual(r[C_FIT], 8.13)
        self.assertEqual(r[C_SCORE_NOW], 6.21)
        self.assertEqual(r[C_SCORE_TRIG], 7.17)
        self.assertEqual(r[C_RR], 2.44)
        self.assertEqual(r[C_RS_1M], 6.2)
        self.assertEqual(r[C_RS_3M], -3.3)

    def test_prices_round_to_two_places(self):
        rows = build([scanned()],
                     {"LEADER": [result(price=1234.5678, trigger_price=1240.1234,
                                        stop=1180.9876)]}, ["LEADER"])
        self.assertEqual(rows[0]["last_price"], 1234.57)
        self.assertEqual(rows[0][C_TRIGGER_PX], 1240.12)
        self.assertEqual(rows[0][C_STOP], 1180.99)

    def test_none_values_become_empty_strings_across_the_row(self):
        rows = build([scanned()],
                     {"LEADER": [result(trigger_total=None, trigger_price=None,
                                        stop=None, rr=None, rs_1m=None,
                                        rs_3m=None)]}, ["LEADER"])
        for col in (C_SCORE_TRIG, C_TRIGGER_PX, C_STOP, C_RR,
                    C_RS_1M, C_RS_3M):
            self.assertEqual(rows[0][col], "", col)

    def test_none_never_reaches_the_file_as_the_word_none(self):
        with tmpdir() as d:
            path = os.path.join(d, "out.csv")
            csv_export.write_csv(path, build(
                [scanned()], {"LEADER": [result(trigger_total=None, stop=None,
                                                rr=None, rs_1m=None)]},
                ["LEADER"]))
            body = raw_lines(path)[1]
            self.assertNotIn("None", body)
            self.assertNotIn("nan", body)

    def test_vetoed_is_one_or_zero_not_a_boolean_word(self):
        clean = build([scanned()], {"LEADER": [result(vetoed=False)]},
                      ["LEADER"])[0]
        veto = build([scanned()], {"LEADER": [result(vetoed=True)]},
                     ["LEADER"])[0]
        self.assertEqual(clean["risk_reward_veto_applied"], 0)
        self.assertEqual(veto["risk_reward_veto_applied"], 1)
        self.assertNotIsInstance(veto["risk_reward_veto_applied"], bool)

    def test_the_action_word_is_carried_through_verbatim(self):
        rows = build([scanned()], {"LEADER": [result(action="BUY HALF")]},
                     ["LEADER"])
        self.assertEqual(rows[0]["action_bucket"], "BUY HALF")

    def test_no_numeric_cell_in_the_file_carries_a_unit_symbol(self):
        with tmpdir() as d:
            path = os.path.join(d, "out.csv")
            csv_export.write_csv(path, build(
                [scanned("TCS", ("BREAKOUT",))],
                {"BREAKOUT": [result("TCS", evidence=dict(BREAKOUT_EV))]},
                ["BREAKOUT"]))
            row = read_back(path)[0]
            for col in (C_FIT, C_SCORE_NOW, C_RR, "last_price",
                        C_RS_1M, C_RS_3M, "evidence_1_metric_value",
                        "evidence_2_metric_value"):
                self.assertNotIn("%", row[col], col)
                self.assertNotIn("x", row[col], col)
                float(row[col])          # sortable without any stripping


# ------------------------------------------------------------------ write_csv

class TestWriteCsv(unittest.TestCase):
    def _rows(self, *symbols):
        return build([scanned(s) for s in symbols],
                     {"LEADER": [result(s) for s in symbols]}, ["LEADER"])

    def test_it_returns_the_number_of_data_rows_written(self):
        with tmpdir() as d:
            n = csv_export.write_csv(os.path.join(d, "out.csv"),
                                     self._rows("A", "B"))
            self.assertEqual(n, 2)

    def test_a_missing_parent_directory_is_created(self):
        with tmpdir() as d:
            path = os.path.join(d, "scans", "out.csv")
            csv_export.write_csv(path, self._rows("A"))
            self.assertTrue(os.path.exists(path))

    def test_a_bare_filename_with_no_directory_part_still_writes(self):
        with tmpdir() as d, chdir(d):
            csv_export.write_csv("out.csv", self._rows("A"))
            self.assertTrue(os.path.exists(os.path.join(d, "out.csv")))

    def test_overwrite_replaces_the_previous_scan_entirely(self):
        with tmpdir() as d:
            path = os.path.join(d, "out.csv")
            csv_export.write_csv(path, self._rows("A", "B"))
            csv_export.write_csv(path, self._rows("C"))
            rows = read_back(path)
            self.assertEqual([r["symbol"] for r in rows], ["C"])
            self.assertEqual(sum(1 for l in raw_lines(path)
                                 if l.startswith("scan_date,")), 1)

    def test_append_to_a_new_file_writes_the_header(self):
        with tmpdir() as d:
            path = os.path.join(d, "out.csv")
            csv_export.write_csv(path, self._rows("A"), append=True)
            self.assertEqual(raw_lines(path)[0], ",".join(EXPECTED_COLUMNS))

    def test_append_to_an_existing_but_empty_file_writes_the_header(self):
        with tmpdir() as d:
            path = os.path.join(d, "out.csv")
            open(path, "w").close()
            csv_export.write_csv(path, self._rows("A"), append=True)
            self.assertEqual(raw_lines(path)[0], ",".join(EXPECTED_COLUMNS))

    def test_append_to_a_populated_file_does_not_repeat_the_header(self):
        with tmpdir() as d:
            path = os.path.join(d, "out.csv")
            csv_export.write_csv(path, self._rows("A", "B"))
            csv_export.write_csv(path, self._rows("C"), append=True)
            lines = raw_lines(path)
            self.assertEqual(sum(1 for l in lines
                                 if l.startswith("scan_date,")), 1)
            self.assertEqual([r["symbol"] for r in read_back(path)],
                             ["A", "B", "C"])

    def test_appending_twice_still_leaves_exactly_one_header(self):
        with tmpdir() as d:
            path = os.path.join(d, "out.csv")
            csv_export.write_csv(path, self._rows("A"), append=True)
            csv_export.write_csv(path, self._rows("B"), append=True)
            csv_export.write_csv(path, self._rows("C"), append=True)
            self.assertEqual(sum(1 for l in raw_lines(path)
                                 if l.startswith("scan_date,")), 1)
            self.assertEqual(len(read_back(path)), 3)

    def test_appending_zero_rows_to_a_new_file_still_writes_the_header(self):
        with tmpdir() as d:
            path = os.path.join(d, "out.csv")
            self.assertEqual(csv_export.write_csv(path, [], append=True), 0)
            self.assertEqual(raw_lines(path), [",".join(EXPECTED_COLUMNS)])

    def test_a_sector_containing_a_comma_is_quoted_not_split(self):
        rows = build([scanned("TCS")],
                     {"LEADER": [result("TCS", sector="Oil, Gas & Fuels")]},
                     ["LEADER"])
        with tmpdir() as d:
            path = os.path.join(d, "out.csv")
            csv_export.write_csv(path, rows)
            back = read_back(path)
            self.assertEqual(len(back), 1)
            self.assertEqual(back[0]["sector"], "Oil, Gas & Fuels")


class TestResolvePath(unittest.TestCase):
    def test_the_bare_flag_resolves_to_the_dated_default(self):
        self.assertEqual(
            csv_export.resolve_path(csv_export.DEFAULT_PATH, "2026-08-02",
                                    base="."),
            os.path.join(".", "scans", "scan_2026-08-02.csv"))

    def test_the_default_path_is_dated_by_the_scan_not_by_a_constant(self):
        a = csv_export.default_path("2026-08-02")
        b = csv_export.default_path("2026-08-03")
        self.assertNotEqual(a, b)
        self.assertIn("2026-08-03", b)

    def test_an_explicit_path_is_returned_exactly(self):
        self.assertEqual(csv_export.resolve_path("/tmp/x/y.csv", "2026-08-02"),
                         "/tmp/x/y.csv")

    def test_a_path_that_merely_looks_like_the_sentinel_is_still_a_path(self):
        """The sentinel is an object, so no filename can collide with it."""
        for text in ("__default__", "<default csv path>", "DEFAULT_PATH"):
            self.assertEqual(csv_export.resolve_path(text, "2026-08-02"), text)

    def test_the_default_lands_under_a_scans_directory(self):
        self.assertEqual(csv_export.DEFAULT_DIR, "scans")
        self.assertIn(os.sep + "scans" + os.sep,
                      csv_export.default_path("2026-08-02"))


# -------------------------------------------------------------- per-setup split

class TestPerSetupPath(unittest.TestCase):
    """The naming: the setup goes BEFORE the extension."""

    def test_the_setup_lands_before_the_extension(self):
        self.assertEqual(
            csv_export.per_setup_path("scans/scan_2026-08-02.csv", "COILED"),
            "scans/scan_2026-08-02_COILED.csv")

    def test_the_result_is_still_a_csv_to_a_glob_or_a_spreadsheet(self):
        """`scan.csv_COILED` opens in nothing and matches `*.csv` in nothing.
        This is the assertion a naive `base + "_" + setup` fails."""
        got = csv_export.per_setup_path("scans/scan_2026-08-02.csv", "BREAKOUT")
        self.assertTrue(got.endswith(".csv"), got)
        self.assertNotIn(".csv_", got)

    def test_the_directory_is_preserved_not_flattened(self):
        got = csv_export.per_setup_path("/a/b/out.csv", "TURN")
        self.assertEqual(os.path.dirname(got), "/a/b")

    def test_a_dot_in_the_directory_name_is_not_mistaken_for_an_extension(self):
        """`os.path.splitext` is directory-aware; a hand-rolled `rfind('.')`
        would split `/a.b/out` in the wrong place."""
        self.assertEqual(csv_export.per_setup_path("/a.b/out.csv", "LEADER"),
                         "/a.b/out_LEADER.csv")

    def test_a_base_with_no_extension_gains_none(self):
        """The user named the file they wanted; inventing `.csv` for the
        siblings would be the surprise."""
        self.assertEqual(csv_export.per_setup_path("out", "COILED"),
                         "out_COILED")

    def test_a_non_csv_extension_is_carried_through_verbatim(self):
        self.assertEqual(csv_export.per_setup_path("out.txt", "COILED"),
                         "out_COILED.txt")

    def test_every_setup_gets_a_distinct_path(self):
        """Six setups, six filenames. Two colliding would silently overwrite."""
        names = list(setups.SETUPS) + ["CONFLUENCE"]
        paths = [csv_export.per_setup_path("scans/s.csv", n) for n in names]
        self.assertEqual(len(set(paths)), len(names))

    def test_the_setup_name_is_upper_case_as_the_column_writes_it(self):
        """So the filename and the setup_name column read the same, and a
        case-sensitive filesystem does not end up with two files per setup."""
        self.assertIn("_COILED.csv",
                      csv_export.per_setup_path("s.csv", "COILED"))


class TestGroupBySetup(unittest.TestCase):
    def _rows(self):
        return build([scanned("A", ("COILED", "LEADER")),
                      scanned("B", ("COILED", "LEADER"))],
                     {"COILED": [result("A", evidence=dict(COILED_EV)),
                                 result("B", evidence=dict(COILED_EV))],
                      "LEADER": [result("A")]},
                     ["COILED", "LEADER"])

    def test_rows_are_grouped_under_their_own_setup(self):
        groups = csv_export.group_by_setup(self._rows())
        self.assertEqual([name for name, _ in groups], ["COILED", "LEADER"])
        self.assertEqual([len(g) for _, g in groups], [2, 1])

    def test_each_group_holds_only_that_setups_rows(self):
        """The assertion a grouping that handed every group the whole list
        fails. Asserted on the setup_name column of every row, not on counts."""
        for name, group in csv_export.group_by_setup(self._rows()):
            self.assertEqual({r["setup_name"] for r in group}, {name})

    def test_a_setup_with_no_rows_gets_no_group_at_all(self):
        """Not an empty one. This is where "no matches writes no file" comes
        from: it falls out of the data, not out of a branch."""
        rows = build([scanned("A")], {"LEADER": [result("A")], "TURN": []},
                     ["LEADER", "TURN"])
        groups = csv_export.group_by_setup(rows)
        self.assertEqual([name for name, _ in groups], ["LEADER"])
        self.assertNotIn("TURN", [name for name, _ in groups])

    def test_no_row_is_lost_or_duplicated_by_the_split(self):
        rows = self._rows()
        regrouped = [r for _, g in csv_export.group_by_setup(rows) for r in g]
        self.assertEqual(len(regrouped), len(rows))
        self.assertEqual(sorted(map(id, regrouped)), sorted(map(id, rows)))

    def test_the_group_order_follows_the_combined_files_order(self):
        """Reversed input, reversed groups: the listing reads down in the same
        order as the file it was split from."""
        rows = build([scanned("A", ("COILED", "LEADER"))],
                     {"COILED": [result("A", evidence=dict(COILED_EV))],
                      "LEADER": [result("A")]},
                     ["LEADER", "COILED"])
        self.assertEqual([n for n, _ in csv_export.group_by_setup(rows)],
                         ["LEADER", "COILED"])

    def test_an_empty_scan_groups_into_nothing(self):
        self.assertEqual(csv_export.group_by_setup([]), [])


class TestWritePerSetup(unittest.TestCase):
    def _rows(self):
        """Two COILED, one LEADER, nothing else -- so a file written with ALL
        the rows, or one written for a setup that matched nothing, is visible."""
        return build([scanned("A", ("COILED", "LEADER")),
                      scanned("B", ("COILED",))],
                     {"COILED": [result("A", evidence=dict(COILED_EV)),
                                 result("B", evidence=dict(COILED_EV))],
                      "LEADER": [result("A")],
                      "TURN": []},
                     ["COILED", "LEADER", "TURN"])

    def test_one_file_per_matched_setup_with_its_row_count(self):
        with tmpdir() as d:
            base = os.path.join(d, "scan_2026-08-02.csv")
            got = csv_export.write_per_setup(base, self._rows())
            self.assertEqual(got, [
                (os.path.join(d, "scan_2026-08-02_COILED.csv"), 2),
                (os.path.join(d, "scan_2026-08-02_LEADER.csv"), 1)])

    def test_each_file_holds_only_its_own_setups_rows(self):
        """The mutant this kills writes every row into every file: the counts
        would still be positive and every file would still parse."""
        with tmpdir() as d:
            base = os.path.join(d, "s.csv")
            csv_export.write_per_setup(base, self._rows())
            coiled = read_back(os.path.join(d, "s_COILED.csv"))
            leader = read_back(os.path.join(d, "s_LEADER.csv"))
            self.assertEqual([r["setup_name"] for r in coiled],
                             ["COILED", "COILED"])
            self.assertEqual([r["symbol"] for r in coiled], ["A", "B"])
            self.assertEqual([r["setup_name"] for r in leader], ["LEADER"])
            self.assertEqual([r["symbol"] for r in leader], ["A"])

    def test_a_setup_with_no_matches_writes_no_file_at_all(self):
        """Not a header-only one. An empty file in the directory reads as "the
        scan produced nothing" when it means "this setup matched nothing"."""
        with tmpdir() as d:
            base = os.path.join(d, "s.csv")
            csv_export.write_per_setup(base, self._rows())
            self.assertFalse(os.path.exists(os.path.join(d, "s_TURN.csv")))
            self.assertEqual(sorted(os.listdir(d)),
                             ["s_COILED.csv", "s_LEADER.csv"])

    def test_a_scan_that_matched_nothing_writes_no_per_setup_files(self):
        with tmpdir() as d:
            base = os.path.join(d, "s.csv")
            self.assertEqual(csv_export.write_per_setup(base, []), [])
            self.assertEqual(os.listdir(d), [])

    def test_the_combined_file_is_not_written_by_this_function(self):
        """It is the caller's, written before this runs. Writing it here too
        would double the row count reported for the scan."""
        with tmpdir() as d:
            base = os.path.join(d, "s.csv")
            csv_export.write_per_setup(base, self._rows())
            self.assertFalse(os.path.exists(base))

    def test_every_file_carries_the_full_thirty_one_column_header(self):
        """A slice of the columns would make the per-setup files a different
        schema from the combined one, and no reader could union them."""
        with tmpdir() as d:
            base = os.path.join(d, "s.csv")
            for path, _ in csv_export.write_per_setup(base, self._rows()):
                with open(path, newline="", encoding="utf-8") as fh:
                    self.assertEqual(csvmod.DictReader(fh).fieldnames,
                                     EXPECTED_COLUMNS, path)

    def test_the_rows_are_byte_identical_to_the_combined_files_own(self):
        """Same rows, same rounding, same order -- a split, not a re-render."""
        rows = self._rows()
        with tmpdir() as d:
            base = os.path.join(d, "s.csv")
            csv_export.write_csv(base, rows)
            csv_export.write_per_setup(base, rows)
            combined = raw_lines(base)
            for path, _ in csv_export.write_per_setup(base, rows):
                body = raw_lines(path)[1:]
                for line in body:
                    self.assertIn(line, combined[1:], path)

    def test_ranks_inside_a_per_setup_file_stay_the_scans_own(self):
        """Not renumbered 1..n by the split: the file has to reproduce the
        terminal table, and a re-rank would quietly invent a new ordering."""
        syms = ["S%02d" % i for i in range(3)]
        rows = build([scanned(s) for s in syms],
                     {"LEADER": [result(s) for s in syms]}, ["LEADER"])
        with tmpdir() as d:
            base = os.path.join(d, "s.csv")
            csv_export.write_per_setup(base, rows)
            back = read_back(os.path.join(d, "s_LEADER.csv"))
            self.assertEqual([r["rank_within_setup"] for r in back],
                             ["1", "2", "3"])

    def test_a_missing_parent_directory_is_created_for_the_siblings_too(self):
        with tmpdir() as d:
            base = os.path.join(d, "nested", "s.csv")
            csv_export.write_per_setup(base, self._rows())
            self.assertTrue(os.path.exists(os.path.join(d, "nested",
                                                        "s_COILED.csv")))

    def test_overwriting_replaces_a_stale_per_setup_file(self):
        with tmpdir() as d:
            base = os.path.join(d, "s.csv")
            csv_export.write_per_setup(base, self._rows())
            later = build([scanned("Z", ("COILED",))],
                          {"COILED": [result("Z", evidence=dict(COILED_EV))]},
                          ["COILED"])
            csv_export.write_per_setup(base, later)
            self.assertEqual(
                [r["symbol"] for r in read_back(os.path.join(d, "s_COILED.csv"))],
                ["Z"])

    def test_append_reaches_the_per_setup_files_as_well(self):
        """One flag governs the run: a --append scan must not leave the
        combined file growing while its siblings are truncated."""
        with tmpdir() as d:
            base = os.path.join(d, "s.csv")
            csv_export.write_per_setup(base, self._rows(), append=True)
            later = build([scanned("Z", ("COILED",))],
                          {"COILED": [result("Z", evidence=dict(COILED_EV))]},
                          ["COILED"])
            csv_export.write_per_setup(base, later, append=True)
            path = os.path.join(d, "s_COILED.csv")
            self.assertEqual([r["symbol"] for r in read_back(path)],
                             ["A", "B", "Z"])
            self.assertEqual(sum(1 for l in raw_lines(path)
                                 if l.startswith("scan_date,")), 1)

    def test_the_returned_counts_are_the_rows_really_on_disk(self):
        """Counted off the files, not off the return value that claims them."""
        with tmpdir() as d:
            base = os.path.join(d, "s.csv")
            for path, n in csv_export.write_per_setup(base, self._rows()):
                self.assertEqual(len(read_back(path)), n, path)


# ------------------------------------------------------------------------ CLI

class TestCsvArgs(unittest.TestCase):
    def test_no_csv_flag_means_no_file(self):
        self.assertIsNone(screener.parse_args([]).csv)

    def test_a_bare_csv_flag_yields_the_sentinel(self):
        self.assertIs(screener.parse_args(["--csv"]).csv,
                      csv_export.DEFAULT_PATH)

    def test_csv_with_a_path_yields_that_path(self):
        self.assertEqual(screener.parse_args(["--csv", "/tmp/o.csv"]).csv,
                         "/tmp/o.csv")

    def test_a_bare_csv_flag_does_not_swallow_the_next_flag(self):
        a = screener.parse_args(["--csv", "--strict"])
        self.assertIs(a.csv, csv_export.DEFAULT_PATH)
        self.assertTrue(a.strict)

    def test_append_defaults_off_and_is_a_flag(self):
        self.assertFalse(screener.parse_args([]).append)
        self.assertTrue(screener.parse_args(["--append"]).append)

    def test_csv_composes_with_every_other_scan_flag(self):
        a = screener.parse_args(["--csv", "out.csv", "--append", "--setup",
                                 "coiled,leader", "--sector", "Banks",
                                 "--strict", "--min-turnover", "8.5",
                                 "--top", "3", "--json"])
        self.assertEqual(a.csv, "out.csv")
        self.assertTrue(a.append)
        self.assertTrue(a.strict)
        self.assertTrue(a.json)
        self.assertEqual(a.setup, "coiled,leader")
        self.assertEqual(a.sector, "Banks")
        self.assertAlmostEqual(a.min_turnover, 8.5)
        self.assertEqual(a.top, 3)

    def test_the_help_text_names_the_default_location(self):
        buf = io.StringIO()
        with redirect_stdout(buf), self.assertRaises(SystemExit):
            screener.parse_args(["--help"])
        self.assertIn("--csv", buf.getvalue())
        self.assertIn("scans", buf.getvalue())


class TestCsvPerSetupArgs(unittest.TestCase):
    def _err(self, argv):
        buf = io.StringIO()
        with redirect_stderr(buf), self.assertRaises(SystemExit) as cm:
            screener.parse_args(argv)
        return cm.exception.code, buf.getvalue()

    def test_it_defaults_off(self):
        self.assertFalse(screener.parse_args([]).csv_per_setup)

    def test_it_is_a_flag_that_takes_no_value(self):
        a = screener.parse_args(["--csv", "o.csv", "--csv-per-setup"])
        self.assertTrue(a.csv_per_setup)
        self.assertEqual(a.csv, "o.csv")

    def test_it_composes_with_a_bare_csv_flag(self):
        a = screener.parse_args(["--csv", "--csv-per-setup"])
        self.assertIs(a.csv, csv_export.DEFAULT_PATH)
        self.assertTrue(a.csv_per_setup)

    def test_it_composes_with_append_and_the_scan_flags(self):
        a = screener.parse_args(["--csv", "o.csv", "--csv-per-setup",
                                 "--append", "--strict", "--setup", "coiled"])
        self.assertTrue(a.csv_per_setup)
        self.assertTrue(a.append)
        self.assertTrue(a.strict)
        self.assertEqual(a.setup, "coiled")

    def test_without_csv_it_is_a_usage_error_not_a_silent_no_op(self):
        """The whole point: a user who mistyped the pair must not get exit 0
        and a directory with none of the files they asked for."""
        code, err = self._err(["--csv-per-setup"])
        self.assertNotEqual(code, 0)
        self.assertIn("--csv-per-setup", err)
        self.assertIn("--csv", err)

    def test_the_error_says_why_rather_than_only_that_it_failed(self):
        _, err = self._err(["--csv-per-setup"])
        self.assertIn("requires --csv", err)

    def test_the_usage_error_survives_the_other_flags_being_present(self):
        """It is the ABSENCE of --csv that is the error, not some interaction
        with a bare argv. --strict and --append do not repair it."""
        for extra in (["--strict"], ["--append"], ["--json"],
                      ["--setup", "coiled"]):
            with self.subTest(extra=extra):
                code, err = self._err(["--csv-per-setup"] + extra)
                self.assertNotEqual(code, 0)
                self.assertIn("requires --csv", err)

    def test_csv_alone_is_still_perfectly_legal(self):
        """The other arm of the guard: --csv without --csv-per-setup is the
        ordinary case and must not have become an error."""
        a = screener.parse_args(["--csv", "o.csv"])
        self.assertEqual(a.csv, "o.csv")
        self.assertFalse(a.csv_per_setup)

    def test_neither_flag_is_legal_too(self):
        a = screener.parse_args([])
        self.assertIsNone(a.csv)
        self.assertFalse(a.csv_per_setup)

    def test_the_help_text_names_the_flag_and_its_dependency(self):
        buf = io.StringIO()
        with redirect_stdout(buf), self.assertRaises(SystemExit):
            screener.parse_args(["--help"])
        self.assertIn("--csv-per-setup", buf.getvalue())


# ------------------------------------------------------- main(), offline rig

def scan_row(symbol, sector="Information Technology", total=6.2,
             verdict="HALF SIZE", matched=None, rs=(3.0, 11.0), price=200.0,
             rr=2.4, atr=10.0):
    """A scan() row complete enough for build_result_row and the renderers.

    Every matched entry carries the five volume fields at the top level beside
    `fit` and `evidence` -- setups.evaluate's contract, and the keys
    build_result_row reads. A caller passing its own `matched` has to carry them
    too."""
    if matched is None:
        matched = {"LEADER": dict({"fit": 8.0, "evidence": dict(LEADER_EV)},
                                  **volume())}
    return {"symbol": symbol, "sector": sector, "illiquid": False, "diag": {},
            "rs": {"1m": rs[0], "3m": rs[1]}, "matched": matched,
            "o": {"price": price, "score": {"total": total, "verdict": verdict},
                  "entry_gate": {"rr_at_current_price": rr},
                  "atr": {"daily": atr},
                  "last_closed_bar": {"t": "2026-07-31"}}}


@contextlib.contextmanager
def stub_scan(rows, pairs=None):
    """Runs main() end to end without the network: universe, scan and the
    trigger projection are replaced; ranking, rendering and the export are the
    real ones."""
    saved = (screener.load_universe, screener.scan, screener.W.score_at_trigger)
    screener.load_universe = lambda path, sectors=None: (
        pairs if pairs is not None else [(r["symbol"], r["sector"]) for r in rows])
    screener.scan = lambda *a, **k: (rows, [])
    screener.W.score_at_trigger = lambda o: None
    try:
        yield
    finally:
        (screener.load_universe, screener.scan,
         screener.W.score_at_trigger) = saved


def run_main(argv, rows):
    out, err = io.StringIO(), io.StringIO()
    with stub_scan(rows), redirect_stdout(out), redirect_stderr(err):
        rc = screener.main(argv)
    return rc, out.getvalue(), err.getvalue()


class TestMainCsv(unittest.TestCase):
    def _rows(self, n=4):
        return [scan_row("SYM%d" % i, total=9.0 - i) for i in range(n)]

    def test_no_csv_flag_writes_no_file(self):
        with tmpdir() as d, chdir(d):
            rc, _, err = run_main(["--setup", "leader"], self._rows(2))
            self.assertEqual(rc, 0)
            self.assertFalse(os.path.exists("scans"))
            self.assertNotIn("wrote", err)

    def test_a_bare_csv_flag_writes_the_dated_default_under_scans(self):
        import datetime as dt
        with tmpdir() as d, chdir(d):
            rc, _, err = run_main(["--setup", "leader", "--csv"], self._rows(2))
            self.assertEqual(rc, 0)
            path = os.path.join(".", "scans",
                                "scan_%s.csv" % dt.date.today().isoformat())
            self.assertTrue(os.path.exists(path), err)
            self.assertEqual(len(read_back(path)), 2)

    def test_csv_with_a_path_writes_exactly_there(self):
        with tmpdir() as d:
            path = os.path.join(d, "sub", "mine.csv")
            rc, _, err = run_main(["--setup", "leader", "--csv", path],
                                  self._rows(2))
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(path))
            self.assertFalse(os.path.exists(os.path.join(d, "scans")))
            self.assertIn(path, err)

    def test_top_governs_the_terminal_and_the_file_has_its_own_cap(self):
        """Two independent limits, and this pins that they are independent.

        This test used to assert that the file was never truncated at all. That
        is no longer the contract: --top still governs the terminal alone, and
        the file is capped at MAX_ROWS_PER_SETUP whatever --top says. With four
        matches, --top 2 shows two on screen and the file -- well under its own
        cap -- still holds all four.
        """
        with tmpdir() as d:
            path = os.path.join(d, "o.csv")
            rc, out, _ = run_main(["--setup", "leader", "--top", "2",
                                   "--csv", path], self._rows(4))
            self.assertEqual(rc, 0)
            self.assertIn("showing top 2 of 4", out)
            rows = read_back(path)
            self.assertEqual(len(rows), 4)
            self.assertEqual([r["rank_within_setup"] for r in rows], ["1", "2", "3", "4"])

    def test_the_file_keeps_twenty_rows_per_setup_and_no_more(self):
        """31 matches, and the file holds the top 20 with contiguous ranks."""
        with tmpdir() as d:
            path = os.path.join(d, "o.csv")
            rc, _, err = run_main(["--setup", "leader", "--top", "5",
                                   "--csv", path], self._rows(31))
            self.assertEqual(rc, 0)
            rows = read_back(path)
            self.assertEqual(len(rows), 20)
            self.assertEqual([int(r["rank_within_setup"]) for r in rows],
                             list(range(1, 21)))
            self.assertIn("wrote 20 rows", err)

    def test_the_rows_kept_are_the_TOP_of_the_ranking(self):
        """A cap that dropped the wrong twenty would still count to twenty.
        _rows(n) scores SYM0 highest and descends, so the survivors are named."""
        with tmpdir() as d:
            path = os.path.join(d, "o.csv")
            run_main(["--setup", "leader", "--csv", path], self._rows(25))
            self.assertEqual([r["symbol"] for r in read_back(path)],
                             ["SYM%d" % i for i in range(20)])

    def test_a_high_top_does_not_lift_the_file_cap(self):
        """--top clamps at 20 itself, so this also pins that the two limits are
        not secretly the same number arriving by a different route: --top 20
        with 31 matches still writes 20, and would write 20 at --top 1 too."""
        for top in ("1", "20"):
            with tmpdir() as d:
                path = os.path.join(d, "o.csv")
                run_main(["--setup", "leader", "--top", top, "--csv", path],
                         self._rows(31))
                self.assertEqual(len(read_back(path)), 20, "--top %s" % top)

    def test_the_cap_is_applied_per_setup_not_to_the_whole_file(self):
        """Two setups over the cap write 40 rows, not 20."""
        rows = [scan_row("SYM%d" % i, total=9.0 - i * 0.1, matched={
            # A different ratio per symbol, the same on both of that symbol's
            # setups: it is a property of the name, not of the match.
            "LEADER": dict({"fit": 8.0, "evidence": dict(LEADER_EV)},
                           **volume(ud_ratio=1.0 + i / 100.0)),
            "COILED": dict({"fit": 7.0, "evidence": dict(COILED_EV)},
                           **volume(ud_ratio=1.0 + i / 100.0))})
            for i in range(25)]
        with tmpdir() as d:
            path = os.path.join(d, "o.csv")
            run_main(["--setup", "leader,coiled", "--csv", path], rows)
            back = read_back(path)
            self.assertEqual(len(back), 40)
            for name in ("COILED", "LEADER"):
                self.assertEqual(
                    [int(r["rank_within_setup"]) for r in back
                     if r["setup_name"] == name],
                    list(range(1, 21)), name)

    def test_a_full_scan_writes_at_most_a_hundred_and_twenty_rows(self):
        """Six setups at twenty each. The arithmetic, taken off the code."""
        self.assertEqual(csv_export.MAX_ROWS_PER_SETUP, 20)
        self.assertEqual(len(csv_export.EVIDENCE)
                         * csv_export.MAX_ROWS_PER_SETUP, 120)

    def test_rank_reproduces_the_terminal_order_exactly(self):
        with tmpdir() as d:
            path = os.path.join(d, "o.csv")
            _, out, _ = run_main(["--setup", "leader", "--top", "2",
                                  "--csv", path], self._rows(4))
            shown = [l.split("|")[2].strip() for l in out.split("\n")
                     if l.startswith("| ") and "SYM" in l]
            rows = read_back(path)
            self.assertEqual(shown, ["SYM0", "SYM1"])
            self.assertEqual([r["symbol"] for r in rows
                              if int(r["rank_within_setup"]) <= 2], shown)
            self.assertEqual([r["symbol"] for r in rows],
                             ["SYM0", "SYM1", "SYM2", "SYM3"])

    def test_setup_filter_reaches_the_file(self):
        rows = [scan_row("A", matched={
            "LEADER": dict({"fit": 8.0, "evidence": dict(LEADER_EV)},
                           **volume()),
            "COILED": dict({"fit": 7.0, "evidence": dict(COILED_EV)},
                           **volume())})]
        with tmpdir() as d:
            path = os.path.join(d, "o.csv")
            run_main(["--setup", "coiled", "--csv", path], rows)
            back = read_back(path)
            self.assertEqual([r["setup_name"] for r in back], ["COILED"])
            self.assertEqual(back[0]["all_setups_matched"], "COILED|LEADER")

    def test_strict_is_recorded_in_the_mode_column(self):
        with tmpdir() as d:
            path = os.path.join(d, "o.csv")
            run_main(["--setup", "leader", "--strict", "--csv", path],
                     self._rows(1))
            self.assertEqual(read_back(path)[0]["threshold_mode"], "strict")

    def test_a_loosened_scan_says_so_in_the_mode_column(self):
        with tmpdir() as d:
            path = os.path.join(d, "o.csv")
            run_main(["--setup", "leader", "--csv", path], self._rows(1))
            self.assertEqual(read_back(path)[0]["threshold_mode"], "loosened")

    def test_the_universe_column_is_the_universe_not_the_filename(self):
        with tmpdir() as d:
            path = os.path.join(d, "o.csv")
            run_main(["--setup", "leader", "--universe", "/x/y/nifty500.txt",
                      "--csv", path], self._rows(1))
            self.assertEqual(read_back(path)[0]["universe_name"], "nifty500")

    def test_csv_and_json_are_independent_and_compose(self):
        import json
        with tmpdir() as d:
            path = os.path.join(d, "o.csv")
            rc, out, _ = run_main(["--setup", "leader", "--json", "--csv", path],
                                  self._rows(2))
            self.assertEqual(rc, 0)
            payload = json.loads(out)          # stdout stays parseable
            self.assertIn("LEADER", payload["setups"])
            self.assertEqual(len(read_back(path)), 2)

    def test_the_notice_goes_to_stderr_with_the_row_count(self):
        with tmpdir() as d:
            path = os.path.join(d, "o.csv")
            _, out, err = run_main(["--setup", "leader", "--json",
                                    "--csv", path], self._rows(3))
            self.assertIn("wrote 3 rows", err)
            self.assertNotIn("wrote 3 rows", out)

    def test_append_across_two_runs_keeps_one_header_and_both_scans(self):
        with tmpdir() as d:
            path = os.path.join(d, "o.csv")
            run_main(["--setup", "leader", "--csv", path, "--append"],
                     self._rows(2))
            run_main(["--setup", "leader", "--csv", path, "--append"],
                     [scan_row("LATER")])
            lines = raw_lines(path)
            self.assertEqual(sum(1 for l in lines
                                 if l.startswith("scan_date,")), 1)
            self.assertEqual([r["symbol"] for r in read_back(path)],
                             ["SYM0", "SYM1", "LATER"])

    def test_without_append_the_second_run_replaces_the_first(self):
        with tmpdir() as d:
            path = os.path.join(d, "o.csv")
            run_main(["--setup", "leader", "--csv", path], self._rows(2))
            run_main(["--setup", "leader", "--csv", path], [scan_row("LATER")])
            self.assertEqual([r["symbol"] for r in read_back(path)], ["LATER"])

    def test_an_empty_screen_still_writes_a_headed_file(self):
        """A scan that matched nothing is a finding, and the file has to say so
        in a shape a reader can still parse."""
        rows = [scan_row("A", matched={})]
        with tmpdir() as d:
            path = os.path.join(d, "o.csv")
            rc, _, _ = run_main(["--setup", "leader", "--csv", path], rows)
            self.assertEqual(rc, 0)
            self.assertEqual(raw_lines(path), [",".join(EXPECTED_COLUMNS)])

    def test_confluence_rows_reach_the_file_with_blank_evidence(self):
        rows = [scan_row("A", matched={
            "LEADER": dict({"fit": 8.0, "evidence": dict(LEADER_EV)},
                           **volume()),
            "COILED": dict({"fit": 7.0, "evidence": dict(COILED_EV)},
                           **volume()),
            # CONFLUENCE carries the same top-level keys as its constituents,
            # which is the whole reason they do not live in the evidence: this
            # entry's two evidence slots are the matched label and the mean fit,
            # and there is no third one to put five more fields in.
            "CONFLUENCE": dict({"fit": 7.5,
                                "evidence": {"matched": ["COILED", "LEADER"],
                                             "count": 2,
                                             "label": "COILED+LEADER",
                                             "mean_fit": 7.5}},
                               **volume())})]
        with tmpdir() as d:
            path = os.path.join(d, "o.csv")
            run_main(["--setup", "all", "--csv", path], rows)
            back = {r["setup_name"]: r for r in read_back(path)}
            self.assertEqual(sorted(back), ["COILED", "CONFLUENCE", "LEADER"])
            conf = back["CONFLUENCE"]
            self.assertEqual(conf["evidence_1_metric_name"], "")
            self.assertEqual(conf["evidence_2_metric_value"], "")
            self.assertEqual(conf["all_setups_matched"], "COILED|LEADER")
            self.assertEqual(conf["setups_matched_count"], "2")
            self.assertEqual(back["LEADER"]["all_setups_matched"], "COILED|LEADER")

    def test_the_file_carries_the_scans_own_last_closed_bar(self):
        """...and prints it as a date a spreadsheet will not turn into 46234."""
        with tmpdir() as d:
            path = os.path.join(d, "o.csv")
            run_main(["--setup", "leader", "--csv", path], self._rows(1))
            self.assertEqual(read_back(path)[0]["last_closed_bar_date"], "31-Jul-2026")

    def test_the_scan_date_column_is_formatted_while_the_filename_is_not(self):
        """End to end through main(): the bare --csv flag names the file with
        today's ISO date and stamps the column with today's DD-MMM-YYYY."""
        import datetime as _dt
        today = _dt.date.today()
        with tmpdir() as d, chdir(d):
            run_main(["--setup", "leader", "--csv"], self._rows(1))
            path = os.path.join(".", "scans",
                                "scan_%s.csv" % today.isoformat())
            self.assertTrue(os.path.exists(path))
            self.assertEqual(read_back(path)[0]["scan_date"],
                             today.strftime("%d-%b-%Y"))


class TestMainCsvPerSetup(unittest.TestCase):
    """--csv --csv-per-setup end to end through main()."""

    def _two_setups(self, n=3):
        """n names matching LEADER, the first two also COILED -- so the two
        files must differ in length as well as in content."""
        out = []
        for i in range(n):
            matched = {"LEADER": dict({"fit": 8.0,
                                       "evidence": dict(LEADER_EV)},
                                      **volume())}
            if i < 2:
                matched["COILED"] = dict({"fit": 7.0,
                                          "evidence": dict(COILED_EV)},
                                         **volume())
            out.append(scan_row("SYM%d" % i, total=9.0 - i, matched=matched))
        return out

    def test_the_combined_file_is_still_written_alongside_the_split(self):
        """Additional, not a replacement. A split that consumed the combined
        file would leave a reader who wants the whole scan with nothing."""
        with tmpdir() as d:
            base = os.path.join(d, "scan.csv")
            rc, _, err = run_main(["--setup", "leader,coiled", "--csv", base,
                                   "--csv-per-setup"], self._two_setups())
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(base), err)
            self.assertEqual(len(read_back(base)), 5)

    def test_one_file_per_matched_setup_lands_beside_it(self):
        with tmpdir() as d:
            base = os.path.join(d, "scan.csv")
            run_main(["--setup", "leader,coiled", "--csv", base,
                      "--csv-per-setup"], self._two_setups())
            self.assertEqual(sorted(os.listdir(d)),
                             ["scan.csv", "scan_COILED.csv",
                              "scan_LEADER.csv"])

    def test_each_file_carries_only_its_own_setups_rows(self):
        """The mutant this kills writes the whole scan into every file: both
        files would exist, both would parse, both would be non-empty."""
        with tmpdir() as d:
            base = os.path.join(d, "scan.csv")
            run_main(["--setup", "leader,coiled", "--csv", base,
                      "--csv-per-setup"], self._two_setups())
            leader = read_back(os.path.join(d, "scan_LEADER.csv"))
            coiled = read_back(os.path.join(d, "scan_COILED.csv"))
            self.assertEqual({r["setup_name"] for r in leader}, {"LEADER"})
            self.assertEqual({r["setup_name"] for r in coiled}, {"COILED"})
            self.assertEqual(len(leader), 3)
            self.assertEqual(len(coiled), 2)

    def test_the_two_files_reunion_is_exactly_the_combined_file(self):
        """Nothing dropped, nothing duplicated, nothing re-rendered."""
        with tmpdir() as d:
            base = os.path.join(d, "scan.csv")
            run_main(["--setup", "leader,coiled", "--csv", base,
                      "--csv-per-setup"], self._two_setups())
            parts = []
            for name in ("COILED", "LEADER"):
                parts += raw_lines(os.path.join(d, "scan_%s.csv" % name))[1:]
            self.assertEqual(sorted(parts), sorted(raw_lines(base)[1:]))

    def test_a_setup_that_matched_nothing_gets_no_file(self):
        """--setup all over a scan where only LEADER and COILED matched: four
        setups produced nothing and four files must be absent, not empty."""
        with tmpdir() as d:
            base = os.path.join(d, "scan.csv")
            run_main(["--setup", "all", "--csv", base, "--csv-per-setup"],
                     self._two_setups())
            written = set(os.listdir(d))
            self.assertIn("scan_LEADER.csv", written)
            self.assertIn("scan_COILED.csv", written)
            for name in ("BREAKOUT", "PULLBACK", "TURN"):
                self.assertNotIn("scan_%s.csv" % name, written,
                                 "%s matched nothing" % name)

    def test_a_scan_that_matched_nothing_writes_only_the_headed_combined_file(self):
        """The two rules meeting: the combined file still says "nothing
        matched" in a parseable shape, and no per-setup file claims to."""
        with tmpdir() as d:
            base = os.path.join(d, "scan.csv")
            rc, _, _ = run_main(["--setup", "all", "--csv", base,
                                 "--csv-per-setup"],
                                [scan_row("A", matched={})])
            self.assertEqual(rc, 0)
            self.assertEqual(os.listdir(d), ["scan.csv"])
            self.assertEqual(raw_lines(base), [",".join(EXPECTED_COLUMNS)])

    def test_every_per_setup_file_carries_the_same_thirty_one_columns(self):
        with tmpdir() as d:
            base = os.path.join(d, "scan.csv")
            run_main(["--setup", "leader,coiled", "--csv", base,
                      "--csv-per-setup"], self._two_setups())
            for name in ("COILED", "LEADER"):
                path = os.path.join(d, "scan_%s.csv" % name)
                self.assertEqual(raw_lines(path)[0], ",".join(EXPECTED_COLUMNS))

    def test_one_line_per_file_written_naming_it_and_its_row_count(self):
        with tmpdir() as d:
            base = os.path.join(d, "scan.csv")
            _, _, err = run_main(["--setup", "leader,coiled", "--csv", base,
                                  "--csv-per-setup"], self._two_setups())
            self.assertIn("wrote 5 rows to %s" % base, err)
            self.assertIn("wrote 2 rows to %s"
                          % os.path.join(d, "scan_COILED.csv"), err)
            self.assertIn("wrote 3 rows to %s"
                          % os.path.join(d, "scan_LEADER.csv"), err)

    def test_the_notice_names_no_file_that_was_not_written(self):
        """The absence has to be visible in the output too, not only on disk."""
        with tmpdir() as d:
            base = os.path.join(d, "scan.csv")
            _, _, err = run_main(["--setup", "all", "--csv", base,
                                  "--csv-per-setup"], self._two_setups())
            for name in ("BREAKOUT", "PULLBACK", "TURN"):
                self.assertNotIn("scan_%s.csv" % name, err)

    def test_the_notices_go_to_stderr_so_json_stays_parseable(self):
        import json
        with tmpdir() as d:
            base = os.path.join(d, "scan.csv")
            rc, out, err = run_main(["--setup", "leader,coiled", "--json",
                                     "--csv", base, "--csv-per-setup"],
                                    self._two_setups())
            self.assertEqual(rc, 0)
            json.loads(out)
            self.assertNotIn("scan_LEADER.csv", out)
            self.assertIn("scan_LEADER.csv", err)

    def test_without_the_flag_no_per_setup_file_appears(self):
        """The other arm: --csv alone still writes exactly one file."""
        with tmpdir() as d:
            base = os.path.join(d, "scan.csv")
            run_main(["--setup", "leader,coiled", "--csv", base],
                     self._two_setups())
            self.assertEqual(os.listdir(d), ["scan.csv"])

    def test_the_bare_csv_flag_names_the_siblings_from_the_dated_default(self):
        import datetime as _dt
        today = _dt.date.today().isoformat()
        with tmpdir() as d, chdir(d):
            run_main(["--setup", "leader,coiled", "--csv", "--csv-per-setup"],
                     self._two_setups())
            self.assertEqual(
                sorted(os.listdir("scans")),
                ["scan_%s.csv" % today,
                 "scan_%s_COILED.csv" % today,
                 "scan_%s_LEADER.csv" % today])

    def test_the_setup_filter_reaches_the_split(self):
        """--setup coiled writes the COILED file and no LEADER one, even though
        the names also matched LEADER."""
        with tmpdir() as d:
            base = os.path.join(d, "scan.csv")
            run_main(["--setup", "coiled", "--csv", base, "--csv-per-setup"],
                     self._two_setups())
            self.assertEqual(sorted(os.listdir(d)),
                             ["scan.csv", "scan_COILED.csv"])

    def test_the_twenty_row_cap_applies_to_each_per_setup_file(self):
        """The same ceiling, not a fresh uncapped path: 31 LEADER matches give
        20 rows in the combined file and the same 20 in the split."""
        rows = [scan_row("SYM%02d" % i, total=9.0 - i * 0.1) for i in range(31)]
        with tmpdir() as d:
            base = os.path.join(d, "scan.csv")
            _, _, err = run_main(["--setup", "leader", "--csv", base,
                                  "--csv-per-setup"], rows)
            per = read_back(os.path.join(d, "scan_LEADER.csv"))
            self.assertEqual(len(per), csv_export.MAX_ROWS_PER_SETUP)
            self.assertEqual([int(r["rank_within_setup"]) for r in per],
                             list(range(1, 21)))
            self.assertEqual([r["symbol"] for r in per],
                             ["SYM%02d" % i for i in range(20)])
            self.assertIn("wrote 20 rows to %s"
                          % os.path.join(d, "scan_LEADER.csv"), err)

    def test_append_reaches_the_split_across_two_runs(self):
        with tmpdir() as d:
            base = os.path.join(d, "scan.csv")
            argv = ["--setup", "leader", "--csv", base, "--csv-per-setup",
                    "--append"]
            run_main(argv, [scan_row("FIRST")])
            run_main(argv, [scan_row("LATER")])
            path = os.path.join(d, "scan_LEADER.csv")
            self.assertEqual([r["symbol"] for r in read_back(path)],
                             ["FIRST", "LATER"])
            self.assertEqual(sum(1 for l in raw_lines(path)
                                 if l.startswith("scan_date,")), 1)

    def test_without_append_the_second_run_replaces_the_split_too(self):
        with tmpdir() as d:
            base = os.path.join(d, "scan.csv")
            argv = ["--setup", "leader", "--csv", base, "--csv-per-setup"]
            run_main(argv, [scan_row("FIRST")])
            run_main(argv, [scan_row("LATER")])
            self.assertEqual(
                [r["symbol"] for r in
                 read_back(os.path.join(d, "scan_LEADER.csv"))],
                ["LATER"])

    def test_the_flag_without_csv_exits_non_zero_before_any_scan_runs(self):
        """End to end, not only through parse_args: main() must not scan the
        universe and then discard the work."""
        with tmpdir() as d, chdir(d):
            buf = io.StringIO()
            with redirect_stderr(buf), self.assertRaises(SystemExit) as cm:
                screener.main(["--csv-per-setup"])
            self.assertNotEqual(cm.exception.code, 0)
            self.assertIn("requires --csv", buf.getvalue())
            self.assertEqual(os.listdir(d), [])


class TestLiveSmoke(unittest.TestCase):
    """One live scan of the real universe, cross-checked against the scan's own
    header. Everything else above is offline.

    It runs on the FULL universe deliberately. A three-name universe matched
    nothing on the day this was written, so the file had a header and no rows --
    every per-row assertion passed over an empty list and the test proved
    nothing. The header's match counts are the independent number to check the
    file against.
    """

    def test_a_real_scan_writes_every_match_it_reported(self):
        import re
        with tmpdir() as d:
            path = os.path.join(d, "live.csv")
            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(io.StringIO()):
                rc = screener.main(["--setup", "all", "--top", "5",
                                    "--csv", path])
            self.assertEqual(rc, 0)
            line = [l for l in buf.getvalue().split("\n")
                    if l.startswith("matches ")][0]
            counts = {k: int(v) for k, v in re.findall(r"(\w+) (\d+)", line)}

            with open(path, newline="", encoding="utf-8") as fh:
                reader = csvmod.DictReader(fh)
                self.assertEqual(reader.fieldnames, EXPECTED_COLUMNS)
                rows = list(reader)

            self.assertTrue(sum(counts.values()) > 0,
                            "nothing matched anywhere in the universe -- this "
                            "smoke test cannot say anything today")
            cap = csv_export.MAX_ROWS_PER_SETUP
            expected = sum(min(n, cap) for n in counts.values())
            self.assertEqual(len(rows), expected)
            self.assertLessEqual(len(rows), cap * len(counts))
            for name, n in counts.items():
                ranks = [int(r["rank_within_setup"]) for r in rows
                         if r["setup_name"] == name]
                # Contiguous 1..min(n, cap): the file holds the TOP of each
                # ranking, not the --top 5 the terminal showed and not an
                # arbitrary slice out of the middle.
                self.assertEqual(ranks, list(range(1, min(n, cap) + 1)), name)

            all_setups = list(setups.SETUPS) + ["CONFLUENCE"]
            for r in rows:
                self.assertIn(r["setup_name"], all_setups)
                self.assertIn(r["risk_reward_veto_applied"], ("0", "1"))
                self.assertEqual(r["threshold_mode"], "loosened")
                self.assertEqual(r["universe_name"], "nifty500")
                self.assertTrue(r["symbol"] and r["sector"])
                float(r[C_SCORE_NOW])
                float(r[C_FIT])
                self.assertNotIn("None", list(r.values()))
                self.assertNotIn("nan", list(r.values()))
                matched = [m for m in r["all_setups_matched"].split("|") if m]
                self.assertEqual(int(r["setups_matched_count"]), len(matched))
                if r["setup_name"] != "CONFLUENCE":
                    self.assertIn(r["setup_name"], matched)
                    self.assertTrue(r["evidence_1_metric_name"])
                else:
                    self.assertEqual(r["evidence_1_metric_name"], "")
                    self.assertGreaterEqual(int(r["setups_matched_count"]), 2)


if __name__ == "__main__":
    unittest.main()
