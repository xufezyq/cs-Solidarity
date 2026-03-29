
import json
import time
import requests
from pathlib import Path
from datetime import datetime
from core.base_instance import BaseInstance
from core import wechat_instance

class ChatAuto(BaseInstance):
    def __init__(self, api_key, base_url="https://api.deepseek.com", model="deepseek-chat", 
                 system_prompt="", 
                 trigger_prefix="", allowed_users=None, allowed_groups=None):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.system_prompt = system_prompt
        self.trigger_prefix = trigger_prefix
        
        # 允许的用户和群组列表，如果为 None 则不限制
        self.allowed_users = allowed_users if allowed_users else []
        self.allowed_groups = allowed_groups if allowed_groups else []
        
        # 用于去重，避免重复回复同一条消息
        # 简单的内存去重，key为 (chat_name, content, time) 或者 msg_id 如果有
        self.processed_msgs = set()

    def start(self):
        """
        ChatAuto 不需要独立的循环，它依赖主循环的消息分发。
        """
        print(f"[{datetime.now()}] ChatAuto 已启动，监听前缀: {self.trigger_prefix}")
        pass

    def send_message(self, message):
        """这个方法会被主程序替换，用于发送消息"""
        # 如果没有被替换（例如在测试环境中），则直接调用 _real_send_message
        self._real_send_message(message)

    def _real_send_message(self, message_data):
        """
        实际的发送逻辑，由主线程调用
        message_data 可以是字符串（广播给默认列表）或字典（指定目标）
        """
        if isinstance(message_data, dict):
            target = message_data.get("target")
            content = message_data.get("content")
            if target and content:
                try:
                    wechat_instance.send_message(content, target)
                    print(f"[{datetime.now()}] [ChatAuto] 回复 {target}: {content[:20]}...")
                except Exception as e:
                    print(f"[{datetime.now()}] [ChatAuto] 发送失败: {e}")
        else:
            # 兼容旧行为，如果有默认群组的话
            pass

    def handle_message(self, chat_name: str, msg):
        """
        处理接收到的消息
        msg 格式依赖于 wxauto 版本。通常是 [sender, content, id, type] 或对象
        
        注意：此方法只处理以 trigger_prefix（如 @bot）开头的消息
        其他消息会被直接忽略，不会分发给其他实例
        """
        print(f"[DEBUG] [ChatAuto] handle_message 被调用!")
        print(f"[DEBUG] [ChatAuto] 原始参数：chat_name={chat_name}, msg={msg}, msg 类型={type(msg)}")
        
        # 简单的防抖/去重
        # 假设 msg 是一个对象或列表，我们需要提取 content 和 sender
        sender = ""
        content = ""
        msg_id = ""
        
        try:
            # 尝试解析 msg
            # wxauto 3.9.8.15+ 的 msg 可能是 wxauto.elements.WXMessage 对象
            if hasattr(msg, 'content'):
                content = msg.content
                sender = msg.sender
                msg_id = getattr(msg, 'id', str(time.time()))
                print(f"[DEBUG] [ChatAuto] 解析为对象：sender={sender}, content={content}, msg_id={msg_id}")
            elif isinstance(msg, (list, tuple)):
                # 假设格式：[sender, content, id]
                sender = msg[0]
                content = msg[1]
                msg_id = msg[2] if len(msg) > 2 else str(time.time())
                print(f"[DEBUG] [ChatAuto] 解析为列表：sender={sender}, content={content}, msg_id={msg_id}")
            else:
                # 尝试作为字符串处理
                content = str(msg)
                msg_id = str(hash(content))
                print(f"[DEBUG] [ChatAuto] 解析为字符串：content={content}, msg_id={msg_id}")

            # 过滤非文本消息
            if not isinstance(content, str):
                print(f"[DEBUG] [ChatAuto] 过滤非文本消息：content 类型={type(content)}")
                return
            print(f"[DEBUG] [ChatAuto] 通过非文本消息过滤")

            # 过滤自己发送的消息 (sender == 'Self' or 'self')
            if sender == 'Self':
                print(f"[DEBUG] [ChatAuto] 过滤自己发送的消息：sender={sender}")
                return
            print(f"[DEBUG] [ChatAuto] 通过自己消息过滤")

            # 检查权限
            if self.allowed_groups and chat_name not in self.allowed_groups:
                print(f"[DEBUG] [ChatAuto] 群组 {chat_name} 不在允许列表中: {self.allowed_groups}")
                return
            print(f"[DEBUG] [ChatAuto] 通过权限检查")

            # 去重
            unique_key = f"{chat_name}_{msg_id}"
            if unique_key in self.processed_msgs:
                print(f"[DEBUG] [ChatAuto] 消息已处理过，跳过: {unique_key}")
                return
            self.processed_msgs.add(unique_key)
            # 清理旧的 cache，防止无限增长 (简单处理：超过1000条清空)
            if len(self.processed_msgs) > 1000:
                self.processed_msgs.clear()
            print(f"[DEBUG] [ChatAuto] 通过去重检查")

            print(f"[INFO] [ChatAuto] 收到 {chat_name} - {sender}: {content}")

            # 提取真实 prompt
            # 注意：trigger_prefix 可能在消息中间（如 @某人 /claw），需要找到它的位置
            prefix_index = content.find(self.trigger_prefix)
            user_query = content[prefix_index + len(self.trigger_prefix):].strip()
            if not user_query:
                return
            print(f"[DEBUG] [ChatAuto] 提取问题: {user_query}")

            # 调用 LLM
            print(f"[DEBUG] [ChatAuto] 开始调用 LLM API...")
            reply = self.call_llm(user_query)
            print(f"[DEBUG] [ChatAuto] LLM 返回: {reply[:50]}..." if len(reply) > 50 else f"[DEBUG] [ChatAuto] LLM 返回: {reply}")
            
            # 发送回复
            # 注意：这里调用 self.send_message，它已经被 hook 为入队函数
            # 我们传入一个字典，以便在 _real_send_message 中解析目标
            print(f"[DEBUG] [ChatAuto] 准备发送回复到 {chat_name}")
            self.send_message({"target": chat_name, "content": f"@{sender} {reply}"})
            print(f"[DEBUG] [ChatAuto] 消息已加入队列")

        except Exception as e:
            print(f"[ERROR] [ChatAuto] 处理消息出错: {e}")
            import traceback
            traceback.print_exc()

    def call_llm(self, query):
        """调用 OpenAI 兼容的 LLM API（DeepSeek、OpenClaw 等）"""
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            data = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": query}
                ],
                "stream": False
            }
            
            response = requests.post(f"{self.base_url}/chat/completions", headers=headers, json=data)  # timeout=None 无限等待
            
            if response.status_code == 200:
                result = response.json()
                if 'choices' in result and len(result['choices']) > 0:
                    return result['choices'][0]['message']['content'].strip()
                else:
                    return "API 返回了空结果"
            else:
                return f"API 请求失败: {response.status_code} - {response.text}"
        except Exception as e:
            return f"调用 LLM 出错: {e}"

    @classmethod
    def create_from_config(cls, config_path):
        """从配置文件创建实例"""
        # 这里为了简单，假设 config_path 是整个 config dict，或者我们需要加载它
        # 参考 steam_auto 是加载文件，但 instance_factory 传过来的是 dict (如果是在 config.json 中内嵌)
        # 或者 steam_auto 是传 config_path 字符串。
        # 让我们看 instance_factory.py：
        # register_instance_type('steam', lambda data: SteamAuto.create_from_config(data.get('config')))
        # data.get('config') 是一个路径字符串。
        
        # 我们也支持传入路径
        if isinstance(config_path, str):
             if not Path(config_path).exists():
                 raise FileNotFoundError(f"配置文件 {config_path} 不存在")
             with open(config_path, 'r', encoding='utf-8') as f:
                 config = json.load(f)
        else:
            config = config_path if config_path else {}

        return cls(
            api_key=config.get('api_key'),
            base_url=config.get('base_url', "https://api.deepseek.com"),
            model=config.get('model', "deepseek-chat"),
            system_prompt=config.get('system_prompt', ""),
            trigger_prefix=config.get('trigger_prefix', ""),
            allowed_users=config.get('allowed_users', []),
            allowed_groups=config.get('allowed_groups', [])
        )

