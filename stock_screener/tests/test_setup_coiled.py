import os, sys, unittest
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
sys.path.insert(0, _root)
sys.path.insert(0, _here)
import setups
from engine import A
from fixtures import (bar, contracting_series, flat_series, trend_series,
                      turnover_ladder)


def taper(n, price=105.0, top=6.0, bottom=0.5):
    """n bars whose half-range shrinks smoothly, one bar per step.

    contracting_series with a few wide windows only contracts when the slice
    boundaries happen to line up with the window boundaries -- match_coiled
    re-slices ctx["rows"] by rng["bars"], so a fixture built for a 20-bar slice
    stops contracting at 12 or 14 bars and the base-length guard can no longer
    be isolated. A smooth taper contracts under EVERY tail slice, so a test that
    varies rng["bars"] measures the bars guard and nothing else.
    """
    widths = [top - (top - bottom) * i / (n - 1) for i in range(n)]
    return contracting_series(widths, price=price, bars_per_window=1)


def up_thrusts(n, first_bar=0):
    """`n` UP-labelled thrusts on consecutive bars from the START of a series.

    Dated off the first bars rather than the last because every row series in
    this file -- contracting_series, taper, saw_tooth -- begins on the same day
    zero, so these dates land inside whichever series a test hands the predicate
    while the LENGTHS differ from fixture to fixture.

    TWO by default, because the default fixture has to satisfy strict as well as
    loosened; the boundary between one and two is probed by the tests that build
    the count deliberately.
    """
    return [{"date": str(bar(first_bar + i, 0, 0, 0, 0)["t"]), "dir": "up",
             "vol": 5_000_000, "x_avg": 3.2} for i in range(n)]


def result(**over):
    """A compute()-shaped dict that PASSES coiled. Each test breaks one field."""
    o = {"symbol": "TEST", "price": 108.0,
         "last_closed_bar": {"t": "2026-07-31", "v": 1_000_000},
         "ma": {"sma20": 104.0, "sma50": 102.0, "sma100": 100.0, "sma200": 98.0},
         "atr": {"daily": 1.0, "daily_pct": 1.0},
         "volume": {"dryup_ratio": 0.75, "avg20": 1_000_000, "avg50": 1_300_000,
                    "thrusts": up_thrusts(2)},
         "range": {"hi": 110.0, "lo": 100.0, "bars": 20},
         "hi52": 112.0, "lo52": 70.0,
         "rsi": {"daily": 55.0}, "macd": {"daily": {"hist": 0.2}},
         "returns": {"1m": 3.0, "3m": 9.0},
         "entry_gate": {"rr_at_current_price": 2.0},
         "score": {"total": 6.5}}
    o.update(over)
    return o


def ctx(**over):
    # ud_ratio 1.60 lands on the 1.50-2.00 rung, so fit_accumulation returns 8 --
    # deliberately NEITHER the top nor the floor of the ladder. A fixture pinned
    # at 10 would hide a dropped accumulation term behind a full-marks score, and
    # one pinned at the 2.0 floor would hide it behind the None case.
    c = {"rows": contracting_series([4.0, 2.5, 1.0], price=105.0, bars_per_window=8),
         "rs": {"1m": 1.0, "3m": 5.0},
         "atr_pctile": 0.20, "sma200_rising": True, "sma50_rising": True,
         "ud_ratio": 1.60}
    c.update(over)
    return c


class TestThresholdLookup(unittest.TestCase):
    """T() picks the right element of the (loosened, strict) pair.

    Without this, T returning `lo if strict else st` would still pass every
    predicate test that only ever compares the two MODES against each other --
    it would just swap which mode is the tight one, and near-miss fixtures sit
    far enough from both numbers to survive the swap.
    """

    def test_loosened_takes_the_first_element(self):
        self.assertEqual(setups.T("COILED", "min_bars", False), 16)
        self.assertAlmostEqual(setups.T("COILED", "atr_pctile", False), 0.333)
        self.assertIs(setups.T("COILED", "sma50_rising", False), False)

    def test_strict_takes_the_second_element(self):
        self.assertEqual(setups.T("COILED", "min_bars", True), 20)
        self.assertAlmostEqual(setups.T("COILED", "atr_pctile", True), 0.25)
        self.assertIs(setups.T("COILED", "sma50_rising", True), True)

    def test_registry_names_every_setup_the_screen_reports(self):
        self.assertEqual(setups.SETUPS,
                         ("COILED", "BREAKOUT", "LEADER", "PULLBACK", "TURN"))


class TestBand(unittest.TestCase):
    """band()/band_desc() are the only scoring primitives, and no fit_* test can
    reach their fall-through arm: every match_* guarantees its evidence sits
    inside the last cut before fit_* ever sees it. Probed directly here."""

    CUTS = [(0.85, 10), (0.70, 8), (0.50, 6)]
    DESC = [(0.50, 10), (0.65, 8), (0.80, 6)]

    def test_band_takes_the_first_satisfied_cut(self):
        self.assertEqual(setups.band(0.90, self.CUTS), 10)
        self.assertEqual(setups.band(0.75, self.CUTS), 8)
        self.assertEqual(setups.band(0.60, self.CUTS), 6)

    def test_band_is_inclusive_at_the_cut(self):
        """`>=`, not `>`: a value sitting exactly on a cut earns that cut."""
        self.assertEqual(setups.band(0.85, self.CUTS), 10)
        self.assertEqual(setups.band(0.70, self.CUTS), 8)
        self.assertEqual(setups.band(0.50, self.CUTS), 6)

    def test_band_just_below_a_cut_drops_to_the_next(self):
        self.assertEqual(setups.band(0.8499, self.CUTS), 8)
        self.assertEqual(setups.band(0.4999, self.CUTS), 0.0)

    def test_band_below_every_cut_is_zero(self):
        self.assertEqual(setups.band(0.0, self.CUTS), 0.0)
        self.assertEqual(setups.band(-5.0, self.CUTS), 0.0)

    def test_band_desc_takes_the_first_satisfied_cut(self):
        self.assertEqual(setups.band_desc(0.10, self.DESC), 10)
        self.assertEqual(setups.band_desc(0.60, self.DESC), 8)
        self.assertEqual(setups.band_desc(0.75, self.DESC), 6)

    def test_band_desc_is_inclusive_at_the_cut(self):
        """`<=`, not `<`."""
        self.assertEqual(setups.band_desc(0.50, self.DESC), 10)
        self.assertEqual(setups.band_desc(0.65, self.DESC), 8)
        self.assertEqual(setups.band_desc(0.80, self.DESC), 6)

    def test_band_desc_just_above_a_cut_drops_to_the_next(self):
        self.assertEqual(setups.band_desc(0.5001, self.DESC), 8)
        self.assertEqual(setups.band_desc(0.8001, self.DESC), 0.0)

    def test_band_desc_above_every_cut_is_zero(self):
        self.assertEqual(setups.band_desc(99.0, self.DESC), 0.0)


