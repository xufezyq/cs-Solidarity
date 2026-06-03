"""
全局 WeChat 实例管理
"""
import logging
import threading
import random
import time
import win32api
from wxauto import WeChat
from utils.human_sim import human_delay, human_action_delay

# 隐藏 uiautomation 和 pywinauto 的 DEBUG 日志，避免输出大量 Release 信息
logging.getLogger('uiautomation').setLevel(logging.WARNING)
logging.getLogger('pywinauto').setLevel(logging.WARNING)

log = logging.getLogger(__name__)

_wx = None  # 全局WeChat单例对象，所有模块都可以导入使用
_wx_lock = threading.Lock()  # 防止多线程同时初始化
_send_op_lock = threading.Lock()  # 防止多个线程同时执行 ChatWith+SendMsg（KoriChat Timer 与主线程冲突）


def _get_main():
    """获取 main.py 模块（在 sys.modules['main'] 被假模块占位时，通过 __main__ 绕过）"""
    import sys
    return sys.modules['__main__']


def _bezier_move(from_x, from_y, to_x, to_y):
    """用 Bezier 曲线模拟人类鼠标移动轨迹

    随机生成 2~4 个控制点的二次/三次 Bezier 曲线，
    分 10~25 步移动鼠标，每步 5~15ms，总耗时 100~300ms。
    """
    import uiautomation as uia
    steps = random.randint(10, 25)

    # 随机控制点：在起点和终点之间偏移
    cx1 = (from_x + to_x) / 2 + random.gauss(0, abs(to_x - from_x) * 0.3 + 20)
    cy1 = (from_y + to_y) / 2 + random.gauss(0, abs(to_y - from_y) * 0.3 + 20)

    if random.random() < 0.5:
        # 三次 Bezier：两个控制点
        cx2 = (from_x + to_x) / 2 + random.gauss(0, abs(to_x - from_x) * 0.2 + 15)
        cy2 = (from_y + to_y) / 2 + random.gauss(0, abs(to_y - from_y) * 0.2 + 15)
        for i in range(1, steps + 1):
            t = i / steps
            t2 = t * t
            t3 = t2 * t
            mt = 1 - t
            mt2 = mt * mt
            mt3 = mt2 * mt
            x = mt3 * from_x + 3 * mt2 * t * cx1 + 3 * mt * t2 * cx2 + t3 * to_x
            y = mt3 * from_y + 3 * mt2 * t * cy1 + 3 * mt * t2 * cy2 + t3 * to_y
            uia.SetCursorPos(round(x), round(y))
            time.sleep(random.uniform(0.005, 0.015))
    else:
        # 二次 Bezier：一个控制点
        for i in range(1, steps + 1):
            t = i / steps
            mt = 1 - t
            x = mt * mt * from_x + 2 * mt * t * cx1 + t * t * to_x
            y = mt * mt * from_y + 2 * mt * t * cy1 + t * t * to_y
            uia.SetCursorPos(round(x), round(y))
            time.sleep(random.uniform(0.005, 0.015))


