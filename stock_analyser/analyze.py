#!/usr/bin/env python3
"""
NSE technical analysis data engine.

Fetches OHLC for an NSE symbol and computes every number the framework needs:
levels, indicators, volume structure, R:R at current price, and the mechanical
setup score. Prints a report the agent formats into the final output.

Usage:
    python3 analyze.py LLOYDSENGG
    python3 analyze.py TATAMOTORS --catalyst 7
    python3 analyze.py RELIANCE --json

--catalyst is the only subjective input (0-10, default 5). Set it from news:
  8-10 = durable operating driver (earnings beat, sustained order inflow)
  4-6  = mixed / event-driven re-rating, or nothing notable
  0-3  = dilution pending, governance flag, regulatory overhang
"""

import argparse
import datetime as dt
import json
import sys
import urllib.error
import urllib.request

UA = {"User-Agent": "Mozilla/5.0"}

# Process-lifetime fetch cache. The watchlist renders full detail for shortlisted
# names after already scoring them; without this that second pass re-downloads
# every series. Keyed on the exact request, so it can never serve a mismatch.
_CACHE = {}


# ---------------------------------------------------------------- data access

def fetch(symbol, rng, interval, suffix=".NS"):
    """Yahoo chart API. NSE tickers take the .NS suffix.

    suffix="" fetches an index verbatim (e.g. ^NSEI for Nifty 50), which the
    watchlist relative-strength calc needs.
    """
    key = (symbol, rng, interval, suffix)
    if key in _CACHE:
        return _CACHE[key]

    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}{suffix}"
           f"?range={rng}&interval={interval}")
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise SystemExit(f"ERROR: {symbol}{suffix} not found on Yahoo. "
                             f"Check the NSE ticker spelling.")
        raise SystemExit(f"ERROR: HTTP {e.code} fetching {symbol}{suffix}")
    except Exception as e:
        raise SystemExit(f"ERROR: could not fetch {symbol}{suffix}: {e}")

    err = payload.get("chart", {}).get("error")
    if err:
        raise SystemExit(f"ERROR: Yahoo returned {err} for {symbol}{suffix}")
    results = payload.get("chart", {}).get("result") or []
    if not results:
        raise SystemExit(f"ERROR: empty result for {symbol}{suffix}")

    r0 = results[0]
    # Yahoo answers some unknown tickers with HTTP 200 and a result object that
    # has no timestamp/quote arrays at all, rather than a 404. Without this
    # check that surfaces as a raw KeyError instead of "check the spelling".
    if not r0.get("timestamp") or not r0.get("indicators", {}).get("quote"):
        raise SystemExit(f"ERROR: no price history returned for "
                         f"{symbol}{suffix}. Check the ticker spelling.")
    q = r0["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(r0["timestamp"]):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c):
            continue
        rows.append({"t": dt.datetime.utcfromtimestamp(t).date(),
                     "o": o, "h": h, "l": l, "c": c,
                     "v": q["volume"][i] or 0})
    meta = r0.get("meta", {})
    _CACHE[key] = (rows, meta)
    return rows, meta


# ------------------------------------------------------------------ indicators

def sma(v, n):
    return sum(v[-n:]) / n if len(v) >= n else None


def ema_series(v, n):
    k = 2 / (n + 1)
    e = v[0]
    out = [e]
    for x in v[1:]:
        e = x * k + e * (1 - k)
        out.append(e)
    return out


def rsi(closes, n=14):
    if len(closes) < n + 2:
        return None
    g = l_ = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        g += max(d, 0.0)
        l_ += max(-d, 0.0)
    ag, al = g / n, l_ / n
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0.0)) / n
        al = (al * (n - 1) + max(-d, 0.0)) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def atr(rows, n=14):
    if len(rows) < n + 2:
        return None
    trs = [max(rows[i]["h"] - rows[i]["l"],
               abs(rows[i]["h"] - rows[i - 1]["c"]),
               abs(rows[i]["l"] - rows[i - 1]["c"]))
           for i in range(1, len(rows))]
    a = sum(trs[:n]) / n
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n
    return a


