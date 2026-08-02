#!/usr/bin/env python3
"""
Stock planner: stop-loss and target levels for a long position.

Given a symbol and an entry price, produces
  1. candidate levels from nine independent methods
  2. confluence zones, ranked by how many methods agree
  3. empirical probability tests on this stock's own history
  4. one recommended plan -- close-based stop, hard stop, and three targets

Usage:
    python3 planner.py LLOYDSENGG --entry 89.70
    python3 planner.py TITAN --entry 4820 --json

Long positions only. The geometry lives in stock_analyser/levels.py and the
indicators in stock_analyser/analyze.py; both are imported, never
reimplemented, so a fix in one place fixes every skill that uses it.
"""

import argparse
import importlib.util
import json
import os

SIBLING = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "stock_analyser")


def _load(name):
    """Local copy first, sibling skill second.

    Sibling layout keeps one copy of the engine (Claude Code, all three skills
    installed together). Local copy supports isolated installs where each skill
    is packaged alone and cannot see its neighbours.
    """
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    path = here if os.path.exists(here) else os.path.normpath(
        os.path.join(SIBLING, name))
    if not os.path.exists(path):
        raise SystemExit(
            f"ERROR: cannot find {name}. stock_planner needs either its own "
            f"copy of {name} in the skill folder, or the stock_analyser skill "
            f"installed alongside it in ~/.claude/skills/.")
    spec = importlib.util.spec_from_file_location(name[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


A = _load("analyze.py")
L = _load("levels.py")


# ---------------------------------------------------------------- probability

def hit_rate(rows, pct_below, horizon, mode="close"):
    """Share of historical entries where price fell pct_below within horizon.

    mode="close" tests DAILY CLOSES (what a close-based stop reacts to);
    mode="low" tests intraday lows (what a standing GTT reacts to). The gap
    between the two is the cost of using a hard stop.
    """
    n = hits = 0
    for i in range(len(rows) - horizon - 1):
        e = rows[i]["c"]
        seg = rows[i + 1:i + 1 + horizon]
        worst = min(b["c"] for b in seg) if mode == "close" else min(b["l"] for b in seg)
        n += 1
        if (e - worst) / e * 100 >= pct_below:
            hits += 1
    return hits / n * 100 if n else None


def wick_out_rate(rows, level):
    """Of the bars that dip below a level having closed above it the day
    before, how many close back above the same session? That fraction is what
    a hard intraday stop donates to noise."""
    tests = saved = 0
    for i in range(1, len(rows)):
        if rows[i - 1]["c"] > level and rows[i]["l"] <= level:
            tests += 1
            if rows[i]["c"] > level:
                saved += 1
    return tests, saved, (saved / tests * 100 if tests else None)


def first_touch(rows, tgt_pct, stop_pct, horizon):
    """Which happens first from a historical entry: the target (intraday high)
    or the stop (daily close)? Order is what decides a trade -- both can occur
    inside the same window, and only the sequence pays you."""
    win = loss = none = 0
    for i in range(len(rows) - horizon - 1):
        e = rows[i]["c"]
        out = None
        for b in rows[i + 1:i + 1 + horizon]:
            if (b["h"] - e) / e * 100 >= tgt_pct:
                out = "win"
                break
            if (e - b["c"]) / e * 100 >= stop_pct:
                out = "loss"
                break
        if out == "win":
            win += 1
        elif out == "loss":
            loss += 1
        else:
            none += 1
    tot = win + loss + none
    return (win / tot * 100, loss / tot * 100, none / tot * 100) if tot else (0, 0, 0)


# -------------------------------------------------------------- recommendation

def pick_stops(b, rows, atr, entry):
    """Working stop just below the nearest qualifying support zone; hard stop
    just below a deeper, broadly-confirmed one."""
    zones = [z for z in b["sup_zones"] if z["n_methods"] >= 2]
    zones.sort(key=lambda z: -z["lo"])            # nearest first

    def place(z):
        return round(z["lo"] * 0.998, 2)

    working = next((z for z in zones
                    if (entry - place(z)) / atr >= 1.5), None)
    hard = None
    if working:
        wstop = place(working)
        # The hard stop is gap insurance, so it has to sit MATERIALLY below the
        # working stop. A disaster stop 0.6% lower insures nothing -- require a
        # full ATR of separation, and prefer the most broadly-confirmed zone
        # below rather than merely the first one that clears the threshold.
        # Nearest qualifying zone, not the most-confirmed one: preferring
        # method count alone picks a 5-method cluster 27% away, which is
        # abandonment rather than insurance. Needs real separation from the
        # working stop AND a ceiling on total distance.
        below = [z for z in zones
                 if wstop - place(z) >= 0.75 * atr
                 and z["n_methods"] >= 3
                 and (entry - place(z)) / atr <= 3.5]
        if below:
            hard = max(below, key=lambda z: z["lo"])
    return ((working, place(working)) if working else (None, None)), \
           ((hard, place(hard)) if hard else (None, None))


def pick_targets(b, rows, atr, entry, stop_pct, horizon=15):
    """Rank resistance zones by the probability the target is reached BEFORE
    the stop. Sell into the wall: use each zone's LOWER edge, not its middle.

    A more distant target always pays more per share and always fills less
    often. Ranking on probability rather than reward is the risk-averse
    choice, and it is what the sequence test is for."""
    cands = []
    for z in b["res_zones"]:
        px = round(z["lo"] * 0.998, 2)
        if px <= entry:
            continue
        reward = (px - entry) / entry * 100
        if reward < 0.4 * atr / entry * 100:       # too close to bother
            continue
        w, l, n = first_touch(rows, reward, stop_pct, horizon)
        # NET expectancy: probability-weighted gain minus probability-weighted
        # loss. Reporting only p_first x reward flatters every target, because
        # the stop leg is where the money actually goes.
        cands.append({"zone": z, "px": px, "reward": reward,
                      "p_first": w, "p_stop": l, "p_neither": n,
                      "ev_gross": w / 100 * reward,
                      "ev_net": w / 100 * reward - l / 100 * stop_pct,
                      "n_methods": z["n_methods"]})
    cands.sort(key=lambda c: c["px"])
    return cands


def build(sym, entry):
    b = L.build(sym, entry)
    rows, _ = L.drop_partial(A.fetch(sym, "2y", "1d")[0])
    atr, entry = b["atr"], b["entry"]

    (wz, wstop), (hz, hstop) = pick_stops(b, rows, atr, entry)
    stop_pct = (entry - wstop) / entry * 100 if wstop else 1.5 * atr / entry * 100
    tgts = pick_targets(b, rows, atr, entry, stop_pct)

    # probability profile for every candidate stop zone
    stop_probs = []
    for z in sorted([z for z in b["sup_zones"] if z["n_methods"] >= 2],
                    key=lambda z: -z["lo"])[:6]:
        px = round(z["lo"] * 0.998, 2)
        pct = (entry - px) / entry * 100
        t, s, w = wick_out_rate(rows, px)
        stop_probs.append({
            "px": px, "pct": pct, "atr_mult": (entry - px) / atr,
            "n_methods": z["n_methods"],
            "close_7": hit_rate(rows, pct, 7, "close"),
            "close_15": hit_rate(rows, pct, 15, "close"),
            "low_15": hit_rate(rows, pct, 15, "low"),
            "wick_tests": t, "wick_saved": s, "wick_pct": w})

    return dict(base=b, rows=rows, atr=atr, entry=entry,
                working_zone=wz, working_stop=wstop,
                hard_zone=hz, hard_stop=hstop,
                stop_probs=stop_probs, targets=tgts, stop_pct=stop_pct)


# ------------------------------------------------------------------- rendering

def render(p):
    b, entry, atr = p["base"], p["entry"], p["atr"]
    pr = print
    pr("=" * 96)
    pr(f"STOCK PLANNER — {b['name']} ({b['sym']}.NS)   LONG from {entry:.2f}")
    pr("=" * 96)
    pr(f"Live {b['live']:.2f}   ATR(14) {atr:.2f} ({atr/entry*100:.2f}% of entry)   "
       f"last closed bar {b['closed']['t']}")
    if b["leg"]:
        lo_t, lo_p, hi_t, hi_p = b["leg"]
        pr(f"Fibonacci leg in use: {lo_p:.2f} ({lo_t}) -> {hi_p:.2f} ({hi_t})")

    # 1 -- levels by method
    for title, bucket, rev in (("SUPPORT / STOP-LOSS LEVELS BY METHOD", b["sup"], True),
                               ("RESISTANCE / TARGET LEVELS BY METHOD", b["res"], False)):
        pr("\n" + "=" * 96)
        pr(title)
        pr("=" * 96)
        for meth in L.METHOD_ORDER:
            items = sorted({c["px"]: c for c in bucket if c["method"] == meth}.values(),
                           key=lambda c: -c["px"] if rev else c["px"])
            if not items:
                continue
            pr(f"\n  [{meth}]")
            for c in items[:7]:
                d = (c["px"] - entry) / entry * 100
                pr(f"     {c['px']:>10.2f}  {d:+6.2f}%  {abs(c['px']-entry)/atr:4.2f}xATR   {c['why']}")

    # 2 -- confluence
    for title, zones in (("CONFLUENCE — SUPPORT ZONES", b["sup_zones"]),
                         ("CONFLUENCE — RESISTANCE ZONES", b["res_zones"])):
        pr("\n" + "=" * 96)
        pr(title + "   [ranked by number of agreeing methods]")
        pr("=" * 96)
        for z in sorted(zones, key=lambda z: -z["n_methods"])[:6]:
            if z["n_methods"] < 2:
                continue
            d = (z["mid"] - entry) / entry * 100
            pr(f"\n  {z['lo']:.2f}-{z['hi']:.2f}   mid {z['mid']:.2f}  {d:+.2f}%  "
               f"{abs(z['mid']-entry)/atr:.2f}xATR   {z['n_methods']} methods "
               f"{'#'*z['n_methods']}")
            pr(f"       {', '.join(z['methods'])}")

    # 3 -- probability
    pr("\n" + "=" * 96)
    pr("EMPIRICAL TESTS — this stock's own 2-year record")
    pr("=" * 96)
    pr("\n  Candidate stops: how often price fell that far, and wick-out risk")
    pr(f"  {'stop':>8} {'dist':>7} {'xATR':>6} {'meth':>5} | "
       f"{'close<7d':>9} {'close<15d':>10} {'low<15d':>9} | wick-outs")
    for s in p["stop_probs"]:
        wk = (f"{s['wick_saved']}/{s['wick_tests']} = {s['wick_pct']:.0f}%"
              if s["wick_pct"] is not None else "no tests")
        pr(f"  {s['px']:>8.2f} {s['pct']:>6.2f}% {s['atr_mult']:>6.2f} "
           f"{s['n_methods']:>5} | {s['close_7']:>8.1f}% {s['close_15']:>9.1f}% "
           f"{s['low_15']:>8.1f}% | {wk}")
    pr("\n  close<Nd = chance a DAILY CLOSE breaches it within N sessions "
       "(what a close-based stop reacts to)")
    pr("  low<15d  = chance an intraday LOW breaches it within 15 sessions "
       "(what a standing GTT reacts to)")
    pr("  wick-outs = of genuine tests, how many closed back above the same "
       "day. High % argues for a close-based stop.")

    pr(f"\n  Candidate targets: which comes first over 15 sessions, "
       f"target or the {p['stop_pct']:.2f}% stop?")
    pr(f"  {'target':>9} {'reward':>8} {'meth':>5} | {'hits 1st':>9} "
       f"{'stopped':>9} {'neither':>9} | {'net EV':>8}")
    for t in p["targets"]:
        pr(f"  {t['px']:>9.2f} {t['reward']:>7.2f}% {t['n_methods']:>5} | "
           f"{t['p_first']:>8.1f}% {t['p_stop']:>8.1f}% {t['p_neither']:>8.1f}% | "
           f"{t['ev_net']:>+7.2f}%")
    pr("  net EV = P(target first) x reward  -  P(stopped first) x stop distance.")
    pr("  Single-shot expectancy: it deliberately ignores scaling out and moving")
    pr("  the stop to breakeven, both of which improve it materially.")

    # 4 -- recommendation
    pr("\n" + "=" * 96)
    pr("RECOMMENDED PLAN")
    pr("=" * 96)
    wz, hz = p["working_zone"], p["hard_zone"]
    if p["working_stop"]:
        s = next((x for x in p["stop_probs"] if x["px"] == p["working_stop"]), None)
        pr(f"\n  WORKING STOP (close-based)   {p['working_stop']:.2f}   "
           f"{(p['working_stop']-entry)/entry*100:+.2f}%   "
           f"{(entry-p['working_stop'])/atr:.2f}xATR")
        pr(f"     just below the {wz['lo']:.2f}-{wz['hi']:.2f} zone "
           f"({wz['n_methods']} methods: {', '.join(wz['methods'])})")
        if s and s["wick_pct"] is not None:
            pr(f"     act only on a DAILY CLOSE below it — {s['wick_pct']:.0f}% of "
               f"historical breaches closed back above the same session")
    else:
        pr("\n  WORKING STOP: no support zone sits >=1.5xATR below entry. "
           "Either the entry is extended or the stock is too volatile for a "
           "structural stop here — reduce size rather than inventing a level.")
    if p["hard_stop"]:
        pr(f"\n  HARD STOP (standing GTT)     {p['hard_stop']:.2f}   "
           f"{(p['hard_stop']-entry)/entry*100:+.2f}%   "
           f"{(entry-p['hard_stop'])/atr:.2f}xATR")
        pr(f"     just below the {hz['lo']:.2f}-{hz['hi']:.2f} zone "
           f"({hz['n_methods']} methods) — gap insurance, not the working stop")
    elif p["working_stop"]:
        pr(f"\n  HARD STOP: none recommended. No confirmed zone sits far enough "
           f"below {p['working_stop']:.2f} to be")
        pr(f"     meaningful insurance without being so distant it stops "
           f"insuring anything. The working")
        pr(f"     stop is already {(entry-p['working_stop'])/atr:.2f}xATR out — "
           f"treat it as the only stop and size accordingly.")

    tg = p["targets"]
    if tg:
        # Risk-averse selection: among targets that fill more often than they
        # fail, take the best net expectancy. If none clears that bar, take the
        # best expectancy outright and say plainly that the odds are poor.
        likely = [t for t in tg if t["p_first"] >= 50]
        t1 = max(likely or tg, key=lambda t: t["ev_net"])
        best_ev = max(t["ev_net"] for t in tg)
        rest = sorted([t for t in tg if t["px"] > t1["px"]], key=lambda t: t["px"])

        pr(f"\n  T1  {t1['px']:.2f}  (+{t1['reward']:.2f}%)  — fills before the stop "
           f"{t1['p_first']:.1f}% of the time, net EV {t1['ev_net']:+.2f}%")
        if p["working_stop"]:
            pr(f"      R:R {(t1['px']-entry)/(entry-p['working_stop']):.2f}:1 "
               f"against the working stop")
        n = 2
        for t in rest[:2]:
            pr(f"  T{n}  {t['px']:.2f}  (+{t['reward']:.2f}%)  — {t['n_methods']} "
               f"methods, fills first {t['p_first']:.1f}%, net EV {t['ev_net']:+.2f}%")
            n += 1
        mm = [c for c in b["res"] if c["method"] == "measured-move"]
        if mm:
            far = max(mm, key=lambda c: c["px"])
            pr(f"  T{n}  {far['px']:.2f}  (+{(far['px']-entry)/entry*100:.2f}%)  — "
               f"{far['why']}; hold for this only on a confirmed breakout")

        if best_ev <= 0:
            pr(f"\n  ** WARNING: no target on this chart has positive single-shot "
               f"expectancy against a {p['stop_pct']:.2f}% stop (best {best_ev:+.2f}%).")
            pr(f"     The entry is priced badly relative to the overhead supply. "
               f"Scaling out with a move to breakeven after T1 is what makes this")
            pr(f"     survivable — a single all-or-nothing target here does not pay.")
    pr("\n  Targets sit just BELOW each resistance zone: sell into the wall "
       "rather than waiting for price to clear it.")
    pr("\n  Mechanical output, not personalised investment advice.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--entry", type=float, default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    p = build(a.symbol.upper().replace(".NS", ""), a.entry)
    if a.json:
        p.pop("rows", None)
        p["base"].pop("closed", None)
        print(json.dumps(p, indent=2, default=str))
    else:
        render(p)


if __name__ == "__main__":
    main()
