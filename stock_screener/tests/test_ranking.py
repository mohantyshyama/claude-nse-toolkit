import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import screener


def proj(total, rr):
    return {"total": total, "rr": rr, "trigger": 100.0, "entry": 100.2,
            "stop": 97.0, "target": 110.0, "components": {}}


class TestRepairs(unittest.TestCase):
    def test_repairs_requires_both_score_and_rr(self):
        self.assertTrue(screener.repairs(proj(6.5, 2.4)))
        self.assertFalse(screener.repairs(proj(5.5, 2.4)))
        self.assertFalse(screener.repairs(proj(6.5, 1.8)))
        self.assertFalse(screener.repairs(None))

    def test_constants_match_watchlist_analysers_rule(self):
        """Pins the one intentional duplication. watchlist.py defines repairs()
        as a closure that cannot be imported."""
        self.assertEqual(screener.REPAIR_MIN_TOTAL, 6.0)
        self.assertEqual(screener.REPAIR_MIN_RR, 2.0)


class TestActionMapping(unittest.TestCase):
    def test_wait_that_repairs_becomes_alert(self):
        self.assertEqual(screener._map_action("WAIT @ 123.45", proj(6.5, 2.4)), "ALERT")

    def test_wait_that_does_not_repair_becomes_watch(self):
        self.assertEqual(screener._map_action("WAIT @ 123.45", proj(5.0, 1.2)), "WATCH")

    def test_avoid_that_repairs_becomes_latent(self):
        self.assertEqual(screener._map_action("AVOID", proj(6.4, 2.2)), "LATENT")

    def test_avoid_that_does_not_repair_becomes_watch(self):
        self.assertEqual(screener._map_action("AVOID", proj(4.0, 1.0)), "WATCH")

    def test_buy_actions_pass_through_unchanged(self):
        self.assertEqual(screener._map_action("BUY NOW", None), "BUY NOW")
        self.assertEqual(screener._map_action("BUY HALF", None), "BUY HALF")


class TestRanking(unittest.TestCase):
    def _row(self, sym, total, fit, rr, rs3, trig_total=None):
        return {"symbol": sym, "sector": "X", "fit": fit, "total": total,
                "trigger_total": trig_total, "rr": rr, "rs_3m": rs3,
                "vetoed": rr is not None and rr < 1.5, "action": "BUY NOW"}

    def test_vetoed_names_sort_below_every_clean_name(self):
        rows = [self._row("VETO", 9.0, 10.0, 0.9, 30.0),
                self._row("CLEAN", 5.0, 4.0, 2.0, 1.0)]
        self.assertEqual([r["symbol"] for r in screener.rank(rows, "LEADER")],
                         ["CLEAN", "VETO"])

    def test_leader_ranks_by_score_now(self):
        rows = [self._row("LOW", 5.0, 9.9, 2.0, 1.0),
                self._row("HIGH", 7.0, 3.0, 2.0, 1.0)]
        self.assertEqual([r["symbol"] for r in screener.rank(rows, "LEADER")],
                         ["HIGH", "LOW"])

    def test_coiled_ranks_by_score_at_trigger(self):
        rows = [self._row("A", 5.0, 5.0, 2.0, 1.0, trig_total=6.9),
                self._row("B", 6.5, 5.0, 2.0, 1.0, trig_total=5.1)]
        self.assertEqual([r["symbol"] for r in screener.rank(rows, "COILED")],
                         ["A", "B"])

    def test_turn_also_ranks_by_score_at_trigger(self):
        self.assertIn("TURN", screener.TRIGGER_RANKED)
        self.assertIn("COILED", screener.TRIGGER_RANKED)
        self.assertNotIn("LEADER", screener.TRIGGER_RANKED)

    def test_ties_break_on_three_month_relative_strength(self):
        rows = [self._row("SLOW", 6.0, 5.0, 2.0, 2.0),
                self._row("FAST", 6.0, 5.0, 2.0, 25.0)]
        self.assertEqual([r["symbol"] for r in screener.rank(rows, "LEADER")],
                         ["FAST", "SLOW"])

    def test_confluence_ranks_by_match_count_first(self):
        two = self._row("TWO", 8.5, 9.0, 2.0, 20.0)
        two["match_count"] = 2
        three = self._row("THREE", 5.0, 4.0, 2.0, 1.0)
        three["match_count"] = 3
        self.assertEqual([r["symbol"] for r in screener.rank([two, three], "CONFLUENCE")],
                         ["THREE", "TWO"])


