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


def primary_request(timeframe):
    """The (range, interval) pair compute() fetches for `timeframe`.

    Read out of A.TIMEFRAMES rather than restated here. A second copy of "2y",
    "1d" in this file is exactly how a scan ends up deriving its series from
    daily bars while the scores beside them were computed on weekly ones -- the
    two would agree today and drift the first time either is edited.
    """
    if timeframe not in A.TIMEFRAMES:
        raise SystemExit(f"ERROR: unknown timeframe {timeframe!r} - use "
                         f"{' or '.join(sorted(A.TIMEFRAMES))}.")
    return A.TIMEFRAMES[timeframe]["primary"]


def aligned_rows(o, timeframe="daily"):
    """Primary bars for a scored symbol, aligned to its last closed bar.

    The PRIMARY series, whichever timeframe the scan is running: every window
    below counts bars, so a weekly scan must derive them from the same weekly
    bars compute() scored, not from daily ones.

    Because it is the same request compute() made, A._CACHE already holds this
    series and the call is a cache hit costing no network.
    """
    rows, _ = A.fetch(o["symbol"], *primary_request(timeframe))
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


# Bars the up/down volume ratio is measured over. FIFTY: ~10 weeks, the window
# O'Neil's ratio is conventionally quoted on. Long enough that one earnings
# reaction cannot set the number, short enough that it describes the leg being
# screened rather than last year's.
UD_BARS = 50

# Bars the SHORT up/down window is measured over. TWENTY: ~4 weeks, one month of
# tape. UD_BARS weights all 50 bars equally, so a name that was accumulated 40
# sessions ago and distributed for the last 10 scores identically to one being
# accumulated right now -- VIJAYA read 1.70 over 50 bars and 0.52 over 20. The
# short window is not a better ratio than the long one; it is the SAME ratio
# asked about a nearer span, and accumulation_trend reads one against the other.
UD_SHORT_BARS = 20


def ud_ratio(rows, n=UD_BARS):
    """Up-close volume divided by down-close volume over the last `n` bars.

    O'Neil's up/down volume ratio -- the standard measure of whether a name is
    under net accumulation. Above 1.0 means more volume transacted on days that
    closed up than on days that closed down; below 1.0 means the opposite.

    DIRECTION IS MEASURED AGAINST THE PREVIOUS CLOSE, not against the bar's own
    open. A bar can open down and close up and still be a down day against
    yesterday's settle, and it is the settle-to-settle move that says which side
    the day's volume served. Note that the engine's thrust labels use a
    DIFFERENT convention (`c > o`, the bar's own open) -- the two are separate
    measurements and neither stands in for the other, which is why COILED gates
    on thrust direction and LEADER/TURN gate on this.

    The first bar of the window is judged against the bar BEFORE the window when
    there is one, so exactly `n` bars are classified rather than n-1. Unchanged
    closes belong to neither side: they carry no directional information, and
    parking them on either numerator or denominator would let a series of doji
    decide the ratio.

    Returns None -- never a division, never an infinity -- when the denominator
    is zero, when `n` is not positive, or when no bar could be classified at all.
    CALLERS MUST TREAT None AS A FAILED GATE, not a pass: 50 sessions without a
    single down close does not happen to a liquid NSE name, so in practice None
    means the series is too short, constant, or otherwise unmeasurable. "Cannot
    judge" closes the gate it guards; a gate that exists to demand positive
    evidence of accumulation must not open on the absence of evidence.
    """
    if n <= 0 or len(rows) < 2:
        return None                 # rows[-0:] is the WHOLE list, not an empty
                                    # window -- guard it rather than silently
                                    # measuring two years on a caller's typo
    window = rows[-n:]
    start = len(rows) - len(window)
    up = down = 0.0
    for i, r in enumerate(window):
        prev = start + i - 1
        if prev < 0:
            continue                # no prior close to judge the first bar by
        pc = rows[prev]["c"]
        if r["c"] > pc:
            up += r["v"]
        elif r["c"] < pc:
            down += r["v"]
    if down <= 0:
        return None
    return up / down


def ud_weighted(rows, n=UD_BARS):
    """Close-weighted up/down volume ratio over the last `n` bars.

    ud_ratio compares close to PREVIOUS close, so it is blind to WHERE inside
    its own bar the stock closed. A name can settle +0.1% having traded at its
    low all session and be recorded as a full day of accumulation. This asks the
    other question: on the volume that transacted, did the buyers or the sellers
    own the close?

    Chaikin's money-flow multiplier is the weight:

        m = ((C - L) - (H - C)) / (H - L)

    +1 when the close is exactly at the high, -1 at the low, 0 at the midpoint,
    and linear in between. `volume * m` goes to the up bucket when m > 0 and
    `volume * -m` to the down bucket otherwise; the ratio is up / down. A bar
    closing at its midpoint contributes NOTHING to either side -- m is 0, so the
    down bucket takes 0.0 -- which is the honest answer: a midpoint close says
    neither side won it.

    WHY THIS IS NOT A SECOND OPINION ON ud_ratio BUT A DIFFERENT MEASUREMENT.
    Measured on the live Nifty 500, CONCORDBIO reads ud_ratio 3.74 and this 0.59:
    buyers lift it intraday and sellers hit the bid into the close, session after
    session. LALPATHLAB (2.71 / 0.39), HYUNDAI (2.86 / 0.63) and EMCURE
    (1.56 / 0.53) are the same picture. That is institutional supply being
    distributed into strength, and no close-to-close ratio can see it.

    ZERO-RANGE BARS ARE SKIPPED, not counted as neutral: H == L makes the
    multiplier a division by zero, and a limit-up or limit-down bar carries no
    intrabar information about who owned the close anyway.

    Returns None -- never a division, never an infinity -- when the down bucket
    is zero or `n` is not positive, exactly as ud_ratio does. Callers treat that
    None the way they treat ud_ratio's: fit_accumulation scores it the floor
    rather than rewarding the absence of evidence. The distribution gate is the
    one documented exception, and says why at its own definition.
    """
    if n <= 0 or not rows:
        return None                 # rows[-0:] is the WHOLE list, not an empty
                                    # window -- the same trap ud_ratio guards
    up = down = 0.0
    for r in rows[-n:]:
        span = r["h"] - r["l"]
        if span <= 0:
            continue                # limit bar / stale print: no intrabar signal
        m = ((r["c"] - r["l"]) - (r["h"] - r["c"])) / span
        if m > 0:
            up += r["v"] * m
        else:
            down += r["v"] * -m
    if down <= 0:
        return None
    return up / down


# ----------------------------------------------- reading the ratios in English
#
# Two labels, both TOTAL functions: every input, including a None ratio, gets a
# defined string back. They feed a display column, and a None in a display
# column is a bug someone else has to discover -- an explicit "unknown" says the
# same thing out loud.

VOLUME_SIGNAL_UD = 1.25       # same floor LEADER and TURN gate on, loosened
VOLUME_SIGNAL_WEIGHTED = 1.0  # a ratio of two volume buckets: 1.0 is parity

ACCUMULATION = "accumulation"
DISTRIBUTION_INTO_STRENGTH = "distribution-into-strength"
SUPPORTED = "supported"
DISTRIBUTION = "distribution"
SIGNAL_UNKNOWN = "unknown"

