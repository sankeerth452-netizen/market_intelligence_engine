"""
policies.py
-----------
Policy variants for the ablation study. The point of an ablation is to answer a
question a sceptic will always ask: *which* upgrade actually earned the win?

We build a ladder where each rung adds exactly ONE idea over the rung below it:

  P0  static (the cousin's spec) : fixed weights, greedy top-k
  P1  + effort                   : rank by value-per-effort (ROI), not raw value
  P2  + portfolio                : skip near-duplicate picks (anti-cannibalisation)
  P3  + learning (exploit only)  : LinUCB learns weights from outcomes, no probing
  P4  + exploration (full)       : LinUCB + UCB exploration = the real system

Running all five on the SAME worlds isolates the marginal value of each idea.
P4 mirrors recommender.recommend(); P0 mirrors recommender.static_select().
"""
import config
import recommender as rec
from bandit import LinUCB


class AblationPolicy:
    """One configurable rung of the ablation ladder.

    Flags switch the four upgrades on/off so each rung differs from the next by
    exactly one capability.
    """

    def __init__(self, name, index, *, use_effort=False, use_portfolio=False,
                 learn=False, explore=False):
        self.name = name
        self.index = index
        self.use_effort = use_effort
        self.use_portfolio = use_portfolio
        self.explore = explore
        # A learner only needs an exploration bonus if it is allowed to explore.
        alpha = config.SETTINGS["linucb_alpha"] if explore else 0.0
        self.bandit = LinUCB(config.N_FEATURES, alpha=alpha) if learn else None

    def _score(self, c):
        if self.bandit is not None:
            pred = self.bandit.predict(c["x"])
            base = pred["ucb"] if self.explore else pred["mean"]
        else:
            base = rec.static_score(c["signals"])          # fixed-weight scorer
        if self.use_effort:
            base *= rec._effort_factor(c["topic"].effort)  # value per unit effort
        return base

    def select(self, candidates, k):
        ranked = sorted(candidates, key=self._score, reverse=True)
        if not self.use_portfolio:
            return ranked[:k]
        chosen, thresh = [], config.SETTINGS["portfolio_sim_threshold"]
        for c in ranked:
            if any(self.index.similarity(c["topic"].demand_text,
                                         ch["topic"].demand_text) > thresh
                   for ch in chosen):
                continue                                    # would cannibalise a pick
            chosen.append(c)
            if len(chosen) == k:
                break
        return chosen

    def learn(self, pick, reward):
        if self.bandit is not None:
            self.bandit.update(pick["x"], reward)


def ablation_ladder(index):
    """The five rungs, in order, each adding one capability over the last."""
    return [
        AblationPolicy("P0  static (spec)",        index),
        AblationPolicy("P1  + effort (ROI)",       index, use_effort=True),
        AblationPolicy("P2  + portfolio de-dup",   index, use_effort=True,
                       use_portfolio=True),
        AblationPolicy("P3  + learning (exploit)", index, use_effort=True,
                       use_portfolio=True, learn=True),
        AblationPolicy("P4  + exploration (full)", index, use_effort=True,
                       use_portfolio=True, learn=True, explore=True),
    ]
