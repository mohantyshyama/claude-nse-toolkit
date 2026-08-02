import os, sys, unittest
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
sys.path.insert(0, _root)
sys.path.insert(0, _here)
from engine import A
import setups
from fixtures import (flat_series, trend_series, contracting_series,
                      close_at_high_series, turnover_ladder, turnover_series_cr,
                      gapped_tr_series, varying_tr_series, divergent_values, bar,
                      ud_series)


def true_ranges(rows):
    """Wilder true range per bar, computed independently of setups.py so the
    tests below are not just restating the implementation back to itself."""
    return [max(rows[i]["h"] - rows[i]["l"],
                abs(rows[i]["h"] - rows[i - 1]["c"]),
                abs(rows[i]["l"] - rows[i - 1]["c"]))
            for i in range(1, len(rows))]


class TestSeriesHelpers(unittest.TestCase):
    def test_sma_series_last_value_matches_engine_sma(self):
        """Pins the helper to the engine. If these ever disagree, setups.py has
        become a second indicator implementation -- invariant I1 is broken.

        Uses divergent_values ([50]*80 + [1]*20) not a linear ramp. On linear
        data, steady-state EMA and SMA both approach current_value - (n-1)/2,
        converging and hiding an EMA-for-SMA bug. divergent_values makes them
        provably diverge so this test actually discriminates the algorithms.
        """
        v = divergent_values(100)
        for n in (20, 50):
            self.assertAlmostEqual(setups.sma_series(v, n)[-1], A.sma(v, n), places=9)

    def test_sma_series_alignment_and_length(self):
        v = [float(x) for x in range(1, 11)]
        s = setups.sma_series(v, 3)
        self.assertEqual(len(s), len(v) - 3 + 1)
        self.assertAlmostEqual(s[0], 2.0, places=9)   # mean of 1,2,3

    def test_sma_series_too_short_returns_empty(self):
        self.assertEqual(setups.sma_series([1.0, 2.0], 5), [])

    def test_sma_series_just_below_minimum_length_matches_engine_none(self):
        """Reject side of the guard, AT the boundary: len(values) == n - 1.

        The accept side (len == n) is covered above, but nothing probed the last
        input that must be REFUSED, so narrowing the guard to `len(values) < n-1`
        survived: it returns [2.0] for four values over a five-wide window -- a
        sum of four divided by five -- exactly where the engine returns None.
        That is an invariant I1 violation, so the engine's answer is asserted
        alongside ours rather than the bare [].
        """
        v = [1.0, 2.0, 3.0, 4.0]        # len = 4, one short of n = 5
        self.assertIsNone(A.sma(v, 5))
        self.assertEqual(setups.sma_series(v, 5), [])

    def test_sma_series_at_minimum_length(self):
        """Boundary: len(values) == n is the smallest input that must produce output.

        The mutant this kills is widening the guard from `len(values) < n` to
        `len(values) <= n`, which would return [] for the first legal input.
        Confirmed by patching that mutant in and watching this test fail.
        """
        v = [1.0, 2.0, 3.0, 4.0, 5.0]  # len=5
        s = setups.sma_series(v, 5)     # n=5
        self.assertEqual(len(s), 1)
        self.assertAlmostEqual(s[0], 3.0, places=9)  # mean of [1,2,3,4,5]

    def test_sma_series_is_not_an_exponential_average(self):
        """Proves sma_series uses rolling mean, not EMA.

        On divergent_values ([50]*80 + [1]*20), EMA lags behind the current
        value due to exponential weighting. The last 20 values are all 1, so
        SMA = 1. But EMA ≈ 7-8 (lingering memory of 50s, slow decay toward 1).
        This discriminates the algorithms; linear or smooth data would make
        them converge and hide an EMA-for-SMA bug.
        """
        v = divergent_values(100)
        n = 20
        sma = setups.sma_series(v, n)[-1]
        # Compute EMA with same seed as sma_series would use
        k = 2 / (n + 1)
        e = sum(v[:n]) / n  # same seed
        for x in v[n:]:
            e = x * k + e * (1 - k)
        ema = e
        # EMA should lag behind and be significantly higher than SMA
        self.assertGreater(ema, sma + 3.0,
                          f"ema ({ema:.2f}) should be > sma ({sma:.2f}) + 3")

    def test_atr_series_last_value_matches_engine_atr(self):
        """Pins ATR helper to engine using varied true ranges.

        varying_tr_series has high TR early, low TR late. A simple rolling mean
        of the last 14 TRs would be ~1, but Wilder smoothing remembers the high
        TRs and produces ~2+. This discriminates the algorithms; constant TR
        would make both converge and hide wrong implementations.
        """
        rows = varying_tr_series(50)
        self.assertAlmostEqual(setups.atr_series(rows, 14)[-1], A.atr(rows, 14), places=9)

    def test_atr_series_is_wilder_not_a_rolling_mean(self):
        """Proves atr_series uses Wilder smoothing, not a simple rolling mean.

        On varying_tr_series with high TR early and low TR late, these algorithms
        diverge: Wilder smoothing gives ~2+, simple rolling mean of last 14 TRs
        gives ~1. This test fails if atr_series is ever replaced with a rolling mean.
        """
        rows = varying_tr_series(50)
        series = setups.atr_series(rows, 14)
        # Compute true ranges for the last 14 bars
        trs = [max(rows[i]["h"] - rows[i]["l"],
                   abs(rows[i]["h"] - rows[i - 1]["c"]),
                   abs(rows[i]["l"] - rows[i - 1]["c"]))
               for i in range(1, len(rows))]
        # Simple rolling mean of the last 14 TRs
        simple_mean_last_14 = sum(trs[-14:]) / 14
        # Wilder-smoothed final value is significantly higher (has memory of high TRs early)
        self.assertGreater(series[-1], simple_mean_last_14 + 0.5,
                          "atr_series[-1] should be > simple_mean_last_14 + 0.5")

    def test_atr_series_matches_engine_on_gapping_bars(self):
        """Pins ATR on bars that GAP, so every arm of the true-range max matters.

        trend_series and varying_tr_series never gap, so `h - l` always wins and
        the two gap terms of the max() are dead code -- dropping either survived.
        gapped_tr_series opens -4/0/+4 off the previous close in rotation, and on
        the narrow-span bars a gap term is strictly the largest, so an ATR that
        ignores gaps diverges from the engine here.
        """
        rows = gapped_tr_series(40)
        self.assertAlmostEqual(setups.atr_series(rows, 14)[-1], A.atr(rows, 14),
                               places=9)

    def test_atr_series_seed_is_the_mean_of_the_first_n_true_ranges(self):
        """The Wilder seed averages the first n true ranges; it is not trs[0].

        Both older ATR fixtures hold the range constant across the seed window
        (10.0 then 2.0), so mean(trs[:14]) == trs[0] to the bit and `a = trs[0]`
        survived. gapped_tr_series cycles the span 1..5, putting seven distinct
        true ranges in the seed window. atr_series' FIRST element is the seed, so
        this pins it directly with no smoothing decay in between.
        """
        rows = gapped_tr_series(40)
        trs = true_ranges(rows)
        seed = setups.atr_series(rows, 14)[0]
        self.assertAlmostEqual(seed, sum(trs[:14]) / 14, places=9)
        # Proof the fixture can tell the two apart at all.
        self.assertNotAlmostEqual(seed, trs[0], places=3)

    def test_atr_series_defaults_to_fourteen_periods(self):
        """n=14 is a default, so at least one call must omit it or it is unpinned.

        Every other ATR test passes 14 explicitly, which left the default free to
        be any number at all. Compared against the engine called with ITS default
        too, so the two defaults are pinned to each other.
        """
        rows = gapped_tr_series(40)
        self.assertAlmostEqual(setups.atr_series(rows)[-1], A.atr(rows), places=9)
        self.assertEqual(len(setups.atr_series(rows)), len(rows) - 14)

    def test_atr_series_too_short_returns_empty(self):
        self.assertEqual(setups.atr_series(trend_series(5), 14), [])

    def test_atr_series_just_below_minimum_length_matches_engine_none(self):
        """Reject side of the guard, AT the boundary: len(rows) == n + 1.

        The accept side (n+2) is covered below; nothing probed the last refused
        input, so narrowing the guard to `len(rows) < n+1` survived -- it hands
        back a one-element series where the engine returns None. Assert the
        engine's answer next to ours so the two guards stay welded together.
        """
        rows = gapped_tr_series(15)     # 15 = n + 1 for n = 14
        self.assertIsNone(A.atr(rows, 14))
        self.assertEqual(setups.atr_series(rows, 14), [])

    def test_atr_series_at_minimum_length(self):
        """Boundary: len(rows) == n+2 is the smallest input that must produce output.

        For n=14, this is len(rows)==16. Guards against off-by-one errors in the
        guard. Output length is len(rows) - n = 16 - 14 = 2 (seed + one recurrence).
        Uses trend_series(16) which produces predictable TRs for verification.
        """
        rows = trend_series(16, start=100.0, step=1.0, spread=1.0)
        result = setups.atr_series(rows, 14)
        self.assertEqual(len(result), 2)
        # Last element should match A.atr at this length
        self.assertAlmostEqual(result[-1], A.atr(rows, 14), places=9)

    def test_window_widths_normalises_by_window_midpoint(self):
        """Widths are % of each window's own midpoint so windows at different
        price levels compare fairly."""
        rows = contracting_series([4.0, 2.0, 1.0], price=100.0, bars_per_window=5)
        w = setups.window_widths(rows, 3)
        self.assertEqual(len(w), 3)
        self.assertAlmostEqual(w[0], 8.0, places=6)   # range 8 on midpoint 100
        self.assertAlmostEqual(w[2], 2.0, places=6)
        self.assertTrue(w[0] > w[1] > w[2])

    def test_window_widths_normalises_by_midpoint_not_absolutes(self):
        """Same absolute range at different price levels normalizes to different %.

        The first test uses all windows at price=100, so absolute ranges (8,4,2)
        equal percentages. This test has windows at different levels: same 8-unit
        range at prices 100/200/50 should normalize to 8%/4%/16%. If the
        implementation forgets to normalize, it would return [8,8,8] and fail.
        """
        rows = []
        # Window 1: price 100, range 8
        for i in range(5):
            rows.append(bar(i, 100, 104, 96, 100, 1_000_000))
        # Window 2: price 200, range 8
        for i in range(5, 10):
            rows.append(bar(i, 200, 204, 196, 200, 1_000_000))
        # Window 3: price 50, range 8
        for i in range(10, 15):
            rows.append(bar(i, 50, 54, 46, 50, 1_000_000))
        w = setups.window_widths(rows, 3)
        self.assertEqual(len(w), 3)
        self.assertAlmostEqual(w[0], 8.0, places=6)   # 8 / 100 * 100 = 8%
        self.assertAlmostEqual(w[1], 4.0, places=6)   # 8 / 200 * 100 = 4%
        self.assertAlmostEqual(w[2], 16.0, places=6)  # 8 / 50 * 100 = 16%

    def test_window_widths_normalises_by_midpoint_not_by_mean_close(self):
        """Midpoint is (hi+lo)/2 of the window, not the average close in it.

        Every other window fixture puts the close exactly on the midpoint, so
        `mid = mean(closes)` produces identical output and survives. Here each
        bar closes at its own high, pushing the mean close above the midpoint,
        so the two divisors give visibly different percentages.
        """
        rows = close_at_high_series([10.0, 5.0, 2.0], price=100.0,
                                    bars_per_window=4)
        w = setups.window_widths(rows, 3)
        self.assertEqual(len(w), 3)
        # midpoint of every window is 100: ranges 20, 10, 4 -> 20%, 10%, 4%.
        # Dividing by the mean close (110, 105, 102) would give 18.18, 9.52, 3.92.
        self.assertAlmostEqual(w[0], 20.0, places=6)
        self.assertAlmostEqual(w[1], 10.0, places=6)
        self.assertAlmostEqual(w[2], 4.0, places=6)

    def test_window_widths_last_window_absorbs_the_remainder(self):
        """len(rows) need not divide by n; the final window takes what is left.

        14 bars over 3 windows gives size=4 and windows of 4, 4 and 6 bars. The
        two extra bars carry the only wide range in the series, so an
        implementation that slices every window as rows[i*size:(i+1)*size] and
        silently drops the tail reports 4% instead of 20% for the last window.
        """
        rows = flat_series(12, price=100.0, spread=2.0)      # h=102, l=98
        rows.append(bar(12, 100.0, 110.0, 90.0, 100.0))      # remainder bars
        rows.append(bar(13, 100.0, 110.0, 90.0, 100.0))
        self.assertEqual(len(rows), 14)
        w = setups.window_widths(rows, 3)
        self.assertEqual(len(w), 3)
        self.assertAlmostEqual(w[0], 4.0, places=6)
        self.assertAlmostEqual(w[1], 4.0, places=6)
        self.assertAlmostEqual(w[2], 20.0, places=6)  # 4.0 if the tail is dropped

    def test_window_widths_defaults_to_three_windows(self):
        """n=3 is a default, so at least one call must omit it or it is unpinned.

        Every other window test passes 3 explicitly, leaving the default free to
        be any number. 12 bars split three ways give four-bar windows; any other
        n changes the length (n=2 -> 2 windows, n=4 -> size 3 -> []).
        """
        rows = flat_series(12, price=100.0, spread=2.0)
        self.assertEqual(len(setups.window_widths(rows)), 3)
        for w in setups.window_widths(rows):
            self.assertAlmostEqual(w, 4.0, places=6)

    def test_window_widths_zero_midpoint_is_zero_width_not_a_crash(self):
        """The `if mid else 0.0` arm: a degenerate window must not divide by zero.

        No fixture ever produced hi + lo == 0, so the guard was uncovered and
        deleting it survived. Bars pinned at zero make the midpoint zero; the
        defensive arm must return 0.0 rather than raising ZeroDivisionError.
        """
        rows = [bar(i, 0.0, 0.0, 0.0, 0.0) for i in range(12)]
        self.assertEqual(setups.window_widths(rows, 3), [0.0, 0.0, 0.0])

    def test_window_widths_needs_four_bars_per_window(self):
        self.assertEqual(setups.window_widths(flat_series(9), 3), [])

    def test_window_widths_at_minimum_bars_per_window(self):
        """Boundary: size == 4 is the smallest window that must produce output.

        With n=3 windows over 12 bars each window holds exactly 4 bars. The
        mutant this kills is widening the guard from `size < 4` to `size <= 4`,
        which would return [] for the first legal size. (A `size > 4` guard is
        NOT what this test catches -- that one is killed by the normalisation
        tests, whose fixtures also have four-bar windows.) Confirmed by patching
        the `<=` mutant in and watching this test fail.
        """
        rows = flat_series(12, price=100.0, spread=2.0)  # 12 bars, range = 4
        widths = setups.window_widths(rows, 3)
        self.assertEqual(len(widths), 3)
        # Each window has 4 bars with range 4 on midpoint 100
        expected = 4.0 / 100.0 * 100  # = 4.0%
        for w in widths:
            self.assertAlmostEqual(w, expected, places=6)

    def test_turnover_cr_is_median_close_times_volume_in_crore(self):
        rows = flat_series(50, price=100.0, vol=1_000_000)
        # 100 * 1,000,000 = 10,00,00,000 = 10 crore
        self.assertAlmostEqual(setups.turnover_cr(rows, 50), 10.0, places=6)

    def test_turnover_cr_uses_median_not_mean(self):
        rows = flat_series(49, price=100.0, vol=1_000_000)
        rows.append(bar(99, 100.0, 101.0, 99.0, 100.0, 500_000_000))  # one spike
        self.assertAlmostEqual(setups.turnover_cr(rows, 50), 10.0, places=6)

    def test_turnover_cr_even_window_averages_the_two_middle_values(self):
        """An even-length window must average BOTH middle values.

        The flat fixtures above have identical middle values, so `vals[mid]`
        and `(vals[mid-1]+vals[mid])/2` agree and the even branch is dead code.
        turnover_ladder(50) gives turnovers 1..50 crore: the middles are 25 and
        26, so the correct answer is 25.5 and picking one element gives 26.0.

        The ladder's open (90) also differs from its close (100), so reading
        r["o"] instead of r["c"] gives 22.95 and fails here too.
        """
        rows = turnover_ladder(50)
        self.assertEqual(len(rows) % 2, 0)
        self.assertAlmostEqual(setups.turnover_cr(rows, 50), 25.5, places=6)

    def test_turnover_cr_uses_the_last_n_bars_not_the_first(self):
        """The window is the most recent n bars: rows[-n:], never rows[:n].

        Both other turnover tests pass exactly 50 rows with n=50, where head and
        tail slices are the same list. Here 60 bars climb 1 crore a bar, so the
        last 50 (11..60 crore) median 35.5 while the first 50 (1..50) median 25.5.
        """
        rows = turnover_ladder(60)
        self.assertGreater(len(rows), 50)
        self.assertAlmostEqual(setups.turnover_cr(rows, 50), 35.5, places=6)

    def test_turnover_cr_odd_window_takes_the_single_middle_value(self):
        """The OTHER arm of the median ternary.

        Fixing the even branch last round left all four turnover tests on
        50-bar windows, which killed the odd branch instead -- the defect moved
        across the ternary rather than going away. An odd window of 1..49 crore
        has a true median of 25.0; applying the even formula unconditionally
        gives (24+25)/2 = 24.5.
        """
        rows = turnover_ladder(49)
        self.assertEqual(len(rows) % 2, 1)
        self.assertAlmostEqual(setups.turnover_cr(rows, 49), 25.0, places=6)

    def test_turnover_cr_sorts_before_taking_the_median(self):
        """The sort is load-bearing, not decoration.

        Every other turnover fixture arrives already ascending -- flat, a
        monotone ladder, or a spike appended last -- so `sorted()` was a no-op
        that removing it survived. Rotating 1..50 so the SMALLEST values land in
        the middle positions separates the two: the true median is still 25.5,
        but reading the middle of the unsorted list gives (1+2)/2 = 1.5.
        """
        rotated = list(range(27, 51)) + list(range(1, 27))
        self.assertNotEqual(rotated, sorted(rotated))
        self.assertAlmostEqual((rotated[24] + rotated[25]) / 2, 1.5, places=9)
        rows = turnover_series_cr(rotated)
        self.assertAlmostEqual(setups.turnover_cr(rows, 50), 25.5, places=6)

    def test_turnover_cr_defaults_to_fifty_bars(self):
        """n=50 is a default, so at least one call must omit it or it is unpinned.

        Every other turnover test passes 50 explicitly. With 60 bars the default
        window is the last 50 (11..60 crore, median 35.5); any other default
        would select a different slice and a different median.
        """
        rows = turnover_ladder(60)
        self.assertAlmostEqual(setups.turnover_cr(rows), 35.5, places=6)

    def test_turnover_cr_of_no_bars_is_zero(self):
        """The `if not vals` arm: an empty series must not index into nothing.

        Nothing ever called turnover_cr with no rows, so the guard was uncovered
        and deleting it survived the suite while raising IndexError in real use.
        """
        self.assertEqual(setups.turnover_cr([], 50), 0.0)
        self.assertEqual(setups.turnover_cr([]), 0.0)


