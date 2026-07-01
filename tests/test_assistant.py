"""The assistant must answer from the data, rule-based, with no LLM key (offline).
Now retrieval-augmented (RAG): it retrieves the relevant real facts, then answers."""
import assistant

_DOCS = [
    {"title": "Category — TVs", "text": "TVs — High priority. Search demand 90/100. Real search volume about 4,300 per month."},
    {"title": "Competitor — Harvey Norman", "text": "Harvey Norman (data via Ahrefs): 1,000 pages tracked. Recently published pages: new tv range."},
    {"title": "AI visibility — share of voice", "text": "How often each brand appears when shoppers ask AI assistants (ChatGPT, Australia): JB Hi-Fi 67%, Harvey Norman 35%. Higher is better."},
    {"title": "What the system has learned", "text": "Learned from 60 real results: gaps on your site most reliably pays off."},
]

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


def test_proof_question_describes_validation():
    a = assistant._rule_answer("does it actually work?", _CTX)
    assert "30" in a and "validat" in a.lower()   # non-comparative, client-facing


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


# ---- RAG: retrieval + answering from retrieved facts -----------------------
def test_retrieve_ranks_ai_visibility_for_that_query():
    hits = assistant.retrieve("what's our AI share of voice?", _DOCS)
    assert hits and "AI visibility" in hits[0]["title"]


def test_retrieve_finds_competitor_doc():
    hits = assistant.retrieve("what are competitors publishing?", _DOCS)
    assert any("Competitor" in h["title"] for h in hits)


def test_rule_answer_uses_retrieved_ai_visibility_fact():
    retrieved = assistant.retrieve("what's our AI share of voice?", _DOCS)
    a = assistant._rule_answer("what's our AI share of voice?", _CTX, retrieved)
    assert "67%" in a                       # answered straight from the retrieved fact


def test_answer_grounds_competitor_question_offline(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    a = assistant.answer("what are competitors publishing?", _CTX, _DOCS)
    assert "Harvey Norman" in a             # retrieved the competitor fact, no LLM key


def test_category_question_prefers_rich_retrieved_fact():
    retrieved = assistant.retrieve("how are TVs doing?", _DOCS)
    a = assistant._rule_answer("how are TVs doing?", _CTX, retrieved)
    assert "4,300 per month" in a           # the rich fact (volume) beats the short computed answer
