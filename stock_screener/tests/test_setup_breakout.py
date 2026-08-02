import os, sys, unittest
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
sys.path.insert(0, _root)
sys.path.insert(0, _here)
import setups
from fixtures import base_rows


def result(**over):
    """compute()-shaped dict that PASSES breakout."""
    o = {"symbol": "TEST", "price": 112.0,
         "last_closed_bar": {"t": "2026-07-31", "v": 2_500_000},
         "ma": {"sma20": 106.0, "sma50": 104.0, "sma100": 101.0, "sma200": 98.0},
         "atr": {"daily": 2.0, "daily_pct": 1.8},
         "volume": {"avg20": 1_000_000, "avg50": 950_000, "dryup_ratio": 1.05,
                    "thrusts": []},
         "range": {"hi": 110.0, "lo": 100.0, "bars": 20},
         "hi52": 112.0, "lo52": 70.0,
         "rsi": {"daily": 66.0}, "macd": {"daily": {"hist": 0.9}},
         "returns": {"1m": 8.0, "3m": 14.0},
         "entry_gate": {"rr_at_current_price": 2.2},
         "score": {"total": 7.0}}
    o.update(over)
    return o


def ma(sma50=104.0, sma200=98.0):
    return {"sma20": 106.0, "sma50": sma50, "sma100": 101.0, "sma200": sma200}


def vol(v):
    return {"t": "2026-07-31", "v": v}


def base100(bars=20, lo=92.0):
    """A base topping out at exactly 100.

    Every extension threshold is a round percentage, and hi = 100 makes
    `(px - hi) / hi * 100` equal `px - 100` EXACTLY -- no float residue. With
    the brief's hi = 110 the 12% boundary lands on 12.000000000000002 and a
    test written to accept it would fail for a reason that has nothing to do
    with the guard being tested.
    """
    return {"hi": 100.0, "lo": lo, "bars": bars}


def ctx_for(rows):
    return {"rows": rows, "rs": {"1m": 4.0, "3m": 7.0},
            "atr_pctile": 0.5, "sma200_rising": True, "sma50_rising": True}


#: Bars that AGREE with result()'s range: a 100-110 base under a final bar that
#: printed a 118 high. The base high a breakout has to clear is 110 -- the bars
#: before the candidate bar -- while o["range"]["hi"] is whatever a fixture
#: declares. Every earlier version of this file passed a trend_series() that had
#: nothing to do with the declared range, which is why the predicate could gate
#: on an unsatisfiable condition with all of these tests green.
CTX = ctx_for(base_rows(120, hi=110.0, lo=100.0))

#: The same, matching base100(): a 92-100 base, so `(px - 100) / 100 * 100` is
#: exactly `px - 100` and the extension boundaries land on round numbers.
CTX100 = ctx_for(base_rows(120, hi=100.0, lo=92.0))


class TestBreakoutMatches(unittest.TestCase):
    def test_textbook_breakout_matches(self):
        ev = setups.match_breakout(result(), CTX)
        self.assertIsNotNone(ev)
        self.assertAlmostEqual(ev["vol_mult"], 2.5, places=6)
        self.assertFalse(ev["volume_light"])

    def test_volume_between_1_5_and_2_is_flagged_light(self):
        ev = setups.match_breakout(result(last_closed_bar=vol(1_700_000)), CTX)
        self.assertIsNotNone(ev)
        self.assertTrue(ev["volume_light"])

    def test_pct_above_base_is_measured_from_the_prior_base_high(self):
        """112 over a 110 high is 1.818%, NOT 2.0%.

        The brief asserts 2.0 with the comment "112 vs 110", which is the raw
        rupee gap, not the percentage the implementation computes. Pinned to the
        real value here: an implementation that divided by the base LOW (100)
        would report exactly 2.0 and pass the brief's assertion, so the wrong
        number was also the one that hid the likeliest wrong denominator.

        The 110 is now the highest high of the bars BEFORE the candidate bar,
        which is what the price had to clear -- not o["range"]["hi"], which
        includes the candidate bar's own high and cannot be cleared at all.
        """
        ev = setups.match_breakout(result(), CTX)
        self.assertAlmostEqual(ev["pct_above_base"], 1.8181818181, places=8)

    def test_evidence_reports_every_documented_key(self):
        ev = setups.match_breakout(result(), CTX)
        self.assertEqual(set(ev), {"vol_mult", "pct_above_base", "base_bars",
                                   "tightness", "volume_light"})
        self.assertEqual(ev["base_bars"], 20)
        self.assertAlmostEqual(ev["tightness"], 9.0909090909, places=8)

    def test_tightness_is_the_span_over_the_base_high(self):
        """Normalised by the HIGH, not the low and not the midpoint.

        A 20-wide base under a 110 high is 18.18%; over the low it would be
        22.2% and over the midpoint 20.0%. All three are plausible and only one
        matches the spec, so the discriminating fixture is pinned rather than
        an inequality.

        The span comes from ctx["rows"], not o["range"]: the declared range here
        says lo = 100, which would give 9.09%, while the bars behind it bottom
        at 90. The two are made to disagree on purpose -- o["range"] is the
        engine's own window, and it ends on the breakout bar.
        """
        ev = setups.match_breakout(result(range={"hi": 110.0, "lo": 100.0,
                                                 "bars": 20}),
                                   ctx_for(base_rows(120, hi=110.0, lo=90.0)))
        self.assertAlmostEqual(ev["tightness"], 18.1818181818, places=8)

    def test_no_bars_means_no_call(self):
        """BREAKOUT reads ctx["rows"] for the one thing compute() cannot give it:
        the base high with the candidate bar taken off the end. With no bars
        there is nothing to clear, and "cannot judge" must render as no match --
        never as a pass. An empty ctx used to MATCH, back when the predicate
        read only o["range"]."""
        self.assertIsNone(setups.match_breakout(result(), {}))
        self.assertIsNone(setups.match_breakout(result(), {"rows": []}))
        self.assertIsNone(setups.match_breakout(result(), {"rows": [
            {"h": 100.0, "l": 90.0, "c": 95.0}]}))


