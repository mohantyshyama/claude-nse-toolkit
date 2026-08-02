import os, sys, unittest
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
sys.path.insert(0, _root)
sys.path.insert(0, _here)
import setups
from engine import A
from fixtures import bar, trend_series

ROWS = trend_series(120)


def result(**over):
    o = {"symbol": "TEST", "price": 105.0,
         "last_closed_bar": {"t": "2026-07-31", "v": 1_400_000},
         "ma": {"sma20": 103.0, "sma50": 101.0, "sma100": 99.0, "sma200": 100.0},
         "atr": {"daily": 2.0, "daily_pct": 2.0},
         "volume": {"avg20": 1_300_000, "avg50": 1_000_000, "dryup_ratio": 1.3,
                    "thrusts": []},
         "range": {"hi": 106.0, "lo": 96.0, "bars": 16},
         "hi52": 108.0, "lo52": 80.0,
         "rsi": {"daily": 58.0}, "macd": {"daily": {"hist": 0.4}},
         "returns": {"1m": 5.0, "3m": 11.0},
         "entry_gate": {"rr_at_current_price": 1.8},
         "score": {"total": 6.1},
         "_rows": ROWS}
    o.update(over)
    return o


def ma(sma50=101.0, sma200=100.0):
    return {"sma20": 103.0, "sma50": sma50, "sma100": 99.0, "sma200": sma200}


def ctx(bars_since_cross=15, **over):
    c = {"rows": trend_series(260), "rs": {"1m": 2.0, "3m": 6.0},
         "atr_pctile": 0.5, "sma200_rising": True, "sma50_rising": True,
         "bars_since_cross": bars_since_cross, "vol_expansion": 1.35}
    c.update(over)
    return c


# ----------------------------------------------------------- series builders

def rows_from(closes, vol=1_000_000, span=1.0):
    return [bar(i, c, c + span, c - span, c, vol) for i, c in enumerate(closes)]


def vshape(down_n, up_n, top=300.0, down_step=1.0, up_step=2.0, vol=1_000_000):
    """A V: `down_n` falling bars then `up_n` rising ones.

    The 50-day average crosses back above the 200-day a fixed 59 bars into the
    recovery, so bars_since_cross is exactly `up_n - 59` for any up_n from 59 to
    118. That closed form is what lets the cross thresholds be probed at the
    bar rather than approximately.
    """
    rows, c = [], top
    for _ in range(down_n):
        rows.append(bar(len(rows), c, c + 1, c - 1, c, vol))
        c -= down_step
    for _ in range(up_n):
        c += up_step
        rows.append(bar(len(rows), c, c + 1, c - 1, c, vol))
    return rows


def crossed(bars_ago, vol=1_000_000):
    return vshape(200, 59 + bars_ago, vol=vol)


def whipsaw_closes(up1=58, dip=7, dstep=30.0, up2=4):
    """A recovery, a sharp shakeout, then a snap-back -- two golden crosses
    inside the 61-point search window, at 10 bars ago and 0 bars ago.

    Every single-cross fixture leaves the scan DIRECTION and the `break`
    unverified: a forward scan, or a backward scan with no break, reports the
    same answer when there is only one crossing to find. Both were survivors in
    the first mutation run.
    """
    closes = [300.0 - i for i in range(200)]
    c = closes[-1]
    for _ in range(up1):
        c += 2.0
        closes.append(c)
    for _ in range(dip):
        c -= dstep
        closes.append(c)
    for _ in range(up2):
        c += dstep * 1.2
        closes.append(c)
    return closes


# Two hundred flat bars make the 50- and 200-day averages EXACTLY equal at the
# first bar both are defined for; the rising tail then lifts the 50-day above.
# That is the only shape in which the cross test's `a[i-1] <= b[i-1]` differs
# from `<`, and the age is a known 29.
EQUAL_THEN_RISING = [100.0] * 200 + [100.0 + i for i in range(1, 31)]


def span_rows(specs, vol=1_000_000):
    """(count, half-range) segments at a constant price, for ATR shaping."""
    rows = []
    for n, sp in specs:
        for _ in range(n):
            rows.append(bar(len(rows), 100.0, 100.0 + sp, 100.0 - sp, 100.0, vol))
    return rows


# 18 bars above the old level then 8 below turns the 200-day average down
# recently while leaving it higher than it was 20 bars ago. So the slope reads
# RISING at a 20-bar window and FALLING at a 10-bar one -- the only shape that
# can prove SLOPE_BARS is 20 rather than any other number.
SLOPE_CLOSES = [100.0] * 200 + [150.0] * 18 + [50.0] * 8