def _patch_wxauto_human_behavior():
    """Monkey-patch uiautomation + wxauto，注入人类行为模拟

    覆盖范围：
    1. uiautomation.SetCursorPos → 带抖动
    2. uiautomation.Click → 带抖动 + Bezier轨迹 + 随机延迟
    3. uiautomation.MoveTo → 带抖动
    4. uiautomation.SendKeys → 随机化时序
    5. wxauto.utils.Click（通过命名空间引用）→ 带抖动+延迟
    6. wxauto.WeChat._show → 去掉 TOPMOST 切换
    7. win32api.SetCursorPos → 全局防御
    """
    try:
        import uiautomation as uia
        import ctypes
        import ctypes.wintypes

        # ── 记录当前鼠标位置（用于 Bezier 轨迹起点）──
        _cursor_pos = [0, 0]

        _original_set_cursor_pos = uia.SetCursorPos
        _click_count = 0

        # ============================================================
        # 1. Patch uiautomation.SetCursorPos
        # ============================================================
        def _jittered_set_cursor_pos(x, y):
            if random.random() < 0.08:
                jx = round(random.gauss(0, 5.0))
                jy = round(random.gauss(0, 5.0))
            else:
                jx = round(random.gauss(0, 2.0))
                jy = round(random.gauss(0, 2.0))
            _cursor_pos[0] = x + jx
            _cursor_pos[1] = y + jy
            return _original_set_cursor_pos(x + jx, y + jy)

        # ============================================================
        # 2. Patch uiautomation.Click
        # ============================================================
        def _humanized_click(x, y, waitTime=0.05):
            nonlocal _click_count
            _click_count += 1

            # Bezier 轨迹移动（约 40% 概率），其余瞬移+抖动
            if random.random() < 0.4 and (_cursor_pos[0] != 0 or _cursor_pos[1] != 0):
                _bezier_move(_cursor_pos[0], _cursor_pos[1], x, y)
                tx, ty = x, y
            else:
                # 抖动
                if random.random() < 0.08:
                    jx = round(random.gauss(0, 5.0))
                    jy = round(random.gauss(0, 5.0))
                else:
                    jx = round(random.gauss(0, 2.5))
                    jy = round(random.gauss(0, 2.5))
                tx, ty = x + jx, y + jy

            _cursor_pos[0] = tx
            _cursor_pos[1] = ty

            # 移动
            _original_set_cursor_pos(tx, ty)
            time.sleep(random.uniform(0.02, 0.08))

            from uiautomation import MouseEventFlag, GetScreenSize
            sw, sh = GetScreenSize()
            abs_x = tx * 65535 // sw
            abs_y = ty * 65535 // sh
            ctypes.windll.user32.mouse_event(
                MouseEventFlag.LeftDown | MouseEventFlag.Absolute,
                abs_x, abs_y, 0, 0
            )

            # 按下到释放：人类一般 40~150ms
            time.sleep(random.uniform(0.04, 0.15))

            ctypes.windll.user32.mouse_event(
                MouseEventFlag.LeftUp | MouseEventFlag.Absolute,
                abs_x, abs_y, 0, 0
            )

            # 点击后停顿
            time.sleep(max(0, waitTime + random.uniform(0.01, 0.08)))

            # 每 15~30 次点击后模拟"犹豫"
            if _click_count % random.randint(15, 30) == 0:
                time.sleep(random.uniform(0.5, 2.0))

        # ============================================================
        # 3. Patch uiautomation.MoveTo
        # ============================================================
        _original_move_to = getattr(uia, 'MoveTo', None)
        if _original_move_to:
            def _humanized_move_to(x, y, waitTime=0.01):
                jx = round(random.gauss(0, 1.5))
                jy = round(random.gauss(0, 1.5))
                _cursor_pos[0] = x + jx
                _cursor_pos[1] = y + jy
                _original_move_to(x + jx, y + jy, waitTime)
                time.sleep(random.uniform(0.005, 0.03))
            uia.MoveTo = _humanized_move_to

        # ============================================================
        # 4. Patch uiautomation.SendKeys
        # ============================================================
        _original_send_keys = uia.SendKeys

        def _humanized_send_keys(keys, waitTime=0.05, **kwargs):
            key_str = str(keys)
            # 组合键：加操作前"思考"延迟
            if '{' in key_str:
                time.sleep(random.uniform(0.1, 0.3))
            # 随机化 waitTime
            actual_wait = waitTime + random.uniform(0.02, 0.1)
            _original_send_keys(keys, waitTime=actual_wait, **kwargs)
            time.sleep(random.uniform(0.05, 0.2))

        uia.SendKeys = _humanized_send_keys

        # ============================================================
        # 5. Patch wxauto.utils.Click（命名空间注入）
        # ============================================================
        try:
            import wxauto.wxauto as wxmod
            import wxauto.elements as elmod
            import win32con

            _original_utils_click = wxmod.Click

            def _humanized_utils_click(rect):
                x = (rect.left + rect.right) // 2
                y = (rect.top + rect.bottom) // 2
                # Bezier 轨迹（40% 概率）
                if random.random() < 0.4 and (_cursor_pos[0] != 0 or _cursor_pos[1] != 0):
                    _bezier_move(_cursor_pos[0], _cursor_pos[1], x, y)
                    tx, ty = x, y
                else:
                    jx = round(random.gauss(0, 2.5))
                    jy = round(random.gauss(0, 2.5))
                    tx, ty = x + jx, y + jy

                _cursor_pos[0] = tx
                _cursor_pos[1] = ty

                win32api.SetCursorPos((tx, ty))
                time.sleep(random.uniform(0.02, 0.08))
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, tx, ty, 0, 0)
                time.sleep(random.uniform(0.04, 0.15))
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, tx, ty, 0, 0)
                time.sleep(random.uniform(0.01, 0.08))

            wxmod.Click = _humanized_utils_click
            elmod.Click = _humanized_utils_click
            log.info("wxauto.utils.Click 已注入人类行为模拟")
        except Exception as e:
            log.warning(f"wxauto Click 注入失败: {e}")

        # ============================================================
        # 6. Patch wxauto._show（去掉 TOPMOST + 操作锁）
        # ============================================================
        try:
            import wxauto.wxauto as wxmod
            import wxauto.elements as elmod
            from wxauto.utils import FindWindow
            import win32gui

            _wx_show_lock = threading.Lock()

            def _safe_show(self):
                with _wx_show_lock:
                    self.HWND = FindWindow(classname='WeChatMainWndForPC')
                    win32gui.ShowWindow(self.HWND, 1)
                    win32gui.SetForegroundWindow(self.HWND)
                    time.sleep(random.uniform(0.05, 0.15))

            def _safe_chatwnd_show(self):
                with _wx_show_lock:
                    self.HWND = FindWindow(name=self.who, classname='ChatWnd')
                    win32gui.ShowWindow(self.HWND, 1)
                    win32gui.SetForegroundWindow(self.HWND)
                    time.sleep(random.uniform(0.05, 0.15))

            wxmod.WeChat._show = _safe_show
            elmod.ChatWnd._show = _safe_chatwnd_show
            log.info("wxauto._show 已替换为安全版本（操作锁 + 无 TOPMOST）")
        except Exception as e:
            log.warning(f"wxauto._show 注入失败: {e}")

        # ============================================================
        # 7. Patch win32api.SetCursorPos（全局防御）
        # ============================================================
        try:
            _original_win32_set_cursor = win32api.SetCursorPos

            def _jittered_win32_set_cursor(pos):
                x, y = pos
                jx = round(random.gauss(0, 2.0))
                jy = round(random.gauss(0, 2.0))
                _cursor_pos[0] = x + jx
                _cursor_pos[1] = y + jy
                _original_win32_set_cursor((x + jx, y + jy))

            win32api.SetCursorPos = _jittered_win32_set_cursor
            log.info("win32api.SetCursorPos 已注入全局抖动")
        except Exception as e:
            log.warning(f"win32api SetCursorPos 注入失败: {e}")

        # ============================================================
        # Apply patches
        # ============================================================
        uia.SetCursorPos = _jittered_set_cursor_pos
        uia.Click = _humanized_click

        log.info("uiautomation UI 操作已注入人类行为模拟（增强版）")
        return True
    except Exception as e:
        log.warning(f"uiautomation 行为注入失败（不影响核心功能）: {e}")
        return False


