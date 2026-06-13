"""5EPlay API endpoints used by SteamAuto."""

from typing import Dict

HOST = "https://oss-arena.5eplay.com/"
SEARCH_API = "https://arena.5eplay.com/api/search/player/1/16"
ID_TRANSFER_API = "https://gate.5eplay.com/userinterface/http/v1/userinterface/idTransfer"
MATCH_LIST_API = "https://gate.5eplay.com/crane/http/api/data/match/list"
MATCH_DETAIL_API = "https://gate.5eplay.com/crane/http/api/data/match"
PLAYER_HOME_API = "https://gate.5eplay.com/crane/http/api/data/v3/player/home"
PLAYER_CAREER_API = "https://gate.5eplay.com/crane/http/api/data/player_career"
STEAM_USERNAME_API = "https://api-client-arena.5eplay.com/api/user/steam_username"

DEFAULT_HEADERS: Dict[str, str] = {
    "Accept": "*/*",
    "Accept-Language": "zh-cn",
    "Authorization": "",
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/132.0.0.0 Safari/537.36"
    ),
    "x-ca-key": "5eplay",
    "x-ca-signature": "pm/c+nYSScWXLOYG7WCczBallQAPFsQ+mu3szgvr7xg=",
    "x-ca-signature-headers": "Accept-Language,Authorization",
    "x-ca-signature-method": "HmacSHA256",
}

ELO_LEVELS: Dict[int, str] = {
    1200: "D",
    1350: "C",
    1500: "C+",
    1600: "精英C+",
    1750: "B",
    1900: "B+",
    2000: "精英B+",
    2150: "A",
    2300: "A+",
    2400: "精英A+",
    2401: "S",
}
