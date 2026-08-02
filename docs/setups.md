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

## Volume confirmation, and why each setup asks a different question

Every setup carries a volume test, and they are deliberately **not the same test wearing
five labels**. The setups sit at different points of one life cycle, and "healthy volume"
means something different at each.

The measure most of them use is O'Neil's **up/down volume ratio**: volume on up-closes
divided by volume on down-closes over the last 50 sessions. Above 1.0 means more money
changed hands on days the stock rose than on days it fell — net accumulation. Direction is
measured *settle to settle*, not against the bar's own open: a bar can open down and close
up and still be a down day.

| Setup | Volume test | Loosened | Strict |
|---|---|---|---|
| **COILED** | up-thrusts in the last ~126 sessions | ≥ **1** | ≥ **2** |
| **BREAKOUT** | *(none — it already gates the breakout bar at 1.5–2.0× average)* | — | — |
| **LEADER** | up/down volume ratio | ≥ **1.25** | ≥ **1.50** |
| **PULLBACK** | retracement volume ÷ advance volume | ≤ **0.90** | ≤ **0.75** |
| **TURN** | up/down volume ratio | ≥ **1.25** | ≥ **1.50** |

**Why these were added.** The setups previously used volume *negatively* — "no down-thrust
in the last 10 bars" — and never asked any name for positive evidence that somebody was
buying it. Measured across the live Nifty 500 the median up/down ratio was **1.33 for the
universe and 1.34 for LEADER matches**: the setup that selects stocks near 52-week highs
with positive relative strength had no volume edge over the tape at all. PULLBACK was worse
in a subtler way — its median match retraced on **0.88×** the volume of its own advance, so
half the list was "resting" on very nearly the participation that drove the move up. That is
supply, not rest.

**Why COILED counts thrusts instead.** A base has no current demand by definition — that is
what a base *is* — so demanding a healthy up/down ratio would reject every genuine coil.
Worse, everything else COILED tests is satisfied by a stock nobody trades: the range narrows
because there is no participation, volatility falls to the bottom of its own history because
nothing happens, and the dry-up gate rewards exactly that. What a base *can* be asked is
whether anyone ever took real size in it. A base with no prior accumulation is a dead stock,
not a coiled spring.

**Why TURN is not gated on volume expansion.** The obvious candidate was the existing
"volume since the cross vs. the 50 bars before it" figure. It was rejected as a gate because
its answer depends on the **age of the cross**, not on demand: a cross 30–40 bars old has
long since normalised and reads about 1.0 however strong the buying, while a three-bar-old
cross reads high off three noisy sessions. Gating on it would reject older crosses for being
old and call it weak volume — and TURN already has a cross-recency threshold that says so
honestly. It remains a Fit component, where a soft input belongs.

**When a measurement cannot be made, the gate closes.** A stock with no down-volume at all
in 50 sessions has no ratio; a pullback whose swing high is not in the aligned bars has no
legs to compare. In every such case the name is **rejected**, never passed. A gate that
opens whenever its input is unavailable is decorative.

### These thresholds are absolute, and that is a trade-off

The floors above are fixed numbers, not percentiles of the day's universe. On the tape they
were calibrated against, **73% of the Nifty 500 clears 1.0 and 54% clears 1.25** — so they
are moderate filters, not aggressive ones.

**In a broad selloff the same numbers could reject nearly everything.** If a scan comes back
empty in a falling market, the honest reading is *"this threshold no longer suits the
regime"* — not *"no setups exist"*. Check the rejection funnel: if most names are dying at
the volume gate, that is the market being distributed, and the screen is describing it
correctly even though the output is unhelpful.

A percentile floor would self-adjust to the regime. It was rejected because it would also
manufacture matches every single day, including days when the honest answer is that nothing
is under accumulation — and a screen that always returns something is a screen that has
stopped being evidence.

### The ratio cannot see inside the bar — `ud_weighted`

`ud_ratio` classifies an entire session on one comparison: this close against *yesterday's*
close. That is the right question only if the close is the whole story of the day, and often
it is not. A stock can close +0.1% having traded at its low all afternoon, and the ratio books
the whole day's volume as accumulation. Nothing in the measure can tell that day apart from
one that closed on its high.

