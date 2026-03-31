"""
微信新消息监听模块
通过 WinEventHook 监听 EVENT_SYSTEM_FLASH 事件，
当微信窗口闪烁（收到新消息）时触发回调，无需频繁操作 UI。
"""
import ctypes
import ctypes.wintypes
import threading
import time
import win32gui
import win32con

# Windows API 常量
EVENT_SYSTEM_FLASH = 0x8007
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002

# ctypes 回调类型
WINEVENTPROC = ctypes.WINFUNCTYPE(
    None,
    ctypes.wintypes.HANDLE,   # hWinEventHook
    ctypes.wintypes.DWORD,    # event
    ctypes.wintypes.HWND,     # hwnd
    ctypes.wintypes.LONG,     # idObject
    ctypes.wintypes.LONG,     # idChild
    ctypes.wintypes.DWORD,    # dwEventThread
    ctypes.wintypes.DWORD     # dwmsEventTime
)

user32 = ctypes.windll.user32


class WeChatFlashMonitor:
    """微信窗口闪烁监听器"""

    def __init__(self, on_flash_callback, cooldown=3.0):
        """
        Args:
            on_flash_callback: 检测到微信闪烁时调用的回调函数 (无参数)
            cooldown: 两次触发之间的最小间隔（秒），防止重复触发
        """
        self.on_flash_callback = on_flash_callback
        self.cooldown = cooldown
        self.wechat_hwnd = None
        self._hook = None
        self._thread = None
        self._running = False
        self._last_trigger_time = 0
        self._callback_lock = threading.Lock()

    def _find_wechat_window(self):
        """查找微信窗口句柄"""
        hwnd = win32gui.FindWindow("WeChatMainWndForPC", None)
        return hwnd if hwnd else None

    def _make_hook_proc(self):
        """创建 WinEventHook 回调（必须保持引用防止 GC）"""

        def hook_proc(hWinEventHook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime):
            if event != EVENT_SYSTEM_FLASH:
                return

            # 检查是否是微信窗口
            if self.wechat_hwnd and hwnd == self.wechat_hwnd:
                now = time.time()
                with self._callback_lock:
                    if now - self._last_trigger_time < self.cooldown:
                        return
                    self._last_trigger_time = now

                print(f"[FlashMonitor] 检测到微信窗口闪烁，触发消息检查")
                try:
                    self.on_flash_callback()
                except Exception as e:
                    print(f"[FlashMonitor] 回调执行出错: {e}")

        return WINEVENTPROC(hook_proc)

    def _message_pump(self):
        """Windows 消息循环（在独立线程运行，接收事件通知）"""
        msg = ctypes.wintypes.MSG()

        while self._running:
            # PM_REMOVE = 0x0001，有消息时取出并处理
            has_msg = user32.PeekMessageW(
                ctypes.byref(msg), None, 0, 0, 0x0001
            )
            if has_msg:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                # 没有消息时休眠，避免 CPU 空转
                time.sleep(0.05)

    def start(self):
        """启动监听"""
        if self._running:
            print("[FlashMonitor] 已在运行中")
            return False

        # 查找微信窗口
        self.wechat_hwnd = self._find_wechat_window()
        if not self.wechat_hwnd:
            print("[FlashMonitor] 未找到微信窗口，请先启动微信")
            return False

        print(f"[FlashMonitor] 找到微信窗口: HWND={self.wechat_hwnd}")

        # 创建 Hook 回调（必须保持引用）
        self._hook_proc = self._make_hook_proc()

        # 设置全局事件钩子
        self._hook = user32.SetWinEventHook(
            EVENT_SYSTEM_FLASH,   # eventMin
            EVENT_SYSTEM_FLASH,   # eventMax
            None,                 # hmodWinEventProc (NULL = 所有进程)
            self._hook_proc,      # lpfnWinEventProc
            0,                    # idProcess (0 = 所有进程)
            0,                    # idThread (0 = 所有线程)
            WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS
        )

        if not self._hook:
            print("[FlashMonitor] SetWinEventHook 失败")
            return False

        # 启动消息泵线程
        self._running = True
        self._thread = threading.Thread(target=self._message_pump, daemon=True)
        self._thread.start()

        print("[FlashMonitor] 闪存监听已启动")
        return True

    def stop(self):
        """停止监听"""
        self._running = False

        if self._hook:
            user32.UnhookWinEvent(self._hook)
            self._hook = None
            print("[FlashMonitor] Hook 已卸载")

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
            self._thread = None

        print("[FlashMonitor] 已停止")

    def refresh_hwnd(self):
        """刷新微信窗口句柄（微信重启后需要调用）"""
        new_hwnd = self._find_wechat_window()
        if new_hwnd and new_hwnd != self.wechat_hwnd:
            self.wechat_hwnd = new_hwnd
            print(f"[FlashMonitor] 微信窗口句柄已更新: HWND={new_hwnd}")
            return True
        return False

    def is_running(self):
        """是否正在运行"""
        return self._running and self._hook is not None
