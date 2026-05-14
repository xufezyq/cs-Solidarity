"""
Web API — 聊天消息
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from web.auth import User, get_current_user
from web.bridge import bridge

router = APIRouter(prefix="/api/chat", tags=["聊天"])


class ChatSendRequest(BaseModel):
    content: str
    sender: Optional[str] = None
    chat_name: Optional[str] = "网页聊天室"
    sync_to_wx: Optional[bool] = True


@router.post("/send")
async def send_message(req: ChatSendRequest, current_user: User = Depends(get_current_user)):
    """发送聊天消息到实例处理"""
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="消息内容不能为空")

    sender = req.sender or current_user.username

    params = {
        "content": req.content,
        "sender": sender,
        "chat_name": req.chat_name or "网页聊天室",
        "sync_to_wx": req.sync_to_wx,
    }
    import logging
    logging.getLogger(__name__).info(f"[API] chat.send params: sync_to_wx={req.sync_to_wx} (type={type(req.sync_to_wx).__name__}), raw_body_sync={req.sync_to_wx}")
    result = await bridge.send_request("chat.send", params, timeout=60)

    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "Agent 请求失败"))
    return {"success": True, "data": result.get("data", {})}


@router.get("/history")
async def get_history(limit: int = 100, current_user: User = Depends(get_current_user)):
    """获取聊天历史"""
    result = await bridge.send_request("chat.history", {"limit": limit})
    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "Agent 请求失败"))
    return {"success": True, "data": result.get("data", {})}
