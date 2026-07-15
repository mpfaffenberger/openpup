"""Local web dashboard for inspecting OpenPup.

Run with: ``openpup web`` (or ``openpup dashboard``)

A small FastAPI app exposing read-only views over OpenPup's state: config,
memory, sessions, skills, routines, and heartbeat stats. The pup's chat
adapters are NOT touched here — this is purely an operator surface.

Token auth: a random token is generated on first start and saved to
``~/.openpup/dashboard.token``. Clients must pass it as ``?token=...`` or in
``Authorization: Bearer ...`` header. Set ``OPENPUP_DASHBOARD_TOKEN`` to pin it.
"""
from __future__ import annotations

import logging
import os
import secrets
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("openpup.web_dashboard")

# Lazy imports so the CLI doesn't require fastapi unless 'web' is requested.
try:
    from fastapi import Depends, FastAPI, HTTPException, Query, Request
    from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

DEFAULT_PORT = 8765
DEFAULT_HOST = "127.0.0.1"  # local-only by default


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------
def _token_file() -> Path:
    from openpup.config import get_settings

    return get_settings().state_dir / "dashboard.token"


def get_or_create_token() -> str:
    """Return the dashboard token, creating one if needed.

    Honours ``OPENPUP_DASHBOARD_TOKEN`` for explicit config; otherwise
    reads/persists a generated token in ``~/.openpup/dashboard.token``.
    """
    explicit = os.environ.get("OPENPUP_DASHBOARD_TOKEN")
    if explicit:
        return explicit
    path = _token_file()
    if path.exists():
        try:
            tok = path.read_text().strip()
            if tok:
                return tok
        except Exception:
            logger.debug("could not read dashboard token", exc_info=True)
    # Generate and persist.
    path.parent.mkdir(parents=True, exist_ok=True)
    tok = secrets.token_urlsafe(24)
    try:
        path.write_text(tok + "\n")
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
    except Exception:
        logger.exception("could not persist dashboard token")
    return tok


def require_token(request: Request, token: Optional[str] = None) -> None:
    """Dependency: raise 401 unless a valid token is presented."""
    expected = get_or_create_token()
    # Accept via query string OR Authorization header OR X-Auth-Token header.
    auth = request.headers.get("authorization", "")
    presented = token
    if not presented and auth.lower().startswith("bearer "):
        presented = auth[7:].strip()
    if not presented:
        presented = request.headers.get("x-auth-token")
    if not presented or presented != expected:
        raise HTTPException(status_code=401, detail="invalid or missing token")


# ---------------------------------------------------------------------------
# HTML template (single page, multiple sections). Kept inline to avoid a
# template-engine dep. htmx gives us nice progressive enhancement.
# ---------------------------------------------------------------------------
_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} - OpenPup dashboard</title>
<script src="https://unpkg.com/htmx.org@1.9.10"></script>
<style>
  :root {{ --fg: #111; --muted: #666; --bg: #fafafa; --card: #fff; --accent: #2563eb; --border: #e5e7eb; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --fg: #f3f4f6; --muted: #9ca3af; --bg: #0b0d10; --card: #16191d; --accent: #60a5fa; --border: #2a2f36; }} }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, system-ui, sans-serif; margin: 0; padding: 0; background: var(--bg); color: var(--fg); }}
  header {{ background: var(--card); border-bottom: 1px solid var(--border); padding: 12px 24px; display: flex; align-items: center; justify-content: space-between; }}
  h1 {{ font-size: 18px; margin: 0; }}
  .meta {{ font-size: 12px; color: var(--muted); }}
  main {{ max-width: 1100px; margin: 24px auto; padding: 0 24px; }}
  nav.tabs {{ display: flex; gap: 0; border-bottom: 1px solid var(--border); margin-bottom: 24px; }}
  nav.tabs a {{ padding: 10px 16px; text-decoration: none; color: var(--muted); border-bottom: 2px solid transparent; font-size: 14px; }}
  nav.tabs a.active {{ color: var(--fg); border-color: var(--accent); }}
  section {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 16px; }}
  section h2 {{ margin: 0 0 12px; font-size: 14px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th, td {{ text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--border); }}
  th {{ color: var(--muted); font-weight: 500; }}
  tr:last-child td {{ border-bottom: 0; }}
  input[type=text], input[type=search] {{ padding: 8px 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg); color: var(--fg); font-size: 14px; width: 100%; }}
  .row {{ display: flex; gap: 8px; align-items: center; }}
  .pill {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; background: var(--border); color: var(--muted); }}
  code {{ font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px; }}
  pre {{ background: var(--bg); padding: 8px; border-radius: 4px; overflow: auto; margin: 0; }}
  .empty {{ color: var(--muted); padding: 24px; text-align: center; }}
  footer {{ text-align: center; color: var(--muted); font-size: 12px; padding: 24px; }}
