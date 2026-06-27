# Market Intelligence Engine — Closed-Loop Upgrade

An upgrade of the original *Market Intelligence Engine* spec. The original is a
smart **open-loop recommender**: it watches the market and guesses what to do,
but never learns whether its advice worked. This version **closes the loop** — it
places small, deliberate bets, measures what actually happened, and gets better
every week, while exploring on purpose so it never fools itself.

---

## The one idea that changes everything

The original design **gives advice and never finds out if it was right.** That
single gap is why all its confident-looking scores (92, 84, 81…) are really just
guesses dressed up as maths — nothing ever checks them against reality, so the
system can't improve.

But closing the loop *naively* creates a famous failure mode: if you only ever
act on what the model already likes, you only ever get feedback on those things,
and the model goes blind everywhere else (a self-reinforcing **feedback trap**).

The fix is a **contextual bandit** (LinUCB). It mostly does what works
(*exploit*) but deliberately probes topics it is *uncertain* about (*explore*),
using the uncertainty itself to decide what's worth a probe. That keeps its eyes
open. Everything else here is built around that core.

---

## Proof it works (run `python simulate.py`)

The upgraded engine and a faithful re-implementation of the original spec compete
on the **same** synthetic market, same weekly budget, over 20 weeks:

| Policy | Real value captured | Junk pages built | Value / action |
|---|---|---|---|
| Original (static, fixed weights) | 26.10 | **19** | 0.435 |
| Closed-loop (this project) | **36.50** | **2** | **0.608** |

**+40% more real value, while building 17 fewer junk pages.**

The most striking result is what the engine *taught itself*. It learned this
weighting from outcomes alone:

```
semantic_gap            +0.299
news_relevance          +0.242
cross_source_agreement  +0.187
reddit_neg_sentiment    +0.147     <- reputation-risk signal, learned to value
trend_surprise          +0.114
trend_changepoint       +0.071
reddit_growth           -0.009
tiktok_velocity         -0.323     <- LEARNED to DISTRUST the loud bot channel
```

The original design *trusted* TikTok velocity at a fixed +0.15. The learner
discovered, with no hand-holding, that loud single-channel spikes predict
**wasted effort** — and drove its weight negative. See `results.png`.

> The world is synthetic and *designed* to contain the failure modes real
> markets have (bot-amplified hype, lagging search signals, under-served
> demand). It's a mechanism demonstration, not a benchmark on live data — but
> the **learning is real**: the bandit genuinely fits weights from outcomes, and
> the distrust of the hype channel was discovered, not programmed.

---

## What was upgraded, and why

| # | Original weakness | Upgrade in this repo |
|---|---|---|
| 1 | **Open loop** — never learns from outcomes | `bandit.py` + `store.py`: every executed action's result feeds back |
| 2 | **Hand-picked weights** (30/25/15/15/10/5) | LinUCB *learns* the weights from realised value |
| 3 | **No exploration** → feedback trap | UCB exploration bonus probes uncertain topics |
| 4 | **Crude trend deltas** ("+27%") fire on noise | `trend_detection.py`: deseasonalise + robust z-score + CUSUM change-point |
| 5 | **"Before competitors" is unproven** | sleeper topics model lagging search; the learner catches early Reddit signals |
| 6 | **Gap = "page exists? y/n"** | `semantic.py`: embedding cosine distance = *how under-served* |
| 7 | **Scores value, ignores effort** | ROI = value ÷ effort in `recommender.py` |
| 8 | **Ranks items in isolation** (cannibalisation) | portfolio selection skips near-duplicate picks |
| 9 | **Easily gamed** by one loud channel | `cross_source_agreement` feature + learned distrust of lone spikes |
| 10 | **Every score looks certain** | bandit returns calibrated `mean ± uncertainty` |

---

## Architecture

```
 raw signals ──► trend_detection (deseasonalise, z-score, CUSUM)
                 semantic        (embedding gap vs site content)
                        │
                        ▼
                 features  x  (config.FEATURE_NAMES)
                        │
                        ▼
             bandit (LinUCB)  ──► mean ± uncertainty
                        │
                        ▼
             recommender  ──► ROI rank + portfolio + rationale
                        │
        ┌───────────────┴───────────────┐
        ▼                               ▼
   morning brief                   store (SQLite)
        │                               │
        └──────── outcome ◄─────────────┘   ← THE CLOSED LOOP
                 (realised value feeds bandit.update)
```

## Files

| File | Role |
|---|---|
| `config.py` | categories, feature schema, the original spec's fixed weights, settings |
| `trend_detection.py` | seasonality removal, robust surprise, CUSUM change-point |
| `semantic.py` | TF-IDF embeddings + cosine content-gap |
| `world.py` | synthetic market (genuine / decoy / sleeper topics) + reward |
| `bandit.py` | **LinUCB** — learning, exploration, uncertainty |
| `recommender.py` | ROI scoring, portfolio selection, rationale, static baseline |
| `store.py` | SQLite persistence (recommendations + outcomes) |
| `simulate.py` | head-to-head proof + chart (`results.png`) |
| `cli.py` | day-to-day commands (`brief`, `outcome`, `status`) |

## Run it

```bash
pip install -r requirements.txt
python simulate.py            # head-to-head + results.png
python cli.py brief --week 8  # this week's ranked opportunities
python cli.py outcome 1 0.72  # record a realised result (closes the loop)
python cli.py status          # what the loop has learned so far
```

## Path to production

1. **Swap the synthetic world for real adapters** — keep `observe()`'s output
   shape; back it with Google Trends, Reddit/TikTok (Apify), News RSS, and a site
   crawl. Everything downstream is unchanged.
2. **Attribute outcomes honestly** — the loop is only as good as its reward
   signal. Prefer geo/time-split A/B rollouts (ship a change in some regions,
   compare) so you measure *causal* lift, not "the topic was rising anyway."
3. **Persist & schedule** — move `store.py` to Postgres, run the weekly cycle on
   a scheduler, snapshot the bandit state.
4. **Serve** — wrap `cli.py`'s brief in a small API + dashboard.

Build order matters: get outcome tracking working *first*, then exploration, then
the fancier signal processing. Skip straight to ML before the loop exists and you
have only built a more expensive guesser.
