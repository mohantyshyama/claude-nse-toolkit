"""The six bullish setups.

Every predicate is a pure function of the dict analyze.compute() returns. It
READS engine fields; it never recalculates one. The only exceptions are the two
series helpers below, which exist because compute() returns SMA and ATR as
scalars and two setups need history. Both are pinned by tests to reproduce
A.sma and A.atr exactly, so they cannot drift into a second implementation.
"""
from engine import A


# ----------------------------------------------------------- derived series

def _truncate(rows, cutoff_iso):
    """Keep bars up to and including the engine's last CLOSED bar.

    compute() discards a partial in-progress bar before computing anything;
    fetch() still returns it. Deriving a series from raw fetch output would put
    it one bar ahead of every scalar the engine reports -- enough to misdate a
    golden cross or shift the ATR percentile. compute() stores the cutoff as an
    ISO date string, so a lexicographic compare is correct.
    """
    return [r for r in rows if str(r["t"]) <= cutoff_iso]


def aligned_rows(o):
    """Daily bars for a scored symbol, aligned to its last closed bar.

    A._CACHE already holds this series from compute(), so this is a cache hit
    and costs no network.
    """
    rows, _ = A.fetch(o["symbol"], "2y", "1d")
    return _truncate(rows, o["last_closed_bar"]["t"])


def sma_series(values, n):
    """Rolling simple mean, aligned to values[n-1:]. Last element equals A.sma."""
    if len(values) < n:
        return []
    run = sum(values[:n])
    out = [run / n]
    for i in range(n, len(values)):
        run += values[i] - values[i - n]
        out.append(run / n)
    return out


def atr_series(rows, n=14):
    """Wilder ATR at every bar. Last element equals A.atr(rows, n).

    Seeded with the mean of the first n true ranges then smoothed, exactly as
    A.atr does -- emitting the intermediate values it discards.
    """
    if len(rows) < n + 2:
        return []
    trs = [max(rows[i]["h"] - rows[i]["l"],
               abs(rows[i]["h"] - rows[i - 1]["c"]),
               abs(rows[i]["l"] - rows[i - 1]["c"]))
           for i in range(1, len(rows))]
    a = sum(trs[:n]) / n
    out = [a]
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n
        out.append(a)
    return out


MIN_BARS_PER_WINDOW = 4    # below this a window is noise, and window_widths
                           # returns [] rather than measuring it


def window_widths(rows, n=3):
    """Split `rows` into n consecutive equal windows; return each window's range
    as a percentage of its own midpoint.

    Normalising by the window's own midpoint lets windows sitting at different
    price levels be compared -- an absolute range shrinks simply by the stock
    falling, which is not a contraction.
    """
    size = len(rows) // n
    if size < MIN_BARS_PER_WINDOW:
        return []
    out = []
    for i in range(n):
        chunk = rows[i * size:(i + 1) * size] if i < n - 1 else rows[(n - 1) * size:]
        hi = max(r["h"] for r in chunk)
        lo = min(r["l"] for r in chunk)
        mid = (hi + lo) / 2
        out.append((hi - lo) / mid * 100 if mid else 0.0)
    return out


def turnover_cr(rows, n=50):
    """Median daily turnover over the last n bars, in rupees crore.

    Median, not mean: one delivery-day spike should not qualify a name that is
    untradeable on every other day.
    """
    vals = sorted(r["c"] * r["v"] for r in rows[-n:])
    if not vals:
        return 0.0
    mid = len(vals) // 2
    med = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
    return med / 1e7


# ------------------------------------------------------------- setup registry

SETUPS = ("COILED", "BREAKOUT", "LEADER", "PULLBACK", "TURN")

# Windows match_coiled splits its base into. FOUR, not three: three windows
# give only two consecutive comparisons, so the strict contraction threshold of
# 3 could never be met and strict COILED matched nothing at all.
#
# ARITHMETIC TIE -- do not change one of these without the other:
#   THRESHOLDS["COILED"]["min_bars"] >= COILED_WINDOWS * MIN_BARS_PER_WINDOW
# window_widths returns [] when any window is shorter than MIN_BARS_PER_WINDOW,
# and match_coiled returns None on a short widths list. A min_bars below
# 4 * 4 = 16 therefore makes COILED match NOTHING for bases in the gap --
# silently, with no rejection anyone can see. 16 is the true floor for four
# windows; strict's 20 gives five bars per window and stays a genuine subset.
# TestCoiledWindowArithmetic derives both numbers from the code and fails if
# this tie is ever broken.
COILED_WINDOWS = 4

