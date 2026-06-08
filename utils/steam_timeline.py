"""
Steam 时间轴事件记录器

为 web 面板的两个时间轴（历史极值变化、好友游玩记录）提供持久化与查询。
数据存放在与 steam_data.json 同目录的 steam_timeline.json 文件中，
采用与 cs-Solidarity 其他 JSON 配置相同的读写锁模式避免并发损坏。
"""
import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# 各类型事件的最大保留条数（环形覆盖：超出后从最旧的开始丢）
MAX_EXTREME_CHANGES = 200
MAX_PLAY_RECORDS = 300

# 读写锁：与 instances/steam_auto.py 中的 _config_lock 同模式
_timeline_lock = threading.Lock()

_TIMELINE_FILENAME = "steam_timeline.json"


def _empty_state() -> Dict[str, list]:
    return {"extreme_changes": [], "play_records": []}


def _load_state(data_path: str) -> Dict[str, list]:
    timeline_file = Path(data_path).parent / _TIMELINE_FILENAME
    if not timeline_file.exists():
        return _empty_state()
    try:
        with open(timeline_file, "r", encoding="utf-8") as f:
            state = json.load(f)
        # 兜底缺字段
        state.setdefault("extreme_changes", [])
        state.setdefault("play_records", [])
        return state
    except (json.JSONDecodeError, OSError):
        return _empty_state()