class TestTopClamp(unittest.TestCase):
    def test_default_and_cap(self):
        self.assertEqual(screener.MAX_TOP, 20)
        self.assertEqual(screener.clamp_top(15), (15, False))
        self.assertEqual(screener.clamp_top(20), (20, False))

    def test_above_cap_clamps_and_flags(self):
        self.assertEqual(screener.clamp_top(50), (20, True))

    def test_below_one_clamps_up(self):
        self.assertEqual(screener.clamp_top(0), (1, False))


class TestRepairsBoundaries(unittest.TestCase):
    """Both sides of both thresholds, at the boundary."""

    def test_exactly_at_both_thresholds_repairs(self):
        self.assertTrue(screener.repairs(proj(6.0, 2.0)))

    def test_a_hair_under_the_score_threshold_does_not(self):
        self.assertFalse(screener.repairs(proj(5.99, 2.0)))

    def test_a_hair_under_the_ratio_threshold_does_not(self):
        self.assertFalse(screener.repairs(proj(6.99, 1.99)))

    def test_a_projection_with_no_ratio_does_not_repair(self):
        """score_at_trigger returns rr=None when no objective clears the entry.
        Comparing None with >= raises in Python 3, so the guard is load-bearing."""
        self.assertFalse(screener.repairs(proj(9.0, None)))
        self.assertFalse(screener.repairs(proj(9.0, 0.0)))

    def test_repairs_returns_a_bool_not_a_truthy_value(self):
        self.assertIs(screener.repairs(proj(6.5, 2.4)), True)
        self.assertIs(screener.repairs(None), False)


class TestActionMatrix(unittest.TestCase):
    """Every shape action_for can return, against repairs() true and false."""

    REPAIRING = proj(7.0, 3.0)
    HOLLOW = proj(4.0, 1.0)

    def test_buy_now_ignores_the_projection_either_way(self):
        self.assertEqual(screener._map_action("BUY NOW", self.REPAIRING), "BUY NOW")
        self.assertEqual(screener._map_action("BUY NOW", self.HOLLOW), "BUY NOW")

    def test_buy_half_ignores_the_projection_either_way(self):
        self.assertEqual(screener._map_action("BUY HALF", self.REPAIRING), "BUY HALF")
        self.assertEqual(screener._map_action("BUY HALF", self.HOLLOW), "BUY HALF")

    def test_bare_wait_with_no_price_still_maps_on_repairs(self):
        """action_for returns a bare 'WAIT' when there is no trigger price."""
        self.assertEqual(screener._map_action("WAIT", self.REPAIRING), "ALERT")
        self.assertEqual(screener._map_action("WAIT", self.HOLLOW), "WATCH")

    def test_avoid_with_no_projection_at_all_is_watch(self):
        self.assertEqual(screener._map_action("AVOID", None), "WATCH")

    def test_wait_with_no_projection_at_all_is_watch(self):
        self.assertEqual(screener._map_action("WAIT @ 10.00", None), "WATCH")