</style>
</head>
<body>
<header>
  <h1>OpenPup dashboard</h1>
  <div class="meta">{name} &middot; <a href="?{query_no_tab}" style="color: var(--muted);">refresh</a></div>
</header>
<main>
<nav class="tabs">
  {tabs}
</nav>
{body}
</main>
<footer>OpenPup dashboard &middot; local-only &middot; all state stays on this machine</footer>
</body>
</html>
"""


def _render(title: str, body: str, active: str, token: str = "") -> str:
    tabs_html = "".join(
        f'<a href="?{_qs(tab=t)}"{" class=\"active\"" if t == active else ""}>{label}</a>'
        for t, label in [
            ("status", "Status"),
            ("memory", "Memory"),
            ("sessions", "Sessions"),
            ("skills", "Skills"),
            ("routines", "Routines"),
            ("heartbeat", "Heartbeat"),
        ]
    )
    return _HTML.format(
        title=title,
        name=_short_pup_name(),
        tabs=tabs_html,
        body=body,
        query_no_tab=_qs(tab=None, token=token),
    )


def _qs(tab: Optional[str] = None, token: str = "") -> str:
    """Build a query string with tab + token (used for links)."""
    parts: list[str] = []
    if token:
        parts.append(f"token={token}")
    if tab:
        parts.append(f"tab={tab}")
    return "&".join(parts)


def _short_pup_name() -> str:
    try:
        from openpup.config import get_settings

        return get_settings().name or "OpenPup"
    except Exception:
        return "OpenPup"


# ---------------------------------------------------------------------------
# Build the FastAPI app
# ---------------------------------------------------------------------------
def _require_fastapi() -> None:
    if not HAS_FASTAPI:
        raise RuntimeError(
            "Web dashboard requires fastapi. Install with: pip install 'openpup[web]'"
        )


def create_app() -> "FastAPI":
    """Construct the dashboard FastAPI app. The app is read-only over OpenPup state."""
    _require_fastapi()

    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

    app = FastAPI(title="OpenPup Dashboard", docs_url=None, redoc_url=None)

    # -- HTML pages ---------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, tab: Optional[str] = None, token: Optional[str] = None) -> HTMLResponse:
        require_token(request, token=token)
        active = tab or "status"
        token_str = get_or_create_token()  # for link building
        body_html = _render_body_for_tab(active, token_str)
        html = _render(title=active.title(), body=body_html, active=active, token=token_str)
        return HTMLResponse(html)

    # -- JSON API -----------------------------------------------------------
    @app.get("/api/status")
    def api_status(request: Request, token: Optional[str] = None) -> JSONResponse:
        require_token(request, token=token)
        from openpup.config import get_settings
        from openpup.messaging.registry import get_registry

        s = get_settings()
        reg = get_registry()
        platforms = reg.platforms()
        return JSONResponse(
            {
                "name": s.name,
                "model": s.model or "(code-puppy default)",
                "reflection_model": s.reflection_model or "(same as agent)",
                "owner": s.owner_address,
                "owner_addresses": s.owner_addresses,
                "kennel_root": str(s.kennel_path),
                "heartbeat_enabled": s.heartbeat_enabled,
                "heartbeat_interval_s": s.heartbeat_interval,
                "heartbeat_behaviors": list(s.behaviors),
                "platforms": platforms,
                "send_policy": s.send_policy,
                "send_rate_per_min": s.send_rate_per_min,
                "universal_constructor": bool(s.universal_constructor),
                "ts": int(time.time()),
            }
        )

    @app.get("/api/memory")
    def api_memory(
        request: Request,
        q: str = Query(..., min_length=1),
        top_k: int = Query(10, ge=1, le=50),
        token: Optional[str] = None,
    ) -> JSONResponse:
        require_token(request, token=token)
        from openpup import memory

        results = memory.recall(q, top_k=top_k)
        return JSONResponse({"matches": results, "count": len(results), "query": q})

    @app.get("/api/sessions")
    def api_sessions(
        request: Request, limit: int = Query(10, ge=1, le=50), token: Optional[str] = None
    ) -> JSONResponse:
        require_token(request, token=token)
        from openpup.sessions import get_session_store

        sessions = get_session_store().recent_sessions(limit=limit)
        return JSONResponse({"sessions": sessions})

    @app.get("/api/skills")
    def api_skills(
        request: Request,
        include_archived: bool = Query(False),
        token: Optional[str] = None,
    ) -> JSONResponse:
        require_token(request, token=token)
        from openpup.skills.store import get_skill_store

        store = get_skill_store()
        skills = store.list(include_archived=include_archived)
        return JSONResponse(
            {
                "skills": [
                    {
                        "name": s.name,
                        "description": s.description,
                        "category": s.category,
                        "state": s.state,
                    }
                    for s in skills
                ]
            }
        )

    @app.get("/api/routines")
    def api_routines(request: Request, token: Optional[str] = None) -> JSONResponse:
        require_token(request, token=token)
        from openpup.heartbeat.scheduler import get_scheduler

        now = time.time()
        sched = get_scheduler()
        return JSONResponse(
            {
                "schedules": [
                    {
                        "name": r.name,
                        "enabled": r.enabled,
                        "when": r.describe_when(),
                        "last_run": r.describe_last(),
                        "next_run": r.describe_next(now),
                        "is_one_shot": r.is_one_shot,
                        "deliver": r.deliver or None,
                    }
                    for r in sched.routines
                ]
            }
        )

    @app.get("/api/heartbeat")
    def api_heartbeat(request: Request, token: Optional[str] = None) -> JSONResponse:
        require_token(request, token=token)
        from openpup.heartbeat.engine import Heartbeat  # type: ignore
        from openpup.config import get_settings
        from openpup.messaging.registry import PlatformRegistry

        s = get_settings()
        sched = None
        try:
            from openpup.heartbeat.scheduler import get_scheduler

            sched = get_scheduler()
        except Exception:
            pass
        # Light stats; no full heartbeat boot.
        return JSONResponse(
            {
                "enabled": s.heartbeat_enabled,
                "interval_s": s.heartbeat_interval,
                "jitter_s": s.heartbeat_jitter,
                "quiet_hours": s.quiet_hours,
                "behaviors": list(s.behaviors),
                "registry_count": len(PlatformRegistry().platforms()),
                "scheduled_jobs": len(sched.routines) if sched else 0,
                "ts": int(time.time()),
            }
        )

    return app


def _render_body_for_tab(tab: str, token: str) -> str:
    """Render the body of a tab. Returns HTML."""
    if tab == "status":
        return _render_status()
    if tab == "memory":
        return _render_memory_search()
    if tab == "sessions":
        return _render_sessions()
    if tab == "skills":
        return _render_skills()
    if tab == "routines":
        return _render_routines()
    if tab == "heartbeat":
        return _render_heartbeat()
    return f'<section><h2>unknown tab</h2><p>unknown tab {tab}</p></section>'


def _render_status() -> str:
    from openpup.config import get_settings

    s = get_settings()
    reg = _safe_registry()
    platforms = ", ".join(reg.platforms()) if reg else "(unknown)"
    return f"""
