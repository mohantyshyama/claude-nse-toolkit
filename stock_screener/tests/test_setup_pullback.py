import os, sys, unittest
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
sys.path.insert(0, _root)
sys.path.insert(0, _here)
import setups
from fixtures import trend_series

ROWS = trend_series(120)


def result(**over):
    o = {"symbol": "TEST", "price": 101.0,
         "last_closed_bar": {"t": "2026-07-31", "v": 700_000},
         "ma": {"sma20": 100.5, "sma50": 99.0, "sma100": 95.0, "sma200": 90.0},
         "atr": {"daily": 2.0, "daily_pct": 2.0},
         "volume": {"avg20": 800_000, "avg50": 1_000_000, "dryup_ratio": 0.8,
                    "thrusts": []},
         "range": {"hi": 108.0, "lo": 98.0, "bars": 20},
         "hi52": 110.0, "lo52": 70.0,
         "rsi": {"daily": 48.0}, "macd": {"daily": {"hist": -0.1}},
         "returns": {"1m": -3.0, "3m": 9.0},
         "entry_gate": {"rr_at_current_price": 2.6, "nearest_support": 99.5},
         "score": {"total": 6.8},
         "swing_highs": swings(104.0, 110.0),
         "_rows": ROWS}
    o.update(over)
    return o


def swings(*prices):
    """compute()'s swing_highs shape: the last ten pivot highs, oldest first.

    Every fixture in this file now carries them, because the support arm reads
    them -- and an omitted key silently closes that arm, which would make the
    support-route tests pass for the wrong reason.
    """
    return [{"date": str(ROWS[-10 + i]["t"]), "px": p}
            for i, p in enumerate(prices)]


def ma(sma20=100.5, sma50=99.0, sma200=90.0):
    return {"sma20": sma20, "sma50": sma50, "sma100": 95.0, "sma200": sma200}


def gate(support=99.5):
    g = {"rr_at_current_price": 2.6}
    if support is not None:
        g["nearest_support"] = support
    return g


def vol(dryup=0.8, thrusts=()):
    return {"avg20": 800_000, "avg50": 1_000_000, "dryup_ratio": dryup,
            "thrusts": [{"date": str(ROWS[i]["t"]), "dir": d, "vol": 4_000_000,
                         "x_avg": 3.4} for i, d in thrusts]}


# A base whose MA distances land on exact percentages: sma20 = 100 makes
# |px - sma20| / sma20 * 100 equal px - 100 with no float residue, so the 3%
# and 2% ceilings can be probed one paisa either side. nearest_support stays
# far enough away that the MA route is the only one open.
def exact(price):
    return result(price=price, ma=ma(sma20=100.0, sma50=99.0, sma200=90.0),
                  entry_gate=gate(support=80.0))


# Far from every average, so the SUPPORT route is the only one open. atr 2.5
# puts the loosened reach at exactly 3.00 and the strict reach at exactly 2.50.
def far_from_ma(support, atr=2.5, price=103.5):
    return result(price=price, ma=ma(sma20=94.0, sma50=93.0, sma200=90.0),
                  atr={"daily": atr, "daily_pct": 2.0},
                  entry_gate=gate(support=support))


CTX = {"rows": ROWS, "rs": {"1m": -1.0, "3m": 4.0},
       "atr_pctile": 0.5, "sma200_rising": True, "sma50_rising": True}
FALLING = dict(CTX, sma200_rising=False)


