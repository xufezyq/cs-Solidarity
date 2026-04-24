"""
cs-Solidarity Web Server — Agent 连接桥

管理与 Agent 的 WebSocket 连接，提供请求转发能力。
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import WebSocket

from shared.protocol import make_request, make_ping, parse_message

log = logging.getLogger(__name__)


class AgentBridge:
    """管理 Agent WebSocket 连接"""

    def __init__(self):
        self.agent_ws: Optional[WebSocket] = None
        self.connected_at: Optional[datetime] = None
        self.hostname: str = ""
        self.connection_id: str = ""  # 每次连接的唯一 ID，防止竞态断开
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()
        self._log_subscribers: list = []  # 实例变量，非类变量
        self._file_chunks: Dict[str, Dict[str, Any]] = {}  # download_id -> {chunks, total, filename, file_size}
        self._download_queues: Dict[str, asyncio.Queue] = {}  # download_id -> chunk queue for streaming

    @property
    def is_connected(self) -> bool:
        return self.agent_ws is not None

    async def connect(self, ws: WebSocket, agent_token: str = ""):
        """接受 Agent 连接"""
        async with self._lock:
            # 如果已有连接，断开旧的
            if self.agent_ws:
                try:
                    await self.agent_ws.close(code=1000, reason="新连接替代")
                except Exception:
                    pass
                log.info("已断开旧 Agent 连接")

            self.agent_ws = ws
            self.connected_at = datetime.now()
            self.connection_id = str(uuid.uuid4())  # 生成新连接 ID
            log.info("✅ Agent 已连接")

    async def disconnect(self, conn_id: str = ""):
        """Agent 断开连接

        Args:
            conn_id: 可选的连接 ID。如果提供了且与当前连接 ID 不同，则忽略这次断开请求。
                     这防止了旧连接的 finally 块误断新连接。
        """
        async with self._lock:
            # 安全检查：如果调用者提供了 connection_id，必须匹配当前连接
            if conn_id and conn_id != self.connection_id:
                log.debug(f"忽略旧连接 (conn_id={conn_id[:8]}...) 的断开请求，当前连接为 {self.connection_id[:8]}...")
                return

            self.agent_ws = None
            self.connected_at = None
            self.hostname = ""
            self.connection_id = ""

            # 取消所有待处理的请求
            for req_id, future in self._pending_requests.items():
                if not future.done():
                    future.set_exception(ConnectionError("Agent 已断开"))
            self._pending_requests.clear()

            log.warning("⚠️ Agent 已断开连接")

    async def send_request(self, action: str, params: Dict[str, Any] = None, timeout: float = 15.0) -> Dict[str, Any]:
        """向 Agent 发送请求并等待响应"""
        # 获取连接的引用并加锁，防止并发时 disconnect 将 ws 设为 None
        async with self._lock:
            ws = self.agent_ws
        if not ws:
            return {"success": False, "error": "Agent 未连接"}

        req_id = str(uuid.uuid4())
        future = asyncio.get_event_loop().create_future()
        self._pending_requests[req_id] = future

        try:
            msg = make_request(action, params or {}, req_id)
            await ws.send_text(msg)

            # 等待响应
            result = await asyncio.wait_for(future, timeout=timeout)
            return result

        except asyncio.TimeoutError:
            return {"success": False, "error": f"请求超时（{timeout}s）: {action}"}
        except ConnectionError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": f"请求异常: {e}"}
        finally:
            self._pending_requests.pop(req_id, None)

    async def handle_agent_message(self, raw: str):
        """处理 Agent 发来的消息"""
        msg = parse_message(raw)
        if not msg:
            return

        msg_type = msg.get("type")

        if msg_type == "response":
            # 响应：找到对应的 pending request
            req_id = msg.get("id", "")
            future = self._pending_requests.get(req_id)
            if future and not future.done():
                future.set_result({
                    "success": msg.get("success", False),
                    "data": msg.get("data"),
                    "error": msg.get("error"),
                })
            return

        if msg_type == "push":
            # 推送：广播给所有 WebSocket 日志订阅者
            event = msg.get("event", "")
            data = msg.get("data", {})
            await self._broadcast_push(event, data)
            # 处理文件块推送（流式写入下载队列）
            if event == "file.chunk":
                download_id = data.get("download_id", "_default")
                queue = self._download_queues.get(download_id)
                if queue:
                    chunk_data = data.get("chunk")
                    if chunk_data is None and data.get("chunk_index", 0) < 0:
                        await queue.put(None)
                    else:
                        await queue.put(chunk_data)
            return

        if msg_type == "pong":
            return

    def subscribe_logs(self, ws: WebSocket):
        """添加日志订阅者"""
        self._log_subscribers.append(ws)

    def unsubscribe_logs(self, ws: WebSocket):
        """移除日志订阅者"""
        if ws in self._log_subscribers:
            self._log_subscribers.remove(ws)

    async def _broadcast_push(self, event: str, data: dict):
        """广播推送消息给所有订阅者"""
        msg = json.dumps({"type": "push", "event": event, "data": data}, ensure_ascii=False)
        dead = []
        for ws in self._log_subscribers:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.unsubscribe_logs(ws)

    def get_status(self) -> dict:
        """获取连接状态"""
        return {
            "connected": self.is_connected,
            "connected_at": self.connected_at.isoformat() if self.connected_at else None,
            "hostname": self.hostname,
        }


# 全局单例
bridge = AgentBridge()