<section>
  <h2>Status</h2>
  <table>
    <tr><th>Name</th><td>{s.name}</td></tr>
    <tr><th>Model</th><td>{s.model or '(code-puppy default)'}</td></tr>
    <tr><th>Reflection model</th><td>{s.reflection_model or '(same as agent)'}</td></tr>
    <tr><th>Owner</th><td>{s.owner_address or '(unset)'}</td></tr>
    <tr><th>Kennel</th><td><code>{s.kennel_path}</code></td></tr>
    <tr><th>Heartbeat</th><td>{'on' if s.heartbeat_enabled else 'off'}</td></tr>
    <tr><th>Behaviors</th><td>{', '.join(s.behaviors) or '(none)'}</td></tr>
    <tr><th>Platforms</th><td>{platforms}</td></tr>
  </table>
</section>
"""


def _render_memory_search() -> str:
    return """
<section>
  <h2>Memory</h2>
  <form hx-get="/api/memory" hx-target="#memory-results" hx-trigger="submit">
    <div class="row">
      <input type="search" name="q" placeholder="search the kennel..." required>
      <button type="submit">Search</button>
    </div>
  </form>
  <div id="memory-results" class="meta" style="margin-top:12px">Enter a query to search memories.</div>
</section>
"""


def _render_sessions() -> str:
    try:
        from openpup.sessions import get_session_store

        store = get_session_store()
        sessions = store.recent_sessions(limit=10)
        if not sessions:
            return '<section><h2>Sessions</h2><div class="empty">no sessions yet</div></section>'
        rows = "".join(
            f"<tr><td><code>{s['session_id']}</code></td><td>{s.get('source') or '?'}</td>"
            f"<td>{s.get('message_count', 0)}</td><td>{_fmt_ts(s.get('last_active'))}</td></tr>"
            for s in sessions
        )
        return f"""