# (loosened, strict) per spec section 3. Strict must always be a SUBSET of
# loosened -- Task 9's test asserts it across the live universe.
THRESHOLDS = {
    "COILED": {"min_bars": (16, 20), "atr_pctile": (0.333, 0.25),
               "contractions": (2, 3), "pos_in_base": (0.50, 0.60),
               "dryup": (1.0, 0.9), "sma50_rising": (False, True)},
    "BREAKOUT": {"min_bars": (12, 15), "vol_mult": (1.5, 2.0),
                 "max_extension_pct": (12.0, 8.0), "strict_ma_stack": (False, True)},
    "LEADER": {"max_from_high_pct": (10.0, 5.0), "rs_1m_floor": (-2.0, 0.0),
               "rsi_lo": (50.0, 55.0), "rsi_hi": (88.0, 85.0),
               "atr_pctile_hi": (0.90, 0.85), "max_run_pct": (10.0, 8.0),
               "strict_ma_stack": (False, True)},
    "PULLBACK": {"ma_dist_pct": (3.0, 2.0), "atr_mult_to_support": (1.2, 1.0),
                 "swing_margin_atr": (1.0, 1.5),
                 "rsi_lo": (38.0, 40.0), "rsi_hi": (62.0, 58.0),
                 "dryup": (1.1, 1.0), "thrust_bars": (8, 10)},
    "TURN": {"cross_bars": (45, 30), "rsi_lo": (48.0, 50.0),
             "off_low_pct": (12.0, 20.0)},
}


def T(name, key, strict):
    lo, st = THRESHOLDS[name][key]
    return st if strict else lo


def band(value, cuts):
    """Map a value to a 0-10 sub-score. `cuts` is [(threshold, score), ...] in
    the order tested; the first satisfied entry wins, else 0."""
    for threshold, score in cuts:
        if value >= threshold:
            return score
    return 0.0


def band_desc(value, cuts):
    """Same as band() but for metrics where LOWER is better."""
    for threshold, score in cuts:
        if value <= threshold:
            return score
    return 0.0


def liquid(ctx, min_cr):
    return turnover_cr(ctx["rows"], 50) >= min_cr


# ------------------------------------------------------------- rejection funnel

def _reject(diag, step, label):
    """Record the condition that rejected this name, then return None.

    INSTRUMENTATION ONLY. It always returns None, whatever `diag` is, so a
    predicate's matched/unmatched verdict is byte-identical with and without a
    diagnostic dict -- the funnel can never change what the screen matches.

    Each predicate returns at the FIRST condition a name fails, so a name is
    counted at exactly one gate per setup and the number that reached a later
    gate is recoverable by subtraction. `step` is that gate's position in the
    predicate, so the report can print the funnel in the order the predicate
    applies it rather than sorted by whichever gate happened to reject most.

    `label` names the condition a PASSING name satisfies, so "N failed <label>"
    and "N reached <label>" both read correctly.
    """
    if diag is not None:
        _, seen = diag.get(label, (step, 0))
        diag[label] = (step, seen + 1)
    return None


def _no_down_thrust(o, bars):
    """True if no DOWN-thrust among the last `bars` sessions.

    compute() labels thrusts directionally, so a name selling off on 3x volume
    cannot dress up as strength. Read the label; never re-derive it.
    """
    recent = [str(r["t"]) for r in (o.get("_rows") or [])[-bars:]]
    if not recent:
        return True
    return not any(t["dir"] == "down" and t["date"] in recent
                   for t in o["volume"]["thrusts"])


# -------------------------------------------------------------------- COILED

