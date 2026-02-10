"""
完美世界平台监控实例
监控好友的比赛状态变化，实时推送通知

参考: /Users/lintao/CS/cs-Solidarity/instances/steam_auto.py
"""

import time
import schedule
import json
from datetime import datetime
from pathlib import Path
from core import wechat_instance
from core.base_instance import BaseInstance
from perfectworld.pw_api import PerfectWorldAPI, AuthenticationError, APIRequestError


class PWMonitorAuto(BaseInstance):
    """完美世界平台监控实例"""

    def __init__(self, api: PerfectWorldAPI, wechat_groups=None,
                 monitored_friends=None, check_interval=60,
                 enable_match_start_notify=True,
                 enable_match_end_notify=True,
                 startup_message=""):
        """
        初始化监控实例

        Args:
            api: PerfectWorldAPI实例
            wechat_groups: 微信群组列表
            monitored_friends: 监控的好友列表 [{"steam_id": xxx, "nickname": "xxx"}]
            check_interval: 检查间隔（秒）
            enable_match_start_notify: 是否启用比赛开始通知
            enable_match_end_notify: 是否启用比赛结束通知
            startup_message: 启动消息
        """
        self.api = api
        self.check_interval = check_interval
        self.enable_match_start_notify = enable_match_start_notify
        self.enable_match_end_notify = enable_match_end_notify
        self.startup_message = startup_message

        # 配置接收消息的微信群/个人
        self.wechat_groups = []
        if wechat_groups:
            if isinstance(wechat_groups, list):
                self.wechat_groups = wechat_groups
            else:
                self.wechat_groups = [wechat_groups]
        else:
            self.wechat_groups = ['文件传输助手']

        # 配置监听的好友列表
        self.monitored_friends = []
        self.friend_nickname_map = {}  # 映射steam_id到nickname

        if monitored_friends:
            for friend in monitored_friends:
                if isinstance(friend, dict):
                    steam_id = str(friend.get('steam_id', ''))
                    nickname = friend.get('nickname', '未知昵称')
                    if steam_id:
                        self.monitored_friends.append(steam_id)
                        self.friend_nickname_map[steam_id] = nickname

        # 状态追踪：记录每个好友的最新比赛信息
        # {steam_id: {'latest_match_id': xxx, 'is_playing': bool, 'match_data': {}}}
        self.friend_match_status = {}

        print(f"[{datetime.now()}] PWMonitorAuto 初始化完成")
        print(f"[{datetime.now()}] 监控好友数: {len(self.monitored_friends)}")
        print(f"[{datetime.now()}] 检查间隔: {self.check_interval}秒")

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

    def get_friend_latest_match(self, steam_id: str) -> dict:
        """
        获取好友的最新比赛记录

        Args:
            steam_id: 好友的Steam ID

        Returns:
            最新比赛数据，若无比赛或出错则返回None
        """
        try:
            data = self.api.get_match_list(
                to_steam_id=int(steam_id),
                page=1,
                page_size=1
            )

            match_list = data.get("matchList", [])
            if match_list:
                return match_list[0]
            return None

        except (AuthenticationError, APIRequestError) as e:
            print(f"[{datetime.now()}] 获取 {steam_id} 的比赛记录失败: {e}")
            return None
        except Exception as e:
            print(f"[{datetime.now()}] 获取 {steam_id} 的比赛记录时发生未知错误: {e}")
            return None

    def check_match_changes(self):
        """
        检查所有监控好友的比赛状态变化
        """
        messages = []

        for steam_id in self.monitored_friends:
            try:
                nickname = self.friend_nickname_map.get(steam_id, steam_id)

                # 获取最新比赛
                latest_match = self.get_friend_latest_match(steam_id)

                if not latest_match:
                    continue

                match_id = latest_match.get("matchId")
                prev_status = self.friend_match_status.get(steam_id, {})
                prev_match_id = prev_status.get("latest_match_id")

                # 情况1: 检测到新比赛
                if match_id != prev_match_id:
                    # 判断比赛是否已结束
                    end_time_str = latest_match.get("endTime")
                    is_finished = self._is_match_finished(end_time_str)

                    if not is_finished and self.enable_match_start_notify:
                        # 新比赛开始通知
                        msg = self._format_match_start_message(nickname, latest_match)
                        messages.append(msg)

                    if is_finished and self.enable_match_end_notify:
                        # 比赛已结束通知
                        msg = self._format_match_end_message(nickname, latest_match)
                        messages.append(msg)

                    # 更新状态
                    self.friend_match_status[steam_id] = {
                        "latest_match_id": match_id,
                        "is_playing": not is_finished,
                        "match_data": latest_match
                    }

                # 情况2: 已存在的比赛，检查是否从进行中变为已结束
                elif prev_status.get("is_playing"):
                    end_time_str = latest_match.get("endTime")
                    is_finished = self._is_match_finished(end_time_str)

                    if is_finished and self.enable_match_end_notify:
                        # 比赛结束通知
                        msg = self._format_match_end_message(nickname, latest_match)
                        messages.append(msg)

                        # 更新状态
                        self.friend_match_status[steam_id]["is_playing"] = False

            except Exception as e:
                print(f"[{datetime.now()}] 检查 {steam_id} 状态时发生错误: {e}")
                continue

        # 批量发送消息
        if messages:
            combined_message = "\n\n".join(messages)
            self.send_message(combined_message)

    def _is_match_finished(self, end_time_str: str) -> bool:
        """
        判断比赛是否已结束

        Args:
            end_time_str: 比赛结束时间字符串

        Returns:
            是否已结束
        """
        if not end_time_str:
            return False

        try:
            # 解析结束时间
            end_time = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S")
            # 如果结束时间是过去的时间，则认为比赛已结束
            return end_time < datetime.now()
        except Exception:
            return False

    def _format_match_start_message(self, nickname: str, match: dict) -> str:
        """
        格式化比赛开始消息

        Args:
            nickname: 好友昵称
            match: 比赛数据

        Returns:
            格式化的消息
        """
        map_name = match.get("mapName", "未知地图")
        mode = match.get("mode", "未知模式")
        start_time = match.get("startTime", "")

        message = f"🎮 【比赛开始】\n"
        message += f"玩家：{nickname}\n"
        message += f"地图：{map_name}\n"
        message += f"模式：{mode}\n"
        message += f"时间：{start_time}"

        return message

    def _format_match_end_message(self, nickname: str, match: dict) -> str:
        """
        格式化比赛结束消息

        Args:
            nickname: 好友昵称
            match: 比赛数据

        Returns:
            格式化的消息
        """
        map_name = match.get("mapName", "未知地图")
        result = self.api.get_match_result(match)
        score = self.api.format_match_score(match)
        kill = match.get("kill", 0)
        death = match.get("death", 0)
        assist = match.get("assist", 0)
        rating = match.get("rating", 0)
        pvp_score_change = match.get("pvpScoreChange", 0)
        duration = match.get("duration", 0)

        # 根据结果选择图标
        result_icon = "✅" if result == "胜利" else "❌"

        message = f"{result_icon} 【比赛结束】\n"
        message += f"玩家：{nickname}\n"
        message += f"地图：{map_name}\n"
        message += f"结果：{result} ({score})\n"
        message += f"K/D/A：{kill}/{death}/{assist}\n"
        message += f"Rating：{rating}\n"

        if pvp_score_change != 0:
            sign = "+" if pvp_score_change > 0 else ""
            message += f"分数变化：{sign}{pvp_score_change}\n"

        message += f"时长：{duration}分钟"

        return message

    def start(self):
        """
        启动监控循环
        """
        print(f"[{datetime.now()}] PWMonitorAuto 启动")

        # 发送启动消息
        if self.startup_message:
            self.send_message(self.startup_message)

        # 初始化：立即执行一次检查
        try:
            self.check_match_changes()
        except Exception as e:
            print(f"[{datetime.now()}] 初始检查失败: {e}")

        # 设置周期性任务
        schedule.every(self.check_interval).seconds.do(self.check_match_changes)

        # 启动调度循环
        try:
            while True:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n[{datetime.now()}] PWMonitorAuto 已停止")

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
            PWMonitorAuto实例
        """
        config = PWMonitorAuto.load_config(config_path)

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
        return PWMonitorAuto(
            api=api,
            wechat_groups=config.get('wechat_groups', ['文件传输助手']),
            monitored_friends=config.get('monitored_friends', []),
            check_interval=config.get('check_interval', 60),
            enable_match_start_notify=config.get('enable_match_start_notify', True),
            enable_match_end_notify=config.get('enable_match_end_notify', True),
            startup_message=config.get('startup_message', '')
        )
