"""
Web API — TeamSpeak music bot control.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from web.auth import User, get_current_user
from web.bridge import bridge


router = APIRouter(prefix="/api/teamspeak", tags=["TeamSpeak"])


class TeamSpeakMoveRequest(BaseModel):
    target_cid: int


@router.get("/status")
async def get_teamspeak_status(current_user: User = Depends(get_current_user)):
    result = await bridge.send_request("teamspeak.status", timeout=15)
    if not result.get("success"):
        return {
            "success": True,
            "data": {
                "connected": False,
                "error": result.get("error", "Agent 请求失败"),
                "channels": [],
                "clients": [],
                "music_bot": {"online": False, "is_home": False},
                "online_human_count": 0,
            },
        }
    return {"success": True, "data": result.get("data", {})}


@router.post("/music-bot/move")
async def move_music_bot(req: TeamSpeakMoveRequest, current_user: User = Depends(get_current_user)):
    result = await bridge.send_request("teamspeak.move_music_bot", {"target_cid": req.target_cid}, timeout=15)
    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "Agent 请求失败"))
    return {"success": True, "data": result.get("data", {})}


@router.post("/music-bot/home")
async def move_music_bot_home(current_user: User = Depends(get_current_user)):
    result = await bridge.send_request("teamspeak.move_music_bot_home", timeout=15)
    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "Agent 请求失败"))
    return {"success": True, "data": result.get("data", {})}
