import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import screener


class TestScanIsolation(unittest.TestCase):
    """Live network tests. TATAMOTORS no longer resolves on Yahoo post-demerger
    and is the fixture proving one dead ticker cannot abort a scan."""

    def test_dead_ticker_does_not_abort_the_scan(self):
        pairs = [("RELIANCE", "Oil"), ("TATAMOTORS", "Auto"), ("TCS", "IT")]
        rows, failed = screener.scan(pairs, strict=False, min_turnover=3.0, workers=4)
        self.assertEqual({r["symbol"] for r in rows}, {"RELIANCE", "TCS"})
        self.assertEqual([s for s, _ in failed], ["TATAMOTORS"])

    def test_failure_reason_is_reported_not_swallowed(self):
        _, failed = screener.scan([("NOTAREALTICKERXYZ", "X")], strict=False,
                                  min_turnover=3.0, workers=2)
        self.assertEqual(len(failed), 1)
        self.assertTrue(failed[0][1])

    def test_scan_preserves_sector(self):
        rows, _ = screener.scan([("TCS", "Information Technology")], strict=False,
                                min_turnover=3.0, workers=2)
        self.assertEqual(rows[0]["sector"], "Information Technology")

    def test_score_matches_the_engine_exactly(self):
        """Invariant I1's guard. Fails the moment anyone reimplements a factor."""
        from engine import A
        rows, _ = screener.scan([("RELIANCE", "Oil")], strict=False,
                                min_turnover=3.0, workers=2)
        expected = A.compute("RELIANCE", catalyst=5.0)["score"]["total"]
        self.assertAlmostEqual(rows[0]["o"]["score"]["total"], expected, places=9)


class TestIndexReturns(unittest.TestCase):
    def test_returns_1m_and_3m_windows(self):
        r = screener.index_returns()
        self.assertIn("1m", r)
        self.assertIn("3m", r)

    def test_missing_baseline_degrades_to_none_rather_than_crashing(self):
        from engine import A
        original = A.fetch
        A.fetch = lambda *a, **k: (_ for _ in ()).throw(SystemExit("boom"))
        try:
            self.assertEqual(screener.index_returns(), {"1m": None, "3m": None})
        finally:
            A.fetch = original


_UNSET = object()      # None is a meaningful `matched` value, so it cannot be
                       # the default sentinel.


class _Stub:
    """Offline rig for the branches a live scan cannot reach on demand.

    A dead baseline, a symbol with no 1-month history and an exception with an
    empty message all exist in a 500-name scan; none can be summoned from Yahoo
    on request, so they are injected here.
    """

    def __init__(self, test, idx=None, returns=None, raise_exc=None,
                 matched=_UNSET, diag_fill=None):
        self.test = test
        self.idx = {"1m": 2.0, "3m": 5.0} if idx is None else idx
        self.returns = {"1m": 7.0, "3m": 15.0} if returns is None else returns
        self.raise_exc = raise_exc
        # What the stubbed evaluate() hands back. `{}` is the liquid-but-quiet
        # default; None is the liquidity-gate rejection.
        self.matched = {} if matched is _UNSET else matched
        # What the stubbed evaluate() writes into the funnel dict it is handed,
        # standing in for the predicates recording where they rejected.
        self.diag_fill = diag_fill
        self.seen = []          # (strict, min_turnover) handed to evaluate
        self.diags = []         # the diag dict handed to evaluate, per symbol
        self.workers = []       # max_workers handed to ThreadPoolExecutor
        self.compute_tf = []    # timeframe handed to A.compute, per symbol
        self.eval_tf = []       # timeframe handed to setups.evaluate, per symbol
        self.index_tf = []      # timeframe handed to index_returns

    def __enter__(self):
        import engine
        self.saved = (screener.index_returns, engine.A.compute,
                      screener.setups.evaluate, screener.ThreadPoolExecutor)
        self.engine = engine
        stub = self

        def compute(sym, catalyst=5.0, timeframe="daily"):
            stub.compute_tf.append(timeframe)
            if stub.raise_exc is not None:
                raise stub.raise_exc
            return {"symbol": sym, "returns": dict(stub.returns)}

        def evaluate(o, rs, strict=False, min_turnover=3.0, diag=None,
                     timeframe="daily"):
            stub.seen.append((strict, min_turnover))
            stub.eval_tf.append(timeframe)
            stub.diags.append(diag)
            if diag is not None and stub.diag_fill:
                diag.update(stub.diag_fill)
            return stub.matched

        real_pool = self.saved[3]

        def pool(max_workers=None):
            stub.workers.append(max_workers)
            return real_pool(max_workers=max_workers)

        def index_returns(timeframe="daily"):
            stub.index_tf.append(timeframe)
            return dict(stub.idx)

        screener.index_returns = index_returns
        engine.A.compute = compute
        screener.setups.evaluate = evaluate
        screener.ThreadPoolExecutor = pool
        return self

    def __exit__(self, *exc):
        (screener.index_returns, self.engine.A.compute,
         screener.setups.evaluate, screener.ThreadPoolExecutor) = self.saved
        return False


