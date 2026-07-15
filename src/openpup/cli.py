"""OpenPup command-line interface (Typer).

Commands:
  openpup run                 start the always-on companion
  openpup status              show config + enabled platforms
  openpup say <addr> <text>   send a one-off message to a platform address
  openpup memory recall <q>   search the kennel
  openpup memory recent       show recent memories
  openpup sessions ...        search / browse / replay conversation transcripts
  openpup routine add/list/rm manage scheduled routines
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import signal
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from openpup.config import get_settings

app = typer.Typer(help="OpenPup - an always-on AI companion.", no_args_is_help=True)
memory_app = typer.Typer(help="Inspect OpenPup's memory (puppy_kennel).")
sessions_app = typer.Typer(help="Search and replay past conversation transcripts.")
routine_app = typer.Typer(help="Manage scheduled routines.")
access_app = typer.Typer(help="Manage who can talk to OpenPup (owner + allowlists).")
backup_app = typer.Typer(
    help="Encrypted backup & restore of OpenPup's state.", no_args_is_help=True
)
group_app = typer.Typer(help="Manage group-chat policies (mention rules, etc.).", no_args_is_help=True)
household_app = typer.Typer(help="Household mode: role-based access and per-user memory.", no_args_is_help=True)
voice_app = typer.Typer(help="Voice transcription and synthesis.", no_args_is_help=True)
calendar_app = typer.Typer(help="Calendar integration (CalDAV / Google).", no_args_is_help=True)
rag_app = typer.Typer(help="Local-files RAG: index + search a personal vault.", no_args_is_help=True)

gallery_app = typer.Typer(
    help="Community skill gallery: install and publish skills.", no_args_is_help=True
)
app.add_typer(memory_app, name="memory")
app.add_typer(sessions_app, name="sessions")
app.add_typer(routine_app, name="routine")
app.add_typer(access_app, name="access")
app.add_typer(backup_app, name="backup")
app.add_typer(gallery_app, name="skills-gallery")
app.add_typer(group_app, name="group")
app.add_typer(household_app, name="household")
app.add_typer(voice_app, name="voice")
app.add_typer(calendar_app, name="calendar")
app.add_typer(rag_app, name="rag")

console = Console()


def _setup_logging(verbose: bool) -> None:
    from openpup.logging_setup import setup_logging

    setup_logging(verbose)


@app.command()
def run(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    """Start the always-on companion (blocks until Ctrl-C)."""
    _setup_logging(verbose)
    from openpup.runtime import OpenPup

    pup = OpenPup()

    async def _main() -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, pup.request_stop)
            except NotImplementedError:  # pragma: no cover - windows
                pass
        await pup.run_forever()

    asyncio.run(_main())


@app.command()
def users() -> None:
    """Edit the per-platform user roster (name / handle / role / notes)."""
    from openpup.tui.roster import run_roster_menu

    asyncio.run(run_roster_menu())


@app.command()
def persona(
    env_file: Optional[str] = typer.Option(None, "--env-file", help="Path to the .env to write."),
) -> None:
    """Edit your pup's identity (name, personality, proactivity -> SOUL.md)."""
    from pathlib import Path

    from openpup.tui.persona import run_persona_menu

    path = Path(env_file) if env_file else None
    asyncio.run(run_persona_menu(path))


@app.command()
def setup(
    env_file: Optional[str] = typer.Option(None, "--env-file", help="Path to the .env to write."),
) -> None:
    """On-rails guided setup: get + validate credentials for each platform."""
    from pathlib import Path

    from openpup.setup import run_setup_wizard

    path = Path(env_file) if env_file else None
    asyncio.run(run_setup_wizard(path))


@app.command()
def config(
    env_file: Optional[str] = typer.Option(None, "--env-file", help="Path to the .env to edit."),
) -> None:
    """Open the interactive TUI to configure everything (writes .env)."""
    from pathlib import Path

    from openpup.tui import run_config_menu

    path = Path(env_file) if env_file else None
    asyncio.run(run_config_menu(path))


@app.command()
def web(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address (default localhost only)."),
    port: int = typer.Option(8765, "--port", "-p", help="Port to listen on."),
) -> None:
    """Boot the local web dashboard (Status / Memory / Sessions / Skills / Routines / Heartbeat).

    Prints a URL with the auth token to your terminal.
    """
    from openpup.web_dashboard import get_or_create_token, run as _web_run

    token = get_or_create_token()
    console.print(f"[cyan]token:[/cyan] {token}")
    _web_run(host=host, port=port)


