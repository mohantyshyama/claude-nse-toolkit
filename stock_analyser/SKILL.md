---
name: stock_analyser
description: Use when the user names an NSE or Indian stock ticker and wants technical analysis, support and resistance levels, price targets, entry or exit levels, position sizing, or a long/no-long call. Triggers include "analyse X on NSE", "S/R levels for X", "should I go long X", "targets for X".
---

# NSE Technical Analysis

Produces a decisive, reproducible trading readout for any NSE symbol: levels,
a mechanical setup score, entry setups with R:R, sizing, and invalidation.

**Core principle: the trend and the entry price are two separate questions.**
A stock can be in a flawless uptrend and still be un-buyable today because the
nearest resistance is closer than the nearest viable stop. Conflating them is
the failure this framework exists to prevent.

## Data source: do NOT use the TradingView MCP for NSE analysis

The TradingView MCP has **no TA coverage for NSE India**. `coin_analysis` and
`combined_analysis` silently rewrite `exchange="NSE"` to KUCOIN/NASDAQ, return
`SYMBOL_NOT_FOUND`, and `combined_analysis` then emits
`confluence: {signals_agree: true, confidence: "HIGH"}` on top of zero data.
Reporting that envelope means reporting confident garbage.

| Need | Use |
|---|---|
| Levels, indicators, score | `analyze.py` (bundled) — Yahoo `.NS` OHLC |
| Stops/targets for a position you already hold | `levels.py SYMBOL --entry <price>` (bundled) |
| Live quote cross-check | `mcp__tradingview__stock_prices` with `NSE:SYMBOL` (scanner works) |
| Catalyst / news | WebSearch |

## Workflow

1. `python3 <skill-dir>/analyze.py SYMBOL` — all numbers in one pass.
   Non-existent tickers exit with an error. **Never invent levels when the
   fetch fails** — say the ticker didn't resolve and ask for the correct one.
2. WebSearch the company for catalysts and pending events (results dates,
   fundraises, dilution, regulatory items).
3. Re-run with `--catalyst N` (0-10) to fold that judgement into the score.
4. Write the report using the output contract below.

## Managing an existing position

When the user already holds the stock, the entry-gate verdict is the wrong
question — they are past it. Use `python3 <skill-dir>/levels.py SYMBOL --entry
<price>`, which derives stop and target candidates from nine independent
methods (volatility, horizontal structure, fibonacci, trendline, high-volume
candles, volume nodes, moving averages, pivots, measured move) and clusters
them into confluence zones.

**Rank stop and target zones by how many methods agree, then filter by
distance.** A six-method zone 0.3×ATR from entry is not a stop — it is where
price already is. The usable stop is the highest-confluence zone that also sits
at least 1.5×ATR away; put the stop just below it. Targets go just *below* a
high-confluence resistance zone — sell into the wall rather than waiting for
price to clear it.

## Output contract

Produce these sections, in this order. The verdict comes **first** — a reader
must not have to hunt for it.

1. **Verdict line** — one of INITIATE FULL / HALF SIZE / WATCHLIST / STAND
   ASIDE, plus the bias (bullish/bearish) stated separately from the action.
   When the two diverge ("bullish bias, no long here"), say so explicitly and
   give the R:R arithmetic that forces it.
2. **Header** — price, day range, 52w range, % change.
3. **Trend picture** — MA stack, what created the current structure (name the
   volume thrust and its date), daily vs weekly indicator table.
4. **Support table** — zone, and *what is there* (swing low, volume node,
   MA, fib, pivot). A level with only one thing at it is weak; say so.
5. **Resistance table** — same, including the rejection-test count.
6. **Targets** — measured move from the consolidation range, fib extensions,
   round numbers. Give the breakout trigger condition (close + volume
   multiple), not just the number.
7. **Weighted score table** — six factors, weights, subtotals, band.
8. **Entry setups** — for each viable setup: trigger, entry, stop, risk %,
   targets, R:R, and what invalidates it. Mark the preferred one.
9. **Position sizing** — ATR-normalised share counts at 1% account risk, with
   the exposure cap applied.
