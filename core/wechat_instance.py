"""
全局WeChat实例管理
"""
from wxauto import WeChat

_use_pywechat = True
_wx = None # 全局WeChat单例对象，所有模块都可以导入使用

def get_wechat():
    """获取WeChat实例，延迟初始化"""
    if _use_pywechat:
        return None  # 使用 pywechat 时不需要 WeChat 实例
    global _wx
    if _wx is None:
        _wx = WeChat()
    return _wx

def init_wechat():
    """显式初始化WeChat实例"""
    if _use_pywechat:
        return None  # 使用 pywechat 时不需要 WeChat 实例
    global _wx
    if _wx is None:
        _wx = WeChat()
    return _wx
