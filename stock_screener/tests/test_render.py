import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import screener


def row(sym="TCS", **over):
    r = {"symbol": sym, "sector": "Information Technology", "price": 3200.0,
         "fit": 8.4, "total": 6.9, "trigger_total": 7.4, "trigger_price": 3300.0,
         "stop": 3100.0, "rr": 2.1, "rs_1m": 3.2, "rs_3m": 11.5,
         "vetoed": False, "action": "BUY HALF", "match_count": 1,
         "evidence": {"vol_mult": 2.4, "pct_above_base": 1.8, "base_bars": 22,
                      "tightness": 6.0, "volume_light": False,
                      "contraction": 0.55, "pos_in_base": 0.82, "dryup": 0.78,
                      "pct_from_high": 3.1, "rs_1m": 3.2, "rs_3m": 11.5,
                      "full_stack": True, "dist_to_ma_pct": 1.4, "rsi": 51.0,
                      "close_position": 0.74, "retrace_pct": 17.1,
                      "retrace_of_52w_range_pct": 33.0, "bars_since_cross": 12,
                      "macd_hist": 0.4, "sma200_rising": True,
                      "vol_expansion": 1.2, "count": 2, "label": "COILED+LEADER",
                      "mean_fit": 8.0, "matched": ["COILED", "LEADER"]}}
    r.update(over)
    return r


class TestColumns(unittest.TestCase):
    def test_every_setup_has_exactly_two_evidence_columns(self):
        for name in list(screener.setups.SETUPS) + ["CONFLUENCE"]:
            self.assertIn(name, screener.EVIDENCE_COLUMNS)
            self.assertEqual(len(screener.EVIDENCE_COLUMNS[name]), 2, name)

    def test_headers_are_full_words_not_abbreviations(self):
        banned = ("Rel.", " RS ", "Vol.", "Str.", "Mkt")
        for name in list(screener.setups.SETUPS) + ["CONFLUENCE"]:
            for header, _ in screener.EVIDENCE_COLUMNS[name]:
                for b in banned:
                    self.assertNotIn(b, header, f"{name}: {header}")

    def test_evidence_formatters_render_without_error(self):
        for name in list(screener.setups.SETUPS) + ["CONFLUENCE"]:
            for _, fmt in screener.EVIDENCE_COLUMNS[name]:
                self.assertIsInstance(fmt(row()), str)


class TestTable(unittest.TestCase):
    def test_table_includes_sector_and_catalyst_neutral_header(self):
        out = screener.render_table([row()], "LEADER", shown=1, total=1)
        self.assertIn("Sector", out)
        self.assertIn("Score Now (catalyst-neutral)", out)
        self.assertIn("Information Technology", out)

    def test_truncation_is_announced(self):
        out = screener.render_table([row()], "LEADER", shown=15, total=41)
        self.assertIn("showing top 15 of 41", out)

    def test_no_truncation_notice_when_all_shown(self):
        out = screener.render_table([row()], "LEADER", shown=3, total=3)
        self.assertNotIn("showing top", out)

    def test_vetoed_row_is_marked(self):
        out = screener.render_table([row(vetoed=True, rr=0.8, action="ALERT")],
                                    "LEADER", shown=1, total=1)
        self.assertIn("*", out)

    def test_volume_light_breakout_is_flagged(self):
        ev = dict(row()["evidence"], volume_light=True, vol_mult=1.7)
        out = screener.render_table([row(evidence=ev)], "BREAKOUT", shown=1, total=1)
        self.assertIn("light", out.lower())

    def test_key_declares_units_and_catalyst_neutrality(self):
        k = screener.render_key("LEADER")
        self.assertIn("percentage points", k)
        self.assertIn("catalyst", k.lower())
        self.assertIn("1.5", k)   # the ATR multiple behind the stop


