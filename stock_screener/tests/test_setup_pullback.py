import os, sys, unittest
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
sys.path.insert(0, _root)
sys.path.insert(0, _here)
import setups
from fixtures import trend_series

# The advance trades at ADVANCE_VOL and the retracement at half of it, so the
# pullback-volume gate reads ~0.5 and clears the loosened 0.90 ceiling and the
# strict 0.75 one alike. Every pre-existing case in this file therefore still
# turns on the condition it was written for; the gate itself is probed by
# TestPullbackVolumeAgainstTheAdvance, which sets the two legs deliberately.
#
# The light tail starts at ROWS[-9], which is the bar swings() dates the HIGHER
# of its two pivots on -- the pivot _retrace_swing picks and the bar the
# retracement leg therefore begins at. A tail measured from anywhere else would
# leave advance bars inside the pullback leg or the reverse, and the ratio would
# stop meaning what the gate says it means.
ADVANCE_VOL = 1_000_000
PULLBACK_VOL = 500_000
#: The volume on the reversal bar rows_for() substitutes for the last one. Named
#: rather than inlined because it lands INSIDE the retracement leg and so is a
#: term in every pullback-volume expectation in this file.
REVERSAL_VOL = 1_000_000
ROWS = trend_series(120, vol=ADVANCE_VOL)
for _bar in ROWS[-9:]:
    _bar["v"] = PULLBACK_VOL


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


# ud_ratio 1.60 bands to 8 on the shared accumulation ladder -- mid-rung, so a
# dropped term is visible. PULLBACK does not GATE on this ratio (it gates on the
# retracement's volume against the advance's), so the value only reaches the Fit.
CTX = {"rows": ROWS, "rs": {"1m": -1.0, "3m": 4.0},
       "atr_pctile": 0.5, "sma200_rising": True, "sma50_rising": True,
       # ud_weighted 1.30 and ud_20 1.55 alongside it: three DIFFERENT
       # numbers, so a fit term reading the wrong key, or a gate reading the
       # 50-bar ratio where it means the 20-bar one, changes the answer. Both
       # clear the 1.0 distribution floor, and 1.55/1.60 bands "steady", so
       # every pre-existing case here still turns on the condition it was
       # written for rather than on a trend penalty.
       "ud_ratio": 1.60, "ud_weighted": 1.30, "ud_20": 1.55}
FALLING = dict(CTX, sma200_rising=False)


def clean_reversal_bar(o):
    """A textbook reversal bar for THIS fixture's own support levels.

    It dips a paisa THROUGH the highest candidate level sitting under the
    fixture's price, closes back at that price, and closes three quarters of the
    way up its own range -- so it clears the loosened 0.50 floor and the strict
    0.60 one alike, and clears any support tolerance down to zero.

    Returns None when the fixture has no level below its price at all. There is
    nothing to reject off in that case and the bar is left alone, which is what
    those fixtures are asserting anyway.
    """
    px = o["price"]
    levels = [lv for lv in (o["ma"].get("sma20"), o["ma"].get("sma50"),
                            (o.get("entry_gate") or {}).get("nearest_support"))
              if lv is not None and lv < px]
    if not levels:
        return None
    low = max(levels) - 0.01
    reach = px - low
    return {"o": px - reach * 0.5, "h": px + reach / 3.0, "l": low, "c": px,
            "v": REVERSAL_VOL}


def rows_for(o):
    """ROWS with its LAST bar replaced by this fixture's clean reversal bar.

    One shared 120-bar series cannot be consistent with fixtures priced anywhere
    from 80 to 112 -- trend_series' final bar sits at 219 and reaches no support
    any of them names. Only the last bar is replaced: the one before it stays at
    219 and can never qualify by accident, so the loosened two-bar window is
    exercised only by the tests that build it deliberately.
    """
    rows = list(ROWS)
    bar = clean_reversal_bar(o)
    if bar is not None:
        rows[-1] = dict(bar, t=rows[-1]["t"])
    return rows


def obar(o, h, l, c, v=1_000_000):
    """One bar in analyze.fetch()'s shape, minus the date rows_ending supplies."""
    return {"o": o, "h": h, "l": l, "c": c, "v": v}


#: A bar that can never be a reversal for any fixture in this file: it sits at
#: 219, hundreds of points above every candidate support, so `low <= L + tol`
#: is false for all of them. Used to fill the window slots a test is not
#: exercising, so a pass can only come from the bar the test built.
DEAD_BAR = obar(218.0, 220.0, 218.0, 219.0)


def rows_ending(*tail):
    """ROWS with its final len(tail) bars replaced, oldest first.

    Only the OHLCV is taken; each bar keeps the date it is replacing, so the
    thrust dates and the swing dates go on meaning what they meant.
    """
    rows = list(ROWS)
    for i, b in enumerate(tail, start=len(rows) - len(tail)):
        rows[i] = dict(b, t=rows[i]["t"])
    return rows


def pull(o, ctx=None, strict=False, diag=None):
    """match_pullback against bars consistent with the fixture it is given.

    Every pre-existing case in this file predates the reversal gate and was
    written to turn on something else; handing each one a clean reversal bar
    keeps it turning on that something else. The reversal gate itself is tested
    by TestPullbackNeedsAReversalAtSupport, which builds its bars by hand.
    """
    return setups.match_pullback(o, dict(CTX if ctx is None else ctx,
                                         rows=rows_for(o)), strict, diag)


class TestPullbackMatches(unittest.TestCase):
    def test_textbook_pullback_matches(self):
        ev = pull(result(), CTX)
        self.assertIsNotNone(ev)
        self.assertLessEqual(ev["dist_to_ma_pct"], 3.0)

    def test_qualifies_via_support_proximity_when_far_from_mas(self):
        """Within 1.2x ATR of structural support is an alternative route in."""
        o = result(price=103.5, ma=ma(sma20=94.0, sma50=93.0, sma200=90.0),
                   entry_gate=gate(support=102.0))
        self.assertIsNotNone(pull(o, CTX))

    def test_evidence_reports_every_documented_key(self):
        ev = pull(result(), CTX)
        self.assertEqual(set(ev), {"dist_to_ma_pct", "rsi", "dryup",
                                   "close_position", "retrace_pct",
                                   "pullback_vol_ratio", "ud_ratio",
                                   "ud_weighted", "ud_20",
                                   "retrace_of_52w_range_pct"})
        self.assertAlmostEqual(ev["ud_ratio"], 1.60, places=6)
        self.assertAlmostEqual(ev["ud_weighted"], 1.30, places=6)
        self.assertAlmostEqual(ev["ud_20"], 1.55, places=6)
        # The nine-bar retracement leg is eight tail bars at PULLBACK_VOL plus
        # the clean reversal bar rows_for() substitutes in, which carries
        # REVERSAL_VOL of its own; the thirty-bar advance is all ADVANCE_VOL.
        # Spelled out rather than written as 0.5, because the substituted bar is
        # exactly the sort of detail a rounded literal would bury.
        self.assertAlmostEqual(
            ev["pullback_vol_ratio"],
            (8 * PULLBACK_VOL + REVERSAL_VOL) / 9 / ADVANCE_VOL, places=6)

    def test_an_unmeasurable_ratio_reaches_the_evidence_as_none(self):
        """PULLBACK gates on the retracement's volume against the advance's, NOT
        on the up/down ratio, so a name whose up/down ratio cannot be formed
        still matches and its None travels into the evidence -- and from there
        into the report's Up/Down Volume Ratio column, which prints a dash.

        `ctx.get("ud_ratio") or 1.0` would print a confident "1.00" instead.
        """
        ev = pull(result(), dict(CTX, ud_ratio=None, ud_weighted=None,
                                 ud_20=None))
        self.assertIsNotNone(ev)
        self.assertIsNone(ev["ud_ratio"])
        self.assertIsNone(ev["ud_weighted"])
        self.assertIsNone(ev["ud_20"])
        self.assertAlmostEqual(setups.fit_pullback(ev),
                               setups.fit_pullback(dict(ev, ud_ratio=0.5,
                                                        ud_weighted=0.5,
                                                        ud_20=0.5)),
                               places=6)

    def test_a_measured_zero_reaches_the_evidence_as_zero(self):
        """0.0 is measured, not missing: a name with no up-volume at all. It
        must not be reported as a neutral 1.0."""
        ev = pull(result(), dict(CTX, ud_ratio=0.0))
        self.assertIsNotNone(ev)
        self.assertEqual(ev["ud_ratio"], 0.0)
        self.assertAlmostEqual(ev["rsi"], 48.0, places=6)
        self.assertAlmostEqual(ev["dryup"], 0.8, places=6)

    def test_the_two_retracement_numbers_are_not_the_same_number(self):
        """retrace_pct is the percent under a recent SWING HIGH -- the gate's
        own number and the one the report publishes. retrace_of_52w_range_pct is
        the share of the 52-week range fit_pullback bands. Emitting one under
        both names would put every match in the depth band's bottom rung, since
        the gate only asks for 3%.

        101 against a 110 swing high is 8.18%; against a 70-110 range it is
        22.5%. The two must not be interchangeable.
        """
        ev = pull(result(), CTX)
        self.assertAlmostEqual(ev["retrace_pct"], 9.0 / 110 * 100, places=8)
        self.assertAlmostEqual(ev["retrace_of_52w_range_pct"], 22.5, places=8)

    def test_distance_is_to_the_NEAREST_of_sma20_and_sma50(self):
        """min, not max and not sma20 alone. 101 sits 0.498% off sma20 (100.5)
        and 2.02% off sma50 (99); reporting either the larger or the wrong
        average changes the number, and both alternatives are under the 3%
        ceiling so no near-miss test would notice."""
        ev = pull(result(), CTX)
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
        self.assertIsNone(pull(o, CTX))

    def test_reported_distance_is_never_negative(self):
        near = pull(
            result(price=100.0, ma=ma(sma20=100.5, sma50=99.0)), CTX)
        self.assertGreater(near["dist_to_ma_pct"], 0.0)

    def test_distance_is_normalised_by_the_average_not_the_price(self):
        """0.5 / 100.5 and 0.5 / 101 differ in the fourth decimal; the fixture
        above pins the former."""
        ev = pull(result(), CTX)
        self.assertNotAlmostEqual(ev["dist_to_ma_pct"], abs(101 - 100.5) / 101 * 100,
                                  places=8)

    def test_retrace_is_measured_across_the_52_week_span(self):
        """(hi52 - px) / (hi52 - lo52): 9 points off a 40-point span is 22.5%.
        Against the price it would be 8.9% and against hi52 alone 8.2%, both of
        which land in a different depth band inside fit_pullback."""
        self.assertAlmostEqual(pull(result(), CTX)["retrace_of_52w_range_pct"],
                               22.5, places=8)

    def test_flat_52_week_span_reports_zero_range_retrace(self):
        """The `if span else 0.0` arm; hi52 == lo52 divides by zero otherwise.

        The swing-high retracement is unaffected -- it never touches hi52 -- so
        the name still matches, which is what makes the guard reachable.
        """
        ev = pull(result(hi52=110.0, lo52=110.0), CTX)
        self.assertIsNotNone(ev)
        self.assertAlmostEqual(ev["retrace_of_52w_range_pct"], 0.0, places=8)
        self.assertAlmostEqual(ev["retrace_pct"], 9.0 / 110 * 100, places=8)

    def test_a_missing_sma20_falls_back_to_the_sma50_distance(self):
        """The `if m` filter inside the list comprehension. Without it,
        abs(px - None) raises TypeError for a name younger than 20 sessions
        that somehow reached this predicate."""
        ev = pull(result(price=101.0,
                                          ma=ma(sma20=None, sma50=100.0)), CTX)
        self.assertIsNotNone(ev)
        self.assertAlmostEqual(ev["dist_to_ma_pct"], 1.0, places=8)


