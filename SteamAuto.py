import SteamAPI
import time
import schedule
import json
from datetime import datetime
from wxauto import WeChat
from pathlib import Path

class SteamAuto():
    def __init__(self, steam_api_key, steam_id, wechat_groups=None, monitored_friends=None, enable_all_friends=True):
        self.steam = SteamAPI.SteamAPI(steam_api_key)
        self.steam_id = steam_id
        self.wx = WeChat()
        self.friend_game_status = {} # 用于追踪好友的游戏状态变化
        
        # 配置接收消息的微信群/个人
        self.wechat_groups = []
        if wechat_groups:
            if isinstance(wechat_groups, list):
                self.wechat_groups = wechat_groups
            else:
                self.wechat_groups = [wechat_groups]
        else:
            self.wechat_groups = ['【CS】团结友爱']
        
        # 配置监听的好友列表
        self.monitored_friends = set()
        self.enable_all_friends = enable_all_friends
        
        if monitored_friends:
            # 将监听列表转换为集合，方便查询
            for friend in monitored_friends:
                if isinstance(friend, dict):
                    self.monitored_friends.add(friend.get('steamid', ''))
                else:
                    self.monitored_friends.add(str(friend))
            # 移除空字符串
            self.monitored_friends.discard('')
    
    @staticmethod
    def load_config(config_path='config.json'):
        """从配置文件加载配置"""
        if not Path(config_path).exists():
            raise FileNotFoundError(f"配置文件 {config_path} 不存在")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        return config
    
    @staticmethod
    def create_from_config(config_path='config.json'):
        """从配置文件创建 SteamAuto 实例"""
        config = SteamAuto.load_config(config_path)
        
        # 支持新旧配置格式兼容
        wechat_groups = config.get('wechat_groups')
        if not wechat_groups:
            # 如果没有 wechat_groups，尝试使用旧的 wechat_group
            old_group = config.get('wechat_group')
            wechat_groups = [old_group] if old_group else ['【CS】团结友爱']
        
        return SteamAuto(
            steam_api_key=config.get('steam_api_key'),
            steam_id=config.get('steam_id'),
            wechat_groups=wechat_groups,
            monitored_friends=config.get('monitored_friends', []),
            enable_all_friends=config.get('enable_all_friends', True)
        )

    def send_message(self, message):
        """
        发送消息到所有配置的微信群/个人
        :param message: 要发送的消息内容
        """
        if not message or not message.strip():
            return
        
        for group in self.wechat_groups:
            try:
                self.wx.SendMsg(message, group)
                print(f"[{datetime.now()}] 消息已发送到: {group}")
            except Exception as e:
                print(f"[{datetime.now()}] 发送消息到 {group} 失败: {e}")
    
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
        
        # 如果启用了所有好友监听，则监听全部；否则只监听指定的好友
        if self.enable_all_friends:
            friend_steam_ids = [friend["steamid"] for friend in friend_list]
        else:
            friend_steam_ids = [friend["steamid"] for friend in friend_list if friend["steamid"] in self.monitored_friends]
        
        if not friend_steam_ids:
            print(f"[{datetime.now()}] 没有要监听的好友")
            return []
        
        print(f"[{datetime.now()}] 正在检查 {len(friend_steam_ids)} 位好友的状态...")
        
        # 批量查询好友状态
        friend_status_list = self.steam.get_friend_status(friend_steam_ids)
        return friend_status_list

    def check_status_changes(self):
        """检查好友游戏状态变化"""
        friend_status_list = self.get_steam_friend_status()
        
        if not friend_status_list:
            return
        # 收集本次检查产生的所有通知，最后一次性发送
        messages = []

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
                # 先收集，后面统一发送
                messages.append(message)
                
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
                # 先收集，后面统一发送
                messages.append(message)
                
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

        # 如果有需要通知的消息，一次性合并并发送
        if messages:
            combined = "\n".join(messages)
            print(f"[{datetime.now()}] 发送合并消息：\n{combined}")
            self.send_message(combined)

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