class TestFunnel(unittest.TestCase):
    """merge_funnel adds the per-symbol counters up; funnel_stages turns
    first-failure counts into a reached/failed funnel."""

    def diag(self, setup, label, step):
        return {"diag": {setup: {label: (step, 1)}}}

    def test_counts_for_the_same_condition_are_added_across_symbols(self):
        rows = [self.diag("LEADER", "an RSI between 50 and 88", 7)
                for _ in range(3)]
        self.assertEqual(screener.merge_funnel(rows, "LEADER"),
                         {"an RSI between 50 and 88": (7, 3)})

    def test_only_the_requested_setup_is_counted(self):
        rows = [self.diag("LEADER", "an RSI", 7), self.diag("TURN", "a cross", 1)]
        self.assertEqual(screener.merge_funnel(rows, "TURN"), {"a cross": (1, 1)})

    def test_rows_without_a_funnel_are_skipped_rather_than_raising(self):
        """A row from an older payload, or an illiquid name, has nothing to add.
        merge_funnel walks every row, so it must tolerate both shapes."""
        rows = [{}, {"diag": None}, {"diag": {}},
                self.diag("LEADER", "an RSI", 7)]
        self.assertEqual(screener.merge_funnel(rows, "LEADER"), {"an RSI": (7, 1)})

    def test_reached_is_the_screened_count_less_everyone_who_fell_earlier(self):
        gates = {"second": (2, 30), "first": (1, 70), "third": (3, 100)}
        self.assertEqual(screener.funnel_stages(gates, 400),
                         [("first", 400, 70), ("second", 330, 30),
                          ("third", 300, 100)])

    def test_stages_are_ordered_by_the_predicate_not_by_size(self):
        """The step number decides, so a late condition that rejected the most
        does not jump to the front and misdescribe the funnel."""
        gates = {"late but huge": (9, 300), "early and small": (1, 4)}
        self.assertEqual([s[0] for s in screener.funnel_stages(gates, 400)],
                         ["early and small", "late but huge"])

    def test_an_empty_funnel_is_an_empty_list_not_a_crash(self):
        self.assertEqual(screener.funnel_stages({}, 400), [])


class TestBreadthAndEmpty(unittest.TestCase):
    def test_breadth_mentions_counts_and_sector_concentration(self):
        counts = {"COILED": 22, "BREAKOUT": 9, "LEADER": 41,
                  "PULLBACK": 18, "TURN": 6, "CONFLUENCE": 11}
        rows = ([row("F%d" % i, sector="Financial Services") for i in range(6)]
                + [row("O%d" % i, sector="Information Technology")
                   for i in range(3)])
        out = screener.render_breadth(counts, {"BREAKOUT": rows})
        self.assertIn("41", out)
        self.assertIn("Financial Services", out)

    def test_empty_result_names_the_binding_condition(self):
        out = screener.render_empty(
            "BREAKOUT", [("a base of at least 12 bars", 20, 2),
                         ("volume at least 1.5x the 20-day average", 18, 18)],
            screened=20)
        self.assertIn("BREAKOUT", out)
        self.assertIn("18", out)
        self.assertIn("volume at least 1.5x the 20-day average", out)
        self.assertNotIn("top pick", out.lower())

    def test_handoff_is_paste_ready(self):
        out = screener.render_handoff(["TITAN", "BEL"])
        self.assertIn("watchlist.py", out)
        self.assertIn('"TITAN,BEL"', out)

    def test_handoff_is_empty_when_nothing_qualified(self):
        self.assertEqual(screener.render_handoff([]), "")


class TestNumberFormatter(unittest.TestCase):
    def test_default_format_is_two_decimals(self):
        self.assertEqual(screener._n(3.14159), "3.14")

    def test_default_dash_marks_an_unmeasurable_value(self):
        self.assertEqual(screener._n(None), "-")

    def test_an_explicit_dash_overrides_the_default(self):
        self.assertEqual(screener._n(None, "{:.1f}", "none"), "none")

    def test_zero_formats_as_zero_and_is_not_treated_as_missing(self):
        """0.0 is falsy; the guard must test None, not truthiness."""
        self.assertEqual(screener._n(0.0), "0.00")


