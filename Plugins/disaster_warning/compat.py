"""
AstrBot 兼容层
提供与 AstrBot API 接口兼容的替代实现
"""

import base64
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

# 创建 logger
logger = logging.getLogger("disaster_warning")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# 数据目录 - Plugins/data/disaster_warning/
_PLUGIN_DIR = Path(__file__).parent  # disaster_warning/
_DATA_DIR = _PLUGIN_DIR.parent / "data" / "disaster_warning"  # Plugins/data/disaster_warning/
_DATA_DIR.mkdir(parents=True, exist_ok=True)


class StarTools:
    """替代 AstrBot 的 StarTools"""

    @staticmethod
    def get_data_dir(plugin_name: str = None) -> Path:
        """获取数据目录"""
        return _DATA_DIR


class MessageChain:
    """简化的 MessageChain 实现"""

    def __init__(self, components=None):
        self._components = components or []
        self.chain = self._components  # 兼容 code中使用 chain.chain.append()

    @property
    def content(self) -> str:
        """返回纯文本内容"""
        parts = []
        for comp in self._components:
            if hasattr(comp, 'text'):
                parts.append(comp.text)
            elif hasattr(comp, 'content'):
                parts.append(comp.content)
            elif isinstance(comp, str):
                parts.append(comp)
            elif hasattr(comp, 'as_string'):
                parts.append(comp.as_string())
        return "".join(parts)

    def as_string(self) -> str:
        return self.content

    def __str__(self) -> str:
        return self.content


class Plain:
    """简化的 Plain 文本组件"""

    def __init__(self, text: str):
        self.text = text
        self.content = text

    def __str__(self) -> str:
        return self.text


class Image:
    """简化的图片组件，支持 base64 和 URL 两种数据源"""

    def __init__(self, b64_data: str = None, url: str = None, path: str = None):
        self._b64_data = b64_data
        self._url = url
        self._path = path
        self._created_temp = False

    @classmethod
    def fromBase64(cls, b64_data: str) -> "Image":
        return cls(b64_data=b64_data)

    @classmethod
    def fromURL(cls, url: str) -> "Image":
        return cls(url=url)

    @classmethod
    def fromFile(cls, path: str) -> "Image":
        return cls(path=path)

    def save_to_file(self, temp_dir: str) -> str | None:
        """将图片保存到临时文件，返回文件路径。失败返回 None。"""
        filepath = None
        try:
            if self._path:
                self._created_temp = False
                return self._path
            ts = int(time.time() * 1000)
            filepath = os.path.join(temp_dir, f"img_{ts}_{uuid.uuid4().hex[:8]}.png")
            self._created_temp = True
            if self._b64_data:
                payload = self._b64_data.strip()
                if payload.startswith("data:") and "," in payload:
                    payload = payload.split(",", 1)[1]
                payload = "".join(payload.split())
                if not payload:
                    return None
                padding = (-len(payload)) % 4
                if padding:
                    payload += "=" * padding
                with open(filepath, "wb") as f:
                    f.write(base64.b64decode(payload))
                return filepath
            if self._url:
                import urllib.request
                urllib.request.urlretrieve(self._url, filepath)
                return filepath
        except Exception:
            if filepath and os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except OSError:
                    pass
            return None
        return None


class Comp:
    """替代 astrbot.api.message_components"""

    Plain = Plain
    Image = Image


def get_message_chain(text: str) -> MessageChain:
    """创建消息链"""
    return MessageChain([Plain(text)])


def get_data_dir(plugin_name: str = None) -> Path:
    """获取数据目录的便捷函数"""
    return _DATA_DIR
