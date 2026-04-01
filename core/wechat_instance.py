"""
全局WeChat实例管理
"""
from wxauto import WeChat
from utils.human_sim import human_delay, human_action_delay

_wx = None  # 全局WeChat单例对象，所有模块都可以导入使用


def _patch_wxauto_human_behavior():
    """Monkey-patch uiautomation 的底层点击函数，注入人类行为模拟

    wxauto 所有 UI 操作最终调用 uiautomation.Click()，该函数内部用
    ctypes.windll.user32.SetCursorPos + mouse_event，不走 win32api。
    因此必须 patch uiautomation 自身的函数才能生效。

    影响范围：
    - uiautomation.SetCursorPos → 带 ±1px 随机抖动
    - uiautomation.Click → 带抖动 + 随机延迟（按下/释放间隔）
    """
    try:
        import uiautomation as uia
        import random as _random
        import time as _time

        # 保存原始函数
        _original_set_cursor_pos = uia.SetCursorPos

        def _jittered_set_cursor_pos(x, y):
            """带随机抖动的 SetCursorPos"""
            jx = round(_random.gauss(0, 1.0))
            jy = round(_random.gauss(0, 1.0))
            return _original_set_cursor_pos(x + jx, y + jy)

        def _humanized_click(x, y, waitTime=0.05):
            """替换 uia.Click，添加抖动和随机延迟

            模拟人类点击的三个阶段：
            1. 移动到目标（带抖动）
            2. 按下鼠标（随机短延迟）
            3. 释放鼠标（随机短延迟）
            """
            import ctypes
            import ctypes.wintypes

            # 点击位置抖动
            jx = round(_random.gauss(0, 1.5))
            jy = round(_random.gauss(0, 1.5))
            tx, ty = x + jx, y + jy

            # 1. 移动光标
            _original_set_cursor_pos(tx, ty)

            # 移动后的短暂停顿（人类不会瞬间点击）
            _time.sleep(_random.uniform(0.01, 0.06))

            # 2. 按下鼠标
            from uiautomation import MouseEventFlag, GetScreenSize
            sw, sh = GetScreenSize()
            abs_x = tx * 65535 // sw
            abs_y = ty * 65535 // sh
            ctypes.windll.user32.mouse_event(
                MouseEventFlag.LeftDown | MouseEventFlag.Absolute,
                abs_x, abs_y, 0, 0
            )

            # 按下和释放之间的随机间隔（人类的物理按压时间）
            _time.sleep(_random.uniform(0.03, 0.12))

            # 3. 释放鼠标
            ctypes.windll.user32.mouse_event(
                MouseEventFlag.LeftUp | MouseEventFlag.Absolute,
                abs_x, abs_y, 0, 0
            )

            # 点击后的等待
            _time.sleep(max(0, waitTime + _random.uniform(-0.02, 0.05)))

        # 应用 patch —— 替换 uiautomation 模块自身的函数
        uia.SetCursorPos = _jittered_set_cursor_pos
        uia.Click = _humanized_click

        print("[INFO] uiautomation UI 操作已注入人类行为模拟（抖动+延迟）")
        return True
    except Exception as e:
        print(f"[WARN] uiautomation 行为注入失败（不影响核心功能）: {e}")
        return False


def send_message(message, group):
    """发送消息并捕获发送期间的新消息（带人类行为模拟）

    流程：
    1. ChatWith(group) — 打开目标聊天
    2. 读取消息列表，保存最后一条消息 ID
    3. 发送消息
    4. 再次读取消息列表，对比 ID 找出新消息
    5. 返回新消息列表
    """
    wx = get_wechat()
    human_action_delay()

    # 1. 打开目标聊天
    try:
        wx.ChatWith(group)
        human_delay(300, 600)
    except Exception as e:
        print(f"[ERROR] 打开聊天 {group} 失败: {e}")
        return []

    # 2. 读取消息列表，保存最后一条消息 ID
    pre_msgs = []
    last_id_before = None
    try:
        pre_msgs = wx.GetAllMessage()
        if pre_msgs:
            last_id_before = pre_msgs[-1].id if hasattr(pre_msgs[-1], 'id') else pre_msgs[-1][-1]
            print(f"[DEBUG] [send] 发送前 {group} 最后消息ID: {last_id_before}")
    except Exception as e:
        print(f"[DEBUG] [send] 读取消息列表失败: {e}")

    # 3. 发送消息
    try:
        wx.SendMsg(message, group)
        print(f"[DEBUG] [send] 消息已发送到 {group}")
    except Exception as e:
        print(f"[ERROR] [send] 发送失败: {e}")
        return []

    human_delay(300, 800)

    # 4. 再次读取消息列表，找出新消息
    new_msgs = []
    try:
        post_msgs = wx.GetAllMessage()
        if post_msgs and last_id_before:
            found_idx = -1
            for i, msg in enumerate(post_msgs):
                msg_id = msg.id if hasattr(msg, 'id') else msg[-1]
                if msg_id == last_id_before:
                    found_idx = i
                    break

            if found_idx >= 0:
                raw_new = post_msgs[found_idx + 1:]
            else:
                raw_new = post_msgs

            for msg in raw_new:
                msg_type = msg.type if hasattr(msg, 'type') else None
                sender = msg.sender if hasattr(msg, 'sender') else (msg[0] if isinstance(msg, (list, tuple)) else None)
                if msg_type != 'self' and sender != 'Self':
                    new_msgs.append(msg)

            if new_msgs:
                print(f"[INFO] [send] 发送期间 {group} 收到 {len(new_msgs)} 条新消息")
        elif post_msgs and not last_id_before:
            for msg in post_msgs:
                msg_type = msg.type if hasattr(msg, 'type') else None
                sender = msg.sender if hasattr(msg, 'sender') else (msg[0] if isinstance(msg, (list, tuple)) else None)
                if msg_type != 'self' and sender != 'Self':
                    new_msgs.append(msg)
            if new_msgs:
                print(f"[INFO] [send] 发送期间 {group} 收到 {len(new_msgs)} 条新消息（首次）")
    except Exception as e:
        print(f"[ERROR] [send] 读取新消息失败: {e}")

    return new_msgs


def get_wechat():
    """获取WeChat实例，延迟初始化"""
    global _wx
    if _wx is None:
        _wx = WeChat()
    return _wx


def is_using_wxauto():
    """是否使用 wxauto（当前固定 True）"""
    return True


def init_wechat():
    """显式初始化WeChat实例"""
    global _wx
    if _wx is None:
        _wx = WeChat()
        _patch_wxauto_human_behavior()
    return _wx


def get_new_messages():
    """获取所有新消息

    增加了人类行为模拟延迟：
    - 切换聊天后等待随机时间
    - 读取消息列表前等待随机时间
    """
    wx = get_wechat()
    if wx:
        try:
            print(f"[DEBUG] [wechat_instance] 调用 wx.GetAllNewMessage()")

            # 人类行为模拟：在获取消息前随机等待
            human_delay(500, 2000)

            msgs = wx.GetAllNewMessage()

            # 人类行为模拟：获取消息后短暂等待
            human_delay(200, 600)

            print(f"[DEBUG] [wechat_instance] wxauto 返回消息: {msgs}")
            return msgs
        except Exception as e:
            print(f"[ERROR] [wechat_instance] 获取新消息失败: {e}")
            import traceback
            traceback.print_exc()
            return {}
    return {}