class TestEvidenceColumnValues(unittest.TestCase):
    """Exact rendered text per setup. isinstance(str) alone cannot fail."""

    def _cells(self, setup, r=None):
        return [fmt(r or row()) for _, fmt in screener.EVIDENCE_COLUMNS[setup]]

    def test_coiled_shows_contraction_and_position_as_a_percentage(self):
        self.assertEqual(self._cells("COILED"), ["0.55", "82%"])

    def test_breakout_shows_the_volume_multiple_and_extension(self):
        self.assertEqual(self._cells("BREAKOUT"), ["2.40x", "1.8%"])

    def test_breakout_appends_light_only_when_volume_is_light(self):
        ev = dict(row()["evidence"], volume_light=True, vol_mult=1.7)
        self.assertEqual(self._cells("BREAKOUT", row(evidence=ev))[0], "1.70x light")

    def test_leader_shows_distance_from_high_and_signed_relative_strength(self):
        self.assertEqual(self._cells("LEADER"), ["3.1%", "+3.2"])

    def test_leader_relative_strength_reads_from_the_row_not_the_evidence(self):
        """rs_1m on the row is the scan's value; evidence may not carry one."""
        r = row(rs_1m=-4.25)
        r["evidence"] = dict(r["evidence"], rs_1m=99.0)
        self.assertEqual(self._cells("LEADER", r)[1], "-4.2")

    def test_pullback_shows_the_reversal_close_and_the_swing_retracement(self):
        """0.74 renders as a whole-number percentage, the swing retracement to
        one decimal. Neither is the 52-week range share, which is 33.0 in this
        fixture and must not appear."""
        self.assertEqual(self._cells("PULLBACK"), ["74%", "17.1%"])

    def test_turn_shows_bars_since_cross_and_a_signed_histogram(self):
        self.assertEqual(self._cells("TURN"), ["12", "+0.40"])

    def test_confluence_shows_the_label_and_the_mean_fit(self):
        self.assertEqual(self._cells("CONFLUENCE"), ["COILED+LEADER", "8.00"])

    def test_a_blank_evidence_value_renders_as_a_dash_not_a_crash(self):
        r = row(rs_1m=None)
        r["evidence"] = dict(r["evidence"], macd_hist=None, rsi=None,
                             close_position=None, retrace_pct=None)
        self.assertEqual(self._cells("LEADER", r)[1], "-")
        self.assertEqual(self._cells("TURN", r)[1], "-")
        self.assertEqual(self._cells("PULLBACK", r), ["-", "-"])


