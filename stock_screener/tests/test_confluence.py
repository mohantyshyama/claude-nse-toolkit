import itertools, os, sys, unittest
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
sys.path.insert(0, _root)
sys.path.insert(0, _here)
import setups
from engine import A
from fixtures import bar, trend_series


def vshape(down_n, up_n, top=300.0, down_step=1.0, up_step=2.0, vol=1_000_000,
           down_spread=2.0):
    """The same V used in the TURN tests: the 50D crosses back above the 200D
    exactly 59 bars into the recovery, so vshape(200, 74) puts a golden cross
    15 bars ago and makes the whole rig match TURN as well as BREAKOUT.

    `down_spread` is the intraday half-range of the DECLINE only; the recovery
    always prints a 1-point half-range. It exists because LEADER now has an
    extension guard reading ctx["atr_pctile"], and a fixture where every bar has
    the same intraday span makes that percentile degenerate: with the decline as
    tight as the recovery, the up-leg gaps 2 a bar against a 2-point span and
    the Wilder ATR climbs monotonically, so today's ATR is the highest of its
    own six months by construction (percentile 1.0) and LEADER rejects for a
    reason that has nothing to do with the chart the fixture means to describe.
    A wider decline puts the recovery on the calm side of its own history, which
    is what "an orderly advance off a bottom" is supposed to look like.

    The closes, the volumes and the recovery bars are untouched by this
    parameter, so the golden-cross date, the liquidity gate, the base high a
    breakout has to clear and the base widths COILED measures are all exactly
    what they were. TestVshapeVolatility pins both of those claims.
    """
    rows, c = [], top
    for _ in range(down_n):
        rows.append(bar(len(rows), c, c + down_spread, c - down_spread, c, vol))
        c -= down_step
    for _ in range(up_n):
        c += up_step
        rows.append(bar(len(rows), c, c + 1, c - 1, c, vol))
    return rows


def m(fit):
    return {"fit": fit, "evidence": {}}


def stub_match(ev):
    """A predicate stub carrying the real signature -- including the optional
    funnel dict evaluate() threads through every predicate."""
    return lambda o, ctx, strict=False, diag=None: ev


class TestConfluence(unittest.TestCase):
    def test_impossible_pairs_are_declared(self):
        self.assertIn(frozenset({"BREAKOUT", "PULLBACK"}), setups.IMPOSSIBLE_PAIRS)

    def test_impossible_pairs_are_exactly_that_one(self):
        """An over-broad table does not fail safe -- it rejects legitimate
        confluences as bugs, and because scan() catches the AssertionError as a
        BaseException the name is deleted from the run rather than reported.
        The membership assertion above cannot see extra entries."""
        self.assertEqual(setups.IMPOSSIBLE_PAIRS,
                         frozenset({frozenset({"BREAKOUT", "PULLBACK"})}))

    def test_confluence_absent_with_fewer_than_two_matches(self):
        self.assertNotIn("CONFLUENCE", setups._add_confluence({"LEADER": m(8.0)}))

    def test_confluence_absent_with_no_matches_at_all(self):
        self.assertEqual(setups._add_confluence({}), {})

    def test_confluence_present_with_two_matches_and_averages_fit(self):
        out = setups._add_confluence({"COILED": m(8.0), "LEADER": m(6.0)})
        self.assertIn("CONFLUENCE", out)
        self.assertAlmostEqual(out["CONFLUENCE"]["fit"], 7.0, places=6)
        self.assertEqual(out["CONFLUENCE"]["evidence"]["matched"], ["COILED", "LEADER"])
        self.assertEqual(out["CONFLUENCE"]["evidence"]["count"], 2)

    def test_confluence_fit_is_the_mean_not_the_max_or_the_sum(self):
        """8.0 and 6.0 average to 7.0, but so does nothing else plausible --
        except that max would give 8.0 and sum 14.0. A THIRD, lower fit
        separates the mean from a median as well: 8, 6, 1 means 5.0 and medians
        6.0."""
        out = setups._add_confluence({"COILED": m(8.0), "LEADER": m(6.0),
                                      "TURN": m(1.0)})
        self.assertAlmostEqual(out["CONFLUENCE"]["fit"], 5.0, places=6)
        self.assertEqual(out["CONFLUENCE"]["evidence"]["count"], 3)

    def test_confluence_fit_is_rounded_to_two_places(self):
        """8.0, 7.0 and 6.1 average to 7.0333...; an unrounded fit would print
        seventeen digits into the report."""
        out = setups._add_confluence({"COILED": m(8.0), "LEADER": m(7.0),
                                      "TURN": m(6.1)})
        self.assertEqual(out["CONFLUENCE"]["fit"], 7.03)

    def test_mean_fit_evidence_agrees_with_the_headline_fit(self):
        out = setups._add_confluence({"COILED": m(8.0), "LEADER": m(6.5)})
        self.assertEqual(out["CONFLUENCE"]["evidence"]["mean_fit"],
                         out["CONFLUENCE"]["fit"])

    def test_matched_label_is_ordered_by_life_cycle_not_alphabetically(self):
        out = setups._add_confluence({"LEADER": m(6.0), "COILED": m(8.0)})
        self.assertEqual(out["CONFLUENCE"]["evidence"]["label"], "COILED+LEADER")

    def test_life_cycle_order_is_the_SETUPS_order_throughout(self):
        """Insertion order is deliberately reversed, and the pair chosen so that
        alphabetical, insertion and life-cycle orders all disagree: life cycle
        puts BREAKOUT before LEADER before TURN, alphabetical puts BREAKOUT
        first too but LEADER after... so a third element (PULLBACK) is added,
        where alphabetical would give LEADER, PULLBACK, TURN and life cycle
        gives the same -- hence TURN is fed first to break insertion order."""
        out = setups._add_confluence({"TURN": m(5.0), "PULLBACK": m(6.0),
                                      "LEADER": m(7.0)})
        self.assertEqual(out["CONFLUENCE"]["evidence"]["matched"],
                         ["LEADER", "PULLBACK", "TURN"])
        self.assertEqual(out["CONFLUENCE"]["evidence"]["label"],
                         "LEADER+PULLBACK+TURN")

    def test_the_result_dict_is_updated_in_place_and_returned(self):
        matched = {"COILED": m(8.0), "LEADER": m(6.0)}
        self.assertIs(setups._add_confluence(matched), matched)
        self.assertIn("CONFLUENCE", matched)

    def test_the_original_setup_entries_are_left_alone(self):
        matched = {"COILED": m(8.0), "LEADER": m(6.0)}
        setups._add_confluence(matched)
        self.assertEqual(matched["COILED"]["fit"], 8.0)
        self.assertEqual(matched["LEADER"]["fit"], 6.0)

    def test_confluence_never_counts_itself(self):
        """`[n for n in SETUPS if n in matched]` filters to real setups; naively
        listing the dict's keys would fold the CONFLUENCE row it just wrote back
        into its own matched list on a second pass, reporting a three-way
        confluence between two setups and itself.
        """
        matched = setups._add_confluence({"COILED": m(8.0), "LEADER": m(6.0)})
        again = setups._add_confluence(matched)
        self.assertEqual(again["CONFLUENCE"]["evidence"]["matched"],
                         ["COILED", "LEADER"])
        self.assertEqual(again["CONFLUENCE"]["evidence"]["count"], 2)
        self.assertEqual(again["CONFLUENCE"]["evidence"]["label"], "COILED+LEADER")
        self.assertAlmostEqual(again["CONFLUENCE"]["fit"], 7.0, places=6)


