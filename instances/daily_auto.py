import time
import json
from datetime import datetime
import schedule
from pathlib import Path
from core.base_instance import BaseInstance
from core.wechat_instance import *
from pywechat.WechatAuto import Messages

class DailyAuto(BaseInstance):
    def __init__(self, wechat_groups=None, send_time="08:00", message="", debug=False):
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
        # debug 模式：True 时立即发送一次，不等待定时时间
        self.debug = debug

    def send_message(self, message):
        """
        发送消息到所有配置的微信群/个人
        :param message: 要发送的消息内容
        """
        print(f"[DEBUG] send_message 被调用：message='{message}'")
        if not message or not message.strip():
            print(f"[DEBUG] 消息为空，跳过发送")
            return

        print(f"[DEBUG] 开始发送消息到 {len(self.wechat_groups)} 个群组/个人")
        for group in self.wechat_groups:
            try:
                if is_using_wxauto():
                    get_wechat().SendMsg(message, group)
                else:
                    Messages.send_messages_to_friend(friend=group, messages=[message], delay=0.2, tickle=False, search_pages=0)

                print(f"[{datetime.now()}] 消息已发送到：{group}")
            except Exception as e:
                print(f"[{datetime.now()}] 发送消息到 {group} 失败：{e}")
                import traceback
                traceback.print_exc()

    def start(self):
        """
        启动每日定时发送
        """
        if self.debug:
            print(f"[{datetime.now()}] DailyAuto 启动 (DEBUG 模式)，立即发送消息")
            print(f"[DEBUG] message 内容：'{self.message}'")
            print(f"[DEBUG] wechat_groups: {self.wechat_groups}")
            self.send_message(self.message)
            print(f"[DEBUG] send_message 调用完成，消息已入队")
            # 等待一小段时间让主线程处理队列
            time.sleep(2)
            return
        
        print(f"[{datetime.now()}] DailyAuto 启动，计划每天 {self.send_time} 发送固定消息")
        # 每天固定时刻发送
        schedule.every().day.at(self.send_time).do(lambda: self.send_message(self.message))

        try:
            while True:
                schedule.run_pending()
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

        # 尝试从主配置文件读取 debug_mode
        try:
            with open('config.json', 'r', encoding='utf-8') as f:
                master_config = json.load(f)
                debug_mode = master_config.get('debug_mode', False)
        except Exception:
            debug_mode = False

        # 如果 data 中包含 config 路径，先加载配置文件
        if 'config' in data:
            config_path = data['config']
            if not Path(config_path).exists():
                raise FileNotFoundError(f"配置文件 {config_path} 不存在")
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        else:
            config = data

        return DailyAuto(
            wechat_groups=config.get("wechat_groups", []),
            send_time=config.get("time", "08:00"),
            message=config.get("message", ""),
            debug=debug_mode or config.get("debug", False)
        )
