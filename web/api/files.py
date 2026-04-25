"""
Web API — 文件管理

支持两种存储模式：
- web: 文件直接存储在 Web 服务器本地，上传/下载不走 WebSocket，速度快
- agent: 文件存储在 Agent 端，通过 WebSocket 中转，适合 Web 和 Agent 不在同一机器的场景
"""

import asyncio
import base64
import json
import threading
import uuid
from datetime import datetime
from fastapi import APIRouter, Body, Depends, Form, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse, StreamingResponse
from pathlib import Path

from web.auth import User, get_current_user
from web.bridge import bridge

router = APIRouter(prefix="/api/files", tags=["文件管理"])

MAX_FILE_SIZE = 1024 * 1024 * 1024  # 1GB
CHUNK_SIZE = 1024 * 1024  # 1MB per chunk

# Web 本地存储目录
_WEB_FILES_DIR = Path(__file__).resolve().parent.parent / "shared_files"
_WEB_FILES_DIR.mkdir(parents=True, exist_ok=True)

# Web 配置文件
_WEB_CONFIG_FILE = Path(__file__).resolve().parent.parent / "web_config.json"

# 上传进度跟踪（防竞态）
_upload_progress_lock = threading.Lock()
_upload_progress: dict = {}


def _get_storage_mode() -> str:
    if _WEB_CONFIG_FILE.exists():
        try:
            cfg = json.loads(_WEB_CONFIG_FILE.read_text(encoding="utf-8"))
            return cfg.get("file_storage_mode", "web")
        except Exception:
            pass
    return "web"


def _set_storage_mode(mode: str):
    cfg = {}
    if _WEB_CONFIG_FILE.exists():
        try:
            cfg = json.loads(_WEB_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    cfg["file_storage_mode"] = mode
    _WEB_CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    else:
        return f"{size / (1024 * 1024 * 1024):.1f} GB"


def _read_meta(file_path: Path) -> dict:
    meta_path = file_path.parent / f"{file_path.name}.meta.json"
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _write_meta(file_path: Path, meta: dict):
    meta_path = file_path.parent / f"{file_path.name}.meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


# ═══════════════════════════════════════════════════════
#  存储模式 API
# ═══════════════════════════════════════════════════════

@router.get("/mode")
async def get_storage_mode(current_user: User = Depends(get_current_user)):
    return {"success": True, "data": {"mode": _get_storage_mode()}}


@router.put("/mode")
async def set_storage_mode(mode: str = Query(..., regex="^(web|agent)$"), current_user: User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可切换存储模式")
    _set_storage_mode(mode)
    return {"success": True, "data": {"mode": mode}}


# ═══════════════════════════════════════════════════════
#  文件列表
# ═══════════════════════════════════════════════════════

@router.get("")
async def list_files(current_user: User = Depends(get_current_user)):
    storage_mode = _get_storage_mode()

    if storage_mode == "web":
        return await _list_files_web(current_user)
    else:
        return await _list_files_agent(current_user)


async def _list_files_web(current_user: User):
    files = []
    total_size = 0
    for f in sorted(_WEB_FILES_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.is_file() and not f.name.endswith(".meta.json"):
            stat = f.stat()
            meta = _read_meta(f)
            files.append({
                "filename": f.name,
                "size": stat.st_size,
                "size_text": _format_size(stat.st_size),
                "uploader": meta.get("uploader", "unknown"),
                "uploaded_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "is_own": meta.get("uploader") == current_user.username,
                "can_delete": current_user.role == "admin" or meta.get("uploader") == current_user.username,
            })
            total_size += stat.st_size

    return {"success": True, "data": {"files": files, "total_size": total_size, "storage_mode": "web"}}


async def _list_files_agent(current_user: User):
    result = await bridge.send_request("files.list", {})
    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "获取文件列表失败"))

    files = result.get("data", {}).get("files", [])
    for f in files:
        f["is_own"] = f.get("uploader") == current_user.username
        f["can_delete"] = current_user.role == "admin" or f["is_own"]

    return {"success": True, "data": {"files": files, "total_size": result.get("data", {}).get("total_size", 0), "storage_mode": "agent"}}


# ═══════════════════════════════════════════════════════
#  上传文件
# ═══════════════════════════════════════════════════════

@router.post("/init-upload")
async def init_upload(
    body: dict = Body(...),
    current_user: User = Depends(get_current_user)
):
    """初始化上传，获取 upload_id 和实际文件名（防止并发冲突）"""
    storage_mode = _get_storage_mode()
    if storage_mode != "web":
        raise HTTPException(status_code=400, detail="仅 web 存储模式支持此接口")

    filename = body.get("filename", "")
    total_chunks = body.get("total_chunks", 1)

    if not filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="文件名无效")

    with _upload_progress_lock:
        upload_id = str(uuid.uuid4())[:8]
        file_path = _WEB_FILES_DIR / filename
        if file_path.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            stem = file_path.stem
            ext = file_path.suffix
            file_path = _WEB_FILES_DIR / f"{stem}_{timestamp}{ext}"
        _upload_progress[upload_id] = {
            "file_path": file_path,
            "uploader": current_user.username,
            "original_filename": filename,
        }
        file_path.touch()

    return {"success": True, "data": {"upload_id": upload_id, "filename": file_path.name}}


@router.post("/chunk")
async def upload_chunk(
    file: UploadFile = File(...),
    chunk_index: int = Form(0),
    total_chunks: int = Form(1),
    filename: str = Form(""),
    upload_id: str = Form(""),
    current_user: User = Depends(get_current_user)
):
    storage_mode = _get_storage_mode()

    if storage_mode == "web":
        return await _upload_chunk_web(file, chunk_index, total_chunks, filename, upload_id, current_user)
    else:
        return await _upload_chunk_agent(file, chunk_index, total_chunks, filename, current_user)


