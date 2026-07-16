"""GitHub PR / issue monitoring (public REST API).

Watches one or more repos and surfaces new activity (PRs, issues, releases)
to the owner. Uses the public GitHub REST API so no auth is required for
public repos; ``OPENPUP_GITHUB_TOKEN`` enables authenticated requests for
private / higher-rate-limit use.

Storage: ``~/.openpup/github_watched.json`` tracks per-watch last-seen
event IDs / numbers. Run from a heartbeat or scheduled routine to deliver
digests.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

logger = logging.getLogger("openpup.github_monitor")

DEFAULT_STORE = "github_watched.json"
GITHUB_API = "https://api.github.com"


@dataclass
class RepoWatch:
    """One watched repo: owner/name + last seen event id."""

    owner: str
    name: str
    last_issue_ts: float = 0.0  # epoch seconds

    @property
    def key(self) -> str:
        return f"{self.owner}/{self.name}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "RepoWatch":
        return cls(
            owner=str(raw["owner"]),
            name=str(raw["name"]),
            last_issue_ts=float(raw.get("last_issue_ts", 0.0)),
        )


def _headers(token: str = "") -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "openpup"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def fetch_recent_issues(
    owner: str,
    repo: str,
    *,
    since_ts: float = 0.0,
    state: str = "all",
    token: str = "",
    timeout: float = 15.0,
) -> list[dict]:
    """Fetch issues + PRs created/updated after ``since_ts`` (epoch seconds).

    Returns a list of dicts with at least ``number``, ``title``, ``html_url``,
    ``state``, ``updated_at``, ``is_pr``.
    """
    url = f"{GITHUB_API}/repos/{owner}/{repo}/issues"
    params = {
        "state": state,
        "sort": "updated",
        "direction": "desc",
        "per_page": "30",
    }
    if since_ts:
        # GitHub's since filter is on updated_at.
        from datetime import datetime, timezone

        params["since"] = datetime.fromtimestamp(since_ts, tz=timezone.utc).isoformat()
    out: list[dict] = []
    try:
        resp = httpx.get(url, params=params, headers=_headers(token), timeout=timeout)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("GitHub fetch %s/%s failed: %r", owner, repo, exc)
        return out
    for issue in resp.json():
        # /issues returns both issues and PRs; PRs have a pull_request key.
        is_pr = "pull_request" in issue
        updated_at = issue.get("updated_at", "")
        out.append(
            {
                "number": issue.get("number", 0),
                "title": issue.get("title", "(untitled)"),
                "html_url": issue.get("html_url", ""),
                "state": issue.get("state", "unknown"),
                "updated_at": updated_at,
                "is_pr": is_pr,
                "user": (issue.get("user") or {}).get("login", "unknown"),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Persistent watch store
# ---------------------------------------------------------------------------
class WatchStore:
    """JSON-backed store of repo watches."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, RepoWatch]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text())
        except Exception:
            logger.exception("could not read watch file %s", self.path)
            return {}
        return {
            f"{w['owner']}/{w['name']}": RepoWatch.from_dict(w)
            for w in raw.get("watches", [])
        }

    def _save(self, watches: dict[str, RepoWatch]) -> None:
        out = {"watches": [w.to_dict() for w in watches.values()]}
        self.path.write_text(json.dumps(out, indent=2, sort_keys=True))

    def list(self) -> list[RepoWatch]:
        return sorted(self._load().values(), key=lambda w: (w.owner, w.name))

    def watch(self, owner: str, name: str) -> RepoWatch:
        watches = self._load()
        key = f"{owner}/{name}"
        if key not in watches:
            watches[key] = RepoWatch(owner=owner, name=name)
            self._save(watches)
        return watches[key]

    def unwatch(self, owner: str, name: str) -> bool:
        watches = self._load()
        key = f"{owner}/{name}"
        if key in watches:
            del watches[key]
            self._save(watches)
            return True
        return False


def default_store_path() -> Path:
    from openpup.config import config_home

    return config_home() / DEFAULT_STORE


def get_store() -> WatchStore:
    return WatchStore(default_store_path())
