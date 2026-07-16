"""Encrypted backup & restore for OpenPup's state.

Pack up ``~/.openpup/`` into a tar.gz, encrypt it with a passphrase-derived
key, and write it to a target (local dir, S3, ...). Restore does the inverse
and verifies the archive before extraction.

File format (version 1)::

    [16 bytes salt][12 bytes nonce][N bytes AES-GCM ciphertext]

where ``ciphertext = AES-GCM(tar.gz of ~/.openpup/, key, nonce)`` and the key
is ``Argon2id(passphrase, salt)`` with sane defaults.

The tar contains a top-level ``VERSION`` file with ``format_version``,
``created_at``, ``hostname``, and ``openpup_version`` plus the verbatim
contents of the source directory.

This module is intentionally synchronous and dependency-light (cryptography +
argon2-cffi). It does not require ``boto3`` unless the user actually picks an
S3 target.
"""
from __future__ import annotations

import io
import logging
import os
import socket
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

logger = logging.getLogger("openpup.backup")

# Header version. Bump when the on-disk format changes incompatibly.
FORMAT_VERSION = 1

# Argon2id parameters. Tuned for ~250ms on a modest server; raise time_cost if
# you have headroom (Argon2id is intentionally slow).
ARGON2_TIME_COST = 3
ARGON2_MEMORY_COST = 64 * 1024  # 64 MiB
ARGON2_PARALLELISM = 4

SALT_LEN = 16
NONCE_LEN = 12

# Try imports lazily so the CLI is usable without the optional deps.
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    HAS_CRYPTO = True
except ImportError:  # pragma: no cover
    HAS_CRYPTO = False

try:
    from argon2.low_level import hash_secret_raw, Type

    HAS_ARGON2 = True
except ImportError:  # pragma: no cover
    HAS_ARGON2 = False


# ---------------------------------------------------------------------------
# Crypto primitives
# ---------------------------------------------------------------------------
def _require_deps() -> None:
    missing = []
    if not HAS_CRYPTO:
        missing.append("cryptography")
    if not HAS_ARGON2:
        missing.append("argon2-cffi")
    if missing:
        raise RuntimeError(
            "Backup requires: " + ", ".join(missing) + ". "
            "Install with: pip install 'openpup[backup]' (or 'openpup[all]')."
        )


def derive_key(passphrase: str, salt: bytes) -> bytes:
    """Argon2id -> 32-byte AES key. Deterministic for (passphrase, salt)."""
    _require_deps()
    if not passphrase:
        raise ValueError("passphrase must not be empty")
    if len(salt) != SALT_LEN:
        raise ValueError(f"salt must be exactly {SALT_LEN} bytes")
    return hash_secret_raw(
        secret=passphrase.encode("utf-8"),
        salt=salt,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST,
        parallelism=ARGON2_PARALLELISM,
        hash_len=32,
        type=Type.ID,
    )


def encrypt(plaintext: bytes, passphrase: str) -> bytes:
    """Encrypt with a passphrase. Output layout: salt | nonce | ciphertext.

    AAD is empty (no separate metadata is required; the VERSION file inside the
    tar carries human-readable metadata).
    """
    _require_deps()
    if not plaintext:
        raise ValueError("plaintext must not be empty")
    salt = os.urandom(SALT_LEN)
    nonce = os.urandom(NONCE_LEN)
    key = derive_key(passphrase, salt)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, associated_data=None)
    return salt + nonce + ciphertext


def decrypt(blob: bytes, passphrase: str) -> bytes:
    """Inverse of :func:`encrypt`. Raises on tamper or wrong passphrase."""
    _require_deps()
    if len(blob) < SALT_LEN + NONCE_LEN + 16:
        # 16 = min AES-GCM tag size
        raise ValueError("backup is truncated")
    salt = blob[:SALT_LEN]
    nonce = blob[SALT_LEN : SALT_LEN + NONCE_LEN]
    ct = blob[SALT_LEN + NONCE_LEN :]
    key = derive_key(passphrase, salt)
    try:
        return AESGCM(key).decrypt(nonce, ct, associated_data=None)
    except Exception as exc:  # cryptography raises InvalidTag on bad key/tag
        raise ValueError(
            "decryption failed (wrong passphrase or corrupt backup)"
        ) from exc


