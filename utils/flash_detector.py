"""
系统级通知检测

混合检测策略：
1. Win32 API 检查窗口状态（GetWindowPlacement，比 IsIconic 更可靠）
2. 精确定位系统托盘通知区域截图对比（缩小检测范围，提高准确率）
3. 自适应频率降低资源占用
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

# ── Win32 常量 ──
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
GWL_STYLE = -16
WS_MINIMIZE = 0x20000000


def _find_notification_area_rect():
    """截取屏幕右下角任务栏通知区域

    截取右下角 300x48 像素的区域，避开右侧时钟区域（约100像素）。
    检测区域 = 从屏幕右侧 (clock_width + margin) 开始，向左延伸 tray_width 像素。
    """
    user32 = ctypes.windll.user32

    try:
        screen_w = user32.GetSystemMetrics(0)
        screen_h = user32.GetSystemMetrics(1)
        tray_width = 300
        tray_height = 48
        clock_width = 100  # 时钟/日期区域宽度，需要避开
        margin = 4
        # 区域：右下角，避开时钟，向左延伸 300px
        right = screen_w - clock_width - margin
        left = right - tray_width
        bottom = screen_h - margin
        top = bottom - tray_height
        tray_rect = (left, top, right, bottom)
        log.debug(f"托盘图标区域: {tray_rect}")
        return tray_rect
    except Exception:
        pass

    return None


def _check_window_state():
    """通过 Win32 API 检查窗口状态

    使用 GetWindowPlacement 替代 IsIconic，Win11 兼容性更好。
    同时检查窗口是否可见、是否最小化。
    """
    user32 = ctypes.windll.user32

    hwnd = user32.FindWindowW("WeChatMainWndForPC", None)
    if not hwnd:
        # 备用：尝试其他可能的类名
        hwnd = user32.FindWindowW("WeChatMainWndForPC_xxx", None)
    if not hwnd:
        return None

    # 方法1：GetWindowPlacement（最可靠）
    class WINDOWPLACEMENT(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_uint),
            ("flags", ctypes.c_uint),
            ("showCmd", ctypes.c_uint),
            ("ptMinPosition", wintypes.POINT),
            ("ptMaxPosition", wintypes.POINT),
            ("rcNormalPosition", wintypes.RECT),
        ]

    wp = WINDOWPLACEMENT()
    wp.length = ctypes.sizeof(WINDOWPLACEMENT)
    if user32.GetWindowPlacement(hwnd, ctypes.byref(wp)):
        # showCmd: 1=SW_SHOWNORMAL, 2=SW_SHOWMINIMIZED, 3=SW_SHOWMAXIMIZED
        if wp.showCmd == 2:
            log.debug(f"GetWindowPlacement: 微信已最小化 (showCmd={wp.showCmd})")
            return hwnd

    # 方法2：检查 WS_MINIMIZE 样式（备用）
    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    if style & WS_MINIMIZE:
        log.debug(f"GetWindowLongW: 微信已最小化 (WS_MINIMIZE)")
        return hwnd

    # 方法3：IsIconic（最后备用）
    if user32.IsIconic(hwnd):
        log.debug(f"IsIconic: 微信已最小化")
        return hwnd

    # 窗口没最小化
    return None


def _screenshot_check(region):
    """截屏对比检测（降级方案）"""
    try:
        from PIL import ImageGrab, ImageChops

        img1 = ImageGrab.grab(bbox=region, all_screens=True)
        time.sleep(0.12 + random.uniform(0, 0.08))
        img2 = ImageGrab.grab(bbox=region, all_screens=True)

        diff = ImageChops.difference(img1, img2)
        c = sum(1 for px in diff.getdata() if any(v > 8 for v in px[:3]))
        # 缩小检测区域后阈值可以适当降低
        return c > 5
    except Exception as e:
        log.debug(f"截屏检测异常: {e}")
        return False


def is_wechat_flashing():
    """检测微信是否有新消息

    策略：
    1. 先用 Win32 API 检查窗口是否最小化（零成本）
    2. 连续无消息时动态降低截屏频率
    3. 截取通知区域（而非整个任务栏）对比像素变化
    """
    global _last_check_time, _last_result, _consecutive_false

    now = time.time()

    # 窗口检查（零成本）
    hwnd = _check_window_state()
    if hwnd is None:
        return None

    # 动态降频
    if _consecutive_false > 3:
        min_interval = 2.0
    elif _consecutive_false > 0:
        min_interval = 1.0
    else:
        min_interval = 0.5

    if now - _last_check_time < min_interval + random.uniform(0, 0.5):
        return _last_result

    _last_check_time = now

    # 精确截取通知区域
    region = _find_notification_area_rect()
    if not region:
        return None

    is_flashing = _screenshot_check(region)

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

    hwnd = _check_window_state()
    user32 = ctypes.windll.user32
    raw_hwnd = user32.FindWindowW("WeChatMainWndForPC", None)
    minimized = hwnd is not None
    region = _find_notification_area_rect()

    log.info(f"微信窗口: {'存在' if raw_hwnd else '未找到'} (hwnd={raw_hwnd})")
    log.info(f"最小化: {'是' if minimized else '否'}")
    log.info(f"通知区域: {region}")

    if raw_hwnd and minimized and region:
        log.info("\n采样检测（请让微信闪烁）...\n")
        for i in range(10):
            r = is_wechat_flashing()
            log.info(f"  [{i}] = {r}")
            time.sleep(0.2)
    else:
        log.info("\n请将微信最小化后重试")