VOLUME_SIGNALS = frozenset({ACCUMULATION, DISTRIBUTION_INTO_STRENGTH,
                            SUPPORTED, DISTRIBUTION, SIGNAL_UNKNOWN})


def volume_signal(ud, weighted):
    """The two ratios read together, in four words.

    Neither ratio alone answers the question. The close-to-close ratio says
    which days closed up; the close-weighted one says who owned the closes. The
    interesting cases are the two where they DISAGREE:

      ud >= 1.25, weighted >= 1.0   ``accumulation``
          Genuine accumulation -- price rising and closing strong.
      ud >= 1.25, weighted <  1.0   ``distribution-into-strength``
          Price drifts up, but sellers control the close -- institutional supply
          being distributed into strength.
      ud <  1.25, weighted >= 1.0   ``supported``
          Price soft, but buyers defend every dip -- often a base forming.
      ud <  1.25, weighted <  1.0   ``distribution``
          Distribution, unambiguously.

    Either ratio being None makes the READING unknown, not one of the four: the
    four labels are statements about a disagreement, and a measurement that does
    not exist cannot agree or disagree with anything.
    """
    if ud is None or weighted is None:
        return SIGNAL_UNKNOWN
    if ud >= VOLUME_SIGNAL_UD:
        return (ACCUMULATION if weighted >= VOLUME_SIGNAL_WEIGHTED
                else DISTRIBUTION_INTO_STRENGTH)
    return (SUPPORTED if weighted >= VOLUME_SIGNAL_WEIGHTED
            else DISTRIBUTION)


# Where the 20-bar ratio sits against the 50-bar one, as a fraction. Below 0.70
# the recent month is materially weaker than the quarter; 0.70-0.90 is a drift;
# 0.90-1.30 is noise on two overlapping windows of the same tape (the 20 bars
# ARE 20 of the 50, so the two can never be independent and a band this wide is
# what "unchanged" honestly looks like); above it the near window is carrying
# the number.
TREND_FADE = 0.70
TREND_FLAT = 0.90
TREND_STEADY_HI = 1.30
# Below this the near window is not merely weaker, it has crossed into net
# distribution -- which is a different statement from "less accumulation".
TREND_REVERSAL_UD = 1.0

TREND_REVERSED = "reversed"
TREND_FADING = "fading"
TREND_FLATTENING = "flattening"
TREND_STEADY = "steady"
TREND_STRENGTHENING = "strengthening"
TREND_UNKNOWN = "unknown"

ACCUMULATION_TRENDS = frozenset({TREND_REVERSED, TREND_FADING, TREND_FLATTENING,
                                 TREND_STEADY, TREND_STRENGTHENING,
                                 TREND_UNKNOWN})