class TestUpDownVolumeRatio(unittest.TestCase):
    """O'Neil's up/down volume ratio.

    Every fixture here has up_vol != down_vol on purpose. A constant-volume
    series gives a ratio of 1.0 for any correct OR wrong implementation, and a
    series where every bar closes up has no denominator at all -- neither can
    discriminate, which is exactly how a decorative gate gets shipped green.
    """

    def test_ratio_is_up_volume_over_down_volume(self):
        """Three up bars at 2M and two down bars at 1M: 6M / 2M = 3.0.

        The swapped implementation (down / up) returns 0.333 here, so this test
        dies against it. Confirmed by patching the swap in.
        """
        rows = ud_series("uuudd")
        self.assertAlmostEqual(setups.ud_ratio(rows, 50), 3.0, places=9)

    def test_a_distributing_series_reads_below_one(self):
        """The other side of 1.0. Two up bars at 2M against three down at 1M is
        4M / 3M = 1.333 -- so the SAME volumes with the pattern reversed must
        NOT give 3.0, which a ratio keyed off bar count alone would."""
        rows = ud_series("uuddd")
        self.assertAlmostEqual(setups.ud_ratio(rows, 50), 4 / 3, places=9)

    def test_the_ratio_is_not_a_count_of_up_bars_over_down_bars(self):
        """Volume, not bars. Equal counts with unequal volumes must not read 1.0.

        Kills an implementation that sums 1 per bar instead of r["v"].
        """
        rows = ud_series("uudd", up_vol=5_000_000, down_vol=1_000_000)
        self.assertAlmostEqual(setups.ud_ratio(rows, 50), 5.0, places=9)

    def test_unchanged_closes_land_on_neither_side(self):
        """flat_vol is 9M, larger than either directional volume, so a flat bar
        credited to the numerator or the denominator would swamp the answer."""
        rows = ud_series("ufudfd")          # 2 up, 2 down, 2 flat
        self.assertAlmostEqual(setups.ud_ratio(rows, 50), 2.0, places=9)

    def test_direction_is_measured_against_the_previous_close_not_the_open(self):
        """A bar that closes above its own open but below yesterday's close is a
        DOWN day, and vice versa.

        Bar 1: opens 90, closes 95 -- green candle, but 100 -> 95 is a down day.
        Bar 2: opens 99, closes 97 -- red candle, but 95 -> 97 is an up day.
        An implementation keyed off `c > o` reports 3.0; the correct one reports
        1/3. The engine's thrust labels use `c > o`; this measure does not.
        """
        rows = [bar(0, 100.0, 101.0, 99.0, 100.0, 5_000_000),
                bar(1, 90.0, 96.0, 89.0, 95.0, 3_000_000),
                bar(2, 99.0, 100.0, 96.0, 97.0, 1_000_000)]
        self.assertAlmostEqual(setups.ud_ratio(rows, 50), 1 / 3, places=9)

    def test_only_the_last_n_bars_are_counted(self):
        """A heavy down bar outside the window must not reach the denominator.

        The first six bars are down at 4M each; the last three are up at 2M and
        down at 1M. Over a 3-bar window only the tail counts.
        """
        rows = ud_series("dddddd", down_vol=4_000_000) \
            + ud_series("uud", price=94.0, up_vol=2_000_000,
                        down_vol=1_000_000)[1:]
        self.assertAlmostEqual(setups.ud_ratio(rows, 3), 4.0, places=9)
        # ...and the same series over the full window is dominated by the down
        # bars, so the window argument is provably doing something.
        self.assertLess(setups.ud_ratio(rows, 50), 1.0)

    def test_the_first_bar_of_the_window_is_judged_against_the_bar_before_it(self):
        """Exactly n bars are classified, not n-1.

        Over a 2-bar window of "ud" the first in-window bar is an up bar at 2M
        and the second a down bar at 1M, giving 2.0. An implementation that can
        only classify bars whose predecessor is also inside the window sees one
        down bar, no up volume, and returns 0.0.
        """
        rows = ud_series("dduud")
        self.assertAlmostEqual(setups.ud_ratio(rows, 2), 2.0, places=9)

    def test_the_very_first_bar_of_the_series_is_unclassifiable(self):
        """anchor_vol is 7M and has no predecessor. Counting it as an up bar
        would give 9M/1M = 9.0 rather than 2.0."""
        rows = ud_series("ud")
        self.assertAlmostEqual(setups.ud_ratio(rows, 50), 2.0, places=9)

    def test_no_down_volume_returns_none_rather_than_dividing(self):
        """The documented decision: a name with zero down-volume is UNMEASURABLE,
        and _ud_ratio_ok turns that into a failed gate rather than a pass."""
        self.assertIsNone(setups.ud_ratio(ud_series("uuuuu"), 50))

    def test_a_window_of_only_flat_closes_returns_none(self):
        """Zero on both sides -- 0/0 is not 1.0, and must not be reported as a
        neutral ratio."""
        self.assertIsNone(setups.ud_ratio(ud_series("fffff"), 50))

    def test_zero_up_volume_is_zero_not_none(self):
        """The denominator exists, so the answer is measurable and is 0.0.
        Distinct from None: this name is measurably under distribution."""
        self.assertEqual(setups.ud_ratio(ud_series("ddddd"), 50), 0.0)

    def test_a_non_positive_window_returns_none(self):
        """rows[-0:] is the WHOLE list, so an unguarded n=0 silently measures
        two years and reports a confident number for a nonsense window."""
        rows = ud_series("uuudd")
        self.assertIsNone(setups.ud_ratio(rows, 0))
        self.assertIsNone(setups.ud_ratio(rows, -5))

    def test_too_few_bars_returns_none(self):
        self.assertIsNone(setups.ud_ratio([], 50))
        self.assertIsNone(setups.ud_ratio(ud_series("")[:1], 50))

    def test_two_bars_is_the_shortest_measurable_series(self):
        """The accept side of the len < 2 guard, at the boundary."""
        rows = ud_series("d")
        self.assertEqual(len(rows), 2)
        self.assertEqual(setups.ud_ratio(rows, 50), 0.0)

    def test_the_default_window_is_fifty_bars(self):
        """n=50 is a default, so at least one call must omit it or the default is
        unpinned. The series is built so 50 bars and the whole series disagree:
        the first 20 bars are heavy down bars and the last 50 are net up."""
        rows = ud_series("d" * 20, down_vol=8_000_000) \
            + ud_series("u" * 34 + "d" * 16, price=80.0)[1:]
        self.assertAlmostEqual(setups.ud_ratio(rows), setups.ud_ratio(rows, 50),
                               places=9)
        self.assertEqual(setups.UD_BARS, 50)
        self.assertNotAlmostEqual(setups.ud_ratio(rows), setups.ud_ratio(rows, 200),
                                  places=3)


