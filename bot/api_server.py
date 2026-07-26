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
import json
from pathlib import Path
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
    force: bool = False  # 强制发送，绕过维护时间检查


class SendLocalFileRequest(BaseModel):
    target: str
    path: str
    idempotency_key: str
    force: bool = False


_local_send_lock = threading.Lock()
_local_send_results = {}


def _allowed_export_file(raw_path: str) -> Path:
    root = Path(__file__).resolve().parent.parent
    config_path = root / "instconfig" / "cs2_video_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    export_dir = Path(config.get("export_dir", "data/cs2-video/exports"))
    if not export_dir.is_absolute(): export_dir = root / export_dir
    export_dir = export_dir.resolve()
    candidate = Path(raw_path).resolve()
    try:
        if os.path.commonpath([str(export_dir).lower(), str(candidate).lower()]) != str(export_dir).lower():
            raise ValueError
    except ValueError:
        raise ValueError("文件不在允许的导出目录中")
    if candidate.suffix.lower() != ".mp4" or not candidate.is_file():
        raise ValueError("只允许发送已存在的 MP4 文件")
    return candidate


# ── 路由 ──

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/send/message")
async def send_message(req: SendMessageRequest):
    """发送文本消息（投队列，主循环处理）"""
    if _is_maintenance_time() and not req.force:
        return {"success": False, "error": "当前是维护时段，暂不支持发送（可使用 force=true 强制发送）"}
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

    # 等主循环处理完（最多 300 秒）
    try:
        return result_q.get(timeout=300)
    except queue.Empty:
        return {"success": False, "error": "发送超时"}


@app.post("/send/file")
async def send_file(
    target: str = Form(...),
    file: UploadFile = File(...),
    force: bool = Form(False),
):
    """发送文件/图片（multipart 上传，投队列，主循环处理）"""
    if _is_maintenance_time() and not force:
        return {"success": False, "error": "当前是维护时段，暂不支持发送（可使用 force=true 强制发送）"}
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
        result = result_q.get(timeout=300)
    except queue.Empty:
        result = {"success": False, "error": "发送超时"}
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    return result


@app.post("/send/local-file")
async def send_local_file(req: SendLocalFileRequest):
    """Queue an existing exported MP4 without loading it into API memory."""
    if _is_maintenance_time() and not req.force:
        return {"success": False, "error": "当前是维护时段，暂不支持发送"}
    if not req.target or not req.idempotency_key:
        return {"success": False, "error": "target 和 idempotency_key 不能为空"}
    try:
        path = _allowed_export_file(req.path)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    with _local_send_lock:
        previous = _local_send_results.get(req.idempotency_key)
        if previous is not None: return previous
        _local_send_results[req.idempotency_key] = {"success": False, "error": "发送处理中"}
    result_q = queue.Queue()
    api_send_queue.put({"type": "file", "target": req.target, "content": str(path),
                        "filename": path.name, "result_q": result_q, "keep_file": True})
    try: result = result_q.get(timeout=300)
    except queue.Empty: result = {"success": False, "error": "发送超时，结果未知"}
    with _local_send_lock: _local_send_results[req.idempotency_key] = result
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
