import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import screener


class TestParseArgs(unittest.TestCase):
    def test_defaults(self):
        a = screener.parse_args([])
        self.assertEqual(a.setup, "all")
        self.assertEqual(a.top, 15)
        self.assertFalse(a.strict)
        self.assertAlmostEqual(a.min_turnover, 3.0)

    def test_setup_list_and_strict(self):
        a = screener.parse_args(["--setup", "coiled,leader", "--strict"])
        self.assertEqual(a.setup, "coiled,leader")
        self.assertTrue(a.strict)

    def test_sector_filter_is_split_on_commas(self):
        a = screener.parse_args(["--sector", "Banks,Information Technology"])
        self.assertEqual(a.sector, "Banks,Information Technology")


class TestResolveSetups(unittest.TestCase):
    def test_all_expands_to_every_setup_plus_confluence(self):
        self.assertEqual(screener.resolve_setups("all"),
                         list(screener.setups.SETUPS) + ["CONFLUENCE"])

    def test_names_are_case_insensitive_and_ordered_canonically(self):
        self.assertEqual(screener.resolve_setups("leader,coiled"), ["COILED", "LEADER"])

    def test_confluence_is_selectable_on_its_own(self):
        self.assertEqual(screener.resolve_setups("confluence"), ["CONFLUENCE"])

    def test_unknown_setup_is_a_hard_error_listing_valid_names(self):
        with self.assertRaises(SystemExit) as ctx:
            screener.resolve_setups("bullflag")
        # The message upper-cases the offending token, so match case-insensitively.
        self.assertIn("bullflag", str(ctx.exception).lower())
        self.assertIn("COILED", str(ctx.exception))

    def test_duplicates_are_collapsed(self):
        self.assertEqual(screener.resolve_setups("leader,leader"), ["LEADER"])