class TestTurnMatches(unittest.TestCase):
    def test_recent_golden_cross_matches(self):
        ev = setups.match_turn(result(), ctx())
        self.assertIsNotNone(ev)
        self.assertEqual(ev["bars_since_cross"], 15)

    def test_evidence_reports_every_documented_key(self):
        ev = setups.match_turn(result(), ctx())
        self.assertEqual(set(ev), {"bars_since_cross", "macd_hist",
                                   "sma200_rising", "vol_expansion"})
        self.assertAlmostEqual(ev["macd_hist"], 0.4, places=6)
        self.assertAlmostEqual(ev["vol_expansion"], 1.35, places=6)
        self.assertIs(ev["sma200_rising"], True)

    def test_a_falling_200_day_is_recorded_but_does_not_reject(self):
        """Unlike PULLBACK, TURN does not gate on the 200-day slope -- the whole
        point is that the trend may only just have turned. It is carried as
        evidence and priced by fit_turn instead."""
        ev = setups.match_turn(result(), ctx(sma200_rising=False))
        self.assertIsNotNone(ev)
        self.assertIs(ev["sma200_rising"], False)

    def test_slope_evidence_is_coerced_to_a_real_bool(self):
        ev = setups.match_turn(result(), ctx(sma200_rising=1))
        self.assertIs(ev["sma200_rising"], True)

    def test_missing_volume_expansion_defaults_to_one(self):
        """The `or 1.0` arm, both sides. A ctx built before the cross was known
        carries no expansion figure, and fit_turn must still band it."""
        c = ctx()
        del c["vol_expansion"]
        self.assertAlmostEqual(setups.match_turn(result(), c)["vol_expansion"],
                               1.0, places=6)
        self.assertAlmostEqual(
            setups.match_turn(result(), ctx(vol_expansion=0))["vol_expansion"],
            1.0, places=6)
        self.assertAlmostEqual(
            setups.match_turn(result(), ctx(vol_expansion=2.4))["vol_expansion"],
            2.4, places=6)


class TestTurnNearMisses(unittest.TestCase):
    def test_no_cross_rejects(self):
        self.assertIsNone(setups.match_turn(result(), ctx(bars_since_cross=None)))

    def test_absent_cross_key_rejects(self):
        """`.get`, not `[...]`: a ctx missing the key must reject, not raise."""
        c = ctx()
        del c["bars_since_cross"]
        self.assertIsNone(setups.match_turn(result(), c))

    def test_stale_cross_rejects(self):
        self.assertIsNone(setups.match_turn(result(), ctx(bars_since_cross=60)))

    def test_price_below_sma200_rejects(self):
        self.assertIsNone(setups.match_turn(result(price=97.0), ctx()))

    def test_price_above_sma50_but_below_sma200_rejects(self):
        """Isolates the sma200 clause: the brief's fixture (97) is under BOTH
        averages, so the second half of the `or` could be deleted unnoticed."""
        self.assertIsNone(setups.match_turn(
            result(price=100.0, ma=ma(sma50=99.0, sma200=100.0)), ctx()))

    def test_price_above_sma200_but_below_sma50_rejects(self):
        self.assertIsNone(setups.match_turn(
            result(price=100.0, ma=ma(sma50=101.0, sma200=99.0)), ctx()))

    def test_missing_sma50_rejects(self):
        self.assertIsNone(setups.match_turn(result(ma=ma(sma50=None)), ctx()))

    def test_missing_sma200_rejects(self):
        self.assertIsNone(setups.match_turn(result(ma=ma(sma200=None)), ctx()))

    def test_negative_macd_histogram_rejects(self):
        self.assertIsNone(setups.match_turn(result(macd={"daily": {"hist": -0.3}}),
                                            ctx()))

    def test_missing_macd_histogram_rejects(self):
        """`hist is None`; `None <= 0` raises on Python 3."""
        self.assertIsNone(setups.match_turn(result(macd={"daily": {"hist": None}}),
                                            ctx()))

    def test_rsi_below_48_rejects(self):
        self.assertIsNone(setups.match_turn(result(rsi={"daily": 45.0}), ctx()))

    def test_missing_rsi_rejects(self):
        self.assertIsNone(setups.match_turn(result(rsi={"daily": None}), ctx()))

    def test_too_close_to_the_52_week_low_rejects(self):
        """A cross that happens while price is still at the lows is a dead-cat
        bounce, not a trend turn."""
        self.assertIsNone(setups.match_turn(result(price=105.0, lo52=100.0), ctx()))

    def test_missing_52_week_low_rejects_without_dividing_by_zero(self):
        """The `if o["lo52"] else 0.0` arm: no low means no measurable advance
        off it, and 0.0 is below every floor. Deleting the guard raises."""
        self.assertIsNone(setups.match_turn(result(lo52=0.0), ctx()))
        self.assertIsNone(setups.match_turn(result(lo52=None), ctx()))


class TestTurnBoundaries(unittest.TestCase):
    def test_cross_recency_ceiling_is_inclusive_at_45_bars(self):
        self.assertIsNotNone(setups.match_turn(result(), ctx(bars_since_cross=45)))
        self.assertIsNone(setups.match_turn(result(), ctx(bars_since_cross=46)))

    def test_a_cross_on_the_last_bar_is_accepted(self):
        """bars_since_cross of 0 is the freshest possible signal, not a falsy
        stand-in for "no cross" -- `bars is None`, not `not bars`."""
        self.assertIsNotNone(setups.match_turn(result(), ctx(bars_since_cross=0)))

    def test_price_must_be_strictly_above_both_averages(self):
        self.assertIsNone(setups.match_turn(result(price=101.0), ctx()))   # == sma50
        self.assertIsNone(setups.match_turn(
            result(price=100.0, ma=ma(sma50=99.0, sma200=100.0)), ctx()))
        self.assertIsNotNone(setups.match_turn(result(price=101.01), ctx()))

    def test_macd_histogram_must_be_strictly_positive(self):
        self.assertIsNone(setups.match_turn(result(macd={"daily": {"hist": 0.0}}),
                                            ctx()))
        self.assertIsNotNone(setups.match_turn(
            result(macd={"daily": {"hist": 0.01}}), ctx()))

    def test_rsi_floor_is_exclusive_at_48(self):
        """`<=`: exactly 48 is not above 48."""
        self.assertIsNone(setups.match_turn(result(rsi={"daily": 48.0}), ctx()))
        self.assertIsNotNone(setups.match_turn(result(rsi={"daily": 48.01}), ctx()))

    def test_off_low_floor_is_inclusive_at_12_percent(self):
        """lo52 = 100 makes the percentage exact: price 112 is 12.00% off."""
        self.assertIsNotNone(setups.match_turn(result(price=112.0, lo52=100.0),
                                               ctx()))
        self.assertIsNone(setups.match_turn(result(price=111.99, lo52=100.0), ctx()))