class TestPullbackMatches(unittest.TestCase):
    def test_textbook_pullback_matches(self):
        ev = setups.match_pullback(result(), CTX)
        self.assertIsNotNone(ev)
        self.assertLessEqual(ev["dist_to_ma_pct"], 3.0)

    def test_qualifies_via_support_proximity_when_far_from_mas(self):
        """Within 1.2x ATR of structural support is an alternative route in."""
        o = result(price=103.5, ma=ma(sma20=94.0, sma50=93.0, sma200=90.0),
                   entry_gate=gate(support=102.0))
        self.assertIsNotNone(setups.match_pullback(o, CTX))

    def test_evidence_reports_every_documented_key(self):
        ev = setups.match_pullback(result(), CTX)
        self.assertEqual(set(ev), {"dist_to_ma_pct", "rsi", "dryup", "retrace_pct"})
        self.assertAlmostEqual(ev["rsi"], 48.0, places=6)
        self.assertAlmostEqual(ev["dryup"], 0.8, places=6)

    def test_distance_is_to_the_NEAREST_of_sma20_and_sma50(self):
        """min, not max and not sma20 alone. 101 sits 0.498% off sma20 (100.5)
        and 2.02% off sma50 (99); reporting either the larger or the wrong
        average changes the number, and both alternatives are under the 3%
        ceiling so no near-miss test would notice."""
        ev = setups.match_pullback(result(), CTX)
        self.assertAlmostEqual(ev["dist_to_ma_pct"], 0.4975124378, places=8)

    def test_far_BELOW_the_short_average_rejects_just_as_far_above_does(self):
        """abs(px - m), not px - m. Survivor from the first mutation run.

        Every other fixture sits above both averages, where a signed distance
        and an absolute one agree. Here 100 is 9.1% UNDER sma20 (110) and 10.5%
        over a distant sma50 (90.5): the absolute nearest is 9.1% and rejects,
        while a signed nearest is -9.1%, sails under the 3% ceiling and matches.

        The fixture has to route around the sma50 floor to exist at all -- while
        price is below sma50, `px > 0.97 * sma50` already bounds the distance to
        sma50 under 3.1%, so the only reachable version of this defect puts a
        FAR sma50 below the price and the offending average above it.
        """
        o = result(price=100.0, ma=ma(sma20=110.0, sma50=90.5, sma200=90.0),
                   entry_gate=gate(support=80.0))
        self.assertIsNone(setups.match_pullback(o, CTX))

    def test_reported_distance_is_never_negative(self):
        near = setups.match_pullback(
            result(price=100.0, ma=ma(sma20=100.5, sma50=99.0)), CTX)
        self.assertGreater(near["dist_to_ma_pct"], 0.0)

    def test_distance_is_normalised_by_the_average_not_the_price(self):
        """0.5 / 100.5 and 0.5 / 101 differ in the fourth decimal; the fixture
        above pins the former."""
        ev = setups.match_pullback(result(), CTX)
        self.assertNotAlmostEqual(ev["dist_to_ma_pct"], abs(101 - 100.5) / 101 * 100,
                                  places=8)

    def test_retrace_is_measured_across_the_52_week_span(self):
        """(hi52 - px) / (hi52 - lo52): 9 points off a 40-point span is 22.5%.
        Against the price it would be 8.9% and against hi52 alone 8.2%, both of
        which land in a different depth band inside fit_pullback."""
        self.assertAlmostEqual(setups.match_pullback(result(), CTX)["retrace_pct"],
                               22.5, places=8)

    def test_flat_52_week_span_reports_zero_retrace(self):
        """The `if span else 0.0` arm; hi52 == lo52 divides by zero otherwise."""
        ev = setups.match_pullback(result(hi52=110.0, lo52=110.0), CTX)
        self.assertIsNotNone(ev)
        self.assertAlmostEqual(ev["retrace_pct"], 0.0, places=8)

    def test_a_missing_sma20_falls_back_to_the_sma50_distance(self):
        """The `if m` filter inside the list comprehension. Without it,
        abs(px - None) raises TypeError for a name younger than 20 sessions
        that somehow reached this predicate."""
        ev = setups.match_pullback(result(price=101.0,
                                          ma=ma(sma20=None, sma50=100.0)), CTX)
        self.assertIsNotNone(ev)
        self.assertAlmostEqual(ev["dist_to_ma_pct"], 1.0, places=8)


class TestPullbackNearMisses(unittest.TestCase):
    def test_below_sma200_rejects(self):
        self.assertIsNone(setups.match_pullback(result(ma=ma(sma200=105.0)), CTX))

    def test_sma50_below_sma200_rejects(self):
        self.assertIsNone(setups.match_pullback(
            result(ma=ma(sma50=89.0, sma200=92.0)), CTX))

    def test_falling_sma200_rejects_in_both_modes(self):
        """The knife-catching guard. Not parameterised by --strict on purpose."""
        self.assertIsNone(setups.match_pullback(result(), FALLING))
        self.assertIsNone(setups.match_pullback(result(), FALLING, strict=True))

    def test_missing_sma200_rejects(self):
        self.assertIsNone(setups.match_pullback(result(ma=ma(sma200=None)), CTX))

    def test_missing_sma50_rejects(self):
        self.assertIsNone(setups.match_pullback(result(ma=ma(sma50=None)), CTX))

    def test_too_far_from_any_moving_average_or_support_rejects(self):
        self.assertIsNone(setups.match_pullback(
            result(price=107.0, entry_gate=gate(support=90.0)), CTX))

    def test_lost_the_sma50_rejects(self):
        o = result(price=95.0, ma=ma())
        self.assertIsNone(setups.match_pullback(o, CTX))

    def test_rsi_below_38_rejects(self):
        self.assertIsNone(setups.match_pullback(result(rsi={"daily": 33.0}), CTX))

    def test_rsi_above_62_rejects(self):
        self.assertIsNone(setups.match_pullback(result(rsi={"daily": 70.0}), CTX))

    def test_missing_rsi_rejects(self):
        """The `r is None` arm; the chained comparison raises otherwise."""
        self.assertIsNone(setups.match_pullback(result(rsi={"daily": None}), CTX))

    def test_volume_not_drying_up_rejects(self):
        self.assertIsNone(setups.match_pullback(result(volume=vol(dryup=1.5)), CTX))

    def test_missing_dryup_ratio_rejects(self):
        self.assertIsNone(setups.match_pullback(result(volume=vol(dryup=None)), CTX))

    def test_recent_down_thrust_rejects(self):
        self.assertIsNone(setups.match_pullback(
            result(volume=vol(thrusts=[(-2, "down")])), CTX))

    def test_recent_up_thrust_does_not_reject(self):
        """The sibling arm -- a high-volume accumulation day during a pullback
        is the tell you want, not a disqualifier."""
        self.assertIsNotNone(setups.match_pullback(
            result(volume=vol(thrusts=[(-2, "up")])), CTX))


