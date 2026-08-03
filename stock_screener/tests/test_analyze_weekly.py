"""compute(timeframe=...) -- the weekly primary series and its consequences.

Deterministic and synthetic: these tests are about WHICH bars compute() asks
for and what it does when there is no higher timeframe, not about any live
number. tests/test_analyze_daily_regression.py pins the numbers on real bars.

The stub fetch refuses an unrecorded request, so every routing assertion here
fails loudly rather than silently serving the wrong series.
"""
import datetime as dt
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import setups                                                    # noqa: E402
from engine import A                                             # noqa: E402


def wave_bars(n, step_days=7, start=100.0):
    """`n` bars that rise on a wobble, so the indicators have something to say.

    Not a straight line: a monotonic series gives RSI exactly 100 and no down
    closes at all, which switches off half of what is being tested here.
    """
    rows = []
    for i in range(n):
        drift = start + i * 0.35
        wobble = 6.0 * math.sin(i / 9.0) + 2.0 * math.sin(i / 2.3)
        c = drift + wobble
        o = drift + 6.0 * math.sin((i - 1) / 9.0) + 2.0 * math.sin((i - 1) / 2.3)
        rows.append({"t": dt.date(2016, 1, 4) + dt.timedelta(days=step_days * i),
                     "o": o, "h": max(o, c) + 1.5, "l": min(o, c) - 1.5, "c": c,
                     "v": 1_000_000 + (i % 7) * 50_000})
    return rows


META = {"longName": "Synthetic Ltd", "regularMarketPrice": None}


class StubFetch:
    """Serves a declared set of requests and records what was asked for."""

    def __init__(self, series):
        self.series = series            # {(rng, interval): rows}
        self.calls = []

    def __call__(self, symbol, rng, interval, suffix=".NS"):
        self.calls.append((symbol, rng, interval, suffix))
        if (rng, interval) not in self.series:
            raise AssertionError(
                "compute() asked for %s/%s, which this test does not serve. "
                "Served: %s" % (rng, interval, sorted(self.series)))
        rows = self.series[(rng, interval)]
        meta = dict(META, regularMarketPrice=rows[-1]["c"])
        return list(rows), meta


WEEKLY_10Y = wave_bars(523)
DAILY_2Y = wave_bars(500, step_days=1)
WEEKLY_5Y = wave_bars(262)


def run_compute(series, **kw):
    stub = StubFetch(series)
    original = A.fetch
    A.fetch = stub
    try:
        return A.compute("SYNTH", catalyst=5.0, **kw), stub
    finally:
        A.fetch = original


DAILY_SERIES = {("2y", "1d"): DAILY_2Y, ("5y", "1wk"): WEEKLY_5Y}
WEEKLY_SERIES = {("10y", "1wk"): WEEKLY_10Y}


class TestTimeframeRouting(unittest.TestCase):

    def test_the_default_is_daily(self):
        """No timeframe argument must fetch exactly what it always fetched.

        Serving ONLY the daily pair means a default that flipped to weekly
        raises here instead of quietly scanning a different horizon for two
        skills that never pass the argument.
        """
        _, stub = run_compute(DAILY_SERIES)
        self.assertEqual(stub.calls, [("SYNTH", "2y", "1d", ".NS"),
                                      ("SYNTH", "5y", "1wk", ".NS")])

    def test_daily_named_explicitly_is_the_same_two_requests(self):
        _, stub = run_compute(DAILY_SERIES, timeframe="daily")
        self.assertEqual(stub.calls, [("SYNTH", "2y", "1d", ".NS"),
                                      ("SYNTH", "5y", "1wk", ".NS")])

    def test_daily_and_the_default_produce_the_same_dict(self):
        explicit, _ = run_compute(DAILY_SERIES, timeframe="daily")
        default, _ = run_compute(DAILY_SERIES)
        self.assertEqual(explicit, default)

    def test_weekly_fetches_ten_years_of_weekly_bars_and_nothing_else(self):
        """One request, 10y/1wk. Not 5y, and not a second series.

        Serving only that pair is the assertion: a weekly path that still
        reached for a higher timeframe, or that asked for 5y, raises.
        """
        _, stub = run_compute(WEEKLY_SERIES, timeframe="weekly")
        self.assertEqual(stub.calls, [("SYNTH", "10y", "1wk", ".NS")])

    def test_the_configured_ranges_are_the_measured_ones(self):
        self.assertEqual(A.TIMEFRAMES["daily"]["primary"], ("2y", "1d"))
        self.assertEqual(A.TIMEFRAMES["daily"]["higher"], ("5y", "1wk"))
        self.assertEqual(A.TIMEFRAMES["weekly"]["primary"], ("10y", "1wk"))
        self.assertIsNone(A.TIMEFRAMES["weekly"]["higher"])

    def test_an_unknown_timeframe_is_refused(self):
        with self.assertRaises(SystemExit) as cm:
            run_compute(DAILY_SERIES, timeframe="monthly")
        self.assertIn("monthly", str(cm.exception))

    def test_rendering_is_refused_where_there_is_no_higher_timeframe(self):
        """The report has a "weekly hist" line; formatting None through it
        raises a TypeError halfway down the page. Refuse it at the top."""
        with self.assertRaises(SystemExit) as cm:
            run_compute(WEEKLY_SERIES, timeframe="weekly", render=True)
        self.assertIn("higher", str(cm.exception))


