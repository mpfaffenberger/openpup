"""Tests for PWA scaffold."""

import json

from openpup.pwa import (
    MANIFEST,
    manifest_json,
    manifest_path,
    service_worker_js,
    service_worker_path,
)


def test_manifest_json():
    s = manifest_json()
    data = json.loads(s)
    assert data["name"] == "OpenPup"
    assert data["display"] == "standalone"
    assert any(i["sizes"] == "192x192" for i in data["icons"])


def test_service_worker_js():
    js = service_worker_js()
    assert "addEventListener" in js
    assert "fetch" in js


def test_paths():
    assert manifest_path() == "/manifest.json"
    assert service_worker_path() == "/sw.js"
