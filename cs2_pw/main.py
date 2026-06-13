import asyncio
import os
import sys
import io
import re
import json
from datetime import datetime
from .request import PerfectWorldApi

# 修复 Windows 控制台编码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def main():
    # 请在这里填入你的 完美平台 ID (Steam ID) 和 Token
    # 你可以通过抓包完美平台 App 获取 Token
    uid = ""  # 例如: "76561198xxxxxxxxx"
    token = "" # 例如: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    # 如果环境变量中有配置，则优先使用环境变量
    if os.getenv("CS2_UID"):
        uid = os.getenv("CS2_UID")
    if os.getenv("CS2_TOKEN"):
        token = os.getenv("CS2_TOKEN")

    if uid == "" or token == "":
        print("请在 main.py 中配置 uid 和 token，或者设置 CS2_UID 和 CS2_TOKEN 环境变量。")
        return

    print(f"正在使用 UID: {uid} 和 Token: {token[:5]}... 进行测试\n")

    api = PerfectWorldApi(uid=uid, token=token)

    # 创建输出目录，保存所有接口响应
    output_dir = os.path.join(os.path.dirname(__file__), "test_output")
    os.makedirs(output_dir, exist_ok=True)

    # 1:1 复刻 steam_auto 的完美战绩播报逻辑
    steam_ids = ["76561199262650715"]  # 测试用好友列表

    match_groups = {}  # match_id -> list of (steam_id, match_data)

    print(f"[{datetime.now()}] 开始查询 {len(steam_ids)} 位好友的完美平台战绩: {steam_ids}\n")

    for steam_id in steam_ids:
        try:
            # 获取最近对局列表 (dataSource=3 表示完美平台)
            match_data = await api.get_csgopfmatch(steam_id, csgoSeasonId=3, type=-1)

            # 保存 get_csgopfmatch 响应
            with open(os.path.join(output_dir, f"csgopfmatch_{steam_id}.json"), "w", encoding="utf-8") as f:
                json.dump(match_data, f, ensure_ascii=False, indent=2)

            if isinstance(match_data, int) or not match_data.get('data'):
                continue

            matches = match_data['data'].get('matchList', [])
            if not matches:
                continue

            # 获取最近一场比赛
            last_match = matches[0]
            match_id = last_match.get('matchId')

            # 检查比赛是否是最近结束的 (例如 30 分钟内)
            # 测试时不限制时间
            end_time_str = last_match.get('endTime')
            if end_time_str:
                end_time = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S")
                time_diff = (datetime.now() - end_time).total_seconds()
                print(f"[{datetime.now()}] {steam_id} 发现比赛: {match_id}, 结束时间: {end_time_str} ({int(time_diff/60)}分钟前)")

            if match_id not in match_groups:
                match_groups[match_id] = []
            match_groups[match_id].append((steam_id, last_match))

        except Exception as e:
            print(f"[{datetime.now()}] 查询完美战绩出错 ({steam_id}): {e}")

    if not match_groups:
        print(f"[{datetime.now()}] 本次查询未发现有效的新比赛")
        return

    print(f"\n[{datetime.now()}] 共发现 {len(match_groups)} 场有效比赛，正在生成战报...\n")

    # 为每场对局调用 get_match_detail 获取完美平台昵称（同一 matchId 只调一次）
    match_pw_nicknames = {}  # match_id -> {steam_id: pw_nickname}
    player_avatar_map = {}   # steam_id -> avatar_url (最新一场对局的头像)
    match_player_details = {}  # match_id -> {playerId: {threeKill, fourKill, fiveKill, vs3, vs4, vs5}}
    match_base_info = {}  # match_id -> {halfScore1, halfScore2, extraScore1, extraScore2, duration, greenMatch}
    match_mvp_info = {}  # match_id -> {statsDesc, dataDesc, mvp_nickname, statsList}
    match_advance_info = {}  # match_id -> {steamId: {hitRate, scramRate, tradeRate, tradeFragRate}}
    match_all_players = {}  # match_id -> [all players data from detail['players']]

    for match_id in match_groups:
        try:
            detail = await api.get_match_detail(match_id)
            # 保存 get_match_detail 响应
            with open(os.path.join(output_dir, f"match_detail_{match_id.replace('@', '_at_')}.json"), "w", encoding="utf-8") as f:
                json.dump(detail, f, ensure_ascii=False, indent=2)
            print(f"\n--- get_match_detail: {match_id} ---")
            if isinstance(detail, int) or not detail.get('players'):
                match_pw_nicknames[match_id] = {}
                match_player_details[match_id] = {}
                match_base_info[match_id] = {}
                match_mvp_info[match_id] = {}
                match_all_players[match_id] = []
                match_advance_info[match_id] = {}
                print(f"  返回数据异常，跳过")
                continue

            # 提取对局基本信息
            base = detail.get('base', {})
            match_base_info[match_id] = {
                'halfScore1': base.get('halfScore1', 0),
                'halfScore2': base.get('halfScore2', 0),
                'extraScore1': base.get('extraScore1', 0),
                'extraScore2': base.get('extraScore2', 0),
                'duration': base.get('duration', 0),
                'greenMatch': base.get('greenMatch', False),
                'winTeam': base.get('winTeam', 0),
            }
            print(f"  base: halfScore={base.get('halfScore1',0)}:{base.get('halfScore2',0)}, extraScore={base.get('extraScore1',0)}:{base.get('extraScore2',0)}, duration={base.get('duration',0)}, greenMatch={base.get('greenMatch',False)}, winTeam={base.get('winTeam',0)}")

            # 获取MVP称号信息
            try:
                mvp_info = await api.get_match_mvp(match_id)
                # 保存 get_match_mvp 响应
                with open(os.path.join(output_dir, f"match_mvp_{match_id.replace('@', '_at_')}.json"), "w", encoding="utf-8") as f:
                    json.dump(mvp_info, f, ensure_ascii=False, indent=2)
                print(f"\n  --- get_match_mvp: {match_id} ---")
                print(f"  mvp_info type: {type(mvp_info)}, is int: {isinstance(mvp_info, int)}")
                if not isinstance(mvp_info, int) and mvp_info:
                    clean_data_desc = re.sub(r'<[^>]+>', '', mvp_info.get('dataDesc', ''))
                    print(f"  MVP: nickName={mvp_info.get('nickName','')}, statsDesc={mvp_info.get('statsDesc','')}, dataDesc={clean_data_desc}, mvpCnt={mvp_info.get('mvpCnt',0)}")
                    match_mvp_info[match_id] = {
                        'statsDesc': mvp_info.get('statsDesc', ''),
                        'dataDesc': mvp_info.get('dataDesc', ''),
                        'mvp_nickname': mvp_info.get('nickName', ''),
                        'statsList': mvp_info.get('statsList', []),
                    }
                else:
                    print(f"  mvp_info 异常或为空: {mvp_info}")
                    match_mvp_info[match_id] = {}
            except Exception as e:
                print(f"  获取MVP信息失败: {e}")
                match_mvp_info[match_id] = {}

            # 获取高级数据（命中率、拉枪率等）
            try:
                advance_data = await api.get_match_advance(match_id)
                with open(os.path.join(output_dir, f"match_advance_{match_id.replace('@', '_at_')}.json"), "w", encoding="utf-8") as f:
                    json.dump(advance_data, f, ensure_ascii=False, indent=2)
                if not isinstance(advance_data, int) and advance_data:
                    if isinstance(advance_data, list):
                        match_advance_info[match_id] = {item.get('steamId', ''): item for item in advance_data}
                    print(f"\n  --- get_match_advance: {match_id} ---")
                    print(f"  高级数据: {len(advance_data) if isinstance(advance_data, list) else 0} 名玩家")
                else:
                    match_advance_info[match_id] = {}
            except Exception as e:
                print(f"  获取高级数据失败: {e}")
                match_advance_info[match_id] = {}

            nick_map = {}
            player_detail_map = {}
            # 保存所有玩家数据
            match_all_players[match_id] = detail['players']
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

            # 打印有高光数据的玩家
            print(f"\n  --- Players with highlights ---")
            for pid, pdetail in player_detail_map.items():
                nick = nick_map.get(pid, '?')
                if pdetail['fiveKill'] > 0 or pdetail['fourKill'] > 0 or pdetail['threeKill'] > 0 or pdetail['vs5'] > 0 or pdetail['vs4'] > 0 or pdetail['vs3'] > 0:
                    print(f"  {nick} (pid={pid}): 3k={pdetail['threeKill']} 4k={pdetail['fourKill']} 5k={pdetail['fiveKill']} vs3={pdetail['vs3']} vs4={pdetail['vs4']} vs5={pdetail['vs5']}")

            match_pw_nicknames[match_id] = nick_map
            match_player_details[match_id] = player_detail_map
            print(f"\n  对局 {match_id} 获取到 {len(nick_map)} 个完美昵称")

        except Exception as e:
            print(f"[{datetime.now()}] 获取对局详情失败 ({match_id}): {e}")
            match_pw_nicknames[match_id] = {}
            match_player_details[match_id] = {}
            match_base_info[match_id] = {}
            match_mvp_info[match_id] = {}
            match_all_players[match_id] = []
            match_advance_info[match_id] = {}

    # 收集所有玩家的数据，用于合并和排序
    all_players = []  # [(steam_id, data, map_name, score1, score2, nickname, result)]
    # 建立 playerId -> match_data (包含 pvpScore, pvpScoreChange) 的映射
    playerId_match_map = {}  # playerId -> match_data
    for match_id, group in match_groups.items():
        for steam_id, data in group:
            player_id = data.get('playerId', '')
            if player_id:
                playerId_match_map[player_id] = data

    for match_id, group in match_groups.items():
        try:
            first_player_data = group[0][1]
            map_name = first_player_data.get('mapName', '未知地图')
            score1 = first_player_data.get('score1')
            score2 = first_player_data.get('score2')

            pw_nicks = match_pw_nicknames.get(match_id, {})

            for steam_id, data in group:
                pw_name = pw_nicks.get(steam_id, '')
                nickname = pw_name if pw_name else f"steam_{steam_id[-4:]}"

                # 跳过已播报的对局（这里简化处理，不做历史记录）
                # hist = self.friend_pw_history_stats.get(steam_id, {})
                # if hist.get('last_match_id') == match_id:
                #     continue

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
            print(f"[{datetime.now()}] 处理比赛数据出错 ({match_id}): {e}")

    # 按WE排序（从高到低）
    all_players.sort(key=lambda x: x[1].get('we', 0), reverse=True)

    # 生成消息：按 match_id 分组（同一局只发一次）
    messages = []
    if all_players:
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

        print("\n" + "=" * 50)
        print("生成的战报消息：")
        print("=" * 50 + "\n")

        for match_id, match_info in match_msg_groups.items():
            map_name = match_info['map_name']
            score1 = match_info['score1']
            score2 = match_info['score2']
            players = match_info['players']

            # 获取对局详细信息
            base_info = match_base_info.get(match_id, {})
            win_team = base_info.get('winTeam', 0)
            half1 = base_info.get('halfScore1', 0)
            half2 = base_info.get('halfScore2', 0)
            extra1 = base_info.get('extraScore1', 0)
            extra2 = base_info.get('extraScore2', 0)
            duration = base_info.get('duration', 0)
            green_match = base_info.get('greenMatch', False)

            # 获取MVP称号
            mvp_info = match_mvp_info.get(match_id, {})
            mvp_title = mvp_info.get('statsDesc', '')
            mvp_data_desc = mvp_info.get('dataDesc', '')
            # 去掉 dataDesc 中的 HTML 标签
            mvp_data_desc = re.sub(r'<[^>]+>', '', mvp_data_desc)
            mvp_nick = mvp_info.get('mvp_nickname', '')
            stats_list = mvp_info.get('statsList', [])

            # 获取所有玩家并按WE排序
            all_match_players = match_all_players.get(match_id, [])

            # 判断总体胜负（基于比分）
            if score1 > score2:
                result_emoji = '✅'
            elif score2 > score1:
                result_emoji = '❌'
            else:
                result_emoji = '🤝'

            # 构建比分信息
            score_info = f"{score1}:{score2}"
            if extra1 > 0 or extra2 > 0:
                score_info += f" (半场 {half1}:{half2} | 加时 {extra1}:{extra2})"
            elif half1 > 0 or half2 > 0:
                score_info += f" (半场 {half1}:{half2})"
            if duration > 0:
                score_info += f" | {duration}分钟"
            if green_match:
                score_info += " | 🟢绿色对局"

            # 构建MVP称号信息（支持多称号）
            title_line = ""
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
            elif mvp_title and mvp_nick:
                title_line = f"👑 MVP: {mvp_nick} | {mvp_title}"
                if mvp_data_desc:
                    title_line += f" | {mvp_data_desc}"
                title_line += "\n"

            msg = f"{result_emoji} {map_name}  {score_info}\n"
            msg += f"{'─' * 14}\n"
            msg += title_line

            # 按WE排序本场玩家
            players_sorted = sorted(all_match_players, key=lambda x: x.get('we', 0), reverse=True)

            for player in players_sorted:
                nickname = player.get('nickName', '未知')
                kills = player.get('kill', 0)
                deaths = player.get('death', 0)
                assists = player.get('assist', 0)
                rating = player.get('rating', 0.0)
                pwRating = player.get('pwRating', 0.0)
                we = player.get('we', 0)
                team = player.get('team', 0)
                win_team = base_info.get('winTeam', 0)

                # 胜负判断
                if win_team == 0:
                    result = "平局"
                    r_emoji = '🟡'
                elif win_team == team:
                    result = "胜利"
                    r_emoji = '🟢'
                else:
                    result = "失败"
                    r_emoji = '🔴'

                # 获取MVP和星级（从player对象直接获取）
                is_mvp = player.get('mvp', False)
                mvp_tag = ' ⭐MVP' if is_mvp else ''

                # 多杀和残局数据（从 match_player_details 获取）
                player_id = str(player.get('playerId', ''))
                player_detail = match_player_details.get(match_id, {}).get(player_id, {})
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

                # 构建天梯信息（从player对象获取）
                player_id = str(player.get('playerId', ''))
                match_data = playerId_match_map.get(player_id, {})
                pvpScore = player.get('pvpScore', 0)
                pvpScoreChange = match_data.get('pvpScoreChange', 0)
                score_sign = '+' if pvpScoreChange >= 0 else ''
                pvpStars = player.get('pvpStars', 0)
                stars_str = f"⭐×{pvpStars}" if pvpStars > 0 else ''

                # 高级数据（从 get_match_advance）
                steam_id_for_advance = player.get('playerId', '')  # MatchAdvance uses playerId as steamId key
                advance = match_advance_info.get(match_id, {}).get(steam_id_for_advance, {})
                hit_rate = advance.get('hitRate', 0)
                trade_rate = advance.get('tradeRate', 0)
                adv_str = f"  命中率:{hit_rate:.1%} 拉枪率:{trade_rate:.1%}" if hit_rate or trade_rate else ""

                msg += f"{r_emoji} {nickname}{tags}\n"
                msg += f"  {kills}/{deaths}/{assists} | pwRT:{pwRating:.2f} | WE:{we:.1f}\n"

                # 构建分数行
                score_parts = []
                if pvpScoreChange != 0:
                    score_parts.append(f"分数:{pvpScore} ({score_sign}{pvpScoreChange})")
                elif pvpScore:
                    score_parts.append(f"分数:{pvpScore}")
                if stars_str:
                    score_parts.append(stars_str)
                if score_parts:
                    msg += "  " + " | ".join(score_parts) + "\n"
                if adv_str:
                    msg += adv_str + "\n"

            messages.append(msg)
            print(msg)
            print("-" * 30)

    print(f"\n共生成 {len(messages)} 条战报消息")

if __name__ == "__main__":
    asyncio.run(main())
