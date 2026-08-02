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


EXPECTED_COLUMNS = [
    "scan_date", "last_closed_bar", "universe", "mode",
    "symbol", "sector",
    "setup", "rank", "setup_fit",
    "score_now", "score_at_trigger", "risk_reward", "vetoed", "action",
    "price", "trigger_price", "stop",
    "rs_1m", "rs_3m", "ud_ratio", "ud_weighted", "ud_20",
    "volume_signal", "accumulation_trend",
    "setups_matched", "match_count",
    "evidence_1_label", "evidence_1_value",
    "evidence_2_label", "evidence_2_value",
    "flags",
]

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
        self.assertEqual({r["setup"]: r["ud_ratio"] for r in rows},
                         {"COILED": 1.11, "LEADER": 2.22, "CONFLUENCE": 3.33})

    def test_it_is_the_raw_ratio_not_a_formatted_string(self):
        """House rule for this file: raw sortable numbers, never `"1.47x"`."""
        r = build([scanned()], {"LEADER": [result()]}, ["LEADER"])[0]
        self.assertIsInstance(r["ud_ratio"], float)

    def test_it_is_rounded_to_two_places_like_the_terminal_column(self):
        """Two places, not three: the ratio is built from 50 bars of volume and
        the third decimal is noise the input cannot support. It is also what the
        terminal prints, and the file and the screen must not show a reader two
        different numbers for one measurement. The asserts below fail on a
        four-place, a three-place and a whole-number rounding alike."""
        r = build([scanned()], {"LEADER": [result(ud_ratio=1.4728394)]},
                  ["LEADER"])[0]
        self.assertEqual(r["ud_ratio"], 1.47)
        with tmpdir() as d:
            path = os.path.join(d, "s.csv")
            csv_export.write_csv(path, [r])
            self.assertEqual(read_back(path)[0]["ud_ratio"], "1.47")

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
        self.assertEqual(rows[0]["ud_ratio"], "")
        with tmpdir() as d:
            path = os.path.join(d, "s.csv")
            csv_export.write_csv(path, rows)
            self.assertEqual(read_back(path)[0]["ud_ratio"], "")

    def test_a_measured_zero_is_written_as_zero_not_left_blank(self):
        """0.0 is a measured finding -- no up-volume at all -- and must be
        distinguishable from a missing one. `if v is None`, never `if not v`."""
        rows = build([scanned()], {"LEADER": [result(ud_ratio=0.0)]}, ["LEADER"])
        self.assertEqual(rows[0]["ud_ratio"], 0.0)
        with tmpdir() as d:
            path = os.path.join(d, "s.csv")
            csv_export.write_csv(path, rows)
            self.assertEqual(read_back(path)[0]["ud_ratio"], "0.0")


