"""
系统级通知检测（无截图，纯 Win32 API + PIL）

通过读取微信任务栏按钮区域的颜色变化检测新消息。
不操控微信窗口，不注入任何进程。
"""
import ctypes
import ctypes.wintypes as wintypes
import time
import logging
from PIL import ImageGrab, ImageChops

log = logging.getLogger(__name__)


def _find_taskbar_rect():
    """获取任务栏矩形"""
    shell = ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None)
    if not shell:
        return None
    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(shell, ctypes.byref(rect))
    return (rect.left, rect.top, rect.right, rect.bottom)


def is_wechat_flashing():
    """检测微信任务栏按钮是否在闪烁/变色"""
    hwnd = ctypes.windll.user32.FindWindowW("WeChatMainWndForPC", None)
    if not hwnd:
        return None
    if not ctypes.windll.user32.IsIconic(hwnd):
        return None

    taskbar = _find_taskbar_rect()
    if not taskbar:
        return None

    changes = []
    for _ in range(3):
        img1 = ImageGrab.grab(bbox=taskbar, all_screens=True)
        time.sleep(0.2)
        img2 = ImageGrab.grab(bbox=taskbar, all_screens=True)

        diff = ImageChops.difference(img1, img2)
        c = sum(1 for px in diff.getdata() if any(v > 5 for v in px[:3]))
        changes.append(c)

    flash_count = sum(1 for c in changes if c > 10)
    is_flashing = flash_count >= 1

    log.debug(f"变化: {changes} → {'有消息' if is_flashing else '正常'}")
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