class TestLiquid(unittest.TestCase):
    def test_turnover_above_the_floor_is_liquid(self):
        c = {"rows": flat_series(50, price=100.0, vol=1_000_000)}   # 10 cr/day
        self.assertTrue(setups.liquid(c, 5.0))

    def test_turnover_below_the_floor_is_not(self):
        c = {"rows": flat_series(50, price=100.0, vol=1_000_000)}
        self.assertFalse(setups.liquid(c, 25.0))

    def test_floor_is_inclusive(self):
        """`>=`: a name sitting exactly on the floor passes. Both sides of the
        comparison are pinned here, one tick apart, so `>` cannot survive."""
        c = {"rows": flat_series(50, price=100.0, vol=1_000_000)}
        self.assertTrue(setups.liquid(c, 10.0))
        self.assertFalse(setups.liquid(c, 10.000001))

    def test_window_is_the_last_fifty_bars(self):
        """The hardcoded 50 is load-bearing.

        A 60-bar ladder medians 35.5 crore over its last 50 bars but 30.5 over
        all 60, so passing len(rows) or omitting the window changes the verdict
        at a floor set between the two.
        """
        c = {"rows": turnover_ladder(60)}
        self.assertTrue(setups.liquid(c, 35.5))
        self.assertFalse(setups.liquid(c, 35.6))
        self.assertTrue(setups.liquid(c, 33.0))    # False for a 60-bar window


class TestNoDownThrust(unittest.TestCase):
    ROWS = trend_series(30)

    def obj(self, thrusts, rows=ROWS):
        o = {"volume": {"thrusts": thrusts}}
        if rows is not None:
            o["_rows"] = rows
        return o

    def thrust(self, index, direction):
        return {"date": str(self.ROWS[index]["t"]), "dir": direction,
                "vol": 5_000_000, "x_avg": 3.1}

    def test_no_thrusts_at_all_is_clean(self):
        self.assertTrue(setups._no_down_thrust(self.obj([]), 10))

    def test_down_thrust_inside_the_window_is_dirty(self):
        self.assertFalse(setups._no_down_thrust(self.obj([self.thrust(-1, "down")]), 10))

    def test_down_thrust_on_the_oldest_bar_in_the_window_is_dirty(self):
        """Window boundary, INSIDE edge: rows[-bars] is the first bar counted.

        rows[-10:] must include the 10th-from-last bar; an off-by-one slice
        (rows[-bars + 1:]) drops exactly this bar and lets the thrust through.
        """
        self.assertFalse(setups._no_down_thrust(self.obj([self.thrust(-10, "down")]), 10))

    def test_down_thrust_one_bar_outside_the_window_is_clean(self):
        """Window boundary, OUTSIDE edge: rows[-11] must NOT be counted.

        Paired with the test above so the window is pinned from both sides --
        either alone leaves a one-bar-wide error alive.
        """
        self.assertTrue(setups._no_down_thrust(self.obj([self.thrust(-11, "down")]), 10))

    def test_up_thrust_inside_the_window_is_clean(self):
        """The direction label is read, not ignored: an accumulation day on 3x
        volume is the opposite of a distribution day and must not reject."""
        self.assertTrue(setups._no_down_thrust(self.obj([self.thrust(-1, "up")]), 10))

    def test_window_size_is_the_argument_not_a_constant(self):
        o = self.obj([self.thrust(-5, "down")])
        self.assertFalse(setups._no_down_thrust(o, 10))
        self.assertTrue(setups._no_down_thrust(o, 3))

    def test_missing_rows_cannot_be_evaluated_and_passes(self):
        """The `if not recent` arm. Without rows there are no dates to compare,
        so the check abstains rather than rejecting every name -- and it must
        not raise.

        Mutation note: deleting the guard is an EQUIVALENT mutant, not a killed
        one. `t["date"] in []` is False for every thrust, so the any() below
        already returns True on empty rows. The guard is documentation of intent
        and a cheap short-circuit, not load-bearing logic -- so this test pins
        the BEHAVIOUR (abstain, don't raise, don't reject) and makes no claim
        about which line produces it.
        """
        self.assertTrue(setups._no_down_thrust(self.obj([self.thrust(-1, "down")],
                                                        rows=None), 10))
        self.assertTrue(setups._no_down_thrust(self.obj([self.thrust(-1, "down")],
                                                        rows=[]), 10))


