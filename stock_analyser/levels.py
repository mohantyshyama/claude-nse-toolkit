#!/usr/bin/env python3
"""
Multi-method stop-loss and target generator for an NSE position.

Given a symbol and an entry price, derives candidate levels from EIGHT
independent methods, then clusters them so you can see where methods agree.
One method's level is an opinion; four methods landing on the same price is
information -- confluence is the point of this tool, not any single number.

Usage:
    python3 levels.py LLOYDSENGG --entry 89.70
    python3 levels.py TITAN --entry 4820 --side long
    python3 levels.py MPHASIS --entry 2361 --json

Methods
  1 volatility    ATR multiples around the entry
  2 horizontal    fractal swing highs/lows and repeatedly-tested zones
  3 fibonacci     retracements/extensions of the live leg and the 52-week leg
  4 trendline     fitted through recent swing lows / highs, projected to today
  5 volume-candle key prices of high-volume thrust bars (where size changed hands)
  6 volume-node   heaviest traded price buckets over 12 months
  7 moving-avg    20/50/100/200-day as dynamic support
  8 pivots        classic floor pivots off the last closed session
  9 measured-move consolidation range projection
"""

import argparse
import importlib.util
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "analyze", os.path.join(HERE, "analyze.py"))
A = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(A)


# ------------------------------------------------------------------ helpers

def drop_partial(rows):
    """Same in-progress-bar guard analyze.compute() uses."""
    pv = [b["v"] for b in rows[-21:-1] if b["v"]]
    avg = sum(pv) / len(pv) if pv else 0
    if len(rows) > 1:
        last = rows[-1]
        malformed = last["h"] == last["l"] or last["c"] > last["h"] or last["c"] < last["l"]
        thin = bool(avg) and last["v"] < 0.25 * avg
        if malformed or thin:
            return rows[:-1], last
    return rows, None


def fit_line(p1, p2):
    """(index, price) pairs -> slope, intercept."""
    (x1, y1), (x2, y2) = p1, p2
    if x2 == x1:
        return None
    m = (y2 - y1) / (x2 - x1)
    return m, y1 - m * x1


def best_trendline(rows, pivots_, kind, tol=0.015):
    """Pick the pivot pair whose line has the most touches and no decisive
    violation. Returns (value_today, touches, description) or None.

    A trendline nobody respected is not a level. Requiring touches and
    rejecting violated lines is what separates a real trendline from two
    points connected by wishful thinking.
    """
    if len(pivots_) < 2:
        return None
    idx = {r["t"]: i for i, r in enumerate(rows)}
    pts = [(idx[t], p) for t, p in pivots_ if t in idx]
    if len(pts) < 2:
        return None
    n = len(rows) - 1
    best = None
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            line = fit_line(pts[i], pts[j])
            if not line:
                continue
            m, c = line
            if kind == "support" and m < 0:
                continue                     # want rising support
            if kind == "resistance" and m > 0:
                continue                     # want falling resistance
            touches = viol = 0
            for k in range(pts[i][0], len(rows)):
                y = m * k + c
                if y <= 0:
                    continue
                bar = rows[k]
                if kind == "support":
                    if abs(bar["l"] - y) / y <= tol:
                        touches += 1
                    elif bar["c"] < y * (1 - tol):
                        viol += 1
                else:
                    if abs(bar["h"] - y) / y <= tol:
                        touches += 1
                    elif bar["c"] > y * (1 + tol):
                        viol += 1
            if viol > 1 or touches < 2:
                continue
            today = m * n + c
            if today <= 0:
                continue
            score = (touches, -viol)
            if best is None or score > best[0]:
                best = (score, today, touches, viol,
                        f"through {rows[pts[i][0]]['t']} and {rows[pts[j][0]]['t']}")
    if not best:
        return None
    return best[1], best[2], best[4]