class TestImpossiblePairs(unittest.TestCase):
    """The assertion has to FIRE, and only for the one declared pair."""

    def test_impossible_pair_raises(self):
        with self.assertRaises(AssertionError):
            setups._add_confluence({"BREAKOUT": m(7.0), "PULLBACK": m(6.0)})

    def test_the_message_names_the_offending_pair(self):
        """A bare AssertionError would send whoever hits this hunting through
        five predicates."""
        with self.assertRaises(AssertionError) as caught:
            setups._add_confluence({"BREAKOUT": m(7.0), "PULLBACK": m(6.0)})
        self.assertIn("BREAKOUT", str(caught.exception))
        self.assertIn("PULLBACK", str(caught.exception))

    def test_an_impossible_pair_buried_among_legal_ones_still_raises(self):
        """The scan is over every pair, not just the first two names: here
        COILED+BREAKOUT and COILED+PULLBACK are both legal and only the third
        combination is illegal."""
        with self.assertRaises(AssertionError):
            setups._add_confluence({"COILED": m(8.0), "BREAKOUT": m(7.0),
                                    "PULLBACK": m(6.0)})

    def test_a_non_adjacent_impossible_pair_still_raises(self):
        """The inner loop must span names[i+1:], not just the next name.

        In life-cycle order these three are BREAKOUT, LEADER, PULLBACK. The two
        adjacent pairs are both legal and the only offence -- BREAKOUT with
        PULLBACK -- sits at indices 0 and 2. An adjacent-only scan reports a
        happy three-way confluence.
        """
        with self.assertRaises(AssertionError):
            setups._add_confluence({"BREAKOUT": m(7.0), "LEADER": m(8.0),
                                    "PULLBACK": m(6.0)})

    def test_legal_pairs_do_not_raise(self):
        """The sibling arm. Without this, an assertion that fired on EVERY pair
        would pass all four tests above. COILED+BREAKOUT leads the list: it is
        the pair the table used to forbid, and the one this ruling restored."""
        for pair in (("COILED", "BREAKOUT"),
                     ("COILED", "LEADER"), ("COILED", "PULLBACK"),
                     ("COILED", "TURN"), ("BREAKOUT", "LEADER"),
                     ("BREAKOUT", "TURN"), ("LEADER", "PULLBACK"),
                     ("LEADER", "TURN"), ("PULLBACK", "TURN")):
            out = setups._add_confluence({pair[0]: m(8.0), pair[1]: m(6.0)})
            self.assertIn("CONFLUENCE", out, "%s+%s" % pair)

    def test_every_subset_containing_a_forbidden_pair_raises(self):
        """Exhaustive over all 26 subsets of two or more setups.

        The hand-written cases above each probe one shape; this asserts the
        property itself, so a pair added to IMPOSSIBLE_PAIRS later is covered
        the moment it is declared rather than when someone remembers to write a
        case for it.

        It also now pins the OUTER loop by example, which it could not while
        COILED+BREAKOUT was forbidden: back then both forbidden pairs contained
        BREAKOUT and every offending subset put the offence on names[0], so a
        scan that only ever took the first name as its left-hand side agreed
        with this one everywhere. BREAKOUT+PULLBACK sits at SETUPS indices 1 and
        3, so {COILED, BREAKOUT, PULLBACK} offends without involving names[0]
        at all and a first-name-only scan fails here.

        Eight subsets of the five setups contain both BREAKOUT and PULLBACK --
        2**3, one per subset of the remaining three names.
        """
        raised = 0
        for r in range(2, len(setups.SETUPS) + 1):
            for subset in itertools.combinations(setups.SETUPS, r):
                offends = any(frozenset(p) in setups.IMPOSSIBLE_PAIRS
                              for p in itertools.combinations(subset, 2))
                matched = {n: m(6.0) for n in subset}
                if offends:
                    raised += 1
                    with self.assertRaises(AssertionError, msg=str(subset)):
                        setups._add_confluence(matched)
                else:
                    self.assertIn("CONFLUENCE", setups._add_confluence(matched),
                                  str(subset))
        self.assertEqual(raised, 8, "the forbidden-pair table changed shape")

    def test_a_single_setup_can_never_trip_the_assertion(self):
        for name in setups.SETUPS:
            self.assertNotIn("CONFLUENCE", setups._add_confluence({name: m(8.0)}))

    def test_the_assertion_fires_through_the_public_entry_point(self):
        """evaluate() must not swallow it.

        The predicates cannot actually produce an impossible pair -- that is the
        whole point -- so the registry is stubbed to force one. Without this the
        assertion is only ever reached by calling the private helper directly,
        and a try/except around _add_confluence inside evaluate would go
        unnoticed.
        """
        rig = Rig()
        rig.seed()
        try:
            always = (stub_match({"stub": True}), lambda ev: 8.0)
            never = (stub_match(None), lambda ev: 0.0)
            original = setups.REGISTRY
            setups.REGISTRY = dict(original, BREAKOUT=always, PULLBACK=always,
                                   COILED=never, LEADER=never, TURN=never)
            try:
                with self.assertRaises(AssertionError):
                    setups.evaluate(rig.scored(), {"1m": 4.0, "3m": 10.0})
            finally:
                setups.REGISTRY = original
        finally:
            rig.clear()


