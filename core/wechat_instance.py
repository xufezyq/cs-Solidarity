"""
全局WeChat实例管理
"""
from wxauto import WeChat

# 全局WeChat单例对象，所有模块都可以导入使用
_wx = None

def get_wechat():
    """获取WeChat实例，延迟初始化"""
    global _wx
    if _wx is None:
        _wx = WeChat()
    return _wx

def init_wechat():
    """显式初始化WeChat实例"""
    global _wx
    if _wx is None:
        _wx = WeChat()
    return _wx
