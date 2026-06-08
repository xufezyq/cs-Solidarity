"""
Web API — 配置管理（通过 Agent 转发）
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from web.auth import User, require_admin
from web.bridge import bridge

router = APIRouter(prefix="/api/config", tags=["配置管理"])


class ConfigWriteRequest(BaseModel):
    content: str


class ConfigRestoreRequest(BaseModel):
    backup_file: str
    target: str


@router.get("")
async def list_configs(current_user: User = Depends(require_admin)):
    """列出所有配置文件"""
    result = await bridge.send_request("config.list")
    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "Agent 请求失败"))
    return {"success": True, "data": result.get("data", {})}


@router.get("/backups/list")
async def list_backups(current_user: User = Depends(require_admin)):
    """获取备份列表"""
    result = await bridge.send_request("config.backups")
    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "Agent 请求失败"))
    return {"success": True, "data": result.get("data", {})}


@router.get("/{file_path:path}")
async def read_config(file_path: str, current_user: User = Depends(require_admin)):
    """读取配置文件"""
    result = await bridge.send_request("config.read", {"file": file_path})
    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "Agent 请求失败"))
    return {"success": True, "data": result.get("data", {})}


@router.put("/{file_path:path}")
async def write_config(file_path: str, req: ConfigWriteRequest, current_user: User = Depends(require_admin)):
    """写入配置文件"""
    result = await bridge.send_request("config.write", {
        "file": file_path,
        "content": req.content,
    })
    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "Agent 请求失败"))
    return {"success": True, "data": result.get("data", {})}


@router.post("/{file_path:path}/backup")
async def backup_config(file_path: str, current_user: User = Depends(require_admin)):
    """备份配置文件"""
    result = await bridge.send_request("config.backup", {"file": file_path})
    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "Agent 请求失败"))
    return {"success": True, "data": result.get("data", {})}


@router.post("/restore")
async def restore_config(req: ConfigRestoreRequest, current_user: User = Depends(require_admin)):
    """从备份恢复配置"""
    result = await bridge.send_request("config.restore", {
        "backup_file": req.backup_file,
        "target": req.target,
    })
    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "Agent 请求失败"))
    return {"success": True, "data": result.get("data", {})}
