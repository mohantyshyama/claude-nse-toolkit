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
   already ran. Add `--csv-per-setup` alongside it when they want each setup in its own
   file rather than one file to filter. Use `--csv-dir DIR` instead of `--csv` when they
   want every run kept separately — it puts this scan's reports in a new timestamped
   folder under `DIR` rather than writing over yesterday's file.
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
(`close_weighted_volume_ratio_50d` in the CSV) and the 20-day ratio
(`up_down_volume_ratio_20d`) are both below 1.0 — two independent measures
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
python3 <skill-dir>/screener.py --setup all --csv --csv-per-setup    # + one file per setup
python3 <skill-dir>/screener.py --setup all --csv-dir /tmp/nsereports # a new folder per run
```

### CSV headers are self-describing — a standing constraint

**A header must convey what the number is and in what unit, without the reader consulting
this document.** The file is opened in a spreadsheet weeks later by someone who does not
have the key beside them, so `up_down_volume_ratio_20d` is the column name and `ud_20` is
not. `relative_strength_3month_vs_nifty50_pct_points` says what was measured, against what,
and on what scale; `rs_3m` said none of the three. `stop_price_1p5_atr_below_last` says
where the stop came from; `stop` did not.

This is not a style preference, it is the schema's contract, and it binds every column
added from here on:

- The name states the measurement **and its unit or scale** — `_0_to_10`, `_pct_points`,
  `_ratio_50d`, `_price`, `_1p5_atr_`.
- Names stay valid snake_case identifiers with no spaces, so `pandas` attribute access and
  spreadsheet formulas both work. A decimal point becomes `p`: `1p5_atr`, never `1.5_atr`.
- Names never repeat and never nest inside one another. Two overlapping verbose names is
  precisely the confusion the length exists to prevent.
- Length is not a cost worth trading away. A header that needs a glossary entry to be
  understood is the bug; the twelve extra characters that avoid it are not.

The rule is also recorded at the top of `csv_export.py`, where someone adding a 32nd column
reads it. The **internal** field names that `screener.py` ranks and renders from stay terse
on purpose — those are in-memory keys reaching back into `analyze.py`'s shape, and only the
file is read cold.

### Semantics

- **Long format: one row per (symbol, setup).** A stock matching three setups gets three
  rows. Group or filter on the `setup_name` column; never expect one row per stock.
- **The file keeps the top 20 of each setup's ranking**, so a full scan writes at most 120
  rows. `--top` is a separate limit and governs the terminal alone — it never reaches the
  file, and raising or lowering it does not change what is written. The
  `rank_within_setup` column preserves the on-screen order and stays contiguous `1..20`, so
  `rank_within_setup <= 15` reproduces the table exactly.
- **Dates read `02-Aug-2026`, not `2026-08-02`.** Excel turns an ISO date into its internal
  serial and shows a bare number. The default *filename* stays ISO
  (`scans/scan_2026-08-02.csv`) on purpose, so a directory of scans lists chronologically.
  The `--csv-dir` *folder* name is a third format and deliberately breaks that second rule —
  see below.
- **`all_setups_matched` and `setups_matched_count` are on every row**, so a COILED row
  shows the stock is also a LEADER without joining the file to itself.
- **Values are raw numbers** — `6.217`, not `"6.2%"`; `4.106`, not `"4.11x"`; `pos_in_base`
  as `0.982`, not `98%`. Sortable as they stand. `risk_reward_veto_applied` is `0`/`1`,
  missing values are empty cells, and `warning_flags` carries `volume_light` for a 1.5–2.0x
  breakout. The unit lives in the header, so it never has to live in the cell.
- **CONFLUENCE rows leave the evidence pair blank** — `all_setups_matched` and
  `setup_fit_score_0_to_10` already are its evidence.
- `--append` writes the header only when the file is new or empty, so a growing log stays
  one table. `--json` and `--csv` are independent and may be used together; the "wrote N
  rows" notice goes to stderr so JSON on stdout stays parseable.

### The 31 columns, in order

| # | Column | What it holds |
|---|---|---|
| 1 | `scan_date` | The day the scan ran, `02-Aug-2026` |
| 2 | `last_closed_bar_date` | The last completed session the scan read |
| 3 | `universe_name` | `nifty500` — the universe, not the file it came from |
| 4 | `threshold_mode` | `strict` or `loosened` |
| 5 | `symbol` | NSE ticker |
| 6 | `sector` | NSE sector |
| 7 | `setup_name` | `COILED`, `BREAKOUT`, `LEADER`, `PULLBACK`, `TURN`, `CONFLUENCE` |
| 8 | `rank_within_setup` | 1..20, this setup's own ranking |
| 9 | `setup_fit_score_0_to_10` | How well the name fits *this* setup |
| 10 | `score_now_catalyst_neutral_0_to_10` | Weighted 6-factor total, catalyst held at 5.0 |
| 11 | `score_if_trigger_fires_0_to_10` | The same total projected at the breakout trigger |
| 12 | `risk_reward_ratio_vs_1p5_atr_stop` | Reward ÷ risk, risk measured to the 1.5×ATR stop |
| 13 | `risk_reward_veto_applied` | `1` when R:R fell under 1.5 and the name was demoted |
| 14 | `action_bucket` | `BUY NOW` / `BUY HALF` / `ALERT` / `WATCH` |
| 15 | `last_price` | Close of the last completed session |
| 16 | `trigger_price_that_repairs_setup` | The breakout level the projection assumes |
| 17 | `stop_price_1p5_atr_below_last` | `last_price − 1.5 × daily ATR` |
| 18 | `relative_strength_1month_vs_nifty50_pct_points` | 1-month return minus Nifty 50's, in points of percent |
| 19 | `relative_strength_3month_vs_nifty50_pct_points` | The same over 3 months |
| 20 | `up_down_volume_ratio_50d` | Up-close volume ÷ down-close volume, 50 sessions |
| 21 | `close_weighted_volume_ratio_50d` | The same 50 sessions, each bar weighted by where it closed in its own range |
| 22 | `up_down_volume_ratio_20d` | The plain ratio over the last 20 sessions |
| 23 | `volume_signal_reading` | `accumulation` / `distribution-into-strength` / `supported` / `distribution` / `unknown` |
| 24 | `accumulation_trend_reading` | `strengthening` / `steady` / `flattening` / `fading` / `reversed` / `unknown` |
| 25 | `all_setups_matched` | Pipe-delimited, life-cycle ordered, on every row |
| 26 | `setups_matched_count` | How many, CONFLUENCE excluded |
| 27 | `evidence_1_metric_name` | The setup-specific metric, e.g. `contraction` |
| 28 | `evidence_1_metric_value` | Its raw number |
| 29 | `evidence_2_metric_name` | The second setup-specific metric |
| 30 | `evidence_2_metric_value` | Its raw number |
| 31 | `warning_flags` | Pipe-delimited caveats; `volume_light` today |

`up_down_volume_ratio_50d` is on every row including CONFLUENCE — a per-symbol metric like
the relative-strength pair, not an evidence slot, so it sits with them rather than in the
setup-specific pair. An unmeasurable ratio is an empty cell, never a `1.00`.

The four columns beside it qualify it, and are per-symbol in the same way.
`close_weighted_volume_ratio_50d` is the same 50 sessions with each bar weighted by where it
closed *inside its own range* (Chaikin's money-flow multiplier: +1 at the high, −1 at the
low, 0 at the midpoint) rather than against yesterday's close. `up_down_volume_ratio_20d` is
the plain ratio over 20 bars. `volume_signal_reading` is the four-way reading of the 50-day
ratio against its close-weighted twin, cut at 1.25 and 1.0 — `accumulation` /
`distribution-into-strength` / `supported` / `distribution` — and
`accumulation_trend_reading` is the 20-day ratio as a fraction of the 50-day:
`strengthening` above 1.30, `steady` 0.90–1.30, `flattening` 0.70–0.90, `fading` below 0.70,
and `reversed` when that same drop also puts the 20-day ratio below 1.0 outright.
Either label reads `unknown` when there was too little volume history to classify the name —
a stated finding, and written out as that word rather than left blank. The numbers are kept
alongside the labels so the file carries the inputs, not only the verdict.

`threshold_mode` records `strict` or `loosened`, so two files from different threshold
settings can never be silently concatenated as one scan.

### `--csv-per-setup`

Passed alongside `--csv`, it *also* writes one file per setup that matched, named from the
`--csv` path:

```
scans/scan_2026-08-02.csv          the combined scan, still written
scans/scan_2026-08-02_COILED.csv   11 rows
scans/scan_2026-08-02_LEADER.csv    7 rows
```

Each carries the same 31 columns and the same 20-row cap, holding only that setup's rows.
Three rules:

- **The combined file is still written.** The split is additional, never a replacement.
- **A setup that matched nothing writes no file**, not a header-only one. An empty
  `scan_2026-08-02_TURN.csv` reads as "the scan produced nothing" to whoever opens it, when
  what it means is that TURN matched nothing while COILED matched eleven. Absence is the
  honest form of that. The combined file keeps the opposite rule for the opposite reason: a
  scan that matched nothing anywhere *is* a finding, and needs a headed, parseable file to
  say so.
- **`--csv-per-setup` without `--csv` is a usage error**, not a silent no-op — the
  per-setup files are named from the `--csv` path, so alone the flag has no base to build
  on.

One stderr line per file names it and its row count, so `--json` on stdout stays parseable.

### `--csv-dir` — a new timestamped folder per run

`--csv-dir DIR` writes this scan's reports into a **new subfolder of `DIR`**, named
`scan_<dd-mm-yy>_<HHMMSS>`. Use it when the user wants every run kept rather than one file
overwritten or one log appended to. `DIR` and any missing parents are created; if `DIR`
already exists as a *file* the run stops with a message naming it, before the scan runs.

Inside the folder the combined file is always `scan.csv`, and `--csv-per-setup` adds
`scan_<SETUP>.csv` beside it:

```bash
python3 <skill-dir>/screener.py --setup all --csv-dir /tmp/nsereports --csv-per-setup
```

```
/tmp/nsereports/
  scan_02-08-26_205134/        a scan at 20:51:34 on 2 August 2026
    scan.csv                   the combined scan, always written
    scan_COILED.csv            11 rows
    scan_LEADER.csv             7 rows
    scan_CONFLUENCE.csv         4 rows
  scan_02-08-26_205207/        a second scan 33 seconds later, untouched by the first
    scan.csv
    ...