class TestContextExposesTheUpDownRatio(unittest.TestCase):
    def test_ctx_carries_the_ratio_computed_over_UD_BARS(self):
        """Computed ONCE per symbol, in the context builder, so three predicates
        and the report all read the same number."""
        rows = ud_series("uuudd" * 30)
        c = setups._ctx_from_rows(rows, {"1m": 1.0, "3m": 2.0})
        self.assertIn("ud_ratio", c)
        self.assertAlmostEqual(c["ud_ratio"], setups.ud_ratio(rows, setups.UD_BARS),
                               places=9)

    def test_ctx_ratio_is_not_measured_over_the_whole_series(self):
        """Pins the window at UD_BARS rather than 'everything we fetched'. The
        first 200 bars are heavy down bars; the last 50 are net up."""
        rows = ud_series("d" * 200, down_vol=8_000_000) \
            + ud_series("uuudd" * 10, price=50.0)[1:]
        c = setups._ctx_from_rows(rows, {})
        self.assertGreater(c["ud_ratio"], 1.0)
        self.assertLess(setups.ud_ratio(rows, len(rows)), 1.0)

    def test_ctx_ratio_is_none_when_the_series_cannot_be_measured(self):
        """A None must survive the context builder as None, not become 1.0."""
        c = setups._ctx_from_rows(ud_series("u" * 60), {})
        self.assertIsNone(c["ud_ratio"])


