import time
import json
import logging
from datetime import datetime
import schedule
from pathlib import Path
from core.base_instance import BaseInstance
from core.wechat_instance import get_wechat, is_using_wxauto

log = logging.getLogger(__name__)


class DailyAuto(BaseInstance):
    def __init__(self, wechat_groups=None, send_time="08:00", message="", debug=False):
        self.wechat_groups = []
        if wechat_groups:
            if isinstance(wechat_groups, list):
                self.wechat_groups = wechat_groups
            else:
                self.wechat_groups = [wechat_groups]
        else:
            self.wechat_groups = ['文件传输助手']

        self.send_time = send_time
        self.message = message
        self.debug = debug

    def send_message(self, message):
        """发送消息到所有配置的微信群/个人"""
        if not message or not message.strip():
            log.debug("[DailyAuto] 消息为空，跳过发送")
            return

        log.debug(f"[DailyAuto] 开始发送消息到 {len(self.wechat_groups)} 个群/个人")
        for group in self.wechat_groups:
            try:
                wx = get_wechat()
                wx.SendMsg(message, group)
                log.info(f"[DailyAuto] 消息已发送到：{group}")
            except Exception as e:
                log.error(f"[DailyAuto] 发送消息到 {group} 失败：{e}")
                import traceback
                log.debug(traceback.format_exc())

    def start(self):
        """启动每日定时发送"""
        if self.debug:
            log.info(f"[DailyAuto] DEBUG 模式，立即发送消息")
            log.debug(f"[DailyAuto] message 内容: '{self.message}'")
            log.debug(f"[DailyAuto] wechat_groups: {self.wechat_groups}")
            self.send_message(self.message)
            log.debug("[DailyAuto] send_message 调用完成，消息已入队")
            time.sleep(2)
            return

        def safe_send():
            try:
                from core import check_maintenance
                if check_maintenance():
                    log.info("[DailyAuto] 当前在维护时段，跳过发送")
                    return
            except (ImportError, AttributeError):
                pass
            self.send_message(self.message)

        log.info(f"[DailyAuto] 启动，计划每天 {self.send_time} 发送固定消息")
        schedule.every().day.at(self.send_time).do(safe_send)

        try:
            while True:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            log.info("[DailyAuto] 程序已停止")

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

        try:
            with open('config.json', 'r', encoding='utf-8') as f:
                master_config = json.load(f)
                debug_mode = master_config.get('debug_mode', False)
        except Exception:
            debug_mode = False

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
