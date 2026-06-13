"""
Bot 端聊天 TCP 服务器

Agent handler 通过 TCP 连接发送聊天消息到 Bot，Bot 处理后返回回复。
使用 socketserver.ThreadingMixIn 实现并发处理。
"""

import json
import socket
import socketserver
import threading
import logging

log = logging.getLogger(__name__)

# 默认端口
DEFAULT_PORT = 18766


class ChatHandler(socketserver.BaseRequestHandler):
    """处理 Agent 的聊天请求"""

    def handle(self):
        try:
            # 读取长度前缀（4 字节 big-endian）
            length_bytes = self.request.recv(4)
            if len(length_bytes) < 4:
                return
            length = int.from_bytes(length_bytes, 'big')
            if length > 1024 * 1024:  # 最大 1MB
                return

            # 读取消息体
            data = b''
            while len(data) < length:
                chunk = self.request.recv(length - len(data))
                if not chunk:
                    return
                data += chunk

            msg = json.loads(data.decode('utf-8'))
            server = self.server
            result = server.process_message(msg)

            # 提取 replies_q（不可序列化），然后从响应中移除
            replies_q = result.pop("_replies_q", None)

            # 发送响应
            response = json.dumps(result, ensure_ascii=False).encode('utf-8')
            self.request.sendall(len(response).to_bytes(4, 'big') + response)

            # 如果是 chat.send 的 pending 响应，保持连接等待异步推送
            if replies_q:
                self._wait_and_push_replies(replies_q)

        except Exception as e:
            log.error(f"处理聊天请求失败: {e}", exc_info=True)
            try:
                error_resp = json.dumps({"success": False, "error": str(e)}, ensure_ascii=False).encode('utf-8')
                self.request.sendall(len(error_resp).to_bytes(4, 'big') + error_resp)
            except Exception:
                pass

    def _wait_and_push_replies(self, replies_q):
        """等待回复并通过 TCP 推送给 Agent"""
        import time
        replies = []
        try:
            # 等待第一条回复（OpenClaw 可能需要几分钟）
            first_reply = replies_q.get(timeout=300)
            replies.append(first_reply)
            # 短暂等待，收集可能紧随其后的更多回复
            while True:
                try:
                    replies.append(replies_q.get(timeout=2))
                except Exception:
                    break
        except Exception:
            pass  # 超时无回复

        if replies:
            push_msg = json.dumps({
                "type": "push",
                "event": "chat.replies",
                "data": {"replies": replies}
            }, ensure_ascii=False).encode('utf-8')
            try:
                self.request.sendall(len(push_msg).to_bytes(4, 'big') + push_msg)
            except Exception:
                log.debug("[聊天服务器] 推送回复失败（Agent 可能已断开）")


class ChatServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Bot 聊天 TCP 服务器"""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, port=DEFAULT_PORT):
        self.port = port
        self._instances_ref = None  # (name, instance) 列表的引用
        self._process_fn = None  # process_web_messages 函数
        self._web_msg_queue = None
        self._steam_reset_lock = threading.Lock()
        super().__init__(("127.0.0.1", port), ChatHandler)

    def set_context(self, instances, process_fn, web_msg_queue):
        """设置处理上下文（实例列表、处理函数、消息队列）"""
        self._instances_ref = instances
        self._process_fn = process_fn
        self._web_msg_queue = web_msg_queue

    def process_message(self, msg):
        """处理聊天消息，返回结果"""
        action = msg.get("action", "")
        if action == "chat.send":
            return self._handle_chat_send(msg.get("params", {}))
        if action == "steam.reset_pw_season_records":
            return self._handle_steam_reset_pw_season_records()
        if action == "steam.reset_5e_season_records":
            return self._handle_steam_reset_5e_season_records()
        # chat.history 由 Agent handler 直接处理（内存），不走 TCP
        return {"success": False, "error": f"未知操作: {action}"}

    def _handle_steam_reset_pw_season_records(self):
        """清空运行中 Steam 实例的完美赛季历史统计和排行榜缓存。"""
        if not self._instances_ref:
            return {"success": False, "error": "Bot 尚未初始化实例"}

        with self._steam_reset_lock:
            for name, inst in self._instances_ref:
                reset_fn = getattr(inst, "reset_pw_season_records", None)
                if callable(reset_fn):
                    data = reset_fn()
                    data["instance"] = name
                    return {"success": True, "data": data}

        return {"success": False, "error": "未找到 Steam 实例"}

    def _handle_steam_reset_5e_season_records(self):
        """清空运行中 Steam 实例的 5E 赛季历史统计。"""
        if not self._instances_ref:
            return {"success": False, "error": "Bot 尚未初始化实例"}

        with self._steam_reset_lock:
            for name, inst in self._instances_ref:
                reset_fn = getattr(inst, "reset_5e_season_records", None)
                if callable(reset_fn):
                    data = reset_fn()
                    data["instance"] = name
                    return {"success": True, "data": data}

        return {"success": False, "error": "未找到 Steam 实例"}

    def _handle_chat_send(self, params):
        """处理 chat.send：投入 web_msg_queue，异步等待回复"""
        import queue
        import time
        import json as _json
        from pathlib import Path

        content = params.get("content", "").strip()
        sender = params.get("sender", "WebUser")
        chat_name = params.get("chat_name", "")

        # 如果没有指定 chat_name，从配置读取目标群
        if not chat_name or chat_name == "网页聊天室":
            try:
                config_path = Path(__file__).resolve().parent.parent / "config.json"
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = _json.load(f)
                chat_name = cfg.get("web_chat", {}).get("target_group", "网页聊天室")
            except Exception:
                chat_name = "网页聊天室"

        if not content:
            return {"success": False, "error": "消息内容不能为空"}

        if not self._web_msg_queue or not self._process_fn:
            return {"success": False, "error": "Bot 尚未初始化"}

        # 记录用户消息
        msg_id = str(time.time()).replace('.', '')[:8]

        # 创建回复队列（拦截器需要它来路由回复）
        replies_q = queue.Queue()

        _sync = params.get("sync_to_wx", True)
        self._web_msg_queue.put({
            "content": content,
            "sender": sender,
            "chat_name": chat_name,
            "replies": replies_q,
            "sync_to_wx": _sync,
        })

        # 立即返回 pending 状态，回复将通过 TCP 异步推送
        log.info(f"[聊天服务器] 消息已入队，等待异步回复: chat_name={chat_name}")

        return {
            "success": True,
            "data": {
                "message_id": msg_id,
                "replies": [],
                "pending": True,
            },
            "_replies_q": replies_q,  # 内部字段，供 ChatHandler 使用
        }


_server_instance = None


def start_chat_server(port=DEFAULT_PORT):
    """启动聊天 TCP 服务器（后台线程）"""
    global _server_instance
    try:
        _server_instance = ChatServer(port)
        thread = threading.Thread(target=_server_instance.serve_forever, daemon=True, name="ChatServer")
        thread.start()
        log.info(f"聊天服务器已启动: 127.0.0.1:{port}")
        return _server_instance
    except OSError as e:
        log.error(f"聊天服务器启动失败（端口 {port} 可能被占用）: {e}")
        return None


def send_action_to_bot(action, params=None, port=DEFAULT_PORT, timeout=65):
    """Agent 端调用：通过 TCP 向 Bot 发送本地 action。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(("127.0.0.1", port))

        msg = json.dumps({"action": action, "params": params or {}}, ensure_ascii=False).encode('utf-8')
        sock.sendall(len(msg).to_bytes(4, 'big') + msg)

        # 读取初始响应
        length_bytes = sock.recv(4)
        if len(length_bytes) < 4:
            return {"success": False, "error": "连接中断"}
        length = int.from_bytes(length_bytes, 'big')

        data = b''
        while len(data) < length:
            chunk = sock.recv(length - len(data))
            if not chunk:
                return {"success": False, "error": "连接中断"}
            data += chunk

        result = json.loads(data.decode('utf-8'))

        # 如果是 pending 状态，等待异步推送的回复
        if result.get("data", {}).get("pending"):
            sock.settimeout(300)  # 5 分钟超时等待回复
            try:
                push_length_bytes = sock.recv(4)
                if push_length_bytes and len(push_length_bytes) >= 4:
                    push_length = int.from_bytes(push_length_bytes, 'big')
                    push_data = b''
                    while len(push_data) < push_length:
                        chunk = sock.recv(push_length - len(push_data))
                        if not chunk:
                            break
                        push_data += chunk

                    push_msg = json.loads(push_data.decode('utf-8'))
                    replies = push_msg.get("data", {}).get("replies", [])
                    result["data"]["replies"] = replies
                    result["data"]["pending"] = False
            except socket.timeout:
                pass  # 超时无回复

        return result
    except socket.timeout:
        return {"success": False, "error": f"请求超时（{timeout}s）"}
    except ConnectionRefusedError:
        return {"success": False, "error": "Bot 聊天服务器未启动"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        sock.close()


def send_chat_to_bot(params, port=DEFAULT_PORT, timeout=65):
    """Agent 端调用：通过 TCP 发送聊天消息到 Bot，支持异步推送回复。"""
    return send_action_to_bot("chat.send", params, port=port, timeout=timeout)
