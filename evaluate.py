"""
evaluate.py
-----------
Turns the single-seed demo into a defensible result.

Two studies, both run offline over many INDEPENDENT synthetic markets:

  1. ROBUSTNESS — the head-to-head (static spec vs. full closed-loop) across N
     different worlds. Reports the mean value lift with a 95% confidence
     interval and the fraction of worlds the closed loop wins, so "+40%" stops
     being one lucky seed and becomes a distribution.

  2. ABLATION — the five-rung ladder (static -> +effort -> +portfolio ->
     +learning -> +exploration) across the same N worlds, to attribute the gain
     to each individual upgrade.

Run:
    python evaluate.py                 # default 30 worlds
    python evaluate.py --seeds 50

Writes evaluation.png (chart) and evaluation.json (headline numbers for the UI).
"""
import argparse
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import config
from world import build_world
from bandit import LinUCB
from engine_core import run_head_to_head, run_single_policy
from policies import ablation_ladder

HERE = os.path.dirname(__file__)
TEAL, AMBER, GREY, INK = "#0F766E", "#B7791F", "#9AA1AC", "#15171E"


def _ci95(x):
    """Half-width of the 95% confidence interval for the mean (normal approx)."""
    x = np.asarray(x, dtype=float)
    if len(x) < 2:
        return 0.0
    return float(1.96 * x.std(ddof=1) / np.sqrt(len(x)))


# ----------------------------------------------------------------- study 1 ----
def robustness(seeds, weeks, k):
    lifts, tot_s, tot_l, dec_s, dec_l, wins = [], [], [], [], [], 0
    for seed in seeds:
        topics, index, _ = build_world(seed=seed)
        rng = np.random.default_rng(seed + 1)
        bandit = LinUCB(config.N_FEATURES, alpha=config.SETTINGS["linucb_alpha"])
        res = run_head_to_head(topics, index, weeks, k, rng, bandit)
        lifts.append(res["lift_pct"])
        tot_s.append(res["total_static"]);  tot_l.append(res["total_loop"])
        dec_s.append(res["decoys_static"]);  dec_l.append(res["decoys_loop"])
        wins += int(res["total_loop"] > res["total_static"])
    return {
        "n": len(seeds),
        "lift_mean": float(np.mean(lifts)), "lift_ci": _ci95(lifts),
        "static_mean": float(np.mean(tot_s)), "static_ci": _ci95(tot_s),
        "loop_mean": float(np.mean(tot_l)), "loop_ci": _ci95(tot_l),
        "decoys_static_mean": float(np.mean(dec_s)),
        "decoys_loop_mean": float(np.mean(dec_l)),
        "win_rate": wins / len(seeds), "wins": wins,
        "lifts": lifts,
    }


# ----------------------------------------------------------------- study 2 ----
def ablation(seeds, weeks, k):
    names, totals, decoys = None, None, None
    for seed in seeds:
        topics, index, _ = build_world(seed=seed)
        ladder = ablation_ladder(index)
        if names is None:
            names = [p.name for p in ladder]
            totals = {n: [] for n in names}
            decoys = {n: [] for n in names}
        for p in ladder:
            rng = np.random.default_rng(seed + 1)   # identical world+noise per rung
            r = run_single_policy(topics, index, weeks, k, rng, p)
            totals[p.name].append(r["total"])
            decoys[p.name].append(r["decoys"])
    rows = []
    prev = None
    for n in names:
        mean = float(np.mean(totals[n]))
        rows.append({"name": n, "mean": mean, "ci": _ci95(totals[n]),
                     "decoys": float(np.mean(decoys[n])),
                     "delta": None if prev is None else mean - prev})
        prev = mean
    return rows


# -------------------------------------------------------------------- report --
def _print_report(rob, abl):
    n = rob["n"]
    print("=" * 72)
    print(f"ROBUSTNESS  —  static spec vs. full closed-loop across {n} independent markets")
    print("=" * 72)
    print(f"  Real value captured (mean +/- 95% CI):")
    print(f"    static (spec)   {rob['static_mean']:6.2f}  +/- {rob['static_ci']:.2f}")
    print(f"    closed-loop     {rob['loop_mean']:6.2f}  +/- {rob['loop_ci']:.2f}")
    print(f"  Value lift          {rob['lift_mean']:+5.1f}%  +/- {rob['lift_ci']:.1f}%")
    print(f"  Closed loop wins    {rob['wins']}/{n} worlds  ({rob['win_rate']*100:.0f}%)")
    print(f"  Junk pages built    {rob['decoys_static_mean']:.1f} (static) "
          f"vs {rob['decoys_loop_mean']:.1f} (loop), mean per run")
    print()
    print("=" * 72)
    print(f"ABLATION  —  where the gain comes from (mean value over {n} markets)")
    print("=" * 72)
    print(f"  {'policy':<28}{'value':>8}{'+/-95%':>9}{'gain vs prev':>15}{'decoys':>9}")
    for r in abl:
        delta = "  (baseline)" if r["delta"] is None else f"{r['delta']:+.2f}"
        print(f"  {r['name']:<28}{r['mean']:>8.2f}{r['ci']:>9.2f}{delta:>15}{r['decoys']:>9.1f}")
    print()