On the live universe the gap is not marginal:

| Symbol | `ud_ratio` | close-weighted |
|---|---|---|
| **CONCORDBIO** | 3.74 | **0.59** |
| **LALPATHLAB** | 2.71 | **0.39** |
| **HYUNDAI** | 2.86 | **0.63** |

Three names the 50-day ratio calls strong accumulation — and all three are handing their
closes back.

**`ud_weighted` changes the weighting, not the window.** Same 50 sessions and the same volume,
but each bar is scored by where it closed *within its own range*, using Chaikin's money-flow
multiplier:

```
m = ((Close − Low) − (High − Close)) / (High − Low)
```

`m` is **+1** when the close is on the high, **−1** on the low and **0** at the midpoint, and
each bar contributes `volume × m` rather than casting its full volume for whichever side won
by a rupee. A mid-range close is then recorded as what it was — indecisive — instead of as a
full day of conviction.

**Two real CONCORDBIO sessions, where the two measures disagree in opposite directions:**

| | 17 Jul | 27 Jul |
|---|---|---|
| High / Low / Close | 1352.7 / 1309.2 / 1342.8 | 1275.3 / 1244.5 / 1256.4 |
| Previous close | 1346.0 | 1248.5 |
| Settle to settle | **−3.2 — a down day** | **+7.9 — an up day** |
| Close within its own bar | **77% up** | **39% up** |
| `ud_ratio` books the day as | selling | buying |
| `m` | **+0.54** | **−0.23** |

On 17 July the stock was pushed down to 1309 and buyers dragged it back to within ten rupees
of the high. It settled 3.2 below the previous close, so `ud_ratio` counts the entire day as
distribution; the weighted reading is +0.54, accumulation. On 27 July it rallied to 1275 and
gave nearly all of it back, closing 7.9 up on the day — `ud_ratio` counts the whole session
as buying, while the weighted reading is −0.23, distribution. In both cases the weighted
number is the one describing what actually happened inside the session.

**Neither ratio replaces the other; the pair is the measure.** Read together they answer two
different questions — *is price closing higher than it was* and *is it closing strong within
its own range* — and the interesting cases are the ones where the answers differ:

| | Meaning |
|---|---|
| **Both high** | Genuine accumulation — price rising and closing strong |
| **U/D high, weighted low** | Price drifts up, but sellers control the close. Institutional supply being distributed into strength |
| **U/D low, weighted high** | Price soft, but buyers defend every dip — often a base forming |
| **Both low** | Distribution, unambiguously |

"High" and "low" are `ud_ratio` at **1.25** — the same floor LEADER and TURN gate on, so the
signal and the gates cut the tape in the same place — and `ud_weighted` at **1.0**, which on a
ratio of two volume buckets is simply parity.

The four readings are emitted as **`volume_signal`**, labelled `accumulation` /
`distribution-into-strength` / `supported` / `distribution`. A fifth value, `unknown`, means
there was not enough volume history to classify the name — it is a real finding and prints as
that word, not as a blank or a neutral middle.

**The second row is why the measure exists.** It is the case the screener previously could not
see at all: every price condition satisfied, a 50-day up/down ratio in the top decile, and
supply being fed into the advance one strong-looking close at a time. CONCORDBIO, LALPATHLAB
and HYUNDAI above are all that row. On the old measure they were the best-looking names on the
list.

### 50 sessions, all weighted equally — `ud_20` and `accumulation_trend`

The second blind spot is chronological. A 50-bar window treats a bar from ten weeks ago
exactly like yesterday's, so a stock that was accumulated hard for 40 sessions and has been
distributed for the last 10 scores identically to one being accumulated right now. The number
is accurate and out of date at the same time.

**`ud_20` is the same ratio over 20 bars**, and comparing it against the 50-day gives
**`accumulation_trend`** — whether the buying is still going on or is something that already
happened. Live examples:

| Symbol | 50-day | 20-day | Reading |
|---|---|---|---|
| **VIJAYA** | 1.70 | 0.52 | `reversed` — accumulation stopped and turned |
| **CONCORDBIO** | 3.74 | 1.18 | `fading` |
| **BHARATFORG** | 2.05 | 1.06 | `fading` |

