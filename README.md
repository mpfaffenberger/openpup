# OpenPup

**An always-on AI companion built on the [code-puppy](https://github.com/mpfaffenberger/code_puppy) SDK.**

OpenPup wraps code-puppy as a *library* and adds three things to turn a coding
agent into a persistent, reachable companion:

1. **Memory** - persistent local memory via code-puppy's `puppy_kennel`
   (SQLite + FTS5, no daemon, no cloud).
2. **A consciousness heartbeat** - a periodic loop that lets the agent
   *think on its own*: idle self-reflection, proactive outreach, scheduled
   routines, and inbound polling.
3. **Messaging integrations** - reach it (and let it reach you) over
   **Discord, Telegram, WhatsApp, Email, and SMS**.

---

## How it works

```
            inbound msg                          outbound reply / proactive ping
 Discord  ┐                                                          ┌ Discord
 Telegram ┤                                                          ┤ Telegram
 WhatsApp ┼──> PlatformRegistry ──> OpenPup runtime ──> AgentHost ──>┼ WhatsApp
 Email    ┤        (envelopes)         (routing)      (code-puppy)   ┤ Email
 SMS      ┘                                  │                       └ SMS
                                             │
                                  ┌──────────┴──────────┐
                                  │   Heartbeat (loop)  │
                                  │  reflect / outreach │
                                  │  routines / inbound │
                                  └──────────┬──────────┘
                                             │
                                     puppy_kennel memory
```

- The agent is code-puppy plus OpenPup's own tools: `openpup_check_email`,
  `openpup_send_message`, `openpup_list_platforms`, `openpup_browse` (a
  stealth browser — see *Platform notes*), and (optionally) the **Universal
  Constructor** (`universal_constructor`) so it can build brand-new tools for
  itself at runtime. So "check my email" or "text my owner" just work.
- Every inbound message becomes a normalized **`Envelope`** and is routed
  through the agent; the reply goes back out on the same channel.
- The **heartbeat** ticks on a jittered interval and runs whichever behaviors
  you enable. Idle reflection reads recent memory, writes a short private
  reflection back to memory, and builds a continuous inner narrative across
  restarts - the "simulated consciousness."
- All long-term state lives in the **kennel** so the mind survives restarts.

## Install

```bash
git clone https://github.com/mpfaffenberger/openpup
cd openpup
uv venv && source .venv/bin/activate
uv pip install -e ".[all]"      # or pick extras: .[discord,telegram,email]
```

Extras: `discord`, `telegram`, `whatsapp` (uses `web`), `email`, `sms`, `web`, `all`.

## Configure

The easiest way is the **interactive TUI** (same arrow-key menu style as
code-puppy's `/agent` and `/model_settings`):

```bash
openpup config
```

It opens a nested menu - Identity & Model, Owner & Memory, Heartbeat, and one
section per platform plus the webhook server - with a live preview pane, secret
masking, on/off toggles, a model picker (pulled from your code-puppy config),
and a behaviors multi-toggle. Changes are written back to `.env`.

```
OpenPup configuration  (/path/.env)

> Identity & Model
  Owner & Memory
  Heartbeat (consciousness)
  Telegram
  ...
  Save & exit
  Exit without saving
+- Preview ----------------------------------------+
| 4 settings - currently on                        |
+--------------------------------------------------+
(Up/Down or Ctrl+P/N to move, Enter to confirm, Esc to cancel)
```

Prefer editing by hand? Copy the template instead:

```bash
cp .env.example .env   # then edit
```

You also need a working code-puppy model configuration (`~/.code_puppy`). Set
`OPENPUP_MODEL` (or use the TUI model picker), or leave it blank for
code-puppy's default.

## Run

```bash
openpup config     # interactive TUI configuration menus
openpup status     # show config + enabled platforms
openpup run        # start the always-on companion (Ctrl-C to stop)
```

Other commands:

```bash
openpup say telegram:123456 "hello from the pup"     # one-off message
openpup memory recall "what did we decide about X"    # search memory
openpup memory recent                                 # recent memories
openpup routine add digest "Summarize today's AI news" \
    --deliver telegram:123456 --daily 08:00           # scheduled routine
openpup routine list
```

## Agentic behavior & prompting (hermes-style)

OpenPup ports hermes-agent's prompting and task-tracking discipline on top of
code-puppy's tool-calling loop, so the agent plans and *finishes* multi-step
work instead of stopping after a stub:

- **Editable identity** — `~/.openpup/SOUL.md` is your pup's persona.
  `~/.openpup/USER.md` holds durable facts about you. Edit the persona from the
  CLI:
  ```bash
  openpup persona          # name + personality + proactivity, with live preview
  ```
  Personality presets: `warm_loyal_sassy` (default), `sharp_dry`, `calm_pro`,
  `chaotic_retriever`. Proactivity: `relentless` (default), `proactive`,
  `balanced`, `reserved`. "Save" regenerates SOUL.md; or drop into `$EDITOR`
  for full hand-control. Also reachable from `openpup config` -> Persona.
- **Layered system prompt** — SOUL identity -> capabilities -> agentic guidance
  ("take action, don't describe it"; "finish the job, never fabricate output";
  memory discipline) -> user profile -> recent-memory snapshot -> timestamp.
- **Task list tool** — `openpup_todo` (ported from hermes) lets the agent
  decompose a request into a plan and work it top-to-bottom, one item
  `in_progress` at a time. Per-conversation, so chats don't share a list.

What's intentionally *not* copied: hermes's own run-loop (code-puppy already has
one) and heavyweight subsystems (kanban/browser/tts). OpenPup's heartbeat +
routines cover recurring autonomous work.

## Comms tooling & governance (hermes-style)

The agent gets a governed cross-platform messaging surface, ported in spirit
from hermes-agent:

- **Contact directory** — OpenPup learns who's reachable from every inbound
  message (persisted to `~/.openpup/contacts.json`). The agent can
  `openpup_contacts(query?)` to list/search them, and address people by **name**
  (`Mike` or `telegram:Mike`) instead of raw chat ids — `openpup_send_message`
  resolves names to addresses.
- **Outbound governance:**
  - **Owner-only** — only the owner can trigger sends (role-gated).
  - **Send policy** (`OPENPUP_SEND_POLICY`): `open` / `contacts` (owner + known
    contacts only) / `owner_only`.
  - **Rate limiting** (`OPENPUP_SEND_RATE_PER_MIN`) — per-platform sliding
    window defuses runaway loops / spam.
  - **Secret redaction** — tokens/keys are scrubbed from tool error text.

This complements inbound access control: `access.py` governs who may talk to
OpenPup; `governance.py` governs who OpenPup may message, and how fast.

## Session recall (hermes-style)

Every conversation turn — yours and the heartbeat's — is recorded to a
transcript store (`~/.openpup/sessions.db`, SQLite + FTS5, same no-daemon
recipe as memory). Sessions are date-bucketed: `{platform}:{channel}:{YYYYMMDD}`
per conversation peer, `heartbeat:{behavior}:{YYYYMMDD}` for the pup's own ticks.

```bash
openpup sessions search "postgres upgrade"        # full-text, best hit per session
openpup sessions recent                           # recently active sessions
openpup sessions show telegram:123456:20260214    # replay one transcript
```

The agent has the same recall via `openpup_session_search` (**owner-only** —
transcripts are private), so "what did we decide about the deploy last week?"
just works. The calling shape picks the mode:

| You pass | Mode |
|----------|------|
| `query` | **discover** — FTS5 search, best hit per session + surrounding context |
| `session_id` | **read** — whole transcript (head/tail truncated when huge) |
| `session_id` + `around_message_id` | **scroll** — ±N messages around an anchor |
| nothing | **browse** — most recently active sessions |

## Skills & the learning loop (hermes-style)

OpenPup learns *procedures*, not just facts. Skills are
[agentskills.io](https://agentskills.io)-compatible `SKILL.md` folders under
`~/.openpup/skills/` (one optional category level; retiring moves a skill to
`.archive/` — nothing is ever deleted). Progressive disclosure: the system
prompt carries only each skill's name + description; the full body is loaded
on demand via the `openpup_skill` tool (`list` / `load` / `create` / `update`
/ `archive` / `unarchive` / `pin` / `unpin` — mutations owner-only).

The prompt wires in a **learning loop**: finish a non-trivial multi-step task
→ save the procedure as a skill; using a skill taught you something → fold the
correction back in; learn a durable fact about the owner → persist it to
memory. Idle reflection surfaces skill candidates too. So "save what you just
did as a skill" works — or drop your own skill folders into
`~/.openpup/skills/` and they're live on the next turn.

An opt-in **curator** heartbeat behavior (add `curator` to
`OPENPUP_HEARTBEAT_BEHAVIORS`) reviews the shelf roughly weekly and archives
long-idle *agent-created* skills. Hermes invariants, verbatim: user skills are
sacred, pinned skills bypass everything, archive only — never delete. Knobs:
`OPENPUP_CURATOR_INTERVAL_HOURS` / `_STALE_AFTER_DAYS` / `_ARCHIVE_AFTER_DAYS`.

## Security hardening

Defense in depth for an agent that strangers can message:

| Layer | What it does |
|-------|--------------|
| Secret redaction (`security/redact.py`) | Deep scrub of tokens / keys / credential URLs from tool errors and outbound text. |
| Skills guard (`security/skills_guard.py`) | Audits skill bodies + bundled scripts (AST) on every load/create/update. Block findings refuse the skill (only *pinned user-created* skills — explicit owner trust — bypass); warn findings get a caution banner; quarantined skills are dropped from the prompt index. |
| Threat guard (`OPENPUP_THREAT_GUARD`, default on) | Scans **non-owner** messages for prompt-injection patterns (instruction override, secret fishing, impersonation) and warns the agent inline. Advisory only — never blocks. Owner messages are never scanned. |
| URL safety (`security/url_safety.check_url`) | SSRF / scheme / private-IP pre-flight for anything fetch-shaped. |
| Approval gate (`security/approval.py`) | Risky actions ping you: `[approval] <summary> — reply 'yes <id>' or 'no <id>'`. Default-deny: no answer within `OPENPUP_APPROVAL_TIMEOUT_S` (300s) means no. |

## Scheduler & reminders

OpenPup has a built-in scheduler (no cron dependency) that the heartbeat drives.
Jobs fire either a **reminder** (plain text delivered verbatim) or a **task** (an
agent prompt whose output is delivered), on one of:

- **one-shot**: `--in <seconds>` or `--at <ISO datetime>` (fires once, then removed)
- **recurring**: `--every <seconds>` or `--daily HH:MM`

```bash
openpup routine add coffee  --message "go get coffee" --in 3600
openpup routine add standup --message "daily standup!" --daily 09:00 --deliver telegram:123
openpup routine add digest  --prompt "Summarize today's AI news" --daily 08:00
openpup routine list
openpup routine rm coffee
```

**The agent can schedule things itself** (owner-only) via bound tools:
`openpup_schedule(...)`, `openpup_list_schedules()`, `openpup_cancel_schedule(name)`.
So "remind me to call mom in 2 hours" or "every morning text me the weather" just
work — delivery defaults to the owner and resolves contact names. The agent and
the heartbeat share one scheduler, so jobs the pup sets fire live.

## Access control (owner + allowlists)

OpenPup distinguishes **you (the owner)** from anyone else who messages the bot.
Privileged tools (reading your email, sending messages on your behalf) are
**owner-only**; the agent is told per-message whether it's talking to you or a
stranger.

You can be the owner on **several platforms at once** (e.g. Telegram *and* your
cell). `OPENPUP_OWNER_ADDRESS` is your primary (default outreach target);
`OPENPUP_OWNER_ADDRESSES` is the full comma-separated list. You're recognized
and reachable at any of them.

```bash
openpup access owner telegram:12345               # set primary
openpup access owner sms:+15559876543 --add       # also recognize your cell
```

> SMS note: `TWILIO_FROM_NUMBER` is the Twilio-owned **sender** number you buy
> in Twilio; your **personal cell** is the owner address (`sms:+1...`). They are
> two different numbers. The setup wizard now asks for both.

Each platform has an access **mode**:

| Mode | Who can interact |
|------|------------------|
| `open` (default) | anyone (but the owner is still distinguished) |
| `allowlist` | the owner + allow-listed senders |
| `owner_only` | only the owner |

```bash
openpup access list                          # show owner + policies
openpup access owner telegram:12345          # mark yourself as owner
openpup access allow telegram 67890          # whitelist a friend (-> allowlist mode)
openpup access mode telegram allowlist       # lock telegram to owner + allowlist
openpup access deny telegram 67890           # remove someone
```

Senders are matched by chat id / phone / email / user id, so it works across
platforms. Policies persist to `~/.openpup/access.json`.

### User roster (editable table per platform)

Every connector has an editable **user table** -- name, handle, **role**, notes:

```bash
openpup users        # pick a platform -> add/edit/remove users
```
(Also under `openpup config` -> Users / Roster.) Users are learned
automatically when people message you, and you can edit them by hand. The
**role** drives access:

| Role | Effect |
|------|--------|
| `(none)` | follows the platform's mode |
| `allowed` | can always talk to the pup, even in allowlist mode |
| `blocked` | messages are dropped |
| `owner` | treated as you |

Backed by `~/.openpup/contacts.json`.

## The heartbeat behaviors

Configured via `OPENPUP_HEARTBEAT_BEHAVIORS` (comma-separated):

| Behavior   | What it does |
|------------|--------------|
| `reflect`  | Reads recent memory, writes a short private reflection back to memory. |
| `outreach` | Decides whether to message you unprompted. Guard-railed: quiet hours + daily cap + the agent must explicitly opt in. |
| `routines` | Runs due scheduled jobs (reminders + tasks) and delivers them (with a `[SILENT]` no-spam escape hatch). |
| `inbound`  | Polls poll-based chat adapters (e.g. iMessage) for new messages. (Email is *not* polled — it's a read-only sensor you watch via a scheduled `openpup_check_email` job.) |
| `curator`  | *(opt-in)* Roughly-weekly maintenance of agent-created skills: archives stale ones (never deletes; pinned bypasses). See *Skills & the learning loop*. |

Tuning knobs (see `.env.example`): `OPENPUP_HEARTBEAT_INTERVAL`,
`OPENPUP_HEARTBEAT_JITTER`, `OPENPUP_QUIET_HOURS`, `OPENPUP_OUTREACH_MAX_PER_DAY`,
`OPENPUP_REFLECTION_MODEL` (use a cheap model for ticks), `OPENPUP_CURATOR_*`
(curator cadence + staleness thresholds).

## Platform notes

- **Discord** - bot token; responds to DMs and @mentions.
- **Telegram** - bot token; long-polling, no public URL needed.
- **WhatsApp** - Meta Cloud API; requires the webhook server
  (`OPENPUP_WEB_ENABLED=true`) reachable over HTTPS + a verified number.
- **Email** - a **one-way, read-only inbox sensor**, *not* a chat channel: the
  pup never auto-replies to incoming mail. It reads your inbox on demand and
  from scheduled checks (`openpup_check_email`, which can return only-new mail
  via a watermark). Ask it to *"check my email every 30m and tell me about new
  ones on topic X"* and it schedules a recurring job that notifies you on your
  normal channel. SMTP out still works when you explicitly ask it to send.
- **SMS** - Twilio; inbound via the webhook server's `/webhook/sms` route.

### Stealth browser (`openpup_browse`)

With the `browser` extra installed (`pip install "openpup[browser]"`), the pup
gets an `openpup_browse(url)` tool backed by
[CloakBrowser](https://github.com/CloakHQ/cloakbrowser) — a fingerprint-evading
Playwright Chromium. Use it to read pages that block plain HTTP clients
(Cloudflare/Turnstile/DataDome/CAPTCHA walls) or that need JS to render. It's
**owner-only** and every URL is run through the same SSRF guard
(`security/url_safety.py`) as the rest of OpenPup, so private/loopback/cloud-
metadata addresses are refused. The stealth Chromium binary downloads
automatically on first use. It's heavier than a plain GET — the pup is told to
reach for it only when a normal fetch would fail.

## Architecture

```
src/openpup/
  config.py            # pydantic-settings, all env config
  runtime.py           # boots everything, central async loop
  agent_host.py        # headless code-puppy SDK harness
  memory.py            # facade over puppy_kennel
  sessions.py          # transcript store (SQLite + FTS5)
  transcripts.py       # fire-and-forget turn recording, date-bucketed ids
  webserver.py         # FastAPI inbound webhooks (WhatsApp/SMS)
  messaging/
    envelope.py        # normalized message model
    registry.py        # adapter registry + delivery
  platforms/
    base.py            # PlatformAdapter interface + factory
    discord_adapter.py telegram_adapter.py whatsapp_adapter.py
    email_adapter.py   sms_adapter.py
  skills/
    store.py           # agentskills.io SKILL.md folders (~/.openpup/skills)
    tool.py            # openpup_skill: the learning loop's hands
    loader.py          # skill index block for the system prompt
  security/
    redact.py          # deep secret redaction
    skills_guard.py    # skill body + bundled-script audit
    threats.py         # inbound prompt-injection advisories
    url_safety.py      # SSRF / scheme / private-IP checks
    approval.py        # owner yes/no approval gate
  heartbeat/
    engine.py          # the tick loop
    scheduler.py       # routine scheduling (no cron dep)
    reflect.py outreach.py routines.py
    curator.py         # opt-in skill-shelf maintenance
  tui/
    select.py          # prompt_toolkit arrow-select + input primitives
    env_store.py       # comment-preserving .env editor
  mcp_server.py        # OPTIONAL: MCP stdio server exposing OpenPup tools
  backup.py            # OPTIONAL: encrypted backup & restore (Argon2id + AES-GCM)
  skills_gallery.py    # OPTIONAL: community skill registry install/publish
  web_dashboard.py     # OPTIONAL: local web dashboard (FastAPI)
  heartbeat/
    briefings.py        # OPTIONAL: RSS/Atom digest heartbeat behavior
  group_policy.py       # PER-PLATFORM: chat_type + mention policy (smart/open/silent)
  voice.py              # OPTIONAL: voice transcription + TTS (faster-whisper + pyttsx3)
  calendar_integration.py  # OPTIONAL: CalDAV calendar (iCloud / Fastmail / Nextcloud)
  rag.py                # OPTIONAL: local-files RAG (SQLite FTS5, with PDF + DOCX extras)
  household.py          # PER-USER: role-based access + per-user memory
```

## News briefings

A new opt-in heartbeat behavior (`briefings`) that watches a list of RSS / Atom
feeds and aggregates new items into a single digest delivered to the owner.
Useful for "tell me every morning what's new on X" workflows.

```bash
# .env / settings
OPENPUP_HEARTBEAT_BEHAVIORS=reflect,outreach,routines,inbound,briefings
OPENPUP_BRIEFING_FEEDS=https://hnrss.org/frontpage,https://export.arxiv.org/rss/cs.AI
OPENPUP_BRIEFING_INTERVAL_HOURS=12
```

What it does:
- Fetches each configured feed (RSS 2.0 or Atom).
- Tracks last-seen timestamp per feed in `~/.openpup/briefings_seen.json`.
- Aggregates items newer than the watermark into a single digest.
- Delivers to `OPENPUP_OWNER_ADDRESS` (subject to the same send-policy + quiet-hours
  guards as `outreach`).
- Throttled to at most one digest per hour regardless of cadence.

Pure stdlib XML parsing (no feedparser dep) so it stays light.

## Skill gallery

A small community registry of skills (`registry/skills.json` in this repo by
default). One command to install a community skill:

```bash
# Browse what's available
openpup skills-gallery list
openpup skills-gallery search summary

# Drop a skill into ~/.openpup/skills/
openpup skills-gallery install summarize-url

# Maintainers: package a local skill for the registry
openpup skills-gallery publish ./my-skill --tag web --tag summary
```

Override the registry with `OPENPUP_SKILLS_REGISTRY` (URL or local file path).
Each registry entry pins a `SKILL.md` body (frontmatter + content) for full
reproducibility — the `commit` SHA, when present, pins to a specific
revision.

## Encrypted backup & restore

OpenPup's entire mind lives in `~/.openpup/`. Snapshots it to an encrypted
archive you can restore after a disaster, migration, or new machine. Backups
use **Argon2id + AES-GCM** with a passphrase-derived key, so the storage
target (S3, NAS, friend's box) never sees plaintext.

```bash
uv pip install -e ".[backup]"       # or "[all]"

# Create a snapshot (state dir defaults to ~/.openpup)
openpup backup create --label before-upgrade

# List what's in the backup target
openpup backup list

# Restore into a NEW directory (refuses to clobber existing content)
openpup backup restore 20260215T103000Z-before-upgrade.openpup-backup --to /tmp/pup-restore

# Verify without extracting (decrypts and reads metadata only)
openpup backup verify 20260215T103000Z-before-upgrade.openpup-backup
```

Targets are pluggable. Configure via `OPENPUP_BACKUP_TARGET`:

```bash
# Local dir (default if env unset): ~/.local/share/openpup/backups
export OPENPUP_BACKUP_TARGET="local:/mnt/nas/openpup-backups"

# S3 / S3-compatible (uses standard AWS env vars or instance creds)
export OPENPUP_BACKUP_TARGET="s3:my-bucket/openpup-backups"
```

The passphrase is prompted interactively, or pass `--passphrase` /
`OPENPUP_BACKUP_PASSPHRASE` for scripts. **Don't lose the passphrase** — the
key is derived from it; there's no recovery.

File format: `[16-byte salt][12-byte nonce][AES-GCM ciphertext]`. The tar
inside contains a `VERSION` file with format version, timestamp, hostname,
and OpenPup version for forensic verification.

## Voice transcription & TTS

Optional `voice` extras (faster-whisper + pyttsx3) let the pup **transcribe
inbound voice notes** and **reply with synthesized speech** when the
platform supports audio attachments.

```bash
uv pip install -e ".[voice]"          # local: faster-whisper + pyttsx3
# Or: uv pip install -e ".[voice-cloud]"   # hosted APIs (stub for now)

# Inspect what's available
openpup voice info

# Transcribe an audio file
openpup voice transcribe recording.ogg --language en

# Synthesize text to a WAV
openpup voice speak "Good morning Mike" --out morning.wav
```

Both backends are optional — `openpup.voice.is_available()` tells you whether
local transcription / TTS is installed. Platforms that don't support audio
attachments (email, SMS) just fall back to text replies.

## Calendar integration

Native calendar via CalDAV (iCloud, Fastmail, Nextcloud, Radicale) and a stub
backend for unconfigured setups. Set:

```bash
export OPENPUP_CALENDAR_URL=https://caldav.icloud.com
export OPENPUP_CALENDAR_USER=you@icloud.com
export OPENPUP_CALENDAR_PASSWORD=app-specific-password
export OPENPUP_CALENDAR_DEFAULT=personal
```

Then `openpup calendar today` or `openpup calendar week` to read events.
Tools exposed to the agent (via `openpup_calendar`):
`list_events`, `find_free_slot`, `create_event`, `reschedule`, `cancel`. PDF
(PDF / DOCX) require `pip install 'openpup[rag]'` (see below).

## Local-files RAG (index a personal vault)

Index a folder of notes / docs / code and search them with citations. Uses
SQLite + FTS5 (BM25) for v1 — no model download, no vector store.

```bash
uv pip install -e ".[rag]"             # adds pypdf + python-docx for PDFs

# Index a folder
openpup rag index ~/Notes
openpup rag index ~/code/myproject

# Search
openpup rag search "postgres upgrade"
```

Each result is a `file:line-line` citation. Files supported out of the box:
Markdown, plain text, and common source code. PDF (`.pdf`) and Word
(`.docx`) via `pypdf` + `python-docx` (both optional). The index is
incremental and idempotent — re-running `rag index` on unchanged files is a
no-op.

The store lives at `~/.openpup/rag.sqlite` (BM5 FTS5 table).

## Household mode

When `OPENPUP_HOUSEHOLD_MODE=true`, OpenPup can serve a small group
(owner + partner/family/friends/team/guest) instead of one owner. Each role
gets a default capability set:

| Role | Send | Calendar | Browse | Email | Routines | Config |
|------|------|----------|--------|-------|----------|--------|
| owner | Y | Y | Y | Y | Y | Y |
| partner | Y | Y | Y | - | Y | - |
| family | - | - | Y | - | Y | - |
| friend | - | - | - | - | - | - |
| team | - | Y | Y | - | - | - |
| guest | - | - | - | - | - | - |

```bash
openpup household on
openpup household show     # see default policies per role
openpup household off
```

State persists to `~/.openpup/group_policies.json`-style config-store; users
are tagged in the contact directory with their role, and the agent chooses
tools based on `policy_for(role)`.

## Group-chat etiquette

Per-platform policies control when OpenPup responds in group chats. DMs are
unaffected; group replies are gated on per-platform policy.

```bash
# Default policy: bot must be @mentioned (or contain a keyword) in groups.
openpup group show telegram
openpup group set telegram --mode smart --require-mention --keyword pup
openpup group list
```

Three modes:

| Mode | Behavior |
|------|----------|
| `smart` (default) | Reply only when @mentioned (or keyword present) |
| `open` | Always reply in groups (legacy behavior) |
| `silent` | Never reply in groups (only DMs get a reply) |

The Telegram + Discord adapters populate `Envelope.chat_type` (from the SDK
chat type) and `Envelope.mentions` (from text_mention entities / `message.mentions`).
When `require_mention=true` and the message has no mention / no keyword, the
heartbeat's `handle_inbound` short-circuits without invoking the agent.

State persists to `~/.openpup/group_policies.json` (separate from access.json
so changing group policy doesn't risk your owner / allowlist settings).

## Local web dashboard

A read-only browser surface for inspecting your pup without ssh-ing in or
typing CLI commands. Six tabs cover everything visible about your pup:

| Tab | Shows |
|-----|-------|
| **Status** | Name, model, owner, kennel path, enabled platforms, heartbeat cadence |
| **Memory** | Live kennel search (BM25) — type and hit Enter |
| **Sessions** | Recently active sessions with source + last-active |
| **Skills** | All installed skills (incl. archived), category, state |
| **Routines** | Each scheduled job with last/next fire time |
| **Heartbeat** | Cadence, behaviors, quiet hours |

```bash
uv pip install -e ".[dashboard]"   # or "[all]"
openpup web                          # prints a URL with a random token
```

The dashboard binds to `127.0.0.1` by default (local-only, no network exposure).
Auth is via a random per-install token saved to `~/.openpup/dashboard.token`,
accepted via `?token=...` or `Authorization: Bearer ...`. Override with
`OPENPUP_DASHBOARD_TOKEN` or `OPENPUP_DASHBOARD_HOST` / `_PORT`. No telemetry,
no external requests.

For automation, the same data is available as JSON:

```bash
curl -H 'Authorization: Bearer <token>' http://127.0.0.1:8765/api/status
curl -H 'Authorization: Bearer <token>' 'http://127.0.0.1:8765/api/memory?q=postgres'
```

## MCP server

OpenPup can run as an [MCP](https://modelcontextprotocol.io/) (Model Context
Protocol) server, exposing its tools to MCP-capable clients like **Claude
Desktop**, **Cursor**, and **Windsurf**. One pup can be reached from chat
(Telegram/Discord/etc.) *and* from an MCP client, backed by the same kennel,
sessions, and skills.

```bash
uv pip install -e ".[mcp]"          # or "[all]"
openpup mcp                          # runs an MCP stdio server
```

Add to your MCP client config (e.g. Claude Desktop's
`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "openpup": {
      "command": "openpup",
      "args": ["mcp"],
      "cwd": "/absolute/path/to/openpup"
    }
  }
}
```

Exposed tools (11 total):

| Tool | What it does |
|------|--------------|
| `memory_recall(query, top_k)` | BM25 search the kennel |
| `memory_recent(top_k)` | Most recent memories |
| `memory_store(content, wing?, room?)` | Write a note into the kennel |
| `session_search(query?, session_id?, around_message_id?)` | Search/read/scroll session transcripts |
| `list_platforms()` | Connected platforms + owner address |
| `send_message(address, text)` | Send a message (rate-limited, governed) |
| `list_schedules()` | List scheduled jobs |
| `cancel_schedule(name)` | Remove a scheduled job |
| `list_skills(category?)` | List installed skills |
| `load_skill(name)` | Load a skill's full body |
| `list_contacts(query?)` | List/search contacts |

Owner-trusted by default: the server assumes the operator is the owner (it runs
on the owner's box). For shared deployments, set `OPENPUP_MCP_RESTRICT=true`
to hide privileged tools (`send_message`, `list_contacts`) from the schema.
    menus.py           # the config menu tree
```

## Development

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
ruff check --fix src tests && ruff format src tests
```

## License

MIT. Built on code-puppy. Integration designs inspired by hermes-agent.
