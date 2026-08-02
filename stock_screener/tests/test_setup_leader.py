import os, sys, unittest
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
sys.path.insert(0, _root)
sys.path.insert(0, _here)
import setups
from fixtures import trend_series

ROWS = trend_series(120)


def result(**over):
    o = {"symbol": "TEST", "price": 108.0,
         "last_closed_bar": {"t": "2026-07-31", "v": 1_200_000},
         "ma": {"sma20": 105.0, "sma50": 100.0, "sma100": 95.0, "sma200": 90.0},
         "atr": {"daily": 2.0, "daily_pct": 1.9},
         "volume": {"avg20": 1_000_000, "avg50": 950_000, "dryup_ratio": 1.05,
                    "thrusts": []},
         "range": {"hi": 109.0, "lo": 99.0, "bars": 18},
         "hi52": 112.0, "lo52": 70.0,
         "rsi": {"daily": 68.0}, "macd": {"daily": {"hist": 0.5}},
         "returns": {"1m": 6.0, "3m": 18.0},
         "entry_gate": {"rr_at_current_price": 1.9},
         "score": {"total": 7.2},
         "_rows": ROWS}
    o.update(over)
    return o


def ctx(rs_1m=3.0, rs_3m=12.0, **over):
    c = {"rows": ROWS, "rs": {"1m": rs_1m, "3m": rs_3m},
         "atr_pctile": 0.5, "sma200_rising": True, "sma50_rising": True,
         "run_pct": 2.0}
    c.update(over)
    return c


def ma(sma20=105.0, sma50=100.0, sma200=90.0):
    return {"sma20": sma20, "sma50": sma50, "sma100": 95.0, "sma200": sma200}


def thrusts(*specs):
    """specs are (row_index, direction) pairs against ROWS."""
    return {"avg20": 1_000_000, "avg50": 950_000, "dryup_ratio": 1.05,
            "thrusts": [{"date": str(ROWS[i]["t"]), "dir": d, "vol": 5_000_000,
                         "x_avg": 3.1} for i, d in specs]}


# A 52-week high of 120 makes every distance-from-high threshold land on an
# exact float: px 108 is 10.00% below it and px 114 is 5.00% below it. The
# brief's 112 puts the loosened boundary at 100.8, which is UNDER sma20 = 105
# and so rejects for an unrelated reason -- the same collision that makes the
# brief's own strict test (price 104) fail. A low sma20 keeps the MA stack out
# of the way while the distance guard is measured.
EXACT = {"hi52": 120.0, "ma": ma(sma20=100.0, sma50=98.0, sma200=90.0)}


class TestLeaderMatches(unittest.TestCase):
    def test_textbook_leader_matches(self):
        ev = setups.match_leader(result(), ctx())
        self.assertIsNotNone(ev)
        self.assertTrue(ev["full_stack"])
        self.assertAlmostEqual(ev["pct_from_high"], 100 * (112 - 108) / 112, places=6)

    def test_shallow_recent_breather_still_qualifies(self):
        """RS 1m of -2pp is the loosened floor: a genuine leader taking a rest
        should not be dropped from the screen."""
        self.assertIsNotNone(setups.match_leader(result(), ctx(rs_1m=-1.5)))

    def test_evidence_reports_every_documented_key(self):
        ev = setups.match_leader(result(), ctx(rs_1m=3.0, rs_3m=12.0))
        self.assertEqual(set(ev), {"pct_from_high", "rs_1m", "rs_3m", "full_stack"})
        self.assertAlmostEqual(ev["rs_1m"], 3.0, places=6)
        self.assertAlmostEqual(ev["rs_3m"], 12.0, places=6)

    def test_relative_strength_comes_from_ctx_not_from_raw_returns(self):
        """o["returns"] holds ABSOLUTE returns (6.0 / 18.0); ctx["rs"] holds the
        same windows measured AGAINST the index (3.0 / 12.0). Reading the wrong
        one would still produce plausible positive numbers, so the two are given
        different values and the evidence is pinned to the ctx pair."""
        ev = setups.match_leader(result(), ctx(rs_1m=3.0, rs_3m=12.0))
        self.assertNotAlmostEqual(ev["rs_1m"], 6.0)
        self.assertNotAlmostEqual(ev["rs_3m"], 18.0)