class TestPullbackNearMisses(unittest.TestCase):
    def test_below_sma200_rejects(self):
        self.assertIsNone(pull(result(ma=ma(sma200=105.0)), CTX))

    def test_sma50_below_sma200_rejects(self):
        self.assertIsNone(pull(
            result(ma=ma(sma50=89.0, sma200=92.0)), CTX))

    def test_falling_sma200_rejects_in_both_modes(self):
        """The knife-catching guard. Not parameterised by --strict on purpose."""
        self.assertIsNone(pull(result(), FALLING))
        self.assertIsNone(pull(result(), FALLING, strict=True))

    def test_missing_sma200_rejects(self):
        self.assertIsNone(pull(result(ma=ma(sma200=None)), CTX))

    def test_missing_sma50_rejects(self):
        self.assertIsNone(pull(result(ma=ma(sma50=None)), CTX))

    def test_too_far_from_any_moving_average_or_support_rejects(self):
        self.assertIsNone(pull(
            result(price=107.0, entry_gate=gate(support=90.0)), CTX))

    def test_lost_the_sma50_rejects(self):
        o = result(price=95.0, ma=ma())
        self.assertIsNone(pull(o, CTX))

    def test_rsi_below_38_rejects(self):
        self.assertIsNone(pull(result(rsi={"daily": 33.0}), CTX))

    def test_rsi_above_62_rejects(self):
        self.assertIsNone(pull(result(rsi={"daily": 70.0}), CTX))

    def test_missing_rsi_rejects(self):
        """The `r is None` arm; the chained comparison raises otherwise."""
        self.assertIsNone(pull(result(rsi={"daily": None}), CTX))

    def test_volume_not_drying_up_rejects(self):
        self.assertIsNone(pull(result(volume=vol(dryup=1.5)), CTX))

    def test_missing_dryup_ratio_rejects(self):
        self.assertIsNone(pull(result(volume=vol(dryup=None)), CTX))

    def test_recent_down_thrust_rejects(self):
        self.assertIsNone(pull(
            result(volume=vol(thrusts=[(-2, "down")])), CTX))

    def test_recent_up_thrust_does_not_reject(self):
        """The sibling arm -- a high-volume accumulation day during a pullback
        is the tell you want, not a disqualifier."""
        self.assertIsNotNone(pull(
            result(volume=vol(thrusts=[(-2, "up")])), CTX))


class TestPullbackSupportRoute(unittest.TestCase):
    """`near_ma > ceiling and not near_sup` -- a two-armed OR written as an AND
    of negations, so all four combinations need a case."""

    def test_near_ma_and_near_support_matches(self):
        self.assertIsNotNone(pull(result(), CTX))

    def test_near_ma_but_far_from_support_matches(self):
        self.assertIsNotNone(pull(
            result(entry_gate=gate(support=60.0)), CTX))

    def test_far_from_ma_but_near_support_matches(self):
        self.assertIsNotNone(pull(far_from_ma(102.0), CTX))

    def test_far_from_both_rejects(self):
        self.assertIsNone(pull(far_from_ma(80.0), CTX))

    def test_support_reach_is_inclusive_at_1_2_atr(self):
        """`<=`, and the multiple is applied to the DAILY ATR. atr 2.5 puts the
        reach at exactly 3.00 points from 103.50."""
        self.assertIsNotNone(pull(far_from_ma(100.5), CTX))
        self.assertIsNone(pull(far_from_ma(100.49), CTX))

    def test_support_above_the_price_counts_too(self):
        """abs(), not px - sup: overhead support that price has just poked
        through is the same distance and must be treated the same."""
        self.assertIsNotNone(pull(far_from_ma(106.5), CTX))
        self.assertIsNone(pull(far_from_ma(106.51), CTX))

    def test_missing_support_level_closes_the_support_route(self):
        """The `sup and` arm. entry_gate may omit nearest_support entirely, and
        `abs(px - None)` would raise rather than reject."""
        self.assertIsNone(pull(
            far_from_ma(None), CTX))

    def test_missing_atr_closes_the_support_route(self):
        """The `atr_d and` arm: with no ATR there is no reach to compute."""
        o = far_from_ma(102.0)
        o["atr"] = {"daily": 0.0, "daily_pct": 2.0}
        self.assertIsNone(pull(o, CTX))
        o["atr"] = {"daily": None, "daily_pct": 2.0}
        self.assertIsNone(pull(o, CTX))


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
    #: under the 110 swing high with support in reach. ATR 5.0 puts the loosened
    #: margin at 5.00 points and the strict margin at 7.50.
    #:
    #: The ATR is 5.0 rather than the 2.5 this fixture carried before the
    #: minimum-retracement gate existed, and the size is FORCED, not cosmetic.
    #: One ATR of 2.5 against a 110 swing high is 2.27% -- inside the gate's own
    #: 3% floor -- so every price this class walks across the ATR margin would
    #: have been rejected by the retracement gate first and none of the
    #: assertions below could fail. At 5.0 the loosened margin is 4.55% and the
    #: strict one 6.82%, both clear of the 3%/5% floors, so the ATR margin is
    #: again the only thing being measured here.
    def at_high(self, price, support=None, **over):
        o = result(price=price,
                   ma=ma(sma20=94.0, sma50=93.0, sma200=90.0),
                   atr={"daily": 5.0, "daily_pct": 4.7},
                   entry_gate=gate(support=price - 1.0 if support is None
                                   else support))
        o.update(over)
        return o

    def test_the_margin_and_the_retracement_gate_do_not_overlap_here(self):
        """The fixture's own arithmetic, asserted rather than assumed.

        If one ATR were ever narrower than the minimum retracement, every
        margin assertion in this class would be measuring the retracement gate
        instead and would pass however the margin was written.
        """
        atr_d, swing = 5.0, 110.0
        th = setups.THRESHOLDS["PULLBACK"]
        for i in (0, 1):
            margin_pct = th["swing_margin_atr"][i] * atr_d / swing * 100
            self.assertGreater(margin_pct, th["min_retrace_pct"][i],
                               "one margin is inside the retracement floor")

    def test_the_fixture_really_does_enter_through_the_support_arm(self):
        """Otherwise the rejection below could be the MA ceiling firing and the
        new condition could be deleted without a failure."""
        o = self.at_high(103.5)
        near_ma = min(abs(o["price"] - m) / m * 100
                      for m in (o["ma"]["sma20"], o["ma"]["sma50"]))
        self.assertGreater(near_ma, setups.THRESHOLDS["PULLBACK"]["ma_dist_pct"][0])
        self.assertIsNotNone(pull(o, CTX))

    def test_a_name_at_a_new_high_cannot_enter_as_a_pullback(self):
        """109.9 against a 110 swing high with ATR 5.0: support is 1.0 away, so
        the old arm opened. It has retraced 0.25% of its 52-week range."""
        o = self.at_high(109.9)
        self.assertLessEqual(abs(o["price"] - o["entry_gate"]["nearest_support"]),
                             1.2 * o["atr"]["daily"])
        self.assertIsNone(pull(o, CTX))

    def test_a_name_above_every_recent_swing_high_cannot_either(self):
        """The max(), not the latest: price above all ten pivots is the literal
        definition of printing new highs."""
        o = self.at_high(112.0, swing_highs=swings(104.0, 110.0))
        self.assertIsNone(pull(o, CTX))

    def test_the_margin_is_measured_from_the_HIGHEST_recent_swing(self):
        """max(), not the latest pivot, and the pair separates them.

        The latest swing here is 106.0 and the highest 120.0. At 105.0 with ATR
        5.0 the arm needs 5.00 points of room: the 120 pivot gives it, the 106
        one does not. A name that has come off a real high is a pullback even if
        it has since printed a lower pivot underneath the decline.
        """
        self.assertIsNotNone(pull(
            self.at_high(105.0, swing_highs=swings(120.0, 106.0)), CTX))
        self.assertIsNone(pull(
            self.at_high(105.0, swing_highs=swings(106.0)), CTX))

    def test_the_margin_is_inclusive_at_one_atr(self):
        """`<=`: exactly one ATR below the swing high is far enough. 110 - 5.0
        is 105.00, and a paisa higher is not."""
        self.assertIsNotNone(pull(self.at_high(105.00), CTX))
        self.assertIsNone(pull(self.at_high(105.01), CTX))

    def test_strict_asks_for_a_bigger_margin(self):
        """1.5 ATR is 7.50 points, so the strict threshold sits at 102.50."""
        o = self.at_high(104.0)
        self.assertIsNotNone(pull(o, CTX))
        self.assertIsNone(pull(o, CTX, strict=True))
        self.assertIsNotNone(pull(self.at_high(102.50), CTX, strict=True))
        self.assertIsNone(pull(self.at_high(102.51), CTX, strict=True))

    def test_the_moving_average_arm_is_untouched_by_this(self):
        """The ruling is about the support arm alone.

        105.5 with ATR 6.0 fails the swing margin outright -- it needs 6.00
        points of room under the 110 pivot and has 4.50 -- and its support at
        105.0 is well within 1.2 ATR, so the margin is the ONLY thing closing
        the support arm. It matches anyway, through the 20-day sitting 0.48%
        away. The control moves both averages out of reach and nothing else, and
        the name then has no way in at all.

        (The ATR has to be this wide for the case to exist: the margin and the
        3% retracement floor both scale off the same swing high, so a name can
        fail the margin while clearing the retracement only when one ATR is
        worth more than 3% of that high.)
        """
        o = result(price=105.5, ma=ma(sma20=105.0, sma50=100.0, sma200=90.0),
                   atr={"daily": 6.0, "daily_pct": 5.7},
                   entry_gate=gate(support=105.0))
        self.assertFalse(setups._below_recent_swing_high(o, 105.5, 6.0, 1.0))
        self.assertLessEqual(abs(105.5 - 105.0), 1.2 * 6.0)
        self.assertIsNotNone(pull(o, CTX))
        self.assertIsNone(pull(
            dict(o, ma=ma(sma20=94.0, sma50=93.0, sma200=90.0)), CTX))

    def test_no_swing_highs_at_all_closes_the_support_arm(self):
        """"Cannot judge" must close the arm it guards, never open it. Both the
        missing-key and the empty-list shapes."""
        o = self.at_high(103.5)
        del o["swing_highs"]
        self.assertIsNone(pull(o, CTX))
        self.assertIsNone(pull(self.at_high(103.5,
                                                             swing_highs=[]), CTX))

    def test_swing_entries_without_a_price_are_skipped_not_crashed_on(self):
        """The priced pivot is dated through swings() rather than written out,
        because the volume gate measures its two legs FROM that pivot: a pivot
        dated in January puts eleven weeks of the advance inside the pullback
        leg and the name is rejected on volume, which would make this test pass
        or fail on something it is not about."""
        o = self.at_high(103.5,
                         swing_highs=[{"date": "2026-01-01", "px": None}]
                                     + swings(110.0))
        self.assertIsNotNone(pull(o, CTX))

    def test_the_rejection_names_the_swing_high_condition(self):
        diag = {}
        pull(self.at_high(109.9), CTX, diag=diag)
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