class TestCoiledMatches(unittest.TestCase):
    def test_textbook_coiled_matches(self):
        ev = setups.match_coiled(result(), ctx())
        self.assertIsNotNone(ev)
        self.assertLess(ev["contraction"], 1.0)
        self.assertGreaterEqual(ev["pos_in_base"], 0.5)

    def test_evidence_reports_the_measured_numbers(self):
        """Pins the evidence to the fixture rather than to inequalities.

        The FOUR windows measure 7.619 / 4.762 / 4.762 / 1.905 percent, so
        contraction is 1.905/7.619 = 0.25 -- last window over FIRST. Dividing by
        any other window satisfies every `< 1.0` assertion above; in particular
        widths[2]/widths[0] -- the pre-correction index, correct only for three
        windows -- gives 0.625 here, so the index arithmetic is pinned to the
        first-to-last span rather than to a literal 2.
        """
        ev = setups.match_coiled(result(), ctx())
        self.assertAlmostEqual(ev["contraction"], 0.25, places=6)
        self.assertAlmostEqual(ev["pos_in_base"], 0.8, places=6)
        self.assertAlmostEqual(ev["dryup"], 0.75, places=6)
        self.assertEqual(len(ev["widths"]), 4)
        self.assertAlmostEqual(ev["widths"][0], 7.6190476, places=6)
        self.assertAlmostEqual(ev["widths"][-1], 1.9047619, places=6)
        self.assertNotAlmostEqual(ev["widths"][2], ev["widths"][-1], places=6)

    def test_fit_is_in_range_and_rewards_tighter_contraction(self):
        tight = setups.fit_coiled(setups.match_coiled(result(), ctx()))
        loose_ctx = ctx(rows=contracting_series([4.0, 3.9, 3.8], price=105.0,
                                                bars_per_window=8))
        loose = setups.fit_coiled(setups.match_coiled(result(), loose_ctx))
        self.assertTrue(0.0 <= loose <= tight <= 10.0)
        self.assertGreater(tight, loose)

    def test_fit_weights_are_thirty_five_twenty_five_twenty_twenty(self):
        """Pins the absolute score, not just the ordering.

        contraction 0.25 -> 10, position 0.80 -> 8, dry-up 0.75 -> 8,
        accumulation 1.60 -> 8, so
        0.35*10 + 0.25*8 + 0.20*8 + 0.20*8 = 3.5 + 2.0 + 1.6 + 1.6 = 8.7.
        Any other weighting that preserves the ordering above -- equal quarters,
        for instance, which gives 8.5 -- lands elsewhere.
        """
        self.assertAlmostEqual(setups.fit_coiled(setups.match_coiled(result(), ctx())),
                               8.7, places=6)

    def test_the_accumulation_term_is_exactly_a_fifth_of_the_score(self):
        """The new term, isolated. Moving the ratio from the 1.50 rung (8) to
        the sub-1.00 rung (2) must move the total by 0.20 * 6 = 1.2 and nothing
        else -- every other input is held.

        Without this the 20% weight is pinned only by the sum above, which any
        redistribution among four terms could reproduce.
        """
        strong = setups.fit_coiled(setups.match_coiled(result(), ctx(ud_ratio=1.60)))
        weak = setups.fit_coiled(setups.match_coiled(result(), ctx(ud_ratio=0.80)))
        self.assertAlmostEqual(strong - weak, 1.2, places=6)
        self.assertAlmostEqual(weak, 7.5, places=6)

    def test_an_unmeasurable_ratio_scores_the_floor_not_the_top(self):
        """COILED does NOT gate on the up/down ratio, so a None reaches its fit.
        It must score the 2.0 floor -- identical to a distributing name, and 6
        sub-score points below the fixture -- rather than being rewarded for the
        absence of evidence."""
        none_ = setups.fit_coiled(setups.match_coiled(result(), ctx(ud_ratio=None)))
        weak = setups.fit_coiled(setups.match_coiled(result(), ctx(ud_ratio=0.80)))
        self.assertAlmostEqual(none_, weak, places=6)
        self.assertAlmostEqual(none_, 7.5, places=6)

    def test_fit_rewards_a_deeper_volume_dryup(self):
        """The dry-up term carries weight of its own; the ordering test above
        varies only the contraction, so a fit that ignored dry-up survived it."""
        wet = result(volume={"dryup_ratio": 0.95, "avg20": 1, "avg50": 1,
                             "thrusts": up_thrusts(2)})
        self.assertGreater(setups.fit_coiled(setups.match_coiled(result(), ctx())),
                           setups.fit_coiled(setups.match_coiled(wet, ctx())))

    def test_fit_rewards_price_higher_in_the_base(self):
        """Likewise for the position term: 108 sits at 0.80 of the base and 106
        at 0.60, which band()s to 8 and 6."""
        self.assertGreater(setups.fit_coiled(setups.match_coiled(result(), ctx())),
                           setups.fit_coiled(setups.match_coiled(result(price=106.0),
                                                                 ctx())))