class TestWeeklyHasNoHigherTimeframe(unittest.TestCase):

    def setUp(self):
        self.out, _ = run_compute(WEEKLY_SERIES, timeframe="weekly")
        self.daily, _ = run_compute(DAILY_SERIES)

    def test_every_higher_timeframe_slot_is_empty(self):
        self.assertIsNone(self.out["rsi"]["weekly"])
        self.assertIsNone(self.out["atr"]["weekly"])
        self.assertEqual(self.out["macd"]["weekly"],
                         {"line": None, "signal": None, "hist": None})

    def test_the_daily_run_fills_those_same_slots(self):
        """The mirror image, so the test above cannot pass by accident on a
        compute() that never filled the higher-timeframe slots at all."""
        self.assertIsNotNone(self.daily["rsi"]["weekly"])
        self.assertIsNotNone(self.daily["atr"]["weekly"])
        self.assertIsNotNone(self.daily["macd"]["weekly"]["hist"])

    def test_the_primary_slot_carries_the_weekly_series(self):
        """On weekly the slot named "daily" holds the PRIMARY series, and the
        primary series is the weekly bars -- to the bit, not approximately."""
        closes = [r["c"] for r in WEEKLY_10Y]
        self.assertEqual(self.out["rsi"]["daily"], A.rsi(closes))
        self.assertEqual(self.out["atr"]["daily"], A.atr(WEEKLY_10Y))
        self.assertEqual(self.out["macd"]["daily"]["hist"], A.macd(closes)[2])

    def test_the_primary_slot_is_not_the_daily_series(self):
        """Guards the assertion above against a fixture coincidence: the two
        timeframes must actually disagree for any of this to mean anything."""
        self.assertNotEqual(self.out["rsi"]["daily"], self.daily["rsi"]["daily"])
        self.assertNotEqual(self.out["atr"]["daily"], self.daily["atr"]["daily"])


class TestWeeklyMomentumDoesNotDoubleCount(unittest.TestCase):
    """score_momentum degrades by dropping the confirmation arms, never by
    passing the one series it has into both slots."""

    def setUp(self):
        self.out, _ = run_compute(WEEKLY_SERIES, timeframe="weekly")
        self.rsi_w = self.out["rsi"]["daily"]
        self.hist_w = self.out["macd"]["daily"]["hist"]

    def test_the_score_is_the_single_series_form(self):
        self.assertEqual(self.out["score"]["momentum"],
                         A.score_momentum(self.rsi_w, None, self.hist_w, None))

    def test_the_score_is_not_the_double_counted_form(self):
        doubled = A.score_momentum(self.rsi_w, self.rsi_w,
                                   self.hist_w, self.hist_w)
        self.assertNotEqual(self.out["score"]["momentum"], doubled)

    def test_the_two_forms_genuinely_differ_on_this_fixture(self):
        """Without this the test above could pass on a fixture where the two
        forms happen to coincide, which would make it unfailable."""
        single = A.score_momentum(self.rsi_w, None, self.hist_w, None)
        doubled = A.score_momentum(self.rsi_w, self.rsi_w,
                                   self.hist_w, self.hist_w)
        self.assertNotEqual(single, doubled)

    def test_a_missing_higher_timeframe_only_silences_its_own_arms(self):
        """Each arm is guarded independently, so dropping the higher series
        removes 1.0 for a hot slow RSI and 1.5 for the slow MACD sign, and
        changes nothing else."""
        self.assertEqual(A.score_momentum(55.0, None, 1.0, None), 5.0 + 1.5 + 1.0)
        self.assertEqual(A.score_momentum(55.0, 75.0, 1.0, 1.0),
                         5.0 + 1.5 - 1.0 + 1.0 + 1.5)
        self.assertEqual(A.score_momentum(None, None, None, None), 5.0)


