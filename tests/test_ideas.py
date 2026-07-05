"""Marketing-idea engine: topics discovered from gaps, many ranked ideas per topic
across lanes, grounded and well-formed."""
import ideas


def test_generate_ranked_topics_and_ideas():
    d = ideas.generate()
    assert d["available"] is True
    assert d["topic_count"] > 0 and d["idea_count"] > 0
    scores = [t["score"] for t in d["topics"]]
    assert scores == sorted(scores, reverse=True)          # topics ranked by demand


def test_every_topic_spans_lanes_and_is_well_formed():
    for t in ideas.generate()["topics"]:
        lanes = {i["lane"] for i in t["ideas"]}
        assert "SEO" in lanes and len(lanes) >= 3
        s = [i["score"] for i in t["ideas"]]
        assert s == sorted(s, reverse=True)                # ideas ranked within topic
        for i in t["ideas"]:
            for k in ("lane", "type", "what", "why", "why_now", "evidence",
                      "confidence", "impact", "effort", "score"):
                assert i.get(k) not in (None, "", [])


def test_labels_normalise_acronyms():
    assert ideas._label("oled", "TVs") == "OLED"
    assert ideas._label("ssd", "Computers") == "SSD"
    assert ideas._label("printer", "Computers") == "Printer"


def test_discover_topics_clusters_and_generates_ideas():
    opps = [
        {"keyword": "qled vs oled", "category": "TVs", "volume": 5600, "intent": ["Commercial"],
         "type": "Comparison page", "competitors": [{"name": "The Good Guys", "position": 2}]},
        {"keyword": "oled vs qled", "category": "TVs", "volume": 2400, "intent": ["Informational"],
         "type": "Comparison page", "competitors": [{"name": "The Good Guys", "position": 4}]},
    ]
    topics = ideas.discover_topics(opps)
    assert len(topics) == 1 and topics[0]["gap_count"] == 2
    lanes = {i["lane"] for i in topics[0]["ideas"]}
    assert "SEO" in lanes and "Social" in lanes          # comparison -> SEO page + short-form video
