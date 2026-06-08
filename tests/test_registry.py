import pytest

from openpup.messaging.envelope import Envelope
from openpup.messaging.registry import PlatformRegistry


class FakeAdapter:
    def __init__(self, name):
        self.name = name
        self.sent = []

    async def send(self, envelope):
        self.sent.append(envelope)


@pytest.mark.asyncio
async def test_register_and_send():
    reg = PlatformRegistry()
    adapter = FakeAdapter("telegram")
    reg.register(adapter)
    assert "telegram" in reg.platforms()

    ok = await reg.send(Envelope.to("telegram:1", "hi"))
    assert ok is True
    assert adapter.sent[0].text == "hi"


@pytest.mark.asyncio
async def test_send_unknown_platform_returns_false():
    reg = PlatformRegistry()
    ok = await reg.send(Envelope.to("nope:1", "hi"))
    assert ok is False


@pytest.mark.asyncio
async def test_inbound_dispatch():
    reg = PlatformRegistry()
    received = []

    async def handler(env):
        received.append(env)

    reg.set_inbound_handler(handler)
    await reg.dispatch_inbound(Envelope(platform="sms", channel="+1", text="yo"))
    assert received[0].text == "yo"


@pytest.mark.asyncio
async def test_inbound_without_handler_is_safe():
    reg = PlatformRegistry()
    # should not raise
    await reg.dispatch_inbound(Envelope(platform="sms", channel="+1", text="yo"))