def macd(closes):
    if len(closes) < 35:
        return None, None, None
    line = [a - b for a, b in zip(ema_series(closes, 12), ema_series(closes, 26))]
    sig = ema_series(line, 9)
    return line[-1], sig[-1], line[-1] - sig[-1]


def pct_return(closes, n):
    """Trailing % return over n bars. Feeds watchlist relative strength."""
    return (closes[-1] / closes[-1 - n] - 1) * 100 if len(closes) > n else None


def pivots(h, l, c):
    p = (h + l + c) / 3
    return {"P": p, "R1": 2 * p - l, "R2": p + (h - l), "R3": h + 2 * (p - l),
            "S1": 2 * p - h, "S2": p - (h - l), "S3": l - 2 * (h - p)}


# ------------------------------------------------------------------- structure

def fractals(rows, k=6):
    """Swing pivots: bar is the extreme of a 2k+1 window centred on it."""
    hi, lo = [], []
    for i in range(k, len(rows) - k):
        win = rows[i - k:i + k + 1]
        if rows[i]["h"] == max(x["h"] for x in win):
            hi.append((rows[i]["t"], rows[i]["h"]))
        if rows[i]["l"] == min(x["l"] for x in win):
            lo.append((rows[i]["t"], rows[i]["l"]))
    return hi, lo


def cluster(levels, tol_pct, max_width_pct=3.0):
    """Group nearby price levels into zones. Returns [(lo,hi,count,mid)].

    max_width_pct caps total zone width so a dense ladder of levels cannot
    chain into one meaninglessly wide band (a 'tested 26x' 8-point zone is
    not a level, it is the whole range).
    """
    if not levels:
        return []
    vals = sorted(levels)
    groups, cur = [], [vals[0]]
    for v in vals[1:]:
        gap_ok = (v - cur[-1]) / cur[-1] * 100 <= tol_pct
        width_ok = (v - cur[0]) / cur[0] * 100 <= max_width_pct
        if gap_ok and width_ok:
            cur.append(v)
        else:
            groups.append(cur)
            cur = [v]
    groups.append(cur)
    return [(min(g), max(g), len(g), sum(g) / len(g)) for g in groups]


def consolidation(rows, thrusts, lookback=40, min_bars=15):
    """The range that matters is the CURRENT one, not the 52-week span.

    Anchor to the bar after the most recent volume thrust when there is one --
    that thrust is what created the range. Otherwise use a fixed lookback.
    Without this the 'measured move' is computed off a year-long trend leg and
    produces targets that are not levels (e.g. a negative breakdown target).
    """
    seg = None
    if thrusts:
        last_thrust_date = max(r["t"] for r in thrusts)
        after = [r for r in rows if r["t"] > last_thrust_date]
        if len(after) >= min_bars:
            seg = after
    if seg is None:
        seg = rows[-lookback:]
    return {"bars": len(seg), "since": seg[0]["t"],
            "hi": max(r["h"] for r in seg), "lo": min(r["l"] for r in seg)}


def volume_profile(rows, nbins=30):
    lo = min(r["l"] for r in rows)
    hi = max(r["h"] for r in rows)
    w = (hi - lo) / nbins
    if w <= 0:
        return []
    buckets = [0.0] * nbins
    for r in rows:
        idx = min(nbins - 1, int(((r["h"] + r["l"] + r["c"]) / 3 - lo) / w))
        buckets[idx] += r["v"]
    return sorted(
        [{"lo": lo + i * w, "hi": lo + (i + 1) * w, "vol": buckets[i]}
         for i in range(nbins)],
        key=lambda b: -b["vol"])


def rejection_zones(rows, tol_pct=0.8, min_tests=3, max_width_pct=2.5):
    """Highs that were tested repeatedly and closed well below = supply."""
    tested = [r["h"] for r in rows if (r["h"] - r["c"]) / r["h"] * 100 > 0.5]
    zones = cluster(tested, tol_pct, max_width_pct)
    return [z for z in zones if z[2] >= min_tests]


