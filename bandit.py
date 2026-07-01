"""
bandit.py
---------
A LinUCB contextual bandit (Li et al., 2010) — the brain of the upgrade.

WHY THIS MATTERS (three of the original spec's flaws fixed by one object):

  * Closed loop  -> it `update`s itself from the realised reward of every
                    action that gets executed. It actually learns.
  * Learned weights -> the linear coefficients ARE the scoring weights. They
                    are estimated from outcomes, not hand-picked, so the engine
                    discovers (e.g.) that loud single-source spikes don't pay.
  * Safe exploration -> the upper-confidence bonus makes the engine occasionally
                    probe topics it is *uncertain* about. This is the principled
                    cure for the "feedback trap": a model that only ever acts on
                    what it already likes goes blind to everything else.

Each prediction returns a *mean* and an *uncertainty*, so the rest of the
system can show calibrated confidence instead of a bare number.

Maths recap:
    A = I (d x d),  b = 0 (d)
    theta = A^{-1} b
    mean(x)        = theta . x
    uncertainty(x) = alpha * sqrt(x^T A^{-1} x)
    UCB(x)         = mean + uncertainty
    on reward r:   A += x x^T ;  b += r x
"""
import numpy as np


class LinUCB:
    def __init__(self, n_features: int, alpha: float = 0.65):
        self.d = n_features
        self.alpha = alpha
        self.A = np.identity(self.d)        # design matrix (starts at identity)
        self.A_inv = np.identity(self.d)    # cached inverse, kept in sync
        self.b = np.zeros(self.d)
        self.n_updates = 0

    def _theta(self) -> np.ndarray:
        return self.A_inv @ self.b

    def predict(self, x) -> dict:
        x = np.asarray(x, dtype=float)
        mean = float(self._theta() @ x)
        uncertainty = float(self.alpha * np.sqrt(max(0.0, x @ self.A_inv @ x)))
        return {"mean": mean, "uncertainty": uncertainty, "ucb": mean + uncertainty}

    def update(self, x, reward: float) -> None:
        """Learn from one executed action and the value it actually produced."""
        x = np.asarray(x, dtype=float)
        self.A += np.outer(x, x)
        self.b += reward * x
        # Sherman–Morrison rank-1 inverse update (keeps predict() O(d^2)).
        Ax = self.A_inv @ x
        self.A_inv -= np.outer(Ax, Ax) / (1.0 + float(x @ Ax))
        self.n_updates += 1

    def seed_prior(self, weights, strength: float = 1.0) -> "LinUCB":
        """Start from a PRIOR belief theta ~= weights, held with confidence
        `strength` (equivalent to `strength` pseudo-observations of ridge prior).

        This is NOT synthetic training data and does NOT count as a real update
        (n_updates stays 0): it's just a sensible starting point (marketing
        best-practice) so the model works out-of-the-box and refines from real
        recorded results, rather than starting blank. A += sI, b = s*weights =>
        theta = A^{-1} b = weights, with uncertainty scaled down by sqrt(s)."""
        w = np.asarray(weights, dtype=float)
        s = max(1e-6, float(strength))
        self.A = np.identity(self.d) * s
        self.A_inv = np.identity(self.d) / s
        self.b = w * s
        return self

    def learned_weights(self) -> dict:
        """Expose the current learned coefficients for interpretability."""
        return {"theta": self._theta().tolist(), "n_updates": self.n_updates}

    # ---- persistence (so the feedback loop survives a restart) ----
    def to_dict(self) -> dict:
        return {"d": self.d, "alpha": self.alpha, "A": self.A.tolist(),
                "A_inv": self.A_inv.tolist(), "b": self.b.tolist(),
                "n_updates": self.n_updates}

    @classmethod
    def from_dict(cls, data: dict) -> "LinUCB":
        m = cls(int(data["d"]), float(data["alpha"]))
        m.A = np.array(data["A"], dtype=float)
        m.A_inv = np.array(data["A_inv"], dtype=float)
        m.b = np.array(data["b"], dtype=float)
        m.n_updates = int(data["n_updates"])
        return m
