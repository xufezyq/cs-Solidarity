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
                - avatar_dir: 人设目录
                - group_chat_config: 群聊配置列表
                - private_chat_config: 私聊配置列表
        """
        self.config = config
        self.config_file = config.get('config_file', os.path.join(korichat_dir, 'data', 'config', 'config.json'))
        self.avatar_dir = config.get('avatar_dir', None)
        self.group_chat_config = config.get('group_chat_config', None)
        self.private_chat_config = config.get('private_chat_config', None)
        
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
        
        print(f"[KoriChat] 实例初始化完成")
        if self.group_chat_config:
            print(f"  群聊配置数量：{len(self.group_chat_config)}")
        print(f"  人设目录：{self.avatar_dir}")
        if self.private_chat_config:
            print(f"  私聊配置数量：{len(self.private_chat_config)}")
    
    @classmethod
    def create_from_config(cls, config_path: str):
        """从配置文件创建 KoriChat 实例"""
        if not Path(config_path).exists():
            raise FileNotFoundError(f"配置文件 {config_path} 不存在")

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        return KoriChatInstance(
            config=config
        )
    
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
            
            # 更新人设目录（主框架配置优先）
            if self.avatar_dir:
                korichat_config.behavior.context.avatar_dir = self.avatar_dir
                print(f"[KoriChat] 更新人设目录：{self.avatar_dir}")
            
            # 更新群聊配置（主框架配置优先）
            if self.group_chat_config is not None:
                # 将字典列表转换为 GroupChatConfigItem 对象列表
                from data.config import GroupChatConfigItem
                converted_configs = []
                for config_item in self.group_chat_config:
                    # 自动生成 ID（使用群名）
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
                print(f"[KoriChat] 更新群聊配置：{converted_configs}")
                print(f"[DEBUG] 转换后的群聊配置数量：{len(converted_configs)}")
                for idx, cfg in enumerate(converted_configs):
                    print(f"[DEBUG] 配置 {idx}: group_name={cfg.group_name}, avatar={cfg.avatar}")

            
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
            # 从 group_chat_config 中提取 replyMode 为 all 的群聊列表
            auto_send_list = []
            if self.group_chat_config:
                for config_item in self.group_chat_config:
                    if config_item.get('replyMode') == 'all':
                        auto_send_list.append(config_item['groupName'])
            
            self._auto_sender = AutoSendHandler(self._message_handler, korichat_config, auto_send_list)
            print(f"[KoriChat] AutoSendHandler 初始化完成，自动发送列表：{auto_send_list}")
            
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
            # 获取所有可能的机器人名称
            robot_names = set()
            
            # 1. 优先从 wxauto 实例获取机器人名称（最准确）
            from core.wechat_instance import get_wechat, is_using_wxauto
            if is_using_wxauto():
                wx = get_wechat()
                if wx and hasattr(wx, 'A_MyIcon') and wx.A_MyIcon:
                    robot_name = wx.A_MyIcon.Name
                    if robot_name:
                        robot_names.add(robot_name)
            
            # 2. 从 message_handler 获取机器人名称
            if self._message_handler and hasattr(self._message_handler, 'robot_name'):
                robot_name = self._message_handler.robot_name
                if robot_name:
                    robot_names.add(robot_name)
            
            # 3. 从人设配置获取机器人名称
            from data.config import config
            if hasattr(config, 'behavior') and hasattr(config.behavior, 'context'):
                avatar_dir = config.behavior.context.avatar_dir
                if avatar_dir:
                    robot_name = os.path.basename(avatar_dir)
                    if robot_name:
                        robot_names.add(robot_name)
            
            # 4. 从群聊配置中获取机器人名称（群昵称/备注名）
            if hasattr(config, 'user') and hasattr(config.user, 'group_chat_config'):
                for gc_config in config.user.group_chat_config:
                    if gc_config.avatar:
                        robot_name = os.path.basename(gc_config.avatar)
                        if robot_name:
                            robot_names.add(robot_name)
            
            # 5. 添加常见的机器人昵称（如 ATRI）
            # 这些可能是用户在群里给机器人设置的备注名
            common_names = ['ATRI', 'atri', 'Atri', '亚托莉']
            robot_names.update(common_names)
            
            # 检查消息中是否@了任何一个机器人名称
            # 微信@人格式: @名字\u2005 或 @名字空格
            for name in robot_names:
                # 检查多种可能的格式
                at_patterns = [
                    f"@{name}\u2005",  # 微信特殊空格
                    f"@{name} ",      # 普通空格
                    f"@{name}",       # 无空格（可能在消息开头或结尾）
                ]
                for pattern in at_patterns:
                    if pattern in content:
                        print(f"[KoriChat] 检测到@机器人: {name} (匹配模式: {repr(pattern)})")
                        return True
            
            print(f"[KoriChat] 未检测到@机器人，内容: {content[:50]}..., 已知的机器人名称: {robot_names}")
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
            print(f"[DEBUG] 消息类型: {type(message)}, message={message}")
            if hasattr(message, 'content'):
                content = message.content
                sender = getattr(message, 'sender', chat_name)  # 从消息对象获取发送者
                msg_id = getattr(message, 'id', None)
                
                # 注意：FriendMessage 类型既可能是私聊也可能是群聊
                # 需要根据 sender 和 chat_name 的关系来判断
                message_type = type(message).__name__
                print(f"[DEBUG] 检测到消息对象类型: {message_type}, sender={sender}")
                # 不再强制设置 sender，保持从消息对象中提取的原始值
            elif isinstance(message, str):
                content = message
                sender = chat_name
                msg_id = None
                print(f"[DEBUG] 消息是字符串格式")
            elif isinstance(message, (list, tuple)) and len(message) >= 2:
                # wxauto 格式：[sender, content, id]
                sender = message[0]
                content = message[1]
                msg_id = message[2] if len(message) > 2 else None
                print(f"[DEBUG] 消息是列表格式: sender={sender}, content={content}")
            else:
                content = str(message)
                sender = chat_name
                msg_id = None
                print(f"[DEBUG] 消息是其他格式")
            
            # KoriChat 区分群聊和私聊的逻辑：
            # 接收窗口名跟发送人一样，代表是私聊，否则是群聊
            # 如果 sender == chat_name，说明是私聊（发送者就是聊天对象）
            # 如果 sender != chat_name，说明是群聊（发送者是群成员，chat_name 是群名）
            is_group = (sender != chat_name)
            print(f"[DEBUG] 判断结果: chat_name={chat_name}, sender={sender}, is_group={is_group}")
            
            # 私聊消息默认接收，群聊消息需要检查配置
            if is_group:
                # 检查群聊配置和回复模式
                from data.config import config
                group_config = None
                reply_mode = None  # 默认没有配置
                
                if config and hasattr(config, 'user') and config.user.group_chat_config:
                    for gc_config in config.user.group_chat_config:
                        if gc_config.group_name == chat_name:
                            group_config = gc_config
                            reply_mode = getattr(gc_config, 'replyMode', 'at_only')
                            break
                
                # 如果没有配置，跳过该群聊
                if reply_mode is None:
                    print(f"[KoriChat] 群聊没有配置，已跳过：{chat_name}")
                    return
                
                # 根据回复模式判断是否需要@机器人
                if reply_mode == 'all':
                    # 回复所有模式，不需要@机器人，直接继续处理
                    print(f"[KoriChat] 群聊配置为回复所有模式，不需要@机器人")
                else:
                    # 只回复@模式，检查是否@了机器人
                    if not self._is_at_robot(content):
                        print(f"[KoriChat] 群聊消息未@机器人，已跳过：{chat_name}")
                        return
                    
                    # 剔除@机器人名字
                    # 从消息中提取实际@的名字并清理
                    import re
                    # 匹配@后面的名字（支持特殊空格\u2005和普通空格）
                    at_match = re.search(r'@([^\s\u2005]+)(?:[\s\u2005]|$)', content)
                    if at_match:
                        at_name = at_match.group(1)
                        # 剔除@名字（包括特殊空格和普通空格）
                        content = re.sub(f'@{at_name}\u2005', '', content).strip()
                        content = re.sub(f'@{at_name} ', '', content).strip()
                        content = re.sub(f'@{at_name}', '', content).strip()
                        print(f"[KoriChat] 已剔除@名字 '{at_name}'，剩余内容: {content}")
            
            print(f"[KoriChat] 处理消息 - 来源：{chat_name}, 发送者：{sender}, 类型：{'群聊' if is_group else '私聊'}, 内容：{content[:50]}...")
            
            # 调用消息处理器处理
            if self._message_handler:
                # 检查是否需要根据配置切换人设
                need_restore = False
                
                # 使用 korichat_config 中的配置
                from data.config import config as korichat_config
                
                # 群聊配置
                if is_group:
                    group_chat_configs = korichat_config.user.group_chat_config if korichat_config else []
                    print(f"[DEBUG] is_group={is_group}, group_chat_configs={group_chat_configs}")
                    if group_chat_configs:
                        print(f"[DEBUG] 开始遍历群聊配置，共 {len(group_chat_configs)} 个配置")
                        # 查找当前群聊的配置
                        for idx, gc_config in enumerate(group_chat_configs):
                            print(f"[DEBUG] 配置 {idx}: group_name={gc_config.group_name}, avatar={gc_config.avatar}")
                            if gc_config.group_name == chat_name:
                                avatar_path = gc_config.avatar
                                if avatar_path:
                                    print(f"[KoriChat] 群聊 {chat_name} 配置人设：{avatar_path}")
                                    # 临时切换人设
                                    self._message_handler.switch_avatar_temporarily(avatar_path)
                                    need_restore = True
                                else:
                                    print(f"[DEBUG] 群聊 {chat_name} 配置中 avatar 为空")
                                break
                
                # 私聊配置
                elif not is_group and self.private_chat_config:
                    print(f"[DEBUG] 开始遍历私聊配置，共 {len(self.private_chat_config)} 个配置")
                    # 查找当前私聊对象的配置
                    for pc_config in self.private_chat_config:
                        if pc_config.get('friendName') == chat_name:
                            avatar_path = pc_config.get('avatar')
                            if avatar_path:
                                print(f"[KoriChat] 私聊 {chat_name} 配置人设：{avatar_path}")
                                # 临时切换人设
                                self._message_handler.switch_avatar_temporarily(avatar_path)
                                need_restore = True
                            else:
                                print(f"[DEBUG] 私聊 {chat_name} 配置中 avatar 为空")
                            break
                
                try:
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
                finally:
                    # 恢复默认人设
                    if need_restore:
                        self._message_handler.restore_default_avatar()
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
