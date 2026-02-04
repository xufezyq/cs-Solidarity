from .SteamAPI import SteamAPI
import time
import schedule
import json
from datetime import datetime
from pathlib import Path
from core.wechat_instance import *
from pywechat.WechatAuto import Messages

_use_pywechat = True

class SteamAuto():
    def __init__(self, steam_api_key, steam_id, wechat_groups=None, monitored_friends=None, enable_all_friends=True, code_update_message=""):
        self.steam = SteamAPI(steam_api_key)
        self.steam_id = steam_id
        self.friend_game_status = {} # 用于追踪好友的游戏状态变化
        self.friend_daily_stats = {} # 用于统计好友今天的游玩时长 {"steamid": {"game_name": total_seconds, ...}}
        self.cached_friend_list = None # 缓存好友列表，避免频繁调用 API
        self.code_update_message = code_update_message

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
        self.friend_nickname_map = {}  # 映射steamid到nickname
        self.enable_all_friends = enable_all_friends
        
        if monitored_friends:
            # 将监听列表转换为集合，方便查询，同时构建nickname映射
            for friend in monitored_friends:
                if isinstance(friend, dict):
                    steamid = friend.get('steamid', '')
                    nickname = friend.get('nickname', friend.get('personaname', '未知昵称'))
                    self.monitored_friends.add(steamid)
                    self.friend_nickname_map[steamid] = nickname
                else:
                    steamid = str(friend)
                    self.monitored_friends.add(steamid)
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
    def save_config(config, config_path='config.json'):
        """保存配置到文件"""
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    def get_cached_friend_list(self, force_refresh=False):
        """返回缓存的好友列表；若无缓存或 force_refresh=True 则从 API 拉取并缓存"""
        if force_refresh or not self.cached_friend_list:
            try:
                self.cached_friend_list = self.steam.get_friend_list(self.steam_id)
            except Exception as e:
                print(f"[{datetime.now()}] 获取好友列表失败: {e}")
                self.cached_friend_list = None
        return self.cached_friend_list

    def invalidate_friend_list_cache(self):
        """使好友列表缓存失效，下次调用将重新拉取"""
        self.cached_friend_list = None
    
    def auto_fill_monitored_friends(self, config_path='config.json'):
        """首次执行时自动填充monitored_friends"""
        config = self.load_config(config_path)
        monitored_friends = config.get('monitored_friends', [])
        
        # 判断是否需要填充：monitored_friends为空或只有空值
        need_fill = not monitored_friends or all(
            not friend.get('steamid', '').strip() 
            for friend in monitored_friends if isinstance(friend, dict)
        )
        
        if not need_fill:
            return
        
        print(f"[{datetime.now()}] 首次执行，正在获取所有好友信息...")
        
        try:
            # 获取好友列表（使用缓存，必要时可强制刷新）
            friend_list = self.get_cached_friend_list()
            if not friend_list:
                print(f"[{datetime.now()}] 未获取到好友列表")
                return
            
            # 获取好友的详细信息
            friend_ids = [friend["steamid"] for friend in friend_list]
            friend_ids.append(self.steam_id)  # 把自己的状态也添加进去
            friend_status_list = self.steam.get_friend_status(friend_ids)
            
            if not friend_status_list:
                print(f"[{datetime.now()}] 未获取到好友详细信息")
                return
            
            # 构建好友列表配置
            friends_config = []
            for friend in friend_status_list:
                friends_config.append({
                    "steamid": friend.get('steamid', ''),
                    "personaname": friend.get('personaname', '未知昵称'),
                    "nickname": friend.get('personaname', '未知昵称')
                })
            
            # 更新配置
            config['monitored_friends'] = friends_config
            config['enable_all_friends'] = False  # 自动填充后改为false
            
            # 保存配置
            self.save_config(config, config_path)
            
            print(f"[{datetime.now()}] 成功填充 {len(friends_config)} 位好友的信息到配置文件")
            for friend in friends_config:
                print(f"  - {friend['nickname']} ({friend['steamid']})")
            
        except Exception as e:
            print(f"[{datetime.now()}] 自动填充好友信息失败: {e}")
    
    @staticmethod
    def create_from_config(config_path='config.json'):
        """从配置文件创建 SteamAuto 实例"""
        config = SteamAuto.load_config(config_path)

        # 创建临时实例用于自动填充
        temp_instance = SteamAuto(
            steam_api_key=config.get('steam_api_key'),
            steam_id=config.get('steam_id'),
            wechat_groups=config.get('wechat_groups', ['文件传输助手']),
            monitored_friends=config.get('monitored_friends', []),
            enable_all_friends=config.get('enable_all_friends', True)
        )
        
        # 首次执行发生一次消息
        temp_instance.send_message(config.get('code_update_message', ''))
        
        # 首次执行时且好友信息为空，自动填充好友信息
        temp_instance.auto_fill_monitored_friends(config_path)
        
        # 重新加载配置（可能已被更新）
        config = SteamAuto.load_config(config_path)
        
        # 显示配置信息
        print("=" * 50)
        print("配置信息：")
        print(f"配置文件: {config_path}")
        print(f"WeChat 群组/个人数量: {len(config.get('wechat_groups', ['文件传输助手']))}")
        for idx, group in enumerate(config.get('wechat_groups', ['文件传输助手']), 1):
            print(f"  {idx}. {group}")
        print(f"监听全部好友: {config.get('enable_all_friends', True)}")
        if not config.get('enable_all_friends', True):
            print(f"监听的好友数量: {len(config.get('monitored_friends', []))}")
        print("=" * 50)

        # 创建最终实例
        return SteamAuto(
            steam_api_key=config.get('steam_api_key'),
            steam_id=config.get('steam_id'),
            wechat_groups=config.get('wechat_groups', ['文件传输助手']),
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
                if is_using_wxauto():
                    get_wechat().SendMsg(message, group)
                else:
                    Messages.send_messages_to_friend(friend=group, messages=[message], delay=0.2, tickle=False, search_pages=0)

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
        friend_list = self.get_cached_friend_list()
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
        friend_steam_ids.append(self.steam_id)  # 把自己的状态也添加进去
        friend_status_list = self.steam.get_friend_status(friend_steam_ids)
        return friend_status_list

    def check_status_changes(self):
        """检查好友游戏状态变化，并累计今日游玩时长"""
        friend_status_list = self.get_steam_friend_status()
        
        if not friend_status_list:
            return
        # 收集本次检查产生的所有通知，最后一次性发送
        messages = []

        for friend in friend_status_list:
            steam_id = friend.get('steamid')
            # 从config中的nickname_map获取昵称，如果没有则使用personaname
            nickname = self.friend_nickname_map.get(steam_id, friend.get('personaname', '未知昵称'))
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
                
                # 累计今日游玩时长
                if steam_id not in self.friend_daily_stats:
                    self.friend_daily_stats[steam_id] = {'nickname': nickname, 'games': {}}
                
                if prev_game_name not in self.friend_daily_stats[steam_id]['games']:
                    self.friend_daily_stats[steam_id]['games'][prev_game_name] = 0
                
                self.friend_daily_stats[steam_id]['games'][prev_game_name] += duration
                
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

    def get_friend_game_stats(self):
        """获取好友今天的游玩统计信息"""
        if not self.friend_daily_stats:
            return None
        
        return self.friend_daily_stats

    def format_game_stats_message(self, stats_data):
        """格式化今日游玩统计信息为消息字符串"""
        if not stats_data:
            return "今日还没有好友游玩记录"
        
        today = datetime.now().strftime("%Y年%m月%d日")
        message = f"📊 【好友今日游玩统计 - {today}】\n\n"
        
        for steam_id, friend_data in stats_data.items():
            nickname = friend_data.get('nickname', '未知昵称')
            games = friend_data.get('games', {})
            
            message += f"👤 {nickname}:\n"
            
            if not games:
                message += "  暂无游玩记录\n"
            else:
                # 按游玩时间排序
                sorted_games = sorted(games.items(), key=lambda x: x[1], reverse=True)
                
                total_time = sum(games.values())
                
                for idx, (game_name, duration) in enumerate(sorted_games, 1):
                    time_str = self.format_duration(duration)
                    message += f"  {idx}. {game_name}: {time_str}\n"
                
                total_time_str = self.format_duration(total_time)
                message += f"  📈 今日总计: {total_time_str}\n"
            
            message += "\n"
        
        return message

    def reset_daily_stats(self):
        """重置每日游玩统计（在每天0点调用）"""
        print(f"[{datetime.now()}] 重置每日游玩统计")
        self.friend_daily_stats = {}

    def send_daily_stats(self):
        """发送每日游玩统计"""
        print(f"[{datetime.now()}] 执行每日统计任务...")
        try:
            stats_data = self.get_friend_game_stats()
            if stats_data:
                message = self.format_game_stats_message(stats_data)
                self.send_message(message)
                # 统计发送完毕后，重置计数器
                self.reset_daily_stats()
            else:
                print(f"[{datetime.now()}] 今日无游玩记录")
        except Exception as e:
            print(f"[{datetime.now()}] 发送每日统计失败: {e}")

    def daily_update_tasks(self):
        """封装每天 00:00 需要执行的任务集合。

        包含：发送每日统计、清理/刷新需要每天更新的缓存或计数器等。
        如需添加其他每日任务，可在此处扩展。
        """
        print(f"[{datetime.now()}] 执行每日更新任务...")
        try:
            # 发送并重置每日统计（内部已包含重置逻辑）
            self.send_daily_stats()
        except Exception as e:
            print(f"[{datetime.now()}] 执行 send_daily_stats 失败: {e}")

        try:
            # 每天刷新好友列表缓存，确保次日拉取到最新好友变更
            self.invalidate_friend_list_cache()
            print(f"[{datetime.now()}] 好友列表缓存已失效，将在下一次访问时刷新")
        except Exception as e:
            print(f"[{datetime.now()}] 清理好友列表缓存失败: {e}")

    def start(self, check_interval=60):
        """
        启动定时检查
        :param check_interval: 检查间隔（秒），默认60秒
        """
        print(f"[{datetime.now()}] 程序启动，将每 {check_interval} 秒检查一次好友游戏状态")
        print(f"[{datetime.now()}] 目标Steam ID: {self.steam_id}")
        print(f"[{datetime.now()}] 每天 00:00 将发送好友游玩统计")
        
        # 初始化一次，获取当前状态
        self.check_status_changes()
        
        # 设置定时任务：每60秒检查一次好友游戏状态变化
        schedule.every(check_interval).seconds.do(self.check_status_changes)
        
        # 设置每日定时任务：每天0点执行封装的每日更新任务
        schedule.every().day.at("00:00").do(self.daily_update_tasks)
        
        try:
            while True:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n[{datetime.now()}] 程序已停止")