class TestVolumeColumns(unittest.TestCase):
    """The four columns that join ud_ratio: two more raw ratios and two labels.

    ud_ratio alone cannot separate a name being accumulated from one being
    distributed into strength -- both read above 1.0 -- so the file carries the
    close-weighted ratio, the 20-bar ratio, and the two labels derived from
    them, all as universal per-row columns rather than evidence slots.
    """

    NEW = ("ud_weighted", "ud_20", "volume_signal", "accumulation_trend")
    RATIOS = ("ud_ratio", "ud_weighted", "ud_20")
    LABELS = ("volume_signal", "accumulation_trend")

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
        self.assertEqual(row["ud_ratio"], 1.47)
        self.assertEqual(row["ud_weighted"], 0.63)
        self.assertEqual(row["ud_20"], 2.85)
        self.assertEqual(row["volume_signal"], "distribution-into-strength")
        self.assertEqual(row["accumulation_trend"], "fading")

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
        self.assertEqual(cells["ud_ratio"], "1.47")
        self.assertEqual(cells["ud_weighted"], "0.63")
        self.assertEqual(cells["ud_20"], "2.85")
        self.assertEqual(cells["volume_signal"], "supported")
        self.assertEqual(cells["accumulation_trend"], "reversed")

    def test_the_two_new_ratios_are_raw_numbers_not_formatted_strings(self):
        row = self.one()
        self.assertIsInstance(row["ud_weighted"], float)
        self.assertIsInstance(row["ud_20"], float)

    def test_the_two_new_ratios_are_rounded_to_two_places_like_ud_ratio(self):
        """The same convention, for the same reason: they are ratios built from
        20 or 50 bars of volume, and the third decimal is noise the input cannot
        support. The asserts fail on a three-place and a whole-number rounding
        alike."""
        row = self.one(ud_weighted=0.6349281, ud_20=2.8551749)
        self.assertEqual(row["ud_weighted"], 0.63)
        self.assertEqual(row["ud_20"], 2.86)
        disk = self.on_disk(ud_weighted=0.6349281, ud_20=2.8551749)
        self.assertEqual(disk["ud_weighted"], "0.63")
        self.assertEqual(disk["ud_20"], "2.86")

    def test_the_weighted_ratio_is_not_written_from_the_plain_one(self):
        """The pair a copy-paste most easily crosses, and the one case where
        crossing them inverts the finding: a plain ratio well above 1.0 beside a
        weighted ratio below it IS distribution into strength."""
        row = self.one(ud_ratio=1.90, ud_weighted=0.71)
        self.assertEqual(row["ud_ratio"], 1.90)
        self.assertEqual(row["ud_weighted"], 0.71)

    def test_the_twenty_bar_ratio_is_not_written_from_the_fifty_bar_one(self):
        row = self.one(ud_ratio=1.10, ud_20=2.40)
        self.assertEqual(row["ud_ratio"], 1.10)
        self.assertEqual(row["ud_20"], 2.40)

    def test_the_labels_are_written_verbatim_including_the_hyphens(self):
        """Nothing is title-cased, truncated or re-spelled on the way to the
        file: these are the same words the terminal key defines, so a reader can
        filter the file on the label the screen showed them."""
        for signal in ("accumulation", "distribution-into-strength",
                       "supported", "distribution", "unknown"):
            self.assertEqual(self.on_disk(volume_signal=signal)["volume_signal"],
                             signal)
        for trend in ("strengthening", "steady", "flattening", "fading",
                      "reversed", "unknown"):
            self.assertEqual(
                self.on_disk(accumulation_trend=trend)["accumulation_trend"],
                trend)

    def test_the_two_labels_are_not_transposed(self):
        """Disjoint vocabularies: no signal is ever `steady`, no trend is ever
        `supported`, so a swap cannot pass as a plausible row."""
        disk = self.on_disk(volume_signal="supported",
                            accumulation_trend="steady")
        self.assertEqual(disk["volume_signal"], "supported")
        self.assertEqual(disk["accumulation_trend"], "steady")

    def test_a_missing_value_is_an_empty_cell_and_never_the_word_none(self):
        """One field at a time, so no assertion is satisfied by a row that
        blanked the whole block. `str(None)` would write the four characters
        `None`, which sorts and filters as if it were a label of its own -- and
        for the ratios it would break every consumer that sums the column."""
        for key in self.RATIOS + self.LABELS:
            with self.subTest(field=key):
                row = self.one(**{key: None})
                self.assertEqual(row[key], "")
                disk = self.on_disk(**{key: None})
                self.assertEqual(disk[key], "")
                self.assertNotIn("None", list(disk.values()))
                for other in self.RATIOS + self.LABELS:
                    if other != key:
                        self.assertNotEqual(disk[other], "", other)

    def test_a_measured_zero_ratio_is_written_as_zero_not_left_blank(self):
        """0.0 on the weighted ratio is a name whose every up-bar closed at its
        low -- measured, not missing. `if v is None`, never `if not v`."""
        for key in ("ud_weighted", "ud_20"):
            with self.subTest(field=key):
                self.assertEqual(self.one(**{key: 0.0})[key], 0.0)
                self.assertEqual(self.on_disk(**{key: 0.0})[key], "0.0")

    def test_an_empty_label_string_is_kept_rather_than_becoming_none(self):
        """The sibling arm of the None case: `""` is not None, so text() must
        leave it alone rather than routing it through the same branch."""
        self.assertEqual(self.one(volume_signal="")["volume_signal"], "")

    def test_a_row_missing_any_new_field_raises_rather_than_writing_a_blank(self):
        """The sibling arm of the None case. None is a value that could not be
        formed and is a blank cell honestly; a MISSING key is a caller that never
        built the row build_result_row promises, and `.get` would blank -- or,
        on a label, invent the real word `unknown` for -- the whole column."""
        for key in self.NEW:
            with self.subTest(field=key):
                r = result()
                del r[key]
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
        by_setup = {r["setup"]: r for r in rows}
        self.assertEqual(sorted(by_setup), ["COILED", "CONFLUENCE", "LEADER"])
        self.assertEqual({k: v["ud_weighted"] for k, v in by_setup.items()},
                         {"COILED": 0.11, "LEADER": 0.22, "CONFLUENCE": 0.33})
        self.assertEqual({k: v["ud_20"] for k, v in by_setup.items()},
                         {"COILED": 1.11, "LEADER": 2.22, "CONFLUENCE": 3.33})
        self.assertEqual({k: v["volume_signal"] for k, v in by_setup.items()},
                         {"COILED": "accumulation", "LEADER": "supported",
                          "CONFLUENCE": "distribution"})
        self.assertEqual({k: v["accumulation_trend"] for k, v in by_setup.items()},
                         {"COILED": "strengthening", "LEADER": "fading",
                          "CONFLUENCE": "reversed"})