class TestLeaderNearMisses(unittest.TestCase):
    def test_more_than_10_percent_below_high_rejects(self):
        self.assertIsNone(setups.match_leader(result(price=99.0), ctx()))

    def test_negative_3m_relative_strength_rejects(self):
        self.assertIsNone(setups.match_leader(result(), ctx(rs_3m=-1.0)))

    def test_1m_relative_strength_below_floor_rejects(self):
        self.assertIsNone(setups.match_leader(result(), ctx(rs_1m=-5.0)))

    def test_missing_relative_strength_rejects(self):
        self.assertIsNone(setups.match_leader(result(), ctx(rs_3m=None)))

    def test_missing_one_month_relative_strength_rejects(self):
        """The other half of the None guard. The brief blanks only the 3m
        window, so `rs.get("1m") is None` was never the reason for a rejection
        and could be deleted."""
        self.assertIsNone(setups.match_leader(result(), ctx(rs_1m=None)))

    def test_absent_relative_strength_keys_reject(self):
        """`.get`, not `[...]`: a baseline fetch that failed outright may omit
        the keys rather than set them to None, and that must reject rather than
        raise KeyError."""
        self.assertIsNone(setups.match_leader(result(), ctx(rs={})))
        self.assertIsNone(setups.match_leader(result(), ctx(rs={"3m": 12.0})))
        self.assertIsNone(setups.match_leader(result(), ctx(rs={"1m": 3.0})))

    def test_rsi_below_50_rejects(self):
        self.assertIsNone(setups.match_leader(result(rsi={"daily": 44.0}), ctx()))

    def test_parabolic_rsi_above_88_rejects(self):
        self.assertIsNone(setups.match_leader(result(rsi={"daily": 91.0}), ctx()))

    def test_missing_rsi_rejects(self):
        """The `r is None` arm. `None <= 88.0` raises on Python 3, so deleting
        this half of the guard is a crash rather than a wrong verdict."""
        self.assertIsNone(setups.match_leader(result(rsi={"daily": None}), ctx()))

    def test_broken_ma_stack_rejects(self):
        o = result(ma=ma(sma20=105.0, sma50=95.0, sma200=99.0))
        self.assertIsNone(setups.match_leader(o, ctx()))

    def test_recent_down_thrust_rejects(self):
        self.assertIsNone(setups.match_leader(result(volume=thrusts((-3, "down"))),
                                              ctx()))

    def test_recent_up_thrust_does_not_reject(self):
        """The sibling arm: accumulation on 3x volume is the opposite signal and
        must not disqualify a leader. Without this the thrust guard could be
        reading the date and ignoring the direction."""
        self.assertIsNotNone(setups.match_leader(result(volume=thrusts((-3, "up"))),
                                                 ctx()))

    def test_missing_hi52_rejects_without_dividing_by_zero(self):
        """The `if o["hi52"] else 100.0` arm. A name with no 52-week high has no
        measurable distance from one, so the fallback of 100% guarantees a
        rejection; deleting the guard raises instead."""
        self.assertIsNone(setups.match_leader(result(hi52=0.0), ctx()))
        self.assertIsNone(setups.match_leader(result(hi52=None), ctx()))


class TestLeaderMissingAverages(unittest.TestCase):
    """`not (sma20 and sma50 and sma200)` -- one case per conjunct, because a
    single None fixture leaves the other two operands unverified."""

    def test_missing_sma20_rejects(self):
        self.assertIsNone(setups.match_leader(result(ma=ma(sma20=None)), ctx()))

    def test_missing_sma50_rejects(self):
        self.assertIsNone(setups.match_leader(result(ma=ma(sma50=None)), ctx()))

    def test_missing_sma200_rejects(self):
        self.assertIsNone(setups.match_leader(result(ma=ma(sma200=None)), ctx()))