class TestTurnStrict(unittest.TestCase):
    def test_strict_narrows_cross_recency(self):
        self.assertIsNotNone(setups.match_turn(result(), ctx(bars_since_cross=38)))
        self.assertIsNone(setups.match_turn(result(), ctx(bars_since_cross=38),
                                            strict=True))

    def test_strict_cross_ceiling_is_inclusive_at_30_bars(self):
        self.assertIsNotNone(setups.match_turn(result(), ctx(bars_since_cross=30),
                                               strict=True))
        self.assertIsNone(setups.match_turn(result(), ctx(bars_since_cross=31),
                                            strict=True))

    def test_strict_requires_20_percent_off_the_low(self):
        o = result(price=105.0, lo52=92.0)   # 14% off
        self.assertIsNotNone(setups.match_turn(o, ctx()))
        self.assertIsNone(setups.match_turn(o, ctx(), strict=True))

    def test_strict_off_low_floor_is_inclusive_at_20_percent(self):
        self.assertIsNotNone(setups.match_turn(result(price=120.0, lo52=100.0),
                                               ctx(), strict=True))
        self.assertIsNone(setups.match_turn(result(price=119.99, lo52=100.0),
                                            ctx(), strict=True))

    def test_strict_raises_the_rsi_floor_to_50(self):
        o = result(rsi={"daily": 49.0})
        self.assertIsNotNone(setups.match_turn(o, ctx()))
        self.assertIsNone(setups.match_turn(o, ctx(), strict=True))
        self.assertIsNone(setups.match_turn(result(rsi={"daily": 50.0}), ctx(),
                                            strict=True))
        self.assertIsNotNone(setups.match_turn(result(rsi={"daily": 50.01}), ctx(),
                                               strict=True))

    def test_strict_defaults_to_false_when_omitted(self):
        self.assertIsNotNone(setups.match_turn(result(), ctx(bars_since_cross=38)))


class TestTurnFit(unittest.TestCase):
    def ev(self, **over):
        e = {"bars_since_cross": 15, "macd_hist": 0.4, "sma200_rising": True,
             "vol_expansion": 1.35}
        e.update(over)
        return e

    def test_fresher_cross_scores_higher(self):
        fresh = setups.fit_turn(setups.match_turn(result(), ctx(bars_since_cross=6)))
        stale = setups.fit_turn(setups.match_turn(result(), ctx(bars_since_cross=40)))
        self.assertTrue(0.0 <= stale < fresh <= 10.0)

    def test_rising_200_day_scores_higher(self):
        self.assertGreater(setups.fit_turn(self.ev(sma200_rising=True)),
                           setups.fit_turn(self.ev(sma200_rising=False)))

    def test_volume_expansion_scores_higher(self):
        self.assertGreater(setups.fit_turn(self.ev(vol_expansion=1.5)),
                           setups.fit_turn(self.ev(vol_expansion=1.0)))

    def test_weights_are_thirty_five_thirty_twenty_fifteen(self):
        """cross 15 -> 9, slope True -> 10, expansion 1.35 -> 10, macd + -> 10.
        0.35*9 + 0.30*10 + 0.20*10 + 0.15*10 = 3.15 + 6.5 = 9.65. Each further
        case moves exactly one term, pinning its weight rather than the sum.
        """
        self.assertAlmostEqual(setups.fit_turn(self.ev()), 9.65, places=6)
        self.assertAlmostEqual(setups.fit_turn(self.ev(bars_since_cross=5)), 10.0,
                               places=6)
        self.assertAlmostEqual(setups.fit_turn(self.ev(sma200_rising=False)), 7.85,
                               places=6)
        self.assertAlmostEqual(setups.fit_turn(self.ev(vol_expansion=1.2)), 9.25,
                               places=6)
        self.assertAlmostEqual(setups.fit_turn(self.ev(macd_hist=-0.1)), 9.05,
                               places=6)

    def test_slope_bonus_is_exactly_six_points_of_sub_score(self):
        self.assertAlmostEqual(setups.fit_turn(self.ev(sma200_rising=True))
                               - setups.fit_turn(self.ev(sma200_rising=False)),
                               1.8, places=6)

    def test_macd_bonus_is_exactly_four_points_of_sub_score(self):
        """The negative arm is unreachable through match_turn, which requires a
        positive histogram, so it can only be shown here."""
        self.assertAlmostEqual(setups.fit_turn(self.ev(macd_hist=0.1))
                               - setups.fit_turn(self.ev(macd_hist=-0.1)),
                               0.6, places=6)
        self.assertAlmostEqual(setups.fit_turn(self.ev(macd_hist=0.0)),
                               setups.fit_turn(self.ev(macd_hist=-5.0)), places=6)

    def test_every_recency_cut_is_reachable(self):
        cuts = [(10, 10), (20, 9), (30, 7), (45, 5)]
        for i, (bars, sub) in enumerate(cuts):
            self.assertAlmostEqual(setups.fit_turn(self.ev(bars_since_cross=bars)),
                                   round(0.35 * sub + 6.5, 2), places=6,
                                   msg="at cut %s" % bars)
            above = cuts[i + 1][1] if i + 1 < len(cuts) else 0.0
            self.assertAlmostEqual(
                setups.fit_turn(self.ev(bars_since_cross=bars + 1)),
                round(0.35 * above + 6.5, 2), places=6,
                msg="just above cut %s" % bars)

    def test_every_expansion_cut_is_reachable(self):
        cuts = [(1.30, 10), (1.10, 8), (0.0, 5)]
        for i, (mult, sub) in enumerate(cuts):
            self.assertAlmostEqual(setups.fit_turn(self.ev(vol_expansion=mult)),
                                   round(3.15 + 3.0 + 0.20 * sub + 1.5, 2), places=6,
                                   msg="at cut %s" % mult)
            below = cuts[i + 1][1] if i + 1 < len(cuts) else 0.0
            self.assertAlmostEqual(
                setups.fit_turn(self.ev(vol_expansion=mult - 0.001)),
                round(3.15 + 3.0 + 0.20 * below + 1.5, 2), places=6,
                msg="just below cut %s" % mult)

    def test_fit_stays_inside_zero_to_ten(self):
        best = self.ev(bars_since_cross=0, vol_expansion=5.0, sma200_rising=True,
                       macd_hist=1.0)
        worst = self.ev(bars_since_cross=45, vol_expansion=-1.0,
                        sma200_rising=False, macd_hist=-1.0)
        self.assertAlmostEqual(setups.fit_turn(best), 10.0, places=6)
        self.assertAlmostEqual(setups.fit_turn(worst), 3.85, places=6)
        self.assertTrue(0.0 <= setups.fit_turn(worst) <= 10.0)


