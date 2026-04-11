"""
cs-Solidarity Web Server — JWT 认证与权限控制

提供用户认证、JWT 生成/校验、角色权限装饰器。
"""

import json
import secrets
import string
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

# ── 配置 ──
_SECRET_FILE = Path(__file__).parent / ".secret_key"

def _get_or_create_secret() -> str:
    """持久化 SECRET_KEY，避免重启后所有 token 失效"""
    if _SECRET_FILE.exists():
        try:
            return _SECRET_FILE.read_text().strip()
        except Exception:
            pass
    key = secrets.token_hex(32)
    try:
        _SECRET_FILE.write_text(key)
    except Exception:
        pass  # 写入失败不影响运行，只是重启后 token 失效
    return key

SECRET_KEY = _get_or_create_secret()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24
USERS_FILE = Path(__file__).parent / "users.json"
REGISTRATIONS_FILE = Path(__file__).parent / "registrations.json"

# 密码哈希
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Bearer token 解析
security = HTTPBearer(auto_error=False)


class User:
    """用户对象"""
    def __init__(self, username: str, role: str, display_name: str = ""):
        self.username = username
        self.role = role
        self.display_name = display_name or username

    def to_dict(self):
        return {"username": self.username, "role": self.role, "display_name": self.display_name}


def _load_users() -> dict:
    """加载用户数据"""
    if not USERS_FILE.exists():
        return {"users": []}
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"users": []}


def _save_users(data: dict):
    """保存用户数据"""
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def init_users() -> Optional[str]:
    """初始化用户数据（首次运行生成 admin 账户）"""
    data = _load_users()
    if data["users"]:
        return None  # 已有用户

    # 生成随机密码
    alphabet = string.ascii_letters + string.digits
    password = "".join(secrets.choice(alphabet) for _ in range(12))

    data["users"] = [
        {
            "username": "admin",
            "password_hash": pwd_context.hash(password),
            "role": "admin",
            "display_name": "管理员",
            "created_at": datetime.now().isoformat(),
            "last_login": None,
        }
    ]
    _save_users(data)
    return password


def verify_password(plain: str, hashed: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain, hashed)


def hash_password(password: str) -> str:
    """哈希密码"""
    return pwd_context.hash(password)


def create_token(username: str, role: str) -> str:
    """创建 JWT token"""
    expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": username,
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """解码 JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def authenticate(username: str, password: str) -> Optional[dict]:
    """验证用户名密码，返回用户信息"""
    data = _load_users()
    for user in data["users"]:
        if user["username"] == username:
            if verify_password(password, user["password_hash"]):
                # 更新最后登录时间
                user["last_login"] = datetime.now().isoformat()
                _save_users(data)
                return {"username": user["username"], "role": user["role"], "display_name": user.get("display_name", "")}
    return None


async def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> User:
    """FastAPI 依赖：从请求中解析当前用户"""
    if not credentials:
        raise HTTPException(status_code=401, detail="未登录")

    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")

    return User(
        username=payload["sub"],
        role=payload.get("role", "user"),
    )


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """FastAPI 依赖：要求管理员权限"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return current_user


def _load_registrations() -> dict:
    """加载注册申请数据"""
    if not REGISTRATIONS_FILE.exists():
        return {"pending": []}
    try:
        with open(REGISTRATIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"pending": []}


def _save_registrations(data: dict):
    """保存注册申请数据"""
    with open(REGISTRATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def submit_registration(username: str, password: str, display_name: str = "") -> str:
    """提交注册申请，返回结果消息"""
    if not username or not password:
        return "用户名和密码不能为空"
    if len(username) < 2 or len(username) > 32:
        return "用户名长度需在 2-32 之间"
    if len(password) < 6:
        return "密码长度不能少于 6 位"

    # 检查用户名是否已存在
    users_data = _load_users()
    for u in users_data["users"]:
        if u["username"] == username:
            return "用户名已存在"

    # 检查是否已有待审核的同名申请
    reg_data = _load_registrations()
    for r in reg_data["pending"]:
        if r["username"] == username:
            return "该用户名已有待审核的注册申请"

    reg_data["pending"].append({
        "username": username,
        "password_hash": hash_password(password),
        "display_name": display_name or username,
        "role": "user",
        "created_at": datetime.now().isoformat(),
    })
    _save_registrations(reg_data)
    return ""


def approve_registration(username: str) -> str:
    """审核通过注册申请，返回结果消息"""
    reg_data = _load_registrations()
    target = None
    for r in reg_data["pending"]:
        if r["username"] == username:
            target = r
            break

    if not target:
        return "注册申请不存在"

    # 再次检查用户名是否已被占用
    users_data = _load_users()
    for u in users_data["users"]:
        if u["username"] == username:
            reg_data["pending"] = [r for r in reg_data["pending"] if r["username"] != username]
            _save_registrations(reg_data)
            return "用户名已存在，申请已移除"

    # 添加到用户列表
    users_data["users"].append({
        "username": target["username"],
        "password_hash": target["password_hash"],
        "role": target.get("role", "user"),
        "display_name": target.get("display_name", target["username"]),
        "created_at": datetime.now().isoformat(),
        "last_login": None,
    })
    _save_users(users_data)

    # 从待审核列表移除
    reg_data["pending"] = [r for r in reg_data["pending"] if r["username"] != username]
    _save_registrations(reg_data)
    return ""


def reject_registration(username: str) -> str:
    """拒绝注册申请，返回结果消息"""
    reg_data = _load_registrations()
    original_len = len(reg_data["pending"])
    reg_data["pending"] = [r for r in reg_data["pending"] if r["username"] != username]

    if len(reg_data["pending"]) == original_len:
        return "注册申请不存在"

    _save_registrations(reg_data)
    return ""
