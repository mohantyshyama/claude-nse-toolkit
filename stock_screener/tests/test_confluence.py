import itertools, os, sys, unittest
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
sys.path.insert(0, _root)
sys.path.insert(0, _here)
import setups
from engine import A
from fixtures import bar, cmf_series, flat_series, trend_series, ud_series


def vshape(down_n, up_n, top=300.0, down_step=1.0, up_step=2.0, vol=1_000_000,
           down_spread=2.0, pause_at=-8):
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

    `pause_at` swaps two adjacent closes near the end so the advance prints one
    DOWN close. Without it every bar in the last 50 closes up, ud_ratio has no
    denominator, and LEADER and TURN both reject this rig on their volume gate
    for a reason the fixture never meant to express -- the exact blind spot a
    monotonic series creates.

    A SWAP, not an inserted dip, because a swap is invisible to almost
    everything else the rig is asked to be: the multiset of closes is unchanged,
    so the median turnover the liquidity gate reads is identical to the bit
    (TestEvaluateLiquidityGate pins it at 2.985 crore); and every moving-average
    window containing BOTH bars sums to exactly what it did before, so only a
    window beginning between them differs -- one SMA value, mid-recovery,
    nowhere near the cross. Highs and lows travel with their closes, so the bars
    stay well formed and the base high a breakout must clear is unmoved.
    """
    rows, c = [], top
    for _ in range(down_n):
        rows.append(bar(len(rows), c, c + down_spread, c - down_spread, c, vol))
        c -= down_step
    for _ in range(up_n):
        c += up_step
        rows.append(bar(len(rows), c, c + 1, c - 1, c, vol))
    if pause_at is not None and len(rows) > abs(pause_at):
        rows[pause_at]["c"], rows[pause_at + 1]["c"] = \
            rows[pause_at + 1]["c"], rows[pause_at]["c"]
        for r in (rows[pause_at], rows[pause_at + 1]):
            r["h"], r["l"] = r["c"] + 1, r["c"] - 1
    return rows


def m(fit, ud=None):
    """A matched entry shaped the way evaluate() builds one.

    That includes the TOP-LEVEL ud_ratio beside fit, not only the copy inside
    evidence: _add_confluence reads the top-level key, and a helper that omitted
    it would let these unit tests pass against a contract the real caller
    violates.
    """
    return {"fit": fit, "ud_ratio": ud,
            "evidence": {} if ud is None else {"ud_ratio": ud}}


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

    def test_confluence_carries_the_up_down_ratio_of_its_constituents(self):
        """The report prints a ud_ratio column for CONFLUENCE too, so the
        evidence has to carry one. It is a property of the SYMBOL, so every
        constituent holds the identical number and copying the first is not a
        choice between disagreeing values."""
        out = setups._add_confluence({"COILED": m(8.0, ud=1.42),
                                      "LEADER": m(6.0, ud=1.42)})
        self.assertAlmostEqual(out["CONFLUENCE"]["evidence"]["ud_ratio"], 1.42,
                               places=6)

    def test_confluence_ratio_is_copied_not_recomputed_or_averaged(self):
        """A CONFLUENCE row disagreeing with the rows it is made of would be
        worse than no column. The mean fit IS averaged; the ratio is not."""
        out = setups._add_confluence({"COILED": m(8.0, ud=2.0),
                                      "LEADER": m(6.0, ud=2.0)})
        self.assertAlmostEqual(out["CONFLUENCE"]["evidence"]["ud_ratio"], 2.0,
                               places=6)
        self.assertAlmostEqual(out["CONFLUENCE"]["evidence"]["mean_fit"], 7.0,
                               places=6)

    def test_an_unmeasurable_ratio_survives_into_confluence_as_none(self):
        """None must not become 1.0 or vanish on the way up: the column prints
        a dash for it, and a silent default would print a confident number for a
        name whose ratio could not be formed."""
        out = setups._add_confluence({"COILED": m(8.0), "LEADER": m(6.0)})
        self.assertIn("ud_ratio", out["CONFLUENCE"]["evidence"])
        self.assertIsNone(out["CONFLUENCE"]["evidence"]["ud_ratio"])

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
            # The volume block is part of the entry shape, not an extra: the
            # renderer reads it off every match without consulting evidence.
            self.assertEqual(set(out[name]),
                             {"fit", "evidence"} | set(setups.VOLUME_KEYS))
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
        # The volume block still rides along even though this stub's evidence
        # is empty: it is read from ctx, so it does not depend on the
        # predicate's payload.
        expected = setups._volume_block(
            setups._ctx_from_rows(self.rig.rows, self.rs))
        expected.update({"fit": 4.0, "evidence": {}})
        self.assertEqual(out["COILED"], expected)
        self.assertEqual(out["COILED"]["ud_ratio"],
                         setups.ud_ratio(self.rig.rows, setups.UD_BARS))

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
                             "close_position", "up_thrusts", "ud_ratio"}
        tighter_is_lower = {"atr_pctile", "max_extension_pct", "dryup",
                            "max_from_high_pct", "rsi_hi", "ma_dist_pct",
                            "atr_mult_to_support", "cross_bars",
                            "atr_pctile_hi", "max_run_pct",
                            "support_tol_atr", "reversal_bars",
                            "pullback_vol_ratio"}
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


class TestUdRatioRidesOnEveryMatchedEntry(unittest.TestCase):
    """The interface contract: ``matched[setup]["ud_ratio"]``, at the TOP level.

    A renderer prints this figure for every table including CONFLUENCE, whose
    two evidence slots are already spoken for by the matched label and the mean
    fit. Reading the number out of ``evidence`` therefore cannot serve
    CONFLUENCE at all, which is why the key rides beside ``fit`` rather than
    inside whichever payload a predicate happened to build.
    """

    def setUp(self):
        self.rig = Rig()
        self.rig.seed()
        self.rs = {"1m": 8.0, "3m": 14.0}

    def tearDown(self):
        self.rig.clear()

    def test_every_entry_including_confluence_carries_the_key(self):
        m = setups.evaluate(self.rig.scored(), self.rs)
        self.assertIn("CONFLUENCE", m,
                      "the rig stopped matching two setups, so the CONFLUENCE "
                      "arm of this contract is no longer exercised")
        for name, hit in m.items():
            self.assertIn("ud_ratio", hit, name)

    def test_the_value_is_the_symbols_own_measured_ratio(self):
        """Pinned to what ud_ratio() returns for these very rows, so a constant,
        a copy of fit, or a different ctx key all fail."""
        expected = setups.ud_ratio(self.rig.rows, setups.UD_BARS)
        self.assertIsNotNone(expected)
        # A fixture sitting at 1.0 or at the fit value could not tell a real
        # read from a hardcoded one.
        self.assertNotEqual(expected, 1.0)
        m = setups.evaluate(self.rig.scored(), self.rs)
        for name, hit in m.items():
            self.assertEqual(hit["ud_ratio"], expected, name)
            self.assertNotEqual(hit["fit"], expected, name)

    def test_the_key_comes_from_ctx_and_not_from_the_predicates_evidence(self):
        """A predicate whose evidence omits ud_ratio must STILL get the key.

        This is what makes the contract independent of five separate payload
        dicts. An `evidence.get("ud_ratio")` implementation hands back None here
        and dies; reading ctx once cannot.
        """
        expected = setups.ud_ratio(self.rig.rows, setups.UD_BARS)
        orig = setups.REGISTRY["COILED"]
        setups.REGISTRY["COILED"] = (
            lambda o, ctx, strict, diag: {"contraction": 0.5, "pos_in_base": 0.9,
                                          "dryup": 0.6},
            lambda ev: 5.0)
        try:
            m = setups.evaluate(self.rig.scored(), self.rs)
        finally:
            setups.REGISTRY["COILED"] = orig
        self.assertNotIn("ud_ratio", m["COILED"]["evidence"])
        self.assertEqual(m["COILED"]["ud_ratio"], expected)

    def test_confluence_carries_none_through_rather_than_dropping_the_key(self):
        """None means unmeasurable and must REACH the renderer as None.

        An implementation that only set the key when it had a number would drop
        it here, and the renderer would raise on exactly the names that need a
        dash printed.
        """
        matched = {
            "COILED": {"fit": 7.0, "evidence": {"ud_ratio": None}, "ud_ratio": None},
            "LEADER": {"fit": 8.0, "evidence": {"ud_ratio": None}, "ud_ratio": None}}
        out = setups._add_confluence(matched)
        self.assertIn("ud_ratio", out["CONFLUENCE"])
        self.assertIsNone(out["CONFLUENCE"]["ud_ratio"])

    def test_confluence_reports_the_same_number_as_its_constituents(self):
        """Distinct from every fit in the rig, so copying a fit up fails."""
        matched = {
            "COILED": {"fit": 7.0, "evidence": {"ud_ratio": 2.5}, "ud_ratio": 2.5},
            "LEADER": {"fit": 8.0, "evidence": {"ud_ratio": 2.5}, "ud_ratio": 2.5}}
        out = setups._add_confluence(matched)
        self.assertEqual(out["CONFLUENCE"]["ud_ratio"], 2.5)
        self.assertEqual(out["CONFLUENCE"]["evidence"]["ud_ratio"], 2.5)


class TestUdWeighted(unittest.TestCase):
    """The close-weighted ratio: volume x Chaikin multiplier, up over down.

    Every fixture here is built by cmf_series, whose whole reason to exist is
    that the close position VARIES bar to bar -- see its docstring for the three
    ways the older fixtures cannot tell a correct implementation from a wrong
    one.
    """

    VOLS = (1_000_000, 2_000_000, 3_000_000, 4_000_000, 5_000_000)

    def test_multiplier_weights_each_bars_volume_by_its_close_position(self):
        # positions 1.0 / 0.75 / 0.5 / 0.25 / 0.0 -> m = +1, +0.5, 0, -0.5, -1
        #   up   = 1e6*1.0 + 2e6*0.5           = 2e6
        #   down = 4e6*0.5 + 5e6*1.0           = 7e6
        rows = cmf_series([1.0, 0.75, 0.5, 0.25, 0.0], vols=self.VOLS)
        self.assertAlmostEqual(setups.ud_weighted(rows, 50), 2 / 7, places=9)

    def test_the_fixture_can_tell_up_over_down_from_down_over_up(self):
        """The guard on this whole class.

        A sign-flipped multiplier and a swapped numerator/denominator both
        return the RECIPROCAL of the right answer, so a fixture landing on 1.0 --
        which every equal-close-position series does -- proves nothing at all.
        """
        rows = cmf_series([1.0, 0.75, 0.5, 0.25, 0.0], vols=self.VOLS)
        r = setups.ud_weighted(rows, 50)
        self.assertNotAlmostEqual(r, 1 / r, places=6)

    def test_a_midpoint_close_counts_toward_neither_bucket(self):
        """m == 0 is not a down bar. `else: down += v` is the natural typo and
        it would let a fortnight of doji decide the ratio."""
        vols = (1_000_000, 2_000_000, 3_000_000)
        quiet = cmf_series([1.0, 0.0, 0.5], vols=vols)
        loud = cmf_series([1.0, 0.0, 0.5], vols=(1_000_000, 2_000_000, 90_000_000))
        self.assertAlmostEqual(setups.ud_weighted(quiet, 50), 0.5, places=9)
        self.assertAlmostEqual(setups.ud_weighted(loud, 50), 0.5, places=9)

    def test_a_bar_is_weighted_by_how_far_off_the_midpoint_it_closed(self):
        """Not a bar count and not a raw volume sum: a close 60% of the way up
        its range is worth a fifth of one at the high, on the same volume."""
        equal_vol = (1_000_000, 1_000_000, 1_000_000)
        rows = cmf_series([1.0, 0.6, 0.0], vols=equal_vol)
        #   up = 1e6*1.0 + 1e6*0.2 = 1.2e6 ; down = 1e6*1.0
        self.assertAlmostEqual(setups.ud_weighted(rows, 50), 1.2, places=9)
        # `up += v` (unweighted) would read 2.0 here.
        self.assertNotAlmostEqual(setups.ud_weighted(rows, 50), 2.0, places=6)

    def test_zero_range_bars_are_skipped_not_counted_as_neutral(self):
        plain = cmf_series([1.0, 0.0], vols=(1_000_000, 2_000_000))
        with_limit_bar = cmf_series(
            [1.0, 0.0, 1.0], vols=(1_000_000, 2_000_000, 50_000_000),
            spans=(2.0, 2.0, 0.0))
        self.assertEqual(with_limit_bar[2]["h"], with_limit_bar[2]["l"],
                         "the fixture stopped building a real zero-range bar")
        self.assertAlmostEqual(setups.ud_weighted(plain, 50), 0.5, places=9)
        self.assertAlmostEqual(setups.ud_weighted(with_limit_bar, 50), 0.5,
                               places=9)

    def test_an_all_zero_range_series_is_unmeasurable_rather_than_a_crash(self):
        self.assertIsNone(setups.ud_weighted(flat_series(60, spread=0.0), 50))

    def test_none_when_no_bar_closed_below_its_own_midpoint(self):
        """The denominator is empty, so there is no ratio -- the same decision
        ud_ratio makes when nothing closed down."""
        self.assertIsNone(setups.ud_weighted(
            cmf_series([1.0, 0.75, 0.5, 0.6], vols=self.VOLS), 50))

    def test_zero_up_volume_is_a_measured_zero_and_not_none(self):
        """0.0 and None are different findings and must stay so: one says every
        close was sold, the other says the series could not be judged."""
        rows = cmf_series([0.0, 0.25, 0.5], vols=self.VOLS)
        self.assertEqual(setups.ud_weighted(rows, 50), 0.0)
        self.assertIsNotNone(setups.ud_weighted(rows, 50))

    def test_a_non_positive_window_is_none_and_not_the_whole_series(self):
        """`rows[-0:]` is the WHOLE list. The same trap ud_ratio guards, and a
        fixture whose full-series answer is a real number is what makes an
        unguarded implementation visible."""
        rows = cmf_series([1.0, 0.75, 0.5, 0.25, 0.0], vols=self.VOLS)
        self.assertIsNotNone(setups.ud_weighted(rows, 5))
        self.assertIsNone(setups.ud_weighted(rows, 0))
        self.assertIsNone(setups.ud_weighted(rows, -3))

    def test_an_empty_series_is_none(self):
        self.assertIsNone(setups.ud_weighted([], 50))

    def test_only_the_last_n_bars_are_measured(self):
        rows = (cmf_series([0.0, 0.0, 0.0], vols=(9_000_000,) * 3)
                + cmf_series([1.0, 0.0], vols=(1_000_000, 2_000_000)))
        self.assertAlmostEqual(setups.ud_weighted(rows, 2), 0.5, places=9)
        self.assertLess(setups.ud_weighted(rows, 50), 0.5)

    def test_the_default_window_is_the_shared_fifty_bar_one(self):
        """A repeating pattern reads the same over 20 bars as over 50 and could
        not tell the default apart from UD_SHORT_BARS. The heavy selling here
        sits in the far 30 bars only."""
        rows = (cmf_series([0.1] * 30, vols=(1_000_000,))
                + cmf_series([1.0, 0.0] * 10, vols=(1_000_000, 2_000_000)))
        self.assertEqual(setups.ud_weighted(rows),
                         setups.ud_weighted(rows, setups.UD_BARS))
        self.assertAlmostEqual(setups.ud_weighted(rows, setups.UD_SHORT_BARS),
                               0.5, places=9)
        self.assertAlmostEqual(setups.ud_weighted(rows), 10 / 44, places=9)


class TestUdShortWindow(unittest.TestCase):
    def test_the_short_window_is_twenty_bars(self):
        self.assertEqual(setups.UD_SHORT_BARS, 20)
        self.assertLess(setups.UD_SHORT_BARS, setups.UD_BARS)


class TestVolumeSignal(unittest.TestCase):
    def test_the_split_points_are_the_documented_ones(self):
        self.assertEqual(setups.VOLUME_SIGNAL_UD, 1.25)
        self.assertEqual(setups.VOLUME_SIGNAL_WEIGHTED, 1.0)

    def test_both_strong_is_accumulation(self):
        self.assertEqual(setups.volume_signal(1.60, 1.40), setups.ACCUMULATION)

    def test_rising_price_sold_into_the_close_is_distribution_into_strength(self):
        """The case the whole measurement exists for. CONCORDBIO's live numbers."""
        self.assertEqual(setups.volume_signal(3.74, 0.59),
                         setups.DISTRIBUTION_INTO_STRENGTH)

    def test_soft_price_bought_on_every_dip_is_supported(self):
        self.assertEqual(setups.volume_signal(0.80, 1.40), setups.SUPPORTED)

    def test_both_weak_is_distribution(self):
        self.assertEqual(setups.volume_signal(0.80, 0.60), setups.DISTRIBUTION)

    def test_the_ud_boundary_is_inclusive(self):
        self.assertEqual(setups.volume_signal(1.25, 1.40), setups.ACCUMULATION)
        self.assertEqual(setups.volume_signal(1.24, 1.40), setups.SUPPORTED)

    def test_the_weighted_boundary_is_inclusive(self):
        self.assertEqual(setups.volume_signal(1.60, 1.0), setups.ACCUMULATION)
        self.assertEqual(setups.volume_signal(1.60, 0.99),
                         setups.DISTRIBUTION_INTO_STRENGTH)
        self.assertEqual(setups.volume_signal(0.80, 1.0), setups.SUPPORTED)
        self.assertEqual(setups.volume_signal(0.80, 0.99), setups.DISTRIBUTION)

    def test_an_unmeasurable_ratio_reads_unknown_from_either_side(self):
        self.assertEqual(setups.volume_signal(None, 1.40), setups.SIGNAL_UNKNOWN)
        self.assertEqual(setups.volume_signal(1.60, None), setups.SIGNAL_UNKNOWN)
        self.assertEqual(setups.volume_signal(None, None), setups.SIGNAL_UNKNOWN)

    def test_a_measured_zero_is_not_treated_as_missing(self):
        """0.0 is a finding; None is the absence of one. `if not ud` collapses
        them and would print 'unknown' for the most distributed name on the
        list."""
        self.assertEqual(setups.volume_signal(0.0, 0.0), setups.DISTRIBUTION)
        self.assertEqual(setups.volume_signal(0.0, 2.0), setups.SUPPORTED)
        self.assertEqual(setups.volume_signal(2.0, 0.0),
                         setups.DISTRIBUTION_INTO_STRENGTH)

    def test_every_input_including_none_gets_a_defined_label(self):
        values = (None, 0.0, 0.5, 0.99, 1.0, 1.24, 1.25, 3.0)
        for ud in values:
            for w in values:
                out = setups.volume_signal(ud, w)
                self.assertIn(out, setups.VOLUME_SIGNALS, "%r/%r" % (ud, w))
                self.assertIsInstance(out, str)

    def test_the_four_real_labels_are_all_reachable(self):
        seen = {setups.volume_signal(ud, w)
                for ud in (0.5, 2.0) for w in (0.5, 2.0)}
        self.assertEqual(seen, setups.VOLUME_SIGNALS - {setups.SIGNAL_UNKNOWN})


