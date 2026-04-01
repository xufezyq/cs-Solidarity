"""
系统级通知检测模块

通过 Win32 系统托盘图标检测微信通知，替代屏幕截图方案。
直接读取 Windows 内部托盘数据，不需要截图或操控微信窗口。
"""
import ctypes
import ctypes.wintypes as wintypes
import re
import logging

log = logging.getLogger(__name__)

# Win32 常量
WM_USER = 0x0400
TB_BUTTONCOUNT = WM_USER + 24
TB_GETBUTTON = WM_USER + 23


class TBBUTTON(ctypes.Structure):
    _fields_ = [
        ("iBitmap", ctypes.c_int),
        ("idCommand", ctypes.c_int),
        ("fsState", ctypes.c_byte),
        ("fsStyle", ctypes.c_byte),
        ("bReserved", ctypes.c_byte * 6),
        ("dwData", ctypes.c_ulonglong),
        ("iString", ctypes.c_ulonglong),
    ]


def _get_tray_toolbar_hwnds():
    """获取系统托盘工具栏句柄列表"""
    hwnds = []

    shell_tray = ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None)
    if not shell_tray:
        return hwnds

    tray_notify = ctypes.windll.user32.FindWindowExW(shell_tray, 0, "TrayNotifyWnd", None)
    if tray_notify:
        sys_pager = ctypes.windll.user32.FindWindowExW(tray_notify, 0, "SysPager", None)
        if sys_pager:
            toolbar = ctypes.windll.user32.FindWindowExW(sys_pager, 0, "ToolbarWindow32", None)
            if toolbar:
                hwnds.append(toolbar)

    if not hwnds:
        def enum_child(hwnd, param):
            buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
            if buf.value == "ToolbarWindow32":
                param.append(hwnd)
            return True
        cb = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        ctypes.windll.user32.EnumChildWindows(shell_tray, cb(enum_child), id(hwnds))

    return hwnds


def _read_remote_string(h_process, address, max_len=512):
    """从远程进程读取 Unicode 字符串"""
    buf = ctypes.create_unicode_buffer(max_len)
    ctypes.windll.kernel32.ReadProcessMemory(
        h_process, address, buf, max_len * 2, ctypes.byref(ctypes.c_size_t())
    )
    return buf.value


def has_wechat_notification():
    """检测微信是否有未读通知（Win32 系统托盘图标）

    Returns:
        True  - 检测到未读消息
        False - 无未读消息
        None  - 检测失败
    """
    try:
        toolbar_hwnds = _get_tray_toolbar_hwnds()
        if not toolbar_hwnds:
            return None

        for toolbar_hwnd in toolbar_hwnds:
            pid = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(toolbar_hwnd, ctypes.byref(pid))
            if pid.value == 0:
                continue

            PROCESS_ALL_ACCESS = 0x1F0FFF
            h_proc = ctypes.windll.kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid.value)
            if not h_proc:
                continue

            try:
                btn_count = ctypes.windll.user32.SendMessageW(toolbar_hwnd, TB_BUTTONCOUNT, 0, 0)
                if btn_count == 0:
                    continue

                MEM_COMMIT_RESERVE = 0x3000
                PAGE_RW = 0x04
                remote_buf = ctypes.windll.kernel32.VirtualAllocEx(
                    h_proc, 0, ctypes.sizeof(TBBUTTON), MEM_COMMIT_RESERVE, PAGE_RW
                )
                if not remote_buf:
                    continue

                try:
                    for i in range(btn_count):
                        ctypes.windll.user32.SendMessageW(
                            toolbar_hwnd, TB_GETBUTTON, i, remote_buf
                        )

                        tb = TBBUTTON()
                        ctypes.windll.kernel32.ReadProcessMemory(
                            h_proc, remote_buf, ctypes.byref(tb),
                            ctypes.sizeof(TBBUTTON), ctypes.byref(ctypes.c_size_t())
                        )

                        if not tb.dwData:
                            continue

                        try:
                            tray_hwnd = wintypes.HWND()
                            ctypes.windll.kernel32.ReadProcessMemory(
                                h_proc, tb.dwData, ctypes.byref(tray_hwnd),
                                ctypes.sizeof(wintypes.HWND), ctypes.byref(ctypes.c_size_t())
                            )
                            if not tray_hwnd:
                                continue

                            cls = ctypes.create_unicode_buffer(256)
                            ctypes.windll.user32.GetClassNameW(tray_hwnd, cls, 256)
                            if cls.value != "WeChatMainWndForPC":
                                continue

                            tooltip = ""
                            if tb.iString and tb.iString != -1:
                                tooltip = _read_remote_string(h_proc, tb.iString)

                            log.debug(f"[notification] 微信托盘图标 tooltip: '{tooltip}'")

                            match = re.search(r'[\(（](\d+)[\)）]|(\d+)\s*条新消息', tooltip)
                            if match:
                                count = int(match.group(1) or match.group(2))
                                log.debug(f"[notification] 检测到 {count} 条未读消息")
                                return True
                            else:
                                log.debug("[notification] 微信在线，无未读消息")
                                return False

                        except Exception:
                            continue

                finally:
                    MEM_RELEASE = 0x8000
                    ctypes.windll.kernel32.VirtualFreeEx(h_proc, remote_buf, 0, MEM_RELEASE)

            finally:
                ctypes.windll.kernel32.CloseHandle(h_proc)

        log.debug("[notification] 未在托盘中找到微信图标")
        return None

    except Exception as e:
        log.error(f"[notification] {e}")
        return None