@app.command()
def mcp() -> None:
    """Run OpenPup as an MCP (Model Context Protocol) server over stdio.

    Exposes OpenPup's tools (memory, sessions, send_message, etc.) so other
    MCP-capable clients (Claude Desktop, Cursor, Windsurf, ...) can call them.

    The server is owner-trusted by default (it runs on your box). Set
    ``OPENPUP_MCP_RESTRICT=true`` to hide privileged tools (send_message,
    list_contacts) for shared deployments.
    """
    from openpup.mcp_server import main as _mcp_main

    _mcp_main()


@app.command()
def status() -> None:
    """Show configuration and which platforms are enabled."""
    s = get_settings()
    table = Table(title=f"{s.name} status")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="white")
    from openpup.agent_def import is_auto, slugify

    agent_label = f"auto (generated: {slugify(s.name)})" if is_auto(s.agent) else s.agent
    table.add_row("Agent", agent_label)
    table.add_row("Model", s.model or "(code-puppy default)")
    table.add_row("Reflection model", s.reflection_model or "(same as agent)")
    table.add_row("Universal Constructor", "on" if s.universal_constructor else "off")
    table.add_row("Owner", s.owner_address or "(unset)")
    extra_owners = [a for a in s.owner_addresses if a != s.owner_address]
    if extra_owners:
        table.add_row("  also owner at", ", ".join(extra_owners))
    table.add_row("Send policy", f"{s.send_policy} ({s.send_rate_per_min}/min)")
    table.add_row("Kennel root", str(s.kennel_path))
    table.add_row("Heartbeat", "on" if s.heartbeat_enabled else "off")
    table.add_row("  interval", f"{s.heartbeat_interval}s +/-{s.heartbeat_jitter}s")
    table.add_row("  behaviors", ", ".join(s.behaviors))
    table.add_row("  quiet hours", s.quiet_hours or "(none)")
    enabled = [
        name
        for name, on in [
            ("discord", s.discord_enabled),
            ("telegram", s.telegram_enabled),
            ("whatsapp", s.whatsapp_enabled),
            ("email", s.email_enabled),
            ("sms", s.sms_enabled),
            ("imessage", s.imessage_enabled),
        ]
        if on
    ]
    table.add_row("Platforms", ", ".join(enabled) or "(none)")
    table.add_row("Webhook server", "on" if s.web_enabled else "off")
    console.print(table)