class TestRelativeStrength(unittest.TestCase):
    """Both arms of the `is not None` guard on each side of the subtraction."""

    def test_relative_strength_is_the_symbol_return_minus_the_index(self):
        with _Stub(self, idx={"1m": 2.0, "3m": 5.0},
                   returns={"1m": 7.0, "3m": 15.0}):
            rows, _ = screener.scan([("X", "S")], workers=1)
        self.assertAlmostEqual(rows[0]["rs"]["1m"], 5.0, places=9)
        self.assertAlmostEqual(rows[0]["rs"]["3m"], 10.0, places=9)

    def test_a_missing_baseline_blanks_relative_strength_without_failing(self):
        with _Stub(self, idx={"1m": None, "3m": None}):
            rows, failed = screener.scan([("X", "S")], workers=1)
        self.assertEqual(failed, [])
        self.assertEqual(rows[0]["rs"], {"1m": None, "3m": None})

    def test_a_missing_symbol_return_blanks_only_that_window(self):
        with _Stub(self, returns={"1m": None, "3m": 15.0}):
            rows, _ = screener.scan([("X", "S")], workers=1)
        self.assertIsNone(rows[0]["rs"]["1m"])
        self.assertAlmostEqual(rows[0]["rs"]["3m"], 10.0, places=9)


class TestFailureReason(unittest.TestCase):
    def test_the_exception_message_is_reported_verbatim(self):
        with _Stub(self, raise_exc=SystemExit("ERROR: kaboom")):
            _, failed = screener.scan([("X", "S")], workers=1)
        self.assertEqual(failed, [("X", "ERROR: kaboom")])

    def test_an_empty_message_falls_back_to_the_exception_type(self):
        """`str(e) or type(e).__name__` -- a bare raise must not report "".
        The header prints the reason; an empty one reads as no reason."""
        with _Stub(self, raise_exc=KeyError()):
            _, failed = screener.scan([("X", "S")], workers=1)
        self.assertEqual(failed, [("X", "KeyError")])


class TestScanDefaults(unittest.TestCase):
    def test_defaults_are_loosened_three_crore_and_sixteen_workers(self):
        with _Stub(self) as stub:
            screener.scan([("X", "S")])
        self.assertEqual(stub.seen, [(False, 3.0)])
        self.assertEqual(stub.workers, [16])

    def test_explicit_arguments_reach_evaluate_and_the_pool(self):
        with _Stub(self) as stub:
            screener.scan([("X", "S")], strict=True, min_turnover=9.5, workers=3)
        self.assertEqual(stub.seen, [(True, 9.5)])
        self.assertEqual(stub.workers, [3])