class TestBaseHighExcludesTheCandidateBar(unittest.TestCase):
    """D1: the base a breakout clears must exclude the bar that breaks it out.

    analyze.consolidation() always ends its window on the last closed bar, so
    o["range"]["hi"] >= that bar's high >= its close = o["price"]. Gating on
    `price > rng["hi"]` was therefore unsatisfiable for every name on every day
    -- measured 0 of 500 live, closest miss -0.22% -- and every BREAKOUT
    threshold below it was dead code. The fixtures here are the live shape: the
    candidate bar printed the range high, and rng["hi"] is that bar's own high.
    """

    def rows(self, **over):
        return base_rows(120, hi=110.0, lo=100.0, last_high=118.0, **over)

    def live_range(self, bars=20):
        """What consolidation() reports on a breakout day: hi is the candidate
        bar's own high, 118, not the 110 the base had before it."""
        return {"hi": 118.0, "lo": 100.0, "bars": bars}

    def test_the_fixture_really_is_the_unsatisfiable_live_shape(self):
        """Guards the fixture itself: if the candidate bar stopped printing the
        range high, the two tests below would stop testing the defect."""
        rows = self.rows()
        self.assertEqual(rows[-1]["h"], self.live_range()["hi"])
        self.assertEqual(max(r["h"] for r in rows[-20:]), self.live_range()["hi"])
        self.assertGreaterEqual(rows[-1]["h"], rows[-1]["c"])

    def test_a_close_under_the_prior_base_high_is_not_a_breakout(self):
        """The candidate bar poked to 118 intraday but closed at 108, under the
        110 the base had been capped at. That is a failed probe, not a breakout,
        and excluding the candidate bar must not turn it into one."""
        self.assertIsNone(setups.match_breakout(
            result(price=108.0, range=self.live_range()), ctx_for(self.rows())))

    def test_a_close_above_the_prior_base_high_matches(self):
        """The killer case. 112 clears the 110 the base had before today, and is
        below the 118 rng["hi"] that includes today -- so the old
        `px <= rng["hi"]` gate rejected it, as it rejected every name in the
        Nifty 500. pct_above_base is measured off the same 110."""
        ev = setups.match_breakout(result(price=112.0, range=self.live_range()),
                                   ctx_for(self.rows()))
        self.assertIsNotNone(ev)
        self.assertAlmostEqual(ev["pct_above_base"], 1.8181818181, places=8)

    def test_the_first_bar_of_the_base_is_part_of_the_base(self):
        """Both slice ends are pinned. Lifting the high of the base's FIRST bar
        (rows[-bars]) to 115 must raise the bar a breakout has to clear: 112 no
        longer qualifies and 116 does. An implementation that started the slice
        one bar late would keep matching at 112."""
        rows = self.rows()
        rows[-20]["h"] = 115.0
        ctx = ctx_for(rows)
        self.assertIsNone(setups.match_breakout(
            result(price=112.0, range=self.live_range()), ctx))
        self.assertIsNotNone(setups.match_breakout(
            result(price=116.0, range=self.live_range()), ctx))

    def test_the_bar_before_the_base_is_not_part_of_the_base(self):
        """The other end. rows[-(bars+1)] is OUTSIDE the window rng describes --
        and when consolidation() anchors to a volume thrust it is that thrust
        bar, excluded on purpose. A 130 high there must not raise the base high,
        so 112 still matches. Shifting the window back a bar to keep its length
        at `bars` would reject it."""
        rows = self.rows()
        rows[-21]["h"] = 130.0
        self.assertIsNotNone(setups.match_breakout(
            result(price=112.0, range=self.live_range()), ctx_for(rows)))


