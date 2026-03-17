import time
import json
from datetime import datetime
import schedule
from pathlib import Path
from core.base_instance import BaseInstance
from core.wechat_instance import *
from pywechat.WechatAuto import Messages

class DailyAuto(BaseInstance):
    def __init__(self, wechat_groups=None, send_time="08:00", message=""):
        # 配置接收消息的微信群/个人
        self.wechat_groups = []
        if wechat_groups:
            if isinstance(wechat_groups, list):
                self.wechat_groups = wechat_groups
            else:
                self.wechat_groups = [wechat_groups]
        else:
            self.wechat_groups = ['文件传输助手']

        # 每日固定发送的时刻（"HH:MM" 或 "HH:MM:SS"）
        self.send_time = send_time
        # 每日固定发送的消息内容
        self.message = message

    def send_message(self, message):
        """
        发送消息到所有配置的微信群/个人
        :param message: 要发送的消息内容
        """
        if not message or not message.strip():
            return

        for group in self.wechat_groups:
            try:
                if is_using_wxauto():
                    get_wechat().SendMsg(message, group)
                else:
                    Messages.send_messages_to_friend(friend=group, messages=[message], delay=0.2, tickle=False, search_pages=0)

                print(f"[{datetime.now()}] 消息已发送到: {group}")
            except Exception as e:
                print(f"[{datetime.now()}] 发送消息到 {group} 失败: {e}")

    def start(self):
        """
        启动每日定时发送
        """
        print(f"[{datetime.now()}] DailyAuto 启动，计划每天 {self.send_time} 发送固定消息")
        scheduler = schedule.Scheduler()
        # 每天固定时刻发送
        scheduler.every().day.at(self.send_time).do(lambda: self.send_message(self.message))

        try:
            while True:
                scheduler.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n[{datetime.now()}] DailyAuto 程序已停止")

    @classmethod
    def create_from_config(cls, config_path: str):
        """从配置文件创建 DailyAuto 实例"""
        if not Path(config_path).exists():
            raise FileNotFoundError(f"配置文件 {config_path} 不存在")

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        return DailyAuto(
            wechat_groups=config.get('wechat_groups', ['文件传输助手']),
            send_time=config.get('time', '08:00'),
            message=config.get('message', '')
        )

    @classmethod
    def create_from_data(cls, data: dict):
        """从字典数据创建 DailyAuto 实例"""
        if not isinstance(data, dict):
            raise TypeError("DailyAuto.create_from_data 需要传入字典数据")

        return DailyAuto(
            wechat_groups=data.get("wechat_groups", []),
            send_time=data.get("time", "08:00"),
            message=data.get("message", ""),
        )