class TestTableStructure(unittest.TestCase):
    def _cells_of(self, out, line_index):
        return [c.strip() for c in out.splitlines()[line_index].strip("|").split("|")]

    def test_every_data_row_has_one_cell_per_header(self):
        """A formatter added without a header silently shifts every later column."""
        for setup in list(screener.setups.SETUPS) + ["CONFLUENCE"]:
            out = screener.render_table([row(), row("BEL")], setup, shown=2, total=2)
            headers = self._cells_of(out, 1)
            self.assertEqual(len(headers),
                             len(screener.BASE_COLUMNS)
                             + len(screener.EVIDENCE_COLUMNS[setup])
                             + len(screener.TAIL_COLUMNS), setup)
            for i in (3, 4):
                self.assertEqual(len(self._cells_of(out, i)), len(headers), setup)

    def test_rows_are_numbered_from_one_in_the_order_given(self):
        out = screener.render_table([row("AAA"), row("BBB"), row("CCC")],
                                    "LEADER", shown=3, total=3)
        self.assertEqual([self._cells_of(out, i)[0] for i in (3, 4, 5)],
                         ["1", "2", "3"])
        self.assertEqual([self._cells_of(out, i)[1] for i in (3, 4, 5)],
                         ["AAA", "BBB", "CCC"])

    def test_a_clean_row_carries_no_veto_mark(self):
        """Sibling arm of test_vetoed_row_is_marked."""
        out = screener.render_table([row(vetoed=False)], "LEADER", shown=1, total=1)
        self.assertNotIn("*", out)

    def test_the_veto_mark_sits_on_the_score_now_cell(self):
        out = screener.render_table([row(vetoed=True)], "LEADER", shown=1, total=1)
        self.assertEqual(self._cells_of(out, 3)[5], "6.90*")

    def test_one_more_than_shown_still_announces_the_truncation(self):
        out = screener.render_table([row()], "LEADER", shown=20, total=21)
        self.assertIn("showing top 20 of 21", out)

    def test_exactly_shown_is_not_announced(self):
        out = screener.render_table([row()], "LEADER", shown=20, total=20)
        self.assertNotIn("showing top", out)

    def test_a_name_already_through_the_gate_reads_none_not_a_dash(self):
        out = screener.render_table([row(trigger_total=None, trigger_price=None)],
                                    "LEADER", shown=1, total=1)
        cells = self._cells_of(out, 3)
        self.assertEqual(cells[6], "none")
        self.assertEqual(cells[-3], "none")

    def test_unmeasurable_ratio_and_stop_read_as_dashes(self):
        out = screener.render_table([row(rr=None, stop=None, rs_3m=None)],
                                    "LEADER", shown=1, total=1)
        cells = self._cells_of(out, 3)
        self.assertEqual(cells[7], "-")
        self.assertEqual(cells[8], "-")
        self.assertEqual(cells[-2], "-")

    def test_ratio_and_relative_strength_carry_their_units_and_signs(self):
        out = screener.render_table([row()], "LEADER", shown=1, total=1)
        cells = self._cells_of(out, 3)
        self.assertEqual(cells[7], "2.10:1")
        self.assertEqual(cells[8], "+11.5")

    def test_the_action_is_the_last_column(self):
        out = screener.render_table([row(action="LATENT")], "LEADER",
                                    shown=1, total=1)
        self.assertEqual(self._cells_of(out, 3)[-1], "LATENT")

    def test_an_empty_row_list_still_renders_the_header(self):
        out = screener.render_table([], "LEADER", shown=0, total=0)
        self.assertIn("Score Now (catalyst-neutral)", out)


class TestKey(unittest.TestCase):
    def test_the_key_defines_every_action_the_table_can_print(self):
        k = screener.render_key("COILED")
        for act in ("BUY NOW", "BUY HALF", "ALERT", "LATENT", "WATCH"):
            self.assertIn(act, k)

    def test_the_key_warns_that_fit_is_not_comparable_across_setups(self):
        k = screener.render_key("TURN")
        self.assertIn("not be compared across tables", k)

    def test_the_key_explains_the_none_in_the_trigger_column(self):
        self.assertIn("`none`", screener.render_key("LEADER"))

    def test_the_key_defines_risk_reward_against_the_same_stop_the_table_prints(self):
        """The Stop column and the Risk:Reward denominator must be the same
        1.5x multiple, or the ratio measures a stop nobody is using."""
        self.assertIn("divided by risk to a 1.5x Average True Range stop",
                      screener.render_key("LEADER"))