def send_message(message, group, at=None, at_all=False):
    """发送消息并捕获发送期间的新消息（带人类行为模拟）

    Args:
        message: 消息内容（str 或 dict）
        group: 目标聊天名称
        at: 需要@的人的列表（list of str），在群聊内生效
        at_all: 是否@所有人（bool），在群聊内生效

    流程：
    1. 【关键】ChatWith 之前，先从侧边栏读取目标聊天的未读消息
       → ChatWith 会清掉未读状态，必须在之前捕获
    2. ChatWith 切换到目标聊天
    3. 发送消息
    4. 再次读取，捕获发送期间到达的新消息
    5. 合并预捕获 + 发送期间捕获的消息
    """
    # 调试拦截：打印到日志而非发送到微信
    if getattr(_get_main(), 'MOCK_SEND', False):
        log.info(f"[MOCK→{group}]: {message}")
        return []

    # 设置全局标志，确保整个发送过程期间主循环不会最小化窗口
    with _get_main()._send_lock:
        _get_main()._sending_count += 1
        _get_main()._is_sending = True
        _get_main()._last_send_time = time.time()
    
    try:
        wx = get_wechat()
        human_action_delay()

        # ── 互斥锁：确保 ChatWith+SendMsg 不会被其他线程（如 KoriChat Timer）打断 ──
        # 没有这个锁，后台 Timer 和主线程可能同时执行 ChatWith，导致窗口来回切换，
        # 消息发送到错误的聊天（如文件传输助手）。
        with _send_op_lock:
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
                human_delay(400, 900)
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
            # "打字延迟"：模拟人类输入内容需要的时间
            if isinstance(message, dict):
                content_len = len(message.get("content", ""))
            elif isinstance(message, str):
                content_len = len(message)
            else:
                content_len = 0

            typing_delay = min(max(content_len * 0.05, 0.3), 2.0)  # 0.3-2 秒
            time.sleep(typing_delay + random.uniform(0, 0.3))

            # 实际发送
            actual_msg = message.get("content") if isinstance(message, dict) else message
            actual_at = message.get("at") if isinstance(message, dict) else at
            actual_at_all = message.get("at_all") if isinstance(message, dict) else at_all
            log.info(f"[send] 发送消息到 {group}: msg={actual_msg[:30]!r}..., at={actual_at}, at_all={actual_at_all}")
            try:
                # 有 @ 时：@名字 + 回车选人，然后粘贴消息，最后回车发送
                if (actual_at and isinstance(actual_at, list)) or actual_at_all:
                    import uiautomation as uia
                    from wxauto.utils import SetClipboardText
                    # 确保窗口可见
                    wx._show()
                    human_delay(200, 400)
                    # 获取输入框
                    editbox = wx.ChatBox.EditControl(searchDepth=10)
                    if not editbox.Exists():
                        editbox = wx.ChatBox.EditControl(Name=group, searchDepth=10)
                    if not editbox.HasKeyboardFocus:
                        editbox.Click(simulateMove=False)
                        human_delay(100, 200)

                    # 清空输入框
                    uia.SendKeys('{Ctrl}a', waitTime=0.05)
                    time.sleep(0.1)

                    # @所有人
                    if actual_at_all:
                        log.info("[send] 输入 @所有人 回车")
                        uia.SendKeys('@所有人', waitTime=0.1)
                        time.sleep(0.5)
                        uia.SendKeys('{Enter}', waitTime=0.1)
                        time.sleep(0.2)

                    # @特定成员：输入 @名字 回车选人
                    if actual_at and isinstance(actual_at, list):
                        for member in actual_at:
                            log.info(f"[send] 输入 @{member} 回车")
                            uia.SendKeys(f'@{member}', waitTime=0.1)
                            time.sleep(0.5)
                            uia.SendKeys('{Enter}', waitTime=0.1)
                            time.sleep(0.2)

                    # 粘贴消息内容
                    time.sleep(0.1)
                    SetClipboardText(actual_msg)
                    uia.SendKeys('{Ctrl}v', waitTime=0.1)
                    time.sleep(0.3)

                    # 回车发送
                    uia.SendKeys('{Enter}', waitTime=0.1)
                    log.info(f"[send] SendMsg(at) 完成")
                else:
                    wx.SendMsg(actual_msg, clear=True)
                    log.info(f"[send] SendMsg 完成")
            except Exception as send_e:
                log.error(f"[send] SendMsg 异常: {send_e}")
                import traceback
                log.debug(traceback.format_exc())
                raise
            # 更新发送时间戳
            with _get_main()._send_lock:
                _get_main()._last_send_time = time.time()

            # ── 第五步：等待消息出现在聊天记录中 ──
            sent_id = None
            for _ in range(20):  # 最多等 10 秒
                time.sleep(0.5)
                try:
                    after_msgs = wx.GetAllMessage()
                    if after_msgs and len(after_msgs) > len(pre_msgs):
                        new_msgs = after_msgs[len(pre_msgs):]
                        for nm in new_msgs:
                            nm_sender = nm.sender if hasattr(nm, 'sender') else (nm[0] if isinstance(nm, (list, tuple)) else None)
                            if nm_sender == 'Self':
                                sent_id = nm.id if hasattr(nm, 'id') else nm[-1]
                                break
                        if sent_id:
                            break
                except Exception:
                    pass

            if sent_id:
                log.debug(f"[send] 消息已确认发送 (ID={sent_id})")
            else:
                log.warning(f"[send] 消息可能未成功发送到 {group}")

            # ── 第六步：捕获发送期间到达的新消息 ──
            post_caught = []
            try:
                post_msgs = wx.GetAllMessage()
                if post_msgs:
                    start_idx = 0
                    if last_id_before:
                        for i, pm in enumerate(post_msgs):
                            pm_id = pm.id if hasattr(pm, 'id') else pm[-1]
                            if pm_id == last_id_before:
                                start_idx = i + 1
                                break

                    new_after_send = post_msgs[start_idx:]
                    for nm in new_after_send:
                        nm_id = nm.id if hasattr(nm, 'id') else nm[-1]
                        if sent_id and nm_id == sent_id:
                            continue
                        nm_type = nm.type if hasattr(nm, 'type') else None
                        nm_sender = nm.sender if hasattr(nm, 'sender') else (nm[0] if isinstance(nm, (list, tuple)) else None)
                        if nm_type != 'self' and nm_sender != 'Self':
                            post_caught.append(nm)

                    if post_caught:
                        log.info(f"[send] 发送期间捕获 {len(post_caught)} 条新消息")
            except Exception as e:
                log.debug(f"[send] 捕获新消息失败: {e}")

            return pre_caught + post_caught
    
    finally:
        # 发送完成后重置标志和计数器
        with _get_main()._send_lock:
            _get_main()._sending_count -= 1
            if _get_main()._sending_count <= 0:
                _get_main()._is_sending = False
                _get_main()._sending_count = 0


