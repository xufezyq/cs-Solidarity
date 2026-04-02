"""
cs-Solidarity Web 控制面板 - Agent-Server 通信协议定义

消息格式：
- 请求: {"id": "uuid", "type": "request", "action": "xxx", "params": {}}
- 响应: {"id": "uuid", "type": "response", "success": true, "data": {}}
- 推送: {"type": "push", "event": "xxx", "data": {}}
- 心跳: {"type": "ping"} / {"type": "pong"}
"""

import json
import uuid
from typing import Any, Dict, Optional


def make_request(action: str, params: Optional[Dict[str, Any]] = None, req_id: Optional[str] = None) -> str:
    """创建请求消息"""
    msg = {
        "id": req_id or str(uuid.uuid4()),
        "type": "request",
        "action": action,
        "params": params or {}
    }
    return json.dumps(msg)


def make_response(req_id: str, success: bool, data: Optional[Any] = None, error: Optional[str] = None) -> str:
    """创建响应消息"""
    msg = {
        "id": req_id,
        "type": "response",
        "success": success,
        "data": data or {}
    }
    if error:
        msg["error"] = error
    return json.dumps(msg)


def make_push(event: str, data: Optional[Any] = None) -> str:
    """创建推送消息"""
    msg = {
        "type": "push",
        "event": event,
        "data": data or {}
    }
    return json.dumps(msg)


def make_ping() -> str:
    """创建心跳 ping"""
    return json.dumps({"type": "ping"})


def make_pong() -> str:
    """创建心跳 pong"""
    return json.dumps({"type": "pong"})


def parse_message(raw: str) -> Optional[Dict[str, Any]]:
    """解析消息"""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