class TestTurnThresholdTable(unittest.TestCase):
    def test_registry_carries_the_spec_numbers(self):
        self.assertEqual(setups.THRESHOLDS["TURN"],
                         {"cross_bars": (45, 30), "rsi_lo": (48.0, 50.0),
                          "off_low_pct": (12.0, 20.0)})

    def test_strict_is_never_looser_than_loosened(self):
        th = setups.THRESHOLDS["TURN"]
        self.assertLessEqual(th["cross_bars"][1], th["cross_bars"][0])
        self.assertGreaterEqual(th["rsi_lo"][1], th["rsi_lo"][0])
        self.assertGreaterEqual(th["off_low_pct"][1], th["off_low_pct"][0])

    def test_anything_matching_strict_also_matches_loosened(self):
        checked = 0
        for bars in (None, 0, 30, 31, 45, 46):
            for rsi_val in (48.0, 49.0, 50.0, 50.01, 58.0):
                for lo in (None, 100.0, 92.0, 80.0):
                    for hist in (-0.1, 0.0, 0.4):
                        o = result(rsi={"daily": rsi_val}, lo52=lo,
                                   macd={"daily": {"hist": hist}})
                        c = ctx(bars_since_cross=bars)
                        if setups.match_turn(o, c, strict=True) is not None:
                            checked += 1
                            self.assertIsNotNone(
                                setups.match_turn(o, c, strict=False),
                                "strict matched but loosened did not: bars=%s "
                                "rsi=%s lo52=%s hist=%s" % (bars, rsi_val, lo, hist))
        self.assertGreater(checked, 0, "grid produced no strict matches at all")


class TestCtxConstants(unittest.TestCase):
    def test_cross_lookback_exceeds_the_widest_recency_threshold(self):
        """A lookback at or below the threshold would silently cap the screen:
        crosses inside the accepted window would report None."""
        self.assertGreater(setups.CROSS_LOOKBACK,
                           max(setups.THRESHOLDS["TURN"]["cross_bars"]))

    def test_constants_are_the_documented_values(self):
        self.assertEqual(setups.CROSS_LOOKBACK, 60)
        self.assertEqual(setups.SLOPE_BARS, 20)
        self.assertEqual(setups.ATR_PCTILE_BARS, 126)


