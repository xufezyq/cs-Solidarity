"""
KoriChat 实例适配器
将 KoriChat 的核心功能封装为 BaseInstance 的子类，集成到框架中
"""
import os
import sys
import threading
import time
import logging
import json
import re
from datetime import datetime
from pathlib import Path
from core.base_instance import BaseInstance

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
korichat_dir = os.path.join(root_dir, 'KouriChat')

if korichat_dir not in sys.path:
    sys.path.insert(0, korichat_dir)

log = logging.getLogger(__name__)


class KoriChatInstance(BaseInstance):
    """
    KoriChat 实例适配器
    将 KoriChat 的消息处理、AI 回复、记忆系统等功能集成到框架中
    """

    def __init__(self, config: dict):
        self.config = config
        self.config_file = config.get('config_file', os.path.join(korichat_dir, 'data', 'config', 'config.json'))
        self.avatar_dir = config.get('avatar_dir', None)
        self.group_chat_config = config.get('group_chat_config', None)
        self.private_chat_config = config.get('private_chat_config', None)

        self._initialized = False
        self._message_handler = None
        self._image_handler = None
        self._emoji_handler = None
        self._memory_service = None
        self._content_generator = None
        self._image_recognition_service = None
        self._auto_sender = None
        self._wx = None

        self._stop_event = threading.Event()

        log.info("[KoriChat] 实例初始化完成")
        if self.group_chat_config:
            log.info(f"  群聊配置数量：{len(self.group_chat_config)}")
        log.info(f"  人设目录：{self.avatar_dir}")
        if self.private_chat_config:
            log.info(f"  私聊配置数量：{len(self.private_chat_config)}")

    @classmethod
    def create_from_config(cls, config_path: str):
        """从配置文件创建 KoriChat 实例"""
        if not Path(config_path).exists():
            raise FileNotFoundError(f"配置文件 {config_path} 不存在")
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return KoriChatInstance(config=config)

    def _initialize_korichat(self):
        """初始化 KoriChat 的核心组件"""
        if self._initialized:
            return

        try:
            log.info("[KoriChat] 开始初始化核心组件...")

            if korichat_dir not in sys.path:
                sys.path.insert(0, korichat_dir)
                log.debug(f"[KoriChat] 已添加路径：{korichat_dir}")

            from data.config import config as korichat_config

            if self.avatar_dir:
                korichat_config.behavior.context.avatar_dir = self.avatar_dir
                log.debug(f"[KoriChat] 更新人设目录：{self.avatar_dir}")

            if self.group_chat_config is not None:
                from data.config import GroupChatConfigItem
                converted_configs = []
                for config_item in self.group_chat_config:
                    auto_id = f"group_{config_item['groupName']}"
                    converted_configs.append(GroupChatConfigItem(
                        id=auto_id,
                        group_name=config_item['groupName'],
                        avatar=config_item['avatar'],
                        triggers=config_item.get('triggers', []),
                        enable_at_trigger=config_item.get('enableAtTrigger', True),
                        replyMode=config_item.get('replyMode', 'at_only')
                    ))
                korichat_config.user.group_chat_config = converted_configs
                log.info(f"[KoriChat] 更新群聊配置，共 {len(converted_configs)} 个")
                for idx, cfg in enumerate(converted_configs):
                    log.debug(f"  配置 {idx}: group_name={cfg.group_name}, avatar={cfg.avatar}")

            from src.handlers.emoji import EmojiHandler
            from src.handlers.image import ImageHandler
            from src.handlers.message import MessageHandler
            from modules.memory.memory_service import MemoryService
            from modules.memory.content_generator import ContentGenerator
            from src.services.ai.image_recognition_service import ImageRecognitionService
            from src.handlers.autosend import AutoSendHandler

            self._emoji_handler = EmojiHandler(root_dir=korichat_dir)
            log.debug("[KoriChat] EmojiHandler 初始化完成")

            self._image_handler = ImageHandler(
                root_dir=korichat_dir,
                api_key=korichat_config.media.image_recognition.api_key,
                base_url=korichat_config.media.image_recognition.base_url,
                image_model=korichat_config.media.image_recognition.model
            )
            log.debug("[KoriChat] ImageHandler 初始化完成")

            self._memory_service = MemoryService(
                root_dir=korichat_dir,
                api_key=korichat_config.llm.api_key,
                base_url=korichat_config.llm.base_url,
                model=korichat_config.llm.model,
                max_token=korichat_config.llm.max_tokens,
                temperature=korichat_config.llm.temperature,
                max_groups=korichat_config.behavior.context.max_groups
            )
            log.debug("[KoriChat] MemoryService 初始化完成")

            self._content_generator = ContentGenerator(
                root_dir=korichat_dir,
                api_key=korichat_config.llm.api_key,
                base_url=korichat_config.llm.base_url,
                model=korichat_config.llm.model,
                max_token=korichat_config.llm.max_tokens,
                temperature=korichat_config.llm.temperature
            )
            log.debug("[KoriChat] ContentGenerator 初始化完成")

            self._image_recognition_service = ImageRecognitionService(
                api_key=korichat_config.media.image_recognition.api_key,
                base_url=korichat_config.media.image_recognition.base_url,
                temperature=korichat_config.media.image_recognition.temperature,
                model=korichat_config.media.image_recognition.model
            )
            log.debug("[KoriChat] ImageRecognitionService 初始化完成")

            robot_name = ""
            try:
                from core.wechat_instance import get_wechat
                wx = get_wechat()
                if wx and hasattr(wx, 'A_MyIcon') and wx.A_MyIcon:
                    robot_name = wx.A_MyIcon.Name
                    self._wx = wx
                log.info(f"[KoriChat] 机器人名称：{robot_name}")
            except Exception as e:
                log.error(f"[KoriChat] 获取机器人名称失败：{e}")
                robot_name = ""

            avatar_dir = os.path.join(korichat_dir, korichat_config.behavior.context.avatar_dir)
            prompt_path = os.path.join(avatar_dir, "avatar.md")
            prompt_content = ""
            if os.path.exists(prompt_path):
                with open(prompt_path, "r", encoding="utf-8") as f:
                    prompt_content = f.read()
                log.debug(f"[KoriChat] 已加载人设：{prompt_path}")
            else:
                log.warning(f"[KoriChat] 人设文件不存在：{prompt_path}")

            self._message_handler = MessageHandler(
                root_dir=korichat_dir,
                api_key=korichat_config.llm.api_key,
                base_url=korichat_config.llm.base_url,
                model=korichat_config.llm.model,
                max_token=korichat_config.llm.max_tokens,
                temperature=korichat_config.llm.temperature,
                max_groups=korichat_config.behavior.context.max_groups,
                robot_name=robot_name,
                prompt_content=prompt_content,
                image_handler=self._image_handler,
                emoji_handler=self._emoji_handler,
                memory_service=self._memory_service,
                content_generator=self._content_generator
            )
            log.debug("[KoriChat] MessageHandler 初始化完成")

            auto_send_list = []
            if self.group_chat_config:
                for config_item in self.group_chat_config:
                    if config_item.get('replyMode') == 'all':
                        auto_send_list.append(config_item['groupName'])

            self._auto_sender = AutoSendHandler(self._message_handler, korichat_config, auto_send_list)
            log.info(f"[KoriChat] AutoSendHandler 初始化完成，自动发送列表：{auto_send_list}")

            self._auto_sender.start_countdown()
            log.debug("[KoriChat] 主动消息倒计时已启动")

            self._initialized = True
            log.info("[KoriChat] 核心组件初始化完成！")

        except Exception as e:
            log.error(f"[KoriChat] 初始化失败：{e}")
            import traceback
            log.debug(traceback.format_exc())
            raise

    def send_message(self, message: str):
        """发送消息（由框架调度器调用）"""
        if not self._initialized:
            self._initialize_korichat()

        try:
            log.debug(f"[KoriChat] 主动发送消息：{message[:50]}...")
            if self.listen_list:
                chat_id = self.listen_list[0]
                self._message_handler.send_message(
                    content=message, chat_id=chat_id,
                    sender_name="System", is_group=False
                )
                log.info(f"[KoriChat] 消息已发送到 {chat_id}")
            else:
                log.warning("[KoriChat] 没有可用的聊天对象")
        except Exception as e:
            log.error(f"[KoriChat] 发送消息失败：{e}")
            import traceback
            log.debug(traceback.format_exc())

    def start(self):
        """启动 KoriChat"""
        if not self._initialized:
            self._initialize_korichat()

        log.info("[KoriChat] 已启动，等待主框架分发...")

        while not self._stop_event.is_set():
            time.sleep(1)

        log.info("[KoriChat] 已停止")

    def _is_at_robot(self, content: str) -> bool:
        """检查消息是否@机器人"""
        try:
            robot_names = set()

            from core.wechat_instance import get_wechat
            wx = get_wechat()
            if wx and hasattr(wx, 'A_MyIcon') and wx.A_MyIcon:
                robot_name = wx.A_MyIcon.Name
                if robot_name:
                    robot_names.add(robot_name)

            if self._message_handler and hasattr(self._message_handler, 'robot_name'):
                robot_name = self._message_handler.robot_name
                if robot_name:
                    robot_names.add(robot_name)

            from data.config import config
            if hasattr(config, 'behavior') and hasattr(config.behavior, 'context'):
                avatar_dir = config.behavior.context.avatar_dir
                if avatar_dir:
                    robot_name = os.path.basename(avatar_dir)
                    if robot_name:
                        robot_names.add(robot_name)

            if hasattr(config, 'user') and hasattr(config.user, 'group_chat_config'):
                for gc_config in config.user.group_chat_config:
                    if gc_config.avatar:
                        robot_name = os.path.basename(gc_config.avatar)
                        if robot_name:
                            robot_names.add(robot_name)

            common_names = ['ATRI', 'atri', 'Atri', '亚托莉']
            robot_names.update(common_names)

            for name in robot_names:
                at_patterns = [
                    f"@{name}\u2005",
                    f"@{name} ",
                    f"@{name}",
                ]
                for pattern in at_patterns:
                    if pattern in content:
                        log.debug(f"[KoriChat] 检测到@机器人: {name} (匹配: {repr(pattern)})")
                        return True

            log.debug(f"[KoriChat] 未检测到@机器人, 内容: {content[:50]}..., 已知名称: {robot_names}")
            return False

        except Exception as e:
            log.error(f"[KoriChat] 检查@机器人失败：{e}")
            return False

    def handle_message(self, chat_name: str, message):
        """处理接收到的消息（由框架调用）"""
        if not self._initialized:
            self._initialize_korichat()

        try:
            log.debug(f"消息类型: {type(message)}, message={message}")
            if hasattr(message, 'content'):
                content = message.content
                sender = getattr(message, 'sender', chat_name)
                msg_id = getattr(message, 'id', None)
                message_type = type(message).__name__
                log.debug(f"检测到消息对象类型: {message_type}, sender={sender}")
            elif isinstance(message, str):
                content = message
                sender = getattr(message, 'sender', chat_name)
                msg_id = None
                log.debug(f"消息是字符串格式, sender={sender}")
            elif isinstance(message, (list, tuple)) and len(message) >= 2:
                sender = message[0]
                content = message[1]
                msg_id = message[2] if len(message) > 2 else None
                log.debug(f"消息是列表格式: sender={sender}, content={content}")
            else:
                content = str(message)
                sender = chat_name
                msg_id = None
                log.debug("消息是其他格式")

            is_group = (sender != chat_name)
            log.debug(f"判断: chat_name={chat_name}, sender={sender}, is_group={is_group}")

            if is_group:
                from data.config import config
                group_config = None
                reply_mode = None

                if config and hasattr(config, 'user') and config.user.group_chat_config:
                    for gc_config in config.user.group_chat_config:
                        if gc_config.group_name == chat_name:
                            group_config = gc_config
                            reply_mode = getattr(gc_config, 'replyMode', 'at_only')
                            break

                if reply_mode is None:
                    log.debug(f"[KoriChat] 群聊没有配置，已跳过：{chat_name}")
                    return

                if reply_mode == 'all':
                    log.debug("[KoriChat] 群聊配置为回复所有模式，不需要@机器人")
                else:
                    if not self._is_at_robot(content):
                        log.debug(f"[KoriChat] 群聊消息未@机器人，已跳过：{chat_name}")
                        return

                    at_match = re.search(r'@([^\s\u2005]+)(?:[\s\u2005]|$)', content)
                    if at_match:
                        at_name = at_match.group(1)
                        content = re.sub(f'@{at_name}\u2005', '', content).strip()
                        content = re.sub(f'@{at_name} ', '', content).strip()
                        content = re.sub(f'@{at_name}', '', content).strip()
                        log.debug(f"[KoriChat] 已剔除@名字 '{at_name}'，剩余: {content}")

            log.info(f"[KoriChat] 处理消息 - 来源：{chat_name}, 发送者：{sender}, {'群聊' if is_group else '私聊'}, 内容：{content[:50]}...")

            if self._message_handler:
                need_restore = False
                from data.config import config as korichat_config

                if is_group:
                    group_chat_configs = korichat_config.user.group_chat_config if korichat_config else []
                    if group_chat_configs:
                        for idx, gc_config in enumerate(group_chat_configs):
                            log.debug(f"  群聊配置 {idx}: group_name={gc_config.group_name}, avatar={gc_config.avatar}")
                            if gc_config.group_name == chat_name:
                                avatar_path = gc_config.avatar
                                if avatar_path:
                                    log.debug(f"[KoriChat] 群聊 {chat_name} 配置人设：{avatar_path}")
                                    self._message_handler.switch_avatar_temporarily(avatar_path)
                                    need_restore = True
                                break

                elif not is_group and self.private_chat_config:
                    for pc_config in self.private_chat_config:
                        if pc_config.get('friendName') == chat_name:
                            avatar_path = pc_config.get('avatar')
                            if avatar_path:
                                log.debug(f"[KoriChat] 私聊 {chat_name} 配置人设：{avatar_path}")
                                self._message_handler.switch_avatar_temporarily(avatar_path)
                                need_restore = True
                            break

                try:
                    self._message_handler.handle_user_message(
                        content=content, chat_id=chat_name,
                        sender_name=sender, username=sender,
                        is_group=is_group, is_image_recognition=False
                    )
                    log.debug(f"[KoriChat] 消息处理完成：{chat_name} (群聊：{is_group})")
                finally:
                    if need_restore:
                        self._message_handler.restore_default_avatar()
            else:
                log.warning("[KoriChat] 消息处理器未初始化")

        except Exception as e:
            log.error(f"[KoriChat] 处理消息失败：{e}")
            import traceback
            log.debug(traceback.format_exc())

    def stop(self):
        """停止实例"""
        log.info("[KoriChat] 停止实例...")
        self._stop_event.set()
        log.info("[KoriChat] 实例已停止")

    def __del__(self):
        self.stop()