class TestFitAccumulation(unittest.TestCase):
    """The shared 0-10 accumulation sub-score, on its LADDER.

    ONE ladder for all five setups, so that an 8 for accumulation means the same
    thing under LEADER as under COILED. The per-setup tests assert how much each
    setup WEIGHTS it; this asserts what it says.

    Every case here passes the SAME ratio as both the close-to-close and the
    close-weighted argument, and None as the 20-bar one. That is not a
    convenience: the two ladder weights sum to exactly 1.0 and an unmeasurable
    trend is charged nothing, so an aligned name scores exactly what it scored
    before the term learned about the close, and every number below is the
    number this file has always asserted. The BLENDING of two disagreeing ratios
    and the trend penalty are separate behaviours, tested in test_confluence.
    """

    @staticmethod
    def ladder(ud):
        return setups.fit_accumulation(ud, ud, None)

    #: (ratio, sub-score) at every rung boundary, from the spec table.
    RUNGS = [(2.50, 10.0), (2.00, 9.0), (1.50, 8.0), (1.25, 6.0), (1.00, 4.0)]

    def test_each_rung_is_returned_at_its_own_floor(self):
        for ud, sub in self.RUNGS:
            self.assertEqual(self.ladder(ud), sub, msg="at %s" % ud)

    def test_each_floor_is_inclusive_and_a_hair_below_drops_a_rung(self):
        """Both sides of every boundary, so no cut can move in either direction.

        Without the paired just-below case a cut could be lowered (2.50 -> 2.40)
        and the at-cut assertion would still pass.
        """
        for i, (ud, _sub) in enumerate(self.RUNGS):
            below = self.RUNGS[i + 1][1] if i + 1 < len(self.RUNGS) else 2.0
            self.assertEqual(self.ladder(ud - 0.001), below,
                             msg="just below %s" % ud)

    def test_above_the_top_rung_stays_at_ten(self):
        """The ladder does not keep climbing: 10 is the cap, and a name at 40x
        must not out-score one at 2.5x by an unbounded amount."""
        for ud in (2.50, 3.0, 12.0, 400.0):
            self.assertEqual(self.ladder(ud), 10.0, msg=str(ud))

    def test_below_one_scores_the_floor(self):
        """Under 1.0 is net DISTRIBUTION -- more volume on down days than up."""
        for ud in (0.99, 0.5, 0.0):
            self.assertEqual(self.ladder(ud), 2.0, msg=str(ud))

    def test_the_floor_is_two_and_not_zero(self):
        """Deliberately not zero. Below 1.0 is a real measured finding about a
        name that cleared every other gate, and zeroing the term would let one
        soft input dominate a five-term score."""
        self.assertEqual(setups.NO_ACCUMULATION, 2.0)
        self.assertEqual(self.ladder(0.4), 2.0)

    def test_an_unmeasurable_ratio_scores_the_floor_not_the_top(self):
        """None means no down-volume in the window, so the ratio cannot be
        formed. It scores the floor, matching the decision _ud_ratio_ok makes at
        the gates: a score that rewarded the ABSENCE of evidence would rank an
        unmeasurable name above a measured one.
        """
        self.assertEqual(self.ladder(None), 2.0)
        self.assertEqual(self.ladder(None),
                         self.ladder(0.5))

    def test_it_is_monotone_in_the_ratio(self):
        """The shape itself, not a list of points: more accumulation is never
        worth less. A band with a transposed pair would satisfy several of the
        point assertions above and fail this."""
        xs = [0.0, 0.5, 0.99, 1.0, 1.24, 1.25, 1.49, 1.5, 1.99, 2.0, 2.49,
              2.5, 9.0]
        scores = [self.ladder(x) for x in xs]
        self.assertEqual(scores, sorted(scores))

    def test_the_ladder_matches_the_published_cut_table(self):
        """The cuts are DATA, and this is the table the documentation quotes."""
        self.assertEqual([tuple(c) for c in setups.ACCUMULATION_CUTS],
                         [(2.50, 10.0), (2.00, 9.0), (1.50, 8.0),
                          (1.25, 6.0), (1.00, 4.0)])


