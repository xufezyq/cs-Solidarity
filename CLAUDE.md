# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

cs-Solidarity is a multi-functional WeChat (微信) chat bot built on the `wxauto` GUI automation library. **Windows only** — it automates WeChat PC client via Win32 API and UI automation. Features: Steam game monitoring, scheduled messages, AI chat (DeepSeek/OpenAI-compatible), KoriChat intelligent assistant, and information push (gold prices, stocks, news). Includes a web-based remote management panel (Agent-Server WebSocket architecture).

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot (requires WeChat PC client running)
python main.py

# Web control panel (separate process/machine)
pip install -r web/requirements.txt
cd web && uvicorn server:app --host 0.0.0.0 --port 8000

# Agent client (runs on bot machine, connects to web panel)
pip install -r agent/requirements.txt
python agent/client.py --server ws://SERVER:8000/ws/agent --token TOKEN --root PATH
```

No test suite, linter, or CI/CD is configured. Python 3.7+ for the bot, 3.9+ for the web panel.

## Architecture

### Thread Model (Critical)

**All WeChat GUI operations must run on the main thread.** Background daemon threads run business logic but their `send_message()` calls are monkey-patched at startup to enqueue messages into `msg_queue` instead of executing directly. The main thread serially drains the queue.

Main loop order each iteration:
1. Maintenance window check (00:15–08:00 stops all operations; `debug_mode` skips this)
2. Process send queue (all pending sends before any receives)
3. Flash detection → receive messages → dispatch to instances
4. Idle timeout → minimize WeChat window

**Send-before-receive ordering exists to prevent race conditions** — `ChatWith()` clears unread state, so all sends (which call `ChatWith`) must complete before the receive phase reads unread messages.

### Instance/Plugin System

All feature modules extend `BaseInstance` (core/base_instance.py) with three methods:
- `start()` — background loop running in a daemon thread
- `send_message(message)` — called by main thread to actually send (hooked to enqueue at runtime)
- `handle_message(chat_name, msg)` — optional, receives incoming messages

Instances are registered via factory pattern in `core/instance_factory.py`. The `config.json` `type` field maps to registered factory functions. Current types: `steam`, `daily`, `chat`, `korichat`, `infopush`.

### Message Routing

Two-tier dispatch in `main.py`:
- **Exclusive instances** — have a `trigger_prefix` (e.g., ChatAuto with `/claw`). Matching messages go only to that instance.
- **Broadcast instances** — no `trigger_prefix` (e.g., KoriChat). Receive all non-exclusive messages.

### Anti-Detection

`core/wechat_instance.py` monkey-patches `uiautomation.SetCursorPos` and `uiautomation.Click` to inject Gaussian jitter (±1px) and randomized delays (10–120ms). Polling uses Gaussian-distributed intervals (0.3s ± 0.15s). All human-facing delays use `utils/human_sim.py`.

### Dual Capture Mechanism

When sending a message, the system captures unread messages in two phases to prevent data loss:
1. **Pre-capture** — reads unread messages from target chat via `GetAllNewMessage()` *before* `ChatWith()` (which clears unread state)
2. **During-capture** — after sending, diffs message list to catch messages that arrived during send

Both batches are merged and deduplicated by message ID.

### Web Panel: Agent-Server Model

- `web/server.py` — FastAPI server (public-facing), serves Vue 3 SPA from `web/static/index.html`
- `agent/client.py` — WebSocket client on bot's machine, handles config read/write, bot control, log streaming
- `shared/protocol.py` — JSON message protocol (request/response/push/ping)
- JWT auth with admin/user roles in `web/auth.py`

## Configuration

- `config.json` — master config: `debug_mode` flag + list of instance entries with `type` and optional `config` path
- `instconfig/*.json` — per-instance configs (API keys, schedules, trigger prefixes, target groups/chats)
- Instance configs are loaded by each instance's `create_from_config()` or `create_from_data()` class method

## Key Directories

- `wxauto/` — vendored WeChat PC automation library (core dependency)
- `KouriChat/` — vendored KoriChat AI assistant project
- `steam/` — Steam Web API wrapper
- `cs2_pw/` — Perfect World (完美世界) platform API for CS2
- `pywechat/` — vendored alternative WeChat automation library

## Adding a New Instance Type

1. Create a class extending `BaseInstance` in `instances/`
2. Register it in `core/instance_factory.py` via `register_instance_type()`
3. Add a config entry in `config.json`
