"""
全局WeChat实例管理
"""
import logging
import threading
from wxauto import WeChat
from utils.human_sim import human_delay, human_action_delay

log = logging.getLogger(__name__)

_wx = None  # 全局WeChat单例对象，所有模块都可以导入使用
_wx_lock = threading.Lock()  # 防止多线程同时初始化


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

        _original_set_cursor_pos = uia.SetCursorPos

        def _jittered_set_cursor_pos(x, y):
            """带随机抖动的 SetCursorPos"""
            jx = round(_random.gauss(0, 1.0))
            jy = round(_random.gauss(0, 1.0))
            return _original_set_cursor_pos(x + jx, y + jy)

        def _humanized_click(x, y, waitTime=0.05):
            """替换 uia.Click，添加抖动和随机延迟"""
            import ctypes
            import ctypes.wintypes

            jx = round(_random.gauss(0, 1.5))
            jy = round(_random.gauss(0, 1.5))
            tx, ty = x + jx, y + jy

            _original_set_cursor_pos(tx, ty)
            _time.sleep(_random.uniform(0.01, 0.06))

            from uiautomation import MouseEventFlag, GetScreenSize
            sw, sh = GetScreenSize()
            abs_x = tx * 65535 // sw
            abs_y = ty * 65535 // sh
            ctypes.windll.user32.mouse_event(
                MouseEventFlag.LeftDown | MouseEventFlag.Absolute,
                abs_x, abs_y, 0, 0
            )

            _time.sleep(_random.uniform(0.03, 0.12))

            ctypes.windll.user32.mouse_event(
                MouseEventFlag.LeftUp | MouseEventFlag.Absolute,
                abs_x, abs_y, 0, 0
            )

            _time.sleep(max(0, waitTime + _random.uniform(-0.02, 0.05)))

        uia.SetCursorPos = _jittered_set_cursor_pos
        uia.Click = _humanized_click

        log.info("uiautomation UI 操作已注入人类行为模拟（抖动+延迟）")
        return True
    except Exception as e:
        log.warning(f"uiautomation 行为注入失败（不影响核心功能）: {e}")
        return False


def send_message(message, group):
    """发送消息并捕获发送期间的新消息（带人类行为模拟）

    流程：
    1. 【关键】ChatWith 之前，先从侧边栏读取目标聊天的未读消息
       → ChatWith 会清掉未读状态，必须在之前捕获
    2. ChatWith 切换到目标聊天
    3. 发送消息
    4. 再次读取，捕获发送期间到达的新消息
    5. 合并预捕获 + 发送期间捕获的消息
    """
    wx = get_wechat()
    human_action_delay()

    # ── 第一步：ChatWith 之前预捕获未读消息 ──
    # ChatWith 会清掉该聊天的未读状态（闪烁消失），
    # 如果等到 ChatWith 之后再读，GetAllNewMessage 就拿不到了。
    pre_caught = []
    try:
        all_new = wx.GetAllNewMessage()
        if all_new and group in all_new:
            raw = all_new[group]
            for msg in raw:
                msg_type = msg.type if hasattr(msg, 'type') else None
                sender = msg.sender if hasattr(msg, 'sender') else (msg[0] if isinstance(msg, (list, tuple)) else None)
                if msg_type != 'self' and sender != 'Self':
                    pre_caught.append(msg)
            if pre_caught:
                log.info(f"[send] 预捕获 {group} {len(pre_caught)} 条未读消息")
    except Exception as e:
        log.debug(f"[send] 预捕获失败（非致命）: {e}")

    # ── 第二步：切换到目标聊天 ──
    try:
        wx.ChatWith(group)
        human_delay(300, 600)
    except Exception as e:
        log.error(f"打开聊天 {group} 失败: {e}")
        return pre_caught  # 即使切换失败，预捕获的消息也要返回

    # ── 第三步：记录发送前的消息快照 ──
    pre_msgs = []
    last_id_before = None
    try:
        pre_msgs = wx.GetAllMessage()
        if pre_msgs:
            last_id_before = pre_msgs[-1].id if hasattr(pre_msgs[-1], 'id') else pre_msgs[-1][-1]
            log.debug(f"[send] 发送前 {group} 最后消息ID: {last_id_before}")
    except Exception as e:
        log.debug(f"[send] 读取消息列表失败: {e}")

    # ── 第四步：发送 ──
    try:
        wx.SendMsg(message, group)
        log.debug(f"[send] 消息已发送到 {group}")
    except Exception as e:
        log.error(f"[send] 发送失败: {e}")
        return pre_caught

    human_delay(300, 800)

    # ── 第五步：捕获发送期间到达的新消息 ──
    send_caught = []
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
                    send_caught.append(msg)

            if send_caught:
                log.info(f"[send] 发送期间 {group} 收到 {len(send_caught)} 条新消息")
        elif post_msgs and not last_id_before:
            for msg in post_msgs:
                msg_type = msg.type if hasattr(msg, 'type') else None
                sender = msg.sender if hasattr(msg, 'sender') else (msg[0] if isinstance(msg, (list, tuple)) else None)
                if msg_type != 'self' and sender != 'Self':
                    send_caught.append(msg)
            if send_caught:
                log.info(f"[send] 发送期间 {group} 收到 {len(send_caught)} 条新消息（首次）")
    except Exception as e:
        log.error(f"[send] 读取新消息失败: {e}")

    # ── 第六步：合并预捕获 + 发送期间捕获，去重 ──
    all_caught = list(pre_caught)  # 预捕获优先
    seen_ids = set()
    for msg in all_caught:
        mid = msg.id if hasattr(msg, 'id') else (msg[-1] if isinstance(msg, (list, tuple)) else None)
        if mid:
            seen_ids.add(mid)

    for msg in send_caught:
        mid = msg.id if hasattr(msg, 'id') else (msg[-1] if isinstance(msg, (list, tuple)) else None)
        if mid and mid not in seen_ids:
            all_caught.append(msg)
        elif not mid:
            all_caught.append(msg)  # 没有 ID 的保守保留

    return all_caught


def get_wechat():
    """获取WeChat实例，延迟初始化（线程安全）"""
    global _wx
    if _wx is None:
        with _wx_lock:
            if _wx is None:
                _wx = WeChat()
    return _wx


def is_using_wxauto():
    """是否使用 wxauto（当前固定 True）"""
    return True


def init_wechat():
    """显式初始化WeChat实例（线程安全）"""
    global _wx
    if _wx is None:
        with _wx_lock:
            if _wx is None:
                _wx = WeChat()
                _patch_wxauto_human_behavior()
    return _wx


def get_new_messages():
    """获取所有新消息"""
    wx = get_wechat()
    if wx:
        try:
            log.debug("调用 wx.GetAllNewMessage()")
            human_delay(500, 2000)
            msgs = wx.GetAllNewMessage()
            human_delay(200, 600)
            log.debug(f"wxauto 返回消息: {msgs}")
            return msgs
        except Exception as e:
            log.error(f"获取新消息失败: {e}")
            import traceback
            log.debug(traceback.format_exc())
            return {}
    return {}