class TestCoiledNearMisses(unittest.TestCase):
    """One test per condition, so every threshold is proven load-bearing."""

    def test_base_too_short_rejects(self):
        o = result(range={"hi": 110.0, "lo": 100.0, "bars": 15})
        self.assertIsNone(setups.match_coiled(o, ctx()))

    def test_atr_not_compressed_rejects(self):
        self.assertIsNone(setups.match_coiled(result(), ctx(atr_pctile=0.60)))

    def test_only_one_contraction_rejects(self):
        c = ctx(rows=contracting_series([2.0, 4.0, 3.0], price=105.0, bars_per_window=8))
        self.assertIsNone(setups.match_coiled(result(), c))

    def test_price_low_in_base_rejects(self):
        self.assertIsNone(setups.match_coiled(result(price=102.0), ctx()))

    def test_below_sma50_rejects(self):
        o = result(ma={"sma20": 104.0, "sma50": 112.0, "sma100": 100.0, "sma200": 98.0})
        self.assertIsNone(setups.match_coiled(o, ctx()))

    def test_sma200_falling_rejects(self):
        self.assertIsNone(setups.match_coiled(result(), ctx(sma200_rising=False)))

    def test_no_volume_dryup_rejects(self):
        o = result(volume={"dryup_ratio": 1.4, "avg20": 1, "avg50": 1, "thrusts": up_thrusts(2)})
        self.assertIsNone(setups.match_coiled(o, ctx()))

    # --- conditions the brief's near-misses do not reach --------------------

    def test_above_sma50_but_below_sma200_rejects(self):
        """The sma200 guard has no near-miss of its own above: the sma50 fixture
        (sma50 = 112) trips the EARLIER guard, so deleting the sma200 line
        survives. Here 108 clears sma50 = 102 and fails only on sma200."""
        o = result(ma={"sma20": 104.0, "sma50": 102.0, "sma100": 100.0, "sma200": 115.0})
        self.assertIsNone(setups.match_coiled(o, ctx()))

    def test_missing_sma50_rejects(self):
        """The `not ma["sma50"]` arm -- a young listing has no 50-day average.
        Every other fixture supplies a float, so the falsy arm was uncovered."""
        o = result(ma={"sma20": 104.0, "sma50": None, "sma100": 100.0, "sma200": 98.0})
        self.assertIsNone(setups.match_coiled(o, ctx()))

    def test_missing_sma200_rejects(self):
        o = result(ma={"sma20": 104.0, "sma50": 102.0, "sma100": 100.0, "sma200": None})
        self.assertIsNone(setups.match_coiled(o, ctx()))

    def test_missing_dryup_ratio_rejects(self):
        """The `dryup is None` arm. `None >= 1.0` raises on Python 3, so
        deleting this half of the guard is a crash, not a wrong answer."""
        o = result(volume={"dryup_ratio": None, "avg20": 1, "avg50": 1, "thrusts": up_thrusts(2)})
        self.assertIsNone(setups.match_coiled(o, ctx()))

    def test_zero_width_base_rejects_without_dividing_by_zero(self):
        """The `if span else 0.0` arm: hi == lo makes the base infinitely thin.
        No other fixture has a degenerate range, so the guard was uncovered and
        deleting it raises ZeroDivisionError instead of returning None."""
        o = result(range={"hi": 110.0, "lo": 110.0, "bars": 20})
        self.assertIsNone(setups.match_coiled(o, ctx()))

    def test_too_few_bars_to_form_four_windows_rejects(self):
        """The `len(widths) != COILED_WINDOWS` arm. window_widths returns []
        below four bars a window, and the contraction count would then index
        into nothing.

        Nine bars over four windows gives size 2, so the guard fires even though
        the base LENGTH field says 20 -- rng["bars"] is the engine's count and
        ctx["rows"] is the data actually present; they can disagree.
        """
        c = ctx(rows=contracting_series([4.0, 2.5, 1.0], price=105.0,
                                        bars_per_window=3))   # 9 bars -> size 2
        self.assertIsNone(setups.match_coiled(result(), c))


class TestCoiledBoundaries(unittest.TestCase):
    """Accept AND reject sides of each loosened threshold, one tick apart."""

    def test_base_length_floor_is_sixteen_bars(self):
        """Both sides of the bars guard, isolated.

        The brief's short-base fixture rejects for a second reason -- a short
        base re-slices ctx["rows"], which stops contracting -- so deleting the
        guard survives it. The smooth taper contracts at both lengths, leaving
        the guard as the only difference between these two.

        Sixteen is not a free choice: four windows of four bars each is the
        smallest base window_widths will measure. See TestCoiledWindowArithmetic.
        """
        c = ctx(rows=taper(20))
        self.assertIsNotNone(setups.match_coiled(
            result(range={"hi": 110.0, "lo": 100.0, "bars": 16}), c))
        self.assertIsNone(setups.match_coiled(
            result(range={"hi": 110.0, "lo": 100.0, "bars": 15}), c))

    def test_atr_percentile_ceiling_is_inclusive(self):
        self.assertIsNotNone(setups.match_coiled(result(), ctx(atr_pctile=0.333)))
        self.assertIsNone(setups.match_coiled(result(), ctx(atr_pctile=0.334)))

    def test_position_in_base_floor_is_inclusive(self):
        """Price at exactly half the base is accepted; just under is not.

        The brief's low-price fixture (102) is also AT sma50, so it rejects even
        with the position guard deleted. 104 and 105 both clear sma50 = 102.
        """
        ev = setups.match_coiled(result(price=105.0), ctx())
        self.assertIsNotNone(ev)
        self.assertAlmostEqual(ev["pos_in_base"], 0.50, places=9)
        self.assertIsNone(setups.match_coiled(result(price=104.0), ctx()))

    def test_price_must_be_strictly_above_both_averages(self):
        """`<=` not `<`: sitting exactly ON the average is not above it."""
        at50 = result(ma={"sma20": 104.0, "sma50": 108.0, "sma100": 100.0,
                          "sma200": 98.0})
        self.assertIsNone(setups.match_coiled(at50, ctx()))
        at200 = result(ma={"sma20": 104.0, "sma50": 102.0, "sma100": 100.0,
                           "sma200": 108.0})
        self.assertIsNone(setups.match_coiled(at200, ctx()))

    def test_dryup_ceiling_is_exclusive(self):
        """`>=`: a ratio of exactly 1.0 is average volume, not a dry-up."""
        at = result(volume={"dryup_ratio": 1.0, "avg20": 1, "avg50": 1, "thrusts": up_thrusts(2)})
        self.assertIsNone(setups.match_coiled(at, ctx()))
        under = result(volume={"dryup_ratio": 0.999, "avg20": 1, "avg50": 1,
                               "thrusts": up_thrusts(2)})
        self.assertIsNotNone(setups.match_coiled(under, ctx()))

    def test_two_contractions_is_the_floor_and_one_is_not(self):
        two = ctx(rows=contracting_series([5.0, 3.0, 1.5], price=105.0,
                                          bars_per_window=8))
        self.assertIsNotNone(setups.match_coiled(result(), two))
        one = ctx(rows=contracting_series([5.0, 6.0, 1.5], price=105.0,
                                          bars_per_window=8))
        self.assertIsNone(setups.match_coiled(result(), one))


def saw_tooth(first, mid_a, mid_b, last, price=105.0):
    """Four aligned five-bar windows with the half-ranges given.

    Twenty bars split four ways lands the window boundaries exactly on the
    fixture's own, so the widths match_coiled measures are the ones written
    here rather than an artefact of the re-slice.
    """
    return contracting_series([first, mid_a, mid_b, last], price=price,
                              bars_per_window=5)