class TestScreenerActionUsesWatchlistVocabulary(unittest.TestCase):
    """Drives the real watchlist.action_for so the two skills cannot drift."""

    def _o(self, verdict):
        return {"score": {"verdict": verdict}}

    def test_full_position_verdict_is_buy_now(self):
        self.assertEqual(
            screener.screener_action(self._o("INITIATE FULL POSITION"), None),
            "BUY NOW")

    def test_half_size_verdict_is_buy_half(self):
        self.assertEqual(screener.screener_action(self._o("HALF SIZE"), None),
                         "BUY HALF")

    def test_watchlist_verdict_becomes_alert_when_the_trigger_repairs(self):
        self.assertEqual(
            screener.screener_action(self._o("WATCHLIST - WAIT FOR TRIGGER"),
                                     proj(7.0, 3.0)), "ALERT")

    def test_watchlist_verdict_becomes_watch_when_it_does_not(self):
        self.assertEqual(
            screener.screener_action(self._o("WATCHLIST - WAIT FOR TRIGGER"),
                                     proj(4.0, 1.0)), "WATCH")

    def test_stand_aside_verdict_becomes_latent_when_the_trigger_repairs(self):
        self.assertEqual(
            screener.screener_action(self._o("STAND ASIDE / BEAR BIAS"),
                                     proj(7.0, 3.0)), "LATENT")

    def test_stand_aside_verdict_becomes_watch_when_it_does_not(self):
        self.assertEqual(
            screener.screener_action(self._o("STAND ASIDE / BEAR BIAS"),
                                     proj(4.0, 1.0)), "WATCH")


class TestClampBoundaries(unittest.TestCase):
    def test_one_over_the_cap_clamps_and_flags(self):
        self.assertEqual(screener.clamp_top(21), (20, True))

    def test_one_is_left_alone(self):
        self.assertEqual(screener.clamp_top(1), (1, False))

    def test_negative_clamps_up_without_flagging(self):
        self.assertEqual(screener.clamp_top(-5), (1, False))

    def test_default_top_is_fifteen_and_below_the_cap(self):
        self.assertEqual(screener.DEFAULT_TOP, 15)
        self.assertLessEqual(screener.DEFAULT_TOP, screener.MAX_TOP)


class _ProjStub:
    """Controls score_at_trigger while leaving action_for real."""

    def __init__(self, proj):
        self.proj = proj

    def __enter__(self):
        self.saved = screener.W.score_at_trigger
        screener.W.score_at_trigger = lambda o: self.proj
        return self

    def __exit__(self, *exc):
        screener.W.score_at_trigger = self.saved
        return False


def scanned(verdict="WATCHLIST - WAIT FOR TRIGGER", rr=2.4, atr=10.0,
            evidence=None, price=200.0, total=6.2, fit=8.1,
            rs=None, sector="Information Technology"):
    return {"symbol": "TCS", "sector": sector,
            "rs": rs if rs is not None else {"1m": 3.0, "3m": 11.0},
            "matched": {"LEADER": {"fit": fit,
                                   "evidence": {} if evidence is None else evidence}},
            "o": {"price": price, "score": {"total": total, "verdict": verdict},
                  "entry_gate": {"rr_at_current_price": rr},
                  "atr": {"daily": atr}}}


