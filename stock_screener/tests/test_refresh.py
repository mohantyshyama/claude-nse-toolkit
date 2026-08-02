import contextlib
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import universe

CSV = ("Company Name,Industry,Symbol,Series,ISIN Code\n"
       "Reliance Industries Ltd.,Oil Gas & Consumable Fuels,RELIANCE,EQ,INE002A01018\n"
       "Tata Consultancy Services Ltd.,Information Technology,TCS,EQ,INE467B01029\n")

HEADER = "Company Name,Industry,Symbol,Series,ISIN Code\n"


def _tempfile(text):
    fd, path = tempfile.mkstemp(suffix=".txt")
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    return path


class TestParseNseCsv(unittest.TestCase):
    def test_extracts_symbol_and_industry(self):
        self.assertEqual(universe.parse_nse_csv(CSV),
                         [("RELIANCE", "Oil Gas & Consumable Fuels"),
                          ("TCS", "Information Technology")])

    def test_handles_quoted_commas_inside_company_names(self):
        csv = ('Company Name,Industry,Symbol,Series,ISIN Code\n'
               '"Bajaj Finance, Ltd.",Financial Services,BAJFINANCE,EQ,INE296A01024\n')
        self.assertEqual(universe.parse_nse_csv(csv),
                         [("BAJFINANCE", "Financial Services")])

    def test_missing_required_columns_is_an_error(self):
        with self.assertRaises(SystemExit):
            universe.parse_nse_csv("Foo,Bar\n1,2\n")

    def test_empty_body_is_an_error(self):
        with self.assertRaises(SystemExit):
            universe.parse_nse_csv("Company Name,Industry,Symbol,Series,ISIN Code\n")

    # --- both arms of the column guard -----------------------------------

    def test_missing_industry_column_alone_is_an_error(self):
        # Symbol present, Industry absent: the guard must be an OR, not an AND.
        with self.assertRaises(SystemExit):
            universe.parse_nse_csv("Company Name,Symbol,Series\nFoo Ltd,TCS,EQ\n")

    def test_missing_symbol_column_alone_is_an_error(self):
        with self.assertRaises(SystemExit):
            universe.parse_nse_csv(
                "Company Name,Industry,Series\nFoo Ltd,Information Technology,EQ\n")

    def test_empty_text_is_an_error(self):
        # No header at all -> fieldnames is None, which must not blow up on iteration.
        with self.assertRaises(SystemExit):
            universe.parse_nse_csv("")

    def test_header_matching_ignores_case_and_whitespace(self):
        csv = (" Company Name , INDUSTRY , symbol , Series \n"
               "Foo Ltd,Information Technology,TCS,EQ\n")
        self.assertEqual(universe.parse_nse_csv(csv),
                         [("TCS", "Information Technology")])

    # --- per-row normalisation, both arms ---------------------------------

    def test_symbol_is_upper_cased_and_stripped(self):
        csv = HEADER + "Foo Ltd,Information Technology,  tcs  ,EQ,INE467B01029\n"
        self.assertEqual(universe.parse_nse_csv(csv),
                         [("TCS", "Information Technology")])

    def test_sector_is_stripped_but_otherwise_preserved(self):
        csv = HEADER + "Foo Ltd,  Information Technology  ,TCS,EQ,INE467B01029\n"
        self.assertEqual(universe.parse_nse_csv(csv)[0][1], "Information Technology")

    def test_blank_industry_becomes_unknown(self):
        csv = HEADER + "Foo Ltd,   ,TCS,EQ,INE467B01029\n"
        self.assertEqual(universe.parse_nse_csv(csv), [("TCS", "Unknown")])

    def test_rows_without_a_symbol_are_skipped(self):
        csv = (HEADER +
               "Ghost Ltd,Financial Services,,EQ,INE000A01000\n"
               "Tata Consultancy Services Ltd.,Information Technology,TCS,EQ,INE467B01029\n")
        self.assertEqual(universe.parse_nse_csv(csv),
                         [("TCS", "Information Technology")])

    def test_short_rows_do_not_crash(self):
        # A truncated line yields None for the missing fields.
        csv = (HEADER +
               "Truncated Ltd,Financial Services\n"
               "Tata Consultancy Services Ltd.,Information Technology,TCS,EQ,INE467B01029\n")
        self.assertEqual(universe.parse_nse_csv(csv),
                         [("TCS", "Information Technology")])

    def test_order_follows_the_csv(self):
        reversed_csv = ("Company Name,Industry,Symbol,Series,ISIN Code\n"
                        "Tata Consultancy Services Ltd.,Information Technology,TCS,EQ,INE467B01029\n"
                        "Reliance Industries Ltd.,Oil Gas & Consumable Fuels,RELIANCE,EQ,INE002A01018\n")
        self.assertEqual([s for s, _ in universe.parse_nse_csv(reversed_csv)],
                         ["TCS", "RELIANCE"])

    def test_quoted_comma_inside_industry_is_preserved(self):
        csv = HEADER + 'Foo Ltd,"Chemicals, Fertilisers",TCS,EQ,INE467B01029\n'
        self.assertEqual(universe.parse_nse_csv(csv),
                         [("TCS", "Chemicals, Fertilisers")])

    def test_column_order_is_read_from_the_header_not_hardcoded(self):
        # Same data, columns shuffled: a positional parser would return garbage.
        csv = ("ISIN Code,Symbol,Series,Industry,Company Name\n"
               "INE467B01029,TCS,EQ,Information Technology,Tata Consultancy Services Ltd.\n")
        self.assertEqual(universe.parse_nse_csv(csv),
                         [("TCS", "Information Technology")])


