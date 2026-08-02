"""Synthetic OHLC builders. Rows match analyze.fetch()'s shape exactly:
{"t": datetime.date, "o","h","l","c": float, "v": int}."""
import datetime as dt


def bar(day, o, h, l, c, v=1_000_000):
    return {"t": dt.date(2026, 1, 1) + dt.timedelta(days=day),
            "o": o, "h": h, "l": l, "c": c, "v": v}


def flat_series(n, price=100.0, spread=1.0, vol=1_000_000):
    """n bars of constant price with a fixed daily range."""
    return [bar(i, price, price + spread, price - spread, price, vol)
            for i in range(n)]


def trend_series(n, start=100.0, step=1.0, spread=1.0, vol=1_000_000):
    """n bars rising by `step` each bar."""
    rows = []
    for i in range(n):
        p = start + i * step
        rows.append(bar(i, p, p + spread, p - spread, p, vol))
    return rows


def base_rows(n=120, hi=110.0, lo=100.0, last_high=None, vol=1_000_000):
    """A base spanning exactly lo..hi, ending on a candidate breakout bar.

    Every bar but the last spans the FULL lo..hi range, so the highest high over
    any window that excludes the final bar is exactly `hi` whatever base length
    a fixture declares -- which lets `o["range"]` and `ctx["rows"]` agree without
    the test having to compute the slice itself.

    The last bar is the candidate breakout bar. Its high is `last_high`
    (default hi + 8), ABOVE the base, which is the universal live case:
    analyze.consolidation() ends its window on that bar, so o["range"]["hi"]
    is that bar's own high and no close can ever exceed it.
    """
    mid = (hi + lo) / 2
    rows = [bar(i, mid, hi, lo, mid, vol) for i in range(n - 1)]
    top = hi + 8.0 if last_high is None else last_high
    rows.append(bar(n - 1, mid, top, mid, top - 1.0, vol))
    return rows


def contracting_series(widths, price=100.0, bars_per_window=5, vol=1_000_000):
    """One window of `bars_per_window` bars per entry in `widths`, each window
    having that half-range around `price`. Used for the COILED contraction test."""
    rows, day = [], 0
    for w in widths:
        for _ in range(bars_per_window):
            rows.append(bar(day, price, price + w, price - w, price, vol))
            day += 1
    return rows


def close_at_high_series(halves, price=100.0, bars_per_window=4, vol=1_000_000):
    """One window per entry in `halves`, each bar closing AT its own high.

    contracting_series puts the close exactly on the window midpoint, which
    makes "normalise by (hi+lo)/2" and "normalise by mean close" produce the
    same number -- a wrong implementation would survive. Here the mean close is
    price+half while the midpoint is price, so the two disagree.
    """
    rows, day = [], 0
    for h in halves:
        for _ in range(bars_per_window):
            rows.append(bar(day, price, price + h, price - h, price + h, vol))
            day += 1
    return rows


def turnover_series_cr(values_cr, price=100.0, open_ratio=0.9):
    """One bar per entry: bar i's turnover (close x volume) is values_cr[i] crore,
    IN THE ORDER GIVEN.

    Passing an unsorted order is the point -- every earlier turnover fixture was
    already ascending (flat, monotone, or spike-last), which makes the sort inside
    turnover_cr a no-op that no test can see. Open (0.9x), high (1.05x) and low
    (0.85x) all sit off the close, so reading the wrong price field changes the
    answer too.
    """
    rows = []
    for i, cr in enumerate(values_cr):
        rows.append(bar(i, price * open_ratio, price * 1.05, price * 0.85,
                        price, int(cr * 1e7 / price)))
    return rows


def turnover_ladder(n, first_cr=1, price=100.0, open_ratio=0.9):
    """n bars whose turnover (close x volume) climbs 1 crore per bar.

    Bar i has a turnover of exactly `first_cr + i` crore, so the median over any
    contiguous slice is known in closed form and an EVEN-length window has two
    DISTINCT middle values -- `(a+b)/2` and `b` differ, which a constant-turnover
    fixture can never show. Pass an ODD n to reach the other arm of that ternary.
    """
    return turnover_series_cr([first_cr + i for i in range(n)], price, open_ratio)


def ud_series(pattern, price=100.0, step=1.0, up_vol=2_000_000,
              down_vol=1_000_000, flat_vol=9_000_000, anchor_vol=7_000_000):
    """Bars whose close direction follows `pattern`, with a DIFFERENT volume on
    up bars, down bars and unchanged bars.

    `pattern` is a string of "u" (close above the previous close), "d" (below)
    and "f" (flat). A leading anchor bar carries the starting close; it has no
    predecessor and so belongs to neither side of the ratio.

    Every volume is deliberately distinct, because a constant-volume fixture
    cannot tell a correct up/down ratio from a wrong one -- with one volume the
    ratio collapses to a count of up bars over down bars and a swapped numerator
    and denominator merely inverts a number the test would have to know anyway.
    Here up_vol != down_vol, so the swap is visible; flat_vol and anchor_vol are
    the largest of the four, so a bar wrongly credited to either side moves the
    answer by more than any rounding.
    """
    rows = [bar(0, price, price + 1.0, price - 1.0, price, anchor_vol)]
    c = price
    for i, ch in enumerate(pattern, start=1):
        prev = c
        if ch == "u":
            c, v = prev + step, up_vol
        elif ch == "d":
            c, v = prev - step, down_vol
        else:
            v = flat_vol
        rows.append(bar(i, prev, max(prev, c) + 1.0, min(prev, c) - 1.0, c, v))
    return rows


