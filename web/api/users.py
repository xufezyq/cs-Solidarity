"""
Web API — 用户管理（仅 admin）
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from web.auth import User, require_admin, hash_password, _load_users, _save_users
from datetime import datetime

router = APIRouter(prefix="/api/users", tags=["用户管理"])


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "user"
    display_name: str = ""


class UpdateRoleRequest(BaseModel):
    role: str


class ResetPasswordRequest(BaseModel):
    new_password: str


@router.get("")
async def list_users(current_user: User = Depends(require_admin)):
    """获取用户列表"""
    data = _load_users()
    users = []
    for u in data["users"]:
        users.append({
            "username": u["username"],
            "role": u["role"],
            "display_name": u.get("display_name", ""),
            "created_at": u.get("created_at", ""),
            "last_login": u.get("last_login", ""),
        })
    return {"success": True, "data": {"users": users}}


@router.post("")
async def create_user(req: CreateUserRequest, current_user: User = Depends(require_admin)):
    """创建用户"""
    if req.role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="角色必须是 admin 或 user")

    data = _load_users()
    for u in data["users"]:
        if u["username"] == req.username:
            raise HTTPException(status_code=400, detail="用户名已存在")

    data["users"].append({
        "username": req.username,
        "password_hash": hash_password(req.password),
        "role": req.role,
        "display_name": req.display_name or req.username,
        "created_at": datetime.now().isoformat(),
        "last_login": None,
    })
    _save_users(data)

    return {"success": True, "message": f"用户 {req.username} 已创建"}


@router.delete("/{username}")
async def delete_user(username: str, current_user: User = Depends(require_admin)):
    """删除用户"""
    if username == current_user.username:
        raise HTTPException(status_code=400, detail="不能删除自己")

    data = _load_users()
    original_len = len(data["users"])
    data["users"] = [u for u in data["users"] if u["username"] != username]

    if len(data["users"]) == original_len:
        raise HTTPException(status_code=404, detail="用户不存在")

    _save_users(data)
    return {"success": True, "message": f"用户 {username} 已删除"}


@router.put("/{username}/role")
async def update_role(username: str, req: UpdateRoleRequest, current_user: User = Depends(require_admin)):
    """修改用户角色"""
    if req.role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="角色必须是 admin 或 user")

    data = _load_users()
    for u in data["users"]:
        if u["username"] == username:
            u["role"] = req.role
            _save_users(data)
            return {"success": True, "message": f"用户 {username} 角色已改为 {req.role}"}

    raise HTTPException(status_code=404, detail="用户不存在")


@router.put("/{username}/password")
async def reset_password(username: str, req: ResetPasswordRequest, current_user: User = Depends(require_admin)):
    """重置用户密码"""
    data = _load_users()
    for u in data["users"]:
        if u["username"] == username:
            u["password_hash"] = hash_password(req.new_password)
            _save_users(data)
            return {"success": True, "message": f"用户 {username} 密码已重置"}

    raise HTTPException(status_code=404, detail="用户不存在")
