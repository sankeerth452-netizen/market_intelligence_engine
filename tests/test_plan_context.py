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