class TestPullbackSupportRoute(unittest.TestCase):
    """`near_ma > ceiling and not near_sup` -- a two-armed OR written as an AND
    of negations, so all four combinations need a case."""

    def test_near_ma_and_near_support_matches(self):
        self.assertIsNotNone(setups.match_pullback(result(), CTX))

    def test_near_ma_but_far_from_support_matches(self):
        self.assertIsNotNone(setups.match_pullback(
            result(entry_gate=gate(support=60.0)), CTX))

    def test_far_from_ma_but_near_support_matches(self):
        self.assertIsNotNone(setups.match_pullback(far_from_ma(102.0), CTX))

    def test_far_from_both_rejects(self):
        self.assertIsNone(setups.match_pullback(far_from_ma(80.0), CTX))

    def test_support_reach_is_inclusive_at_1_2_atr(self):
        """`<=`, and the multiple is applied to the DAILY ATR. atr 2.5 puts the
        reach at exactly 3.00 points from 103.50."""
        self.assertIsNotNone(setups.match_pullback(far_from_ma(100.5), CTX))
        self.assertIsNone(setups.match_pullback(far_from_ma(100.49), CTX))

    def test_support_above_the_price_counts_too(self):
        """abs(), not px - sup: overhead support that price has just poked
        through is the same distance and must be treated the same."""
        self.assertIsNotNone(setups.match_pullback(far_from_ma(106.5), CTX))
        self.assertIsNone(setups.match_pullback(far_from_ma(106.51), CTX))

    def test_missing_support_level_closes_the_support_route(self):
        """The `sup and` arm. entry_gate may omit nearest_support entirely, and
        `abs(px - None)` would raise rather than reject."""
        self.assertIsNone(setups.match_pullback(
            far_from_ma(None), CTX))

    def test_missing_atr_closes_the_support_route(self):
        """The `atr_d and` arm: with no ATR there is no reach to compute."""
        o = far_from_ma(102.0)
        o["atr"] = {"daily": 0.0, "daily_pct": 2.0}
        self.assertIsNone(setups.match_pullback(o, CTX))
        o["atr"] = {"daily": None, "daily_pct": 2.0}
        self.assertIsNone(setups.match_pullback(o, CTX))