The label is read off the 20-day as a **fraction of the 50-day**: above **1.30** is
`strengthening`, the near window carrying the number; **0.90–1.30** is `steady`, a band that
wide because the 20 bars *are* 20 of the 50 and two overlapping windows of the same tape can
never be independent; **0.70–0.90** is `flattening`; below **0.70** is `fading`. `reversed` is
tested first and is the strictly stronger statement: the same sub-0.70 drop, plus a 20-day
ratio that has crossed **below 1.0** outright — not merely less accumulation, but distribution.
`unknown` means one of the two ratios could not be measured. VIJAYA is the clearest case: a perfectly respectable 1.70 on the window the gates read, and a recent month
in which more volume has moved it down than up. The 50-day number is not wrong — it is a fair
description of a period that has ended.

### How the two measures are used

**As a gate, deliberately conservative.** A setup fails only when `ud_weighted < 1.0` **and**
`ud_20 < 1.0` — the close-weighted reading and the recent window both saying the stock is
being distributed *now*. Either one alone is a caution, not a finding: a weighted ratio below
1.0 on its own can be a month of thin, mid-range drift, and a soft 20-day on its own can be a
normal pause inside a healthy trend. Two independent measurements agreeing is a different
class of evidence from one, and only that case is excluded. A `distribution-into-strength`
name therefore still matches and is still reported — with its label attached, so the reader
weighs it. Hiding it would trade one blind spot for another.

**As a ranking input.** Both feed the shared **accumulation** component of Setup Fit, so they
order the list as well as filter it — a name closing strong sits above one closing weak even
when both cleared the gate.

**In the output.** Three terminal columns — `Up/Down Volume Ratio`, `Volume Signal` and
`Accumulation Trend` — and five CSV columns: `up_down_volume_ratio_50d`,
`close_weighted_volume_ratio_50d`, `up_down_volume_ratio_20d`, `volume_signal_reading` and
`accumulation_trend_reading`. The CSV names are longer than the terminal labels on purpose:
a header has to state the measurement and its unit without the reader consulting this
document.

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
| Volume — dry-up | 20-day average below 50-day average | ratio < 0.9 |
| **Volume — accumulation** | ≥ **1** up-thrust in the last ~126 sessions | ≥ **2** |

The base is split into **four equal windows** of at least 4 bars each, giving three
consecutive comparisons. The net-contraction rule exists because a base can narrow twice
and then blow out again — without it, a stock whose last window is *wider* than its first
still qualified, which is not a coil by any definition.

**The two volume rules pull in opposite directions on purpose.** Dry-up asks whether volume
is quiet *now*, which is what makes a base a base. The up-thrust count asks whether the
stock was ever *bought*, which is what makes the base worth watching. A dead stock passes
the first and fails the second, and before the second existed it could lead the table. The
thrust direction is read off the engine's own label, so a name that only ever traded size on
the way *down* has been distributed, not accumulated, and does not qualify. Strict asks for
two, because a single thrust can be an index rebalance or a block crossing.

**Evidence columns:** `Contraction` (last window ÷ first — lower is tighter) and
`Position in Base` (%).

**Setup Fit:** contraction 35% · position in base 25% · dry-up 20% · accumulation 20%.

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

**BREAKOUT is the one setup with no up/down volume gate**, and that is not an oversight.
The breakout bar's own volume multiple is the most direct volume evidence any of these five
setups has — a name that cleared its base on 2× average did not do it quietly, whatever a
trailing 50-session ratio says. Adding a second volume floor on top would reject genuine
breakouts out of bases that were, correctly, quiet.

**Evidence columns:** `Volume (multiple of average 20-day)` and `Percent Above Base High`.

**Setup Fit:** volume multiple 35% · freshness 25% · base quality 20% · accumulation 20%.
The accumulation term is here even though the gate is not: it costs a breakout nothing to
also be under accumulation, and between two otherwise identical breakouts the one being
accumulated is the better row.

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
| **Volume — accumulation** | up/down volume ratio ≥ **1.25** | ≥ **1.50** |

