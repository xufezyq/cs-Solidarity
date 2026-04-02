"""
Web API — Bot 控制（仅 admin）
"""

from fastapi import APIRouter, Depends, HTTPException

from web.auth import User, require_admin
from web.bridge import bridge

router = APIRouter(prefix="/api/control", tags=["控制"])


@router.post("/bot/start")
async def start_bot(current_user: User = Depends(require_admin)):
    """启动 bot"""
    result = await bridge.send_request("bot.start")
    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "Agent 请求失败"))
    return {"success": True, "data": result.get("data", {})}


@router.post("/bot/stop")
async def stop_bot(current_user: User = Depends(require_admin)):
    """停止 bot"""
    result = await bridge.send_request("bot.stop")
    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "Agent 请求失败"))
    return {"success": True, "data": result.get("data", {})}


@router.post("/bot/restart")
async def restart_bot(current_user: User = Depends(require_admin)):
    """重启 bot"""
    result = await bridge.send_request("bot.restart", timeout=30)
    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "Agent 请求失败"))
    return {"success": True, "data": result.get("data", {})}


@router.get("/bot/pid")
async def get_bot_pid(current_user: User = Depends(require_admin)):
    """获取 bot 进程 PID"""
    result = await bridge.send_request("status.overview")
    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "Agent 请求失败"))
    data = result.get("data", {})
    return {
        "success": True,
        "data": {
            "pid": data.get("bot_pid"),
            "running": data.get("bot_running", False),
        }
    }