class TestTightnessExcludesTheBreakoutBar(unittest.TestCase):
    """fit_breakout penalised the strongest breakouts for being strong.

    `tightness` came off o["range"], whose window ends ON the breakout bar. A
    powerful breakout prints a tall bar, the engine's range high rises to that
    bar's high, the span balloons, and fit_breakout's `tightness > 8.0` test
    docks 20% off base quality -- so the harder a name broke out, the more
    likely it was to be marked as having broken out of a sloppy base. The term
    is supposed to say the opposite.
    """

    #: A tight 105-110 base, twenty bars, with the candidate bar the only thing
    #: that differs between the two cases below.
    def rows(self, last_high):
        return base_rows(120, hi=110.0, lo=105.0, last_high=last_high)

    def live_range(self, hi):
        """consolidation() on the breakout day: hi is the candidate bar's own
        high, whatever the base was before it."""
        return {"hi": hi, "lo": 105.0, "bars": 20}

    def case(self, price, last_high):
        return setups.match_breakout(result(price=price,
                                            range=self.live_range(last_high)),
                                     ctx_for(self.rows(last_high)))

    def test_the_breakout_bar_does_not_change_the_base_it_broke_out_of(self):
        """The killer case. Same base, same twenty bars; one name closed just
        over the high and the other gapped 18% past it. Their bases are
        identical, so their tightness must be too -- under the old code the
        strong one measured 19.2% against the weak one's 5.4%."""
        weak = self.case(110.5, 111.0)
        strong = self.case(115.0, 130.0)
        self.assertAlmostEqual(weak["tightness"], strong["tightness"], places=9)
        self.assertAlmostEqual(strong["tightness"], 5.0 / 110.0 * 100, places=8)

    def test_the_strong_breakout_is_no_longer_docked_for_base_quality(self):
        """The consequence, at the level the report prints. 4.55% is inside the
        8.0 penalty threshold; the old 19.2% was not, and cost 0.48 of fit."""
        strong = self.case(115.0, 130.0)
        self.assertLess(strong["tightness"], 8.0)
        self.assertAlmostEqual(setups.fit_breakout(strong), 8.4, places=6)
        self.assertAlmostEqual(
            setups.fit_breakout(dict(strong, tightness=19.23)), 7.92, places=6)

    def test_a_genuinely_wide_base_is_still_penalised(self):
        """The other arm: the fix must not disable the penalty, only stop the
        breakout bar from triggering it. A 90-110 base is 18.2% wide before the
        candidate bar ever prints."""
        ev = setups.match_breakout(
            result(price=115.0, range=self.live_range(130.0)),
            ctx_for(base_rows(120, hi=110.0, lo=90.0, last_high=130.0)))
        self.assertGreater(ev["tightness"], 8.0)
        self.assertLess(setups.fit_breakout(ev), 8.4)

    def test_the_low_comes_from_the_same_slice_as_the_high(self):
        """Both ends of the base are read off rows[-bars:-1], and the low needs
        its own case: the base bars all bottom at 105, so including the
        candidate bar can only matter when that bar prints BELOW them.

        This is the undercut-and-rally shape -- a shakeout to 95 that closed at
        115, right through the base high. The base it broke out of was still
        105-110 wide; an implementation reading rows[-bars:] would call it
        105-95, land at 13.6% and dock the row for a wide base that its own
        breakout bar created.
        """
        rows = base_rows(120, hi=110.0, lo=105.0, last_high=130.0)
        rows[-1]["l"] = 95.0
        ev = setups.match_breakout(result(price=115.0,
                                          range=self.live_range(130.0)),
                                   ctx_for(rows))
        self.assertAlmostEqual(ev["tightness"], 5.0 / 110.0 * 100, places=8)
        self.assertLess(ev["tightness"], 8.0)


class TestBaseRangeHelper(unittest.TestCase):
    """The two-ended slice on its own, where the boundaries are countable.

    TestBaseHighHelper covers the high; the low has its own arithmetic and its
    own off-by-one, and the ROWS there hold every low at 0.0 so a wrong slice
    would be invisible.
    """

    ROWS = [{"h": float(i), "l": float(i) - 0.5, "c": float(i)}
            for i in (1, 2, 3, 4, 5)]

    def test_the_window_ends_one_bar_before_the_last(self):
        """bars=3 over 1..5 is rows[-3:-1] -- bars 3 and 4 -- so (4.0, 2.5)."""
        self.assertEqual(setups.base_range_before_last_bar(self.ROWS, 3),
                         (4.0, 2.5))

    def test_the_low_is_the_lowest_of_the_base_not_the_first(self):
        rows = [{"h": 10.0, "l": 9.0, "c": 9.5},
                {"h": 10.0, "l": 7.0, "c": 9.5},
                {"h": 10.0, "l": 8.0, "c": 9.5},
                {"h": 20.0, "l": 1.0, "c": 19.0}]
        self.assertEqual(setups.base_range_before_last_bar(rows, 4), (10.0, 7.0))

    def test_a_base_longer_than_the_history_uses_what_there_is(self):
        self.assertEqual(setups.base_range_before_last_bar(self.ROWS, 99),
                         (4.0, 0.5))

    def test_the_no_measurement_cases_return_none_not_a_pair(self):
        """Unpacking None is a TypeError, so every caller has to check first."""
        for bars, rows in ((1, self.ROWS), (0, self.ROWS), (20, self.ROWS[:1]),
                           (20, [])):
            self.assertIsNone(setups.base_range_before_last_bar(rows, bars),
                              "bars=%s len=%s" % (bars, len(rows)))

    def test_the_high_helper_is_this_helper(self):
        """They must never be taken off different slices. Probed rather than
        asserted by inspection: the high helper's answer has to equal this
        one's first element for every shape, including the None cases."""
        for bars in (0, 1, 2, 3, 5, 99):
            for rows in (self.ROWS, self.ROWS[:1], []):
                pair = setups.base_range_before_last_bar(rows, bars)
                self.assertEqual(setups.base_high_before_last_bar(rows, bars),
                                 None if pair is None else pair[0],
                                 "bars=%s len=%s" % (bars, len(rows)))