The 1-month floor of −2pp deliberately tolerates a shallow recent breather. A genuine
leader resting for a fortnight should not drop out of the screen; one actively being sold
should.

**Why a leader is asked for the up/down ratio.** This is the one setup whose entire claim
is that somebody with size is buying the stock — that is what "leadership" means, and
everything else in the table is a consequence rather than the thing itself. Proximity to
the 52-week high, a clean average stack and positive relative strength are all satisfied by
a name drifting up on nobody's participation, and the distribution test above only asks
that nothing violent happened in ten sessions. Measured on the live universe that is
exactly what the setup was doing: median up/down ratio **1.34 against a universe median of
1.33** — a price screen wearing a volume screen's reputation. The ratio is the direct
question, asked over the same 50 sessions for every name, and 1.25 is not a demanding
answer for a stock that is supposed to be leading.

**Evidence columns:** `Percent From 52-Week High` and `Relative Strength (1-month)`.

**Setup Fit:** relative strength 3-month 35% · proximity to the high 30% · stack
completeness 15% · accumulation 20%. Every name reaching Fit has already cleared 1.25 and
so scores at least 6 on the accumulation term — the term still earns its weight, because
the gate cannot tell 1.26 from 3.0 and on this setup that is precisely the distinction the
ranking should show.

**Ranked by Score Now**, tie-broken on 3-month relative strength.

**What it will not catch:** the leader *before* it leads. By construction this setup
requires the outperformance to already exist, so it is always somewhat late. TURN is the
early version of the same idea.

---

## PULLBACK — an uptrend resting, and turning back up

**What it looks for:** a stock in an intact uptrend that has genuinely retraced from a
recent swing high, come back to support — its 20- or 50-day average, or a structural
support zone — and then printed a bar showing the retracement is *ending*: it reached that
support, closed back above it, and closed in the top of its own range.

**Why it works.** This is the setup with the best risk-reward arithmetic available, because
it is the only one where you buy *into* weakness inside strength. Support is close, so the
stop is tight; the prior high is a natural target, so reward is defined. The other setups
mostly ask you to buy strength, which means a wider stop by construction.

But that arithmetic only holds if the pullback is over. Buying a stock still falling into
support gets you the tight stop and the falling stock — the stop is close precisely because
the level is close, and price is heading through it. So the setup no longer asks only
"has this stock come back to support"; it asks **"has it come back to support and started
to turn"**. The reversal bar is the evidence. A hammer at the 50-day, a close in the upper
half of a wide range, a level reclaimed after being probed — those are a seller exhausted
and a buyer showing up, on the same bar, at the level that matters. Without one, the two
facts the old version relied on (near an average, momentum cooled) are equally true of a
stock on its way down through both.

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
| **Retracement** | **≥ 3%** below the highest of the last 5 swing highs | **≥ 5%** |
| **Reversal — tested** | bar low within **0.25× ATR** of a support level | **0.10× ATR** |
| **Reversal — reclaimed** | bar close above **that same** level | same |
| **Reversal — closed strong** | close in the top **50%** of the bar's range | top **40%** |
| **Reversal — recency** | the last closed bar **or the one before it** | last closed bar only |
| Momentum | RSI 38–62 | RSI 40–58 |
| Volume — dry-up | 20-day average / 50-day average < 1.1 | < 1.0 |
| Distribution | no down-thrust in last 8 bars | 10 bars |
| **Volume — the retracement** | pullback volume ÷ advance volume ≤ **0.90** | ≤ **0.75** |

**Both new conditions exist because of real failures, measured on live data.**

*Nothing required a retracement.* MARICO sat 0.3% under its swing high and matched — it had
gone sideways while its 20-day average rose *into* it, which satisfies "within 3% of the
20-day" without a retracement ever happening. NH matched at 1.0%. The swing-high guard that
would have caught them applies to the support arm alone, and neither of them entered
through it; the minimum-retracement gate now applies to **both** arms.

