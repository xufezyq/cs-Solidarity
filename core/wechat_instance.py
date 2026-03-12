"""
全局WeChat实例管理
"""
from wxauto import WeChat
from pywechat import Messages

_use_wxauto = False
_wx = None # 全局WeChat单例对象，所有模块都可以导入使用

def send_message(message, group):
    """发送消息到指定的群或好友"""
    print(f"[DEBUG] 准备发送消息到 {group}: {message[:50]}...")
    if is_using_wxauto():
        try:
            get_wechat().SendMsg(message, group)
            print(f"[DEBUG] 使用 wxauto 发送消息成功")
        except Exception as e:
            print(f"[DEBUG] 使用 wxauto 发送消息失败: {e}")
            raise
    else:
        try:
            Messages.send_messages_to_friend(friend=group, messages=[message], delay=0.5, tickle=False, search_pages=0)
            print(f"[DEBUG] 使用 pywechat 发送消息成功")
        except Exception as e:
            print(f"[DEBUG] 使用 pywechat 发送消息失败: {e}")
            raise
        
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
    print(f"[DEBUG] 开始获取新消息")
    if is_using_wxauto():
        wx = get_wechat()
        if wx:
            try:
                # 获取所有新消息
                msgs = wx.GetAllNewMessage()
                print(f"[DEBUG] 使用 wxauto 获取到 {len(msgs)} 条新消息")
                return msgs
            except Exception as e:
                print(f"[DEBUG] 获取新消息失败: {e}")
                return {}
    else:
        # pywechat 模式
        try:
            # check_new_message 返回的是 list[dict]
            # dict 包含：'好友名称', '新消息条数', '消息内容'(list), '发送消息群成员'(list, optional)
            print(f"[DEBUG] 使用 pywechat 检查新消息")
            new_msgs_list = Messages.check_new_message(close_wechat=False)
            print(f"[DEBUG] pywechat 返回 {len(new_msgs_list) if new_msgs_list else 0} 个消息对象")
            if not new_msgs_list:
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
                    print(f"[DEBUG] 处理 {chat_name} 的 {len(msg_list)} 条消息")
            
            print(f"[DEBUG] 最终返回 {len(result)} 个聊天对象的消息")
            return result
        except Exception as e:
            print(f"[DEBUG] pywechat 获取新消息失败: {e}")
            return {}
    return {}