class TestPullbackNeedsARealRetracement(unittest.TestCase):
    """A pullback has to have pulled back, on BOTH entry arms.

    MARICO closed 0.3% under its swing high and matched: it had gone sideways
    while its 20-day average caught UP to it, which satisfied "price back within
    3% of the 20-day" without a retracement ever happening. NH matched at 1.0%.
    The swing-margin guard that would have caught them applies to the support
    arm alone, and neither of them entered through it.
    """

    #: A 200-point swing high, chosen because 3% and 5% of it land on 194.00 and
    #: 190.00 with no float residue at all -- the inclusive boundary can be
    #: probed a paisa either side and mean it. The 20-day sits half a percent
    #: under the price, so the MOVING-AVERAGE arm is the one open and the
    #: retracement gate is the only other thing in play.
    def ma_arm(self, price, sma20, **over):
        o = result(price=price,
                   ma=ma(sma20=sma20, sma50=sma20 - 5.0, sma200=sma20 - 20.0),
                   atr={"daily": 4.0, "daily_pct": 2.0},
                   hi52=210.0, lo52=150.0,
                   entry_gate=gate(support=sma20),
                   swing_highs=swings(150.0, 200.0))
        o.update(over)
        return o

    def test_a_name_that_never_pulled_back_is_rejected(self):
        """MARICO's shape: 0.3% under the swing high, resting on a 20-day that
        rose into it. The moving-average arm is wide open -- 0.18% away."""
        o = self.ma_arm(199.4, 199.05)
        near_ma = abs(o["price"] - o["ma"]["sma20"]) / o["ma"]["sma20"] * 100
        self.assertLess(near_ma, setups.THRESHOLDS["PULLBACK"]["ma_dist_pct"][1])
        self.assertIsNone(pull(o, CTX))

    def test_the_same_name_further_off_the_high_is_a_pullback(self):
        """The control. Everything is held except the distance from the swing
        high, so the rejection above cannot be blamed on anything else."""
        self.assertIsNotNone(pull(self.ma_arm(180.0, 179.5), CTX))

    def test_the_floor_is_inclusive_at_three_percent_loosened(self):
        """200 - 3% is exactly 194.00 in binary, so this boundary is real."""
        self.assertIsNotNone(pull(self.ma_arm(194.0, 193.5), CTX))
        self.assertIsNone(pull(self.ma_arm(194.01, 193.5), CTX))

    def test_strict_asks_for_five_percent(self):
        """200 - 5% is exactly 190.00."""
        self.assertIsNotNone(pull(self.ma_arm(190.0, 189.5), CTX, strict=True))
        self.assertIsNone(pull(self.ma_arm(190.01, 189.5), CTX, strict=True))
        self.assertIsNotNone(pull(self.ma_arm(190.01, 189.5), CTX))

    def test_the_gate_applies_to_the_support_arm_as_well(self):
        """The arm CHOLAFIN entered through. Far from every average, within
        1.2 ATR of support, and 1.5% under the swing high: the ATR swing margin
        lets it through -- 1 ATR of 1.0 is only 0.5% of a 200 swing -- and the
        retracement floor is what stops it."""
        o = result(price=197.0, ma=ma(sma20=170.0, sma50=165.0, sma200=150.0),
                   atr={"daily": 1.0, "daily_pct": 0.5},
                   hi52=210.0, lo52=150.0,
                   entry_gate=gate(support=196.5),
                   swing_highs=swings(150.0, 200.0))
        self.assertTrue(setups._below_recent_swing_high(o, 197.0, 1.0, 1.0))
        near_ma = min(abs(197.0 - m) / m * 100 for m in (170.0, 165.0))
        self.assertGreater(near_ma, setups.THRESHOLDS["PULLBACK"]["ma_dist_pct"][0])
        self.assertIsNone(pull(o, CTX))

    def test_no_swing_highs_at_all_rejects_rather_than_passing(self):
        """"Cannot judge" is a rejection here too. The moving-average arm is
        open, so without this the name would match on no evidence at all."""
        self.assertIsNone(pull(self.ma_arm(180.0, 179.5, swing_highs=[]), CTX))
        o = self.ma_arm(180.0, 179.5)
        del o["swing_highs"]
        self.assertIsNone(pull(o, CTX))

    def test_the_rejection_names_the_retracement(self):
        diag = {}
        pull(self.ma_arm(199.4, 199.05), CTX, diag=diag)
        (label, _), = diag.items()
        self.assertIn("below a recent swing high", label)

    def test_the_helper_measures_from_the_highest_of_the_last_five_pivots(self):
        """RETRACE_SWINGS, and the max within it.

        The three readings are deliberately far apart, so no two of them can be
        confused for one another:

            the latest pivot alone   150 -> 0.0%   a stock 40% off its high
                                                   reading as a fresh high,
                                                   because a decline prints a
                                                   lower pivot on every bounce
            all seven pivots         400 -> 62.5%  a high three legs back
            the last five, highest   250 -> 40.0%  the current leg
        """
        pivots = (400.0, 300.0, 250.0, 200.0, 180.0, 170.0, 150.0)
        o = {"swing_highs": [{"date": "d", "px": p} for p in pivots]}
        self.assertEqual(setups.RETRACE_SWINGS, 5)
        self.assertAlmostEqual(setups._retrace_from_swing_high(o, 150.0), 40.0,
                               places=9)
        self.assertAlmostEqual((max(pivots) - 150.0) / max(pivots) * 100, 62.5,
                               places=9)
        self.assertAlmostEqual((pivots[-1] - 150.0) / pivots[-1] * 100, 0.0,
                               places=9)

    def test_the_helper_abstains_rather_than_guessing(self):
        self.assertIsNone(setups._retrace_from_swing_high({}, 100.0))
        self.assertIsNone(setups._retrace_from_swing_high(
            {"swing_highs": [{"date": "d", "px": None}]}, 100.0))
        self.assertIsNone(setups._retrace_from_swing_high(
            {"swing_highs": [{"date": "d", "px": 0.0}]}, 100.0))

    def test_the_helper_goes_negative_above_the_swing_high(self):
        """A name ABOVE every recent pivot must report a negative retracement,
        not zero and not an absolute value: the gate compares against a positive
        floor and `abs()` would turn a new high into a deep pullback."""
        o = {"swing_highs": [{"date": "d", "px": 100.0}]}
        self.assertAlmostEqual(setups._retrace_from_swing_high(o, 110.0), -10.0,
                               places=9)