class Rig(object):
    """A seeded, liquid symbol that really matches three setups.

    A.fetch memoises on (symbol, range, interval, suffix), so seeding _CACHE
    drives the whole evaluate() path -- build_ctx, aligned_rows, the liquidity
    gate and all five predicates -- with no network.
    """
    SYMBOL = "LYNX"

    def __init__(self, vol=1_000_000, down_spread=2.0):
        self.rows = vshape(200, 74, vol=vol, down_spread=down_spread)
        self.key = (self.SYMBOL, "2y", "1d", ".NS")

    def seed(self):
        A._CACHE[self.key] = (self.rows, {})

    def clear(self):
        A._CACHE.pop(self.key, None)

    def scored(self, **over):
        px = self.rows[-1]["c"]
        o = {"symbol": self.SYMBOL, "price": px,
             "last_closed_bar": {"t": str(self.rows[-1]["t"]), "v": 2_500_000},
             "ma": {"sma20": px - 5, "sma50": px - 12, "sma100": px - 20,
                    "sma200": px - 30},
             "atr": {"daily": 2.0, "daily_pct": 1.0},
             "volume": {"avg20": 1_000_000, "avg50": 950_000, "dryup_ratio": 0.75,
                        "thrusts": []},
             "range": {"hi": px - 1, "lo": px - 20, "bars": 20},
             "hi52": px, "lo52": px * 0.5,
             "rsi": {"daily": 60.0}, "macd": {"daily": {"hist": 0.5}},
             "returns": {"1m": 8.0, "3m": 14.0},
             "entry_gate": {"rr_at_current_price": 2.2, "nearest_support": px - 3},
             "score": {"total": 7.0}}
        o.update(over)
        return o

    def rankable(self, **over):
        """scored() plus the fields build_result_row and watchlist_analyser's
        projection need, so a matched row can be carried all the way to the
        ranked table rather than only as far as evaluate()."""
        px = self.rows[-1]["c"]
        o = self.scored(
            range={"hi": px - 1, "lo": px - 20, "bars": 20,
                   "breakout_target": px + 30},
            entry_gate={"rr_at_current_price": 2.2, "nearest_support": px - 3,
                        "nearest_resistance": px + 10, "next_resistance": px + 40,
                        "objective_used": px + 10},
            rejection_zones=[],
            fib_extension={"1.272": px + 50},
            score={"total": 7.0, "verdict": "WATCHLIST - constructive",
                   "trend": 8.0, "location": 7.0, "volume": 6.0,
                   "momentum": 7.0, "catalyst": 5.0, "volatility": 6.0})
        o.update(over)
        return o


class TestVshapeVolatility(unittest.TestCase):
    """The decline's width is the ONLY thing `down_spread` may change.

    It was added so LEADER's extension guard could be exercised against a
    fixture that is not, by construction, at the top of its own ATR range. If it
    moved the closes it would move the golden cross, the base high and the
    liquidity gate with it, and every Rig-driven test would be measuring
    something new without saying so.
    """

    def test_only_the_decline_bars_widen(self):
        tight = vshape(200, 74, down_spread=1.0)
        wide = vshape(200, 74, down_spread=2.0)
        self.assertEqual(len(tight), len(wide))
        for a, b in zip(tight, wide):
            self.assertEqual(a["c"], b["c"])
            self.assertEqual(a["o"], b["o"])
            self.assertEqual(a["v"], b["v"])
        for a, b in zip(tight[-74:], wide[-74:]):
            self.assertEqual((a["h"], a["l"]), (b["h"], b["l"]))
        self.assertNotEqual(tight[0]["h"], wide[0]["h"])

    def test_the_golden_cross_does_not_move(self):
        for spread in (1.0, 2.0, 3.0):
            c = setups._ctx_from_rows(vshape(200, 74, down_spread=spread), {})
            self.assertEqual(c["bars_since_cross"], 15, "spread %s" % spread)

    def test_the_default_fixture_is_not_at_the_top_of_its_own_atr_range(self):
        """The claim the default rests on. If this stops holding, every LEADER
        assertion driven by the Rig is being satisfied by the extension guard
        rather than by the condition it names."""
        c = setups._ctx_from_rows(vshape(200, 74), {})
        self.assertLessEqual(c["atr_pctile"],
                             setups.THRESHOLDS["LEADER"]["atr_pctile_hi"][1])

    def test_the_tight_variant_really_is_at_the_top_of_its_range(self):
        """The other side, which is what makes the parameter necessary rather
        than cosmetic."""
        c = setups._ctx_from_rows(vshape(200, 74, down_spread=1.0), {})
        self.assertGreater(c["atr_pctile"],
                           setups.THRESHOLDS["LEADER"]["atr_pctile_hi"][0])