```

The filename inside the folder is undated because the **folder** carries the stamp —
`scan_02-08-26_205134/scan_02-08-26_205134.csv` would say it twice. The existing per-setup
rules are unchanged: a setup that matched nothing writes no file at all, and the combined
file is written even when nothing matched anywhere.

**The seconds are load-bearing.** Two scans in the same minute would otherwise resolve to
one folder and the second would write over the first, with no error and no way to tell
afterwards which scan the folder holds.

**The folder name is `dd-mm-yy` and therefore does not sort chronologically.** That inverts
the rule two sections up — the ISO *filename* exists precisely so a directory of scans lists
in date order — and it is a deliberate choice made at the user's explicit request, not an
oversight. The cost is real: `scan_02-08-26` sorts next to `scan_02-09-25`, a folder from a
different year. Changing `TIMESTAMP_DIR_FORMAT` in `csv_export.py` to `%y-%m-%d_%H%M%S`
would restore chronological sorting and change nothing else. The three formats and their
three jobs, in one place:

| Where | Format | Why |
|---|---|---|
| Date **cells** in the file | `02-Aug-2026` | Excel renders an ISO date as a serial number |
| `--csv` **filename** | `scan_2026-08-02.csv` | A directory of scans lists in date order |
| `--csv-dir` **folder** | `scan_02-08-26_205134` | The order the user asked to read it in |

Two pairings are usage errors rather than silent behaviour:

- **`--csv-dir` with `--csv` (in either form).** One names a file and the other names a
  directory; there is no way to honour both, and silently preferring one would put the scan
  somewhere the user is not looking while exiting 0. `--csv-dir` on its own is sufficient —
  it satisfies `--csv-per-setup` too, and does not additionally require `--csv`.
- **`--csv-dir` with `--append`.** The folder was created a moment earlier and is empty, so
  there is nothing in it to append to. Accepting the flag would imply a history is
  accumulating when each run starts a new folder. Use `--csv PATH --append` for a growing
  log.

The created folder is printed first, then the usual one line per file — all on stderr, so
`--json` on stdout stays parseable:

```
created /tmp/nsereports/scan_02-08-26_205134
wrote 62 rows to /tmp/nsereports/scan_02-08-26_205134/scan.csv
wrote 11 rows to /tmp/nsereports/scan_02-08-26_205134/scan_COILED.csv
```

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
| Shortening a CSV header to match the terminal's label | Headers are self-describing by contract; the unit lives in the name |
| Reading a missing `scan_<date>_TURN.csv` as a failed export | No file means that setup matched nothing; the combined file is always written |
| Passing `--csv` and `--csv-dir` together | Usage error — one names a file, the other a directory; `--csv-dir` alone is sufficient |
| Passing `--append` with `--csv-dir` | Usage error — the folder is new and empty every run, so there is nothing to append to |
| Reading `--csv-dir` folders as chronologically sorted | The folder name is `dd-mm-yy` by request; only the `--csv` filename is ISO |
| Reading a short PULLBACK list as a data problem | It waits for a reversal at support; most dips do not have one |
| Appending scans with different `--strict` settings and reading them as one | The `threshold_mode` column is there to keep them apart |
| Reporting a sub-1.0 `Up/Down Volume Ratio` without comment | The price chart and the volume disagree, and only the reader can weigh that |
| Reading a `-` in the ratio column as a neutral 1.00 | It means the ratio could not be measured at all |
| Reporting a `distribution-into-strength` row on its strong `Up/Down Volume Ratio` alone | Price and volume disagree; the label is the reason to look closer |
| Calling a name distributing off one sub-1.0 reading | The gate needs both measures; one is a caution, not a finding |
| Calling an empty selloff screen "no setups exist" | The absolute volume floors may simply no longer suit the regime |