class TestLeaderBoundaries(unittest.TestCase):
    """Accept AND reject sides of each loosened threshold, one tick apart."""

    def test_three_month_relative_strength_must_be_strictly_positive(self):
        """`<= 0`: matching the index is not leading it."""
        self.assertIsNone(setups.match_leader(result(), ctx(rs_3m=0.0)))
        self.assertIsNotNone(setups.match_leader(result(), ctx(rs_3m=0.01)))

    def test_one_month_floor_is_inclusive_at_minus_two(self):
        self.assertIsNotNone(setups.match_leader(result(), ctx(rs_1m=-2.0)))
        self.assertIsNone(setups.match_leader(result(), ctx(rs_1m=-2.01)))

    def test_distance_from_high_ceiling_is_inclusive_at_ten_percent(self):
        self.assertIsNotNone(setups.match_leader(result(price=108.0, **EXACT), ctx()))
        self.assertIsNone(setups.match_leader(result(price=107.99, **EXACT), ctx()))

    def test_rsi_window_is_inclusive_at_both_ends(self):
        for rsi_val in (50.0, 88.0):
            self.assertIsNotNone(setups.match_leader(
                result(rsi={"daily": rsi_val}), ctx()), "rsi %s" % rsi_val)
        for rsi_val in (49.99, 88.01):
            self.assertIsNone(setups.match_leader(
                result(rsi={"daily": rsi_val}), ctx()), "rsi %s" % rsi_val)

    def test_down_thrust_window_is_ten_bars(self):
        """Pinned from both sides so the hardcoded 10 cannot drift."""
        self.assertIsNone(setups.match_leader(result(volume=thrusts((-10, "down"))),
                                              ctx()))
        self.assertIsNotNone(setups.match_leader(result(volume=thrusts((-11, "down"))),
                                                 ctx()))


