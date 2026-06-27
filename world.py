"""
world.py
--------
A synthetic but *honest* market world used to demonstrate and stress-test the
engine. Real adapters (Google Trends, Reddit/TikTok via Apify, News RSS, site
crawl) would replace this module while keeping the same feature interface.

It deliberately bakes in the failure modes the original spec is blind to:

  * GENUINE topics : real latent business value; multiple sources corroborate.
  * DECOY topics   : ~zero latent value, but LOUD on a single channel
                     (bot-amplified TikTok / brigaded Reddit) and uncovered on
                     the site -> the original fixed-weight scorer loves them.
  * SLEEPER topics : real value, but the search signal LAGS — early whispers
                     show up on Reddit first. Only an exploring learner catches
                     these before they're obvious.
  * COVERED topics : real demand that the site already serves well (low gap).

The latent value is HIDDEN from the engine. The engine only sees noisy signals
and must learn which signal patterns actually translate into value.
"""
from dataclasses import dataclass, field
import numpy as np

import config
from trend_detection import trend_features
from semantic import SemanticIndex


@dataclass
class Topic:
    id: int
    name: str
    category: str
    kind: str                 # 'genuine' | 'decoy' | 'sleeper' | 'covered'
    latent_value: float       # HIDDEN ground-truth business value (0..1)
    effort: str               # 'low' | 'med' | 'high'
    demand_text: str          # what people are actually asking about
    rise_week: int = 0        # week at which real search interest starts rising
    base_search: float = 30.0
    profile: dict = field(default_factory=dict)  # per-source signal tendencies


# Vocabulary fragments used to synthesise believable demand text per topic.
_THEMES = {
    "genuine": ["split level homes sloping block design floor plans",
                "knockdown rebuild process timeline council approval",
                "house and land package inclusions hidden upgrades",
                "double storey home designs facade options price",
                "custom home builder fixed price contract stages",
                "first home buyer grant eligibility deposit guide"],
    "decoy":   ["viral tiny house tour aesthetic mood lighting trend",
                "celebrity mansion walkthrough dramatic reveal reaction",
                "satisfying pour concrete slab oddly relaxing clip",
                "luxury kitchen splashback colour trend gone wrong"],
    "sleeper": ["sloping block retaining wall site cost surprise budget",
                "build delay compensation liquidated damages clause",
                "structural engineer report sloping site foundation cost",
                "owner builder finance valuation progress payment gap"],
    "covered": ["display home opening hours appointment locations",
                "single storey home designs popular four bedroom"],
}


def _series_for(topic: Topic, week: int, rng: np.random.Generator) -> np.ndarray:
    """Build a 90-day daily search series whose shape matches the topic kind/week."""
    n = config.SETTINGS["trends_series_len"]
    t = np.arange(n)
    weekly = 6.0 * np.sin(2 * np.pi * t / 7.0)          # weekday seasonality
    noise = rng.normal(0, 4.0, n)
    base = topic.base_search

    if topic.kind in ("genuine", "covered"):
        # A real, corroborated rise that has been building for a while.
        active = max(0, week - topic.rise_week)
        ramp = np.clip((t - (n - 35 - 4 * active)) / 35.0, 0, 1) * (22 + 3 * active)
        return base + ramp + weekly + noise
    if topic.kind == "sleeper":
        # Search interest only starts climbing once `rise_week` is reached.
        if week < topic.rise_week:
            return base + weekly + noise                # still flat in search
        active = week - topic.rise_week
        ramp = np.clip((t - (n - 18 - 3 * active)) / 18.0, 0, 1) * (10 + 4 * active)
        return base + ramp + weekly + noise
    # decoy: no genuine search rise at all (the hype lives off-search)
    return base + weekly + noise


def _agreement(trend_s: float, reddit_g: float, tiktok_v: float, news_r: float) -> float:
    """How well do INDEPENDENT sources corroborate? Low when only one is loud."""
    arr = np.array([trend_s, reddit_g, tiktok_v, news_r])
    frac_high = float((arr > 0.5).mean())               # breadth of agreement
    dispersion = 1.0 - min(1.0, float(arr.std()) / 0.35)  # penalise lone spikes
    return float(np.clip(0.5 * frac_high + 0.5 * dispersion, 0.0, 1.0))


