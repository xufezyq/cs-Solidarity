"""
完美平台战绩播报模块
将 _fetch_pw_stats_async 的核心逻辑抽取为独立类，提高可维护性
"""
import re
from datetime import datetime


class PwStatsReporter:
    """完美平台战绩 reporter"""

    # 历史记录字段默认值（避免在循环中重复创建）
    _HISTORY_REQUIRED_FIELDS = {
        'pw_nickname': '未知好友',
        'avatar': '',
        'last_match_id': '',
        'max_kills': 0,
        'min_kills': 999,
        'max_deaths': 0,
        'min_deaths': 999,
        'max_rating': 0.0,
        'min_rating': 999.0,
        'max_pw_rating': 0.0,
        'min_pw_rating': 999.0,
        'max_we': 0,
        'min_we': 999,
        'max_score': 0,
        'min_score': 9999,
    }

    def __init__(self, pw_api, friend_pw_nickname_map, friend_pw_history_stats,
                 friend_pw_daily_stats, log):
        """
        Args:
            pw_api: PerfectWorldApi 实例
            friend_pw_nickname_map: 好友昵称映射
            friend_pw_history_stats: 历史战绩统计
            friend_pw_daily_stats: 每日战绩统计
            log: 日志函数
        """
        self.pw_api = pw_api
        self.friend_pw_nickname_map = friend_pw_nickname_map
        self.friend_pw_history_stats = friend_pw_history_stats
        self.friend_pw_daily_stats = friend_pw_daily_stats
        self.log = log

    async def fetch_and_report(self, steam_ids: list) -> list[str]:
        """主入口：获取战绩并生成消息"""
        if not self.pw_api:
            return []

        match_groups = await self._fetch_match_lists(steam_ids)
        if not match_groups:
            return []

        self.log(f"[{datetime.now()}] 共发现 {len(match_groups)} 场有效比赛，正在生成战报...")

        # 获取对局详情
        details = await self._fetch_match_details(match_groups)
        match_pw_nicknames = details['nicknames']
        match_player_details = details['player_details']
        match_base_info = details['base_info']
        match_mvp_info = details['mvp_info']
        match_advance_info = details['advance_info']
        player_avatar_map = details['avatar_map']
        match_all_players = details['all_players']

        # 收集所有玩家的数据，用于合并和排序
        all_players = self._collect_player_data(
            match_groups, match_pw_nicknames, match_all_players
        )

        # 更新统计数据
        await self._update_daily_stats(all_players)
        self._update_history_stats(all_players, player_avatar_map)

        # 生成消息
        messages = self._generate_messages(
            match_groups, all_players, match_base_info,
            match_mvp_info, match_player_details
        )

        return messages

    async def _fetch_match_lists(self, steam_ids: list) -> dict:
        """获取所有好友的对局列表"""
        match_groups = {}  # match_id -> list of (steam_id, match_data)

        self.log(f"[{datetime.now()}] 开始查询 {len(steam_ids)} 位好友的完美平台战绩: {steam_ids}")

        for steam_id in steam_ids:
            try:
                match_data = await self.pw_api.get_csgopfmatch(steam_id, csgoSeasonId=3, type=-1)

                if isinstance(match_data, int) or not match_data.get('data'):
                    continue

                matches = match_data['data'].get('matchList', [])
                if not matches:
                    continue

                last_match = matches[0]
                match_id = last_match.get('matchId')

                self.log(f"[{datetime.now()}] {steam_id} 发现最近比赛: {match_id}")

                if match_id not in match_groups:
                    match_groups[match_id] = []
                match_groups[match_id].append((steam_id, last_match))

            except Exception as e:
                self.log(f"[{datetime.now()}] 查询完美战绩出错 ({steam_id}): {e}")

        return match_groups

    async def _fetch_match_details(self, match_groups: dict) -> dict:
        """获取对局详情（昵称、MVP、高级数据等）"""
        match_pw_nicknames = {}
        player_avatar_map = {}
        match_player_details = {}
        match_base_info = {}
        match_mvp_info = {}
        match_advance_info = {}
        match_all_players = {}

        for match_id in match_groups:
            try:
                detail = await self.pw_api.get_match_detail(match_id)
                if isinstance(detail, int) or not detail.get('players'):
                    match_pw_nicknames[match_id] = {}
                    match_player_details[match_id] = {}
                    match_base_info[match_id] = {}
                    match_mvp_info[match_id] = {}
                    match_all_players[match_id] = []
                    match_advance_info[match_id] = {}
                    continue

                # 对局基本信息
                base = detail.get('base', {})
                match_base_info[match_id] = {
                    'halfScore1': base.get('halfScore1', 0),
                    'halfScore2': base.get('halfScore2', 0),
                    'extraScore1': base.get('extraScore1', 0),
                    'extraScore2': base.get('extraScore2', 0),
                    'duration': base.get('duration', 0),
                    'greenMatch': base.get('greenMatch', False),
                }

                # MVP 称号
                try:
                    mvp_info = await self.pw_api.get_match_mvp(match_id)
                    if not isinstance(mvp_info, int) and mvp_info:
                        match_mvp_info[match_id] = {
                            'statsDesc': mvp_info.get('statsDesc', ''),
                            'dataDesc': mvp_info.get('dataDesc', ''),
                            'mvp_nickname': mvp_info.get('nickName', ''),
                            'statsList': mvp_info.get('statsList', []),
                        }
                    else:
                        match_mvp_info[match_id] = {}
                except Exception as e:
                    self.log(f"[{datetime.now()}] 获取MVP信息失败 ({match_id}): {e}")
                    match_mvp_info[match_id] = {}

                # 高级数据
                try:
                    advance_data = await self.pw_api.get_match_advance(match_id)
                    if not isinstance(advance_data, int) and advance_data:
                        if isinstance(advance_data, list):
                            match_advance_info[match_id] = {item.get('steamId', ''): item for item in advance_data}
                except Exception as e:
                    self.log(f"[{datetime.now()}] 获取高级数据失败 ({match_id}): {e}")
                    match_advance_info[match_id] = {}

                # 提取玩家昵称和详情
                nick_map = {}
                player_detail_map = {}
                for player in detail['players']:
                    pid = str(player.get('playerId', ''))
                    pw_nick = player.get('nickName', '')
                    avatar = player.get('avatar', '')
                    if pid and pw_nick:
                        nick_map[pid] = pw_nick
                    if pid and avatar:
                        player_avatar_map[pid] = avatar
                    if pid:
                        player_detail_map[pid] = {
                            'threeKill': player.get('threeKill', 0),
                            'fourKill': player.get('fourKill', 0),
                            'fiveKill': player.get('fiveKill', 0),
                            'vs3': player.get('vs3', 0),
                            'vs4': player.get('vs4', 0),
                            'vs5': player.get('vs5', 0),
                        }

                match_pw_nicknames[match_id] = nick_map
                match_player_details[match_id] = player_detail_map
                match_all_players[match_id] = detail['players']
                self.log(f"[{datetime.now()}] 对局 {match_id} 获取到 {len(nick_map)} 个完美昵称")

            except Exception as e:
                self.log(f"[{datetime.now()}] 获取对局详情失败 ({match_id}): {e}")
                match_pw_nicknames[match_id] = {}
                match_player_details[match_id] = {}
                match_base_info[match_id] = {}
                match_mvp_info[match_id] = {}
                match_all_players[match_id] = []
                match_advance_info[match_id] = {}

        return {
            'nicknames': match_pw_nicknames,
            'player_details': match_player_details,
            'base_info': match_base_info,
            'mvp_info': match_mvp_info,
            'advance_info': match_advance_info,
            'avatar_map': player_avatar_map,
            'all_players': match_all_players,
        }

    def _collect_player_data(self, match_groups: dict, match_pw_nicknames: dict,
                             match_all_players: dict) -> list:
        """收集所有玩家的数据"""
        all_players = []

        for match_id, group in match_groups.items():
            try:
                first_player_data = group[0][1]
                map_name = first_player_data.get('mapName', '未知地图')
                score1 = first_player_data.get('score1')
                score2 = first_player_data.get('score2')

                pw_nicks = match_pw_nicknames.get(match_id, {})

                for steam_id, data in group:
                    pw_name = pw_nicks.get(steam_id, '')
                    if pw_name:
                        nickname = pw_name
                        self.friend_pw_nickname_map[steam_id] = pw_name
                    else:
                        nickname = self.friend_pw_nickname_map.get(steam_id, '未知好友')

                    # 跳过已播报
                    hist = self.friend_pw_history_stats.get(steam_id, {})
                    if hist.get('last_match_id') == match_id:
                        self.log(f"[{datetime.now()}] {nickname} 的对局 {match_id} 已播报过，跳过")
                        continue

                    # 胜负
                    win_team = data.get('winTeam')
                    my_team = data.get('team')
                    if win_team == 0:
                        result = "平局"
                    elif win_team == my_team:
                        result = "胜利"
                    else:
                        result = "失败"

                    all_players.append((steam_id, data, map_name, score1, score2, nickname, result))

            except Exception as e:
                self.log(f"[{datetime.now()}] 处理比赛数据出错 ({match_id}): {e}")

        # 按 WE 排序
        all_players.sort(key=lambda x: x[1].get('we', 0), reverse=True)
        return all_players

    async def _update_daily_stats(self, all_players: list) -> None:
        """更新每日统计"""
        for steam_id, data, _, _, _, nickname, result in all_players:
            kills = data.get('kill', 0)
            deaths = data.get('death', 0)
            assists = data.get('assist', 0)
            rating = data.get('rating', 0.0)
            pwRating = data.get('pwRating', 0.0)
            we = data.get('we', 0)
            score_change = data.get('pvpScoreChange', 0)
            match_id = data.get('matchId', '')

            if steam_id not in self.friend_pw_daily_stats:
                self.friend_pw_daily_stats[steam_id] = {
                    'pw_nickname': nickname,
                    'matches': [],
                    'wins': 0,
                    'losses': 0,
                    'draws': 0,
                    'total_score_change': 0,
                    'total_kills': 0,
                    'total_deaths': 0,
                    'total_assists': 0,
                    'total_rating': 0.0,
                    'total_pw_rating': 0.0,
                    'total_we': 0,
                    'match_count': 0
                }

            stats = self.friend_pw_daily_stats[steam_id]
            stats['matches'].append(match_id)
            if result == "胜利":
                stats['wins'] += 1
            elif result == "失败":
                stats['losses'] += 1
            elif result == "平局":
                stats['draws'] += 1

            stats['total_score_change'] += score_change
            stats['total_kills'] += kills
            stats['total_deaths'] += deaths
            stats['total_assists'] += assists
            stats['total_rating'] += rating
            stats['total_pw_rating'] += pwRating
            stats['total_we'] += we
            stats['match_count'] += 1

    def _update_history_stats(self, all_players: list, player_avatar_map: dict) -> None:
        """更新历史最佳战绩"""
        for steam_id, data, _, _, _, nickname, _ in all_players:
            kills = data.get('kill', 0)
            deaths = data.get('death', 0)
            rating = data.get('rating', 0.0)
            pwRating = data.get('pwRating', 0.0)
            we = data.get('we', 0)
            pvpScore = data.get('pvpScore', 0)
            match_id = data.get('matchId', '')
            pw_name = data.get('nickName', '')

            if steam_id not in self.friend_pw_history_stats:
                self.friend_pw_history_stats[steam_id] = {
                    'pw_nickname': pw_name or nickname,
                    'avatar': player_avatar_map.get(steam_id, ''),
                    'last_match_id': match_id,
                    'max_kills': 0,
                    'min_kills': 999,
                    'max_deaths': 0,
                    'min_deaths': 999,
                    'max_rating': 0.0,
                    'min_rating': 999.0,
                    'max_pw_rating': 0.0,
                    'min_pw_rating': 999.0,
                    'max_we': 0,
                    'min_we': 999,
                    'max_score': 0,
                    'min_score': 9999,
                }

            hist = self.friend_pw_history_stats[steam_id]

            for field, default_val in self._HISTORY_REQUIRED_FIELDS.items():
                if field not in hist:
                    hist[field] = default_val

            # 更新头像
            if player_avatar_map.get(steam_id):
                hist['avatar'] = player_avatar_map[steam_id]

            # 更新各项历史记录
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

            if pwRating > hist['max_pw_rating']:
                hist['max_pw_rating'] = pwRating
            if pwRating < hist['min_pw_rating'] and pwRating > 0:
                hist['min_pw_rating'] = pwRating

            if we > hist['max_we']:
                hist['max_we'] = we
            if we < hist['min_we'] and we > 0:
                hist['min_we'] = we

            if pvpScore > 0:
                if pvpScore > hist['max_score']:
                    hist['max_score'] = pvpScore
                if pvpScore < hist['min_score']:
                    hist['min_score'] = pvpScore

            # 更新昵称和最后一局
            hist['pw_nickname'] = nickname
            if pw_name:
                hist['pw_nickname'] = pw_name
            hist['last_match_id'] = match_id

    def _generate_messages(self, match_groups: dict, all_players: list,
                           match_base_info: dict, match_mvp_info: dict,
                           match_player_details: dict) -> list[str]:
        """生成战报消息"""
        messages = []
        if not all_players:
            return messages

        # 按 match_id 分组
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

            # 对局详情
            base_info = match_base_info.get(match_id, {})
            half1 = base_info.get('halfScore1', 0)
            half2 = base_info.get('halfScore2', 0)
            extra1 = base_info.get('extraScore1', 0)
            extra2 = base_info.get('extraScore2', 0)
            duration = base_info.get('duration', 0)
            green_match = base_info.get('greenMatch', False)

            # MVP
            mvp_info = match_mvp_info.get(match_id, {})
            mvp_title = mvp_info.get('statsDesc', '')
            mvp_data_desc = mvp_info.get('dataDesc', '')
            mvp_data_desc = re.sub(r'<[^>]+>', '', mvp_data_desc)
            mvp_nick = mvp_info.get('mvp_nickname', '')

            # 总体胜负
            wins = sum(1 for _, _, _, r in players if r == '胜利')
            losses = sum(1 for _, _, _, r in players if r == '失败')
            draws = sum(1 for _, _, _, r in players if r == '平局')

            if draws > 0:
                result_emoji = '🤝'
            else:
                result_emoji = '✅' if wins > losses else ('❌' if losses > wins else '🤝')

            # 比分信息
            score_info = f"{score1}:{score2}"
            if extra1 > 0 or extra2 > 0:
                score_info += f" (半场 {half1}:{half2} | 加时 {extra1}:{extra2})"
            elif half1 > 0 or half2 > 0:
                score_info += f" (半场 {half1}:{half2})"
            if duration > 0:
                score_info += f" | {duration}分钟"
            if green_match:
                score_info += " | 🟢绿色对局"

            # MVP 称号
            title_line = ""
            if mvp_title and mvp_nick:
                title_line = f"👑 MVP: {mvp_nick} | {mvp_title}"
                if mvp_data_desc:
                    title_line += f" | {mvp_data_desc}"
                title_line += "\n"

            msg = f"{result_emoji} {map_name}  {score_info}\n"
            msg += f"{'─' * 14}\n"
            msg += title_line

            # 按 WE 排序
            players_sorted = sorted(players, key=lambda x: x[1].get('we', 0), reverse=True)

            for steam_id, data, nickname, result in players_sorted:
                kills = data.get('kill', 0)
                deaths = data.get('death', 0)
                assists = data.get('assist', 0)
                rating = data.get('rating', 0.0)
                pwRating = data.get('pwRating', 0.0)
                we = data.get('we', 0)
                pvpScore = data.get('pvpScore', 0)
                score_change = data.get('pvpScoreChange', 0)
                score_sign = '+' if score_change >= 0 else ''
                is_mvp = data.get('pvpMvp', False)
                mvp_tag = ' ⭐MVP' if is_mvp else ''
                pvpStars = data.get('pvpStars', 0)

                # 多杀和残局
                player_detail = match_player_details.get(match_id, {}).get(steam_id, {})
                three_kill = player_detail.get('threeKill', 0)
                four_kill = player_detail.get('fourKill', 0)
                five_kill = player_detail.get('fiveKill', 0)
                vs3 = player_detail.get('vs3', 0)
                vs4 = player_detail.get('vs4', 0)
                vs5 = player_detail.get('vs5', 0)

                tags = mvp_tag
                if five_kill > 0:
                    tags += ' 🔥五杀'
                if four_kill > 0:
                    tags += ' 💥四杀'
                if three_kill > 0:
                    tags += ' 💥三杀'
                if vs5 > 0:
                    tags += ' 🎯1v5'
                if vs4 > 0:
                    tags += ' 🎯1v4'
                if vs3 > 0:
                    tags += ' 🎯1v3'

                r_emoji = '🟢' if result == '胜利' else ('🔴' if result == '失败' else '🟡')
                stars_str = f"⭐×{pvpStars}" if pvpStars > 0 else ''

                msg += f"{r_emoji} {nickname}{tags}\n"
                msg += f"  {kills}/{deaths}/{assists}  pwRT:{pwRating:.2f}  WE:{we:.1f}\n"
                msg += f"  分数:{pvpScore} ({score_sign}{score_change}) | {stars_str}\n"

            messages.append(msg)

        return messages
