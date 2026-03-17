"""
全局WeChat实例管理
"""
from wxauto import WeChat
from pywechat import Messages

_use_wxauto = True
_wx = None # 全局WeChat单例对象，所有模块都可以导入使用

def send_message(message, group):
    """发送消息到指定的群或好友"""
    if is_using_wxauto():
        wx = get_wechat()
        wx.SendMsg(message, group)
        # 发送完后切换到文件传输助手，避免影响获取新消息
        try:
            wx.ChatWith('文件传输助手')
        except Exception as e:
            print(f"[DEBUG] 切换到文件传输助手失败: {e}")
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

def get_new_messages():
    """获取所有新消息（兼容 wxauto 和 pywechat）"""
    print(f"[DEBUG] [wechat_instance] is_using_wxauto() = {is_using_wxauto()}")
    
    if is_using_wxauto():
        wx = get_wechat()
        if wx:
            try:
                # 获取所有新消息
                print(f"[DEBUG] [wechat_instance] wxauto 模式，调用 wx.GetAllNewMessage()")
                msgs = wx.GetAllNewMessage()
                print(f"[DEBUG] [wechat_instance] wxauto 返回消息: {msgs}")
                return msgs
            except Exception as e:
                print(f"[ERROR] [wechat_instance] 获取新消息失败: {e}")
                import traceback
                traceback.print_exc()
                return {}
    else:
        # pywechat 模式
        print(f"[DEBUG] [wechat_instance] pywechat 模式，调用 Messages.check_new_message()")
        try:
            # check_new_message 返回的是 list[dict]
            # dict 包含：'好友名称', '新消息条数', '消息内容'(list), '发送消息群成员'(list, optional)
            new_msgs_list = Messages.check_new_message(close_wechat=False)
            print(f"[DEBUG] [wechat_instance] pywechat 返回: {new_msgs_list}")
            
            if not new_msgs_list:
                print(f"[DEBUG] [wechat_instance] pywechat 没有新消息")
                return {}
            
            result = {}
            for item in new_msgs_list:
                chat_name = item.get('好友名称')
                if not chat_name:
                    continue
                
                contents = item.get('消息内容', [])
                senders = item.get('发送消息群成员', [])
                
                # 构造消息列表，尽量模拟 wxauto 的格式 [sender, content, id]
                # pywechat 可能没有 msg id，我们用时间戳或 hash 代替
                import time
                msg_list = []
                for i, content in enumerate(contents):
                    # 如果是群聊且有发送者列表，尝试获取发送者；否则默认为 chat_name
                    # 注意：pywechat 个人聊天不返回发送者列表
                    if senders and i < len(senders):
                        sender = senders[i]
                    else:
                        sender = chat_name
                        
                    # 模拟 wxauto 的消息结构，这里用简单的 list: [sender, content, id]
                    msg_id = f"{time.time()}-{i}"
                    msg_list.append([sender, content, msg_id])
                
                if msg_list:
                    result[chat_name] = msg_list
            
            print(f"[DEBUG] [wechat_instance] 处理后返回: {result}")
            return result
        except Exception as e:
            print(f"[ERROR] [wechat_instance] pywechat 获取新消息失败: {e}")
            import traceback
            traceback.print_exc()
            return {}
    return {}