10. **Scenario tree** — 3-4 outcomes with probabilities that sum to 100%.
11. **Invalidation rules** — the single price that breaks the thesis.
12. **Pre-trade checklist** — the 8 items, ticked against current state.
13. One line noting this is mechanical framework output, not personalised
    investment advice.

### When the user asks for brevity

A short answer is the full contract *compressed*, not a subset of it. Whatever
the length, the output IS these six parts, in this order:

1. Verdict + band, one line
2. The R:R arithmetic that produced it — entry, 1.5×ATR stop, target, ratio
3. Support and resistance zones
4. Targets, each with its breakout trigger (close + volume multiple)
5. Invalidation price, and the position size the exposure cap allows
6. The not-advice line

Brevity compresses prose, merges tables, and cuts the narrative.

The compressed form ends with this exact line, filled in — it is one line, so
it survives any length limit:

```
RISK: stop <price> (<x>%) · size <n> sh per ₹1L (cap-bound) · invalid on close <above/below> <price>
```

Compute `<n>` as: shares = min(1% of ₹1L ÷ risk-per-share, 15% of ₹1L ÷ entry).
Whichever binds is the honest number — say which one did.

## Scoring

| Factor | Weight | Objective basis |
|---|---|---|
| Trend | 25% | MA stack: price>200D, 50D>200D, price>50D, 20D>50D (2.5 each) |
| Location | 25% | R:R at current price vs a 1.5×ATR stop |
| Volume | 15% | Thrust **direction** and recency, dry-up vs a clean baseline |
| Momentum | 15% | RSI bands + MACD histogram sign, daily and weekly |
| Catalyst | 10% | Manual `--catalyst`, from news |
| Volatility | 10% | ATR as % of price |

Bands: **≥7.5** initiate full · **6.0-7.4** half size · **4.5-5.9** watchlist ·
**<4.5** stand aside.

**The R:R veto overrides the band.** R:R below 1.5:1 at current price caps the
verdict at WATCHLIST however high the total. Report both the capped verdict and
what the raw score would have said. A weighted average otherwise lets a 10/10
trend outvote a fatal entry price.

## Rules that make the numbers mean something

- **Stops floor at 1.5×ATR.** Tighter is noise-stopped. This is what makes a
  mid-range entry fail the gate automatically, with no discretion involved.
- **Cap single-name exposure at 15-20% of capital** regardless of what the stop
  math permits. A tight stop is not a licence to oversize.
- **Breakout triggers need a daily close plus a volume multiple** (≥2× avg20).
  Intraday tags of a level are how false breakouts start.
- **Resistance inside 0.5×ATR is not resistance** — price is already at it.
- **In blue sky, R:R runs against the measured-move objective**, not against
  "no resistance". Otherwise R:R is undefined, the veto switches off, and the
  framework waves through the largest position exactly where a runaway trend
  is most tempting.
- **Distinguish event-driven from earnings-driven catalysts.** Event-driven
  re-ratings mean-revert more often; demand better R:R, don't skip the name.
- **Check the live quote against the last closed bar.** Pivots must come from
  the last *closed* session; the script reports both and flags an open bar.
- **Volume thrusts are direction-aware and measured against a prior baseline.**
  The script labels each UP-thrust (accumulation) or DOWN-thrust
  (distribution) and scores them oppositely, so a crash on 3× volume no longer
  reads as strength. Report the label; don't re-derive it.
- **A weak fundamental case does not license refusing the call.** Say STAND
  ASIDE and give the levels that would change it. "Consult an advisor" instead
  of a verdict is the one output the framework cannot produce.

## Common mistakes

| Mistake | Consequence |
|---|---|
| Reporting TradingView's HIGH-confidence envelope for NSE | Confident output built on zero data |
| Listing targets without computing R:R at current price | The whole point of the framework is skipped |
| Scoring trend and skipping location | Chases every extended move |
| Using the 52w range as the consolidation range | Nonsense measured moves |
| Burying the verdict under the analysis | Reader can't act on it |
| Softening to "it depends" when asked for a call | The framework exists to produce a decision |