def fib_leg(rows, swings_h, swings_l, min_bars=12, lookback=60):
    """The structural advance the market is currently retracing.

    Picking "the most recent swing low with a decent rally after it" selects a
    five-session pop over the multi-week advance that actually built the
    structure. Choose the LARGEST-range leg instead, and require it to span
    enough bars to be a real move rather than a spike.
    """
    if not swings_l or not swings_h:
        return None
    idx = {r["t"]: i for i, r in enumerate(rows)}
    # Only lows inside the recent window qualify. Without this the largest leg
    # is always the whole bull run, which the separate 52-week grid already
    # covers -- the point of this one is the advance currently being retraced.
    cutoff = len(rows) - lookback
    best = None
    for lo_t, lo_p in swings_l:
        if idx.get(lo_t, -1) < cutoff:
            continue
        highs_after = [(ht, hp) for ht, hp in swings_h
                       if ht > lo_t and hp > lo_p]
        if not highs_after:
            continue
        hi_t, hi_p = max(highs_after, key=lambda x: x[1])
        if lo_t not in idx or hi_t not in idx:
            continue
        if idx[hi_t] - idx[lo_t] < min_bars:
            continue
        rng = hi_p - lo_p
        if best is None or rng > best[0]:
            best = (rng, lo_t, lo_p, hi_t, hi_p)
    if not best:
        return None
    return best[1], best[2], best[3], best[4]


def cluster_levels(cands, tol_pct=1.2, max_width_pct=2.5):
    """Group candidate levels from different methods into confluence zones.

    max_width_pct stops a dense ladder chaining into one 4%-wide "zone" --
    a band that broad is a neighbourhood, not a level, and it inflates the
    method count by sweeping in things that do not actually agree.
    """
    if not cands:
        return []
    s = sorted(cands, key=lambda c: c["px"])
    groups, cur = [], [s[0]]
    for c in s[1:]:
        gap_ok = (c["px"] - cur[-1]["px"]) / cur[-1]["px"] * 100 <= tol_pct
        width_ok = (c["px"] - cur[0]["px"]) / cur[0]["px"] * 100 <= max_width_pct
        if gap_ok and width_ok:
            cur.append(c)
        else:
            groups.append(cur)
            cur = [c]
    groups.append(cur)
    out = []
    for g in groups:
        methods = sorted({c["method"] for c in g})
        out.append({"lo": min(c["px"] for c in g), "hi": max(c["px"] for c in g),
                    "mid": sum(c["px"] for c in g) / len(g),
                    "n_methods": len(methods), "methods": methods,
                    "items": g})
    return out


# --------------------------------------------------------------------- main

