# The six setups

Five of these are stages of a single bullish life cycle. That is the organising idea of
the whole screener, and it is why a stock appearing in two setups is signal rather than
double-counting:

```
COILED  ──────►  BREAKOUT  ──────►  LEADER
 a base            the base           the stock now
 tightening        gives way          leads the index

PULLBACK   re-entry into a trend that is already established
TURN       entry into a trend that has only just begun
```

A stock does not have to pass through every stage, and most never complete the sequence.
But knowing *which* stage a name is in tells you what to do with it: COILED and TURN are
alert candidates, BREAKOUT and PULLBACK are entry candidates, LEADER is a
position-you-should-already-own candidate.

Every setup is evaluated against the same 6-factor score from `stock_analyser`, so a stock
carries the same score everywhere it appears. What differs is the *entry condition* and the
*evidence* each setup reports.

Two thresholds columns appear throughout: **loosened** is the default, **strict** is
`--strict`. Strict is always a subset — anything matching strict must also match loosened,
and a test asserts this across the live universe.

---

## COILED — volatility contracting inside a base

**What it looks for:** a stock that has stopped moving. Range narrowing, volatility falling
toward the bottom of its own recent history, volume drying up, price holding in the upper
half of the base rather than sagging to the lows.

**Why it works.** A base is a negotiation between buyers and sellers, and a contracting
range means the negotiation is running out of participants. Sellers willing to hit bids at
these prices have been exhausted; the remaining holders want higher. Volatility is
mean-reverting, so a stock at the bottom of its own volatility range is closer to an
expansion than a stock in the middle of one. Whether that expansion resolves up or down is
what the trend filters are for — a coil above a rising 200-day average resolves upward far
more often than one below it.

**The tell that separates a real coil from a quiet drift** is position in the base. Price
in the upper half means the contraction is happening *near the highs* — buyers are
absorbing supply without needing a discount. A stock coiling at the lows of its base is
distributing, not accumulating.

| Condition | Loosened | Strict |
|---|---|---|
| Base length | ≥ 16 bars | ≥ 20 bars |
| Volatility | ATR% in bottom **third** of its own 6-month range | bottom **quarter** |
| Contraction | ≥ **2 of 3** window-to-window comparisons tighter | **3 of 3** |
| Net contraction | last window **must** be tighter than the first | same |
| Position in base | ≥ 50% | ≥ 60% |
| Trend | above 50-day and 200-day, 200-day rising | plus 50-day rising |
| Volume | 20-day average below 50-day average | ratio < 0.9 |

The base is split into **four equal windows** of at least 4 bars each, giving three
consecutive comparisons. The net-contraction rule exists because a base can narrow twice
and then blow out again — without it, a stock whose last window is *wider* than its first
still qualified, which is not a coil by any definition.

**Evidence columns:** `Contraction` (last window ÷ first — lower is tighter) and
`Position in Base` (%).

**Ranked by Score at Trigger**, not today's score. The point of a coil is what happens when
it fires, so ranking on the current entry location would bury the best setups.

**What it will not catch:** a stock that gaps out of a base without contracting first. Fast
moves off news skip this stage entirely — that is what BREAKOUT is for.

---

## BREAKOUT — the base gives way, on volume

**What it looks for:** a close above the high of the base *as that base stood before this
bar*, on volume meaningfully above average, in a stock that was already above its 200-day
average.

**Why it works.** A breakout on volume is the only price event that reliably tells you
something changed. Price alone can drift through a level on nobody's participation and fall
straight back; volume is the evidence that the move required real buyers to take real size.
The base high is meaningful because it is where supply previously overwhelmed demand —
clearing it means the sellers who defended that level are done.

**The subtlety that makes or breaks this screen** is *which* base high you compare against.
The obvious implementation — compare today's close to the consolidation high — is
mathematically incapable of ever being true, because the consolidation range is computed
over a window that includes today, so the range high is always at least today's high.
This screener compares against the base **excluding the breakout bar**. Getting this wrong
produces a screener that silently matches nothing while all its tests pass.

| Condition | Loosened | Strict |
|---|---|---|
| Breakout | close above the prior base high (breakout bar excluded) | same |
| Base length | ≥ 12 bars | ≥ 15 bars |
| Volume | ≥ **1.5×** 20-day average (1.5–2.0× flagged **"light"**) | ≥ **2.0×** |
| Extension cap | ≤ **12%** above the base high | ≤ **8%** |
| Trend | above the 200-day average | above 50-day > 200-day |

**The extension cap is what makes this a breakout screen rather than a "has broken out"
screen.** Without it, every stock that broke out three weeks ago and has run 30% since
still qualifies — which is precisely the chase the risk-reward veto exists to prevent.

