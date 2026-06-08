from openpup.messaging.envelope import Direction, Envelope


def test_address_and_reply():
    inbound = Envelope(platform="telegram", channel="123", sender="alice", text="hi")
    assert inbound.address == "telegram:123"
    assert inbound.direction == Direction.INBOUND

    out = inbound.reply("hello back")
    assert out.direction == Direction.OUTBOUND
    assert out.platform == "telegram"
    assert out.channel == "123"
    assert out.text == "hello back"


def test_to_factory():
    out = Envelope.to("discord:998877", "yo", subject="x")
    assert out.platform == "discord"
    assert out.channel == "998877"
    assert out.direction == Direction.OUTBOUND
    assert out.meta["subject"] == "x"


def test_to_factory_handles_missing_colon():
    out = Envelope.to("weird", "text")
    assert out.platform == "weird"
    assert out.channel == ""
