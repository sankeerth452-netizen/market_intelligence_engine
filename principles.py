"""
principles.py — principle-based learning (Nitin v2, phase 3).

The brief's "most important feature": the engine should learn PRINCIPLES, not URLs
— e.g. "buying guides outperform generic category pages", "comparison pages generate
higher commercial traffic". So we track outcomes by the marketing idea TYPE that was
used, and learn which kinds of move actually pay off.

Cold-start is solved the same way as the bandit: each type starts with an expert
PRIOR (straight from the brief's stated patterns) worth a few pseudo-observations;
real GSC/GA4 outcomes then gradually take over. Nothing is fabricated — with no
results yet, the priors simply stand.
"""
import store

# Prior expected reward per idea type, on the reward scale [REWARD_MIN=-0.15, 1.0]
# where "no change" ~= 0.425. Higher = the brief expects this move to pay off more.
PRIORS = {
    "Comparison page":        (0.62, "High commercial intent — comparison shoppers are close to buying."),
    "Buying guide":           (0.58, "Captures 'best' buyers and links straight to product pages."),
    "Answer content":         (0.50, "Wins AI-answer and featured-snippet visibility."),
    "New landing page":       (0.47, "New coverage for a proven-demand topic."),
    "Category optimisation":  (0.46, "Fast and low-risk, but competes on generic terms."),
    "Bundle / merchandising": (0.45, "Lifts basket size on existing demand."),
    "Short-form video":       (0.42, "Cheap reach; seeds demand, converts indirectly."),
    "Blog / explainer":       (0.40, "Builds topical authority; slower, top-of-funnel payoff."),
}
STRENGTH = 5.0          # a prior counts as ~5 pseudo-observations
TYPES = list(PRIORS)

# Map a This Week's Plan action to a principle type (the plan's coarse moves).
_ACTION_TYPE = {
    "Optimise existing page": "Category optimisation",
    "Create new page": "New landing page",
}


def map_action(action):
    return _ACTION_TYPE.get(action or "", "New landing page")


def effectiveness(engine, client_key):
    """Learned effectiveness per idea type: the prior blended with real outcomes.
    Returns a list, best first, each with score, sample size and the basis."""
    stats = store.principle_stats(engine, client_key)
    out = []
    for t, (prior, why) in PRIORS.items():
        s = stats.get(t, {"sum": 0.0, "n": 0})
        n = s["n"]
        score = (prior * STRENGTH + s["sum"]) / (STRENGTH + n)
        out.append({
            "type": t,
            "score": round(score, 3),
            "prior": prior,
            "n": n,
            "basis": (f"{n} real result" + ("s" if n != 1 else "")) if n else "expert prior",
            "rationale": why,
        })
    out.sort(key=lambda x: -x["score"])
    return out


def multipliers(engine, client_key):
    """Per-type ranking multiplier (normalised to ~1 average) so proven idea types
    rise in the Marketing Ideas ranking as real outcomes accrue."""
    eff = effectiveness(engine, client_key)
    avg = sum(e["score"] for e in eff) / len(eff) if eff else 1.0
    return {e["type"]: (e["score"] / avg if avg > 0 else 1.0) for e in eff}
