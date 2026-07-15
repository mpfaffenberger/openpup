"""Tests for the voice module.

Covers availability detection, voice-note filename detection, and graceful
errors when backends aren't installed.
"""

import pytest

from openpup import voice
from openpup.voice import (
    DEFAULT_TRANSCRIBE_LANGUAGE,
    DEFAULT_TRANSCRIBE_MODEL,
    TranscriptionResult,
    is_available,
    looks_like_voice_note,
    speak,
    transcription_available,
    transcribe,
    tts_available,
)


class TestAvailability:
    def test_module_loads(self):
        # Just importing should be fine even without the dep.
        assert voice is not None

    def test_unavailable_raises_helpful_error(self):
        if not transcription_available():
            with pytest.raises(RuntimeError, match="pip install"):
                transcribe(b"x")
            with pytest.raises(RuntimeError, match="pip install"):
                speak("hello")


class TestVoiceNoteDetection:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("voice.ogg", True),
            ("recording.opus", True),
            ("audio.wav", True),
            ("sound.mp3", True),
            ("recording.m4a", True),
            ("recording.webm", True),
            ("recording.mp4", True),
            ("", False),
            ("photo.jpg", False),
            ("document.pdf", False),
            ("file.txt", False),
        ],
    )
    def test_filename_heuristic(self, name, expected):
        assert looks_like_voice_note(name) is expected


class TestTranscriptionResult:
    def test_repr_includes_text(self):
        r = TranscriptionResult("hello world", language="en", confidence=0.95)
        r2 = repr(r)
        assert "hello world" in r2
        assert "en" in r2


class TestDefaults:
    def test_default_model_is_set(self):
        assert DEFAULT_TRANSCRIBE_MODEL
        assert DEFAULT_TRANSCRIBE_LANGUAGE


class TestIsAvailable:
    def test_returns_bool(self):
        assert isinstance(is_available(), bool)
        assert isinstance(transcription_available(), bool)
        assert isinstance(tts_available(), bool)


# Skip the import availability probe if the dep isn't there.
def test_module_imports_without_dep():
    # Sanity check that we can import even without faster-whisper / pyttsx3.
    assert hasattr(voice, "transcribe")
    assert hasattr(voice, "speak")