def accumulation_trend(ud_50, ud_20):
    """Is the accumulation the 50-bar ratio reports still happening?

    Order matters and is not an implementation detail: ``reversed`` is tested
    FIRST because it is a strictly stronger statement than ``fading``. Both say
    the near window is under 70% of the far one; ``reversed`` adds that the near
    window has crossed below 1.0, so the name is not merely being accumulated
    less, it is being distributed. VIJAYA reads 1.70 over 50 bars and 0.52 over
    20 -- a 50-bar screen calls that accumulation and it has not been true for a
    month.

    Total, like volume_signal: either ratio None, or a 50-bar ratio of exactly
    zero that no fraction can be taken against, returns ``unknown``.
    """
    if ud_50 is None or ud_20 is None or ud_50 == 0:
        return TREND_UNKNOWN
    frac = ud_20 / ud_50
    if ud_20 < TREND_REVERSAL_UD and frac < TREND_FADE:
        return TREND_REVERSED
    if frac < TREND_FADE:
        return TREND_FADING
    if frac < TREND_FLAT:
        return TREND_FLATTENING
    if frac <= TREND_STEADY_HI:
        return TREND_STEADY
    return TREND_STRENGTHENING


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
#
# VOLUME CONFIRMATION -- one test per setup, chosen for its STAGE. They are not
# the same test wearing four labels:
#
#   COILED    counts prior up-thrusts. A base has no current demand by
#             definition -- that is what a base IS -- so asking it for a healthy
#             up/down ratio would reject every genuine coil. What it can be
#             asked is whether anyone ever accumulated it.
#   BREAKOUT  is NOT gated here. It already demands 1.5-2.0x average volume on
#             the breakout bar itself, which is the most direct volume evidence
#             any of these setups has.
#   LEADER    gates on the up/down ratio: a leader is a name under sustained
#             accumulation, and that is exactly what the ratio measures.
#   PULLBACK  compares the volume of the retracement against the advance it
#             retraces. A pullback on heavier volume than the advance is supply.
#   TURN      gates on the up/down ratio, for the same reason as LEADER. It is
#             deliberately NOT gated on vol_expansion -- see match_turn.
#
# The floors are ABSOLUTE, not percentiles of the day's universe, and that is a
# trade-off with a documented cost: 73% of the live Nifty 500 clears 1.0 and 54%
# clears 1.25, so in this accumulative tape they are moderate filters. In a broad
# selloff the same numbers could reject nearly everything, and an empty screen
# would then mean "this threshold no longer suits the regime" rather than "no
# setups exist". A percentile floor would self-adjust but would also guarantee
# matches every day, including days when the honest answer is that nothing is
# being accumulated. See docs/setups.md.
THRESHOLDS = {
    "COILED": {"min_bars": (16, 20), "atr_pctile": (0.333, 0.25),
               "contractions": (2, 3), "pos_in_base": (0.50, 0.60),
               "dryup": (1.0, 0.9), "sma50_rising": (False, True),
               "up_thrusts": (1, 2)},
    "BREAKOUT": {"min_bars": (12, 15), "vol_mult": (1.5, 2.0),
                 "max_extension_pct": (12.0, 8.0), "strict_ma_stack": (False, True)},
    "LEADER": {"max_from_high_pct": (10.0, 5.0), "rs_1m_floor": (-2.0, 0.0),
               "rsi_lo": (50.0, 55.0), "rsi_hi": (88.0, 85.0),
               "atr_pctile_hi": (0.90, 0.85), "max_run_pct": (10.0, 8.0),
               "strict_ma_stack": (False, True), "ud_ratio": (1.25, 1.50)},
    "PULLBACK": {"ma_dist_pct": (3.0, 2.0), "atr_mult_to_support": (1.2, 1.0),
                 "swing_margin_atr": (1.0, 1.5),
                 "min_retrace_pct": (3.0, 5.0),
                 "support_tol_atr": (0.25, 0.10),
                 "close_position": (0.50, 0.60),
                 "reversal_bars": (2, 1),
                 "rsi_lo": (38.0, 40.0), "rsi_hi": (62.0, 58.0),
                 "dryup": (1.1, 1.0), "thrust_bars": (8, 10),
                 "pullback_vol_ratio": (0.90, 0.75)},
    "TURN": {"cross_bars": (45, 30), "rsi_lo": (48.0, 50.0),
             "off_low_pct": (12.0, 20.0), "ud_ratio": (1.25, 1.50)},
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


# ------------------------------------------------------- the accumulation term
#
# ONE sub-score, shared by all five setups, so that "accumulation" means the
# same thing in every table. A per-setup variant would let an 8 for LEADER and
# an 8 for TURN describe different measurements, which is exactly the confusion
# Setup Fit already carries as a whole and must not compound.
#
# The gates (section 2) ask a yes/no question at a floor; this asks HOW MUCH,
# across the whole range, and so it ranks rather than filters. That is why
# BREAKOUT -- which has no up/down gate at all, because its breakout-bar volume
# multiple is the more direct evidence -- still carries this term: it costs a
# breakout nothing to be under accumulation as well, and between two otherwise
# equal breakouts the one being accumulated is the better row.
ACCUMULATION_CUTS = [(2.50, 10.0), (2.00, 9.0), (1.50, 8.0),
                     (1.25, 6.0), (1.00, 4.0)]

# What a name scores when it is NOT under net accumulation, and what an
# UNMEASURABLE ratio scores. Two is deliberately not zero: below 1.0 is a real,
# measured finding about a name that still cleared every other gate, and zeroing
# the term would let one soft input dominate a five-term score. It is also not
# the 4.0 of the 1.00-1.25 rung, because "distributing" and "mildly
# accumulating" must not tie.
NO_ACCUMULATION = 2.0


def _accumulation_rung(x):
    """The 0-10 ladder, applied to ONE ratio.

    None -- nothing to divide by, so the ratio is unmeasurable -- scores the
    floor, NOT a neutral middle and NOT the top. It is the same decision the
    gates make in _ud_ratio_ok, for the same reason: a score that rewards the
    ABSENCE of evidence would put an unmeasurable name above a measured one, and
    on this metric unmeasurable means a series too short or too flat to judge.
    """
    if x is None or x < ACCUMULATION_CUTS[-1][0]:
        return NO_ACCUMULATION
    return band(x, ACCUMULATION_CUTS)


# How the two ratios share the accumulation term. FIFTY-FIFTY: they are two
# measurements of one question -- is this name being bought -- and neither is
# the senior one. The close-to-close ratio is the conventional number and the
# one a reader recognises; the close-weighted ratio is the one that catches
# supply being distributed into strength. A name has to satisfy both to score
# the top of this term, which is the whole point.
#
# They sum to 1.0, so an aligned name scores exactly what it scored before this
# term learned about the close: ud 1.60 and weighted 1.60 is still an 8.
ACC_WEIGHT_UD = 0.5
ACC_WEIGHT_WEIGHTED = 0.5

# What a fading or reversed accumulation trend costs, in ladder points. Nothing
# is charged for `flattening`, `steady` or `strengthening`, and nothing for
# `unknown`: an unmeasurable trend is already paying through whichever ratio
# could not be measured, and charging it twice would price a data gap as a
# market finding.
#
# `reversed` costs double `fading` because it is the strictly stronger
# statement: both say the near window has collapsed against the far one, and
# `reversed` adds that it has crossed into net distribution.
TREND_PENALTY = {TREND_REVERSED: 2.0, TREND_FADING: 1.0}


def fit_accumulation(ud, weighted, ud_20):
    """0-10 for whether this name is under accumulation. The ranking half of
    section 3, and the one place the three volume numbers are priced together.

    ONE sub-score for all five setups, so "accumulation" means the same thing in
    every table, and it now asks three questions rather than one:

      * the conventional up/down ratio -- which days closed up
      * the close-weighted ratio -- who owned those closes
      * the 20-bar ratio against the 50-bar one -- whether it is still happening

    The third enters as a PENALTY rather than as a third ladder, deliberately.
    It is not an independent measurement: the 20 bars ARE 20 of the 50, so
    scoring it as a peer would count the same tape twice and hand a name credit
    for its own recent history under two headings. What it can say that the
    levels cannot is that the level is stale -- CONCORDBIO reads 3.74 over 50
    bars and 1.18 over 20 -- and a deduction is the honest shape for that.

    All three arguments are REQUIRED. A default would let a call site that
    forgot the close-weighted ratio score every name as if it were unmeasurable
    -- a silent halving of the term across a whole scan, visible nowhere.

    The trend is derived HERE, from the same accumulation_trend the report
    prints, so the penalty a row is charged and the label a reader sees can
    never disagree.
    """
    score = (ACC_WEIGHT_UD * _accumulation_rung(ud)
             + ACC_WEIGHT_WEIGHTED * _accumulation_rung(weighted))
    score -= TREND_PENALTY.get(accumulation_trend(ud, ud_20), 0.0)
    # DEFENSIVE, not load-bearing, and no test can kill either bound today: the
    # ladder's own floor is NO_ACCUMULATION (2.0) and the largest penalty is
    # 2.0, so the arithmetic cannot leave [0, 10] as the constants stand. They
    # are written anyway because the constants above are meant to be tuned, and
    # a Fit component outside 0-10 would silently break every setup's weighting.
    return max(0.0, min(10.0, score))


# Every Fit weight, as DATA rather than as literals inside five expressions, so
# that "each set sums to exactly 1.0" is a property a test can assert about the
# code instead of a claim a docstring makes about it. Each of these sums to 1.0
# exactly in binary floating point -- none of them needs a tolerance.
#
# The accumulation term was not bolted on top; every other weight came down to
# make room, so a Fit is still out of 10 and still comparable with yesterday's
# in kind if not in value. PULLBACK is the one structural change: its blunt
# `dryup` term -- the 20-day average against the 50-day, a statement about the
# last month rather than about this pullback -- is REPLACED by the
# pullback-versus-advance ratio, which measures the same idea properly.
FIT_WEIGHTS = {
    "COILED":   {"contraction": 0.35, "pos_in_base": 0.25,
                 "dryup": 0.20, "accumulation": 0.20},
    "BREAKOUT": {"vol_mult": 0.35, "freshness": 0.25,
                 "base_quality": 0.20, "accumulation": 0.20},
    "LEADER":   {"rs_3m": 0.35, "proximity": 0.30,
                 "stack": 0.15, "accumulation": 0.20},
    "PULLBACK": {"dist_to_ma": 0.30, "rsi": 0.20, "pullback_vol": 0.25,
                 "retrace_depth": 0.15, "accumulation": 0.10},
    "TURN":     {"cross_recency": 0.30, "sma200_slope": 0.25,
                 "vol_expansion": 0.15, "macd": 0.10, "accumulation": 0.20},
}


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


def _ud_ratio_ok(ctx, name, strict):
    """Does this name clear its up/down volume floor?

    THE SINGLE PLACE the None decision is written down, so LEADER and TURN
    cannot drift apart on it: an UNMEASURABLE ratio FAILS. `r is not None and
    ...` rather than `(r or 0) >= floor` because the two differ on a real 0.0 --
    a name with up-volume of zero is measurably under distribution and must
    reject through the comparison, not through the None guard, or the funnel
    would report a data problem where there is a market finding.
    """
    r = ctx.get("ud_ratio")
    return r is not None and r >= T(name, "ud_ratio", strict)


# The floor both new measures have to be UNDER, together, before a name is
# excluded from every setup. (loosened, strict), like every threshold in this
# file, so strict can tighten it later; the two are equal today because the
# gate's whole claim is the unambiguous case and 1.0 is the point at which each
# ratio changes sign. Strict must never be BELOW loosened -- a lower floor
# excludes fewer names, which would let strict match something loosened does
# not and break the subset invariant that holds everywhere else.
#
# Kept OUTSIDE the per-setup THRESHOLDS table because it is not a per-setup
# judgement: it is one statement about the symbol, applied identically to all
# five, and five copies of the same pair would be five places to disagree.
DISTRIBUTION_FLOOR = (1.0, 1.0)


def _not_distributing(ctx, strict):
    """False only when BOTH new measures say the name is being distributed NOW.

    Two independent readings have to agree before this rejects anything. The
    close-weighted ratio says sellers own the closes; the 20-bar ratio says the
    recent month is net down-volume. Either one alone is a finding worth
    printing and NOT a reason to drop the name -- a `distribution-into-strength`
    name still matches, still ranks, and carries its label into the table.

    A None on either measure is NOT read as distribution, and that is a
    deliberate departure from _ud_ratio_ok, which fails a None outright. The two
    gates ask opposite questions. _ud_ratio_ok demands positive evidence of
    accumulation, so the absence of evidence closes it. This one demands
    positive evidence of DISTRIBUTION -- "two independent measures both saying
    the stock is distributing now" -- and a measurement that does not exist is
    not one of them saying anything. Reading None as distribution would also be
    factually backwards: ud_weighted returns None exactly when NO bar closed
    below its own midpoint, which is the most bullish tape there is.
    """
    floor = DISTRIBUTION_FLOOR[1 if strict else 0]
    weighted, short = ctx.get("ud_weighted"), ctx.get("ud_20")
    return not (weighted is not None and weighted < floor
                and short is not None and short < floor)


def _distributing_label(strict):
    """The condition a PASSING name satisfies, for the rejection funnel."""
    return ("at least one of the close-weighted and 20-day volume ratios at "
            "%.2f or better" % DISTRIBUTION_FLOOR[1 if strict else 0])


# Sessions COILED counts prior up-thrusts over. 126 is ~6 months, the same
# window ATR_PCTILE_BARS ranks volatility in, so "quiet relative to its own six
# months" and "accumulated at some point in those six months" describe one span.
#
# ARITHMETIC NOTE, so nobody reads more into this number than it does:
# analyze.detect_thrusts scans `window=90` bars and labels nothing older, so no
# thrust older than 90 bars EXISTS to be counted and 126 behaves exactly as 90
# does today. It is written as 126 anyway -- it stays correct if the engine's
# window ever widens, and it says what this gate MEANS rather than what the
# engine currently supplies. TestCoiledUpThrustLookback pins the relationship.
UP_THRUST_BARS = 126


def _up_thrust_count(o, rows, bars):
    """How many UP-labelled volume thrusts fall inside the last `bars` sessions.

    Reads the engine's own directional label, exactly as _no_down_thrust does;
    it never re-derives one. `rows` is a parameter rather than being taken off
    o["_rows"] so that this count and the rest of the predicate provably read
    the same series -- a predicate reading a key the engine does not set would
    silently count zero and reject everything.
    """
    recent = {str(r["t"]) for r in rows[-bars:]} if bars > 0 else set()
    if not recent:
        return 0
    return sum(1 for t in (o["volume"].get("thrusts") or [])
               if t.get("dir") == "up" and t.get("date") in recent)


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

    # A base with no prior accumulation is a dead stock, not a coiled spring.
    # Everything above this line is satisfied by a name nobody is trading: the
    # range narrows because there is no participation, volatility falls to the
    # bottom of its own history because nothing happens, and the dry-up gate
    # rewards exactly that. What separates a spring from a corpse is that
    # somebody took real size in it at some point -- at least one bar of 2.5x
    # volume the engine labelled UP. Strict asks for two, because a single
    # thrust can be an index rebalance or a block crossing.
    #
    # Counted, not merely detected: the direction is read off the engine's label
    # and never re-derived, so a name that sold off on 3x volume cannot be
    # counted as accumulation here any more than it can in _no_down_thrust.
    ups = _up_thrust_count(o, ctx.get("rows") or [], UP_THRUST_BARS)
    if ups < T("COILED", "up_thrusts", strict):
        return _reject(diag, 12, "at least %d up-thrust in the last %d sessions"
                       % (T("COILED", "up_thrusts", strict), UP_THRUST_BARS))

    # First-to-last window, whatever COILED_WINDOWS is: widths[-1], not widths[2].
    # The net-contraction gate above guarantees this ratio is < 1.0 for every
    # name that reaches here -- the Contraction column can no longer print 1.01.
    #
    # Mutation note: the `if widths[0]` fallback is now DEFENSIVE and
    # unreachable, not load-bearing. widths[0] == 0 makes `widths[-1] >=
    # widths[0]` true for any non-negative width, so a zero first window is
    # rejected at the net-contraction gate and never reaches this line. Kept as
    # a division guard in case that gate is ever reordered.

    # Both new volume measures below 1.0 at once: the closes are being sold AND
    # the last month is net down-volume. Neither reading alone rejects -- a name
    # drifting up while sellers own the close is a real finding the table prints
    # with its label -- but two independent measures agreeing that the name is
    # being distributed RIGHT NOW is not a setup, whatever the price is doing.
    if not _not_distributing(ctx, strict):
        return _reject(diag, 13, _distributing_label(strict))

    return {"contraction": widths[-1] / widths[0] if widths[0] else 1.0,
            "pos_in_base": pos, "dryup": dryup, "widths": widths,
            "ud_ratio": ctx.get("ud_ratio"),
            "ud_weighted": ctx.get("ud_weighted"), "ud_20": ctx.get("ud_20")}


def fit_coiled(ev):
    """Contraction 35% / position in base 25% / dry-up 20% / accumulation 20%.

    The dry-up term and the accumulation term are not the same measurement
    twice. Dry-up asks whether volume is quiet NOW, which is what makes a base a
    base; accumulation asks whether it was ever bought, which is what makes the
    base worth watching. A dead stock scores well on the first and badly on the
    second, and before this term existed it could lead the table.
    """
    w = FIT_WEIGHTS["COILED"]
    c = band_desc(ev["contraction"], [(0.50, 10), (0.65, 8), (0.80, 6), (1.00, 4)])
    p = band(ev["pos_in_base"], [(0.85, 10), (0.70, 8), (0.50, 6)])
    d = band_desc(ev["dryup"], [(0.70, 10), (0.85, 8), (1.00, 6)])
    acc = fit_accumulation(ev.get("ud_ratio"), ev.get("ud_weighted"),
                           ev.get("ud_20"))
    return round(w["contraction"] * c + w["pos_in_base"] * p + w["dryup"] * d
                 + w["accumulation"] * acc, 2)


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

    # Both new volume measures below 1.0 at once: the closes are being sold AND
    # the last month is net down-volume. Neither reading alone rejects -- a name
    # drifting up while sellers own the close is a real finding the table prints
    # with its label -- but two independent measures agreeing that the name is
    # being distributed RIGHT NOW is not a setup, whatever the price is doing.
    if not _not_distributing(ctx, strict):
        return _reject(diag, 9, _distributing_label(strict))

    span = base_hi - base_lo
    return {"vol_mult": vol_mult, "pct_above_base": above,
            "base_bars": rng["bars"],
            "tightness": span / base_hi * 100 if base_hi else 0.0,
            "volume_light": vol_mult < CONFIRMED_VOL_MULT,
            "ud_ratio": ctx.get("ud_ratio"),
            "ud_weighted": ctx.get("ud_weighted"), "ud_20": ctx.get("ud_20")}


def fit_breakout(ev):
    """Volume multiple 35% / freshness 25% / base quality 20% / accumulation 20%.

    BREAKOUT is the one setup with no up/down volume GATE, because its
    breakout-bar multiple is the more direct evidence and gating twice on volume
    would count it twice. It still carries the accumulation term, which costs a
    genuine breakout nothing and separates a bar that fired out of ten weeks of
    buying from one that fired out of ten weeks of nothing.
    """
    w = FIT_WEIGHTS["BREAKOUT"]
    v = band(ev["vol_mult"], [(3.0, 10), (2.5, 9), (2.0, 8), (1.75, 6), (1.5, 4)])
    f = band_desc(ev["pct_above_base"], [(2.0, 10), (5.0, 8), (8.0, 6), (12.0, 4)])
    b = band(ev["base_bars"], [(30, 10), (20, 8), (15, 6), (12, 4)])
    if ev["tightness"] > 8.0:
        b *= 0.8
    acc = fit_accumulation(ev.get("ud_ratio"), ev.get("ud_weighted"),
                           ev.get("ud_20"))
    return round(w["vol_mult"] * v + w["freshness"] * f + w["base_quality"] * b
                 + w["accumulation"] * acc, 2)


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

    # Positive evidence of accumulation, not merely the absence of a down-thrust.
    # Measured across the live Nifty 500, LEADER's median up/down volume ratio
    # was 1.34 against a universe median of 1.33 -- statistically the same tape.
    # The setup selected names near 52-week highs with positive relative
    # strength and NO volume edge whatever, which is a price screen wearing a
    # volume screen's reputation. The down-thrust test above cannot supply this:
    # it asks only that nothing violent happened in ten sessions, and a name
    # drifting up on nobody's participation passes it every time.
    if not _ud_ratio_ok(ctx, "LEADER", strict):
        return _reject(diag, 11, "volume on up-closes at least %.2fx volume on "
                                 "down-closes over %d sessions"
                       % (T("LEADER", "ud_ratio", strict), UD_BARS))


    # Both new volume measures below 1.0 at once: the closes are being sold AND
    # the last month is net down-volume. Neither reading alone rejects -- a name
    # drifting up while sellers own the close is a real finding the table prints
    # with its label -- but two independent measures agreeing that the name is
    # being distributed RIGHT NOW is not a setup, whatever the price is doing.
    if not _not_distributing(ctx, strict):
        return _reject(diag, 12, _distributing_label(strict))

    return {"pct_from_high": from_high, "rs_1m": rs["1m"], "rs_3m": rs["3m"],
            "full_stack": bool(px > ma["sma20"] > ma["sma50"] > ma["sma200"]),
            "ud_ratio": ctx.get("ud_ratio"),
            "ud_weighted": ctx.get("ud_weighted"), "ud_20": ctx.get("ud_20")}


def fit_leader(ev):
    """Relative strength 3m 35% / proximity 30% / stack 15% / accumulation 20%.

    LEADER now gates on the up/down ratio as well, so every name reaching this
    function is already at 1.25 or better and scores at least 6 here. The term
    is still doing work: the gate cannot separate a name at 1.26 from one at
    3.0, and on a setup whose whole claim is sustained institutional demand that
    is the difference the ranking should show.
    """
    w = FIT_WEIGHTS["LEADER"]
    r = band(ev["rs_3m"], [(20.0, 10), (10.0, 8), (5.0, 6), (0.0, 4)])
    p = band_desc(ev["pct_from_high"], [(2.0, 10), (5.0, 8), (10.0, 6)])
    s = 10.0 if ev["full_stack"] else 7.0
    acc = fit_accumulation(ev.get("ud_ratio"), ev.get("ud_weighted"),
                           ev.get("ud_20"))
    return round(w["rs_3m"] * r + w["proximity"] * p + w["stack"] * s
                 + w["accumulation"] * acc, 2)


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


# How many of compute()'s swing highs the RETRACEMENT is measured from. FIVE --
# not one, and not all ten:
#
#   * one pivot is wrong in the direction that matters. A stock still falling
#     prints a fresh lower pivot on every bounce, so the LATEST swing high sits
#     just above the price and a name in a decline reads as "0.4% off its swing
#     high" -- the opposite of the truth, and precisely the reading that would
#     have let a falling name through this gate.
#   * all ten reaches back a year or more on a slow-moving name. The level a
#     retracement is measured from would then be a high the stock left three
#     legs ago, which says nothing about the move being screened, and the
#     percentage would grow simply with the length of the history.
#
# Five is the current leg plus enough behind it to contain the high that leg
# started from. On every name in the live universe the last five and the last
# ten agree, so the number is not load-bearing today -- it is a bound on how far
# back a stale high can be dragged in on the day one day disagrees.
RETRACE_SWINGS = 5


def _retrace_swing(o):
    """The pivot this retracement is measured FROM: the highest of the last
    RETRACE_SWINGS swing highs, as a whole {date, px} record.

    Shared by the retracement gate and the advance-versus-pullback volume gate
    so that both provably describe the SAME leg. Two gates measuring "the
    pullback" from two different highs would be two different setups sharing a
    name, and the disagreement would be invisible in the output.

    Returns None when there is no usable pivot.
    """
    swings = [s for s in (o.get("swing_highs") or []) if s.get("px")]
    if not swings:
        return None
    return max(swings[-RETRACE_SWINGS:], key=lambda s: s["px"])


def _retrace_from_swing_high(o, px):
    """How far below a recent swing high `px` sits, in percent.

    Returns None when there is no swing to measure against, or when the pivot
    price is not positive -- "cannot judge", which the caller must treat as a
    rejection and never as a pass.
    """
    peak = _retrace_swing(o)
    if peak is None:
        return None
    hi = peak["px"]
    if hi <= 0:
        return None
    return (hi - px) / hi * 100


# Bars BEFORE the swing high the advance's volume is averaged over. THIRTY: long
# enough to describe the leg that carried price to the high rather than its last
# few bars, short enough that it does not reach back through the base the advance
# started from and average the dead volume in it.
ADVANCE_BARS = 30

# The shortest leg on either side that can carry an average worth comparing.
# Below this the "average" is one or two prints and a single block trade sets
# the ratio, so the answer is None -- unmeasurable -- rather than a number.
MIN_LEG_BARS = 5


def _pullback_volume_ratio(o, rows):
    """Average volume in the retracement over average volume in the advance.

    Below 1.0 means the pullback is trading on lighter volume than the move it
    is retracing: holders are resting rather than selling. Above 1.0 means the
    retracement is drawing MORE participation than the advance did, which is
    distribution wearing a pullback's shape. Measured on the live Nifty 500, the
    median PULLBACK match came in at 0.88 -- most "pullbacks" this screen found
    were retracing on volume nearly as heavy as the advance before them.

    The legs, stated explicitly because the slice boundaries are the whole test:

        advance    rows[peak - 30 : peak]     the 30 bars BEFORE the pivot
        pullback   rows[peak :]               the pivot bar to the last closed one

    The pivot bar belongs to the PULLBACK leg. It is the bar that printed the
    high, so it is where the retracement starts; and when its volume is a
    climax print, counting it against the pullback makes the gate harder to
    pass, which is the safe direction for a gate whose whole purpose is to
    demand evidence.

    Returns None -- and the caller MUST reject on None, never pass -- when there
    is no pivot, when the pivot's date is not in `rows` at all, when either leg
    is shorter than MIN_LEG_BARS, or when the advance carried no volume to
    divide by. A gate that opens whenever its measurement is unavailable is
    decorative, and every one of these cases is reachable: a swing high dated
    outside the aligned rows, a pivot within a few bars of the series start, and
    a zero-volume advance in a halted name.
    """
    peak = _retrace_swing(o)
    if peak is None:
        return None
    date = str(peak.get("date"))
    # Searched from the RIGHT: the pivot is near the end of the series, and on
    # the impossible-but-cheap case of a repeated date the later bar is the one
    # this leg is about.
    idx = None
    for i in range(len(rows) - 1, -1, -1):
        if str(rows[i]["t"]) == date:
            idx = i
            break
    if idx is None:
        return None
    pullback = rows[idx:]
    advance = rows[max(0, idx - ADVANCE_BARS):idx]
    if len(pullback) < MIN_LEG_BARS or len(advance) < MIN_LEG_BARS:
        return None
    adv = sum(r["v"] for r in advance) / len(advance)
    if adv <= 0:
        return None
    return (sum(r["v"] for r in pullback) / len(pullback)) / adv


def _close_position(bar):
    """Where the close sat inside the bar's own range: 0.0 at the low, 1.0 at
    the high.

    None on a zero-range bar, where the question has no answer. Not 0.0 and not
    1.0 -- either would let a bar carrying no information decide the gate, and a
    synthetic h == l bar is exactly the fixture that would then pass silently.
    """
    span = bar["h"] - bar["l"]
    if span <= 0:
        return None
    return (bar["c"] - bar["l"]) / span


def _rejection_at_support(o, ctx, strict):
    """The close position of the bar that rejected support, or None.

    A pullback that has not yet turned is a stock still falling. NH closed at
    22% of its daily range and MARICO at 13% -- both near the low, both counted
    as pullbacks by a screen that never asked whether a buyer had appeared.

    A bar qualifies on a candidate level L when ALL THREE hold:

        tested it     bar low <= L + tol * ATR   (it actually reached support)
        reclaimed it  bar close > L              (it did not close under it)
        closed strong close position >= floor    (buyers took the bar back)

    All three, on the SAME level: a low that reached the 50-day and a close
    above the 20-day is not a rejection of anything.

    The candidate levels are the 20-day, the 50-day and the engine's nearest
    support, each kept only when it sits at or below the last closed price --
    a level ABOVE the price is resistance, and "reclaiming" it would mean the
    stock is under it, which is not this setup.

    The bar may be the last closed one or the one before it (loosened), or the
    last closed one alone (strict): the turn is often confirmed by an inside day
    that closes mid-range, and demanding the hammer itself be the final bar
    throws away the second day of every genuine reversal. CEMPRO is the live
    case -- its hammer is the 30th, and the 31st closed strong but no longer
    reached back to the 50-day.

    Returns None when there is no ATR, no candidate level or no qualifying bar.
    """
    atr_d = o["atr"]["daily"]
    if not atr_d:
        return None
    px = o["price"]
    levels = [lv for lv in (o["ma"].get("sma20"), o["ma"].get("sma50"),
                            (o.get("entry_gate") or {}).get("nearest_support"))
              if lv is not None and lv <= px]
    if not levels:
        return None

    tol = T("PULLBACK", "support_tol_atr", strict) * atr_d
    floor = T("PULLBACK", "close_position", strict)
    window = T("PULLBACK", "reversal_bars", strict)
    # Most recent first, so the evidence reports the freshest qualifying bar
    # when both are eligible.
    for bar in reversed((ctx.get("rows") or [])[-window:]):
        pos = _close_position(bar)
        if pos is None or pos < floor:
            continue
        for lv in levels:
            if bar["l"] <= lv + tol and bar["c"] > lv:
                return pos
    return None


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

    # A pullback has to have PULLED BACK. Nothing above says so: the swing-margin
    # guard applies to the support arm alone, and the moving-average arm asks
    # only that price sit near the 20- or 50-day -- which a stock going sideways
    # satisfies when the average catches UP to it. MARICO closed 0.3% under its
    # swing high and matched on exactly that; NH at 1.0%. Neither had retraced;
    # their averages had simply arrived.
    #
    # Applied to BOTH arms, because both were open to the same defect.
    retrace = _retrace_from_swing_high(o, px)
    if retrace is None or retrace < T("PULLBACK", "min_retrace_pct", strict):
        return _reject(diag, 7, "price at least %.0f%% below a recent swing high"
                       % T("PULLBACK", "min_retrace_pct", strict))

    # ...and the pullback has to be ENDING. A retracement with no turn in it is
    # a stock still falling: NH closed at 22% of its daily range and MARICO at
    # 13%, both near the low, and both were counted. See _rejection_at_support.
    close_pos = _rejection_at_support(o, ctx, strict)
    if close_pos is None:
        return _reject(diag, 8, "a bar that tested support, closed back above it "
                                "and closed in the top %.0f%% of its own range"
                       % round((1 - T("PULLBACK", "close_position", strict)) * 100))

    r = o["rsi"]["daily"]
    if r is None or not (T("PULLBACK", "rsi_lo", strict) <= r
                         <= T("PULLBACK", "rsi_hi", strict)):
        return _reject(diag, 9, "a daily RSI between %.0f and %.0f"
                       % (T("PULLBACK", "rsi_lo", strict),
                          T("PULLBACK", "rsi_hi", strict)))

    dryup = o["volume"]["dryup_ratio"]
    if dryup is None or dryup >= T("PULLBACK", "dryup", strict):
        return _reject(diag, 10, "volume dried up below %.2fx its own average"
                       % T("PULLBACK", "dryup", strict))
    if not _no_down_thrust(o, T("PULLBACK", "thrust_bars", strict)):
        return _reject(diag, 11, "no down-thrust in the last %d sessions"
                       % T("PULLBACK", "thrust_bars", strict))

    # The retracement has to be RESTING, not being sold. Neither gate above says
    # so: dryup compares the 20-day average against the 50-day, which is a
    # statement about the last month rather than about this pullback, and the
    # down-thrust test only asks that no single bar exceeded 2.5x average. A
    # stock can retrace on steady heavy volume for a fortnight and pass both.
    # It did: the median PULLBACK match retraced at 0.88x the volume of its own
    # advance, so half the list was resting on almost exactly the participation
    # that drove the move up. That is supply.
    pull_vol = _pullback_volume_ratio(o, ctx.get("rows") or [])
    if pull_vol is None or pull_vol > T("PULLBACK", "pullback_vol_ratio", strict):
        return _reject(diag, 12, "a pullback on no more than %.2fx the volume "
                                 "of the advance it retraces"
                       % T("PULLBACK", "pullback_vol_ratio", strict))


    # Both new volume measures below 1.0 at once: the closes are being sold AND
    # the last month is net down-volume. Neither reading alone rejects -- a name
    # drifting up while sellers own the close is a real finding the table prints
    # with its label -- but two independent measures agreeing that the name is
    # being distributed RIGHT NOW is not a setup, whatever the price is doing.
    if not _not_distributing(ctx, strict):
        return _reject(diag, 13, _distributing_label(strict))

    # TWO retracement numbers, deliberately, because they answer two questions
    # and neither substitutes for the other:
    #
    #   retrace_pct              how far under a recent swing high price sits.
    #                            The gate above, and the number the report
    #                            publishes -- it is what "has it pulled back"
    #                            means to a reader looking at one name.
    #   retrace_of_52w_range_pct where the retracement sits inside the 52-week
    #                            range. fit_pullback scores THIS one, against a
    #                            band calibrated to the 38.2% fib zone of a
    #                            year's range. Feeding it the swing-high
    #                            percentage would put every match in the band's
    #                            bottom rung, since the gate only asks for 3%.
    span = o["hi52"] - o["lo52"]
    # dryup stays in the evidence though fit_pullback no longer scores it: it is
    # still a live GATE, so the CSV's flags and any reader asking "why did this
    # match" need the number that let it through.
    return {"dist_to_ma_pct": near_ma, "rsi": r, "dryup": dryup,
            "close_position": close_pos, "retrace_pct": retrace,
            "pullback_vol_ratio": pull_vol,
            "ud_ratio": ctx.get("ud_ratio"),
            "ud_weighted": ctx.get("ud_weighted"), "ud_20": ctx.get("ud_20"),
            "retrace_of_52w_range_pct": (o["hi52"] - px) / span * 100
                                        if span else 0.0}


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


# The pullback-versus-advance ratio, banded. LOWER is better, so band_desc.
#
# The gate already rejects anything above 0.90 (strict 0.75), so the 4.0 rung is
# the floor a matching name can reach and the 0.0 fall-through is unreachable
# through match_pullback -- it is a guard for a caller passing evidence in by
# hand, not a live arm. The rungs sit BELOW the gate rather than around it,
# because the interesting distinction among matches is between a retracement at
# half the advance's volume and one at nine tenths of it.
PULLBACK_VOL_CUTS = [(0.50, 10), (0.65, 8), (0.80, 6), (0.90, 4)]


def fit_pullback(ev):
    """Distance to MA 30% / RSI near 50 20% / pullback volume 25% /
    retrace depth 15% / accumulation 10%.

    The depth term reads retrace_of_52w_range_pct, NOT retrace_pct: retrace_depth
    bands a share of the 52-week range, and the swing-high percentage the gate
    uses lives on a different scale entirely.

    The blunt `dryup` term this setup used to carry is REPLACED, not merely
    outweighed, by the pullback-versus-advance ratio. Both claim to measure "is
    this retracement quiet", but dryup compares a 20-day average against a
    50-day one -- a statement about the last month that knows nothing about
    where the pullback began -- while the new term measures the retracement leg
    against the advance it is retracing. Keeping both would have scored one idea
    twice and given the worse measurement half the credit. dryup remains a gate.

    PULLBACK carries the SMALLEST accumulation weight of the five at 10%, and
    deliberately: it already spends 25% on a volume term of its own, and this
    setup buys a name that is by definition NOT being accumulated this week.
    The up/down ratio here describes the trend the pullback interrupts.
    """
    w = FIT_WEIGHTS["PULLBACK"]
    d = band_desc(ev["dist_to_ma_pct"], [(1.0, 10), (2.0, 8), (3.0, 6)])
    r = band_desc(abs(ev["rsi"] - 50.0), [(5.0, 10), (10.0, 8), (99.0, 5)])
    v = band_desc(ev["pullback_vol_ratio"], PULLBACK_VOL_CUTS)
    acc = fit_accumulation(ev.get("ud_ratio"), ev.get("ud_weighted"),
                           ev.get("ud_20"))
    return round(w["dist_to_ma"] * d + w["rsi"] * r + w["pullback_vol"] * v
                 + w["retrace_depth"] * retrace_depth(ev["retrace_of_52w_range_pct"])
                 + w["accumulation"] * acc, 2)


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

    # A new trend nobody is accumulating is a moving average crossing, not a
    # turn. Everything above this line is price and price-derived: two averages,
    # their order, a histogram, an RSI, a distance off the low. A stock can
    # produce all of it by drifting up on no participation at all, which is
    # precisely what a golden cross does when it is an artifact of the 200-day
    # flattening rather than of demand.
    #
    # The gate is the up/down ratio and NOT ctx["vol_expansion"], deliberately.
    # vol_expansion compares volume since the cross against the 50 bars before
    # it, so its answer depends on the AGE of the cross: a cross 30-40 bars old
    # has long since normalised and reads ~1.0 however strong the demand behind
    # it, while a cross 3 bars old reads high on three noisy sessions. Gating on
    # it would penalise the age of the cross and call it weak demand. It stays a
    # Fit component, where a soft input is appropriate, and never a gate.
    if not _ud_ratio_ok(ctx, "TURN", strict):
        return _reject(diag, 8, "volume on up-closes at least %.2fx volume on "
                                "down-closes over %d sessions"
                       % (T("TURN", "ud_ratio", strict), UD_BARS))


    # Both new volume measures below 1.0 at once: the closes are being sold AND
    # the last month is net down-volume. Neither reading alone rejects -- a name
    # drifting up while sellers own the close is a real finding the table prints
    # with its label -- but two independent measures agreeing that the name is
    # being distributed RIGHT NOW is not a setup, whatever the price is doing.
    if not _not_distributing(ctx, strict):
        return _reject(diag, 9, _distributing_label(strict))

    return {"bars_since_cross": bars, "macd_hist": hist,
            "sma200_rising": bool(ctx["sma200_rising"]),
            "vol_expansion": ctx.get("vol_expansion") or 1.0,
            "ud_ratio": ctx.get("ud_ratio"),
            "ud_weighted": ctx.get("ud_weighted"), "ud_20": ctx.get("ud_20")}


def fit_turn(ev):
    """Cross recency 30% / 200D slope 25% / volume expansion 15% / MACD 10% /
    accumulation 20%.

    vol_expansion and accumulation are BOTH here and they are not redundant.
    vol_expansion is anchored to the golden cross, so it answers "has
    participation picked up since the turn" and decays as the cross ages;
    the up/down ratio is a fixed 50-bar window that answers "who is winning the
    days" regardless of when the cross happened. That decay is exactly why
    vol_expansion is a Fit component and never a gate -- see match_turn -- and
    why it now carries less weight than the measure that does not decay.
    """
    w = FIT_WEIGHTS["TURN"]
    c = band_desc(ev["bars_since_cross"], [(10, 10), (20, 9), (30, 7), (45, 5)])
    s = 10.0 if ev["sma200_rising"] else 4.0
    v = band(ev["vol_expansion"], [(1.30, 10), (1.10, 8), (0.0, 5)])
    m = 10.0 if ev["macd_hist"] > 0 else 6.0
    acc = fit_accumulation(ev.get("ud_ratio"), ev.get("ud_weighted"),
                           ev.get("ud_20"))
    return round(w["cross_recency"] * c + w["sma200_slope"] * s
                 + w["vol_expansion"] * v + w["macd"] * m
                 + w["accumulation"] * acc, 2)


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
            "run_pct": run_pct,
            # Once per symbol, here, for the same reason as every other value in
            # this dict: LEADER and TURN both gate on it and the report prints it
            # for every setup, so recomputing it per predicate would walk the
            # same 50 bars three times for each of 500 names.
            "ud_ratio": ud_ratio(rows, UD_BARS),
            # The same window measured a second way, and the same measurement
            # over a nearer window. Three numbers rather than one because they
            # disagree in ways that matter -- see ud_weighted and
            # accumulation_trend -- and all three are computed HERE so the five
            # predicates, the two labels and the Fit term cannot drift apart on
            # which bars any of them describes.
            "ud_weighted": ud_weighted(rows, UD_BARS),
            "ud_20": ud_ratio(rows, UD_SHORT_BARS)}


