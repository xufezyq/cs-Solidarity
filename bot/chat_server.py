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
DEFAULT_PORT = 18765


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

            # 发送响应
            response = json.dumps(result, ensure_ascii=False).encode('utf-8')
            self.request.sendall(len(response).to_bytes(4, 'big') + response)

        except Exception as e:
            log.error(f"处理聊天请求失败: {e}", exc_info=True)
            try:
                error_resp = json.dumps({"success": False, "error": str(e)}, ensure_ascii=False).encode('utf-8')
                self.request.sendall(len(error_resp).to_bytes(4, 'big') + error_resp)
            except Exception:
                pass


class ChatServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Bot 聊天 TCP 服务器"""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, port=DEFAULT_PORT):
        self.port = port
        self._instances_ref = None  # (name, instance) 列表的引用
        self._process_fn = None  # process_web_messages 函数
        self._web_msg_queue = None
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
        # chat.history 由 Agent handler 直接处理（内存），不走 TCP
        return {"success": False, "error": f"未知操作: {action}"}

    def _handle_chat_send(self, params):
        """处理 chat.send：投入 web_msg_queue，等待回复"""
        import queue
        import time
        import json as _json
        from datetime import datetime
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
        timestamp = datetime.now().isoformat()

        # 创建回复队列
        replies_q = queue.Queue()

        self._web_msg_queue.put({
            "content": content,
            "sender": sender,
            "chat_name": chat_name,
            "replies": replies_q,
            "sync_to_wx": params.get("sync_to_wx", True),
        })

        # 等待第一条回复到达（KoriChat 等实例是异步处理的，需要等 API 返回）
        replies = []
        try:
            first_reply = replies_q.get(timeout=60)
            replies.append(first_reply)
            # 短暂等待，收集可能紧随其后的更多回复
            while True:
                try:
                    replies.append(replies_q.get(timeout=1))
                except queue.Empty:
                    break
        except queue.Empty:
            pass  # 超时无回复

        log.info(f"[聊天服务器] 收集到 {len(replies)} 条回复, chat_name={chat_name}")

        return {
            "success": True,
            "data": {
                "message_id": msg_id,
                "replies": replies,
            }
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


def send_chat_to_bot(params, port=DEFAULT_PORT, timeout=65):
    """Agent 端调用：通过 TCP 发送聊天消息到 Bot"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(("127.0.0.1", port))

        msg = json.dumps({"action": "chat.send", "params": params}, ensure_ascii=False).encode('utf-8')
        sock.sendall(len(msg).to_bytes(4, 'big') + msg)

        # 读取响应
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

        return json.loads(data.decode('utf-8'))
    except socket.timeout:
        return {"success": False, "error": f"请求超时（{timeout}s）"}
    except ConnectionRefusedError:
        return {"success": False, "error": "Bot 聊天服务器未启动"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        sock.close()
