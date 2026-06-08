"""OpenPup command-line interface (Typer).

Commands:
  openpup run                 start the always-on companion
  openpup status              show config + enabled platforms
  openpup say <addr> <text>   send a one-off message to a platform address
  openpup memory recall <q>   search the kennel
  openpup memory recent       show recent memories
  openpup routine add/list/rm manage scheduled routines
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from openpup.config import get_settings

app = typer.Typer(help="OpenPup - an always-on AI companion.", no_args_is_help=True)
memory_app = typer.Typer(help="Inspect OpenPup's memory (puppy_kennel).")
routine_app = typer.Typer(help="Manage scheduled routines.")
app.add_typer(memory_app, name="memory")
app.add_typer(routine_app, name="routine")

console = Console()


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


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
def status() -> None:
    """Show configuration and which platforms are enabled."""
    s = get_settings()
    table = Table(title=f"{s.name} status")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="white")
    table.add_row("Agent", s.agent)
    table.add_row("Model", s.model or "(code-puppy default)")
    table.add_row("Reflection model", s.reflection_model or "(same as agent)")
    table.add_row("Owner", s.owner_address or "(unset)")
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


@routine_app.command("list")
def routine_list() -> None:
    """List configured routines."""
    from openpup.heartbeat.scheduler import Scheduler

    s = get_settings()
    sched = Scheduler.load(s.state_dir / "routines.json")
    if not sched.routines:
        console.print("[dim]no routines[/dim]")
        return
    table = Table(title="Routines")
    for col in ("name", "trigger", "deliver", "enabled"):
        table.add_column(col)
    for r in sched.routines:
        trigger = f"every {r.every}s" if r.every else f"daily {r.daily}"
        table.add_row(r.name, trigger, r.deliver, str(r.enabled))
    console.print(table)


@routine_app.command("add")
def routine_add(
    name: str,
    prompt: str,
    deliver: str = typer.Option(..., help="platform:channel address"),
    every: Optional[int] = typer.Option(None, help="seconds between runs"),
    daily: Optional[str] = typer.Option(None, help="HH:MM local time"),
) -> None:
    """Add or replace a scheduled routine."""
    from openpup.heartbeat.scheduler import Routine, Scheduler

    if not (every or daily):
        console.print("[red]Provide --every or --daily[/red]")
        raise typer.Exit(1)
    s = get_settings()
    sched = Scheduler.load(s.state_dir / "routines.json")
    sched.add(Routine(name=name, prompt=prompt, deliver=deliver, every=every, daily=daily))
    console.print(f"[green]added routine '{name}'[/green]")


@routine_app.command("rm")
def routine_rm(name: str) -> None:
    """Remove a routine by name."""
    from openpup.heartbeat.scheduler import Scheduler

    s = get_settings()
    sched = Scheduler.load(s.state_dir / "routines.json")
    ok = sched.remove(name)
    console.print("[green]removed[/green]" if ok else "[yellow]not found[/yellow]")


if __name__ == "__main__":
    app()