class TestPullbackNeedsAReversalAtSupport(unittest.TestCase):
    """A retracement with no turn in it is a stock still falling.

    NH closed at 22% of its daily range and MARICO at 13% -- both near the low,
    both counted as pullbacks by a screen that never asked whether a buyer had
    appeared. The bar has to test a support level, close back above THAT level,
    and close in the top of its own range.
    """

    #: Price 101 with a single candidate support: the 50-day at 99.0. The 20-day
    #: is deliberately ABOVE the price, so it is filtered out as resistance and
    #: cannot quietly carry a bar the test meant to fail; nearest_support is
    #: omitted for the same reason. ATR 2.0 puts the loosened tolerance at 0.50
    #: points and the strict one at 0.20.
    def one_level(self, price=101.0, **over):
        o = result(price=price,
                   ma=ma(sma20=103.0, sma50=99.0, sma200=90.0),
                   atr={"daily": 2.0, "daily_pct": 2.0},
                   entry_gate=gate(support=None))
        o.update(over)
        return o

    def run_bars(self, *tail, **kw):
        o = kw.pop("o", None) or self.one_level()
        return setups.match_pullback(o, dict(CTX, rows=rows_ending(*tail)),
                                     kw.pop("strict", False), kw.pop("diag", None))

    def test_the_fixture_has_exactly_one_candidate_level(self):
        """Otherwise a bar built to fail against the 50-day could pass against
        something else and every rejection below would be unreadable."""
        o = self.one_level()
        self.assertGreater(o["ma"]["sma20"], o["price"])
        self.assertNotIn("nearest_support", o["entry_gate"])
        self.assertLess(o["ma"]["sma50"], o["price"])

    # ------------------------------------------------------------ tested it
    def test_a_bar_that_never_reached_support_is_not_a_reversal(self):
        """Low 99.6 against a 50-day at 99.0 and a 0.50 tolerance: it closed
        strong and above the level, but it never went there."""
        self.assertIsNone(self.run_bars(DEAD_BAR,
                                        obar(99.8, 101.2, 99.6, 101.0)))

    def test_the_tolerance_is_inclusive_at_a_quarter_of_an_atr(self):
        """99.0 + 0.25 x 2.0 is exactly 99.50."""
        self.assertIsNotNone(self.run_bars(DEAD_BAR,
                                           obar(99.8, 101.2, 99.50, 101.0)))
        self.assertIsNone(self.run_bars(DEAD_BAR,
                                        obar(99.8, 101.2, 99.51, 101.0)))

    def test_strict_narrows_the_tolerance_to_a_tenth_of_an_atr(self):
        """99.0 + 0.10 x 2.0 is exactly 99.20."""
        self.assertIsNotNone(self.run_bars(DEAD_BAR,
                                           obar(99.5, 101.2, 99.20, 101.0),
                                           strict=True))
        self.assertIsNone(self.run_bars(DEAD_BAR,
                                        obar(99.5, 101.2, 99.21, 101.0),
                                        strict=True))
        self.assertIsNotNone(self.run_bars(DEAD_BAR,
                                           obar(99.5, 101.2, 99.21, 101.0)))

    def test_the_tolerance_is_measured_in_ATR_not_in_points(self):
        """Same bar, same level, half the ATR: 0.25 x 1.0 reaches only 99.25."""
        wide = self.one_level()
        tight = self.one_level(atr={"daily": 1.0, "daily_pct": 1.0})
        bar = obar(99.8, 101.2, 99.4, 101.0)
        self.assertIsNotNone(self.run_bars(DEAD_BAR, bar, o=wide))
        self.assertIsNone(self.run_bars(DEAD_BAR, bar, o=tight))

    # --------------------------------------------------------- reclaimed it
    def test_a_bar_that_closed_under_the_level_is_not_a_reversal(self):
        """Reaching support and closing beneath it is the level breaking, not
        holding. Tested on the earlier bar of the window, because the last bar's
        close IS the price the candidate levels are filtered against and can
        never sit under one of them.

        The bar closes two thirds of the way up its own range, so the strength
        condition is satisfied and the level is the only thing failing."""
        bar = obar(98.5, 99.5, 98.0, 99.0)
        self.assertAlmostEqual(setups._close_position(bar), 2.0 / 3, places=9)
        self.assertIsNone(self.run_bars(bar, obar(100.8, 101.2, 100.9, 101.0)))

    def test_a_paisa_above_the_level_is_enough_to_have_reclaimed_it(self):
        """`>`, and the bar either side of it. 98.99 fails, 99.01 passes, and
        both close well clear of the strength floor."""
        self.assertIsNone(self.run_bars(obar(98.5, 99.5, 98.0, 98.99),
                                        obar(100.8, 101.2, 100.9, 101.0)))
        self.assertIsNotNone(self.run_bars(obar(98.5, 99.5, 98.0, 99.01),
                                           obar(100.8, 101.2, 100.9, 101.0)))

    def test_all_three_conditions_must_hold_on_the_SAME_level(self):
        """The bug an `any tested and any reclaimed` implementation would ship.

        Two levels, 100.8 and 99.0. The bar's low of 100.3 tests the 100.8 but
        not the 99.0 (which needs 99.50 or lower); its close of 100.6 reclaims
        the 99.0 but not the 100.8. Every condition is satisfied by SOME level
        and none by one level, so this is not a reversal.
        """
        o = self.one_level(ma=ma(sma20=100.8, sma50=99.0, sma200=90.0))
        weak = obar(100.4, 101.0, 100.3, 100.7)          # closes under the 20-day
        quiet = obar(100.9, 101.2, 100.9, 101.0)         # close position 0.33
        # The strength condition must be clear of its floor, or the rejection
        # below would come from THAT and the level pairing would go untested.
        self.assertGreater(setups._close_position(weak),
                           setups.THRESHOLDS["PULLBACK"]["close_position"][0])
        self.assertIsNone(self.run_bars(weak, quiet, o=o))
        # Same bar, closing a paisa above the 20-day: one level now carries all
        # three and it is a reversal.
        strong = obar(100.4, 101.0, 100.3, 100.9)
        self.assertIsNotNone(self.run_bars(strong, quiet, o=o))

    def test_a_level_above_the_close_is_resistance_not_support(self):
        """The 20-day at 103.0 sits over a last close of 101. It is not a
        support candidate, and a bar cannot reclaim it.

        The case has to be built on the EARLIER bar of the window. On the last
        bar the close IS the price the levels are filtered against, so "close
        above the level" and "level at or below the price" say the same thing
        and dropping the filter changes nothing. Two sessions ago the stock
        closed at 104 -- above the 20-day -- and has since fallen under it. That
        old close does not turn today's resistance into support.
        """
        o = self.one_level(ma=ma(sma20=103.0, sma50=80.0, sma200=70.0))
        over = obar(102.8, 104.5, 102.5, 104.0)      # closed 104, over the 20-day
        quiet = obar(100.9, 101.2, 100.9, 101.0)     # close position 0.33
        self.assertGreater(setups._close_position(over),
                           setups.THRESHOLDS["PULLBACK"]["close_position"][0])
        self.assertGreater(o["ma"]["sma20"], o["price"])
        self.assertGreater(over["c"], o["ma"]["sma20"])
        self.assertIsNone(self.run_bars(over, quiet, o=o))
        # ...and with the same bar under a 20-day that IS below the price, the
        # only thing that changed is the filter, and it is a reversal.
        low20 = self.one_level(ma=ma(sma20=100.5, sma50=80.0, sma200=70.0))
        self.assertIsNotNone(self.run_bars(obar(100.3, 101.5, 100.2, 101.2),
                                           quiet, o=low20))

    # -------------------------------------------------------- closed strong
    def test_a_bar_that_closed_near_its_low_is_not_a_reversal(self):
        """NH's bar: it reached support and closed above it, at 22% of its own
        range. That is a stock still falling."""
        self.assertIsNone(self.run_bars(DEAD_BAR,
                                        obar(101.5, 103.0, 99.0, 99.9)))

    def test_the_close_position_floor_is_inclusive_at_a_half(self):
        """(101 - 99) / (103 - 99) is exactly 0.5."""
        self.assertIsNotNone(self.run_bars(DEAD_BAR,
                                           obar(99.5, 103.0, 99.0, 101.0),
                                           o=self.one_level(price=101.0)))
        self.assertIsNone(self.run_bars(DEAD_BAR,
                                        obar(99.5, 103.0, 99.0, 100.99),
                                        o=self.one_level(price=100.99)))

    def test_strict_asks_for_three_fifths(self):
        """(102 - 99) / (104 - 99) is exactly 0.6."""
        o = self.one_level(price=102.0, ma=ma(sma20=104.0, sma50=99.0,
                                              sma200=90.0))
        self.assertIsNotNone(self.run_bars(DEAD_BAR,
                                           obar(99.5, 104.0, 99.0, 102.0),
                                           o=o, strict=True))
        near = self.one_level(price=101.99, ma=ma(sma20=104.0, sma50=99.0,
                                                  sma200=90.0))
        self.assertIsNone(self.run_bars(DEAD_BAR,
                                        obar(99.5, 104.0, 99.0, 101.99),
                                        o=near, strict=True))
        self.assertIsNotNone(self.run_bars(DEAD_BAR,
                                           obar(99.5, 104.0, 99.0, 101.99),
                                           o=near))

    def test_a_zero_range_bar_is_undefined_not_perfect(self):
        """high == low divides by zero. It must not raise, and it must not be
        read as a close at the high either -- the bar says nothing."""
        flat = obar(99.0, 99.0, 99.0, 99.0)
        self.assertIsNone(setups._close_position(flat))
        o = self.one_level(price=99.0, ma=ma(sma20=103.0, sma50=98.0,
                                             sma200=90.0))
        self.assertIsNone(self.run_bars(DEAD_BAR, flat, o=o))

    def test_close_position_is_reported_as_the_evidence(self):
        ev = self.run_bars(DEAD_BAR, obar(99.5, 103.0, 99.0, 102.0),
                           o=self.one_level(price=102.0,
                                            ma=ma(sma20=104.0, sma50=99.0,
                                                  sma200=90.0)))
        self.assertAlmostEqual(ev["close_position"], 0.75, places=9)

    # ------------------------------------------------------ recency window
    def test_the_bar_before_last_counts_loosened_but_not_strict(self):
        """CEMPRO's shape: the hammer is the earlier bar and the last bar closed
        strong without reaching back to support."""
        rev = obar(99.5, 101.0, 99.0, 100.5)
        after = obar(100.6, 101.2, 100.4, 101.0)      # never reaches 99.50
        self.assertIsNotNone(self.run_bars(rev, after))
        self.assertIsNone(self.run_bars(rev, after, strict=True))

    def test_a_reversal_three_bars_back_is_stale_in_both_modes(self):
        rev = obar(99.5, 101.0, 99.0, 100.5)
        after = obar(100.6, 101.2, 100.4, 101.0)
        self.assertIsNone(self.run_bars(rev, after, after))
        self.assertIsNone(self.run_bars(rev, after, after, strict=True))

    def test_the_window_is_the_threshold_not_a_hard_coded_two(self):
        self.assertEqual(setups.THRESHOLDS["PULLBACK"]["reversal_bars"], (2, 1))

    # ----------------------------------------------------- candidate levels
    def test_each_of_the_three_levels_can_carry_the_reversal_alone(self):
        """sma20, sma50 and nearest_support, one at a time. Whichever is left in
        play sits at 99.0; the other two are pushed out of reach, so exactly one
        level can be the one that qualified the bar."""
        bar = obar(99.5, 101.0, 99.0, 101.0)
        far = 60.0
        cases = {
            "sma20": self.one_level(ma=ma(sma20=99.0, sma50=far, sma200=50.0)),
            "sma50": self.one_level(ma=ma(sma20=103.0, sma50=99.0,
                                          sma200=50.0)),
            "support": self.one_level(ma=ma(sma20=103.0, sma50=far,
                                            sma200=50.0),
                                      entry_gate=gate(support=99.0)),
        }
        for name, o in cases.items():
            self.assertIsNotNone(self.run_bars(DEAD_BAR, bar, o=o), name)
            # ...and with that one level moved away too, nothing is left.
            if name == "support":
                dead = dict(o, entry_gate=gate(support=far))
            else:
                dead = dict(o, ma=ma(sma20=103.0, sma50=far, sma200=50.0))
            self.assertIsNone(self.run_bars(DEAD_BAR, bar, o=dead), name)

    def test_no_atr_closes_the_reversal_gate(self):
        """Without an ATR there is no tolerance to measure the test with."""
        bar = obar(99.5, 101.0, 99.0, 101.0)
        for atr_d in (0.0, None):
            o = self.one_level(atr={"daily": atr_d, "daily_pct": 2.0})
            self.assertIsNone(self.run_bars(DEAD_BAR, bar, o=o), repr(atr_d))

    def test_an_empty_bar_series_rejects_rather_than_raising(self):
        o = self.one_level()
        self.assertIsNone(setups.match_pullback(o, dict(CTX, rows=[])))

    def test_the_rejection_names_the_reversal(self):
        diag = {}
        self.run_bars(DEAD_BAR, obar(101.5, 103.0, 99.0, 99.9), diag=diag)
        (label, _), = diag.items()
        self.assertIn("closed back above it", label)

    def test_the_named_percentage_follows_the_threshold(self):
        """The funnel prints "the top N% of its own range"; N is 1 - the floor,
        and the two modes must not print the same sentence."""
        loose, strict = {}, {}
        self.run_bars(DEAD_BAR, obar(101.5, 103.0, 99.0, 99.9), diag=loose)
        self.run_bars(DEAD_BAR, obar(101.5, 103.0, 99.0, 99.9), diag=strict,
                      strict=True)
        self.assertIn("top 50%", list(loose)[0])
        self.assertIn("top 40%", list(strict)[0])


