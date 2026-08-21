from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from core.base_instance import BaseInstance
from utils.teamspeak_service import TeamSpeakConfigError, TeamSpeakQueryError, get_default_teamspeak_service


log = logging.getLogger(__name__)


class TeamSpeakAuto(BaseInstance):
    """Background TeamSpeak music bot recycler."""

    def __init__(self, config_path: str | None = None, check_interval_seconds: int | None = None, root_dir: str | Path | None = None):
        self.root_dir = Path(root_dir or Path.cwd()).resolve()
        self.config_path = config_path
        self.service = get_default_teamspeak_service(root_dir=self.root_dir, config_path=config_path)
        self.check_interval_seconds = int(check_interval_seconds or self.service.config.check_interval_seconds)
        self._config_error_logged = False

    @staticmethod
    def create_from_data(data: dict[str, Any] | None = None) -> "TeamSpeakAuto":
        item = data or {}
        config_path = item.get("config") or item.get("config_path")
        check_interval = item.get("check_interval_seconds") or item.get("check_interval")
        return TeamSpeakAuto(config_path=config_path, check_interval_seconds=check_interval)

    @staticmethod
    def create_from_config(config_path: str | None = None) -> "TeamSpeakAuto":
        return TeamSpeakAuto(config_path=config_path)

    def send_message(self, message: str):
        """TeamSpeak recycler does not send WeChat messages."""
        return None

    def start(self):
        log.info(
            f"[{datetime.now()}] TeamSpeak 自动回收启动，"
            f"每 {self.check_interval_seconds}s 检查一次，home cid={self.service.config.home_channel_id}"
        )
        while True:
            try:
                result = self.service.check_empty_return()
                self._config_error_logged = False
                if result.get("moved"):
                    log.info(f"[{datetime.now()}] TeamSpeak 自动回收完成: {result.get('move', result)}")
            except TeamSpeakConfigError as exc:
                if not self._config_error_logged:
                    log.warning(f"[{datetime.now()}] TeamSpeak 自动回收未启用: {exc}")
                    self._config_error_logged = True
            except (OSError, TeamSpeakQueryError, ValueError) as exc:
                log.info(f"[{datetime.now()}] TeamSpeak 自动回收检查失败: {exc}")
            except Exception as exc:
                log.exception(f"[{datetime.now()}] TeamSpeak 自动回收异常: {exc}")
            time.sleep(max(1, self.check_interval_seconds))
