"""
全局WeChat实例管理
"""
from wxauto import WeChat
from pywechat import Messages

_use_wxauto = False
_wx = None # 全局WeChat单例对象，所有模块都可以导入使用

def send_message(message, group):
    """发送消息到指定的群或好友"""
    if is_using_wxauto():
        get_wechat().SendMsg(message, group)
    else:
        Messages.send_messages_to_friend(friend=group, messages=[message], delay=0.5, tickle=False, search_pages=0)
        
def get_wechat():
    """获取WeChat实例，延迟初始化"""
    if is_using_wxauto():
        global _wx
        if _wx is None:
            _wx = WeChat()
        return _wx
    else:   
        return None  # 使用 pywechat 时不需要 WeChat 实例

def init_wechat():
    """显式初始化WeChat实例"""
    if is_using_wxauto():
        global _wx
        if _wx is None:
            _wx = WeChat()
        return _wx
    else:   
        return None  # 使用 pywechat 时不需要 WeChat 实例

def is_using_wxauto():
    """检查是否使用 wxauto"""
    return _use_wxauto