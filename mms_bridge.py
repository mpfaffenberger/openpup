"""Host-side mmsd-tng inbox and safe attachment extraction."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger("mms_bridge")

BUSCTL = "/usr/bin/busctl"
MMS_BUS = "org.ofono.mms"
MMS_SERVICE_PATH = "/org/ofono/mms/modemmanager"
MMS_SERVICE_INTERFACE = "org.ofono.mms.Service"
DEFAULT_STORAGE_ROOT = "~/.openpup-mms/.mms/modemmanager"
DEFAULT_SPOOL_ROOT = "~/.openpup-container/mms-incoming"
DEFAULT_CONTAINER_ROOT = "/data/mms-incoming"
MAX_MESSAGE_BYTES = 1_100_000
MAX_ATTACHMENTS = 25
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_IMAGE_EXTENSIONS = {
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def _run_busctl_payload() -> dict[str, Any]:
    result = subprocess.run(
        [
            BUSCTL,
            "--user",
            "--json=short",
            "call",
            MMS_BUS,
            MMS_SERVICE_PATH,
            MMS_SERVICE_INTERFACE,
            "GetMessages",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "mmsd-tng D-Bus call failed")
    return json.loads(result.stdout)


def _unwrap(value: Any) -> Any:
    if isinstance(value, dict) and "type" in value and "data" in value:
        return _unwrap(value["data"])
    if isinstance(value, dict):
        return {key: _unwrap(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_unwrap(item) for item in value]
    return value


def _records(payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    data = _unwrap(payload.get("data", []))
    if not data or not isinstance(data[0], list):
        return []
    records = []
    for record in data[0]:
        if not isinstance(record, list) or len(record) != 2:
            continue
        path, properties = record
        if isinstance(path, str) and isinstance(properties, dict):
            records.append((path, properties))
    return records


def _message_id(object_path: str) -> str:
    message_id = object_path.rsplit("/", 1)[-1]
    if not _SAFE_ID.fullmatch(message_id):
        raise ValueError("unsafe MMS message identifier")
    return message_id


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _valid_image_magic(mime_type: str, data: bytes) -> bool:
    if mime_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if mime_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if mime_type == "image/gif":
        return data.startswith((b"GIF87a", b"GIF89a"))
    if mime_type == "image/webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


class MMSInbox:
    """Read completed mmsd messages and extract safe parts into a spool."""

    def __init__(
        self,
        storage_root: str | Path | None = None,
        spool_root: str | Path | None = None,
        container_root: str | Path = DEFAULT_CONTAINER_ROOT,
    ) -> None:
        storage = storage_root or os.environ.get("OPENPUP_MMS_STORAGE", DEFAULT_STORAGE_ROOT)
        spool = spool_root or os.environ.get("OPENPUP_MMS_SPOOL", DEFAULT_SPOOL_ROOT)
        self.storage_root = Path(storage).expanduser().resolve()
        self.spool_root = Path(spool).expanduser().resolve()
        self.container_root = Path(container_root)
        self.spool_root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def health(self) -> dict[str, Any]:
        try:
            payload = _run_busctl_payload()
            return {
                "status": "ok",
                "mmsd": True,
                "messages": len(_records(payload)),
            }
        except Exception as exc:
            return {"status": "degraded", "mmsd": False, "error": str(exc)}

    def poll(self, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        source = payload if payload is not None else _run_busctl_payload()
        messages = []
        for object_path, properties in _records(source):
            if str(properties.get("Status", "")).lower() != "received":
                continue
            try:
                message = self._extract_message(object_path, properties)
            except Exception:
                logger.exception("Failed to extract MMS %s", object_path)
                continue
            if message is not None:
                messages.append(message)
        return messages

    def acknowledge(self, message_id: str) -> bool:
        if not _SAFE_ID.fullmatch(message_id):
            return False
        message_dir = self.spool_root / message_id
        if not message_dir.is_dir():
            return False
        marker = message_dir / ".acknowledged"
        marker.write_text("ok\n", encoding="utf-8")
        return True

    def _extract_message(
        self,
        object_path: str,
        properties: dict[str, Any],
    ) -> dict[str, Any] | None:
        message_id = _message_id(object_path)
        message_dir = self.spool_root / message_id
        if (message_dir / ".acknowledged").exists():
            return None
        message_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

        parts = properties.get("Attachments", [])
        if not isinstance(parts, list) or len(parts) > MAX_ATTACHMENTS:
            raise ValueError("invalid MMS attachment list")

        attachments = []
        text_parts = []
        total_bytes = 0
        for index, part in enumerate(parts, start=1):
            if not isinstance(part, list) or len(part) != 5:
                continue
            _, raw_mime, raw_path, raw_offset, raw_length = part
            mime_type = str(raw_mime).split(";", 1)[0].strip().lower()
            source_path = Path(str(raw_path)).expanduser().resolve()
            offset = int(raw_offset)
            length = int(raw_length)
            total_bytes += length
            if total_bytes > MAX_MESSAGE_BYTES:
                raise ValueError("MMS exceeds configured size limit")
            data = self._read_part(source_path, offset, length)

            if mime_type == "text/plain":
                text_parts.append(data.decode("utf-8", errors="replace").strip())
                continue
            extension = _IMAGE_EXTENSIONS.get(mime_type)
            if not extension or not _valid_image_magic(mime_type, data):
                logger.warning("Ignoring unsupported MMS part type %s", mime_type)
                continue

            filename = f"image-{index:02d}{extension}"
            destination = message_dir / filename
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            temporary.write_bytes(data)
            temporary.chmod(0o600)
            temporary.replace(destination)
            attachments.append(
                {
                    "path": str(self.container_root / message_id / filename),
                    "mime_type": mime_type,
                    "size": len(data),
                    "source": "mms",
                }
            )

        subject = str(properties.get("Subject", "")).strip()
        text = "\n".join(part for part in text_parts if part)
        if subject and subject != text:
            text = f"{subject}\n{text}".strip()
        if not text:
            text = "Sent an image via MMS."

        return {
            "id": message_id,
            "sender": str(properties.get("Sender", "")).strip(),
            "date": str(properties.get("Date", "")).strip(),
            "text": text,
            "attachments": attachments,
        }

    def _read_part(self, source_path: Path, offset: int, length: int) -> bytes:
        if not _is_within(source_path, self.storage_root):
            raise ValueError("MMS attachment path escaped storage root")
        if offset < 0 or length < 0 or length > MAX_MESSAGE_BYTES:
            raise ValueError("invalid MMS attachment bounds")
        file_size = source_path.stat().st_size
        if offset + length > file_size:
            raise ValueError("MMS attachment exceeds source file")
        with source_path.open("rb") as source:
            source.seek(offset)
            data = source.read(length)
        if len(data) != length:
            raise ValueError("short read extracting MMS attachment")
        return data