class TestBuildCtxSlopes(unittest.TestCase):
    def test_detects_a_golden_cross_and_reports_slopes(self):
        """Rising series: the 50D sits above the 200D throughout, so there is no
        cross INSIDE the window and bars_since_cross must be None -- not 0."""
        c = setups._ctx_from_rows(trend_series(260), {"1m": 1.0, "3m": 2.0})
        self.assertTrue(c["sma200_rising"])
        self.assertTrue(c["sma50_rising"])
        self.assertIsNone(c["bars_since_cross"])

    def test_falling_series_reports_both_slopes_down(self):
        falling = rows_from([500.0 - i for i in range(260)])
        c = setups._ctx_from_rows(falling, {})
        self.assertFalse(c["sma200_rising"])
        self.assertFalse(c["sma50_rising"])

    def test_slope_window_is_twenty_bars(self):
        """SLOPE_BARS is load-bearing, not decorative.

        This series turned down about ten bars ago but is still well above where
        it stood twenty bars ago. A 20-bar window therefore reads RISING and a
        10-bar window reads FALLING, so the constant cannot be changed without
        flipping both flags here.
        """
        c = setups._ctx_from_rows(rows_from(SLOPE_CLOSES), {})
        self.assertTrue(c["sma200_rising"])
        self.assertTrue(c["sma50_rising"])
        closes = SLOPE_CLOSES
        s200 = setups.sma_series(closes, 200)
        s50 = setups.sma_series(closes, 50)
        self.assertGreater(s200[-1], s200[-1 - setups.SLOPE_BARS])
        self.assertLess(s200[-1], s200[-11])      # a 10-bar window would say No
        self.assertLess(s50[-1], s50[-11])

    def test_a_series_shorter_than_the_slope_window_is_not_rising(self):
        """`len(s200) > SLOPE_BARS`: with 210 bars the 200-day average has only
        11 points, too few to measure a 20-bar slope. It must report False
        rather than index off the front of the list."""
        c = setups._ctx_from_rows(rows_from([100.0 + i for i in range(210)]), {})
        self.assertFalse(c["sma200_rising"])
        self.assertTrue(c["sma50_rising"])

    def test_slope_window_boundary_needs_more_than_twenty_points(self):
        """221 closes give the 200-day average exactly 22 points, one more than
        the 21 the comparison indexes -- the accept side of the same guard."""
        c = setups._ctx_from_rows(rows_from([100.0 + i for i in range(221)]), {})
        self.assertTrue(c["sma200_rising"])

    def test_exactly_twenty_average_points_is_still_too_few(self):
        """The reject side of `len(s200) > SLOPE_BARS` AT the boundary.

        219 closes give the 200-day average exactly 20 points, and the slope
        comparison indexes s200[-21]. `>=` would reach one past the front of the
        list and raise IndexError, so this is the case that separates the two.
        """
        c = setups._ctx_from_rows(rows_from([100.0 + i for i in range(219)]), {})
        self.assertFalse(c["sma200_rising"])

    def test_a_flat_average_is_not_rising(self):
        """`>`, not `>=`: an average at exactly the level it held twenty bars
        ago has not turned up. Constant closes make both averages perfectly
        flat, which no trending fixture can show."""
        c = setups._ctx_from_rows(rows_from([100.0] * 250), {})
        self.assertFalse(c["sma200_rising"])
        self.assertFalse(c["sma50_rising"])

    def test_a_short_series_cannot_measure_the_fifty_day_slope(self):
        """`len(s50) > SLOPE_BARS`, reject side. 60 closes give the 50-day
        average 11 points; dropping the length guard indexes s50[-21] and
        raises. The 200-day version of this guard is covered above."""
        c = setups._ctx_from_rows(rows_from([100.0 + i for i in range(60)]), {})
        self.assertFalse(c["sma50_rising"])
        self.assertFalse(c["sma200_rising"])

    def test_exactly_twenty_fifty_day_points_is_still_too_few(self):
        """The 50-day twin of the boundary above: 69 closes give the average
        exactly 20 points, where `>=` would index s50[-21] and raise."""
        c = setups._ctx_from_rows(rows_from([100.0 + i for i in range(69)]), {})
        self.assertFalse(c["sma50_rising"])
        c = setups._ctx_from_rows(rows_from([100.0 + i for i in range(70)]), {})
        self.assertTrue(c["sma50_rising"])

    def test_a_series_too_short_for_any_average_is_flat_and_crossless(self):
        c = setups._ctx_from_rows(rows_from([100.0] * 10), {})
        self.assertFalse(c["sma200_rising"])
        self.assertFalse(c["sma50_rising"])
        self.assertIsNone(c["bars_since_cross"])
        self.assertAlmostEqual(c["atr_pctile"], 1.0, places=9)


class TestBuildCtxRunPct(unittest.TestCase):
    """`run_pct` is the 5-session return LEADER's extension guard reads.

    It is derived here rather than read off o["returns"], whose shortest window
    is a month -- a name can be flat for three weeks and gap 13% in five days,
    which is the shape the guard exists to catch.
    """

    def test_the_window_is_five_moves_back_not_six(self):
        """closes[-1 - RUN_BARS], so with RUN_BARS = 5 the baseline is the close
        five bars before the last one. Powers of two make an off-by-one visible:
        the last six closes are 32, 34, 36, 38, 40, 42, so 42 against 32 is
        31.25% while 42 against the bar before it (30) would be 40%."""
        closes = [10.0 + 2 * i for i in range(120)]
        closes[-6:] = [32.0, 34.0, 36.0, 38.0, 40.0, 42.0]
        closes[-7] = 30.0
        c = setups._ctx_from_rows(rows_from(closes), {})
        self.assertAlmostEqual(c["run_pct"], (42.0 / 32.0 - 1) * 100, places=9)

    def test_the_constant_is_five_sessions(self):
        self.assertEqual(setups.RUN_BARS, 5)

    def test_a_flat_five_sessions_is_zero_not_none(self):
        """0.0 is a measurement and must be judged; None means unmeasurable.
        `if run` in place of `if run is not None` conflates them."""
        c = setups._ctx_from_rows(rows_from([100.0] * 120), {})
        self.assertIsNotNone(c["run_pct"])
        self.assertAlmostEqual(c["run_pct"], 0.0, places=9)

    def test_a_decline_reports_a_negative_run(self):
        c = setups._ctx_from_rows(rows_from([200.0 - i for i in range(120)]), {})
        self.assertLess(c["run_pct"], 0.0)
        self.assertAlmostEqual(c["run_pct"], (81.0 / 86.0 - 1) * 100, places=9)

    def test_a_series_too_short_to_measure_reports_none(self):
        """`len(closes) > RUN_BARS`, both sides. Six closes have a fifth-back
        bar; five do not, and indexing anyway would silently wrap to the front
        of the list and report a made-up run."""
        self.assertIsNone(setups._ctx_from_rows(
            rows_from([100.0 + i for i in range(5)]), {})["run_pct"])
        self.assertIsNotNone(setups._ctx_from_rows(
            rows_from([100.0 + i for i in range(6)]), {})["run_pct"])

    def test_a_zero_baseline_close_reports_none_rather_than_dividing_by_zero(self):
        closes = [100.0 + i for i in range(120)]
        closes[-6] = 0.0
        self.assertIsNone(setups._ctx_from_rows(rows_from(closes), {})["run_pct"])