class TestHeader(unittest.TestCase):
    COUNTS = {"COILED": 3, "BREAKOUT": 1, "LEADER": 7, "PULLBACK": 2, "TURN": 0,
              "CONFLUENCE": 4}

    def _header(self, **over):
        kw = {"scan_date": "2026-08-02", "closed_bar": "2026-08-01",
              "universe_name": "nifty500.txt", "n_universe": 500,
              "strict": False, "n_scored": 480, "failed": [], "n_illiquid": 12,
              "counts": self.COUNTS}
        kw.update(over)
        return screener.render_header(**kw)

    def test_the_header_states_the_scan_and_bar_dates_and_the_universe(self):
        out = self._header()
        self.assertIn("2026-08-02", out)
        self.assertIn("2026-08-01", out)
        self.assertIn("nifty500.txt (500)", out)
        self.assertIn("scored 480", out)
        self.assertIn("below turnover floor 12", out)

    def test_loosened_mode_is_named(self):
        self.assertIn("loosened", self._header(strict=False))

    def test_strict_mode_is_named(self):
        out = self._header(strict=True)
        self.assertIn("strict", out)
        self.assertNotIn("loosened", out)

    def test_no_failures_prints_no_parenthetical(self):
        out = self._header(failed=[])
        self.assertIn("FAILED 0", out)
        self.assertNotIn("(", out.split("\n")[1])

    def test_failures_are_named_not_just_counted(self):
        out = self._header(failed=[("TATAMOTORS", "404"), ("FOO", "boom")])
        self.assertIn("FAILED 2 (TATAMOTORS, FOO)", out)

    def test_six_failures_are_all_named_without_an_ellipsis(self):
        failed = [(f"S{i}", "x") for i in range(6)]
        out = self._header(failed=failed)
        self.assertIn("S5", out)
        self.assertNotIn("...", out)

    def test_a_seventh_failure_is_elided(self):
        failed = [(f"S{i}", "x") for i in range(7)]
        out = self._header(failed=failed)
        self.assertIn("FAILED 7", out)
        self.assertIn("S5...", out)
        self.assertNotIn("S6", out)

    def test_match_counts_are_listed_in_life_cycle_order(self):
        line = self._header().splitlines()[2]
        self.assertEqual(
            line, "matches  COILED 3 · BREAKOUT 1 · LEADER 7 · PULLBACK 2 · "
                  "TURN 0 · CONFLUENCE 4")

    def test_a_setup_absent_from_the_counts_reads_zero(self):
        line = self._header(counts={"LEADER": 7}).splitlines()[2]
        self.assertIn("COILED 0", line)
        self.assertIn("LEADER 7", line)


