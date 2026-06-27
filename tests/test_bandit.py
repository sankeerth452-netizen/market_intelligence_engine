"""LinUCB bandit: the incremental inverse must stay exact, and the model must
persist losslessly and learn in the right direction."""
import numpy as np
import pytest

from bandit import LinUCB


def test_sherman_morrison_matches_brute_force_inverse():
    """The cached rank-1 inverse update must equal a fresh exact inverse of A."""
    rng = np.random.default_rng(0)
    m = LinUCB(n_features=6, alpha=0.5)
    for _ in range(40):
        m.update(rng.normal(size=6), float(rng.uniform(0, 1)))
    assert np.allclose(m.A_inv, np.linalg.inv(m.A), atol=1e-9)


def test_ucb_is_mean_plus_uncertainty():
    m = LinUCB(4, alpha=0.7)
    p = m.predict([1.0, 0.2, 0.5, 0.3])
    assert p["ucb"] == pytest.approx(p["mean"] + p["uncertainty"])
    assert p["uncertainty"] >= 0.0


def test_uncertainty_shrinks_with_evidence():
    m = LinUCB(4, alpha=0.7)
    x = np.array([1.0, 0.6, 0.2, 0.9])
    before = m.predict(x)["uncertainty"]
    for _ in range(15):
        m.update(x, 0.8)
    assert m.predict(x)["uncertainty"] < before


def test_learns_reward_direction():
    m = LinUCB(3, alpha=0.0)  # alpha=0 -> pure exploitation, test the mean only
    x = np.array([1.0, 1.0, 0.0])
    for _ in range(30):
        m.update(x, 1.0)
    assert m.predict(x)["mean"] > 0.3


def test_persistence_roundtrip_preserves_predictions():
    rng = np.random.default_rng(1)
    m = LinUCB(5, alpha=0.6)
    for _ in range(20):
        m.update(rng.normal(size=5), float(rng.uniform(0, 1)))
    restored = LinUCB.from_dict(m.to_dict())
    x = rng.normal(size=5)
    a, b = restored.predict(x), m.predict(x)
    assert a["mean"] == pytest.approx(b["mean"])
    assert a["uncertainty"] == pytest.approx(b["uncertainty"])
    assert restored.n_updates == m.n_updates