class TestAccumulationTrend(unittest.TestCase):
    def test_the_bands_are_the_documented_ones(self):
        self.assertEqual(setups.TREND_FADE, 0.70)
        self.assertEqual(setups.TREND_FLAT, 0.90)
        self.assertEqual(setups.TREND_STEADY_HI, 1.30)
        self.assertEqual(setups.TREND_REVERSAL_UD, 1.0)

    def test_a_near_window_under_one_and_far_below_the_far_one_has_reversed(self):
        """VIJAYA: 1.70 over 50 bars, 0.52 over 20."""
        self.assertEqual(setups.accumulation_trend(1.70, 0.52),
                         setups.TREND_REVERSED)

    def test_a_collapsing_ratio_still_above_one_is_only_fading(self):
        """CONCORDBIO 3.74/1.18 and BHARATFORG 2.05/1.06: both under 70% of
        their own 50-bar reading, neither yet distributing."""
        self.assertEqual(setups.accumulation_trend(3.74, 1.18),
                         setups.TREND_FADING)
        self.assertEqual(setups.accumulation_trend(2.05, 1.06),
                         setups.TREND_FADING)

    def test_reversed_is_tested_before_fading(self):
        """Both conditions hold for these inputs; the stronger label must win.
        Reordering the two branches returns 'fading' here."""
        self.assertEqual(setups.accumulation_trend(2.0, 0.5),
                         setups.TREND_REVERSED)

    def test_both_arms_of_the_reversed_condition_are_required(self):
        # fraction low, near window still at 1.0 exactly -> not reversed
        self.assertEqual(setups.accumulation_trend(2.0, 1.0), setups.TREND_FADING)
        self.assertEqual(setups.accumulation_trend(2.0, 0.999),
                         setups.TREND_REVERSED)
        # near window under 1.0 but holding 80% of the far one -> not reversed
        self.assertEqual(setups.accumulation_trend(1.0, 0.8),
                         setups.TREND_FLATTENING)

    def test_the_fading_boundary(self):
        self.assertEqual(setups.accumulation_trend(2.0, 1.39), setups.TREND_FADING)
        self.assertEqual(setups.accumulation_trend(2.0, 1.4),
                         setups.TREND_FLATTENING)

    def test_the_flattening_boundary(self):
        self.assertEqual(setups.accumulation_trend(2.0, 1.79),
                         setups.TREND_FLATTENING)
        self.assertEqual(setups.accumulation_trend(2.0, 1.8), setups.TREND_STEADY)

    def test_the_steady_boundary(self):
        self.assertEqual(setups.accumulation_trend(1.0, 1.30), setups.TREND_STEADY)
        self.assertEqual(setups.accumulation_trend(1.0, 1.31),
                         setups.TREND_STRENGTHENING)

    def test_an_unchanged_pair_is_steady(self):
        self.assertEqual(setups.accumulation_trend(1.47, 1.47),
                         setups.TREND_STEADY)

    def test_an_unmeasurable_ratio_reads_unknown_from_either_side(self):
        self.assertEqual(setups.accumulation_trend(None, 1.2),
                         setups.TREND_UNKNOWN)
        self.assertEqual(setups.accumulation_trend(1.2, None),
                         setups.TREND_UNKNOWN)
        self.assertEqual(setups.accumulation_trend(None, None),
                         setups.TREND_UNKNOWN)

    def test_a_zero_far_window_is_unknown_rather_than_a_zero_division(self):
        self.assertEqual(setups.accumulation_trend(0.0, 0.0),
                         setups.TREND_UNKNOWN)
        self.assertEqual(setups.accumulation_trend(0.0, 1.5),
                         setups.TREND_UNKNOWN)

    def test_a_zero_near_window_is_measured_not_discarded(self):
        self.assertEqual(setups.accumulation_trend(2.0, 0.0),
                         setups.TREND_REVERSED)

    def test_every_input_including_none_gets_a_defined_label(self):
        values = (None, 0.0, 0.3, 0.52, 1.0, 1.06, 1.7, 3.74)
        for far in values:
            for near in values:
                out = setups.accumulation_trend(far, near)
                self.assertIn(out, setups.ACCUMULATION_TRENDS,
                              "%r/%r" % (far, near))
                self.assertIsInstance(out, str)

    def test_all_five_real_labels_are_reachable(self):
        seen = {setups.accumulation_trend(2.0, near)
                for near in (0.5, 1.2, 1.5, 1.8, 2.8)}
        self.assertEqual(seen, setups.ACCUMULATION_TRENDS - {setups.TREND_UNKNOWN})