class TestPullbackSupportArmNeedsRoomBelowASwingHigh(unittest.TestCase):
    """A name printing new highs cannot enter through the support arm.

    CHOLAFIN ranked PULLBACK #1 having closed +4.29% at 1849.90, 1.3% under its
    52-week high on results. It was 3.55% above its 20DMA -- past PULLBACK's own
    3.0% ceiling -- so the moving-average arm had already rejected it, and it
    entered here: nearest_support was the 20DMA it had just run away from, 63.4
    points off against a 1.2xATR allowance of 69.5. "Near support" is trivially
    true for a name that just left its averages behind, because the average it
    left behind IS the nearest support.
    """

    #: Far from every average, so only the support arm is open, and priced right
    #: under the 110 swing high with support in reach. ATR 2.5 puts the loosened
    #: margin at 2.50 points and the strict margin at 3.75.
    def at_high(self, price, support=None, **over):
        o = result(price=price,
                   ma=ma(sma20=94.0, sma50=93.0, sma200=90.0),
                   atr={"daily": 2.5, "daily_pct": 2.4},
                   entry_gate=gate(support=price - 1.0 if support is None
                                   else support))
        o.update(over)
        return o

    def test_the_fixture_really_does_enter_through_the_support_arm(self):
        """Otherwise the rejection below could be the MA ceiling firing and the
        new condition could be deleted without a failure."""
        o = self.at_high(103.5)
        near_ma = min(abs(o["price"] - m) / m * 100
                      for m in (o["ma"]["sma20"], o["ma"]["sma50"]))
        self.assertGreater(near_ma, setups.THRESHOLDS["PULLBACK"]["ma_dist_pct"][0])
        self.assertIsNotNone(setups.match_pullback(o, CTX))

    def test_a_name_at_a_new_high_cannot_enter_as_a_pullback(self):
        """109.9 against a 110 swing high with ATR 2.5: support is 0.9 away, so
        the old arm opened. It has retraced 0.25% of its 52-week range."""
        o = self.at_high(109.9)
        self.assertLessEqual(abs(o["price"] - o["entry_gate"]["nearest_support"]),
                             1.2 * o["atr"]["daily"])
        self.assertIsNone(setups.match_pullback(o, CTX))

    def test_a_name_above_every_recent_swing_high_cannot_either(self):
        """The max(), not the latest: price above all ten pivots is the literal
        definition of printing new highs."""
        o = self.at_high(112.0, swing_highs=swings(104.0, 110.0))
        self.assertIsNone(setups.match_pullback(o, CTX))

    def test_the_margin_is_measured_from_the_HIGHEST_recent_swing(self):
        """max(), not the latest pivot, and the pair separates them.

        The latest swing here is 106.0 and the highest 120.0. At 105.0 with ATR
        2.5 the arm needs 2.50 points of room: the 120 pivot gives it, the 106
        one does not. A name that has come off a real high is a pullback even if
        it has since printed a lower pivot underneath the decline.
        """
        self.assertIsNotNone(setups.match_pullback(
            self.at_high(105.0, swing_highs=swings(120.0, 106.0)), CTX))
        self.assertIsNone(setups.match_pullback(
            self.at_high(105.0, swing_highs=swings(106.0)), CTX))

    def test_the_margin_is_inclusive_at_one_atr(self):
        """`<=`: exactly one ATR below the swing high is far enough. 110 - 2.5
        is 107.50, and a paisa higher is not."""
        self.assertIsNotNone(setups.match_pullback(self.at_high(107.50), CTX))
        self.assertIsNone(setups.match_pullback(self.at_high(107.51), CTX))

    def test_strict_asks_for_a_bigger_margin(self):
        """1.5 ATR is 3.75 points, so the strict threshold sits at 106.25."""
        o = self.at_high(107.0)
        self.assertIsNotNone(setups.match_pullback(o, CTX))
        self.assertIsNone(setups.match_pullback(o, CTX, strict=True))
        self.assertIsNotNone(setups.match_pullback(self.at_high(106.25), CTX,
                                                   strict=True))
        self.assertIsNone(setups.match_pullback(self.at_high(106.26), CTX,
                                                strict=True))

    def test_the_moving_average_arm_is_untouched_by_this(self):
        """The ruling is about the support arm alone. A name at a new high that
        is genuinely resting ON its 20-day -- a flat base at highs -- still
        qualifies, and the support route is closed here so only the MA arm can
        be letting it through."""
        o = result(price=109.9, ma=ma(sma20=108.0, sma50=100.0, sma200=90.0),
                   atr={"daily": 2.5, "daily_pct": 2.4},
                   entry_gate=gate(support=80.0))
        self.assertIsNotNone(setups.match_pullback(o, CTX))
        self.assertIsNone(setups.match_pullback(
            dict(o, ma=ma(sma20=94.0, sma50=93.0, sma200=90.0)), CTX))

    def test_no_swing_highs_at_all_closes_the_support_arm(self):
        """"Cannot judge" must close the arm it guards, never open it. Both the
        missing-key and the empty-list shapes."""
        o = self.at_high(103.5)
        del o["swing_highs"]
        self.assertIsNone(setups.match_pullback(o, CTX))
        self.assertIsNone(setups.match_pullback(self.at_high(103.5,
                                                             swing_highs=[]), CTX))

    def test_swing_entries_without_a_price_are_skipped_not_crashed_on(self):
        o = self.at_high(103.5, swing_highs=[{"date": "2026-01-01", "px": None},
                                             {"date": "2026-02-01", "px": 110.0}])
        self.assertIsNotNone(setups.match_pullback(o, CTX))

    def test_the_rejection_names_the_swing_high_condition(self):
        diag = {}
        setups.match_pullback(self.at_high(109.9), CTX, diag=diag)
        (label, _), = diag.items()
        self.assertIn("swing high", label)

    def test_the_helper_reads_the_margin_it_is_given(self):
        """_below_recent_swing_high on its own, where the arithmetic is
        countable, including both no-data arms."""
        o = {"swing_highs": swings(104.0, 110.0)}
        self.assertTrue(setups._below_recent_swing_high(o, 107.5, 2.5, 1.0))
        self.assertFalse(setups._below_recent_swing_high(o, 107.51, 2.5, 1.0))
        self.assertTrue(setups._below_recent_swing_high(o, 106.25, 2.5, 1.5))
        self.assertFalse(setups._below_recent_swing_high(o, 106.26, 2.5, 1.5))
        self.assertFalse(setups._below_recent_swing_high({}, 50.0, 2.5, 1.0))
        self.assertFalse(setups._below_recent_swing_high(o, 50.0, None, 1.0))
        self.assertFalse(setups._below_recent_swing_high(o, 50.0, 0.0, 1.0))


