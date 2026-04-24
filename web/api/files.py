"""
Web API — 文件管理
"""

import base64
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

    # 分块上传
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
    """下载文件"""
    result = await bridge.send_request("files.download", {"filename": filename})
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "文件不存在"))

    data = result.get("data", {})
    download_id = data.get("download_id")

    # 等待块收集完成（最多等 5 分钟）
    import time
    for _ in range(300):
        if download_id in bridge._file_chunks and bridge._file_chunks[download_id].get("ready"):
            break
        time.sleep(1)

    if download_id not in bridge._file_chunks or not bridge._file_chunks[download_id].get("ready"):
        raise HTTPException(status_code=504, detail="文件块收集超时")

    dc = bridge._file_chunks[download_id]
    # 合并块
    import base64
    chunks_list = [dc["chunks"][i] for i in range(dc["total"]) if i in dc["chunks"]]
    content_b64 = "".join(chunks_list)
    content = base64.b64decode(content_b64)

    # 清理
    del bridge._file_chunks[download_id]

    return StreamingResponse(
        iter([content]),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )