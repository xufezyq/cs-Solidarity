"""
完美世界CSGO平台API封装

参考:
- /Users/lintao/CS/PerfectWorld-API-Collection-master/docs/
- /Users/lintao/CS/cs-Solidarity/steam/SteamAPI.py
"""

import requests
import json
from typing import Optional, Dict, List, Any
from datetime import datetime
from pathlib import Path
import urllib3

# 禁用SSL警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class AuthToken:
    """认证令牌数据类"""

    def __init__(self, token: str, steam_id: int, user_id: int = 0,
                 mobile_phone: str = "", created_at: int = 0):
        self.token = token
        self.steam_id = steam_id
        self.user_id = user_id
        self.mobile_phone = mobile_phone
        self.created_at = created_at

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "token": self.token,
            "steam_id": self.steam_id,
            "user_id": self.user_id,
            "mobile_phone": self.mobile_phone,
            "created_at": self.created_at,
            "saved_at": int(datetime.now().timestamp())
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AuthToken':
        """从字典创建"""
        return cls(
            token=data.get("token", ""),
            steam_id=data.get("steam_id", 0),
            user_id=data.get("user_id", 0),
            mobile_phone=data.get("mobile_phone", ""),
            created_at=data.get("created_at", 0)
        )


class PerfectWorldAPIError(Exception):
    """API错误基类"""
    pass


class AuthenticationError(PerfectWorldAPIError):
    """认证错误"""
    pass


class APIRequestError(PerfectWorldAPIError):
    """API请求错误"""
    pass