class TestCoiledRequiresNetContraction(unittest.TestCase):
    """Counting local narrowings is not the same as contracting.

    `contractions` counts consecutive comparisons, and a saw-tooth satisfies
    two of three while ending wider than it started. OIL ranked COILED #11 on
    windows 6.48 / 5.62 / 4.98 / 6.58 -- its own Contraction column read 1.01 --
    with ALKEM at 1.205 and GLENMARK alongside it. Three of eleven rows were
    names that were not contracting at all.
    """

    #: OIL's shape, to scale: two narrowings then a final window wider than the
    #: first. The consecutive count is 2, which clears the loosened floor.
    OIL = (3.40, 2.95, 2.60, 3.45)

    def test_the_fixture_really_does_clear_the_consecutive_count(self):
        """Otherwise the rejection below could be the old gate firing, and the
        new one could be deleted without a failure."""
        widths = setups.window_widths(saw_tooth(*self.OIL), setups.COILED_WINDOWS)
        self.assertEqual(len(widths), 4)
        contractions = sum(1 for i in range(1, 4) if widths[i] < widths[i - 1])
        self.assertEqual(contractions, 2)
        self.assertGreaterEqual(contractions,
                                setups.THRESHOLDS["COILED"]["contractions"][0])

    def test_a_base_that_ends_wider_than_it_started_rejects(self):
        self.assertIsNone(setups.match_coiled(result(),
                                              ctx(rows=saw_tooth(*self.OIL))))

    def test_the_ratio_the_old_code_would_have_printed_is_above_one(self):
        """Pins WHY it rejects: 3.45 / 3.40 = 1.0147, the 1.01 the report
        printed. A fixture that merely failed some other gate would satisfy the
        assertion above without saying anything about contraction."""
        widths = setups.window_widths(saw_tooth(*self.OIL), setups.COILED_WINDOWS)
        self.assertGreater(widths[-1] / widths[0], 1.0)
        self.assertAlmostEqual(widths[-1] / widths[0], 3.45 / 3.40, places=6)

    def test_the_same_base_ending_narrower_than_it_started_matches(self):
        """The accept arm, one tick the other side: only the last window moves,
        so nothing but the net comparison separates this from the case above."""
        ev = setups.match_coiled(result(),
                                 ctx(rows=saw_tooth(3.40, 2.95, 2.60, 3.39)))
        self.assertIsNotNone(ev)
        self.assertLess(ev["contraction"], 1.0)

    def test_a_base_ending_exactly_where_it_started_is_not_a_contraction(self):
        """`>=`, not `>`: equal width first and last is a range, not a coil."""
        self.assertIsNone(setups.match_coiled(
            result(), ctx(rows=saw_tooth(3.40, 2.95, 2.60, 3.40))))

    def test_the_gate_is_applied_in_strict_mode_too(self):
        """Strict cannot be looser than loosened here either.

        The guard can never be the REASON a strict name rejects -- strict wants
        3 of 3 consecutive narrowings, which already forces the last window
        below the first -- so this asserts the property rather than a reachable
        arm: the saw-tooth is rejected in both modes.

        Mutation note: `if not strict and widths[-1] >= widths[0]` is therefore
        an EQUIVALENT mutant, not a survivor. No input can distinguish it, and
        the test below proves why. The guard is written unconditionally so the
        two modes cannot start disagreeing about what COILED means the moment
        the strict contraction count is loosened below 3 of 3.
        """
        c = ctx(rows=saw_tooth(*self.OIL))
        self.assertIsNone(setups.match_coiled(result(), c, strict=False))
        self.assertIsNone(setups.match_coiled(result(), c, strict=True))

    def test_three_of_three_narrowings_implies_net_contraction(self):
        """Why the guard is unreachable under strict, asserted rather than
        assumed: if a future change made a 3-of-3 base able to end wider than it
        started, this fails and the claim in the comment stops being true."""
        for widths in ([5.0, 4.0, 3.0, 2.0], [9.0, 8.9, 8.8, 8.7],
                       [2.0, 1.0, 0.5, 0.25]):
            contractions = sum(1 for i in range(1, 4)
                               if widths[i] < widths[i - 1])
            self.assertEqual(contractions, 3)
            self.assertLess(widths[-1], widths[0])

    def test_no_matching_name_can_report_a_contraction_of_one_or_more(self):
        """The property the report depends on, over a grid of base shapes: the
        Contraction column of a COILED row is now always below 1.00."""
        checked = 0
        for last in (1.0, 2.0, 2.59, 2.60, 3.39, 3.40, 3.41, 5.0):
            for mid in (2.60, 2.95, 3.50):
                for strict in (False, True):
                    ev = setups.match_coiled(
                        result(), ctx(rows=saw_tooth(3.40, mid, 2.60, last)),
                        strict=strict)
                    if ev is not None:
                        checked += 1
                        self.assertLess(ev["contraction"], 1.0,
                                        "last=%s mid=%s strict=%s"
                                        % (last, mid, strict))
        self.assertGreater(checked, 0, "grid produced no COILED matches at all")


