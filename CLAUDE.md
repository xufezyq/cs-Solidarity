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
cd web && uvicorn server:app --host 0.0.0.0 --port 11029

# Agent client (runs on bot machine, connects to web panel)
pip install -r agent/requirements.txt
python agent/client.py --server ws://SERVER:11029/ws/agent --token TOKEN --root PATH
```

No test suite, linter, or CI/CD is configured. Python 3.10+ is required for the bot because parts of the project use modern type syntax; Python 3.11 is recommended. The web panel needs Python 3.9+.

## Coding Guidelines

### Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

## Architecture

### Thread Model (Critical)

**All WeChat GUI operations must run on the main thread.** Background daemon threads run business logic but their `send_message()` calls are monkey-patched at startup to enqueue messages into `msg_queue` instead of executing directly. The main thread serially drains the queue.

Main loop order each iteration:
1. Process Web chat queue (`web_msg_queue`) even when WeChat receive is disabled
2. Maintenance window check (00:15–08:00 reduces normal operations; `debug_mode` skips this)
3. Process instance send queue and local API queue (all pending sends before any receives)
4. Flash detection → receive messages → dispatch to instances
5. Idle timeout → switch to File Transfer Assistant and minimize WeChat window

**Send-before-receive ordering exists to prevent race conditions** — `ChatWith()` clears unread state, so all sends (which call `ChatWith`) must complete before the receive phase reads unread messages.

### Instance/Plugin System

All feature modules extend `BaseInstance` (core/base_instance.py) with three methods:
- `start()` — background loop running in a daemon thread
- `send_message(message)` — called by main thread to actually send (hooked to enqueue at runtime)
- `handle_message(chat_name, msg)` — optional, receives incoming messages

Instances are registered via factory pattern in `core/instance_factory.py`. The `config.json` `type` field maps to registered factory functions. Current default types are: `steam`, `daily`, `chat`, `korichat`, `infopush`, `disaster_warning`. `chat` may point at a shared `instconfig/chat_configs.json` and select a named config through the instance item's `name` field.

### Message Routing

Two-tier dispatch in `main.py`:
- **Exclusive instances** — have a `trigger_prefix` (e.g., ChatAuto with `/claw`). Matching messages go only to that instance.
- **Broadcast instances** — no `trigger_prefix` (e.g., KoriChat). Receive all non-exclusive messages.

### Anti-Detection

`core/wechat_instance.py` monkey-patches `uiautomation.SetCursorPos`, `uiautomation.Click`, `uiautomation.SendKeys`, `wxauto.Click`, `wxauto._show`, and `win32api.SetCursorPos` to inject jitter, Bezier-like movement, randomized delays, and safer window focus behavior. Polling uses `random_poll_interval(2.0, 1.5)`, a clamped log-normal interval with a long tail. All human-facing delays use `utils/human_sim.py`.

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
- Web chat uses `/api/chat/send` → Agent `chat.send` → local TCP chat server on `127.0.0.1:18766` → `web_msg_queue`.
- The bot also starts a local HTTP API on `127.0.0.1:18800` for same-machine tools to enqueue text/file sends.
- File management supports `web` storage in `web/shared_files/` and `agent` storage in the Agent-side `shared_files/`.

## Configuration

- `config.json` — master config: `debug_mode`, `mock_send`, send/receive/flash switches, maintenance window, optional `web_chat.target_group`, and instance entries with `type`, optional `config`, and optional `name`
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


# Superpowers-ZH 中文增强版

本项目已安装 superpowers-zh 技能框架（20 个 skills）。

## 核心规则

1. **收到任务时，先检查是否有匹配的 skill** — 哪怕只有 1% 的可能性也要检查
2. **设计先于编码** — 收到功能需求时，先用 brainstorming skill 做需求分析
3. **测试先于实现** — 写代码前先写测试（TDD）
4. **验证先于完成** — 声称完成前必须运行验证命令

## 可用 Skills

Skills 位于 `.claude/skills/` 目录，每个 skill 有独立的 `SKILL.md` 文件。

- **brainstorming**: 在任何创造性工作之前必须使用此技能——创建功能、构建组件、添加功能或修改行为。在实现之前先探索用户意图、需求和设计。
- **chinese-code-review**: 中文代码审查规范——在保持专业严谨的同时，用符合国内团队文化的方式给出有效反馈
- **chinese-commit-conventions**: 中文 Git 提交规范 — 适配国内团队的 commit message 规范和 changelog 自动化
- **chinese-documentation**: 中文技术文档写作规范——排版、术语、结构一步到位，告别机翻味
- **chinese-git-workflow**: 适配国内 Git 平台和团队习惯的工作流规范——Gitee、Coding、极狐 GitLab、CNB 全覆盖
- **dispatching-parallel-agents**: 当面对 2 个以上可以独立进行、无共享状态或顺序依赖的任务时使用
- **executing-plans**: 当你有一份书面实现计划需要在单独的会话中执行，并设有审查检查点时使用
- **finishing-a-development-branch**: 当实现完成、所有测试通过、需要决定如何集成工作时使用——通过提供合并、PR 或清理等结构化选项来引导开发工作的收尾
- **mcp-builder**: MCP 服务器构建方法论 — 系统化构建生产级 MCP 工具，让 AI 助手连接外部能力
- **receiving-code-review**: 收到代码审查反馈后、实施建议之前使用，尤其当反馈不明确或技术上有疑问时——需要技术严谨性和验证，而非敷衍附和或盲目执行
- **requesting-code-review**: 完成任务、实现重要功能或合并前使用，用于验证工作成果是否符合要求
- **subagent-driven-development**: 当在当前会话中执行包含独立任务的实现计划时使用
- **systematic-debugging**: 遇到任何 bug、测试失败或异常行为时使用，在提出修复方案之前执行
- **test-driven-development**: 在实现任何功能或修复 bug 时使用，在编写实现代码之前
- **using-git-worktrees**: 当需要开始与当前工作区隔离的功能开发或执行实现计划之前使用——创建具有智能目录选择和安全验证的隔离 git 工作树
- **using-superpowers**: 在开始任何对话时使用——确立如何查找和使用技能，要求在任何响应（包括澄清性问题）之前调用 Skill 工具
- **verification-before-completion**: 在宣称工作完成、已修复或测试通过之前使用，在提交或创建 PR 之前——必须运行验证命令并确认输出后才能声称成功；始终用证据支撑断言
- **workflow-runner**: 在 Claude Code / OpenClaw / Cursor 中直接运行 agency-orchestrator YAML 工作流——无需 API key，使用当前会话的 LLM 作为执行引擎。当用户提供 .yaml 工作流文件或要求多角色协作完成任务时触发。
- **writing-plans**: 当你有规格说明或需求用于多步骤任务时使用，在动手写代码之前
- **writing-skills**: 当创建新技能、编辑现有技能或在部署前验证技能是否有效时使用

## 如何使用

当任务匹配某个 skill 时，使用 `Skill` 工具加载对应 skill 并严格遵循其流程。绝不要用 Read 工具读取 SKILL.md 文件。

如果你认为哪怕只有 1% 的可能性某个 skill 适用于你正在做的事情，你必须调用该 skill 检查。
