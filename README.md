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

| Skill | Use it when | Produces |
|---|---|---|
| **stock_screener** | You want candidates and have no names in mind | Ranked tables for six bullish setups across the Nifty 500 |
| **watchlist_analyser** | You have 2+ tickers to compare | Comparative table, relative strength vs Nifty 50, "score if the trigger fires" |
| **stock_analyser** | You have one ticker | Levels, weighted score, entry setups with R:R, position sizing, scenario tree |
| **stock_planner** | You already hold the stock | Stop and target zones from nine independent methods, clustered by confluence |

They share one scoring engine. `stock_screener` and `watchlist_analyser` both import
`stock_analyser/analyze.py` rather than reimplementing it, so **the same stock never carries
two different scores** — a test asserts equality to nine decimal places.

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
| **PULLBACK** | An established uptrend resting into support | Score Now |
| **TURN** | The early part of a confirmed new trend | Score at Trigger |
| **CONFLUENCE** | Names matching two or more of the above | Match count |

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

### Screener scores are catalyst-neutral

Catalyst needs a news search per name, which is not feasible across 500 stocks, so every
scanned name sits at the neutral default of 5.0. A screener score will therefore differ
slightly from `watchlist_analyser`'s for the same stock once real catalysts are set.

That gap is not an inconsistency — it is why the handoff exists. The screener produces
candidates; adjudication happens one level down.

### An empty screen is a finding

When nothing matches, the output names the condition that rejected the field rather than
reporting a bare zero. The screener will not pad a list to fill 15 rows.

## Architecture

```
stock_screener/
  SKILL.md        the contract Claude follows when the skill triggers
  engine.py       loads the shared scoring engine exactly once
  universe.py     universe parsing, sector filter, NSE constituent refresh
  setups.py       six setup predicates, fit scoring, confluence
  screener.py     parallel scan, ranking, rendering, CLI
  nifty500.txt    500 symbols with sectors, refreshable from NSE
  tests/          764 tests

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

764 tests, no third-party test runner. Beyond the usual coverage, the suite is
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