class TestPullbackBoundaries(unittest.TestCase):
    def test_price_must_be_strictly_above_sma200(self):
        """`<=` not `<`. sma50 is lifted above sma200 in both cases so the NEXT
        clause cannot be the one doing the rejecting -- with the fixture's
        sma50 of 99 an sma200 near 101 trips `sma50 <= sma200` first and the
        accept side can never hold."""
        self.assertIsNone(setups.match_pullback(
            result(ma=ma(sma50=101.5, sma200=101.0)), CTX))
        self.assertIsNotNone(setups.match_pullback(
            result(ma=ma(sma50=101.5, sma200=100.99)), CTX))

    def test_sma50_must_be_strictly_above_sma200(self):
        self.assertIsNone(setups.match_pullback(
            result(ma=ma(sma50=99.0, sma200=99.0)), CTX))
        self.assertIsNotNone(setups.match_pullback(
            result(ma=ma(sma50=99.0, sma200=98.99)), CTX))

    def test_ma_distance_ceiling_is_inclusive_at_three_percent(self):
        self.assertIsNotNone(setups.match_pullback(exact(103.0), CTX))
        self.assertIsNone(setups.match_pullback(exact(103.01), CTX))

    def test_three_percent_below_sma50_is_the_floor(self):
        """`px <= sma50 * 0.97`, isolated.

        The brief's fixture for this guard (price 95) is already 4.04% from the
        nearest average, so it rejects at the DISTANCE ceiling and the 0.97
        multiplier could be deleted without a failure. Here sma20 sits right on
        the price, so the distance route is wide open and the sma50 floor is the
        only thing in play. sma50 = 100 makes 0.97 * sma50 exactly 97.0.
        """
        below = result(price=97.0, ma=ma(sma20=97.0, sma50=100.0, sma200=90.0))
        self.assertIsNone(setups.match_pullback(below, CTX))
        at = result(price=97.01, ma=ma(sma20=97.0, sma50=100.0, sma200=90.0))
        self.assertIsNotNone(setups.match_pullback(at, CTX))

    def test_rsi_window_is_inclusive_at_both_ends(self):
        for r in (38.0, 62.0):
            self.assertIsNotNone(setups.match_pullback(result(rsi={"daily": r}), CTX),
                                 "rsi %s" % r)
        for r in (37.99, 62.01):
            self.assertIsNone(setups.match_pullback(result(rsi={"daily": r}), CTX),
                              "rsi %s" % r)

    def test_dryup_ceiling_is_exclusive_at_1_1(self):
        self.assertIsNone(setups.match_pullback(result(volume=vol(dryup=1.1)), CTX))
        self.assertIsNotNone(setups.match_pullback(result(volume=vol(dryup=1.099)),
                                                   CTX))

    def test_down_thrust_window_is_eight_bars_loosened(self):
        self.assertIsNone(setups.match_pullback(
            result(volume=vol(thrusts=[(-8, "down")])), CTX))
        self.assertIsNotNone(setups.match_pullback(
            result(volume=vol(thrusts=[(-9, "down")])), CTX))