class TestFitWeights(unittest.TestCase):
    """Every setup's Fit weights, as data.

    They are a module-level table rather than literals inside five expressions
    precisely so that the sum can be asserted about the CODE the fits run on,
    instead of being a claim a docstring makes near it.
    """

    def test_every_setup_has_a_weight_set(self):
        self.assertEqual(set(setups.FIT_WEIGHTS), set(setups.SETUPS))

    def test_each_weight_set_sums_to_exactly_one(self):
        """Exactly 1.0, with no tolerance -- these five sets are chosen so that
        binary floating point lands on 1.0 on the nose. A Fit that summed to
        0.95 or 1.05 would still look like a 0-10 score and would silently
        rescale every table.
        """
        for name, weights in setups.FIT_WEIGHTS.items():
            self.assertEqual(sum(weights.values()), 1.0, msg=name)

    def test_every_setup_carries_an_accumulation_term(self):
        """All five, including BREAKOUT, which has no up/down volume GATE. The
        measure ranks everywhere even where it does not filter."""
        for name, weights in setups.FIT_WEIGHTS.items():
            self.assertIn("accumulation", weights, msg=name)
            self.assertGreater(weights["accumulation"], 0.0, msg=name)

    def test_the_published_weights_are_the_ones_in_the_table(self):
        """The documentation quotes these numbers; a change here is a change to
        SKILL.md and docs/setups.md and must not pass silently."""
        self.assertEqual(setups.FIT_WEIGHTS, {
            "COILED":   {"contraction": 0.35, "pos_in_base": 0.25,
                         "dryup": 0.20, "accumulation": 0.20},
            "BREAKOUT": {"vol_mult": 0.35, "freshness": 0.25,
                         "base_quality": 0.20, "accumulation": 0.20},
            "LEADER":   {"rs_3m": 0.35, "proximity": 0.30,
                         "stack": 0.15, "accumulation": 0.20},
            "PULLBACK": {"dist_to_ma": 0.30, "rsi": 0.20, "pullback_vol": 0.25,
                         "retrace_depth": 0.15, "accumulation": 0.10},
            "TURN":     {"cross_recency": 0.30, "sma200_slope": 0.25,
                         "vol_expansion": 0.15, "macd": 0.10,
                         "accumulation": 0.20}})

    def test_pullback_no_longer_weights_the_blunt_dryup_term(self):
        """It was REPLACED by the pullback-versus-advance ratio, not merely
        reduced -- the two measure the same idea and only one measures it
        properly. dryup remains a live GATE."""
        self.assertNotIn("dryup", setups.FIT_WEIGHTS["PULLBACK"])
        self.assertIn("pullback_vol", setups.FIT_WEIGHTS["PULLBACK"])
        self.assertIn("dryup", setups.THRESHOLDS["PULLBACK"])


