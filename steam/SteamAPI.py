import requests
import json

# 禁用SSL警告（可选，避免控制台输出警告信息）
requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

class SteamAPI:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.steampowered.com/"  # 建议使用HTTPS更安全
        # 在线状态码映射（中文）
        self.STATE_MAP = {
            0: "离线",
            1: "在线",
            2: "忙碌",
            3: "离开",
            4: "暂离/睡眠",
            5: "求交易",
            6: "求组队"
        }
    
    def get_steam_id(self, vanity_url):
        """通过自定义URL解析SteamID64"""
        url = f"{self.base_url}ISteamUser/ResolveVanityURL/v0001/"
        params = {"key": self.api_key, "vanityurl": vanity_url}
        try:
            response = requests.get(url, params=params, verify=False)
            response.raise_for_status()  # 抛出HTTP错误
            data = response.json()
            if data["response"]["success"] == 1:
                return data["response"]["steamid"]
            else:
                print(f"获取Steam ID失败: {data['response']['message']}")
                return None
        except requests.exceptions.RequestException as e:
            print(f"解析自定义URL请求错误: {e}")
            return None
    
    def get_player_summary(self, steam_id):
        """获取单个用户的基础信息（含自身状态）"""
        url = f"{self.base_url}ISteamUser/GetPlayerSummaries/v0002/"
        params = {"key": self.api_key, "steamids": steam_id}
        try:
            response = requests.get(url, params=params, verify=False)
            response.raise_for_status()
            data = response.json()
            if data["response"]["players"]:
                return data["response"]["players"][0]
            else:
                print("未找到用户信息")
                return None
        except requests.exceptions.RequestException as e:
            print(f"获取用户信息请求错误: {e}")
            return None
    
    def get_owned_games(self, steam_id, include_free_games=True):
        """获取用户拥有的游戏列表"""
        url = f"{self.base_url}IPlayerService/GetOwnedGames/v0001/"
        params = {
            "key": self.api_key,
            "steamid": steam_id,
            "include_appinfo": 1,
            "include_played_free_games": 1 if include_free_games else 0
        }
        try:
            response = requests.get(url, params=params, verify=False)
            response.raise_for_status()
            data = response.json()
            return data["response"].get("games", [])
        except requests.exceptions.RequestException as e:
            print(f"获取拥有游戏请求错误: {e}")
            return None
    
    def get_app_details(self, app_id):
        """获取单款游戏的详细信息"""
        url = f"https://store.steampowered.com/api/appdetails/"
        params = {"appids": app_id, "cc": "cn", "l": "zh-CN"}
        try:
            response = requests.get(url, params=params, verify=False)
            response.raise_for_status()
            data = response.json()
            if data[str(app_id)]["success"]:
                return data[str(app_id)]["data"]
            else:
                print(f"获取游戏详情失败: App ID {app_id} 不存在或无法访问")
                return None
        except requests.exceptions.RequestException as e:
            print(f"获取游戏详情请求错误: {e}")
            return None

    def get_friend_list(self, steam_id):
        """获取用户的双向好友列表（仅返回SteamID）"""
        url = f"{self.base_url}ISteamUser/GetFriendList/v0001/"
        # 必须添加 relationship=friend 参数，否则接口返回空
        params = {
            "key": self.api_key,
            "steamid": steam_id,
            "relationship": "friend"
        }
        try:
            response = requests.get(url, params=params, verify=False)
            response.raise_for_status()
            data = response.json()
            return data["friendslist"].get("friends", [])
        except requests.exceptions.RequestException as e:
            print(f"获取好友列表请求错误: {e}")
            return None
    
    def get_friend_status(self, steam_ids):
        """批量查询好友的在线状态和游戏状态"""
        if not steam_ids:
            print("好友SteamID列表为空")
            return []
        
        url = f"{self.base_url}ISteamUser/GetPlayerSummaries/v0002/"
        params = {
            "key": self.api_key,
            "steamids": ",".join(steam_ids)  # 拼接多个SteamID
        }
        try:
            response = requests.get(url, params=params, verify=False)
            response.raise_for_status()
            data = response.json()
            return data["response"]["players"]
        except requests.exceptions.RequestException as e:
            print(f"查询好友状态请求错误: {e}")
            return []
    
    def get_next_match_code(self, steam_id):
        """调用 Steam API 获取上一场比赛的 Share Code"""
        url = f"{self.base_url}ICSGOPlayers_730/GetNextMatchSharingCode/v1/"
        params = {
            'key': self.api_key,
            'steamid': steam_id,
            'steamidkey': self.auth_code,
            'knowncode': self.known_share_code
        }
        try:
            response = requests.get(url, params=params, verify=False)
            response.raise_for_status()
            data = response.json()
            return data['result']['nextcode']
        except requests.exceptions.RequestException as e:
            print(f"获取下一个比赛代码请求错误: {e}")
            return None

    def get_steam_news(self, app_id, count=5):
        """获取游戏的最新新闻"""
        url = f"{self.base_url}ISteamNews/GetNewsForApp/v2/"
        params = {
            "key": self.api_key,
            "appid": app_id,
            "count": count,
            "maxlength": 300
        }
        try:
            response = requests.get(url, params=params, verify=False)
            response.raise_for_status()
            data = response.json()
            return data["appnews"]["newsitems"]
        except requests.exceptions.RequestException as e:
            print(f"获取游戏新闻请求错误: {e}")
            return None