class TestScanRecordsWhyASymbolMatchedNothing(unittest.TestCase):
    """scan() is where evaluate()'s tri-state is turned into a row.

    The row must (a) remember which of the two falsy outcomes happened, and
    (b) still expose a dict under "matched", because every downstream consumer
    does `name in row["matched"]` and `row["matched"][setup]`.
    """

    def test_a_gate_rejection_is_flagged_illiquid(self):
        with _Stub(self, matched=None):
            rows, _ = screener.scan([("X", "S")], workers=1)
        self.assertTrue(rows[0]["illiquid"])

    def test_a_liquid_name_that_matched_nothing_is_not_flagged_illiquid(self):
        """The sibling arm. Both return falsy from evaluate(); only one is
        below the turnover floor."""
        with _Stub(self, matched={}):
            rows, _ = screener.scan([("X", "S")], workers=1)
        self.assertFalse(rows[0]["illiquid"])

    def test_a_matching_name_is_not_flagged_illiquid(self):
        hit = {"LEADER": {"fit": 8.0, "evidence": {}}}
        with _Stub(self, matched=hit):
            rows, _ = screener.scan([("X", "S")], workers=1)
        self.assertFalse(rows[0]["illiquid"])
        self.assertEqual(rows[0]["matched"], hit)

    def test_none_never_reaches_the_matched_field(self):
        """`name in None` is a TypeError, and main() does exactly that for
        every setup on every row. The None must be absorbed here."""
        with _Stub(self, matched=None):
            rows, _ = screener.scan([("X", "S")], workers=1)
        self.assertEqual(rows[0]["matched"], {})
        self.assertIsNotNone(rows[0]["matched"])
        self.assertNotIn("LEADER", rows[0]["matched"])   # would raise on None

    def test_the_funnel_evaluate_fills_in_is_kept_on_the_row(self):
        """scan() must hand evaluate a funnel dict and carry the result out --
        the counters are collected inside the one scoring pass, and main() has
        no other way to reach them once the pool has closed."""
        fill = {"BREAKOUT": {"a close above the base high": (3, 1)}}
        with _Stub(self, diag_fill=fill) as stub:
            rows, _ = screener.scan([("X", "S")], workers=1)
        self.assertEqual(len(stub.diags), 1)
        self.assertIsInstance(stub.diags[0], dict)
        self.assertEqual(rows[0]["diag"], fill)

    def test_every_symbol_gets_its_own_funnel_dict(self):
        """One shared dict across 16 worker threads would be a race; it would
        also make every name's rejections indistinguishable."""
        with _Stub(self) as stub:
            rows, _ = screener.scan([("X", "S"), ("Y", "S")], workers=2)
        self.assertEqual(len(stub.diags), 2)
        self.assertIsNot(stub.diags[0], stub.diags[1])
        self.assertIsNot(rows[0]["diag"], rows[1]["diag"])

    def test_an_illiquid_name_carries_an_empty_funnel_not_a_missing_key(self):
        """A gated name never reached a predicate, so it contributes nothing --
        but the key must still be there, because merge_funnel reads every row."""
        with _Stub(self, matched=None):
            rows, _ = screener.scan([("X", "S")], workers=1)
        self.assertEqual(rows[0]["diag"], {})

    def test_an_illiquid_name_is_still_a_scored_row_not_a_failure(self):
        """Being too thin to trade is a finding about the name, not an error in
        the scan; it must not land in `failed`."""
        with _Stub(self, matched=None):
            rows, failed = screener.scan([("X", "S")], workers=1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(failed, [])


class TestIndexReturnsWindows(unittest.TestCase):
    def test_baseline_uses_the_nifty_index_verbatim_over_21_and_63_bars(self):
        """Pins the ticker, the empty suffix (^NSEI has no .NS) and both
        windows. 21/63 must match analyze's own return windows or relative
        strength subtracts two different measurements."""
        from engine import A
        calls = []
        closes = [100.0 + i for i in range(100)]
        original = A.fetch
        A.fetch = lambda *a, **k: (calls.append((a, k)),
                                   ([{"c": c} for c in closes], {}))[1]
        try:
            r = screener.index_returns()
        finally:
            A.fetch = original
        self.assertEqual(calls[0][0], ("^NSEI", "2y", "1d"))
        self.assertEqual(calls[0][1], {"suffix": ""})
        self.assertAlmostEqual(r["1m"], (closes[-1] / closes[-22] - 1) * 100, places=9)
        self.assertAlmostEqual(r["3m"], (closes[-1] / closes[-64] - 1) * 100, places=9)


if __name__ == "__main__":
    unittest.main()