class TestLeaderExtensionGuard(unittest.TestCase):
    """Leadership is not the question the extension guard asks; the ENTRY is.

    LAURUSLABS scored Fit 10.00 / BUY NOW at RSI 81.8 with ATR at the 98th
    percentile of its own six months and +13.4% in six sessions, on a stock
    moving ~3% a day against a 1.5x ATR stop 3.7% below. Its relative strength
    was genuine -- RS 3m +54.4, market cap past Dr Reddy's -- so no
    strength-based threshold could have caught it. rsi_hi stays at 88/85: RSI
    and extension are different measurements and one cannot stand in for the
    other.
    """

    #: The row the review objected to, as the predicate sees it. Everything
    #: except the two extension inputs makes it a textbook leader.
    LAURUS_O = {"rsi": {"daily": 81.8}}
    LAURUS_CTX = {"atr_pctile": 0.976, "run_pct": 13.43}

    def test_the_laurus_row_no_longer_matches(self):
        self.assertIsNone(setups.match_leader(result(**self.LAURUS_O),
                                              ctx(**self.LAURUS_CTX)))

    def test_the_same_row_at_a_calm_moment_still_matches(self):
        """The other side, and the point of the whole guard: the name is a
        leader, it is the moment that is wrong. Only the two extension inputs
        move -- an RSI of 81.8 still passes the 88 ceiling."""
        ev = setups.match_leader(result(**self.LAURUS_O),
                                 ctx(atr_pctile=0.50, run_pct=2.0))
        self.assertIsNotNone(ev)
        self.assertAlmostEqual(ev["rs_3m"], 12.0, places=6)

    def test_the_rsi_ceiling_does_not_catch_it(self):
        """Proves the guard is not redundant with rsi_hi: 81.8 is inside the
        loosened window at both ends, so the RSI gate passes this row."""
        lo, hi = (setups.THRESHOLDS["LEADER"]["rsi_lo"][0],
                  setups.THRESHOLDS["LEADER"]["rsi_hi"][0])
        self.assertTrue(lo <= 81.8 <= hi)

    def test_atr_in_the_top_decile_rejects_on_its_own(self):
        """One arm at a time: the run is calm here, so only the ATR percentile
        can be doing the rejecting."""
        self.assertIsNone(setups.match_leader(result(),
                                              ctx(atr_pctile=0.91, run_pct=2.0)))

    def test_a_five_session_run_over_ten_percent_rejects_on_its_own(self):
        """The other arm, with the ATR percentile held mid-range. This is the
        name that gapped away from its base before its ATR caught up."""
        self.assertIsNone(setups.match_leader(result(),
                                              ctx(atr_pctile=0.50, run_pct=10.01)))

    def test_the_atr_ceiling_is_inclusive_at_the_ninetieth_percentile(self):
        """`>`, not `>=`: the top DECILE is above 0.90, and a name sitting
        exactly on it is not in it."""
        self.assertIsNotNone(setups.match_leader(result(), ctx(atr_pctile=0.90)))
        self.assertIsNone(setups.match_leader(result(), ctx(atr_pctile=0.9001)))

    def test_the_run_ceiling_is_inclusive_at_ten_percent(self):
        self.assertIsNotNone(setups.match_leader(result(), ctx(run_pct=10.0)))
        self.assertIsNone(setups.match_leader(result(), ctx(run_pct=10.01)))

    def test_a_fall_over_the_same_window_is_not_an_extension(self):
        """A one-sided ceiling, not abs(): a leader that gave back 10% in five
        sessions has not run away from its base. Without this the guard could be
        reading a magnitude and rejecting the pullbacks it should keep."""
        self.assertIsNotNone(setups.match_leader(result(), ctx(run_pct=-13.43)))

    def test_an_unmeasurable_run_abstains_rather_than_rejecting(self):
        """The `run is not None` arm. A series too short to measure a run is a
        data gap, not a chase -- and `None > 10.0` raises on Python 3, so
        deleting the guard is a crash rather than a wrong verdict."""
        self.assertIsNotNone(setups.match_leader(result(), ctx(run_pct=None)))

    def test_an_absent_run_key_abstains_too(self):
        """`.get`, not `[...]`: every predicate must survive a ctx built by an
        older caller."""
        c = ctx()
        del c["run_pct"]
        self.assertIsNotNone(setups.match_leader(result(), c))

    def test_a_flat_run_is_measured(self):
        """0.0 is falsy. The verdict is the same either way here -- 0.0 fails
        the ceiling comparison it would be skipping -- so this pins the
        behaviour rather than claiming `if run` is killable."""
        self.assertIsNotNone(setups.match_leader(result(), ctx(run_pct=0.0)))

    def test_strict_tightens_the_atr_ceiling(self):
        self.assertIsNotNone(setups.match_leader(result(), ctx(atr_pctile=0.86)))
        self.assertIsNone(setups.match_leader(result(), ctx(atr_pctile=0.86),
                                              strict=True))

    def test_strict_atr_ceiling_is_inclusive_at_the_eighty_fifth_percentile(self):
        self.assertIsNotNone(setups.match_leader(result(), ctx(atr_pctile=0.85),
                                                 strict=True))
        self.assertIsNone(setups.match_leader(result(), ctx(atr_pctile=0.8501),
                                              strict=True))

    def test_strict_tightens_the_run_ceiling(self):
        self.assertIsNotNone(setups.match_leader(result(), ctx(run_pct=9.0)))
        self.assertIsNone(setups.match_leader(result(), ctx(run_pct=9.0),
                                              strict=True))

    def test_strict_run_ceiling_is_inclusive_at_eight_percent(self):
        self.assertIsNotNone(setups.match_leader(result(), ctx(run_pct=8.0),
                                                 strict=True))
        self.assertIsNone(setups.match_leader(result(), ctx(run_pct=8.01),
                                              strict=True))

    def test_strict_defaults_to_false_when_omitted(self):
        """An input the two modes disagree on, called with no strict argument."""
        self.assertIsNotNone(setups.match_leader(result(), ctx(atr_pctile=0.86)))