def match_coiled(o, ctx, strict=False, diag=None):
    """Volatility contraction inside a base, pre-breakout. Spec section 3.1."""
    rng, ma = o["range"], o["ma"]
    if rng["bars"] < T("COILED", "min_bars", strict):
        return _reject(diag, 1, "a base of at least %d bars"
                       % T("COILED", "min_bars", strict))
    if ctx["atr_pctile"] > T("COILED", "atr_pctile", strict):
        return _reject(diag, 2, "volatility in the bottom %d%% of its own 6 months"
                       % round(T("COILED", "atr_pctile", strict) * 100))

    # Four windows -> three consecutive comparisons, so (2, 3) is satisfiable in
    # both modes. The slice floor is the same arithmetic tie as min_bars: never
    # ask window_widths for windows it cannot fill. See COILED_WINDOWS.
    #
    # Mutation note: `floor` is DEFENSIVE, not load-bearing -- the min_bars guard
    # above already forces rng["bars"] >= 16, so max() always returns rng["bars"]
    # and writing `12` here is an equivalent mutant that no test can kill. It
    # earns its place by staying correct if min_bars is ever lowered; the tie
    # test guards that case directly.
    floor = COILED_WINDOWS * MIN_BARS_PER_WINDOW
    widths = window_widths(ctx["rows"][-max(rng["bars"], floor):], COILED_WINDOWS)
    if len(widths) != COILED_WINDOWS:
        return _reject(diag, 3, "a base that splits into %d measurable windows"
                       % COILED_WINDOWS)
    contractions = sum(1 for i in range(1, len(widths)) if widths[i] < widths[i - 1])
    if contractions < T("COILED", "contractions", strict):
        return _reject(diag, 4, "at least %d of %d windows narrower than the last"
                       % (T("COILED", "contractions", strict), COILED_WINDOWS - 1))

    # NET contraction, first window to last. The consecutive count above is a
    # count of local narrowings and a saw-tooth satisfies it: OIL measured
    # 6.48 / 5.62 / 4.98 / 6.58 -- two of the three comparisons narrower, and a
    # base that ended WIDER than it began. It ranked COILED #11 with the report's
    # own Contraction column reading 1.01; ALKEM ranked #7 at 1.205. A base that
    # is no tighter at the end than at the start is not coiling, whatever the
    # path in between looked like.
    #
    # Applied in BOTH modes, though it can only ever reject in loosened: strict
    # asks for 3 of 3 consecutive narrowings, which forces widths[0] > widths[1]
    # > widths[2] > widths[3] and so implies this outright. It is written
    # unconditionally anyway -- the two modes must not be able to disagree about
    # what COILED MEANS if the contraction count is ever loosened again.
    if widths[-1] >= widths[0]:
        return _reject(diag, 5, "a base narrower at the end than at the start")

    span = rng["hi"] - rng["lo"]
    pos = (o["price"] - rng["lo"]) / span if span else 0.0
    if pos < T("COILED", "pos_in_base", strict):
        return _reject(diag, 6, "price in the top %d%% of the base"
                       % round((1 - T("COILED", "pos_in_base", strict)) * 100))

    if not ma["sma50"] or o["price"] <= ma["sma50"]:
        return _reject(diag, 7, "price above the 50-day average")
    if not ma["sma200"] or o["price"] <= ma["sma200"]:
        return _reject(diag, 8, "price above the 200-day average")
    if not ctx["sma200_rising"]:
        return _reject(diag, 9, "a rising 200-day average")
    if T("COILED", "sma50_rising", strict) and not ctx["sma50_rising"]:
        return _reject(diag, 10, "a rising 50-day average")

    dryup = o["volume"]["dryup_ratio"]
    if dryup is None or dryup >= T("COILED", "dryup", strict):
        return _reject(diag, 11, "volume dried up below %.2fx its own average"
                       % T("COILED", "dryup", strict))

    # First-to-last window, whatever COILED_WINDOWS is: widths[-1], not widths[2].
    # The net-contraction gate above guarantees this ratio is < 1.0 for every
    # name that reaches here -- the Contraction column can no longer print 1.01.
    #
    # Mutation note: the `if widths[0]` fallback is now DEFENSIVE and
    # unreachable, not load-bearing. widths[0] == 0 makes `widths[-1] >=
    # widths[0]` true for any non-negative width, so a zero first window is
    # rejected at the net-contraction gate and never reaches this line. Kept as
    # a division guard in case that gate is ever reordered.
    return {"contraction": widths[-1] / widths[0] if widths[0] else 1.0,
            "pos_in_base": pos, "dryup": dryup, "widths": widths}


def fit_coiled(ev):
    """Contraction 40% / position in base 30% / dry-up 30%."""
    c = band_desc(ev["contraction"], [(0.50, 10), (0.65, 8), (0.80, 6), (1.00, 4)])
    p = band(ev["pos_in_base"], [(0.85, 10), (0.70, 8), (0.50, 6)])
    d = band_desc(ev["dryup"], [(0.70, 10), (0.85, 8), (1.00, 6)])
    return round(0.40 * c + 0.30 * p + 0.30 * d, 2)


# ------------------------------------------------------------------ BREAKOUT

CONFIRMED_VOL_MULT = 2.0   # stock_analyser's trigger definition; below this the
                           # row is flagged "volume light" rather than dropped.


def base_range_before_last_bar(rows, bars):
    """(high, low) of the consolidation base, EXCLUDING the last closed bar.

    Both numbers come off the same slice, because both describe the same thing:
    the base as it stood BEFORE the candidate bar. The high is what a breakout
    has to clear; the width is how tight the base it broke out of was.

    Neither is o["range"]. analyze.consolidation() measures its segment over the
    `bars` bars ENDING on the last closed bar, so o["range"] is stretched by the
    breakout bar itself -- see base_high_before_last_bar for why that made the
    gate unsatisfiable, and fit_breakout for why it made the base-quality
    penalty land hardest on the strongest breakouts.

    Slice boundaries, stated explicitly because they are the whole fix:

        the base rng describes   rows[-bars:]     (ends ON the last closed bar)
        the base before it       rows[-bars:-1]   (same start, one bar shorter)

    The START is deliberately not pushed back to keep the length at `bars`
    (`rows[-(bars+1):-1]`): when consolidation() anchors to a volume thrust,
    rows[-(bars+1)] IS that thrust bar, the move it excludes on purpose as the
    one that created the range. Pulling it back in would lift the base high on
    exactly the names this predicate exists to find.

    Returns None when there is no prior bar to measure -- the caller must treat
    that as "cannot judge", never as a pass.
    """
    if bars < 2 or len(rows) < 2:
        return None
    base = rows[-bars:-1]
    if not base:
        return None
    return max(r["h"] for r in base), min(r["l"] for r in base)