# ----------------------------------------------------------------- the scoring

def score_trend(px, s20, s50, s100, s200):
    pts, notes = 0.0, []
    for cond, label in ((s200 and px > s200, "price>200D"),
                        (s50 and s200 and s50 > s200, "50D>200D"),
                        (s50 and px > s50, "price>50D"),
                        (s20 and s50 and s20 > s50, "20D>50D")):
        if cond:
            pts += 2.5
            notes.append(label)
    return pts, notes


def score_location(rr):
    if rr is None:
        return 5.0
    for thresh, s in ((3.0, 10), (2.0, 8), (1.5, 6), (1.0, 4), (0.75, 3)):
        if rr >= thresh:
            return float(s)
    return 1.0


def detect_thrusts(rows, mult=2.5, base=50, window=90):
    """Thrusts measured against a PRIOR baseline, never a window containing
    the thrust itself.

    Comparing a bar to an average that includes it is self-defeating: two
    221M-share crash days lifted avg50 to 88M, so neither could clear its own
    3x threshold and the biggest bars on the chart went undetected. The same
    contamination made avg20/avg50 read 0.80 -- scoring a volume explosion as
    a healthy dry-up.
    """
    out = []
    for i in range(max(base, len(rows) - window), len(rows)):
        b = sum(r["v"] for r in rows[i - base:i]) / base
        if b and rows[i]["v"] > mult * b:
            out.append({**rows[i], "x_avg": rows[i]["v"] / b})
    return out


def score_volume(v_last, av20, av50, thrusts, rows):
    """Volume quality -- DIRECTION-AWARE.

    A naive 'thrust happened, +2' is direction-blind and scores a distribution
    crash the same as an accumulation breakout: a stock down 11% on 3x volume
    was rating 9/10. Direction and recency both have to count. A stale
    up-thrust whose move has been fully retraced is not evidence of demand.
    """
    pts = 5.0
    recent_cut = rows[-20]["t"] if len(rows) >= 20 else rows[0]["t"]
    up = [t for t in thrusts if t["c"] > t["o"]]
    down = [t for t in thrusts if t["c"] <= t["o"]]
    recent_up = [t for t in up if t["t"] >= recent_cut]
    recent_down = [t for t in down if t["t"] >= recent_cut]

    if recent_up:
        pts += 2.0                      # fresh demand
    elif up:
        # Stale up-thrust: only credit it if price held the move.
        held = rows[-1]["c"] > max(t["c"] for t in up)
        pts += 1.0 if held else -0.5
    if recent_down:
        pts -= 2.5                      # distribution, and it is current
    elif down:
        pts -= 0.5

    # Dry-up measured against a baseline that EXCLUDES the recent bars, so a
    # current volume surge cannot masquerade as contraction.
    if len(rows) >= 55:
        baseline = sum(r["v"] for r in rows[-55:-5]) / 50
        recent = sum(r["v"] for r in rows[-5:]) / 5
        if baseline:
            ratio = recent / baseline
            if ratio < 0.85 and not recent_down:
                pts += 1.5              # genuine dry-up during consolidation
            elif ratio > 1.5 and recent_down:
                pts -= 1.0              # volume expanding on the way DOWN only
    return max(0.0, min(10.0, pts))


def score_momentum(rsi_d, rsi_w, hist_d, hist_w):
    pts = 5.0
    if rsi_d is not None:
        if 50 <= rsi_d <= 65:
            pts += 1.5                  # constructive, room to run
        elif rsi_d > 75:
            pts -= 1.5                  # extended
        elif rsi_d < 40:
            pts -= 1.0
    if rsi_w is not None and rsi_w > 70:
        pts -= 1.0
    if hist_d is not None:
        pts += 1.0 if hist_d > 0 else -1.0
    if hist_w is not None:
        pts += 1.5 if hist_w > 0 else -1.5
    return max(0.0, min(10.0, pts))