async def _upload_chunk_web(file: UploadFile, chunk_index: int, total_chunks: int, filename: str, upload_id: str, current_user: User):
    content = await file.read()

    if not filename and not upload_id:
        raise HTTPException(status_code=400, detail="文件名或 upload_id 不能同时为空")

    with _upload_progress_lock:
        if chunk_index == 0:
            if upload_id and upload_id in _upload_progress:
                entry = _upload_progress[upload_id]
            else:
                upload_id = str(uuid.uuid4())[:8]
                file_path = _WEB_FILES_DIR / filename
                if file_path.exists():
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    stem = file_path.stem
                    ext = file_path.suffix
                    file_path = _WEB_FILES_DIR / f"{stem}_{timestamp}{ext}"
                entry = {
                    "file_path": file_path,
                    "uploader": current_user.username,
                    "original_filename": filename,
                }
                _upload_progress[upload_id] = entry
                file_path.touch()
            file_path = entry["file_path"]
        else:
            if not upload_id or upload_id not in _upload_progress:
                raise HTTPException(status_code=400, detail="上传上下文无效，请从头开始")
            entry = _upload_progress[upload_id]
            file_path = entry["file_path"]

    with open(file_path, "ab") as f:
        f.write(content)

    if chunk_index + 1 >= total_chunks:
        actual_size = file_path.stat().st_size
        _write_meta(file_path, {
            "uploader": current_user.username,
            "uploaded_at": datetime.now().isoformat(),
            "file_size": actual_size,
        })
        with _upload_progress_lock:
            _upload_progress.pop(upload_id, None)
        return {"success": True, "data": {"filename": file_path.name, "size": actual_size}}

    return {"success": True, "data": {"chunk_received": chunk_index + 1, "total_chunks": total_chunks, "upload_id": upload_id}}


async def _upload_chunk_agent(file: UploadFile, chunk_index: int, total_chunks: int, filename: str, current_user: User):
    content = await file.read()
    chunk_b64 = base64.b64encode(content).decode("utf-8")

    result = await bridge.send_request("files.upload", {
        "filename": filename,
        "chunk": chunk_b64,
        "chunk_index": chunk_index,
        "total_chunks": total_chunks,
        "uploader": current_user.username,
        "file_size": -1,
    }, timeout=60.0)

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "上传失败"))

    return {"success": True, "data": result.get("data", {})}


# ═══════════════════════════════════════════════════════
#  删除文件
# ═══════════════════════════════════════════════════════

@router.delete("/{filename}")
async def delete_file(filename: str, current_user: User = Depends(get_current_user)):
    storage_mode = _get_storage_mode()

    if storage_mode == "web":
        return await _delete_file_web(filename, current_user)
    else:
        return await _delete_file_agent(filename, current_user)


async def _delete_file_web(filename: str, current_user: User):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="文件名无效")

    file_path = _WEB_FILES_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    meta = _read_meta(file_path)
    if current_user.role != "admin" and meta.get("uploader") != current_user.username:
        raise HTTPException(status_code=403, detail="无权限删除此文件")

    file_path.unlink(missing_ok=True)
    meta_path = file_path.parent / f"{file_path.name}.meta.json"
    meta_path.unlink(missing_ok=True)

    return {"success": True, "data": {"message": "删除成功"}}


async def _delete_file_agent(filename: str, current_user: User):
    list_result = await bridge.send_request("files.list", {})
    if not list_result.get("success"):
        raise HTTPException(status_code=502, detail="获取文件列表失败")

    files = list_result.get("data", {}).get("files", [])
    target_file = next((f for f in files if f.get("filename") == filename), None)

    if not target_file:
        raise HTTPException(status_code=404, detail="文件不存在")

    if current_user.role != "admin" and target_file.get("uploader") != current_user.username:
        raise HTTPException(status_code=403, detail="无权限删除此文件")

    result = await bridge.send_request("files.delete", {"filename": filename})
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "删除失败"))

    return {"success": True, "data": {"message": "删除成功"}}


# ═══════════════════════════════════════════════════════
#  下载文件
# ═══════════════════════════════════════════════════════

@router.get("/download/{filename}")
async def download_file(filename: str, current_user: User = Depends(get_current_user)):
    storage_mode = _get_storage_mode()

    if storage_mode == "web":
        return await _download_file_web(filename, current_user)
    else:
        return await _download_file_agent(filename, current_user)


async def _download_file_web(filename: str, current_user: User):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="文件名无效")

    file_path = _WEB_FILES_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(
        file_path,
        media_type="application/octet-stream",
        filename=filename,
    )


async def _download_file_agent(filename: str, current_user: User = Depends(get_current_user)):
    download_id = str(uuid.uuid4())[:8]
    queue = asyncio.Queue()
    bridge._download_queues[download_id] = queue

    try:
        result = await bridge.send_request("files.download", {
            "filename": filename,
            "chunk_size": 1024 * 1024,
            "download_id": download_id,
        })
        if not result.get("success"):
            raise HTTPException(status_code=404, detail=result.get("error", "文件不存在"))

        file_size = result.get("data", {}).get("size", 0)

        async def async_generate():
            while True:
                chunk_b64 = await queue.get()
                if chunk_b64 is None:
                    break
                yield base64.b64decode(chunk_b64)

        headers = {"Content-Disposition": f"attachment; filename={filename}"}
        if file_size > 0:
            headers["Content-Length"] = str(file_size)

        return StreamingResponse(
            async_generate(),
            media_type="application/octet-stream",
            headers=headers,
        )
    finally:
        bridge._download_queues.pop(download_id, None)