class TestBaseHighHelper(unittest.TestCase):
    """The slice arithmetic on its own, where the boundaries are countable."""

    ROWS = [{"h": float(i), "l": 0.0, "c": float(i)} for i in (1, 2, 3, 4, 5)]

    def test_the_window_ends_one_bar_before_the_last(self):
        """bars=3 over highs 1..5 is rows[-3:-1] -- highs 3 and 4 -- so 4, not
        the 5 that includes the candidate bar and not the 3 of rows[-3:-2]."""
        self.assertEqual(setups.base_high_before_last_bar(self.ROWS, 3), 4.0)

    def test_a_two_bar_base_measures_exactly_one_prior_bar(self):
        self.assertEqual(setups.base_high_before_last_bar(self.ROWS, 2), 4.0)

    def test_a_base_longer_than_the_history_uses_what_there_is(self):
        self.assertEqual(setups.base_high_before_last_bar(self.ROWS, 99), 4.0)

    def test_a_one_bar_base_has_nothing_to_measure(self):
        self.assertIsNone(setups.base_high_before_last_bar(self.ROWS, 1))

    def test_a_zero_bar_base_does_not_silently_measure_everything(self):
        """rows[-0:-1] is the WHOLE series minus the last bar, so the guard has
        to be `bars < 2`, not a falsy check on the slice."""
        self.assertIsNone(setups.base_high_before_last_bar(self.ROWS, 0))

    def test_a_single_bar_of_history_has_no_prior_bar(self):
        self.assertIsNone(setups.base_high_before_last_bar(self.ROWS[:1], 20))
        self.assertIsNone(setups.base_high_before_last_bar([], 20))

    def test_two_bars_of_history_measure_the_first(self):
        self.assertEqual(setups.base_high_before_last_bar(self.ROWS[:2], 20), 1.0)


class TestBreakoutNearMisses(unittest.TestCase):
    def test_price_at_or_below_base_high_rejects(self):
        self.assertIsNone(setups.match_breakout(result(price=110.0), CTX))

    def test_base_too_short_rejects(self):
        self.assertIsNone(setups.match_breakout(
            result(range={"hi": 110.0, "lo": 100.0, "bars": 11}), CTX))

    def test_volume_below_1_5x_rejects(self):
        self.assertIsNone(setups.match_breakout(
            result(last_closed_bar=vol(1_400_000)), CTX))

    def test_more_than_12_percent_extended_rejects(self):
        """The extension cap is what makes this a BREAKOUT screen rather than a
        HAS-BROKEN-OUT screen -- without it every name that ran 30% qualifies."""
        self.assertIsNone(setups.match_breakout(result(price=125.0), CTX))

    def test_below_sma200_rejects(self):
        self.assertIsNone(setups.match_breakout(result(ma=ma(sma200=130.0)), CTX))

    def test_missing_sma200_rejects(self):
        """The `not ma["sma200"]` arm -- a listing under 200 sessions old. Every
        other fixture supplies a float, so the falsy half was uncovered."""
        self.assertIsNone(setups.match_breakout(result(ma=ma(sma200=None)), CTX))

    def test_missing_sma50_does_not_reject_loosened(self):
        """A young listing with no 50-day average still screens loosened.

        The loosened MA test is `price > sma200` and nothing else, so sma50
        being absent is not grounds for rejection -- it is a data gap, not a
        trend judgement. Reinstating the old second arm makes this fail.
        """
        self.assertIsNotNone(setups.match_breakout(result(ma=ma(sma50=None)), CTX))

    def test_zero_avg20_volume_rejects_without_dividing_by_zero(self):
        """The `if not avg20` guard. A halted or freshly listed name reports a
        zero 20-day average; deleting the guard raises ZeroDivisionError on the
        next line instead of returning None."""
        v = {"avg20": 0, "avg50": 950_000, "dryup_ratio": 1.05, "thrusts": []}
        self.assertIsNone(setups.match_breakout(result(volume=v), CTX))

    def test_missing_avg20_volume_rejects(self):
        v = {"avg20": None, "avg50": 950_000, "dryup_ratio": 1.05, "thrusts": []}
        self.assertIsNone(setups.match_breakout(result(volume=v), CTX))