class TestPullbackBoundaries(unittest.TestCase):
    def test_price_must_be_strictly_above_sma200(self):
        """`<=` not `<`. sma50 is lifted above sma200 in both cases so the NEXT
        clause cannot be the one doing the rejecting -- with the fixture's
        sma50 of 99 an sma200 near 101 trips `sma50 <= sma200` first and the
        accept side can never hold."""
        self.assertIsNone(pull(
            result(ma=ma(sma50=101.5, sma200=101.0)), CTX))
        self.assertIsNotNone(pull(
            result(ma=ma(sma50=101.5, sma200=100.99)), CTX))

    def test_sma50_must_be_strictly_above_sma200(self):
        self.assertIsNone(pull(
            result(ma=ma(sma50=99.0, sma200=99.0)), CTX))
        self.assertIsNotNone(pull(
            result(ma=ma(sma50=99.0, sma200=98.99)), CTX))

    def test_ma_distance_ceiling_is_inclusive_at_three_percent(self):
        self.assertIsNotNone(pull(exact(103.0), CTX))
        self.assertIsNone(pull(exact(103.01), CTX))

    def test_three_percent_below_sma50_is_the_floor(self):
        """`px <= sma50 * 0.97`, isolated.

        The brief's fixture for this guard (price 95) is already 4.04% from the
        nearest average, so it rejects at the DISTANCE ceiling and the 0.97
        multiplier could be deleted without a failure. Here sma20 sits right on
        the price, so the distance route is wide open and the sma50 floor is the
        only thing in play. sma50 = 100 makes 0.97 * sma50 exactly 97.0.
        """
        below = result(price=97.0, ma=ma(sma20=97.0, sma50=100.0, sma200=90.0))
        self.assertIsNone(pull(below, CTX))
        at = result(price=97.01, ma=ma(sma20=97.0, sma50=100.0, sma200=90.0))
        self.assertIsNotNone(pull(at, CTX))

    def test_rsi_window_is_inclusive_at_both_ends(self):
        for r in (38.0, 62.0):
            self.assertIsNotNone(pull(result(rsi={"daily": r}), CTX),
                                 "rsi %s" % r)
        for r in (37.99, 62.01):
            self.assertIsNone(pull(result(rsi={"daily": r}), CTX),
                              "rsi %s" % r)

    def test_dryup_ceiling_is_exclusive_at_1_1(self):
        self.assertIsNone(pull(result(volume=vol(dryup=1.1)), CTX))
        self.assertIsNotNone(pull(result(volume=vol(dryup=1.099)),
                                                   CTX))

    def test_down_thrust_window_is_eight_bars_loosened(self):
        self.assertIsNone(pull(
            result(volume=vol(thrusts=[(-8, "down")])), CTX))
        self.assertIsNotNone(pull(
            result(volume=vol(thrusts=[(-9, "down")])), CTX))


