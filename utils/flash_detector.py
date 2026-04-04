"""
系统级通知检测

混合检测策略：优先用 Win32 API 读取窗口状态（零截图），
只在 API 不可用时降级到截图对比。大幅减少截屏频率。
"""
import ctypes
import ctypes.wintypes as wintypes
import time
import logging
import random

log = logging.getLogger(__name__)

# ── 状态跟踪 ──
_last_check_time = 0
_last_result = False
_consecutive_false = 0  # 连续"无消息"次数，用于动态降频


def _find_taskbar_rect():
    """获取任务栏矩形"""
    shell = ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None)
    if not shell:
        return None
    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(shell, ctypes.byref(rect))
    return (rect.left, rect.top, rect.right, rect.bottom)


def _check_window_state():
    """通过 Win32 API 检查窗口状态（零截图）

    返回 True 如果窗口可能存在未读消息：
    - 窗口处于最小化状态（有闪烁可能）
    - 窗口类名匹配微信
    """
    hwnd = ctypes.windll.user32.FindWindowW("WeChatMainWndForPC", None)
    if not hwnd:
        return None
    if not ctypes.windll.user32.IsIconic(hwnd):
        return None  # 窗口没最小化，不检测
    return hwnd


def _screenshot_check(taskbar):
    """截屏对比检测（降级方案，尽量少用）"""
    try:
        from PIL import ImageGrab, ImageChops

        # 只截两次（而非三次），减少截屏次数
        img1 = ImageGrab.grab(bbox=taskbar, all_screens=True)
        time.sleep(0.15 + random.uniform(0, 0.1))  # 间隔随机化
        img2 = ImageGrab.grab(bbox=taskbar, all_screens=True)

        diff = ImageChops.difference(img1, img2)
        c = sum(1 for px in diff.getdata() if any(v > 5 for v in px[:3]))
        return c > 10
    except Exception as e:
        log.debug(f"截屏检测异常: {e}")
        return False


def is_wechat_flashing():
    """检测微信是否有新消息

    策略变化：
    1. 先检查窗口是否最小化（零成本）
    2. 连续无消息时动态降低截屏频率
    3. 每隔 N 次轮询才做一次截屏对比
    """
    global _last_check_time, _last_result, _consecutive_false

    now = time.time()

    # 窗口检查（零成本）
    hwnd = _check_window_state()
    if hwnd is None:
        return None

    # 动态降频：连续 N 次无消息后，截屏间隔拉长
    # 这大幅减少了截屏 API 的调用频率
    if _consecutive_false > 3:
        # 连续 3 次无消息 → 每 2~3 秒才截一次
        min_interval = 2.0
    elif _consecutive_false > 0:
        # 连续 1~3 次无消息 → 每 1~1.5 秒截一次
        min_interval = 1.0
    else:
        # 上次有消息 → 保持较快检测
        min_interval = 0.5

    if now - _last_check_time < min_interval + random.uniform(0, 0.5):
        # 没到间隔，返回上一次的结果（避免固定频率截屏）
        return _last_result

    _last_check_time = now

    # 实际截屏检测
    taskbar = _find_taskbar_rect()
    if not taskbar:
        return None

    is_flashing = _screenshot_check(taskbar)

    if is_flashing:
        _consecutive_false = 0
        _last_result = True
    else:
        _consecutive_false += 1
        _last_result = False

    log.debug(f"闪烁检测: {'有消息' if is_flashing else '无消息'} (连续空闲: {_consecutive_false})")
    return is_flashing


def has_wechat_notification():
    """统一接口"""
    return is_wechat_flashing()


# ============================================================
# 测试
# ============================================================
if __name__ == "__main__":
    import logging as _log
    _log.basicConfig(level=_log.DEBUG, format="%(message)s")

    hwnd = ctypes.windll.user32.FindWindowW("WeChatMainWndForPC", None)
    minimized = ctypes.windll.user32.IsIconic(hwnd) if hwnd else False
    taskbar = _find_taskbar_rect()

    log.info(f"微信窗口: {'存在' if hwnd else '未找到'}")
    log.info(f"最小化: {'是' if minimized else '否'}")
    log.info(f"任务栏: {taskbar}")

    if hwnd and minimized and taskbar:
        log.info("\n采样检测（请让微信闪烁）...\n")
        for i in range(10):
            r = is_wechat_flashing()
            time.sleep(0.2)
    else:
        log.info("\n请将微信最小化后重试")
