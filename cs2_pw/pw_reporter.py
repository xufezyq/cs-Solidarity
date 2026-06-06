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

    # 仅播报 N 秒以内结束的比赛；设为 0 或 None 表示不限制
    MAX_MATCH_AGE_SECONDS = 3600

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

    @staticmethod
    def _is_draw_result(win_team, score1, score2) -> bool:
        """完美平局可能返回 winTeam=-1；旧逻辑只兼容 winTeam=0。"""
        if win_team in (0, -1):
            return True
        if score1 is None or score2 is None:
            return False
        return str(score1) == str(score2)

    async def fetch_and_report(self, steam_ids: list) -> tuple:
        """主入口：获取战绩并生成消息

        Returns:
            (messages, processed_matches) 元组：
            - messages: 战报文本列表
            - processed_matches: 已处理的对局条目列表，每项为
              (steam_id, match_data, map_name, score1, score2, nickname, result)
        """
        if not self.pw_api:
            return [], []

        match_groups = await self._fetch_match_lists(steam_ids)
        if not match_groups:
            return [], []

        self.log(f"[{datetime.now()}] 共发现 {len(match_groups)} 场有效比赛，正在生成战报...")

        # 获取对局详情
        details = await self._fetch_match_details(match_groups)
        match_pw_nicknames = details['nicknames']
        match_player_details = details['player_details']
        match_base_info = details['base_info']
        match_mvp_info = details['mvp_info']
        player_avatar_map = details['avatar_map']

        # 收集所有玩家的数据，用于合并和排序
        all_players = self._collect_player_data(
            match_groups, match_pw_nicknames
        )

        # 更新统计数据
        await self._update_daily_stats(all_players)
        self._update_history_stats(all_players, player_avatar_map)

        # 生成消息
        messages = self._generate_messages(
            match_groups, all_players, match_base_info,
            match_mvp_info, match_player_details
        )

        # 检测 S 段位晋级（仅从 <2401 升到 >=2401 时播报）
        promo_msgs = []
        for steam_id, data, _, _, _, nickname, _ in all_players:
            pvpScore = data.get('pvpScore', 0)
            prev_score = data.get('_prev_pvpScore', 0)
            if pvpScore >= 2401 and prev_score < 2401:
                pw_name = data.get('nickName', '') or nickname
                promo_msgs.append(f"🎉 恭喜 {pw_name} 达到 S 段位！")

        return messages + promo_msgs, all_players

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

                # 时间窗口过滤：仅播报最近 1 小时以内结束的比赛
                end_time_str = last_match.get('endTime')
                if end_time_str and PwStatsReporter.MAX_MATCH_AGE_SECONDS:
                    try:
                        end_time = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S")
                        age_seconds = (datetime.now() - end_time).total_seconds()
                        if age_seconds > PwStatsReporter.MAX_MATCH_AGE_SECONDS:
                            self.log(
                                f"[{datetime.now()}] {steam_id} 最近比赛 {match_id} "
                                f"已结束 {int(age_seconds // 60)} 分钟，"
                                f"超过 {PwStatsReporter.MAX_MATCH_AGE_SECONDS // 60} 分钟限制，跳过"
                            )
                            continue
                    except ValueError as e:
                        self.log(f"[{datetime.now()}] 解析对局 {match_id} 结束时间失败: {end_time_str} ({e})")
                        # 解析失败时按现有流程继续，不因字段异常丢失可能有效的播报

                # 记录上一场的星星和分数，用于计算变化/晋级检测
                prev_match = matches[1] if len(matches) > 1 else None
                last_match['_prev_pvpStars'] = prev_match.get('pvpStars', 0) if prev_match else 0
                last_match['_prev_pvpScore'] = prev_match.get('pvpScore', 0) if prev_match else 0

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

        for match_id in match_groups:
            try:
                # 1. 获取全场数据
                detail = await self.pw_api.get_match_detail(match_id)
                if isinstance(detail, int) or not detail.get('players'):
                    match_pw_nicknames[match_id] = {}
                    match_player_details[match_id] = {}
                    match_base_info[match_id] = {}
                    match_mvp_info[match_id] = {}
                    continue

                # 2. 构建监控好友的 playerId 集合
                monitored_player_ids = {str(data.get('playerId', '')) for _, data in match_groups[match_id] if data.get('playerId')}

                # 3. 提取全场基础信息（所有玩家共享）
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
                }

                # 4. 提取好友相关数据（仅监控好友）
                nick_map = {}
                player_detail_map = {}
                for player in detail['players']:
                    pid = str(player.get('playerId', ''))
                    if pid not in monitored_player_ids:
                        continue
                    pw_nick = player.get('nickName', '')
                    avatar = player.get('avatar', '')
                    if pw_nick:
                        nick_map[pid] = pw_nick
                    if avatar:
                        player_avatar_map[pid] = avatar
                    player_detail_map[pid] = {
                        'fourKill': player.get('fourKill', 0),
                        'fiveKill': player.get('fiveKill', 0),
                        'vs4': player.get('vs4', 0),
                        'vs5': player.get('vs5', 0),
                    }

                match_pw_nicknames[match_id] = nick_map
                match_player_details[match_id] = player_detail_map

                # 5. 按需获取额外数据（仅当好友需要时）
                match_mvp_info[match_id] = {}

                # 5.1 MVP 称号（仅当好友是MVP时才获取）
                friend_is_mvp = any(
                    player.get('mvp', False) and str(player.get('playerId', '')) in monitored_player_ids
                    for player in detail['players']
                )
                if friend_is_mvp:
                    try:
                        mvp_info = await self.pw_api.get_match_mvp(match_id)
                        if not isinstance(mvp_info, int) and mvp_info:
                            match_mvp_info[match_id] = {
                                'statsDesc': mvp_info.get('statsDesc', ''),
                                'dataDesc': mvp_info.get('dataDesc', ''),
                                'mvp_nickname': mvp_info.get('nickName', ''),
                                'statsList': mvp_info.get('statsList', []),
                            }
                    except Exception as e:
                        self.log(f"[{datetime.now()}] 获取MVP信息失败 ({match_id}): {e}")

                # 5.2 高级数据（预留接口，暂未使用）
                # try:
                #     advance_data = await self.pw_api.get_match_advance(match_id)
                #     if not isinstance(advance_data, int) and advance_data:
                #         if isinstance(advance_data, list):
                #             match_advance_info[match_id] = {item.get('steamId', ''): item for item in advance_data}
                # except Exception as e:
                #     self.log(f"[{datetime.now()}] 获取高级数据失败 ({match_id}): {e}")

                self.log(f"[{datetime.now()}] 对局 {match_id} 获取到 {len(nick_map)} 个完美昵称")

            except Exception as e:
                self.log(f"[{datetime.now()}] 获取对局详情失败 ({match_id}): {e}")
                match_pw_nicknames[match_id] = {}
                match_player_details[match_id] = {}
                match_base_info[match_id] = {}
                match_mvp_info[match_id] = {}

        return {
            'nicknames': match_pw_nicknames,
            'player_details': match_player_details,
            'base_info': match_base_info,
            'mvp_info': match_mvp_info,
            'avatar_map': player_avatar_map,
        }

    def _collect_player_data(self, match_groups: dict, match_pw_nicknames: dict) -> list:
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
                    if self._is_draw_result(win_team, score1, score2):
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
            pvpStars = data.get('pvpStars', 0)
            prev_pvpStars = data.get('_prev_pvpStars', 0)
            stars_change = pvpStars - prev_pvpStars if pvpStars or prev_pvpStars else 0
            match_id = data.get('matchId', '')

            if steam_id not in self.friend_pw_daily_stats:
                self.friend_pw_daily_stats[steam_id] = {
                    'pw_nickname': nickname,
                    'matches': [],
                    'wins': 0,
                    'losses': 0,
                    'draws': 0,
                    'total_score_change': 0,
                    'total_stars_change': 0,
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
            stats['total_stars_change'] = stats.get('total_stars_change', 0) + stars_change
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
            fh1 = base_info.get('firstHalfScore1', 0)
            fh2 = base_info.get('firstHalfScore2', 0)
            sh1 = base_info.get('secondHalfScore1', 0)
            sh2 = base_info.get('secondHalfScore2', 0)
            ex1 = base_info.get('extraScore1', 0)
            ex2 = base_info.get('extraScore2', 0)
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
            if ex1 > 0 or ex2 > 0:
                score_info += f" (半场 {fh1}:{fh2}/{sh1}:{sh2} | 加时 {ex1}:{ex2})"
            elif fh1 > 0 or fh2 > 0:
                score_info += f" (半场 {fh1}:{fh2}/{sh1}:{sh2})"
            if duration > 0:
                score_info += f" | {duration}分钟"
            if green_match:
                score_info += " | 🟢绿色对局"

            # MVP 称号
            title_line = ""
            stats_list = mvp_info.get('statsList', [])
            if stats_list:
                title_line = f"👑 MVP: {mvp_nick}\n"
                for stat in stats_list:
                    stats_desc = stat.get('statsDesc', '')
                    data_desc = re.sub(r'<[^>]+>', '', stat.get('dataDesc', ''))
                    if stats_desc:
                        if data_desc:
                            title_line += f"   ◆ {stats_desc}：{data_desc}\n"
                        else:
                            title_line += f"   ◆ {stats_desc}\n"
                title_line += "\n"
            elif mvp_title and mvp_nick:
                title_line = f"👑 MVP: {mvp_nick} | {mvp_title}"
                if mvp_data_desc:
                    title_line += f" | {mvp_data_desc}"
                title_line += "\n\n"

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
                prev_pvpStars = data.get('_prev_pvpStars', 0)
                stars_change = pvpStars - prev_pvpStars if pvpStars or prev_pvpStars else 0

                tags = mvp_tag
                player_detail = match_player_details.get(match_id, {}).get(steam_id, {})
                four_kill = player_detail.get('fourKill', 0)
                five_kill = player_detail.get('fiveKill', 0)
                vs4 = player_detail.get('vs4', 0)
                vs5 = player_detail.get('vs5', 0)
                if five_kill > 0:
                    tags += ' 🔥五杀'
                if four_kill > 0:
                    tags += ' 🔥四杀'
                if vs5 > 0:
                    tags += ' 🎯1v5'
                if vs4 > 0:
                    tags += ' 🎯1v4'

                r_emoji = '🟢' if result == '胜利' else ('🔴' if result == '失败' else '🟡')

                msg += f"{r_emoji} {nickname}{tags}\n"
                msg += f"  {kills}/{deaths}/{assists} | pwRT:{pwRating:.2f} | WE:{we:.1f}\n"
                stars_str = ''
                if pvpStars > 0:
                    stars_str = f"⭐×{pvpStars}"
                    if stars_change > 0:
                        stars_str += f" (+{stars_change})"
                    elif stars_change < 0:
                        stars_str += f" ({stars_change})"
                # 构建分数行：有星星显示星星，有变化显示变化，有分数显示分数
                score_parts = []
                if pvpScore:
                    if score_change != 0:
                        score_parts.append(f"分数:{pvpScore} ({score_sign}{score_change})")
                    else:
                        score_parts.append(f"分数:{pvpScore}")
                if stars_str:
                    score_parts.append(stars_str)
                if score_parts:
                    msg += "  " + " | ".join(score_parts) + "\n"

            messages.append(msg)

        return messages
