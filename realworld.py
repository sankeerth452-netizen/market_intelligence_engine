"""
realworld.py
------------
Assembles REAL candidates for the engine from the live adapters, in exactly the
shape recommender.recommend() expects — so the same bandit + recommender that run
on the synthetic world run on real signals, with nothing downstream changed.

Live now: news_relevance (Google News), semantic_gap (site crawl / demo site).
Not-yet-wired signals (trends, reddit, tiktok) default to a neutral 0.5 and are
flagged, so the engine simply has less to go on for those until they're added.
Synthetic mode stays the default; real mode is opt-in (DATA_MODE=real).
"""
import os

import numpy as np

import config
from world import Topic
import adapters

NEUTRAL = 0.5  # "unknown / not yet wired" for signals we don't have live yet


def _effort_for(gap: float) -> str:
    # a brand-new page (high gap) is more work than refreshing an existing one
    return "high" if gap > 0.75 else ("med" if gap > 0.45 else "low")


def real_candidates(site_url=None):
    """Fetch live signals for each monitored category, assembled as candidates."""
    site_url = site_url or os.environ.get("SITE_URL")
    demands = [c.lower() for c in config.CATEGORIES]
    index, site_label = adapters.build_site_index(site_url, extra_corpus=demands)

    cands = []
    for i, cat in enumerate(config.CATEGORIES):
        gap = adapters.semantic_gap(cat.lower(), index)
        news = adapters.news_relevance(cat)
        news = NEUTRAL if news is None else news
        signals = {
            "trend_surprise": NEUTRAL,
            "trend_changepoint": NEUTRAL,
            "reddit_growth": NEUTRAL,
            "reddit_neg_sentiment": NEUTRAL,
            "tiktok_velocity": NEUTRAL,
            "news_relevance": news,
            "semantic_gap": gap,
            "cross_source_agreement": NEUTRAL,   # needs >=2 independent live sources
        }
        x = [1.0] + [signals[f] for f in config.FEATURE_NAMES[1:]]
        topic = Topic(id=i, name=cat, category=cat, kind="real",
                      latent_value=0.0, effort=_effort_for(gap),
                      demand_text=cat.lower())
        cands.append({"topic": topic, "x": x, "signals": signals, "gap": gap})
    return cands, index, site_label


def real_brief(bandit, k=3, site_url=None):
    """Rank the real candidates with the (already-trained) bandit + recommender."""
    import recommender as rec
    cands, index, label = real_candidates(site_url)
    return rec.recommend(cands, bandit, index, k), label


if __name__ == "__main__":   # end-to-end: synthetic-trained bandit on REAL signals
    import numpy as np
    from world import build_world
    from bandit import LinUCB
    from engine_core import run_loop_training
    import recommender as rec

    # Train the bandit on the synthetic world (as the app does), then point it at
    # live data — this is the real morning brief the deployed app would produce.
    topics, index, _ = build_world()
    rng = np.random.default_rng(config.SETTINGS["seed"] + 1)
    bandit = LinUCB(config.N_FEATURES, alpha=config.SETTINGS["linucb_alpha"])
    run_loop_training(topics, index, config.SETTINGS["weeks"],
                      config.SETTINGS["weekly_budget"], rng, bandit)

    picks, label = real_brief(bandit, k=5)
    print(f"\nREAL morning brief  (site: {label})\n" + "-" * 64)
    for i, p in enumerate(picks, 1):
        s = p["signals"]
        print(f"{i}. {p['topic'].name}   [ROI {p['roi']:.2f}, gap {s['semantic_gap']:.2f}, "
              f"news {s['news_relevance']:.2f}, {p['topic'].effort} effort]")
        print(f"   {rec.rationale(s, p['pred'], p['topic'].effort, p['exploring'])}")
