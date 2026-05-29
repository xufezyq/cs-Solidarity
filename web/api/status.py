"""
Web API — 状态监控
"""

from fastapi import APIRouter, Depends, HTTPException

from web.auth import User, get_current_user, require_admin
from web.bridge import bridge

router = APIRouter(prefix="/api/status", tags=["状态监控"])


@router.get("/overview")
async def get_overview(current_user: User = Depends(get_current_user)):
    """获取总体状态"""
    result = await bridge.send_request("status.overview")
    if not result.get("success"):
        # Agent 未连接时返回基本信息
        return {
            "success": True,
            "data": {
                "bot_running": False,
                "agent_connected": False,
                "error": result.get("error", "Agent 未连接"),
            }
        }

    data = result.get("data", {})
    data["agent_connected"] = True
    data["agent_status"] = bridge.get_status()
    return {"success": True, "data": data}


@router.get("/instances")
async def get_instances(current_user: User = Depends(get_current_user)):
    """获取实例列表"""
    result = await bridge.send_request("status.instances")
    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "Agent 请求失败"))
    return {"success": True, "data": result.get("data", {})}


@router.get("/agent")
async def get_agent_status(current_user: User = Depends(get_current_user)):
    """获取 Agent 连接状态"""
    return {"success": True, "data": bridge.get_status()}


@router.get("/steam/friends-status")
async def get_steam_friends_status(current_user: User = Depends(get_current_user)):
    """获取 Steam 好友在线状态"""
    result = await bridge.send_request("steam.friends_status")
    if not result.get("success"):
        return {"success": True, "data": {"friends": [], "error": result.get("error", "获取失败")}}
    return {"success": True, "data": result.get("data", {})}


@router.post("/steam/pw-season/reset")
async def reset_steam_pw_season_records(current_user: User = Depends(require_admin)):
    """管理员手动清空完美平台赛季历史统计和排行榜。"""
    result = await bridge.send_request("steam.reset_pw_season_records", timeout=30)
    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "Agent 请求失败"))
    return {"success": True, "data": result.get("data", {})}


@router.get("/hardware")
async def get_hardware(source: str = "web", current_user: User = Depends(get_current_user)):
    """获取硬件信息（web=本机, agent=Agent 机器）"""
    try:
        import psutil
        import platform
        cpu_percent = psutil.cpu_percent(interval=0.3)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        hardware = {
            "cpu_percent": cpu_percent,
            "cpu_count": psutil.cpu_count(),
            "memory_total": memory.total,
            "memory_used": memory.used,
            "memory_percent": memory.percent,
            "disk_total": disk.total,
            "disk_used": disk.used,
            "disk_percent": disk.percent,
        }
        return {
            "success": True,
            "data": {
                "hardware": hardware,
                "hostname": platform.node(),
            }
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