class TestWeeklyPeriodsAreBarCounts(unittest.TestCase):
    """20/50/100/200 are periods on the PRIMARY series, not calendar spans."""

    def setUp(self):
        self.out, _ = run_compute(WEEKLY_SERIES, timeframe="weekly")
        self.closes = [r["c"] for r in WEEKLY_10Y]

    def test_each_average_is_that_many_weekly_bars(self):
        for n, key in ((20, "sma20"), (50, "sma50"),
                       (100, "sma100"), (200, "sma200")):
            self.assertEqual(self.out["ma"][key],
                             sum(self.closes[-n:]) / n, key)

    def test_the_two_hundred_period_average_spans_about_four_years(self):
        """The intended meaning of a weekly 200: ~4 years, not a smoothed 200
        days. Measured off the fixture's own dates rather than asserted as a
        constant."""
        span = WEEKLY_10Y[-1]["t"] - WEEKLY_10Y[-200]["t"]
        self.assertGreater(span.days, 3 * 365)
        self.assertLess(span.days, 5 * 365)

    def test_a_five_year_weekly_primary_would_leave_too_little_history(self):
        """Why the weekly range is 10y. Live on 2026-08-01, 5y/1wk returned 262
        bars and 10y/1wk returned 523; those two lengths are what the fixtures
        hold. A 200-period average consumes 199 of them.
        """
        self.assertEqual(len(WEEKLY_5Y), 262)
        self.assertEqual(len(WEEKLY_10Y), 523)
        short = setups.sma_series([r["c"] for r in WEEKLY_5Y], 200)
        long_ = setups.sma_series([r["c"] for r in WEEKLY_10Y], 200)
        self.assertEqual(len(short), 63)
        self.assertEqual(len(long_), 324)
        # 63 usable points is fewer than the window the screener ranks
        # volatility over; 324 is comfortably more.
        self.assertLess(len(short), setups.ATR_PCTILE_BARS)
        self.assertGreater(len(long_), setups.ATR_PCTILE_BARS)


class TestWeeklyStructureFollowsThePrimarySeries(unittest.TestCase):
    """Thrusts, consolidation, fractals, rejection zones, the volume profile,
    the 52-period range and the R:R gate all read the primary series, so none
    of them needed a timeframe argument. This asserts they actually did."""

    def setUp(self):
        self.out, _ = run_compute(WEEKLY_SERIES, timeframe="weekly")

    def test_the_fifty_two_period_range_is_the_last_250_weekly_bars(self):
        yr = WEEKLY_10Y[-250:]
        self.assertEqual(self.out["hi52"], max(r["h"] for r in yr))
        self.assertEqual(self.out["lo52"], min(r["l"] for r in yr))

    def test_the_range_and_the_gate_are_computed_from_weekly_bars(self):
        self.assertGreater(self.out["range"]["bars"], 0)
        self.assertIsNotNone(self.out["entry_gate"]["min_stop_1.5atr"])
        # The stop floor is 1.5x the PRIMARY ATR below the live price.
        self.assertEqual(self.out["entry_gate"]["min_stop_1.5atr"],
                         self.out["price"] - 1.5 * A.atr(WEEKLY_10Y))

    def test_the_swing_pivots_come_from_the_weekly_window(self):
        hi, lo = A.fractals(WEEKLY_10Y[-250:], 6)
        self.assertEqual([s["px"] for s in self.out["swing_highs"]],
                         [p for _, p in hi[-10:]])
        self.assertEqual([s["px"] for s in self.out["swing_lows"]],
                         [p for _, p in lo[-10:]])

    def test_the_volume_profile_is_built_from_weekly_bars(self):
        self.assertEqual(self.out["volume_nodes"],
                         A.volume_profile(WEEKLY_10Y[-250:])[:8])

    def test_the_returns_are_bar_counts_on_the_primary_series(self):
        closes = [r["c"] for r in WEEKLY_10Y]
        self.assertEqual(self.out["returns"]["1m"], A.pct_return(closes, 21))
        self.assertEqual(self.out["returns"]["3m"], A.pct_return(closes, 63))


if __name__ == "__main__":
    unittest.main()
