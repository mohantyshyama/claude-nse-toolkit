"""Live end-to-end checks against the real Nifty 500 and the live Yahoo API.

These are slow (~30s) and require network. They exist because every other test
uses synthetic fixtures, and a screener that passes unit tests while returning
nonsense on real data has failed at the only thing it does.
"""
import os, sys, time, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import screener
import setups
from universe import DEFAULT_UNIVERSE, load_universe


class TestLiveScan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pairs = load_universe(DEFAULT_UNIVERSE)
        t = time.time()
        cls.rows, cls.failed = screener.scan(cls.pairs, strict=False,
                                             min_turnover=3.0, workers=16)
        cls.elapsed = time.time() - t

    def test_scans_the_full_universe_within_two_minutes(self):
        self.assertLess(self.elapsed, 120,
                        f"scan took {self.elapsed:.0f}s; benchmark was ~23s")

    def test_the_vast_majority_of_symbols_resolve(self):
        self.assertGreater(len(self.rows), 0.9 * len(self.pairs),
                           f"{len(self.failed)} failures is too many: "
                           f"{self.failed[:10]}")

    def test_scan_normalises_matched_to_a_dict_for_every_row(self):
        """evaluate() is tri-state -- None (illiquid), {} (liquid, no match),
        non-empty dict. scan() must fold None into {} and record it separately,
        or every `name in row["matched"]` downstream explodes on an illiquid
        name. Pins that normalisation against live data."""
        for r in self.rows:
            self.assertIsInstance(r["matched"], dict, r["symbol"])
            self.assertIsInstance(r["illiquid"], bool, r["symbol"])
            if r["illiquid"]:
                self.assertEqual(r["matched"], {}, r["symbol"])

    def test_no_impossible_confluence_pair_occurs_in_the_real_market(self):
        """Guards spec section 3.6 across every name, not just fixtures."""
        for r in self.rows:
            names = [n for n in setups.SETUPS if n in r["matched"]]
            for i, a in enumerate(names):
                for b in names[i + 1:]:
                    self.assertNotIn(frozenset({a, b}), setups.IMPOSSIBLE_PAIRS,
                                     f"{r['symbol']}: {a}+{b}")
        # _add_confluence asserts the same thing inside the worker, and scan()
        # catches BaseException -- so a real violation would land in `failed`
        # and never reach the loop above. Check there too, or this test can pass
        # while the bug it exists to catch is happening on every scan.
        for sym, reason in self.failed:
            self.assertNotIn("impossible pair", reason, f"{sym}: {reason}")

    def test_every_strict_match_is_also_a_loosened_match(self):
        """Spec section 3: strict must be a subset of loosened."""
        sample = [(r["symbol"], r["sector"]) for r in self.rows[:60]]
        strict_rows, _ = screener.scan(sample, strict=True, min_turnover=3.0, workers=16)
        loose = {r["symbol"]: set(r["matched"]) for r in self.rows}
        for r in strict_rows:
            for name in r["matched"]:
                self.assertIn(name, loose.get(r["symbol"], set()),
                              f"{r['symbol']} matched {name} strict but not loosened")

    def test_scores_agree_with_the_engine_on_a_sample(self):
        from engine import A
        for r in self.rows[:5]:
            expected = A.compute(r["symbol"], catalyst=5.0)["score"]["total"]
            self.assertAlmostEqual(r["o"]["score"]["total"], expected, places=9)

    def test_confluence_never_reports_a_single_setup(self):
        for r in self.rows:
            if "CONFLUENCE" in r["matched"]:
                self.assertGreaterEqual(r["matched"]["CONFLUENCE"]["evidence"]["count"], 2)


if __name__ == "__main__":
    unittest.main()
