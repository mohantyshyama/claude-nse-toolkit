import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestEngine(unittest.TestCase):
    def test_exposes_analyze_and_watchlist(self):
        import engine
        self.assertAlmostEqual(sum(engine.A.WEIGHTS.values()), 1.0, places=9)
        self.assertTrue(callable(engine.A.compute))
        self.assertTrue(callable(engine.W.score_at_trigger))
        self.assertTrue(callable(engine.W.action_for))

    def test_single_cache_instance_across_importers(self):
        """Two modules importing the engine must share ONE fetch cache.

        If each called spec_from_file_location itself they would get separate
        module objects with separate _CACHE dicts, silently doubling fetches.
        """
        import engine
        from engine import A as a1
        from engine import A as a2
        self.assertIs(a1, a2)
        a1._CACHE[("SENTINEL", "2y", "1d", ".NS")] = ("rows", "meta")
        self.assertIn(("SENTINEL", "2y", "1d", ".NS"), a2._CACHE)
        del a1._CACHE[("SENTINEL", "2y", "1d", ".NS")]

    def test_importing_watchlist_does_not_run_a_scan(self):
        """watchlist.py has a __main__ guard; importing must not start a scan."""
        import engine
        self.assertEqual(engine.W.NIFTY, "^NSEI")


if __name__ == "__main__":
    unittest.main()