def send_file(filepath, group):
    """发送文件并复用消息发送的窗口/锁保护。"""
    if getattr(_get_main(), 'MOCK_SEND', False):
        log.info(f"[MOCK FILE→{group}]: {filepath}")
        return []

    with _get_main()._send_lock:
        _get_main()._sending_count += 1
        _get_main()._is_sending = True
        _get_main()._last_send_time = time.time()

    try:
        wx = get_wechat()
        human_action_delay()

        with _send_op_lock:
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
                        log.info(f"[send-file] 预捕获 {group} {len(pre_caught)} 条未读消息")
            except Exception as e:
                log.debug(f"[send-file] 预捕获失败（非致命）: {e}")

            try:
                wx.ChatWith(group)
                human_delay(400, 900)
            except Exception as e:
                log.error(f"打开聊天 {group} 失败: {e}")
                return pre_caught

            last_id_before = None
            try:
                pre_msgs = wx.GetAllMessage()
                if pre_msgs:
                    last_id_before = pre_msgs[-1].id if hasattr(pre_msgs[-1], 'id') else pre_msgs[-1][-1]
            except Exception as e:
                log.debug(f"[send-file] 读取消息列表失败: {e}")

            try:
                log.info(f"[send-file] 发送文件到 {group}: {filepath}")
                wx.SendFiles(filepath)
                with _get_main()._send_lock:
                    _get_main()._last_send_time = time.time()
            except Exception as send_e:
                log.error(f"[send-file] SendFiles 异常: {send_e}")
                raise

            human_delay(400, 1000)

            post_caught = []
            try:
                post_msgs = wx.GetAllMessage()
                if post_msgs and last_id_before:
                    found_idx = -1
                    for i, msg in enumerate(post_msgs):
                        msg_id = msg.id if hasattr(msg, 'id') else msg[-1]
                        if msg_id == last_id_before:
                            found_idx = i
                            break
                    raw_new = post_msgs[found_idx + 1:] if found_idx >= 0 else post_msgs
                    for msg in raw_new:
                        msg_type = msg.type if hasattr(msg, 'type') else None
                        sender = msg.sender if hasattr(msg, 'sender') else (msg[0] if isinstance(msg, (list, tuple)) else None)
                        if msg_type != 'self' and sender != 'Self':
                            post_caught.append(msg)
                    if post_caught:
                        log.info(f"[send-file] 发送期间捕获 {len(post_caught)} 条新消息")
            except Exception as e:
                log.debug(f"[send-file] 捕获新消息失败: {e}")

            return pre_caught + post_caught

    finally:
        with _get_main()._send_lock:
            _get_main()._sending_count -= 1
            if _get_main()._sending_count <= 0:
                _get_main()._is_sending = False
                _get_main()._sending_count = 0