class TestBreakoutBoundaries(unittest.TestCase):
    """Accept AND reject sides of every loosened threshold, one tick apart."""

    def test_price_must_clear_the_base_high_strictly(self):
        """`<=` not `<`: closing exactly on the old high is not a breakout."""
        self.assertIsNone(setups.match_breakout(result(price=110.0), CTX))
        self.assertIsNotNone(setups.match_breakout(result(price=110.01), CTX))

    def test_base_length_floor_is_twelve_bars(self):
        r = {"hi": 110.0, "lo": 100.0}
        self.assertIsNotNone(setups.match_breakout(
            result(range=dict(r, bars=12)), CTX))
        self.assertIsNone(setups.match_breakout(
            result(range=dict(r, bars=11)), CTX))

    def test_volume_multiple_floor_is_inclusive(self):
        """`<` not `<=`: exactly 1.5x qualifies."""
        self.assertIsNotNone(setups.match_breakout(
            result(last_closed_bar=vol(1_500_000)), CTX))
        self.assertIsNone(setups.match_breakout(
            result(last_closed_bar=vol(1_499_999)), CTX))

    def test_extension_ceiling_is_inclusive_at_twelve_percent(self):
        """`>` not `>=`: exactly 12% above the base still qualifies.

        hi = 100 so the percentage is exact -- see base100(). CTX100 carries the
        bars that agree with it: a 92-100 base under the candidate bar.
        """
        self.assertIsNotNone(setups.match_breakout(
            result(price=112.0, range=base100()), CTX100))
        self.assertIsNone(setups.match_breakout(
            result(price=112.01, range=base100()), CTX100))

    def test_price_must_be_strictly_above_sma200(self):
        """`<=` not `<`: sitting exactly on the 200-day is not above it."""
        self.assertIsNone(setups.match_breakout(result(ma=ma(sma200=112.0)), CTX))
        self.assertIsNotNone(setups.match_breakout(result(ma=ma(sma200=111.99)), CTX))

    def test_volume_light_flag_flips_at_exactly_two_x(self):
        """`<` not `<=`: 2.0x IS stock_analyser's confirmed trigger, so a row at
        exactly 2.0 must NOT be flagged light. Both sides pinned one unit apart
        so neither the constant nor the comparison can move."""
        self.assertFalse(setups.match_breakout(
            result(last_closed_bar=vol(2_000_000)), CTX)["volume_light"])
        self.assertTrue(setups.match_breakout(
            result(last_closed_bar=vol(1_999_999)), CTX)["volume_light"])

    def test_confirmed_multiple_matches_the_analyser_contract(self):
        self.assertEqual(setups.CONFIRMED_VOL_MULT, 2.0)


class TestBreakoutMaStack(unittest.TestCase):
    """The MA-stack condition, both modes.

    Loosened asks for `price > sma200` and nothing more; strict asks for the
    full `price > sma50 > sma200` chain. The earlier second loosened arm --
    `sma50 and (sma50 > sma200 or px > sma50)` -- was deleted as a tautology:
    the sma200 guard above it already established px > sma200, so sma50 <=
    sma200 forces px > sma50 and the disjunction can never be false. All it
    ever rejected was a MISSING sma50, which is a data gap rather than a trend
    judgement, and the brief's test for it (sma50 = 118 > sma200 = 108 with
    px = 112, named "sma50 below sma200 AND price below sma50") named a state
    no assignment can reach: px > sma200 >= sma50 >= px is unsatisfiable.
    """

    def test_loosened_accepts_a_sma50_below_sma200(self):
        """A not-yet-golden-crossed name still screens in loosened mode."""
        self.assertIsNotNone(setups.match_breakout(result(ma=ma(sma50=97.0)), CTX))

    def test_strict_requires_price_above_sma50_above_sma200(self):
        self.assertIsNone(setups.match_breakout(result(ma=ma(sma50=97.0)), CTX,
                                                strict=True))

    def test_price_below_its_fifty_day_matches_loosened_and_not_strict(self):
        """The behaviour the loosening actually buys, pinned from both sides.

        px 112 clears sma200 = 98 but sits UNDER sma50 = 115 -- a breakout out
        of a base that formed below the 50-day, which is common after a long
        correction. Loosened must take it; strict must not. Nothing else in this
        file pins the pair: the assertIsNotNone alone also passes with the old
        tautological arm in place, and the assertIsNone alone also passes if
        loosened were tightened to the full stack, so both directions are
        required to hold the ruling in place.
        """
        o = result(ma=ma(sma50=115.0))
        self.assertGreater(o["ma"]["sma50"], o["price"])
        self.assertGreater(o["price"], o["ma"]["sma200"])
        self.assertIsNotNone(setups.match_breakout(o, CTX, strict=False))
        self.assertIsNone(setups.match_breakout(o, CTX, strict=True))

    def test_strict_rejects_a_missing_sma50(self):
        """The `not ma["sma50"]` arm INSIDE the strict branch. Reaching it needs
        strict mode; the loosened test above exercises a different line."""
        self.assertIsNone(setups.match_breakout(result(ma=ma(sma50=None)), CTX,
                                                strict=True))

    def test_strict_ma_stack_is_inclusive_of_the_chain_boundaries(self):
        """`>` twice, not `>=`: equality anywhere in the chain breaks it."""
        self.assertIsNone(setups.match_breakout(result(ma=ma(sma50=112.0)), CTX,
                                                strict=True))    # px == sma50
        self.assertIsNone(setups.match_breakout(result(ma=ma(sma50=98.0)), CTX,
                                                strict=True))    # sma50 == sma200
        self.assertIsNotNone(setups.match_breakout(result(ma=ma(sma50=98.01)), CTX,
                                                   strict=True))