class TestLeaderFunnel(unittest.TestCase):
    """One row per rejecting condition, distinct, in predicate order.

    Inserting the extension guard renumbered the down-thrust condition, and
    `reached` in the printed funnel is recovered by subtraction -- a duplicate
    step or label silently merges two conditions into one row.
    """

    CASES = [
        ("no relative-strength baseline", {}, ctx(rs_3m=None), False),
        ("3-month relative strength", {}, ctx(rs_3m=-1.0), False),
        ("1-month relative strength", {}, ctx(rs_1m=-5.0), False),
        ("too far below the high", dict(price=99.0), ctx(), False),
        ("an average missing", dict(ma=ma(sma20=None)), ctx(), False),
        ("broken stack", dict(ma=ma(sma50=95.0, sma200=99.0)), ctx(), False),
        ("rsi outside the window", dict(rsi={"daily": 44.0}), ctx(), False),
        ("volatility at its own extreme", {}, ctx(atr_pctile=0.95), False),
        ("run away from the base", {}, ctx(run_pct=13.43), False),
        ("recent down-thrust", dict(volume=thrusts((-3, "down"))), ctx(), False),
    ]

    def test_each_condition_records_itself_exactly_once(self):
        for name, over, c, strict in self.CASES:
            diag = {}
            self.assertIsNone(setups.match_leader(result(**over), c,
                                                  strict=strict, diag=diag), name)
            self.assertEqual(len(diag), 1, "%s recorded %s" % (name, diag))
            (label, (step, count)), = diag.items()
            self.assertEqual(count, 1, name)
            self.assertTrue(label.strip(), name)

    def test_the_conditions_are_distinct_and_ordered_as_tested(self):
        steps = []
        for name, over, c, strict in self.CASES:
            diag = {}
            setups.match_leader(result(**over), c, strict=strict, diag=diag)
            (label, (step, _)), = diag.items()
            steps.append((step, label))
        self.assertEqual(len(set(l for _, l in steps)), len(self.CASES),
                         "two conditions share a label")
        self.assertEqual(len(set(s for s, _ in steps)), len(self.CASES),
                         "two conditions share a step number")
        self.assertEqual(steps, sorted(steps), "steps are out of predicate order")

    def test_the_two_extension_conditions_read_differently(self):
        """They reject for different reasons and must say so: one is "this name
        is at its own most violent", the other "this name has just run"."""
        labels = []
        for c in (ctx(atr_pctile=0.95), ctx(run_pct=13.43)):
            diag = {}
            setups.match_leader(result(), c, diag=diag)
            (label, _), = diag.items()
            labels.append(label)
        self.assertIn("volatility", labels[0])
        self.assertIn("sessions", labels[1])
        self.assertNotEqual(labels[0], labels[1])

    def test_a_match_records_nothing(self):
        diag = {}
        self.assertIsNotNone(setups.match_leader(result(), ctx(), diag=diag))
        self.assertEqual(diag, {})

    def test_the_verdict_is_identical_with_and_without_the_funnel(self):
        for name, over, c, strict in self.CASES + [("match", {}, ctx(), False)]:
            plain = setups.match_leader(result(**over), c, strict=strict)
            traced = setups.match_leader(result(**over), c, strict=strict, diag={})
            self.assertEqual(plain, traced, name)