def _save_state(data_path: str, state: Dict[str, list]) -> None:
    timeline_file = Path(data_path).parent / _TIMELINE_FILENAME
    timeline_file.parent.mkdir(parents=True, exist_ok=True)
    with open(timeline_file, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _now_pair() -> Dict[str, str]:
    now = datetime.now()
    return {"timestamp": now.strftime("%Y-%m-%d %H:%M:%S"), "timestamp_iso": now.isoformat()}


def _resolve_timestamp(timestamp: Optional[str] = None) -> tuple[str, str]:
    """支持传入 "%Y-%m-%d %H:%M:%S" 或 ISO；不传则取当前时间。返回 (display, iso)。"""
    if timestamp:
        if "T" in timestamp:
            return timestamp, timestamp
        return timestamp, timestamp.replace(" ", "T")
    now = datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S"), now.isoformat()


def _find_or_create_group(
    state: Dict[str, list],
    kind: str,
    game_name: str,
    ts_iso: str,
    window_seconds: int = 60,
) -> str:
    """从已有事件里反推 group_id：60s 内同 kind + 同 game_name 复用同一 group。"""
    try:
        new_dt = datetime.fromisoformat(ts_iso)
    except ValueError:
        return uuid.uuid4().hex
    for ev in reversed(state.get("play_records", [])):
        if ev.get("kind") != kind:
            continue
        if ev.get("game_name") != game_name:
            continue
        gid = ev.get("group_id")
        ev_ts = ev.get("timestamp_iso")
        if not gid or not ev_ts:
            continue
        try:
            ev_dt = datetime.fromisoformat(ev_ts)
        except ValueError:
            continue
        if abs((new_dt - ev_dt).total_seconds()) <= window_seconds:
            return gid
    return uuid.uuid4().hex


def _push_with_cap(state: Dict[str, list], key: str, event: Dict[str, Any], cap: int) -> None:
    """插入事件，超出 cap 时丢弃最旧的。"""
    state[key].append(event)
    if len(state[key]) > cap:
        del state[key][: len(state[key]) - cap]


class SteamTimelineRecorder:
    """Steam 时间轴事件记录器

    复用 SteamAuto 的 data_path 定位存档目录；事件以追加 + 上限裁剪方式持久化。
    """

    def __init__(self, data_path: str):
        self.data_path = data_path

    def record_extreme_change(
        self,
        steamid: str,
        pw_nickname: str,
        metric: str,
        metric_label: str,
        metric_emoji: str,
        old_value,
        new_value,
        is_improvement: bool,
        previous_holder: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """记录一次排行榜极值变化（如击杀王由 A 的 20 变为 B 的 30）。

        返回写入的事件 dict；若值和持有者都未变化则返回 None。
        """
        if old_value == new_value and not previous_holder:
            return None

        event = {
            "id": uuid.uuid4().hex,
            "steamid": steamid,
            "pw_nickname": pw_nickname,
            "metric": metric,
            "metric_label": metric_label,
            "metric_emoji": metric_emoji,
            "old_value": old_value,
            "new_value": new_value,
            "delta": (new_value - old_value) if isinstance(new_value, (int, float)) and isinstance(old_value, (int, float)) else 0,
            "is_improvement": is_improvement,
            **_now_pair(),
        }

        with _timeline_lock:
            state = _load_state(self.data_path)
            event["previous_holder"] = previous_holder
            _push_with_cap(state, "extreme_changes", event, MAX_EXTREME_CHANGES)
            _save_state(self.data_path, state)
        return event

    def record_game_start(
        self,
        steamid: str,
        pw_nickname: str,
        game_name: str,
        timestamp: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """记录一个好友开始玩某游戏。60s 内同游戏名复用 group_id。"""
        if not steamid or not game_name:
            return None
        ts, ts_iso = _resolve_timestamp(timestamp)
        with _timeline_lock:
            state = _load_state(self.data_path)
            group_id = _find_or_create_group(state, "start", game_name, ts_iso)
            event = {
                "id": uuid.uuid4().hex,
                "kind": "start",
                "steamid": steamid,
                "pw_nickname": pw_nickname,
                "game_name": game_name,
                "group_id": group_id,
                "timestamp": ts,
                "timestamp_iso": ts_iso,
            }
            _push_with_cap(state, "play_records", event, MAX_PLAY_RECORDS)
            _save_state(self.data_path, state)
        return event

    def record_game_end(
        self,
        steamid: str,
        pw_nickname: str,
        game_name: str,
        timestamp: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """记录一个好友结束玩某游戏。60s 内同游戏名复用 group_id。"""
        if not steamid or not game_name:
            return None
        ts, ts_iso = _resolve_timestamp(timestamp)
        with _timeline_lock:
            state = _load_state(self.data_path)
            group_id = _find_or_create_group(state, "end", game_name, ts_iso)
            event = {
                "id": uuid.uuid4().hex,
                "kind": "end",
                "steamid": steamid,
                "pw_nickname": pw_nickname,
                "game_name": game_name,
                "group_id": group_id,
                "timestamp": ts,
                "timestamp_iso": ts_iso,
            }
            _push_with_cap(state, "play_records", event, MAX_PLAY_RECORDS)
            _save_state(self.data_path, state)
        return event

    def record_game_match(
        self,
        match_id: str,
        map_name: str,
        score: str,
        players: List[Dict[str, Any]],
        timestamp: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """记录一场多人对局。match_id 已存在则跳过（去重）。players 是 dict 列表。"""
        if not match_id or not players:
            return None
        with _timeline_lock:
            state = _load_state(self.data_path)
            if any(r.get("match_id") == match_id and r.get("kind") == "match" for r in state["play_records"]):
                return None
            ts, ts_iso = _resolve_timestamp(timestamp)
            event = {
                "id": uuid.uuid4().hex,
                "kind": "match",
                "match_id": match_id,
                "map_name": map_name,
                "score": score,
                "players": players,
                "timestamp": ts,
                "timestamp_iso": ts_iso,
            }
            _push_with_cap(state, "play_records", event, MAX_PLAY_RECORDS)
            _save_state(self.data_path, state)
        return event

    def get_extreme_changes(self, limit: int = 50) -> List[Dict[str, Any]]:
        with _timeline_lock:
            state = _load_state(self.data_path)
        events = state.get("extreme_changes", [])
        if limit > 0:
            return events[-limit:]
        return events

    def get_play_records(self, limit: int = 50) -> List[Dict[str, Any]]:
        with _timeline_lock:
            state = _load_state(self.data_path)
        events = state.get("play_records", [])
        if limit > 0:
            return events[-limit:]
        return events