class TestBreakoutStrict(unittest.TestCase):
    def test_strict_requires_2x_volume(self):
        o = result(last_closed_bar=vol(1_700_000))
        self.assertIsNotNone(setups.match_breakout(o, CTX, strict=False))
        self.assertIsNone(setups.match_breakout(o, CTX, strict=True))

    def test_strict_volume_floor_is_inclusive_at_two_x(self):
        self.assertIsNotNone(setups.match_breakout(
            result(last_closed_bar=vol(2_000_000)), CTX, strict=True))
        self.assertIsNone(setups.match_breakout(
            result(last_closed_bar=vol(1_999_999)), CTX, strict=True))

    def test_strict_caps_extension_at_8_percent(self):
        o = result(price=120.0)   # 9.1% above base high
        self.assertIsNotNone(setups.match_breakout(o, CTX, strict=False))
        self.assertIsNone(setups.match_breakout(o, CTX, strict=True))

    def test_strict_extension_ceiling_is_inclusive_at_eight_percent(self):
        self.assertIsNotNone(setups.match_breakout(
            result(price=108.0, range=base100()), CTX100, strict=True))
        self.assertIsNone(setups.match_breakout(
            result(price=108.01, range=base100()), CTX100, strict=True))

    def test_strict_requires_fifteen_bars_of_base(self):
        r = {"hi": 110.0, "lo": 100.0}
        self.assertIsNotNone(setups.match_breakout(
            result(range=dict(r, bars=14)), CTX, strict=False))
        self.assertIsNone(setups.match_breakout(
            result(range=dict(r, bars=14)), CTX, strict=True))
        self.assertIsNotNone(setups.match_breakout(
            result(range=dict(r, bars=15)), CTX, strict=True))

    def test_strict_defaults_to_false_when_omitted(self):
        """Every other call in this file either passes strict explicitly or uses
        a fixture both modes agree on, which leaves the DEFAULT unverified. This
        input is accepted loosened and rejected strict, so omitting the argument
        can only match one of them."""
        o = result(last_closed_bar=vol(1_700_000))
        self.assertIsNotNone(setups.match_breakout(o, CTX))


class TestBreakoutFunnel(unittest.TestCase):
    """Every rejecting condition records itself, and none of them changes the
    verdict. A predicate that skips a `_reject` still returns None, so the
    screen looks right while the funnel under-reports and every later stage's
    "reached" count is silently inflated."""

    #: one input per rejecting condition in match_breakout, in predicate order
    CASES = [
        ("base length", dict(range={"hi": 110.0, "lo": 100.0, "bars": 11}),
         CTX, False),
        ("no bars at all", {}, {}, False),
        ("price under the base high", dict(price=109.0), CTX, False),
        ("no 20-day volume",
         dict(volume={"avg20": 0, "avg50": 1, "dryup_ratio": 1.0,
                      "thrusts": []}), CTX, False),
        ("volume too light", dict(last_closed_bar=vol(1_400_000)), CTX, False),
        ("too extended", dict(price=125.0), CTX, False),
        ("below the 200-day", dict(ma=ma(sma200=130.0)), CTX, False),
        ("strict stack", dict(ma=ma(sma50=97.0)), CTX, True),
    ]

    def test_each_condition_records_itself_exactly_once(self):
        seen = {}
        for name, over, ctx, strict in self.CASES:
            diag = {}
            self.assertIsNone(setups.match_breakout(result(**over), ctx,
                                                    strict=strict, diag=diag),
                              name)
            self.assertEqual(len(diag), 1, "%s recorded %s" % (name, diag))
            (label, (step, count)), = diag.items()
            self.assertEqual(count, 1, name)
            self.assertTrue(label.strip(), name)
            seen[name] = (step, label)
        self.assertEqual(len(seen), len(self.CASES))

    def test_the_conditions_are_distinct_and_ordered_as_tested(self):
        """Two conditions sharing a label would merge into one funnel row, and
        steps out of order would print the funnel out of sequence."""
        steps = []
        for name, over, ctx, strict in self.CASES:
            diag = {}
            setups.match_breakout(result(**over), ctx, strict=strict, diag=diag)
            (label, (step, _)), = diag.items()
            steps.append((step, label))
        self.assertEqual(len(set(l for _, l in steps)), len(self.CASES),
                         "two conditions share a label")
        self.assertEqual(steps, sorted(steps), "steps are out of predicate order")

    def test_the_base_high_condition_names_the_bar_it_excludes(self):
        """The condition D1 turned on. It has to be legible in the report, or
        an unsatisfiable gate reads as a market finding again."""
        diag = {}
        setups.match_breakout(result(price=109.0), CTX, diag=diag)
        (label, _), = diag.items()
        self.assertIn("base high", label)
        self.assertIn("breakout bar excluded", label)

    def test_a_match_records_nothing(self):
        diag = {}
        self.assertIsNotNone(setups.match_breakout(result(), CTX, diag=diag))
        self.assertEqual(diag, {})

    def test_the_verdict_is_identical_with_and_without_the_funnel(self):
        for name, over, ctx, strict in self.CASES + [("match", {}, CTX, False)]:
            o = result(**over)
            plain = setups.match_breakout(o, ctx, strict=strict)
            traced = setups.match_breakout(o, ctx, strict=strict, diag={})
            self.assertEqual(plain, traced, name)