<section>
  <h2>Sessions (recent)</h2>
  <table>
    <tr><th>session</th><th>source</th><th>msgs</th><th>last active</th></tr>
    {rows}
  </table>
</section>
"""
    except Exception as exc:
        return f'<section><h2>Sessions</h2><div class="empty">error: {exc}</div></section>'


def _render_skills() -> str:
    try:
        from openpup.skills.store import get_skill_store

        store = get_skill_store()
        skills = store.list(include_archived=True)
        if not skills:
            return '<section><h2>Skills</h2><div class="empty">no skills installed</div></section>'
        rows = "".join(
            f"<tr><td><code>{s.name}</code></td><td>{s.category or '-'}</td>"
            f"<td><span class='pill'>{s.state}</span></td>"
            f"<td>{s.description[:120]}</td></tr>"
            for s in skills
        )
        return f"""
<section>
  <h2>Skills ({len(skills)})</h2>
  <table>
    <tr><th>name</th><th>category</th><th>state</th><th>description</th></tr>
    {rows}
  </table>
</section>
"""
    except Exception as exc:
        return f'<section><h2>Skills</h2><div class="empty">error: {exc}</div></section>'


def _render_routines() -> str:
    try:
        from openpup.heartbeat.scheduler import get_scheduler

        sched = get_scheduler()
        if not sched.routines:
            return '<section><h2>Routines</h2><div class="empty">no routines scheduled</div></section>'
        now = time.time()
        rows = "".join(
            f"<tr><td><code>{r.name}</code></td>"
            f"<td>{r.describe_when()}</td>"
            f"<td>{r.describe_last()}</td>"
            f"<td>{r.describe_next(now)}</td>"
            f"<td>{r.deliver or '-'}</td></tr>"
            for r in sched.routines
        )
        return f"""
<section>
  <h2>Routines ({len(sched.routines)})</h2>
  <table>
    <tr><th>name</th><th>when</th><th>last</th><th>next</th><th>deliver</th></tr>
    {rows}
  </table>
</section>
"""
    except Exception as exc:
        return f'<section><h2>Routines</h2><div class="empty">error: {exc}</div></section>'


def _render_heartbeat() -> str:
    try:
        from openpup.config import get_settings

        s = get_settings()
        return f"""
<section>
  <h2>Heartbeat</h2>
  <table>
    <tr><th>Enabled</th><td>{'yes' if s.heartbeat_enabled else 'no'}</td></tr>
    <tr><th>Interval</th><td>{s.heartbeat_interval}s (jitter +/-{s.heartbeat_jitter}s)</td></tr>
    <tr><th>Quiet hours</th><td>{s.quiet_hours or '(none)'}</td></tr>
    <tr><th>Behaviors</th><td>{', '.join(s.behaviors) or '(none)'}</td></tr>
  </table>
</section>
"""
    except Exception as exc:
        return f'<section><h2>Heartbeat</h2><div class="empty">error: {exc}</div></section>'


def _safe_registry():
    try:
        from openpup.messaging.registry import get_registry

        return get_registry()
    except Exception:
        return None


def _fmt_ts(ts) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts)))
    except Exception:
        return "?"


# ---------------------------------------------------------------------------
# Runner (used by the CLI subcommand)
# ---------------------------------------------------------------------------
def run(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    log_level: str = "warning",
) -> None:
    """Boot uvicorn and serve the dashboard. Blocks until shutdown."""
    _require_fastapi()
    import uvicorn

    token = get_or_create_token()
    app = create_app()
    url = f"http://{host}:{port}/?token={token}"
    print(f"\n  OpenPup dashboard running at:\n    {url}\n")
    uvicorn.run(app, host=host, port=port, log_level=log_level)


if __name__ == "__main__":  # pragma: no cover
    run()