def build_world(seed: int = None):
    """Construct topics + a semantic index over the (already-built) site pages."""
    seed = config.SETTINGS["seed"] if seed is None else seed
    rng = np.random.default_rng(seed)

    topics, name_id = [], 0

    def add(kind, n, value_range, efforts, rise_choices):
        nonlocal name_id
        for _ in range(n):
            theme = _THEMES[kind][rng.integers(len(_THEMES[kind]))]
            cat = config.CATEGORIES[rng.integers(len(config.CATEGORIES))]
            topics.append(Topic(
                id=name_id,
                name=f"{cat}: {' '.join(theme.split()[:3])}",
                category=cat,
                kind=kind,
                latent_value=float(rng.uniform(*value_range)),
                effort=str(rng.choice(efforts)),
                demand_text=theme + " " + " ".join(rng.choice(theme.split(), 3)),
                rise_week=int(rng.choice(rise_choices)),
                base_search=float(rng.uniform(20, 45)),
                profile={"jitter": float(rng.uniform(0.04, 0.10))},
            ))
            name_id += 1

    add("genuine", 50, (0.55, 0.92), ["low", "med"],        [0, 0, 1])
    add("decoy",   20, (0.00, 0.08), ["med", "high"],        [0])
    add("sleeper", 20, (0.60, 0.88), ["low", "med"],         [3, 4, 5, 6])
    # A handful of pages the site already serves well (low gap, real value).
    add("covered", 0,  (0.50, 0.80), ["low"],                [0])

    # The site currently has pages on these themes (=> low semantic gap there).
    existing_pages = [
        "display home locations opening hours book appointment visit",
        "single storey home designs four bedroom family floor plans price",
        "double storey home designs modern facade upstairs living",
        "house and land packages estates move in ready turnkey",
        "first home buyer information loans deposit getting started",
    ]
    fit_corpus = existing_pages + [t.demand_text for t in topics]
    index = SemanticIndex(existing_pages, fit_corpus=fit_corpus)

    return topics, index, rng


def observe(topic: Topic, index: SemanticIndex, week: int,
            rng: np.random.Generator) -> dict:
    """Produce this week's OBSERVABLE signals + assembled context vector for a topic."""
    j = topic.profile["jitter"]
    series = _series_for(topic, week, rng)
    tf = trend_features(series)

    # Per-source signals, generated from the topic's hidden kind (+ realistic noise).
    if topic.kind == "decoy":
        reddit_growth = float(np.clip(rng.normal(0.78, j), 0, 1))   # brigaded
        tiktok_velocity = float(np.clip(rng.normal(0.88, j), 0, 1)) # bot-amplified
        news_relevance = float(np.clip(rng.normal(0.15, j), 0, 1))
        reddit_neg = float(np.clip(rng.normal(0.30, j), 0, 1))
    elif topic.kind == "sleeper":
        early = week < topic.rise_week
        reddit_growth = float(np.clip(rng.normal(0.70 if early else 0.80, j), 0, 1))
        tiktok_velocity = float(np.clip(rng.normal(0.45, j), 0, 1))
        news_relevance = float(np.clip(rng.normal(0.40, j), 0, 1))
        reddit_neg = float(np.clip(rng.normal(0.55, j), 0, 1))      # pain/complaints
    elif topic.kind == "covered":
        reddit_growth = float(np.clip(rng.normal(0.55, j), 0, 1))
        tiktok_velocity = float(np.clip(rng.normal(0.45, j), 0, 1))
        news_relevance = float(np.clip(rng.normal(0.45, j), 0, 1))
        reddit_neg = float(np.clip(rng.normal(0.25, j), 0, 1))
    else:  # genuine
        reddit_growth = float(np.clip(rng.normal(0.66, j), 0, 1))
        tiktok_velocity = float(np.clip(rng.normal(0.60, j), 0, 1))
        news_relevance = float(np.clip(rng.normal(0.55, j), 0, 1))
        reddit_neg = float(np.clip(rng.normal(0.30, j), 0, 1))

    gap = index.gap(topic.demand_text)
    agreement = _agreement(tf["trend_surprise"], reddit_growth, tiktok_velocity,
                           news_relevance)

    signals = {
        "trend_surprise": tf["trend_surprise"],
        "trend_changepoint": tf["trend_changepoint"],
        "reddit_growth": reddit_growth,
        "reddit_neg_sentiment": reddit_neg,
        "tiktok_velocity": tiktok_velocity,
        "news_relevance": news_relevance,
        "semantic_gap": gap,
        "cross_source_agreement": agreement,
    }
    # Context vector in the exact FEATURE_NAMES order (bias first).
    x = [1.0] + [signals[f] for f in config.FEATURE_NAMES[1:]]
    return {"x": x, "signals": signals, "gap": gap}


def realised_reward(topic: Topic, gap: float, rng: np.random.Generator) -> float:
    """
    Net value actually produced by acting on a topic (HIDDEN from the engine
    until observed). Value scales with latent worth AND with how under-served
    the topic was, minus execution effort, plus measurement noise.
    """
    captured = topic.latent_value * (0.40 + 0.60 * gap)
    net = captured - config.EFFORT_COST[topic.effort] + rng.normal(0, 0.04)
    return float(np.clip(net, config.REWARD_MIN, config.REWARD_MAX))
