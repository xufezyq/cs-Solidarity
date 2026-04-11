"""
Web API — 认证
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from web.auth import (
    authenticate, create_token, get_current_user, verify_password, hash_password,
    _load_users, _save_users, submit_registration, approve_registration,
    reject_registration, _load_registrations, require_admin
)
from fastapi import Depends
from web.auth import User

router = APIRouter(prefix="/api/auth", tags=["认证"])


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""


@router.post("/login")
async def login(req: LoginRequest):
    """登录获取 JWT token"""
    user = authenticate(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_token(user["username"], user["role"])
    return {
        "success": True,
        "token": token,
        "user": {
            "username": user["username"],
            "role": user["role"],
            "display_name": user.get("display_name", ""),
        }
    }


@router.post("/register")
async def register(req: RegisterRequest):
    """用户提交注册申请"""
    error = submit_registration(req.username, req.password, req.display_name)
    if error:
        raise HTTPException(status_code=400, detail=error)
    return {"success": True, "message": "注册申请已提交，请等待管理员审核"}


@router.get("/registrations")
async def list_registrations(current_user: User = Depends(require_admin)):
    """获取待审核的注册申请列表"""
    reg_data = _load_registrations()
    pending = []
    for r in reg_data.get("pending", []):
        pending.append({
            "username": r["username"],
            "display_name": r.get("display_name", r["username"]),
            "created_at": r.get("created_at", ""),
        })
    return {"success": True, "data": {"pending": pending}}


@router.post("/registrations/{username}/approve")
async def approve_reg(username: str, current_user: User = Depends(require_admin)):
    """审核通过注册申请"""
    error = approve_registration(username)
    if error:
        raise HTTPException(status_code=400, detail=error)
    return {"success": True, "message": f"用户 {username} 已审核通过"}


@router.post("/registrations/{username}/reject")
async def reject_reg(username: str, current_user: User = Depends(require_admin)):
    """拒绝注册申请"""
    error = reject_registration(username)
    if error:
        raise HTTPException(status_code=400, detail=error)
    return {"success": True, "message": f"用户 {username} 的注册申请已拒绝"}


@router.post("/change-password")
async def change_password(req: ChangePasswordRequest, current_user: User = Depends(get_current_user)):
    """修改自己的密码"""
    data = _load_users()
    for user in data["users"]:
        if user["username"] == current_user.username:
            if not verify_password(req.old_password, user["password_hash"]):
                raise HTTPException(status_code=400, detail="原密码错误")
            user["password_hash"] = hash_password(req.new_password)
            _save_users(data)
            return {"success": True, "message": "密码已修改"}

    raise HTTPException(status_code=404, detail="用户不存在")


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    """获取当前用户信息"""
    return {
        "success": True,
        "user": current_user.to_dict()
    }
