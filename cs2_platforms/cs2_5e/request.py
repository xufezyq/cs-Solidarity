import json as js
import logging
from copy import deepcopy
from typing import Any, Dict, List, Literal, Optional, Union

from httpx import AsyncClient

from .api import (
    DEFAULT_HEADERS,
    ELO_LEVELS,
    HOST,
    ID_TRANSFER_API,
    MATCH_DETAIL_API,
    MATCH_LIST_API,
    PLAYER_CAREER_API,
    PLAYER_HOME_API,
    SEARCH_API,
    STEAM_USERNAME_API,
)

logger = logging.getLogger("CS2.5E")


class FiveEApi:
    """Async 5EPlay API client."""

    ssl_verify = False

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self.headers: Dict[str, str] = DEFAULT_HEADERS

    async def _request(
        self,
        url: str,
        method: Literal["GET", "POST"] = "GET",
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        need_headers: bool = True,
    ) -> Union[Dict[str, Any], List[Any], int, str]:
        request_headers = deepcopy(headers or self.headers) if need_headers else None
        if json is not None:
            method = "POST"

        async with AsyncClient(verify=self.ssl_verify) as client:
            try:
                resp = await client.request(
                    method,
                    url=url,
                    headers=request_headers,
                    params=params,
                    json=json,
                    data=data,
                    timeout=self.timeout,
                )
                try:
                    raw_data = resp.json()
                except Exception:
                    try:
                        raw_data = js.loads(resp.text)
                    except Exception:
                        raw_data = resp.text
                if resp.status_code >= 400:
                    return {
                        "_http_status": resp.status_code,
                        "_url": str(resp.url),
                        "_body": raw_data,
                    }
                return raw_data
            except Exception as e:
                logger.error("5E request failed: %s %s, %s", method, url, e)
                return -1

    @staticmethod
    def asset_url(path: Optional[str]) -> str:
        if not path:
            return ""
        if path.startswith(("http://", "https://")):
            return path
        return f"{HOST.rstrip('/')}/{path.lstrip('/')}"

    @staticmethod
    def elo_level_name(elo: Any) -> str:
        try:
            elo_num = int(float(elo))
        except (TypeError, ValueError):
            return "未定级"
        if elo_num < 1:
            return "未定级"
        result = "S"
        thresholds = sorted(ELO_LEVELS.keys())
        for index, threshold in enumerate(thresholds):
            previous = 1 if index == 0 else thresholds[index - 1] + 1
            if previous <= elo_num <= threshold:
                result = ELO_LEVELS[threshold]
                break
        return result

    async def get_username_by_steam_id(self, steam_id: str) -> Optional[str]:
        data = await self._request(f"{STEAM_USERNAME_API}/{steam_id}", need_headers=False)
        if isinstance(data, int):
            return None
        try:
            username = data["data"]["username"]  # type: ignore[index]
            return str(username) if username else None
        except Exception:
            return None

    async def search_player(self, keyword: str) -> Union[List[Dict[str, Any]], int]:
        data = await self._request(SEARCH_API, params={"keywords": keyword}, need_headers=False)
        if isinstance(data, int):
            return data
        try:
            users = data["data"]["user"]["list"]  # type: ignore[index]
            return users if isinstance(users, list) else []
        except Exception:
            return []

    async def get_uuid(self, domain: str) -> Optional[str]:
        data = await self._request(ID_TRANSFER_API, json={"trans": {"domain": domain}})
        if isinstance(data, int):
            return None
        try:
            uuid = data["data"]["uuid"]  # type: ignore[index]
            return str(uuid) if uuid else None
        except Exception:
            return None

    async def resolve_user_by_steam_id(self, steam_id: str) -> Optional[Dict[str, str]]:
        username = await self.get_username_by_steam_id(steam_id)
        if not username:
            return None
        users = await self.search_player(username)
        if isinstance(users, int) or not users:
            return None

        selected = None
        for user in users:
            if user.get("username") == username:
                selected = user
                break
        selected = selected or users[0]
        domain = selected.get("domain")
        if not domain:
            return None
        uuid = await self.get_uuid(str(domain))
        if not uuid:
            return None
        return {
            "username": str(selected.get("username") or username),
            "domain": str(domain),
            "uuid": uuid,
            "avatar": self.asset_url(selected.get("avatar_url")),
        }

    async def get_player_home(self, uuid: str) -> Optional[Dict[str, Any]]:
        data = await self._request(PLAYER_HOME_API, params={"uuid": uuid})
        if isinstance(data, int):
            return None
        try:
            home = data["data"]  # type: ignore[index]
            return home if isinstance(home, dict) else None
        except Exception:
            return None

    async def get_player_career(self, uuid: str) -> Optional[Dict[str, Any]]:
        data = await self._request(PLAYER_CAREER_API, params={"uuid": uuid})
        if isinstance(data, int):
            return None
        try:
            career = data["data"]["career_data"]  # type: ignore[index]
            return career if isinstance(career, dict) else None
        except Exception:
            return None

    async def get_match_list(
        self,
        uuid: str,
        limit: int = 20,
        match_type: int = -1,
        data_source: int = 0,
        cs_type: int = 0,
    ) -> Union[List[Dict[str, Any]], int]:
        params = {
            "match_type": match_type,
            "page": 1,
            "data": data_source,
            "start_time": 0,
            "end_time": 0,
            "uuid": uuid,
            "limit": limit,
            "cs_type": cs_type,
        }
        data = await self._request(MATCH_LIST_API, params=params)
        if isinstance(data, int):
            return data
        try:
            matches = data.get("data", [])  # type: ignore[union-attr]
            return matches if isinstance(matches, list) else []
        except Exception:
            return []

    async def get_match_detail(self, match_id: str) -> Optional[Dict[str, Any]]:
        data = await self._request(f"{MATCH_DETAIL_API}/{match_id}")
        if isinstance(data, int):
            return None
        try:
            detail = data["data"]  # type: ignore[index]
            return detail if isinstance(detail, dict) else None
        except Exception:
            return None