class TestBuildCtxCross(unittest.TestCase):
    def test_finds_the_cross_when_one_occurs(self):
        """The brief builds the recovery leg 120 bars long, which puts the cross
        61 bars back -- one bar past CROSS_LOOKBACK's reach -- so its own
        assertIsNotNone cannot hold. 110 bars lands the cross 50 back, inside
        the window, and the age is asserted exactly rather than as `> 0`, which
        any positive constant would satisfy.
        """
        falling = [dict(r, o=300 - i, h=301 - i, l=299 - i, c=300 - i)
                   for i, r in enumerate(trend_series(200))]
        rising = [dict(r, o=100 + i * 2, h=101 + i * 2, l=99 + i * 2, c=100 + i * 2)
                  for i, r in enumerate(trend_series(110))]
        c = setups._ctx_from_rows(falling + rising, {"1m": 1.0, "3m": 2.0})
        self.assertIsNotNone(c["bars_since_cross"])
        self.assertEqual(c["bars_since_cross"], 50)

    def test_cross_age_is_counted_in_bars_from_the_last_one(self):
        """The exact arithmetic of `len(a) - 1 - i`, at four separate ages.

        An off-by-one, or counting from the START of the window instead of the
        end, changes every one of these. The brief asserts only `> 0`, which any
        positive constant satisfies.
        """
        for age in (0, 1, 5, 15, 44, 59):
            self.assertEqual(setups._ctx_from_rows(crossed(age), {})["bars_since_cross"],
                             age, "age %s" % age)

    def test_a_cross_beyond_the_lookback_is_not_reported(self):
        """CROSS_LOOKBACK caps the search. The window holds 61 points and the
        scan needs a preceding point to compare against, so 59 bars is the
        oldest age reachable and 60 falls off the end."""
        self.assertEqual(setups._ctx_from_rows(crossed(59), {})["bars_since_cross"], 59)
        self.assertIsNone(setups._ctx_from_rows(crossed(60), {})["bars_since_cross"])
        self.assertIsNone(setups._ctx_from_rows(crossed(75), {})["bars_since_cross"])

    def test_a_death_cross_is_not_reported_as_a_turn(self):
        """`a[i] > b[i] and a[i - 1] <= b[i - 1]` -- direction matters. Dropping
        either half would report the 50D crossing DOWN through the 200D as a
        golden cross, which is the exact opposite signal."""
        rise_then_fall = vshape(200, 120, top=100.0, down_step=-1.0, up_step=-2.0)
        self.assertIsNone(setups._ctx_from_rows(rise_then_fall, {})["bars_since_cross"])

    def test_no_cross_when_the_fast_average_never_gets_below(self):
        self.assertIsNone(
            setups._ctx_from_rows(rows_from([100.0 + i for i in range(320)]),
                                  {})["bars_since_cross"])

    def test_the_most_recent_of_two_crosses_wins(self):
        """Scan direction and the `break`, together.

        This series crosses at 10 bars ago and again at 0. Scanning forwards
        would report 10; scanning backwards without breaking would overwrite
        down to 10 as well. Only a backwards scan that stops at the first hit
        reports 0, and 0 is the right answer -- the screen ranks on how FRESH
        the turn is.
        """
        closes = whipsaw_closes()
        c = setups._ctx_from_rows(rows_from(closes), {})
        self.assertEqual(c["bars_since_cross"], 0)

        a = setups.sma_series(closes, 50)
        b = setups.sma_series(closes, 200)
        n = min(len(a), len(b), setups.CROSS_LOOKBACK + 1)
        a, b = a[-n:], b[-n:]
        ages = [len(a) - 1 - i for i in range(len(a) - 1, 0, -1)
                if a[i] > b[i] and a[i - 1] <= b[i - 1]]
        self.assertEqual(ages, [0, 10], "fixture must contain exactly two crosses")

    def test_an_average_touching_from_below_counts_as_a_cross(self):
        """`a[i - 1] <= b[i - 1]`, not `<`.

        Two hundred flat bars leave the averages exactly equal at the first bar
        both exist for; the rising tail lifts the 50-day above on the next. With
        a strict `<` the crossing is missed entirely and the name never screens.
        """
        c = setups._ctx_from_rows(rows_from(EQUAL_THEN_RISING), {})
        self.assertEqual(c["bars_since_cross"], 29)

    def test_a_series_with_no_two_hundred_day_average_reports_no_cross(self):
        """The `if s50 and s200` guard, at the only input that can distinguish
        it: 150 closes give a 50-day average but no 200-day one. Dropping the
        guard slices the two series to mismatched lengths and raises."""
        c = setups._ctx_from_rows(rows_from([100.0 + i for i in range(150)]), {})
        self.assertIsNone(c["bars_since_cross"])
        self.assertTrue(c["sma50_rising"])
        self.assertFalse(c["sma200_rising"])


