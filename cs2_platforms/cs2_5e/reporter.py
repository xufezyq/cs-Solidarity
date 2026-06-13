from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _fmt_num(value: float) -> str:
    if abs(value - int(value)) < 0.005:
        return str(int(value))
    return f"{value:.2f}"


class FiveEStatsReporter:
    """5E stats reporter for SteamAuto."""

    _HISTORY_REQUIRED_FIELDS = {
        "fivee_nickname": "未知好友",
        "avatar": "",
        "last_match_id": "",
        "max_kills": 0,
        "min_kills": 999,
        "max_deaths": 0,
        "min_deaths": 999,
        "max_rating": 0.0,
        "min_rating": 999.0,
        "max_rws": 0.0,
        "min_rws": 999.0,
        "max_adr": 0.0,
        "min_adr": 999.0,
        "max_elo": 0.0,
        "min_elo": 9999.0,
    }

    MAX_MATCH_AGE_SECONDS = 3600

    def __init__(
        self,
        fivee_api,
        monitored_friends: List[Dict[str, Any]],
        friend_5e_history_stats: Dict[str, Any],
        friend_5e_daily_stats: Dict[str, Any],
        log,
    ):
        self.fivee_api = fivee_api
        self.monitored_friends = monitored_friends
        self.friend_5e_history_stats = friend_5e_history_stats
        self.friend_5e_daily_stats = friend_5e_daily_stats
        self.log = log
        self.resolved_friend_updates: Dict[str, Dict[str, str]] = {}

    async def fetch_and_report(self, steam_ids: list) -> Tuple[List[str], list]:
        match_groups = await self._fetch_match_lists(steam_ids)
        if not match_groups:
            return [], []

        self.log(f"[{datetime.now()}] 共发现 {len(match_groups)} 场有效 5E 比赛，正在生成战报...")
        all_players = await self._collect_player_data(match_groups)
        self._update_daily_stats(all_players)
        self._update_history_stats(all_players)
        messages = self._generate_messages(all_players)
        return messages, all_players

    async def _resolve_friend(self, steam_id: str) -> Optional[Dict[str, str]]:
        cached = None
        for friend in self.monitored_friends:
            if isinstance(friend, dict) and str(friend.get("steamid", "")) == str(steam_id):
                cached = friend
                break

        if cached and cached.get("fivee_uuid"):
            return {
                "uuid": str(cached.get("fivee_uuid")),
                "domain": str(cached.get("fivee_domain", "")),
                "username": str(cached.get("fivee_nickname") or cached.get("personaname") or steam_id),
                "avatar": str(cached.get("fivee_avatar", "")),
            }

        resolved = await self.fivee_api.resolve_user_by_steam_id(str(steam_id))
        if resolved:
            self.resolved_friend_updates[str(steam_id)] = resolved
        return resolved

    async def _fetch_match_lists(self, steam_ids: list) -> Dict[str, list]:
        match_groups: Dict[str, list] = {}
        self.log(f"[{datetime.now()}] 开始查询 {len(steam_ids)} 位好友的 5E 战绩: {steam_ids}")

        for steam_id in steam_ids:
            try:
                resolved = await self._resolve_friend(str(steam_id))
                if not resolved:
                    continue
                matches = await self.fivee_api.get_match_list(resolved["uuid"], limit=5)
                if isinstance(matches, int) or not matches:
                    continue
                last_match = matches[0]
                match_id = last_match.get("match_id")
                if not match_id:
                    continue

                end_ts = _to_int(last_match.get("end_time"))
                if end_ts and self.MAX_MATCH_AGE_SECONDS:
                    age_seconds = (datetime.now() - datetime.fromtimestamp(end_ts)).total_seconds()
                    if age_seconds > self.MAX_MATCH_AGE_SECONDS:
                        self.log(
                            f"[{datetime.now()}] {steam_id} 最近 5E 比赛 {match_id} "
                            f"已结束 {int(age_seconds // 60)} 分钟，跳过"
                        )
                        continue

                prev_match = matches[1] if len(matches) > 1 else None
                last_match["_steam_id"] = str(steam_id)
                last_match["_fivee_uuid"] = resolved["uuid"]
                last_match["_fivee_nickname"] = resolved["username"]
                last_match["_fivee_avatar"] = resolved.get("avatar", "")
                last_match["_prev_elo"] = _to_float(prev_match.get("origin_elo")) if prev_match else 0.0

                match_groups.setdefault(str(match_id), []).append((str(steam_id), last_match))
                self.log(f"[{datetime.now()}] {steam_id} 发现最近 5E 比赛: {match_id}")
            except Exception as e:
                self.log(f"[{datetime.now()}] 查询 5E 战绩出错 ({steam_id}): {e}")

        return match_groups

    @staticmethod
    def _player_from_detail(player: Dict[str, Any]) -> Dict[str, Any]:
        fight = player.get("fight") or {}
        user_data = (player.get("user_info") or {}).get("user_data") or {}
        profile = user_data.get("profile") or {}
        steam = user_data.get("steam") or {}
        level_info = player.get("level_info") or {}
        return {
            "steam_id": str(steam.get("steamId", "")),
            "uuid": str(user_data.get("uuid", "")),
            "nickname": str(user_data.get("username", "")),
            "avatar": profile.get("avatarUrl", ""),
            "team": str(fight.get("group_id", "")),
            "kill": _to_int(fight.get("kill")),
            "death": _to_int(fight.get("death")),
            "assist": _to_int(fight.get("assist")),
            "rating": _to_float(fight.get("rating")),
            "rws": _to_float(fight.get("rws")),
            "adr": _to_float(fight.get("adr")),
            "first_kill": _to_int(fight.get("first_kill")),
            "awp_kill": _to_int(fight.get("awp_kill")),
            "kill_3": _to_int(fight.get("kill_3")),
            "kill_4": _to_int(fight.get("kill_4")),
            "kill_5": _to_int(fight.get("kill_5")),
            "is_mvp": fight.get("is_mvp") in ("1", 1, True),
            "is_svp": fight.get("is_svp") in ("1", 1, True),
            "is_win": fight.get("is_win") in ("1", 1, True),
            "origin_elo": _to_float(level_info.get("origin_elo")),
            "change_elo": _to_float(level_info.get("change_elo")),
            "level_id": _to_int(level_info.get("level_id")),
        }

    async def _collect_player_data(self, match_groups: Dict[str, list]) -> list:
        all_players = []
        known_steam_ids = {str(f.get("steamid", "")) for f in self.monitored_friends if isinstance(f, dict)}
        uuid_to_steam = {
            str(f.get("fivee_uuid", "")): str(f.get("steamid", ""))
            for f in self.monitored_friends
            if isinstance(f, dict) and f.get("fivee_uuid") and f.get("steamid")
        }

        for match_id, group in match_groups.items():
            detail = await self.fivee_api.get_match_detail(match_id)
            if not detail:
                continue
            main = detail.get("main") or {}
            map_name = main.get("map_desc") or group[0][1].get("map_desc") or group[0][1].get("map_name") or "未知地图"
            score1 = main.get("group1_all_score", group[0][1].get("group1_all_score"))
            score2 = main.get("group2_all_score", group[0][1].get("group2_all_score"))
            winner = str(main.get("match_winner", ""))

            detail_players = [
                self._player_from_detail(p)
                for p in [*(detail.get("group_1") or []), *(detail.get("group_2") or [])]
            ]
            grouped_steam_ids = {sid for sid, _ in group}

            for detail_player in detail_players:
                sid = detail_player["steam_id"] or uuid_to_steam.get(detail_player["uuid"], "")
                if not sid or sid not in known_steam_ids or sid in grouped_steam_ids:
                    continue
                synthetic = {
                    "match_id": match_id,
                    "group1_all_score": score1,
                    "group2_all_score": score2,
                    "map_desc": map_name,
                    "_steam_id": sid,
                    "_fivee_uuid": detail_player["uuid"],
                    "_fivee_nickname": detail_player["nickname"],
                    "_fivee_avatar": self.fivee_api.asset_url(detail_player["avatar"]),
                }
                group.append((sid, synthetic))
                grouped_steam_ids.add(sid)
                self.log(f"[{datetime.now()}] 5E 对局 {match_id} 中发现好友 {sid}，一并加入播报")

            by_sid = {p["steam_id"]: p for p in detail_players if p["steam_id"]}
            by_uuid = {p["uuid"]: p for p in detail_players if p["uuid"]}

            for steam_id, data in group:
                hist = self.friend_5e_history_stats.get(steam_id, {})
                if hist.get("last_match_id") == match_id:
                    nickname = hist.get("fivee_nickname", data.get("_fivee_nickname", "未知好友"))
                    self.log(f"[{datetime.now()}] {nickname} 的 5E 对局 {match_id} 已播报过，跳过")
                    continue

                detail_player = by_sid.get(steam_id) or by_uuid.get(data.get("_fivee_uuid", ""))
                if not detail_player:
                    continue

                enriched = dict(data)
                enriched.update({
                    "matchId": match_id,
                    "match_id": match_id,
                    "team": _to_int(detail_player.get("team")),
                    "winTeam": _to_int(winner),
                    "kill": detail_player["kill"],
                    "death": detail_player["death"],
                    "assist": detail_player["assist"],
                    "rating": detail_player["rating"],
                    "rws": detail_player["rws"],
                    "adr": detail_player["adr"],
                    "firstKill": detail_player["first_kill"],
                    "awpKill": detail_player["awp_kill"],
                    "kill3": detail_player["kill_3"],
                    "kill4": detail_player["kill_4"],
                    "kill5": detail_player["kill_5"],
                    "isMvp": detail_player["is_mvp"],
                    "isSvp": detail_player["is_svp"],
                    "eloChange": detail_player["change_elo"],
                    "elo": detail_player["origin_elo"] + detail_player["change_elo"],
                    "originElo": detail_player["origin_elo"],
                    "levelId": detail_player["level_id"],
                    "endTime": main.get("end_time", data.get("end_time")),
                    "duration": round((_to_int(main.get("end_time")) - _to_int(main.get("start_time"))) / 60)
                    if main.get("end_time") and main.get("start_time") else 0,
                })

                nickname = detail_player["nickname"] or data.get("_fivee_nickname", "未知好友")
                avatar = self.fivee_api.asset_url(detail_player["avatar"]) or data.get("_fivee_avatar", "")
                enriched["_fivee_nickname"] = nickname
                enriched["_fivee_avatar"] = avatar

                if score1 == score2:
                    result = "平局"
                elif detail_player["is_win"]:
                    result = "胜利"
                else:
                    result = "失败"

                all_players.append((steam_id, enriched, map_name, score1, score2, nickname, result))

        all_players.sort(key=lambda x: x[1].get("rating", 0), reverse=True)
        return all_players

    def _update_daily_stats(self, all_players: list) -> None:
        for steam_id, data, _, _, _, nickname, result in all_players:
            stats = self.friend_5e_daily_stats.setdefault(steam_id, {
                "fivee_nickname": nickname,
                "matches": [],
                "wins": 0,
                "losses": 0,
                "draws": 0,
                "total_elo_change": 0.0,
                "total_kills": 0,
                "total_deaths": 0,
                "total_assists": 0,
                "total_rating": 0.0,
                "total_rws": 0.0,
                "total_adr": 0.0,
                "match_count": 0,
            })
            stats["fivee_nickname"] = nickname
            stats["matches"].append(data.get("match_id") or data.get("matchId", ""))
            if result == "胜利":
                stats["wins"] += 1
            elif result == "失败":
                stats["losses"] += 1
            else:
                stats["draws"] += 1
            stats["total_elo_change"] += _to_float(data.get("eloChange"))
            stats["total_kills"] += _to_int(data.get("kill"))
            stats["total_deaths"] += _to_int(data.get("death"))
            stats["total_assists"] += _to_int(data.get("assist"))
            stats["total_rating"] += _to_float(data.get("rating"))
            stats["total_rws"] += _to_float(data.get("rws"))
            stats["total_adr"] += _to_float(data.get("adr"))
            stats["match_count"] += 1

    def _update_history_stats(self, all_players: list) -> None:
        for steam_id, data, _, _, _, nickname, _ in all_players:
            hist = self.friend_5e_history_stats.setdefault(steam_id, dict(self._HISTORY_REQUIRED_FIELDS))
            for field, default in self._HISTORY_REQUIRED_FIELDS.items():
                hist.setdefault(field, default)

            kills = _to_int(data.get("kill"))
            deaths = _to_int(data.get("death"))
            rating = _to_float(data.get("rating"))
            rws = _to_float(data.get("rws"))
            adr = _to_float(data.get("adr"))
            elo = _to_float(data.get("elo"))

            hist["fivee_nickname"] = nickname
            if data.get("_fivee_avatar"):
                hist["avatar"] = data["_fivee_avatar"]
            hist["last_match_id"] = data.get("match_id") or data.get("matchId", "")

            if kills > hist["max_kills"]:
                hist["max_kills"] = kills
            if 0 < kills < hist["min_kills"]:
                hist["min_kills"] = kills
            if deaths > hist["max_deaths"]:
                hist["max_deaths"] = deaths
            if 0 < deaths < hist["min_deaths"]:
                hist["min_deaths"] = deaths
            if rating > hist["max_rating"]:
                hist["max_rating"] = rating
            if 0 < rating < hist["min_rating"]:
                hist["min_rating"] = rating
            if rws > hist["max_rws"]:
                hist["max_rws"] = rws
            if 0 < rws < hist["min_rws"]:
                hist["min_rws"] = rws
            if adr > hist["max_adr"]:
                hist["max_adr"] = adr
            if 0 < adr < hist["min_adr"]:
                hist["min_adr"] = adr
            if elo > hist["max_elo"]:
                hist["max_elo"] = elo
            if 0 < elo < hist["min_elo"]:
                hist["min_elo"] = elo

    def _generate_messages(self, all_players: list) -> List[str]:
        if not all_players:
            return []
        groups: Dict[str, Dict[str, Any]] = {}
        for steam_id, data, map_name, score1, score2, nickname, result in all_players:
            match_id = data.get("match_id") or data.get("matchId")
            bucket = groups.setdefault(match_id, {
                "map_name": map_name,
                "score1": score1,
                "score2": score2,
                "duration": data.get("duration", 0),
                "players": [],
            })
            bucket["players"].append((steam_id, data, nickname, result))

        messages = []
        for match_id, info in groups.items():
            wins = sum(1 for _, _, _, r in info["players"] if r == "胜利")
            losses = sum(1 for _, _, _, r in info["players"] if r == "失败")
            draws = sum(1 for _, _, _, r in info["players"] if r == "平局")
            result_emoji = "🤝" if draws else ("✅" if wins > losses else "❌")
            score_info = f"{info['score1']}:{info['score2']}"
            if info.get("duration"):
                score_info += f" | {info['duration']}分钟"
            msg = f"{result_emoji} [5E] {info['map_name']}  {score_info}\n"
            msg += f"{'─' * 14}\n"

            players = sorted(info["players"], key=lambda x: x[1].get("rating", 0), reverse=True)
            for _, data, nickname, result in players:
                r_emoji = "🟢" if result == "胜利" else ("🔴" if result == "失败" else "🟡")
                tags = ""
                if data.get("isMvp"):
                    tags += " ⭐MVP"
                if data.get("isSvp"):
                    tags += " 🔥SVP"
                if data.get("kill5"):
                    tags += " 🔥五杀"
                elif data.get("kill4"):
                    tags += " 💥四杀"
                elif data.get("kill3"):
                    tags += " 💥三杀"

                elo_change = _to_float(data.get("eloChange"))
                score_sign = "+" if elo_change >= 0 else ""
                msg += f"{r_emoji} {nickname}{tags}\n"
                msg += (
                    f"  {data.get('kill', 0)}/{data.get('death', 0)}/{data.get('assist', 0)} "
                    f"| RT:{_to_float(data.get('rating')):.2f} "
                    f"| RWS:{_to_float(data.get('rws')):.2f} "
                    f"| ADR:{_to_float(data.get('adr')):.1f}\n"
                )
                if data.get("elo"):
                    msg += f"  ELO:{_fmt_num(_to_float(data.get('elo')))} ({score_sign}{_fmt_num(elo_change)})\n"

            messages.append(msg.rstrip())

        return messages
