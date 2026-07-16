"""Tests for the voice_calls module."""


from openpup.voice_calls import CallRequest, build_twiml, place_call


class TestPlaceCall:
    def test_missing_to(self):
        r = place_call(CallRequest(to=""))
        assert not r.ok
        assert "missing 'to'" in r.error

    def test_missing_from_number(self, monkeypatch):
        monkeypatch.delenv("OPENPUP_TWILIO_FROM_NUMBER", raising=False)
        r = place_call(CallRequest(to="+15551234567"))
        assert not r.ok
        assert "FROM number" in r.error

    def test_explicit_from_number(self, monkeypatch):
        monkeypatch.delenv("OPENPUP_TWILIO_FROM_NUMBER", raising=False)
        r = place_call(
            CallRequest(to="+15551234567", message="hi"),
            from_number="+15559999999",
        )
        assert r.ok
        assert r.call_sid.startswith("STUB-")
        assert r.to == "+15551234567"

    def test_env_from_number(self, monkeypatch):
        monkeypatch.setenv("OPENPUP_TWILIO_FROM_NUMBER", "+15559999999")
        r = place_call(CallRequest(to="+15551234567"))
        assert r.ok


class TestTwiML:
    def test_basic(self):
        xml = build_twiml("Hello, world!")
        assert xml.startswith("<?xml")
        assert "<Response>" in xml
        assert "<Say>Hello, world!</Say>" in xml

    def test_escaping(self):
        xml = build_twiml("a < b & c > d")
        assert "&lt;" in xml
        assert "&amp;" in xml
        assert "&gt;" in xml
        # Should not contain raw < or > or &.
        for fragment in ["a < b", "c > d"]:
            assert fragment not in xml