class TestBuildResultRow(unittest.TestCase):
    def test_a_waiting_name_keeps_its_trigger(self):
        with _ProjStub(proj(7.0, 3.0)):
            r = screener.build_result_row(scanned(), "LEADER")
        self.assertEqual(r["action"], "ALERT")
        self.assertAlmostEqual(r["trigger_total"], 7.0)
        self.assertAlmostEqual(r["trigger_price"], 100.0)

    def test_a_buyable_name_has_no_trigger_to_wait_for(self):
        """The sibling arm: a BUY drops the projection even though one exists."""
        with _ProjStub(proj(7.0, 3.0)):
            r = screener.build_result_row(scanned(verdict="HALF SIZE"), "LEADER")
        self.assertEqual(r["action"], "BUY HALF")
        self.assertIsNone(r["trigger_total"])
        self.assertIsNone(r["trigger_price"])

    def test_no_projection_at_all_blanks_the_trigger_columns(self):
        with _ProjStub(None):
            r = screener.build_result_row(scanned(), "LEADER")
        self.assertIsNone(r["trigger_total"])
        self.assertIsNone(r["trigger_price"])
        self.assertEqual(r["action"], "WATCH")

    def test_stop_is_one_and_a_half_average_true_ranges_below_price(self):
        with _ProjStub(None):
            r = screener.build_result_row(scanned(price=200.0, atr=10.0), "LEADER")
        self.assertAlmostEqual(r["stop"], 185.0, places=9)

    def test_no_average_true_range_means_no_stop_rather_than_a_crash(self):
        with _ProjStub(None):
            r = screener.build_result_row(scanned(atr=None), "LEADER")
        self.assertIsNone(r["stop"])

    def test_ratio_below_one_point_five_is_vetoed(self):
        with _ProjStub(None):
            r = screener.build_result_row(scanned(rr=1.49), "LEADER")
        self.assertTrue(r["vetoed"])

    def test_ratio_exactly_one_point_five_is_not_vetoed(self):
        with _ProjStub(None):
            r = screener.build_result_row(scanned(rr=1.5), "LEADER")
        self.assertFalse(r["vetoed"])

    def test_a_missing_ratio_is_not_a_veto(self):
        """None is 'unmeasurable', not 'bad'. Comparing it with < raises."""
        with _ProjStub(None):
            r = screener.build_result_row(scanned(rr=None), "LEADER")
        self.assertFalse(r["vetoed"])
        self.assertIsNone(r["rr"])

    def test_match_count_defaults_to_one_for_a_single_setup(self):
        with _ProjStub(None):
            r = screener.build_result_row(scanned(evidence={"rs_3m": 4.0}), "LEADER")
        self.assertEqual(r["match_count"], 1)

    def test_match_count_is_read_from_confluence_evidence(self):
        with _ProjStub(None):
            r = screener.build_result_row(scanned(evidence={"count": 3}), "LEADER")
        self.assertEqual(r["match_count"], 3)

    def test_scan_fields_are_carried_through_unchanged(self):
        ev = {"pct_from_high": 2.0}
        with _ProjStub(None):
            r = screener.build_result_row(
                scanned(evidence=ev, price=200.0, total=6.2, fit=8.1,
                        rs={"1m": 3.0, "3m": 11.0}, sector="Metals"), "LEADER")
        self.assertEqual(r["symbol"], "TCS")
        self.assertEqual(r["sector"], "Metals")
        self.assertAlmostEqual(r["price"], 200.0)
        self.assertAlmostEqual(r["total"], 6.2)
        self.assertAlmostEqual(r["fit"], 8.1)
        self.assertAlmostEqual(r["rs_1m"], 3.0)
        self.assertAlmostEqual(r["rs_3m"], 11.0)
        self.assertIs(r["evidence"], ev)
        self.assertIn("o", r)

    def test_the_fit_reported_is_the_selected_setups_fit(self):
        row = scanned(fit=8.1)
        row["matched"]["COILED"] = {"fit": 2.2, "evidence": {}}
        with _ProjStub(None):
            self.assertAlmostEqual(
                screener.build_result_row(row, "COILED")["fit"], 2.2)


