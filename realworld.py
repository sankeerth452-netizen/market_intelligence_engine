"""
realworld.py
------------
Assembles REAL candidates for the engine from the live adapters + the client's
website, in the exact shape recommender.recommend() expects — so the same
synthetic-trained bandit + recommender run on real signals, unchanged.

Everything client-specific comes from the active ClientConfig (categories, site
URL); the engine stays client-agnostic. Live signals: news_relevance (Google
News) and semantic_gap (the client's crawled site, or the demo site when no
SITE_URL is configured). Trends/Reddit/TikTok default to a neutral 0.5 until
wired. Synthetic mode stays the default; real mode is opt-in (DATA_MODE=real).
"""
import config
import client_config
import crawler
import demo_client
import adapters
import apify
from semantic import SemanticIndex
from world import Topic

NEUTRAL = 0.5  # "unknown / not yet wired" for signals we don't have live yet


def _effort_for(gap: float) -> str:
    # a brand-new page (high gap) is more work than refreshing an existing one
    return "high" if gap > 0.75 else ("med" if gap > 0.45 else "low")


def site_index(client, extra_corpus=None):
    """Build a SemanticIndex over the client's site content. Crawls client.site_url
    when set (falling back to the demo site on any failure / empty crawl), else
    uses the built-in demo site. Returns (index, human-readable source label)."""
    pages, label = None, None
    if client.site_url:
        slugs = crawler.sitemap_corpus(client.site_url)      # broad, robots-friendly
        if slugs:
            pages, label = slugs, f"{client.site_url} — {len(slugs)} pages from sitemap"
        else:
            crawled = crawler.crawl(client.site_url)          # fall back to page text
            if crawled:
                pages, label = crawled, f"{client.site_url} — {len(crawled)} pages crawled"
    if pages is None:
        pages, label = demo_client.DEMO_SITE_PAGES, "demo site (built-in; set SITE_URL for a real client)"
    corpus = list(pages) + list(extra_corpus or [])
    # char n-grams: robust to plural/morphology when matching real catalog slugs
    return SemanticIndex(pages, fit_corpus=corpus, char_ngrams=True), label


def real_candidates(client=None):
    """Live candidates for the active client's category framework."""
    client = client or client_config.active_client()
    demands = [c.lower() for c in client.categories]
    index, label = site_index(client, extra_corpus=demands)

    cands = []
    for i, cat in enumerate(client.categories):
        gap = index.gap(cat.lower())
        d = adapters.demand_signals(cat)        # one fetch: news relevance + trend
        news = NEUTRAL if d["news_relevance"] is None else d["news_relevance"]
        tr = d["trend"]
        tik = apify.tiktok_velocity(cat) if apify.enabled() else None  # real, or None
        # cross-source agreement: do the INDEPENDENT live sources corroborate?
        # (high when the real signals we actually have all point the same way)
        real_vals = []
        if tr:
            real_vals.append(tr["trend_surprise"])
        if d["news_relevance"] is not None:
            real_vals.append(news)
        if tik is not None:
            real_vals.append(tik)
        cross = round(1.0 - (max(real_vals) - min(real_vals)), 3) if len(real_vals) >= 2 else NEUTRAL
        signals = {
            "trend_surprise": tr["trend_surprise"] if tr else NEUTRAL,
            "trend_changepoint": tr["trend_changepoint"] if tr else NEUTRAL,
            "reddit_growth": NEUTRAL,
            "reddit_neg_sentiment": NEUTRAL,
            "tiktok_velocity": NEUTRAL if tik is None else tik,
            "news_relevance": news,
            "semantic_gap": gap,
            "cross_source_agreement": cross,
        }
        x = [1.0] + [signals[f] for f in config.FEATURE_NAMES[1:]]
        topic = Topic(id=i, name=cat, category=cat, kind="real",
                      latent_value=0.0, effort=_effort_for(gap),
                      demand_text=cat.lower())
        cands.append({"topic": topic, "x": x, "signals": signals, "gap": gap,
                      "headlines": d.get("headlines", [])})
    return cands, index, label


def real_brief(bandit, k=3, client=None):
    """Rank the real candidates with the (already-trained) bandit + recommender."""
    import recommender as rec
    cands, index, label = real_candidates(client)
    return rec.recommend(cands, bandit, index, k), label


if __name__ == "__main__":   # end-to-end: synthetic-trained bandit on REAL signals
    import numpy as np
    from world import build_world
    from bandit import LinUCB
    from engine_core import run_loop_training
    import recommender as rec

    client = client_config.active_client()
    topics, index, _ = build_world()
    rng = np.random.default_rng(config.SETTINGS["seed"] + 1)
    bandit = LinUCB(config.N_FEATURES, alpha=config.SETTINGS["linucb_alpha"])
    run_loop_training(topics, index, config.SETTINGS["weeks"],
                      config.SETTINGS["weekly_budget"], rng, bandit)

    picks, label = real_brief(bandit, k=5)
    print(f"\nClient: {client.name}  ({client.industry})")
    print(f"REAL morning brief  (site: {label})\n" + "-" * 64)
    for i, p in enumerate(picks, 1):
        s = p["signals"]
        print(f"{i}. {p['topic'].name}   [ROI {p['roi']:.2f}, gap {s['semantic_gap']:.2f}, "
              f"news {s['news_relevance']:.2f}, {p['topic'].effort} effort]")
        print(f"   {rec.rationale(s, p['pred'], p['topic'].effort, p['exploring'])}")