class TestBreadth(unittest.TestCase):
    def test_leaders_far_outnumbering_breakouts_reads_as_extended(self):
        out = screener.render_breadth({"LEADER": 19, "BREAKOUT": 9, "COILED": 1}, {})
        self.assertIn("already-extended", out)

    def test_leaders_at_exactly_twice_breakouts_is_not_extended(self):
        """Boundary: the test is strictly greater than, not greater-or-equal."""
        out = screener.render_breadth({"LEADER": 18, "BREAKOUT": 9, "COILED": 1}, {})
        self.assertNotIn("already-extended", out)
        self.assertIn("mixed tape", out)

    def test_coiled_bases_dominating_reads_as_compressing(self):
        out = screener.render_breadth({"LEADER": 5, "BREAKOUT": 20, "COILED": 30}, {})
        self.assertIn("compressing rather than trending", out)

    def test_coiled_at_exactly_twice_leaders_is_not_compressing(self):
        out = screener.render_breadth({"LEADER": 5, "BREAKOUT": 20, "COILED": 10}, {})
        self.assertNotIn("compressing", out)
        self.assertIn("mixed tape", out)

    def test_one_coiled_base_over_twice_the_leaders_is_compressing(self):
        """Boundary partner: pins the multiple at 2, not 3."""
        out = screener.render_breadth({"LEADER": 5, "BREAKOUT": 20, "COILED": 11}, {})
        self.assertIn("compressing rather than trending", out)

    def test_an_even_tape_reads_as_mixed(self):
        out = screener.render_breadth({"LEADER": 5, "BREAKOUT": 5, "COILED": 5}, {})
        self.assertIn("mixed tape", out)

    def test_missing_counts_default_to_zero_without_dividing_by_zero(self):
        out = screener.render_breadth({}, {})
        self.assertIn("0 breakouts, 0 coiled, 0 leaders", out)

    def test_a_scattered_sector_spread_makes_no_sector_claim(self):
        rows = [row(str(i), sector=f"S{i}") for i in range(6)]
        out = screener.render_breadth({"LEADER": 6}, {"LEADER": rows})
        self.assertNotIn("sector call", out)

    def test_half_the_names_in_one_sector_is_a_sector_call(self):
        rows = ([row(f"F{i}", sector="Financial Services") for i in range(5)]
                + [row(f"O{i}", sector=f"Other {i}") for i in range(5)])
        out = screener.render_breadth({"LEADER": 10}, {"LEADER": rows})
        self.assertIn("5 of 10 LEADER names are Financial Services", out)

    def test_just_under_half_is_not_a_sector_call(self):
        """The share boundary, one name apart: 5 of 10 is a claim (above), 5 of
        11 is not. Integer arithmetic, so no float decides it."""
        rows = ([row(f"F{i}", sector="Financial Services") for i in range(5)]
                + [row(f"O{i}", sector=f"Other {i}") for i in range(6)])
        out = screener.render_breadth({"LEADER": 11}, {"LEADER": rows})
        self.assertNotIn("sector call", out)

    def test_a_small_unanimous_plurality_is_not_concentration(self):
        """The absolute floor, both arms. Four names all in one sector is 100%
        of a match set too small to say anything about the market -- the old
        `n >= max(2, len(rows) // 2)` fired on 2 of 3 and manufactured market
        structure out of a handful of rows. Five is a claim."""
        four = [row(f"F{i}", sector="Metals") for i in range(4)]
        self.assertNotIn("sector call",
                         screener.render_breadth({"LEADER": 4}, {"LEADER": four}))
        five = [row(f"F{i}", sector="Metals") for i in range(5)]
        self.assertIn("5 of 5 LEADER names are Metals",
                      screener.render_breadth({"LEADER": 5}, {"LEADER": five}))

    def test_a_majority_of_too_few_names_is_not_concentration(self):
        """3 of 5 is 60% and still not a finding: the absolute floor and the
        share are separate tests, and this case can only be rejected by the
        count. Dropping `n >= SECTOR_MIN_NAMES` makes it print."""
        rows = ([row(f"F{i}", sector="Metals") for i in range(3)]
                + [row(f"O{i}", sector=f"Other {i}") for i in range(2)])
        out = screener.render_breadth({"LEADER": 5}, {"LEADER": rows})
        self.assertNotIn("sector call", out)

    def test_a_setup_that_matched_nothing_is_skipped_not_crashed_on(self):
        out = screener.render_breadth({"LEADER": 0}, {"LEADER": []})
        self.assertNotIn("sector call", out)

    def test_a_two_of_three_plurality_is_not_concentration(self):
        rows = [row("A", sector="Banks"), row("B", sector="Banks"),
                row("C", sector="Metals")]
        out = screener.render_breadth({"LEADER": 3}, {"LEADER": rows})
        self.assertNotIn("sector call", out)

    def test_every_setup_is_examined_for_concentration(self):
        rows = [row(f"F{i}", sector="Metals") for i in range(5)]
        out = screener.render_breadth({"LEADER": 5, "COILED": 5},
                                      {"LEADER": rows, "COILED": rows})
        self.assertIn("5 of 5 LEADER names are Metals", out)
        self.assertIn("5 of 5 COILED names are Metals", out)

    def test_a_sector_filtered_run_makes_no_sector_claim(self):
        """Both arms of the suppression. The user passed --sector, so the sector
        is their premise, not the screen's finding."""
        rows = [row(f"F{i}", sector="Financial Services") for i in range(6)]
        self.assertIn("sector call",
                      screener.render_breadth({"LEADER": 6}, {"LEADER": rows},
                                              sector_filtered=False))
        self.assertNotIn("sector call",
                         screener.render_breadth({"LEADER": 6}, {"LEADER": rows},
                                                 sector_filtered=True))

    def test_a_sector_filtered_run_still_reads_the_market_stage(self):
        """Suppression is of the sector sentence only -- the counts sentence is
        as true under a filter as without one."""
        rows = [row(f"F{i}", sector="Financial Services") for i in range(6)]
        out = screener.render_breadth({"LEADER": 19, "BREAKOUT": 9, "COILED": 1},
                                      {"LEADER": rows}, sector_filtered=True)
        self.assertIn("already-extended", out)

    def test_sector_filtering_defaults_to_off(self):
        """Omitting the argument must not silently suppress the observation."""
        rows = [row(f"F{i}", sector="Financial Services") for i in range(6)]
        self.assertIn("sector call",
                      screener.render_breadth({"LEADER": 6}, {"LEADER": rows}))


