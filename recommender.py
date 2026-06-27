"""
recommender.py
--------------
Turns signals + the learned bandit into a ranked, de-duplicated, explainable
plan — and provides the original spec's policy as a baseline to beat.

Upgrades over the original spec captured here:
  * Value-per-effort (ROI), not raw value.
  * Portfolio selection: skip near-duplicate picks that would cannibalise.
  * Calibrated confidence from the bandit's uncertainty.
  * Human rationale that cites the evidence and the confidence.
"""
import numpy as np

import config
from bandit import LinUCB
from semantic import SemanticIndex


# ---------------------------------------------------------------- baseline ----
def static_score(signals: dict) -> float:
    """The original spec's fixed-weight scorer (0..1). No learning, no effort."""
    return float(sum(w * signals[f] for f, w in config.STATIC_WEIGHTS.items()))


def static_select(candidates, k: int):
    """Greedy top-k by fixed score (faithful to the original design)."""
    ranked = sorted(candidates, key=lambda c: static_score(c["signals"]), reverse=True)
    return ranked[:k]


# --------------------------------------------------------------- upgraded ----
def _effort_factor(effort: str) -> float:
    return {"low": 1.0, "med": 0.7, "high": 0.45}[effort]


def roi_score(pred: dict, effort: str) -> float:
    """Expected value adjusted for effort, using the UCB (value + exploration)."""
    return pred["ucb"] * _effort_factor(effort)


def confidence_label(uncertainty: float) -> str:
    if uncertainty < 0.18:
        return "high confidence"
    if uncertainty < 0.35:
        return "moderate confidence"
    return "exploratory probe"


def rationale(signals: dict, pred: dict, effort: str, exploring: bool) -> str:
    bits = []
    if signals["trend_surprise"] > 0.6:
        bits.append("a genuine rise in demand")
    if signals["trend_changepoint"] > 0.5:
        bits.append("a detected change-point")
    if signals["cross_source_agreement"] > 0.6:
        bits.append("corroboration across independent sources")
    elif signals["cross_source_agreement"] < 0.4:
        bits.append("ONLY a single-channel spike (low corroboration)")
    if signals["reddit_neg_sentiment"] > 0.5:
        bits.append("rising negative sentiment (reputation angle)")
    if signals["semantic_gap"] > 0.6:
        bits.append("a real content gap on-site")
    evidence = "; ".join(bits) if bits else "weak/mixed signals"
    tag = "PROBE (uncertain, run to learn)" if exploring else confidence_label(pred["uncertainty"])
    return (f"Expected value {pred['mean']:.2f} (\u00b1{pred['uncertainty']:.2f}, {tag}); "
            f"effort {effort}. Evidence: {evidence}.")


def recommend(candidates, bandit: LinUCB, index: SemanticIndex, k: int):
    """
    Score every candidate with the bandit, then greedily pick the best PORTFOLIO
    of k items, skipping any pick too semantically similar to one already chosen.
    """
    scored = []
    for c in candidates:
        pred = bandit.predict(c["x"])
        scored.append({
            **c,
            "pred": pred,
            "roi": roi_score(pred, c["topic"].effort),
            "exploring": pred["uncertainty"] > 0.35,
        })
    scored.sort(key=lambda s: s["roi"], reverse=True)

    chosen, thresh = [], config.SETTINGS["portfolio_sim_threshold"]
    for cand in scored:
        if any(index.similarity(cand["topic"].demand_text, ch["topic"].demand_text) > thresh
               for ch in chosen):
            continue  # would cannibalise an already-selected page
        chosen.append(cand)
        if len(chosen) == k:
            break
    return chosen
