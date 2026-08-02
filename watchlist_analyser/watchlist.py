#!/usr/bin/env python3
"""
NSE watchlist comparative engine.

Scores a list of NSE symbols on the stock_analyser framework, adds the two
things that only exist in a watchlist context -- relative strength versus the
Nifty 50, and a "score if the trigger hits" projection -- then ranks them so a
shortlist falls out mechanically.

Usage:
    python3 watchlist.py TITAN,MPHASIS,SUZLON,BEL
    python3 watchlist.py "TITAN, MPHASIS, BEL" --catalyst TITAN=8,BEL=3
    python3 watchlist.py TITAN,MPHASIS --json

--catalyst takes per-symbol overrides (0-10). Symbols not listed default to 5.
Set them from news AFTER a first pass, then re-run.

Scoring lives in stock_analyser/analyze.py and is imported, never reimplemented
-- two copies would drift and the table would stop agreeing with the per-name
report.
"""

import argparse
import importlib.util
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

NIFTY = "^NSEI"
SIBLING = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "stock_analyser", "analyze.py")


def load_engine():
    """Local copy first, sibling skill second -- so the same file works whether
    the three skills are installed together or this one is packaged alone."""
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analyze.py")
    path = here if os.path.exists(here) else os.path.normpath(SIBLING)
    if not os.path.exists(path):
        raise SystemExit(
            f"ERROR: cannot find analyze.py. watchlist_analyser needs either "
            f"its own copy in the skill folder, or the stock_analyser skill "
            f"installed alongside it in ~/.claude/skills/.")
    spec = importlib.util.spec_from_file_location("analyze", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


A = load_engine()


# --------------------------------------------------------------- projections

def score_at_trigger(o):
    """What the score becomes IF the breakout trigger fires.

    A name can be high quality and un-buyable today (strong trend, terrible
    entry). Ranking on today's score alone buries those; ranking on quality
    alone recommends chasing them. Computing both lets the shortlist separate
    "buy now" from "worth an alert".

    Only trend and location are recomputed -- those are the two that move with
    price. Volume, momentum, catalyst and volatility are properties of the
    chart's recent history and do not change because price ticked higher.
    """
    gate, ma, atr_d = o["entry_gate"], o["ma"], o["atr"]["daily"]
    trigger = gate["nearest_resistance"] or gate["objective_used"]
    if not trigger or not atr_d:
        return None

    zones = o.get("rejection_zones") or []

    # If the trigger sits INSIDE a tested supply band, clearing that band is
    # the real trigger. Otherwise the "breakout" level is a price the stock
    # has been rejected from repeatedly, and the projection rewards buying
    # into the middle of a wall.
    for z in zones:
        if z["lo"] <= trigger <= z["hi"] and z["tests"] >= 3:
            trigger = max(trigger, z["hi"])

    entry = trigger * 1.002                      # just through the level
    stop = entry - 1.5 * atr_d

    # Objectives must include the NEXT supply band. Without it the projection
    # targets the measured move on the far side of zones tested 17-19 times
    # and reports a fantasy ratio -- rr_now uses nearest resistance, so the
    # projection has to as well or the two numbers mean different things.
    objectives = [x for x in (gate["next_resistance"],
                              o["range"]["breakout_target"],
                              o["fib_extension"].get("1.272"))
                  if x and x > entry * 1.01]
    objectives += [z["lo"] for z in zones
                   if z["tests"] >= 3 and z["lo"] > entry * 1.01]
    target = min(objectives) if objectives else None
    rr = (target - entry) / (entry - stop) if target and entry > stop else None

    sc = dict({k: o["score"][k] for k in A.WEIGHTS})
    sc["trend"], _ = A.score_trend(entry, ma["sma20"], ma["sma50"],
                                   ma["sma100"], ma["sma200"])
    sc["location"] = A.score_location(rr)
    total = sum(sc[k] * A.WEIGHTS[k] for k in A.WEIGHTS)
    return {"trigger": trigger, "entry": entry, "stop": stop,
            "target": target, "rr": rr, "total": total, "components": sc}


ACTIONS = {"INITIATE FULL POSITION": "BUY NOW",
           "HALF SIZE": "BUY HALF"}


def action_for(o, proj):
    """Map the framework verdict to a watchlist action. Reuses band() output
    rather than inventing a second decision rule that could disagree."""
    verdict = o["score"]["verdict"]
    for key, act in ACTIONS.items():
        if verdict.startswith(key):
            return act, None
    if verdict.startswith("WATCHLIST"):
        trig = proj["trigger"] if proj else None
        return (f"WAIT @ {trig:.2f}" if trig else "WAIT"), trig
    return "AVOID", None


# --------------------------------------------------------------------- main

def parse_catalysts(spec):
    out = {}
    if not spec:
        return out
    for part in spec.split(","):
        if "=" not in part:
            raise SystemExit(f"ERROR: --catalyst needs SYM=N form, got '{part}'")
        k, v = part.split("=", 1)
        try:
            out[k.strip().upper()] = float(v)
        except ValueError:
            raise SystemExit(f"ERROR: catalyst for {k} must be a number")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", help="comma-separated NSE tickers")
    ap.add_argument("--catalyst", default="",
                    help="per-symbol overrides, e.g. TITAN=8,BEL=3")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--detail", action="store_true",
                    help="also render the full per-name report for "
                         "BUY and ALERT names (no extra fetches)")
    a = ap.parse_args()

    syms = [s.strip().upper().replace(".NS", "")
            for s in a.symbols.split(",") if s.strip()]
    if not syms:
        raise SystemExit("ERROR: no symbols given")
    seen, ordered = set(), []
    for s in syms:                               # dedupe, keep order
        if s not in seen:
            seen.add(s)
            ordered.append(s)
    syms = ordered
    cats = parse_catalysts(a.catalyst)

    # Nifty 50 baseline for relative strength.
    idx_ret = {}
    try:
        nrows, _ = A.fetch(NIFTY, "2y", "1d", suffix="")
        nc = [r["c"] for r in nrows]
        idx_ret = {"1m": A.pct_return(nc, 21), "3m": A.pct_return(nc, 63),
                   "6m": A.pct_return(nc, 126)}
    except SystemExit as e:
        print(f"WARNING: Nifty baseline unavailable ({e}); "
              f"relative strength will be blank.\n", file=sys.stderr)

    def run(sym):
        try:
            return sym, A.compute(sym, catalyst=cats.get(sym, 5.0)), None
        except SystemExit as e:
            return sym, None, str(e)
        except Exception as e:                   # noqa: BLE001 - report, don't abort
            return sym, None, f"ERROR: {type(e).__name__}: {e}"

    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(run, syms))

    rows, failed = [], []
    for sym, o, err in results:
        if err:
            failed.append((sym, err))
            continue
        proj = score_at_trigger(o)
        act, trig = action_for(o, proj)
        # An already-buyable name has no trigger to wait for. Projecting one
        # measures a hypothetical entry further up its own move and prints a
        # LOWER number next to BUY NOW, which reads as "it gets worse if it
        # rises". Suppress it rather than show a misleading figure.
        if act.startswith("BUY"):
            proj = None
        rs = {k: (o["returns"][k] - idx_ret[k])
              if o["returns"].get(k) is not None and idx_ret.get(k) is not None
              else None for k in ("1m", "3m")}
        rows.append({"symbol": sym, "name": o["name"], "price": o["price"],
                     "total": o["score"]["total"],
                     "trigger_total": proj["total"] if proj else None,
                     "components": {k: o["score"][k] for k in A.WEIGHTS},
                     "rr": o["entry_gate"]["rr_at_current_price"],
                     "verdict": o["score"]["verdict"], "action": act,
                     "trigger": trig, "rs": rs,
                     "ret": o["returns"], "proj": proj, "full": o})

    # Rank: actionable first, then by score. Ties broken by 3m relative strength.
    order = {"BUY NOW": 0, "BUY HALF": 1}
    rows.sort(key=lambda r: (order.get(r["action"].split(" @")[0],
                             2 if r["action"].startswith("WAIT") else 3),
                             -(r["total"] or 0),
                             -(r["rs"].get("3m") or -999)))

    if a.json:
        for r in rows:
            r.pop("full", None)
        print(json.dumps({"rows": rows, "failed": failed,
                          "nifty": idx_ret}, indent=2, default=str))
        return

    w = 168
    print("=" * w)
    print(f"WATCHLIST COMPARATIVE — {len(rows)} scored"
          + (f", {len(failed)} failed" if failed else ""))
    if idx_ret:
        print(f"Nifty 50 baseline: 1-month {idx_ret['1m']:+.1f}%   "
              f"3-month {idx_ret['3m']:+.1f}%   6-month {idx_ret['6m']:+.1f}%")
    print("=" * w)
    # Two-line header so every column can carry a real word instead of a
    # three-letter code the reader has to decode.
    # Column widths defined once so the group-label row, the name row and the
    # weight row all line up. A group label sitting over the wrong columns is
    # worse than no group label.
    head = f"{'':>3} {'':<12} {'':>10} "
    comp = f"{'':>7} {'':>9}   "
    print(head + comp
          + f"{'COMPONENT SCORES (raw out of 10)':<56}"
          + f"{'':>14}{'RELATIVE STRENGTH vs NIFTY 50':<20}")
    print(f"{'#':>3} {'SYMBOL':<12} {'PRICE':>10} {'SCORE':>7} {'SCORE AT':>9}   "
          f"{'Trend':>7} {'Location':>9} {'Volume':>7} {'Momentum':>9} "
          f"{'Catalyst':>9} {'Volatility':>11}  {'Risk:Reward':>12} "
          f"{'1-month':>9} {'3-month':>9}   ACTION")
    print(f"{'':>3} {'':<12} {'':>10} {'NOW':>7} {'TRIGGER':>9}   "
          f"{'(25%)':>7} {'(25%)':>9} {'(15%)':>7} {'(15%)':>9} "
          f"{'(10%)':>9} {'(10%)':>11}")
    print("-" * w)
    for i, r in enumerate(rows, 1):
        c = r["components"]
        tt = f"{r['trigger_total']:.2f}" if r["trigger_total"] else "none"
        rr = f"{r['rr']:.2f}:1" if r["rr"] else "n/a"
        r1 = f"{r['rs']['1m']:+.1f}pp" if r["rs"].get("1m") is not None else "n/a"
        r3 = f"{r['rs']['3m']:+.1f}pp" if r["rs"].get("3m") is not None else "n/a"
        star = "*" if "VETO" in r["verdict"] else " "
        print(f"{i:>3} {r['symbol']:<12} {r['price']:>10.2f} "
              f"{r['total']:>6.2f}{star}{tt:>9}   "
              f"{c['trend']:>7.1f} {c['location']:>9.1f} {c['volume']:>7.1f} "
              f"{c['momentum']:>9.1f} {c['catalyst']:>9.1f} "
              f"{c['volatility']:>11.1f}  {rr:>12} {r1:>9} {r3:>9}   {r['action']}")
    print("-" * w)
    print("""KEY — what each column means
  SCORE NOW          Weighted total out of 10 at today's price. An asterisk means the
                     Risk:Reward veto was applied, capping the verdict at WATCHLIST.
  SCORE AT TRIGGER   What the total would become if the breakout trigger fired. Shows
                     "none" for names already buyable, which have no trigger to wait for.
  Trend              Moving-average stack: price above 200-day, 50-day above 200-day,
                     price above 50-day, 20-day above 50-day. 2.5 points each.
  Location           Quality of the entry price itself, from Risk:Reward at this price.
  Volume             Direction and recency of volume thrusts, plus genuine dry-up.
  Momentum           RSI bands and MACD histogram sign, on daily and weekly.
  Catalyst           News and fundamentals. Manual input, defaults to 5 if not set.
  Volatility         Average True Range as a percentage of price. Lower scores higher.
  Risk:Reward        Reward to nearest real resistance divided by risk to a 1.5x ATR stop.
                     The framework gate is 2:1; below 1.5:1 the veto fires.
  Relative Strength  Return minus the Nifty 50 over the same window, in percentage
                     points (pp). Positive means the stock is outpacing the index.
  ACTION             BUY NOW / BUY HALF / WAIT @ price / AVOID.""")

    if failed:
        print("\nFAILED:")
        for sym, err in failed:
            print(f"  {sym}: {err}")

    # Split the WAIT bucket by whether the trigger ACTUALLY repairs the setup.
    # Some names break out into a worse location than they occupy now -- their
    # projected score falls and projected R:R stays under the gate. Listing
    # those beside a genuine alert candidate defeats the point of a shortlist.
    def repairs(r):
        p = r["proj"]
        return bool(p and p["rr"] and p["rr"] >= 2.0 and p["total"] >= 6.0)

    buyable = [r for r in rows if r["action"].startswith("BUY")]
    waiting = [r for r in rows if r["action"].startswith("WAIT")]
    alerts = [r for r in waiting if repairs(r)]
    hollow = [r for r in waiting if not repairs(r)]
    # An AVOID whose breakout WOULD qualify is worth an alert too.
    latent = [r for r in rows if r["action"] == "AVOID" and repairs(r)]

    print(f"\nSHORTLIST: {len(buyable)} buy now · {len(alerts)} worth an alert · "
          f"{len(hollow)} wait-but-trigger-doesn't-repair · "
          f"{len(rows)-len(buyable)-len(alerts)-len(hollow)} avoid")

    def line(tag, r):
        p = r["proj"]
        extra = (f" -> {p['total']:.2f} at {p['entry']:.2f}, R:R {p['rr']:.2f}:1"
                 if p and p["rr"] else "")
        trig = f"@ {p['trigger']:.2f}" if p else "-"
        print(f"  {tag:<7}{r['symbol']:<12} now {r['total']:>5.2f}  {trig}{extra}")

    detail_rows = (buyable + alerts) if a.detail else []

    for r in buyable:
        print(f"  {'BUY':<7}{r['symbol']:<12} now {r['total']:>5.2f}  "
              f"R:R {r['rr']:.2f}:1")
    for r in alerts:
        line("ALERT", r)
    for r in latent:
        line("LATENT", r)
    if hollow:
        print("  -- trigger does NOT repair these; breaking out leaves them "
              "under the gate:")
        for r in hollow:
            line("(no)", r)

    # Names worth spending a web search on. A stock below every moving average
    # on distribution volume, whose breakout would still fail the gate, will not
    # be rescued by a headline -- and catalyst is only 10% of the score. Skipping
    # those roughly halves the searches on a typical basket.
    worth_news = [r["symbol"] for r in buyable + alerts + latent + hollow]
    skipped = [r["symbol"] for r in rows if r["symbol"] not in worth_news]
    print(f"\nNEWS SCAN LIST (search these, then re-run with --catalyst):"
          f"\n  {','.join(worth_news) if worth_news else '(none)'}")
    if skipped:
        print(f"  skipping {len(skipped)} name(s) failing on technicals alone: "
              f"{','.join(skipped)}")

    if detail_rows:
        print("\n" + "=" * w)
        print(f"FULL DETAIL — {len(detail_rows)} shortlisted name(s). "
              f"Everything else gets a brief; see SKILL.md.")
        print("=" * w)
        for r in detail_rows:
            print()
            A.compute(r["symbol"], catalyst=cats.get(r["symbol"], 5.0),
                      render=True)          # fetches are cached, so this is free
    elif a.detail:
        print("\nNo BUY or ALERT names in this basket — no full detail to render.")
    else:
        print("\nAdd --detail to render the full report for BUY/ALERT names "
              "in this same run (avoids a second call per name).")


if __name__ == "__main__":
    main()
