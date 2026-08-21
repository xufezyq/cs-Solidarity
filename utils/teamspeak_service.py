"""TeamSpeak music bot service helpers.

This module centralizes TeamSpeak ServerQuery access so the background instance,
Steam hook, Agent API, and tests all use the same movement and status logic.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable


DEFAULT_HOST = ""
DEFAULT_QUERY_PORT = 10011
DEFAULT_SERVER_PORT = 9987
DEFAULT_BOT_NICKNAME = ""
DEFAULT_BOT_UID = ""
DEFAULT_HOME_CHANNEL_ID = 0
DEFAULT_CHANNEL_PASSWORD = ""
DEFAULT_EMPTY_RETURN_DELAY_SECONDS = 60
DEFAULT_CHECK_INTERVAL_SECONDS = 15
DEFAULT_TIMEOUT = 10.0


class TeamSpeakConfigError(ValueError):
    """Raised when TeamSpeak settings are incomplete or invalid."""


class TeamSpeakQueryError(RuntimeError):
    """Raised when TeamSpeak ServerQuery returns an error."""


_ESCAPE_MAP = {
    "\\": "\\\\",
    "/": "\\/",
    " ": "\\s",
    "|": "\\p",
    "\a": "\\a",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
    "\v": "\\v",
}

_UNESCAPE_MAP = {
    "\\": "\\",
    "/": "/",
    "s": " ",
    "p": "|",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
}


@dataclass(slots=True)
class QueryResponse:
    lines: list[str]
    items: list[dict[str, str]]
    error: dict[str, str]


def _escape_query_value(value: Any) -> str:
    return "".join(_ESCAPE_MAP.get(char, char) for char in str(value))


def _unescape_query_value(value: str) -> str:
    result: list[str] = []
    i = 0
    while i < len(value):
        char = value[i]
        if char == "\\" and i + 1 < len(value):
            i += 1
            result.append(_UNESCAPE_MAP.get(value[i], value[i]))
        else:
            result.append(char)
        i += 1
    return "".join(result)


def _parse_query_kv(blob: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for token in blob.strip().split():
        if not token:
            continue
        if "=" not in token:
            data[token] = ""
            continue
        key, value = token.split("=", 1)
        data[key] = _unescape_query_value(value)
    return data


def _parse_query_items(line: str) -> list[dict[str, str]]:
    if not line.strip():
        return []
    return [_parse_query_kv(item) for item in line.split("|") if item.strip()]


def _build_query_command(command: str, **params: Any) -> str:
    parts = [command]
    for key, value in params.items():
        if value is not None:
            parts.append(f"{key}={_escape_query_value(value)}")
    return " ".join(parts)


def _parse_query_response_items(lines: Iterable[str]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for line in lines:
        items.extend(_parse_query_items(line))
    return items


class TeamSpeak3ServerQuery:
    """Minimal synchronous TeamSpeak 3 ServerQuery client."""

    def __init__(self, host: str, port: int = 10011, timeout: float = 10.0):
        self.host = host
        self.port = int(port)
        self.timeout = timeout
        self._sock: socket.socket | None = None

    def __enter__(self) -> "TeamSpeak3ServerQuery":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def connect(self) -> None:
        if self._sock is not None:
            return
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._sock.settimeout(0.25)
        try:
            while True:
                self._recv_line()
        except socket.timeout:
            pass
        finally:
            self._sock.settimeout(self.timeout)

    def close(self) -> None:
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def login(self, username: str, password: str) -> QueryResponse:
        return self.command(
            _build_query_command(
                "login",
                client_login_name=username,
                client_login_password=password,
            )
        )

    def use_server(self, *, server_id: int | None = None, server_port: int | None = None) -> QueryResponse:
        if server_id is None and server_port is None:
            raise ValueError("server_id or server_port is required")
        if server_id is not None:
            return self.command(_build_query_command("use", sid=server_id))
        return self.command(_build_query_command("use", port=server_port))

    def list_clients(self) -> list[dict[str, str]]:
        return self.command("clientlist -uid").items

    def list_channels(self) -> list[dict[str, str]]:
        return self.command("channellist").items

    def move_client(
        self,
        *,
        client_id: int | str,
        channel_id: int | str,
        channel_password: str | None = None,
    ) -> QueryResponse:
        return self.command(
            _build_query_command(
                "clientmove",
                clid=client_id,
                cid=channel_id,
                cpw=channel_password or None,
            )
        )

    def command(self, command_line: str) -> QueryResponse:
        self.connect()
        assert self._sock is not None
        self._sock.sendall((command_line + "\n").encode("utf-8"))

        lines: list[str] = []
        while True:
            line = self._recv_line()
            if line.startswith("error "):
                error = _parse_query_kv(line[len("error ") :])
                if error.get("id") != "0":
                    msg = error.get("msg", "unknown TeamSpeak ServerQuery error")
                    raise TeamSpeakQueryError(f"ServerQuery error {error.get('id')}: {msg}")
                return QueryResponse(lines=lines, items=_parse_query_response_items(lines), error=error)
            if line:
                lines.append(line)

    def _recv_line(self) -> str:
        assert self._sock is not None
        chunks: list[bytes] = []
        while True:
            chunk = self._sock.recv(1)
            if not chunk:
                raise TeamSpeakQueryError("ServerQuery connection closed")
            if chunk == b"\n":
                break
            if chunk != b"\r":
                chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", errors="replace")


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _as_int(value: Any, default: int | None = None) -> int | None:
    if value in (None, ""):
        return default
    return int(value)


def _as_float(value: Any, default: float) -> float:
    if value in (None, ""):
        return default
    return float(value)


def _public_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _decode_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _load_root_env(root: Path) -> None:
    """Load simple KEY=VALUE pairs from the project .env if present.

    Existing process environment variables take precedence over .env values.
    This keeps TeamSpeak secrets out of tracked JSON while preserving normal
    deployment overrides.
    """
    env_path = root / ".env"
    if not env_path.exists():
        return
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = _decode_env_value(value)


@dataclass(slots=True)
class TeamSpeakConfig:
    host: str = DEFAULT_HOST
    query_port: int = DEFAULT_QUERY_PORT
    server_port: int | None = DEFAULT_SERVER_PORT
    server_id: int | None = None
    username: str | None = None
    password: str | None = None
    bot_nickname: str = DEFAULT_BOT_NICKNAME
    bot_uid: str = DEFAULT_BOT_UID
    home_channel_id: int = DEFAULT_HOME_CHANNEL_ID
    channel_password: str = DEFAULT_CHANNEL_PASSWORD
    empty_return_delay_seconds: int = DEFAULT_EMPTY_RETURN_DELAY_SECONDS
    check_interval_seconds: int = DEFAULT_CHECK_INTERVAL_SECONDS
    timeout: float = DEFAULT_TIMEOUT
    config_path: str | None = None
    state_path: str | None = None

    @property
    def has_credentials(self) -> bool:
        return bool(self.username and self.password)


def load_teamspeak_config(
    config_path: str | Path | None = None,
    *,
    root_dir: str | Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> TeamSpeakConfig:
    """Load TeamSpeak settings from local JSON plus environment variables.

    Environment variables intentionally override file values, which keeps the
    ServerQuery password out of repository files and web responses.
    """

    root = Path(root_dir or Path.cwd()).resolve()
    _load_root_env(root)
    path = Path(config_path) if config_path else root / "instconfig" / "teamspeak3.local.json"
    if not path.is_absolute():
        path = root / path

    data: dict[str, Any] = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as fp:
            loaded = json.load(fp)
        if not isinstance(loaded, dict):
            raise TeamSpeakConfigError(f"TeamSpeak 配置必须是 JSON 对象: {path}")
        data.update(loaded)
    if overrides:
        data.update(overrides)

    env = os.environ
    state_path_value = data.get("state_path")
    if state_path_value:
        state_path = Path(state_path_value)
        if not state_path.is_absolute():
            state_path = root / state_path
    else:
        state_path = root / "instconfig" / "teamspeak3_state.json"
    return TeamSpeakConfig(
        host=str(_coalesce(env.get("TS3_HOST"), data.get("host"), DEFAULT_HOST)),
        query_port=_as_int(_coalesce(env.get("TS3_QUERY_PORT"), data.get("query_port")), DEFAULT_QUERY_PORT) or DEFAULT_QUERY_PORT,
        server_port=_as_int(_coalesce(env.get("TS3_SERVER_PORT"), data.get("server_port")), DEFAULT_SERVER_PORT),
        server_id=_as_int(_coalesce(env.get("TS3_SERVER_ID"), data.get("server_id")), None),
        username=_coalesce(env.get("TS3_QUERY_USER"), env.get("TS3_QUERY_USERNAME"), data.get("username")),
        password=_coalesce(env.get("TS3_QUERY_PASSWORD"), data.get("password")),
        bot_nickname=str(_coalesce(env.get("TS3_BOT_NICKNAME"), data.get("bot_nickname"), DEFAULT_BOT_NICKNAME)),
        bot_uid=str(_coalesce(env.get("TS3_BOT_UID"), data.get("bot_uid"), DEFAULT_BOT_UID)),
        home_channel_id=_as_int(
            _coalesce(env.get("TS3_HOME_CHANNEL_ID"), data.get("home_channel_id"), data.get("target_cid")),
            DEFAULT_HOME_CHANNEL_ID,
        ) or DEFAULT_HOME_CHANNEL_ID,
        channel_password=str(_coalesce(env.get("TS3_CHANNEL_PASSWORD"), data.get("channel_password"), DEFAULT_CHANNEL_PASSWORD)),
        empty_return_delay_seconds=max(
            1,
            _as_int(
                _coalesce(env.get("TS3_EMPTY_RETURN_DELAY_SECONDS"), data.get("empty_return_delay_seconds")),
                DEFAULT_EMPTY_RETURN_DELAY_SECONDS,
            ) or DEFAULT_EMPTY_RETURN_DELAY_SECONDS,
        ),
        check_interval_seconds=max(
            1,
            _as_int(
                _coalesce(env.get("TS3_CHECK_INTERVAL_SECONDS"), data.get("check_interval_seconds")),
                DEFAULT_CHECK_INTERVAL_SECONDS,
            ) or DEFAULT_CHECK_INTERVAL_SECONDS,
        ),
        timeout=_as_float(_coalesce(env.get("TS3_TIMEOUT"), data.get("timeout")), DEFAULT_TIMEOUT),
        config_path=str(path),
        state_path=str(state_path),
    )


class TeamSpeakRuntimeState:
    """Small JSON-backed state shared between Bot and Agent processes."""

    def __init__(self, path: str | Path | None):
        self.path = Path(path).resolve() if path else None
        self._lock = threading.Lock()
        self.empty_since: float | None = None
        self.last_auto_move: dict[str, Any] | None = None
        self._load()

    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(data, dict):
            self.empty_since = data.get("empty_since")
            self.last_auto_move = data.get("last_auto_move")

    def _save_locked(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "empty_since": self.empty_since,
            "last_auto_move": self.last_auto_move,
        }
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "empty_since": self.empty_since,
                "last_auto_move": self.last_auto_move,
            }

    def set_empty_since(self, value: float | None) -> None:
        with self._lock:
            if self.empty_since == value:
                return
            self.empty_since = value
            self._save_locked()

    def record_move(
        self,
        *,
        reason: str,
        target_cid: int,
        target_channel_name: str | None,
        previous_cid: int | None,
        moved: bool,
        automated: bool,
    ) -> None:
        with self._lock:
            self.last_auto_move = {
                "reason": reason,
                "time": datetime.now().isoformat(),
                "target_cid": target_cid,
                "target_channel_name": target_channel_name,
                "previous_cid": previous_cid,
                "moved": moved,
                "automated": automated,
            }
            self.empty_since = None
            self._save_locked()


def _is_query_client(client: dict[str, Any]) -> bool:
    return str(client.get("client_type", "0")) == "1"


def _is_music_bot(client: dict[str, Any], config: TeamSpeakConfig) -> bool:
    uid = str(client.get("client_unique_identifier") or "")
    nickname = str(client.get("client_nickname") or "")
    return bool((config.bot_uid and uid == config.bot_uid) or (not config.bot_uid and nickname == config.bot_nickname))


def _client_view(client: dict[str, Any], channel_name: str, config: TeamSpeakConfig) -> dict[str, Any]:
    is_query = _is_query_client(client)
    is_bot = _is_music_bot(client, config)
    return {
        "clid": _public_int(client.get("clid")),
        "cid": _public_int(client.get("cid")),
        "channel_name": channel_name,
        "client_type": _public_int(client.get("client_type")) or 0,
        "nickname": client.get("client_nickname") or "",
        "uid": client.get("client_unique_identifier") or "",
        "is_query": is_query,
        "is_music_bot": is_bot,
        "is_human": not is_query and not is_bot,
    }


def aggregate_teamspeak_status(
    channels: Iterable[dict[str, Any]],
    clients: Iterable[dict[str, Any]],
    config: TeamSpeakConfig,
    *,
    state: dict[str, Any] | None = None,
    connected: bool = True,
    error: str | None = None,
) -> dict[str, Any]:
    """Combine ServerQuery channels and clients into frontend-friendly state."""

    channel_rows = list(channels or [])
    client_rows = list(clients or [])
    channel_by_cid = {str(ch.get("cid")): ch for ch in channel_rows}

    clients_by_cid: dict[str, list[dict[str, Any]]] = {str(ch.get("cid")): [] for ch in channel_rows}
    public_clients: list[dict[str, Any]] = []
    music_bot: dict[str, Any] | None = None
    online_human_count = 0

    for client in client_rows:
        cid_key = str(client.get("cid"))
        channel_name = str(channel_by_cid.get(cid_key, {}).get("channel_name") or "")
        view = _client_view(client, channel_name, config)
        if not view["is_query"]:
            public_clients.append(view)
            clients_by_cid.setdefault(cid_key, []).append(view)
        if view["is_music_bot"]:
            music_bot = view
        if view["is_human"]:
            online_human_count += 1

    channel_views = []
    for channel in channel_rows:
        cid_key = str(channel.get("cid"))
        channel_clients = clients_by_cid.get(cid_key, [])
        human_count = sum(1 for client in channel_clients if client.get("is_human"))
        channel_views.append({
            "cid": _public_int(channel.get("cid")),
            "pid": _public_int(channel.get("pid")),
            "channel_name": channel.get("channel_name") or "",
            "total_clients": _public_int(channel.get("total_clients")) or len(channel_clients),
            "human_count": human_count,
            "bot_here": any(client.get("is_music_bot") for client in channel_clients),
            "clients": channel_clients,
        })

    tree_nodes = [{**channel, "children": []} for channel in channel_views]
    tree_by_cid = {node.get("cid"): node for node in tree_nodes}
    channel_tree = []
    for node in tree_nodes:
        parent = tree_by_cid.get(node.get("pid"))
        if parent and parent is not node:
            parent["children"].append(node)
        else:
            channel_tree.append(node)

    home_channel = channel_by_cid.get(str(config.home_channel_id)) or {}
    bot_online = bool(music_bot)
    bot_cid = music_bot.get("cid") if music_bot else None
    bot_is_home = bot_online and bot_cid == config.home_channel_id
    music_bot_state = {
        "online": bot_online,
        "clid": music_bot.get("clid") if music_bot else None,
        "cid": bot_cid,
        "channel_name": music_bot.get("channel_name") if music_bot else None,
        "nickname": music_bot.get("nickname") if music_bot else config.bot_nickname,
        "uid": music_bot.get("uid") if music_bot else config.bot_uid,
        "is_home": bool(bot_is_home),
    }

    runtime = state or {}
    return {
        "connected": connected,
        "error": error,
        "host": config.host,
        "server_port": config.server_port,
        "home_channel_id": config.home_channel_id,
        "home_channel_name": home_channel.get("channel_name") or None,
        "online_human_count": online_human_count,
        "channels": channel_views,
        "channel_tree": channel_tree,
        "clients": public_clients,
        "music_bot": music_bot_state,
        "empty_since": runtime.get("empty_since"),
        "last_auto_move": runtime.get("last_auto_move"),
        "empty_return_delay_seconds": config.empty_return_delay_seconds,
        "check_interval_seconds": config.check_interval_seconds,
    }


class TeamSpeakMusicBotService:
    """High-level music bot status and movement service."""

    def __init__(
        self,
        config: TeamSpeakConfig,
        *,
        state: TeamSpeakRuntimeState | None = None,
        query_factory: Callable[..., TeamSpeak3ServerQuery] = TeamSpeak3ServerQuery,
    ):
        self.config = config
        self.state = state or TeamSpeakRuntimeState(config.state_path)
        self.query_factory = query_factory

    def _ensure_ready(self) -> None:
        if not self.config.host:
            raise TeamSpeakConfigError("缺少 TeamSpeak host，请在 teamspeak3.local.json 或 TS3_HOST 中配置")
        if not self.config.has_credentials:
            raise TeamSpeakConfigError("缺少 TeamSpeak ServerQuery 用户名或密码，请配置 username 和 TS3_QUERY_PASSWORD")
        if self.config.server_id is None and self.config.server_port is None:
            raise TeamSpeakConfigError("缺少 TeamSpeak server_id 或 server_port")
        if not (self.config.bot_uid or self.config.bot_nickname):
            raise TeamSpeakConfigError("缺少 TeamSpeak 音乐机器人 UID 或昵称，请配置 bot_uid 或 bot_nickname")
        if not self.config.home_channel_id:
            raise TeamSpeakConfigError("缺少 TeamSpeak 音乐机器人频道 ID，请配置 home_channel_id")

    def _login_and_select(self, query: TeamSpeak3ServerQuery) -> None:
        self._ensure_ready()
        query.login(self.config.username or "", self.config.password or "")
        query.use_server(server_id=self.config.server_id, server_port=self.config.server_port)

    def _fetch_raw(self) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        with self.query_factory(self.config.host, self.config.query_port, timeout=self.config.timeout) as query:
            self._login_and_select(query)
            channels = query.list_channels()
            clients = query.list_clients()
        return channels, clients

    def status(self) -> dict[str, Any]:
        try:
            channels, clients = self._fetch_raw()
            return aggregate_teamspeak_status(channels, clients, self.config, state=self.state.snapshot())
        except (OSError, TeamSpeakConfigError, TeamSpeakQueryError, ValueError) as exc:
            return aggregate_teamspeak_status(
                [],
                [],
                self.config,
                state=self.state.snapshot(),
                connected=False,
                error=str(exc),
            )

    def _find_music_bot(self, clients: Iterable[dict[str, Any]]) -> dict[str, Any]:
        matches = [client for client in clients if not _is_query_client(client) and _is_music_bot(client, self.config)]
        if not matches:
            raise TeamSpeakQueryError("未找到在线的 KTV点歌姬")
        if len(matches) > 1:
            raise TeamSpeakQueryError("找到多个匹配的 KTV点歌姬，请使用唯一 UID")
        return matches[0]

    def _find_channel(self, channels: Iterable[dict[str, Any]], cid: int) -> dict[str, Any]:
        for channel in channels:
            if _public_int(channel.get("cid")) == cid:
                return channel
        raise TeamSpeakQueryError(f"未找到 TeamSpeak 频道 cid={cid}")

    def move_music_bot(self, target_cid: int, *, reason: str = "manual", automated: bool = False) -> dict[str, Any]:
        target = int(target_cid)
        with self.query_factory(self.config.host, self.config.query_port, timeout=self.config.timeout) as query:
            self._login_and_select(query)
            channels = query.list_channels()
            clients = query.list_clients()
            channel = self._find_channel(channels, target)
            bot = self._find_music_bot(clients)
            previous_cid = _public_int(bot.get("cid"))
            target_name = channel.get("channel_name") or None

            if previous_cid == target:
                return {
                    "moved": False,
                    "noop": True,
                    "reason": reason,
                    "target_cid": target,
                    "target_channel_name": target_name,
                    "previous_cid": previous_cid,
                    "message": "KTV点歌姬已在目标频道",
                }

            query.move_client(
                client_id=bot["clid"],
                channel_id=target,
                channel_password=self.config.channel_password,
            )

        self.state.record_move(
            reason=reason,
            target_cid=target,
            target_channel_name=target_name,
            previous_cid=previous_cid,
            moved=True,
            automated=automated,
        )
        return {
            "moved": True,
            "noop": False,
            "reason": reason,
            "target_cid": target,
            "target_channel_name": target_name,
            "previous_cid": previous_cid,
            "message": f"已移动 KTV点歌姬到 {target_name or target}",
        }

    def move_home(self, *, reason: str = "manual_home", automated: bool = False) -> dict[str, Any]:
        return self.move_music_bot(self.config.home_channel_id, reason=reason, automated=automated)

    def check_empty_return(self, *, now: float | None = None) -> dict[str, Any]:
        now_ts = time.time() if now is None else float(now)
        channels, clients = self._fetch_raw()
        status = aggregate_teamspeak_status(channels, clients, self.config, state=self.state.snapshot())
        bot = status["music_bot"]
        if not bot.get("online"):
            self.state.set_empty_since(None)
            return {"moved": False, "reason": "bot_offline", "status": status}
        if bot.get("is_home"):
            self.state.set_empty_since(None)
            return {"moved": False, "reason": "bot_home", "status": status}

        current_cid = bot.get("cid")
        current_channel = next((channel for channel in status["channels"] if channel.get("cid") == current_cid), None)
        human_count = int((current_channel or {}).get("human_count") or 0)
        if human_count > 0:
            self.state.set_empty_since(None)
            return {"moved": False, "reason": "channel_has_humans", "status": status}

        empty_since = self.state.snapshot().get("empty_since")
        if not empty_since:
            empty_since = now_ts
            self.state.set_empty_since(empty_since)

        elapsed = now_ts - float(empty_since)
        if elapsed >= self.config.empty_return_delay_seconds:
            move_result = self.move_home(reason="empty_channel", automated=True)
            return {"moved": bool(move_result.get("moved")), "reason": "empty_channel", "move": move_result}

        return {
            "moved": False,
            "reason": "empty_channel_waiting",
            "empty_since": empty_since,
            "remaining_seconds": max(0, self.config.empty_return_delay_seconds - elapsed),
            "status": status,
        }


def get_default_teamspeak_service(
    *,
    root_dir: str | Path | None = None,
    config_path: str | Path | None = None,
) -> TeamSpeakMusicBotService:
    config = load_teamspeak_config(config_path, root_dir=root_dir)
    return TeamSpeakMusicBotService(config)