def score_volatility(atr_pct):
    if atr_pct is None:
        return 5.0
    for thresh, s in ((2.0, 9), (3.0, 7), (4.0, 5), (5.0, 4)):
        if atr_pct < thresh:
            return float(s)
    return 2.0


WEIGHTS = {"trend": .25, "location": .25, "volume": .15,
           "momentum": .15, "catalyst": .10, "volatility": .10}

BANDS = [(7.5, "INITIATE FULL POSITION"),
         (6.0, "HALF SIZE"),
         (4.5, "WATCHLIST - WAIT FOR TRIGGER"),
         (0.0, "STAND ASIDE / BEAR BIAS")]


RR_VETO = 1.5


def band(total, rr):
    """Weighted score picks the band -- but R:R holds a veto.

    A weighted average lets a 10/10 trend outvote a fatal entry price: a
    setup can score 6.3 ("half size") while its R:R at current price is
    0.82:1. No positive-expectancy system enters below ~1.5:1 no matter how
    good the trend, so a failing R:R caps the verdict at WATCHLIST rather
    than merely docking points. Trend and location are separate questions;
    the veto is what keeps them from being averaged together.
    """
    label = next(lb for lo, lb in BANDS if total >= lo)
    if rr is not None and rr < RR_VETO:
        capped = "WATCHLIST - WAIT FOR TRIGGER"
        if label in ("INITIATE FULL POSITION", "HALF SIZE"):
            return f"{capped}  [R:R VETO: {rr:.2f}:1 < {RR_VETO} - " \
                   f"score {total:.2f} would say {label}]"
    return label


# ----------------------------------------------------------------------- main

