"""
AstrBot 兼容层
提供与 AstrBot API 接口兼容的替代实现
"""

import logging
import os
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


class Comp:
    """替代 astrbot.api.message_components"""

    Plain = Plain


def get_message_chain(text: str) -> MessageChain:
    """创建消息链"""
    return MessageChain([Plain(text)])


def get_data_dir(plugin_name: str = None) -> Path:
    """获取数据目录的便捷函数"""
    return _DATA_DIR