def build_ctx(o, rs, timeframe="daily"):
    """Public entry: derive every context value for a scored symbol.

    `timeframe` selects the bars, and must be the SAME one `o` was computed on
    -- every value in the returned dict is a bar count (50 for the up/down
    ratio, 126 for the ATR percentile, 60 for the cross lookback), so mixing a
    weekly score with a daily context would silently measure two horizons at
    once.
    """
    rows = aligned_rows(o, timeframe)
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


# The volume block every matched entry carries at its TOP LEVEL, CONFLUENCE
# included. Named once, as data, because five producers and several consumers
# have to agree on it exactly: a renderer walking matched[setup][key] cannot
# special-case one entry, and a key that appeared on four setups out of six
# would fail in whichever table nobody opened today.
#
# All five are properties of the SYMBOL and none of any one match, which is why
# they are lifted from ctx rather than out of a predicate's evidence payload --
# see the note in evaluate().
VOLUME_KEYS = ("ud_ratio", "ud_weighted", "ud_20",
               "volume_signal", "accumulation_trend")


def _volume_block(ctx):
    """The five volume keys for one symbol, derived once from its context."""
    ud, weighted, short = ctx["ud_ratio"], ctx["ud_weighted"], ctx["ud_20"]
    return {"ud_ratio": ud, "ud_weighted": weighted, "ud_20": short,
            "volume_signal": volume_signal(ud, weighted),
            "accumulation_trend": accumulation_trend(ud, short)}