# ---------------------------------------------------------------------------
# Tar helpers
# ---------------------------------------------------------------------------
def _version_metadata(source: Path) -> dict:
    """Build the VERSION metadata block included in every backup."""
    return {
        "format_version": FORMAT_VERSION,
        "created_at": int(time.time()),
        "hostname": socket.gethostname()[:255],
        "openpup_version": _pkg_version(),
        "source_path": str(source),
    }


def _pkg_version() -> str:
    try:
        from importlib.metadata import version

        return version("openpup")
    except Exception:
        return "unknown"


def _add_version_to_tar(tar: tarfile.TarFile, source: Path) -> None:
    info = tarfile.TarInfo(name="VERSION")
    data = "\n".join(f"{k}: {v}" for k, v in _version_metadata(source).items()).encode()
    info.size = len(data)
    info.mtime = int(time.time())
    info.mode = 0o644
    tar.addfile(info, io.BytesIO(data))


def make_tar(source: Path) -> bytes:
    """Pack ``source`` into a tar.gz (in-memory). Adds a VERSION metadata file."""
    if not source.exists():
        raise FileNotFoundError(f"source {source} does not exist")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6) as tar:
        _add_version_to_tar(tar, source)
        tar.add(str(source), arcname=source.name, recursive=True)
    return buf.getvalue()


def extract_tar(blob: bytes, target: Path) -> None:
    """Extract a tar.gz into ``target`` (created if missing)."""
    target.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO(blob)
    with tarfile.open(fileobj=buf, mode="r:gz") as tar:
        # Safe extraction: refuse path traversal and absolute paths.
        for member in tar.getmembers():
            name = member.name
            if name.startswith("/") or ".." in name.split("/"):
                raise ValueError(f"refusing unsafe path in archive: {name}")
        # filter='data' (Python 3.12+) blocks extraction of device/symlink members.
        tar.extractall(target, filter="data")


def read_version(blob: bytes) -> dict:
    """Read the VERSION metadata from an *unencrypted* tar.gz (for verification)."""
    buf = io.BytesIO(blob)
    with tarfile.open(fileobj=buf, mode="r:gz") as tar:
        for member in tar.getmembers():
            if member.name == "VERSION":
                f = tar.extractfile(member)
                if f is None:
                    continue
                raw = f.read().decode("utf-8", errors="replace")
                return dict(line.split(": ", 1) for line in raw.splitlines() if ": " in line)
    return {}


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------
@runtime_checkable
class BackupTarget(Protocol):
    """A place to write backups to / read them from.

    Targets are intentionally simple: ``write(name, data)`` and ``read(name)``
    are the only required ops. ``list()`` is optional; if missing, the CLI
    falls back to globbing ``exists()`` per candidate.
    """

    def write(self, name: str, data: bytes) -> str: ...
    def read(self, name: str) -> bytes: ...
    def delete(self, name: str) -> bool: ...


@dataclass
class LocalTarget:
    """Target that writes to a local directory on disk."""

    directory: Path

    def __post_init__(self) -> None:
        self.directory = Path(self.directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        if "/" in name or "\\" in name or name.startswith("."):
            raise ValueError(f"backup name {name!r} contains path separators")
        return self.directory / name

    def write(self, name: str, data: bytes) -> str:
        path = self._path(name)
        path.write_bytes(data)
        # Encrypted backups contain the full state directory (~/.openpup/):
        # kennel memory, contacts, platform credentials, etc. Default umask
        # leaves them 0o644 on most systems (world-readable). Best-effort
        # chmod 0o600 so the bytes never leak off-box before any remote
        # upload. Failure here is non-fatal (chmod may not be supported on
        # every filesystem); the write already succeeded.
        try:
            os.chmod(path, 0o600)
        except OSError:
            logger.debug("could not chmod backup file %s", path, exc_info=True)
        return str(path)

    def read(self, name: str) -> bytes:
        return self._path(name).read_bytes()

    def delete(self, name: str) -> bool:
        try:
            self._path(name).unlink()
            return True
        except FileNotFoundError:
            return False

    def list(self) -> list[str]:
        return sorted(p.name for p in self.directory.iterdir() if p.is_file())


@dataclass
class S3Target:
    """S3 / S3-compatible target (uses boto3).

    Construct via :func:`s3_target` for lazy import.
    """

    bucket: str
    prefix: str = ""
    client: object = None  # boto3 S3 client

    def _key(self, name: str) -> str:
        if "/" in name or name.startswith("."):
            raise ValueError(f"backup name {name!r} contains path separators")
        if self.prefix:
            return f"{self.prefix.rstrip('/')}/{name}"
        return name

    def write(self, name: str, data: bytes) -> str:
        self.client.put_object(Bucket=self.bucket, Key=self._key(name), Body=data)
        return f"s3://{self.bucket}/{self._key(name)}"

    def read(self, name: str) -> bytes:
        obj = self.client.get_object(Bucket=self.bucket, Key=self._key(name))
        return obj["Body"].read()

    def delete(self, name: str) -> bool:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=self._key(name))
            return True
        except Exception:
            return False

    def list(self) -> list[str]:
        resp = self.client.list_objects_v2(Bucket=self.bucket, Prefix=self.prefix)
        out = []
        for obj in resp.get("Contents", []):
            key = obj["Key"]
            name = key[len(self.prefix) + 1:] if self.prefix else key
            if name:
                out.append(name)
        return sorted(out)