class TestLeaderMaStack(unittest.TestCase):
    """The loosened arm is `px > sma50 > sma200 and px > sma20` -- three
    comparisons, each of which must be shown load-bearing on its own."""

    def test_price_below_sma50_rejects(self):
        self.assertIsNone(setups.match_leader(result(ma=ma(sma50=109.0)), ctx()))

    def test_price_at_sma50_rejects(self):
        self.assertIsNone(setups.match_leader(result(ma=ma(sma50=108.0)), ctx()))

    def test_sma50_at_or_below_sma200_rejects(self):
        self.assertIsNone(setups.match_leader(result(ma=ma(sma50=100.0,
                                                           sma200=100.0)), ctx()))
        self.assertIsNone(setups.match_leader(result(ma=ma(sma50=100.0,
                                                           sma200=101.0)), ctx()))

    def test_price_below_sma20_rejects_even_with_a_clean_long_stack(self):
        """The `and px > sma20` conjunct, isolated: 108 > 100 > 90 holds, so
        dropping this conjunct would let an extended-then-faded name through.
        This is exactly the case the brief's strict fixture (price 104, sma20
        105) hits by accident, which is why that fixture never reached the
        threshold it meant to test."""
        self.assertIsNone(setups.match_leader(result(ma=ma(sma20=110.0)), ctx()))

    def test_price_at_sma20_rejects(self):
        self.assertIsNone(setups.match_leader(result(ma=ma(sma20=108.0)), ctx()))

    def test_sma20_below_sma50_still_matches_loosened_but_is_not_a_full_stack(self):
        """full_stack is evidence, not a gate: 108 > 99 and 108 > 100 > 90, so
        the loosened arm passes while the short average sits out of order.
        Covers the False arm of full_stack, which every other fixture skips."""
        ev = setups.match_leader(result(ma=ma(sma20=99.0, sma50=100.0)), ctx())
        self.assertIsNotNone(ev)
        self.assertFalse(ev["full_stack"])

    def test_strict_requires_the_short_average_on_top(self):
        """Same fixture as above under strict: the ordered stack is mandatory."""
        self.assertIsNone(setups.match_leader(result(ma=ma(sma20=99.0, sma50=100.0)),
                                              ctx(), strict=True))

    def test_strict_chain_is_exclusive_at_every_link(self):
        """`>` three times, not `>=`.

        Both cases were survivors in the first mutation run: loosening either
        link of the strict chain changed no verdict any test looked at, because
        the near-miss fixtures sit far from equality. Equality is also where a
        loosened link would BREAK NESTING -- strict would accept an input that
        the loosened arm rejects -- so each case asserts both modes.
        """
        at_sma20 = result(ma=ma(sma20=108.0, sma50=100.0))    # px == sma20
        self.assertIsNone(setups.match_leader(at_sma20, ctx(), strict=True))
        self.assertIsNone(setups.match_leader(at_sma20, ctx()))

        tied = result(ma=ma(sma20=98.0, sma50=98.0))          # sma20 == sma50
        self.assertIsNone(setups.match_leader(tied, ctx(), strict=True))
        self.assertIsNotNone(setups.match_leader(tied, ctx()))

        tied_long = result(ma=ma(sma20=99.0, sma50=95.0, sma200=95.0))
        self.assertIsNone(setups.match_leader(tied_long, ctx(), strict=True))


class TestLeaderStrict(unittest.TestCase):
    def test_strict_requires_within_5_percent_of_high(self):
        """The brief uses price 104 against sma20 105, which the loosened MA
        stack rejects outright -- its assertIsNotNone cannot hold. 106 is 5.36%
        below the 112 high and still above every average, so the distance
        threshold is the only thing separating the two modes.
        """
        o = result(price=106.0)
        self.assertIsNotNone(setups.match_leader(o, ctx()))
        self.assertIsNone(setups.match_leader(o, ctx(), strict=True))

    def test_strict_distance_ceiling_is_inclusive_at_five_percent(self):
        self.assertIsNotNone(setups.match_leader(result(price=114.0, **EXACT),
                                                 ctx(), strict=True))
        self.assertIsNone(setups.match_leader(result(price=113.99, **EXACT),
                                              ctx(), strict=True))

    def test_strict_requires_positive_1m_relative_strength(self):
        self.assertIsNotNone(setups.match_leader(result(), ctx(rs_1m=-1.0)))
        self.assertIsNone(setups.match_leader(result(), ctx(rs_1m=-1.0), strict=True))

    def test_strict_one_month_floor_is_inclusive_at_zero(self):
        self.assertIsNotNone(setups.match_leader(result(), ctx(rs_1m=0.0),
                                                 strict=True))
        self.assertIsNone(setups.match_leader(result(), ctx(rs_1m=-0.01),
                                              strict=True))

    def test_strict_narrows_the_rsi_window_at_both_ends(self):
        for rsi_val in (55.0, 85.0):
            self.assertIsNotNone(setups.match_leader(
                result(rsi={"daily": rsi_val}), ctx(), strict=True),
                "rsi %s" % rsi_val)
        for rsi_val in (54.99, 85.01):
            self.assertIsNotNone(setups.match_leader(
                result(rsi={"daily": rsi_val}), ctx()), "loosened rsi %s" % rsi_val)
            self.assertIsNone(setups.match_leader(
                result(rsi={"daily": rsi_val}), ctx(), strict=True),
                "strict rsi %s" % rsi_val)

    def test_strict_defaults_to_false_when_omitted(self):
        """An input the two modes disagree on, called with no strict argument."""
        self.assertIsNotNone(setups.match_leader(result(), ctx(rs_1m=-1.0)))


