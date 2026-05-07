"""
cs-Solidarity Web Server — 主入口

用法：
    python -m web.server --host 0.0.0.0 --port 8080 --token your_agent_token
"""

import argparse
import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# 设置进程名
try:
    import setproctitle
    setproctitle.setproctitle("cs-Solidarity Web")
except ImportError:
    pass  # 忽略导入失败，兼容没有安装 setproctitle 的环境

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# 确保项目根目录在 path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web.auth import init_users
from web.auth import decode_token
from web.bridge import bridge
from web.api import auth, users, config, status, logs, control, files, chat

# ── 日志 ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("web")

# Agent 连接令牌（启动时生成或由参数指定）
AGENT_TOKEN = ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    # 启动时初始化
    global AGENT_TOKEN
    if not AGENT_TOKEN:
        import secrets
        AGENT_TOKEN = secrets.token_hex(16)
        log.info(f"🔑 Agent 连接令牌（自动）: {AGENT_TOKEN}")
    else:
        log.info(f"🔑 Agent 连接令牌: {AGENT_TOKEN}")

    admin_password = init_users()
    if admin_password:
        log.info("=" * 50)
        log.info("⚠️  首次运行，已创建管理员账户")
        log.info(f"   用户名: admin")
        log.info(f"   密码:   {admin_password}")
        log.info("   请登录后立即修改密码！")
        log.info("=" * 50)

    yield

    # 关闭时清理
    log.info("Web Server 正在关闭...")


# ── 创建 FastAPI 应用 ──
app = FastAPI(
    title="cs-Solidarity Web 控制面板",
    description="微信机器人远程管理面板",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 API 路由
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(config.router)
app.include_router(status.router)
app.include_router(logs.router)
app.include_router(control.router)
app.include_router(files.router)
app.include_router(chat.router)


# ── Agent WebSocket 端点 ──
@app.websocket("/ws/agent")
async def websocket_agent(ws: WebSocket):
    """Agent 连接端点"""
    # ── 先验证 token，通过后再 accept ──
    try:
        auth_header = ws.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        else:
            token = ws.query_params.get("token", "")

        if token != AGENT_TOKEN:
            await ws.close(code=4001, reason="Agent token 无效")
            log.warning("Agent 连接被拒绝：token 无效")
            return
    except Exception:
        await ws.close(code=4001, reason="认证失败")
        return

    # 认证通过，建立连接
    await ws.accept()
    await bridge.connect(ws)
    bridge.setup_event_loop()
    conn_id = bridge.connection_id  # 记录当前连接 ID
    log.info(f"Agent WebSocket 连接已建立 (conn_id={conn_id[:8]}...)")

    async def _ping_loop():
        """定期 ping 检测 Agent 是否存活"""
        try:
            while True:
                await asyncio.sleep(30)
                await ws.send_text('{"type":"ping"}')
        except Exception:
            pass

    ping_task = asyncio.create_task(_ping_loop())

    try:
        while True:
            raw = await ws.receive_text()
            await bridge.handle_agent_message(raw)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.error(f"Agent WebSocket 异常: {e}")
    finally:
        ping_task.cancel()
        try:
            await ping_task
        except asyncio.CancelledError:
            pass
        await bridge.disconnect(conn_id)


# ── 静态文件和前端 ──
STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
async def serve_index():
    """返回前端页面"""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file, media_type="text/html")
    return {"message": "前端页面不存在，请确保 static/index.html 存在"}


# 如果 static 目录存在，挂载静态文件
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── WebSocket 日志推送（直接注册到 app，避免 router 冲突）──
@app.websocket("/ws/logs")
async def websocket_logs(ws: WebSocket):
    """WebSocket 实时日志推送"""
    from fastapi import WebSocketDisconnect
    token = ws.query_params.get("token", "")
    payload = decode_token(token)
    if not payload:
        await ws.close(code=4001, reason="认证失败")
        return

    await ws.accept()
    bridge.subscribe_logs(ws)
    try:
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        bridge.unsubscribe_logs(ws)


# ── WebSocket 聊天推送 ──
@app.websocket("/ws/chat")
async def websocket_chat(ws: WebSocket):
    """WebSocket 实时聊天消息推送"""
    token = ws.query_params.get("token", "")
    payload = decode_token(token)
    if not payload:
        await ws.close(code=4001, reason="认证失败")
        return

    await ws.accept()
    bridge.subscribe_chat(ws)
    try:
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        bridge.unsubscribe_chat(ws)


# ── 健康检查 ──
@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "agent": bridge.get_status(),
    }


# ── 启动 ──
def main():
    global AGENT_TOKEN
    import uvicorn

    parser = argparse.ArgumentParser(description="cs-Solidarity Web Server")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1，远程访问用 0.0.0.0）")
    parser.add_argument("--port", type=int, default=8080, help="监听端口（默认 8080）")
    parser.add_argument("--token", default="", help="Agent 连接令牌（不指定则自动生成）")
    args = parser.parse_args()

    if args.token:
        AGENT_TOKEN = args.token

    log.info(f"🌐 Web Server 启动: http://{args.host}:{args.port}")

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
        websocket_max_size=10 * 1024 * 1024,  # 10MB max WebSocket message
    )


if __name__ == "__main__":
    main()