class TestRefreshSafety(unittest.TestCase):
    def test_failed_refresh_leaves_the_existing_file_untouched(self):
        fd, path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w") as fh:
            fh.write("TCS\tInformation Technology\n")
        original = open(path).read()

        def boom(_):
            raise OSError("NSE blocked the request")

        saved, universe._fetch_nse_csv = universe._fetch_nse_csv, boom
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = universe.refresh_universe(path)
        finally:
            universe._fetch_nse_csv = saved
        self.assertNotEqual(rc, 0)
        self.assertEqual(open(path).read(), original)

    def test_successful_refresh_rewrites_the_file(self):
        fd, path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w") as fh:
            fh.write("OLD\tSector\n")
        saved, universe._fetch_nse_csv = universe._fetch_nse_csv, lambda _: CSV
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = universe.refresh_universe(path)
        finally:
            universe._fetch_nse_csv = saved
        self.assertEqual(rc, 0)
        self.assertEqual([s for s, _ in universe.load_universe(path)],
                         ["RELIANCE", "TCS"])

    def test_successful_refresh_preserves_sectors(self):
        path = _tempfile("OLD\tSector\n")
        saved, universe._fetch_nse_csv = universe._fetch_nse_csv, lambda _: CSV
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                universe.refresh_universe(path)
        finally:
            universe._fetch_nse_csv = saved
        self.assertEqual(universe.load_universe(path),
                         [("RELIANCE", "Oil Gas & Consumable Fuels"),
                          ("TCS", "Information Technology")])

    def test_written_rows_are_tab_separated_under_a_comment_header(self):
        # A sector containing a comma proves the writer uses tabs, not commas.
        csv = HEADER + 'Foo Ltd,"Chemicals, Fertilisers",TCS,EQ,INE467B01029\n'
        path = _tempfile("OLD\tSector\n")
        saved, universe._fetch_nse_csv = universe._fetch_nse_csv, lambda _: csv
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                universe.refresh_universe(path)
        finally:
            universe._fetch_nse_csv = saved
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        self.assertTrue(lines[0].startswith("#"), lines[0])
        body = [ln for ln in lines if ln and not ln.startswith("#")]
        self.assertEqual(body, ["TCS\tChemicals, Fertilisers"])

    def test_failed_refresh_does_not_create_a_missing_file(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "does_not_exist.txt")

        def boom(_):
            raise OSError("NSE blocked the request")

        saved, universe._fetch_nse_csv = universe._fetch_nse_csv, boom
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = universe.refresh_universe(path)
        finally:
            universe._fetch_nse_csv = saved
        self.assertNotEqual(rc, 0)
        self.assertFalse(os.path.exists(path),
                         "a failed refresh must not create a truncated universe file")

    def test_malformed_download_propagates_and_leaves_the_file_untouched(self):
        path = _tempfile("TCS\tInformation Technology\n")
        original = open(path).read()
        saved, universe._fetch_nse_csv = universe._fetch_nse_csv, lambda _: "Foo,Bar\n1,2\n"
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit):
                    universe.refresh_universe(path)
        finally:
            universe._fetch_nse_csv = saved
        self.assertEqual(open(path).read(), original)

    def test_refresh_defaults_to_the_bundled_universe_path(self):
        path = _tempfile("OLD\tSector\n")
        saved_fetch = universe._fetch_nse_csv
        saved_default = universe.DEFAULT_UNIVERSE
        universe._fetch_nse_csv = lambda _: CSV
        universe.DEFAULT_UNIVERSE = path
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = universe.refresh_universe()
        finally:
            universe._fetch_nse_csv = saved_fetch
            universe.DEFAULT_UNIVERSE = saved_default
        self.assertEqual(rc, 0)
        self.assertEqual([s for s, _ in universe.load_universe(path)],
                         ["RELIANCE", "TCS"])

    def test_refresh_fetches_the_nse_index_url(self):
        path = _tempfile("OLD\tSector\n")
        seen = []

        def spy(url):
            seen.append(url)
            return CSV

        saved, universe._fetch_nse_csv = universe._fetch_nse_csv, spy
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                universe.refresh_universe(path)
        finally:
            universe._fetch_nse_csv = saved
        self.assertEqual(seen, [universe.NSE_CSV_URL])
        self.assertIn("nifty500list", universe.NSE_CSV_URL)

    def test_success_reports_how_many_symbols_were_written(self):
        path = _tempfile("OLD\tSector\n")
        buf = io.StringIO()
        saved, universe._fetch_nse_csv = universe._fetch_nse_csv, lambda _: CSV
        try:
            with contextlib.redirect_stdout(buf):
                universe.refresh_universe(path)
        finally:
            universe._fetch_nse_csv = saved
        out = buf.getvalue()
        self.assertIn("2", out)
        self.assertIn(path, out)

    def test_failure_explains_itself_and_says_nothing_changed(self):
        path = _tempfile("TCS\tInformation Technology\n")
        buf = io.StringIO()

        def boom(_):
            raise OSError("HTTP Error 403: Forbidden")

        saved, universe._fetch_nse_csv = universe._fetch_nse_csv, boom
        try:
            with contextlib.redirect_stdout(buf):
                universe.refresh_universe(path)
        finally:
            universe._fetch_nse_csv = saved
        out = buf.getvalue()
        self.assertIn("403", out)
        self.assertIn(universe.NSE_CSV_URL, out)
        self.assertIn(path, out)
        self.assertIn("NOT modified", out)


