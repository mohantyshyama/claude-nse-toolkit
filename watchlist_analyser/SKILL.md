---
name: watchlist_analyser
description: Use when the user gives a list of two or more NSE or Indian stock tickers and wants them compared, ranked, screened, or shortlisted — which to go long, which to drop, relative scoring across the basket. Triggers include "analyse these stocks", "compare X, Y, Z on NSE", "rank my watchlist", "which of these should I buy".
---

# NSE Watchlist Analyser

Scores a basket of NSE symbols on the same framework as `stock_analyser`, then
adds the two things that only exist across a list: **relative strength vs the
Nifty 50**, and a **"score if the trigger fires"** projection. Output is a
ranked comparative table, a shortlist, full reports for the names you might act
on, and a five-line brief for the rest.

**Core principle: a shortlist ranks by actionability, not by quality.** The
best chart in the basket is often the one you cannot buy today. Ranking on the
raw score buries buyable names under un-buyable good ones; ranking on quality
alone recommends chasing. Show both numbers and let the gap do the work.

Single ticker? Use `stock_analyser` instead — this skill's value is the
comparison.

## Data source

Same constraint as `stock_analyser`: the TradingView MCP has **no NSE India TA
coverage** and `combined_analysis` emits `confidence: "HIGH"` on top of zero
data. Levels come from `watchlist.py`; `mcp__tradingview__stock_prices` with
`NSE:SYMBOL` is fine for a live quote cross-check.

**This skill imports the scoring engine from `stock_analyser/analyze.py`.**
Both skills must be installed in `~/.claude/skills/`. The scoring is never
reimplemented here — two copies would drift and the table would stop agreeing
with the per-name reports.

## Workflow

Three steps, three tool calls total regardless of basket size.

1. `python3 <skill-dir>/watchlist.py "SYM1,SYM2,SYM3"` — scores the basket in
   parallel (~2s for 12 names). Bad tickers are reported in a FAILED list and
   do not abort the run. **Never invent a level for a failed ticker** — name it
   and ask.
2. WebSearch **only the names in the printed NEWS SCAN LIST**. The engine omits
   names that are AVOID *and* whose trigger would still fail — a stock below
   every moving average on distribution volume is not rescued by a headline,
   and catalyst is 10% of the score. Searching them anyway is the single
   largest avoidable cost in this skill.
3. Re-run **once** with per-symbol catalysts and `--detail`:
   `--catalyst TITAN=8,BEL=3 --detail`. This prints the table, the shortlist
   *and* the full per-name report for every BUY/ALERT name in one pass — fetches
   are cached, so the detail costs nothing.

**Do not call `analyze.py` per name.** `--detail` already emitted those reports;
a second call per name re-runs work you have in front of you.

## Output contract

The table and shortlist come **first**, before any per-name detail — a 12-name
run is long and the ranking is the reason the user asked.

1. **Comparative table** — one row per name, ranked. Columns: Price, Score Now,
   Score at Trigger, the six component scores, Risk:Reward, Relative Strength
   1-month and 3-month, Action. Mark veto-capped rows.

   **Write column headers as full words.** Use these exact strings, including
   the weights:

   `Symbol · Price · Score Now · Score at Trigger · Trend (25%) · Location
   (25%) · Volume (15%) · Momentum (15%) · Catalyst (10%) · Volatility (10%) ·
   Risk:Reward · Relative Strength (1-month) · Relative Strength (3-month) ·
   Action`

   Spell out "Relative Strength" in the header itself — not "Rel. Str." or
   "RS", even when the column is narrow. Put the
   factor weight in the header (`Trend (25%)`) so a total can be checked against
   its parts. Immediately after the table, include the **key** explaining what
   each column measures and its units: scores are raw out of 10, Risk:Reward is
   a ratio against a 1.5×ATR stop, relative strength is in percentage points
   versus the Nifty 50. A reader must never have to decode an abbreviation or
   guess a unit.
2. **Shortlist** — the four buckets the engine emits, in order:
   - **BUY NOW / BUY HALF** — passes the gate today
   - **ALERT** — vetoed today, but the trigger genuinely repairs it
     (projected ≥6.0 *and* projected Risk:Reward ≥2:1). Give the alert price.
   - **LATENT** — currently AVOID, but a breakout *would* qualify. Worth an
     alert, not a position.
   - **trigger does not repair** — names that break out into a worse location
     than they occupy now. Say so explicitly; they look like candidates and
     are not.
3. **Cross-sectional read** — what the relative-strength columns say about the basket. Which
   names lead the index, which merely float with it, which are being sold.
   A high score with negative relative strength on both windows deserves a caveat.