# --------------------------------------------------------------------- chart --
def _chart(rob, abl, path):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    # Left: robustness — mean value with 95% CI, plus win-rate annotation.
    labels = ["Static\n(spec)", "Closed-loop\n(ours)"]
    means = [rob["static_mean"], rob["loop_mean"]]
    errs = [rob["static_ci"], rob["loop_ci"]]
    bars = ax1.bar(labels, means, yerr=errs, capsize=8,
                   color=[GREY, TEAL], width=0.6)
    ax1.set_ylim(0, rob["loop_mean"] * 1.22)
    ax1.set_title(f"Value captured across {rob['n']} independent markets\n"
                  f"(mean ± 95% CI)", fontweight="bold", fontsize=11)
    ax1.set_ylabel("Real value captured")
    for b, m in zip(bars, means):
        ax1.text(b.get_x() + b.get_width() / 2, m + 0.4, f"{m:.1f}",
                 ha="center", va="bottom", fontweight="bold")
    ax1.text(0.04, 0.92,
             f"+{rob['lift_mean']:.0f}% ± {rob['lift_ci']:.0f}% more value",
             transform=ax1.transAxes, ha="left", fontsize=11.5, color=TEAL,
             fontweight="bold")
    ax1.text(0.04, 0.85,
             f"wins {rob['wins']}/{rob['n']} markets   ·   junk pages "
             f"{rob['decoys_static_mean']:.0f} → {rob['decoys_loop_mean']:.0f}",
             transform=ax1.transAxes, ha="left", fontsize=9.5, color=INK)
    ax1.grid(axis="y", alpha=0.25)

    # Right: ablation ladder — staircase of mean value, each rung labelled.
    names = [r["name"] for r in abl]
    vals = [r["mean"] for r in abl]
    errs2 = [r["ci"] for r in abl]
    colors = [GREY, GREY, GREY, TEAL, TEAL]
    y = np.arange(len(names))[::-1]
    ax2.barh(y, vals, xerr=errs2, capsize=5, color=colors, height=0.62)
    ax2.set_yticks(y); ax2.set_yticklabels(names, fontsize=9)
    ax2.set_title("Where the gain comes from\n(each rung adds one upgrade)",
                  fontweight="bold", fontsize=11)
    ax2.set_xlabel("Real value captured (mean)")
    for yi, r in zip(y, abl):
        lbl = f"{r['mean']:.1f}" + (f"  ({r['delta']:+.1f})" if r["delta"] is not None else "")
        ax2.text(r["mean"], yi, "  " + lbl, va="center", fontsize=9)
    ax2.set_xlim(0, max(vals) * 1.18)
    ax2.text(0.0, -0.16, "grey = open-loop tuning   ·   teal = learning from outcomes "
             "(the closed loop)", transform=ax2.transAxes, fontsize=8.5, color=INK)
    ax2.grid(axis="x", alpha=0.25)

    fig.suptitle("Market Intelligence Engine — the closed loop wins, and we can prove it",
                 fontweight="bold", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(path, dpi=140)
    print(f"Saved chart -> {os.path.relpath(path, HERE)}")


def main():
    ap = argparse.ArgumentParser(description="Multi-seed robustness + ablation study")
    ap.add_argument("--seeds", type=int, default=30, help="number of markets")
    ap.add_argument("--start", type=int, default=100, help="first seed")
    args = ap.parse_args()

    s = config.SETTINGS
    weeks, k = s["weeks"], s["weekly_budget"]
    seeds = list(range(args.start, args.start + args.seeds))

    print(f"\nEvaluating over {len(seeds)} markets "
          f"(seeds {seeds[0]}..{seeds[-1]}, {weeks} weeks, budget {k}/week)...\n")
    rob = robustness(seeds, weeks, k)
    abl = ablation(seeds, weeks, k)
    _print_report(rob, abl)

    _chart(rob, abl, os.path.join(HERE, "evaluation.png"))
    with open(os.path.join(HERE, "evaluation.json"), "w") as f:
        json.dump({"robustness": {kk: vv for kk, vv in rob.items() if kk != "lifts"},
                   "ablation": abl,
                   "settings": {"seeds": len(seeds), "weeks": weeks, "budget": k}},
                  f, indent=2)
    print("Saved headline numbers -> evaluation.json\n")


if __name__ == "__main__":
    main()