class TestRankingEdges(unittest.TestCase):
    def _row(self, sym, **over):
        r = {"symbol": sym, "sector": "X", "fit": 5.0, "total": 6.0,
             "trigger_total": None, "rr": 2.0, "rs_3m": 1.0, "vetoed": False}
        r.update(over)
        return r

    def test_trigger_ranked_setup_falls_back_to_score_now_when_untriggered(self):
        rows = [self._row("NOTRIG", trigger_total=None, total=9.0),
                self._row("TRIG", trigger_total=8.0, total=1.0)]
        self.assertEqual([r["symbol"] for r in screener.rank(rows, "COILED")],
                         ["NOTRIG", "TRIG"])

    def test_turn_ranks_on_the_projection_in_practice_not_just_in_the_tuple(self):
        rows = [self._row("LOWNOW", total=1.0, trigger_total=8.0),
                self._row("HIGHNOW", total=9.0, trigger_total=2.0)]
        self.assertEqual([r["symbol"] for r in screener.rank(rows, "TURN")],
                         ["LOWNOW", "HIGHNOW"])

    def test_a_missing_score_sorts_as_zero_rather_than_crashing(self):
        rows = [self._row("NONE", total=None), self._row("SOME", total=0.5)]
        self.assertEqual([r["symbol"] for r in screener.rank(rows, "LEADER")],
                         ["SOME", "NONE"])

    def test_confluence_breaks_equal_counts_on_setup_fit(self):
        rows = [self._row("DULL", match_count=2, fit=4.0, total=9.0),
                self._row("SHARP", match_count=2, fit=9.0, total=1.0)]
        self.assertEqual([r["symbol"] for r in screener.rank(rows, "CONFLUENCE")],
                         ["SHARP", "DULL"])

    def test_confluence_count_defaults_to_one_when_absent(self):
        rows = [self._row("TWO", match_count=2, fit=1.0),
                self._row("BARE", fit=9.0)]
        self.assertEqual([r["symbol"] for r in screener.rank(rows, "CONFLUENCE")],
                         ["TWO", "BARE"])

    def test_an_absent_count_ties_with_an_explicit_one_not_with_zero(self):
        """The default is 1, not 0: a bare row must tie a single-match row and
        fall through to the fit tiebreak, not sort above it."""
        rows = [self._row("EXPLICIT", match_count=1, fit=1.0, total=1.0),
                self._row("BARE", fit=9.0, total=9.0)]
        self.assertEqual([r["symbol"] for r in screener.rank(rows, "CONFLUENCE")],
                         ["BARE", "EXPLICIT"])

    def test_match_count_is_ignored_outside_confluence(self):
        """The sibling arm of the CONFLUENCE branch: count must not leak into
        a single-setup table, where every row matched exactly one setup."""
        rows = [self._row("MANY", match_count=3, total=1.0),
                self._row("BETTER", match_count=1, total=9.0)]
        self.assertEqual([r["symbol"] for r in screener.rank(rows, "LEADER")],
                         ["BETTER", "MANY"])

    def test_setup_fit_is_ignored_outside_confluence(self):
        rows = [self._row("FITTER", fit=10.0, total=1.0),
                self._row("SCORER", fit=1.0, total=9.0)]
        self.assertEqual([r["symbol"] for r in screener.rank(rows, "LEADER")],
                         ["SCORER", "FITTER"])

    def test_unmeasurable_relative_strength_sorts_below_even_a_negative_one(self):
        rows = [self._row("BLANK", rs_3m=None), self._row("WEAK", rs_3m=-50.0)]
        self.assertEqual([r["symbol"] for r in screener.rank(rows, "LEADER")],
                         ["WEAK", "BLANK"])

    def test_a_row_with_no_veto_key_is_treated_as_clean(self):
        clean = self._row("CLEAN")
        del clean["vetoed"]
        rows = [self._row("VETOED", vetoed=True, total=10.0), clean]
        self.assertEqual([r["symbol"] for r in screener.rank(rows, "LEADER")],
                         ["CLEAN", "VETOED"])

    def test_veto_outranks_the_trigger_score_too(self):
        rows = [self._row("VETOED", vetoed=True, trigger_total=10.0),
                self._row("CLEAN", trigger_total=0.1)]
        self.assertEqual([r["symbol"] for r in screener.rank(rows, "COILED")],
                         ["CLEAN", "VETOED"])

    def test_ranking_does_not_mutate_the_input_order(self):
        rows = [self._row("B", total=1.0), self._row("A", total=9.0)]
        screener.rank(rows, "LEADER")
        self.assertEqual([r["symbol"] for r in rows], ["B", "A"])


if __name__ == "__main__":
    unittest.main()