class TestContextCarriesBothNewMeasurements(unittest.TestCase):
    """Computed ONCE per symbol, beside ud_ratio, over the windows they claim."""

    def setUp(self):
        self.rows = cmf_series([1.0, 0.75, 0.5, 0.25, 0.0] * 24,
                               vols=(1_000_000, 2_000_000, 3_000_000,
                                     4_000_000, 5_000_000))

    def test_ud_weighted_is_the_fifty_bar_close_weighted_ratio(self):
        ctx = setups._ctx_from_rows(self.rows, {})
        self.assertAlmostEqual(ctx["ud_weighted"],
                               setups.ud_weighted(self.rows, setups.UD_BARS),
                               places=12)
        self.assertIsNotNone(ctx["ud_weighted"])

    def test_ud_20_is_the_same_ud_ratio_over_a_twenty_bar_window(self):
        ctx = setups._ctx_from_rows(self.rows, {})
        self.assertEqual(ctx["ud_20"],
                         setups.ud_ratio(self.rows, setups.UD_SHORT_BARS))

    def test_ud_20_is_not_silently_the_fifty_bar_number(self):
        """A monotone series reads the same over both windows and could not tell
        a real 20-bar measurement from a copy of the 50-bar key. This one puts
        the down closes inside the far window only: 8.0 over 50, 2.0 over 20."""
        ctx = setups._ctx_from_rows(ud_series("u" * 40 + "d" * 10 + "u" * 10), {})
        self.assertAlmostEqual(ctx["ud_ratio"], 8.0, places=9)
        self.assertAlmostEqual(ctx["ud_20"], 2.0, places=9)

    def test_both_survive_a_series_too_short_to_measure(self):
        ctx = setups._ctx_from_rows(flat_series(3, spread=0.0), {})
        self.assertIsNone(ctx["ud_weighted"])
        self.assertIsNone(ctx["ud_20"])