class TestBreakoutFit(unittest.TestCase):
    def ev(self, **over):
        e = {"vol_mult": 2.5, "pct_above_base": 1.0, "base_bars": 20,
             "tightness": 5.0, "volume_light": False}
        e.update(over)
        return e

    def test_fresher_breakout_scores_higher_than_extended_one(self):
        fresh = setups.fit_breakout(setups.match_breakout(result(price=110.5), CTX))
        ext = setups.fit_breakout(setups.match_breakout(result(price=122.0), CTX))
        self.assertTrue(0.0 <= ext < fresh <= 10.0)

    def test_bigger_volume_scores_higher(self):
        big = setups.fit_breakout(setups.match_breakout(
            result(last_closed_bar=vol(3_500_000)), CTX))
        small = setups.fit_breakout(setups.match_breakout(
            result(last_closed_bar=vol(1_600_000)), CTX))
        self.assertGreater(big, small)

    def test_longer_base_scores_higher(self):
        """The base-quality term carries weight of its own; the two ordering
        tests above hold base_bars constant, so a fit ignoring it survived."""
        long_ = setups.fit_breakout(self.ev(base_bars=30))
        short = setups.fit_breakout(self.ev(base_bars=12))
        self.assertGreater(long_, short)

    def test_weights_are_forty_thirty_thirty(self):
        """Pins the absolute score. vol 2.5 -> 9, freshness 1.0 -> 10,
        base 20 bars -> 8, tightness 5.0 -> no penalty.
        0.4*9 + 0.3*10 + 0.3*8 = 9.0. Equal thirds would give 9.0 as well,
        so the second case breaks the tie: vol 1.5 -> 4 gives
        0.4*4 + 0.3*10 + 0.3*8 = 7.0, where equal thirds gives 7.33.
        """
        self.assertAlmostEqual(setups.fit_breakout(self.ev()), 9.0, places=6)
        self.assertAlmostEqual(setups.fit_breakout(self.ev(vol_mult=1.5)), 7.0,
                               places=6)

    def test_wide_base_is_penalised_twenty_percent(self):
        """Both arms of the `tightness > 8.0` penalty, at the boundary.

        A 20-bar base bands to 8; the penalty takes it to 6.4, moving the total
        by 0.3 * 1.6 = 0.48. Without a case on each side the branch is half
        dead whichever way the comparison is written.
        """
        self.assertAlmostEqual(setups.fit_breakout(self.ev(tightness=8.0)), 9.0,
                               places=6)
        self.assertAlmostEqual(setups.fit_breakout(self.ev(tightness=8.01)), 8.52,
                               places=6)

    def test_penalty_scales_the_base_term_only(self):
        """Not a flat subtraction: a 30-bar base (10) loses 2.0 of sub-score
        while a 12-bar base (4) loses only 0.8, which a constant penalty cannot
        reproduce."""
        self.assertAlmostEqual(
            setups.fit_breakout(self.ev(base_bars=30, tightness=9.0)),
            setups.fit_breakout(self.ev(base_bars=30, tightness=5.0)) - 0.3 * 2.0,
            places=6)
        self.assertAlmostEqual(
            setups.fit_breakout(self.ev(base_bars=12, tightness=9.0)),
            setups.fit_breakout(self.ev(base_bars=12, tightness=5.0)) - 0.3 * 0.8,
            places=6)

    def test_every_volume_cut_is_reachable(self):
        """One fixture per band AT the cut and one just BELOW it.

        The at-cut case alone pins each cut from one side only: nudging a cut
        DOWN (2.5 -> 2.4) leaves 2.5 in the same band and survives. The paired
        just-below case forces the next band down, so a cut cannot move in
        either direction. Sub-score is recovered by inverting the fixed
        0.3*10 + 0.3*8 = 5.4 remainder.
        """
        cuts = [(3.0, 10), (2.5, 9), (2.0, 8), (1.75, 6), (1.5, 4)]
        for i, (mult, sub) in enumerate(cuts):
            self.assertAlmostEqual(setups.fit_breakout(self.ev(vol_mult=mult)),
                                   round(0.4 * sub + 5.4, 2), places=6,
                                   msg="at cut %s" % mult)
            below = cuts[i + 1][1] if i + 1 < len(cuts) else 0.0
            self.assertAlmostEqual(setups.fit_breakout(self.ev(vol_mult=mult - 0.001)),
                                   round(0.4 * below + 5.4, 2), places=6,
                                   msg="just below cut %s" % mult)

    def test_every_freshness_cut_is_reachable(self):
        """band_desc, so the paired case sits just ABOVE each cut."""
        cuts = [(2.0, 10), (5.0, 8), (8.0, 6), (12.0, 4)]
        for i, (pct, sub) in enumerate(cuts):
            self.assertAlmostEqual(setups.fit_breakout(self.ev(pct_above_base=pct)),
                                   round(3.6 + 0.3 * sub + 2.4, 2), places=6,
                                   msg="at cut %s" % pct)
            above = cuts[i + 1][1] if i + 1 < len(cuts) else 0.0
            self.assertAlmostEqual(
                setups.fit_breakout(self.ev(pct_above_base=pct + 0.001)),
                round(3.6 + 0.3 * above + 2.4, 2), places=6,
                msg="just above cut %s" % pct)

    def test_every_base_length_cut_is_reachable(self):
        cuts = [(30, 10), (20, 8), (15, 6), (12, 4)]
        for i, (bars, sub) in enumerate(cuts):
            self.assertAlmostEqual(setups.fit_breakout(self.ev(base_bars=bars)),
                                   round(3.6 + 3.0 + 0.3 * sub, 2), places=6,
                                   msg="at cut %s" % bars)
            below = cuts[i + 1][1] if i + 1 < len(cuts) else 0.0
            self.assertAlmostEqual(setups.fit_breakout(self.ev(base_bars=bars - 1)),
                                   round(3.6 + 3.0 + 0.3 * below, 2), places=6,
                                   msg="just below cut %s" % bars)

    def test_fit_stays_inside_zero_to_ten(self):
        best = self.ev(vol_mult=9.0, pct_above_base=0.0, base_bars=200,
                       tightness=1.0)
        worst = self.ev(vol_mult=1.5, pct_above_base=12.0, base_bars=12,
                        tightness=40.0)
        self.assertAlmostEqual(setups.fit_breakout(best), 10.0, places=6)
        self.assertTrue(0.0 <= setups.fit_breakout(worst) <= 10.0)