class TestPullbackStrict(unittest.TestCase):
    def test_strict_narrows_the_moving_average_distance(self):
        o = result(price=103.0)   # 2.5% above sma20
        self.assertIsNotNone(setups.match_pullback(o, CTX))
        self.assertIsNone(setups.match_pullback(o, CTX, strict=True))

    def test_strict_ma_distance_ceiling_is_inclusive_at_two_percent(self):
        self.assertIsNotNone(setups.match_pullback(exact(102.0), CTX, strict=True))
        self.assertIsNone(setups.match_pullback(exact(102.01), CTX, strict=True))

    def test_strict_narrows_the_support_reach_to_one_atr(self):
        """atr 2.5: loosened reaches 3.00 points, strict only 2.50."""
        self.assertIsNotNone(setups.match_pullback(far_from_ma(101.0), CTX,
                                                   strict=True))
        self.assertIsNone(setups.match_pullback(far_from_ma(100.9), CTX,
                                                strict=True))
        self.assertIsNotNone(setups.match_pullback(far_from_ma(100.9), CTX))

    def test_strict_narrows_the_rsi_band(self):
        o = result(rsi={"daily": 39.0})
        self.assertIsNotNone(setups.match_pullback(o, CTX))
        self.assertIsNone(setups.match_pullback(o, CTX, strict=True))

    def test_strict_rsi_window_is_inclusive_at_both_ends(self):
        for r in (40.0, 58.0):
            self.assertIsNotNone(setups.match_pullback(result(rsi={"daily": r}), CTX,
                                                       strict=True), "rsi %s" % r)
        for r in (39.99, 58.01):
            self.assertIsNotNone(setups.match_pullback(result(rsi={"daily": r}), CTX),
                                 "loosened rsi %s" % r)
            self.assertIsNone(setups.match_pullback(result(rsi={"daily": r}), CTX,
                                                    strict=True), "strict rsi %s" % r)

    def test_strict_requires_a_deeper_dryup(self):
        o = result(volume=vol(dryup=1.0))
        self.assertIsNotNone(setups.match_pullback(o, CTX))
        self.assertIsNone(setups.match_pullback(o, CTX, strict=True))
        self.assertIsNotNone(setups.match_pullback(result(volume=vol(dryup=0.999)),
                                                   CTX, strict=True))

    def test_strict_widens_the_down_thrust_window_to_ten_bars(self):
        """The one threshold whose STRICT value is the LARGER number: a longer
        lookback rejects more, not fewer."""
        o = result(volume=vol(thrusts=[(-9, "down")]))
        self.assertIsNotNone(setups.match_pullback(o, CTX))
        self.assertIsNone(setups.match_pullback(o, CTX, strict=True))
        self.assertIsNone(setups.match_pullback(
            result(volume=vol(thrusts=[(-10, "down")])), CTX, strict=True))
        self.assertIsNotNone(setups.match_pullback(
            result(volume=vol(thrusts=[(-11, "down")])), CTX, strict=True))

    def test_strict_defaults_to_false_when_omitted(self):
        self.assertIsNotNone(setups.match_pullback(result(rsi={"daily": 39.0}), CTX))


