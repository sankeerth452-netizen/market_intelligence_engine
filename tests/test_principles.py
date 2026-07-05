"""Principle-based learning: priors on day one, real outcomes shift the beliefs,
and the learned effectiveness re-weights the marketing ideas."""
import pytest

import store
import principles
import ideas


@pytest.fixture
def engine(tmp_path):
    return store.connect(f"sqlite:///{tmp_path / 'test.db'}")


def test_priors_stand_when_no_data(engine):
    eff = principles.effectiveness(engine, "jbhifi")
    assert len(eff) == len(principles.TYPES)
    assert all(e["n"] == 0 and e["basis"] == "expert prior" for e in eff)
    types = [e["type"] for e in eff]                      # the brief's patterns encoded as priors
    assert types.index("Comparison page") < types.index("Blog / explainer")


def test_multipliers_normalise_around_one(engine):
    m = principles.multipliers(engine, "jbhifi")
    assert abs(sum(m.values()) / len(m) - 1.0) < 0.02


def test_map_action():
    assert principles.map_action("Optimise existing page") == "Category optimisation"
    assert principles.map_action("Create new page") == "New landing page"


def test_real_outcomes_shift_a_prior(engine):
    ck = "jbhifi"
    for rid, r in [(101, 0.95), (102, 0.9)]:
        store.principle_set_type(engine, rid, ck, "Blog / explainer")
        store.principle_set_reward(engine, rid, r)
    blog = {e["type"]: e for e in principles.effectiveness(engine, ck)}["Blog / explainer"]
    assert blog["n"] == 2 and "real result" in blog["basis"]
    assert blog["score"] > 0.40                          # blended up from the 0.40 prior


def test_learned_multipliers_reweight_ideas():
    boosted = ideas.generate(mult={t: (3.0 if t == "Buying guide" else 0.5) for t in principles.TYPES})
    assert boosted["available"]
    assert any(t["ideas"] and t["ideas"][0]["type"] == "Buying guide" for t in boosted["topics"])