class TestCoiledFunnel(unittest.TestCase):
    """Every rejecting condition records itself, once, under its own label, in
    the order the predicate applies it.

    The funnel is what the empty screen prints, and `reached` is recovered by
    subtraction -- so two conditions sharing a label merge into one row and a
    step out of sequence prints the funnel out of order. Inserting the
    net-contraction gate renumbered every step below it, which nothing else in
    the suite would have noticed.
    """

    #: one input per rejecting condition, in predicate order
    CASES = [
        ("base too short", dict(range={"hi": 110.0, "lo": 100.0, "bars": 15}),
         ctx(), False),
        ("volatility not compressed", {}, ctx(atr_pctile=0.60), False),
        ("too few bars for four windows", {},
         ctx(rows=contracting_series([4.0, 2.5, 1.0], price=105.0,
                                     bars_per_window=3)), False),
        ("too few narrowings", {},
         ctx(rows=contracting_series([2.0, 4.0, 3.0], price=105.0,
                                     bars_per_window=8)), False),
        ("no net contraction", {},
         ctx(rows=saw_tooth(3.40, 2.95, 2.60, 3.45)), False),
        ("low in the base", dict(price=104.0), ctx(), False),
        ("below the 50-day", dict(ma={"sma20": 104.0, "sma50": 112.0,
                                      "sma100": 100.0, "sma200": 98.0}),
         ctx(), False),
        ("below the 200-day", dict(ma={"sma20": 104.0, "sma50": 102.0,
                                       "sma100": 100.0, "sma200": 115.0}),
         ctx(), False),
        ("200-day falling", {}, ctx(sma200_rising=False), False),
        ("50-day falling, strict only", {},
         ctx(rows=taper(20), sma50_rising=False), True),
        ("volume not dried up",
         dict(volume={"dryup_ratio": 1.4, "avg20": 1, "avg50": 1,
                      "thrusts": up_thrusts(2)}), ctx(), False),
    ]

    def test_each_condition_records_itself_exactly_once(self):
        for name, over, c, strict in self.CASES:
            diag = {}
            self.assertIsNone(setups.match_coiled(result(**over), c,
                                                  strict=strict, diag=diag), name)
            self.assertEqual(len(diag), 1, "%s recorded %s" % (name, diag))
            (label, (step, count)), = diag.items()
            self.assertEqual(count, 1, name)
            self.assertTrue(label.strip(), name)

    def test_the_conditions_are_distinct_and_ordered_as_tested(self):
        steps = []
        for name, over, c, strict in self.CASES:
            diag = {}
            setups.match_coiled(result(**over), c, strict=strict, diag=diag)
            (label, (step, _)), = diag.items()
            steps.append((step, label))
        self.assertEqual(len(set(l for _, l in steps)), len(self.CASES),
                         "two conditions share a label")
        self.assertEqual(len(set(s for s, _ in steps)), len(self.CASES),
                         "two conditions share a step number")
        self.assertEqual(steps, sorted(steps), "steps are out of predicate order")

    def test_the_net_contraction_condition_is_legible_in_the_report(self):
        diag = {}
        setups.match_coiled(result(), ctx(rows=saw_tooth(3.40, 2.95, 2.60, 3.45)),
                            diag=diag)
        (label, _), = diag.items()
        self.assertIn("narrower at the end", label)

    def test_a_match_records_nothing(self):
        diag = {}
        self.assertIsNotNone(setups.match_coiled(result(), ctx(), diag=diag))
        self.assertEqual(diag, {})

    def test_the_verdict_is_identical_with_and_without_the_funnel(self):
        for name, over, c, strict in self.CASES + [("match", {}, ctx(), False)]:
            plain = setups.match_coiled(result(**over), c, strict=strict)
            traced = setups.match_coiled(result(**over), c, strict=strict, diag={})
            self.assertEqual(plain, traced, name)


class TestCoiledStrict(unittest.TestCase):
    def test_strict_requires_three_contractions(self):
        """Two contractions out of three comparisons passes loosened, not strict.

        [5, 3, 1.5] over eight-bar windows, re-sliced to the last 20 bars and
        split four ways, measures 9.52 / 5.71 / 5.71 / 2.86 -- the middle pair
        ties because the fixture's window boundaries do not line up with the
        re-slice, so exactly two of the three comparisons contract. That is the
        loosened floor and one short of strict.
        """
        c = ctx(rows=contracting_series([5.0, 3.0, 1.5], price=105.0, bars_per_window=8))
        ev = setups.match_coiled(result(), c, strict=False)
        self.assertIsNotNone(ev)
        self.assertEqual(len(ev["widths"]), 4)
        self.assertIsNone(setups.match_coiled(result(), c, strict=True))

    def test_strict_contraction_threshold_is_satisfiable(self):
        """Three contractions out of three comparisons MATCHES strict.

        This is the whole point of four windows. With three windows there were
        only two comparisons, `contractions` was capped at 2, and the strict
        threshold of 3 could never be met -- strict COILED silently matched
        nothing and every other strict-COILED assertion in this class was
        satisfied vacuously by a guard that rejected first.

        A smooth 20-bar taper contracts across every one of the four windows,
        and the rest of the fixture already clears the strict atr_pctile,
        pos_in_base, dry-up and rising-sma50 thresholds, so a strict match here
        proves the contraction arm is reachable rather than merely bypassed.
        """
        c = ctx(rows=taper(20))
        ev = setups.match_coiled(result(), c, strict=True)
        self.assertIsNotNone(ev, "strict COILED matches nothing at all")
        w = ev["widths"]
        self.assertEqual(len(w), 4)
        self.assertTrue(w[0] > w[1] > w[2] > w[3], w)

    def test_strict_guards_after_the_contraction_count_still_reject(self):
        """The contraction arm no longer masks the rest of strict.

        Same three-contraction base as above, so every assertIsNone here is
        reached at the guard it names instead of being satisfied earlier.
        """
        c = ctx(rows=taper(20))
        self.assertIsNone(setups.match_coiled(result(), ctx(rows=taper(20),
                                                            atr_pctile=0.30),
                                              strict=True))
        self.assertIsNone(setups.match_coiled(result(price=105.0), c, strict=True))
        wet = result(volume={"dryup_ratio": 0.95, "avg20": 1, "avg50": 1,
                             "thrusts": up_thrusts(2)})
        self.assertIsNone(setups.match_coiled(wet, c, strict=True))

    def test_strict_requires_rising_sma50(self):
        """The taper fixture, not the default one: with the default base strict
        rejects at the contraction count first and this assertion is vacuous --
        deleting the sma50_rising guard outright would still pass. The third
        case proves non-vacuity by matching strict once the average is rising.
        """
        falling = ctx(rows=taper(20), sma50_rising=False)
        self.assertIsNotNone(setups.match_coiled(result(), falling))
        self.assertIsNone(setups.match_coiled(result(), falling, strict=True))
        self.assertIsNotNone(setups.match_coiled(
            result(), ctx(rows=taper(20), sma50_rising=True), strict=True))

    def test_loosened_ignores_a_falling_sma50(self):
        """The other arm of `T(...) and not ctx["sma50_rising"]`: in loosened
        mode the threshold is False, so the second operand is never consulted
        and a falling 50-day average cannot reject."""
        self.assertIsNotNone(setups.match_coiled(result(), ctx(sma50_rising=False)))
        self.assertIsNotNone(setups.match_coiled(result(), ctx(sma50_rising=True)))


