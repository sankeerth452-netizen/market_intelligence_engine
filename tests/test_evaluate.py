"""The multi-seed evaluation must run and tell a coherent story (kept to a
couple of seeds so the suite stays fast)."""
import pytest

import config
from evaluate import robustness, ablation

SEEDS = [200, 201]
WEEKS = config.SETTINGS["weeks"]
K = config.SETTINGS["weekly_budget"]


def test_robustness_loop_beats_static():
    r = robustness(SEEDS, WEEKS, K)
    assert r["loop_mean"] > r["static_mean"]
    assert r["win_rate"] > 0.0
    assert r["decoys_loop_mean"] < r["decoys_static_mean"]


def test_ablation_ladder_shape_and_learning_helps():
    rows = ablation(SEEDS, WEEKS, K)
    assert len(rows) == 5
    by_rung = {r["name"].split()[0]: r["mean"] for r in rows}
    # Turning on learning (P3) must clearly beat the static spec (P0).
    assert by_rung["P3"] > by_rung["P0"]
    assert by_rung["P4"] > by_rung["P0"]