CMF_VOLS = (1_000_000, 2_000_000, 3_000_000, 4_000_000, 5_000_000)


def cmf_series(positions, price=100.0, span=2.0, vols=None, spans=None):
    """Bars whose CLOSE POSITION INSIDE ITS OWN RANGE is set per bar.

    `positions[i]` is where bar i closes between its own low (0.0) and its own
    high (1.0), so the Chaikin multiplier for that bar is exactly `2p - 1`:
    1.0 -> +1, 0.5 -> 0, 0.0 -> -1.

    THREE blind spots this exists to close, all of them present in every other
    fixture in this file:

    * flat_series, trend_series and contracting_series close every bar on its
      own MIDPOINT, so every multiplier is 0, both buckets are empty and
      ud_weighted returns None whatever the implementation does.
    * close_at_high_series closes every bar at its high, so every multiplier is
      +1 and the down bucket is empty -- again None, and a swapped numerator and
      denominator is invisible.
    * a series where every close sits at the SAME relative position gives every
      bar the same multiplier, so the ratio collapses to a volume total and a
      sign-flipped multiplier merely inverts it.

    Volumes default to five DISTINCT values cycling, so a bar credited to the
    wrong bucket moves the answer rather than cancelling out, and `up/down`
    cannot be confused with `down/up`.

    `spans` overrides the intraday half-range per bar. A 0 entry builds a
    genuine ZERO-RANGE bar (h == l == c), which is the division ud_weighted has
    to guard.
    """
    v = CMF_VOLS if vols is None else vols
    rows = []
    for i, p in enumerate(positions):
        s = span if spans is None else spans[i]
        hi, lo = price + s, price - s
        c = lo + (hi - lo) * p if s else price
        rows.append(bar(i, price, hi, lo, c, v[i % len(v)]))
    return rows


def gapped_tr_series(n=40, start=100.0, vol=1_000_000):
    """Bars whose true range varies bar to bar AND that gap in both directions.

    Two separate blind spots in the older ATR fixtures:

    * trend_series and varying_tr_series hold the range CONSTANT across the first
      14 bars, so the Wilder seed `sum(trs[:n])/n` equals `trs[0]` exactly and the
      averaging in the seed is invisible. Here the intraday span cycles 1..5, so
      the seed window contains five different true ranges.
    * Neither fixture ever gaps, so `h - l` is always the largest of the three TR
      candidates and the two gap terms of the max() are dead. Here the open jumps
      -4 / 0 / +4 off the previous close in rotation, and on the narrow-span bars
      a gap term is strictly the largest -- so all three arms win somewhere.

    The close is deliberately parked off the bar's midpoint, alternating near the
    low and near the high, so the next bar's gap terms stay asymmetric.
    """
    rows, c = [], start
    for i in range(n):
        span = 1.0 + (i % 5)            # 1..5, varies inside the seed window
        o = c + ((i % 3) - 1) * 4.0     # gap down / flat / gap up, in rotation
        h, l = o + span, o - span
        c = l + span * (0.25 if i % 2 else 1.75)   # off-midpoint close
        rows.append(bar(i, o, h, l, c, vol))
    return rows


def varying_tr_series(n=50):
    """n bars with high TR early, low TR late.

    Essential for ATR test discrimination: if the last 14 TRs are all ~1.0
    but Wilder smoothing has 'memory' of earlier 10.0 TRs, the final ATR
    will be > 1.0 (still discounting old values, not converged to new ones).
    A simple rolling mean of the last 14 TRs would be ~1.0. This fixture
    ensures only true Wilder smoothing passes the engine-equality test.
    """
    rows = []
    # First 20 bars: high volatility → TR ≈ 10
    p = 100.0
    for i in range(20):
        rows.append(bar(i, p, p + 5, p - 5, p, 1_000_000))
        p += 1  # slight uptrend, no gaps
    # Next 30 bars: tight range → TR ≈ 0.5-1.0
    for i in range(20, 50):
        rows.append(bar(i, p, p + 0.5, p - 0.5, p, 1_000_000))
        p += 0.1  # tiny uptrend, no gaps
    return rows


def divergent_values(n=100):
    """Non-monotonic float series for SMA/EMA discrimination.

    On linear series like [1..100], steady-state EMA and trailing SMA both
    approach current_value - (n-1)/2, converging to the same value and
    preventing algorithm discrimination. This fixture has high values early
    then drops sharply: [50]*80 + [1]*20. Now
    - At the end, last 20 values are all 1
    - SMA of last 20 = 1 (pure average of 1s)
    - EMA ≈ 7-8 (has lag memory of 50s, decays slowly toward 1)
    This makes EMA and SMA provably diverge significantly at the final point.
    """
    return [50.0] * 80 + [1.0] * 20