class TestPullbackFit(unittest.TestCase):
    def ev(self, **over):
        e = {"dist_to_ma_pct": 0.5, "rsi": 48.0, "dryup": 0.8, "retrace_pct": 30.0}
        e.update(over)
        return e

    def test_closer_to_the_moving_average_scores_higher(self):
        near = setups.fit_pullback(setups.match_pullback(result(price=100.8), CTX))
        far = setups.fit_pullback(setups.match_pullback(result(price=103.4), CTX))
        self.assertTrue(0.0 <= far < near <= 10.0)

    def test_rsi_nearer_fifty_scores_higher(self):
        self.assertGreater(setups.fit_pullback(self.ev(rsi=50.0)),
                           setups.fit_pullback(self.ev(rsi=39.0)))

    def test_rsi_term_is_symmetric_about_fifty(self):
        """abs(rsi - 50), not rsi - 50: an overbought-side reading of 58 and an
        oversold-side reading of 42 are equally far from neutral. Without this a
        signed distance would band 42 as 'better than perfect'."""
        self.assertAlmostEqual(setups.fit_pullback(self.ev(rsi=58.0)),
                               setups.fit_pullback(self.ev(rsi=42.0)), places=6)

    def test_deeper_dryup_scores_higher(self):
        self.assertGreater(setups.fit_pullback(self.ev(dryup=0.7)),
                           setups.fit_pullback(self.ev(dryup=1.05)))

    def test_weights_are_thirty_five_twenty_five_twenty_twenty(self):
        """dist 0.5 -> 10, |rsi-50| = 2 -> 10, dryup 0.8 -> 10, retrace 30 -> 10.
        0.35*10 + 0.25*10 + 0.20*10 + 0.20*10 = 10.0. The second case moves one
        term at a time so the individual weights, not just their sum, are
        pinned: dist 2.5 -> 6 costs 0.35*4 = 1.4, giving 8.6.
        """
        self.assertAlmostEqual(setups.fit_pullback(self.ev()), 10.0, places=6)
        self.assertAlmostEqual(setups.fit_pullback(self.ev(dist_to_ma_pct=2.5)), 8.6,
                               places=6)
        self.assertAlmostEqual(setups.fit_pullback(self.ev(rsi=62.0)), 8.75,
                               places=6)
        self.assertAlmostEqual(setups.fit_pullback(self.ev(dryup=0.9)), 9.6,
                               places=6)
        self.assertAlmostEqual(setups.fit_pullback(self.ev(retrace_pct=60.0)), 8.8,
                               places=6)

    def test_every_distance_cut_is_reachable(self):
        cuts = [(1.0, 10), (2.0, 8), (3.0, 6)]
        for i, (dist, sub) in enumerate(cuts):
            self.assertAlmostEqual(setups.fit_pullback(self.ev(dist_to_ma_pct=dist)),
                                   round(0.35 * sub + 6.5, 2), places=6,
                                   msg="at cut %s" % dist)
            above = cuts[i + 1][1] if i + 1 < len(cuts) else 0.0
            self.assertAlmostEqual(
                setups.fit_pullback(self.ev(dist_to_ma_pct=dist + 0.001)),
                round(0.35 * above + 6.5, 2), places=6,
                msg="just above cut %s" % dist)

    def test_distance_falls_through_to_zero_for_a_support_only_match(self):
        """The fall-through arm of band_desc IS reachable here, unlike in the
        other fits: a name that qualified via the support route can sit 10%
        from every average."""
        self.assertAlmostEqual(setups.fit_pullback(self.ev(dist_to_ma_pct=10.1)),
                               6.5, places=6)

    def test_every_rsi_cut_is_reachable(self):
        cuts = [(5.0, 10), (10.0, 8), (99.0, 5)]
        for i, (gap, sub) in enumerate(cuts):
            self.assertAlmostEqual(setups.fit_pullback(self.ev(rsi=50.0 + gap)),
                                   round(3.5 + 0.25 * sub + 4.0, 2), places=6,
                                   msg="at cut %s" % gap)
            above = cuts[i + 1][1] if i + 1 < len(cuts) else 0.0
            self.assertAlmostEqual(
                setups.fit_pullback(self.ev(rsi=50.0 + gap + 0.001)),
                round(3.5 + 0.25 * above + 4.0, 2), places=6,
                msg="just above cut %s" % gap)

    def test_every_dryup_cut_is_reachable(self):
        cuts = [(0.80, 10), (0.95, 8), (1.10, 5)]
        for i, (dry, sub) in enumerate(cuts):
            self.assertAlmostEqual(setups.fit_pullback(self.ev(dryup=dry)),
                                   round(3.5 + 2.5 + 0.20 * sub + 2.0, 2), places=6,
                                   msg="at cut %s" % dry)
            above = cuts[i + 1][1] if i + 1 < len(cuts) else 0.0
            self.assertAlmostEqual(setups.fit_pullback(self.ev(dryup=dry + 0.001)),
                                   round(3.5 + 2.5 + 0.20 * above + 2.0, 2), places=6,
                                   msg="just above cut %s" % dry)

    def test_retrace_depth_ladder_has_six_reachable_arms(self):
        """The band falls away on BOTH sides of the 25-45 fib window now.

        Every boundary is probed at the cut and one tick the other side, so no
        arm can widen or narrow undetected. The deep side is unchanged; the
        shallow side used to award a flat 8 for anything under 25%, which is how
        a 4.4% retracement outscored a textbook 20% one.
        """
        for pct, sub in [(0.0, 3), (4.4, 3), (9.99, 3), (10.0, 5),
                         (17.99, 5), (18.0, 8), (24.99, 8), (25.0, 10),
                         (38.2, 10), (45.0, 10), (45.01, 7), (55.0, 7),
                         (55.01, 4), (90.0, 4)]:
            self.assertAlmostEqual(setups.fit_pullback(self.ev(retrace_pct=pct)),
                                   round(8.0 + 0.20 * sub, 2), places=6,
                                   msg="retrace %s" % pct)

    def test_a_trivial_retracement_no_longer_scores_near_the_top(self):
        """CHOLAFIN's 4.4% against a textbook 20%. The old band gave both 8/10
        and the shallow one led the table on the strength of it."""
        self.assertLess(setups.fit_pullback(self.ev(retrace_pct=4.4)),
                        setups.fit_pullback(self.ev(retrace_pct=20.0)))
        self.assertAlmostEqual(setups.retrace_depth(4.4), 3.0, places=9)
        self.assertAlmostEqual(setups.retrace_depth(20.0), 8.0, places=9)

    def test_the_ladder_peaks_in_the_fib_zone_and_falls_away_both_sides(self):
        """The shape itself, not a list of points: monotone up to the fib zone,
        flat across it, monotone down after. A band that merely lowered the
        shallow end without keeping the ideal in the middle would pass the
        point-by-point test above by moving every number down."""
        peak = setups.retrace_depth(38.2)
        self.assertEqual(peak, 10.0)
        rising = [setups.retrace_depth(x) for x in (0.0, 12.0, 20.0, 30.0)]
        self.assertEqual(rising, sorted(rising))
        falling = [setups.retrace_depth(x) for x in (30.0, 50.0, 70.0)]
        self.assertEqual(falling, sorted(falling, reverse=True))

    def test_fit_stays_inside_zero_to_ten(self):
        worst = self.ev(dist_to_ma_pct=50.0, rsi=200.0, dryup=5.0, retrace_pct=99.0)
        self.assertAlmostEqual(setups.fit_pullback(worst), 0.8, places=6)
        self.assertTrue(0.0 <= setups.fit_pullback(worst) <= 10.0)


