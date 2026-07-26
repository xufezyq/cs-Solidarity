from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from web.auth import User, get_current_user
from web.bridge import bridge

router = APIRouter(prefix="/api/cs2-video", tags=["CS2 视频制作"])


class MatchQueryRequest(BaseModel): player_id: str
class JobRequest(BaseModel): query_id: str; match_id: str
class RenderRequest(BaseModel):
    event_keys: list[str] = Field(min_length=1, max_length=20)
    preset_id: str
    packaging_id: str = "clean"
    bgm_id: str = "none"
    wechat_target: str

class InsightSettingsRequest(BaseModel):
    settings: dict


def identity(user): return {"_username": user.username, "_role": user.role}


async def call(action, params, user, timeout=15):
    result = await bridge.send_request(action, {**params, **identity(user)}, timeout=timeout)
    if not result.get("success"):
        error = result.get("error") or "Agent 请求失败"
        status = 403 if "无权" in error else 400 if any(x in error for x in ("无效", "上限", "允许", "不能", "不可")) else 502
        raise HTTPException(status_code=status, detail=error)
    return {"success": True, "data": result.get("data")}


@router.get("/bootstrap")
async def bootstrap(user: User = Depends(get_current_user)): return await call("cs2_video.bootstrap", {}, user)
@router.post("/match-queries", status_code=202)
async def create_query(req: MatchQueryRequest, user: User = Depends(get_current_user)): return await call("cs2_video.query.create", req.model_dump(), user)
@router.get("/match-queries/{query_id}")
async def get_query(query_id: str, user: User = Depends(get_current_user)): return await call("cs2_video.query.get", {"query_id": query_id}, user)
@router.post("/jobs", status_code=202)
async def create_job(req: JobRequest, user: User = Depends(get_current_user)): return await call("cs2_video.job.create", req.model_dump(), user)
@router.get("/jobs")
async def list_jobs(user: User = Depends(get_current_user)): return await call("cs2_video.job.list", {}, user)
@router.get("/jobs/{job_id}")
async def get_job(job_id: str, user: User = Depends(get_current_user)): return await call("cs2_video.job.get", {"job_id": job_id}, user)
@router.post("/jobs/{job_id}/render")
async def render(job_id: str, req: RenderRequest, user: User = Depends(get_current_user)): return await call("cs2_video.job.render", {"job_id": job_id, "render": req.model_dump()}, user)
@router.post("/jobs/{job_id}/cancel")
async def cancel(job_id: str, user: User = Depends(get_current_user)): return await call("cs2_video.job.cancel", {"job_id": job_id}, user)
@router.post("/jobs/{job_id}/retry")
async def retry(job_id: str, user: User = Depends(get_current_user)): return await call("cs2_video.job.retry", {"job_id": job_id}, user)
@router.get("/settings")
async def insight_settings(user: User = Depends(get_current_user)): return await call("cs2_video.settings.get", {}, user)
@router.put("/settings")
async def update_insight_settings(req: InsightSettingsRequest, user: User = Depends(get_current_user)): return await call("cs2_video.settings.update", req.model_dump(), user)
