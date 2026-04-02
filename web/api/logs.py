"""
Web API — 日志查看
"""

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import Optional

from web.auth import User, get_current_user, decode_token
from web.bridge import bridge

router = APIRouter(tags=["日志"])


@router.get("/api/logs/list")
async def list_logs(current_user: User = Depends(get_current_user)):
    """列出可用日志文件"""
    result = await bridge.send_request("log.list")
    if not result.get("success"):
        return {"success": True, "data": {"files": []}}
    return {"success": True, "data": result.get("data", {})}


@router.get("/api/logs/today")
async def read_today_log(
    level: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = 1,
    page_size: int = 200,
    current_user: User = Depends(get_current_user),
):
    """读取今日日志"""
    from datetime import datetime
    date = datetime.now().strftime("%Y-%m-%d")
    return await _read_log(date, level, keyword, page, page_size)


@router.get("/api/logs/{date}")
async def read_log_by_date(
    date: str,
    level: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = 1,
    page_size: int = 200,
    current_user: User = Depends(get_current_user),
):
    """读取指定日期日志"""
    return await _read_log(date, level, keyword, page, page_size)


async def _read_log(date: str, level: str, keyword: str, page: int, page_size: int):
    """读取日志的通用方法"""
    result = await bridge.send_request("log.read", {
        "date": date,
        "level": level or "",
        "keyword": keyword or "",
        "page": page,
        "page_size": page_size,
    })
    if not result.get("success"):
        return {"success": True, "data": {"lines": [], "total": 0, "date": date}}
    return {"success": True, "data": result.get("data", {})}


@router.websocket("/ws/logs")
async def websocket_logs(ws: WebSocket):
    """WebSocket 实时日志推送"""
    # 从 query 参数获取 token
    token = ws.query_params.get("token", "")
    payload = decode_token(token)
    if not payload:
        await ws.close(code=4001, reason="认证失败")
        return

    await ws.accept()
    bridge.subscribe_logs(ws)
    try:
        while True:
            # 保持连接，等待客户端消息（心跳）
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        bridge.unsubscribe_logs(ws)
