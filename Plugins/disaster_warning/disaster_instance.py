"""
灾害预警实例封装
将 AstrBot 的 disaster_warning 插件适配到 cs-Solidarity 框架
"""

import asyncio
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

# 添加插件路径到 sys.path（使用绝对路径避免导入问题）
_plugin_dir = Path(__file__).resolve().parent  # Plugins/disaster_warning/
_plugins_root = _plugin_dir.parent  # Plugins/
_project_root = _plugins_root.parent  # cs-Solidarity 项目根目录

# 添加到 sys.path（如果尚未添加）
if str(_plugins_root) not in sys.path:
    sys.path.insert(0, str(_plugins_root))
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from core.base_instance import BaseInstance
from core import wechat_instance

log = logging.getLogger(__name__)

# 数据目录
DATA_DIR = Path(__file__).parent.parent / "data" / "disaster_warning"
DATA_DIR.mkdir(parents=True, exist_ok=True)


class ConfigDict(dict):
    """支持属性赋值的 dict，用于挂载 save_config 等方法"""
    pass


class DisasterWarningInstance(BaseInstance):
    """灾害预警实例 - 封装 disaster_warning 插件到 cs-Solidarity"""

    def __init__(
        self,
        config: dict[str, Any],
        plugin_root: str = None,
        config_path: str = None
    ):
        """
        初始化灾害预警实例

        Args:
            config: 实例配置字典
            plugin_root: 插件根目录路径
            config_path: 配置文件路径（用于持久化保存）
        """
        self.config = config
        self.config_path = config_path
        self.plugin_root = Path(plugin_root) if plugin_root else Path(__file__).parent
        self.running = False
        self._service = None
        self._service_thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._service_task: asyncio.Task | None = None
        self._web_server = None

        # 微信群列表（用于命令响应广播）- 兼容 cs-Solidarity
        self.wechat_groups = config.get("wechat_groups", ["文件传输助手"])

        # target_sessions 缺省时回退到 wechat_groups（告警推送目标）
        if "target_sessions" not in config:
            config["target_sessions"] = list(self.wechat_groups)

        # 让 config 对象支持 save_config（Web 端修改配置后可持久化）
        if config_path:
            _abs_path = str(Path(config_path).resolve())
            def _save_config():
                import json as _json
                try:
                    with open(_abs_path, 'w', encoding='utf-8') as _f:
                        _json.dump(config, _f, ensure_ascii=False, indent=2)
                    log.info(f"[灾害预警] 配置已保存到 {_abs_path}")
                except Exception as e:
                    log.error(f"[灾害预警] 保存配置失败: {e}")
            config.save_config = _save_config

        # 管理员用户列表
        self.admin_users = set(config.get("admin_users", []))

        # 遥测开关
        self.telemetry_enabled = config.get("telemetry_config", {}).get("enabled", False)

        log.info(f"[灾害预警] 实例初始化完成，插件目录: {self.plugin_root}")

    def send_message(self, message: str):
        """
        发送消息到目标会话

        注意：此方法在 start_instances 中会被替换为入队函数。
        灾害预警服务本身会管理自己的消息发送，这里主要用于命令响应等场景。
        """
        if not message or not message.strip():
            return

        for session in self.wechat_groups:
            try:
                wechat_instance.send_message(message, session)
                log.debug(f"[灾害预警] 消息已发送到: {session}")
            except Exception as e:
                log.error(f"[灾害预警] 发送消息到 {session} 失败: {e}")

    def start(self):
        """启动灾害预警服务"""
        if self.running:
            log.warning("[灾害预警] 服务已在运行中")
            return

        # 降低 aiosqlite 的日志级别，减少数据库操作日志
        logging.getLogger('aiosqlite').setLevel(logging.WARNING)

        log.info("[灾害预警] 正在启动灾害预警服务...")

        # 检查是否启用
        if not self.config.get("enabled", True):
            log.info("[灾害预警] 插件已禁用，跳过启动")
            return

        self.running = True

        # 在独立线程中运行 asyncio 服务
        self._service_thread = threading.Thread(
            target=self._run_service,
            daemon=True,
            name="DisasterWarningService"
        )
        self._service_thread.start()

        log.info("[灾害预警] 灾害预警服务已在后台线程启动")

    def _run_service(self):
        """在独立线程中运行 asyncio 服务"""
        try:
            # 创建新的事件循环
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            # 调度启动协程（不要用 run_until_complete，它会在协程完成后关闭 loop，
            # 导致 aiosqlite 等库的后台线程报错 "Event loop is closed"）
            self._loop.create_task(self._start_service())
            self._loop.run_forever()

        except Exception as e:
            log.error(f"[灾害预警] 服务运行出错: {e}")
            import traceback
            log.error(traceback.format_exc())
        finally:
            if self._loop and not self._loop.is_closed():
                self._loop.close()

    async def _start_service(self):
        """异步启动服务"""
        try:
            # 延迟导入避免循环依赖
            from .core.app.disaster_service import get_disaster_service, stop_disaster_service
            from .core.network.web_server import WebAdminServer

            # 创建适配器来替代 AstrBot context
            context_adapter = ContextAdapter(self)

            # 获取并启动服务
            self._service = await get_disaster_service(self.config, context_adapter)

            log.info("[灾害预警] 核心服务初始化完成")

            # 启动 Web 管理端
            if self.config.get("web_admin", {}).get("enabled", False):
                print("[灾害预警] 正在启动 Web 管理端...", flush=True)
                self._web_server = WebAdminServer(self._service, self.config)
                self._service.web_admin_server = self._web_server
                await self._web_server.start()
                print("[灾害预警] Web 管理端启动完成", flush=True)

            # 将服务启动托管给 asyncio task（避免 run_until_complete 提前退出导致 uvicorn 被取消）
            self._service_task = asyncio.create_task(self._service.start())

        except Exception as e:
            log.error(f"[灾害预警] 启动服务失败: {e}")
            import traceback
            log.error(traceback.format_exc())

    def _stop_loop(self):
        """停止事件循环（从另一线程调用）"""
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)

    async def _stop_service(self):
        """异步停止服务"""
        try:
            # 停止 Web 管理端
            if self._web_server:
                await self._web_server.stop()
                log.info("[灾害预警] Web 管理端已停止")

            # 停止灾害预警服务
            if self._service:
                await self._service.stop()
                log.info("[灾害预警] 核心服务已停止")

            # 停止事件循环
            self._stop_loop()

        except Exception as e:
            log.error(f"[灾害预警] 停止服务失败: {e}")
            import traceback
            log.error(traceback.format_exc())

    def handle_message(self, chat_name: str, message: Any):
        """
        处理接收到的消息

        Args:
            chat_name: 消息来源（群名或好友名）
            message: 消息内容
        """
        # 解析消息内容
        content = ""
        sender = ""

        if hasattr(message, 'content'):
            content = message.content
            sender = getattr(message, 'sender', '')
        elif isinstance(message, (list, tuple)):
            sender = message[0] if len(message) > 0 else ''
            content = message[1] if len(message) > 1 else ''
        else:
            content = str(message)

        # 过滤非文本消息
        if not isinstance(content, str):
            return

        # 过滤自己发送的消息
        if sender == 'Self':
            return

        log.debug(f"[灾害预警] 收到消息: {chat_name} - {sender}: {content}")

        # 处理灾害预警命令
        if content.startswith("/灾害预警"):
            self._handle_disaster_command(chat_name, sender, content)
        elif content.startswith("/地震列表查询"):
            self._handle_earthquake_list_command(chat_name, sender, content)
        elif content.startswith("/地震预警"):
            self._handle_eew_command(chat_name, sender, content)
        elif content.startswith("/气象预警"):
            self._handle_weather_command(chat_name, sender, content)
        elif content.startswith("/灾害预警统计"):
            self._handle_stats_command(chat_name, sender, content)

    def _handle_disaster_command(self, chat_name: str, sender: str, content: str):
        """处理灾害预警命令"""
        cmd = content.strip()

        if cmd == "/灾害预警" or cmd == "/灾害预警帮助":
            help_text = """🚨 灾害预警插件使用说明

📋 可用命令：
• /灾害预警 - 显示此帮助信息
• /灾害预警状态 - 查看服务运行状态
• /灾害预警重连 - 强制重连所有数据源 (仅管理员)
• /地震列表查询 [数据源] [数量] - 查询最新地震列表
• /地震预警查询 - 查询各机构 EEW 状态
• /气象预警查询 <省份/地名|全国> [预警类型] [预警颜色]
• /灾害预警统计 - 查看事件统计报告

更多信息可参考 README 文档"""
            self.send_message(help_text)

        elif cmd == "/灾害预警状态":
            self._send_status(chat_name)

        elif cmd == "/灾害预警重连":
            if not self._is_admin(sender):
                self.send_message("🚫 权限不足：此命令仅限管理员使用。")
                return
            self._reconnect_sources(chat_name)

        else:
            # 未知子命令
            self.send_message(f"未知命令: {cmd}\n输入 /灾害预警 查看帮助")

    def _handle_earthquake_list_command(self, chat_name: str, sender: str, content: str):
        """处理地震列表查询命令"""
        self.send_message("🔍 地震列表查询功能正在开发中...")

    def _handle_eew_command(self, chat_name: str, sender: str, content: str):
        """处理地震预警查询命令"""
        self.send_message("🔍 地震预警查询功能正在开发中...")

    def _handle_weather_command(self, chat_name: str, sender: str, content: str):
        """处理气象预警查询命令"""
        self.send_message("🔍 气象预警查询功能正在开发中...")

    def _handle_stats_command(self, chat_name: str, sender: str, content: str):
        """处理统计命令"""
        self.send_message("📊 统计功能正在开发中...")

    def _send_status(self, chat_name: str):
        """发送服务状态"""
        status_parts = ["📊 灾害预警服务状态\n"]

        status_parts.append(f"运行状态: {'✅ 运行中' if self.running else '❌ 已停止'}")
        status_parts.append(f"微信群: {len(self.wechat_groups)} 个")
        status_parts.append(f"数据源: 配置中...")

        self.send_message("\n".join(status_parts))

    def _reconnect_sources(self, chat_name: str):
        """重连所有数据源"""
        self.send_message("🔄 正在重连所有离线数据源...")

        # TODO: 调用服务的重连方法
        # if self._service:
        #     asyncio.create_task(self._service.reconnect_all_sources())

    def _is_admin(self, user_id: str) -> bool:
        """检查用户是否为管理员"""
        return user_id in self.admin_users

    @classmethod
    def create_from_config(cls, config_path: str):
        """从配置文件创建实例"""
        import json

        if not Path(config_path).exists():
            raise FileNotFoundError(f"配置文件 {config_path} 不存在")

        with open(config_path, 'r', encoding='utf-8') as f:
            config = ConfigDict(json.load(f))

        # 插件根目录位于 Plugins/disaster_warning/
        plugin_root = Path(__file__).parent

        return cls(config=config, plugin_root=str(plugin_root), config_path=str(config_path))

    @classmethod
    def create_from_data(cls, data: dict):
        """从字典数据创建实例"""
        if not isinstance(data, dict):
            raise TypeError("DisasterWarningInstance.create_from_data 需要传入字典数据")

        # 如果 data 包含 'config' 键，说明使用了配置文件引用
        config_path = None
        if 'config' in data and isinstance(data.get('config'), str):
            config_path = data['config']
            if Path(config_path).exists():
                import json
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = ConfigDict(json.load(f))
            else:
                # 配置文件不存在，使用 data 本身
                config = ConfigDict(data)
        else:
            config = ConfigDict(data)

        # 插件根目录位于 Plugins/disaster_warning/
        plugin_root = Path(__file__).parent

        return cls(config=config, plugin_root=str(plugin_root), config_path=config_path)


class ContextAdapter:
    """
    AstrBot Context 适配器
    将 cs-Solidarity 的发送机制适配为 AstrBot 的 context.send_message 接口
    """

    def __init__(self, instance: DisasterWarningInstance):
        self._instance = instance

    async def send_message(self, session: str, message_chain):
        """
        发送消息到指定会话

        Args:
            session: 目标会话名称（微信群名）
            message_chain: AstrBot MessageChain 对象或字符串
        """
        if hasattr(message_chain, 'content'):
            content = message_chain.content
        elif hasattr(message_chain, 'as_string'):
            content = message_chain.as_string()
        else:
            content = str(message_chain)

        try:
            wechat_instance.send_message(content, session)
        except Exception as e:
            log.error(f"[灾害预警] 发送消息到 {session} 失败: {e}")

    def get_config(self):
        """返回配置对象（适配 AstrBot 的 get_config）"""
        class ConfigAdapter:
            def __init__(self, data: dict):
                self._data = data

            def get(self, key, default=None):
                return self._data.get(key, default)

        return ConfigAdapter(self._instance.config)