@app.command()
def say(address: str, text: str, verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    """Send a one-off message to ``platform:channel`` (boots adapters briefly)."""
    _setup_logging(verbose)
    from openpup.messaging.envelope import Envelope
    from openpup.messaging.registry import get_registry
    from openpup.platforms.base import build_enabled_adapters

    s = get_settings()

    async def _send() -> None:
        registry = get_registry()
        adapters = build_enabled_adapters(s, registry)
        for a in adapters:
            await a.start()
        ok = await registry.send(Envelope.to(address, text))
        for a in adapters:
            await a.stop()
        console.print("[green]sent[/green]" if ok else "[red]failed[/red]")

    asyncio.run(_send())


@memory_app.command("recall")
def memory_recall(query: str, top_k: int = 5) -> None:
    """Search the kennel for memories matching a query."""
    from openpup import memory

    get_settings()  # ensure kennel root env is set
    results = memory.recall(query, top_k=top_k)
    if not results:
        console.print("[dim]no matches[/dim]")
        return
    for i, r in enumerate(results, 1):
        console.print(f"[cyan]{i}.[/cyan] {r}")


@memory_app.command("recent")
def memory_recent(top_k: int = 5) -> None:
    """Show the most recent memories."""
    from openpup import memory

    get_settings()
    results = memory.recent(top_k=top_k)
    if not results:
        console.print("[dim]empty[/dim]")
        return
    for i, r in enumerate(results, 1):
        console.print(f"[cyan]{i}.[/cyan] {r}")


def _fmt_ts(ts) -> str:
    from datetime import datetime

    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return "?"


@sessions_app.command("search")
def sessions_search(
    query: str,
    limit: int = typer.Option(5, "--limit", help="max sessions to show"),
) -> None:
    """Full-text search across transcripts (best hit per session)."""
    from openpup.sessions import get_session_store

    get_settings()  # ensure state dir env is set
    hits = get_session_store().search(query, limit=limit)
    if not hits:
        console.print("[dim]no matches[/dim]")
        return
    table = Table(title=f"Sessions matching {query!r}")
    table.add_column("session", style="cyan")
    table.add_column("msg id", style="magenta")
    table.add_column("role")
    table.add_column("when", style="dim")
    table.add_column("snippet", overflow="fold")
    for h in hits:
        table.add_row(
            h["session_id"], str(h["message_id"]), h["role"], _fmt_ts(h["ts"]), h["snippet"]
        )
    console.print(table)


@sessions_app.command("recent")
def sessions_recent(
    limit: int = typer.Option(5, "--limit", help="max sessions to show"),
) -> None:
    """Show the most recently active sessions."""
    from openpup.sessions import get_session_store

    get_settings()
    sessions = get_session_store().recent_sessions(limit=limit)
    if not sessions:
        console.print("[dim]no sessions yet[/dim]")
        return
    table = Table(title="Recent sessions")
    table.add_column("session", style="cyan")
    table.add_column("source")
    table.add_column("msgs", justify="right")
    table.add_column("last active", style="dim")
    table.add_column("preview", overflow="fold")
    for s in sessions:
        table.add_row(
            s["session_id"],
            s.get("source") or "?",
            str(s["message_count"]),
            _fmt_ts(s["last_active"]),
            s["preview"],
        )
    console.print(table)


@sessions_app.command("show")
def sessions_show(session_id: str) -> None:
    """Replay one session's transcript (head/tail truncated when huge)."""
    from openpup.sessions import get_session_store

    get_settings()
    data = get_session_store().read_session(session_id)
    if data["session"] is None:
        console.print(f"[red]session '{session_id}' not found[/red]")
        raise typer.Exit(1)
    sess = data["session"]
    console.print(
        f"[bold cyan]{sess['id']}[/bold cyan] "
        f"[dim]({sess.get('source') or '?'}, started {_fmt_ts(sess['started_at'])})[/dim]"
    )
    role_styles = {"user": "green", "assistant": "cyan"}
    for m in data["messages"]:
        style = role_styles.get(m["role"], "yellow")
        console.print(
            f"[dim]{_fmt_ts(m['ts'])}[/dim] [{style}]{m['role']:>9}[/{style}] {m['content']}"
        )
    if data["truncated"]:
        console.print(f"[yellow]... {data['omitted']} middle messages omitted ...[/yellow]")


@routine_app.command("list")
def routine_list(
    full: bool = typer.Option(
        False, "--full", "-f", help="Show full prompt/notification text (no truncation)."
    ),
) -> None:
    """View scheduled prompts (tasks) and notifications (reminders).

    Shows each job's timing, next/last fire, delivery target, and its actual
    content. Use --full to see untruncated prompt/message text.
    """
    from openpup.tui.schedules import render_schedules

    render_schedules(console, full=full)


@routine_app.command("add")
def routine_add(
    name: str,
    deliver: str = typer.Option("", help="platform:channel address (default: owner)"),
    message: str = typer.Option("", help="plain reminder text to deliver"),
    prompt: str = typer.Option("", help="agent task prompt to run"),
    every: Optional[int] = typer.Option(None, help="recurring: seconds between runs"),
    daily: Optional[str] = typer.Option(None, help="recurring: HH:MM local time"),
    in_seconds: Optional[int] = typer.Option(None, "--in", help="one-shot: fire in N seconds"),
    at: Optional[str] = typer.Option(None, help="one-shot: ISO datetime (2026-06-09T09:00)"),
) -> None:
    """Add or replace a scheduled job (reminder or task)."""
    from openpup.heartbeat.scheduler import Scheduler, make_routine

    if not (message or prompt):
        console.print("[red]Provide --message or --prompt[/red]")
        raise typer.Exit(1)
    timings = [t for t in (every, daily, in_seconds, at) if t not in (None, "")]
    if len(timings) != 1:
        console.print("[red]Provide exactly one of --every, --daily, --in, --at[/red]")
        raise typer.Exit(1)
    s = get_settings()
    sched = Scheduler.load(s.state_dir / "routines.json")
    sched.add(
        make_routine(
            name=name,
            message=message,
            prompt=prompt,
            deliver=deliver,
            delay_seconds=in_seconds,
            at_iso=at,
            every_seconds=every,
            daily=daily,
        )
    )
    console.print(f"[green]added job '{name}'[/green]")


@access_app.command("list")
def access_list() -> None:
    """Show the owner and per-platform access policies."""
    from openpup.access import AccessControl, default_access_path

    s = get_settings()
    ac = AccessControl(
        default_access_path(s.state_dir),
        owner_address=s.owner_address,
        owner_addresses=s.owner_addresses,
    )
    console.print(ac.describe())


@access_app.command("owner")
def access_owner(
    address: str,
    primary: bool = typer.Option(
        True, "--primary/--add", help="--primary sets the default outreach target; --add only adds."
    ),
) -> None:
    """Add/set an owner address (platform:channel), saved to the config store.

    The owner can be reachable on several platforms (telegram + sms + ...). Use
    ``--add`` to register an extra one without changing your primary address.
    """
    from openpup.config_store import get_config_store

    if ":" not in address:
        console.print("[red]Address must be 'platform:channel', e.g. sms:+15559876543[/red]")
        raise typer.Exit(1)
    store = get_config_store()
    if primary or not store.get("OPENPUP_OWNER_ADDRESS"):
        store.set("OPENPUP_OWNER_ADDRESS", address)
    existing = [a.strip() for a in store.get("OPENPUP_OWNER_ADDRESSES").split(",") if a.strip()]
    if address not in existing:
        existing.append(address)
    store.set("OPENPUP_OWNER_ADDRESSES", ",".join(existing))
    store.save()
    console.print(f"[green]Owner address registered: {address}[/green]")


@access_app.command("allow")
def access_allow(platform: str, identifier: str) -> None:
    """Allow a sender on a platform (chat id / phone / email / user id)."""
    from openpup.access import AccessControl, default_access_path

    s = get_settings()
    ac = AccessControl(
        default_access_path(s.state_dir),
        owner_address=s.owner_address,
        owner_addresses=s.owner_addresses,
    )
    ac.allow(platform, identifier)
    console.print(f"[green]Allowed {identifier} on {platform} (mode now allowlist).[/green]")


@access_app.command("deny")
def access_deny(platform: str, identifier: str) -> None:
    """Remove a sender from a platform's allowlist."""
    from openpup.access import AccessControl, default_access_path

    s = get_settings()
    ac = AccessControl(
        default_access_path(s.state_dir),
        owner_address=s.owner_address,
        owner_addresses=s.owner_addresses,
    )
    ok = ac.deny(platform, identifier)
    console.print(
        f"[green]Removed {identifier} from {platform}.[/green]"
        if ok
        else f"[yellow]{identifier} was not on {platform}'s allowlist.[/yellow]"
    )


@access_app.command("mode")
def access_mode(platform: str, mode: str) -> None:
    """Set a platform's access mode: open | allowlist | owner_only."""
    from openpup.access import MODES, AccessControl, default_access_path

    if mode not in MODES:
        console.print(f"[red]mode must be one of: {', '.join(MODES)}[/red]")
        raise typer.Exit(1)
    s = get_settings()
    ac = AccessControl(
        default_access_path(s.state_dir),
        owner_address=s.owner_address,
        owner_addresses=s.owner_addresses,
    )
    ac.set_mode(platform, mode)
    console.print(f"[green]{platform} access mode set to {mode}.[/green]")


@routine_app.command("rm")
def routine_rm(name: str) -> None:
    """Remove a routine by name."""
    from openpup.heartbeat.scheduler import Scheduler

    s = get_settings()
    sched = Scheduler.load(s.state_dir / "routines.json")
    ok = sched.remove(name)
    console.print("[green]removed[/green]" if ok else "[yellow]not found[/yellow]")


def _backup_target(spec: Optional[str]):
    """Build a backup target from --target spec or env fallback."""
    from openpup.backup import default_target, parse_target_spec

    if spec:
        return parse_target_spec(spec)
    return default_target()


def _backup_passphrase(provided: Optional[str], confirm: bool = False) -> str:
    """Get a passphrase from --passphrase or interactive prompt."""
    if provided:
        return provided
    from openpup.backup import ask_passphrase

    pw = ask_passphrase("Passphrase: ")
    if confirm:
        pw2 = ask_passphrase("Confirm passphrase: ")
        if pw != pw2:
            console.print("[red]Passphrases do not match[/red]")
            raise typer.Exit(1)
    return pw


@backup_app.command("create")
def backup_create(
    label: str = typer.Option(
        "", "--label", "-l", help="Optional label suffix for the backup name."
    ),
    target: Optional[str] = typer.Option(
        None, "--target", help="local:PATH or s3:BUCKET[/PREFIX]."
    ),
    passphrase: Optional[str] = typer.Option(
        None,
        "--passphrase",
        help="Use this passphrase (skip interactive prompt). Also reads OPENPUP_BACKUP_PASSPHRASE.",
    ),
    state_dir: Optional[str] = typer.Option(
        None,
        "--state-dir",
        help="Override the state dir to back up (default: ~/.openpup).",
    ),
) -> None:
    """Create an encrypted snapshot of OpenPup's state directory."""
    from openpup.backup import create_backup as _create

    s = get_settings()
    src = Path(state_dir) if state_dir else s.state_dir
    if not src.exists():
        console.print(f"[red]State dir {src} does not exist[/red]")
        raise typer.Exit(1)

    passphrase = passphrase or os.environ.get("OPENPUP_BACKUP_PASSPHRASE")
    pw = _backup_passphrase(
        passphrase, confirm=bool(passphrase or os.environ.get("OPENPUP_BACKUP_PASSPHRASE"))
    )

    tgt = _backup_target(target)
    summary = _create(Path(src), tgt, pw, label=label)
    console.print(f"[green]wrote[/green] {summary['location']}")
    console.print(f"  size:    {summary['size_bytes']:,} bytes (encrypted)")
    console.print(f"  source:  {summary['source']}")


@backup_app.command("restore")
def backup_restore(
    name: str = typer.Argument(
        ..., help="Name of the backup to restore (see `openpup backup list`)."
    ),
    target: Optional[str] = typer.Option(
        None, "--target", help="local:PATH or s3:BUCKET[/PREFIX]."
    ),
    passphrase: Optional[str] = typer.Option(
        None, "--passphrase", help="Use this passphrase (skip interactive prompt)."
    ),
    to: str = typer.Option(
        ..., "--to", help="Directory to extract into (must be empty or not exist)."
    ),
    state_dir_override: Optional[str] = typer.Option(
        None,
        "--state-dir-override",
        help="Override OPENPUP_STATE_DIR for the restore (advanced).",
    ),
) -> None:
    """Decrypt and extract a backup to a directory."""
    from openpup.backup import restore_backup as _restore

    passphrase = passphrase or os.environ.get("OPENPUP_BACKUP_PASSPHRASE")
    pw = _backup_passphrase(passphrase)

    tgt = _backup_target(target)
    out = Path(to).expanduser()
    if out.exists():
        contents = list(out.iterdir())
        if contents:
            console.print(
                f"[red]{out} is not empty (contains {len(contents)} entries); refusing to overwrite[/red]"
            )
            raise typer.Exit(1)
    result = _restore(tgt, name, pw, out)
    console.print(f"[green]restored[/green] {name} -> {result['extracted_to']}")
    if result.get("metadata", {}).get("hostname"):
        console.print(f"  original hostname: {result['metadata']['hostname']}")
    if result.get("metadata", {}).get("openpup_version"):
        console.print(f"  openpup version:   {result['metadata']['openpup_version']}")


@gallery_app.command("list")
def gallery_list(
    registry: Optional[str] = typer.Option(
        None, "--registry", help="Override registry URL or file path."
    ),
    limit: int = typer.Option(50, "--limit", "-n"),
) -> None:
    """List skills available in the community gallery."""
    from openpup.skills_gallery import search

    reg = _load_registry(registry)
    entries = search(reg, "", limit=limit)
    if not entries:
        console.print("[dim]no skills in gallery[/dim]")
        return
    table = Table(title=f"Skills gallery ({len(entries)})")
    table.add_column("name", style="cyan")
    table.add_column("category", style="magenta")
    table.add_column("description")
    for e in entries:
        table.add_row(e.name, e.category or "-", e.description[:80])
    console.print(table)


@gallery_app.command("search")
def gallery_search(
    query: str = typer.Argument(
        "", help="Substring to match against name/description/category/tags."
    ),
    registry: Optional[str] = typer.Option(
        None, "--registry", help="Override registry URL or file path."
    ),
    limit: int = typer.Option(20, "--limit", "-n"),
) -> None:
    """Search the community skill gallery."""
    from openpup.skills_gallery import search as _search

    reg = _load_registry(registry)
    entries = _search(reg, query, limit=limit)
    if not entries:
        console.print(f"[dim]no matches for {query!r}[/dim]")
        return
    table = Table(title=f"Search: {query!r} ({len(entries)})")
    table.add_column("name", style="cyan")
    table.add_column("category", style="magenta")
    table.add_column("description")
    for e in entries:
        table.add_row(e.name, e.category or "-", e.description[:80])
    console.print(table)


@gallery_app.command("install")
def gallery_install(
    name: str = typer.Argument(..., help="Skill name to install."),
    registry: Optional[str] = typer.Option(
        None, "--registry", help="Override registry URL or file path."
    ),
    skills_root: Optional[str] = typer.Option(
        None, "--skills-root", help="Override the skills root (default: ~/.openpup/skills)."
    ),
) -> None:
    """Install a skill from the community gallery."""
    import tempfile

    from openpup.skills_gallery import install_entry, search

    reg = _load_registry(registry)
    entries = search(reg, name, limit=50)
    match = next((e for e in entries if e.name == name), None)
    if match is None:
        console.print(
            f"[red]skill {name!r} not found in gallery (try `openpup skills-gallery search`)[/red]"
        )
        raise typer.Exit(1)

    root = Path(skills_root).expanduser() if skills_root else _default_skills_root()
    # Fetch to a temp file first, then move into place (atomic).
    body = _http_get(match.fetch_url)
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as tmp:
        tmp.write(body)
        tmp_path = Path(tmp.name)
    try:
        # Re-use install_entry with the body to skip a second fetch.
        install_entry(match, root, body=body)
    finally:
        tmp_path.unlink(missing_ok=True)
    console.print(f"[green]installed[/green] {name} into {root}")


@gallery_app.command("publish")
def gallery_publish(
    skill_dir: str = typer.Argument(
        ..., help="Path to a local skill directory containing SKILL.md."
    ),
    registry_json: str = typer.Option(
        "registry/skills.json", "--registry-json", help="Path to the registry JSON to write."
    ),
    repo: str = typer.Option(
        "mpfaffenberger/openpup", "--repo", help="GitHub owner/repo for the registry."
    ),
    commit_sha: str = typer.Option(
        "", "--commit", help="Commit SHA the skill was added at (for pinning)."
    ),
    tag: list[str] = typer.Option([], "--tag", help="Tag (repeatable)."),
) -> None:
    """Add a local skill to the gallery registry JSON (for maintainers)."""
    from openpup.skills_gallery import publish as _publish

    result = _publish(
        Path(skill_dir), Path(registry_json), tags=tag, commit_sha=commit_sha, repo=repo
    )
    console.print(f"[green]added[/green] {result.entry.name} to {result.registry_path}")


def _default_skills_root() -> Path:
    from openpup.config import get_settings

    return get_settings().skills_root


def _load_registry(registry: Optional[str]):
    """Load a registry from --registry URL, env override, or default URL."""
    from openpup.skills_gallery import fetch_registry, load_registry_file

    spec = registry or __import__("os").environ.get("OPENPUP_SKILLS_REGISTRY", "")
    if spec and spec.startswith(("http://", "https://")):
        return fetch_registry(spec)
    if spec:
        return load_registry_file(Path(spec).expanduser())
    return fetch_registry()


def _http_get(url: str) -> str:
    import urllib.request

    with urllib.request.urlopen(url, timeout=15) as resp:  # noqa: S310
        return resp.read().decode("utf-8")


@voice_app.command("info")
def voice_info() -> None:
    """Show whether local voice (transcribe / TTS) is available."""
    from openpup.voice import transcription_available, tts_available

    console.print(
        f"[cyan]transcription:[/cyan] {'available' if transcription_available() else 'not installed'}"
    )
    console.print(
        f"[cyan]tts:[/cyan] {'available' if tts_available() else 'not installed'}"
    )
    console.print("Install with: pip install 'openpup[voice]' (local) or 'openpup[voice-cloud]' (cloud).")


@voice_app.command("transcribe")
def voice_transcribe(
    audio: str = typer.Argument(..., help="Path to an audio file (ogg/wav/mp3)."),
    model: str = typer.Option("small", "--model", "-m", help="Whisper model size (tiny/base/small/medium)."),
    language: str = typer.Option("en", "--language", "-l", help="Language hint."),
) -> None:
    """Transcribe an audio file to text."""
    from openpup.voice import transcribe

    result = transcribe(audio, model=model, language=language)
    console.print(result.text)


@voice_app.command("speak")
def voice_speak(
    text: str = typer.Argument(..., help="Text to synthesize."),
    out: str = typer.Option("out.wav", "--out", "-o", help="Output WAV path."),
) -> None:
    """Synthesize text to a WAV file (local TTS)."""
    from pathlib import Path

    from openpup.voice import speak

    data = speak(text)
    Path(out).write_bytes(data)
    console.print(f"[green]wrote[/green] {out} ({len(data):,} bytes)")


@calendar_app.command("today")
def calendar_today() -> None:
    """List today's events from the configured calendar."""
    from datetime import datetime, timezone

    from openpup.calendar_integration import default_calendar, get_backend

    now = datetime.now(timezone.utc)
    end = now.replace(hour=23, minute=59, second=59)
    backend = get_backend()
    cal_name = default_calendar()
    events = backend.list_events(cal_name, now.replace(hour=0, minute=0, second=0), end)
    if not events:
        console.print("[dim]no events today[/dim]")
        return
    table = Table(title=f"Today ({len(events)})")
    table.add_column("time", style="cyan")
    table.add_column("summary")
    table.add_column("location")
    for e in events:
        table.add_row(e.start.strftime("%H:%M"), e.summary, e.location or "-")
    console.print(table)


@calendar_app.command("week")
def calendar_week() -> None:
    """List the next 7 days of events."""
    from datetime import datetime, timedelta, timezone

    from openpup.calendar_integration import default_calendar, get_backend

    now = datetime.now(timezone.utc)
    end = now + timedelta(days=7)
    backend = get_backend()
    cal_name = default_calendar()
    events = backend.list_events(cal_name, now, end, limit=50)
    if not events:
        console.print("[dim]no events in the next 7 days[/dim]")
        return
    table = Table(title=f"Next 7 days ({len(events)})")
    table.add_column("date", style="cyan")
    table.add_column("time")
    table.add_column("summary")
    table.add_column("location")
    for e in events:
        table.add_row(e.start.strftime("%Y-%m-%d"), e.start.strftime("%H:%M"), e.summary, e.location or "-")
    console.print(table)


@rag_app.command("index")
def rag_index_cmd(
    path: str = typer.Argument(".", help="Directory or file to index."),
) -> None:
    """Index a local folder into the RAG store."""
    from openpup.rag import get_store

    p = Path(path).expanduser()
    if not p.exists():
        console.print(f"[red]{p} does not exist[/red]")
        raise typer.Exit(1)
    store = get_store()
    if p.is_file():
        n = store.ingest_file(p)
        console.print(f"[green]indexed[/green] {p}: {n} chunks")
    else:
        total = 0
        count = 0
        for f in _iter_files(p):
            n = store.ingest_file(f)
            total += n
            count += 1
        console.print(f"[green]indexed[/green] {count} files, {total} total chunks")


@rag_app.command("search")
def rag_search_cmd(
    query: str = typer.Argument(..., help="Search query."),
    limit: int = typer.Option(5, "--limit", "-n"),
) -> None:
    """Search the RAG index."""
    from openpup.rag import get_store

    store = get_store()
    results = store.search(query, limit=limit)
    if not results:
        console.print(f"[dim]no matches for {query!r}[/dim]")
        return
    for r in results:
        console.print(f"[cyan]{r.citation}[/cyan]")
        console.print(f"  {r.text[:200]}{'...' if len(r.text) > 200 else ''}")


def _iter_files(root: Path):
    """Yield files under root, skipping dotfiles and binary cache dirs."""
    skip_dirs = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}
    for entry in root.rglob("*"):
        if not entry.is_file():
            continue
        parts = set(entry.parts)
        if parts & skip_dirs:
            continue
        if any(p.startswith(".") for p in entry.relative_to(root).parts[:-1]):
            continue
        yield entry


