"""Tests for the backup module.

Covers crypto round-trip, tamper detection, tar packaging, target I/O, and
the end-to-end create/restore flow.
"""

import io
import tarfile
from pathlib import Path
from unittest import mock

import pytest

from openpup.backup import (
    LocalTarget,
    S3Target,
    decrypt,
    derive_key,
    encrypt,
    extract_tar,
    make_tar,
    parse_target_spec,
    restore_backup,
    s3_target,
    verify_backup,
    create_backup,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _populate(dir: Path, files: dict[str, str]) -> None:
    """Write a {relpath: content} map into dir (creating subdirs)."""
    for rel, content in files.items():
        full = dir / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)


# ---------------------------------------------------------------------------
# Crypto
# ---------------------------------------------------------------------------
class TestCrypto:
    def test_roundtrip(self):
        msg = b"hello backup world" * 100
        blob = encrypt(msg, "correct horse battery staple")
        # Distinct encryptions => different ciphertext (random salt+nonce).
        blob2 = encrypt(msg, "correct horse battery staple")
        assert blob != blob2
        assert decrypt(blob, "correct horse battery staple") == msg
        assert decrypt(blob2, "correct horse battery staple") == msg

    def test_wrong_passphrase_raises(self):
        msg = b"secret stuff"
        blob = encrypt(msg, "right")
        with pytest.raises(ValueError, match="wrong passphrase|decryption failed"):
            decrypt(blob, "wrong")

    def test_tampered_ciphertext_raises(self):
        msg = b"important"
        blob = bytearray(encrypt(msg, "pw"))
        # Flip a byte in the ciphertext region (past salt+nonce).
        blob[-5] ^= 0xFF
        with pytest.raises(ValueError, match="wrong passphrase|decryption failed"):
            decrypt(bytes(blob), "pw")

    def test_truncated_blob_raises(self):
        with pytest.raises(ValueError, match="truncated"):
            decrypt(b"short", "pw")

    def test_empty_plaintext_rejected(self):
        with pytest.raises(ValueError):
            encrypt(b"", "pw")

    def test_empty_passphrase_rejected(self):
        with pytest.raises(ValueError):
            encrypt(b"x", "")

    def test_salt_must_be_16_bytes(self):
        with pytest.raises(ValueError):
            derive_key("pw", b"tooshort")

    def test_salt_uniqueness(self):
        # Two different salts should derive different keys.
        k1 = derive_key("pw", b"a" * 16)
        k2 = derive_key("pw", b"b" * 16)
        assert k1 != k2


# ---------------------------------------------------------------------------
# Tar packaging
# ---------------------------------------------------------------------------
class TestTar:
    def test_make_tar_includes_version(self, tmp_path):
        _populate(tmp_path, {"a.txt": "alpha", "sub/b.txt": "bravo"})
        tar = make_tar(tmp_path)
        buf = io.BytesIO(tar)
        with tarfile.open(fileobj=buf, mode="r:gz") as tf:
            names = {m.name for m in tf.getmembers()}
            assert "VERSION" in names
            assert any(n.endswith("a.txt") for n in names)
            assert any(n.endswith("sub/b.txt") for n in names)

    def test_extract_tar_round_trip(self, tmp_path):
        # Build a tar in tmp_path, extract to another dir, compare.
        src = tmp_path / "src"
        src.mkdir()
        _populate(src, {"x.txt": "X", "nested/y.txt": "Y"})
        tar_bytes = make_tar(src)
        out = tmp_path / "out"
        extract_tar(tar_bytes, out)
        assert (out / src.name / "x.txt").read_text() == "X"
        assert (out / src.name / "nested" / "y.txt").read_text() == "Y"

    def test_extract_tar_refuses_path_traversal(self, tmp_path):
        # Build a tar.gz with a malicious member. Use a relative name that
        # tarfile.addfile accepts but that traverses up.
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            info = tarfile.TarInfo(name="../../etc/passwd")
            data = b"pwned"
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        with pytest.raises(ValueError, match="unsafe path"):
            extract_tar(buf.getvalue(), tmp_path)

    def test_extract_tar_refuses_absolute_path(self, tmp_path):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            info = tarfile.TarInfo(name="/etc/passwd")
            data = b"pwned"
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        with pytest.raises(ValueError, match="unsafe path"):
            extract_tar(buf.getvalue(), tmp_path)

    def test_make_tar_missing_source_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            make_tar(tmp_path / "nope")


