"""
Central configuration for the Market Intelligence Engine (upgraded).

Everything tunable lives here so the rest of the code stays clean.
"""

# ----- Client category framework (Home Builder example from the original spec) -----
CATEGORIES = [
    "Home Builder", "House and Land Packages", "Display Homes", "Knockdown Rebuild",
    "Townhouse Builder", "Home Designs", "Single Storey Homes", "Double Storey Homes",
    "Custom Homes", "First Home Buyers", "Building Costs", "Sustainable Homes",
]

# ----- Context-feature schema used by the learning engine -----
# The order here is the order of the context vector x fed to the bandit.
FEATURE_NAMES = [
    "bias",                    # constant 1.0 (intercept term)
    "trend_surprise",          # deseasonalised, robust search-demand surprise (0..1)
    "trend_changepoint",       # CUSUM change-point strength (0..1)
    "reddit_growth",           # growth in relevant Reddit discussion volume (0..1)
    "reddit_neg_sentiment",    # share of negative sentiment -> reputation-risk signal (0..1)
    "tiktok_velocity",         # view/engagement velocity on TikTok (0..1)
    "news_relevance",          # relevance of recent Google News items (0..1)
    "semantic_gap",            # 1 - best cosine match to existing site content (0..1)
    "cross_source_agreement",  # do *independent* sources corroborate? (0..1)
]
N_FEATURES = len(FEATURE_NAMES)

# ----- The ORIGINAL design's hand-picked weights (used by the baseline policy) -----
# Mapped from the spec's "Opportunity Scoring System":
#   Search Demand 30%, Website Gap 25%, Reddit 15%, TikTok 15%, News 10%, Business 5%.
# Note what it CANNOT express: change-points, sentiment, or cross-source agreement.
STATIC_WEIGHTS = {
    "trend_surprise":     0.30,
    "semantic_gap":       0.25,
    "reddit_growth":      0.15,
    "tiktok_velocity":    0.15,
    "news_relevance":     0.10,
    # "business_priority" 0.05 folded into a constant; the rest are unrepresentable.
}

# ----- Effort model (the original spec scores value but ignores effort) -----
EFFORT_COST = {"low": 0.03, "med": 0.07, "high": 0.12}

# ----- Reward scale: the NET realised value one action can produce -----
# Acting on a worthless, high-effort topic is a net LOSS, so the floor is below
# zero. The live API and dashboard use this same range, so a recorded "flop" is
# a genuine loss — exactly the signal the model was trained on.
REWARD_MIN = -0.15
REWARD_MAX = 1.0

# ----- Engine / simulation settings -----
SETTINGS = {
    "seed": 7,
    "weeks": 20,            # simulated planning horizon
    "weekly_budget": 3,     # how many actions the team can execute per week
    "linucb_alpha": 0.65,   # exploration strength (higher = explore more)
    "portfolio_sim_threshold": 0.78,  # block near-duplicate picks within one week
    "trends_series_len": 90,          # days of search history per topic
}
