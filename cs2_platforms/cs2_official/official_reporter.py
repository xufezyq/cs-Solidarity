"""
官匹战绩播报模块
复用完美世界 API（dataSource=1），独立于完美平台战绩（dataSource=3）

官匹 API 限制（经实测确认）：
- pwRating / we / pvpScore / pvpScoreChange / pvpStars 始终为 0
- get_match_mvp() 返回 null
- get_match_advance() 返回 404
- 可用字段：rating, rws, kast, headShotRatio, entryKill, entryDeath, threeKill 等
"""
import asyncio
import re
from datetime import datetime


class OfficialStatsReporter:
    """官匹战绩 reporter"""

    _HISTORY_REQUIRED_FIELDS = {
        'official_nickname': '未知好友',
        'avatar': '',
        'last_match_id': '',
        'max_kills': 0,
        'min_kills': 999,
        'max_deaths': 0,
        'min_deaths': 999,
        'max_rating': 0.0,
        'min_rating': 999.0,
        'max_rws': 0.0,
        'min_rws': 999.0,
        'max_kast': 0.0,
        'min_kast': 999.0,
    }

    MAX_MATCH_AGE_SECONDS = 3600

    def __init__(self, pw_api, friend_official_nickname_map, friend_official_history_stats,
                 friend_official_daily_stats, log):
        self.pw_api = pw_api
        self.friend_official_nickname_map = friend_official_nickname_map
        self.friend_official_history_stats = friend_official_history_stats
        self.friend_official_daily_stats = friend_official_daily_stats
        self.log = log

    @staticmethod
    def _is_draw_result(win_team, score1, score2) -> bool:
        if win_team in (0, -1):
            return True
        if score1 is None or score2 is None:
            return False
        return str(score1) == str(score2)

    async def fetch_and_report(self, steam_ids: list) -> tuple:
        """主入口：获取官匹战绩并生成消息

        Returns:
            (messages, processed_matches)
        """
        if not self.pw_api:
            return [], []

        match_groups = await self._fetch_match_lists(steam_ids)
        if not match_groups:
            return [], []

        self.log(f"[{datetime.now()}] 共发现 {len(match_groups)} 场有效官匹比赛，正在生成战报...")

        details = await self._fetch_match_details(match_groups)
        match_nicknames = details['nicknames']
        match_player_details = details['player_details']
        match_base_info = details['base_info']
        player_avatar_map = details['avatar_map']

        all_players = self._collect_player_data(match_groups, match_nicknames)

        await self._update_daily_stats(all_players)
        self._update_history_stats(all_players, player_avatar_map)

        messages = self._generate_messages(
            match_groups, all_players, match_base_info,
            match_player_details
        )

        return messages, all_players

    async def _fetch_match_lists(self, steam_ids: list) -> dict:
        """获取所有好友的官匹对局列表"""
        match_groups = {}

        self.log(f"[{datetime.now()}] 开始查询 {len(steam_ids)} 位好友的官匹战绩: {steam_ids}")

        for steam_id in steam_ids:
            try:
                match_data = await self.pw_api.get_csgopfmatch(steam_id, csgoSeasonId=1, type=-1)

                if isinstance(match_data, int) or not match_data.get('data'):
                    continue

                matches = match_data['data'].get('matchList', [])
                if not matches:
                    continue

                last_match = matches[0]
                match_id = last_match.get('matchId')

                end_time_str = last_match.get('endTime')
                if end_time_str and OfficialStatsReporter.MAX_MATCH_AGE_SECONDS:
                    try:
                        end_time = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S")
                        age_seconds = (datetime.now() - end_time).total_seconds()
                        if age_seconds > OfficialStatsReporter.MAX_MATCH_AGE_SECONDS:
                            self.log(
                                f"[{datetime.now()}] {steam_id} 最近官匹比赛 {match_id} "
                                f"已结束 {int(age_seconds // 60)} 分钟，"
                                f"超过 {OfficialStatsReporter.MAX_MATCH_AGE_SECONDS // 60} 分钟限制，跳过"
                            )
                            continue
                    except ValueError as e:
                        self.log(f"[{datetime.now()}] 解析官匹对局 {match_id} 结束时间失败: {end_time_str} ({e})")

                prev_match = matches[1] if len(matches) > 1 else None
                last_match['_prev_rating'] = prev_match.get('rating', 0.0) if prev_match else 0.0

                self.log(f"[{datetime.now()}] {steam_id} 发现最近官匹比赛: {match_id}")

                if match_id not in match_groups:
                    match_groups[match_id] = []
                match_groups[match_id].append((steam_id, last_match))

            except Exception as e:
                self.log(f"[{datetime.now()}] 查询官匹战绩出错 ({steam_id}): {e}")

        return match_groups

    async def _fetch_match_details(self, match_groups: dict) -> dict:
        """获取官匹对局详情"""
        match_nicknames = {}
        player_avatar_map = {}
        match_player_details = {}
        match_base_info = {}

        for match_id in match_groups:
            try:
                detail = await self.pw_api.get_match_detail(match_id, dataSource=1)
                if isinstance(detail, int) or not detail.get('players'):
                    match_nicknames[match_id] = {}
                    match_player_details[match_id] = {}
                    match_base_info[match_id] = {}
                    continue

                all_known_friends = set(self.friend_official_history_stats.keys())
                group_steam_ids = {sid for sid, _ in match_groups[match_id]}
                newly_discovered = set()

                base = detail.get('base', {})
                fh1 = base.get('halfScore1', 0)
                fh2 = base.get('halfScore2', 0)
                match_base_info[match_id] = {
                    'firstHalfScore1': fh1,
                    'firstHalfScore2': fh2,
                    'secondHalfScore1': base.get('score1', 0) - fh1,
                    'secondHalfScore2': base.get('score2', 0) - fh2,
                    'extraScore1': base.get('extraScore1', 0),
                    'extraScore2': base.get('extraScore2', 0),
                    'duration': base.get('duration', 0),
                    'greenMatch': base.get('greenMatch', False),
                    'map': base.get('map', ''),
                }

                for player in detail.get('players', []):
                    pid = str(player.get('playerId', ''))
                    if not pid:
                        continue
                    if pid in group_steam_ids:
                        continue
                    if pid not in all_known_friends:
                        continue
                    last_match = {
                        'matchId': match_id,
                        'mapName': match_groups[match_id][0][1].get('mapName', ''),
                        'score1': match_groups[match_id][0][1].get('score1'),
                        'score2': match_groups[match_id][0][1].get('score2'),
                        'winTeam': match_groups[match_id][0][1].get('winTeam'),
                        'playerId': pid,
                    }
                    match_groups[match_id].append((pid, last_match))
                    newly_discovered.add(pid)
                    self.log(f"[{datetime.now()}] 官匹对局 {match_id} 中发现好友 {pid}，一并加入播报")

                if newly_discovered:
                    async def _fetch_prev(sid):
                        try:
                            md = await self.pw_api.get_csgopfmatch(sid, csgoSeasonId=1, type=-1)
                            if isinstance(md, int) or not md.get('data'):
                                return sid, None
                            ml = md['data'].get('matchList', [])
                            if len(ml) >= 2:
                                return sid, ml[1]
                            return sid, None
                        except Exception:
                            return sid, None

                    prev_results = await asyncio.gather(*[_fetch_prev(sid) for sid in newly_discovered])
                    for sid, prev_match in prev_results:
                        for i, (gsid, gdata) in enumerate(match_groups[match_id]):
                            if gsid == sid and gdata.get('matchId') == match_id:
                                gdata['_prev_rating'] = prev_match.get('rating', 0.0) if prev_match else 0.0
                                break

                monitored_player_ids = {str(data.get('playerId', '')) for _, data in match_groups[match_id] if data.get('playerId')}

                nick_map = {}
                player_detail_map = {}
                for player in detail['players']:
                    pid = str(player.get('playerId', ''))
                    if pid not in monitored_player_ids:
                        continue
                    nick = player.get('nickName', '')
                    avatar = player.get('avatar', '')
                    if nick:
                        nick_map[pid] = nick
                    if avatar:
                        player_avatar_map[pid] = avatar
                    player_detail_map[pid] = {
                        'threeKill': player.get('threeKill', 0),
                        'fourKill': player.get('fourKill', 0),
                        'fiveKill': player.get('fiveKill', 0),
                        'vs3': player.get('vs3', 0),
                        'vs4': player.get('vs4', 0),
                        'vs5': player.get('vs5', 0),
                        'entryKill': player.get('entryKill', 0),
                        'entryDeath': player.get('entryDeath', 0),
                    }

                match_nicknames[match_id] = nick_map
                match_player_details[match_id] = player_detail_map

                self.log(f"[{datetime.now()}] 官匹对局 {match_id} 获取到 {len(nick_map)} 个昵称")

            except Exception as e:
                self.log(f"[{datetime.now()}] 获取官匹对局详情失败 ({match_id}): {e}")
                match_nicknames[match_id] = {}
                match_player_details[match_id] = {}
                match_base_info[match_id] = {}

        return {
            'nicknames': match_nicknames,
            'player_details': match_player_details,
            'base_info': match_base_info,
            'avatar_map': player_avatar_map,
        }

    def _collect_player_data(self, match_groups: dict, match_nicknames: dict) -> list:
        """收集所有玩家的数据"""
        all_players = []

        for match_id, group in match_groups.items():
            try:
                first_player_data = group[0][1]
                map_name = first_player_data.get('mapName', '未知地图')
                score1 = first_player_data.get('score1')
                score2 = first_player_data.get('score2')

                nicks = match_nicknames.get(match_id, {})

                for steam_id, data in group:
                    nick = nicks.get(steam_id, '')
                    if nick:
                        nickname = nick
                        self.friend_official_nickname_map[steam_id] = nick
                    else:
                        nickname = self.friend_official_nickname_map.get(steam_id, '未知好友')

                    hist = self.friend_official_history_stats.get(steam_id, {})
                    if hist.get('last_match_id') == match_id:
                        self.log(f"[{datetime.now()}] {nickname} 的官匹对局 {match_id} 已播报过，跳过")
                        continue

                    win_team = data.get('winTeam')
                    my_team = data.get('team')
                    if self._is_draw_result(win_team, score1, score2):
                        result = "平局"
                    elif win_team == my_team:
                        result = "胜利"
                    else:
                        result = "失败"

                    all_players.append((steam_id, data, map_name, score1, score2, nickname, result))

            except Exception as e:
                self.log(f"[{datetime.now()}] 处理官匹比赛数据出错 ({match_id}): {e}")

        all_players.sort(key=lambda x: x[1].get('rating', 0), reverse=True)
        return all_players

    async def _update_daily_stats(self, all_players: list) -> None:
        """更新每日官匹统计"""
        for steam_id, data, _, _, _, nickname, result in all_players:
            kills = data.get('kill', 0)
            deaths = data.get('death', 0)
            assists = data.get('assist', 0)
            rating = data.get('rating', 0.0)
            rws = data.get('rws', 0.0)
            kast = data.get('kast', 0.0)
            match_id = data.get('matchId', '')

            if steam_id not in self.friend_official_daily_stats:
                self.friend_official_daily_stats[steam_id] = {
                    'official_nickname': nickname,
                    'matches': [],
                    'wins': 0,
                    'losses': 0,
                    'draws': 0,
                    'total_kills': 0,
                    'total_deaths': 0,
                    'total_assists': 0,
                    'total_rating': 0.0,
                    'total_rws': 0.0,
                    'total_kast': 0.0,
                    'match_count': 0
                }

            stats = self.friend_official_daily_stats[steam_id]
            stats['matches'].append(match_id)
            if result == "胜利":
                stats['wins'] += 1
            elif result == "失败":
                stats['losses'] += 1
            elif result == "平局":
                stats['draws'] += 1

            stats['total_kills'] += kills
            stats['total_deaths'] += deaths
            stats['total_assists'] += assists
            stats['total_rating'] += rating
            stats['total_rws'] += rws
            stats['total_kast'] += kast
            stats['match_count'] += 1

    def _update_history_stats(self, all_players: list, player_avatar_map: dict) -> None:
        """更新官匹历史最佳战绩"""
        for steam_id, data, _, _, _, nickname, _ in all_players:
            kills = data.get('kill', 0)
            deaths = data.get('death', 0)
            rating = data.get('rating', 0.0)
            rws = data.get('rws', 0.0)
            kast = data.get('kast', 0.0)
            match_id = data.get('matchId', '')
            nick = data.get('nickName', '')

            if steam_id not in self.friend_official_history_stats:
                self.friend_official_history_stats[steam_id] = {
                    'official_nickname': nick or nickname,
                    'avatar': player_avatar_map.get(steam_id, ''),
                    'last_match_id': match_id,
                    'max_kills': 0,
                    'min_kills': 999,
                    'max_deaths': 0,
                    'min_deaths': 999,
                    'max_rating': 0.0,
                    'min_rating': 999.0,
                    'max_rws': 0.0,
                    'min_rws': 999.0,
                    'max_kast': 0.0,
                    'min_kast': 999.0,
                }

            hist = self.friend_official_history_stats[steam_id]

            for field, default_val in self._HISTORY_REQUIRED_FIELDS.items():
                if field not in hist:
                    hist[field] = default_val

            if player_avatar_map.get(steam_id):
                hist['avatar'] = player_avatar_map[steam_id]

            if kills > hist['max_kills']:
                hist['max_kills'] = kills
            if kills < hist['min_kills'] and kills > 0:
                hist['min_kills'] = kills

            if deaths > hist['max_deaths']:
                hist['max_deaths'] = deaths
            if deaths < hist['min_deaths'] and deaths > 0:
                hist['min_deaths'] = deaths

            if rating > hist['max_rating']:
                hist['max_rating'] = rating
            if rating < hist['min_rating'] and rating > 0:
                hist['min_rating'] = rating

            if rws > hist['max_rws']:
                hist['max_rws'] = rws
            if rws < hist['min_rws'] and rws > 0:
                hist['min_rws'] = rws

            if kast > hist['max_kast']:
                hist['max_kast'] = kast
            if kast < hist['min_kast'] and kast > 0:
                hist['min_kast'] = kast

            hist['official_nickname'] = nickname
            if nick:
                hist['official_nickname'] = nick
            hist['last_match_id'] = match_id

    def _generate_messages(self, match_groups: dict, all_players: list,
                           match_base_info: dict,
                           match_player_details: dict) -> list[str]:
        """生成官匹战报消息"""
        messages = []
        if not all_players:
            return messages

        match_msg_groups = {}
        for steam_id, data, map_name, score1, score2, nickname, result in all_players:
            match_id = data.get('matchId', f'{map_name}_{score1}_{score2}')
            if match_id not in match_msg_groups:
                match_msg_groups[match_id] = {
                    'map_name': map_name,
                    'score1': score1,
                    'score2': score2,
                    'players': []
                }
            match_msg_groups[match_id]['players'].append((steam_id, data, nickname, result))

        for match_id, match_info in match_msg_groups.items():
            map_name = match_info['map_name']
            score1 = match_info['score1']
            score2 = match_info['score2']
            players = match_info['players']

            base_info = match_base_info.get(match_id, {})
            fh1 = base_info.get('firstHalfScore1', 0)
            fh2 = base_info.get('firstHalfScore2', 0)
            sh1 = base_info.get('secondHalfScore1', 0)
            sh2 = base_info.get('secondHalfScore2', 0)
            ex1 = base_info.get('extraScore1', 0)
            ex2 = base_info.get('extraScore2', 0)
            duration = base_info.get('duration', 0)
            green_match = base_info.get('greenMatch', False)
            detail_map = base_info.get('map', '')
            if not map_name or map_name == '未知地图':
                map_name = detail_map or '未知地图'

            wins = sum(1 for _, _, _, r in players if r == '胜利')
            losses = sum(1 for _, _, _, r in players if r == '失败')
            draws = sum(1 for _, _, _, r in players if r == '平局')

            if draws > 0:
                result_emoji = '🤝'
            else:
                result_emoji = '✅' if wins > losses else ('❌' if losses > wins else '🤝')

            score_info = f"{score1}:{score2}"
            if ex1 > 0 or ex2 > 0:
                score_info += f" (半场 {fh1}:{fh2}/{sh1}:{sh2} | 加时 {ex1}:{ex2})"
            elif fh1 > 0 or fh2 > 0:
                score_info += f" (半场 {fh1}:{fh2}/{sh1}:{sh2})"
            if duration > 0:
                score_info += f" | {duration}分钟"
            if green_match:
                score_info += " | 🟢绿色对局"

            msg = f"{result_emoji} [官匹] {map_name}  {score_info}\n"
            msg += f"{'─' * 14}\n"

            players_sorted = sorted(players, key=lambda x: x[1].get('rating', 0), reverse=True)

            for steam_id, data, nickname, result in players_sorted:
                kills = data.get('kill', 0)
                deaths = data.get('death', 0)
                assists = data.get('assist', 0)
                rating = data.get('rating', 0.0)
                rws = data.get('rws', 0.0)
                kast = data.get('kast', 0.0)
                headshot = data.get('headShotRatio', 0.0)
                is_mvp = data.get('mvp', False)
                mvp_tag = ' ⭐MVP' if is_mvp else ''

                tags = mvp_tag
                player_detail = match_player_details.get(match_id, {}).get(steam_id, {})
                five_kill = player_detail.get('fiveKill', 0)
                four_kill = player_detail.get('fourKill', 0)
                three_kill = player_detail.get('threeKill', 0)
                vs5 = player_detail.get('vs5', 0)
                vs4 = player_detail.get('vs4', 0)
                vs3 = player_detail.get('vs3', 0)
                entry_kill = player_detail.get('entryKill', 0)
                if five_kill > 0:
                    tags += ' 🔥五杀'
                if four_kill > 0:
                    tags += ' 🔥四杀'
                if three_kill > 0:
                    tags += ' 💥三杀'
                if vs5 > 0:
                    tags += ' 🎯1v5'
                if vs4 > 0:
                    tags += ' 🎯1v4'
                if vs3 > 0:
                    tags += ' 🎯1v3'

                r_emoji = '🟢' if result == '胜利' else ('🔴' if result == '失败' else '🟡')

                msg += f"{r_emoji} {nickname}{tags}\n"
                msg += f"  {kills}/{deaths}/{assists} | RT:{rating:.2f} | RWS:{rws:.1f} | KAST:{kast:.0f}%\n"

                stat_parts = []
                if headshot > 0:
                    stat_parts.append(f"HS:{headshot:.0f}%")
                if entry_kill > 0:
                    stat_parts.append(f"首杀:{entry_kill}")
                if stat_parts:
                    msg += "  " + " | ".join(stat_parts) + "\n"

            messages.append(msg)

        return messages