class TestBreakoutThresholdTable(unittest.TestCase):
    def test_registry_carries_the_spec_numbers(self):
        self.assertEqual(setups.THRESHOLDS["BREAKOUT"],
                         {"min_bars": (12, 15), "vol_mult": (1.5, 2.0),
                          "max_extension_pct": (12.0, 8.0),
                          "strict_ma_stack": (False, True)})

    def test_strict_is_never_looser_than_loosened(self):
        """The nesting property, checked on the numeric keys of this setup.

        min_bars and vol_mult are floors (strict >= loosened);
        max_extension_pct is a ceiling (strict <= loosened). Getting a pair
        backwards would let a name match strict but not loosened, which the
        CONFLUENCE logic in Task 9 assumes cannot happen.
        """
        th = setups.THRESHOLDS["BREAKOUT"]
        for key in ("min_bars", "vol_mult"):
            self.assertGreaterEqual(th[key][1], th[key][0], key)
        self.assertLessEqual(th["max_extension_pct"][1],
                             th["max_extension_pct"][0])

    def test_anything_matching_strict_also_matches_loosened(self):
        """The nesting property end to end, over a grid rather than the table.

        A threshold pair can be ordered correctly and still be applied with the
        wrong comparison; this walks real inputs through both modes and asserts
        strict implies loosened for every one.
        """
        checked = 0
        for price in (100.5, 104.0, 108.0, 112.0, 120.0, 130.0):
            for v in (1_400_000, 1_500_000, 2_000_000, 3_000_000):
                for bars in (11, 12, 14, 15, 30):
                    for sma50 in (None, 97.0, 104.0, 115.0):
                        o = result(price=price, last_closed_bar=vol(v),
                                   ma=ma(sma50=sma50),
                                   range={"hi": 100.0, "lo": 92.0, "bars": bars})
                        if setups.match_breakout(o, CTX100, strict=True) is not None:
                            checked += 1
                            self.assertIsNotNone(
                                setups.match_breakout(o, CTX100, strict=False),
                                "strict matched but loosened did not: "
                                "px=%s v=%s bars=%s sma50=%s"
                                % (price, v, bars, sma50))
        self.assertGreater(checked, 0, "grid produced no strict matches at all")


if __name__ == "__main__":
    unittest.main()