def _add_confluence(matched):
    names = [n for n in SETUPS if n in matched]      # life-cycle order, not alphabetical
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            assert frozenset({a, b}) not in IMPOSSIBLE_PAIRS, (
                f"impossible pair {a}+{b} -- a predicate is wrong, not the market")
    if len(names) < 2:
        return matched
    fits = [matched[n]["fit"] for n in names]
    # Every volume key is a property of the SYMBOL, not of any one setup, so
    # every constituent carries identical values and taking the first is not a
    # choice between disagreeing numbers. They are copied up rather than
    # recomputed so the CONFLUENCE row prints the same figures as the rows it is
    # made of -- a column that disagreed with its own inputs would be worse than
    # no column, and recomputing a LABEL would additionally risk CONFLUENCE
    # reading "accumulation" under constituents reading "distribution".
    #
    # Carried at the TOP LEVEL, because CONFLUENCE must satisfy the same read as
    # every other entry: a renderer walking matched[setup][key] cannot
    # special-case one key. `.get` rather than `[...]`: _add_confluence is
    # called with hand-built dicts in tests and by anything composing matches
    # itself, and a missing key must arrive as the None a renderer already knows
    # how to print, not as a KeyError halfway through a 500-name scan.
    conf = {k: matched[names[0]].get(k) for k in VOLUME_KEYS}
    conf.update({
        "fit": round(sum(fits) / len(fits), 2),
        "evidence": {"matched": names, "count": len(names),
                     "label": "+".join(names),
                     "ud_ratio": matched[names[0]]["evidence"].get("ud_ratio"),
                     "mean_fit": round(sum(fits) / len(fits), 2)}})
    matched["CONFLUENCE"] = conf
    return matched


