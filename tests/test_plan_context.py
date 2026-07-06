"""The plan must not push 'strengthen X' where JB already leads. The competitive
context (from the Ahrefs exports) flags leaders vs wide-open categories."""
import engine_service


def test_context_flags_leader_and_downweights():
    ctx = engine_service.ENGINE._category_context()
    assert ctx, "expected context from the committed Ahrefs exports"
    hp = ctx.get("headphones")
    comp = ctx.get("computers")
    assert hp and comp
    # JB covers Headphones well (few gaps + real traffic) -> flagged as leader, down-weighted
    assert hp["leads"] is True
    assert hp["mult"] < 1.0
    assert hp["note"] == "you already lead here"
    # Computers is wide open (many gaps) -> not a leader, lifted above the leader
    assert comp["leads"] is False
    assert comp["mult"] > hp["mult"]


def test_top_gap_names_a_specific_page_per_category():
    top = engine_service.ENGINE._top_gap_by_category()
    assert top, "expected a top gap per category from the committed export"
    # each category maps to a SPECIFIC missing page (a keyword + a content type),
    # not the generic category name
    for cat, gap in top.items():
        assert gap["keyword"] and gap["type"] and gap["competitors"]
        assert gap["keyword"].lower() != cat.lower()


def test_stronger_gap_outranks_weaker_by_value():
    # the plan ranks by the gap's real value: TVs ('qled vs oled', 5.6k) must beat
    # Laptops (whose best gap is only 'oled laptop', 500/mo)
    top = engine_service.ENGINE._top_gap_by_category()
    assert top["TVs"]["score"] > top["Laptops"]["score"]
    assert top["Computers"]["score"] > top["Laptops"]["score"]   # 'best uhd monitors' 16k