**The volume-light flag is not cosmetic.** `stock_analyser` defines a valid trigger as a
close *plus* ≥2× average volume. Screening from 1.5× surfaces useful near-misses, but
reporting one as a confirmed breakout would contradict the framework underneath. The row
says `light` so you can tell them apart.

**Evidence columns:** `Volume (multiple of average 20-day)` and `Percent Above Base High`.

**Ranked by Score Now** — the trigger has already fired, so today's location is the
relevant question.

---

## LEADER — already leading, near highs, not yet exhausted

**What it looks for:** a stock within 10% of its 52-week high, outperforming the Nifty 50
over three months, in a clean moving-average stack, with momentum strong but not vertical.

**Why it works.** Relative strength persists. A stock outperforming the index over a
quarter is more likely than a random name to keep doing so, because outperformance is
usually the market repricing something real — an earnings inflection, a margin shift, a
sector rotation — and repricings take longer than one quarter to complete. This is the one
setup where the *absence* of a discount is the point: you are paying up for demonstrated
strength.

**The failure mode this setup must defend against** is buying a leader at its most
extended. A stock can be a genuine leader and still be a terrible purchase on a given day
if it has just gone vertical. RSI alone does not catch this — a stock can sit at RSI 78
while calm, or at RSI 78 mid-blowoff — so the screener also tests volatility and recent
run.

| Condition | Loosened | Strict |
|---|---|---|
| Proximity to high | within **10%** of the 52-week high | within **5%** |
| Relative strength | 3-month > 0 and 1-month ≥ **−2pp** vs Nifty 50 | both > 0 |
| Trend | price > 50-day > 200-day, and price > 20-day | full 20 > 50 > 200 stack |
| Momentum | RSI 50–88 | RSI 55–85 |
| **Extension guard** | ATR% **not** in top decile of its own 6-month range | not in top 15% |
| **Extension guard** | run over last 5 sessions ≤ **10%** | ≤ **8%** |
| Distribution | no down-thrust on ≥2.5× volume in the last 10 bars | same |

The 1-month floor of −2pp deliberately tolerates a shallow recent breather. A genuine
leader resting for a fortnight should not drop out of the screen; one actively being sold
should.

**Evidence columns:** `Percent From 52-Week High` and `Relative Strength (1-month)`.

**Ranked by Score Now**, tie-broken on 3-month relative strength.

**What it will not catch:** the leader *before* it leads. By construction this setup
requires the outperformance to already exist, so it is always somewhat late. TURN is the
early version of the same idea.

---

## PULLBACK — an established uptrend resting

**What it looks for:** a stock in an intact uptrend that has retraced into support — either
to its 20- or 50-day average, or into a structural support zone — with momentum cooled and
volume drying up.

**Why it works.** This is the setup with the best risk-reward arithmetic available, because
it is the only one where you buy *into* weakness inside strength. Support is close, so the
stop is tight; the prior high is a natural target, so reward is defined. The other setups
mostly ask you to buy strength, which means a wider stop by construction.

**The condition that defines this setup — and that is deliberately not loosened — is that
the 200-day average must be rising.** That single test is what separates "a pullback in an
uptrend" from "a falling knife in a downtrend". Loosening it would not widen the screen; it
would change what the screen means. Every other threshold here has a strict and a loosened
value. This one does not.

| Condition | Loosened | Strict |
|---|---|---|
| Trend intact | price > 200-day, 50-day > 200-day, **200-day rising** | same |
| Retraced — either | within **3%** of the 20- or 50-day average | within **2%** |
| — or | within **1.2× ATR** of structural support | within **1.0× ATR** |
| Support-arm guard | **and** at least **1.0× ATR** below a recent swing high | **1.5× ATR** |
| Not broken | price above 50-day × 0.97 | same |
| Momentum | RSI 38–62 | RSI 40–58 |
| Volume | 20-day average / 50-day average < 1.1 | < 1.0 |
| Distribution | no down-thrust in last 8 bars | 10 bars |

**The swing-high guard on the support arm exists because of a real failure.** Without it, a
stock closing +4.3% at a *new high* qualified as a pullback — it was near a support zone
in absolute terms, and the support arm never checked whether the stock had actually pulled
back from anything. A pullback must have something to pull back from.

**Evidence columns:** `Distance to 20-Day or 50-Day Average` and `RSI (daily)`.

**Ranked by Score Now.** This is the setup where location scores well and the risk-reward
veto most often passes, so today's score is genuinely informative here.

---

## TURN — a brand-new trend

**What it looks for:** a stock whose 50-day average has recently crossed above its 200-day,
trading above both, with positive momentum, and far enough off its 52-week low that the
move is a trend change rather than a bounce.