class TestVolumeBlockRidesOnEveryMatchedEntry(unittest.TestCase):
    """The interface contract the renderer and the CSV writer both read.

    Five keys, at the TOP level of every entry including CONFLUENCE. It is
    load-bearing in the literal sense: screener.build_result_row subscripts them
    rather than using .get, deliberately, because "unknown" is itself a real
    label and a `.get(..., "unknown")` default would make a producer that
    stopped emitting the key indistinguishable from a market with no history.
    """

    def setUp(self):
        self.rig = Rig()
        self.rig.seed()
        self.rs = {"1m": 8.0, "3m": 14.0}

    def tearDown(self):
        self.rig.clear()

    def test_the_key_list_is_the_documented_five(self):
        self.assertEqual(setups.VOLUME_KEYS,
                         ("ud_ratio", "ud_weighted", "ud_20",
                          "volume_signal", "accumulation_trend"))

    def test_every_entry_including_confluence_carries_all_five(self):
        m = setups.evaluate(self.rig.scored(), self.rs)
        self.assertIn("CONFLUENCE", m,
                      "the rig stopped matching two setups, so the CONFLUENCE "
                      "arm of this contract is no longer exercised")
        for name, hit in m.items():
            for key in setups.VOLUME_KEYS:
                self.assertIn(key, hit, "%s.%s" % (name, key))

    def test_the_values_are_the_symbols_own_measurements(self):
        rows = self.rig.rows
        expected = {
            "ud_ratio": setups.ud_ratio(rows, setups.UD_BARS),
            "ud_weighted": setups.ud_weighted(rows, setups.UD_BARS),
            "ud_20": setups.ud_ratio(rows, setups.UD_SHORT_BARS)}
        # A fixture whose three ratios coincided could not tell one key from
        # another, and one sitting at the fit value could not tell a real read
        # from a copy.
        self.assertEqual(len(set(expected.values())), 3, expected)
        m = setups.evaluate(self.rig.scored(), self.rs)
        for name, hit in m.items():
            for key, want in expected.items():
                self.assertEqual(hit[key], want, "%s.%s" % (name, key))
                self.assertNotEqual(hit["fit"], want, "%s.%s" % (name, key))

    def test_the_labels_are_derived_from_this_symbols_own_ratios(self):
        rows = self.rig.rows
        m = setups.evaluate(self.rig.scored(), self.rs)
        want_sig = setups.volume_signal(
            setups.ud_ratio(rows, setups.UD_BARS),
            setups.ud_weighted(rows, setups.UD_BARS))
        want_trend = setups.accumulation_trend(
            setups.ud_ratio(rows, setups.UD_BARS),
            setups.ud_ratio(rows, setups.UD_SHORT_BARS))
        for name, hit in m.items():
            self.assertEqual(hit["volume_signal"], want_sig, name)
            self.assertEqual(hit["accumulation_trend"], want_trend, name)

    def test_the_labels_are_always_strings_never_none(self):
        m = setups.evaluate(self.rig.scored(), self.rs)
        for name, hit in m.items():
            self.assertIn(hit["volume_signal"], setups.VOLUME_SIGNALS, name)
            self.assertIn(hit["accumulation_trend"], setups.ACCUMULATION_TRENDS,
                          name)

    def test_the_block_comes_from_ctx_and_not_from_the_predicates_evidence(self):
        """A predicate whose evidence omits every volume key must STILL get all
        five. This is what makes the contract independent of five separate
        payload dicts."""
        orig = setups.REGISTRY["COILED"]
        setups.REGISTRY["COILED"] = (
            lambda o, ctx, strict, diag: {"contraction": 0.5, "pos_in_base": 0.9,
                                          "dryup": 0.6},
            lambda ev: 5.0)
        try:
            m = setups.evaluate(self.rig.scored(), self.rs)
        finally:
            setups.REGISTRY["COILED"] = orig
        for key in setups.VOLUME_KEYS:
            self.assertNotIn(key, m["COILED"]["evidence"], key)
            self.assertIn(key, m["COILED"], key)
        self.assertEqual(m["COILED"]["ud_ratio"],
                         setups.ud_ratio(self.rig.rows, setups.UD_BARS))

    def test_confluence_reports_the_same_block_as_its_constituents(self):
        m = setups.evaluate(self.rig.scored(), self.rs)
        first = [n for n in setups.SETUPS if n in m][0]
        for key in setups.VOLUME_KEYS:
            self.assertEqual(m["CONFLUENCE"][key], m[first][key], key)

    def test_confluence_carries_none_ratios_through_rather_than_dropping_them(self):
        """None means unmeasurable and must REACH the renderer as None."""
        block = {"ud_ratio": None, "ud_weighted": None, "ud_20": None,
                 "volume_signal": setups.SIGNAL_UNKNOWN,
                 "accumulation_trend": setups.TREND_UNKNOWN}
        matched = {"COILED": dict(block, fit=7.0, evidence={"ud_ratio": None}),
                   "LEADER": dict(block, fit=8.0, evidence={"ud_ratio": None})}
        out = setups._add_confluence(matched)
        for key in setups.VOLUME_KEYS:
            self.assertIn(key, out["CONFLUENCE"], key)
        self.assertIsNone(out["CONFLUENCE"]["ud_weighted"])
        self.assertEqual(out["CONFLUENCE"]["volume_signal"],
                         setups.SIGNAL_UNKNOWN)

    def test_confluence_copies_the_block_rather_than_recomputing_it(self):
        """Values distinct from every fit in the pair, so copying a fit up
        fails; and a label that disagrees with its own ratios, so a CONFLUENCE
        that re-derived the labels would print something its constituents do
        not."""
        block = {"ud_ratio": 2.5, "ud_weighted": 0.4, "ud_20": 0.9,
                 "volume_signal": "sentinel-signal",
                 "accumulation_trend": "sentinel-trend"}
        matched = {"COILED": dict(block, fit=7.0, evidence={"ud_ratio": 2.5}),
                   "LEADER": dict(block, fit=8.0, evidence={"ud_ratio": 2.5})}
        out = setups._add_confluence(matched)
        for key, want in block.items():
            self.assertEqual(out["CONFLUENCE"][key], want, key)
        self.assertEqual(out["CONFLUENCE"]["evidence"]["ud_ratio"], 2.5)


