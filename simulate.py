"""
simulate.py
-----------
Runs the original design and the upgraded engine over the SAME market world and
budget, then reports who captured more real value — and renders a chart.

Static policy   = the cousin's spec: fixed weights, greedy top-k, no learning,
                  no exploration, no effort/portfolio awareness.
Closed-loop     = LinUCB + ROI + portfolio + the feedback loop.

The world is synthetic and illustrative (it is *designed* to contain learnable
structure that mirrors real failure modes). It is a mechanism demonstration,
not an empirical benchmark on live data.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import config
from world import build_world
from bandit import LinUCB
from engine_core import run_head_to_head
import recommender as rec
import store


def run():
    s = config.SETTINGS
    weeks, k = s["weeks"], s["weekly_budget"]

    topics, index, _ = build_world()
    rng = np.random.default_rng(s["seed"] + 1)  # reward/observation noise stream

    bandit = LinUCB(config.N_FEATURES, alpha=s["linucb_alpha"])
    conn = store.connect("mie.db")

    # Persist every executed closed-loop recommendation (and its realised result)
    # so the proof run also populates the audit log, exactly as before.
    def persist(week, p, reward):
        rid = store.save_recommendation(
            conn, week, p["topic"].name, p["topic"].category, p["topic"].kind,
            p["roi"], p["pred"]["mean"], p["pred"]["uncertainty"], p["topic"].effort,
            rec.rationale(p["signals"], p["pred"], p["topic"].effort, p["exploring"]))
        store.record_outcome(conn, rid, reward)

    # The whole head-to-head now lives in one shared, tested function.
    res = run_head_to_head(topics, index, weeks, k, rng, bandit, on_loop_pick=persist)
    tot_static, tot_loop = res["total_static"], res["total_loop"]
    decoys_static, decoys_loop = res["decoys_static"], res["decoys_loop"]
    cum_static, cum_loop = res["static"], res["loop"]
    last_loop_picks = res["last_loop_picks"]

    # ---------------------------------------------------------------- report ----
    print("=" * 70)
    print("MARKET INTELLIGENCE ENGINE  \u2014  static design vs. closed-loop upgrade")
    print("=" * 70)
    print(f"Horizon: {weeks} weeks  |  Budget: {k}/week  |  "
          f"{len(topics)} topics (50 genuine, 20 decoy, 20 sleeper)\n")
    print(f"{'Policy':<22}{'Total value':>14}{'Decoys built':>16}{'Avg/action':>14}")
    n_actions = weeks * k
    print(f"{'Original (static)':<22}{tot_static:>14.2f}{decoys_static:>16}"
          f"{tot_static / n_actions:>14.3f}")
    print(f"{'Closed-loop (ours)':<22}{tot_loop:>14.2f}{decoys_loop:>16}"
          f"{tot_loop / n_actions:>14.3f}")
    lift = (tot_loop - tot_static) / max(1e-9, abs(tot_static)) * 100
    print(f"\n>> Closed-loop captured {lift:+.0f}% more real value while building "
          f"{decoys_static - decoys_loop} fewer junk pages.\n")

    print("DB:", store.summary(conn))

    # Show the learned weights — note which signals the engine came to trust.
    theta = bandit.learned_weights()["theta"]
    print("\nLearned signal weights (vs the spec's fixed guesses):")
    for name, w in sorted(zip(config.FEATURE_NAMES, theta),
                          key=lambda z: -z[1]):
        if name == "bias":
            continue
        print(f"  {name:<24}{w:+.3f}")

    # A sample of the upgraded 'morning brief' from the final week.
    print("\n" + "-" * 70)
    print("SAMPLE MORNING BRIEF (final week, closed-loop output):")
    print("-" * 70)
    for i, p in enumerate(last_loop_picks, 1):
        print(f"{i}. {p['topic'].name}  [ROI {p['roi']:.2f}]")
        print(f"   {rec.rationale(p['signals'], p['pred'], p['topic'].effort, p['exploring'])}")

    _chart(cum_static, cum_loop, decoys_static, decoys_loop)
    return tot_static, tot_loop, decoys_static, decoys_loop


def _chart(cum_static, cum_loop, decoys_static, decoys_loop):
    weeks = np.arange(1, len(cum_static) + 1)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.6))

    ax1.plot(weeks, cum_static, "o-", color="#b0492b", label="Original (static)")
    ax1.plot(weeks, cum_loop, "o-", color="#1f6f6f", label="Closed-loop (ours)")
    ax1.fill_between(weeks, cum_static, cum_loop, where=np.array(cum_loop) >= np.array(cum_static),
                     color="#1f6f6f", alpha=0.10)
    ax1.set_title("Cumulative real value captured")
    ax1.set_xlabel("Week"); ax1.set_ylabel("Cumulative net value")
    ax1.legend(); ax1.grid(alpha=0.25)

    ax2.bar(["Original", "Closed-loop"], [decoys_static, decoys_loop],
            color=["#b0492b", "#1f6f6f"])
    ax2.set_title("Junk ('decoy') pages built")
    ax2.set_ylabel("count")
    for i, v in enumerate([decoys_static, decoys_loop]):
        ax2.text(i, v + 0.05, str(v), ha="center")

    fig.suptitle("Market Intelligence Engine: closing the loop beats a static scorer",
                 fontweight="bold")
    fig.tight_layout()
    fig.savefig("results.png", dpi=140)
    print("\nSaved chart -> results.png")


if __name__ == "__main__":
    run()
