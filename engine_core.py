"""
engine_core.py
--------------
The single, shared implementation of "run a policy over the synthetic market
for N weeks." Before this module the exact same week-by-week loop was
copy-pasted in three places (simulate.py, engine_service._train_initial and
engine_service.simulate); a fix in one was a silent bug in the others.

Two primitives live here:

  * run_loop_training  — the closed-loop learner alone: observe -> recommend ->
                         realise reward -> update the bandit. Trains a model.
  * run_head_to_head   — the original static scorer and the closed-loop learner
                         on the SAME world and budget, so we can measure who
                         captured more real value. Powers both the proof chart
                         and the live /api/simulate endpoint.

Both consume randomness only through the `rng` you pass in, so results are fully
reproducible and the same code can be swept across many seeds (see evaluate.py).

Optional `on_pick` / `on_loop_pick` callbacks let a caller persist each executed
recommendation without this module needing to know about SQLite.
"""
from typing import Callable, Optional

import numpy as np

from world import observe, realised_reward
import recommender as rec


# A candidate is the unit the recommender scores: a topic plus this week's
# observed context vector, raw signals and content-gap.
def iter_candidates(topics, index, week: int, rng: np.random.Generator,
                    exclude=frozenset()) -> list:
    """Observe every not-yet-built topic this week -> a list of candidate dicts."""
    cands = []
    for t in topics:
        if t.id in exclude:
            continue
        o = observe(t, index, week, rng)
        cands.append({"topic": t, "x": o["x"],
                      "signals": o["signals"], "gap": o["gap"]})
    return cands


def run_loop_training(topics, index, weeks: int, k: int,
                      rng: np.random.Generator, bandit,
                      on_pick: Optional[Callable] = None):
    """Run the closed-loop policy for `weeks`, learning from each realised reward.

    Mutates and returns `bandit`. If `on_pick(week, pick, reward)` is given it is
    called for every executed recommendation (used to persist to a store).
    """
    done = set()
    for week in range(weeks):
        cands = iter_candidates(topics, index, week, rng, done)
        for p in rec.recommend(cands, bandit, index, k):
            reward = realised_reward(p["topic"], p["gap"], rng)
            if on_pick is not None:
                on_pick(week, p, reward)
            bandit.update(p["x"], reward)
            done.add(p["topic"].id)
    return bandit


def run_single_policy(topics, index, weeks: int, k: int,
                      rng: np.random.Generator, policy) -> dict:
    """Run ONE policy over the world and report what it captured.

    Used by the ablation study (evaluate.py), where many policies are each run
    on the same world + noise stream so the only thing that differs is the
    policy itself. A `policy` exposes `.select(candidates, k)` and
    `.learn(pick, reward)` (a no-op for non-learning policies).
    """
    done = set()
    total = 0.0
    decoys = 0
    for week in range(weeks):
        cands = iter_candidates(topics, index, week, rng, done)
        for p in policy.select(cands, k):
            reward = realised_reward(p["topic"], p["gap"], rng)
            total += reward
            decoys += (p["topic"].kind == "decoy")
            policy.learn(p, reward)
            done.add(p["topic"].id)
    return {"total": total, "decoys": decoys}


def run_head_to_head(topics, index, weeks: int, k: int,
                     rng: np.random.Generator, bandit,
                     on_loop_pick: Optional[Callable] = None) -> dict:
    """Static scorer vs. closed-loop learner on one world; return the comparison.

    The static policy is evaluated first each week so the shared `rng` is
    consumed in a fixed order (this keeps the head-to-head reproducible). The
    `bandit` you pass in is trained by the closed-loop side and can be inspected
    afterwards for its learned weights.
    """
    done_s, done_l = set(), set()
    cum_static, cum_loop = [], []
    decoys_static = decoys_loop = 0
    tot_static = tot_loop = 0.0
    last_loop_picks = []

    for week in range(weeks):
        # ---- Static policy (the original spec: fixed weights, greedy top-k) ----
        for p in rec.static_select(iter_candidates(topics, index, week, rng, done_s), k):
            tot_static += realised_reward(p["topic"], p["gap"], rng)
            done_s.add(p["topic"].id)
            decoys_static += (p["topic"].kind == "decoy")
        cum_static.append(round(tot_static, 3))

        # ---- Closed-loop policy (the upgrade: LinUCB + ROI + portfolio) ----
        picks_l = rec.recommend(iter_candidates(topics, index, week, rng, done_l), bandit, index, k)
        last_loop_picks = picks_l
        for p in picks_l:
            r = realised_reward(p["topic"], p["gap"], rng)
            tot_loop += r
            done_l.add(p["topic"].id)
            decoys_loop += (p["topic"].kind == "decoy")
            bandit.update(p["x"], r)          # CLOSE THE LOOP
            if on_loop_pick is not None:
                on_loop_pick(week, p, r)
        cum_loop.append(round(tot_loop, 3))

    return {
        "weeks": list(range(1, weeks + 1)),
        "static": cum_static, "loop": cum_loop,
        "decoys_static": int(decoys_static), "decoys_loop": int(decoys_loop),
        "total_static": round(tot_static, 2), "total_loop": round(tot_loop, 2),
        "lift_pct": round((tot_loop - tot_static) / max(1e-9, abs(tot_static)) * 100),
        "last_loop_picks": last_loop_picks,
    }