class TestMainSmoke(unittest.TestCase):
    """Live network. The seeded universe is small, so this stays quick."""

    def test_json_output_is_keyed_by_setup(self):
        import io, json
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = screener.main(["--setup", "leader", "--top", "5", "--json"])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertIn("scan", payload)
        self.assertIn("setups", payload)
        self.assertIn("LEADER", payload["setups"])
        self.assertIn("failed", payload)

    def test_top_above_cap_prints_the_clamp_notice(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            screener.main(["--setup", "leader", "--top", "50"])
        self.assertIn("20", buf.getvalue())


class TestParseArgsRemainingFlags(unittest.TestCase):
    def test_every_other_default_is_pinned_by_an_omitting_call(self):
        a = screener.parse_args([])
        self.assertEqual(a.universe, screener.DEFAULT_UNIVERSE)
        self.assertIsNone(a.sector)
        self.assertEqual(a.workers, 16)
        self.assertFalse(a.json)
        self.assertFalse(a.refresh)

    def test_top_is_parsed_as_an_integer(self):
        a = screener.parse_args(["--top", "7"])
        self.assertEqual(a.top, 7)
        self.assertIsInstance(a.top, int)

    def test_min_turnover_is_a_float_on_its_underscored_destination(self):
        a = screener.parse_args(["--min-turnover", "12.5"])
        self.assertAlmostEqual(a.min_turnover, 12.5)

    def test_universe_and_workers_are_overridable(self):
        a = screener.parse_args(["--universe", "/tmp/u.txt", "--workers", "4"])
        self.assertEqual(a.universe, "/tmp/u.txt")
        self.assertEqual(a.workers, 4)

    def test_json_and_refresh_are_flags_not_values(self):
        a = screener.parse_args(["--json", "--refresh-universe"])
        self.assertTrue(a.json)
        self.assertTrue(a.refresh)

    def test_the_help_text_names_every_selectable_setup(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf), self.assertRaises(SystemExit):
            screener.parse_args(["--help"])
        for name in screener.ALL_SETUPS:
            self.assertIn(name.lower(), buf.getvalue())


class TestResolveSetupsEdges(unittest.TestCase):
    def test_all_is_case_insensitive_and_tolerates_padding(self):
        self.assertEqual(screener.resolve_setups("  ALL "), screener.ALL_SETUPS)

    def test_all_returns_a_copy_that_cannot_corrupt_the_constant(self):
        got = screener.resolve_setups("all")
        got.append("BOGUS")
        self.assertNotIn("BOGUS", screener.ALL_SETUPS)

    def test_padded_names_are_accepted(self):
        self.assertEqual(screener.resolve_setups(" turn , pullback "),
                         ["PULLBACK", "TURN"])

    def test_every_unknown_name_is_listed_not_just_the_first(self):
        with self.assertRaises(SystemExit) as ctx:
            screener.resolve_setups("bullflag,leader,pennant")
        msg = str(ctx.exception).lower()
        self.assertIn("bullflag", msg)
        self.assertIn("pennant", msg)

    def test_an_empty_selection_selects_nothing_rather_than_everything(self):
        self.assertEqual(screener.resolve_setups(""), [])
        self.assertEqual(screener.resolve_setups(" , "), [])


FULL_EVIDENCE = {"pct_from_high": 3.1, "contraction": 0.55, "pos_in_base": 0.82,
                 "vol_mult": 2.4, "pct_above_base": 1.8, "volume_light": False,
                 "dist_to_ma_pct": 1.4, "rsi": 51.0, "bars_since_cross": 12,
                 "macd_hist": 0.4, "label": "COILED+LEADER", "mean_fit": 8.0,
                 "count": 2}


def scan_row(sym, sector="Information Technology", matched=("LEADER",),
             verdict="HALF SIZE", rr=2.0, total=6.5, price=100.0,
             illiquid=False):
    return {"symbol": sym, "sector": sector, "rs": {"1m": 1.0, "3m": 2.0},
            "illiquid": illiquid,
            "matched": {n: {"fit": 8.0, "evidence": dict(FULL_EVIDENCE)}
                        for n in matched},
            "o": {"price": price, "score": {"total": total, "verdict": verdict},
                  "entry_gate": {"rr_at_current_price": rr},
                  "atr": {"daily": 2.0},
                  "last_closed_bar": {"t": "2026-07-31"}}}


class _MainStub:
    """Runs main() end to end with the network replaced. Records what main
    handed the scanner so the CLI-to-scan wiring is checked, not assumed."""

    def __init__(self, rows=None, failed=None, pairs=None, proj=None):
        self.rows = [scan_row("TCS")] if rows is None else rows
        self.failed = failed or []
        self.pairs = pairs or [("TCS", "Information Technology")]
        self.proj = proj
        self.scan_kwargs = None
        self.universe_args = None

    def __enter__(self):
        self.saved = (screener.scan, screener.load_universe,
                      screener.W.score_at_trigger)
        stub = self

        def fake_scan(pairs, strict=False, min_turnover=3.0, workers=16):
            stub.scan_kwargs = {"pairs": pairs, "strict": strict,
                                "min_turnover": min_turnover, "workers": workers}
            return stub.rows, stub.failed

        def fake_universe(path=None, sectors=None):
            stub.universe_args = (path, sectors)
            return stub.pairs

        screener.scan = fake_scan
        screener.load_universe = fake_universe
        screener.W.score_at_trigger = lambda o: stub.proj
        return self

    def __exit__(self, *exc):
        (screener.scan, screener.load_universe,
         screener.W.score_at_trigger) = self.saved
        return False


def run_main(argv, stub):
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with stub, redirect_stdout(buf):
        rc = screener.main(argv)
    return rc, buf.getvalue()


class TestMainWiring(unittest.TestCase):
    def test_cli_options_reach_the_scanner(self):
        stub = _MainStub()
        rc, _ = run_main(["--strict", "--min-turnover", "8.5", "--workers", "3"], stub)
        self.assertEqual(rc, 0)
        self.assertTrue(stub.scan_kwargs["strict"])
        self.assertAlmostEqual(stub.scan_kwargs["min_turnover"], 8.5)
        self.assertEqual(stub.scan_kwargs["workers"], 3)

    def test_no_sector_filter_passes_none_rather_than_an_empty_list(self):
        stub = _MainStub()
        run_main([], stub)
        self.assertIsNone(stub.universe_args[1])

    def test_a_sector_filter_is_split_on_commas_before_it_is_passed_on(self):
        stub = _MainStub()
        run_main(["--sector", "Banks,Information Technology"], stub)
        self.assertEqual(stub.universe_args[1], ["Banks", "Information Technology"])

    def test_an_empty_sector_string_is_no_filter_rather_than_an_empty_one(self):
        """load_universe hard-errors on a filter that matches nothing, so
        `--sector ''` must read as 'unset', not as 'match the empty string'."""
        stub = _MainStub()
        run_main(["--sector", ""], stub)
        self.assertIsNone(stub.universe_args[1])

    def test_the_universe_path_is_passed_through(self):
        stub = _MainStub()
        run_main(["--universe", "/tmp/mine.txt"], stub)
        self.assertEqual(stub.universe_args[0], "/tmp/mine.txt")

    def test_an_omitted_argv_falls_back_to_the_process_arguments(self):
        stub = _MainStub()
        saved = sys.argv
        sys.argv = ["screener.py", "--setup", "leader", "--workers", "9"]
        try:
            with stub:
                import io
                from contextlib import redirect_stdout
                with redirect_stdout(io.StringIO()):
                    screener.main()
        finally:
            sys.argv = saved
        self.assertEqual(stub.scan_kwargs["workers"], 9)


class TestMainRefresh(unittest.TestCase):
    def test_refresh_returns_the_refresher_code_and_never_scans(self):
        import universe
        stub = _MainStub()
        saved = universe.refresh_universe
        universe.refresh_universe = lambda path=None: 7
        try:
            rc, _ = run_main(["--refresh-universe", "--universe", "/tmp/u.txt"], stub)
        finally:
            universe.refresh_universe = saved
        self.assertEqual(rc, 7)
        self.assertIsNone(stub.scan_kwargs)


class TestMainJson(unittest.TestCase):
    def _payload(self, argv, stub):
        import json as _json
        rc, out = run_main(argv, stub)
        self.assertEqual(rc, 0)
        return _json.loads(out)

    def test_the_scan_block_describes_the_run(self):
        stub = _MainStub(pairs=[("A", "X"), ("B", "Y"), ("C", "Z")],
                         rows=[scan_row("A"), scan_row("B")],
                         failed=[("C", "404")])
        p = self._payload(["--json", "--strict", "--top", "4"], stub)
        # Three names offered, two scored: the two numbers must not be the same
        # field, or a failure-heavy scan looks like a smaller universe.
        self.assertEqual(p["scan"]["universe_size"], 3)
        self.assertEqual(p["scan"]["scored"], 2)
        self.assertTrue(p["scan"]["strict"])
        self.assertEqual(p["scan"]["top"], 4)
        self.assertEqual(p["scan"]["last_closed_bar"], "2026-07-31")
        self.assertEqual(p["scan"]["counts"]["LEADER"], 2)
        self.assertEqual(p["scan"]["counts"]["COILED"], 0)

    def test_only_the_chosen_setups_are_emitted(self):
        stub = _MainStub(rows=[scan_row("A", matched=("LEADER", "TURN"))])
        p = self._payload(["--json", "--setup", "turn"], stub)
        self.assertEqual(list(p["setups"]), ["TURN"])

    def test_the_counts_cover_the_whole_market_not_only_the_chosen_setups(self):
        """Narrowing --setup narrows the tables, never the breadth tally."""
        stub = _MainStub(rows=[scan_row("A", matched=("LEADER", "TURN"))])
        p = self._payload(["--json", "--setup", "turn"], stub)
        self.assertEqual(p["scan"]["counts"]["LEADER"], 1)
        self.assertEqual(sorted(p["scan"]["counts"]), sorted(screener.ALL_SETUPS))

    def test_the_raw_engine_result_is_not_serialised(self):
        """`o` is the whole analyze payload; emitting it would bury the row."""
        stub = _MainStub()
        p = self._payload(["--json"], stub)
        self.assertNotIn("o", p["setups"]["LEADER"][0])
        self.assertIn("symbol", p["setups"]["LEADER"][0])

    def test_the_top_limit_keeps_the_best_ranked_names_not_the_first_scanned(self):
        rows = [scan_row(f"S{i}", total=float(i)) for i in range(6)]
        p = self._payload(["--json", "--top", "2"], _MainStub(rows=rows))
        self.assertEqual([r["symbol"] for r in p["setups"]["LEADER"]], ["S5", "S4"])

    def test_the_top_cap_applies_to_json_as_well(self):
        rows = [scan_row(f"S{i}", total=float(i)) for i in range(25)]
        p = self._payload(["--json", "--top", "50"], _MainStub(rows=rows))
        self.assertEqual(len(p["setups"]["LEADER"]), screener.MAX_TOP)
        self.assertEqual(p["scan"]["top"], screener.MAX_TOP)

    def test_failures_are_reported_as_objects_not_dropped(self):
        stub = _MainStub(failed=[("TATAMOTORS", "404 not found")])
        p = self._payload(["--json"], stub)
        self.assertEqual(p["failed"],
                         [{"symbol": "TATAMOTORS", "reason": "404 not found"}])

    def test_an_all_failed_scan_reports_no_closing_bar(self):
        stub = _MainStub(rows=[], failed=[("A", "x")])
        p = self._payload(["--json"], stub)
        self.assertEqual(p["scan"]["last_closed_bar"], "n/a")
        self.assertEqual(p["scan"]["scored"], 0)

    def test_the_universe_is_reported_by_basename_not_full_path(self):
        stub = _MainStub()
        p = self._payload(["--json", "--universe", "/tmp/deep/my500.txt"], stub)
        self.assertEqual(p["scan"]["universe"], "my500.txt")

    def test_json_suppresses_the_human_report_entirely(self):
        stub = _MainStub()
        _, out = run_main(["--json", "--top", "50"], stub)
        self.assertNotIn("Mechanical framework output", out)
        self.assertNotIn("NOTE: --top clamped", out)


class TestHeaderIlliquidCount(unittest.TestCase):
    """`below turnover floor N` must be the liquidity-gate count.

    A real 500-name scan has a handful of gate rejections and several hundred
    liquid names that simply match nothing. Reporting the second number under
    the first heading is the header telling the reader a falsehood about the
    scan, which is the header's only job to avoid. The stub below is that
    500-name scan in miniature: one thin name, three quiet ones, one hit.
    """
    #: 1 gated + 3 liquid-but-quiet + 1 match. The two candidate numbers are
    #: 1 and 4, and neither is a prefix of the other in the rendered line.
    ROWS = ([scan_row("THIN", matched=(), illiquid=True)]
            + [scan_row("Q%d" % i, matched=()) for i in range(3)]
            + [scan_row("HIT", matched=("LEADER",))])

    def _floor(self, out):
        line = [ln for ln in out.splitlines() if "below turnover floor" in ln]
        self.assertEqual(len(line), 1, "exactly one header line reports the floor")
        return int(line[0].rsplit("below turnover floor", 1)[1].strip())

    def test_the_floor_count_is_the_gate_count_not_the_no_match_count(self):
        _, out = run_main(["--setup", "leader"], _MainStub(rows=self.ROWS))
        self.assertEqual(self._floor(out), 1)

    def test_liquid_names_that_matched_nothing_are_not_counted(self):
        """Same rows minus the one gated name: the floor count must fall to
        zero, even though four rows still have an empty `matched`."""
        rows = [r for r in self.ROWS if not r["illiquid"]]
        _, out = run_main(["--setup", "leader"], _MainStub(rows=rows))
        self.assertEqual(self._floor(out), 0)

    def test_a_matching_name_is_not_counted_either(self):
        _, out = run_main(["--setup", "leader"],
                          _MainStub(rows=[scan_row("HIT", matched=("LEADER",))]))
        self.assertEqual(self._floor(out), 0)

    def test_every_gated_name_is_counted(self):
        """The accept side of the same guard: raise the gate count and the
        header must follow it, so the fix is not a hardcoded small number."""
        rows = [scan_row("T%d" % i, matched=(), illiquid=True) for i in range(4)]
        _, out = run_main(["--setup", "leader"], _MainStub(rows=rows))
        self.assertEqual(self._floor(out), 4)

    def test_the_empty_finding_counts_only_the_names_actually_screened(self):
        """The screened count sits under a setup with no hits. It must exclude
        the gated names, or it claims a name passed a gate that rejected it."""
        _, out = run_main(["--setup", "coiled"], _MainStub(rows=self.ROWS))
        self.assertIn("4 names were screened", out)
        self.assertNotIn("5 names were screened", out)


class TestEmptyScreenNamesTheRejectingCondition(unittest.TestCase):
    """Spec 5.4, end to end through main().

    `{"the liquidity and scoring pass": len(rows)}` named no condition at all,
    which is how a BREAKOUT predicate that could not match on any day reported
    itself as a market finding for the life of the project. The funnel below is
    the shape a real scan produces: every name counted at the first condition
    it failed.
    """

    def rows(self, *funnels):
        """One scanned row per funnel, none of them matching anything."""
        out = []
        for i, f in enumerate(funnels):
            r = scan_row("N%d" % i, matched=())
            r["diag"] = {"BREAKOUT": f}
            out.append(r)
        return out

    BASE = {"a base of at least 12 bars": (1, 1)}
    HIGH = {"a close above the base high, breakout bar excluded": (3, 1)}
    VOL = {"volume at least 1.5x the 20-day average": (5, 1)}

    def out(self, rows):
        _, out = run_main(["--setup", "breakout"], _MainStub(rows=rows))
        return out

    def test_the_condition_that_rejected_most_names_is_named(self):
        rows = self.rows(self.BASE, self.HIGH, self.HIGH, self.HIGH)
        out = self.out(rows)
        self.assertIn("The binding condition is a close above the base high, "
                      "breakout bar excluded — it rejected 3 of the 3 names "
                      "that reached it", out)

    def test_the_funnel_reports_every_condition_names_reached(self):
        rows = self.rows(self.BASE, self.HIGH, self.HIGH, self.VOL)
        out = self.out(rows)
        self.assertIn("4 reached a base of at least 12 bars, 1 failed", out)
        self.assertIn("3 reached a close above the base high, breakout bar "
                      "excluded, 2 failed", out)
        self.assertIn("1 reached volume at least 1.5x the 20-day average, "
                      "1 failed", out)

    def test_a_different_binding_condition_is_reported_differently(self):
        """The accept side: the message follows the data rather than printing a
        fixed sentence about the base high."""
        rows = self.rows(self.BASE, self.BASE, self.BASE, self.HIGH)
        out = self.out(rows)
        self.assertIn("The binding condition is a base of at least 12 bars", out)
        self.assertNotIn("The binding condition is a close above", out)

    def test_a_gated_name_is_not_counted_as_having_reached_anything(self):
        rows = self.rows(self.HIGH, self.HIGH)
        rows.append(scan_row("THIN", matched=(), illiquid=True))
        rows[-1]["diag"] = {}
        out = self.out(rows)
        self.assertIn("2 names were screened", out)
        self.assertIn("2 reached a close above the base high", out)

    def test_confluence_reports_the_screened_count_without_inventing_a_funnel(self):
        """CONFLUENCE has no predicate, so it has no condition to blame."""
        rows = self.rows(self.HIGH, self.HIGH)
        _, out = run_main(["--setup", "confluence"], _MainStub(rows=rows))
        self.assertIn("### CONFLUENCE", out)
        self.assertIn("2 names were screened", out)
        self.assertNotIn("binding condition", out)


class TestBreadthReadsTheWholeScreen(unittest.TestCase):
    """The breadth read must describe the screen, not the top of the table.

    Both reproductions from the live-output review. `--setup leader
    --min-turnover 25 --top 5` printed "56 leaders" and then drew its sector
    conclusion from 5 rows; `--sector "Financial Services" --top 5" announced
    "5 of 5 LEADER names are Financial Services" to a user who had just said so
    themselves.
    """

    def rows(self, n_fs=5, n_other=6):
        """LEADER matches where the concentrated sector sorts to the TOP.

        rank() orders on Score Now, so the higher total puts every Financial
        Services name in the first `top` rows: truncating to 5 gives 5 of 5
        financials out of a match set that is 5 of 11.
        """
        return ([scan_row("F%d" % i, sector="Financial Services",
                          matched=("LEADER",), total=9.0) for i in range(n_fs)]
                + [scan_row("O%d" % i, sector="Other %d" % i,
                            matched=("LEADER",), total=6.0)
                   for i in range(n_other)])

    def test_the_sector_read_counts_the_match_set_not_the_displayed_rows(self):
        rows = self.rows()
        _, out = run_main(["--setup", "leader", "--top", "5"],
                          _MainStub(rows=rows))
        self.assertIn("LEADER 11", out)           # the header says eleven...
        self.assertIn("showing top 5 of 11", out)  # ...and the table shows five
        self.assertNotIn("sector call", out)
        self.assertNotIn("5 of 5", out)

    def test_a_concentrated_match_set_is_still_reported(self):
        """The accept side: when the WHOLE match set is concentrated, truncating
        the table must not silence the observation either."""
        rows = self.rows(n_fs=8, n_other=2)
        _, out = run_main(["--setup", "leader", "--top", "5"],
                          _MainStub(rows=rows))
        self.assertIn("8 of 10 LEADER names are Financial Services", out)

    def test_a_sector_filtered_run_does_not_report_the_chosen_sector(self):
        rows = self.rows(n_fs=8, n_other=0)
        _, out = run_main(["--setup", "leader", "--sector", "Financial Services"],
                          _MainStub(rows=rows))
        self.assertNotIn("sector call", out)

    def test_the_same_rows_unfiltered_do_report_it(self):
        """Pins that the suppression is the --sector flag and not the rows."""
        rows = self.rows(n_fs=8, n_other=0)
        _, out = run_main(["--setup", "leader"], _MainStub(rows=rows))
        self.assertIn("8 of 8 LEADER names are Financial Services", out)


class TestMainReport(unittest.TestCase):
    def test_the_report_carries_header_table_key_breadth_and_disclaimer(self):
        stub = _MainStub(rows=[scan_row("TCS")])
        rc, out = run_main(["--setup", "leader"], stub)
        self.assertEqual(rc, 0)
        self.assertIn("SCAN ", out)
        self.assertIn("### LEADER", out)
        self.assertIn("Score Now (catalyst-neutral)", out)
        self.assertIn("**Key**", out)
        self.assertIn("leaders", out)
        self.assertIn("Mechanical framework output, not personalised "
                      "investment advice.", out)

    def test_a_clamped_top_is_announced(self):
        rc, out = run_main(["--setup", "leader", "--top", "21"], _MainStub())
        self.assertIn("NOTE: --top clamped to the 20-name cap", out)

    def test_a_top_at_the_cap_is_not_announced(self):
        _, out = run_main(["--setup", "leader", "--top", "20"], _MainStub())
        self.assertNotIn("clamped", out)

    def test_a_setup_with_no_matches_prints_the_empty_finding_not_a_table(self):
        stub = _MainStub(rows=[scan_row("TCS", matched=("LEADER",))])
        _, out = run_main(["--setup", "coiled"], stub)
        self.assertIn("No names matched", out)
        self.assertNotIn("| Rank |", out)

    def test_truncation_is_announced_in_the_report(self):
        rows = [scan_row(f"S{i}", total=float(i)) for i in range(6)]
        _, out = run_main(["--setup", "leader", "--top", "2"], _MainStub(rows=rows))
        self.assertIn("showing top 2 of 6", out)

    def test_buyable_and_alert_names_reach_the_handoff(self):
        stub = _MainStub(rows=[scan_row("TCS", verdict="HALF SIZE")])
        _, out = run_main(["--setup", "leader"], stub)
        self.assertIn('watchlist.py "TCS"', out)

    def test_watch_only_names_produce_no_handoff(self):
        """The sibling arm: a screen full of WATCH has nothing to adjudicate."""
        stub = _MainStub(rows=[scan_row("TCS", verdict="STAND ASIDE / BEAR BIAS")])
        _, out = run_main(["--setup", "leader"], stub)
        self.assertNotIn("watchlist.py", out)
        # ...and leaves no blank gap where the handoff block would have been.
        lines = out.rstrip("\n").split("\n")
        self.assertEqual(lines[-1], "Mechanical framework output, not "
                                    "personalised investment advice.")
        self.assertEqual(lines[-2], "")
        self.assertNotEqual(lines[-3], "")

    def test_the_handoff_deduplicates_names_across_setup_tables(self):
        stub = _MainStub(rows=[scan_row("TCS", matched=("LEADER", "TURN"))])
        _, out = run_main(["--setup", "leader,turn"], stub)
        self.assertIn('watchlist.py "TCS"', out)

    def test_the_handoff_is_capped_at_ten_names(self):
        rows = [scan_row(f"S{i}", total=float(i)) for i in range(14)]
        _, out = run_main(["--setup", "leader", "--top", "14"], _MainStub(rows=rows))
        line = [ln for ln in out.splitlines() if "watchlist.py" in ln][0]
        self.assertEqual(len(line.split('"')[1].split(",")), 10)


if __name__ == "__main__":
    unittest.main()
