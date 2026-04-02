"""
日志模块
按日期生成日志文件，同时输出到控制台
"""
import logging
import sys
import threading
from datetime import datetime
from pathlib import Path


class _DateRotatingFileHandler(logging.FileHandler):
    """按日期自动切换日志文件的 Handler（线程安全）"""

    def __init__(self, log_dir="logs", encoding="utf-8"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.encoding = encoding
        self._current_date = None
        self._filename = None
        self._rotate_lock = threading.Lock()
        # 初始化时打开第一天的文件
        self._rotate()
        super().__init__(self._filename, encoding=self.encoding)

    def _rotate(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._current_date:
            self._current_date = today
            self._filename = str(self.log_dir / f"{today}.log")

    def emit(self, record):
        # 每次写入前检查是否跨天
        self._rotate()
        with self._rotate_lock:
            if self.baseFilename != self._filename:
                old_stream = self.stream
                self.close()
                self.baseFilename = self._filename
                self.stream = self._open()
                # 安全关闭旧流（其他线程不再引用）
                if old_stream:
                    try:
                        old_stream.close()
                    except Exception:
                        pass
        super().emit(record)


class _ConsoleHandler(logging.StreamHandler):
    """控制台输出，强制 UTF-8"""

    def __init__(self):
        super().__init__(sys.stdout)
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except Exception:
                pass


# ============================================================
# 格式
# ============================================================
_LOG_FMT = "[%(asctime)s] [%(levelname)s] %(message)s"
_DATE_FMT = "%H:%M:%S"


def setup_logger(log_dir="logs", level=logging.DEBUG):
    """初始化全局日志配置

    Args:
        log_dir: 日志文件目录（相对于项目根目录）
        level: 日志级别

    Returns:
        root logger
    """
    root = logging.getLogger()
    root.setLevel(level)

    # 清除已有 handler（避免重复添加）
    root.handlers.clear()

    formatter = logging.Formatter(_LOG_FMT, datefmt=_DATE_FMT)

    # 文件 handler（按日期切分）
    fh = _DateRotatingFileHandler(log_dir=log_dir)
    fh.setLevel(level)
    fh.setFormatter(formatter)
    root.addHandler(fh)

    # 控制台 handler
    ch = _ConsoleHandler()
    ch.setLevel(level)
    ch.setFormatter(formatter)
    root.addHandler(ch)

    return root


# ============================================================
# 便捷函数
# ============================================================
_logger = logging.getLogger("app")


def debug(msg):
    _logger.debug(msg)


def info(msg):
    _logger.info(msg)


def warning(msg):
    _logger.warning(msg)


def error(msg):
    _logger.error(msg)
