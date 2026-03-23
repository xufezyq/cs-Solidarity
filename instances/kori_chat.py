"""
KoriChat 实例适配器
将 KoriChat 的核心功能封装为 BaseInstance 的子类，集成到当前框架中
"""
import os
import sys
import threading
import time
import logging
from datetime import datetime
from pathlib import Path
from core.base_instance import BaseInstance

# 添加 KoriChat 目录到 Python 路径
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 返回项目根目录
korichat_dir = os.path.join(root_dir, 'KouriChat')

# 将 KouriChat 目录添加到路径，这样可以导入 data、src、modules 等模块
if korichat_dir not in sys.path:
    sys.path.insert(0, korichat_dir)

# 设置日志
logger = logging.getLogger(__name__)


class KoriChatInstance(BaseInstance):
    """
    KoriChat 实例适配器
    将 KoriChat 的消息处理、AI 回复、记忆系统等功能集成到框架中
    """
    
    def __init__(self, config: dict):
        """
        初始化 KoriChat 实例
        
        Args:
            config: 配置字典，包含：
                - config_file: KoriChat 配置文件路径
                - listen_list: 监听的聊天列表
                - avatar_dir: 人设目录
                - group_chat_config: 群聊配置列表
        """
        self.config = config
        self.config_file = config.get('config_file', os.path.join(korichat_dir, 'data', 'config', 'config.json'))
        self.listen_list = config.get('listen_list', [])
        self.avatar_dir = config.get('avatar_dir', None)
        self.group_chat_config = config.get('group_chat_config', None)
        
        # 初始化标志
        self._initialized = False
        self._message_handler = None
        self._image_handler = None
        self._emoji_handler = None
        self._memory_service = None
        self._content_generator = None
        self._image_recognition_service = None
        self._auto_sender = None
        self._wx = None
        
        # 线程相关
        self._stop_event = threading.Event()
        
        print(f"[KoriChat] 实例初始化完成，监听列表：{self.listen_list}, 人设目录：{self.avatar_dir}")
    
    def _initialize_korichat(self):
        """初始化 KoriChat 的核心组件"""
        if self._initialized:
            return
        
        try:
            print("[KoriChat] 开始初始化核心组件...")
            
            # 确保 KoriChat 目录在 Python 路径中
            if korichat_dir not in sys.path:
                sys.path.insert(0, korichat_dir)
                print(f"[KoriChat] 已添加路径：{korichat_dir}")
            
            # 导入 KoriChat 的配置
            from data.config import config as korichat_config
            
            # 更新配置中的监听列表（主框架配置优先）
            if self.listen_list:
                korichat_config.user.listen_list = self.listen_list
                print(f"[KoriChat] 更新监听列表：{self.listen_list}")
            
            # 更新人设目录（主框架配置优先）
            if self.avatar_dir:
                korichat_config.behavior.context.avatar_dir = self.avatar_dir
                print(f"[KoriChat] 更新人设目录：{self.avatar_dir}")
            
            # 更新群聊配置（主框架配置优先）
            if self.group_chat_config is not None:
                korichat_config.user.group_chat_config = self.group_chat_config
                print(f"[KoriChat] 更新群聊配置：{self.group_chat_config}")
            
            # 初始化各个处理器
            from src.handlers.emoji import EmojiHandler
            from src.handlers.image import ImageHandler
            from src.handlers.message import MessageHandler
            from modules.memory.memory_service import MemoryService
            from modules.memory.content_generator import ContentGenerator
            from src.services.ai.image_recognition_service import ImageRecognitionService
            from src.handlers.autosend import AutoSendHandler
            
            # 创建表情符号处理器
            self._emoji_handler = EmojiHandler(root_dir=korichat_dir)
            print("[KoriChat] EmojiHandler 初始化完成")
            
            # 创建图像处理器
            self._image_handler = ImageHandler(
                root_dir=korichat_dir,
                api_key=korichat_config.media.image_recognition.api_key,
                base_url=korichat_config.media.image_recognition.base_url,
                image_model=korichat_config.media.image_recognition.model
            )
            print("[KoriChat] ImageHandler 初始化完成")
            
            # 创建记忆服务
            self._memory_service = MemoryService(
                root_dir=korichat_dir,
                api_key=korichat_config.llm.api_key,
                base_url=korichat_config.llm.base_url,
                model=korichat_config.llm.model,
                max_token=korichat_config.llm.max_tokens,
                temperature=korichat_config.llm.temperature,
                max_groups=korichat_config.behavior.context.max_groups
            )
            print("[KoriChat] MemoryService 初始化完成")
            
            # 创建内容生成器
            self._content_generator = ContentGenerator(
                root_dir=korichat_dir,
                api_key=korichat_config.llm.api_key,
                base_url=korichat_config.llm.base_url,
                model=korichat_config.llm.model,
                max_token=korichat_config.llm.max_tokens,
                temperature=korichat_config.llm.temperature
            )
            print("[KoriChat] ContentGenerator 初始化完成")
            
            # 创建图像识别服务
            self._image_recognition_service = ImageRecognitionService(
                api_key=korichat_config.media.image_recognition.api_key,
                base_url=korichat_config.media.image_recognition.base_url,
                temperature=korichat_config.media.image_recognition.temperature,
                model=korichat_config.media.image_recognition.model
            )
            print("[KoriChat] ImageRecognitionService 初始化完成")
            
            # 获取机器人名称（使用全局微信实例，避免重复初始化）
            robot_name = ""
            try:
                from core.wechat_instance import get_wechat
                # 使用全局单例，避免重复初始化
                wx = get_wechat()
                if wx and hasattr(wx, 'A_MyIcon') and wx.A_MyIcon:
                    robot_name = wx.A_MyIcon.Name
                    self._wx = wx  # 保存引用
                print(f"[KoriChat] 机器人名称：{robot_name}")
            except Exception as e:
                print(f"[KoriChat] 获取机器人名称失败：{e}")
                robot_name = ""
            
            # 读取人设内容
            avatar_dir = os.path.join(korichat_dir, korichat_config.behavior.context.avatar_dir)
            prompt_path = os.path.join(avatar_dir, "avatar.md")
            prompt_content = ""
            if os.path.exists(prompt_path):
                with open(prompt_path, "r", encoding="utf-8") as f:
                    prompt_content = f.read()
                print(f"[KoriChat] 已加载人设：{prompt_path}")
            else:
                print(f"[KoriChat] 警告：人设文件不存在 {prompt_path}")
            
            # 创建消息处理器
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
            print("[KoriChat] MessageHandler 初始化完成")
            
            # 创建主动消息处理器
            self._auto_sender = AutoSendHandler(self._message_handler, korichat_config, self.listen_list)
            print("[KoriChat] AutoSendHandler 初始化完成")
            
            # 启动主动消息倒计时
            self._auto_sender.start_countdown()
            print("[KoriChat] 主动消息倒计时已启动")
            
            self._initialized = True
            print("[KoriChat] 核心组件初始化完成！")
            
        except Exception as e:
            print(f"[KoriChat] 初始化失败：{e}")
            import traceback
            traceback.print_exc()
            raise
    
    def send_message(self, message: str):
        """
        发送消息（由框架调度器调用）
        注意：KoriChat 主要通过消息处理器自动回复，此方法用于主动发送
        """
        if not self._initialized:
            self._initialize_korichat()
        
        try:
            # KoriChat 的消息发送主要通过 message_handler 完成
            # 这里可以添加主动发送逻辑
            print(f"[KoriChat] 主动发送消息：{message[:50]}...")
            
            # 如果有监听列表，发送到第一个聊天
            if self.listen_list:
                chat_id = self.listen_list[0]
                self._message_handler.send_message(
                    content=message,
                    chat_id=chat_id,
                    sender_name="System",
                    is_group=False
                )
                print(f"[KoriChat] 消息已发送到 {chat_id}")
            else:
                print("[KoriChat] 没有可用的聊天对象")
                
        except Exception as e:
            print(f"[KoriChat] 发送消息失败：{e}")
            import traceback
            traceback.print_exc()
    
    def start(self):
        """
        启动 KoriChat（在当前线程中运行，不需要创建额外的微信实例）
        消息的接收和分发由主框架统一处理
        """
        if not self._initialized:
            self._initialize_korichat()
        
        print("[KoriChat] 已启动，等待主框架分发...")
        
        # KoriChat 不再创建独立的消息分发器
        # 消息由主框架统一接收并分发到 handle_message 方法
        
        # 保持运行直到停止事件被设置
        while not self._stop_event.is_set():
            time.sleep(1)
        
        print("[KoriChat] 已停止")
    
    # 注意：_message_dispatcher 方法已移除
    # 消息的接收和分发由主框架统一处理，KoriChat 不再创建独立的微信实例
    # 这样可以避免多个 wxauto 实例冲突
    
    def _is_at_robot(self, content: str) -> bool:
        """
        检查消息是否@机器人
        
        Args:
            content: 消息内容
            
        Returns:
            bool: 是否@机器人
        """
        try:
            # 1. 优先从 wxauto 实例获取机器人名称（最准确）
            from core.wechat_instance import get_wechat, is_using_wxauto
            if is_using_wxauto():
                wx = get_wechat()
                if wx and hasattr(wx, 'A_MyIcon') and wx.A_MyIcon:
                    robot_name = wx.A_MyIcon.Name
                    if robot_name:
                        # 微信@人的格式：@机器人名字\u2005（特殊空格）
                        # 检查是否包含@机器人名字
                        if f"@{robot_name}" in content:
                            return True
            
            # 2. 从 message_handler 获取机器人名称
            if self._message_handler and hasattr(self._message_handler, 'robot_name'):
                robot_name = self._message_handler.robot_name
                if robot_name:
                    if f"@{robot_name}" in content:
                        return True
                    if f"@{robot_name} " in content:
                        return True
            
            # 3. 从人设配置获取机器人名称
            from data.config import config
            if hasattr(config, 'behavior') and hasattr(config.behavior, 'context'):
                avatar_dir = config.behavior.context.avatar_dir
                if avatar_dir:
                    robot_name = os.path.basename(avatar_dir)
                    if robot_name and f"@{robot_name}" in content:
                        return True
            
            return False
            
        except Exception as e:
            print(f"[KoriChat] 检查@机器人失败：{e}")
            return False
    
    def handle_message(self, chat_name: str, message):
        """
        处理接收到的消息（由框架调用）
        
        Args:
            chat_name: 消息来源（群名或好友名）
            message: 消息内容（可能是字符串或消息对象）
        """
        if not self._initialized:
            self._initialize_korichat()
        
        try:
            # 提取消息内容（如果是对象则获取 content 属性）
            if hasattr(message, 'content'):
                content = message.content
                sender = getattr(message, 'sender', chat_name)  # 从消息对象获取发送者
                msg_id = getattr(message, 'id', None)
            elif isinstance(message, str):
                content = message
                sender = chat_name
                msg_id = None
            elif isinstance(message, (list, tuple)) and len(message) >= 2:
                # wxauto 格式：[sender, content, id]
                sender = message[0]
                content = message[1]
                msg_id = message[2] if len(message) > 2 else None
            else:
                content = str(message)
                sender = chat_name
                msg_id = None
            
            # 检查是否在监听列表中
            if self.listen_list and chat_name not in self.listen_list:
                print(f"[KoriChat] 跳过非监听列表用户：{chat_name}")
                return
            
            # KoriChat 区分群聊和私聊的逻辑：
            # 接收窗口名跟发送人一样，代表是私聊，否则是群聊
            # 如果 sender == chat_name，说明是私聊（发送者就是聊天对象）
            # 如果 sender != chat_name，说明是群聊（发送者是群成员，chat_name 是群名）
            is_group = (sender != chat_name)
            
            # 私聊消息默认回复，群聊消息只有在@机器人的时候才回复
            if is_group:
                # 检查群聊消息是否@机器人
                if not self._is_at_robot(content):
                    print(f"[KoriChat] 群聊消息未@机器人，已跳过：{chat_name}")
                    return
                
                # 剔除@机器人名字（KoriChat 原始逻辑）
                # 获取机器人名称用于剔除
                from core.wechat_instance import get_wechat, is_using_wxauto
                robot_name = None
                if is_using_wxauto():
                    wx = get_wechat()
                    if wx and hasattr(wx, 'A_MyIcon') and wx.A_MyIcon:
                        robot_name = wx.A_MyIcon.Name
                
                if not robot_name and self._message_handler and hasattr(self._message_handler, 'robot_name'):
                    robot_name = self._message_handler.robot_name
                
                if robot_name and content:
                    # 剔除@机器人名字（包括特殊空格和普通空格）
                    import re
                    content = re.sub(f'@{robot_name}\u2005', '', content).strip()
                    content = re.sub(f'@{robot_name} ', '', content).strip()
            
            print(f"[KoriChat] 处理消息 - 来源：{chat_name}, 发送者：{sender}, 类型：{'群聊' if is_group else '私聊'}, 内容：{content[:50]}...")
            
            # 调用消息处理器处理
            if self._message_handler:
                # 使用 message_handler 的 handle_user_message 方法
                self._message_handler.handle_user_message(
                    content=content,
                    chat_id=chat_name,
                    sender_name=sender,
                    username=sender,
                    is_group=is_group,
                    is_image_recognition=False
                )
                print(f"[KoriChat] 消息处理完成：{chat_name} (群聊：{is_group})")
            else:
                print(f"[KoriChat] 消息处理器未初始化")
                
        except Exception as e:
            print(f"[KoriChat] 处理消息失败：{e}")
            import traceback
            traceback.print_exc()
    
    def stop(self):
        """停止实例"""
        print("[KoriChat] 停止实例...")
        self._stop_event.set()
        
        # KoriChat 不再创建独立线程，由主框架统一管理
        print("[KoriChat] 实例已停止")
    
    def __del__(self):
        """析构函数，确保线程停止"""
        self.stop()
