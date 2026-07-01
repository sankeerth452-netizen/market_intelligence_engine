"""The AI Strategist must always return a structured, grounded plan offline
(no API key) — i.e. the templated tier stands on its own, and the JSON parser
for the LLM tier is robust."""
import strategist

_ITEM = {
    "topic": "4K TVs",
    "action": "Create new page",
    "effort": "low",
    "headlines": ["Best 4K TV deals this month - example.com"],
    "signals": {"trend_surprise": 0.9, "trend_changepoint": 0.6,
                "news_relevance": 0.8, "semantic_gap": 0.7},
}


def test_template_plan_has_full_structure():
    p = strategist._template_plan(_ITEM)
    assert p["title"] and p["angle"] and p["why_now"]
    assert isinstance(p["points"], list) and 1 <= len(p["points"]) <= 4
    assert p["source"] == "template"


def test_template_plan_is_grounded_in_the_topic():
    assert "4K TVs" in strategist._template_plan(_ITEM)["title"]


def test_why_now_uses_the_real_headline():
    assert "Best 4K TV deals" in strategist._template_plan(_ITEM)["why_now"]


def test_action_plan_falls_back_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    p = strategist.action_plan(_ITEM)
    assert p["source"] == "template" and p["title"]


def test_parse_plan_extracts_json_with_fences():
    raw = 'Sure!\n```json\n{"title":"T","angle":"A","why_now":"W","points":["x","y"]}\n```'
    p = strategist._parse_plan(raw)
    assert p and p["title"] == "T" and p["points"] == ["x", "y"]


def test_parse_plan_rejects_garbage_or_incomplete():
    assert strategist._parse_plan("no json here") is None
    assert strategist._parse_plan('{"title":"only"}') is None   # missing required keys
