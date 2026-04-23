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
    """上传文件"""
    # 读取文件内容
    content = await file.read()

    # 检查文件大小
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件大小不能超过 1GB")

    # Base64 编码
    content_b64 = base64.b64encode(content).decode("utf-8")

    result = await bridge.send_request("files.upload", {
        "filename": file.filename,
        "content": content_b64,
        "uploader": current_user.username
    })

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
    """下载文件"""
    result = await bridge.send_request("files.download", {"filename": filename})
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "文件不存在"))

    data = result.get("data", {})
    content = base64.b64decode(data.get("content", ""))

    return StreamingResponse(
        iter([content]),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )