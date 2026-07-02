"""
reward_engine.py — turn a STANDARDISED outcome into a learning reward.

The learning engine only ever sees this standardised outcome shape, so any source
(Google today; Adobe Analytics, a CRM, etc. tomorrow) can feed it without touching
the learner:

    {
      "source": "google",
      "clicks_change_pct":       float | None,   # organic clicks, % vs baseline
      "impressions_change_pct":  float | None,
      "position_change":         float | None,   # avg-position improvement (+ = moved up)
      "ctr_change_pct":          float | None,
      "sessions_change_pct":     float | None,   # organic sessions
      "conversions_change_pct":  float | None,   # if the property has conversions
      "data_confidence":         float,          # 0..1, from traffic volume (noise guard)
    }

reward() maps it to config.REWARD_MIN..REWARD_MAX. No change -> the neutral midpoint;
strong genuine improvement -> ~1.0; a real decline -> negative. Never fabricated —
callers pass measured changes or nothing.
"""
import math

import config

# Each metric's saturating scale (the % change that counts as "clearly good")
# and its weight in the blended success score.
_TERMS = [
    ("clicks_change_pct",      50.0, 0.28),   # the headline SEO outcome
    ("position_change",         5.0, 0.24),   # ranking improvement (in positions)
    ("sessions_change_pct",    50.0, 0.16),   # organic traffic (corroborates clicks)
    ("impressions_change_pct", 60.0, 0.12),
    ("ctr_change_pct",         40.0, 0.10),
    ("conversions_change_pct", 50.0, 0.10),   # business value, when available
]


def reward(outcome):
    """Blend the standardised metric changes into a reward in the model's range,
    or None if there's nothing measurable to learn from."""
    num = den = 0.0
    for key, scale, w in _TERMS:
        v = outcome.get(key)
        if v is None:
            continue
        num += math.tanh(v / scale) * w        # tanh -> -1..1, saturating
        den += w
    if den == 0:
        return None
    score = num / den                            # -1..1
    lo, hi = config.REWARD_MIN, config.REWARD_MAX
    r = lo + (score + 1.0) / 2.0 * (hi - lo)     # -1 -> lo, 0 -> midpoint, +1 -> hi
    return round(max(lo, min(hi, r)), 4)


def is_success(outcome):
    """A convenience flag for the dashboard: did the recommendation clearly help?"""
    r = reward(outcome)
    if r is None:
        return None
    midpoint = config.REWARD_MIN + (config.REWARD_MAX - config.REWARD_MIN) / 2.0
    return r > midpoint + 0.05