class TestBuildCtxAtrPercentile(unittest.TestCase):
    LOW_TAIL = span_rows([(200, 5.0), (130, 1.0)])

    def test_percentile_is_between_zero_and_one(self):
        c = setups._ctx_from_rows(trend_series(260), {"1m": None, "3m": None})
        self.assertTrue(0.0 <= c["atr_pctile"] <= 1.0)

    def test_a_compressed_tail_ranks_near_the_bottom(self):
        """Five months of wide bars then six of tight ones: today's ATR is the
        lowest reading in its own trailing window, so the percentile is the
        smallest non-zero value the window can express."""
        c = setups._ctx_from_rows(self.LOW_TAIL, {})
        self.assertAlmostEqual(c["atr_pctile"], 1.0 / 126.0, places=12)

    def test_percentile_window_is_one_hundred_and_twenty_six_bars(self):
        """The same series ranks 1/126 over the documented window and 1/100 over
        a 100-bar one, so ATR_PCTILE_BARS cannot be changed silently."""
        atrs = setups.atr_series(self.LOW_TAIL, 14)
        self.assertAlmostEqual(
            setups._ctx_from_rows(self.LOW_TAIL, {})["atr_pctile"],
            sum(1 for x in atrs[-126:] if x <= atrs[-1]) / len(atrs[-126:]),
            places=12)
        self.assertNotAlmostEqual(
            setups._ctx_from_rows(self.LOW_TAIL, {})["atr_pctile"],
            sum(1 for x in atrs[-100:] if x <= atrs[-1]) / len(atrs[-100:]),
            places=6)

    def test_todays_reading_counts_itself(self):
        """`<=`, not `<`. Today's ATR is always in its own window, so a strict
        comparison would report 0.0 here instead of 1/126 and every COILED
        candidate would look maximally compressed."""
        self.assertGreater(setups._ctx_from_rows(self.LOW_TAIL, {})["atr_pctile"], 0.0)

    def test_an_expanding_tail_ranks_at_the_top(self):
        wide = span_rows([(200, 1.0), (130, 5.0)])
        self.assertAlmostEqual(setups._ctx_from_rows(wide, {})["atr_pctile"], 1.0,
                               places=9)

    def test_no_atr_history_ranks_as_maximally_extended(self):
        """The `if window else 1.0` arm. Below 16 bars atr_series returns
        nothing; 1.0 rejects every COILED candidate, which is the safe verdict
        when volatility cannot be ranked. Deleting the guard raises IndexError.
        """
        self.assertAlmostEqual(
            setups._ctx_from_rows(rows_from([100.0] * 12), {})["atr_pctile"],
            1.0, places=9)


class TestBuildCtxVolumeExpansion(unittest.TestCase):
    def marked(self, age=15, after=3_000_000, before=1_000_000, outside=9_999_999):
        """Post-cross bars, the 50 bars before them, and everything earlier get
        three distinct volumes, so a window that slips by even one bar drags in
        the outside figure and changes the ratio beyond recognition."""
        rows = crossed(age)
        n = len(rows)
        for i, row in enumerate(rows):
            if i >= n - age - 1:
                row["v"] = after
            elif i >= n - age - 51:
                row["v"] = before
            else:
                row["v"] = outside
        return rows

    def test_expansion_is_post_cross_mean_over_the_fifty_bars_before(self):
        self.assertAlmostEqual(
            setups._ctx_from_rows(self.marked(), {})["vol_expansion"], 3.0, places=9)

    def test_contraction_reports_a_ratio_below_one(self):
        self.assertAlmostEqual(
            setups._ctx_from_rows(self.marked(after=500_000), {})["vol_expansion"],
            0.5, places=9)

    def test_window_edges_are_exact(self):
        """Same shape at three cross ages, including a cross on the very last
        bar, where the post-cross window is a single row."""
        for age in (0, 1, 40):
            self.assertAlmostEqual(
                setups._ctx_from_rows(self.marked(age=age), {})["vol_expansion"],
                3.0, places=9, msg="age %s" % age)

    def test_before_window_is_fifty_bars_not_a_shorter_tail(self):
        """A GRADED before-window, because a uniform one cannot see its length.

        The 50 bars before the cross run at 1.0m for thirty bars then 4.0m for
        twenty, averaging 2.2m. Post-cross volume is 3.0m, so the ratio is
        3.0 / 2.2 = 1.3636. Measured over only the last 20 of those bars the
        baseline would be 4.0m and the ratio 0.75 -- a name that expanded would
        read as one that dried up.
        """
        rows = crossed(15)
        n, age = len(rows), 15
        for i, row in enumerate(rows):
            if i >= n - age - 1:
                row["v"] = 3_000_000
            elif i >= n - age - 21:
                row["v"] = 4_000_000
            elif i >= n - age - 51:
                row["v"] = 1_000_000
            else:
                row["v"] = 9_999_999
        self.assertAlmostEqual(setups._ctx_from_rows(rows, {})["vol_expansion"],
                               3.0 / 2.2, places=9)

    def test_no_cross_means_no_expansion_figure(self):
        c = setups._ctx_from_rows(trend_series(260), {})
        self.assertIsNone(c["bars_since_cross"])
        self.assertAlmostEqual(c["vol_expansion"], 1.0, places=9)

    def test_the_length_half_of_the_expansion_guard_is_unreachable(self):
        """DEAD CODE, pinned rather than removed.

        `len(rows) > bars_since_cross + 50` can never be False once a cross has
        been found: a cross needs a 200-day average, so rows >= 200, while
        bars_since_cross is capped at 59 by CROSS_LOOKBACK, making the largest
        right-hand side 109. Mutation confirms it -- deleting that half of the
        condition kills no test, and cannot.

        This test states the invariant so the clause stops being load-bearing
        only deliberately: if CROSS_LOOKBACK ever grows past 150, the guard
        becomes live and this assertion fails first.
        """
        self.assertLess(setups.CROSS_LOOKBACK + 50, 200)

    def test_zero_volume_before_the_cross_falls_back_to_one(self):
        """The `if mb else 1.0` arm -- a suspended counter reports zero volume,
        and the ratio would be a ZeroDivisionError."""
        self.assertAlmostEqual(
            setups._ctx_from_rows(self.marked(before=0), {})["vol_expansion"],
            1.0, places=9)