@group_app.command("show")
def group_show(
    platform: str = typer.Argument(..., help="Platform name (e.g. telegram, discord)."),
) -> None:
    """Show the current group-chat policy for a platform."""
    from openpup.group_policy import get_store

    pol = get_store().get(platform)
    console.print(f"[cyan]{pol.platform}[/cyan] mode={pol.mode} require_mention={pol.require_mention} require_keyword={pol.require_keyword!r}")


@group_app.command("set")
def group_set(
    platform: str = typer.Argument(..., help="Platform name (e.g. telegram, discord)."),
    mode: str = typer.Option("smart", "--mode", help="smart | open | silent."),
    require_mention: bool = typer.Option(True, "--require-mention/--no-require-mention", help="Require an @mention before replying in groups."),
    require_keyword: str = typer.Option("", "--keyword", help="Also treat this literal substring as a mention."),
) -> None:
    """Set the group-chat policy for a platform."""
    from openpup.group_policy import MODES, GroupPolicy, get_store

    if mode not in MODES:
        console.print(f"[red]mode must be one of: {', '.join(MODES)}[/red]")
        raise typer.Exit(1)
    pol = GroupPolicy(
        platform=platform,
        mode=mode,
        require_mention=bool(require_mention),
        require_keyword=require_keyword,
    )
    get_store().upsert(pol)
    console.print(f"[green]saved[/green] {platform}: mode={pol.mode} require_mention={pol.require_mention} keyword={pol.require_keyword!r}")


