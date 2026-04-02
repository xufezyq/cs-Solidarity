"""
cs-Solidarity Agent — 日志文件监听器

监听日志文件变化，通过 WebSocket 主动推送到 Server。
"""

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)


class LogWatcher:
    """监听日志文件变化，推送新内容"""

    def __init__(self, root_dir: str, push_callback: Optional[Callable] = None):
        self.root_dir = Path(root_dir).resolve()
        self.log_dir = self.root_dir / "logs"
        self.push_callback = push_callback  # async function(event, data)
        self._current_file: Optional[Path] = None
        self._last_size = 0
        self._running = False

    def _get_today_log(self) -> Optional[Path]:
        """获取今天的日志文件"""
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = self.log_dir / f"{today}.log"
        return log_file if log_file.exists() else None

    async def watch(self):
        """持续监听日志文件变化"""
        self._running = True
        log.info("日志监听器已启动")

        while self._running:
            try:
                today_log = self._get_today_log()

                # 日期变化时重置
                if today_log != self._current_file:
                    self._current_file = today_log
                    self._last_size = 0

                if self._current_file and self._current_file.exists():
                    await self._check_new_content()

                await asyncio.sleep(2)  # 每 2 秒检查一次

            except Exception as e:
                log.error(f"日志监听异常: {e}")
                await asyncio.sleep(5)

    async def _check_new_content(self):
        """检查文件是否有新内容"""
        if not self._current_file or not self._current_file.exists():
            return

        try:
            current_size = self._current_file.stat().st_size
        except OSError:
            return

        if current_size <= self._last_size:
            # 文件可能被截断（日志轮转），重置 offset
            if current_size < self._last_size:
                log.debug(f"检测到日志文件截断，重置读取位置")
                self._last_size = 0
            return

        try:
            with open(self._current_file, "r", encoding="utf-8") as f:
                f.seek(self._last_size)
                new_lines = f.readlines()

            self._last_size = current_size

            if new_lines and self.push_callback:
                for line in new_lines:
                    line = line.rstrip("\n")
                    if line:
                        # 解析日志级别
                        level = "INFO"
                        for lv in ["ERROR", "WARNING", "INFO", "DEBUG"]:
                            if f"[{lv}]" in line or f" {lv} " in line:
                                level = lv
                                break

                        await self.push_callback("log.new", {
                            "line": line,
                            "level": level,
                            "timestamp": datetime.now().isoformat(),
                            "date": self._current_file.stem,
                        })

        except Exception as e:
            log.error(f"读取日志新内容失败: {e}")

    def stop(self):
        """停止监听"""
        self._running = False
        log.info("日志监听器已停止")