class PerfectWorldAPI:
    """完美世界CSGO平台API封装"""

    # API基础URL
    PASSPORT_BASE_URL = "https://passport.pwesports.cn"
    API_BASE_URL = "https://api.wmpvp.com/api/csgo"
    SEARCH_BASE_URL = "https://appengine.wmpvp.com/steamcn/app"

    # 常量
    APP_ID = 2
    APP_VERSION = "3.5.4.172"
    PLATFORM = "android"
    GAME_TYPE = "1,2"

    def __init__(self, verify_ssl: bool = False):
        """
        初始化API客户端

        Args:
            verify_ssl: 是否验证SSL证书
        """
        self.verify_ssl = verify_ssl
        self.session = requests.Session()
        self._auth_token: Optional[AuthToken] = None

    @property
    def is_authenticated(self) -> bool:
        """检查是否已认证"""
        return self._auth_token is not None

    @property
    def steam_id(self) -> Optional[int]:
        """获取当前登录的Steam ID"""
        return self._auth_token.steam_id if self._auth_token else None

    def _get_default_headers(self, include_auth: bool = True) -> Dict[str, str]:
        """
        获取默认请求头

        Args:
            include_auth: 是否包含认证信息

        Returns:
            请求头字典
        """
        headers = {
            "appversion": self.APP_VERSION,
            "platform": self.PLATFORM,
            "gameType": self.GAME_TYPE,
            "gameTypeStr": self.GAME_TYPE,
            "Content-Type": "application/json"
        }

        if include_auth and self._auth_token:
            headers["token"] = self._auth_token.token

        return headers

    def _handle_response(self, response: requests.Response,
                        api_name: str) -> Dict[str, Any]:
        """
        统一处理API响应

        Args:
            response: requests响应对象
            api_name: API名称（用于错误信息）

        Returns:
            解析后的JSON数据

        Raises:
            APIRequestError: 请求失败
        """
        try:
            data = response.json()
        except json.JSONDecodeError:
            raise APIRequestError(f"{api_name}: 无法解析响应数据")

        # HTTP状态码检查
        if response.status_code != 200:
            raise APIRequestError(
                f"{api_name}: HTTP错误 {response.status_code}"
            )

        return data

    # ==================== 认证相关 ====================

    def login(self, mobile_phone: str, security_code: str) -> AuthToken:
        """
        登录完美平台

        Args:
            mobile_phone: 手机号
            security_code: 验证码

        Returns:
            AuthToken对象

        Raises:
            AuthenticationError: 登录失败
        """
        url = f"{self.PASSPORT_BASE_URL}/account/login"
        payload = {
            "appId": self.APP_ID,
            "mobilePhone": mobile_phone,
            "securityCode": security_code
        }

        try:
            response = self.session.post(
                url,
                json=payload,
                verify=self.verify_ssl,
                timeout=10
            )
            data = self._handle_response(response, "登录")

            # 检查返回码
            if data.get("code") != 0:
                raise AuthenticationError(
                    f"登录失败: {data.get('description', '未知错误')}"
                )

            # 提取认证信息
            account_info = data["result"]["loginResult"]["accountInfo"]
            self._auth_token = AuthToken(
                token=account_info["token"],
                steam_id=account_info["steamId"],
                user_id=account_info["userId"],
                mobile_phone=account_info["mobilePhone"],
                created_at=account_info["create"]
            )

            print(f"[{datetime.now()}] 登录成功，Steam ID: {self._auth_token.steam_id}")
            return self._auth_token

        except requests.RequestException as e:
            raise AuthenticationError(f"登录请求失败: {str(e)}")

    def set_token(self, token: str, steam_id: int):
        """
        手动设置token（用于token持久化后的恢复）

        Args:
            token: 认证令牌
            steam_id: Steam ID
        """
        self._auth_token = AuthToken(
            token=token,
            steam_id=steam_id,
            user_id=0,
            mobile_phone="",
            created_at=0
        )

    def load_token_from_file(self, token_path: str) -> bool:
        """
        从文件加载token

        Args:
            token_path: token文件路径

        Returns:
            是否加载成功
        """
        try:
            path = Path(token_path)
            if not path.exists():
                return False

            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self._auth_token = AuthToken.from_dict(data)
            print(f"[{datetime.now()}] 从文件加载token成功，Steam ID: {self._auth_token.steam_id}")
            return True

        except (json.JSONDecodeError, KeyError) as e:
            print(f"[{datetime.now()}] 加载token文件失败: {e}")
            return False

    def save_token_to_file(self, token_path: str):
        """
        保存token到文件

        Args:
            token_path: token文件路径
        """
        if not self._auth_token:
            return

        try:
            path = Path(token_path)
            path.parent.mkdir(parents=True, exist_ok=True)

            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self._auth_token.to_dict(), f, indent=2, ensure_ascii=False)

            print(f"[{datetime.now()}] Token已保存到: {token_path}")

        except Exception as e:
            print(f"[{datetime.now()}] 保存token文件失败: {e}")

    def logout(self):
        """登出（清除本地token）"""
        self._auth_token = None

    # ==================== 玩家数据相关 ====================

    def get_player_stats(self, to_steam_id: int,
                        my_steam_id: Optional[int] = None,
                        csgo_season_id: str = "") -> Dict[str, Any]:
        """
        获取玩家详细统计数据

        Args:
            to_steam_id: 被查询玩家的Steam ID
            my_steam_id: 查询者的Steam ID（默认使用登录账号）
            csgo_season_id: 赛季ID（可选）

        Returns:
            玩家统计数据字典

        Raises:
            AuthenticationError: 未认证
            APIRequestError: 请求失败
        """
        if not self.is_authenticated:
            raise AuthenticationError("请先登录")

        if my_steam_id is None:
            my_steam_id = self._auth_token.steam_id

        url = f"{self.API_BASE_URL}/home/pvp/detailStats"
        payload = {
            "mySteamId": my_steam_id,
            "toSteamId": to_steam_id,
            "accessToken": "",
            "csgoSeasonId": csgo_season_id
        }

        try:
            response = self.session.post(
                url,
                json=payload,
                headers=self._get_default_headers(),
                verify=self.verify_ssl,
                timeout=15
            )
            data = self._handle_response(response, "获取玩家统计")

            # 检查状态码
            if data.get("statusCode") != 0:
                error_msg = data.get('errorMessage', '未知错误')
                # token失效检测
                if 'token' in error_msg.lower() or 'auth' in error_msg.lower():
                    raise AuthenticationError(f"Token失效: {error_msg}")
                raise APIRequestError(f"获取玩家统计失败: {error_msg}")

            return data["data"]

        except requests.RequestException as e:
            raise APIRequestError(f"获取玩家统计请求失败: {str(e)}")

    # ==================== 比赛记录相关 ====================

    def get_match_list(self, to_steam_id: int,
                      my_steam_id: Optional[int] = None,
                      page: int = 1,
                      page_size: int = 50,
                      csgo_season_id: str = "recent",
                      data_source: int = 3,
                      pvp_type: int = -1) -> Dict[str, Any]:
        """
        获取比赛记录列表

        Args:
            to_steam_id: 被查询玩家的Steam ID
            my_steam_id: 查询者的Steam ID（默认使用登录账号，必须与token匹配）
            page: 页码（从1开始）
            page_size: 每页记录数
            csgo_season_id: 赛季ID（"recent"表示最近）
            data_source: 数据源
            pvp_type: 对战类型

        Returns:
            包含matchList的数据字典

        Raises:
            AuthenticationError: 未认证或Steam ID不匹配
            APIRequestError: 请求失败
        """
        if not self.is_authenticated:
            raise AuthenticationError("请先登录")

        if my_steam_id is None:
            my_steam_id = self._auth_token.steam_id
        elif my_steam_id != self._auth_token.steam_id:
            raise AuthenticationError(
                "mySteamId必须与token对应的Steam ID一致"
            )

        url = f"{self.API_BASE_URL}/home/match/list"
        payload = {
            "mySteamId": my_steam_id,
            "toSteamId": to_steam_id,
            "page": page,
            "pageSize": page_size,
            "csgoSeasonId": csgo_season_id,
            "dataSource": data_source,
            "pvpType": pvp_type
        }

        try:
            response = self.session.post(
                url,
                json=payload,
                headers=self._get_default_headers(),
                verify=self.verify_ssl,
                timeout=15
            )
            data = self._handle_response(response, "获取比赛记录")

            # 检查状态码
            if data.get("statusCode") != 0:
                error_msg = data.get('errorMessage', '未知错误')
                # token失效检测
                if 'token' in error_msg.lower() or 'auth' in error_msg.lower():
                    raise AuthenticationError(f"Token失效: {error_msg}")
                raise APIRequestError(f"获取比赛记录失败: {error_msg}")

            return data["data"]

        except requests.RequestException as e:
            raise APIRequestError(f"获取比赛记录请求失败: {str(e)}")

    # ==================== 搜索功能 ====================

    def search_users(self, keyword: str, page: int = 1) -> List[Dict[str, Any]]:
        """
        搜索用户

        Args:
            keyword: 搜索关键词（昵称）
            page: 页码（推荐使用1）

        Returns:
            用户列表

        Raises:
            AuthenticationError: 未认证
            APIRequestError: 请求失败
        """
        if not self.is_authenticated:
            raise AuthenticationError("请先登录")

        url = f"{self.SEARCH_BASE_URL}/search/user"
        payload = {
            "keyword": keyword,
            "page": page
        }

        try:
            response = self.session.post(
                url,
                json=payload,
                headers=self._get_default_headers(),
                verify=self.verify_ssl,
                timeout=10
            )
            data = self._handle_response(response, "搜索用户")

            # 检查状态码
            if data.get("code") != 1:
                raise APIRequestError(
                    f"搜索用户失败: {data.get('message', '未知错误')}"
                )

            return data.get("result", [])

        except requests.RequestException as e:
            raise APIRequestError(f"搜索用户请求失败: {str(e)}")

    # ==================== 辅助方法 ====================

    def get_match_result(self, match: Dict[str, Any]) -> str:
        """判断比赛结果"""
        if match.get("team") == match.get("winTeam"):
            return "胜利"
        return "失败"

    def format_match_score(self, match: Dict[str, Any]) -> str:
        """格式化比赛比分"""
        return f"{match.get('score1', 0)} : {match.get('score2', 0)}"

    def get_kd_ratio(self, kill: int, death: int) -> float:
        """计算K/D比"""
        if death == 0:
            return float(kill)
        return round(kill / death, 2)