def build(sym, entry, side="long"):
    d, meta = A.fetch(sym, "2y", "1d")
    d, partial = drop_partial(d)
    if len(d) < 60:
        raise SystemExit(f"ERROR: only {len(d)} bars for {sym}")
    live = meta.get("regularMarketPrice") or (partial or d[-1])["c"]
    entry = entry or live
    dc = [r["c"] for r in d]
    atr = A.atr(d)
    yr = d[-250:] if len(d) >= 250 else d
    sh, sl = A.fractals(yr, 6)
    rej = A.rejection_zones(d[-120:])
    vprof = A.volume_profile(yr)[:10]
    thrusts = A.detect_thrusts(d, window=180)
    closed = d[-1]

    sup, res = [], []      # candidate dicts: method, px, why

    # A level 50% below entry is not a stop and a level 200% above is not a
    # target. Keep only what is tradeable from here: within 6x ATR, floored at
    # 12% so low-volatility names still get a usable window.
    reach = max(6 * atr, entry * 0.12)

    def add(bucket, method, px, why):
        if px and px > 0 and abs(px - entry) <= reach:
            bucket.append({"method": method, "px": round(px, 2), "why": why})

    # 1 -- volatility
    for k in (1.0, 1.5, 2.0, 2.5):
        add(sup, "volatility", entry - k * atr, f"{k}x ATR below entry")
        add(res, "volatility", entry + k * atr, f"{k}x ATR above entry")

    # 2 -- horizontal structure
    for t, p in sl:
        if p < entry:
            add(sup, "horizontal", p, f"swing low {t}")
    for t, p in sh:
        if p > entry:
            add(res, "horizontal", p, f"swing high {t}")
    for z_lo, z_hi, z_tests, _mid in rej:          # cluster() yields tuples
        if z_hi < entry:
            add(sup, "horizontal", z_hi,
                f"tested zone {z_lo:.2f}-{z_hi:.2f}, {z_tests}x (now support)")
        elif z_lo > entry:
            add(res, "horizontal", z_lo,
                f"tested zone {z_lo:.2f}-{z_hi:.2f}, {z_tests}x")

    # 3 -- fibonacci
    leg = fib_leg(d, sh, sl)
    fibs = []
    if leg:
        lo_t, lo_p, hi_t, hi_p = leg
        rng = hi_p - lo_p
        for f in (0.236, 0.382, 0.5, 0.618, 0.786):
            fibs.append((hi_p - rng * f, f"{f:.3f} retrace of {lo_p:.2f}({lo_t})->{hi_p:.2f}({hi_t})"))
        for f in (1.272, 1.414, 1.618):
            fibs.append((lo_p + rng * f, f"{f} extension of the live leg"))
    hi52 = max(r["h"] for r in yr)
    lo52 = min(r["l"] for r in yr)
    r52 = hi52 - lo52
    for f in (0.236, 0.382, 0.5):
        fibs.append((hi52 - r52 * f, f"{f:.3f} retrace of the 52-week leg"))
    for f in (1.272, 1.618):
        fibs.append((lo52 + r52 * f, f"{f} extension of the 52-week leg"))
    for px, why in fibs:
        add(sup if px < entry else res, "fibonacci", px, why)

    # 4 -- trendline
    tl_s = best_trendline(d[-180:], sl, "support")
    if tl_s:
        add(sup if tl_s[0] < entry else res, "trendline", tl_s[0],
            f"rising support line, {tl_s[1]} touches, {tl_s[2]}")
    tl_r = best_trendline(d[-180:], sh, "resistance")
    if tl_r:
        add(res if tl_r[0] > entry else sup, "trendline", tl_r[0],
            f"falling resistance line, {tl_r[1]} touches, {tl_r[2]}")

    # 5 -- volume candles: where size actually changed hands
    for t in sorted(thrusts, key=lambda r: -r["v"])[:6]:
        up = t["c"] > t["o"]
        tag = "UP" if up else "DOWN"
        lbl = f"{tag}-thrust {t['t']} {t['v']/1e6:.0f}M ({t['x_avg']:.1f}x)"
        if up:
            add(sup if t["l"] < entry else res, "volume-candle", t["l"],
                f"low of {lbl} — demand appeared here")
            add(res if t["h"] > entry else sup, "volume-candle", t["h"],
                f"high of {lbl}")
        else:
            add(res if t["h"] > entry else sup, "volume-candle", t["h"],
                f"high of {lbl} — supply appeared here")
            add(sup if t["l"] < entry else res, "volume-candle", t["l"],
                f"low of {lbl}")

    # 6 -- volume nodes
    for b in vprof[:6]:
        mid = (b["lo"] + b["hi"]) / 2
        add(sup if mid < entry else res, "volume-node", mid,
            f"node {b['lo']:.2f}-{b['hi']:.2f}, {b['vol']/1e6:.0f}M shares")

    # 7 -- moving averages
    for n, label in ((20, "20-day"), (50, "50-day"), (100, "100-day"), (200, "200-day")):
        v = A.sma(dc, n)
        if v:
            add(sup if v < entry else res, "moving-avg", v, f"{label} moving average")

    # 8 -- pivots
    pv = A.pivots(closed["h"], closed["l"], closed["c"])
    for k, v in pv.items():
        if k == "P":
            continue
        add(sup if v < entry else res, "pivot", v, f"floor pivot {k}")

    # 9 -- measured move
    cons = A.consolidation(d, thrusts)
    width = cons["hi"] - cons["lo"]
    add(res, "measured-move", cons["hi"] + width,
        f"range {cons['lo']:.2f}-{cons['hi']:.2f} projected up")
    add(sup, "measured-move", cons["lo"] - width,
        f"range {cons['lo']:.2f}-{cons['hi']:.2f} projected down")
    add(res, "measured-move", cons["hi"], "range high (breakout trigger)")
    add(sup, "measured-move", cons["lo"], "range low (structure breaks)")

    return dict(sym=sym, name=meta.get("longName", sym), entry=entry, live=live,
                atr=atr, closed=closed, sup=sup, res=res,
                sup_zones=cluster_levels(sup), res_zones=cluster_levels(res),
                leg=leg, side=side)