class TestSchema(unittest.TestCase):
    def test_columns_are_the_agreed_thirty_one_in_order(self):
        self.assertEqual(csv_export.COLUMNS, EXPECTED_COLUMNS)
        self.assertEqual(len(csv_export.COLUMNS), 31)

    def test_the_up_down_ratio_sits_beside_relative_strength(self):
        """A universal metric, not an evidence slot: it means the same thing on
        every row of every setup, so it lives with rs_1m/rs_3m and risk_reward
        rather than in the per-setup evidence pair."""
        cols = csv_export.COLUMNS
        self.assertEqual(cols[cols.index("rs_3m") + 1], "ud_ratio")
        self.assertNotIn("ud_ratio", [k for pair in csv_export.EVIDENCE.values()
                                      for k, _ in pair])

    def test_the_four_new_volume_columns_follow_ud_ratio_in_order(self):
        """Asserted as a contiguous slice, not four `in COLUMNS` checks: order
        is the schema. A column emitted one position late shifts every value to
        its right in a file whose reader keys on position."""
        cols = csv_export.COLUMNS
        start = cols.index("ud_ratio")
        self.assertEqual(cols[start:start + 5],
                         ["ud_ratio", "ud_weighted", "ud_20", "volume_signal",
                          "accumulation_trend"])
        self.assertEqual(cols[start + 5], "setups_matched")

    def test_the_new_volume_columns_are_not_evidence_slots(self):
        """Like ud_ratio: they mean the same thing on every row of every setup,
        including CONFLUENCE, whose two evidence slots are already spoken for."""
        evidence_keys = [k for pair in csv_export.EVIDENCE.values()
                         for k, _ in pair]
        for name in ("ud_weighted", "ud_20", "volume_signal",
                     "accumulation_trend"):
            self.assertNotIn(name, evidence_keys)

    def test_no_column_name_is_repeated(self):
        self.assertEqual(len(set(csv_export.COLUMNS)), len(csv_export.COLUMNS))

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
        self.assertEqual(rows[0]["last_closed_bar"], "31-Jul-2026")
        self.assertEqual(rows[0]["universe"], "nifty500")
        self.assertEqual(rows[0]["mode"], "strict")


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
            self.assertEqual(back["last_closed_bar"], "31-Jul-2026")

    def test_one_row_per_symbol_setup_pair(self):
        scan_rows = [scanned("TCS", ("COILED", "LEADER"))]
        by_setup = {"COILED": [result("TCS", evidence=dict(COILED_EV))],
                    "LEADER": [result("TCS")],
                    "CONFLUENCE": [result("TCS", evidence={"matched": ["COILED", "LEADER"],
                                                           "count": 2,
                                                           "label": "COILED+LEADER",
                                                           "mean_fit": 8.0})]}
        rows = build(scan_rows, by_setup, ["COILED", "LEADER", "CONFLUENCE"])
        self.assertEqual([r["setup"] for r in rows],
                         ["COILED", "LEADER", "CONFLUENCE"])
        self.assertEqual({r["symbol"] for r in rows}, {"TCS"})

    def test_setups_matched_is_identical_on_every_row_of_that_symbol(self):
        scan_rows = [scanned("TCS", ("COILED", "LEADER"))]
        by_setup = {"COILED": [result("TCS", evidence=dict(COILED_EV))],
                    "LEADER": [result("TCS")]}
        rows = build(scan_rows, by_setup, ["COILED", "LEADER"])
        for r in rows:
            self.assertEqual(r["setups_matched"], "COILED|LEADER")
            self.assertEqual(r["match_count"], 2)

    def test_setups_matched_reports_setups_this_export_did_not_ask_for(self):
        """--setup coiled still says the name is also a LEADER: the question is
        about the stock, not about the slice being exported."""
        rows = build([scanned("TCS", ("COILED", "LEADER"))],
                     {"COILED": [result("TCS", evidence=dict(COILED_EV))]},
                     ["COILED"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["setups_matched"], "COILED|LEADER")
        self.assertEqual(rows[0]["match_count"], 2)

    def test_setups_matched_is_life_cycle_ordered_not_alphabetical(self):
        rows = build([scanned("TCS", ("TURN", "COILED", "BREAKOUT"))],
                     {"LEADER": [result("TCS")]}, ["LEADER"])
        self.assertEqual(rows[0]["setups_matched"], "COILED|BREAKOUT|TURN")

    def test_confluence_is_not_counted_as_a_matched_setup(self):
        scan_rows = [scanned("TCS", ("COILED", "LEADER"))]
        scan_rows[0]["matched"]["CONFLUENCE"] = {"fit": 8.0, "evidence": {}}
        rows = build(scan_rows, {"LEADER": [result("TCS")]}, ["LEADER"])
        self.assertEqual(rows[0]["setups_matched"], "COILED|LEADER")
        self.assertEqual(rows[0]["match_count"], 2)

    def test_a_single_setup_name_still_gets_the_pair_of_columns(self):
        rows = build([scanned("TCS", ("LEADER",))],
                     {"LEADER": [result("TCS")]}, ["LEADER"])
        self.assertEqual(rows[0]["setups_matched"], "LEADER")
        self.assertEqual(rows[0]["match_count"], 1)

    def test_a_row_whose_symbol_never_scanned_degrades_instead_of_crashing(self):
        rows = build([scanned("TCS")], {"LEADER": [result("GHOST")]}, ["LEADER"])
        self.assertEqual(rows[0]["setups_matched"], "")
        self.assertEqual(rows[0]["match_count"], 0)

    def test_rank_is_one_based_and_follows_the_given_order(self):
        by_setup = {"LEADER": [result("A"), result("B"), result("C")]}
        rows = build([scanned("A"), scanned("B"), scanned("C")],
                     by_setup, ["LEADER"])
        self.assertEqual([(r["symbol"], r["rank"]) for r in rows],
                         [("A", 1), ("B", 2), ("C", 3)])

    def test_rank_restarts_at_one_for_each_setup(self):
        by_setup = {"COILED": [result("A", evidence=dict(COILED_EV)),
                               result("B", evidence=dict(COILED_EV))],
                    "LEADER": [result("C")]}
        rows = build([scanned("A"), scanned("B"), scanned("C")],
                     by_setup, ["COILED", "LEADER"])
        self.assertEqual([(r["setup"], r["rank"]) for r in rows],
                         [("COILED", 1), ("COILED", 2), ("LEADER", 1)])

    def test_setups_are_emitted_in_the_chosen_order(self):
        by_setup = {"COILED": [result("A", evidence=dict(COILED_EV))],
                    "LEADER": [result("B")]}
        rows = build([scanned("A"), scanned("B")], by_setup,
                     ["LEADER", "COILED"])
        self.assertEqual([r["setup"] for r in rows], ["LEADER", "COILED"])

    def test_a_chosen_setup_with_no_matches_contributes_no_rows(self):
        rows = build([scanned("A")], {"LEADER": [result("A")], "TURN": []},
                     ["LEADER", "TURN"])
        self.assertEqual([r["setup"] for r in rows], ["LEADER"])

    def test_the_cap_is_enforced_where_the_rows_are_built(self):
        """Not only through main(): any caller of build_rows gets the cap, so a
        second export path cannot reintroduce an uncapped file."""
        syms = ["S%02d" % i for i in range(30)]
        rows = build([scanned(s) for s in syms],
                     {"LEADER": [result(s) for s in syms]}, ["LEADER"])
        self.assertEqual(len(rows), csv_export.MAX_ROWS_PER_SETUP)
        self.assertEqual([r["symbol"] for r in rows],
                         syms[:csv_export.MAX_ROWS_PER_SETUP])
        self.assertEqual([r["rank"] for r in rows],
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
        self.assertEqual([r["setup"] for r in rows], ["LEADER"])


class TestEvidenceColumns(unittest.TestCase):
    def _row(self, setup, evidence, symbol="TCS"):
        return build([scanned(symbol, (setup,) if setup != "CONFLUENCE"
                              else ("COILED", "LEADER"))],
                     {setup: [result(symbol, evidence=evidence)]}, [setup])[0]

    def test_coiled_emits_contraction_and_position_in_base(self):
        r = self._row("COILED", {"contraction": 0.61, "pos_in_base": 0.98172})
        self.assertEqual(r["evidence_1_label"], "contraction")
        self.assertEqual(r["evidence_1_value"], 0.61)
        self.assertEqual(r["evidence_2_label"], "pos_in_base")
        self.assertEqual(r["evidence_2_value"], 0.982)

    def test_position_in_base_stays_a_fraction_rather_than_a_percent_string(self):
        r = self._row("COILED", {"contraction": 0.61, "pos_in_base": 0.982})
        self.assertNotIsInstance(r["evidence_2_value"], str)
        self.assertLess(r["evidence_2_value"], 1.0)

    def test_breakout_emits_volume_multiple_and_extension_as_bare_numbers(self):
        r = self._row("BREAKOUT", {"vol_mult": 4.1064, "pct_above_base": 6.2171,
                                   "volume_light": False})
        self.assertEqual((r["evidence_1_label"], r["evidence_1_value"]),
                         ("vol_mult", 4.106))
        self.assertEqual((r["evidence_2_label"], r["evidence_2_value"]),
                         ("pct_above_base", 6.217))

    def test_leader_emits_stack_completeness_not_a_second_copy_of_rs_1m(self):
        """rs_1m already has a column; two columns claiming the same number at
        two roundings is the bug this replaces. full_stack is a real input to
        fit_leader and appears nowhere else in the row."""
        r = self._row("LEADER", {"pct_from_high": 3.4567, "rs_1m": 6.2178,
                                 "full_stack": True})
        self.assertEqual((r["evidence_1_label"], r["evidence_1_value"]),
                         ("pct_from_high", 3.457))
        self.assertEqual(r["evidence_2_label"], "ma_stack_full")
        self.assertEqual(r["evidence_2_value"], 1)
        self.assertNotIn("rs_1m", (r["evidence_1_label"], r["evidence_2_label"]))

    def test_an_incomplete_stack_is_zero_rather_than_blank(self):
        r = self._row("LEADER", {"pct_from_high": 3.4, "full_stack": False})
        self.assertEqual(r["evidence_2_value"], 0)

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
        self.assertEqual((r["evidence_1_label"], r["evidence_1_value"]),
                         ("close_position", 0.736))
        self.assertEqual((r["evidence_2_label"], r["evidence_2_value"]),
                         ("retrace_pct", 17.057))

    def test_pullback_close_position_stays_a_fraction_in_the_file(self):
        """The terminal prints 74%; the file keeps 0.736, like pos_in_base."""
        r = self._row("PULLBACK", {"close_position": 0.73578,
                                   "retrace_pct": 17.0567})
        self.assertNotIsInstance(r["evidence_1_value"], str)
        self.assertLess(r["evidence_1_value"], 1.0)

    def test_pullback_publishes_the_swing_retracement_not_the_range_share(self):
        """The two are different numbers on different scales and the file must
        carry the one the gate uses. 17.06% under a swing high and 33% of the
        52-week range are both true of the same name."""
        r = self._row("PULLBACK", {"close_position": 0.74,
                                   "retrace_pct": 17.0567,
                                   "retrace_of_52w_range_pct": 33.0})
        self.assertEqual(r["evidence_2_value"], 17.057)

    def test_pullback_evidence_keys_exist_on_the_real_predicates_output(self):
        """Pins the export to match_pullback's actual evidence dict, so renaming
        a key there cannot silently blank a column here."""
        import inspect
        src = inspect.getsource(setups.match_pullback)
        self.assertIn('"close_position"', src)
        self.assertIn('"retrace_pct"', src)

    def test_turn_emits_bars_since_cross_and_the_macd_histogram(self):
        r = self._row("TURN", {"bars_since_cross": 12, "macd_hist": 1.23456})
        self.assertEqual((r["evidence_1_label"], r["evidence_1_value"]),
                         ("bars_since_cross", 12))
        self.assertEqual((r["evidence_2_label"], r["evidence_2_value"]),
                         ("macd_hist", 1.235))

    def test_confluence_leaves_both_evidence_pairs_blank(self):
        """Its evidence is setups_matched plus setup_fit, already in the row."""
        r = self._row("CONFLUENCE", {"matched": ["COILED", "LEADER"],
                                     "count": 2, "label": "COILED+LEADER",
                                     "mean_fit": 8.0})
        self.assertEqual(r["evidence_1_label"], "")
        self.assertEqual(r["evidence_1_value"], "")
        self.assertEqual(r["evidence_2_label"], "")
        self.assertEqual(r["evidence_2_value"], "")
        self.assertEqual(r["setups_matched"], "COILED|LEADER")

    def test_a_missing_evidence_key_blanks_the_value_but_keeps_the_label(self):
        r = self._row("COILED", {"contraction": 0.61})
        self.assertEqual(r["evidence_2_label"], "pos_in_base")
        self.assertEqual(r["evidence_2_value"], "")


class TestFlags(unittest.TestCase):
    def _flags(self, evidence, setup="BREAKOUT"):
        return build([scanned("TCS", (setup,))],
                     {setup: [result("TCS", evidence=evidence)]},
                     [setup])[0]["flags"]

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
            self.assertEqual(read_back(path)[0]["flags"], "volume_light")

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
        self.assertEqual(r["setup_fit"], 8.13)
        self.assertEqual(r["score_now"], 6.21)
        self.assertEqual(r["score_at_trigger"], 7.17)
        self.assertEqual(r["risk_reward"], 2.44)
        self.assertEqual(r["rs_1m"], 6.2)
        self.assertEqual(r["rs_3m"], -3.3)

    def test_prices_round_to_two_places(self):
        rows = build([scanned()],
                     {"LEADER": [result(price=1234.5678, trigger_price=1240.1234,
                                        stop=1180.9876)]}, ["LEADER"])
        self.assertEqual(rows[0]["price"], 1234.57)
        self.assertEqual(rows[0]["trigger_price"], 1240.12)
        self.assertEqual(rows[0]["stop"], 1180.99)

    def test_none_values_become_empty_strings_across_the_row(self):
        rows = build([scanned()],
                     {"LEADER": [result(trigger_total=None, trigger_price=None,
                                        stop=None, rr=None, rs_1m=None,
                                        rs_3m=None)]}, ["LEADER"])
        for col in ("score_at_trigger", "trigger_price", "stop", "risk_reward",
                    "rs_1m", "rs_3m"):
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
        self.assertEqual(clean["vetoed"], 0)
        self.assertEqual(veto["vetoed"], 1)
        self.assertNotIsInstance(veto["vetoed"], bool)

    def test_the_action_word_is_carried_through_verbatim(self):
        rows = build([scanned()], {"LEADER": [result(action="BUY HALF")]},
                     ["LEADER"])
        self.assertEqual(rows[0]["action"], "BUY HALF")

    def test_no_numeric_cell_in_the_file_carries_a_unit_symbol(self):
        with tmpdir() as d:
            path = os.path.join(d, "out.csv")
            csv_export.write_csv(path, build(
                [scanned("TCS", ("BREAKOUT",))],
                {"BREAKOUT": [result("TCS", evidence=dict(BREAKOUT_EV))]},
                ["BREAKOUT"]))
            row = read_back(path)[0]
            for col in ("setup_fit", "score_now", "risk_reward", "price",
                        "rs_1m", "rs_3m", "evidence_1_value",
                        "evidence_2_value"):
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
            self.assertEqual([r["rank"] for r in rows], ["1", "2", "3", "4"])

    def test_the_file_keeps_twenty_rows_per_setup_and_no_more(self):
        """31 matches, and the file holds the top 20 with contiguous ranks."""
        with tmpdir() as d:
            path = os.path.join(d, "o.csv")
            rc, _, err = run_main(["--setup", "leader", "--top", "5",
                                   "--csv", path], self._rows(31))
            self.assertEqual(rc, 0)
            rows = read_back(path)
            self.assertEqual(len(rows), 20)
            self.assertEqual([int(r["rank"]) for r in rows],
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
                    [int(r["rank"]) for r in back if r["setup"] == name],
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
                              if int(r["rank"]) <= 2], shown)
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
            self.assertEqual([r["setup"] for r in back], ["COILED"])
            self.assertEqual(back[0]["setups_matched"], "COILED|LEADER")

    def test_strict_is_recorded_in_the_mode_column(self):
        with tmpdir() as d:
            path = os.path.join(d, "o.csv")
            run_main(["--setup", "leader", "--strict", "--csv", path],
                     self._rows(1))
            self.assertEqual(read_back(path)[0]["mode"], "strict")

    def test_a_loosened_scan_says_so_in_the_mode_column(self):
        with tmpdir() as d:
            path = os.path.join(d, "o.csv")
            run_main(["--setup", "leader", "--csv", path], self._rows(1))
            self.assertEqual(read_back(path)[0]["mode"], "loosened")

    def test_the_universe_column_is_the_universe_not_the_filename(self):
        with tmpdir() as d:
            path = os.path.join(d, "o.csv")
            run_main(["--setup", "leader", "--universe", "/x/y/nifty500.txt",
                      "--csv", path], self._rows(1))
            self.assertEqual(read_back(path)[0]["universe"], "nifty500")

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
            back = {r["setup"]: r for r in read_back(path)}
            self.assertEqual(sorted(back), ["COILED", "CONFLUENCE", "LEADER"])
            conf = back["CONFLUENCE"]
            self.assertEqual(conf["evidence_1_label"], "")
            self.assertEqual(conf["evidence_2_value"], "")
            self.assertEqual(conf["setups_matched"], "COILED|LEADER")
            self.assertEqual(conf["match_count"], "2")
            self.assertEqual(back["LEADER"]["setups_matched"], "COILED|LEADER")

    def test_the_file_carries_the_scans_own_last_closed_bar(self):
        """...and prints it as a date a spreadsheet will not turn into 46234."""
        with tmpdir() as d:
            path = os.path.join(d, "o.csv")
            run_main(["--setup", "leader", "--csv", path], self._rows(1))
            self.assertEqual(read_back(path)[0]["last_closed_bar"], "31-Jul-2026")

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
                ranks = [int(r["rank"]) for r in rows if r["setup"] == name]
                # Contiguous 1..min(n, cap): the file holds the TOP of each
                # ranking, not the --top 5 the terminal showed and not an
                # arbitrary slice out of the middle.
                self.assertEqual(ranks, list(range(1, min(n, cap) + 1)), name)

            all_setups = list(setups.SETUPS) + ["CONFLUENCE"]
            for r in rows:
                self.assertIn(r["setup"], all_setups)
                self.assertIn(r["vetoed"], ("0", "1"))
                self.assertEqual(r["mode"], "loosened")
                self.assertEqual(r["universe"], "nifty500")
                self.assertTrue(r["symbol"] and r["sector"])
                float(r["score_now"])
                float(r["setup_fit"])
                self.assertNotIn("None", list(r.values()))
                self.assertNotIn("nan", list(r.values()))
                matched = [m for m in r["setups_matched"].split("|") if m]
                self.assertEqual(int(r["match_count"]), len(matched))
                if r["setup"] != "CONFLUENCE":
                    self.assertIn(r["setup"], matched)
                    self.assertTrue(r["evidence_1_label"])
                else:
                    self.assertEqual(r["evidence_1_label"], "")
                    self.assertGreaterEqual(int(r["match_count"]), 2)


if __name__ == "__main__":
    unittest.main()