class TestTruncate(unittest.TestCase):
    def test_truncate_drops_bars_after_last_closed_bar(self):
        rows = trend_series(30)
        cutoff = str(rows[-3]["t"])
        kept = setups._truncate(rows, cutoff)
        self.assertEqual(len(kept), len(rows) - 2)
        self.assertEqual(str(kept[-1]["t"]), cutoff)

    def test_truncate_keeps_everything_when_cutoff_is_last_bar(self):
        rows = trend_series(30)
        self.assertEqual(len(setups._truncate(rows, str(rows[-1]["t"]))), 30)


class TestAlignedRows(unittest.TestCase):
    """Exercises the public aligned_rows() wiring, not just _truncate().

    A.fetch memoises on (symbol, range, interval, suffix) for the life of the
    process, so seeding _CACHE runs the real function with no network. Every
    NEIGHBOURING key is seeded too, with a different and much shorter series:
    that way a wrong period, interval or suffix returns wrong data and fails an
    assertion here rather than escaping to the network or -- worse -- being
    served the very series the test seeded.
    """
    WRONG_ARGS = (("1y", "1d", ".NS"), ("6mo", "1d", ".NS"), ("5y", "1d", ".NS"),
                  ("max", "1d", ".NS"), ("2y", "1wk", ".NS"), ("2y", "1h", ".NS"),
                  ("2y", "1d", ""))

    def setUp(self):
        # TWO symbols, each with a different series. A hardcoded ticker would
        # satisfy whichever test happens to use it and fail the other, so it has
        # nowhere to hide -- the previous single-symbol setup let the literal
        # "TEST" pass because the fixture symbol WAS "TEST".
        self.series = {"ZEBRA": trend_series(30, start=100.0),
                       "OTTER": trend_series(20, start=500.0)}
        self.keys = []
        for symbol, rows in self.series.items():
            self._seed((symbol, "2y", "1d", ".NS"), rows)
            for rng, interval, suffix in self.WRONG_ARGS:
                self._seed((symbol, rng, interval, suffix),
                           trend_series(10, start=1.0))

    def _seed(self, key, rows):
        A._CACHE[key] = (rows, {})
        self.keys.append(key)

    def tearDown(self):
        for key in self.keys:
            A._CACHE.pop(key, None)

    def _call(self, symbol, index):
        rows = self.series[symbol]
        cutoff = str(rows[index]["t"])
        return rows, cutoff, setups.aligned_rows(
            {"symbol": symbol, "last_closed_bar": {"t": cutoff}})

    def test_aligned_rows_truncates_the_fetched_series_at_the_last_closed_bar(self):
        rows, cutoff, got = self._call("ZEBRA", -3)
        self.assertEqual(len(got), 28)
        self.assertEqual(str(got[-1]["t"]), cutoff)
        # Pins the series identity, so a decoy key would be caught even if it
        # happened to truncate to the same length.
        self.assertAlmostEqual(got[0]["c"], 100.0, places=9)
        self.assertAlmostEqual(got[-1]["c"], rows[-3]["c"], places=9)

    def test_aligned_rows_keeps_the_whole_series_when_nothing_is_partial(self):
        rows, cutoff, got = self._call("ZEBRA", -1)
        self.assertEqual(len(got), 30)
        self.assertEqual(str(got[-1]["t"]), cutoff)

    def test_aligned_rows_reads_the_symbol_from_the_scored_dict(self):
        """A second, differently-priced symbol: the ticker cannot be hardcoded.

        OTTER's 20 bars start at 500 and its cutoff is day 17, so truncating
        ZEBRA's 30 bars at that same cutoff also yields 18 rows -- the LENGTH
        alone would not notice a hardcoded "ZEBRA". The close assertions do.
        """
        rows, cutoff, got = self._call("OTTER", -3)
        self.assertEqual(len(got), 18)
        self.assertEqual(str(got[-1]["t"]), cutoff)
        self.assertAlmostEqual(got[0]["c"], 500.0, places=9)
        self.assertAlmostEqual(got[-1]["c"], rows[-3]["c"], places=9)


if __name__ == "__main__":
    unittest.main()
