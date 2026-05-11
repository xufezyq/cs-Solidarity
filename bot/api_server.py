"""
Bot 本地 HTTP API — 供 OpenClaw 等同机 agent 直接调用发送消息/文件

请求投入 api_send_queue，由主循环统一处理（避免与窗口管理、消息捕获冲突）。
仅监听 127.0.0.1，无需认证。
"""

import logging
import os
import queue
import tempfile
import threading
from datetime import datetime, time as dt_time

from fastapi import FastAPI, File, Form, UploadFile
from pydantic import BaseModel
from typing import List, Optional

log = logging.getLogger(__name__)

app = FastAPI(title="cs-Solidarity Bot API", version="1.0")


def _is_maintenance_time():
    """检查当前是否在维护时间内（与 main.py 逻辑一致）"""
    try:
        import main
        if getattr(main, 'DEBUG_MODE', False):
            return False
        return main.MAINTENANCE_START <= datetime.now().time() < main.MAINTENANCE_END
    except Exception:
        return False


# 发送队列：API → 主循环
# 每项格式: {"type": "text"|"file", "target": str, "content": str|path, "result_q": Queue}
api_send_queue: queue.Queue = queue.Queue()


# ── 请求模型 ──

class SendMessageRequest(BaseModel):
    target: str
    content: str
    at: Optional[List[str]] = None
    at_all: bool = False


# ── 路由 ──

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/send/message")
async def send_message(req: SendMessageRequest):
    """发送文本消息（投队列，主循环处理）"""
    if _is_maintenance_time():
        return {"success": False, "error": "当前是维护时段，暂不支持发送"}
    if not req.target or not req.content:
        return {"success": False, "error": "target 和 content 不能为空"}

    result_q = queue.Queue()
    api_send_queue.put({
        "type": "text",
        "target": req.target,
        "content": req.content,
        "at": req.at,
        "at_all": req.at_all,
        "result_q": result_q,
    })

    # 等主循环处理完（最多 60 秒）
    try:
        return result_q.get(timeout=60)
    except queue.Empty:
        return {"success": False, "error": "发送超时"}


@app.post("/send/file")
async def send_file(
    target: str = Form(...),
    file: UploadFile = File(...),
):
    """发送文件/图片（multipart 上传，投队列，主循环处理）"""
    if _is_maintenance_time():
        return {"success": False, "error": "当前是维护时段，暂不支持发送"}
    if not target:
        return {"success": False, "error": "target 不能为空"}

    # 先保存到临时文件（主循环读取后会清理）
    suffix = os.path.splitext(file.filename or "")[1] or ".tmp"
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    content = await file.read()
    with open(tmp_path, "wb") as f:
        f.write(content)

    result_q = queue.Queue()
    api_send_queue.put({
        "type": "file",
        "target": target,
        "content": tmp_path,
        "filename": file.filename,
        "result_q": result_q,
    })

    try:
        result = result_q.get(timeout=60)
    except queue.Empty:
        result = {"success": False, "error": "发送超时"}
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    return result


def start_api_server(host="127.0.0.1", port=18800):
    """在后台线程启动 HTTP API server"""
    def _run():
        import uvicorn
        log.info(f"[API] 启动本地 API server: http://{host}:{port}")
        uvicorn.run(app, host=host, port=port, log_level="warning")

    t = threading.Thread(target=_run, daemon=True, name="api-server")
    t.start()
    return t