@group_app.command("list")
def group_list() -> None:
    """List group-chat policies per platform."""
    from openpup.group_policy import get_store

    policies = get_store().load()
    if not policies:
        console.print("[dim]no per-platform group policies (defaults to 'dm_only' implicit)[/dim]")
        return
    table = Table(title="Group policies")
    table.add_column("platform", style="cyan")
    table.add_column("mode")
    table.add_column("require_mention")
    table.add_column("keyword")
    for name in sorted(policies):
        p = policies[name]
        table.add_row(
            p.platform,
            p.mode,
            "yes" if p.require_mention else "no",
            p.require_keyword or "-",
        )
    console.print(table)


@household_app.command("show")
def household_show() -> None:
    """Show whether household mode is on and the default role policies."""
    from openpup.household import describe_household

    s = get_settings()
    info = describe_household(s)
    console.print(f"[cyan]Household mode:[/cyan] {'on' if info['enabled'] else 'off'}")
    if not info["enabled"]:
        return
    table = Table(title="Role policies")
    table.add_column("role", style="cyan")
    table.add_column("description")
    table.add_column("send", justify="center")
    table.add_column("cal", justify="center")
    table.add_column("browse", justify="center")
    table.add_column("email", justify="center")
    table.add_column("routines", justify="center")
    table.add_column("config", justify="center")
    for role, p in info["policies"].items():
        table.add_row(
            role,
            p["description"],
            "Y" if p["can_send_messages"] else "-",
            "Y" if p["can_use_calendar"] else "-",
            "Y" if p["can_use_browser"] else "-",
            "Y" if p["can_read_email"] else "-",
            "Y" if p["can_schedule_routines"] else "-",
            "Y" if p["can_modify_config"] else "-",
        )
    console.print(table)