*Nothing required buyers.* NH closed at 22% of its daily range that day and MARICO at 13% —
near the low, which is the signature of a stock still falling. Meanwhile CEMPRO, 17.1% off
its swing high, printed a textbook hammer with a lower wick nearly sixteen times its body
and closed at 74% of its range. The screen ranked all four the same way. It now separates
them: on the day this landed, the loosened screen went from 78 names to 40, CEMPRO and
AJANTPHARM survived, NH and MARICO did not.

**All three reversal conditions must hold on the same level.** A low that reached the
50-day and a close that cleared the 20-day is not a rejection of anything — it is two
unrelated facts about one bar.

**The reversal bar may be the one before last.** A turn is often confirmed by a quiet inside
day, and demanding the hammer itself be the final bar throws away the second day of every
genuine reversal. CEMPRO is the case: its hammer was the 30th, and the 31st closed strong
without reaching back to the 50-day. Strict takes the last closed bar alone.

**Why the volume test here compares two legs rather than reading a ratio.** A pullback is
the one stage of the life cycle where the *right* answer is quiet volume: holders sitting
still while price comes back to support is what "resting" looks like, and an up/down ratio
would ask this setup for the accumulation it is by definition not showing this week. The
question that does belong here is comparative — is the retracement drawing less
participation than the advance it retraces? So the screen averages volume over the **30
bars before the swing high** (the advance) and over the **pivot bar to the last closed one**
(the pullback), and divides. The pivot belongs to the pullback leg: it is the bar that
printed the high, and when its print is a climax, counting it against the pullback makes
the gate harder to pass, which is the safe direction for a gate that exists to demand
evidence. Either leg shorter than 5 bars, or a swing high not found in the aligned bars,
makes the ratio unmeasurable — and the name is rejected.

Neither existing volume rule could ask this. Dry-up compares a 20-day average against a
50-day one, which is a statement about the last month that knows nothing about where the
pullback began; the down-thrust test only asks that no single bar exceeded 2.5× average. A
stock can retrace on steady heavy volume for a fortnight and pass both, and the median
match did: **0.88×** the volume of its own advance. Half the list was resting on very nearly
the participation that drove the move up, which is supply, not rest.

**Evidence columns:** `Close Position in Reversal Bar` and `Percent Below Recent Swing
High`. Distance-to-average and RSI used to sit here; both are already inside the entry
gate, and neither could separate a name that turned at support from one falling into it.

**Setup Fit:** distance to the average 30% · RSI near 50 20% · pullback-versus-advance
volume 25% · retracement depth 15% · accumulation 10%. The blunt `dryup` term this setup
used to score is **replaced**, not merely outweighed — both claimed to measure "is this
retracement quiet", and keeping the pair would have scored one idea twice while giving the
worse measurement half the credit. Dry-up remains a live *gate*, and its number stays in
the evidence so a reader can still see what let a name through. Accumulation carries the
smallest weight of the five setups here, at 10%: PULLBACK already spends 25% on a volume
term of its own, and the up/down ratio on this setup describes the trend the pullback
interrupts rather than the pullback itself.

**Expect a short list.** Most dips do not end on the day you look at them, so PULLBACK is
now the narrowest of the five setups by some margin. A short list is the gate working.

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
| **Volume — accumulation** | up/down volume ratio ≥ **1.25** | ≥ **1.50** |

**A new trend nobody is accumulating is a moving average crossing, not a turn.** Every
other condition in that table is price or price-derived: two averages, their order, a
histogram, an RSI, a distance off the low. A stock can produce all of it by drifting up on
no participation at all — which is precisely what a golden cross *is* when it is an
artifact of the 200-day flattening rather than of demand, and the distance-from-low test
was the only thing standing between the screen and that name. The up/down ratio asks
directly whether anyone has been buying the days.

**It is deliberately not gated on `vol_expansion`** — the volume-since-the-cross figure —
even though that measure is already computed and looks like the obvious candidate. See
*Volume confirmation* above: its answer tracks the age of the cross rather than the
strength of demand, so gating on it would reject older crosses for being old and call it
weak volume. It stays a Fit component, where a soft input belongs.

**Evidence columns:** `Bars Since Cross` and `MACD Histogram`.