def compute(sym, catalyst=5.0, render=False, as_json=False):
    """Every number for one symbol. THE single scoring implementation.

    watchlist_analyser imports this rather than reimplementing the factors --
    two copies of the scoring would drift apart and the comparative table
    would stop agreeing with the single-name report.
    """
    sym = sym.upper().replace(".NS", "")

    d, meta = fetch(sym, "2y", "1d")
    w, _ = fetch(sym, "5y", "1wk")
    if len(d) < 60:
        raise SystemExit(f"ERROR: only {len(d)} daily bars for {sym} - "
                         f"too little history for this framework.")

    dc = [r["c"] for r in d]
    wc = [r["c"] for r in w]

    # Yahoo emits a stub bar for the session in progress: zero range
    # (o==h==l), or a close outside [low, high] entirely. Left in the series it
    # corrupts ATR, shifts the rejection zones and produces pivots where
    # P==R1==R2==S1. Drop it and treat its close as the live price -- the last
    # COMPLETED session is what every level must be measured from.
    # A session in progress also shows up as a normal-looking bar carrying a
    # tiny fraction of a day's volume -- three minutes after the open it has a
    # real range and a real close, and nothing about its shape says "partial".
    # Volume is the only reliable tell.
    prior_vol = ([b["v"] for b in d[-21:-1] if b["v"]] or [0])
    avg_prior = sum(prior_vol) / len(prior_vol) if prior_vol else 0

    def stub(b):
        malformed = b["h"] == b["l"] or b["c"] > b["h"] or b["c"] < b["l"]
        thin = bool(avg_prior) and b["v"] < 0.25 * avg_prior
        return malformed or thin

    partial = None
    if len(d) > 1 and stub(d[-1]) and not stub(d[-2]):
        partial = d.pop()
        dc.pop()
        if w and w[-1]["t"] >= partial["t"]:
            w = w[:-1]
            wc = wc[:-1]

    # Live quote vs last daily bar. If the last daily bar is stale, the live
    # quote IS the current session -- pivots must come from the last CLOSED bar.
    live = meta.get("regularMarketPrice") or (partial or d[-1])["c"]
    last = d[-1]
    intraday = abs(live - last["c"]) > 0.001 or partial is not None
    closed = last                       # last fully closed daily bar
    px = live

    s20, s50 = sma(dc, 20), sma(dc, 50)
    s100, s200 = sma(dc, 100), sma(dc, 200)
    e20 = ema_series(dc[-120:], 20)[-1] if len(dc) >= 120 else None
    rsi_d, rsi_w = rsi(dc), rsi(wc)
    atr_d, atr_w = atr(d), atr(w)
    atr_pct = atr_d / px * 100 if atr_d else None
    m_d, m_w = macd(dc), macd(wc)

    av20 = sum(r["v"] for r in d[-20:]) / 20
    av50 = sum(r["v"] for r in d[-50:]) / 50
    thrusts = detect_thrusts(d)
    thrust_dirs = {str(r["t"]): ("up" if r["c"] > r["o"] else "down") for r in thrusts}

    yr = d[-250:] if len(d) >= 250 else d
    hi52 = max(r["h"] for r in yr)
    lo52 = min(r["l"] for r in yr)
    swings_h, swings_l = fractals(yr, 6)
    rej = rejection_zones(d[-90:])
    vprof = volume_profile(yr)[:8]

    # Nearest resistance above / support below, from structure.
    #
    # A level inside 0.5x ATR is not resistance -- price is already AT it, and
    # counting it makes reward ~0 so every symbol scores location=1 and the
    # framework says STAND ASIDE to everything. Require real distance.
    noise = 0.5 * atr_d if atr_d else 0.0
    res_pool = [p for _, p in swings_h if p > px + noise] + \
               [z[3] for z in rej if z[3] > px + noise]
    if hi52 > px + noise:
        res_pool.append(hi52)
    sup_pool = [p for _, p in swings_l if p < px - noise] + \
               [b["hi"] for b in vprof if b["hi"] < px - noise]
    for ma_ in (s20, s50):
        if ma_ and ma_ < px - noise:
            sup_pool.append(ma_)
    res_sorted = sorted(set(res_pool))
    sup_sorted = sorted(set(sup_pool), reverse=True)
    nearest_res = res_sorted[0] if res_sorted else None
    next_res = res_sorted[1] if len(res_sorted) > 1 else None
    nearest_sup = sup_sorted[0] if sup_sorted else None

    # Current consolidation -- anchored to the last thrust, not the 52w span.
    cons = consolidation(d, thrusts)
    rng_hi, rng_lo = cons["hi"], cons["lo"]

    # R:R AT CURRENT PRICE with a volatility-floored stop. This is the gate.
    #
    # In blue sky there is no overhead resistance, so R:R would be undefined
    # and the veto would silently switch off -- precisely where a runaway
    # trend tempts the largest position. Fall back to the measured-move /
    # fib-extension objective so the gate stays live on every symbol.
    stop_floor = px - 1.5 * atr_d if atr_d else None
    rng = hi52 - lo52
    blue_sky = nearest_res is None
    if blue_sky:
        objectives = [t for t in (rng_hi + (rng_hi - rng_lo), lo52 + rng * 1.272)
                      if t > px]
        target = min(objectives) if objectives else None
    else:
        target = nearest_res
    rr_now = None
    if target and stop_floor and px > stop_floor:
        rr_now = (target - px) / (px - stop_floor)

    sc = {}
    sc["trend"], trend_notes = score_trend(px, s20, s50, s100, s200)
    sc["location"] = score_location(rr_now)
    sc["volume"] = score_volume(closed["v"], av20, av50, thrusts, d)
    sc["momentum"] = score_momentum(rsi_d, rsi_w, m_d[2], m_w[2])
    sc["catalyst"] = catalyst
    sc["volatility"] = score_volatility(atr_pct)
    total = sum(sc[k] * WEIGHTS[k] for k in WEIGHTS)

    out = {
        "symbol": sym, "name": meta.get("longName", sym),
        "price": px, "intraday_bar_open": intraday,
        "last_closed_bar": {k: (str(v) if k == "t" else v) for k, v in closed.items()},
        "hi52": hi52, "lo52": lo52,
        "ma": {"sma20": s20, "sma50": s50, "sma100": s100, "sma200": s200, "ema20": e20},
        "rsi": {"daily": rsi_d, "weekly": rsi_w},
        "macd": {"daily": {"line": m_d[0], "signal": m_d[1], "hist": m_d[2]},
                 "weekly": {"line": m_w[0], "signal": m_w[1], "hist": m_w[2]}},
        "atr": {"daily": atr_d, "weekly": atr_w, "daily_pct": atr_pct},
        "volume": {"last": closed["v"], "avg20": av20, "avg50": av50,
                   "dryup_ratio": av20 / av50 if av50 else None,
                   "thrusts": [{"date": str(r["t"]), "vol": r["v"], "x_avg": r["x_avg"],
                                "dir": "up" if r["c"] > r["o"] else "down"} for r in thrusts]},
        "swing_highs": [{"date": str(t), "px": p} for t, p in swings_h[-10:]],
        "swing_lows": [{"date": str(t), "px": p} for t, p in swings_l[-10:]],
        "rejection_zones": [{"lo": z[0], "hi": z[1], "tests": z[2], "mid": z[3]}
                            for z in rej],
        "volume_nodes": vprof,
        "range": {"hi": rng_hi, "lo": rng_lo, "width": rng_hi - rng_lo,
                  "bars": cons["bars"], "since": str(cons["since"]),
                  "breakout_target": rng_hi + (rng_hi - rng_lo),
                  "breakdown_target": rng_lo - (rng_hi - rng_lo)},
        "fib_retracement": {str(f): hi52 - rng * f
                            for f in (.236, .382, .5, .618, .786)},
        "fib_extension": {str(f): lo52 + rng * f for f in (1.272, 1.414, 1.618)},
        "pivots_next_session": pivots(closed["h"], closed["l"], closed["c"]),
        "entry_gate": {
            "nearest_resistance": nearest_res,
            "next_resistance": next_res,
            "blue_sky": blue_sky,
            "objective_used": target,
            "nearest_support": nearest_sup,
            "min_stop_1.5atr": stop_floor,
            "risk_pct": (px - stop_floor) / px * 100 if stop_floor else None,
            "reward_pct": (target - px) / px * 100 if target else None,
            "rr_at_current_price": rr_now,
            "passes_2to1_gate": bool(rr_now and rr_now >= 2.0),
        },
        "score": {**sc, "weights": WEIGHTS, "total": total, "verdict": band(total, rr_now)},
        "trend_notes": trend_notes,
        "returns": {"1m": pct_return(dc, 21), "3m": pct_return(dc, 63),
                    "6m": pct_return(dc, 126)},
    }

    if not render:
        return out
    if as_json:
        print(json.dumps(out, indent=2, default=str))
        return out

    p = print
    p(f"=== {out['name']} ({sym}.NS) ===")
    p(f"Price {px:.2f}   52w {lo52:.2f} - {hi52:.2f}"
      f"   {'[live bar in progress]' if intraday else '[at last close]'}")
    p(f"Last CLOSED bar {closed['t']}  O{closed['o']:.2f} H{closed['h']:.2f} "
      f"L{closed['l']:.2f} C{closed['c']:.2f} V{closed['v']/1e6:.2f}M")
    p(f"\nMA   20D {s20:.2f}  50D {s50:.2f}  "
      f"100D {s100 if s100 is None else round(s100,2)}  "
      f"200D {s200 if s200 is None else round(s200,2)}   [{', '.join(trend_notes)}]")
    p(f"RSI  daily {rsi_d:.1f}   weekly {rsi_w:.1f}")
    p(f"MACD daily hist {m_d[2]:+.2f}   weekly hist {m_w[2]:+.2f}")
    p(f"ATR  daily {atr_d:.2f} ({atr_pct:.1f}% of price)   weekly {atr_w:.2f}")
    p(f"VOL  last {closed['v']/1e6:.2f}M  avg20 {av20/1e6:.2f}M  "
      f"avg50 {av50/1e6:.2f}M  dry-up {av20/av50:.2f}x")
    for t in out["volume"]["thrusts"]:
        p(f"     THRUST {t['date']}  {t['vol']/1e6:.1f}M = {t['x_avg']:.1f}x avg50  "
          f"[{t['dir'].upper()}-thrust = {'accumulation' if t['dir']=='up' else 'DISTRIBUTION'}]")

    p("\n--- SWING HIGHS ---")
    for s in out["swing_highs"]:
        p(f"  {s['date']}  {s['px']:.2f}")
    p("--- SWING LOWS ---")
    for s in out["swing_lows"]:
        p(f"  {s['date']}  {s['px']:.2f}")
    p("--- REJECTION ZONES (repeatedly tested supply) ---")
    for z in out["rejection_zones"]:
        p(f"  {z['lo']:.2f}-{z['hi']:.2f}  tested {z['tests']}x")
    p("--- VOLUME NODES (12m, heaviest first) ---")
    for b in vprof:
        p(f"  {b['lo']:.2f}-{b['hi']:.2f}  {b['vol']/1e6:.0f}M")

    r_ = out["range"]
    p(f"\nRANGE {r_['lo']:.2f} - {r_['hi']:.2f}  (width {r_['width']:.2f}, "
      f"{r_['bars']} bars since {r_['since']})")
    p(f"  breakout measured move  -> {r_['breakout_target']:.2f}")
    p(f"  breakdown measured move -> {r_['breakdown_target']:.2f}")
    p("FIB retracement (52w low->high): " +
      "  ".join(f"{k}={v:.2f}" for k, v in out["fib_retracement"].items()))
    p("FIB extension:                   " +
      "  ".join(f"{k}={v:.2f}" for k, v in out["fib_extension"].items()))
    p("PIVOTS next session: " +
      "  ".join(f"{k}={v:.2f}" for k, v in out["pivots_next_session"].items()))

    g = out["entry_gate"]
    p("\n=== ENTRY GATE AT CURRENT PRICE ===")
    p(f"  nearest resistance  {g['nearest_resistance']:.2f}"
      if g["nearest_resistance"] else "  nearest resistance  none (blue sky)")
    if g["blue_sky"]:
        p(f"  BLUE SKY - no overhead resistance; objective from measured move "
          f"= {g['objective_used']:.2f}" if g["objective_used"] else
          "  BLUE SKY - no objective computable")
    if g["next_resistance"]:
        p(f"  next resistance     {g['next_resistance']:.2f}")
    if g["nearest_support"]:
        p(f"  nearest support     {g['nearest_support']:.2f}")
    p(f"  min stop (1.5xATR)  {g['min_stop_1.5atr']:.2f}   risk {g['risk_pct']:.1f}%")
    if g["rr_at_current_price"]:
        p(f"  reward {g['reward_pct']:.1f}%   R:R {g['rr_at_current_price']:.2f}:1"
          f"   {'PASS' if g['passes_2to1_gate'] else 'FAIL (needs >=2:1)'}")

    p("\n=== SCORE ===")
    for k in ("trend", "location", "volume", "momentum", "catalyst", "volatility"):
        p(f"  {k:<11} {sc[k]:>4.1f}/10  x{WEIGHTS[k]:.2f} = {sc[k]*WEIGHTS[k]:.2f}")
    p(f"  {'TOTAL':<11} {total:>4.2f}/10  -> {band(total, rr_now)}")
    if sc["catalyst"] == 5.0:
        p("  (catalyst is the default 5 - set --catalyst after checking news)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol", help="NSE ticker without .NS, e.g. LLOYDSENGG")
    ap.add_argument("--catalyst", type=float, default=5.0,
                    help="0-10 fundamental/news quality score (default 5)")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    a = ap.parse_args()
    compute(a.symbol, catalyst=a.catalyst, render=True, as_json=a.json)


if __name__ == "__main__":
    main()
