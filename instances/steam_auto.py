from steam.SteamAPI import SteamAPI
import time
import schedule
import json
import asyncio
import re
import threading
import html
from datetime import datetime
from typing import Any, Dict
from pathlib import Path
from core import wechat_instance
from cs2_platforms.cs2_pw.pw_reporter import PwStatsReporter
from cs2_platforms.cs2_official.official_reporter import OfficialStatsReporter
from cs2_platforms.cs2_5e.request import FiveEApi
from cs2_platforms.cs2_5e.reporter import FiveEStatsReporter
from core.base_instance import BaseInstance
from cs2_platforms.cs2_pw.request import PerfectWorldApi
from utils.steam_archive import archive_pw_season_data
from utils.steam_timeline import SteamTimelineRecorder
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
    DEFAULT_GAME_EVENT_MUTE_CONFIG = {
        'enabled': True,
        'window_minutes': 30,
        'threshold': 4,
        'mute_minutes': 60,
    }

    # 排行榜类别：(key, 显示名, emoji, data_field, is_max)
    # 单一来源：时间轴历史极值变化与排行榜播报共用此定义
    LEADERBOARD_CATEGORIES = [
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

    def __init__(self, steam_api_key=None, steam_id=None, wechat_groups=None, monitored_friends=None, enable_all_friends=True, code_update_lines=None, check_interval=60, perfect_world_config=None, check_news_interval=3600, enable_news_check=True, friend_pw_history_stats=None, friend_5e_history_stats=None, friend_official_history_stats=None, cached_news_gids=None, game_event_mute_config=None, config_path='config.json', data_path=None, debug=False):
        # 优先从环境变量读取配置
        self.steam_api_key = steam_api_key or os.getenv('STEAM_API_KEY')
        self.steam_id = steam_id or os.getenv('STEAM_ID')

        self.steam = SteamAPI(self.steam_api_key)
        self.config_path = config_path # 保存配置文件路径
        self.data_path = data_path or str(Path(config_path).parent / 'steam_data.json')
        self.debug = debug  # 调试模式标志
        self.friend_game_status = {} # 用于追踪好友的游戏状态变化
        self.friend_daily_stats = {} # 用于统计好友今天的游玩时长 {"steamid": {"game_name": total_seconds, ...}}
        self.friend_pw_daily_stats = {} # 用于统计好友今天的完美平台战绩 {"steamid": {"matches": [], "wins": 0, "losses": 0, "draws": 0, "total_score_change": 0, "total_stars_change": 0, "total_kills": 0, "total_deaths": 0, "total_assists": 0, "total_rating": 0, "total_pw_rating": 0, "total_we": 0, "match_count": 0}}
        self.friend_pw_history_stats = friend_pw_history_stats or {} # 用于统计好友的历史最佳战绩 {"steamid": {"max_kills": 0, "min_kills": 999, ...}}
        self.friend_5e_daily_stats = {}
        self.friend_5e_history_stats = friend_5e_history_stats or {}
        self.friend_official_daily_stats = {}
        self.friend_official_history_stats = friend_official_history_stats or {}
        self.friend_official_nickname_map = {}
        # 时间轴记录器（历史极值变化 + 好友对局记录）
        self.timeline_recorder = SteamTimelineRecorder(self.data_path)
        self.friend_pw_leaderboard = {}  # 当前排行榜持有者 {"category": {"steamid": ..., "pw_nickname": ..., "value": ...}}
        self.cached_friend_list = None # 缓存好友列表，避免频繁调用 API
        self.code_update_lines = code_update_lines or []
        self.check_interval = check_interval

        # 好友进入/离开游戏防刷静音（仅内存状态，重启后清空）
        self.game_event_mute_config = self._normalize_game_event_mute_config(game_event_mute_config)
        self.game_event_mute_enabled = self.game_event_mute_config['enabled']
        self.game_event_mute_window_minutes = self.game_event_mute_config['window_minutes']
        self.game_event_mute_threshold = self.game_event_mute_config['threshold']
        self.game_event_mute_duration_minutes = self.game_event_mute_config['mute_minutes']
        self.game_event_mute_window_seconds = self.game_event_mute_window_minutes * 60
        self.game_event_mute_duration_seconds = self.game_event_mute_duration_minutes * 60
        self.friend_game_event_history = {}  # steamid -> [timestamp, ...]
        self.friend_game_event_muted_until = {}  # steamid -> timestamp
        
        # 新闻检查相关
        self.enable_news_check = enable_news_check
        self.check_news_interval = check_news_interval  # 新闻检查间隔（秒），默认 1 小时
        # 新闻缓存：{gid: timestamp}，最多保留 100 条，最久 30 天
        self.cached_news_gids = {}  # 从配置加载时会被覆盖为 {gid: timestamp}
        if cached_news_gids:
            for gid in cached_news_gids:
                self.cached_news_gids[gid] = time.time()  # 旧格式无时间戳，统一用当前时间标记（30 天内不会过期）
        
        # 完美平台配置
        self.perfect_world_config = perfect_world_config or {}
        self.pw_uid = self.perfect_world_config.get('uid') or os.getenv('PW_UID')
        self.pw_token = self.perfect_world_config.get('token') or os.getenv('PW_TOKEN')
        self.pw_api = None
        if self.pw_uid and self.pw_token:
            self.pw_api = PerfectWorldApi(uid=self.pw_uid, token=self.pw_token)
        self.fivee_api = FiveEApi()

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

    @classmethod
    def _normalize_game_event_mute_config(cls, config):
        """归一化进入/离开游戏防刷配置，保持缺省配置可直接生效。"""
        normalized = dict(cls.DEFAULT_GAME_EVENT_MUTE_CONFIG)
        if isinstance(config, dict):
            for key in normalized:
                if key in config:
                    normalized[key] = config[key]

        normalized['enabled'] = bool(normalized.get('enabled', True))

        for key in ('window_minutes', 'threshold', 'mute_minutes'):
            default_value = cls.DEFAULT_GAME_EVENT_MUTE_CONFIG[key]
            try:
                value = int(float(normalized.get(key, default_value)))
            except (TypeError, ValueError):
                value = default_value
            normalized[key] = max(1, value)

        return normalized

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
    
    def auto_fill_monitored_friends(self, data_path=None):
        """首次执行时自动填充monitored_friends（写入数据文件）"""
        target_data_path = data_path or self.data_path

        # 从数据文件读取 monitored_friends
        data = {}
        if Path(target_data_path).exists():
            try:
                with open(target_data_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                pass

        monitored_friends = data.get('monitored_friends', [])

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

            # 构建好友列表
            friends_config = []
            for friend in friend_status_list:
                friends_config.append({
                    "steamid": friend.get('steamid', ''),
                    "personaname": friend.get('personaname', '未知昵称'),
                    "pw_nickname": friend.get('personaname', '未知昵称')
                })

            # 写入数据文件
            data['monitored_friends'] = friends_config
            self._update_last_save_time(data)
            self.save_config(data, target_data_path)

            # enable_all_friends 是配置项，写入配置文件
            cfg = self.load_config(self.config_path)
            cfg['enable_all_friends'] = False
            self.save_config(cfg, self.config_path)

            log.info(f"[{datetime.now()}] 成功填充 {len(friends_config)} 位好友的信息到数据文件")
            for friend in friends_config:
                log.debug(f"  - {friend['pw_nickname']} ({friend['steamid']})")

        except Exception as e:
            log.info(f"[{datetime.now()}] 自动填充好友信息失败: {e}")
    
    # 数据文件中的字段（运行时数据，与用户配置分离）
    _DATA_FIELDS = [
        'monitored_friends',
        'friend_pw_history_stats',
        'friend_pw_leaderboard',
        'friend_5e_history_stats',
        'friend_official_history_stats',
        'cached_news_gids',
        'last_update',
    ]

    @staticmethod
    def create_from_config(config_path='config.json'):
        """从配置文件创建 SteamAuto 实例"""
        config = SteamAuto.load_config(config_path)

        # 推导数据文件路径
        cfg_path = Path(config_path)
        data_path = str(cfg_path.parent / 'steam_data.json')

        # 首次迁移：将数据字段从 config 拆分到 data 文件
        if not Path(data_path).exists():
            SteamAuto._migrate_data_from_config(config_path, data_path)
            config = SteamAuto.load_config(config_path)

        # 加载数据文件
        data = {}
        if Path(data_path).exists():
            try:
                with open(data_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                pass

        # 合并：数据字段从 data 文件读取，配置字段从 config 读取
        for key in SteamAuto._DATA_FIELDS:
            if key in data:
                config[key] = data[key]

        # 读取主配置文件的 debug_mode（从实例配置路径推导主配置位置）
        try:
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
            code_update_lines=config.get('code_update_lines', []),
            check_interval=config.get('check_interval', 60),
            perfect_world_config=perfect_world_config,
            check_news_interval=config.get('check_news_interval', 3600),
            enable_news_check=config.get('enable_news_check', True),
            game_event_mute_config=config.get('game_event_mute', {}),
            config_path=config_path,
            data_path=data_path,
        )

        # 首次执行时且好友信息为空，自动填充好友信息
        temp_instance.auto_fill_monitored_friends(data_path)

        # 重新加载数据（可能已被更新）
        if Path(data_path).exists():
            try:
                with open(data_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for key in SteamAuto._DATA_FIELDS:
                    if key in data:
                        config[key] = data[key]
            except Exception:
                pass

        # 显示配置信息
        log.debug("=" * 50)
        log.debug("配置信息：")
        log.debug(f"配置文件: {config_path}")
        log.debug(f"数据文件: {data_path}")
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
            code_update_lines=config.get('code_update_lines', []),
            check_interval=config.get('check_interval', 60),
            perfect_world_config=perfect_world_config,
            check_news_interval=config.get('check_news_interval', 3600),
            enable_news_check=config.get('enable_news_check', True),
            friend_pw_history_stats=config.get('friend_pw_history_stats'),
            friend_5e_history_stats=config.get('friend_5e_history_stats'),
            friend_official_history_stats=config.get('friend_official_history_stats'),
            cached_news_gids=config.get('cached_news_gids'),
            game_event_mute_config=config.get('game_event_mute', {}),
            config_path=config_path,
            data_path=data_path,
            debug=debug_mode
        )
        # 加载已保存的排行榜数据
        instance.friend_pw_leaderboard = config.get('friend_pw_leaderboard', {})
        return instance

    @staticmethod
    def _migrate_data_from_config(config_path, data_path):
        """首次迁移：将数据字段从配置文件拆分到数据文件"""
        try:
            config = SteamAuto.load_config(config_path)
            data = {}
            has_data = False
            for key in SteamAuto._DATA_FIELDS:
                if key in config:
                    data[key] = config.pop(key)
                    has_data = True
            if has_data:
                with _config_lock:
                    with open(data_path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    with open(config_path, 'w', encoding='utf-8') as f:
                        json.dump(config, f, ensure_ascii=False, indent=2)
                log.info(f"已将数据字段迁移到 {data_path}")
        except Exception as e:
            log.warning(f"数据迁移失败: {e}")

    def send_message(self, message):
        """
        发送消息到所有配置的微信群/个人
        :param message: 要发送的消息内容
        """
        if not message or not str(message).strip():
            return
        
        for group in self.wechat_groups:
            try:
                wechat_instance.send_message(str(message), group)
                log.info(f"[{datetime.now()}] 消息已发送到: {group}")
            except Exception as e:
                log.info(f"[{datetime.now()}] 发送消息到 {group} 失败: {e}")

    def send_file(self, file_path: str):
        """
        发送文件到所有配置的微信群/个人
        :param file_path: 要发送的文件路径
        """
        if not file_path:
            return

        for group in self.wechat_groups:
            try:
                wechat_instance.send_file(file_path, group)
                log.info(f"[{datetime.now()}] 文件已发送到: {group}")
            except Exception as e:
                log.info(f"[{datetime.now()}] 发送文件到 {group} 失败: {e}")

        try:
            path_obj = Path(file_path)
            daily_stats_dir = Path(self.data_path).parent / "generated" / "daily_stats"
            if path_obj.resolve().parent == daily_stats_dir.resolve():
                path_obj.unlink(missing_ok=True)
        except Exception as e:
            log.debug(f"[{datetime.now()}] 清理临时日报图片失败: {e}")
    
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

    def _check_game_event_mute(self, steam_id, nickname, now_ts):
        """判断某个好友的进入/离开播报是否需要静音。

        返回 (should_mute, notification)，notification 仅在刚触发新静音时有值。
        """
        if not self.game_event_mute_enabled or not steam_id:
            return False, None

        muted_until = self.friend_game_event_muted_until.get(steam_id, 0)
        if muted_until > now_ts:
            return True, None

        if muted_until:
            self.friend_game_event_muted_until.pop(steam_id, None)
            self.friend_game_event_history.pop(steam_id, None)

        cutoff = now_ts - self.game_event_mute_window_seconds
        history = [
            ts for ts in self.friend_game_event_history.get(steam_id, [])
            if ts >= cutoff
        ]
        history.append(now_ts)

        if len(history) > self.game_event_mute_threshold:
            muted_until = now_ts + self.game_event_mute_duration_seconds
            self.friend_game_event_muted_until[steam_id] = muted_until
            self.friend_game_event_history[steam_id] = []
            notification = (
                f"🔇 {nickname} "
                f"{self.game_event_mute_window_minutes}分钟内频繁进入/离开游戏，"
                f"已静音{self.game_event_mute_duration_minutes}分钟。"
                "期间将不再播报该好友的进入/离开游戏消息。"
            )
            log.info(
                f"[{datetime.now()}] 好友 {nickname}({steam_id}) 触发进入/离开防刷，"
                f"静音到 {datetime.fromtimestamp(muted_until).strftime('%Y-%m-%d %H:%M:%S')}"
            )
            return True, notification

        self.friend_game_event_history[steam_id] = history
        return False, None

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
            # 清理过期缓存（超过 30 天）
            self._clean_news_cache()

            # 获取最新 10 条新闻
            news_items = self.steam.get_steam_news(app_id=730, count=10)

            if not news_items or len(news_items) == 0:
                log.info(f"[{datetime.now()}] 未获取到 CS2 新闻")
                return

            # 初始化缓存（如果还没有）
            if not hasattr(self, 'cached_news_gids') or not self.cached_news_gids:
                current_gids = {news.get('gid', ''): time.time() for news in news_items}
                self.cached_news_gids = current_gids
                self.save_news_cache()  # 首次初始化也要保存到配置文件
                log.info(f"[{datetime.now()}] 首次运行，已初始化新闻缓存，当前缓存 {len(self.cached_news_gids)} 条")
                return

            # 提取当前新闻的 gid 集合
            current_gids_set = set()
            new_news_list = []

            log.info(f"[{datetime.now()}] API 返回的原始 gids: {[news.get('gid', '') for news in news_items]}")
            log.info(f"[{datetime.now()}] 缓存 gids: {sorted(self.cached_news_gids.keys())}")

            now_ts = time.time()
            for news in news_items:
                gid = news.get('gid', '')
                current_gids_set.add(gid)

                # 如果 gid 不在缓存中，说明是新新闻
                if gid not in self.cached_news_gids:
                    new_news_list.append(news)

            # 如果有新新闻，全部发送
            if new_news_list:
                log.info(f"[{datetime.now()}] 发现 {len(new_news_list)} 条新新闻")
                log.info(f"[{datetime.now()}] 当前缓存 gids: {sorted(self.cached_news_gids.keys())}")
                log.info(f"[{datetime.now()}] 本次新 gid: {[n.get('gid', '') for n in new_news_list]}")

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

                # 更新缓存：只把新新闻 gid 加入缓存（用时间戳标记）
                for news in new_news_list:
                    gid = news.get('gid', '')
                    if gid:
                        self.cached_news_gids[gid] = now_ts

                # 限制缓存数量（最多 100 条），超出时删除最旧的
                self._trim_news_cache()

                self.save_news_cache()  # 持久化到配置文件
                log.info(f"[{datetime.now()}] 新闻缓存已更新，当前缓存 {len(self.cached_news_gids)} 条")
            else:
                log.info(f"[{datetime.now()}] 无新新闻，最新 10 条新闻 gid：{[n.get('gid', '') for n in news_items]}")

        except Exception as e:
            log.info(f"[{datetime.now()}] 检查 CS2 新闻失败：{e}")

    async def _fetch_pw_stats_async(self, steam_ids):
        """异步获取完美平台战绩（委托给 PwStatsReporter）"""
        if not self.pw_api:
            return []

        reporter = PwStatsReporter(
            pw_api=self.pw_api,
            friend_pw_nickname_map=self.friend_pw_nickname_map,
            friend_pw_history_stats=self.friend_pw_history_stats,
            friend_pw_daily_stats=self.friend_pw_daily_stats,
            log=log.info
        )

        messages, processed_matches = await reporter.fetch_and_report(steam_ids)

        # 记录好友对局
        try:
            self._record_play_records(processed_matches, platform='pw', platform_label='完美')
        except Exception as e:
            log.info(f"[{datetime.now()}] 记录好友对局失败: {e}")

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

    async def _fetch_5e_stats_async(self, steam_ids):
        """异步获取 5E 战绩。"""
        if not self.fivee_api:
            return []

        reporter = FiveEStatsReporter(
            fivee_api=self.fivee_api,
            monitored_friends=list(self.monitored_friends_detail()),
            friend_5e_history_stats=self.friend_5e_history_stats,
            friend_5e_daily_stats=self.friend_5e_daily_stats,
            log=log.info,
        )

        messages, processed_matches = await reporter.fetch_and_report(steam_ids)

        try:
            self._record_play_records(processed_matches, platform='5e', platform_label='5E')
        except Exception as e:
            log.info(f"[{datetime.now()}] 记录 5E 好友对局失败: {e}")

        try:
            if reporter.resolved_friend_updates:
                self.save_5e_profiles(reporter.resolved_friend_updates)
        except Exception as e:
            log.info(f"[{datetime.now()}] 保存 5E 用户信息失败: {e}")

        try:
            self.save_5e_history_stats()
        except Exception as e:
            log.info(f"[{datetime.now()}] 保存 5E 历史战绩统计失败: {e}")

        return messages

    async def _fetch_official_stats_async(self, steam_ids):
        """异步获取官匹战绩（复用完美世界 API，dataSource=1）"""
        if not self.pw_api:
            return []

        reporter = OfficialStatsReporter(
            pw_api=self.pw_api,
            friend_official_nickname_map=self.friend_official_nickname_map,
            friend_official_history_stats=self.friend_official_history_stats,
            friend_official_daily_stats=self.friend_official_daily_stats,
            log=log.info,
        )

        messages, processed_matches = await reporter.fetch_and_report(steam_ids)

        try:
            self._record_play_records(processed_matches, platform='official', platform_label='官匹')
        except Exception as e:
            log.info(f"[{datetime.now()}] 记录官匹好友对局失败: {e}")

        try:
            self.save_official_history_stats()
        except Exception as e:
            log.info(f"[{datetime.now()}] 保存官匹历史战绩统计失败: {e}")

        return messages

    def monitored_friends_detail(self):
        """Return monitored friends with metadata from the data file."""
        try:
            data = self.load_config(self.data_path)
            friends = data.get('monitored_friends', [])
            if isinstance(friends, list):
                return friends
        except Exception:
            pass
        return [{'steamid': sid, 'pw_nickname': self.friend_pw_nickname_map.get(sid, sid)} for sid in self.monitored_friends]

    def _record_play_records(self, processed_matches: list, platform: str = 'pw', platform_label: str = '完美') -> None:
        """把 reporter 处理过的对局写入时间轴：按 match_id 分桶，多人同场合并到一条 match 事件。"""
        matches_by_id: Dict[str, Dict[str, Any]] = {}
        for entry in processed_matches or []:
            try:
                steam_id, data, map_name, score1, score2, nickname, result = entry
            except (ValueError, TypeError):
                continue
            if not data:
                continue
            match_id = data.get('matchId', '')
            if not match_id:
                continue
            kills = data.get('kill', 0)
            deaths = data.get('death', 0)
            assists = data.get('assist', 0)
            bucket = matches_by_id.setdefault(match_id, {
                'map_name': map_name,
                'score': f"{score1}:{score2}" if score1 is not None and score2 is not None else "-:-",
                'platform': platform,
                'platform_label': platform_label,
                'players': [],
            })
            bucket['players'].append({
                'steamid': steam_id,
                'pw_nickname': nickname,
                'platform': platform,
                'platform_label': platform_label,
                'kda': f"{kills}/{deaths}/{assists}",
                'rating': float(data.get('rating', 0.0) or 0.0),
                'result': result,
                'we': int(data.get('we', 0) or 0),
                'pvp_score_change': int(data.get('pvpScoreChange', 0) or 0),
                'pvp_stars_change': int(data.get('pvpStars', 0) or 0) - int(data.get('_prev_pvpStars', 0) or 0),
            })
        for match_id, info in matches_by_id.items():
            try:
                self.timeline_recorder.record_game_match(
                    match_id=match_id,
                    map_name=info['map_name'],
                    score=info['score'],
                    players=info['players'],
                    platform=info.get('platform', platform),
                    platform_label=info.get('platform_label', platform_label),
                )
            except Exception as e:
                log.info(f"[{datetime.now()}] 记录对局失败 ({match_id}): {e}")

    def check_status_changes(self):
        """检查好友游戏状态变化，并累计今日游玩时长"""
        friend_status_list = self.get_steam_friend_status()

        if not friend_status_list:
            return

        # 收集本次检查产生的所有通知，按游戏名称分组
        game_start_messages = {}  # game_name -> [nickname1, nickname2, ...]
        game_stop_messages = {}  # game_name -> [(nickname, duration_str), ...]
        game_mute_messages = []
        
        # 收集刚结束CS2的好友，用于查询完美战绩
        stopped_cs2_friends = []

        for friend in friend_status_list:
            steam_id = friend.get('steamid')
            # 从config中的nickname_map获取昵称，如果没有则使用personaname
            nickname = friend.get('personaname', '未知昵称')
            game_id = friend.get('gameid', None)
            game_name = friend.get('gameextrainfo', '未游玩游戏')
            personastate = friend.get('personastate', 0)  # 0: 离线, 1: 在线, 2: 忙碌, 3: 离开, 4: 暂离, 5: 求交易, 6: 求组队
            lastlogoff = friend.get('lastlogoff')  # 上次离线时间

            # 获取该好友的上一次状态
            prev_game_id = self.friend_game_status.get(steam_id, {}).get('gameid')
            prev_game_name = self.friend_game_status.get(steam_id, {}).get('game_name')
            prev_start_time = self.friend_game_status.get(steam_id, {}).get('start_time')

            current_time = time.time()

            # 检查游戏状态变化：从无游戏变为有游戏
            if game_id and game_id != '0' and prev_game_id != game_id:
                muted, mute_notice = self._check_game_event_mute(steam_id, nickname, current_time)
                if mute_notice:
                    game_mute_messages.append(mute_notice)
                if not muted:
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
                    'start_time': current_time,
                    'lastlogoff': lastlogoff
                }

                # 写入时间轴启动事件
                try:
                    self.timeline_recorder.record_game_start(
                        steamid=steam_id,
                        pw_nickname=self.friend_pw_nickname_map.get(steam_id, nickname),
                        game_name=game_name or f'游戏 {game_id}',
                    )
                except Exception as e:
                    log.info(f"[{datetime.now()}] 记录游戏启动失败 ({steam_id}/{game_name}): {e}")

            # 检查游戏状态变化：从有游戏变为无游戏
            elif (not game_id or game_id == '0') and prev_game_id and prev_game_id != '0':
                # 计算游玩时长
                duration = current_time - prev_start_time if prev_start_time else 0
                duration_str = self.format_duration(duration)

                muted, mute_notice = self._check_game_event_mute(steam_id, nickname, current_time)
                if mute_notice:
                    game_mute_messages.append(mute_notice)
                if not muted:
                    # 按游戏名称分组收集
                    if prev_game_name not in game_stop_messages:
                        game_stop_messages[prev_game_name] = []
                    game_stop_messages[prev_game_name].append((nickname, duration_str))

                # 如果是 CS2 (AppID 730)，离开后查询平台战绩
                if prev_game_id == '730':
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
                    'start_time': None,
                    'lastlogoff': lastlogoff
                }

                # 写入时间轴结束事件
                try:
                    self.timeline_recorder.record_game_end(
                        steamid=steam_id,
                        pw_nickname=self.friend_pw_nickname_map.get(steam_id, nickname),
                        game_name=prev_game_name or f'游戏 {prev_game_id}',
                    )
                except Exception as e:
                    log.info(f"[{datetime.now()}] 记录游戏结束失败 ({steam_id}/{prev_game_name}): {e}")
            
            # 首次出现的好友，初始化完整状态
            if steam_id not in self.friend_game_status:
                self.friend_game_status[steam_id] = {
                    'gameid': game_id,
                    'game_name': game_name,
                    'personastate': personastate,
                    'nickname': nickname,
                    'start_time': current_time if (game_id and game_id != '0') else None,
                    'lastlogoff': lastlogoff
                }
            else:
                # 已存在的好友，每次检查都更新在线状态和最后离线时间
                self.friend_game_status[steam_id]['personastate'] = personastate
                self.friend_game_status[steam_id]['lastlogoff'] = lastlogoff

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

        messages.extend(game_mute_messages)

        # 查询完美 / 5E / 官匹战绩
        if stopped_cs2_friends:
            if self.pw_api:
                log.info(f"[{datetime.now()}] 正在查询 {len(stopped_cs2_friends)} 位好友的完美平台战绩...")
                try:
                    pw_messages = self._run_async_safe(self._fetch_pw_stats_async(stopped_cs2_friends))
                    if pw_messages:
                        messages.extend(pw_messages)
                except Exception as e:
                    log.info(f"[{datetime.now()}] 查询完美战绩失败: {e}")

                log.info(f"[{datetime.now()}] 正在查询 {len(stopped_cs2_friends)} 位好友的官匹战绩...")
                try:
                    official_messages = self._run_async_safe(self._fetch_official_stats_async(stopped_cs2_friends))
                    if official_messages:
                        messages.extend(official_messages)
                except Exception as e:
                    log.info(f"[{datetime.now()}] 查询官匹战绩失败: {e}")

            log.info(f"[{datetime.now()}] 正在查询 {len(stopped_cs2_friends)} 位好友的 5E 战绩...")
            try:
                fivee_messages = self._run_async_safe(self._fetch_5e_stats_async(stopped_cs2_friends))
                if fivee_messages:
                    messages.extend(fivee_messages)
            except Exception as e:
                log.info(f"[{datetime.now()}] 查询 5E 战绩失败: {e}")

        # 合并所有消息，限制单条长度避免微信截断
        if messages:
            # 维护时间内跳过消息发送，但仍更新状态和累计时长
            try:
                from core import check_maintenance
                if check_maintenance():
                    log.info(f"[{datetime.now()}] 当前在维护时段，跳过消息发送")
                    return
            except (ImportError, AttributeError):
                pass
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

        # 保存好友状态到配置文件，供 Web 面板读取
        self.save_friend_status()

    def save_friend_status(self):
        """保存好友状态到数据文件，供 Web 面板读取"""
        if not self.monitored_friends:
            return

        try:
            with open(self.data_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return

        # 更新 monitored_friends 中的状态字段
        monitored_friends = config.get('monitored_friends', [])
        updated = False

        for friend in monitored_friends:
            steam_id = friend.get('steamid')
            if not steam_id:
                continue

            # 从内存状态中获取最新状态
            game_status = self.friend_game_status.get(steam_id, {})

            # 只有当状态存在时才更新
            if game_status:
                friend['personastate'] = game_status.get('personastate', 0)
                friend['gameextrainfo'] = game_status.get('game_name', '')
                friend['lastlogoff'] = game_status.get('lastlogoff')
                updated = True

        if updated:
            config['monitored_friends'] = monitored_friends
            self._update_last_save_time(config)
            self.save_config(config, self.data_path)
            log.debug(f"[{datetime.now()}] 好友状态已保存到数据文件")

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

    def build_game_stats_html(self, stats_data):
        """生成今日游玩统计 HTML。"""
        if not stats_data:
            return None

        players = []
        for steam_id, friend_data in stats_data.items():
            games = friend_data.get('games', {})
            total_time = sum(games.values()) if games else 0
            if total_time <= 0:
                continue
            players.append((total_time, friend_data.get('nickname', '未知昵称'), games))

        if not players:
            return None

        players.sort(key=lambda x: x[0], reverse=True)
        max_total = max(total for total, _, _ in players) or 1
        cards = []

        for total_time, nickname, games in players:
            nickname_html = html.escape(nickname)
            total_html = html.escape(self.format_duration(total_time))
            game_rows = []
            for game_name, duration in sorted(games.items(), key=lambda x: x[1], reverse=True):
                width = max(6, min(100, duration / max_total * 100))
                game_html = html.escape(game_name)
                duration_html = html.escape(self.format_duration(duration))
                game_rows.append(f"""<div class="game-line">
  <div class="game-line-top">
    <span>{game_html}</span>
    <strong>{duration_html}</strong>
  </div>
  <div class="meter"><i style="width: {width:.1f}%;"></i></div>
</div>""")

            cards.append(f"""<article class="game-player">
  <div class="player-head">
    <div class="avatar-token">{html.escape(nickname[:1] or '?')}</div>
    <div>
      <div class="player-name">{nickname_html}</div>
      <div class="player-sub">今日总计 {total_html}</div>
    </div>
  </div>
  <div class="game-lines">
    {''.join(game_rows)}
  </div>
</article>""")

        return '<div class="game-grid">' + ''.join(cards) + '</div>'

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

    def get_friend_5e_stats(self):
        """获取好友今天的 5E 战绩统计信息"""
        if not self.friend_5e_daily_stats:
            return None
        return self.friend_5e_daily_stats

    def get_friend_5e_history_stats(self):
        """获取好友的 5E 历史最佳战绩"""
        if not self.friend_5e_history_stats:
            return {}
        return self.friend_5e_history_stats

    def get_friend_official_stats(self):
        """获取好友今天的官匹战绩统计信息"""
        if not self.friend_official_daily_stats:
            return None
        return self.friend_official_daily_stats

    def get_friend_official_history_stats(self):
        """获取好友的官匹历史最佳战绩"""
        if not self.friend_official_history_stats:
            return {}
        return self.friend_official_history_stats
    
    def save_pw_nicknames(self):
        """将获取到的完美平台昵称保存到数据文件的 monitored_friends 中"""
        try:
            data = self.load_config(self.data_path)
            monitored_friends = data.get('monitored_friends', [])
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
                self._update_last_save_time(data)
                self.save_config(data, self.data_path)
                log.info(f"[{datetime.now()}] 完美平台昵称已保存到 {self.data_path}")
        except Exception as e:
            log.info(f"[{datetime.now()}] 保存完美平台昵称失败: {e}")

    def save_5e_profiles(self, resolved_updates: dict):
        """将解析到的 5E 用户信息保存到 monitored_friends。"""
        if not resolved_updates:
            return
        try:
            data = self.load_config(self.data_path)
            monitored_friends = data.get('monitored_friends', [])
            changed = False
            for friend in monitored_friends:
                if not isinstance(friend, dict):
                    continue
                steamid = str(friend.get('steamid', ''))
                resolved = resolved_updates.get(steamid)
                if not resolved:
                    continue
                mapping = {
                    'fivee_nickname': resolved.get('username', ''),
                    'fivee_domain': resolved.get('domain', ''),
                    'fivee_uuid': resolved.get('uuid', ''),
                    'fivee_avatar': resolved.get('avatar', ''),
                }
                for key, value in mapping.items():
                    if value and friend.get(key) != value:
                        friend[key] = value
                        changed = True
            if changed:
                self._update_last_save_time(data)
                self.save_config(data, self.data_path)
                log.info(f"[{datetime.now()}] 5E 用户信息已保存到 {self.data_path}")
        except Exception as e:
            log.info(f"[{datetime.now()}] 保存 5E 用户信息失败: {e}")

    def save_history_stats(self):
        """保存历史战绩统计到数据文件"""
        try:
            config = self.load_config(self.data_path)
            config['friend_pw_history_stats'] = self.friend_pw_history_stats
            self._update_last_save_time(config)
            self.save_config(config, self.data_path)
            log.info(f"[{datetime.now()}] 历史战绩统计已保存到 {self.data_path}")
        except Exception as e:
            log.info(f"[{datetime.now()}] 保存历史战绩统计失败: {e}")

    def save_5e_history_stats(self):
        """保存 5E 历史战绩统计到数据文件"""
        try:
            config = self.load_config(self.data_path)
            config['friend_5e_history_stats'] = self.friend_5e_history_stats
            self._update_last_save_time(config)
            self.save_config(config, self.data_path)
            log.info(f"[{datetime.now()}] 5E 历史战绩统计已保存到 {self.data_path}")
        except Exception as e:
            log.info(f"[{datetime.now()}] 保存 5E 历史战绩统计失败: {e}")

    def save_official_history_stats(self):
        """保存官匹历史战绩统计到数据文件"""
        try:
            config = self.load_config(self.data_path)
            config['friend_official_history_stats'] = self.friend_official_history_stats
            self._update_last_save_time(config)
            self.save_config(config, self.data_path)
            log.info(f"[{datetime.now()}] 官匹历史战绩统计已保存到 {self.data_path}")
        except Exception as e:
            log.info(f"[{datetime.now()}] 保存官匹历史战绩统计失败: {e}")

    def _clean_news_cache(self):
        """清理超过 30 天的缓存"""
        if not self.cached_news_gids:
            return
        now_ts = time.time()
        expired_days = 30 * 24 * 3600  # 30 天
        expired_gids = [
            gid for gid, ts in self.cached_news_gids.items()
            if (now_ts - ts) > expired_days
        ]
        for gid in expired_gids:
            del self.cached_news_gids[gid]
        if expired_gids:
            log.info(f"[{datetime.now()}] 清理了 {len(expired_gids)} 条过期新闻缓存")

    def _trim_news_cache(self):
        """限制缓存数量最多 100 条，超出时删除最旧的（timestamp 最小的）"""
        if len(self.cached_news_gids) <= 100:
            return
        # 按 timestamp 排序（升序），删除最旧的直到 <= 100
        sorted_gids = sorted(self.cached_news_gids.keys(), key=lambda g: self.cached_news_gids[g])
        excess = len(self.cached_news_gids) - 100
        for gid in sorted_gids[:excess]:
            del self.cached_news_gids[gid]
        log.info(f"[{datetime.now()}] 缓存超量，删除了 {excess} 条最旧记录")

    def save_news_cache(self):
        """保存新闻缓存到数据文件"""
        try:
            config = self.load_config(self.data_path)
            config['cached_news_gids'] = self.cached_news_gids
            self._update_last_save_time(config)
            self.save_config(config, self.data_path)
            log.info(f"[{datetime.now()}] 新闻缓存已保存到 {self.data_path}")
        except Exception as e:
            log.info(f"[{datetime.now()}] 保存新闻缓存失败: {e}")

    def _update_last_save_time(self, config):
        """更新配置的 last_update 时间戳"""
        config['last_update'] = time.time()

    def save_leaderboard(self):
        """保存排行榜持有者到数据文件"""
        try:
            config = self.load_config(self.data_path)
            config['friend_pw_leaderboard'] = self.friend_pw_leaderboard
            self._update_last_save_time(config)
            self.save_config(config, self.data_path)
            log.info(f"[{datetime.now()}] 排行榜数据已保存到 {self.data_path}")
        except Exception as e:
            log.info(f"[{datetime.now()}] 保存排行榜数据失败: {e}")

    def reset_pw_season_records(self):
        """归档并清空完美平台赛季历史极值和排行榜。"""
        cleared_history_players = len(self.friend_pw_history_stats or {})
        cleared_leaderboard_categories = len(self.friend_pw_leaderboard or {})

        try:
            archive_path = archive_pw_season_data(self.data_path)
            log.info(f"[{datetime.now()}] 完美赛季数据已归档至 {archive_path}")

            with _config_lock:
                config = {}
                if Path(self.data_path).exists():
                    with open(self.data_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                config['friend_pw_history_stats'] = {}
                config['friend_pw_leaderboard'] = {}
                self._update_last_save_time(config)
                with open(self.data_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)

            self.friend_pw_history_stats = {}
            self.friend_pw_leaderboard = {}
            log.info(
                f"[{datetime.now()}] 完美赛季统计已清空: "
                f"history={cleared_history_players}, leaderboard={cleared_leaderboard_categories}, "
                f"archive={archive_path}"
            )
            return {
                "cleared_history_players": cleared_history_players,
                "cleared_leaderboard_categories": cleared_leaderboard_categories,
                "archived_to": archive_path,
                "message": f"完美赛季统计已清空，已归档至 {archive_path}"
            }
        except Exception as e:
            log.info(f"[{datetime.now()}] 清空完美赛季统计失败: {e}")
            raise

    def reset_5e_season_records(self):
        """归档并清空 5E 赛季历史极值。"""
        cleared_history_players = len(self.friend_5e_history_stats or {})

        try:
            archive_path = archive_pw_season_data(self.data_path)
            log.info(f"[{datetime.now()}] 5E 赛季数据已归档至 {archive_path}")

            with _config_lock:
                config = {}
                if Path(self.data_path).exists():
                    with open(self.data_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                config['friend_5e_history_stats'] = {}
                self._update_last_save_time(config)
                with open(self.data_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)

            self.friend_5e_history_stats = {}
            log.info(
                f"[{datetime.now()}] 5E 赛季统计已清空: "
                f"history={cleared_history_players}, "
                f"archive={archive_path}"
            )
            return {
                "cleared_history_players": cleared_history_players,
                "archived_to": archive_path,
                "message": f"5E 赛季统计已清空，已归档至 {archive_path}"
            }
        except Exception as e:
            log.info(f"[{datetime.now()}] 清空 5E 赛季统计失败: {e}")
            raise

    def reset_official_season_records(self):
        """归档并清空官匹赛季历史极值。"""
        cleared_history_players = len(self.friend_official_history_stats or {})

        try:
            archive_path = archive_pw_season_data(self.data_path)
            log.info(f"[{datetime.now()}] 官匹赛季数据已归档至 {archive_path}")

            with _config_lock:
                config = {}
                if Path(self.data_path).exists():
                    with open(self.data_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                config['friend_official_history_stats'] = {}
                self._update_last_save_time(config)
                with open(self.data_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)

            self.friend_official_history_stats = {}
            log.info(
                f"[{datetime.now()}] 官匹赛季统计已清空: "
                f"history={cleared_history_players}, "
                f"archive={archive_path}"
            )
            return {
                "cleared_history_players": cleared_history_players,
                "archived_to": archive_path,
                "message": f"官匹赛季统计已清空，已归档至 {archive_path}"
            }
        except Exception as e:
            log.info(f"[{datetime.now()}] 清空官匹赛季统计失败: {e}")
            raise

    def check_and_report_records(self):
        """检查排行榜变化，返回刷新记录的通知消息列表"""
        return self._check_and_report_records(
            history_stats=self.friend_pw_history_stats,
            leaderboard=self.friend_pw_leaderboard,
            categories=SteamAuto.LEADERBOARD_CATEGORIES,
            nickname_field='pw_nickname',
            save_func=self.save_leaderboard,
            platform_label='',
        )

    def _check_and_report_records(self, history_stats, leaderboard, categories, nickname_field, save_func, platform_label=''):
        """检查排行榜变化，返回刷新记录的通知消息列表。"""
        if not history_stats:
            return []

        notifications = []
        valid_players = {
            sid: d for sid, d in history_stats.items()
            if d.get('max_kills', 0) > 0 or d.get('max_rating', 0) > 0
        }
        if not valid_players:
            return []

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

            best_nick = valid_players[best_sid].get(nickname_field, '未知')
            best_avatar = valid_players[best_sid].get('avatar', '')
            old = leaderboard.get(cat_key)

            if not old or old.get('steamid') != best_sid or old.get('value') != best_val:
                # 记录刷新了
                old_nick = old.get('pw_nickname') or old.get('fivee_nickname') or '未知' if old else None
                old_val = old.get('value') if old else None
                if old and old.get('steamid') != best_sid:
                    notifications.append(f"{emoji} {platform_label}{cat_name}易主！{old_nick}({old_val}) → {best_nick}({best_val})")
                elif old and old.get('value') != best_val:
                    notifications.append(f"{emoji} {platform_label}{cat_name}刷新！{best_nick}: {old_val} → {best_val}")
                elif not old:
                    notifications.append(f"{emoji} {platform_label}{cat_name}诞生！{best_nick} ({best_val})")

                try:
                    is_improvement = True
                    if isinstance(old_val, (int, float)) and isinstance(best_val, (int, float)):
                        is_improvement = (best_val > old_val) if is_max else (best_val < old_val)
                    event_old_val = old_val if old else '-'
                    self.timeline_recorder.record_extreme_change(
                        steamid=best_sid,
                        pw_nickname=best_nick,
                        metric=cat_key,
                        metric_label=f"{platform_label}{cat_name}",
                        metric_emoji=emoji,
                        old_value=event_old_val,
                        new_value=best_val,
                        is_improvement=is_improvement,
                        previous_holder=old_nick if old and old.get('steamid') != best_sid else None,
                    )
                except Exception as e:
                    log.info(f"[{datetime.now()}] 记录排行榜时间轴失败 ({cat_key}): {e}")

                entry = {
                    'steamid': best_sid,
                    'avatar': best_avatar,
                    'value': best_val
                }
                entry[nickname_field] = best_nick
                # Web 时间轴和旧组件默认读 pw_nickname，保留展示兼容。
                entry['pw_nickname'] = best_nick
                leaderboard[cat_key] = entry

        if notifications:
            save_func()

        return notifications

    def format_pw_daily_stats_message(self, pw_stats_data):
        """格式化今日完美平台战绩统计信息"""
        if not pw_stats_data:
            return None
        
        today = datetime.now().strftime("%m月%d日")
        lines = [f"⚔️ 完美平台统计 {today}", ""]

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
            total_stars_change = stats.get('total_stars_change', 0)
            total_kills = stats.get('total_kills', 0)
            total_deaths = stats.get('total_deaths', 0)
            total_assists = stats.get('total_assists', 0)
            total_rating = stats.get('total_rating', 0.0)
            total_we = stats.get('total_we', 0)

            avg_rating = total_rating / match_count if match_count > 0 else 0
            avg_we = total_we / match_count if match_count > 0 else 0
            kd = total_kills / total_deaths if total_deaths > 0 else total_kills

            score_sign = '+' if total_score_change >= 0 else ''
            stars_sign = '+' if total_stars_change >= 0 else ''
            score_summary = f"分数{score_sign}{total_score_change}  ⭐{stars_sign}{total_stars_change}"
            win_rate = wins / match_count * 100 if match_count > 0 else 0

            # 胜率颜色指示
            wr_emoji = '🟢' if win_rate >= 60 else ('🟡' if win_rate >= 40 else '🔴')

            lines.append(f"👤 {nickname}  {match_count}场")
            if draws > 0:
                lines.append(f"  {wr_emoji} {wins}胜{losses}负{draws}平 ({win_rate:.0f}%)  {score_summary}")
            else:
                lines.append(f"  {wr_emoji} {wins}胜{losses}负 ({win_rate:.0f}%)  {score_summary}")
            lines.append(f"  K/D: {kd:.1f}  RT: {avg_rating:.2f}  WE: {avg_we:.1f}")
            lines.append("")

        if len(lines) <= 2:
            return None

        return "\n".join(lines)

    # 旧版文字排行榜 formatter 保留，后续如需恢复“直接发送文本”的状态，
    # 可将下面整段取消注释，并替换当前的 format_pw_leaderboard_message。
    #
    # def format_pw_leaderboard_message(self, history_stats_data):
    #     """格式化完美平台历史战绩排行榜（紧凑版）"""
    #     if not history_stats_data:
    #         return None
    #
    #     valid_players = {sid: d for sid, d in history_stats_data.items()
    #                     if d.get('max_kills', 0) > 0 or d.get('max_rating', 0) > 0 or d.get('max_we', 0) > 0}
    #     if not valid_players:
    #         return None
    #
    #     # 定义排行榜类别（只保留 max 类，最低数据类别已屏蔽播报）
    #     categories = [
    #         ('🔫 击杀王',   'max_kills',   True,  '杀'),
    #         ('💀 唐宋八大家','max_deaths', True,  '死'),
    #         ('👑 RT 之神',   'max_rating',  True,  ''),
    #         ('⚡ PW RT 之神','max_pw_rating',True, ''),
    #         ('💪 WE 之神',   'max_we',      True,  ''),
    #         ('🎖️ 得分王',   'max_score',   True,  '分'),
    #     ]
    #     # 旧版（含 min 类，恢复时取消注释）:
    #     # categories = [
    #     #     ('🔫 击杀王',   'max_kills',   True,  '杀'),
    #     #     ('🤪 精神支持', 'min_kills',   False, '杀'),
    #     #     ('💀 唐宋八大家','max_deaths', True,  '死'),
    #     #     ('🦎 怯战蜥蜴', 'min_deaths',  False, '死'),
    #     #     ('👑 RT 之神',   'max_rating',  True,  ''),
    #     #     ('🧸 吉祥物',   'min_rating',  False, ''),
    #     #     ('⚡ PW RT 之神','max_pw_rating',True, ''),
    #     #     ('❓ 纯路人',   'min_pw_rating',False, ''),
    #     #     ('💪 WE 之神',   'max_we',      True,  ''),
    #     #     ('😅 不懂装懂', 'min_we',      False, ''),
    #     #     ('🎖️ 得分王',   'max_score',   True,  '分'),
    #     #     ('🗑️ 吊车尾',   'min_score',   False, '分'),
    #     # ]
    #
    #     lines = ["🏆 历史战绩排行榜", ""]
    #     # 按顺序定义每组包含的 emoji，每个元素是一个 emoji 列表
    #     # 只有在组的首个 emoji 出现时才切换组（避免屏蔽的 emoji 导致的错误分组）
    #     category_groups = [
    #         ['🔫'],      # 击杀类
    #         ['💀'],      # 死亡类
    #         ['👑'],      # Rating 类
    #         ['⚡'],      # PW Rating
    #         ['💪'],      # WE 类
    #         ['🎯'],      # 得分类
    #     ]
    #     # 旧版（含 min 类的完整分组）:
    #     # category_groups = [
    #     #     ['🔫', '🤪'],      # 击杀类
    #     #     ['💀', '🦎'],      # 死亡类
    #     #     ['👑', '🧸'],      # Rating 类
    #     #     ['⚡' , '❓'],      # PW Rating
    #     #     ['💪', '😅'],      # WE 类
    #     #     ['🎯', '🗑️'],      # 得分类
    #     # ]
    #
    #     current_group = 0
    #     for label, field, is_max, unit in categories:
    #         emoji = label.split()[0]
    #
    #         # 检查是否需要切换到下一组
    #         while current_group < len(category_groups) and emoji not in category_groups[current_group]:
    #             current_group += 1
    #             if current_group < len(category_groups):
    #                 lines.append("")  # 在组之间添加空行
    #
    #         if is_max:
    #             candidates = [(sid, d.get(field, 0)) for sid, d in valid_players.items() if d.get(field, 0) > 0]
    #             if not candidates:
    #                 continue
    #             best_sid, best_val = max(candidates, key=lambda x: x[1])
    #         else:
    #             candidates = [(sid, d.get(field, 9999)) for sid, d in valid_players.items() if 0 < d.get(field, 9999) < 9999]
    #             if not candidates:
    #                 continue
    #             best_sid, best_val = min(candidates, key=lambda x: x[1])
    #
    #         nick = valid_players[best_sid].get('pw_nickname', '?')
    #         val_str = f"{best_val:.2f}" if isinstance(best_val, float) and not unit else str(int(best_val))
    #         lines.append(f"  {label}  {nick} {val_str}{unit}")
    #
    #     if len(lines) <= 2:
    #         return None
    #
    #     return "\n".join(lines)

    def _get_pw_leaderboard_rows(self, history_stats_data):
        """整理完美平台历史战绩排行榜数据。"""
        if not history_stats_data:
            return []

        valid_players = {sid: d for sid, d in history_stats_data.items()
                        if d.get('max_kills', 0) > 0 or d.get('max_rating', 0) > 0 or d.get('max_we', 0) > 0}
        if not valid_players:
            return []

        categories = [
            {'code': 'K', 'name': '击杀王', 'field': 'max_kills', 'is_max': True, 'unit': '杀', 'tone': 'red'},
            {'code': 'k', 'name': '精神支持', 'field': 'min_kills', 'is_max': False, 'unit': '杀', 'tone': 'red'},
            {'code': 'D', 'name': '唐宋八大家', 'field': 'max_deaths', 'is_max': True, 'unit': '死', 'tone': 'slate'},
            {'code': 'd', 'name': '怯战蜥蜴', 'field': 'min_deaths', 'is_max': False, 'unit': '死', 'tone': 'slate'},
            {'code': 'RT', 'name': 'RT 之神', 'field': 'max_rating', 'is_max': True, 'unit': '', 'tone': 'blue'},
            {'code': 'rt', 'name': '团队吉祥物', 'field': 'min_rating', 'is_max': False, 'unit': '', 'tone': 'blue'},
            {'code': 'PR', 'name': 'PW RT 之神', 'field': 'max_pw_rating', 'is_max': True, 'unit': '', 'tone': 'violet'},
            {'code': 'pr', 'name': '纯路人', 'field': 'min_pw_rating', 'is_max': False, 'unit': '', 'tone': 'violet'},
            {'code': 'WE', 'name': 'WE 之神', 'field': 'max_we', 'is_max': True, 'unit': '', 'tone': 'teal'},
            {'code': 'we', 'name': '不懂装懂', 'field': 'min_we', 'is_max': False, 'unit': '', 'tone': 'teal'},
            {'code': 'S', 'name': '得分王', 'field': 'max_score', 'is_max': True, 'unit': '分', 'tone': 'amber'},
            {'code': 's', 'name': '吊车尾', 'field': 'min_score', 'is_max': False, 'unit': '分', 'tone': 'amber'},
        ]

        rows = []
        for category in categories:
            field = category['field']
            if category['is_max']:
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
            unit = category['unit']
            val_str = f"{best_val:.2f}" if isinstance(best_val, float) and not unit else str(int(best_val))
            rows.append({
                **category,
                'nickname': nick,
                'value': val_str,
            })

        return rows

    def format_pw_leaderboard_message(self, history_stats_data):
        """格式化完美平台历史战绩排行榜（文本降级版）"""
        rows = self._get_pw_leaderboard_rows(history_stats_data)
        if not rows:
            return None

        lines = ["历史战绩排行榜"]
        for row in rows:
            lines.append(f"{row['code']:>2}  {row['name']}  {row['nickname']} {row['value']}{row['unit']}")

        return "\n".join(lines)

    def build_pw_daily_stats_html(self, pw_stats_data):
        """生成今日完美平台战绩 HTML。"""
        if not pw_stats_data:
            return None

        cards = []
        sorted_friends = sorted(
            pw_stats_data.items(),
            key=lambda x: (x[1].get('match_count', 0), x[1].get('wins', 0)),
            reverse=True,
        )

        for steam_id, stats in sorted_friends:
            match_count = stats.get('match_count', 0)
            if match_count == 0:
                continue

            nickname = html.escape(stats.get('pw_nickname', '未知好友'))
            wins = stats.get('wins', 0)
            losses = stats.get('losses', 0)
            draws = stats.get('draws', 0)
            total_score_change = stats.get('total_score_change', 0)
            total_stars_change = stats.get('total_stars_change', 0)
            total_kills = stats.get('total_kills', 0)
            total_deaths = stats.get('total_deaths', 0)
            total_rating = stats.get('total_rating', 0.0)
            total_we = stats.get('total_we', 0)

            kd = total_kills / total_deaths if total_deaths > 0 else total_kills
            avg_rating = total_rating / match_count if match_count else 0
            avg_we = total_we / match_count if match_count else 0
            win_rate = wins / match_count * 100 if match_count else 0
            score_sign = '+' if total_score_change >= 0 else ''
            stars_sign = '+' if total_stars_change >= 0 else ''
            tone = 'good' if win_rate >= 60 else ('mid' if win_rate >= 40 else 'bad')
            record = f"{wins}胜{losses}负"
            if draws > 0:
                record += f"{draws}平"

            cards.append(f"""<article class="pw-player">
  <div class="pw-top">
    <div>
      <div class="player-name">{nickname}</div>
      <div class="player-sub">{match_count} 场对局</div>
    </div>
    <div class="win-pill {tone}">{win_rate:.0f}%</div>
  </div>
  <div class="record-line">{record}<span>分数 {score_sign}{total_score_change}</span><span>星 {stars_sign}{total_stars_change}</span></div>
  <div class="stat-strip">
    <div><span>K/D</span><strong>{kd:.1f}</strong></div>
    <div><span>RT</span><strong>{avg_rating:.2f}</strong></div>
    <div><span>WE</span><strong>{avg_we:.1f}</strong></div>
  </div>
</article>""")

        if not cards:
            return None

        return '<div class="pw-grid">' + ''.join(cards) + '</div>'

    def format_5e_daily_stats_message(self, fivee_stats_data):
        """格式化今日 5E 战绩统计信息"""
        if not fivee_stats_data:
            return None

        today = datetime.now().strftime("%m月%d日")
        lines = [f"⚔️ 5E 平台统计 {today}", ""]
        sorted_friends = sorted(fivee_stats_data.items(), key=lambda x: x[1].get('match_count', 0), reverse=True)

        for _, stats in sorted_friends:
            match_count = stats.get('match_count', 0)
            if match_count == 0:
                continue
            nickname = stats.get('fivee_nickname', '未知好友')
            wins = stats.get('wins', 0)
            losses = stats.get('losses', 0)
            draws = stats.get('draws', 0)
            total_elo_change = stats.get('total_elo_change', 0.0)
            total_kills = stats.get('total_kills', 0)
            total_deaths = stats.get('total_deaths', 0)
            total_rating = stats.get('total_rating', 0.0)
            total_rws = stats.get('total_rws', 0.0)
            total_adr = stats.get('total_adr', 0.0)

            avg_rating = total_rating / match_count if match_count else 0
            avg_rws = total_rws / match_count if match_count else 0
            avg_adr = total_adr / match_count if match_count else 0
            kd = total_kills / total_deaths if total_deaths > 0 else total_kills
            win_rate = wins / match_count * 100 if match_count else 0
            wr_emoji = '🟢' if win_rate >= 60 else ('🟡' if win_rate >= 40 else '🔴')
            elo_sign = '+' if total_elo_change >= 0 else ''

            lines.append(f"👤 {nickname}  {match_count}场")
            if draws > 0:
                lines.append(f"  {wr_emoji} {wins}胜{losses}负{draws}平 ({win_rate:.0f}%)  ELO {elo_sign}{total_elo_change:.2f}")
            else:
                lines.append(f"  {wr_emoji} {wins}胜{losses}负 ({win_rate:.0f}%)  ELO {elo_sign}{total_elo_change:.2f}")
            lines.append(f"  K/D: {kd:.1f}  RT: {avg_rating:.2f}  RWS: {avg_rws:.2f}  ADR: {avg_adr:.1f}")
            lines.append("")

        if len(lines) <= 2:
            return None
        return "\n".join(lines)

    def build_5e_daily_stats_html(self, fivee_stats_data):
        """生成今日 5E 战绩 HTML。"""
        if not fivee_stats_data:
            return None

        cards = []
        sorted_friends = sorted(
            fivee_stats_data.items(),
            key=lambda x: (x[1].get('match_count', 0), x[1].get('wins', 0)),
            reverse=True,
        )

        for _, stats in sorted_friends:
            match_count = stats.get('match_count', 0)
            if match_count == 0:
                continue

            nickname = html.escape(stats.get('fivee_nickname', '未知好友'))
            wins = stats.get('wins', 0)
            losses = stats.get('losses', 0)
            draws = stats.get('draws', 0)
            total_elo_change = stats.get('total_elo_change', 0.0)
            total_kills = stats.get('total_kills', 0)
            total_deaths = stats.get('total_deaths', 0)
            total_rating = stats.get('total_rating', 0.0)
            total_rws = stats.get('total_rws', 0.0)

            kd = total_kills / total_deaths if total_deaths > 0 else total_kills
            avg_rating = total_rating / match_count if match_count else 0
            avg_rws = total_rws / match_count if match_count else 0
            win_rate = wins / match_count * 100 if match_count else 0
            elo_sign = '+' if total_elo_change >= 0 else ''
            tone = 'good' if win_rate >= 60 else ('mid' if win_rate >= 40 else 'bad')
            record = f"{wins}胜{losses}负"
            if draws > 0:
                record += f"{draws}平"

            cards.append(f"""<article class="pw-player">
  <div class="pw-top">
    <div>
      <div class="player-name">{nickname}</div>
      <div class="player-sub">{match_count} 场对局</div>
    </div>
    <div class="win-pill {tone}">{win_rate:.0f}%</div>
  </div>
  <div class="record-line">{record}<span>ELO {elo_sign}{total_elo_change:.2f}</span><span>RWS {avg_rws:.2f}</span></div>
  <div class="stat-strip">
    <div><span>K/D</span><strong>{kd:.1f}</strong></div>
    <div><span>RT</span><strong>{avg_rating:.2f}</strong></div>
  </div>
</article>""")

        if not cards:
            return None
        return '<div class="pw-grid">' + ''.join(cards) + '</div>'

    def format_official_daily_stats_message(self, official_stats_data):
        """格式化今日官匹战绩统计信息"""
        if not official_stats_data:
            return None

        today = datetime.now().strftime("%m月%d日")
        lines = [f"⚔️ 官匹平台统计 {today}", ""]
        sorted_friends = sorted(official_stats_data.items(), key=lambda x: x[1].get('match_count', 0), reverse=True)

        for _, stats in sorted_friends:
            match_count = stats.get('match_count', 0)
            if match_count == 0:
                continue
            nickname = stats.get('official_nickname', '未知好友')
            wins = stats.get('wins', 0)
            losses = stats.get('losses', 0)
            draws = stats.get('draws', 0)
            total_kills = stats.get('total_kills', 0)
            total_deaths = stats.get('total_deaths', 0)
            total_rating = stats.get('total_rating', 0.0)
            total_pw_rating = stats.get('total_pw_rating', 0.0)
            total_we = stats.get('total_we', 0)

            avg_rating = total_rating / match_count if match_count else 0
            avg_pw_rating = total_pw_rating / match_count if match_count else 0
            avg_we = total_we / match_count if match_count else 0
            kd = total_kills / total_deaths if total_deaths > 0 else total_kills
            win_rate = wins / match_count * 100 if match_count else 0
            wr_emoji = '🟢' if win_rate >= 60 else ('🟡' if win_rate >= 40 else '🔴')

            lines.append(f"👤 {nickname}  {match_count}场")
            if draws > 0:
                lines.append(f"  {wr_emoji} {wins}胜{losses}负{draws}平 ({win_rate:.0f}%)")
            else:
                lines.append(f"  {wr_emoji} {wins}胜{losses}负 ({win_rate:.0f}%)")
            lines.append(f"  K/D: {kd:.1f}  RT: {avg_rating:.2f}  pwRT: {avg_pw_rating:.2f}  WE: {avg_we:.1f}")
            lines.append("")

        if len(lines) <= 2:
            return None
        return "\n".join(lines)

    def build_official_daily_stats_html(self, official_stats_data):
        """生成今日官匹战绩 HTML。"""
        if not official_stats_data:
            return None

        cards = []
        sorted_friends = sorted(
            official_stats_data.items(),
            key=lambda x: (x[1].get('match_count', 0), x[1].get('wins', 0)),
            reverse=True,
        )

        for _, stats in sorted_friends:
            match_count = stats.get('match_count', 0)
            if match_count == 0:
                continue

            nickname = html.escape(stats.get('official_nickname', '未知好友'))
            wins = stats.get('wins', 0)
            losses = stats.get('losses', 0)
            draws = stats.get('draws', 0)
            total_kills = stats.get('total_kills', 0)
            total_deaths = stats.get('total_deaths', 0)
            total_rating = stats.get('total_rating', 0.0)
            total_we = stats.get('total_we', 0)

            kd = total_kills / total_deaths if total_deaths > 0 else total_kills
            avg_rating = total_rating / match_count if match_count else 0
            avg_we = total_we / match_count if match_count else 0
            win_rate = wins / match_count * 100 if match_count else 0
            tone = 'good' if win_rate >= 60 else ('mid' if win_rate >= 40 else 'bad')
            record = f"{wins}胜{losses}负"
            if draws > 0:
                record += f"{draws}平"

            cards.append(f"""<article class="pw-player">
  <div class="pw-top">
    <div>
      <div class="player-name">{nickname}</div>
      <div class="player-sub">{match_count} 场对局</div>
    </div>
    <div class="win-pill {tone}">{win_rate:.0f}%</div>
  </div>
  <div class="record-line">{record}</div>
  <div class="stat-strip">
    <div><span>K/D</span><strong>{kd:.1f}</strong></div>
    <div><span>RT</span><strong>{avg_rating:.2f}</strong></div>
    <div><span>WE</span><strong>{avg_we:.1f}</strong></div>
  </div>
</article>""")

        if not cards:
            return None
        return '<div class="pw-grid">' + ''.join(cards) + '</div>'

    def build_pw_leaderboard_html(self, history_stats_data):
        """生成完美平台历史战绩排行榜 HTML。"""
        rows = self._get_pw_leaderboard_rows(history_stats_data)
        if not rows:
            return None

        def build_metric_card(row):
            code = html.escape(row['code'])
            name = html.escape(row['name'])
            nick = html.escape(row['nickname'])
            value = html.escape(row['value'])
            unit = html.escape(row['unit'])
            tone = html.escape(row['tone'], quote=True)
            return f"""<div class="leaderboard-row pair-card tone-{tone}">
  <div class="metric-code">{code}</div>
  <div class="metric-main">
    <div class="metric-line">
      <span class="metric-name">{name}</span>
      <span class="metric-holder">{nick}</span>
    </div>
  </div>
  <div class="metric-value"><span>{value}</span>{unit}</div>
</div>"""

        pair_html = []
        for pair_index in range(0, len(rows), 2):
            max_row = rows[pair_index]
            min_row = rows[pair_index + 1] if pair_index + 1 < len(rows) else None
            right_card = build_metric_card(min_row) if min_row else '<div></div>'
            pair_html.append(f"""<div class="leaderboard-pair">
  <div class="pair-num">{pair_index // 2 + 1:02d}</div>
  {build_metric_card(max_row)}
  {right_card}
</div>""")

        return '<div class="leaderboard-grid leaderboard-paired">' + "\n".join(pair_html) + '</div>'

    def render_combined_daily_stats_image(self, sections: list, prefix: str = "daily_report") -> str:
        """将多个每日统计区块渲染为一张 PNG，返回图片路径。"""
        from playwright.sync_api import sync_playwright

        valid_sections = [
            section for section in sections
            if section.get('body') or section.get('body_html')
        ]
        if not valid_sections:
            raise ValueError("日报内容为空，无法生成图片")

        out_dir = Path(self.data_path).parent / "generated" / "daily_stats"
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_prefix = re.sub(r"[^A-Za-z0-9_-]+", "_", prefix).strip("_") or "daily_stats"
        out_path = out_dir / f"{safe_prefix}.png"

        for old_path in out_dir.glob(f"{safe_prefix}*.png"):
            if old_path != out_path:
                try:
                    old_path.unlink()
                except Exception as e:
                    log.debug(f"[{datetime.now()}] 清理旧日报图片失败: {old_path} {e}")

        report_title = f"每日统计日报 {datetime.now().strftime('%Y-%m-%d')}"
        html_content = self._build_daily_stats_html(report_title, valid_sections)

        errors = []
        with sync_playwright() as playwright:
            browser = None
            launch_options = [
                {"channel": "msedge", "headless": True},
                {"channel": "chrome", "headless": True},
                {"headless": True},
            ]
            for options in launch_options:
                try:
                    browser = playwright.chromium.launch(**options)
                    break
                except Exception as e:
                    label = options.get("channel", "bundled chromium")
                    errors.append(f"{label}: {e}")
            if not browser:
                raise RuntimeError("Playwright 浏览器启动失败；" + " | ".join(errors))

            try:
                page = browser.new_page(
                    viewport={"width": 900, "height": 1200},
                    device_scale_factor=2,
                )
                page.set_content(html_content, wait_until="domcontentloaded")
                card = page.locator("#daily-card")
                card.wait_for(state="visible", timeout=5000)
                card.screenshot(path=str(out_path), omit_background=False)
            finally:
                browser.close()

        return str(out_path)

    def render_daily_stats_image(self, message: str, prefix: str) -> str:
        """兼容旧调用：单个统计区块也走合并模板。"""
        lines = message.strip("\n").splitlines()
        title = lines[0] if lines else "每日统计"
        body = "\n".join(lines[1:]).strip("\n")
        return self.render_combined_daily_stats_image([{
            'title': title,
            'body': body,
            'badge': 'Daily',
            'accent': '#2563eb',
        }], prefix)

    def _build_daily_stats_html(self, report_title: str, sections: list) -> str:
        title_html = html.escape(report_title)
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        section_html = "\n".join(self._build_daily_stats_section_html(section) for section in sections)
        template_path = Path(__file__).parent / "templates" / "daily_stats_card.html"
        template = template_path.read_text(encoding="utf-8")
        return (
            template
            .replace("{{REPORT_TITLE}}", title_html)
            .replace("{{GENERATED_AT}}", generated_at)
            .replace("{{SECTIONS}}", section_html)
        )

    def _build_daily_stats_section_html(self, section: dict) -> str:
        title_html = html.escape(section.get('title', '每日统计'))
        body_html = html.escape(section.get('body', ''))
        raw_body_html = section.get('body_html')
        badge_html = html.escape(section.get('badge', 'Daily'))
        accent = html.escape(section.get('accent', '#2563eb'), quote=True)
        class_name = html.escape(section.get('class_name', ''), quote=True)
        section_class = f"section {class_name}".strip()
        body_block = raw_body_html if raw_body_html else f'<pre class="section-body">{body_html}</pre>'
        return f"""<section class="{section_class}" style="--accent: {accent};">
  <div class="section-head">
    <h2 class="section-title">{title_html}</h2>
    <span class="badge">{badge_html}</span>
  </div>
  {body_block}
</section>"""

    def send_daily_stats_image(self, sections: list, prefix: str = "daily_report") -> None:
        """生成合并每日统计图片并入队发送；失败时降级发送合并文本。"""
        try:
            image_path = self.render_combined_daily_stats_image(sections, prefix)
            self.send_file(image_path)
        except Exception as e:
            log.info(f"[{datetime.now()}] 生成每日统计图片失败，改为发送文本：{e}")
            fallback = "\n\n".join(
                f"{section.get('title', '每日统计')}\n{section.get('body', '')}".strip()
                for section in sections
                if section.get('body')
            )
            if fallback:
                self.send_message(fallback)

    def reset_daily_stats(self):
        """重置每日游玩统计（在每天 0 点调用）"""
        log.info(f"[{datetime.now()}] 重置每日游玩统计")
        self.friend_daily_stats = {}
        self.friend_pw_daily_stats = {}
        self.friend_5e_daily_stats = {}
        self.friend_official_daily_stats = {}

    def send_daily_stats(self):
        """发送每日游玩统计（日报 + 排行榜，分条发送）"""
        log.info(f"[{datetime.now()}] 执行每日统计任务...")
        sections = []
        
        # 1. Steam 今日游玩时长
        try:
            stats_data = self.get_friend_game_stats()
            if stats_data:
                msg = self.format_game_stats_message(stats_data)
                if msg:
                    # 旧版文字发送逻辑保留：
                    # self.send_message(msg)
                    # time.sleep(1)  # 间隔 1 秒避免消息太快
                    lines = msg.strip("\n").splitlines()
                    stats_html = self.build_game_stats_html(stats_data)
                    sections.append({
                        'title': '好友今日游玩统计',
                        'body': "\n".join(lines[1:]).strip("\n"),
                        'body_html': stats_html,
                        'badge': 'Steam',
                        'accent': '#2563eb',
                        'class_name': 'section-full section-steam',
                    })
        except Exception as e:
            log.info(f"[{datetime.now()}] Steam 统计失败：{e}")
        
        # 2. 平台今日战绩（完美 + 5E + 官匹，合并展示）
        combined_parts = []
        try:
            pw_stats_data = self.get_friend_pw_stats()
            if pw_stats_data:
                pw_html = self.build_pw_daily_stats_html(pw_stats_data)
                if pw_html:
                    combined_parts.append(
                        '<div class="platform-sub"><span style="background:#14b8a6"></span>完美平台</div>'
                        + pw_html
                    )
        except Exception as e:
            log.info(f"[{datetime.now()}] 完美平台统计失败：{e}")

        try:
            fivee_stats_data = self.get_friend_5e_stats()
            if fivee_stats_data:
                fivee_html = self.build_5e_daily_stats_html(fivee_stats_data)
                if fivee_html:
                    combined_parts.append(
                        '<div class="platform-sub"><span style="background:#7c3aed"></span>5E 平台</div>'
                        + fivee_html
                    )
        except Exception as e:
            log.info(f"[{datetime.now()}] 5E 平台统计失败：{e}")

        try:
            official_stats_data = self.get_friend_official_stats()
            if official_stats_data:
                official_html = self.build_official_daily_stats_html(official_stats_data)
                if official_html:
                    combined_parts.append(
                        '<div class="platform-sub"><span style="background:#ef4444"></span>官匹</div>'
                        + official_html
                    )
        except Exception as e:
            log.info(f"[{datetime.now()}] 官匹统计失败：{e}")

        if combined_parts:
            sections.append({
                'title': '平台战绩统计',
                'body': '',
                'body_html': ''.join(combined_parts),
                'badge': 'Platforms',
                'accent': '#14b8a6',
                'class_name': 'section-full section-pw',
            })

        # 3. 完整历史排行榜
        try:
            history_stats_data = self.get_friend_pw_history_stats()
            if history_stats_data:
                # 旧版文字发送逻辑保留：
                # msg = self.format_pw_leaderboard_message(history_stats_data)
                # if msg:
                #     self.send_message(msg)
                leaderboard_html = self.build_pw_leaderboard_html(history_stats_data)
                if leaderboard_html:
                    fallback_lines = (self.format_pw_leaderboard_message(history_stats_data) or '').splitlines()
                    sections.append({
                        'title': '历史战绩排行榜',
                        'body': "\n".join(fallback_lines[1:]).strip("\n"),
                        'body_html': leaderboard_html,
                        'badge': 'Leaderboard',
                        'accent': '#f59e0b',
                        'class_name': 'section-full section-leaderboard',
                    })
        except Exception as e:
            log.info(f"[{datetime.now()}] 排行榜生成失败：{e}")

        if sections:
            self.send_daily_stats_image(sections, "daily_report")

        self.reset_daily_stats()
        log.info(f"[{datetime.now()}] 每日统计任务完成")

    def daily_update_tasks(self):
        """封装每天需要执行的任务集合。

        包含：发送每日统计、清理/刷新需要每天更新的缓存或计数器等。
        如需添加其他每日任务，可在此处扩展。
        """
        # 维护时间检查：避免在 00:15-08:00 发送消息，但仍执行非发送类维护任务。
        skip_send = False
        try:
            from core import check_maintenance
            if check_maintenance():
                log.info(f"[{datetime.now()}] 当前在维护时段，跳过每日统计发送")
                skip_send = True
        except (ImportError, AttributeError):
            pass
        
        log.info(f"[{datetime.now()}] 执行每日更新任务...")
        if skip_send:
            self.reset_daily_stats()
        else:
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
        if self.code_update_lines and not self.debug:
            log.info(f"[{datetime.now()}] 准备发送启动更新消息")
            msg = "\n".join(self.code_update_lines).replace('{version}', APP_VERSION)
            self.send_message(msg)
            log.info(f"[{datetime.now()}] 启动更新消息已加入队列")
            # 等待一小段时间让主线程处理队列
            time.sleep(2)
        
        check_interval = int(self.check_interval) if isinstance(self.check_interval, (int, float, str)) else 60
        log.info(f"[{datetime.now()}] [cs-Solidarity v{APP_VERSION}] 程序启动")
        log.info(f"[{datetime.now()}] 将每 {check_interval} 秒检查一次好友游戏状态")
        log.info(f"[{datetime.now()}] 目标 Steam ID: {self.steam_id}")
        log.info(f"[{datetime.now()}] 每天 23:55 将发送好友游玩统计")
        log.info(f"[{datetime.now()}] 每天 23:55 将发送日报+完整排行榜")
        
        # 初始化一次，获取当前状态
        self.check_status_changes()
        
        # 设置定时任务：每 check_interval 秒检查一次好友游戏状态变化
        schedule.every(check_interval).seconds.do(self.check_status_changes)
        
        # 设置每日定时任务：每天 23:55 执行每日更新任务
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