**Setup Fit:** cross recency 30% · 200-day slope 25% · volume expansion 15% · MACD 10% ·
accumulation 20%. Volume expansion and accumulation are both here and they are not
redundant: expansion is anchored to the cross and decays as the cross ages, while the
up/down ratio is a fixed 50-bar window that answers "who is winning the days" regardless of
when the cross happened. That decay is why expansion is a Fit component and never a gate,
and why it now carries less weight than the measure that does not decay.

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

**Since Fit now carries an accumulation term, CONFLUENCE ordering has changed.** The tie
inside a match-count group breaks on mean Setup Fit, and every constituent Fit moved when
the weights were rebalanced — so two names that used to sit in a given order can now sit in
the other one on the strength of their up/down ratio alone. The ratio is a property of the
symbol rather than of any one setup, so a CONFLUENCE row copies the identical figure its
constituent rows print; a column that disagreed with its own inputs would be worse than no
column.

---

## Reading the output

### Setup Fit is setup-relative

Fit answers "how textbook is this instance of *this* setup" — base tightness and dry-up for
COILED, volume multiple and freshness for BREAKOUT. **An 8 for COILED and an 8 for PULLBACK
are different measurements.** Never compare Fit across tables.

All five formulas now share one **accumulation** term, fed by the up/down volume ratio and by
the two measures that qualify it — `ud_weighted` and `ud_20` — and scored from the ratio on a
single band (≥2.50 → 10 · 2.00–2.50 → 9 · 1.50–2.00 → 8 · 1.25–1.50 → 6 · 1.00–1.25 →
4 · below 1.00 → 2), so that "accumulation" means the same thing in every table even though
the Fit it feeds does not. An unmeasurable ratio scores the same floor as a distributing
one: a score that rewarded the *absence* of evidence would rank an unmeasured name above a
measured one. The term was not bolted on top — every other weight came down to make room,
so a Fit is still out of 10, comparable with yesterday's in kind if not in value.

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

### The Up/Down Volume Ratio column

Every table carries `Up/Down Volume Ratio`, CONFLUENCE included, and the CSV carries it as
`up_down_volume_ratio_50d` immediately after
`relative_strength_3month_vs_nifty50_pct_points`. It is a
**base column, not evidence**: like Risk:Reward and relative strength it is one number
meaning one thing for every name, rather than one of the two setup-specific facts each
table reports.

It is shown **whether or not it gated**. LEADER and TURN reject on it, so their columns can
never read below their floor; COILED, BREAKOUT and PULLBACK do not, so theirs can read
anything — and on those tables it is the most useful number in the row, because it is the
one fact the setup did not test.

**Below 1.0 means the price chart and the volume disagree.** More money changed hands
pushing the stock down than pushing it up, on a name that nonetheless cleared a bullish
setup's every price condition. That is not automatically disqualifying — a coil is supposed
to be quiet and a pullback is supposed to be sold — but it is the thing to check before
acting on the row.

It reads `-` when the ratio could not be measured: no down-closes in the window to divide
by, which in practice means the series is too short or too flat to judge. A dash is not a
1.00 and must not be read as one.

`BUY NOW` · `BUY HALF` · `ALERT` (vetoed today, but the trigger repairs it) · `LATENT`
(below the bands today, but a breakout would qualify it) · `WATCH` (matches the setup,
neither buyable nor repaired by its trigger).

These reuse `watchlist_analyser`'s vocabulary so the two skills stay mutually legible.
**A `BUY NOW` means "passes the mechanical gate at a neutral catalyst" — not "buy this".**

### `Volume Signal` and `Accumulation Trend` sit beside it

The ratio no longer travels alone. Two further base columns qualify it on every table:
**`Volume Signal`** — `accumulation` / `distribution-into-strength` / `supported` /
`distribution`, the four-way reading of the raw ratio against the close-weighted one — and
**`Accumulation Trend`**, the 20-day ratio against the 50-day as `strengthening` / `steady` /
`flattening` / `fading` / `reversed`. Either can read `unknown`, which means the history was
too short to classify — a stated finding, distinct from the `-` a cell prints when its
producer had nothing to say at all.