class TestCoiledWindowArithmetic(unittest.TestCase):
    """min_bars and the window count are ONE number wearing two hats.

    match_coiled splits the base into N windows; window_widths refuses any
    window shorter than some minimum and returns []; match_coiled then returns
    None. So a min_bars below N * that minimum makes loosened COILED match
    NOTHING for every base in the gap -- silently, with no rejection anyone can
    observe, which is exactly the failure mode the four-window correction
    exists to remove.

    Nothing in the language couples the two numbers, so these tests DERIVE both
    from the implementation -- the window count from what match_coiled actually
    passes, the per-window minimum by probing window_widths -- rather than
    restating literals. Changing COILED_WINDOWS to 5 and leaving min_bars at 16
    fails here; a hardcoded assertEqual(min_bars, 16) would not.
    """

    def windows_requested(self):
        """The n match_coiled actually hands to window_widths."""
        seen = []
        original = setups.window_widths

        def spy(rows, n=3):
            seen.append(n)
            return original(rows, n)

        setups.window_widths = spy
        try:
            setups.match_coiled(result(), ctx(rows=taper(30)))
        finally:
            setups.window_widths = original
        self.assertEqual(len(seen), 1,
                         "match_coiled called window_widths %d times" % len(seen))
        return seen[0]

    def bars_per_window_enforced(self, n):
        """Smallest per-window bar count window_widths will measure, probed.

        Probed rather than read off MIN_BARS_PER_WINDOW so that renaming or
        bypassing the constant cannot make this test agree with itself.
        """
        for size in range(1, 40):
            if setups.window_widths(flat_series(size * n, price=100.0), n):
                return size
        self.fail("window_widths accepts no window size at all")

    def test_match_coiled_asks_for_four_windows(self):
        self.assertEqual(self.windows_requested(), 4)

    def test_min_bars_can_fill_every_window_match_coiled_asks_for(self):
        n = self.windows_requested()
        per = self.bars_per_window_enforced(n)
        lo, st = setups.THRESHOLDS["COILED"]["min_bars"]
        self.assertGreaterEqual(
            lo, n * per,
            "loosened min_bars %d cannot fill %d windows of %d bars: COILED "
            "matches nothing for bases of %d-%d bars" % (lo, n, per, lo, n * per - 1))
        self.assertGreaterEqual(st, lo, "strict min_bars is looser than loosened")

    def test_a_base_at_exactly_the_loosened_floor_still_yields_widths(self):
        """The tie, exercised end to end rather than as arithmetic.

        A base of exactly min_bars bars, with exactly that many rows behind it,
        must still produce a full widths list -- otherwise the floor is one bar
        too low whatever the multiplication says.
        """
        lo = setups.THRESHOLDS["COILED"]["min_bars"][0]
        c = ctx(rows=taper(lo))
        ev = setups.match_coiled(result(range={"hi": 110.0, "lo": 100.0,
                                               "bars": lo}), c)
        self.assertIsNotNone(ev, "the loosened floor is a silent vacuum")
        self.assertEqual(len(ev["widths"]), self.windows_requested())


class TestUpThrustCount(unittest.TestCase):
    """_up_thrust_count in isolation: the label, the window and both ends of it."""

    ROWS = trend_series(30)

    def obj(self, thrusts):
        return {"volume": {"thrusts": thrusts}}

    def thrust(self, index, direction):
        return {"date": str(self.ROWS[index]["t"]), "dir": direction,
                "vol": 5_000_000, "x_avg": 3.1}

    def test_no_thrusts_at_all_counts_zero(self):
        self.assertEqual(setups._up_thrust_count(self.obj([]), self.ROWS, 10), 0)

    def test_an_up_thrust_inside_the_window_counts(self):
        self.assertEqual(
            setups._up_thrust_count(self.obj([self.thrust(-1, "up")]), self.ROWS, 10), 1)

    def test_a_down_thrust_does_not_count(self):
        """The direction label is READ, not ignored. A distribution day on 3x
        volume is the opposite of accumulation, and counting it would let the
        gate be satisfied by exactly the bar it exists to exclude."""
        self.assertEqual(
            setups._up_thrust_count(self.obj([self.thrust(-1, "down")]), self.ROWS, 10), 0)

    def test_several_up_thrusts_are_added_up(self):
        """Not a boolean wearing a number's clothes: strict asks for two."""
        self.assertEqual(
            setups._up_thrust_count(self.obj([self.thrust(-1, "up"),
                                              self.thrust(-4, "up"),
                                              self.thrust(-6, "down")]),
                                    self.ROWS, 10), 2)

    def test_the_oldest_bar_in_the_window_counts(self):
        """Window boundary, INSIDE edge: rows[-bars] is the first bar counted."""
        self.assertEqual(
            setups._up_thrust_count(self.obj([self.thrust(-10, "up")]), self.ROWS, 10), 1)

    def test_one_bar_outside_the_window_does_not(self):
        """Window boundary, OUTSIDE edge. Paired with the test above, so a
        one-bar-wide slice error cannot survive either alone."""
        self.assertEqual(
            setups._up_thrust_count(self.obj([self.thrust(-11, "up")]), self.ROWS, 10), 0)

    def test_the_window_is_the_argument_not_a_constant(self):
        o = self.obj([self.thrust(-5, "up")])
        self.assertEqual(setups._up_thrust_count(o, self.ROWS, 10), 1)
        self.assertEqual(setups._up_thrust_count(o, self.ROWS, 3), 0)

    def test_a_non_positive_window_counts_nothing(self):
        """rows[-0:] is the WHOLE series, so an unguarded zero would count every
        thrust on record and report it as "the last no bars"."""
        o = self.obj([self.thrust(-1, "up")])
        self.assertEqual(setups._up_thrust_count(o, self.ROWS, 0), 0)
        self.assertEqual(setups._up_thrust_count(o, self.ROWS, -5), 0)

    def test_no_rows_counts_nothing(self):
        """No dates to compare against, so nothing can be inside the window --
        and it must not raise."""
        self.assertEqual(
            setups._up_thrust_count(self.obj([self.thrust(-1, "up")]), [], 10), 0)

    def test_a_missing_thrust_list_counts_nothing_rather_than_raising(self):
        self.assertEqual(setups._up_thrust_count({"volume": {}}, self.ROWS, 10), 0)

    def test_a_thrust_without_a_direction_is_not_counted_as_up(self):
        """`.get("dir") == "up"`, so a malformed record fails the gate rather
        than opening it."""
        o = self.obj([{"date": str(self.ROWS[-1]["t"]), "vol": 5_000_000}])
        self.assertEqual(setups._up_thrust_count(o, self.ROWS, 10), 0)


