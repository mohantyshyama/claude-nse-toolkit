# claude-nse-toolkit

Four interlocking [Claude Code](https://claude.com/claude-code) skills for mechanical
technical analysis of NSE-listed Indian equities: scan the market for named bullish setups,
rank a shortlist, work up a single name, and manage the position once you are in it.

Everything is plain Python 3.9 with **no third-party dependencies** — the standard library
and the Yahoo Finance chart API, nothing else. No API keys, no accounts, no `pip install`.

```
stock_screener  ──►  watchlist_analyser  ──►  stock_analyser  ──►  stock_planner
scan 500 names       rank 8-10 with           one name, full       position held,
in ~22 seconds       real catalysts           13-section report    stops & targets
```

---

## The four skills

Each one narrows what the previous produced. The question you are asking determines which
you need:

```
stock_screener  ──►  watchlist_analyser  ──►  stock_analyser  ──►  stock_planner

"what's out          "which of these        "should I buy       "where's my
 there?"              is best?"               this one?"          stop?"

500 names            8-10 names              1 name              position held
```

| Skill | Use it when | Produces |
|---|---|---|
| **stock_screener** | You have no names in mind | Six bullish setups scanned across the Nifty 500 in ~22s, ranked, with CSV export |
| **watchlist_analyser** | You have 2+ tickers to compare | Comparative table, relative strength vs Nifty 50, "score if the trigger fires", shortlist buckets |
| **stock_analyser** | You have one ticker | Full 13-section report: levels, weighted score, entry setups with R:R, position sizing, scenario tree, invalidation price |
| **stock_planner** | You already own it | Stop and target zones from nine independent methods, clustered by how many agree |

### What each one is for

**`stock_screener`** — the top of the funnel. Scans the Nifty 500 for six named setups
(COILED, BREAKOUT, LEADER, PULLBACK, TURN, CONFLUENCE), ranks each, and hands you a
shortlist. Use it when you want candidates rather than an opinion on a name you already
hold. Exports to CSV for tracking scans over time.

**`watchlist_analyser`** — adjudicates a basket. Adds the two things that only exist across
a list: relative strength versus the Nifty 50, and a projection of what each score becomes
*if* its breakout trigger fires. Sorts into BUY / ALERT / LATENT buckets, and flags names
whose trigger leads somewhere worse than where they already are — the ones that look like
candidates and are not.

**`stock_analyser`** — the deep workup on a single name. Support and resistance with what
is actually at each level, the weighted score broken into its six factors, entry setups
with their risk-reward arithmetic, ATR-normalised position sizing, a scenario tree, and the
single price that invalidates the thesis.

**`stock_planner`** — for a position you already hold, where the entry question is moot.
Derives stop and target candidates from nine independent methods (volatility, horizontal
structure, fibonacci, trendline, high-volume candles, volume nodes, moving averages, pivots,
measured move) and clusters them into confluence zones, so you can see which levels several
methods agree on.

### What holds them together

**One scoring engine.** `stock_screener` and `watchlist_analyser` both import
`stock_analyser/analyze.py` rather than reimplementing it, so **the same stock never carries
two different scores** — a test asserts equality to nine decimal places.

**The same six factors everywhere:** trend 25% · location 25% · volume 15% · momentum 15% ·
catalyst 10% · volatility 10%. With one deliberate exception — the screener holds catalyst
at a neutral 5.0, because a news search across 500 names is not feasible. Closing that gap
is precisely what `watchlist_analyser` is for.

**The risk-reward veto runs through all four.** Any name whose reward-to-risk falls below
1.5:1 against a 1.5×ATR stop is capped and demoted, however good its chart. Trend and entry
price are separate questions, and the whole toolkit is built to keep them separate.

> **A note on test coverage.** Only `stock_screener` has a test suite (1367 tests). The other
> three predate it and have none. That matters most for `analyze.py`: three skills import
> it, so a regression there would propagate silently with nothing to catch it.

### Which one do I need?

| If you are thinking… | Reach for |
|---|---|
| "I have money to deploy and no idea where" | `stock_screener` |
| "Show me what's breaking out today" | `stock_screener --setup breakout` |
| "Which stocks are quietly setting up before a move?" | `stock_screener --setup coiled` |
| "Give me only the highest-conviction names" | `stock_screener --setup confluence --strict` |
| "I have eight names on a list, which two deserve capital?" | `watchlist_analyser` |
| "Is my watchlist actually any good, or am I fooling myself?" | `watchlist_analyser` |
| "Everyone's talking about this stock — is it buyable?" | `stock_analyser` |
| "What's my downside if I'm wrong here?" | `stock_analyser` |
| "How many shares can I take at 1% risk?" | `stock_analyser` |
| "I'm up 12% — do I take it or let it run?" | `stock_planner` |
| "Where do I move my stop now?" | `stock_planner` |

### Triggering them in Claude Code

They fire on intent — you never need to name the skill:

**stock_screener**
> *"screen the Nifty 500 for breakouts"* · *"what's coiling right now?"* ·
> *"find me bullish setups"* · *"scan for stocks near 52-week highs"* ·
> *"give me watchlist candidates, strict mode"* · *"export the screen to CSV"*

**watchlist_analyser**
> *"compare TITAN, BEL and CHOLAFIN"* · *"rank my watchlist"* ·
> *"which of these five should I buy?"* · *"screen these names and drop the weak ones"*

**stock_analyser**
> *"analyse FEDERALBNK on NSE"* · *"should I go long BAJFINANCE?"* ·
> *"support and resistance for TITAN"* · *"what are the targets on GAIL?"* ·
> *"position size for a 1% risk on EICHERMOT"*

**stock_planner**
> *"I bought GAIL at 181, where's my stop?"* · *"I'm long TITAN from 4700, when do I exit?"* ·
> *"target and stop for my BAJFINANCE position"*

## A worked run through the funnel

**1. Scan.** No names in mind, so start wide:

```bash
python3 stock_screener/screener.py --setup all --strict --top 20 --csv
```

```
SCAN 02-Aug-2026 (last closed bar 31-Jul-2026) · universe nifty500 (500) · strict
scored 500 · FAILED 0 · below turnover floor 0
matches  COILED 0 · BREAKOUT 4 · LEADER 27 · PULLBACK 7 · TURN 20 · CONFLUENCE 5
```

Five names match two or more setups. The top row matches three — but read the risk-reward
column before getting excited:

| Symbol | Setups | Score | R:R | Action |
|---|---|---|---|---|
| GAIL | BREAKOUT+LEADER+TURN | 6.12 | **0.35:1** | ALERT |
| BAJFINANCE | BREAKOUT+TURN | 7.80 | 2.46:1 | BUY NOW |

**GAIL matches the most setups and is still not buyable.** Resistance sits three times
closer than the stop. It is an alert at its trigger price, not a position. This is the
distinction the whole toolkit exists to enforce.

**2. Adjudicate.** Take the shortlist into `watchlist_analyser`, which sets real catalysts
per name — the 10% of the score the screener could not evaluate:

```bash
python3 watchlist_analyser/watchlist.py "FEDERALBNK,BAJFINANCE,BAJAJ-AUTO,TITAN,GAIL"
```

It prints a NEWS SCAN LIST — the names worth searching. Re-run once with what you find:

```bash
python3 watchlist_analyser/watchlist.py "FEDERALBNK,BAJFINANCE,TITAN" \
    --catalyst FEDERALBNK=8,BAJFINANCE=7,TITAN=5 --detail
```

**3. Work up the survivor.**

```bash
python3 stock_analyser/analyze.py FEDERALBNK --catalyst 8
```

Full report: the verdict first, then levels with what is actually at each one, the six
score components, entry setups with their R:R arithmetic, share counts at 1% account risk,
a scenario tree, and the single price that breaks the thesis.

**4. Manage it.** Once you are in:

```bash
python3 stock_analyser/levels.py FEDERALBNK --entry 358.85
```

Nine methods, clustered. Rank the zones by how many methods agree, then filter by distance —
a six-method cluster 0.3×ATR away is not a stop, it is where price already is.

## Design principles

Four ideas recur across all the skills, and they are the reason the output looks the way it
does.

**The verdict comes first.** Every report leads with its conclusion — INITIATE / HALF SIZE /
WATCHLIST / STAND ASIDE — rather than making you hunt for it beneath the analysis. If bias
and action diverge ("bullish, but no long here"), that is stated explicitly along with the
arithmetic that forces it.

**A weak case still produces a call.** The framework must be able to say STAND ASIDE and
give the levels that would change its mind. "It depends" and "consult an adviser" are the
one output it cannot produce — a screener that never says no is not a screener.

**An empty result is a finding.** When nothing matches, the output says so plainly and names
the condition that rejected the field. Nothing is ever padded to fill a list.

**Numbers must be interrogable.** Every score is broken into its components, every level says
what is at it (swing low, volume node, moving average, fibonacci, pivot), and every column
carries its unit. A level with only one thing at it is weak, and the report says so rather
than leaving you to work it out.

## Quick start

```bash
git clone https://github.com/mohantyshyama/claude-nse-toolkit.git
cp -R claude-nse-toolkit/stock_* claude-nse-toolkit/watchlist_analyser ~/.claude/skills/
```

Then in Claude Code, just ask — the skills trigger on intent:

> *"screen the Nifty 500 for breakouts"* → `stock_screener`
> *"compare TITAN, BEL and CHOLAFIN"* → `watchlist_analyser`
> *"analyse FEDERALBNK on NSE"* → `stock_analyser`
> *"I bought BAJFINANCE at 1141, where's my stop?"* → `stock_planner`

Or run them directly:

```bash
python3 ~/.claude/skills/stock_screener/screener.py --setup all --top 15
python3 ~/.claude/skills/stock_screener/screener.py --setup confluence --top 10
python3 ~/.claude/skills/stock_screener/screener.py --setup breakout --strict
python3 ~/.claude/skills/stock_screener/screener.py --setup leader --sector "Financial Services"
python3 ~/.claude/skills/stock_screener/screener.py --setup all --csv        # ./scans/scan_<date>.csv
python3 ~/.claude/skills/stock_screener/screener.py --setup all --csv --csv-per-setup  # + one file per setup
python3 ~/.claude/skills/stock_screener/screener.py --setup all --csv-dir /tmp/nsereports  # a new timestamped folder per run

python3 ~/.claude/skills/watchlist_analyser/watchlist.py "TITAN,BEL,CHOLAFIN" --detail
python3 ~/.claude/skills/stock_analyser/analyze.py FEDERALBNK
python3 ~/.claude/skills/stock_analyser/levels.py BAJFINANCE --entry 1141
```

## The six setups

Five are stages of one bullish life cycle, which is why a stock appearing in two is signal
rather than double-counting:

```
COILED ──► BREAKOUT ──► LEADER        PULLBACK: re-entry, established trend
(a base     (it gives    (it now       TURN:     entry, brand-new trend
tightening)  way)         leads)       CONFLUENCE: two or more of the above
```

| Setup | Catches | Ranked by |
|---|---|---|
| **COILED** | Volatility contracting inside a base, before the move | Score at Trigger |
| **BREAKOUT** | The base giving way on volume, the day it fires | Score Now |
| **LEADER** | Established leadership near 52-week highs, not yet exhausted | Score Now |
| **PULLBACK** | An uptrend resting into support, and turning back up | Score Now |
| **TURN** | The early part of a confirmed new trend | Score at Trigger |
| **CONFLUENCE** | Names matching two or more of the above | Match count |

**Each setup carries a volume test, and they are deliberately not the same test wearing five
labels.** The setups sit at different points of one life cycle, and "healthy volume" means
something different at each: COILED asks whether the base was ever *bought* (at least one
up-thrust in ~126 sessions), BREAKOUT already gates the breakout bar itself at 1.5–2.0×
average and adds nothing further, LEADER and TURN require O'Neil's **up/down volume ratio**
— volume on up-closes divided by volume on down-closes over 50 sessions — at 1.25 or better,
and PULLBACK requires the retracement to trade on no more than 0.90× the volume of the
advance it retraces. Strict tightens each. Before this, volume was used only *negatively*
("no down-thrust recently"), and it showed: LEADER's median up/down ratio was 1.34 against
a universe median of 1.33 — no volume edge at all.

That same ratio is now a shared **accumulation** term inside every setup's Setup Fit —
20% of it for COILED, BREAKOUT, LEADER and TURN, 10% for PULLBACK, which already spends 25%
on a volume term of its own. Every other weight came down to make room, so Fit is still out
of 10. Because CONFLUENCE ranks on mean Setup Fit, this changes CONFLUENCE ordering.

**Two further measures qualify that ratio, and feed the same accumulation term.**
`ud_weighted` weights each bar by *where it closed inside its own range* rather than against
yesterday's close, so a day spent at the low is no longer booked as accumulation for closing a
paisa up; `ud_20` runs the same ratio over 20 sessions, so a stock that was accumulated two
months ago and distributed since no longer scores like one being bought today. A setup fails
only when **both** read below 1.0 — one negative reading is a caution, two independent ones
are a finding.

**[Full writeup of each setup, with the market logic and exact thresholds →
`docs/setups.md`](docs/setups.md)**

`--strict` tightens every threshold. Strict is always a subset of loosened, verified across
the live universe.

## Understanding the output

### The risk-reward veto is the point

Any name whose reward-to-risk at the current price falls below 1.5:1 — measured to the
nearest real resistance, against a stop 1.5× ATR away — is marked `*` and sorted **below
every clean name**, whatever its score.

This is the mechanic the whole framework exists for. **Trend and entry price are two
separate questions.** A stock can be in a flawless uptrend and still be un-buyable today
because the nearest resistance is closer than the nearest viable stop. Conflating the two
is how good analysis becomes a bad trade.

Vetoed names are kept, not dropped, along with the price that would repair the setup — a
good chart you cannot buy today is information.

### The score

Six weighted factors, out of 10:

| Factor | Weight | Basis |
|---|---|---|
| Trend | 25% | Moving-average stack |
| Location | 25% | Risk-reward at the current price |
| Volume | 15% | Thrust direction and recency, dry-up |
| Momentum | 15% | RSI bands and MACD, daily and weekly |
| Catalyst | 10% | Manual, from news |
| Volatility | 10% | ATR as a percentage of price |

Bands: **≥7.5** full position · **6.0–7.4** half · **4.5–5.9** watchlist · **<4.5** stand
aside. The risk-reward veto overrides the band.

### Every table shows the up/down volume ratio

`Up/Down Volume Ratio` is a base column on every screener table, CONFLUENCE included, and
`up_down_volume_ratio_50d` in the CSV: volume on up-closes divided by volume on down-closes over the last
50 sessions. It is shown whether or not it gated the setup — LEADER and TURN reject on it,
so those columns can never read below their floor, while COILED, BREAKOUT and PULLBACK do
not, which makes it the most informative number in those rows.

**Above 1.0 is net accumulation; below 1.0 means the price chart and the volume disagree.**
It reads `-` when the stock had no down-closes in the window to divide by — a dash is not a
1.00 and must not be read as one.

Two companion columns qualify it. `Volume Signal` reads the raw ratio against the
close-weighted one, four ways — high and low being 1.25 on the raw ratio, the same floor
LEADER and TURN gate on, and 1.0 on the close-weighted one: **both high** is genuine
accumulation, price rising and closing strong (`accumulation`); **ratio high, weighted low**
means price drifts up while sellers
control the close — institutional supply being distributed into strength
(`distribution-into-strength`); **ratio low, weighted high** means price is soft but buyers
defend every dip, often a base forming (`supported`); **both low** is distribution,
unambiguously (`distribution`). `Accumulation Trend` compares the 20-day ratio against the
50-day — `strengthening` / `steady` / `flattening` / `fading` / `reversed` — so a number built
mostly out of buying that stopped a month ago says so. Either column reads `unknown` when
there was not enough volume history to classify the name.

`distribution-into-strength` is the reading the screener previously could not produce at all:
every price condition passed, the up/down ratio in the top decile, and supply being fed into
the advance one strong-looking close at a time.

### Screener scores are catalyst-neutral

Catalyst needs a news search per name, which is not feasible across 500 stocks, so every
scanned name sits at the neutral default of 5.0. A screener score will therefore differ
slightly from `watchlist_analyser`'s for the same stock once real catalysts are set.

That gap is not an inconsistency — it is why the handoff exists. The screener produces
candidates; adjudication happens one level down.

### An empty screen is a finding

When nothing matches, the output names the condition that rejected the field rather than
reporting a bare zero. The screener will not pad a list to fill 15 rows.

### The CSV is long format, capped at 20 rows per setup

`--csv` writes one row per (symbol, setup) pair: a stock matching three setups gets three
rows, so a seventh setup added later costs zero new columns. `all_setups_matched` and
`setups_matched_count` appear on every row, so a COILED row shows the stock is also a
LEADER without a join. Every value is a raw number — `6.217`, not `"6.2%"`; `4.106`, not
`"4.11x"` — because a file that needs string-stripping before a column can be sorted is not
a data file.

The file keeps the top 20 of each setup's ranking, so a full scan writes at most 120 rows.
The fortieth name in a 45-name LEADER table cleared the gate and nothing more; keeping it
made the file look like a data set when it is a shortlist. `--top` is a separate limit and
governs the terminal alone — it never reaches the file. The `rank_within_setup` column
preserves the on-screen order and stays contiguous `1..20`, so `rank_within_setup <= 15`
reproduces the printed table exactly.

Dates in the file read `02-Aug-2026`, not `2026-08-02`, because Excel converts an ISO date
to its internal serial and renders the cell as a bare number. The default *filename* stays
ISO — `scans/scan_2026-08-02.csv` — so a directory of scans lists chronologically. The two
formats serve a spreadsheet cell and a directory listing, and neither is right for both.
The `--csv-dir` *folder* name is a third format that deliberately breaks the second rule;
see below.

`--append` writes the header only when the file is new or empty, and the `threshold_mode`
column records `strict` or `loosened` so two differently-thresholded scans cannot be read
as one.

### CSV headers say what the number is and in what unit

The file is opened in a spreadsheet weeks after the scan, by someone without the
documentation beside them. So every one of the 31 headers carries its own meaning and
scale: `up_down_volume_ratio_20d`, not `ud_20`;
`relative_strength_3month_vs_nifty50_pct_points`, not `rs_3m`;
`stop_price_1p5_atr_below_last`, not `stop`. A header that needs a glossary entry to be
understood is the bug, and the extra characters that avoid it are not a cost.

That is a standing constraint on the schema, recorded at the top of `csv_export.py` and in
`SKILL.md`, and it binds every column added later. Names stay valid snake_case identifiers
so `pandas` attribute access and spreadsheet formulas both work — a decimal point becomes
`p`, as in `1p5_atr` — and no two names repeat or nest inside one another. The *internal*
field names that `screener.py` ranks and renders from stay terse on purpose: those are
in-memory keys reaching into `analyze.py`'s shape, and only the file is read cold.

The 31 columns, in order:

| # | Column | What it holds |
|---|---|---|
| 1 | `scan_date` | The day the scan ran, `02-Aug-2026` |
| 2 | `last_closed_bar_date` | The last completed session the scan read |
| 3 | `universe_name` | `nifty500` |
| 4 | `threshold_mode` | `strict` or `loosened` |
| 5 | `symbol` | NSE ticker |
| 6 | `sector` | NSE sector |
| 7 | `setup_name` | `COILED` / `BREAKOUT` / `LEADER` / `PULLBACK` / `TURN` / `CONFLUENCE` |
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

`up_down_volume_ratio_50d` sits immediately after the 3-month relative strength, alongside
the other per-symbol metrics rather than in an evidence slot, and is written on every row
including CONFLUENCE. An unmeasurable ratio is an empty cell, never a `1.00`. Beside it are
the two other raw numbers and the two labels derived from them —
`close_weighted_volume_ratio_50d`, `up_down_volume_ratio_20d`, `volume_signal_reading` and
`accumulation_trend_reading` — so the file keeps the inputs, not just the verdict, and a
spreadsheet can re-cut the four-way reading itself.

### `--csv-per-setup` splits the scan into one file per setup

Passed alongside `--csv`, it *also* writes one file per setup that matched, named from the
`--csv` path:

```
scans/scan_2026-08-02.csv          the combined scan, still written
scans/scan_2026-08-02_COILED.csv   11 rows
scans/scan_2026-08-02_LEADER.csv    7 rows
```

Each carries the same 31 columns and the same 20-row cap, holding only that setup's rows.
The combined file is still written — the split is additional, never a replacement.

**A setup that matched nothing writes no file**, not a header-only one. An empty
`scan_2026-08-02_TURN.csv` reads as "the scan produced nothing" to whoever opens it, when
what it means is that TURN matched nothing while COILED matched eleven. Absence is the
honest form of that. The combined file keeps the opposite rule for the opposite reason: a
scan that matched nothing anywhere *is* a finding and needs a headed, parseable file to say
so.

`--csv-per-setup` without a destination is a usage error rather than a silent no-op, because
the per-setup files are named from the combined file's path and alone the flag has no base
to build on. Either `--csv` or `--csv-dir` supplies that base.
One stderr line per file names it and its row count, so `--json` on stdout stays parseable.

### `--csv-dir` keeps every run in its own timestamped folder

`--csv-dir DIR` writes the scan into a **new subfolder of `DIR`** named
`scan_<dd-mm-yy>_<HHMMSS>`, rather than to a path that the next run overwrites. `DIR` and
any missing parents are created; if `DIR` exists as a file the run stops with a message
naming it, before the scan runs. Inside the folder the combined file is always `scan.csv`, and `--csv-per-setup`
adds `scan_<SETUP>.csv` beside it:

```bash
python3 stock_screener/screener.py --setup all --csv-dir /tmp/nsereports --csv-per-setup
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

The file inside is undated because the **folder** carries the stamp;
`scan_02-08-26_205134/scan_02-08-26_205134.csv` says it twice. The per-setup rules are
unchanged — a setup that matched nothing writes no file, and the combined file is written
even when nothing matched anywhere.

The **seconds** are load-bearing: two scans in the same minute would otherwise resolve to
one folder and the second would silently write over the first.

The folder name is `dd-mm-yy` and therefore **does not sort chronologically**. That inverts
the filename rule above — the ISO filename exists precisely so a directory of scans lists in
date order — and it is a deliberate choice made at explicit request rather than an
oversight. `scan_02-08-26` sorts next to `scan_02-09-25`, a folder from a different year;
changing `TIMESTAMP_DIR_FORMAT` in `csv_export.py` to `%y-%m-%d_%H%M%S` would restore the
ordering and change nothing else. The three formats and their three jobs:

| Where | Format | Why |
|---|---|---|
| Date **cells** in the file | `02-Aug-2026` | Excel renders an ISO date as a serial number |
| `--csv` **filename** | `scan_2026-08-02.csv` | A directory of scans lists in date order |
| `--csv-dir` **folder** | `scan_02-08-26_205134` | The order it was asked to be read in |

Two pairings are usage errors rather than silent behaviour. **`--csv-dir` with `--csv`, in
either form**, because one names a file and the other a directory: there is no way to honour
both, and silently preferring one would exit 0 having put the scan where nobody is looking.
**`--csv-dir` with `--append`**, because the folder was created a moment earlier and is
empty, so accepting the flag would imply a history is accumulating when every run starts a
new folder — `--csv PATH --append` is the growing log.

The created folder is announced before the files, all on stderr:

```
created /tmp/nsereports/scan_02-08-26_205134
wrote 62 rows to /tmp/nsereports/scan_02-08-26_205134/scan.csv
wrote 11 rows to /tmp/nsereports/scan_02-08-26_205134/scan_COILED.csv
```

## Architecture

```
stock_screener/
  SKILL.md        the contract Claude follows when the skill triggers
  engine.py       loads the shared scoring engine exactly once
  universe.py     universe parsing, sector filter, NSE constituent refresh
  setups.py       six setup predicates, fit scoring, confluence
  screener.py     parallel scan, ranking, rendering, CLI
  csv_export.py   long-format CSV export: self-describing headers, per-setup
                  split, timestamped per-run folders
  nifty500.txt    500 symbols with sectors, refreshable from NSE
  tests/          1367 tests

stock_analyser/   analyze.py (the scoring engine), levels.py (nine-method S/R)
watchlist_analyser/  watchlist.py (comparative scoring, relative strength)
stock_planner/    planner.py (stop and target zones for a held position)
```

Three constraints hold the design together:

1. **No indicator is ever reimplemented.** The screener reads fields from the engine's
   output; where it needs a series the engine returns as a scalar, tests pin the derived
   series to reproduce the engine exactly.
2. **The engine loads once.** Two separate loads would mean two fetch caches and twice the
   network traffic per scan.
3. **One bad ticker cannot abort a scan.** The fetch layer raises `SystemExit` on an
   unresolvable symbol, which `except Exception` does not catch — every worker catches
   `BaseException` and reports the failure instead.

## Data source

Yahoo Finance chart API, `.NS` suffix, 2 years of daily bars and 5 years of weekly per
symbol. A full 500-name scan issues ~1000 requests across 16 workers and completes in about
22 seconds.

**Note for anyone extending this:** TradingView's technical-analysis endpoints have no NSE
India coverage. They silently rewrite the exchange, return no data, and then report
`confidence: "HIGH"` on top of it. Quote lookups are fine; TA is not.

## Testing

```bash
cd stock_screener && python3 -m unittest discover -s tests
```

1367 tests, no third-party test runner. Beyond the usual coverage, the suite is
**mutation-verified**: for each assertion, a deliberately wrong implementation was patched
in and the test confirmed to fail. That practice exists because it caught things ordinary
testing did not — including a predicate that could never match while all of its tests
passed, and roughly a dozen assertions that were incapable of failing because their
fixtures were too uniform to distinguish two different algorithms.

If you add tests, the check that matters is watching the test **fail against wrong code**.
A green test proves nothing on its own.

> Running a mutation sweep? Use `PYTHONDONTWRITEBYTECODE=1 python3 -B` and clear
> `__pycache__` between mutants. Consecutive single-character mutants produce `.pyc` files
> of identical size within the same second, and Python's mtime+size invalidation then
> serves stale bytecode — silently mis-attributing which test killed which mutant.

## Known limitations

- **The volume floors are absolute, not percentiles of the day's universe.** On the tape
  they were calibrated against, 73% of the Nifty 500 clears 1.0 and 54% clears 1.25 — so
  they are moderate filters there. In a broad selloff the same fixed numbers could reject
  nearly everything, and an empty screen would then mean *"this threshold no longer suits
  the regime"* rather than *"no setups exist"*. Those are different findings and must not
  be confused; check the rejection funnel to tell them apart. A percentile floor would
  self-adjust, and was rejected because it would also manufacture matches every day,
  including days when the honest answer is that nothing is under accumulation.
- **Strict COILED currently matches very few names.** It is satisfiable but tight; most
  candidates die at the volatility percentile or the 3-of-3 contraction requirement.
- **The ₹3 crore liquidity floor is inert on the Nifty 500**, where the thinnest constituent
  trades well above it. It only starts filtering if you widen the universe.
- **The constituent list goes stale.** NSE reshuffles the index twice a year;
  `--refresh-universe` re-pulls it.
- **Fundamentals are out of scope.** This is a technical framework. Earnings quality,
  valuation and balance-sheet risk are not modelled anywhere.

## Requirements

Python 3.9+. No dependencies. Claude Code is optional — every script runs standalone from
the command line.

## Disclaimer

**This is mechanical framework output, not investment advice.** It applies fixed rules to
public price data and reports what they produce. It does not know your circumstances, risk
tolerance, tax position or time horizon, and it has no view on whether any business is
worth owning.

A `BUY NOW` label means "passes the mechanical gate at a neutral catalyst" — nothing more.
Every number here is derived from price and volume history, which describes what has
already happened. Do your own research and consider a licensed adviser before risking
capital.

## Licence

MIT