**Why it works.** The golden cross is a lagging signal — by the time it fires the move is
well underway — but that lag is exactly what filters out the noise. A 50/200 crossover
requires roughly a quarter of sustained strength to occur at all, so it does not trigger on
a two-week bounce. What you are buying is the early part of a *confirmed* trend rather than
the speculative part of an unconfirmed one.

**The distance-from-low test is what makes this a turn rather than a dead-cat bounce.** A
cross that happens while price is still hugging its 52-week low is an artifact of a
flattening average, not evidence of demand.

| Condition | Loosened | Strict |
|---|---|---|
| Golden cross | 50-day crossed above 200-day within **45 bars** | within **30 bars** |
| Position | above both the 50-day and 200-day | same |
| Momentum | MACD histogram > 0 and RSI > **48** | RSI > **50** |
| Off the low | ≥ **12%** above the 52-week low | ≥ **20%** |

**Evidence columns:** `Bars Since Cross` and `MACD Histogram`.

**Ranked by Score at Trigger**, like COILED — a fresh trend is usually mid-base, so the
projection is more informative than today's location.

**Read the `Bars Since Cross` column carefully.** A cross 3 bars old and a cross 41 bars old
are different propositions wearing the same label. The Setup Fit score weights recency
heavily, but the raw number is right there in the table.

---

## CONFLUENCE — two or more at once

**What it looks for:** names matching **two or more** of the five setups, ranked by how
many.

**Why it matters.** Because the setups are stages of one life cycle rather than independent
filters, overlap is meaningful. A stock that is both COILED and LEADER is coiling *directly
under its 52-week high while outperforming the index* — a far more specific claim than
either setup makes alone.

**The pair that matters most is COILED+BREAKOUT**, the classic volatility-contraction
breakout: a base that tightened right up to the close that cleared it. This is the
`COILED → BREAKOUT` arrow happening on a single bar, and it is the strongest configuration
the screen can produce.

**BREAKOUT+PULLBACK is structurally impossible** and the engine asserts it. Price cannot be
above the prior base high and simultaneously retraced to the 20- or 50-day average. If it
is ever reported, that is a bug in a predicate, not a rare market event.

**Evidence columns:** `Setups Matched` (e.g. `COILED+LEADER`) and `Mean Setup Fit`.

**Ranked by** match count first, then mean Setup Fit, then Score Now, then 3-month relative
strength. The matched-setup label is shown rather than folded into a hidden weighting,
because a 2-way `COILED+LEADER` and a 2-way `COILED+PULLBACK` are worth different things
and you should be able to see which you have.

---

## Reading the output

### Setup Fit is setup-relative

Fit answers "how textbook is this instance of *this* setup" — base tightness and dry-up for
COILED, volume multiple and freshness for BREAKOUT. **An 8 for COILED and an 8 for PULLBACK
are different measurements.** Never compare Fit across tables.

Fit is a column, not the sort key. A pristine pattern in a weak stock should not outrank a
good pattern in a strong one.

### The risk-reward veto

Any name whose reward-to-risk at the current price falls below 1.5:1 — measured to the
nearest real resistance, against a stop 1.5× ATR away — is marked `*` and sorted **below
every clean name**, regardless of score.

This is the single most important mechanic in the framework. A stock can have a flawless
chart and still be un-buyable today because the nearest resistance is closer than the
nearest viable stop. Trend and entry price are two separate questions, and conflating them
is the failure the whole system exists to prevent.

Vetoed names are kept rather than dropped, with the price that would repair the setup —
a good chart you cannot buy today is information.

### Action labels

`BUY NOW` · `BUY HALF` · `ALERT` (vetoed today, but the trigger repairs it) · `LATENT`
(below the bands today, but a breakout would qualify it) · `WATCH` (matches the setup,
neither buyable nor repaired by its trigger).

These reuse `watchlist_analyser`'s vocabulary so the two skills stay mutually legible.
**A `BUY NOW` means "passes the mechanical gate at a neutral catalyst" — not "buy this".**

### Scores are catalyst-neutral

Catalyst is 10% of the weighted score and requires a news search per name, which is not
feasible across 500 stocks. Every scanned name is held at the neutral default of 5.0.

A screener score will therefore differ slightly from `watchlist_analyser`'s for the same
stock once real catalysts are set. That gap is not an inconsistency — it is the reason the
handoff exists.

### An empty screen is a finding

When nothing matches, the output names the condition that did the rejecting — "500 reached
a close above the base high, 500 failed" — rather than reporting a bare zero. A screen that
returns nothing is telling you what the market is doing.

The screener will not pad a list to fill 15 rows.