# ---------------------------------------------------------------------------
# Local target
# ---------------------------------------------------------------------------
class TestLocalTarget:
    def test_write_read_delete(self, tmp_path):
        t = LocalTarget(directory=tmp_path)
        t.write("foo.bin", b"hello")
        assert (tmp_path / "foo.bin").read_bytes() == b"hello"
        assert t.read("foo.bin") == b"hello"
        assert "foo.bin" in t.list()
        assert t.delete("foo.bin") is True
        assert "foo.bin" not in t.list()

    def test_refuses_path_separators_in_name(self, tmp_path):
        t = LocalTarget(directory=tmp_path)
        with pytest.raises(ValueError):
            t.write("../etc/passwd", b"pwned")
        with pytest.raises(ValueError):
            t.write("sub/dir", b"x")

    def test_create_dir_if_missing(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        LocalTarget(directory=nested)
        assert nested.is_dir()


# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------
class TestEndToEnd:
    def test_create_and_restore(self, tmp_path):
        src = tmp_path / "pup_state"
        src.mkdir()
        _populate(src, {"kennel.db": "fake sqlite", "memories.txt": "many thoughts"})

        backup_dir = tmp_path / "backups"
        target = LocalTarget(directory=backup_dir)

        # Create
        passphrase = "secret-phrase-123"
        summary = create_backup(src, target, passphrase)
        assert summary["name"].endswith(".openpup-backup")
        assert summary["size_bytes"] > 0
        # File exists on disk.
        files = list(target.list())
        assert len(files) == 1

        # Restore to a fresh dir.
        restore_to = tmp_path / "restored"
        restored = restore_backup(target, files[0], passphrase, restore_to)
        assert restored["metadata"]["format_version"] == "1"
        # Restore doesn't extract onto a non-existent path; our tar in tar does that.
        # Verify the kennel file came back.
        assert any(restore_to.rglob("kennel.db"))
        assert any(restore_to.rglob("memories.txt"))

    def test_restore_with_wrong_passphrase_fails(self, tmp_path):
        src = tmp_path / "pup_state"
        src.mkdir()
        _populate(src, {"kennel.db": "x"})
        target = LocalTarget(directory=tmp_path / "backups")
        summary = create_backup(src, target, "right")
        with pytest.raises(ValueError):
            restore_backup(target, summary["name"], "WRONG", tmp_path / "out")

    def test_verify_returns_metadata(self, tmp_path):
        src = tmp_path / "pup_state"
        src.mkdir()
        _populate(src, {"kennel.db": "x"})
        target = LocalTarget(directory=tmp_path / "backups")
        summary = create_backup(src, target, "pw")
        v = verify_backup(target, summary["name"], "pw")
        assert v["metadata"]["format_version"] == "1"
        assert "hostname" in v["metadata"]
        assert "openpup_version" in v["metadata"]

    def test_s3_target_lazy(self, monkeypatch):
        # boto3 isn't installed in test env if not declared as a dep.
        # The function should still construct (boto3 import is inside s3_target).
        with mock.patch.dict("sys.modules", {"boto3": mock.MagicMock()}):
            t = s3_target("my-bucket", "backups/")
            assert isinstance(t, S3Target)
            assert t.bucket == "my-bucket"
            assert t.prefix == "backups/"

    def test_parse_target_spec(self, tmp_path):
        local_t = parse_target_spec(f"local:{tmp_path}/x")
        assert isinstance(local_t, LocalTarget)
        with mock.patch.dict("sys.modules", {"boto3": mock.MagicMock()}):
            s3_t = parse_target_spec("s3:my-bucket/sub/dir")
            assert isinstance(s3_t, S3Target)
            assert s3_t.bucket == "my-bucket"
            assert s3_t.prefix == "sub/dir"
        with pytest.raises(ValueError):
            parse_target_spec("ftp:something")


# ---------------------------------------------------------------------------
# S3Target (unit-level with mocked boto3)
# ---------------------------------------------------------------------------
class TestS3Target:
    def test_key_construction(self):
        fake = mock.MagicMock()
        t = S3Target(bucket="b", prefix="prefix/", client=fake)
        assert t._key("foo.bin") == "prefix/foo.bin"
        t2 = S3Target(bucket="b", client=fake)
        assert t2._key("foo.bin") == "foo.bin"

    def test_write_calls_put_object(self):
        fake = mock.MagicMock()
        t = S3Target(bucket="b", prefix="p/", client=fake)
        loc = t.write("foo.bin", b"data")
        assert loc == "s3://b/p/foo.bin"
        fake.put_object.assert_called_once()
        kwargs = fake.put_object.call_args.kwargs
        assert kwargs["Bucket"] == "b"
        assert kwargs["Key"] == "p/foo.bin"
        assert kwargs["Body"] == b"data"

    def test_list_parses_prefix(self):
        fake = mock.MagicMock()
        fake.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "p/a.bin"},
                {"Key": "p/sub/b.bin"},
            ]
        }
        t = S3Target(bucket="b", prefix="p", client=fake)
        names = t.list()
        assert names == ["a.bin", "sub/b.bin"]  # stripped of prefix

    def test_read_returns_body(self):
        fake = mock.MagicMock()
        fake.get_object.return_value = {"Body": io.BytesIO(b"hi")}
        t = S3Target(bucket="b", client=fake)
        assert t.read("foo") == b"hi"

    def test_refuses_path_separators(self):
        fake = mock.MagicMock()
        t = S3Target(bucket="b", client=fake)
        with pytest.raises(ValueError):
            t.write("../etc/passwd", b"x")