class TestDistributionFloorPair(unittest.TestCase):
    def test_it_is_a_loosened_strict_pair_like_every_other_threshold(self):
        self.assertIsInstance(setups.DISTRIBUTION_FLOOR, tuple)
        self.assertEqual(len(setups.DISTRIBUTION_FLOOR), 2)

    def test_strict_is_never_looser_than_loosened(self):
        """A LOWER floor excludes FEWER names, so a strict half below the
        loosened one would let strict match something loosened does not and
        break the subset invariant that holds everywhere else in this file."""
        lo, st = setups.DISTRIBUTION_FLOOR
        self.assertGreaterEqual(st, lo)

    def test_the_floor_is_the_documented_one(self):
        self.assertEqual(setups.DISTRIBUTION_FLOOR[0], 1.0)

    def test_it_is_not_in_the_per_setup_threshold_table(self):
        """One statement about the symbol, applied identically to all five.
        Five copies of the same pair would be five places to disagree -- and
        test_the_threshold_table_has_no_orphan_entries would then have to be
        told about a key no setup varies."""
        for name, keys in setups.THRESHOLDS.items():
            self.assertNotIn("distribution_floor", keys, name)


class TestNotDistributing(unittest.TestCase):
    """The shared helper, on its own, at every corner of its two conditions."""

    def ctx(self, weighted, short):
        return {"ud_weighted": weighted, "ud_20": short}

    def test_both_below_the_floor_is_the_only_rejection(self):
        self.assertFalse(setups._not_distributing(self.ctx(0.9, 0.9), False))

    def test_either_one_at_or_above_the_floor_passes(self):
        self.assertTrue(setups._not_distributing(self.ctx(1.0, 0.9), False))
        self.assertTrue(setups._not_distributing(self.ctx(0.9, 1.0), False))
        self.assertTrue(setups._not_distributing(self.ctx(1.4, 1.4), False))

    def test_a_none_on_either_side_is_not_a_confirmation(self):
        self.assertTrue(setups._not_distributing(self.ctx(None, 0.1), False))
        self.assertTrue(setups._not_distributing(self.ctx(0.1, None), False))
        self.assertTrue(setups._not_distributing(self.ctx(None, None), False))

    def test_a_missing_key_behaves_like_an_unmeasurable_one(self):
        self.assertTrue(setups._not_distributing({}, False))

    def test_a_measured_zero_rejects_through_the_comparison(self):
        self.assertFalse(setups._not_distributing(self.ctx(0.0, 0.0), False))

    def test_strict_reads_the_second_half_of_the_pair(self):
        orig = setups.DISTRIBUTION_FLOOR
        setups.DISTRIBUTION_FLOOR = (1.0, 1.5)
        try:
            self.assertTrue(setups._not_distributing(self.ctx(1.2, 1.2), False))
            self.assertFalse(setups._not_distributing(self.ctx(1.2, 1.2), True))
        finally:
            setups.DISTRIBUTION_FLOOR = orig

    def test_the_funnel_label_names_the_passing_condition_and_its_floor(self):
        orig = setups.DISTRIBUTION_FLOOR
        setups.DISTRIBUTION_FLOOR = (1.0, 1.5)
        try:
            self.assertIn("1.00", setups._distributing_label(False))
            self.assertIn("1.50", setups._distributing_label(True))
        finally:
            setups.DISTRIBUTION_FLOOR = orig


