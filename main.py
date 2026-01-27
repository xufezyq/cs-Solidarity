from Trainspotting import Trainspotting

STEAM_API_KEY = "4C858E561994F8B512A4402905DB607C"
STEAM_ID = "76561198383859685"
WECHAT_WEBHOOK_KEY = "f80920f2-f924-499a-a741-94139b8aafe0"
    
if __name__ == "__main__":
    trainspotting = Trainspotting(STEAM_API_KEY, STEAM_ID, WECHAT_WEBHOOK_KEY)
    trainspotting.start()