class TestFullUniverse(unittest.TestCase):
    def test_bundled_file_holds_the_full_index(self):
        rows = universe.load_universe(universe.DEFAULT_UNIVERSE)
        self.assertGreaterEqual(len(rows), 480)
        self.assertLessEqual(len(rows), 520)

    def test_no_symbol_is_missing_a_sector(self):
        for sym, sector in universe.load_universe(universe.DEFAULT_UNIVERSE):
            self.assertNotEqual(sector, "Unknown", sym)

    def test_bundled_file_has_no_duplicate_symbols(self):
        # load_universe dedupes, so check the raw file.
        with open(universe.DEFAULT_UNIVERSE, encoding="utf-8") as fh:
            syms = [ln.split("\t")[0].strip() for ln in fh
                    if ln.strip() and not ln.startswith("#")]
        self.assertEqual(len(syms), len(set(syms)),
                         sorted(s for s in set(syms) if syms.count(s) > 1))

    def test_bundled_symbols_look_like_nse_tickers(self):
        for sym, _ in universe.load_universe(universe.DEFAULT_UNIVERSE):
            self.assertRegex(sym, r"^[A-Z0-9&.\-]{2,20}$")

    def test_bundled_file_spans_many_sectors(self):
        sectors = {sec for _, sec in universe.load_universe(universe.DEFAULT_UNIVERSE)}
        self.assertGreaterEqual(len(sectors), 10, sorted(sectors))


if __name__ == "__main__":
    unittest.main()