def base_high_before_last_bar(rows, bars):
    """Highest high of the consolidation base, EXCLUDING the last closed bar.

    This is the number a breakout has to clear, and it is NOT o["range"]["hi"].
    analyze.consolidation() measures its segment over the `bars` bars ENDING on
    the last closed bar, so rng["hi"] includes the high of the very bar the
    breakout fires on -- and since a close can never exceed its own bar's high,
    `price > rng["hi"]` is unsatisfiable. It measured 0 of 500 on live data.

    Slice boundaries, stated explicitly because they are the whole fix:

        the base rng describes   rows[-bars:]     (ends ON the last closed bar)
        the base to clear        rows[-bars:-1]   (same start, one bar shorter)

    The START is deliberately not pushed back to keep the length at `bars`
    (`rows[-(bars+1):-1]`): when consolidation() anchors to a volume thrust,
    rows[-(bars+1)] IS that thrust bar, the move it excludes on purpose as the
    one that created the range. Pulling it back in would lift the base high on
    exactly the names this predicate exists to find.

    Returns None when there is no prior bar to measure -- the caller must treat
    that as "cannot judge", never as a pass.

    A thin projection of base_range_before_last_bar so the two numbers can never
    be taken off different slices.
    """
    base = base_range_before_last_bar(rows, bars)
    return None if base is None else base[0]


def match_breakout(o, ctx, strict=False, diag=None):
    """A base breakout on the day it fires. Spec section 3.2."""
    rng, ma, px = o["range"], o["ma"], o["price"]
    if rng["bars"] < T("BREAKOUT", "min_bars", strict):
        return _reject(diag, 1, "a base of at least %d bars"
                       % T("BREAKOUT", "min_bars", strict))

    base = base_range_before_last_bar(ctx.get("rows") or [], rng["bars"])
    if base is None:
        return _reject(diag, 2, "enough bar history to measure the base")
    base_hi, base_lo = base
    if px <= base_hi:
        return _reject(diag, 3, "a close above the base high, breakout bar excluded")

    avg20 = o["volume"]["avg20"]
    if not avg20:
        return _reject(diag, 4, "a usable 20-day average volume")
    vol_mult = o["last_closed_bar"]["v"] / avg20
    if vol_mult < T("BREAKOUT", "vol_mult", strict):
        return _reject(diag, 5, "volume at least %.1fx the 20-day average"
                       % T("BREAKOUT", "vol_mult", strict))

    above = (px - base_hi) / base_hi * 100
    if above > T("BREAKOUT", "max_extension_pct", strict):
        return _reject(diag, 6, "no more than %.0f%% above the base high"
                       % T("BREAKOUT", "max_extension_pct", strict))

    if not ma["sma200"] or px <= ma["sma200"]:
        return _reject(diag, 7, "price above the 200-day average")
    # Loosened asks for `price > sma200` and nothing more -- the guard above IS
    # the whole loosened test. The old second arm, `sma50 and (sma50 > sma200 or
    # px > sma50)`, was a tautology: px > sma200 already, so sma50 <= sma200
    # forces px > sma50. It only ever rejected a MISSING sma50, which is a data
    # gap rather than a trend judgement. Strict keeps the full stack.
    if T("BREAKOUT", "strict_ma_stack", strict):
        if not ma["sma50"] or not (px > ma["sma50"] > ma["sma200"]):
            return _reject(diag, 8, "price above a 50-day above the 200-day")

    # tightness is measured on the SAME prior-bar base as the gate, not on
    # o["range"]. The engine's range ends on the breakout bar, so a powerful
    # breakout widens its own base: it prints a tall bar, o["range"]["hi"] rises
    # to that bar's high, the span balloons, and fit_breakout's `tightness > 8`
    # test docks 20% off base quality. The stronger the thrust the likelier the
    # penalty -- exactly backwards for a term that is supposed to say "this
    # broke out of a tight base". Measured before the breakout bar, the number
    # describes the base the name actually broke out of, and today's move
    # cannot change it.
    span = base_hi - base_lo
    return {"vol_mult": vol_mult, "pct_above_base": above,
            "base_bars": rng["bars"],
            "tightness": span / base_hi * 100 if base_hi else 0.0,
            "volume_light": vol_mult < CONFIRMED_VOL_MULT}


def fit_breakout(ev):
    """Volume multiple 40% / freshness 30% / base quality 30%."""
    v = band(ev["vol_mult"], [(3.0, 10), (2.5, 9), (2.0, 8), (1.75, 6), (1.5, 4)])
    f = band_desc(ev["pct_above_base"], [(2.0, 10), (5.0, 8), (8.0, 6), (12.0, 4)])
    b = band(ev["base_bars"], [(30, 10), (20, 8), (15, 6), (12, 4)])
    if ev["tightness"] > 8.0:
        b *= 0.8
    return round(0.40 * v + 0.30 * f + 0.30 * b, 2)


# -------------------------------------------------------------------- LEADER