class TestLeaderExtensionGuardThroughEvaluate(unittest.TestCase):
    """The guard reads a ctx value, so it can only be exercised end to end
    against real bars -- the per-predicate tests hand match_leader a literal
    atr_pctile and never prove _ctx_from_rows feeds it the same number."""

    RS = {"1m": 4.0, "3m": 10.0}

    def rig(self, **kw):
        r = Rig(**kw)
        r.seed()
        self.addCleanup(r.clear)
        return r

    def test_a_calm_advance_is_a_leader(self):
        self.assertIn("LEADER", setups.evaluate(self.rig().scored(), self.RS))

    def test_the_same_advance_at_its_own_most_volatile_is_not(self):
        """Identical closes, identical trend, identical relative strength -- the
        decline behind it is narrower, so today's ATR is the highest of its own
        six months and the name is being surfaced at its worst moment."""
        rig = self.rig(down_spread=1.0)
        out = setups.evaluate(rig.scored(), self.RS)
        self.assertNotIn("LEADER", out)

    def test_the_rejection_is_recorded_as_the_extension_condition(self):
        """Not merely absent -- absent for the stated reason. Without this the
        name could be falling out at the MA stack and the guard could be
        deleted."""
        diag = {}
        setups.evaluate(self.rig(down_spread=1.0).scored(), self.RS, diag=diag)
        (label, _), = diag["LEADER"].items()
        self.assertIn("volatility", label)