@household_app.command("on")
def household_on() -> None:
    """Enable household mode (writes to .env / config store)."""
    from openpup.config_store import get_config_store

    get_config_store().set("OPENPUP_HOUSEHOLD_MODE", "true")
    get_config_store().save()
    console.print("[green]household mode on[/green]")


@household_app.command("off")
def household_off() -> None:
    """Disable household mode."""
    from openpup.config_store import get_config_store

    get_config_store().set("OPENPUP_HOUSEHOLD_MODE", "false")
    get_config_store().save()
    console.print("[green]household mode off[/green]")


@backup_app.command("list")
def backup_list(
    target: Optional[str] = typer.Option(
        None, "--target", help="local:PATH or s3:BUCKET[/PREFIX]."
    ),
) -> None:
    """List backups in a target."""
    tgt = _backup_target(target)
    names = tgt.list() if hasattr(tgt, "list") else []
    if not names:
        console.print("[dim]no backups found[/dim]")
        return
    table = Table(title="Backups")
    table.add_column("name", style="cyan")
    for n in names:
        table.add_row(n)
    console.print(table)


@backup_app.command("verify")
def backup_verify(
    name: str = typer.Argument(..., help="Name of the backup to verify."),
    target: Optional[str] = typer.Option(
        None, "--target", help="local:PATH or s3:BUCKET[/PREFIX]."
    ),
    passphrase: Optional[str] = typer.Option(
        None, "--passphrase", help="Use this passphrase (skip interactive prompt)."
    ),
) -> None:
    """Decrypt a backup and print its metadata without extracting."""
    from openpup.backup import verify_backup as _verify

    passphrase = passphrase or os.environ.get("OPENPUP_BACKUP_PASSPHRASE")
    pw = _backup_passphrase(passphrase)

    tgt = _backup_target(target)
    v = _verify(tgt, name, pw)
    console.print(f"[green]{name}[/green] is valid")
    console.print(f"  size:    {v['size_bytes']:,} bytes (encrypted)")
    console.print(f"  tar:     {v['tar_size_bytes']:,} bytes")
    md = v.get("metadata", {})
    for k in ("format_version", "created_at", "hostname", "openpup_version", "source_path"):
        if k in md:
            console.print(f"  {k}: {md[k]}")


if __name__ == "__main__":
    app()