def send_messages(messages, group, at=None, at_all=False):
    """批量发送多条消息到同一聊天（只切换一次窗口，捕获发送期间的新消息）
    
    与 send_message 不同，此方法一次发送多条消息，期间保持 _sending_count > 0，
    防止主循环在消息之间最小化窗口。
    """
    if not messages:
        return []

    if isinstance(messages, str):
        messages = [messages]

    # ════════════════════════════════════════════════════════
    # 标记开始发送（整个批量发送期间保持）
    # ════════════════════════════════════════════════════════
    with _get_main()._send_lock:
        _get_main()._sending_count += 1
        _get_main()._is_sending = True
        _get_main()._last_send_time = time.time()
    
    try:
        wx = get_wechat()
        human_action_delay()

        # ── 互斥锁：确保 ChatWith+SendMsgs 不会被其他线程打断 ──
        with _send_op_lock:
            # ── 预捕获未读消息 ──
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

            # ── 切换到目标聊天 ──
            try:
                wx.ChatWith(group)
                human_delay(400, 900)
            except Exception as e:
                log.error(f"打开聊天 {group} 失败: {e}")
                return pre_caught

            # ── 记录发送前的消息快照 ──
            last_id_before = None
            try:
                pre_msgs = wx.GetAllMessage()
                if pre_msgs:
                    last_id_before = pre_msgs[-1].id if hasattr(pre_msgs[-1], 'id') else pre_msgs[-1][-1]
            except Exception as e:
                log.debug(f"[send] 读取消息列表失败: {e}")

            # ── 批量发送 ──
            total_len = sum(len(m) if isinstance(m, str) else 20 for m in messages)
            typing_time = min(5.0, max(0.8, total_len * 0.02 + random.uniform(0.5, 1.5)))
            log.debug(f"[send] 模拟打字延迟 {typing_time:.1f}s ({len(messages)} 条消息)")
            time.sleep(typing_time)

            try:
                # 提取字典消息中的 at 参数（与 send_message 保持一致）
                first_msg_obj = messages[0] if messages else ""
                actual_at = first_msg_obj.get("at") if isinstance(first_msg_obj, dict) else at
                actual_at_all = first_msg_obj.get("at_all") if isinstance(first_msg_obj, dict) else at_all
                first_msg = first_msg_obj.get("content") if isinstance(first_msg_obj, dict) else first_msg_obj

                if (actual_at and isinstance(actual_at, list)) or actual_at_all:
                    # 有 @ 时：@名字 + 回车选人，粘贴消息，回车发送
                    import uiautomation as uia
                    from wxauto.utils import SetClipboardText

                    first_msg = messages[0] if messages else ""
                    wx._show()
                    human_delay(200, 400)
                    editbox = wx.ChatBox.EditControl(searchDepth=10)
                    if not editbox.Exists():
                        editbox = wx.ChatBox.EditControl(Name=group, searchDepth=10)
                    if not editbox.HasKeyboardFocus:
                        editbox.Click(simulateMove=False)
                        human_delay(100, 200)

                    # 清空输入框
                    uia.SendKeys('{Ctrl}a', waitTime=0.05)
                    time.sleep(0.1)

                    if actual_at_all:
                        log.info("[send] 输入 @所有人 回车")
                        uia.SendKeys('@所有人', waitTime=0.1)
                        time.sleep(0.5)
                        uia.SendKeys('{Enter}', waitTime=0.1)
                        time.sleep(0.2)

                    if actual_at and isinstance(actual_at, list):
                        for member in actual_at:
                            log.info(f"[send] 输入 @{member} 回车")
                            uia.SendKeys(f'@{member}', waitTime=0.1)
                            time.sleep(0.5)
                            uia.SendKeys('{Enter}', waitTime=0.1)
                            time.sleep(0.2)

                    # 粘贴第一条消息
                    time.sleep(0.1)
                    SetClipboardText(first_msg)
                    uia.SendKeys('{Ctrl}v', waitTime=0.1)
                    time.sleep(0.3)
                    uia.SendKeys('{Enter}', waitTime=0.1)
                    log.info(f"[send] 第一条消息(带@)已发送: {first_msg[:30]}...")

                    # 剩余消息用 SendMsgs 批量发送（不带 @）
                    remaining = messages[1:] if len(messages) > 1 else []
                    if remaining:
                        time.sleep(random.uniform(0.5, 1.5))
                        clean_remaining = [m.get("content") if isinstance(m, dict) else m for m in remaining]
                        wx.SendMsgs(clean_remaining, group)
                        log.debug(f"[send] 批量发送剩余 {len(remaining)} 条消息")
                else:
                    clean_messages = [m.get("content") if isinstance(m, dict) else m for m in messages]
                    wx.SendMsgs(clean_messages, group)
                log.debug(f"[send] 批量发送 {len(messages)} 条消息到 {group}")
                # 更新发送时间戳
                with _get_main()._send_lock:
                    _get_main()._last_send_time = time.time()
            except Exception as e:
                log.error(f"[send] 批量发送失败: {e}")
                return pre_caught

            human_delay(400, 1000)

            # ── 捕获发送期间到达的新消息 ──
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

            # ── 合并去重 ──
            all_caught = list(pre_caught)
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
                    all_caught.append(msg)

            return all_caught

    except Exception as e:
        log.error(f"[send] 批量发送失败: {e}")
        return []

    finally:
        # 标记发送完成
        with _get_main()._send_lock:
            _get_main()._sending_count -= 1
            if _get_main()._sending_count <= 0:
                _get_main()._is_sending = False
                _get_main()._sending_count = 0
            log.debug(f"[send] 批量发送完成，剩余计数: {_get_main()._sending_count}")


def get_wechat():
    """获取WeChat实例，延迟初始化（线程安全）"""
    global _wx
    if _wx is None:
        if getattr(_get_main(), 'MOCK_SEND', False):
            _wx = True
            return _wx
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
        if getattr(_get_main(), 'MOCK_SEND', False):
            log.info("[MOCK] 跳过微信初始化（mock_send 已开启）")
            _wx = True  # 标记为已初始化，但非真实实例
            return _wx
        with _wx_lock:
            if _wx is None:
                _wx = WeChat()
                _patch_wxauto_human_behavior()
    return _wx


def get_new_messages():
    """获取所有新消息（受互斥锁保护，避免与发送操作冲突）"""
    if getattr(_get_main(), 'MOCK_SEND', False):
        return {}
    wx = get_wechat()
    if wx:
        try:
            log.debug("调用 wx.GetAllNewMessage()")
            human_delay(500, 2000)
            # 互斥锁：确保收消息时不会有其他线程同时执行 ChatWith
            with _send_op_lock:
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
