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
MAX_PLAY_RECORDS = 200

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
    ) -> Optional[Dict[str, Any]]:
        """记录一次历史极值变化（如击杀王由 20 升到 30）。

        返回写入的事件 dict；若 new_value 与 old_value 相等则返回 None。
        """
        if old_value == new_value:
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
            _push_with_cap(state, "extreme_changes", event, MAX_EXTREME_CHANGES)
            _save_state(self.data_path, state)
        return event

    def record_play_record(
        self,
        match_id: str,
        steamid: str,
        pw_nickname: str,
        map_name: str,
        score: str,
        result: str,
        kda: str,
        rating: float = 0.0,
        we: int = 0,
        pvp_score_change: int = 0,
        pvp_stars_change: int = 0,
    ) -> Optional[Dict[str, Any]]:
        """记录一次好友完美对局。match_id 已播报过则跳过（去重）。"""
        if not match_id:
            return None

        with _timeline_lock:
            state = _load_state(self.data_path)
            if any(r.get("match_id") == match_id and r.get("steamid") == steamid for r in state["play_records"]):
                return None

            event = {
                "id": uuid.uuid4().hex,
                "match_id": match_id,
                "steamid": steamid,
                "pw_nickname": pw_nickname,
                "map_name": map_name,
                "score": score,
                "result": result,
                "kda": kda,
                "rating": rating,
                "we": we,
                "pvp_score_change": pvp_score_change,
                "pvp_stars_change": pvp_stars_change,
                **_now_pair(),
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