def match_leader(o, ctx, strict=False, diag=None):
    """Established relative-strength leadership near highs. Spec section 3.3."""
    ma, px, rs = o["ma"], o["price"], ctx["rs"]
    if rs.get("3m") is None or rs.get("1m") is None:
        # RS is the definition; no baseline, no call.
        return _reject(diag, 1, "a relative-strength baseline to measure against")
    # The two relative-strength floors are reported separately -- they are one
    # `or` in behaviour but two different market statements in a funnel.
    if rs["3m"] <= 0:
        return _reject(diag, 2, "3-month relative strength above the Nifty")
    if rs["1m"] < T("LEADER", "rs_1m_floor", strict):
        return _reject(diag, 3, "1-month relative strength above %+.1f"
                       % T("LEADER", "rs_1m_floor", strict))

    from_high = (o["hi52"] - px) / o["hi52"] * 100 if o["hi52"] else 100.0
    if from_high > T("LEADER", "max_from_high_pct", strict):
        return _reject(diag, 4, "within %.0f%% of the 52-week high"
                       % T("LEADER", "max_from_high_pct", strict))

    if not (ma["sma20"] and ma["sma50"] and ma["sma200"]):
        return _reject(diag, 5, "20-, 50- and 200-day averages all available")
    if T("LEADER", "strict_ma_stack", strict):
        if not (px > ma["sma20"] > ma["sma50"] > ma["sma200"]):
            return _reject(diag, 6, "price above a fully stacked 20/50/200-day")
    elif not (px > ma["sma50"] > ma["sma200"] and px > ma["sma20"]):
        return _reject(diag, 6, "price above the 20-day, and a 50-day above the "
                                "200-day")

    r = o["rsi"]["daily"]
    if r is None or not (T("LEADER", "rsi_lo", strict) <= r <= T("LEADER", "rsi_hi", strict)):
        return _reject(diag, 7, "a daily RSI between %.0f and %.0f"
                       % (T("LEADER", "rsi_lo", strict), T("LEADER", "rsi_hi", strict)))

    # Extension guard. RSI and extension measure different things and the RSI
    # ceiling does not stand in for this one: RSI is the ratio of up-closes to
    # down-closes, so a name can grind to 80 barely moving, or add 13% in six
    # sessions at 70. LAURUSLABS scored Fit 10.00 / BUY NOW at RSI 81.8 --
    # comfortably inside the 88 ceiling -- with ATR at the 98th percentile of its
    # own six months, +13.4% in six sessions, and the 1.5x ATR stop the report
    # prints sitting 3.7% away on a stock moving ~3% a day. The stop was inside
    # the noise. Its leadership was real; the ENTRY was a chase, and the screen
    # said BUY NOW.
    #
    # Two arms because they catch different chases: the ATR percentile catches a
    # name trading at its own most violent, whatever it has done lately, and the
    # 5-session run catches a name that gapped away from its base while its ATR
    # has not caught up yet. rsi_hi stays at 88/85 -- this is not a second RSI.
    if ctx["atr_pctile"] > T("LEADER", "atr_pctile_hi", strict):
        return _reject(diag, 8, "volatility outside the top %d%% of its own "
                                "6 months"
                       % round((1 - T("LEADER", "atr_pctile_hi", strict)) * 100))
    # None means the series is too short to measure a run at all, or its
    # baseline close was zero -- which cannot happen to a name that got this
    # far, since the 200-day average guard above needs far more bars than
    # RUN_BARS + 1. It abstains rather than rejecting: a data gap is not a
    # chase. The guard is against the TypeError `None > 10.0` raises, NOT
    # against a falsy run -- `if run and ...` is an equivalent mutant here,
    # since 0.0 fails the comparison it would be skipping anyway.
    run = ctx.get("run_pct")
    if run is not None and run > T("LEADER", "max_run_pct", strict):
        return _reject(diag, 9, "no more than %.0f%% gained in the last "
                                "%d sessions"
                       % (T("LEADER", "max_run_pct", strict), RUN_BARS))

    if not _no_down_thrust(o, 10):
        return _reject(diag, 10, "no down-thrust in the last 10 sessions")

    return {"pct_from_high": from_high, "rs_1m": rs["1m"], "rs_3m": rs["3m"],
            "full_stack": bool(px > ma["sma20"] > ma["sma50"] > ma["sma200"])}


def fit_leader(ev):
    """Relative strength 3m 40% / proximity to high 35% / stack completeness 25%."""
    r = band(ev["rs_3m"], [(20.0, 10), (10.0, 8), (5.0, 6), (0.0, 4)])
    p = band_desc(ev["pct_from_high"], [(2.0, 10), (5.0, 8), (10.0, 6)])
    s = 10.0 if ev["full_stack"] else 7.0
    return round(0.40 * r + 0.35 * p + 0.25 * s, 2)


# ------------------------------------------------------------------ PULLBACK

def _below_recent_swing_high(o, px, atr_d, mult):
    """True when price sits at least `mult` ATR below the highest recent swing.

    The MAX of the recent pivots, not the latest one: a name printing new highs
    is above every pivot it has made, and taking only the most recent would let
    a stock that just cleared it read as "below a swing high" the moment the
    engine records a new pivot underneath the move.

    Returns False when there is no swing to measure against, or no ATR to
    measure with -- "cannot judge" closes the arm it guards, never opens it.
    compute() always supplies swing_highs, so this is a guard against a caller
    handing over a partial dict rather than a live condition.
    """
    swings = [s.get("px") for s in (o.get("swing_highs") or []) if s.get("px")]
    if not swings or not atr_d:
        return False
    return px <= max(swings) - mult * atr_d