class TestLeaderFit(unittest.TestCase):
    def ev(self, **over):
        e = {"pct_from_high": 3.0, "rs_1m": 3.0, "rs_3m": 12.0, "full_stack": True}
        e.update(over)
        return e

    def test_stronger_relative_strength_scores_higher(self):
        strong = setups.fit_leader(setups.match_leader(result(), ctx(rs_3m=25.0)))
        weak = setups.fit_leader(setups.match_leader(result(), ctx(rs_3m=2.0)))
        self.assertTrue(0.0 <= weak < strong <= 10.0)

    def test_closer_to_the_high_scores_higher(self):
        """The proximity term carries weight of its own; the test above holds
        distance constant, so a fit ignoring it survived."""
        self.assertGreater(setups.fit_leader(self.ev(pct_from_high=1.0)),
                           setups.fit_leader(self.ev(pct_from_high=9.0)))

    def test_full_stack_scores_higher_than_a_partial_one(self):
        self.assertGreater(setups.fit_leader(self.ev(full_stack=True)),
                           setups.fit_leader(self.ev(full_stack=False)))

    def test_weights_are_forty_thirty_five_twenty_five(self):
        """rs 12.0 -> 8, distance 3.0 -> 8, full stack -> 10.
        0.40*8 + 0.35*8 + 0.25*10 = 3.2 + 2.8 + 2.5 = 8.5. Equal thirds would
        give 8.67, and the second case (rs 25 -> 10) separates them further:
        0.40*10 + 2.8 + 2.5 = 9.3 versus 9.33 for equal thirds.
        """
        self.assertAlmostEqual(setups.fit_leader(self.ev()), 8.5, places=6)
        self.assertAlmostEqual(setups.fit_leader(self.ev(rs_3m=25.0)), 9.3, places=6)

    def test_stack_bonus_is_exactly_three_points_of_sub_score(self):
        """10 vs 7 at a weight of 0.25 is a 0.75 gap. An ordering assertion
        alone would survive any pair with the larger value first."""
        self.assertAlmostEqual(setups.fit_leader(self.ev(full_stack=True))
                               - setups.fit_leader(self.ev(full_stack=False)),
                               0.75, places=6)
        self.assertAlmostEqual(setups.fit_leader(self.ev(full_stack=False)), 7.75,
                               places=6)

    def test_every_relative_strength_cut_is_reachable(self):
        """At the cut and just below it, so a cut cannot move in either
        direction. The 0.35*8 + 0.25*10 = 5.3 remainder is held fixed."""
        cuts = [(20.0, 10), (10.0, 8), (5.0, 6), (0.0, 4)]
        for i, (rs, sub) in enumerate(cuts):
            self.assertAlmostEqual(setups.fit_leader(self.ev(rs_3m=rs)),
                                   round(0.40 * sub + 5.3, 2), places=6,
                                   msg="at cut %s" % rs)
            below = cuts[i + 1][1] if i + 1 < len(cuts) else 0.0
            self.assertAlmostEqual(setups.fit_leader(self.ev(rs_3m=rs - 0.001)),
                                   round(0.40 * below + 5.3, 2), places=6,
                                   msg="just below cut %s" % rs)

    def test_every_proximity_cut_is_reachable(self):
        """band_desc, so the paired case sits just ABOVE each cut."""
        cuts = [(2.0, 10), (5.0, 8), (10.0, 6)]
        for i, (pct, sub) in enumerate(cuts):
            self.assertAlmostEqual(setups.fit_leader(self.ev(pct_from_high=pct)),
                                   round(3.2 + 0.35 * sub + 2.5, 2), places=6,
                                   msg="at cut %s" % pct)
            above = cuts[i + 1][1] if i + 1 < len(cuts) else 0.0
            self.assertAlmostEqual(
                setups.fit_leader(self.ev(pct_from_high=pct + 0.001)),
                round(3.2 + 0.35 * above + 2.5, 2), places=6,
                msg="just above cut %s" % pct)

    def test_fit_stays_inside_zero_to_ten(self):
        best = self.ev(rs_3m=90.0, pct_from_high=0.0, full_stack=True)
        worst = self.ev(rs_3m=0.01, pct_from_high=10.0, full_stack=False)
        self.assertAlmostEqual(setups.fit_leader(best), 10.0, places=6)
        self.assertTrue(0.0 <= setups.fit_leader(worst) <= 10.0)


