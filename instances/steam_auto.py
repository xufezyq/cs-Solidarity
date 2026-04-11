from steam.SteamAPI import SteamAPI
import time
import schedule
import json
import asyncio
import threading
from datetime import datetime
from pathlib import Path
from core import wechat_instance
from core.base_instance import BaseInstance
from cs2_pw.request import PerfectWorldApi
import logging
from dotenv import load_dotenv
import os

# 加载 .env 文件
load_dotenv()

log = logging.getLogger(__name__)

# 导入版本信息
try:
    from version import VERSION
    APP_VERSION = VERSION
except ImportError:
    APP_VERSION = "1.0.0"

# 配置文件读写锁，防止后台线程和 Web 面板同时写入导致损坏
_config_lock = threading.Lock()

class SteamAuto(BaseInstance):
    def __init__(self, steam_api_key=None, steam_id=None, wechat_groups=None, monitored_friends=None, enable_all_friends=True, code_update_message="", check_interval=60, perfect_world_config=None, check_news_interval=3600, enable_news_check=True, friend_pw_history_stats=None, config_path='config.json', debug=False):
        # 优先从环境变量读取配置
        self.steam_api_key = steam_api_key or os.getenv('STEAM_API_KEY')
        self.steam_id = steam_id or os.getenv('STEAM_ID')
        
        self.steam = SteamAPI(self.steam_api_key)
        self.config_path = config_path # 保存配置文件路径
        self.debug = debug  # 调试模式标志
        self.friend_game_status = {} # 用于追踪好友的游戏状态变化
        self.friend_daily_stats = {} # 用于统计好友今天的游玩时长 {"steamid": {"game_name": total_seconds, ...}}
        self.friend_pw_daily_stats = {} # 用于统计好友今天的完美平台战绩 {"steamid": {"matches": [], "wins": 0, "losses": 0, "draws": 0, "total_score_change": 0, "total_kills": 0, "total_deaths": 0, "total_assists": 0, "total_rating": 0, "total_pw_rating": 0, "total_we": 0, "match_count": 0}}
        self.friend_pw_history_stats = friend_pw_history_stats or {} # 用于统计好友的历史最佳战绩 {"steamid": {"max_kills": 0, "min_kills": 999, ...}}
        self.friend_pw_leaderboard = {}  # 当前排行榜持有者 {"category": {"steamid": ..., "pw_nickname": ..., "value": ...}}
        self.cached_friend_list = None # 缓存好友列表，避免频繁调用 API
        self.code_update_message = code_update_message
        self.check_interval = check_interval
        
        # 新闻检查相关
        self.enable_news_check = enable_news_check
        self.check_news_interval = check_news_interval  # 新闻检查间隔（秒），默认 1 小时
        # cached_news_titles 将在 check_cs2_news 中首次使用时初始化
        
        # 完美平台配置
        self.perfect_world_config = perfect_world_config or {}
        self.pw_uid = self.perfect_world_config.get('uid') or os.getenv('PW_UID')
        self.pw_token = self.perfect_world_config.get('token') or os.getenv('PW_TOKEN')
        self.pw_api = None
        if self.pw_uid and self.pw_token:
            self.pw_api = PerfectWorldApi(uid=self.pw_uid, token=self.pw_token)

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
        self.friend_pw_nickname_map = {}  # 映射 steamid 到 pw_nickname
        self.enable_all_friends = enable_all_friends

        if monitored_friends:
            # 将监听列表转换为集合，方便查询，同时构建映射
            for friend in monitored_friends:
                if isinstance(friend, dict):
                    steamid = friend.get('steamid', '')
                    pw_nickname = friend.get('pw_nickname', friend.get('personaname', '未知昵称'))

                    self.monitored_friends.add(steamid)
                    self.friend_pw_nickname_map[steamid] = pw_nickname
                else:
                    steamid = str(friend)
                    self.monitored_friends.add(steamid)
            # 移除空字符串
            self.monitored_friends.discard('')
    
    @staticmethod
    def load_config(config_path='config.json'):
        """从配置文件加载配置（线程安全）"""
        if not Path(config_path).exists():
            raise FileNotFoundError(f"配置文件 {config_path} 不存在")

        with _config_lock:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

        return config

    @staticmethod
    def save_config(config, config_path='config.json'):
        """保存配置到文件（线程安全）"""
        with _config_lock:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _run_async_safe(coro):
        """安全地运行异步协程，兼容已有事件循环的情况"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # 已有事件循环在运行，用新线程执行
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        else:
            return asyncio.run(coro)

    def get_cached_friend_list(self, force_refresh=False):
        """返回缓存的好友列表；若无缓存或 force_refresh=True 则从 API 拉取并缓存"""
        if force_refresh or not self.cached_friend_list:
            try:
                self.cached_friend_list = self.steam.get_friend_list(self.steam_id)
            except Exception as e:
                log.info(f"[{datetime.now()}] 获取好友列表失败: {e}")
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
        
        log.info(f"[{datetime.now()}] 首次执行，正在获取所有好友信息...")
        
        try:
            # 获取好友列表（使用缓存，必要时可强制刷新）
            friend_list = self.get_cached_friend_list()
            if not friend_list:
                log.info(f"[{datetime.now()}] 未获取到好友列表")
                return
            
            # 获取好友的详细信息
            friend_ids = [friend["steamid"] for friend in friend_list]
            friend_ids.append(self.steam_id)  # 把自己的状态也添加进去
            friend_status_list = self.steam.get_friend_status(friend_ids)
            
            if not friend_status_list:
                log.info(f"[{datetime.now()}] 未获取到好友详细信息")
                return
            
            # 构建好友列表配置
            friends_config = []
            for friend in friend_status_list:
                friends_config.append({
                    "steamid": friend.get('steamid', ''),
                    "personaname": friend.get('personaname', '未知昵称'),
                    "pw_nickname": friend.get('personaname', '未知昵称')
                })
            
            # 更新配置
            config['monitored_friends'] = friends_config
            config['enable_all_friends'] = False  # 自动填充后改为false
            
            # 保存配置
            self.save_config(config, config_path)
            
            log.info(f"[{datetime.now()}] 成功填充 {len(friends_config)} 位好友的信息到配置文件")
            for friend in friends_config:
                log.debug(f"  - {friend['pw_nickname']} ({friend['steamid']})")
            
        except Exception as e:
            log.info(f"[{datetime.now()}] 自动填充好友信息失败: {e}")
    
    @staticmethod
    def create_from_config(config_path='config.json'):
        """从配置文件创建 SteamAuto 实例"""
        config = SteamAuto.load_config(config_path)

        # 读取主配置文件的 debug_mode（从实例配置路径推导主配置位置）
        try:
            cfg_path = Path(config_path)
            if cfg_path.parent.name == 'instconfig':
                main_cfg_path = cfg_path.parent.parent / 'config.json'
            else:
                main_cfg_path = cfg_path.parent / 'config.json'
            with open(main_cfg_path, 'r', encoding='utf-8') as f:
                master_config = json.load(f)
                debug_mode = master_config.get('debug_mode', False)
        except Exception:
            debug_mode = False

        # 从环境变量读取敏感信息
        steam_api_key = os.getenv('STEAM_API_KEY') or config.get('steam_api_key')
        steam_id = os.getenv('STEAM_ID') or config.get('steam_id')
        
        # 完美平台配置
        perfect_world_config = config.get('perfect_world_config', {})
        perfect_world_config['uid'] = os.getenv('PW_UID') or perfect_world_config.get('uid')
        perfect_world_config['token'] = os.getenv('PW_TOKEN') or perfect_world_config.get('token')

        # 创建临时实例用于自动填充
        temp_instance = SteamAuto(
            steam_api_key=steam_api_key,
            steam_id=steam_id,
            wechat_groups=config.get('wechat_groups', ['文件传输助手']),
            monitored_friends=config.get('monitored_friends', []),
            enable_all_friends=config.get('enable_all_friends', True),
            code_update_message=config.get('code_update_message', ''),
            check_interval=config.get('check_interval', 60),
            perfect_world_config=perfect_world_config,
            check_news_interval=config.get('check_news_interval', 3600),
            enable_news_check=config.get('enable_news_check', True),
            config_path=config_path
        )
        
        # 首次执行时且好友信息为空，自动填充好友信息
        # 注意：这会修改配置文件，是首次运行的一次性副作用
        temp_instance.auto_fill_monitored_friends(config_path)
        
        # 重新加载配置（可能已被更新）
        config = SteamAuto.load_config(config_path)
        
        # 显示配置信息
        log.debug("=" * 50)
        log.debug("配置信息：")
        log.debug(f"配置文件: {config_path}")
        log.debug(f"WeChat 群组/个人数量: {len(config.get('wechat_groups', ['文件传输助手']))}")
        for idx, group in enumerate(config.get('wechat_groups', ['文件传输助手']), 1):
            log.debug(f"  {idx}. {group}")
        log.debug(f"监听全部好友: {config.get('enable_all_friends', True)}")
        if not config.get('enable_all_friends', True):
            log.debug(f"监听的好友数量: {len(config.get('monitored_friends', []))}")
        if config.get('perfect_world_config'):
             log.debug(f"完美平台配置已启用: UID={config['perfect_world_config'].get('uid')}")
        else:
             log.debug("完美平台配置未启用")
        if config.get('friend_pw_history_stats'):
            log.debug(f"历史战绩统计已加载: {len(config['friend_pw_history_stats'])} 位好友")
        log.debug("=" * 50)

        # 创建最终实例
        instance = SteamAuto(
            steam_api_key=steam_api_key,
            steam_id=steam_id,
            wechat_groups=config.get('wechat_groups', ['文件传输助手']),
            monitored_friends=config.get('monitored_friends', []),
            enable_all_friends=config.get('enable_all_friends', True),
            code_update_message=config.get('code_update_message', ''),
            check_interval=config.get('check_interval', 60),
            perfect_world_config=perfect_world_config,
            check_news_interval=config.get('check_news_interval', 3600),
            enable_news_check=config.get('enable_news_check', True),
            friend_pw_history_stats=config.get('friend_pw_history_stats'),
            config_path=config_path,
            debug=debug_mode
        )
        # 加载已保存的排行榜数据
        instance.friend_pw_leaderboard = config.get('friend_pw_leaderboard', {})
        return instance

    def send_message(self, message):
        """
        发送消息到所有配置的微信群/个人
        :param message: 要发送的消息内容
        """
        if not message or not message.strip():
            return
        
        for group in self.wechat_groups:
            try:
                wechat_instance.send_message(message, group)
                log.info(f"[{datetime.now()}] 消息已发送到: {group}")
            except Exception as e:
                log.info(f"[{datetime.now()}] 发送消息到 {group} 失败: {e}")
    
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
            log.info(f"[{datetime.now()}] 未获取到好友列表")
            return []
        
        # 如果启用了所有好友监听，则监听全部；否则只监听指定的好友
        if self.enable_all_friends:
            friend_steam_ids = [friend["steamid"] for friend in friend_list]
        else:
            friend_steam_ids = [friend["steamid"] for friend in friend_list if friend["steamid"] in self.monitored_friends]
        
        if not friend_steam_ids:
            log.info(f"[{datetime.now()}] 没有要监听的好友")
            return []
        
        log.info(f"[{datetime.now()}] 正在检查 {len(friend_steam_ids)} 位好友的状态...")
        
        # 批量查询好友状态
        friend_steam_ids.append(self.steam_id)  # 把自己的状态也添加进去
        friend_status_list = self.steam.get_friend_status(friend_steam_ids)
        return friend_status_list

    def check_cs2_news(self):
        """检查 CS2 是否有新新闻，如果有则发送通知"""
        if not self.enable_news_check:
            return
        
        # 维护时间检查
        try:
            from core import check_maintenance
            if check_maintenance():
                log.info(f"[{datetime.now()}] 当前在维护时段，跳过新闻检查")
                return
        except (ImportError, AttributeError):
            pass
        
        try:
            # 获取最新 5 条新闻
            news_items = self.steam.get_steam_news(app_id=730, count=5)
            
            if not news_items or len(news_items) == 0:
                log.info(f"[{datetime.now()}] 未获取到 CS2 新闻")
                return
            
            # 初始化缓存（如果还没有）
            if not hasattr(self, 'cached_news_gids'):
                self.cached_news_gids = set()
            
            # 如果是第一次运行（缓存为空），只初始化缓存不发送新闻
            if len(self.cached_news_gids) == 0:
                current_gids = set(news.get('gid', '') for news in news_items)
                self.cached_news_gids = current_gids
                log.info(f"[{datetime.now()}] 首次运行，已初始化新闻缓存，当前缓存 {len(self.cached_news_gids)} 条")
                return
            
            # 提取当前新闻的 gid 集合
            current_gids = set()
            new_news_list = []
            
            for news in news_items:
                gid = news.get('gid', '')
                current_gids.add(gid)
                
                # 如果 gid 不在缓存中，说明是新新闻
                if gid not in self.cached_news_gids:
                    new_news_list.append(news)
            
            # 如果有新新闻，全部发送
            if new_news_list:
                log.info(f"[{datetime.now()}] 发现 {len(new_news_list)} 条新新闻")
                
                # 按时间倒序排序（最新的在前）
                # 注意：API 返回的已经是按时间倒序，新新闻应该也是倒序
                # 但为了用户体验，我们从最新的开始发送（列表已经是倒序）
                
                for news in new_news_list:
                    title = news.get('title', '无标题')
                    url = news.get('url', '#')
                    contents = news.get('contents', '无摘要')
                    
                    # 截断摘要内容（最多 200 字）
                    if len(contents) > 300:
                        contents = contents[:300] + '...'
                    
                    # 构建消息
                    message = f"【CS2 更新】\n\n"
                    message += f"{title}\n\n"
                    message += f"{contents}\n\n"
                    message += f"原文链接：{url}"
                    
                    log.info(f"[{datetime.now()}] 发送新新闻：{title}")
                    self.send_message(message)
                
                # 更新缓存：保留最新的 5 条 gid
                self.cached_news_gids = current_gids
                log.info(f"[{datetime.now()}] 新闻缓存已更新，当前缓存 {len(self.cached_news_gids)} 条")
            else:
                log.info(f"[{datetime.now()}] 无新新闻，最新 5 条新闻 gid：{[n.get('gid', '') for n in news_items]}")
                
        except Exception as e:
            log.info(f"[{datetime.now()}] 检查 CS2 新闻失败：{e}")

    async def _fetch_pw_stats_async(self, steam_ids):
        """异步获取完美平台战绩"""
        if not self.pw_api:
            return []
        
        match_groups = {} # match_id -> list of (steam_id, match_data)
        
        log.info(f"[{datetime.now()}] 开始查询 {len(steam_ids)} 位好友的完美平台战绩: {steam_ids}")
        
        for steam_id in steam_ids:
            try:
                # 获取最近对局列表 (dataSource=3 表示完美平台)
                # type=-1 表示全部类型
                match_data = await self.pw_api.get_csgopfmatch(steam_id, csgoSeasonId=3, type=-1)
                
                if isinstance(match_data, int) or not match_data.get('data'):
                    continue
                    
                matches = match_data['data'].get('matchList', [])
                if not matches:
                    continue
                
                # 获取最近一场比赛
                last_match = matches[0]
                match_id = last_match.get('matchId')
                
                # 检查比赛是否是最近结束的 (例如 30 分钟内)
                # endTime 格式: "2024-06-13 21:10:39"
                end_time_str = last_match.get('endTime')
                if end_time_str:
                    end_time = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S")
                    # 简单检查：如果在过去 30 分钟内结束
                    time_diff = (datetime.now() - end_time).total_seconds()
                    if time_diff > 1800:
                         log.info(f"[{datetime.now()}] {steam_id} 最近一场比赛 ({match_id}) 结束于 {end_time_str}，已超过30分钟 ({int(time_diff/60)}分钟)，忽略")
                         # 比赛结束太久了，忽略
                         continue
                    else:
                         log.info(f"[{datetime.now()}] {steam_id} 发现最近比赛: {match_id}, 结束时间: {end_time_str}")
                
                if match_id not in match_groups:
                    match_groups[match_id] = []
                match_groups[match_id].append((steam_id, last_match))
                
            except Exception as e:
                log.info(f"[{datetime.now()}] 查询完美战绩出错 ({steam_id}): {e}")
        
        if not match_groups:
            log.info(f"[{datetime.now()}] 本次查询未发现有效的新比赛")
            return []

        log.info(f"[{datetime.now()}] 共发现 {len(match_groups)} 场有效比赛，正在生成战报...")

        # 为每场对局调用 get_match_detail 获取完美平台昵称（同一 matchId 只调一次）
        match_pw_nicknames = {}  # match_id -> {steam_id: pw_nickname}
        for match_id in match_groups:
            try:
                detail = await self.pw_api.get_match_detail(match_id)
                if isinstance(detail, int) or not detail.get('players'):
                    match_pw_nicknames[match_id] = {}
                    continue
                nick_map = {}
                for player in detail['players']:
                    pid = str(player.get('playerId', ''))
                    pw_nick = player.get('nickName', '')
                    if pid and pw_nick:
                        nick_map[pid] = pw_nick
                match_pw_nicknames[match_id] = nick_map
                log.info(f"[{datetime.now()}] 对局 {match_id} 获取到 {len(nick_map)} 个完美昵称")
            except Exception as e:
                log.info(f"[{datetime.now()}] 获取对局详情失败 ({match_id}): {e}")
                match_pw_nicknames[match_id] = {}

        # 收集所有玩家的数据，用于合并和排序
        all_players = []  # [(steam_id, data, map_name, score1, score2), ...]

        for match_id, group in match_groups.items():
            try:
                # 这一组都是同一场比赛的好友
                # 取第一个人的数据来获取比赛基本信息（地图、比分等）
                first_player_data = group[0][1]
                map_name = first_player_data.get('mapName', '未知地图')
                score1 = first_player_data.get('score1')
                score2 = first_player_data.get('score2')

                pw_nicks = match_pw_nicknames.get(match_id, {})

                for steam_id, data in group:
                    # 优先使用对局详情中的完美平台昵称，其次使用已缓存的昵称
                    pw_name = pw_nicks.get(steam_id, '')
                    if pw_name:
                        nickname = pw_name
                        self.friend_pw_nickname_map[steam_id] = pw_name
                    else:
                        nickname = self.friend_pw_nickname_map.get(steam_id, '未知好友')

                    # 跳过已播报的对局
                    hist = self.friend_pw_history_stats.get(steam_id, {})
                    if hist.get('last_match_id') == match_id:
                        log.info(f"[{datetime.now()}] {nickname} 的对局 {match_id} 已播报过，跳过")
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

                    # KDA
                    kills = data.get('kill', 0)
                    deaths = data.get('death', 0)
                    assists = data.get('assist', 0)
                    rating = data.get('rating', 0.0)
                    pwRating = data.get('pwRating', 0.0)
                    we = data.get('we', 0)
                    pvpScore = data.get('pvpScore', 0)
                    score_change = data.get('pvpScoreChange', 0)

                    # 统计今日完美平台战绩
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

                    # 更新历史最佳战绩
                    if steam_id not in self.friend_pw_history_stats:
                        self.friend_pw_history_stats[steam_id] = {
                            'pw_nickname': pw_name or nickname,
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
                    
                    # 确保所有必要字段都存在
                    required_fields = {
                        'pw_nickname': '未知好友',
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
                    
                    for field, default in required_fields.items():
                        if field not in hist:
                            hist[field] = default
                    
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

                    # 更新昵称和最后一局 matchId
                    hist['pw_nickname'] = nickname
                    if pw_name:
                        hist['pw_nickname'] = pw_name
                    hist['last_match_id'] = match_id

                    # 收集用于显示的数据
                    all_players.append((steam_id, data, map_name, score1, score2, nickname, result))
                
            except Exception as e:
                log.info(f"[{datetime.now()}] 处理比赛数据出错 ({match_id}): {e}")
        
        # 按WE排序（从高到低）
        all_players.sort(key=lambda x: x[1].get('we', 0), reverse=True)
        
        # 生成消息：按 match_id 分组（同一局只发一次）
        messages = []
        if all_players:
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

                # 判断总体胜负（取多数人的结果）
                wins = sum(1 for _, _, _, r in players if r == '胜利')
                losses = sum(1 for _, _, _, r in players if r == '失败')
                draws = sum(1 for _, _, _, r in players if r == '平局')
                
                # 逻辑修正：如果有平局，直接显示平局
                if draws > 0:
                    result_emoji = '🤝'
                else:
                    result_emoji = '✅' if wins > losses else ('❌' if losses > wins else '🤝')

                msg = f"{result_emoji} {map_name}  {score1}:{score2}\n"
                msg += f"{'─' * 14}\n"

                # 按 WE 排序本场玩家
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

                    # 结果 emoji
                    r_emoji = '🟢' if result == '胜利' else ('🔴' if result == '失败' else '🟡')

                    msg += f"{r_emoji} {nickname}{mvp_tag}\n"
                    msg += f"  {kills}/{deaths}/{assists}  pwRT:{pwRating:.2f}  WE:{we:.1f}\n"
                    msg += f"  分数:{pvpScore} ({score_sign}{score_change})\n"

                messages.append(msg)

        # 检查排行榜变化并记录通知
        record_notifications = []
        try:
            record_notifications = self.check_and_report_records()
        except Exception as e:
            log.info(f"[{datetime.now()}] 检查排行榜变化失败: {e}")

        # 保存历史战绩统计到配置文件
        try:
            self.save_history_stats()
        except Exception as e:
            log.info(f"[{datetime.now()}] 保存历史战绩统计失败: {e}")

        # 保存完美平台昵称到配置文件
        try:
            self.save_pw_nicknames()
        except Exception as e:
            log.info(f"[{datetime.now()}] 保存完美平台昵称失败: {e}")

        # 如果有记录刷新通知，附加到最后一条战报后面
        if record_notifications and messages:
            record_msg = "🏆 记录刷新！\n" + "\n".join(record_notifications)
            messages[-1] = messages[-1] + "\n" + record_msg
        elif record_notifications:
            record_msg = "🏆 记录刷新！\n" + "\n".join(record_notifications)
            messages.append(record_msg)

        return messages

    def check_status_changes(self):
        """检查好友游戏状态变化，并累计今日游玩时长"""
        # 维护时间检查：避免在 00:15-08:00 进行状态检查和消息发送
        try:
            from core import check_maintenance
            if check_maintenance():
                log.info(f"[{datetime.now()}] 当前在维护时段，跳过游戏状态检查")
                return
        except (ImportError, AttributeError):
            pass
        
        friend_status_list = self.get_steam_friend_status()
        
        if not friend_status_list:
            return
        
        # 收集本次检查产生的所有通知，按游戏名称分组
        game_start_messages = {}  # game_name -> [nickname1, nickname2, ...]
        game_stop_messages = {}  # game_name -> [(nickname, duration_str), ...]
        
        # 收集刚结束CS2的好友，用于查询完美战绩
        stopped_cs2_friends = []

        for friend in friend_status_list:
            steam_id = friend.get('steamid')
            # 从config中的nickname_map获取昵称，如果没有则使用personaname
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
                # 按游戏名称分组收集
                if game_name not in game_start_messages:
                    game_start_messages[game_name] = []
                game_start_messages[game_name].append(nickname)
                
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
                
                # 按游戏名称分组收集
                if prev_game_name not in game_stop_messages:
                    game_stop_messages[prev_game_name] = []
                game_stop_messages[prev_game_name].append((nickname, duration_str))
                
                # 如果是 CS2 (AppID 730) 且配置了完美API，则加入查询列表
                if prev_game_id == '730' and self.pw_api:
                    stopped_cs2_friends.append(steam_id)
                
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

        # 生成合并的消息
        messages = []
        
        # 生成游戏开始消息（按游戏合并）
        for game_name, nicknames in game_start_messages.items():
            if len(nicknames) == 1:
                messages.append(f"🎮 {nicknames[0]} → {game_name}")
            else:
                messages.append(f"🎮 {', '.join(nicknames)} → {game_name}")
        
        # 生成游戏停止消息（按游戏合并）
        for game_name, stop_info in game_stop_messages.items():
            parts = [f"{nick}({dur})" for nick, dur in stop_info]
            messages.append(f"👋 {', '.join(parts)} 离开{game_name}")

        # 查询完美战绩
        if stopped_cs2_friends:
            log.info(f"[{datetime.now()}] 正在查询 {len(stopped_cs2_friends)} 位好友的完美平台战绩...")
            try:
                pw_messages = self._run_async_safe(self._fetch_pw_stats_async(stopped_cs2_friends))
                if pw_messages:
                    messages.extend(pw_messages)
            except Exception as e:
                log.info(f"[{datetime.now()}] 查询完美战绩失败: {e}")

        # 合并所有消息，限制单条长度避免微信截断
        if messages:
            combined = "\n".join(messages)
            # 微信单条消息建议不超过 2000 字符，超过则分批发送
            max_len = 1800
            if len(combined) <= max_len:
                self.send_message(combined)
            else:
                # 按消息拆分发送
                batch = ""
                for msg in messages:
                    if len(batch) + len(msg) + 1 > max_len and batch:
                        self.send_message(batch)
                        batch = msg
                    else:
                        batch = batch + "\n" + msg if batch else msg
                if batch:
                    self.send_message(batch)

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
            nickname = friend_data.get('pw_nickname', '未知昵称')
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

    def get_friend_pw_stats(self):
        """获取好友今天的完美平台战绩统计信息"""
        if not self.friend_pw_daily_stats:
            return None
        return self.friend_pw_daily_stats

    def get_friend_pw_history_stats(self):
        """获取好友的历史最佳战绩"""
        if not self.friend_pw_history_stats:
            return {}
        return self.friend_pw_history_stats
    
    def save_pw_nicknames(self, config_path=None):
        """将获取到的完美平台昵称保存到配置文件的 monitored_friends 中"""
        try:
            target_config_path = config_path or self.config_path
            config = self.load_config(target_config_path)
            monitored_friends = config.get('monitored_friends', [])
            changed = False
            for friend in monitored_friends:
                if isinstance(friend, dict):
                    steamid = friend.get('steamid', '')
                    pw_nick = self.friend_pw_nickname_map.get(steamid, '')
                    if pw_nick and friend.get('pw_nickname') != pw_nick:
                        friend['pw_nickname'] = pw_nick
                        changed = True
                    # 移除旧的 nickname 字段
                    if 'nickname' in friend:
                        del friend['nickname']
                        changed = True
            if changed:
                self.save_config(config, target_config_path)
                log.info(f"[{datetime.now()}] 完美平台昵称已保存到 {target_config_path}")
        except Exception as e:
            log.info(f"[{datetime.now()}] 保存完美平台昵称失败: {e}")

    def save_history_stats(self, config_path=None):
        """保存历史战绩统计到配置文件"""
        try:
            target_config_path = config_path or self.config_path
            config = self.load_config(target_config_path)
            config['friend_pw_history_stats'] = self.friend_pw_history_stats
            self.save_config(config, target_config_path)
            log.info(f"[{datetime.now()}] 历史战绩统计已保存到 {target_config_path}")
        except Exception as e:
            log.info(f"[{datetime.now()}] 保存历史战绩统计失败: {e}")

    def save_leaderboard(self, config_path=None):
        """保存排行榜持有者到配置文件"""
        try:
            target_config_path = config_path or self.config_path
            config = self.load_config(target_config_path)
            config['friend_pw_leaderboard'] = self.friend_pw_leaderboard
            self.save_config(config, target_config_path)
            log.info(f"[{datetime.now()}] 排行榜数据已保存到 {target_config_path}")
        except Exception as e:
            log.info(f"[{datetime.now()}] 保存排行榜数据失败: {e}")

    def check_and_report_records(self):
        """检查排行榜变化，返回刷新记录的通知消息列表"""
        if not self.friend_pw_history_stats:
            return []

        notifications = []
        valid_players = {sid: d for sid, d in self.friend_pw_history_stats.items()
                        if d.get('max_kills', 0) > 0 or d.get('max_rating', 0) > 0 or d.get('max_we', 0) > 0}
        if not valid_players:
            return []

        # 定义所有排行榜类别：(key_name, display_name, emoji, data_field, is_max)
        categories = [
            ('max_kills', '击杀王', '🔫', 'max_kills', True),
            ('min_kills', '精神支持', '🫡', 'min_kills', False),
            ('max_deaths', '唐宋八大家', '💀', 'max_deaths', True),
            ('min_deaths', '怯战蜥蜴', '🦎', 'min_deaths', False),
            ('max_rating', 'RT 之神', '📊', 'max_rating', True),
            ('min_rating', '团队吉祥物', '🧸', 'min_rating', False),
            ('max_pw_rating', 'PW RT 之神', '⚡', 'max_pw_rating', True),
            ('min_pw_rating', '纯路人', '👤', 'min_pw_rating', False),
            ('max_we', 'WE 之神', '💪', 'max_we', True),
            ('min_we', '不懂装懂', '😅', 'min_we', False),
            ('max_score', '得分王', '🎯', 'max_score', True),
            ('min_score', '吊车尾', '📉', 'min_score', False),
        ]

        for cat_key, cat_name, emoji, field, is_max in categories:
            # 找出当前该类别的最佳/最差玩家
            if is_max:
                candidates = [(sid, d.get(field, 0)) for sid, d in valid_players.items() if d.get(field, 0) > 0]
                if not candidates:
                    continue
                best_sid, best_val = max(candidates, key=lambda x: x[1])
            else:
                candidates = [(sid, d.get(field, 9999)) for sid, d in valid_players.items() if 0 < d.get(field, 9999) < 9999]
                if not candidates:
                    continue
                best_sid, best_val = min(candidates, key=lambda x: x[1])

            best_nick = valid_players[best_sid].get('pw_nickname', '未知')
            old = self.friend_pw_leaderboard.get(cat_key)

            if not old or old.get('steamid') != best_sid or old.get('value') != best_val:
                # 记录刷新了
                if old and old.get('steamid') != best_sid:
                    old_nick = old.get('pw_nickname', '未知')
                    old_val = old.get('value', 0)
                    notifications.append(f"{emoji} {cat_name}易主！{old_nick}({old_val}) → {best_nick}({best_val})")
                elif old and old.get('value') != best_val:
                    old_val = old.get('value', 0)
                    notifications.append(f"{emoji} {cat_name}刷新！{best_nick}: {old_val} → {best_val}")
                elif not old:
                    notifications.append(f"{emoji} {cat_name}诞生！{best_nick} ({best_val})")

                self.friend_pw_leaderboard[cat_key] = {
                    'steamid': best_sid,
                    'pw_nickname': best_nick,
                    'value': best_val
                }

        if notifications:
            self.save_leaderboard()

        return notifications

    def format_pw_daily_stats_message(self, pw_stats_data):
        """格式化今日完美平台战绩统计信息"""
        if not pw_stats_data:
            return None
        
        today = datetime.now().strftime("%m月%d日")
        lines = [f"⚔️ 完美平台日报 {today}", ""]

        sorted_friends = sorted(pw_stats_data.items(), key=lambda x: x[1]['match_count'], reverse=True)

        for steam_id, stats in sorted_friends:
            nickname = stats.get('pw_nickname', '未知好友')
            match_count = stats.get('match_count', 0)
            if match_count == 0:
                continue

            wins = stats.get('wins', 0)
            losses = stats.get('losses', 0)
            draws = stats.get('draws', 0)
            total_score_change = stats.get('total_score_change', 0)
            total_kills = stats.get('total_kills', 0)
            total_deaths = stats.get('total_deaths', 0)
            total_assists = stats.get('total_assists', 0)
            total_rating = stats.get('total_rating', 0.0)
            total_we = stats.get('total_we', 0)

            avg_rating = total_rating / match_count if match_count > 0 else 0
            avg_we = total_we / match_count if match_count > 0 else 0
            kd = total_kills / total_deaths if total_deaths > 0 else total_kills

            score_sign = '+' if total_score_change >= 0 else ''
            win_rate = wins / match_count * 100 if match_count > 0 else 0

            # 胜率颜色指示
            wr_emoji = '🟢' if win_rate >= 60 else ('🟡' if win_rate >= 40 else '🔴')

            lines.append(f"👤 {nickname}  {match_count}场")
            if draws > 0:
                lines.append(f"  {wr_emoji} {wins}胜{losses}负{draws}平 ({win_rate:.0f}%)  分数{score_sign}{total_score_change}")
            else:
                lines.append(f"  {wr_emoji} {wins}胜{losses}负 ({win_rate:.0f}%)  分数{score_sign}{total_score_change}")
            lines.append(f"  K/D: {kd:.1f}  RT: {avg_rating:.2f}  WE: {avg_we:.1f}")
            lines.append("")

        if len(lines) <= 2:
            return None

        return "\n".join(lines)

    def format_pw_leaderboard_message(self, history_stats_data):
        """格式化完美平台历史战绩排行榜（紧凑版）"""
        if not history_stats_data:
            return None

        valid_players = {sid: d for sid, d in history_stats_data.items()
                        if d.get('max_kills', 0) > 0 or d.get('max_rating', 0) > 0 or d.get('max_we', 0) > 0}
        if not valid_players:
            return None

        # 定义排行榜类别
        categories = [
            ('🔫 击杀王',   'max_kills',   True,  '杀'),
            ('🫡 精神支持', 'min_kills',   False, '杀'),
            ('💀 唐宋八大家','max_deaths', True,  '死'),
            ('🦎 怯战蜥蜴', 'min_deaths',  False, '死'),
            ('📊 RT 之神',   'max_rating',  True,  ''),
            ('🧸 吉祥物',   'min_rating',  False, ''),
            ('⚡ PW RT 之神','max_pw_rating',True, ''),
            ('👤 纯路人',   'min_pw_rating',False, ''),
            ('💪 WE 之神',   'max_we',      True,  ''),
            ('😅 不懂装懂', 'min_we',      False, ''),
            ('🎯 得分王',   'max_score',   True,  '分'),
            ('📉 吊车尾',   'min_score',   False, '分'),
        ]

        lines = ["🏆 历史战绩排行榜", ""]
        category_groups = [
            ['🔫', '🫡'],      # 击杀类
            ['💀', '🦎'],      # 死亡类
            ['📊', '🧸'],      # Rating 类
            ['⚡' , '👤'],      # PW Rating
            ['💪', '😅'],      # WE 类
            ['🎯', '📉'],      # 得分类
        ]
        
        current_group = 0
        for label, field, is_max, unit in categories:
            emoji = label.split()[0]
            
            # 检查是否需要切换到下一组
            while current_group < len(category_groups) and emoji not in category_groups[current_group]:
                current_group += 1
                if current_group < len(category_groups):
                    lines.append("")  # 在组之间添加空行
            
            if is_max:
                candidates = [(sid, d.get(field, 0)) for sid, d in valid_players.items() if d.get(field, 0) > 0]
                if not candidates:
                    continue
                best_sid, best_val = max(candidates, key=lambda x: x[1])
            else:
                candidates = [(sid, d.get(field, 9999)) for sid, d in valid_players.items() if 0 < d.get(field, 9999) < 9999]
                if not candidates:
                    continue
                best_sid, best_val = min(candidates, key=lambda x: x[1])

            nick = valid_players[best_sid].get('pw_nickname', '?')
            val_str = f"{best_val:.2f}" if isinstance(best_val, float) and not unit else str(int(best_val))
            lines.append(f"  {label}  {nick} {val_str}{unit}")

        if len(lines) <= 2:
            return None

        return "\n".join(lines)

    def reset_daily_stats(self):
        """重置每日游玩统计（在每天 0 点调用）"""
        log.info(f"[{datetime.now()}] 重置每日游玩统计")
        self.friend_daily_stats = {}
        self.friend_pw_daily_stats = {}

    def send_daily_stats(self):
        """发送每日游玩统计（日报 + 排行榜，分条发送）"""
        log.info(f"[{datetime.now()}] 执行每日统计任务...")
        
        # 1. Steam 今日游玩时长
        try:
            stats_data = self.get_friend_game_stats()
            if stats_data:
                msg = self.format_game_stats_message(stats_data)
                if msg:
                    self.send_message(msg)
                    time.sleep(1)  # 间隔 1 秒避免消息太快
        except Exception as e:
            log.info(f"[{datetime.now()}] Steam 统计失败：{e}")
        
        # 2. 完美平台今日战绩
        try:
            pw_stats_data = self.get_friend_pw_stats()
            if pw_stats_data:
                msg = self.format_pw_daily_stats_message(pw_stats_data)
                if msg:
                    self.send_message(msg)
                    time.sleep(1)
        except Exception as e:
            log.info(f"[{datetime.now()}] 完美平台统计失败：{e}")

        # 3. 完整历史排行榜
        try:
            history_stats_data = self.get_friend_pw_history_stats()
            if history_stats_data:
                msg = self.format_pw_leaderboard_message(history_stats_data)
                if msg:
                    self.send_message(msg)
        except Exception as e:
            log.info(f"[{datetime.now()}] 排行榜生成失败：{e}")

        self.reset_daily_stats()
        log.info(f"[{datetime.now()}] 每日统计任务完成")

    def send_leaderboard(self):
        """检查排行榜变化并播报（排行榜已合并到每日统计中）"""
        # 维护时间检查
        try:
            from core import check_maintenance
            if check_maintenance():
                log.info(f"[{datetime.now()}] 当前在维护时段，跳过排行榜检查")
                return
        except (ImportError, AttributeError):
            pass
        
        log.info(f"[{datetime.now()}] 执行排行榜检查...")
        try:
            notifications = self.check_and_report_records()
            if notifications:
                msg = "🏆 记录刷新！\n" + "\n".join(notifications)
                self.send_message(msg)
                log.info(f"[{datetime.now()}] 已播报 {len(notifications)} 条记录变化")
            else:
                log.info(f"[{datetime.now()}] 排行榜无变化")
        except Exception as e:
            log.info(f"[{datetime.now()}] 排行榜检查失败：{e}")
        try:
            history_stats_data = self.get_friend_pw_history_stats()
            if history_stats_data:
                message = self.format_pw_leaderboard_message(history_stats_data)
                if message:
                    self.send_message(message)
            else:
                log.info(f"[{datetime.now()}] 无历史战绩记录")
        except Exception as e:
            log.info(f"[{datetime.now()}] 发送历史排行榜失败：{e}")

    def daily_update_tasks(self):
        """封装每天需要执行的任务集合。

        包含：发送每日统计、清理/刷新需要每天更新的缓存或计数器等。
        如需添加其他每日任务，可在此处扩展。
        """
        # 维护时间检查：避免在 00:15-08:00 发送消息
        try:
            from core import check_maintenance
            if check_maintenance():
                log.info(f"[{datetime.now()}] 当前在维护时段，跳过每日统计发送")
                return
        except (ImportError, AttributeError):
            pass
        
        log.info(f"[{datetime.now()}] 执行每日更新任务...")
        try:
            # 发送并重置每日统计（内部已包含重置逻辑）
            self.send_daily_stats()
        except Exception as e:
            log.info(f"[{datetime.now()}] 执行 send_daily_stats 失败: {e}")

        try:
            # 每天刷新好友列表缓存，确保次日拉取到最新好友变更
            self.invalidate_friend_list_cache()
            log.info(f"[{datetime.now()}] 好友列表缓存已失效，将在下一次访问时刷新")
        except Exception as e:
            log.info(f"[{datetime.now()}] 清理好友列表缓存失败: {e}")

    def start(self):
        """
        启动定时检查（检查间隔来源于实例配置 self.check_interval）
        """
        # 首次启动时发送更新消息（非调试模式）
        # 注意：此时 send_message 已被主框架替换为入队函数，会受维护时间检查控制
        if self.code_update_message and not self.debug:
            log.info(f"[{datetime.now()}] 准备发送启动更新消息")
            self.send_message(self.code_update_message)
            log.info(f"[{datetime.now()}] 启动更新消息已加入队列")
            # 等待一小段时间让主线程处理队列
            time.sleep(2)
        
        check_interval = int(self.check_interval) if isinstance(self.check_interval, (int, float, str)) else 60
        log.info(f"[{datetime.now()}] [cs-Solidarity v{APP_VERSION}] 程序启动")
        log.info(f"[{datetime.now()}] 将每 {check_interval} 秒检查一次好友游戏状态")
        log.info(f"[{datetime.now()}] 目标 Steam ID: {self.steam_id}")
        log.info(f"[{datetime.now()}] 每天 23:55 将发送好友游玩统计（避开维护时段）")
        log.info(f"[{datetime.now()}] 每天 23:55 将发送日报+完整排行榜")
        
        # 初始化一次，获取当前状态
        self.check_status_changes()
        
        # 设置定时任务：每 check_interval 秒检查一次好友游戏状态变化
        schedule.every(check_interval).seconds.do(self.check_status_changes)
        
        # 设置每日定时任务：每天 00:05 执行每日更新任务（维护时段 00:15 开始，有 10 分钟窗口）
        schedule.every().day.at("23:55").do(self.daily_update_tasks)
        
        # 设置定时任务：定期检查 CS2 新闻（如果启用）
        if self.enable_news_check:
            check_news_interval = int(self.check_news_interval) if isinstance(self.check_news_interval, (int, float, str)) else 3600
            log.info(f"[{datetime.now()}] 已启用新闻检查，将每 {check_news_interval} 秒检查一次 CS2 新闻")
            schedule.every(check_news_interval).seconds.do(self.check_cs2_news)
        
        try:
            while True:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            log.debug(f"\n[{datetime.now()}] 程序已停止")