"""
Web API — 文件管理
"""

import asyncio
import base64
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse

from web.auth import User, get_current_user
from web.bridge import bridge

router = APIRouter(prefix="/api/files", tags=["文件管理"])

MAX_FILE_SIZE = 1024 * 1024 * 1024  # 1GB
CHUNK_SIZE = 1024 * 1024  # 1MB per chunk


@router.get("")
async def list_files(current_user: User = Depends(get_current_user)):
    """获取文件列表"""
    result = await bridge.send_request("files.list", {})
    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "获取文件列表失败"))

    # 添加权限信息
    files = result.get("data", {}).get("files", [])
    for f in files:
        f["is_own"] = f.get("uploader") == current_user.username
        f["can_delete"] = current_user.role == "admin" or f["is_own"]

    return {"success": True, "data": {"files": files, "total_size": result.get("data", {}).get("total_size", 0)}}


@router.post("")
async def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    """上传文件（分块传输）"""
    content = await file.read()
    file_size = len(content)

    if file_size > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件大小不能超过 1GB")

    # 分块上传到 Agent
    offset = 0
    chunk_index = 0
    total_chunks = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE

    while offset < file_size:
        chunk = content[offset:offset + CHUNK_SIZE]
        chunk_b64 = base64.b64encode(chunk).decode("utf-8")

        result = await bridge.send_request("files.upload", {
            "filename": file.filename,
            "chunk": chunk_b64,
            "chunk_index": chunk_index,
            "total_chunks": total_chunks,
            "uploader": current_user.username,
            "file_size": file_size,
        }, timeout=60.0)

        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error", "上传失败"))

        offset += len(chunk)
        chunk_index += 1

    return {"success": True, "data": result.get("data", {})}


@router.post("/chunk")
async def upload_chunk(
    file: UploadFile = File(...),
    chunk_index: int = 0,
    total_chunks: int = 1,
    filename: str = "",
    current_user: User = Depends(get_current_user)
):
    """分块上传（前端逐块上传，进度更准确）"""
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


@router.delete("/{filename}")
async def delete_file(filename: str, current_user: User = Depends(get_current_user)):
    """删除文件"""
    # 先获取文件列表检查权限
    list_result = await bridge.send_request("files.list", {})
    if not list_result.get("success"):
        raise HTTPException(status_code=502, detail="获取文件列表失败")

    files = list_result.get("data", {}).get("files", [])
    target_file = next((f for f in files if f.get("filename") == filename), None)

    if not target_file:
        raise HTTPException(status_code=404, detail="文件不存在")

    # 权限检查
    if current_user.role != "admin" and target_file.get("uploader") != current_user.username:
        raise HTTPException(status_code=403, detail="无权限删除此文件")

    result = await bridge.send_request("files.delete", {"filename": filename})
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "删除失败"))

    return {"success": True, "data": {"message": "删除成功"}}


@router.get("/{filename}")
async def download_file(filename: str, current_user: User = Depends(get_current_user)):
    """下载文件（流式）"""
    # 创建下载队列并注册到 bridge
    download_id = str(uuid.uuid4())[:8]
    queue = asyncio.Queue()
    bridge._download_queues[download_id] = queue

    try:
        # 触发 agent 开始分块推送（agent 会先返回元信息，再异步推送 chunk）
        result = await bridge.send_request("files.download", {
            "filename": filename,
            "chunk_size": 1024 * 1024,  # 1MB per chunk
            "download_id": download_id,
        })
        if not result.get("success"):
            raise HTTPException(status_code=404, detail=result.get("error", "文件不存在"))

        file_size = result.get("data", {}).get("size", 0)

        # 流式 yield：边收边发，不囤内存
        async def async_generate():
            while True:
                chunk_b64 = await queue.get()
                if chunk_b64 is None:
                    break
                yield base64.b64decode(chunk_b64)

        headers = {
            "Content-Disposition": f"attachment; filename={filename}",
        }
        if file_size > 0:
            headers["Content-Length"] = str(file_size)

        return StreamingResponse(
            async_generate(),
            media_type="application/octet-stream",
            headers=headers,
        )
    finally:
        bridge._download_queues.pop(download_id, None)