class TestEverySetupConsultsTheDistributionGate(unittest.TestCase):
    """A gate wired into four predicates out of five is the failure mode this
    class exists for: the fifth would go on matching distributed names in the
    one table nobody checked."""

    def setUp(self):
        self.rig = Rig()
        self.rig.seed()
        self.rs = {"1m": 8.0, "3m": 14.0}

    def tearDown(self):
        self.rig.clear()

    def test_a_gate_that_always_rejects_empties_every_table(self):
        baseline = setups.evaluate(self.rig.scored(), self.rs)
        self.assertTrue(baseline, "the rig stopped matching anything")
        orig = setups._not_distributing
        setups._not_distributing = lambda ctx, strict: False
        try:
            out = setups.evaluate(self.rig.scored(), self.rs)
        finally:
            setups._not_distributing = orig
        self.assertEqual(out, {},
                         "these setups never consulted the gate: %s"
                         % sorted(out))

    def test_a_gate_that_always_passes_leaves_the_tables_alone(self):
        """The paired assertion, so the test above cannot be satisfied by a
        patch that breaks evaluate() outright."""
        baseline = setups.evaluate(self.rig.scored(), self.rs)
        orig = setups._not_distributing
        setups._not_distributing = lambda ctx, strict: True
        try:
            out = setups.evaluate(self.rig.scored(), self.rs)
        finally:
            setups._not_distributing = orig
        self.assertEqual(sorted(out), sorted(baseline))