class TestPullbackStrict(unittest.TestCase):
    def test_strict_narrows_the_moving_average_distance(self):
        o = result(price=103.0)   # 2.5% above sma20
        self.assertIsNotNone(pull(o, CTX))
        self.assertIsNone(pull(o, CTX, strict=True))

    def test_strict_ma_distance_ceiling_is_inclusive_at_two_percent(self):
        self.assertIsNotNone(pull(exact(102.0), CTX, strict=True))
        self.assertIsNone(pull(exact(102.01), CTX, strict=True))

    def test_strict_narrows_the_support_reach_to_one_atr(self):
        """atr 2.5: loosened reaches 3.00 points, strict only 2.50."""
        self.assertIsNotNone(pull(far_from_ma(101.0), CTX,
                                                   strict=True))
        self.assertIsNone(pull(far_from_ma(100.9), CTX,
                                                strict=True))
        self.assertIsNotNone(pull(far_from_ma(100.9), CTX))

    def test_strict_narrows_the_rsi_band(self):
        o = result(rsi={"daily": 39.0})
        self.assertIsNotNone(pull(o, CTX))
        self.assertIsNone(pull(o, CTX, strict=True))

    def test_strict_rsi_window_is_inclusive_at_both_ends(self):
        for r in (40.0, 58.0):
            self.assertIsNotNone(pull(result(rsi={"daily": r}), CTX,
                                                       strict=True), "rsi %s" % r)
        for r in (39.99, 58.01):
            self.assertIsNotNone(pull(result(rsi={"daily": r}), CTX),
                                 "loosened rsi %s" % r)
            self.assertIsNone(pull(result(rsi={"daily": r}), CTX,
                                                    strict=True), "strict rsi %s" % r)

    def test_strict_requires_a_deeper_dryup(self):
        o = result(volume=vol(dryup=1.0))
        self.assertIsNotNone(pull(o, CTX))
        self.assertIsNone(pull(o, CTX, strict=True))
        self.assertIsNotNone(pull(result(volume=vol(dryup=0.999)),
                                                   CTX, strict=True))

    def test_strict_widens_the_down_thrust_window_to_ten_bars(self):
        """The one threshold whose STRICT value is the LARGER number: a longer
        lookback rejects more, not fewer."""
        o = result(volume=vol(thrusts=[(-9, "down")]))
        self.assertIsNotNone(pull(o, CTX))
        self.assertIsNone(pull(o, CTX, strict=True))
        self.assertIsNone(pull(
            result(volume=vol(thrusts=[(-10, "down")])), CTX, strict=True))
        self.assertIsNotNone(pull(
            result(volume=vol(thrusts=[(-11, "down")])), CTX, strict=True))

    def test_strict_defaults_to_false_when_omitted(self):
        self.assertIsNotNone(pull(result(rsi={"daily": 39.0}), CTX))


class TestPullbackFit(unittest.TestCase):
    def ev(self, **over):
        # `dryup` is deliberately still here and deliberately NOT scored: it is
        # a live gate, so a real match carries it, and leaving it in the fixture
        # means a fit_pullback that went back to reading it would be caught by
        # the weights test rather than by a KeyError that looks like a typo.
        # The same trio the CTX fixture carries: 1.60 bands to 8, 1.30 to 6,
        # 1.55/1.60 bands "steady", so accumulation is 7.0 and every remainder
        # constant below derives from it. Three DIFFERENT numbers, so a fit
        # reading the wrong one of them moves every case in this class.
        e = {"dist_to_ma_pct": 0.5, "rsi": 48.0, "dryup": 0.8,
             "pullback_vol_ratio": 0.45,
             "ud_ratio": 1.60, "ud_weighted": 1.30, "ud_20": 1.55,
             "retrace_of_52w_range_pct": 30.0}
        e.update(over)
        return e

    def test_the_depth_term_reads_the_52_week_share_not_the_swing_percent(self):
        """The two retracement numbers live on different scales, and only one of
        them is what retrace_depth's band was calibrated against.

        A match 30% into its 52-week range but only 6% under its swing high
        scores the fib-zone 10 for depth. Reading retrace_pct instead would band
        6% at 3.0 and dock 1.4 off every fit in the table -- silently, since both
        keys are floats in the same dict.
        """
        e = self.ev(retrace_of_52w_range_pct=30.0, retrace_pct=6.0)
        self.assertAlmostEqual(setups.fit_pullback(e), 9.7, places=6)
        self.assertAlmostEqual(
            setups.fit_pullback(dict(e, retrace_of_52w_range_pct=6.0)), 8.65,
            places=6)

    def test_closer_to_the_moving_average_scores_higher(self):
        near = setups.fit_pullback(pull(result(price=100.8), CTX))
        far = setups.fit_pullback(pull(result(price=103.4), CTX))
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

    def test_a_quieter_retracement_scores_higher(self):
        """The replacement for the old dry-up ordering test. The term measures
        the retracement's volume against the advance's, so lower is better."""
        self.assertGreater(setups.fit_pullback(self.ev(pullback_vol_ratio=0.45)),
                           setups.fit_pullback(self.ev(pullback_vol_ratio=0.88)))

    def test_the_blunt_dryup_term_is_no_longer_scored(self):
        """dryup was REPLACED, not merely outweighed.

        It compares a 20-day average against a 50-day one -- a statement about
        the last month that knows nothing about where the pullback began -- and
        scoring it alongside the pullback-versus-advance ratio would price one
        idea twice and give the worse measurement half the credit. Moving it
        across its entire band must now change nothing at all.
        """
        for dry in (0.5, 0.8, 0.95, 1.09):
            self.assertAlmostEqual(setups.fit_pullback(self.ev(dryup=dry)),
                                   setups.fit_pullback(self.ev()), places=6,
                                   msg="dryup %s" % dry)

    def test_weights_are_thirty_twenty_twenty_five_fifteen_ten(self):
        """dist 0.5 -> 10, |rsi-50| = 2 -> 10, pullback volume 0.45 -> 10,
        retrace 30 -> 10, accumulation 7.0.
        0.30*10 + 0.20*10 + 0.25*10 + 0.15*10 + 0.10*7
          = 3.0 + 2.0 + 2.5 + 1.5 + 0.7 = 9.7.
        Each further case moves ONE term, so the individual weights and not just
        their sum are pinned: dist 2.5 -> 6 costs 0.30*4 = 1.2, giving 8.5.
        """
        self.assertAlmostEqual(setups.fit_pullback(self.ev()), 9.7, places=6)
        self.assertAlmostEqual(setups.fit_pullback(self.ev(dist_to_ma_pct=2.5)), 8.5,
                               places=6)
        self.assertAlmostEqual(setups.fit_pullback(self.ev(rsi=62.0)), 8.7,
                               places=6)
        self.assertAlmostEqual(setups.fit_pullback(self.ev(pullback_vol_ratio=0.9)),
                               8.2, places=6)
        # 60% of the 52-week range is PAST the 55 boundary, so depth falls to
        # the 4 rung rather than the 7 one: 0.15 * 6 = 0.9 off.
        self.assertAlmostEqual(setups.fit_pullback(self.ev(retrace_of_52w_range_pct=60.0)), 8.8,
                               places=6)
        # All three volume numbers together, so the whole term drops to its 2.0
        # floor rather than half of it.
        self.assertAlmostEqual(
            setups.fit_pullback(self.ev(ud_ratio=0.80, ud_weighted=0.80,
                                        ud_20=0.80)), 9.2, places=6)

    def test_every_distance_cut_is_reachable(self):
        cuts = [(1.0, 10), (2.0, 8), (3.0, 6)]
        for i, (dist, sub) in enumerate(cuts):
            self.assertAlmostEqual(setups.fit_pullback(self.ev(dist_to_ma_pct=dist)),
                                   round(0.30 * sub + 6.7, 2), places=6,
                                   msg="at cut %s" % dist)
            above = cuts[i + 1][1] if i + 1 < len(cuts) else 0.0
            self.assertAlmostEqual(
                setups.fit_pullback(self.ev(dist_to_ma_pct=dist + 0.001)),
                round(0.30 * above + 6.7, 2), places=6,
                msg="just above cut %s" % dist)

    def test_distance_falls_through_to_zero_for_a_support_only_match(self):
        """The fall-through arm of band_desc IS reachable here, unlike in the
        other fits: a name that qualified via the support route can sit 10%
        from every average."""
        self.assertAlmostEqual(setups.fit_pullback(self.ev(dist_to_ma_pct=10.1)),
                               6.7, places=6)

    def test_every_rsi_cut_is_reachable(self):
        cuts = [(5.0, 10), (10.0, 8), (99.0, 5)]
        for i, (gap, sub) in enumerate(cuts):
            self.assertAlmostEqual(setups.fit_pullback(self.ev(rsi=50.0 + gap)),
                                   round(3.0 + 0.20 * sub + 4.7, 2), places=6,
                                   msg="at cut %s" % gap)
            above = cuts[i + 1][1] if i + 1 < len(cuts) else 0.0
            self.assertAlmostEqual(
                setups.fit_pullback(self.ev(rsi=50.0 + gap + 0.001)),
                round(3.0 + 0.20 * above + 4.7, 2), places=6,
                msg="just above cut %s" % gap)

    def test_every_pullback_volume_cut_is_reachable(self):
        """band_desc, so the paired case sits just ABOVE each cut. The 3.0 + 2.0
        + 1.5 + 0.7 = 7.2 remainder is held fixed.

        The 0.0 fall-through below the last cut is NOT reachable through
        match_pullback -- its gate rejects anything above 0.90 -- so the final
        pair asserts the guard rather than a live arm.
        """
        cuts = [(0.50, 10), (0.65, 8), (0.80, 6), (0.90, 4)]
        for i, (pv, sub) in enumerate(cuts):
            self.assertAlmostEqual(
                setups.fit_pullback(self.ev(pullback_vol_ratio=pv)),
                round(0.25 * sub + 7.2, 2), places=6, msg="at cut %s" % pv)
            above = cuts[i + 1][1] if i + 1 < len(cuts) else 0.0
            self.assertAlmostEqual(
                setups.fit_pullback(self.ev(pullback_vol_ratio=pv + 0.001)),
                round(0.25 * above + 7.2, 2), places=6,
                msg="just above cut %s" % pv)

    def test_every_accumulation_cut_is_reachable(self):
        """The shared ladder at PULLBACK's 10% weight -- the smallest of the
        five, because this setup already spends 25% on a volume term of its own.
        The 3.0 + 2.0 + 2.5 + 1.5 = 9.0 remainder is held fixed.

        Every rung including the sub-1.00 floor is REACHABLE here: PULLBACK has
        no up/down gate, so a name being distributed can still match and must
        still be ranked below one that is not.
        """
        cuts = [(2.50, 10), (2.00, 9), (1.50, 8), (1.25, 6), (1.00, 4)]
        for i, (ud, sub) in enumerate(cuts):
            # Both ladders on the same rung and a steady trend, so the term is
            # exactly that rung and the ladder is seen whole.
            self.assertAlmostEqual(
                setups.fit_pullback(self.ev(ud_ratio=ud, ud_weighted=ud,
                                            ud_20=ud)),
                round(0.10 * sub + 9.0, 2), places=6, msg="at cut %s" % ud)
            below = cuts[i + 1][1] if i + 1 < len(cuts) else 2.0
            lo = ud - 0.001
            self.assertAlmostEqual(
                setups.fit_pullback(self.ev(ud_ratio=lo, ud_weighted=lo,
                                            ud_20=lo)),
                round(0.10 * below + 9.0, 2), places=6,
                msg="just below cut %s" % ud)
        self.assertAlmostEqual(
            setups.fit_pullback(self.ev(ud_ratio=None, ud_weighted=None,
                                        ud_20=None)),
            round(0.10 * 2.0 + 9.0, 2), places=6)

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
            self.assertAlmostEqual(setups.fit_pullback(self.ev(retrace_of_52w_range_pct=pct)),
                                   round(8.2 + 0.15 * sub, 2), places=6,
                                   msg="retrace %s" % pct)

    def test_a_trivial_retracement_no_longer_scores_near_the_top(self):
        """CHOLAFIN's 4.4% against a textbook 20%. The old band gave both 8/10
        and the shallow one led the table on the strength of it."""
        self.assertLess(setups.fit_pullback(self.ev(retrace_of_52w_range_pct=4.4)),
                        setups.fit_pullback(self.ev(retrace_of_52w_range_pct=20.0)))
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
        # Every band at its fall-through except retrace depth, whose floor is
        # 4, and accumulation, whose floor is 2:
        # 0.15*4 + 0.10*2 = 0.6 + 0.2 = 0.8.
        worst = self.ev(dist_to_ma_pct=50.0, rsi=200.0, pullback_vol_ratio=5.0,
                        ud_ratio=0.5, ud_weighted=0.5, ud_20=0.5,
                        retrace_of_52w_range_pct=99.0)
        self.assertAlmostEqual(setups.fit_pullback(worst), 0.8, places=6)
        self.assertTrue(0.0 <= setups.fit_pullback(worst) <= 10.0)