class TestEmptyAndHandoff(unittest.TestCase):
    #: A COILED funnel over 400 screened names: 345 fall at the base, 52 of the
    #: remaining 55 at the contraction rule, and the last 3 at the dry-up.
    STAGES = [("a base of at least 16 bars", 400, 345),
              ("at least 2 of 3 windows narrower than the last", 55, 52),
              ("volume dried up below 1.00x its own average", 3, 3)]

    def test_every_rejection_stage_is_reported(self):
        out = screener.render_empty("COILED", self.STAGES, screened=400)
        self.assertIn("400 reached a base of at least 16 bars, 345 failed", out)
        self.assertIn("55 reached at least 2 of 3 windows narrower than the "
                      "last, 52 failed", out)
        self.assertIn("3 reached volume dried up below 1.00x its own average, "
                      "3 failed", out)

    def test_the_binding_condition_is_named_outright(self):
        """Spec 5.4. The stage that rejected most is called out by name, so the
        reader is not left to compare eight numbers themselves."""
        out = screener.render_empty("COILED", self.STAGES, screened=400)
        self.assertIn("The binding condition is a base of at least 16 bars — "
                      "it rejected 345 of the 400 names that reached it", out)

    def test_the_stages_are_reported_in_the_order_the_setup_tests_them(self):
        """A funnel read out of order is not a funnel: here the LAST stage has
        the smallest count, so sorting by size would reverse the story."""
        out = screener.render_empty("COILED", self.STAGES, screened=400)
        self.assertLess(out.index("a base of at least 16 bars, 345"),
                        out.index("narrower than the last, 52"))
        self.assertLess(out.index("narrower than the last, 52"),
                        out.index("dried up below 1.00x its own average, 3"))

    def test_a_stage_nothing_reached_is_not_reported(self):
        """Once the funnel empties, later conditions were never tested at all --
        printing "0 reached X, 0 failed" for each would pad the finding with
        rows that say nothing."""
        stages = self.STAGES + [("a rising 200-day average", 0, 0)]
        out = screener.render_empty("COILED", stages, screened=400)
        self.assertNotIn("a rising 200-day average", out)

    def test_the_empty_result_is_framed_as_a_finding(self):
        out = screener.render_empty("TURN", self.STAGES[:1], screened=400)
        self.assertIn("that is the finding", out)
        self.assertIn("No names matched", out)
        self.assertIn("400 names were screened", out)

    def test_no_funnel_at_all_still_renders_the_screened_count(self):
        """CONFLUENCE has no predicate of its own, so it has no funnel."""
        out = screener.render_empty("CONFLUENCE", [], screened=400)
        self.assertIn("### CONFLUENCE", out)
        self.assertIn("400 names were screened", out)
        self.assertIn("that is the finding", out)
        self.assertNotIn("binding condition", out)

    def test_a_funnel_that_rejected_nobody_names_no_binding_condition(self):
        """Reachable when a setup matched nothing because every name fell at a
        stage that is not recorded -- never claim a condition did the rejecting
        when none of them did."""
        out = screener.render_empty("LEADER", [("a base", 400, 0)], screened=400)
        self.assertIn("400 reached a base, 0 failed", out)
        self.assertNotIn("binding condition", out)

    def test_a_single_symbol_needs_no_separator(self):
        self.assertIn('"TITAN"', screener.render_handoff(["TITAN"]))

    def test_the_handoff_is_a_fenced_block_for_pasting(self):
        out = screener.render_handoff(["TITAN", "BEL", "CDSL"])
        self.assertEqual(out.count("```"), 2, "the fence must open AND close")
        self.assertIn('"TITAN,BEL,CDSL"', out)

    def test_the_handoff_asks_for_real_catalysts(self):
        self.assertIn("catalyst", screener.render_handoff(["TITAN"]).lower())


if __name__ == "__main__":
    unittest.main()
