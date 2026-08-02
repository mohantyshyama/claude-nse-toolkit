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
   Add `--csv` when the user wants the matches in a file — to sort in a spreadsheet, to
   diff against yesterday's scan, or to keep a record. It costs nothing extra: the scan
   already ran.
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
| PULLBACK | A retracement into support that has started to turn | Score Now |
| TURN | Just after a 50/200 golden cross | Score at Trigger |
| CONFLUENCE | Names matching two or more of the above | Match count |

**COILED+BREAKOUT is the strongest pair the screen can produce**, not a contradiction: it
is the VCP breakout — a base whose volatility contracted right up to the close that cleared
it, which is the `COILED -> BREAKOUT` arrow above happening on one bar. Rank and report it
like any other confluence.

**BREAKOUT+PULLBACK is impossible** — price cannot be above the prior base high and
retraced to the 20- or 50-day average at the same time. The engine asserts this; if you
ever see it reported, it is a predicate bug, not a rare event.

**Each setup carries its own volume test, chosen for its stage.** COILED asks for at least
one prior up-thrust in ~126 sessions — a base nobody ever bought is a dead stock, not a
spring. BREAKOUT is not gated further; its 1.5-2.0x breakout-bar volume already is the
evidence. LEADER and TURN require the up/down volume ratio at 1.25 or better (1.50 strict).
PULLBACK requires the retracement to trade on no more than 0.90x the volume of the advance
it retraces (0.75 strict). TURN is deliberately **not** gated on volume expansion since the
golden cross — that measure decays with the age of the cross, so it would penalise an older
cross rather than weak demand. If asked why, say so; it looks like an omission otherwise.

**One volume gate is shared by all of them**: a setup fails when the close-weighted ratio
(`ud_weighted`) and the 20-day ratio (`ud_20`) are both below 1.0 — two independent measures
agreeing the stock is being distributed *now*. Names failing only one still match, and are
reported with their `Volume Signal` label.

**PULLBACK waits for the turn, not just the dip.** A match is a name at least 3% below a
recent swing high (5% strict) whose last bar — or the one before it — reached a support
level, closed back above that same level, and closed in the top half of its own range
(top 40% strict). A stock still falling into support does not match, however close to its
20-day it sits. Expect far fewer PULLBACK names than the other setups produce; that is the
gate working, not a thin tape.

## Output contract

1. **Scan header** — date, universe, counts, FAILED list, per-setup match counts.
2. **One table per chosen setup**, ranked. Full-word column headers, always including
   `Sector`, `Score Now (catalyst-neutral)`, `Up/Down Volume Ratio`, `Volume Signal` and
   `Accumulation Trend`. Include `showing top N of M` whenever the list was truncated.
3. **The key**, after every table. Never drop it — a narrower table is harder to read,
   not faster.
4. **Breadth read** — two or three sentences on what the match counts and sector
   concentration say about the market.
5. **Handoff line** — the paste-ready `watchlist.py` command for the shortlist.
6. One line noting this is mechanical framework output, not personalised investment advice.

## CSV export

`--csv` writes the same scan to a file. It is an additional output, not a different one:
the terminal tables and the file come from one scan and one ranking.

```bash
python3 <skill-dir>/screener.py --setup all --csv               # ./scans/scan_<date>.csv
python3 <skill-dir>/screener.py --setup coiled --csv picks.csv  # exactly that path
python3 <skill-dir>/screener.py --setup all --csv log.csv --append   # keep a history
```

- **Long format: one row per (symbol, setup).** A stock matching three setups gets three
  rows. Group or filter on the `setup` column; never expect one row per stock.
- **The file keeps the top 20 of each setup's ranking**, so a full scan writes at most 120
  rows. `--top` is a separate limit and governs the terminal alone — it never reaches the
  file, and raising or lowering it does not change what is written. The `rank` column
  preserves the on-screen order and stays contiguous `1..20`, so `rank <= 15` reproduces
  the table exactly.
- **Dates read `02-Aug-2026`, not `2026-08-02`.** Excel turns an ISO date into its internal
  serial and shows a bare number. The default *filename* stays ISO
  (`scans/scan_2026-08-02.csv`) on purpose, so a directory of scans lists chronologically.
- **`setups_matched` and `match_count` are on every row**, so a COILED row shows the stock
  is also a LEADER without joining the file to itself.
- **Values are raw numbers** — `6.217`, not `"6.2%"`; `4.106`, not `"4.11x"`; `pos_in_base`
  as `0.982`, not `98%`. Sortable as they stand. `vetoed` is `0`/`1`, missing values are
  empty cells, and `flags` carries `volume_light` for a 1.5–2.0x breakout.
- **CONFLUENCE rows leave the evidence pair blank** — `setups_matched` and `setup_fit`
  already are its evidence.
- `--append` writes the header only when the file is new or empty, so a growing log stays
  one table. `--json` and `--csv` are independent and may be used together; the "wrote N
  rows" notice goes to stderr so JSON on stdout stays parseable.