if __name__ == "__main__":
    # 配置参数
    API_KEY = ""  # 替换为你的API密钥
    VANITY_URL = ""    # 目标用户的自定义URL（如："xxx123"），为空则使用下面的SteamID
    STEAM_ID = ""  

    # 初始化SteamAPI实例
    steam_api = SteamAPI(API_KEY)
    
    # 获取目标用户的SteamID（优先用自定义URL解析，失败则用预设值）
    steam_id = steam_api.get_steam_id(VANITY_URL) if VANITY_URL else STEAM_ID
    if not steam_id:
        print("未获取到有效SteamID，程序退出")
        exit()
    
    print(f"=== 目标用户基础信息 ===")
    print(f"Steam ID: {steam_id}")
    
    # 获取目标用户自身状态
    player_summary = steam_api.get_player_summary(steam_id)
    if player_summary:
        nickname = player_summary.get('personaname', '未知')
        profile_url = player_summary.get('profileurl', '未知')
        state_code = player_summary.get('personastate', '未知')
        state_cn = steam_api.STATE_MAP.get(state_code, "未知状态")
        game_name = player_summary.get('gameextrainfo', '未游玩游戏')
        game_id = player_summary.get('gameid', '无')
        
        print(f"昵称: {nickname}")
        print(f"个人资料: {profile_url}")
        print(f"当前状态: {state_cn} (状态码: {state_code})")
        print(f"当前游玩: {game_name} (Game ID: {game_id})\n")

    # 获取好友列表并查询状态
    print(f"=== 好友在线&游戏状态 ===")
    friend_list = steam_api.get_friend_list(steam_id)
    if not friend_list:
        print("未获取到好友列表（可能是隐私设置/无双向好友）")
    else:
        # 提取所有好友的SteamID
        friend_steam_ids = [friend["steamid"] for friend in friend_list]
        print(f"共获取到 {len(friend_steam_ids)} 位双向好友\n")
        
        # 批量查询好友状态
        friend_steam_ids.append(steam_id)  # 把自己的状态也添加进去
        friend_status_list = steam_api.get_friend_status(friend_steam_ids)
        if not friend_status_list:
            print("未查询到任何好友的状态信息")
        else:
            # 遍历输出每个好友的状态
            for idx, friend in enumerate(friend_status_list, 1):
                nickname = friend.get('personaname', '未知昵称')
                steam_id = friend.get('steamid', '未知ID')
                state_code = friend.get('personastate', 0)
                state_cn = steam_api.STATE_MAP.get(state_code, "未知状态")
                game_name = friend.get('gameextrainfo', '未游玩游戏')
                game_id = friend.get('gameid', '无')
                last_offline = friend.get('lastlogoff', '未知')
                
                print(f"【{idx}】{nickname} ({steam_id})")
                print(f"  状态: {state_cn} | 游玩游戏: {game_name} (Game ID: {game_id})")
                print(f"  最后离线时间戳: {last_offline}\n")
    
    news_items = steam_api.get_steam_news(app_id = 730, count=1)
    if news_items:
        for news in news_items:
            title = news.get('title', '无标题')
            url = news.get('url', '无链接')
            contents = news.get('contents', '无摘要')
            print(f"新闻标题: {title}")
            print(f"新闻链接: {url}\n")
            print(f"新闻摘要：{contents}\n")
