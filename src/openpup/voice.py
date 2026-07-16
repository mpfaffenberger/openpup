"""Voice transcription + text-to-speech for OpenPup.

A small, dependency-light facade so the pup can transcribe inbound voice notes
and reply with synthesized speech when the platform supports it. Both
backends are pluggable:

* Transcription: ``faster-whisper`` (local, recommended) or a hosted API stub.
* TTS: ``pyttsx3`` (local, recommended) or a hosted API stub.

If neither backend is installed, :func:`is_available` returns False and the
agent gracefully falls back to text-only replies.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

logger = logging.getLogger("openpup.voice")

# Default models (small = fast, medium = balanced).
DEFAULT_TRANSCRIBE_MODEL = "small"
DEFAULT_TRANSCRIBE_LANGUAGE = "en"

# Try imports lazily so the base install doesn't need these.
try:
    import faster_whisper  # noqa: F401

    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False

try:
    import pyttsx3  # noqa: F401

    HAS_TTS = True
except ImportError:
    HAS_TTS = False


# ---------------------------------------------------------------------------
# Detection / availability
# ---------------------------------------------------------------------------
def is_available() -> bool:
    """True if either transcription or TTS can run locally."""
    return HAS_WHISPER or HAS_TTS


def transcription_available() -> bool:
    return HAS_WHISPER


def tts_available() -> bool:
    return HAS_TTS


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------
class TranscriptionResult:
    def __init__(self, text: str, language: str = "", confidence: float = 0.0) -> None:
        self.text = text
        self.language = language
        self.confidence = confidence

    def __repr__(self) -> str:
        return f"TranscriptionResult(text={self.text!r}, language={self.language}, confidence={self.confidence})"


def transcribe(
    source,  # bytes or Path
    *,
    model: str = DEFAULT_TRANSCRIBE_MODEL,
    language: str = DEFAULT_TRANSCRIBE_LANGUAGE,
) -> TranscriptionResult:
    """Transcribe audio bytes (or a file path) to text.

    Returns a :class:`TranscriptionResult`. The language hint is optional and
    improves accuracy when known.
    """
    if not HAS_WHISPER:
        raise RuntimeError(
            "voice transcription needs faster-whisper. "
            "Install with: pip install 'openpup[voice]'"
        )

    audio_path: Path
    if isinstance(source, (bytes, bytearray)):
        # Write to a temp file (faster-whisper needs a file or numpy array).
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(bytes(source))
            audio_path = Path(f.name)
    elif isinstance(source, (str, Path)):
        audio_path = Path(source)
    else:
        raise TypeError(f"unsupported source type {type(source).__name__}")

    try:
        from faster_whisper import WhisperModel

        model_obj = WhisperModel(model, device="auto", compute_type="auto")
        segments, info = model_obj.transcribe(
            str(audio_path),
            language=language if language else None,
            vad_filter=True,
        )
        text_parts = []
        conf_sum = 0.0
        n = 0
        for seg in segments:
            text_parts.append(seg.text)
            if getattr(seg, "avg_logprob", None) is not None:
                import math

                conf_sum += math.exp(seg.avg_logprob)
                n += 1
        text = " ".join(t.strip() for t in text_parts).strip()
        confidence = (conf_sum / n) if n else 0.0
        return TranscriptionResult(
            text=text,
            language=info.language if info else language,
            confidence=confidence,
        )
    finally:
        if audio_path.exists() and "tmp" in str(audio_path):
            audio_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------
def speak(text: str, *, voice: str = "") -> bytes:
    """Synthesize ``text`` to audio bytes (WAV, 16-bit PCM)."""
    if not HAS_TTS:
        raise RuntimeError(
            "voice synthesis needs pyttsx3. "
            "Install with: pip install 'openpup[voice]'"
        )
    import pyttsx3

    engine = pyttsx3.init()
    if voice:
        for v in engine.getProperty("voices"):
            if voice.lower() in (v.name or "").lower():
                engine.setProperty("voice", v.id)
                break
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        out_path = Path(f.name)
    try:
        engine.save_to_file(text, str(out_path))
        engine.runAndWait()
        data = out_path.read_bytes()
        return data
    finally:
        out_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Voice-note detection
# ---------------------------------------------------------------------------
VOICE_EXTENSIONS = {".ogg", ".oga", ".opus", ".wav", ".mp3", ".m4a", ".webm", ".mp4"}


def looks_like_voice_note(filename: str) -> bool:
    """Heuristic: does this filename look like a voice note?"""
    if not filename:
        return False
    ext = Path(filename).suffix.lower()
    return ext in VOICE_EXTENSIONS