The 31 columns, in order: `scan_date`, `last_closed_bar`, `universe`, `mode`, `symbol`,
`sector`, `setup`, `rank`, `setup_fit`, `score_now`, `score_at_trigger`, `risk_reward`,
`vetoed`, `action`, `price`, `trigger_price`, `stop`, `rs_1m`, `rs_3m`, `ud_ratio`,
`ud_weighted`, `ud_20`, `volume_signal`, `accumulation_trend`,
`setups_matched`, `match_count`, `evidence_1_label`, `evidence_1_value`,
`evidence_2_label`, `evidence_2_value`, `flags`.

`ud_ratio` is the up/down volume ratio, on every row including CONFLUENCE — a per-symbol
metric like `rs_3m`, not an evidence slot, so it sits with them rather than in the
setup-specific pair. An unmeasurable ratio is an empty cell, never a `1.00`.

The four columns beside it qualify it, and are per-symbol in the same way. `ud_weighted` is
the same 50 sessions with each bar weighted by where it closed *inside its own range*
(Chaikin's money-flow multiplier: +1 at the high, −1 at the low, 0 at the midpoint) rather
than against yesterday's close. `ud_20` is the plain ratio over 20 bars. `volume_signal` is
the four-way reading of `ud_ratio` against `ud_weighted`, cut at 1.25 and 1.0 —
`accumulation` / `distribution-into-strength` / `supported` / `distribution` — and
`accumulation_trend` is `ud_20` as a fraction of `ud_ratio`: `strengthening` above 1.30,
`steady` 0.90–1.30, `flattening` 0.70–0.90, `fading` below 0.70, and `reversed` when that
same drop also puts `ud_20` below 1.0 outright.
Either label reads `unknown` when there was too little volume history to classify the name —
a stated finding, and written out as that word rather than left blank. The numbers are kept
alongside the labels so the file carries the inputs, not only the verdict.

`mode` records `strict` or `loosened`, so two files from different threshold settings can
never be silently concatenated as one scan.

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
- **An `Up/Down Volume Ratio` below 1.0 means the price chart and the volume disagree.**
  More money moved the stock down than up over the last 50 sessions, on a name that still
  cleared every price condition its setup asks for. Only COILED, BREAKOUT and PULLBACK can
  print it — LEADER and TURN gate above it — and on those it is the one fact the setup did
  not test, so call it out in the write-up rather than letting the row pass unremarked. It
  is not automatically disqualifying: a coil is meant to be quiet and a pullback is meant
  to be sold. A `-` means the ratio could not be measured; it is not a 1.00.
- **A `distribution-into-strength` label means the price and the volume disagree, and the
  name needs a closer look before anyone acts on it.** The up/down ratio is high — price is
  closing above yesterday session after session — while the close-weighted ratio is low, so
  sellers are taking the close each day. That is supply being distributed into strength, and
  it wears a good-looking number: on the raw ratio alone these are the best rows on the page.
  The name still matched its setup and is reported normally; say what the label means rather
  than letting a strong `Up/Down Volume Ratio` speak for the row unchallenged. `supported` is
  the mirror case and reads the other way — a soft ratio with buyers defending every dip,
  often a base forming. Pair both with `Accumulation Trend`: a `fading` or `reversed` trend
  says whatever the 50-day number describes has already stopped.
- **The volume gate takes two negative readings, not one.** A setup fails only when the
  close-weighted ratio and the 20-day ratio are *both* below 1.0. This is deliberately
  conservative: one measure reading negative is a caution and gets surfaced with its label,
  two independent measures agreeing is a finding and gets excluded. Do not describe a single
  sub-1.0 reading as a failed gate.
- **An empty screen in a falling market may be the threshold, not the market.** The volume
  floors are absolute numbers rather than percentiles of the day's universe, so in a broad
  selloff they can reject nearly everything. If the rejection funnel shows most names dying
  at a volume gate, say that the threshold no longer suits the regime — which is a
  different finding from "no setups exist", and the reader must not confuse the two.

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
| Reading the CSV as one row per stock | It is long format; a three-setup name has three rows |
| Expecting `--top` to change the CSV | It governs the terminal only; the file's own cap is 20 per setup |
| Reading a short PULLBACK list as a data problem | It waits for a reversal at support; most dips do not have one |
| Appending scans with different `--strict` settings and reading them as one | The `mode` column is there to keep them apart |
| Reporting a sub-1.0 `Up/Down Volume Ratio` without comment | The price chart and the volume disagree, and only the reader can weigh that |
| Reading a `-` in the ratio column as a neutral 1.00 | It means the ratio could not be measured at all |
| Reporting a `distribution-into-strength` row on its strong `Up/Down Volume Ratio` alone | Price and volume disagree; the label is the reason to look closer |
| Calling a name distributing off one sub-1.0 reading | The gate needs both measures; one is a caution, not a finding |
| Calling an empty selloff screen "no setups exist" | The absolute volume floors may simply no longer suit the regime |
