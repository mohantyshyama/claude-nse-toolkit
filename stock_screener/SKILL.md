---
name: stock_screener
description: Use when the user wants to scan or screen the NSE market for stocks meeting bullish setup criteria, rather than analysing named tickers. Triggers include "screen for breakouts", "which NSE stocks are setting up", "find me bullish stocks", "scan the Nifty 500", "what's coiling", "give me watchlist candidates".
---

# NSE Bullish Setup Screener

Scans the Nifty 500 for six named bullish setups and returns a ranked, evidence-bearing
shortlist. This is the top of the funnel:

    stock_screener -> watchlist_analyser -> stock_analyser -> stock_planner
     500 names,        top 8-10 with        one name, full     position held,
     ~23s              real catalysts       13-section report   stops & targets

**Core principle: the screener never issues a final buy decision without catalyst
adjudication.** Its Action column deliberately reuses `watchlist_analyser`'s own BUY NOW /
BUY HALF labels so the two skills stay mutually legible — but catalyst, 10% of the
weighted score, has not been evaluated for any name in a 500-stock scan; every row sits at
the neutral default. A `BUY NOW` here means "passes the mechanical gate at a neutral
catalyst," not "buy this." Adjudication happens in `watchlist_analyser`, which sets real
catalysts per name. Treating a screener row as a decision, rather than a candidate awaiting
that adjudication, is the failure this skill is designed to prevent.

## Data source

Same constraint as the other three skills: the TradingView MCP has **no NSE India TA
coverage** and `combined_analysis` emits `confidence: "HIGH"` on top of zero data. Every
number here comes from `screener.py`, which imports `stock_analyser/analyze.py` — the same
engine, never a second implementation. `mcp__tradingview__stock_prices` with `NSE:SYMBOL`
is fine for a live quote cross-check.

**This skill requires `stock_analyser` and `watchlist_analyser` installed in
`~/.claude/skills/`.**

## Workflow

1. **Ask which setups to screen** — present the six as a multi-select. All six cost the
   same to compute (one scoring pass feeds every predicate), so selecting several is free.
   If the user already named a setup, skip the question.
2. `python3 <skill-dir>/screener.py --setup <names> --top 15` — one call, ~23s for 500 names.
3. Write up the output using the contract below.

**Do not call `analyze.py` per name afterwards.** The screener's job ends at the shortlist;
per-name detail is `watchlist_analyser`'s, and it needs catalysts set to be worth running.

## The six setups

Five are stages of one bullish life cycle, which is why a name in two is signal:

    COILED -> BREAKOUT -> LEADER          PULLBACK = re-entry, established trend
    (base)    (fires)     (leads)         TURN     = entry, brand-new trend

| Setup | Catches | Ranked by |
|---|---|---|
| COILED | Volatility contraction inside a base, before the move | Score at Trigger |
| BREAKOUT | The base breakout on the day it fires | Score Now |
| LEADER | Established leadership near 52-week highs | Score Now |
| PULLBACK | Retracement into support inside an uptrend | Score Now |
| TURN | Just after a 50/200 golden cross | Score at Trigger |
| CONFLUENCE | Names matching two or more of the above | Match count |

**COILED+BREAKOUT is the strongest pair the screen can produce**, not a contradiction: it
is the VCP breakout — a base whose volatility contracted right up to the close that cleared
it, which is the `COILED -> BREAKOUT` arrow above happening on one bar. Rank and report it
like any other confluence.

**BREAKOUT+PULLBACK is impossible** — price cannot be above the prior base high and
retraced to the 20- or 50-day average at the same time. The engine asserts this; if you
ever see it reported, it is a predicate bug, not a rare event.

## Output contract

1. **Scan header** — date, universe, counts, FAILED list, per-setup match counts.
2. **One table per chosen setup**, ranked. Full-word column headers, always including
   `Sector` and `Score Now (catalyst-neutral)`. Include `showing top N of M` whenever the
   list was truncated.
3. **The key**, after every table. Never drop it — a narrower table is harder to read,
   not faster.
4. **Breadth read** — two or three sentences on what the match counts and sector
   concentration say about the market.
5. **Handoff line** — the paste-ready `watchlist.py` command for the shortlist.
6. One line noting this is mechanical framework output, not personalised investment advice.

### When the user asks for brevity

Brevity drops the per-setup tables down to the top 5 rows each. It never removes a column,
the key, the FAILED list, or the breadth read.

## Rules

- **Screener scores are catalyst-neutral.** A news search per name is impossible across
  500, so catalyst is held at the default 5.0 — 10% of the weighted score. Say so when
  presenting numbers, and expect `watchlist_analyser` to produce a slightly different
  score for the same stock once real catalysts are set. Presenting the two as identical
  is wrong.
- **Report the FAILED list.** A ticker that did not resolve is not silently absent from
  the ranking. `TATAMOTORS` stopped resolving on Yahoo post-demerger; the universe rots.
- **An empty screen is a finding.** Say plainly that nothing is set up this way today and
  give the condition that did the rejecting. Never pad a list to fill 15 rows.
- **Never re-sort the table.** The engine ranks by actionability — vetoed names below
  clean ones — and re-sorting by raw score puts un-buyable names on top.
- **Setup Fit is setup-relative.** An 8 for COILED and an 8 for PULLBACK are different
  measurements. Never compare Fit across tables.
- **Volume-light breakouts are marked.** `stock_analyser` defines a trigger as a close
  plus 2x average volume; the screener surfaces 1.5-2.0x as near-misses and flags them.
  Reporting one as a confirmed breakout contradicts the framework beneath this skill.

## Common mistakes

| Mistake | Consequence |
|---|---|
| Reading a screener row's `BUY NOW` label as a buy decision | The catalyst factor was never evaluated |
| Presenting screener and watchlist scores as the same number | They differ by design; catalyst is neutral here |
| Running `analyze.py` on every screened name | The screener's output is a shortlist, not a research queue |
| Dropping the key to save space | Every column has a unit the reader cannot guess |
| Omitting `showing top N of M` | Reads as "these are all that qualified" when 26 others did |
| Re-sorting by Score Now | Un-buyable names top the list |
| Treating a COILED+BREAKOUT confluence as a bug | It is the VCP breakout — report it, and lead with it |
| Reporting a BREAKOUT+PULLBACK confluence | Structurally impossible — it is a bug |
| Padding an empty screen with the "best of a bad lot" | The framework must be able to say "nothing today" |