def match_pullback(o, ctx, strict=False, diag=None):
    """Retracement into support inside an established uptrend. Spec section 3.4."""
    ma, px, gate = o["ma"], o["price"], o["entry_gate"]

    # Trend intact. sma200 rising is deliberately NOT parameterised by strict:
    # it is what separates a pullback in an uptrend from a falling knife.
    if not (ma["sma200"] and ma["sma50"]):
        return _reject(diag, 1, "50- and 200-day averages both available")
    # One `or` split three ways: "not in an uptrend" is three distinct findings.
    if px <= ma["sma200"]:
        return _reject(diag, 2, "price above the 200-day average")
    if ma["sma50"] <= ma["sma200"]:
        return _reject(diag, 3, "a 50-day average above the 200-day")
    if not ctx["sma200_rising"]:
        return _reject(diag, 4, "a rising 200-day average")

    dists = [abs(px - m) / m * 100 for m in (ma["sma20"], ma["sma50"]) if m]
    near_ma = min(dists) if dists else 999.0
    atr_d = o["atr"]["daily"]
    sup = gate.get("nearest_support")
    # The support arm carries an extra condition the moving-average arm does
    # not: price must also sit a meaningful distance BELOW a recent swing high.
    #
    # Without it the arm is not a pullback test at all. CHOLAFIN ranked
    # PULLBACK #1 having closed +4.29% at 1849.90, 1.3% under its 52-week high
    # on results -- 3.55% above its 20DMA, past PULLBACK's own 3.0% ceiling, so
    # the MA arm had already rejected it. It entered here: nearest_support was
    # the 20DMA 63.4 points away against a 1.2xATR allowance of 69.5. "Near
    # support" is trivially true for a name that has just run away from its
    # averages, because the average it ran away from IS the nearest support.
    #
    # The MA arm needs no such guard: being within 3% of the 20- or 50-day is
    # already a statement that price came back to something.
    near_sup = (atr_d and sup
                and abs(px - sup) <= T("PULLBACK", "atr_mult_to_support",
                                       strict) * atr_d
                and _below_recent_swing_high(
                    o, px, atr_d, T("PULLBACK", "swing_margin_atr", strict)))
    if near_ma > T("PULLBACK", "ma_dist_pct", strict) and not near_sup:
        return _reject(diag, 5, "price back within %.0f%% of the 20- or 50-day, "
                                "or within %.1f ATR of support and at least "
                                "%.1f ATR below a recent swing high"
                       % (T("PULLBACK", "ma_dist_pct", strict),
                          T("PULLBACK", "atr_mult_to_support", strict),
                          T("PULLBACK", "swing_margin_atr", strict)))

    if px <= ma["sma50"] * 0.97:
        return _reject(diag, 6, "price no more than 3% below the 50-day average")

    r = o["rsi"]["daily"]
    if r is None or not (T("PULLBACK", "rsi_lo", strict) <= r
                         <= T("PULLBACK", "rsi_hi", strict)):
        return _reject(diag, 7, "a daily RSI between %.0f and %.0f"
                       % (T("PULLBACK", "rsi_lo", strict),
                          T("PULLBACK", "rsi_hi", strict)))

    dryup = o["volume"]["dryup_ratio"]
    if dryup is None or dryup >= T("PULLBACK", "dryup", strict):
        return _reject(diag, 8, "volume dried up below %.2fx its own average"
                       % T("PULLBACK", "dryup", strict))
    if not _no_down_thrust(o, T("PULLBACK", "thrust_bars", strict)):
        return _reject(diag, 9, "no down-thrust in the last %d sessions"
                       % T("PULLBACK", "thrust_bars", strict))

    span = o["hi52"] - o["lo52"]
    retrace = (o["hi52"] - px) / span * 100 if span else 0.0
    return {"dist_to_ma_pct": near_ma, "rsi": r, "dryup": dryup,
            "retrace_pct": retrace}


def retrace_depth(x):
    """0-10 for how deep the retracement is, as a share of the 52-week range.

    The 38.2% fib zone is the classic ideal and deeper is a warning -- but a
    retracement can also be too SHALLOW to be one, and the old band could not
    say so: everything under 25% earned the same second-best 8, so a name that
    had barely come off its high outscored a textbook 20% retracement.

    CHOLAFIN is what that looked like: 4.4% of its 52-week range, which is not a
    pullback into support by any reading, scored 8/10 on retracement depth and
    led the table. The band now falls away below the fib zone as well as above
    it, so the shallow end is a penalty rather than a near-miss.

    Ordered top-down as it reads on a chart. The deep-side boundaries are
    unchanged: 25-45 is still the ideal, 45-55 still a warning, beyond 55 still
    a broken trend rather than a rest.
    """
    if x < 10.0:
        return 3.0        # a tenth of the year's range: it has not retraced
    if x < 18.0:
        return 5.0
    if x < 25.0:
        return 8.0
    if x <= 45.0:
        return 10.0       # the 38.2% fib zone
    if x <= 55.0:
        return 7.0
    return 4.0


