"""Golden-master regression for the headline proof.

These numbers ARE the result the whole project is built to demonstrate. They are
locked here so a refactor can never silently change them. If one of these fails,
it must be because someone changed the behaviour on purpose."""
import numpy as np
import pytest

import config
from world import build_world
from bandit import LinUCB
from engine_core import run_head_to_head, run_loop_training


def _standard_head_to_head():
    s = config.SETTINGS
    topics, index, _ = build_world()                 # the seed=7 reference world
    rng = np.random.default_rng(s["seed"] + 1)
    bandit = LinUCB(config.N_FEATURES, alpha=s["linucb_alpha"])
    res = run_head_to_head(topics, index, s["weeks"], s["weekly_budget"], rng, bandit)
    return res, bandit


def test_proof_numbers_are_locked():
    res, _ = _standard_head_to_head()
    assert res["total_static"] == pytest.approx(26.1, abs=0.05)
    assert res["total_loop"] == pytest.approx(36.5, abs=0.05)
    assert res["decoys_static"] == 19
    assert res["decoys_loop"] == 2
    assert res["lift_pct"] == 40


def test_loop_beats_static_on_value_and_junk():
    res, _ = _standard_head_to_head()
    assert res["total_loop"] > res["total_static"]
    assert res["decoys_loop"] < res["decoys_static"]


def test_engine_learns_to_distrust_tiktok():
    s = config.SETTINGS
    topics, index, _ = build_world()
    rng = np.random.default_rng(s["seed"] + 1)
    bandit = LinUCB(config.N_FEATURES, alpha=s["linucb_alpha"])
    run_loop_training(topics, index, s["weeks"], s["weekly_budget"], rng, bandit)
    theta = dict(zip(config.FEATURE_NAMES, bandit.learned_weights()["theta"]))
    # The headline qualitative result, discovered not programmed:
    assert theta["tiktok_velocity"] < 0.0          # loud single-channel hype distrusted
    assert theta["semantic_gap"] > 0.0             # genuine under-served demand valued
    assert theta["semantic_gap"] > theta["tiktok_velocity"]
