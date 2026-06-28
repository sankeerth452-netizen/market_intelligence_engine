"""The assistant must answer from the data, rule-based, with no LLM key (offline)."""
import assistant

_CTX = {
    "client": "Acme",
    "items": [
        {"topic": "TVs", "category": "TVs", "roi": 0.72,
         "value": 0.6, "signals": {"trend_surprise": 0.9, "news_relevance": 1.0, "semantic_gap": 0.4}},
        {"topic": "Drones", "category": "Drones", "roi": 0.5,
         "value": 0.3, "signals": {"trend_surprise": 0.2, "news_relevance": 0.3, "semantic_gap": 0.9}},
    ],
    "weights": [{"name": "semantic_gap", "weight": 0.33}, {"name": "tiktok_velocity", "weight": -0.29}],
    "model_updates": 60,
    "robustness": {"lift_mean": 40, "wins": 30, "n": 30},
}


def test_proof_question_cites_the_lift():
    a = assistant._rule_answer("does it actually work?", _CTX)
    assert "40" in a and "30/30" in a


def test_learning_question_cites_weights():
    a = assistant._rule_answer("what has it learned?", _CTX)
    assert "gaps on your site" in a.lower()   # plain label for semantic_gap


def test_gaps_question_names_the_gap_category():
    a = assistant._rule_answer("where are the content gaps?", _CTX)
    assert "Drones" in a


def test_category_question_is_answered():
    a = assistant._rule_answer("how is TVs doing?", _CTX)
    assert "TVs" in a and "priority" in a.lower()


def test_empty_question_offers_help():
    assert len(assistant._rule_answer("", _CTX)) > 0
