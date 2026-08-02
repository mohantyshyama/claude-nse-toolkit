import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from universe import load_universe, DEFAULT_UNIVERSE


def write(text):
    fd, path = tempfile.mkstemp(suffix=".txt")
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    return path


class TestUniverse(unittest.TestCase):
    def test_parses_symbol_and_sector(self):
        p = write("RELIANCE\tOil Gas & Consumable Fuels\nTCS\tInformation Technology\n")
        self.assertEqual(load_universe(p),
                         [("RELIANCE", "Oil Gas & Consumable Fuels"),
                          ("TCS", "Information Technology")])

    def test_skips_blanks_and_comments_and_dedupes(self):
        p = write("# header\n\nTCS\tIT\nTCS\tIT\n  \nINFY\tIT\n")
        self.assertEqual(load_universe(p), [("TCS", "IT"), ("INFY", "IT")])

    def test_missing_sector_column_defaults_to_unknown(self):
        p = write("TCS\n")
        self.assertEqual(load_universe(p), [("TCS", "Unknown")])

    def test_uppercases_and_strips_ns_suffix(self):
        p = write("tcs.ns\tIT\n")
        self.assertEqual(load_universe(p), [("TCS", "IT")])

    def test_sector_filter_is_case_insensitive_substring(self):
        p = write("TCS\tInformation Technology\nSBIN\tFinancial Services\n")
        self.assertEqual(load_universe(p, sectors=["information technology"]),
                         [("TCS", "Information Technology")])

    def test_sector_filter_accepts_several(self):
        p = write("TCS\tIT\nSBIN\tBanks\nITC\tFMCG\n")
        self.assertEqual([s for s, _ in load_universe(p, sectors=["it", "fmcg"])],
                         ["TCS", "ITC"])

    def test_missing_file_is_a_hard_error_naming_the_path(self):
        with self.assertRaises(SystemExit) as ctx:
            load_universe("/nonexistent/nifty500.txt")
        self.assertIn("/nonexistent/nifty500.txt", str(ctx.exception))

    def test_empty_file_is_a_hard_error_not_a_silent_empty_scan(self):
        p = write("# only a comment\n")
        with self.assertRaises(SystemExit):
            load_universe(p)

    def test_bundled_universe_exists_and_is_wellformed(self):
        rows = load_universe(DEFAULT_UNIVERSE)
        self.assertGreaterEqual(len(rows), 40)
        for sym, sector in rows:
            self.assertEqual(sym, sym.upper().strip())
            self.assertTrue(sector)


if __name__ == "__main__":
    unittest.main()
