"""PWA manifest + service worker scaffold for the dashboard.

v1 generates a static ``manifest.json`` and a minimal ``sw.js`` service
worker so the dashboard can be installed as a PWA on Android / iOS.

Real push-notification subscription + offline cache strategies are
follow-up commits.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

logger = logging.getLogger("openpup.pwa")


MANIFEST = {
    "name": "OpenPup",
    "short_name": "pup",
    "description": "Your loyal AI companion.",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#ffffff",
    "theme_color": "#7c3aed",
    "icons": [
        {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
    ],
}

SERVICE_WORKER = """
self.addEventListener('install', (e) => {
  e.waitUntil(caches.open('pup-v1').then((c) => c.addAll(['/'])));
});
self.addEventListener('fetch', (e) => {
  e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
});
""".strip()


def manifest_json() -> str:
    """Return the manifest JSON string."""
    return json.dumps(MANIFEST, indent=2)


def service_worker_js() -> str:
    """Return the service worker JS string."""
    return SERVICE_WORKER


def manifest_path() -> str:
    return "/manifest.json"


def service_worker_path() -> str:
    return "/sw.js"