class TestBuildCtxPassThrough(unittest.TestCase):
    def test_rows_and_relative_strength_are_carried_verbatim(self):
        rows = trend_series(260)
        rs = {"1m": 3.5, "3m": -2.0}
        c = setups._ctx_from_rows(rows, rs)
        self.assertIs(c["rows"], rows)
        self.assertIs(c["rs"], rs)

    def test_context_carries_exactly_the_documented_keys(self):
        """Every predicate reads from this dict; a missing key is a KeyError at
        scan time and an extra one is a silently unused computation."""
        self.assertEqual(set(setups._ctx_from_rows(trend_series(260), {})),
                         {"rows", "rs", "atr_pctile", "sma200_rising",
                          "sma50_rising", "bars_since_cross", "vol_expansion",
                          "run_pct"})


class TestBuildCtxPublicEntry(unittest.TestCase):
    """build_ctx() wiring: fetch, align, stash the rows, then derive.

    A.fetch memoises on (symbol, range, interval, suffix), so seeding _CACHE
    exercises the real call path with no network. Neighbouring keys are seeded
    with a different, much shorter series so a wrong period or interval returns
    obviously wrong data instead of being served the series under test.
    """
    WRONG_ARGS = (("1y", "1d", ".NS"), ("5y", "1d", ".NS"), ("2y", "1wk", ".NS"),
                  ("2y", "1d", ""))

    def setUp(self):
        self.rows = crossed(15)
        self.keys = []
        for key, rows in [(("LYNX", "2y", "1d", ".NS"), self.rows)] + \
                         [(("LYNX",) + args, trend_series(10)) for args in self.WRONG_ARGS]:
            A._CACHE[key] = (rows, {})
            self.keys.append(key)

    def tearDown(self):
        for key in self.keys:
            A._CACHE.pop(key, None)

    def scored(self, index=-1):
        return {"symbol": "LYNX",
                "last_closed_bar": {"t": str(self.rows[index]["t"])}}

    def test_returns_the_same_context_the_row_builder_would(self):
        o = self.scored()
        rs = {"1m": 1.0, "3m": 2.0}
        got = setups.build_ctx(o, rs)
        want = setups._ctx_from_rows(self.rows, rs)
        self.assertEqual(got["bars_since_cross"], want["bars_since_cross"])
        self.assertEqual(got["bars_since_cross"], 15)
        self.assertEqual(got["sma200_rising"], want["sma200_rising"])
        self.assertAlmostEqual(got["atr_pctile"], want["atr_pctile"], places=12)
        self.assertIs(got["rs"], rs)

    def test_stashes_the_aligned_rows_on_the_scored_dict(self):
        """_no_down_thrust dates its window off o["_rows"]; without this write
        every thrust check would silently abstain."""
        o = self.scored()
        ctx_ = setups.build_ctx(o, {})
        self.assertIn("_rows", o)
        self.assertIs(o["_rows"], ctx_["rows"])
        self.assertEqual(len(o["_rows"]), len(self.rows))

    def test_rows_are_truncated_at_the_last_closed_bar(self):
        """The partial in-progress bar the engine discarded must not come back
        in through this door: three unclosed bars, three fewer rows, and a
        cross that is correspondingly three bars older."""
        o = self.scored(index=-4)
        ctx_ = setups.build_ctx(o, {})
        self.assertEqual(len(ctx_["rows"]), len(self.rows) - 3)
        self.assertEqual(str(ctx_["rows"][-1]["t"]), o["last_closed_bar"]["t"])
        self.assertEqual(ctx_["bars_since_cross"], 12)
        self.assertIs(o["_rows"], ctx_["rows"])

    def test_the_context_it_builds_drives_the_predicates(self):
        """End to end: a real ctx, not a literal, reaching match_turn."""
        o = self.scored()
        ctx_ = setups.build_ctx(o, {"1m": 2.0, "3m": 6.0})
        scored = dict(result(), symbol="LYNX", _rows=o["_rows"])
        self.assertIsNotNone(setups.match_turn(scored, ctx_))
        self.assertEqual(setups.match_turn(scored, ctx_)["bars_since_cross"], 15)


if __name__ == "__main__":
    unittest.main()
