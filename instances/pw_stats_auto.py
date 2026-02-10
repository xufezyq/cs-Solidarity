"""
完美世界平台战绩统计实例
定时推送玩家战绩统计报告

参考: /Users/lintao/CS/cs-Solidarity/instances/daily_auto.py
"""

import time
import schedule
import json
from datetime import datetime
from pathlib import Path
from core import wechat_instance
from core.base_instance import BaseInstance
from perfectworld.pw_api import PerfectWorldAPI, AuthenticationError, APIRequestError


class PWStatsAuto(BaseInstance):
    """完美世界平台战绩统计实例"""

    def __init__(self, api: PerfectWorldAPI, wechat_groups=None,
                 target_players=None, send_times=None,
                 include_recent_matches=5,
                 include_hot_maps=True,
                 include_hot_weapons=True):
        """
        初始化战绩统计实例

        Args:
            api: PerfectWorldAPI实例
            wechat_groups: 微信群组列表
            target_players: 目标玩家列表 [{"steam_id": xxx, "nickname": "xxx"}]
            send_times: 发送时间列表 ["08:00", "20:00"]
            include_recent_matches: 包含最近N场比赛
            include_hot_maps: 是否包含常用地图统计
            include_hot_weapons: 是否包含常用武器统计
        """
        self.api = api
        self.include_recent_matches = include_recent_matches
        self.include_hot_maps = include_hot_maps
        self.include_hot_weapons = include_hot_weapons

        # 配置接收消息的微信群/个人
        self.wechat_groups = []
        if wechat_groups:
            if isinstance(wechat_groups, list):
                self.wechat_groups = wechat_groups
            else:
                self.wechat_groups = [wechat_groups]
        else:
            self.wechat_groups = ['文件传输助手']

        # 配置目标玩家列表
        self.target_players = []
        self.player_nickname_map = {}  # 映射steam_id到nickname

        if target_players:
            for player in target_players:
                if isinstance(player, dict):
                    steam_id = str(player.get('steam_id', ''))
                    nickname = player.get('nickname', '未知玩家')
                    if steam_id:
                        self.target_players.append(steam_id)
                        self.player_nickname_map[steam_id] = nickname

        # 配置发送时间
        self.send_times = send_times if send_times else ["08:00"]

        print(f"[{datetime.now()}] PWStatsAuto 初始化完成")
        print(f"[{datetime.now()}] 目标玩家数: {len(self.target_players)}")
        print(f"[{datetime.now()}] 发送时间: {', '.join(self.send_times)}")

    def send_message(self, message):
        """
        发送消息（会被主程序替换为入队函数）

        Args:
            message: 消息内容
        """
        if not message or not message.strip():
            return

        for group in self.wechat_groups:
            try:
                wechat_instance.send_message(message, group)
                print(f"[{datetime.now()}] 消息已发送到: {group}")
            except Exception as e:
                print(f"[{datetime.now()}] 发送消息到 {group} 失败: {e}")

    def generate_stats_report(self, steam_id: str) -> str:
        """
        生成玩家的战绩统计报告

        Args:
            steam_id: 玩家的Steam ID

        Returns:
            格式化的报告文本
        """
        try:
            nickname = self.player_nickname_map.get(steam_id, steam_id)

            # 获取玩家统计数据
            stats = self.api.get_player_stats(to_steam_id=int(steam_id))

            if not stats:
                return f"无法获取玩家 {nickname} 的数据"

            # 构建报告
            report = f"📊 【完美平台战绩报告】\n\n"
            report += f"玩家：{stats.get('name', nickname)}\n"
            report += f"赛季：{stats.get('seasonId', 'N/A')}\n"
            report += f"评价：{stats.get('summary', '')}\n\n"

            # 总体数据
            report += f"🎯 总体数据\n"
            report += f"Rating: {stats.get('rating', 0)} | K/D: {stats.get('kd', 0)}\n"
            win_rate = stats.get('winRate', 0) * 100
            report += f"胜率: {win_rate:.1f}% | 场次: {stats.get('cnt', 0)}场\n"
            report += f"场均伤害: {stats.get('adr', 0)} | MVP: {stats.get('mvpCount', 0)}次\n"
            report += f"爆头率: {stats.get('headShotRatio', 0) * 100:.1f}%\n\n"

            # 残局能力
            vs1_win_rate = stats.get('vs1WinRate', 0)
            if vs1_win_rate:
                report += f"💪 残局能力\n"
                report += f"1v1: {stats.get('vs1', 0)}次 | 胜率: {vs1_win_rate * 100:.1f}%\n"
                report += f"1v2: {stats.get('vs2', 0)}次 | "
                report += f"1v3: {stats.get('vs3', 0)}次\n\n"

            # 近期表现
            if self.include_recent_matches:
                recent_matches = self._get_recent_matches(steam_id)
                if recent_matches:
                    report += f"📈 近期表现（最近{len(recent_matches)}场）\n"
                    for i, match in enumerate(recent_matches, 1):
                        result = self.api.get_match_result(match)
                        result_icon = "✅" if result == "胜利" else "❌"
                        score = self.api.format_match_score(match)
                        kda = f"{match.get('kill', 0)}/{match.get('death', 0)}/{match.get('assist', 0)}"
                        rating = match.get('rating', 0)
                        map_name = match.get('mapName', '未知')
                        report += f"{i}. {result_icon} {map_name} ({score})\n"
                        report += f"   K/D/A: {kda} | Rating: {rating}\n"
                    report += "\n"

            # 常用地图
            if self.include_hot_maps:
                hot_maps = stats.get('hotMaps', [])
                if hot_maps:
                    report += f"🗺️ 常用地图（前3）\n"
                    for i, map_data in enumerate(hot_maps[:3], 1):
                        map_name = map_data.get('mapName', '未知')
                        total_match = map_data.get('totalMatch', 0)
                        win_count = map_data.get('winCount', 0)
                        map_win_rate = (win_count / total_match * 100) if total_match > 0 else 0
                        report += f"{i}. {map_name}: {total_match}场 | 胜率: {map_win_rate:.1f}%\n"
                    report += "\n"

            # 常用武器
            if self.include_hot_weapons:
                hot_weapons = stats.get('hotWeapons', [])
                if hot_weapons:
                    report += f"🔫 常用武器（前3）\n"
                    for i, weapon in enumerate(hot_weapons[:3], 1):
                        weapon_name = weapon.get('weaponName', '未知')
                        kills = weapon.get('weaponKill', 0)
                        headshots = weapon.get('weaponHeadShot', 0)
                        hs_rate = (headshots / kills * 100) if kills > 0 else 0
                        report += f"{i}. {weapon_name}: {kills}击杀 | 爆头率: {hs_rate:.1f}%\n"

            report += f"\n⏰ 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

            return report

        except (AuthenticationError, APIRequestError) as e:
            error_msg = f"获取玩家 {self.player_nickname_map.get(steam_id, steam_id)} 的数据失败: {e}"
            print(f"[{datetime.now()}] {error_msg}")
            return error_msg
        except Exception as e:
            error_msg = f"生成报告时发生未知错误: {e}"
            print(f"[{datetime.now()}] {error_msg}")
            return error_msg

    def _get_recent_matches(self, steam_id: str) -> list:
        """
        获取最近N场比赛

        Args:
            steam_id: 玩家的Steam ID

        Returns:
            比赛列表
        """
        try:
            data = self.api.get_match_list(
                to_steam_id=int(steam_id),
                page=1,
                page_size=self.include_recent_matches
            )
            return data.get("matchList", [])
        except Exception as e:
            print(f"[{datetime.now()}] 获取最近比赛失败: {e}")
            return []

    def send_all_stats(self):
        """发送所有目标玩家的战绩统计"""
        print(f"[{datetime.now()}] 开始生成战绩报告...")

        for steam_id in self.target_players:
            try:
                report = self.generate_stats_report(steam_id)
                self.send_message(report)
                # 避免频繁请求，每个玩家之间间隔2秒
                time.sleep(2)
            except Exception as e:
                print(f"[{datetime.now()}] 处理玩家 {steam_id} 时发生错误: {e}")

        print(f"[{datetime.now()}] 战绩报告发送完成")

    def start(self):
        """
        启动定时任务
        """
        print(f"[{datetime.now()}] PWStatsAuto 启动")
        print(f"[{datetime.now()}] 计划每天 {', '.join(self.send_times)} 发送战绩报告")

        # 创建独立的调度器
        scheduler = schedule.Scheduler()

        # 为每个发送时间创建定时任务
        for send_time in self.send_times:
            scheduler.every().day.at(send_time).do(self.send_all_stats)

        # 调度循环
        try:
            while True:
                scheduler.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n[{datetime.now()}] PWStatsAuto 已停止")

    @staticmethod
    def load_config(config_path):
        """从配置文件加载配置"""
        if not Path(config_path).exists():
            raise FileNotFoundError(f"配置文件 {config_path} 不存在")

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        return config

    @staticmethod
    def create_from_config(config_path):
        """
        工厂方法：从配置文件创建实例

        Args:
            config_path: 配置文件路径

        Returns:
            PWStatsAuto实例
        """
        config = PWStatsAuto.load_config(config_path)

        # 初始化API
        api = PerfectWorldAPI(verify_ssl=False)

        # 获取token文件路径
        token_file = config.get('token_file', 'config/perfectworld/token.json')

        # 尝试加载token
        token_loaded = api.load_token_from_file(token_file)

        if not token_loaded:
            # 如果没有token，尝试登录
            mobile_phone = config.get('mobile_phone')
            security_code = config.get('security_code')

            if not mobile_phone or not security_code:
                raise ValueError(
                    f"未找到token文件 {token_file}，且配置中没有提供 mobile_phone 和 security_code。\n"
                    "首次使用请在配置文件中提供这两个参数以完成登录。"
                )

            print(f"[{datetime.now()}] 首次使用，正在登录...")
            try:
                api.login(mobile_phone, security_code)
                # 保存token
                api.save_token_to_file(token_file)
            except AuthenticationError as e:
                raise ValueError(f"登录失败: {e}")

        # 创建实例
        return PWStatsAuto(
            api=api,
            wechat_groups=config.get('wechat_groups', ['文件传输助手']),
            target_players=config.get('target_players', []),
            send_times=config.get('send_times', ["08:00"]),
            include_recent_matches=config.get('include_recent_matches', 5),
            include_hot_maps=config.get('include_hot_maps', True),
            include_hot_weapons=config.get('include_hot_weapons', True)
        )