class TestFitAccumulationBlend(unittest.TestCase):
    """The composed term: two ladders and a trend deduction.

    test_setups_series.TestFitAccumulation pins the LADDER by passing the same
    ratio to both arms; this pins what happens when they disagree, and what the
    20-bar window costs.
    """

    def test_the_two_ladders_share_the_term_equally(self):
        self.assertEqual(setups.ACC_WEIGHT_UD, 0.5)
        self.assertEqual(setups.ACC_WEIGHT_WEIGHTED, 0.5)

    def test_the_weights_sum_to_one_so_an_aligned_name_is_unchanged(self):
        """The compatibility property, asserted rather than assumed: a name
        whose two ratios agree scores exactly the rung it always did."""
        self.assertAlmostEqual(setups.ACC_WEIGHT_UD + setups.ACC_WEIGHT_WEIGHTED,
                               1.0, places=12)
        for ud, rung in ((2.50, 10.0), (2.00, 9.0), (1.50, 8.0), (1.25, 6.0),
                         (1.00, 4.0), (0.50, 2.0)):
            self.assertAlmostEqual(setups.fit_accumulation(ud, ud, ud), rung,
                                   places=9, msg=str(ud))

    def test_a_disagreement_lands_between_the_two_rungs(self):
        """CONCORDBIO: 3.74 close-to-close tops the ladder at 10, 0.59
        close-weighted sits on the 2.0 floor. Half of each is 6.0 -- and the
        20-bar window is held at the 50-bar value so only the blend moves."""
        self.assertAlmostEqual(setups.fit_accumulation(3.74, 0.59, 3.74), 6.0,
                               places=9)

    def test_the_close_weighted_arm_is_not_ignored(self):
        """Two names identical on the conventional ratio must not tie."""
        self.assertGreater(setups.fit_accumulation(2.0, 2.0, 2.0),
                           setups.fit_accumulation(2.0, 0.5, 2.0))

    def test_the_close_to_close_arm_is_not_ignored(self):
        self.assertGreater(setups.fit_accumulation(2.0, 2.0, 2.0),
                           setups.fit_accumulation(0.5, 2.0, 2.0))

    def test_the_two_arms_are_not_interchangeable(self):
        """A swapped pair of arguments must be visible. Equal weights make the
        SCORE symmetric, so the trend -- which reads the close-to-close ratio
        and not the close-weighted one -- is what tells them apart."""
        self.assertNotAlmostEqual(setups.fit_accumulation(3.0, 1.0, 1.0),
                                  setups.fit_accumulation(1.0, 3.0, 1.0),
                                  places=6)

    def test_the_penalties_are_the_documented_ones(self):
        self.assertEqual(setups.TREND_PENALTY,
                         {setups.TREND_REVERSED: 2.0, setups.TREND_FADING: 1.0})

    def test_a_fading_trend_costs_one_ladder_point(self):
        steady = setups.fit_accumulation(2.0, 2.0, 2.0)
        fading = setups.fit_accumulation(2.0, 2.0, 1.2)
        self.assertEqual(setups.accumulation_trend(2.0, 1.2), setups.TREND_FADING)
        self.assertAlmostEqual(steady - fading, 1.0, places=9)

    def test_a_reversed_trend_costs_two(self):
        steady = setups.fit_accumulation(2.0, 2.0, 2.0)
        rev = setups.fit_accumulation(2.0, 2.0, 0.9)
        self.assertEqual(setups.accumulation_trend(2.0, 0.9),
                         setups.TREND_REVERSED)
        self.assertAlmostEqual(steady - rev, 2.0, places=9)

    def test_reversed_costs_strictly_more_than_fading(self):
        self.assertLess(setups.fit_accumulation(2.0, 2.0, 0.9),
                        setups.fit_accumulation(2.0, 2.0, 1.2))

    def test_the_untroubled_trends_cost_nothing(self):
        base = setups.fit_accumulation(2.0, 2.0, 2.0)
        for near, label in ((1.7, setups.TREND_FLATTENING),
                            (2.0, setups.TREND_STEADY),
                            (2.8, setups.TREND_STRENGTHENING)):
            self.assertEqual(setups.accumulation_trend(2.0, near), label)
            self.assertAlmostEqual(setups.fit_accumulation(2.0, 2.0, near),
                                   base, places=9, msg=label)

    def test_an_unmeasurable_trend_is_not_charged_twice(self):
        """The ratio that could not be measured is already paying through its
        own ladder arm; deducting again would price a data gap as a finding."""
        self.assertAlmostEqual(setups.fit_accumulation(2.0, 2.0, None),
                               setups.fit_accumulation(2.0, 2.0, 2.0), places=9)

    def test_an_unmeasurable_pair_scores_the_floor(self):
        self.assertAlmostEqual(setups.fit_accumulation(None, None, None),
                               setups.NO_ACCUMULATION, places=9)

    def test_the_result_never_leaves_zero_to_ten(self):
        values = (None, 0.0, 0.5, 1.0, 1.25, 1.6, 2.5, 40.0)
        for ud in values:
            for w in values:
                for near in values:
                    out = setups.fit_accumulation(ud, w, near)
                    self.assertTrue(0.0 <= out <= 10.0,
                                    "%r/%r/%r -> %r" % (ud, w, near, out))

    def test_the_floor_is_reachable_and_is_exactly_zero(self):
        """Both ladders at the 2.0 floor and a reversed trend. The lower clamp
        is documented as defensive; this shows the arithmetic reaches it."""
        self.assertEqual(setups.accumulation_trend(0.9, 0.5),
                         setups.TREND_REVERSED)
        self.assertAlmostEqual(setups.fit_accumulation(0.9, 0.9, 0.5), 0.0,
                               places=9)

    def test_all_three_arguments_are_required(self):
        """A default would let a call site that forgot the close-weighted ratio
        score every name as if it were unmeasurable -- a silent halving of the
        term across a whole scan, visible nowhere."""
        with self.assertRaises(TypeError):
            setups.fit_accumulation(1.6)
        with self.assertRaises(TypeError):
            setups.fit_accumulation(1.6, 1.6)

    def test_the_penalty_reads_the_same_trend_the_report_prints(self):
        """A second copy of the banding here would let a row be docked for a
        trend its own label denies."""
        calls = []
        orig = setups.accumulation_trend
        setups.accumulation_trend = lambda far, near: (calls.append((far, near))
                                                       or orig(far, near))
        try:
            setups.fit_accumulation(1.7, 1.4, 0.52)
        finally:
            setups.accumulation_trend = orig
        self.assertEqual(calls, [(1.7, 0.52)])


