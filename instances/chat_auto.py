import json
import time
import logging
import requests
from pathlib import Path
from datetime import datetime
from core.base_instance import BaseInstance
from core import wechat_instance

log = logging.getLogger(__name__)


class ChatAuto(BaseInstance):
    def __init__(self, api_key, base_url="https://api.deepseek.com", model="deepseek-chat",
                 system_prompt="",
                 trigger_prefix="", allowed_users=None, allowed_groups=None,
                 max_history=20):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.system_prompt = system_prompt
        self.trigger_prefix = trigger_prefix

        self.allowed_users = allowed_users if allowed_users else []
        self.allowed_groups = allowed_groups if allowed_groups else []

        # 用于去重，避免重复回复同一条消息
        self.processed_msgs = set()

        # 多用户上下文管理
        self.conversation_histories = {}
        self.max_history = max_history

    def start(self):
        """ChatAuto 不需要独立的循环，它依赖主循环的消息分发。"""
        log.info(f"ChatAuto 已启动，监听前缀: {self.trigger_prefix}")

    def send_message(self, message):
        """这个方法会被主程序替换，用于发送消息"""
        self._real_send_message(message)

    def _real_send_message(self, message_data):
        """实际的发送逻辑，由主线程调用"""
        if isinstance(message_data, dict):
            target = message_data.get("target")
            content = message_data.get("content")
            if target and content:
                try:
                    wechat_instance.send_message(content, target)
                    log.info(f"[ChatAuto] 回复 {target}: {content[:20]}...")
                except Exception as e:
                    log.error(f"[ChatAuto] 发送失败: {e}")

    def handle_message(self, chat_name: str, msg):
        """处理接收到的消息"""
        log.debug(f"[ChatAuto] handle_message: chat_name={chat_name}, msg={msg}, type={type(msg)}")

        sender = ""
        content = ""
        msg_id = ""

        try:
            if hasattr(msg, 'content'):
                content = msg.content
                sender = msg.sender
                msg_id = getattr(msg, 'id', str(time.time()))
                log.debug(f"[ChatAuto] 解析为对象: sender={sender}, content={content}")
            elif isinstance(msg, (list, tuple)):
                sender = msg[0]
                content = msg[1]
                msg_id = msg[2] if len(msg) > 2 else str(time.time())
                log.debug(f"[ChatAuto] 解析为列表: sender={sender}, content={content}")
            else:
                content = str(msg)
                msg_id = str(hash(content))
                log.debug(f"[ChatAuto] 解析为字符串: content={content}")

            # 过滤非文本消息
            if not isinstance(content, str):
                log.debug(f"[ChatAuto] 过滤非文本消息: type={type(content)}")
                return

            # 过滤自己发送的消息
            if sender == 'Self':
                log.debug(f"[ChatAuto] 过滤自己发送的消息: sender={sender}")
                return

            # 检查权限 - 群组
            if self.allowed_groups and chat_name not in self.allowed_groups:
                log.debug(f"[ChatAuto] 群组 {chat_name} 不在允许列表中")
                return

            # 检查权限 - 用户
            if self.allowed_users and sender not in self.allowed_users and sender != 'Self':
                log.debug(f"[ChatAuto] 用户 {sender} 不在允许列表中")
                return

            # 去重
            unique_key = f"{chat_name}_{msg_id}"
            if unique_key in self.processed_msgs:
                log.debug(f"[ChatAuto] 消息已处理过，跳过: {unique_key}")
                return
            self.processed_msgs.add(unique_key)
            if len(self.processed_msgs) > 1000:
                self.processed_msgs.clear()

            log.info(f"[ChatAuto] 收到 {chat_name} - {sender}: {content}")

            # 提取真实 prompt
            prefix_index = content.find(self.trigger_prefix)
            user_query = content[prefix_index + len(self.trigger_prefix):].strip()
            if not user_query:
                return

            # 支持清除上下文命令
            if user_query.lower() in ('clear', 'reset', '重置', '清除上下文', '清除记忆'):
                self.clear_history(chat_name, sender)
                log.info(f"[ChatAuto] 已清除 {sender} 的对话历史")
                self.send_message({"target": chat_name, "content": f"@{sender} ✅ 已清除你的对话上下文"})
                return

            log.debug(f"[ChatAuto] 提取问题: {user_query}")

            # 调用 LLM
            log.debug("[ChatAuto] 开始调用 LLM API...")
            reply = self.call_llm(user_query, chat_name=chat_name, sender=sender)
            log.debug(f"[ChatAuto] LLM 返回: {reply[:80]}")

            # 发送回复
            self.send_message({"target": chat_name, "content": f"@{sender} {reply}"})
            log.debug(f"[ChatAuto] 消息已加入队列")

        except Exception as e:
            log.error(f"[ChatAuto] 处理消息出错: {e}")
            import traceback
            log.debug(traceback.format_exc())

    def _get_history_key(self, chat_name, sender):
        return f"{chat_name}__{sender}"

    def _get_history(self, chat_name, sender):
        key = self._get_history_key(chat_name, sender)
        if key not in self.conversation_histories:
            self.conversation_histories[key] = []
        return self.conversation_histories[key]

    def _add_to_history(self, chat_name, sender, role, content):
        history = self._get_history(chat_name, sender)
        history.append({"role": role, "content": content})
        max_messages = self.max_history * 2
        if len(history) > max_messages:
            self.conversation_histories[chat_name + "__" + sender] = history[-max_messages:]

    def clear_history(self, chat_name=None, sender=None):
        """清除对话历史。不传参数则清除全部。"""
        if chat_name and sender:
            key = self._get_history_key(chat_name, sender)
            self.conversation_histories.pop(key, None)
        elif chat_name:
            keys_to_remove = [k for k in self.conversation_histories if k.startswith(f"{chat_name}__")]
            for k in keys_to_remove:
                del self.conversation_histories[k]
        else:
            self.conversation_histories.clear()

    def call_llm(self, query, chat_name="", sender=""):
        """调用 OpenAI 兼容的 LLM API，支持多用户上下文"""
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            messages = []
            system_content = self.system_prompt
            if sender and chat_name:
                if sender != chat_name:
                    system_content += f"\n\n[系统提示] 当前用户：{sender}，所在群：{chat_name}"
                else:
                    system_content += f"\n\n[系统提示] 当前用户：{sender}（私聊）"

            messages.append({"role": "system", "content": system_content})
            history = self._get_history(chat_name, sender)
            messages.extend(history)
            messages.append({"role": "user", "content": query})

            data = {
                "model": self.model,
                "messages": messages,
                "stream": False
            }

            response = requests.post(f"{self.base_url}/chat/completions", headers=headers, json=data)

            if response.status_code == 200:
                result = response.json()
                if 'choices' in result and len(result['choices']) > 0:
                    reply = result['choices'][0]['message']['content'].strip()
                    self._add_to_history(chat_name, sender, "user", query)
                    self._add_to_history(chat_name, sender, "assistant", reply)
                    return reply
                else:
                    return "API 返回了空结果"
            else:
                return f"API 请求失败: {response.status_code} - {response.text}"
        except Exception as e:
            return f"调用 LLM 出错: {e}"

    @classmethod
    def create_from_config(cls, config_path):
        """从配置文件创建实例"""
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
            allowed_groups=config.get('allowed_groups', []),
            max_history=config.get('max_history', 20)
        )
