import requests
import json

class WeChatRobot:
    def __init__(self, webhook_key):
        self.webhook_key = webhook_key
        self.url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={self.webhook_key}"
        self.headers = {
            "Content-Type": "application/json"
        }

    def send_message(self, content):
        data = {
            "msgtype": "text",
            "text": {
                "content": content
            }
        }

        try:
            response = requests.post(self.url, headers=self.headers, data=json.dumps(data))
            if response.status_code == 200 and response.json().get("errcode") == 0:
                print("消息发送成功！")
            else:
                print(f"发送失败：{response.text}")
        except Exception as e:
            print(f"请求出错：{e}")

if __name__ == "__main__":
    webhook_key = "f80920f2-f924-499a-a741-94139b8aafe0"
    robot = WeChatRobot(webhook_key)
    robot.send_message("Hello from WeChat Robot!")