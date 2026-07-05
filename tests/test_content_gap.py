"""Content-gap ingestion + runtime: relevance filtering must reject noise, and the
committed derived JSON must load with a sane shape."""
import import_ahrefs as imp
import content_gap


def test_categorise_maps_real_electronics():
    assert imp.categorise("best gaming monitor") == "Gaming"
    assert imp.categorise("qled vs oled") == "TVs"
    assert imp.categorise("noise cancelling headphones") == "Headphones"
    assert imp.categorise("best uhd monitors") == "Computers"
    assert imp.categorise("ipad air") == "Tablets"
    assert imp.categorise("clear phone case") == "Phones"


def test_categorise_rejects_noise():
    # furniture / cleaning / stationery / services / substring-accidents must NOT map
    for junk in ["dishwasher tablets", "tv unit", "tv console", "a5 notebook",
                 "megaphone", "computer repairs near me", "ear camera", "baby monitor"]:
        assert imp.categorise(junk) is None, junk


def test_content_type_classifies_intent():
    assert imp.content_type("qled vs oled") == "Comparison page"
    assert imp.content_type("best gaming monitors under 500") == "Buying guide"
    assert imp.content_type("how to set up a soundbar") == "Guide / FAQ"
    assert imp.content_type("4k tv sale") == "Category / deals page"


def test_runtime_loads_committed_json():
    assert content_gap.available() is True
    d = content_gap.content_gaps()
    assert d["kept"] > 0 and d["opportunities"]
    for o in d["opportunities"]:
        # every kept opportunity is category-mapped, has a ranking competitor, has a score
        assert o["category"]
        assert o["competitors"]
        assert o["score"] > 0
        assert o["volume"] >= imp.MIN_VOLUME


def test_top_pages_and_strengths_present():
    tp = content_gap.top_pages()
    assert "JB Hi-Fi" in tp["sites"]
    assert tp["jb_strengths"]         # JB category strengths derived from its top pages