4. **Per-name detail, split by actionability:**

   - **BUY and ALERT names → the complete 13-section `stock_analyser`
     contract.** These are the names the user may act on; they get everything.
     `--detail` has already printed the numbers for them.
   - **LATENT and AVOID names → a five-line brief**, this exact shape:

     ```
     **SYMBOL — score, ACTION**
     Trigger <price>: <repairs / does not repair, with the projected R:R>
     Support <zones> · Resistance <zones, with test counts>
     Invalidation: daily close below <price>
     Why not: <the single binding reason>
     ```

   The brief is not a truncated report — it is a complete answer to "why is
   this not on my list, and what would change that". Every line earns its
   place: the levels are what the user checks when the name moves, and the
   "why not" is what stops them re-asking next week.
5. One line noting this is mechanical framework output, not personalised
   investment advice.

### When the user asks for brevity

"Quick ranking", "no full workup on each", "keep it brief" — that request drops
**part 4 only**. Whatever the length, the output IS these five parts, in order:

1. The comparative table, full column headers, all six components intact
2. The key
3. The shortlist, with all four buckets present — including
   "trigger does not repair", which is the bucket a short answer most tempts
   you to cut and the one that prevents the worst trade
4. The cross-sectional read, compressed to two or three sentences
5. The not-advice line

Brevity removes the full reports, leaving the five-line briefs for every name.
It never removes a column from the table, a bucket from the shortlist, or the
key — a narrower table is harder to read, not faster.

## Reading the table

| Column | Meaning |
|---|---|
| Score Now | Weighted total out of 10 at today's price. `*` = Risk:Reward veto applied |
| Score at Trigger | Projected total if the breakout trigger fires. `none` for already-buyable names, which have no trigger to wait for |
| Trend / Location / Volume / Momentum / Catalyst / Volatility | The six components, so a total can be interrogated rather than trusted |
| Risk:Reward | Reward to the nearest real resistance ÷ risk to a 1.5×ATR stop |
| Relative Strength (1-month / 3-month) | Return minus the Nifty 50 over the same window, in percentage points |

**The most informative cell is the Score Now → Score at Trigger gap.** A large
positive gap (MPHASIS 4.83→6.57) means a good setup waiting on a price. A
negative gap (SBIN 4.93→4.80) means the breakout leads somewhere worse — the
name is not early, it is just weak.

Only trend and location are recomputed at the trigger price. Volume, momentum,
catalyst and volatility describe the chart's history and do not change because
price ticked higher — say so if the projection is questioned.

## Scoring

Identical weights, bands and Risk:Reward veto to `stock_analyser` — trend 25%,
location 25%, volume 15%, momentum 15%, catalyst 10%, volatility 10%; bands
≥7.5 / 6.0 / 4.5; veto caps at WATCHLIST below 1.5:1. Consistency between the
two skills matters more than any tuning gain.

**Relative strength is reported, not scored.** It is a cross-sectional read and
folding it into the weights would make single-name and watchlist scores
disagree for the same stock. Use it to break ties and to caveat, not to rank.

## Rules

- **Rank by actionability, then score, then 3-month relative strength.** The engine does this; do
  not re-sort the table by raw score in the write-up.
- **A basket of AVOIDs is a finding, not a failure.** Say plainly that nothing
  qualifies and give the alert levels. Do not manufacture a top pick to fill
  the shortlist — the framework's job is to say "none of these" when true.
- **Negative relative strength on both windows caps enthusiasm.** A 7.0 score in a stock
  lagging the index by 10 points is a weaker 7.0 than the number suggests.
- **Set catalysts per symbol before the final table.** A run where every
  catalyst is the default 5 has not used a tenth of the framework; say so if
  you are presenting one.
- **Report the FAILED list.** A ticker that did not resolve is not silently
  absent from the ranking.

## Common mistakes

| Mistake | Consequence |
|---|---|
| Running `analyze.py` N times and pasting the outputs | No ranking, no relative strength, no trigger projection — the user asked for a comparison |
| Ranking by raw score | Un-buyable names top the list |
| Listing every WAIT name as a candidate | SBIN-type names look like alerts when their trigger repairs nothing |
| Burying the table under the per-name reports | The ranking is the deliverable |
| Dropping a low-ranked name entirely instead of giving it the five-line brief | The user re-asks about it next week with no record of why it was cut |
| Calling `analyze.py` per name after `--detail` already printed those reports | N wasted tool calls per basket |
| Searching news for names the NEWS SCAN LIST omitted | The largest avoidable cost; catalyst is 10% of the score |
| Folding relative strength into the weighted score | The same stock scores differently in the two skills |