class TestPullbackThresholdTable(unittest.TestCase):
    def test_registry_carries_the_spec_numbers(self):
        self.assertEqual(setups.THRESHOLDS["PULLBACK"],
                         {"ma_dist_pct": (3.0, 2.0), "atr_mult_to_support": (1.2, 1.0),
                          "swing_margin_atr": (1.0, 1.5),
                          "rsi_lo": (38.0, 40.0), "rsi_hi": (62.0, 58.0),
                          "dryup": (1.1, 1.0), "thrust_bars": (8, 10)})

    def test_sma200_rising_is_absent_from_the_table(self):
        """It must not be parameterised: loosening it would not widen the
        screen, it would change what the screen means."""
        self.assertNotIn("sma200_rising", setups.THRESHOLDS["PULLBACK"])

    def test_strict_is_never_looser_than_loosened(self):
        th = setups.THRESHOLDS["PULLBACK"]
        for key in ("ma_dist_pct", "atr_mult_to_support", "rsi_hi", "dryup"):
            self.assertLessEqual(th[key][1], th[key][0], key)
        for key in ("rsi_lo", "thrust_bars", "swing_margin_atr"):
            self.assertGreaterEqual(th[key][1], th[key][0], key)

    def test_anything_matching_strict_also_matches_loosened(self):
        checked = 0
        for price in (97.0, 97.01, 100.8, 102.0, 102.01, 103.0, 103.01, 107.0):
            for rsi_val in (37.99, 39.99, 40.0, 48.0, 58.0, 58.01, 62.01):
                for dry in (0.7, 0.999, 1.0, 1.099, 1.1):
                    for sup in (None, 80.0, 99.5, 102.0):
                        for th in ((), ((-9, "down"),), ((-2, "down"),),
                                   ((-2, "up"),)):
                            o = result(price=price, rsi={"daily": rsi_val},
                                       volume=vol(dryup=dry, thrusts=th),
                                       entry_gate=gate(support=sup))
                            if setups.match_pullback(o, CTX, strict=True) is not None:
                                checked += 1
                                self.assertIsNotNone(
                                    setups.match_pullback(o, CTX, strict=False),
                                    "strict matched but loosened did not: px=%s "
                                    "rsi=%s dryup=%s sup=%s thrusts=%s"
                                    % (price, rsi_val, dry, sup, th))
        self.assertGreater(checked, 0, "grid produced no strict matches at all")

    def test_the_support_arm_nests_across_the_swing_margin_too(self):
        """The grid above never opens the support arm at a price near a swing
        high, so neither swing_margin_atr threshold is walked across its own
        boundary. This one holds everything else clean and varies exactly the
        price, the swing highs and the ATR the margin is measured in."""
        checked = 0
        for price in (100.0, 103.5, 106.25, 106.26, 107.5, 107.51, 109.9):
            for highs in (swings(104.0, 110.0), swings(120.0, 106.0), swings()):
                for atr_d in (1.0, 2.5, 5.0):
                    o = result(price=price,
                               ma=ma(sma20=94.0, sma50=93.0, sma200=90.0),
                               atr={"daily": atr_d, "daily_pct": 2.4},
                               entry_gate=gate(support=price - 0.5),
                               swing_highs=highs)
                    if setups.match_pullback(o, CTX, strict=True) is not None:
                        checked += 1
                        self.assertIsNotNone(
                            setups.match_pullback(o, CTX, strict=False),
                            "strict matched but loosened did not: px=%s "
                            "highs=%s atr=%s" % (price, highs, atr_d))
        self.assertGreater(checked, 0, "grid produced no strict matches at all")


if __name__ == "__main__":
    unittest.main()