class TestCoiledNeedsPriorAccumulation(unittest.TestCase):
    """A base nobody ever bought is a dead stock, not a coiled spring."""

    def test_a_base_with_no_up_thrust_rejects(self):
        o = result(volume={"dryup_ratio": 0.75, "avg20": 1_000_000,
                           "avg50": 1_300_000, "thrusts": []})
        self.assertIsNone(setups.match_coiled(o, ctx()))

    def test_one_up_thrust_is_enough_loosened(self):
        o = result(volume={"dryup_ratio": 0.75, "avg20": 1_000_000,
                           "avg50": 1_300_000, "thrusts": up_thrusts(1)})
        self.assertIsNotNone(setups.match_coiled(o, ctx()))

    def test_one_up_thrust_is_not_enough_strict(self):
        """The two modes must actually differ here, or the strict pair is
        decorative. taper(20) contracts under every tail slice, so strict's
        3-of-3 contraction requirement is satisfied and the count is the only
        thing left to reject on."""
        one = result(volume={"dryup_ratio": 0.75, "avg20": 1_000_000,
                             "avg50": 1_300_000, "thrusts": up_thrusts(1)})
        two = result(volume={"dryup_ratio": 0.75, "avg20": 1_000_000,
                             "avg50": 1_300_000, "thrusts": up_thrusts(2)})
        c = ctx(rows=taper(20))
        self.assertIsNotNone(setups.match_coiled(one, c))
        self.assertIsNone(setups.match_coiled(one, c, strict=True))
        self.assertIsNotNone(setups.match_coiled(two, c, strict=True))

    def test_a_down_thrust_does_not_satisfy_the_gate(self):
        """A base that only ever traded size on the way DOWN has been
        distributed, not accumulated."""
        down = [dict(t, dir="down") for t in up_thrusts(2)]
        o = result(volume={"dryup_ratio": 0.75, "avg20": 1_000_000,
                           "avg50": 1_300_000, "thrusts": down})
        self.assertIsNone(setups.match_coiled(o, ctx()))

    def test_a_thrust_older_than_the_lookback_does_not_count(self):
        """Both ends of the 126-bar window, on a series long enough to have an
        outside. A 140-bar taper puts rows[13] outside and rows[14] inside."""
        rows = taper(140)
        inside = result(volume={"dryup_ratio": 0.75, "avg20": 1_000_000,
                                "avg50": 1_300_000,
                                "thrusts": up_thrusts(1, first_bar=14)})
        outside = result(volume={"dryup_ratio": 0.75, "avg20": 1_000_000,
                                 "avg50": 1_300_000,
                                 "thrusts": up_thrusts(1, first_bar=13)})
        self.assertIsNotNone(setups.match_coiled(inside, ctx(rows=rows)))
        self.assertIsNone(setups.match_coiled(outside, ctx(rows=rows)))

    def test_the_count_reads_the_rows_it_is_given_not_a_stashed_key(self):
        """The predicate passes ctx["rows"]; a name whose thrusts are dated
        outside that series must reject. Without this the argument could be
        replaced by o["_rows"] -- which the COILED fixtures do not set -- and
        every test here would still pass by counting nothing at all.
        """
        o = result(volume={"dryup_ratio": 0.75, "avg20": 1_000_000,
                           "avg50": 1_300_000,
                           "thrusts": [{"date": "1999-01-04", "dir": "up",
                                        "vol": 5_000_000, "x_avg": 3.1}]})
        self.assertIsNone(setups.match_coiled(o, ctx()))

    def test_the_rejection_names_the_up_thrust_condition(self):
        diag = {}
        o = result(volume={"dryup_ratio": 0.75, "avg20": 1_000_000,
                           "avg50": 1_300_000, "thrusts": []})
        setups.match_coiled(o, ctx(), diag=diag)
        (label, _), = diag.items()
        self.assertIn("up-thrust", label)

    def test_the_gate_is_the_last_one_the_predicate_applies(self):
        """Funnel position, so the report reads in predicate order. A name that
        fails BOTH the dry-up and the thrust count must be recorded at the
        dry-up, which comes first."""
        diag = {}
        o = result(volume={"dryup_ratio": 1.4, "avg20": 1_000_000,
                           "avg50": 1_300_000, "thrusts": []})
        setups.match_coiled(o, ctx(), diag=diag)
        (label, (step, _)), = diag.items()
        self.assertIn("dried up", label)
        self.assertEqual(step, 11)


class TestCoiledUpThrustLookback(unittest.TestCase):
    def test_the_lookback_is_the_atr_percentile_window(self):
        """126 is not an arbitrary number: "quiet against its own six months"
        and "accumulated at some point in those six months" have to describe one
        span, or the two halves of the setup are talking about different bases.
        """
        self.assertEqual(setups.UP_THRUST_BARS, setups.ATR_PCTILE_BARS)

    def test_the_engine_supplies_no_thrust_older_than_its_own_window(self):
        """The arithmetic note in the code, asserted rather than asserted-in-a-
        comment. analyze.detect_thrusts scans a 90-bar window, so nothing older
        than 90 bars exists to be counted and the effective lookback today is 90
        whatever this constant says. Our window must be at least as wide as the
        engine's, or we would be discarding labels the engine did supply.
        """
        import inspect
        window = inspect.signature(A.detect_thrusts).parameters["window"].default
        self.assertLessEqual(window, setups.UP_THRUST_BARS)


if __name__ == "__main__":
    unittest.main()