def evaluate(o, rs, strict=False, min_turnover=3.0, diag=None,
             timeframe="daily"):
    """Every setup a scored symbol matches, with its fit and evidence.

    Tri-state return, and the three states are NOT interchangeable:

      * ``None``          -- the symbol failed the liquidity gate. No predicate
                             ever ran; the market has said nothing about it.
      * ``{}``            -- the symbol is liquid and was screened against every
                             predicate, and matched none of them. This is the
                             overwhelmingly common outcome and is a real finding.
      * non-empty ``dict`` -- ``{setup: {"fit", "evidence", *VOLUME_KEYS}}`` per
                             match, plus ``CONFLUENCE`` when two or more setups
                             agree.

    The volume block -- ``ud_ratio``, ``ud_weighted``, ``ud_20``,
    ``volume_signal``, ``accumulation_trend`` -- is present on EVERY entry
    including ``CONFLUENCE``. The three ratios may be None when the symbol had
    nothing to divide by; the two labels are ALWAYS strings, "unknown" being the
    reading of a ratio that could not be measured.

    `timeframe` must match the one `o` was computed on. It reaches only
    build_ctx: every predicate reads `o` and `ctx`, and both already carry the
    primary series, so no predicate needs to know which timeframe produced it.
    On weekly, `o["rsi"]["daily"]`, `o["macd"]["daily"]` and `o["atr"]["daily"]`
    carry the WEEKLY series -- see compute()'s docstring on the slot names --
    which is why the five predicates read weekly numbers without being changed.

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
    ctx = build_ctx(o, rs, timeframe)
    if not liquid(ctx, min_turnover):
        return None
    matched = {}
    for name in SETUPS:
        match_fn, fit_fn = REGISTRY[name]
        ev = match_fn(o, ctx, strict,
                      None if diag is None else diag.setdefault(name, {}))
        if ev is not None:
            # The volume block rides at the TOP LEVEL, beside fit and evidence,
            # not only inside evidence. Every one of its keys is a property of
            # the SYMBOL rather than of any one match, so a caller that wants to
            # print them for every setup -- including CONFLUENCE, whose evidence
            # slots are already spoken for -- must be able to read them off any
            # entry without knowing which predicate produced it. Taken from ctx,
            # the single place they are computed, so the five predicates cannot
            # drift apart on them.
            entry = _volume_block(ctx)
            entry.update({"fit": fit_fn(ev), "evidence": ev})
            matched[name] = entry
    return _add_confluence(matched)