def fit_pullback(ev):
    """Distance to MA 35% / RSI near 50 25% / dry-up 20% / retrace depth 20%."""
    d = band_desc(ev["dist_to_ma_pct"], [(1.0, 10), (2.0, 8), (3.0, 6)])
    r = band_desc(abs(ev["rsi"] - 50.0), [(5.0, 10), (10.0, 8), (99.0, 5)])
    v = band_desc(ev["dryup"], [(0.80, 10), (0.95, 8), (1.10, 5)])
    return round(0.35 * d + 0.25 * r + 0.20 * v
                 + 0.20 * retrace_depth(ev["retrace_pct"]), 2)


# ---------------------------------------------------------------------- TURN

def match_turn(o, ctx, strict=False, diag=None):
    """Entry into a brand-new trend, just after a golden cross. Spec section 3.5."""
    ma, px = o["ma"], o["price"]
    bars = ctx.get("bars_since_cross")
    # "never crossed" and "crossed too long ago" are separated: one is a name
    # with no golden cross in the lookback at all, the other an old trend.
    if bars is None:
        return _reject(diag, 1, "a 50/200 golden cross in the lookback at all")
    if bars > T("TURN", "cross_bars", strict):
        return _reject(diag, 2, "that cross within the last %d bars"
                       % T("TURN", "cross_bars", strict))
    if not (ma["sma50"] and ma["sma200"]):
        return _reject(diag, 3, "50- and 200-day averages both available")
    if px <= ma["sma50"] or px <= ma["sma200"]:
        return _reject(diag, 4, "price above both the 50- and 200-day averages")

    hist = o["macd"]["daily"]["hist"]
    if hist is None or hist <= 0:
        return _reject(diag, 5, "a positive MACD histogram")
    r = o["rsi"]["daily"]
    if r is None or r <= T("TURN", "rsi_lo", strict):
        return _reject(diag, 6, "a daily RSI above %.0f"
                       % T("TURN", "rsi_lo", strict))

    off_low = (px - o["lo52"]) / o["lo52"] * 100 if o["lo52"] else 0.0
    if off_low < T("TURN", "off_low_pct", strict):
        return _reject(diag, 7, "at least %.0f%% off the 52-week low"
                       % T("TURN", "off_low_pct", strict))

    return {"bars_since_cross": bars, "macd_hist": hist,
            "sma200_rising": bool(ctx["sma200_rising"]),
            "vol_expansion": ctx.get("vol_expansion") or 1.0}


def fit_turn(ev):
    """Cross recency 35% / 200D slope 30% / volume expansion 20% / MACD 15%."""
    c = band_desc(ev["bars_since_cross"], [(10, 10), (20, 9), (30, 7), (45, 5)])
    s = 10.0 if ev["sma200_rising"] else 4.0
    v = band(ev["vol_expansion"], [(1.30, 10), (1.10, 8), (0.0, 5)])
    m = 10.0 if ev["macd_hist"] > 0 else 6.0
    return round(0.35 * c + 0.30 * s + 0.20 * v + 0.15 * m, 2)


# ------------------------------------------------------------ context builder

CROSS_LOOKBACK = 60      # bars searched for a 50/200 cross; > the 45-bar max
SLOPE_BARS = 20          # window for "is this moving average rising"
ATR_PCTILE_BARS = 126    # ~6 months, the window the ATR percentile is taken over
RUN_BARS = 5             # sessions LEADER's extension guard measures a run over


def _ctx_from_rows(rows, rs):
    """Every derived input, computed ONCE per symbol.

    Predicates read from this. Building it inside each predicate would recompute
    five series five times per name, which across 500 names is the difference
    between a 23-second scan and a slow one.
    """
    closes = [r["c"] for r in rows]
    s50 = sma_series(closes, 50)
    s200 = sma_series(closes, 200)
    atrs = atr_series(rows, 14)

    sma200_rising = len(s200) > SLOPE_BARS and s200[-1] > s200[-1 - SLOPE_BARS]
    sma50_rising = len(s50) > SLOPE_BARS and s50[-1] > s50[-1 - SLOPE_BARS]

    # ATR percentile: where today's ATR sits within its own trailing 6 months.
    # Rank against its own history, not an absolute number -- a 4% ATR is tight
    # for one stock and wild for another.
    window = atrs[-ATR_PCTILE_BARS:]
    atr_pctile = (sum(1 for x in window if x <= atrs[-1]) / len(window)) if window else 1.0

    # Bars since sma50 crossed ABOVE sma200. Both series are aligned to their
    # own start, so index them from the right where they line up.
    bars_since_cross = None
    if s50 and s200:
        n = min(len(s50), len(s200), CROSS_LOOKBACK + 1)
        a, b = s50[-n:], s200[-n:]
        for i in range(len(a) - 1, 0, -1):
            if a[i] > b[i] and a[i - 1] <= b[i - 1]:
                bars_since_cross = len(a) - 1 - i
                break

    vol_expansion = 1.0
    if bars_since_cross is not None and len(rows) > bars_since_cross + 50:
        after = [r["v"] for r in rows[len(rows) - bars_since_cross - 1:]] or [0]
        before = [r["v"] for r in rows[len(rows) - bars_since_cross - 51:
                                       len(rows) - bars_since_cross - 1]] or [0]
        mb = sum(before) / len(before)
        vol_expansion = (sum(after) / len(after)) / mb if mb else 1.0

    # How far the name has run in the last RUN_BARS sessions, as a percentage.
    # closes[-1 - RUN_BARS] is the close RUN_BARS sessions BEFORE the last one:
    # with RUN_BARS = 5 that is closes[-6], five moves ago, not six. None when
    # there is no such bar, or when it is zero and the ratio is undefined --
    # "cannot measure", which the predicate must not read as a pass or a fail.
    run_pct = None
    if len(closes) > RUN_BARS and closes[-1 - RUN_BARS]:
        run_pct = (closes[-1] / closes[-1 - RUN_BARS] - 1) * 100

    return {"rows": rows, "rs": rs, "atr_pctile": atr_pctile,
            "sma200_rising": sma200_rising, "sma50_rising": sma50_rising,
            "bars_since_cross": bars_since_cross, "vol_expansion": vol_expansion,
            "run_pct": run_pct}


