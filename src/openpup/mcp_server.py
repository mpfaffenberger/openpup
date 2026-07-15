"""OpenPup as an MCP (Model Context Protocol) server.

Run with: ``openpup mcp``

Exposes OpenPup's tools over MCP stdio so they can be called by Claude Desktop,
Cursor, Windsurf, or any other MCP-capable client. The same pup can be reached
from chat (Telegram, Discord, ...) *and* from an MCP client, backed by one
kennel, sessions store, and skills shelf.

Owner-only by default. MCP assumes the operator is the owner (the server runs
on the owner's box); there's no concept of "current message sender" in MCP.
If you want to expose this MCP server to untrusted callers, set
``OPENPUP_MCP_RESTRICT=true`` to hide privileged tools (send_message,
list_contacts, config, etc.) from the schema.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("openpup.mcp")

# Try to import the MCP SDK; required only when actually running the server.
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool

    HAS_MCP = True
except ImportError:
    HAS_MCP = False
    Server = None  # type: ignore[assignment]
    TextContent = None  # type: ignore[assignment]
    Tool = None  # type: ignore[assignment]


def _require_mcp() -> None:
    if not HAS_MCP:
        raise RuntimeError(
            "The MCP extra is required to run the MCP server. "
            "Install with: pip install 'openpup[mcp]' (or 'openpup[all]')."
        )


# ---------------------------------------------------------------------------
# Tool handler protocol
# ---------------------------------------------------------------------------
# Each tool is a (handler, schema) tuple so it can be tested without an MCP
# server running. The schema follows JSON Schema (Draft 7-ish) for inputs.

ToolHandler = Callable[[Dict[str, Any]], Dict[str, Any]]


def _str_result(payload: Any) -> str:
    """Serialize a handler payload as compact JSON for MCP TextContent."""
    return json.dumps(payload, default=str, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------
def tool_memory_recall(args: Dict[str, Any]) -> Dict[str, Any]:
    query = args.get("query")
    if not query or not str(query).strip():
        return {"ok": False, "error": "query is required"}
    top_k = int(args.get("top_k") or 5)
    top_k = max(1, min(top_k, 20))
    from openpup import memory

    results = memory.recall(str(query), top_k=top_k)
    return {"ok": True, "matches": results, "count": len(results)}


def tool_memory_recent(args: Dict[str, Any]) -> Dict[str, Any]:
    top_k = int(args.get("top_k") or 5)
    top_k = max(1, min(top_k, 50))
    from openpup import memory

    results = memory.recent(top_k=top_k)
    return {"ok": True, "memories": results, "count": len(results)}


def tool_memory_store(args: Dict[str, Any]) -> Dict[str, Any]:
    content = args.get("content")
    if not content or not str(content).strip():
        return {"ok": False, "error": "content is required"}
    wing = args.get("wing") or "agent"
    if wing not in ("agent", "user"):
        wing = "agent"
    room = args.get("room") or "notes"
    from openpup import memory

    ok = memory.remember(str(content), wing=wing, room=room)
    return {"ok": ok, "stored_chars": len(str(content))}


def tool_session_search(args: Dict[str, Any]) -> Dict[str, Any]:
    from openpup.sessions import get_session_store

    store = get_session_store()
    query = args.get("query")
    session_id = args.get("session_id")
    around_message_id = args.get("around_message_id")
    window = int(args.get("window") or 5)
    window = max(1, min(window, 20))
    limit = int(args.get("limit") or 3)
    limit = max(1, min(limit, 10))

    try:
        if around_message_id is not None:
            if not session_id:
                return {
                    "ok": False,
                    "error": "around_message_id requires session_id (scroll mode)",
                }
            data = store.messages_around(session_id, int(around_message_id), window=window)
            if not data["messages"]:
                return {
                    "ok": False,
                    "error": f"No message {around_message_id} in session {session_id}.",
                }
            return {
                "ok": True,
                "mode": "scroll",
                "messages": data["messages"],
                "more_before": data["messages_before"],
                "more_after": data["messages_after"],
            }
        if session_id:
            data = store.read_session(session_id)
            if data["session"] is None:
                return {"ok": False, "error": f"Session {session_id} not found."}
            return {
                "ok": True,
                "mode": "read",
                "session": data["session"],
                "messages": data["messages"],
                "truncated": data["truncated"],
                "omitted": data["omitted"],
            }
        if query:
            hits = store.search(str(query), limit=limit)
            results: List[Dict[str, Any]] = []
            for hit in hits:
                ctx = store.messages_around(hit["session_id"], hit["message_id"], window=window)
                results.append({**hit, "context": ctx["messages"]})
            if not results:
                return {
                    "ok": True,
                    "mode": "discover",
                    "matches": [],
                    "message": f"No transcripts match {query!r}.",
                }
            return {
                "ok": True,
                "mode": "discover",
                "matches": results,
                "message": f"{len(results)} session(s) match {query!r}.",
            }
        sessions = store.recent_sessions(limit=limit)
        return {"ok": True, "mode": "browse", "sessions": sessions}
    except Exception as exc:  # noqa: BLE001 — handlers must never raise
        return {"ok": False, "error": f"session_search failed: {exc!r}"}


def tool_list_platforms(args: Dict[str, Any]) -> Dict[str, Any]:
    from openpup.config import get_settings
    from openpup.messaging.registry import get_registry

    reg = get_registry()
    owner = get_settings().owner_address
    return {"ok": True, "platforms": reg.platforms(), "owner": owner}


def tool_send_message(args: Dict[str, Any]) -> Dict[str, Any]:
    import asyncio

    from openpup.directory import get_directory
    from openpup.governance import get_send_policy
    from openpup.messaging.envelope import Envelope
    from openpup.messaging.registry import get_registry
    from openpup.platforms.base import build_enabled_adapters

    address = args.get("address")
    text = args.get("text")
    if not address or not text:
        return {"ok": False, "error": "address and text are required"}

    settings = __import__("openpup.config", fromlist=["get_settings"]).get_settings()

    async def _send() -> bool:
        registry = get_registry()
        adapters = build_enabled_adapters(settings, registry)
        for a in adapters:
            await a.start()
        try:
            directory = get_directory()
            resolved = directory.resolve(address) or address
            if ":" not in resolved:
                return False
            return await registry.send(Envelope.to(resolved, text))
        finally:
            for a in adapters:
                await a.stop()

    try:
        decision = get_send_policy().check(address, directory=get_directory())
        if not decision.allowed:
            return {"ok": False, "error": decision.reason}
        ok = asyncio.run(_send())
        return {"ok": ok, "address": address}
    except Exception as exc:  # noqa: BLE001 — handlers must never raise
        return {"ok": False, "error": f"send failed: {exc!r}"}


def tool_list_schedules(args: Dict[str, Any]) -> Dict[str, Any]:
    from openpup.heartbeat.scheduler import get_scheduler

    sched = get_scheduler()
    return {
        "ok": True,
        "schedules": [
            {
                "name": r.name,
                "when": r.describe_when(),
                "last_run": r.describe_last(),
                "next_run": r.describe_next(__import__("time").time()),
                "enabled": r.enabled,
                "is_one_shot": r.is_one_shot,
                "deliver": r.deliver or None,
                "message": r.message or None,
                "prompt": r.prompt or None,
            }
            for r in sched.routines
        ],
    }


def tool_cancel_schedule(args: Dict[str, Any]) -> Dict[str, Any]:
    name = args.get("name")
    if not name:
        return {"ok": False, "error": "name is required"}
    from openpup.heartbeat.scheduler import get_scheduler

    sched = get_scheduler()
    removed = sched.remove(name)
    return {"ok": removed, "removed": removed, "name": name}


def tool_list_skills(args: Dict[str, Any]) -> Dict[str, Any]:
    from openpup.skills.store import get_skill_store

    store = get_skill_store()
    skills = store.list(include_archived=True)
    category = (args.get("category") or "").strip() or None
    out: List[Dict[str, Any]] = []
    for s in skills:
        if category and s.category != category:
            continue
        out.append(
            {
                "name": s.name,
                "description": s.description,
                "category": s.category,
                "state": s.state,
                "created_by": s.created_by,
            }
        )
    return {"ok": True, "skills": out, "count": len(out)}


def tool_load_skill(args: Dict[str, Any]) -> Dict[str, Any]:
    name = args.get("name")
    if not name:
        return {"ok": False, "error": "name is required"}
    from openpup.skills.store import get_skill_store

    store = get_skill_store()
    skill = store.get(str(name))
    if skill is None:
        return {"ok": False, "error": f"Skill {name!r} not found."}
    return {
        "ok": True,
        "name": skill.name,
        "description": skill.description,
        "category": skill.category,
        "body": skill.body,
    }


def tool_list_contacts(args: Dict[str, Any]) -> Dict[str, Any]:
    from openpup.directory import get_directory

    query = (args.get("query") or "").strip() or None
    directory = get_directory()
    rows = directory.search(query)
    contacts = [
        {
            "platform": c["platform"],
            "channel": c["channel"],
            "name": c.get("name", c["channel"]),
            "address": f"{c['platform']}:{c['channel']}",
        }
        for c in rows
    ]
    return {"ok": True, "contacts": contacts, "count": len(contacts)}


# ---------------------------------------------------------------------------
# Tool registry: tool definitions and their handlers
# ---------------------------------------------------------------------------
TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "memory_recall",
        "description": (
            "Search the OpenPup kennel for memories matching a query. Returns "
            "matching drawer contents (newest first). Use this when answering "
            "questions about what was previously discussed or remembered."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query."},
                "top_k": {
                    "type": "integer",
                    "description": "Max results to return (1-20).",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20,
                },
            },
            "required": ["query"],
        },
        "handler": tool_memory_recall,
    },
    {
        "name": "memory_recent",
        "description": (
            "Return the most recent memories (no query needed). Useful for "
            "getting oriented to the pup's recent context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "top_k": {
                    "type": "integer",
                    "description": "How many memories to return (1-50).",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 50,
                },
            },
        },
        "handler": tool_memory_recent,
    },
    {
        "name": "memory_store",
        "description": (
            "Write a verbatim note into the kennel so it's recallable later. "
            "Use wing='user' for facts about the owner (preferences, "
            "biographical); wing='agent' for the pup's own notes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Note content to store."},
                "wing": {
                    "type": "string",
                    "enum": ["agent", "user"],
                    "default": "agent",
                    "description": "Which memory wing to write to.",
                },
                "room": {
                    "type": "string",
                    "default": "notes",
                    "description": "Room within the wing (defaults to 'notes').",
                },
            },
            "required": ["content"],
        },
        "handler": tool_memory_store,
    },
    {
        "name": "session_search",
        "description": (
            "Recall past conversation transcripts. Mode is selected by which "
            "args are present: (query)=discover (FTS5 search); (session_id)="
            "read whole session; (session_id + around_message_id)=scroll "
            "+/-N messages around an anchor; (nothing)=browse most recently "
            "active sessions. Transcripts are owner-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "FTS5 search query (discover mode).",
                },
                "session_id": {
                    "type": "string",
                    "description": "Specific session to read or scroll.",
                },
                "around_message_id": {
                    "type": "integer",
                    "description": "Anchor message id for scroll mode.",
                },
                "window": {
                    "type": "integer",
                    "description": "Context window each side (1-20).",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20,
                },
                "limit": {
                    "type": "integer",
                    "description": "Max sessions in discover/browse (1-10).",
                    "default": 3,
                    "minimum": 1,
                    "maximum": 10,
                },
            },
        },
        "handler": tool_session_search,
    },
    {
        "name": "list_platforms",
        "description": (
            "List the messaging/email platforms OpenPup currently has connected, "
            "plus the owner's primary address."
        ),
        "input_schema": {"type": "object", "properties": {}},
        "handler": tool_list_platforms,
    },
    {
        "name": "send_message",
        "description": (
            "Send a message to someone on a connected platform. Address can be "
            "'platform:channel' (e.g. 'telegram:12345', 'sms:+15551234567') or "
            "a known contact name (use list_contacts to find one). Governed by "
            "the configured send policy and per-platform rate limit."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": "Target address or contact name.",
                },
                "text": {"type": "string", "description": "Message body."},
            },
            "required": ["address", "text"],
        },
        "handler": tool_send_message,
        "privileged": True,
    },
    {
        "name": "list_schedules",
        "description": (
            "List scheduled jobs (reminders and tasks). Returns each job's "
            "name, timing, last/next fire, and content."
        ),
        "input_schema": {"type": "object", "properties": {}},
        "handler": tool_list_schedules,
    },
    {
        "name": "cancel_schedule",
        "description": "Remove a scheduled job by name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Job name to remove."},
            },
            "required": ["name"],
        },
        "handler": tool_cancel_schedule,
    },
    {
        "name": "list_skills",
        "description": (
            "List installed skills. Optionally filter by category. Each entry "
            "has name, description, category, archived flag, and pinned flag."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Optional category filter (e.g. 'web', 'ops').",
                },
            },
        },
        "handler": tool_list_skills,
    },
    {
        "name": "load_skill",
        "description": (
            "Load the full body of a skill by name. Use list_skills to find available skills first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Skill name to load."},
            },
            "required": ["name"],
        },
        "handler": tool_load_skill,
    },
    {
        "name": "list_contacts",
        "description": (
            "List or search known contacts OpenPup can message. Pass a query "
            "to filter by name/channel/platform."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional filter on name/channel/platform.",
                },
            },
        },
        "handler": tool_list_contacts,
        "privileged": True,
    },
]


# ---------------------------------------------------------------------------
# MCP server wiring (only invoked when actually running)
# ---------------------------------------------------------------------------
def _restricted_mode() -> bool:
    """If True, hide privileged tools (send_message, list_contacts, etc.).

    Default False: this MCP server is owner-trusted (it runs on the owner's
    box). Set ``OPENPUP_MCP_RESTRICT=true`` for shared deployments where the
    server might be called by non-owners.
    """
    flag = (os.environ.get("OPENPUP_MCP_RESTRICT") or "").strip().lower()
    return flag in ("1", "true", "yes", "on")


def build_server() -> Any:
    """Build and return an MCP Server instance with all tools registered.

    Returned server is not yet running; call ``run_server(server)`` to start.
    """
    _require_mcp()

    server = Server("openpup")
    restricted = _restricted_mode()
    visible = [t for t in TOOL_DEFINITIONS if not (restricted and t.get("privileged"))]
    logger.info(
        "starting openpup mcp server (%d tools, restricted=%s)",
        len(visible),
        restricted,
    )

    @server.list_tools()  # type: ignore[misc]
    async def _list_tools() -> List[Any]:
        return [
            Tool(
                name=t["name"],
                description=t["description"],
                inputSchema=t["input_schema"],
            )
            for t in visible
        ]

    @server.call_tool()  # type: ignore[misc]
    async def _call_tool(name: str, arguments: Dict[str, Any]) -> List[Any]:
        handler: Optional[ToolHandler] = next(
            (t["handler"] for t in TOOL_DEFINITIONS if t["name"] == name), None
        )
        if handler is None:
            return [
                TextContent(
                    type="text",
                    text=_str_result({"ok": False, "error": f"unknown or hidden tool {name!r}"}),
                )
            ]
        try:
            payload = handler(arguments or {})
        except Exception as exc:  # noqa: BLE001
            logger.exception("tool %s failed", name)
            payload = {"ok": False, "error": f"{exc!r}"}
        return [TextContent(type="text", text=_str_result(payload))]

    return server


async def run_server() -> None:
    """Entry point: build the server, run on stdio until EOF."""
    _require_mcp()
    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    """Console-script entry: run the stdio server synchronously."""
    # Quiet stderr logging unless explicitly asked; MCP clients hate noise.
    logging.basicConfig(
        level=os.environ.get("OPENPUP_LOG_LEVEL", "WARNING").upper(),
        stream=sys.stderr,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    try:
        import asyncio

        asyncio.run(run_server())
    except KeyboardInterrupt:
        pass
    except Exception:
        logger.exception("MCP server crashed")
        raise


if __name__ == "__main__":  # pragma: no cover
    main()