class TestPullbackThresholdTable(unittest.TestCase):
    def test_registry_carries_the_spec_numbers(self):
        self.assertEqual(setups.THRESHOLDS["PULLBACK"],
                         {"ma_dist_pct": (3.0, 2.0), "atr_mult_to_support": (1.2, 1.0),
                          "swing_margin_atr": (1.0, 1.5),
                          "min_retrace_pct": (3.0, 5.0),
                          "support_tol_atr": (0.25, 0.10),
                          "close_position": (0.50, 0.60),
                          "reversal_bars": (2, 1),
                          "rsi_lo": (38.0, 40.0), "rsi_hi": (62.0, 58.0),
                          "dryup": (1.1, 1.0), "thrust_bars": (8, 10),
                          "pullback_vol_ratio": (0.90, 0.75)})

    def test_sma200_rising_is_absent_from_the_table(self):
        """It must not be parameterised: loosening it would not widen the
        screen, it would change what the screen means."""
        self.assertNotIn("sma200_rising", setups.THRESHOLDS["PULLBACK"])

    def test_strict_is_never_looser_than_loosened(self):
        th = setups.THRESHOLDS["PULLBACK"]
        for key in ("ma_dist_pct", "atr_mult_to_support", "rsi_hi", "dryup",
                    "support_tol_atr", "reversal_bars", "pullback_vol_ratio"):
            self.assertLessEqual(th[key][1], th[key][0], key)
        for key in ("rsi_lo", "thrust_bars", "swing_margin_atr",
                    "min_retrace_pct", "close_position"):
            self.assertGreaterEqual(th[key][1], th[key][0], key)
        self.assertEqual(set(th), {"ma_dist_pct", "atr_mult_to_support",
                                   "rsi_hi", "dryup", "support_tol_atr",
                                   "reversal_bars", "rsi_lo", "thrust_bars",
                                   "swing_margin_atr", "min_retrace_pct",
                                   "close_position", "pullback_vol_ratio"},
                         "a threshold was added without a direction")

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
                            if pull(o, CTX, strict=True) is not None:
                                checked += 1
                                self.assertIsNotNone(
                                    pull(o, CTX, strict=False),
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
                    if pull(o, CTX, strict=True) is not None:
                        checked += 1
                        self.assertIsNotNone(
                            pull(o, CTX, strict=False),
                            "strict matched but loosened did not: px=%s "
                            "highs=%s atr=%s" % (price, highs, atr_d))
        self.assertGreater(checked, 0, "grid produced no strict matches at all")


#: The bar both volume legs are measured from. swings(104.0, 110.0) dates its
#: HIGHER pivot on ROWS[-9], and _retrace_swing takes the highest of the last
#: five pivots -- so the advance is the 30 bars before this index and the
#: retracement is this bar to the end. TestPullbackVolumeLegs asserts it rather
#: than trusting the arithmetic.
PIVOT_INDEX = len(ROWS) - 9


def legs(o, pullback_vol, advance_vol=ADVANCE_VOL, pivot=PIVOT_INDEX,
         ctx=None):
    """A ctx whose rows carry a chosen volume on each side of the pivot.

    The rows are DEEP-copied: rows_for() shares its bar dicts with the module's
    ROWS, and writing volumes through them would rewrite the fixture every other
    test in this file depends on.
    """
    rows = [dict(r) for r in rows_for(o)]
    for r in rows[pivot:]:
        r["v"] = pullback_vol
    for r in rows[max(0, pivot - setups.ADVANCE_BARS):pivot]:
        r["v"] = advance_vol
    return dict(CTX if ctx is None else ctx, rows=rows)


class TestPullbackVolumeLegs(unittest.TestCase):
    """_pullback_volume_ratio in isolation: the pivot, the two slices, the guards."""

    def test_the_pivot_is_the_one_the_retracement_gate_uses(self):
        """Both gates must describe the SAME leg. Two gates measuring "the
        pullback" from two different highs would be two setups sharing a name."""
        self.assertEqual(str(setups._retrace_swing(result())["date"]),
                         str(ROWS[PIVOT_INDEX]["t"]))

    def test_the_ratio_is_the_pullback_mean_over_the_advance_mean(self):
        rows = [dict(r) for r in ROWS]
        for r in rows[PIVOT_INDEX:]:
            r["v"] = 400_000
        for r in rows[PIVOT_INDEX - setups.ADVANCE_BARS:PIVOT_INDEX]:
            r["v"] = 800_000
        self.assertAlmostEqual(setups._pullback_volume_ratio(result(), rows),
                               0.5, places=9)

    def test_the_ratio_is_not_inverted(self):
        """Advance over pullback would report 2.0 where the answer is 0.5, and a
        gate written as a ceiling would then pass exactly the names it exists to
        reject."""
        rows = [dict(r) for r in ROWS]
        for r in rows[PIVOT_INDEX:]:
            r["v"] = 400_000
        for r in rows[PIVOT_INDEX - setups.ADVANCE_BARS:PIVOT_INDEX]:
            r["v"] = 800_000
        self.assertLess(setups._pullback_volume_ratio(result(), rows), 1.0)

    def test_the_advance_window_is_thirty_bars(self):
        """Both edges. The 30th bar before the pivot is inside the window and
        the 31st is outside, so a heavy bar at each position gives different
        answers -- one changed, one unchanged."""
        def ratio(spike_at):
            rows = [dict(r) for r in ROWS]
            for r in rows[PIVOT_INDEX:]:
                r["v"] = 500_000
            for r in rows[:PIVOT_INDEX]:
                r["v"] = 1_000_000
            rows[PIVOT_INDEX - spike_at]["v"] = 31_000_000
            return setups._pullback_volume_ratio(result(), rows)
        self.assertAlmostEqual(ratio(31), 0.5, places=9)     # outside: unchanged
        self.assertLess(ratio(30), 0.5)                      # inside: dragged down

    def test_the_pivot_bar_belongs_to_the_pullback_leg(self):
        """A climax print on the high bar counts against the retracement, which
        is the safe direction for a gate that exists to demand evidence. Were it
        counted in the ADVANCE the same rows would read 0.38 instead of 1.56.
        """
        rows = [dict(r) for r in ROWS]
        for r in rows[PIVOT_INDEX:]:
            r["v"] = 500_000
        for r in rows[PIVOT_INDEX - setups.ADVANCE_BARS:PIVOT_INDEX]:
            r["v"] = 1_000_000
        rows[PIVOT_INDEX]["v"] = 10_000_000
        self.assertAlmostEqual(setups._pullback_volume_ratio(result(), rows),
                               ((10_000_000 + 8 * 500_000) / 9) / 1_000_000,
                               places=9)

    def test_a_pivot_dated_outside_the_rows_cannot_be_measured(self):
        o = result(swing_highs=[{"date": "1999-01-04", "px": 110.0}])
        self.assertIsNone(setups._pullback_volume_ratio(o, ROWS))

    def test_no_pivot_at_all_cannot_be_measured(self):
        self.assertIsNone(setups._pullback_volume_ratio(result(swing_highs=[]),
                                                        ROWS))
        o = result()
        del o["swing_highs"]
        self.assertIsNone(setups._pullback_volume_ratio(o, ROWS))

    def test_a_pullback_leg_shorter_than_five_bars_cannot_be_measured(self):
        """Both sides of MIN_LEG_BARS on the retracement side: four bars is one
        or two prints deciding the gate, five is the shortest measurable leg."""
        four = result(swing_highs=[{"date": str(ROWS[-4]["t"]), "px": 110.0}])
        five = result(swing_highs=[{"date": str(ROWS[-5]["t"]), "px": 110.0}])
        self.assertIsNone(setups._pullback_volume_ratio(four, ROWS))
        self.assertIsNotNone(setups._pullback_volume_ratio(five, ROWS))

    def test_an_advance_shorter_than_five_bars_cannot_be_measured(self):
        """Both sides on the advance side: a pivot four bars into the series has
        no advance to speak of, one five bars in has the minimum."""
        four = result(swing_highs=[{"date": str(ROWS[4]["t"]), "px": 110.0}])
        five = result(swing_highs=[{"date": str(ROWS[5]["t"]), "px": 110.0}])
        self.assertIsNone(setups._pullback_volume_ratio(four, ROWS))
        self.assertIsNotNone(setups._pullback_volume_ratio(five, ROWS))

    def test_a_zero_volume_advance_cannot_be_measured(self):
        """No division by zero, and no infinity reported as a ratio."""
        rows = [dict(r) for r in ROWS]
        for r in rows[PIVOT_INDEX - setups.ADVANCE_BARS:PIVOT_INDEX]:
            r["v"] = 0
        self.assertIsNone(setups._pullback_volume_ratio(result(), rows))

    def test_an_empty_row_series_cannot_be_measured(self):
        self.assertIsNone(setups._pullback_volume_ratio(result(), []))


class TestPullbackVolumeAgainstTheAdvance(unittest.TestCase):
    """The gate itself.

    On the live universe the median PULLBACK match retraced at 0.88x the volume
    of its own advance -- half the list was resting on almost exactly the
    participation that drove the move up, which is supply rather than rest.
    Neither gate above this one can see it: dryup compares the 20-day average
    against the 50-day, a statement about the last month rather than about this
    pullback, and the down-thrust check only asks that no single bar exceeded
    2.5x average.
    """

    def test_a_quiet_retracement_matches(self):
        self.assertIsNotNone(
            setups.match_pullback(result(), legs(result(), 400_000)))

    def test_a_retracement_on_heavier_volume_than_the_advance_rejects(self):
        self.assertIsNone(
            setups.match_pullback(result(), legs(result(), 1_200_000)))

    def test_the_ceiling_is_inclusive_at_0_90(self):
        """`>` rejects, so a ratio of exactly 0.90 passes. Both sides, one part
        in a million apart, so `>=` cannot survive."""
        self.assertIsNotNone(
            setups.match_pullback(result(), legs(result(), 900_000)))
        self.assertIsNone(
            setups.match_pullback(result(), legs(result(), 900_001)))

    def test_strict_tightens_the_ceiling_to_0_75(self):
        o = result()
        for v in (760_000, 800_000, 900_000):
            self.assertIsNotNone(setups.match_pullback(o, legs(o, v)), v)
            self.assertIsNone(setups.match_pullback(o, legs(o, v), strict=True), v)

    def test_the_strict_ceiling_is_inclusive_at_0_75(self):
        o = result()
        self.assertIsNotNone(setups.match_pullback(o, legs(o, 750_000),
                                                   strict=True))

    def test_an_unmeasurable_ratio_rejects(self):
        """"Cannot judge" closes the gate. A silent None-passes-everything is
        how a gate becomes decorative."""
        o = result(swing_highs=[{"date": "1999-01-04", "px": 110.0}])
        self.assertIsNone(setups.match_pullback(o, dict(CTX, rows=rows_for(o))))

    def test_the_gate_reads_the_pivot_the_retracement_gate_used(self):
        """A LATER, LOWER pivot exists three bars from the end. Measuring from
        it would leave a three-bar leg -- under MIN_LEG_BARS, so unmeasurable,
        so a rejection. Measuring from the highest of the last five, as the
        retracement gate does, leaves a nine-bar leg and this name matches.
        """
        o = result(swing_highs=[{"date": str(ROWS[PIVOT_INDEX]["t"]), "px": 110.0},
                                {"date": str(ROWS[-3]["t"]), "px": 104.0}])
        self.assertIsNotNone(setups.match_pullback(o, legs(o, 400_000)))

    def test_the_rejection_names_the_volume_condition(self):
        diag = {}
        setups.match_pullback(result(), legs(result(), 1_200_000), diag=diag)
        (label, _), = diag.items()
        self.assertIn("volume of the advance", label)

    def test_the_gate_sits_after_the_down_thrust_check(self):
        """Funnel order: a name failing both is recorded at the down-thrust."""
        diag = {}
        o = result(volume=vol(dryup=0.8, thrusts=((-2, "down"),)))
        setups.match_pullback(o, legs(o, 1_200_000), diag=diag)
        (label, (step, _)), = diag.items()
        self.assertIn("down-thrust", label)
        self.assertEqual(step, 11)


class TestPullbackDistributionGate(unittest.TestCase):
    """The unambiguous case only: BOTH new measures under the floor at once.

    Two independent measurements have to agree that the name is being
    distributed NOW before it is dropped. Either one alone is a finding the
    table prints -- a `distribution-into-strength` name still matches -- and
    only the doubly-confirmed case is excluded.
    """

    def match(self, **over):
        strict = over.pop("_strict", False)
        diag = over.pop("_diag", None)
        return pull(result(), dict(CTX, **over), strict, diag)

    def test_both_measures_below_the_floor_rejects(self):
        self.assertIsNone(self.match(ud_weighted=0.90, ud_20=0.90))

    def test_the_gate_is_live_in_this_predicate(self):
        """The paired assertion. Without it, a gate that rejected EVERYTHING
        would pass the test above and this file would never notice."""
        self.assertIsNotNone(self.match())

    def test_a_weak_close_weighted_ratio_alone_still_matches(self):
        """distribution-into-strength: price drifts up, sellers own the close.
        Surfaced with its label, never dropped."""
        ev = self.match(ud_ratio=3.74, ud_weighted=0.59, ud_20=1.18)
        self.assertIsNotNone(ev)
        self.assertEqual(setups.volume_signal(3.74, 0.59),
                         setups.DISTRIBUTION_INTO_STRENGTH)

    def test_a_weak_twenty_day_ratio_alone_still_matches(self):
        self.assertIsNotNone(self.match(ud_weighted=1.40, ud_20=0.50))

    def test_the_floor_is_exclusive_on_both_arms(self):
        """Exactly 1.0 is parity, not distribution. `<=` here would drop a name
        whose buyers and sellers finished level."""
        self.assertIsNotNone(self.match(ud_weighted=1.0, ud_20=0.90))
        self.assertIsNotNone(self.match(ud_weighted=0.90, ud_20=1.0))
        self.assertIsNone(self.match(ud_weighted=0.999, ud_20=0.999))

    def test_an_unmeasurable_ratio_is_not_read_as_distribution(self):
        """None means the series could not be judged -- for ud_weighted it means
        NO bar closed below its own midpoint, the most bullish tape there is.
        Two measures must both SAY distribution; one that says nothing does
        not."""
        self.assertIsNotNone(self.match(ud_weighted=None, ud_20=0.50))
        self.assertIsNotNone(self.match(ud_weighted=0.50, ud_20=None))
        self.assertIsNotNone(self.match(ud_weighted=None, ud_20=None))

    def test_a_measured_zero_is_read_as_distribution(self):
        """0.0 is the strongest possible statement of it and must reject through
        the comparison, not survive as if it were missing."""
        self.assertIsNone(self.match(ud_weighted=0.0, ud_20=0.0))

    def test_the_strict_arm_of_the_pair_is_the_one_strict_reads(self):
        """Both halves are 1.0 today, so only a temporarily-tightened pair can
        show that strict indexes element 1 and loosened element 0."""
        orig = setups.DISTRIBUTION_FLOOR
        setups.DISTRIBUTION_FLOOR = (1.0, 1.5)
        try:
            self.assertIsNotNone(self.match(ud_weighted=1.2, ud_20=1.2))
            self.assertIsNone(self.match(ud_weighted=1.2, ud_20=1.2,
                                         _strict=True))
        finally:
            setups.DISTRIBUTION_FLOOR = orig

    def test_the_funnel_names_the_condition_a_passing_name_satisfies(self):
        diag = {}
        self.match(ud_weighted=0.90, ud_20=0.90, _diag=diag)
        self.assertEqual(list(diag), [setups._distributing_label(False)])


if __name__ == "__main__":
    unittest.main()