class TestLeaderThresholdTable(unittest.TestCase):
    def test_registry_carries_the_spec_numbers(self):
        self.assertEqual(setups.THRESHOLDS["LEADER"],
                         {"max_from_high_pct": (10.0, 5.0), "rs_1m_floor": (-2.0, 0.0),
                          "rsi_lo": (50.0, 55.0), "rsi_hi": (88.0, 85.0),
                          "atr_pctile_hi": (0.90, 0.85), "max_run_pct": (10.0, 8.0),
                          "strict_ma_stack": (False, True)})

    def test_the_rsi_ceiling_was_left_alone(self):
        """The extension guard is not a second RSI, and adding it must not have
        been an excuse to move rsi_hi as well."""
        self.assertEqual(setups.THRESHOLDS["LEADER"]["rsi_hi"], (88.0, 85.0))

    def test_strict_is_never_looser_than_loosened(self):
        th = setups.THRESHOLDS["LEADER"]
        self.assertLessEqual(th["max_from_high_pct"][1], th["max_from_high_pct"][0])
        self.assertGreaterEqual(th["rs_1m_floor"][1], th["rs_1m_floor"][0])
        self.assertGreaterEqual(th["rsi_lo"][1], th["rsi_lo"][0])
        self.assertLessEqual(th["rsi_hi"][1], th["rsi_hi"][0])
        self.assertLessEqual(th["atr_pctile_hi"][1], th["atr_pctile_hi"][0])
        self.assertLessEqual(th["max_run_pct"][1], th["max_run_pct"][0])

    def test_anything_matching_strict_also_matches_loosened(self):
        checked = 0
        for price in (99.0, 106.0, 108.0, 114.0, 119.0):
            for rs1 in (-5.0, -2.0, -0.01, 0.0, 4.0):
                for rs3 in (-1.0, 0.0, 0.01, 12.0):
                    for rsi_val in (49.99, 54.99, 55.0, 85.0, 85.01):
                        for sma20 in (98.0, 99.0, 100.0, 108.0, 110.0):
                            o = result(price=price, hi52=120.0,
                                       rsi={"daily": rsi_val},
                                       ma=ma(sma20=sma20, sma50=98.0, sma200=90.0))
                            c = ctx(rs_1m=rs1, rs_3m=rs3)
                            if setups.match_leader(o, c, strict=True) is not None:
                                checked += 1
                                self.assertIsNotNone(
                                    setups.match_leader(o, c, strict=False),
                                    "strict matched but loosened did not: "
                                    "px=%s rs1=%s rs3=%s rsi=%s sma20=%s"
                                    % (price, rs1, rs3, rsi_val, sma20))
        self.assertGreater(checked, 0, "grid produced no strict matches at all")

    def test_the_extension_inputs_nest_too(self):
        """The grid above holds both extension inputs at their fixture defaults,
        so neither threshold pair is walked across its own boundaries. This one
        varies exactly those two, including the None arm."""
        checked = 0
        for pctile in (0.20, 0.85, 0.8501, 0.90, 0.9001, 1.0):
            for run in (None, -13.43, 0.0, 8.0, 8.01, 10.0, 10.01, 25.0):
                c = ctx(atr_pctile=pctile, run_pct=run)
                if setups.match_leader(result(), c, strict=True) is not None:
                    checked += 1
                    self.assertIsNotNone(
                        setups.match_leader(result(), c, strict=False),
                        "strict matched but loosened did not: pctile=%s run=%s"
                        % (pctile, run))
        self.assertGreater(checked, 0, "grid produced no strict matches at all")


if __name__ == "__main__":
    unittest.main()