def s3_target(bucket: str, prefix: str = "", profile: Optional[str] = None) -> S3Target:
    """Build an :class:`S3Target` (lazy boto3 import)."""
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "S3 target requires boto3. Install with: pip install openpup[backup]"
        ) from exc
    if profile:
        session = boto3.Session(profile_name=profile)
        client = session.client("s3")
    else:
        client = boto3.client("s3")
    return S3Target(bucket=bucket, prefix=prefix, client=client)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------
def create_backup(
    source: Path,
    target: BackupTarget,
    passphrase: str,
    label: str = "",
) -> dict:
    """Pack, encrypt, and upload. Returns a summary dict."""
    tar_bytes = make_tar(source)
    encrypted = encrypt(tar_bytes, passphrase)
    # Default name: timestamp + optional label.
    name = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + (f"-{label}" if label else "") + ".openpup-backup"
    location = target.write(name, encrypted)
    return {
        "name": name,
        "location": location,
        "size_bytes": len(encrypted),
        "tar_size_bytes": len(tar_bytes),
        "source": str(source),
    }


def restore_backup(
    target: BackupTarget,
    name: str,
    passphrase: str,
    out_dir: Path,
) -> dict:
    """Download, decrypt, extract. Returns a summary dict."""
    encrypted = target.read(name)
    tar_bytes = decrypt(encrypted, passphrase)
    extract_tar(tar_bytes, out_dir)
    version = read_version(tar_bytes)
    return {
        "name": name,
        "extracted_to": str(out_dir),
        "size_bytes": len(encrypted),
        "tar_size_bytes": len(tar_bytes),
        "metadata": version,
    }


def verify_backup(target: BackupTarget, name: str, passphrase: str) -> dict:
    """Decrypt and read metadata without extracting."""
    encrypted = target.read(name)
    tar_bytes = decrypt(encrypted, passphrase)
    version = read_version(tar_bytes)
    return {
        "name": name,
        "size_bytes": len(encrypted),
        "tar_size_bytes": len(tar_bytes),
        "metadata": version,
    }


# ---------------------------------------------------------------------------
# CLI plumbing (used by openpup.cli)
# ---------------------------------------------------------------------------
def default_target() -> BackupTarget:
    """Pick a default target from env or fall back to local dir."""
    spec = os.environ.get("OPENPUP_BACKUP_TARGET", "").strip()
    if spec.startswith("local:") or spec.startswith("local="):
        path = spec.split(":", 1)[1] if ":" in spec else spec.split("=", 1)[1]
        return LocalTarget(Path(path).expanduser())
    if spec.startswith("s3:"):
        rest = spec[4:]
        bucket, _, prefix = rest.partition("/")
        return s3_target(bucket, prefix)
    # Fallback: local dir under XDG state dir / ~/.local/share/openpup/backups
    fallback = Path.home() / ".local" / "share" / "openpup" / "backups"
    return LocalTarget(fallback)


def parse_target_spec(spec: str) -> BackupTarget:
    """Parse a CLI --target spec: 'local:/path', 's3:bucket/prefix'."""
    if spec.startswith("local:"):
        return LocalTarget(Path(spec[6:]).expanduser())
    if spec.startswith("s3:"):
        rest = spec[3:]
        bucket, _, prefix = rest.partition("/")
        return s3_target(bucket, prefix)
    raise ValueError(f"unknown target spec {spec!r}; use local:PATH or s3:BUCKET[/PREFIX]")


def ask_passphrase(prompt: str = "Passphrase: ") -> str:
    """Prompt for a passphrase (uses getpass)."""
    import getpass

    return getpass.getpass(prompt)
