---
name: stock_planner
description: Use when the user holds or plans a long position in an NSE or Indian stock and names an entry price, asking where to put the stop-loss or targets, what the support and resistance zones are, or how to plan the exit. Triggers include "I bought X at Y, what should my stop be", "target and stop for X", "where do I exit X", "support zones for my position".
---

# Stock Planner — stops and targets for a long position

Given a symbol and an entry price, derives candidate levels from **nine
independent methods**, clusters them into confluence zones, tests them against
this stock's own history, and recommends one plan.

**Core principle: a level is only as good as the number of independent methods
that find it, and only usable if it sits beyond daily noise.** Confluence tells
you where a level *is*; ATR tells you whether you can *trade* it. Both filters
or neither — the highest-confluence zone on a chart is frequently 0.3×ATR from
price, which makes it a fact about the present, not a stop.

Long positions only. For "should I buy this at all", use `stock_analyser`; for
comparing several names, `watchlist_analyser`.

## Data source

`planner.py` imports the geometry from `stock_analyser/levels.py` and the
indicators from `stock_analyser/analyze.py`. **Both skills must be installed in
`~/.claude/skills/`.** Nothing is reimplemented here — one fix propagates
everywhere. The TradingView MCP has no NSE India TA coverage and must not be
used for levels; `mcp__tradingview__stock_prices` is fine for a quote check.

## Workflow

```
python3 <skill-dir>/planner.py SYMBOL --entry <price>
```

One call produces everything. If the entry is omitted it defaults to the live
price. Bad tickers exit with an error — **never invent levels when the fetch
fails.**

## The nine methods

| Method | What produces the level |
|---|---|
| volatility | 1.0 / 1.5 / 2.0 / 2.5 × ATR from entry |
| horizontal | fractal swing highs and lows, and repeatedly-tested zones with test counts |
| fibonacci | retracements and extensions of the live leg and the 52-week leg |
| trendline | fitted through swing pivots, validated for touches and non-violation, projected to today |
| volume-candle | key prices of high-volume thrust bars — the low of an up-thrust is where demand appeared, the high of a down-thrust where supply did |
| volume-node | heaviest traded price buckets over twelve months |
| moving-avg | 20 / 50 / 100 / 200-day |
| pivot | classic floor pivots off the last closed session |
| measured-move | consolidation range projected up and down |

## Output contract

Report in this order. The recommendation comes last because it only means
something once the reader has seen what it was chosen from — but state the two
stops and T1 in the first three lines of the summary so they are findable.

1. **Header** — entry, live price, ATR in points and percent, last closed bar,
   and the fibonacci leg the script selected. Print the leg: it is a heuristic
   and the reader must be able to sanity-check it.
2. **Levels by method** — every method's candidates with distance, ATR
   multiple, and the reason. Grouped by method, never merged into one list.
3. **Confluence zones** — support and resistance, ranked by agreeing methods,
   naming which methods agree.
4. **Empirical tests** — the three tables the script emits:
   - hit rate per candidate stop over 7/15/20 sessions, close-based and
     intraday
   - wick-out rate: of genuine tests, how many closed back above the same day
   - which comes first, target or stop, with net expectancy
5. **Recommended plan** — working stop (close-based), hard stop (standing GTT),
   and T1/T2/T3 with the reasoning for each, including what was rejected.
6. One line noting this is mechanical output, not personalised investment
   advice.

## Reading the recommendation

- **Working stop is close-based.** Act only on a daily close below it. The
  wick-out column is why: in a volatile name half or more of the historical
  breaches close back above the same session, and a standing order donates
  every one of those to noise.
- **Hard stop is a standing GTT** placed well below the working stop. It exists
  for gaps, which a close-based stop cannot protect against. When no zone sits
  far enough below to be meaningful insurance without being absurdly distant,
  the script says so — report that rather than inventing one.
- **T1 is chosen by net expectancy among targets that fill more often than they
  fail**, not by the largest reward. A more distant target always pays more per
  share and always fills less often.
- **Net EV can be negative for every target.** When the script warns, say so
  plainly: it means the entry is priced badly against the overhead supply. Do
  not bury it — that warning is the single most useful line in the output.

## Rules

- **Never recommend a stop closer than 1.5×ATR.** If the nearest confluence
  zone is inside that, go to the next zone down or tell the user to cut size.
  Tightening a stop into the noise band converts a survivable loss into a
  near-certain one.
- **Stop distance comes from the chart; position size is the free variable.**
  If the rupee loss is too large, the answer is fewer shares, never a tighter
  stop.
- **Targets sit just BELOW a resistance zone.** Sell into the wall rather than
  waiting for price to clear it.
- **Report the selected fibonacci leg and the trendline's touch count and
  dates.** Both are heuristics; a trendline fitted to the best-scoring pivot
  pair is not always the one a human would draw.
- **A steep trendline breaks on time alone.** A line rising 0.6/bar through a
  sideways consolidation gets breached by arithmetic, not weakness. Say which
  is happening.
- **Never move a stop down.** Only up.

## Common mistakes

| Mistake | Consequence |
|---|---|
| Recommending the highest-confluence zone without checking distance | The top zone is often 0.3×ATR away — that is where price is, not a stop |
| Quoting gross expectancy (P(win) × reward) | Flatters every target; the stop leg is where the money goes |
| Merging the nine methods into one level list | Destroys the whole point — the user cannot see which methods agree |
| Silently dropping the negative-EV warning | Hides the most important finding in the output |
| Using a hard intraday stop in a high-wick name | Donates half the triggers to noise |
| Inventing a hard stop when none qualifies | A disaster stop 0.6% below the working stop insures nothing |
