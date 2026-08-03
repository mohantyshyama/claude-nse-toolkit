"""--timeframe from argv to every place a scan derives numbers from bars.

There are four of them, and a flag that reaches three is worse than no flag at
all: the header would say "weekly bars" over a table that scored some of its
columns on daily ones.

    argparse -> screener.scan -> A.compute            the six factor scores
                              -> setups.evaluate      -> build_ctx, the setup
                                                         context and gates
                              -> index_returns        the RS benchmark
             -> csv_export.build_rows                 the file's own stamp
             -> render_header                         what the reader is told

Every test below asserts one of those hops in BOTH directions -- the weekly
value arrives, and the daily default arrives when nothing is passed -- because
a hop hard-wired to either constant satisfies only one of the pair.
"""
import contextlib
import csv as csvmod
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import csv_export                                              # noqa: E402
import screener                                                # noqa: E402
import setups                                                  # noqa: E402
from engine import A                                           # noqa: E402

import fixtures                                                # noqa: E402
from test_cli import _MainStub, run_main                        # noqa: E402
from test_csv_export import run_main as run_csv_main            # noqa: E402
from test_csv_export import scan_row as csv_scan_row            # noqa: E402

BOTH = ("daily", "weekly")


@contextlib.contextmanager
def tmpdir():
    d = tempfile.mkdtemp()
    try:
        yield d
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


@contextlib.contextmanager
def recording_fetch():
    """Replace A.fetch with a recorder returning a usable synthetic series."""
    calls = []
    rows = fixtures.flat_series(300, price=100.0)
    saved = A.fetch

    def fetch(symbol, rng, interval, suffix=".NS"):
        calls.append((symbol, rng, interval, suffix))
        return list(rows), {"longName": symbol}

    A.fetch = fetch
    try:
        yield calls
    finally:
        A.fetch = saved


def scored(symbol="X"):
    """The two fields aligned_rows reads off a compute() result."""
    return {"symbol": symbol, "last_closed_bar": {"t": "2999-12-31"}}


# --------------------------------------------------------------- the CLI flag