class TestEverySetupPricesAllThreeNumbers(unittest.TestCase):
    """The wiring, per setup: every fit_* must pass all three keys through.

    A fit that passed only ud_ratio would score every name as if its
    close-weighted ratio were unmeasurable -- half the term, silently, in that
    one table.
    """

    EVIDENCE = {
        "COILED": {"contraction": 0.5, "pos_in_base": 0.9, "dryup": 0.6},
        "BREAKOUT": {"vol_mult": 2.5, "pct_above_base": 1.0, "base_bars": 20,
                     "tightness": 5.0, "volume_light": False},
        "LEADER": {"pct_from_high": 3.0, "rs_1m": 3.0, "rs_3m": 12.0,
                   "full_stack": True},
        "PULLBACK": {"dist_to_ma_pct": 0.5, "rsi": 48.0, "dryup": 0.8,
                     "pullback_vol_ratio": 0.45,
                     "retrace_of_52w_range_pct": 30.0},
        "TURN": {"bars_since_cross": 15, "macd_hist": 0.4, "sma200_rising": True,
                 "vol_expansion": 1.35},
    }

    def fit(self, name, **vol):
        _, fit_fn = setups.REGISTRY[name]
        return fit_fn(dict(self.EVIDENCE[name], **vol))

    def test_each_fit_reads_the_close_weighted_ratio(self):
        for name, w in setups.FIT_WEIGHTS.items():
            strong = self.fit(name, ud_ratio=2.0, ud_weighted=2.0, ud_20=2.0)
            sold = self.fit(name, ud_ratio=2.0, ud_weighted=0.5, ud_20=2.0)
            self.assertAlmostEqual(strong - sold,
                                   round(w["accumulation"] * 0.5 * 7.0, 10),
                                   places=6, msg=name)

    def test_each_fit_reads_the_twenty_bar_ratio(self):
        for name, w in setups.FIT_WEIGHTS.items():
            steady = self.fit(name, ud_ratio=2.0, ud_weighted=2.0, ud_20=2.0)
            rev = self.fit(name, ud_ratio=2.0, ud_weighted=2.0, ud_20=0.9)
            self.assertAlmostEqual(steady - rev, w["accumulation"] * 2.0,
                                   places=6, msg=name)

    def test_every_setups_weights_still_sum_to_exactly_one(self):
        """Nothing was bolted on top of the score: the term learned to read two
        more numbers, it did not take a sixth share of the total."""
        for name, w in setups.FIT_WEIGHTS.items():
            self.assertEqual(sum(w.values()), 1.0, msg=name)
            self.assertIn("accumulation", w, name)


if __name__ == "__main__":
    unittest.main()