They are there because a single ratio can be true and misleading at once. A 3.74 with a
`distribution-into-strength` signal and a `fading` trend is not the same row as a 3.74
without them, and before these columns existed the two were indistinguishable on screen.

**`distribution-into-strength` is the label to stop on.** It means the price chart and the
volume disagree while the price chart still looks strong — the same disagreement a sub-1.0
ratio makes obvious, wearing a good number instead. The name still matched its setup; it has
earned a closer look, not a position.

In the CSV the same information arrives as five columns rather than three, because the file
keeps the numbers the labels were derived from: `up_down_volume_ratio_50d`,
`close_weighted_volume_ratio_50d`, `up_down_volume_ratio_20d`, `volume_signal_reading`,
`accumulation_trend_reading`. That takes it **from 27 columns to 31**.

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

### Where the scan is written

Three flags name a destination, and they are three different answers to "what happens to
yesterday's scan".

| Flag | Writes | Yesterday's scan |
|---|---|---|
| `--csv` | `./scans/scan_<date>.csv`, or the path you give it | Overwritten, unless the date in the default name has changed |
| `--csv PATH --append` | The same file, rows added, header written once | Kept, in the same file |
| `--csv-dir DIR` | `DIR/scan_<dd-mm-yy>_<HHMMSS>/scan.csv` | Kept, in its own folder |

`--csv-per-setup` composes with any of them and *also* writes one file per setup that
matched — `scan_<date>_COILED.csv` under `--csv`, `scan_COILED.csv` inside a `--csv-dir`
folder. A setup that matched nothing writes no file at all; the combined file is written
even when nothing matched anywhere, because a scan that found nothing is itself a finding
and needs a headed, parseable file to say so.

`--csv-dir` creates `DIR` and any missing parents, then a new subfolder for this run:

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

The **seconds** in the folder name are load-bearing, not decoration: without them two scans
in the same minute resolve to one folder and the second writes over the first, with no error
raised and no way to tell afterwards which of the two the folder holds.

The folder name is `dd-mm-yy`, so a listing of these folders **does not sort
chronologically** — `scan_02-08-26` sorts next to `scan_02-09-25`, a folder from a different
year. That inverts the rule the CSV *filename* follows, where ISO is used precisely so a
directory of scans lists in date order, and it is a deliberate choice made at explicit
request rather than an inconsistency nobody noticed. Changing `TIMESTAMP_DIR_FORMAT` in
`csv_export.py` to `%y-%m-%d_%H%M%S` would restore the ordering and change nothing else.
Three formats, three jobs:

| Where | Format | Why |
|---|---|---|
| Date **cells** in the file | `02-Aug-2026` | Excel renders an ISO date as a serial number |
| `--csv` **filename** | `scan_2026-08-02.csv` | A directory of scans lists in date order |
| `--csv-dir` **folder** | `scan_02-08-26_205134` | The order it was asked to be read in |

Two pairings stop with a usage error rather than doing something surprising:

- **`--csv-dir` together with `--csv`**, in either of `--csv`'s forms. One names a file and
  the other names a directory, so there is no way to honour both — and silently preferring
  one would exit 0 having written the scan somewhere the user is not looking. `--csv-dir`
  needs no `--csv`; it satisfies `--csv-per-setup` on its own.
- **`--csv-dir` together with `--append`**. The folder was created seconds earlier and is
  empty, so there is nothing inside it to append to. Accepting the flag would suggest a
  history is accumulating when in fact every run starts a new folder. `--csv PATH --append`
  is the flag pair that keeps one growing file.

If `DIR` exists as a file rather than a directory the run stops before the scan, with a
message naming the path — `--csv-dir scan.csv` is the plausible typo, and an errno from inside the directory
creation would name a path built from the timestamp rather than the argument that was typed.

The created folder is printed before the per-file lines, and all of them go to stderr so
`--json` on stdout stays parseable:

```
created /tmp/nsereports/scan_02-08-26_205134
wrote 62 rows to /tmp/nsereports/scan_02-08-26_205134/scan.csv
wrote 11 rows to /tmp/nsereports/scan_02-08-26_205134/scan_COILED.csv
```
