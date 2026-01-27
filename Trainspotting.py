import SteamAPI
import WeChatRobot
import time
import schedule
from datetime import datetime

class Trainspotting():
    def __init__(self, steam_api_key, steam_id, wechat_webhook_key):
        self.steam = SteamAPI.SteamAPI(steam_api_key)
        self.steam_id = steam_id
        self.wechat_robot = WeChatRobot.WeChatRobot(wechat_webhook_key)
        # 用于追踪好友的游戏状态变化
        self.friend_game_status = {}

    def format_duration(self, seconds):
        """将秒数格式化为可读的时间格式"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        
        if hours > 0:
            return f"{hours}小时{minutes}分钟{secs}秒"
        elif minutes > 0:
            return f"{minutes}分钟{secs}秒"
        else:
            return f"{secs}秒"

    def get_steam_friend_status(self):
        """获取Steam好友列表及其游戏状态"""
        friend_list = self.steam.get_friend_list(self.steam_id)
        if not friend_list:
            print(f"[{datetime.now()}] 未获取到好友列表")
            return []
        
        friend_steam_ids = [friend["steamid"] for friend in friend_list]
        print(f"[{datetime.now()}] 正在检查 {len(friend_steam_ids)} 位好友的状态...")
        
        # 批量查询好友状态
        friend_status_list = self.steam.get_friend_status(friend_steam_ids)
        return friend_status_list

    def check_status_changes(self):
        """检查好友游戏状态变化"""
        friend_status_list = self.get_steam_friend_status()
        
        if not friend_status_list:
            return
        
        for friend in friend_status_list:
            steam_id = friend.get('steamid')
            nickname = friend.get('personaname', '未知昵称')
            game_id = friend.get('gameid', None)
            game_name = friend.get('gameextrainfo', '未游玩游戏')
            personastate = friend.get('personastate', 0)  # 0: 离线, 1: 在线, 2: 忙碌, 3: 离开, 4: 暂离, 5: 求交易, 6: 求组队
            
            # 获取该好友的上一次状态
            prev_game_id = self.friend_game_status.get(steam_id, {}).get('gameid')
            prev_game_name = self.friend_game_status.get(steam_id, {}).get('game_name')
            prev_start_time = self.friend_game_status.get(steam_id, {}).get('start_time')
            
            current_time = time.time()
            
            # 检查游戏状态变化：从无游戏变为有游戏
            if game_id and game_id != '0' and prev_game_id != game_id:
                # 状态发生变化，发送通知
                message = f"🎮 好友 {nickname} 开始游玩 {game_name} 了！"
                print(f"[{datetime.now()}] {message}")
                self.wechat_robot.send_message(message)
                
                # 保存当前状态及开始时间
                self.friend_game_status[steam_id] = {
                    'gameid': game_id,
                    'game_name': game_name,
                    'personastate': personastate,
                    'nickname': nickname,
                    'start_time': current_time
                }
            
            # 检查游戏状态变化：从有游戏变为无游戏
            elif (not game_id or game_id == '0') and prev_game_id and prev_game_id != '0':
                # 计算游玩时长
                duration = current_time - prev_start_time if prev_start_time else 0
                duration_str = self.format_duration(duration)
                
                message = f"👋 好友 {nickname} 停止了游戏 {prev_game_name}，游玩时长：{duration_str}。"
                print(f"[{datetime.now()}] {message}")
                self.wechat_robot.send_message(message)
                
                # 保存当前状态（无游戏）
                self.friend_game_status[steam_id] = {
                    'gameid': game_id,
                    'game_name': game_name,
                    'personastate': personastate,
                    'nickname': nickname,
                    'start_time': None
                }
            
            # 保存状态（其他情况）
            if steam_id not in self.friend_game_status:
                self.friend_game_status[steam_id] = {
                    'gameid': game_id,
                    'game_name': game_name,
                    'personastate': personastate,
                    'nickname': nickname,
                    'start_time': current_time if (game_id and game_id != '0') else None
                }

    def start(self, check_interval=60):
        """
        启动定时检查
        :param check_interval: 检查间隔（秒），默认60秒
        """
        print(f"[{datetime.now()}] 程序启动，将每 {check_interval} 秒检查一次好友游戏状态")
        print(f"[{datetime.now()}] 目标Steam ID: {self.steam_id}\n")
        
        # 初始化一次，获取当前状态
        self.check_status_changes()
        
        # 设置定时任务
        schedule.every(check_interval).seconds.do(self.check_status_changes)
        
        try:
            while True:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n[{datetime.now()}] 程序已停止")