class TestTheFlagItself(unittest.TestCase):

    def test_the_default_is_daily(self):
        self.assertEqual(screener.parse_args([]).timeframe, "daily")

    def test_both_values_are_accepted_verbatim(self):
        for tf in BOTH:
            self.assertEqual(screener.parse_args(["--timeframe", tf]).timeframe,
                             tf)

    def test_an_unknown_value_is_a_usage_error_before_the_scan_runs(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(
                io.StringIO()):
            screener.parse_args(["--timeframe", "monthly"])

    def test_the_accepted_values_are_the_engine_s_own(self):
        """One source of truth. A flag offering a timeframe compute() does not
        implement would fail inside a worker, 500 names deep."""
        self.assertEqual(sorted(BOTH), sorted(A.TIMEFRAMES))


# ------------------------------------------------------- setups derives series

class TestSetupsDerivesTheScannedSeries(unittest.TestCase):

    def test_aligned_rows_requests_the_primary_series_of_the_timeframe(self):
        for tf in BOTH:
            with self.subTest(timeframe=tf), recording_fetch() as calls:
                setups.aligned_rows(scored(), tf)
                self.assertEqual(calls, [("X",) + A.TIMEFRAMES[tf]["primary"]
                                         + (".NS",)])

    def test_aligned_rows_defaults_to_the_daily_series(self):
        with recording_fetch() as calls:
            setups.aligned_rows(scored())
        self.assertEqual(calls, [("X", "2y", "1d", ".NS")])

    def test_the_two_timeframes_request_different_bars(self):
        """Guards the two tests above against a primary_request that returned
        the same pair for both."""
        self.assertNotEqual(A.TIMEFRAMES["daily"]["primary"],
                            A.TIMEFRAMES["weekly"]["primary"])

    def test_primary_request_refuses_a_timeframe_the_engine_lacks(self):
        with self.assertRaises(SystemExit):
            setups.primary_request("monthly")

    def test_build_ctx_passes_the_timeframe_down_to_the_fetch(self):
        for tf in BOTH:
            with self.subTest(timeframe=tf), recording_fetch() as calls:
                setups.build_ctx(scored(), {}, tf)
                self.assertEqual(calls[0][1:3], A.TIMEFRAMES[tf]["primary"])

    def test_build_ctx_defaults_to_daily(self):
        with recording_fetch() as calls:
            setups.build_ctx(scored(), {})
        self.assertEqual(calls[0][1:3], ("2y", "1d"))


class TestEvaluateReachesBuildCtx(unittest.TestCase):
    """The hop a flag is most easily accepted without making.

    build_ctx is recorded rather than run: it returns a context with no bars,
    which fails the liquidity gate, so evaluate returns before any predicate --
    the timeframe is the only thing under test here.
    """

    def setUp(self):
        self.seen = []
        self.saved = setups.build_ctx

        def recorder(o, rs, timeframe="daily"):
            self.seen.append(timeframe)
            return {"rows": []}

        setups.build_ctx = recorder
        self.addCleanup(lambda: setattr(setups, "build_ctx", self.saved))

    def test_the_timeframe_reaches_build_ctx(self):
        for tf in BOTH:
            with self.subTest(timeframe=tf):
                self.seen = []
                self.assertIsNone(setups.evaluate(scored(), {}, timeframe=tf))
                self.assertEqual(self.seen, [tf])

    def test_evaluate_defaults_to_daily(self):
        self.assertIsNone(setups.evaluate(scored(), {}))
        self.assertEqual(self.seen, ["daily"])


# ------------------------------------------------------------- the scan itself

class _ScanStub:
    """screener.scan with the engine replaced, recording the timeframe each of
    the three consumers was handed."""

    def __enter__(self):
        self.compute_tf, self.eval_tf, self.index_tf = [], [], []
        self.saved = (A.compute, screener.setups.evaluate,
                      screener.index_returns)
        stub = self

        def compute(sym, catalyst=5.0, timeframe="daily"):
            stub.compute_tf.append(timeframe)
            return {"symbol": sym, "returns": {"1m": 5.0, "3m": 9.0}}

        def evaluate(o, rs, strict=False, min_turnover=3.0, diag=None,
                     timeframe="daily"):
            stub.eval_tf.append(timeframe)
            return {}

        def index_returns(timeframe="daily"):
            stub.index_tf.append(timeframe)
            return {"1m": 1.0, "3m": 2.0}

        A.compute = compute
        screener.setups.evaluate = evaluate
        screener.index_returns = index_returns
        return self

    def __exit__(self, *exc):
        (A.compute, screener.setups.evaluate,
         screener.index_returns) = self.saved
        return False


class TestScanThreadsTheTimeframe(unittest.TestCase):

    def test_all_three_consumers_receive_the_scans_timeframe(self):
        for tf in BOTH:
            with self.subTest(timeframe=tf), _ScanStub() as stub:
                screener.scan([("X", "S")], workers=1, timeframe=tf)
                self.assertEqual(stub.compute_tf, [tf])
                self.assertEqual(stub.eval_tf, [tf])
                self.assertEqual(stub.index_tf, [tf])

    def test_the_default_scan_is_daily_everywhere(self):
        with _ScanStub() as stub:
            screener.scan([("X", "S")], workers=1)
        self.assertEqual((stub.compute_tf, stub.eval_tf, stub.index_tf),
                         (["daily"], ["daily"], ["daily"]))


class TestTheBenchmarkIsMeasuredOnTheSameBars(unittest.TestCase):
    """Relative strength is a SUBTRACTION. o["returns"] is 21 and 63 primary
    bars, so a benchmark left on daily bars during a weekly scan would take a
    21-day index move away from a 21-week stock move."""

    def test_the_index_is_fetched_on_the_scans_own_interval(self):
        for tf in BOTH:
            with self.subTest(timeframe=tf), recording_fetch() as calls:
                screener.index_returns(tf)
                self.assertEqual(calls, [(screener.NIFTY,)
                                         + A.TIMEFRAMES[tf]["primary"] + ("",)])

    def test_the_index_defaults_to_daily_bars(self):
        with recording_fetch() as calls:
            screener.index_returns()
        self.assertEqual(calls, [(screener.NIFTY, "2y", "1d", "")])

    def test_an_unknown_timeframe_raises_rather_than_blanking_the_columns(self):
        """It is resolved outside the try. Swallowed by the network handler it
        would print "baseline unavailable" and scan on with no benchmark."""
        with self.assertRaises(SystemExit):
            screener.index_returns("monthly")


# --------------------------------------------------------------- what is said

class TestTheHeaderSaysWhichBars(unittest.TestCase):

    def _header(self, *extra):
        return screener.render_header("2026-08-02", "2026-07-31", "u.txt", 10,
                                      False, 10, [], 0, {}, *extra).split("\n")[0]

    def test_each_timeframe_is_named_on_the_first_line(self):
        for tf in BOTH:
            self.assertIn("%s bars" % tf, self._header(tf))

    def test_the_default_header_says_daily_bars(self):
        self.assertIn("daily bars", self._header())

    def test_the_header_never_names_the_other_timeframe(self):
        """A header printing both words tells the reader nothing."""
        self.assertNotIn("weekly", self._header("daily"))
        self.assertNotIn("daily", self._header("weekly"))

    def test_the_mode_is_still_there_beside_it(self):
        line = self._header("weekly")
        self.assertIn("loosened", line)
        self.assertIn("weekly bars", line)


class TestTheCsvStampsTheTimeframe(unittest.TestCase):

    def test_the_column_is_beside_the_threshold_mode(self):
        cols = csv_export.COLUMNS
        self.assertEqual(cols[cols.index("threshold_mode") + 1],
                         "bar_timeframe_daily_or_weekly")

    def test_the_cell_is_the_argument_not_a_constant(self):
        for tf in BOTH:
            with self.subTest(timeframe=tf):
                rows = csv_export.build_rows(
                    [csv_scan_row("TCS")],
                    {"LEADER": [self._result()]}, ["LEADER"],
                    "2026-08-02", "2026-07-31", "nifty500", "loosened", tf)
                self.assertEqual(
                    [r["bar_timeframe_daily_or_weekly"] for r in rows], [tf])

    def test_the_argument_is_required(self):
        """No default: a caller that forgot to thread the flag would otherwise
        stamp a weekly scan `daily`, and nothing downstream could detect it."""
        with self.assertRaises(TypeError):
            csv_export.build_rows([csv_scan_row("TCS")],
                                  {"LEADER": [self._result()]}, ["LEADER"],
                                  "2026-08-02", "2026-07-31", "nifty500",
                                  "loosened")

    def _result(self):
        from test_csv_export import result
        return result()


class TestEndToEndThroughMain(unittest.TestCase):

    def test_the_flag_reaches_the_scanner(self):
        for tf in BOTH:
            with self.subTest(timeframe=tf):
                stub = _MainStub()
                rc, _ = run_main(["--timeframe", tf], stub)
                self.assertEqual(rc, 0)
                self.assertEqual(stub.scan_kwargs["timeframe"], tf)

    def test_an_unflagged_run_scans_daily(self):
        stub = _MainStub()
        run_main([], stub)
        self.assertEqual(stub.scan_kwargs["timeframe"], "daily")

    def test_the_printed_header_names_the_timeframe_that_ran(self):
        for tf in BOTH:
            with self.subTest(timeframe=tf):
                stub = _MainStub()
                _, out = run_main(["--timeframe", tf], stub)
                self.assertIn("%s bars" % tf, out.split("\n")[0])

    def test_the_json_scan_block_carries_it_too(self):
        import json
        for tf in BOTH:
            with self.subTest(timeframe=tf):
                stub = _MainStub()
                _, out = run_main(["--json", "--timeframe", tf], stub)
                self.assertEqual(json.loads(out)["scan"]["timeframe"], tf)

    def test_the_written_file_records_the_timeframe_on_every_row(self):
        for tf in BOTH:
            with self.subTest(timeframe=tf), tmpdir() as d:
                path = os.path.join(d, "scan.csv")
                rc, _, _ = run_csv_main(
                    ["--setup", "leader", "--csv", path, "--timeframe", tf],
                    [csv_scan_row("SYM%d" % i) for i in range(3)])
                self.assertEqual(rc, 0)
                with open(path, newline="", encoding="utf-8") as fh:
                    written = list(csvmod.DictReader(fh))
                self.assertTrue(written)
                self.assertEqual(
                    {r["bar_timeframe_daily_or_weekly"] for r in written}, {tf})

    def test_a_daily_and_a_weekly_file_are_never_readable_as_one(self):
        """The point of the column: concatenate the two files and every row
        still says which scan produced it."""
        rows = []
        for tf in BOTH:
            with tmpdir() as d:
                path = os.path.join(d, "scan.csv")
                run_csv_main(["--setup", "leader", "--csv", path,
                              "--timeframe", tf],
                             [csv_scan_row("SYM%d" % i) for i in range(3)])
                with open(path, newline="", encoding="utf-8") as fh:
                    rows += list(csvmod.DictReader(fh))
        self.assertEqual({r["bar_timeframe_daily_or_weekly"] for r in rows},
                         set(BOTH))


if __name__ == "__main__":
    unittest.main()
