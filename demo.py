from wxauto import WeChat
from Trainspotting import Trainspotting

STEAM_API_KEY = "4C858E561994F8B512A4402905DB607C"
STEAM_ID = "76561198383859685"
WECHAT_WEBHOOK_KEY = "f80920f2-f924-499a-a741-94139b8aafe0"
    
if __name__ == "__main__":
    # wx = WeChat()

    # # 发送消息
    # who = '【CS】团结友爱'
    # for i in range(3):
    #     wx.SendMsg(f'wxauto测试{i+1}', who)
        
    # 获取当前聊天页面（文件传输助手）消息，并自动保存聊天图片
    # msgs = wx.GetAllMessage(savepic=True)
    # for msg in msgs:
    #     print(f"{msg[0]}: {msg[1]}")
    # print('wxauto测试完成！')

    trainspotting = Trainspotting(STEAM_API_KEY, STEAM_ID, WECHAT_WEBHOOK_KEY)
    trainspotting.start()