METHOD_ORDER = ["volatility", "horizontal", "fibonacci", "trendline",
                "volume-candle", "volume-node", "moving-avg", "pivot",
                "measured-move"]


def render(b):
    entry, atr = b["entry"], b["atr"]
    p = print
    p(f"=== {b['name']} ({b['sym']}.NS) ===")
    p(f"Entry {entry:.2f}   live {b['live']:.2f}   "
      f"ATR(14) {atr:.2f} ({atr/entry*100:.2f}% of entry)")
    p(f"Last closed bar {b['closed']['t']}  C{b['closed']['c']:.2f}")
    if b["leg"]:
        lo_t, lo_p, hi_t, hi_p = b["leg"]
        p(f"Live fib leg: {lo_p:.2f} ({lo_t}) -> {hi_p:.2f} ({hi_t})")

    for title, bucket, sign in (("STOP-LOSS CANDIDATES (below entry)", b["sup"], -1),
                                ("TARGET CANDIDATES (above entry)", b["res"], +1)):
        p("\n" + "=" * 100)
        p(title)
        p("=" * 100)
        for meth in METHOD_ORDER:
            items = sorted([c for c in bucket if c["method"] == meth],
                           key=lambda c: -c["px"] if sign < 0 else c["px"])
            if not items:
                continue
            p(f"\n  [{meth}]")
            seen = set()
            for c in items:
                if c["px"] in seen:
                    continue
                seen.add(c["px"])
                dist = (c["px"] - entry) / entry * 100
                mult = abs(c["px"] - entry) / atr
                p(f"     {c['px']:>9.2f}  {dist:+6.2f}%  {mult:4.2f}xATR   {c['why']}")

    # confluence
    for title, zones, sign in (("CONFLUENCE — SUPPORT (stop zones)", b["sup_zones"], -1),
                               ("CONFLUENCE — RESISTANCE (target zones)", b["res_zones"], +1)):
        p("\n" + "=" * 100)
        p(title + "   [ranked by how many independent methods agree]")
        p("=" * 100)
        ranked = sorted(zones, key=lambda z: (-z["n_methods"], -abs(z["mid"] - entry)))
        for z in ranked[:8]:
            if z["n_methods"] < 2:
                continue
            dist = (z["mid"] - entry) / entry * 100
            mult = abs(z["mid"] - entry) / atr
            bar = "#" * z["n_methods"]
            p(f"\n  {z['lo']:.2f}-{z['hi']:.2f}  (mid {z['mid']:.2f}, {dist:+.2f}%, "
              f"{mult:.2f}xATR)   {z['n_methods']} methods {bar}")
            for m in z["methods"]:
                ex = next(c for c in z["items"] if c["method"] == m)
                p(f"       - {m:<14} {ex['px']:>9.2f}  {ex['why']}")

    p("\n" + "=" * 100)
    p("HOW TO USE")
    p("=" * 100)
    p("  A stop belongs just BELOW a high-confluence support zone, and at least")
    p("  1.5x ATR from entry. If the nearest such zone is closer than that, drop")
    p("  to the next one down or cut position size -- never tighten inside the")
    p("  noise band. Targets belong just BELOW a high-confluence resistance zone:")
    p("  sell into the wall, do not wait for price to clear it.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--entry", type=float, default=None,
                    help="your entry price (defaults to the live price)")
    ap.add_argument("--side", default="long", choices=["long", "short"])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    b = build(a.symbol.upper().replace(".NS", ""), a.entry, a.side)
    if a.json:
        b.pop("closed", None)
        print(json.dumps(b, indent=2, default=str))
    else:
        render(b)


if __name__ == "__main__":
    main()