class TestCoiledBreakoutIsALegitimateConfluence(unittest.TestCase):
    """COILED+BREAKOUT is the VCP breakout, not a predicate bug.

    It was in IMPOSSIBLE_PAIRS only because BREAKOUT's gate was unsatisfiable --
    price could never exceed a base high that included the breakout bar, so the
    pair was unreachable and the assertion cost nothing. Once the gate started
    working, the pair became not merely possible but the single most informative
    row a scan can produce: a base contracting into a close above its own prior
    high, the exact COILED -> BREAKOUT progression these setups model.

    The failure was silent, which is why it is tested end to end here rather
    than only at _add_confluence: the assertion fired inside evaluate(), scan()
    caught it as a BaseException, and the name was recorded as FAILED and
    dropped from every table without anything in the output saying so.
    """

    ALWAYS = (stub_match({"stub": True}), lambda ev: 8.0)
    NEVER = (stub_match(None), lambda ev: 0.0)

    def rig(self):
        r = Rig()
        r.seed()
        self.addCleanup(r.clear)
        return r

    def forced(self, **entries):
        """Pin the registry so the named setups match and the rest do not.

        The real predicates cannot be steered into a specific pair from a single
        fixture, and this test is about what _add_confluence and scan() do with
        a pair, not about how it was produced.
        """
        original = setups.REGISTRY
        base = {n: self.NEVER for n in setups.SETUPS}
        base.update(entries)
        setups.REGISTRY = dict(original, **base)
        self.addCleanup(lambda: setattr(setups, "REGISTRY", original))

    def scanned(self, symbol="LYNX", sector="Financial Services", o=None):
        """Drive screener.scan over one seeded symbol, engine stubbed out."""
        import screener
        saved = (A.compute, screener.index_returns)
        A.compute = lambda sym, catalyst=5.0: dict(o, symbol=sym)
        screener.index_returns = lambda: {"1m": 2.0, "3m": 5.0}
        try:
            return screener.scan([(symbol, sector)], workers=1)
        finally:
            A.compute, screener.index_returns = saved

    def test_the_pair_is_not_declared_impossible(self):
        self.assertNotIn(frozenset({"COILED", "BREAKOUT"}),
                         setups.IMPOSSIBLE_PAIRS)

    def test_a_coiled_breakout_name_is_given_a_confluence_row(self):
        out = setups._add_confluence({"COILED": m(8.0), "BREAKOUT": m(7.0)})
        self.assertIn("CONFLUENCE", out)
        self.assertEqual(out["CONFLUENCE"]["evidence"]["count"], 2)
        self.assertAlmostEqual(out["CONFLUENCE"]["fit"], 7.5, places=6)

    def test_the_label_is_in_life_cycle_order_not_alphabetical(self):
        """This pair is the ONLY place the two orders disagree, and until now it
        was unreachable -- so `sorted(matched)` in place of the SETUPS walk was
        an equivalent mutant on every legal input."""
        out = setups._add_confluence({"BREAKOUT": m(7.0), "COILED": m(8.0)})
        self.assertEqual(out["CONFLUENCE"]["evidence"]["label"],
                         "COILED+BREAKOUT")
        self.assertEqual(out["CONFLUENCE"]["evidence"]["matched"],
                         ["COILED", "BREAKOUT"])

    def test_evaluate_returns_the_pair_instead_of_raising(self):
        rig = self.rig()
        self.forced(COILED=self.ALWAYS, BREAKOUT=self.ALWAYS)
        out = setups.evaluate(rig.scored(), {"1m": 4.0, "3m": 10.0})
        self.assertEqual([n for n in out if n != "CONFLUENCE"],
                         ["COILED", "BREAKOUT"])
        self.assertEqual(out["CONFLUENCE"]["evidence"]["label"],
                         "COILED+BREAKOUT")

    def test_the_name_is_scanned_not_moved_into_FAILED(self):
        """The killer case. Old code: scan() reports zero rows and one FAILED
        entry reading "impossible pair COILED+BREAKOUT", so the name is absent
        from the COILED table, the BREAKOUT table and the CONFLUENCE table
        alike."""
        rig = self.rig()
        self.forced(COILED=self.ALWAYS, BREAKOUT=self.ALWAYS)
        rows, failed = self.scanned(o=rig.scored())
        self.assertEqual(failed, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(sorted(rows[0]["matched"]),
                         ["BREAKOUT", "COILED", "CONFLUENCE"])
        self.assertEqual(rows[0]["matched"]["CONFLUENCE"]["evidence"]["label"],
                         "COILED+BREAKOUT")

    def test_the_scanned_name_reaches_the_ranked_confluence_table(self):
        """Surviving scan() is not enough -- main() builds each table from
        `name in row["matched"]`, so the row has to render and rank too."""
        import screener
        rig = self.rig()
        self.forced(COILED=self.ALWAYS, BREAKOUT=self.ALWAYS)
        rows, _ = self.scanned(o=rig.rankable())
        for setup in ("COILED", "BREAKOUT", "CONFLUENCE"):
            hits = [screener.build_result_row(r, setup) for r in rows
                    if setup in r["matched"]]
            self.assertEqual(len(hits), 1, setup)
            ranked = screener.rank(hits, setup)
            self.assertEqual([r["symbol"] for r in ranked], ["LYNX"], setup)
        self.assertEqual(
            screener.build_result_row(rows[0], "CONFLUENCE")["match_count"], 2)


class TestBreakoutPullbackIsStillImpossible(unittest.TestCase):
    """The other pair keeps its alarm: price above the prior base high AND
    retraced to the 20/50DMA is a contradiction, so it means a predicate is
    wrong. Removing one pair from the table must not disarm the other."""

    ALWAYS = (stub_match({"stub": True}), lambda ev: 8.0)
    NEVER = (stub_match(None), lambda ev: 0.0)

    def rig(self):
        r = Rig()
        r.seed()
        self.addCleanup(r.clear)
        return r

    def forced(self, **entries):
        original = setups.REGISTRY
        base = {n: self.NEVER for n in setups.SETUPS}
        base.update(entries)
        setups.REGISTRY = dict(original, **base)
        self.addCleanup(lambda: setattr(setups, "REGISTRY", original))

    def test_add_confluence_still_raises(self):
        with self.assertRaises(AssertionError):
            setups._add_confluence({"BREAKOUT": m(7.0), "PULLBACK": m(6.0)})

    def test_evaluate_still_raises(self):
        rig = self.rig()
        self.forced(BREAKOUT=self.ALWAYS, PULLBACK=self.ALWAYS)
        with self.assertRaises(AssertionError):
            setups.evaluate(rig.scored(), {"1m": 4.0, "3m": 10.0})

    def test_the_alarm_still_reaches_the_scan_report(self):
        """scan() catches it as a BaseException, so the pair surfaces as a
        FAILED entry naming itself rather than as a silent drop. The e2e suite
        asserts no live name ever lands there."""
        import screener
        rig = self.rig()
        self.forced(BREAKOUT=self.ALWAYS, PULLBACK=self.ALWAYS)
        saved = (A.compute, screener.index_returns)
        o = rig.scored()
        A.compute = lambda sym, catalyst=5.0: dict(o, symbol=sym)
        screener.index_returns = lambda: {"1m": 2.0, "3m": 5.0}
        try:
            rows, failed = screener.scan([("LYNX", "S")], workers=1)
        finally:
            A.compute, screener.index_returns = saved
        self.assertEqual(rows, [])
        self.assertEqual(len(failed), 1)
        self.assertIn("impossible pair", failed[0][1])
        self.assertIn("BREAKOUT", failed[0][1])
        self.assertIn("PULLBACK", failed[0][1])


class TestEvaluate(unittest.TestCase):
    def setUp(self):
        self.rig = Rig()
        self.rig.seed()
        self.rs = {"1m": 4.0, "3m": 10.0}

    def tearDown(self):
        self.rig.clear()

    def test_a_real_symbol_matches_several_setups_at_once(self):
        out = setups.evaluate(self.rig.scored(), self.rs)
        self.assertEqual(sorted(k for k in out if k != "CONFLUENCE"),
                         ["BREAKOUT", "LEADER", "TURN"])
        self.assertEqual(out["CONFLUENCE"]["evidence"]["label"],
                         "BREAKOUT+LEADER+TURN")

    def test_each_entry_carries_a_fit_and_the_predicate_evidence(self):
        out = setups.evaluate(self.rig.scored(), self.rs)
        for name in ("BREAKOUT", "LEADER", "TURN"):
            self.assertEqual(set(out[name]), {"fit", "evidence"})
            self.assertTrue(0.0 <= out[name]["fit"] <= 10.0)
            self.assertTrue(out[name]["evidence"])
        self.assertIn("vol_mult", out["BREAKOUT"]["evidence"])
        self.assertIn("rs_3m", out["LEADER"]["evidence"])
        self.assertIn("bars_since_cross", out["TURN"]["evidence"])

    def test_the_fit_matches_the_setups_own_fit_function(self):
        """Guards against the registry pairing a predicate with the wrong fit --
        every fit returns a 0-10 float, so a mismatch would pass any range
        check."""
        out = setups.evaluate(self.rig.scored(), self.rs)
        for name in ("BREAKOUT", "LEADER", "TURN"):
            _, fit_fn = setups.REGISTRY[name]
            self.assertAlmostEqual(out[name]["fit"], fit_fn(out[name]["evidence"]),
                                   places=9)

    def test_a_name_matching_nothing_returns_an_empty_dict(self):
        out = setups.evaluate(self.rig.scored(rsi={"daily": 20.0},
                                              macd={"daily": {"hist": -1.0}},
                                              ma={"sma20": 900.0, "sma50": 900.0,
                                                  "sma100": 900.0, "sma200": 900.0}),
                              self.rs)
        self.assertEqual(out, {})
        self.assertIsNotNone(out, "a liquid name that matched nothing must NOT "
                                  "read as illiquid")

    def test_a_single_match_carries_no_confluence(self):
        """Only BREAKOUT survives: the relative-strength baseline is missing, so
        LEADER cannot be evaluated, and the 52-week low is lifted right under
        the price so TURN's off-the-low floor rejects."""
        px = self.rig.rows[-1]["c"]
        out = setups.evaluate(self.rig.scored(lo52=px - 1),
                              {"1m": None, "3m": None})
        self.assertEqual(list(out), ["BREAKOUT"])
        self.assertNotIn("CONFLUENCE", out)

    def test_evaluate_stashes_the_aligned_rows_for_the_thrust_check(self):
        o = self.rig.scored()
        setups.evaluate(o, self.rs)
        self.assertEqual(len(o["_rows"]), len(self.rig.rows))

    def test_strict_is_forwarded_to_every_predicate(self):
        """A cross 15 bars old passes both modes, so TURN is held constant while
        the 52-week low is set to make strict's 20% floor bite and loosened's
        12% floor pass."""
        px = self.rig.rows[-1]["c"]
        loose = setups.evaluate(self.rig.scored(lo52=px / 1.15), self.rs)
        strict = setups.evaluate(self.rig.scored(lo52=px / 1.15), self.rs,
                                 strict=True)
        self.assertIn("TURN", loose)
        self.assertNotIn("TURN", strict)

    def test_strict_defaults_to_false_when_omitted(self):
        px = self.rig.rows[-1]["c"]
        self.assertIn("TURN", setups.evaluate(self.rig.scored(lo52=px / 1.15),
                                              self.rs))

    def stubbed(self, **entries):
        original = setups.REGISTRY
        setups.REGISTRY = dict(original, **entries)
        self.addCleanup(lambda: setattr(setups, "REGISTRY", original))

    def test_a_match_with_empty_evidence_is_still_a_match(self):
        """`ev is not None`, not `if ev`.

        No predicate returns an empty dict today, so the two spellings agree on
        every real input and only a stub can tell them apart -- but the contract
        the predicates are written against is "None means no match", and a
        future predicate whose evidence happens to be empty must not vanish.
        """
        self.stubbed(COILED=(stub_match({}), lambda ev: 4.0),
                     BREAKOUT=(stub_match(None), lambda ev: 0.0),
                     LEADER=(stub_match(None), lambda ev: 0.0),
                     PULLBACK=(stub_match(None), lambda ev: 0.0),
                     TURN=(stub_match(None), lambda ev: 0.0))
        out = setups.evaluate(self.rig.scored(), self.rs)
        self.assertEqual(list(out), ["COILED"])
        self.assertEqual(out["COILED"], {"fit": 4.0, "evidence": {}})

    def test_setups_not_the_registry_decides_what_the_screen_reports(self):
        """evaluate() walks SETUPS. A registry entry with no place in the
        life-cycle tuple has no defined position in a confluence label and must
        never reach the output."""
        self.stubbed(GHOST=(stub_match({"stub": True}), lambda ev: 9.9))
        out = setups.evaluate(self.rig.scored(), self.rs)
        self.assertNotIn("GHOST", out)
        self.assertTrue(out)


class TestEvaluateLiquidityGate(unittest.TestCase):
    def tearDown(self):
        for rig in getattr(self, "rigs", []):
            rig.clear()

    def rig(self, vol):
        self.rigs = getattr(self, "rigs", [])
        r = Rig(vol=vol)
        r.seed()
        self.rigs.append(r)
        return r

    def test_illiquid_name_matches_nothing(self):
        """The brief only asserts that liquid() says no; this drives the gate
        through evaluate(), which is where the early return lives. At 100k
        shares a day the median turnover is 1.99 crore, under the 3.0 default.
        """
        rig = self.rig(vol=100_000)
        ctx = setups._ctx_from_rows(rig.rows, {"1m": 1.0, "3m": 2.0})
        self.assertFalse(setups.liquid(ctx, 3.0))
        self.assertIsNone(setups.evaluate(rig.scored(), {"1m": 4.0, "3m": 10.0}))

    def test_the_same_name_screens_once_the_floor_is_lowered(self):
        """The accept side. Without it the gate could be rejecting for some
        other reason, or rejecting everything."""
        rig = self.rig(vol=100_000)
        out = setups.evaluate(rig.scored(), {"1m": 4.0, "3m": 10.0},
                              min_turnover=1.0)
        self.assertTrue(out)

    def test_the_default_floor_is_three_crore(self):
        """2.985 crore is rejected by the default and 19.9 crore is not, so the
        default cannot drift far in either direction without a failure."""
        thin = self.rig(vol=150_000)
        self.assertAlmostEqual(
            setups.turnover_cr(thin.rows, 50), 2.985, places=6)
        self.assertIsNone(setups.evaluate(thin.scored(), {"1m": 4.0, "3m": 10.0}))
        self.assertTrue(setups.evaluate(thin.scored(), {"1m": 4.0, "3m": 10.0},
                                        min_turnover=2.98))

    def test_the_gate_runs_before_any_predicate(self):
        """An illiquid name returns None rather than a populated dict, even
        though every predicate would have matched had it been asked."""
        thin = self.rig(vol=150_000)
        self.assertTrue(setups.evaluate(thin.scored(), {"1m": 4.0, "3m": 10.0},
                                        min_turnover=1.0))
        self.assertIsNone(setups.evaluate(thin.scored(), {"1m": 4.0, "3m": 10.0}))


class TestEvaluateTriState(unittest.TestCase):
    """evaluate() has three outcomes, and two of them are falsy.

    Before this contract existed, `if not matched` conflated "never screened,
    too thin to trade" with "screened against all five predicates and matched
    none of them". The second is the common case by a wide margin, so the scan
    header reported several hundred perfectly liquid names as being below the
    turnover floor. Each state gets its own assertion here, and each is asserted
    against BOTH of the others, because `assertFalse` cannot tell them apart.
    """

    #: same rig, mutated into a name no predicate will take: oversold RSI, a
    #: negative MACD histogram and every moving average parked far overhead.
    QUIET = {"rsi": {"daily": 20.0}, "macd": {"daily": {"hist": -1.0}},
             "ma": {"sma20": 900.0, "sma50": 900.0,
                    "sma100": 900.0, "sma200": 900.0}}
    RS = {"1m": 4.0, "3m": 10.0}

    def rig(self, vol=1_000_000):
        r = Rig(vol=vol)
        r.seed()
        self.addCleanup(r.clear)
        return r

    def test_an_illiquid_name_returns_none(self):
        """100k shares a day is 1.99 crore of turnover, under the 3.0 floor."""
        out = setups.evaluate(self.rig(vol=100_000).scored(), self.RS)
        self.assertIsNone(out)

    def test_a_liquid_name_that_matches_nothing_returns_an_empty_dict(self):
        out = setups.evaluate(self.rig().scored(**self.QUIET), self.RS)
        self.assertIsNotNone(out)
        self.assertEqual(out, {})

    def test_a_liquid_name_that_matches_returns_the_matches(self):
        out = setups.evaluate(self.rig().scored(), self.RS)
        self.assertIsNotNone(out)
        self.assertNotEqual(out, {})
        self.assertIn("BREAKOUT", out)

    def test_the_two_falsy_outcomes_are_distinguishable(self):
        """The whole point. Both are falsy; only `is None` separates them, and a
        caller that reaches for truthiness gets the wrong one every time."""
        illiquid = setups.evaluate(self.rig(vol=100_000).scored(), self.RS)
        quiet = setups.evaluate(self.rig().scored(**self.QUIET), self.RS)
        self.assertFalse(illiquid)          # both fail a truthiness test...
        self.assertFalse(quiet)
        self.assertIsNot(illiquid, quiet)   # ...and are still not the same answer
        self.assertIsNone(illiquid)
        self.assertIsNotNone(quiet)

    def test_the_same_illiquid_name_is_screened_once_the_floor_is_lowered(self):
        """The gate, not the predicates, is what returned None: identical input,
        a lower floor, and the name suddenly has matches."""
        rig = self.rig(vol=100_000)
        self.assertIsNone(setups.evaluate(rig.scored(), self.RS))
        self.assertTrue(setups.evaluate(rig.scored(), self.RS, min_turnover=1.0))

    def test_an_illiquid_name_returns_none_even_when_it_would_match_nothing(self):
        """None must mean "not screened", not "not screened AND would have
        matched". A thin name whose predicates would all reject anyway still
        reports the gate as the reason."""
        out = setups.evaluate(self.rig(vol=100_000).scored(**self.QUIET), self.RS)
        self.assertIsNone(out)


class TestFunnelIsInstrumentationOnly(unittest.TestCase):
    """The rejection funnel records where a name fell; it decides nothing.

    A name's matched/unmatched result must be identical with and without the
    diagnostic dict, or the instrumentation has become part of the screen.
    """

    RS = {"1m": 4.0, "3m": 10.0}

    #: The same rig mutated four ways, so the funnel is exercised against names
    #: that fall at different conditions rather than one shape five times.
    MUTATIONS = [
        {},
        {"rsi": {"daily": 20.0}, "macd": {"daily": {"hist": -1.0}}},
        {"ma": {"sma20": 900.0, "sma50": 900.0, "sma100": 900.0,
                "sma200": 900.0}},
        {"volume": {"avg20": 1_000_000, "avg50": 950_000, "dryup_ratio": 2.0,
                    "thrusts": []}},
    ]

    def rig(self, vol=1_000_000):
        r = Rig(vol=vol)
        r.seed()
        self.addCleanup(r.clear)
        return r

    def test_the_matches_are_identical_with_and_without_a_funnel(self):
        rig = self.rig()
        for over in self.MUTATIONS:
            for strict in (False, True):
                plain = setups.evaluate(rig.scored(**over), self.RS, strict=strict)
                traced = setups.evaluate(rig.scored(**over), self.RS,
                                         strict=strict, diag={})
                self.assertEqual(plain, traced, "%s strict=%s" % (over, strict))

    def test_every_setup_that_did_not_match_names_the_condition_it_failed(self):
        """Across all four mutations, so every predicate is seen rejecting.

        A predicate that returns a bare None somewhere still screens correctly
        while its funnel silently under-reports -- and because "reached" is
        recovered by subtraction, one missing entry inflates every stage below
        it. Nothing else in the suite would notice.
        """
        rig = self.rig()
        checked = set()
        for over in self.MUTATIONS:
            diag = {}
            out = setups.evaluate(rig.scored(**over), self.RS, diag=diag)
            for name in setups.SETUPS:
                if name in out:
                    continue
                checked.add(name)
                self.assertIn(name, diag, "%s %s" % (name, over))
                self.assertEqual(len(diag[name]), 1,
                                 "%s must be counted at ONE condition" % name)
                (label, (step, count)), = diag[name].items()
                self.assertIsInstance(label, str)
                self.assertTrue(label.strip(), "%s recorded an empty label" % name)
                self.assertGreaterEqual(step, 1)
                self.assertEqual(count, 1)
        self.assertEqual(checked, set(setups.SETUPS),
                         "some predicate was never seen rejecting")

    def test_a_setup_that_matched_records_no_rejection(self):
        rig = self.rig()
        diag = {}
        out = setups.evaluate(rig.scored(), self.RS, diag=diag)
        for name in setups.SETUPS:
            if name in out:
                self.assertEqual(diag.get(name, {}), {}, name)

    def test_an_illiquid_name_leaves_the_funnel_untouched(self):
        """The gate returns before any predicate runs, so a thin name has no
        condition to report -- the scan counts it under the turnover floor."""
        diag = {}
        self.assertIsNone(setups.evaluate(self.rig(vol=100_000).scored(),
                                          self.RS, diag=diag))
        self.assertEqual(diag, {})

    def test_the_funnel_defaults_to_off(self):
        """Omitting it must neither raise nor require a dict."""
        self.assertIsNotNone(setups.evaluate(self.rig().scored(), self.RS))

    def test_reject_always_returns_none(self):
        for diag in (None, {}):
            self.assertIsNone(setups._reject(diag, 1, "some condition"))

    def test_reject_without_a_dict_records_nothing_and_does_not_raise(self):
        self.assertIsNone(setups._reject(None, 3, "some condition"))

    def test_reject_counts_repeat_hits_on_one_condition(self):
        """merge_funnel adds these up across symbols; within one symbol the
        counter must still be a counter, not an overwrite."""
        diag = {}
        setups._reject(diag, 4, "a condition")
        setups._reject(diag, 4, "a condition")
        setups._reject(diag, 7, "another")
        self.assertEqual(diag, {"a condition": (4, 2), "another": (7, 1)})


class TestEvaluateContract(unittest.TestCase):
    def test_illiquid_name_matches_nothing(self):
        o = {"symbol": "THIN", "price": 108.0,
             "last_closed_bar": {"t": str(trend_series(60)[-1]["t"]), "v": 100},
             "ma": {"sma20": 104.0, "sma50": 102.0, "sma100": 100.0, "sma200": 98.0},
             "atr": {"daily": 1.0, "daily_pct": 1.0},
             "volume": {"avg20": 100, "avg50": 200, "dryup_ratio": 0.5, "thrusts": []},
             "range": {"hi": 110.0, "lo": 100.0, "bars": 20},
             "hi52": 112.0, "lo52": 70.0, "rsi": {"daily": 55.0},
             "macd": {"daily": {"hist": 0.2}}, "returns": {"1m": 3.0, "3m": 9.0},
             "entry_gate": {"rr_at_current_price": 2.0}, "score": {"total": 6.5}}
        rows = trend_series(60, vol=100)          # ~0.0001 crore/day
        ctx = setups._ctx_from_rows(rows, {"1m": 1.0, "3m": 2.0})
        o["_rows"] = rows
        self.assertFalse(setups.liquid(ctx, 3.0))

    def test_every_setup_name_has_a_predicate_and_a_fit(self):
        for name in setups.SETUPS:
            self.assertIn(name, setups.REGISTRY)
            match_fn, fit_fn = setups.REGISTRY[name]
            self.assertTrue(callable(match_fn) and callable(fit_fn))

    def test_the_registry_pairs_each_name_with_its_own_functions(self):
        """Callability alone is satisfied by five copies of the same pair."""
        self.assertEqual(setups.REGISTRY,
                         {"COILED": (setups.match_coiled, setups.fit_coiled),
                          "BREAKOUT": (setups.match_breakout, setups.fit_breakout),
                          "LEADER": (setups.match_leader, setups.fit_leader),
                          "PULLBACK": (setups.match_pullback, setups.fit_pullback),
                          "TURN": (setups.match_turn, setups.fit_turn)})

    def test_the_registry_has_no_setups_the_screen_never_reports(self):
        self.assertEqual(set(setups.REGISTRY), set(setups.SETUPS))

    def test_every_setup_has_a_threshold_entry(self):
        for name in setups.SETUPS:
            self.assertIn(name, setups.THRESHOLDS)

    def test_the_threshold_table_has_no_orphan_entries(self):
        self.assertEqual(set(setups.THRESHOLDS), set(setups.SETUPS))

    def test_impossible_pairs_only_name_real_setups(self):
        for pair in setups.IMPOSSIBLE_PAIRS:
            for name in pair:
                self.assertIn(name, setups.SETUPS)

    def test_strict_thresholds_are_a_subset_of_loosened(self):
        """A name passing strict must always pass loosened. Direction is checked
        per key: some tighten upward (vol_mult), some downward (max_extension).

        Every key is required to be classified. The brief's version silently
        skips anything in neither set, which left five real keys -- contractions,
        thrust_bars, sma50_rising and both strict_ma_stack flags -- unchecked,
        and would go on skipping any key a later task adds.
        """
        tighter_is_higher = {"min_bars", "vol_mult", "rsi_lo", "off_low_pct",
                             "rs_1m_floor", "pos_in_base", "contractions",
                             "thrust_bars", "sma50_rising", "strict_ma_stack",
                             "swing_margin_atr", "min_retrace_pct",
                             "close_position"}
        tighter_is_lower = {"atr_pctile", "max_extension_pct", "dryup",
                            "max_from_high_pct", "rsi_hi", "ma_dist_pct",
                            "atr_mult_to_support", "cross_bars",
                            "atr_pctile_hi", "max_run_pct",
                            "support_tol_atr", "reversal_bars"}
        seen = set()
        for name, keys in setups.THRESHOLDS.items():
            for key, (lo, st) in keys.items():
                seen.add(key)
                self.assertIn(key, tighter_is_higher | tighter_is_lower,
                              "%s.%s is classified in neither direction" % (name, key))
                if key in tighter_is_higher:
                    self.assertGreaterEqual(st, lo, "%s.%s" % (name, key))
                else:
                    self.assertLessEqual(st, lo, "%s.%s" % (name, key))
        self.assertEqual(seen, tighter_is_higher | tighter_is_lower,
                         "the direction tables list keys no setup actually has")

    def test_every_threshold_entry_is_a_loosened_strict_pair(self):
        for name, keys in setups.THRESHOLDS.items():
            for key, pair in keys.items():
                self.assertIsInstance(pair, tuple, "%s.%s" % (name, key))
                self.assertEqual(len(pair), 2, "%s.%s" % (name, key))


class TestStrictNestsAcrossPredicates(unittest.TestCase):
    """The nesting property end to end: anything matching strict must match
    loosened, for every predicate, over a grid of perturbed inputs.

    The per-setup tests each vary their own fields; this one varies a shared
    grid through evaluate(), which is the level the CONFLUENCE logic and the
    --strict CLI flag actually operate at.
    """

    def setUp(self):
        self.rig = Rig()
        self.rig.seed()

    def tearDown(self):
        self.rig.clear()

    def test_strict_matches_are_always_loosened_matches(self):
        px = self.rig.rows[-1]["c"]
        checked = 0
        for rsi_val in (39.0, 48.0, 49.0, 55.0, 60.0, 86.0):
            for lo52 in (px * 0.5, px / 1.15, px - 1):
                for dryup in (0.75, 0.95, 1.05):
                    for rs in ({"1m": 4.0, "3m": 10.0}, {"1m": -1.0, "3m": 10.0},
                               {"1m": 4.0, "3m": -1.0}, {"1m": None, "3m": None}):
                        o_args = dict(
                            rsi={"daily": rsi_val}, lo52=lo52,
                            volume={"avg20": 1_000_000, "avg50": 950_000,
                                    "dryup_ratio": dryup, "thrusts": []})
                        strict = setups.evaluate(self.rig.scored(**o_args), rs,
                                                 strict=True)
                        loose = setups.evaluate(self.rig.scored(**o_args), rs)
                        for name in strict:
                            if name == "CONFLUENCE":
                                continue
                            checked += 1
                            self.assertIn(
                                name, loose,
                                "%s matched strict but not loosened: rsi=%s "
                                "lo52=%s dryup=%s rs=%s"
                                % (name, rsi_val, lo52, dryup, rs))
        self.assertGreater(checked, 0, "grid produced no strict matches at all")


if __name__ == "__main__":
    unittest.main()
