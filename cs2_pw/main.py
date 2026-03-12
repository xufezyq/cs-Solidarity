import asyncio
import os
from .request import PerfectWorldApi

async def main():
    # 请在这里填入你的 完美平台 ID (Steam ID) 和 Token
    # 你可以通过抓包完美平台 App 获取 Token
    uid = "76561199209601450"  # 例如: "76561198xxxxxxxxx"
    token = "6cb373b9a2d2dcf371d9d938474deb7c484d72b8" # 例如: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    # 如果环境变量中有配置，则优先使用环境变量
    if os.getenv("CS2_UID"):
        uid = os.getenv("CS2_UID")
    if os.getenv("CS2_TOKEN"):
        token = os.getenv("CS2_TOKEN")

    if uid == "" or token == "":
        print("请在 main.py 中配置 uid 和 token，或者设置 CS2_UID 和 CS2_TOKEN 环境变量。")
        return

    print(f"正在使用 UID: {uid} 和 Token: {token[:5]}... 进行测试")

    api = PerfectWorldApi(uid=uid, token=token)

    try:
        # # 测试 3: 搜索玩家
        # print("\n--- 搜索玩家 ---")
        # search_data = await api.search_player("76561198383859685")
        # print(search_data)
        
        # # 测试 3: 获取比赛详情
        # print("\n--- 获取比赛详情 ---")
        # match_detail = await api.get_match_detail("9206308531350259852")
        # print(match_detail)

        # # 测试 4: 获取用户详情
        # print("\n--- 获取用户详情 ---")
        # user_detail = await api.get_userdetail("76561198383859685")
        # print(user_detail)

        # # 测试 1: 获取用户信息
        # print("\n--- 获取用户信息 ---")
        # user_info = await api.get_userinfo("76561198383859685")
        # print(user_info)

        # 测试 6: 获取用户箱子记录
        print("\n--- 箱子记录 ---")
        fail_records = await api.get_fall("76561198383859685")
        print(fail_records)

        # 测试 2: 获取最近比赛
        print("\n--- 获取最近比赛 ---")
        # type: -1全部, 41pro, 12/0天梯, 20巅峰赛, 27周末联赛, 14自定义
        match_data = await api.get_csgopfmatch("76561199262650715", csgoSeasonId=3, type=-1)
        print(match_data)
        
        if isinstance(match_data, dict) and "data" in match_data:
             matches = match_data["data"].get("matchList", [])
             if matches:
                 last_match_id = matches[0]["matchId"]
                 data_source = matches[0].get("dataSource", 3)
                 print(f"\n--- 获取最近一场比赛详情 ({last_match_id}, source: {data_source}) ---")
                 match_detail = await api.get_match_detail(last_match_id, dataSource=data_source)
                 print(match_detail)

    except Exception as e:
        print(f"发生错误: {e}")

if __name__ == "__main__":
    asyncio.run(main())