def build_ctx(o, rs):
    """Public entry: derive every context value for a scored symbol."""
    rows = aligned_rows(o)
    o["_rows"] = rows          # _no_down_thrust reads this to date recent bars
    return _ctx_from_rows(rows, rs)


# --------------------------------------------------------------- CONFLUENCE

REGISTRY = {"COILED": (match_coiled, fit_coiled),
            "BREAKOUT": (match_breakout, fit_breakout),
            "LEADER": (match_leader, fit_leader),
            "PULLBACK": (match_pullback, fit_pullback),
            "TURN": (match_turn, fit_turn)}

# Impossible by construction, not merely rare. Emitting this is a predicate bug:
# price cannot be above the prior base high AND retraced to the 20/50DMA at the
# same time. The assertion stays because it is a cheap alarm on exactly that.
#
# COILED+BREAKOUT used to sit here too, and it was WRONG -- not conservative,
# wrong. It read as impossible only while BREAKOUT compared price to a base high
# that included the breakout bar and so could never match anything; once
# base_high_before_last_bar made the gate satisfiable, a base contracting into a
# close above its own prior high became reachable. That is the VCP breakout: the
# exact COILED -> BREAKOUT progression this life cycle models, and the best row a
# scan can produce. Asserting on it did not catch a bug -- _add_confluence
# raised, scan() caught the AssertionError as a BaseException, and the name was
# moved into FAILED and dropped from every table without a word.
IMPOSSIBLE_PAIRS = frozenset({frozenset({"BREAKOUT", "PULLBACK"})})


def _add_confluence(matched):
    names = [n for n in SETUPS if n in matched]      # life-cycle order, not alphabetical
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            assert frozenset({a, b}) not in IMPOSSIBLE_PAIRS, (
                f"impossible pair {a}+{b} -- a predicate is wrong, not the market")
    if len(names) < 2:
        return matched
    fits = [matched[n]["fit"] for n in names]
    matched["CONFLUENCE"] = {
        "fit": round(sum(fits) / len(fits), 2),
        "evidence": {"matched": names, "count": len(names),
                     "label": "+".join(names),
                     "mean_fit": round(sum(fits) / len(fits), 2)}}
    return matched


def evaluate(o, rs, strict=False, min_turnover=3.0, diag=None):
    """Every setup a scored symbol matches, with its fit and evidence.

    Tri-state return, and the three states are NOT interchangeable:

      * ``None``          -- the symbol failed the liquidity gate. No predicate
                             ever ran; the market has said nothing about it.
      * ``{}``            -- the symbol is liquid and was screened against every
                             predicate, and matched none of them. This is the
                             overwhelmingly common outcome and is a real finding.
      * non-empty ``dict`` -- ``{setup: {"fit", "evidence"}}`` per match, plus
                             ``CONFLUENCE`` when two or more setups agree.

    Callers must test ``is None``, never truthiness: both non-match states are
    falsy, and collapsing them makes the scan header report several hundred
    liquid-but-quiet names as "below turnover floor", which is a lie about what
    the scan did.

    One compute() pass feeds all five predicates, so screening for one setup and
    screening for all six cost the same (spec invariant I2).

    Pass a dict as ``diag`` to collect the rejection funnel: it is filled in as
    ``{setup: {condition: (step, count)}}`` naming the first condition this
    symbol failed for each setup it did not match. It is instrumentation only --
    the returned matches are identical whether or not it is supplied, and the
    counters ride along inside the single scoring pass rather than costing a
    second one. An illiquid symbol never reaches a predicate, so it contributes
    nothing to the funnel; the caller already counts the gate separately.
    """
    ctx = build_ctx(o, rs)
    if not liquid(ctx, min_turnover):
        return None
    matched = {}
    for name in SETUPS:
        match_fn, fit_fn = REGISTRY[name]
        ev = match_fn(o, ctx, strict,
                      None if diag is None else diag.setdefault(name, {}))
        if ev is not None:
            matched[name] = {"fit": fit_fn(ev), "evidence": ev}
    return _add_confluence(matched)
