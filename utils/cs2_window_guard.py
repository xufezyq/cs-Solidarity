"""CS2 录制期间的窗口守护：周期性把 CS2 主窗口拉到前台。

Windows 11 对后台窗口会降级渲染（限帧、降 GPU 优先级），
导致 Insight 录屏卡顿。本模块在录制期间以约 1.5s 周期
检测 CS2 窗口并激活到前台，与 main.py 主循环的
cs2_recording 暂停逻辑、wechat_instance._safe_show 的
SetForegroundWindow 跳过逻辑配合使用。
"""
import ctypes
import logging
import threading

log = logging.getLogger(__name__)

# Win32 常量（避免依赖 win32con 在所有路径上都可导入）
_VK_MENU = 0x12            # ALT 键
_KEYEVENTF_KEYUP = 0x0002
_SW_RESTORE = 9
_SW_SHOWNORMAL = 1

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32


def find_cs2_window():
    """返回 cs2.exe 主窗口的 HWND（int），找不到返回 None。

    CS2 主窗口类名 SDL_app、标题含 "Counter-Strike"。
    CS2 启动早期可能出现加载窗口；优先选 SDL_app + Counter-Strike 标题的窗口，
    否则退回到任意可见且有标题的 cs2.exe 顶级窗口。
    """
    try:
        import psutil
        import win32gui
        import win32process
    except ImportError:
        return None

    # 收集所有 cs2.exe 进程 PID（大小写不敏感）
    cs2_pids = set()
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = proc.info.get("name") or ""
            if name.lower() == "cs2.exe":
                cs2_pids.add(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if not cs2_pids:
        return None

    candidates = []  # [(hwnd, title, class_name)]

    def _enum(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid not in cs2_pids:
                return True
            title = (win32gui.GetWindowText(hwnd) or "").strip()
            if not title:
                return True
            cls = win32gui.GetClassName(hwnd) or ""
            candidates.append((hwnd, title, cls))
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(_enum, None)
    except Exception as exc:
        log.debug("[cs2-window-guard] EnumWindows failed: %s", exc)
        return None

    if not candidates:
        return None
    # 优先匹配 SDL_app + Counter-Strike
    for hwnd, title, cls in candidates:
        if cls == "SDL_app" and "Counter-Strike" in title:
            return hwnd
    # 退化：取第一个
    return candidates[0][0]


def bring_to_foreground(hwnd) -> bool:
    """把 hwnd 激活到前台。返回 True 表示最终前台确为 hwnd。"""
    if not hwnd:
        return False
    try:
        import win32gui
    except ImportError:
        return False

    try:
        # 已经是前台 → 跳过
        if _user32.GetForegroundWindow() == hwnd:
            return True
        # 最小化则先恢复
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, _SW_RESTORE)
        # 微小等待，让恢复生效
        import time as _t
        _t.sleep(0.05)

        # ── 方法 1：Alt 键 trick ──
        # 发一次虚拟 ALT 按下/抬起，让 SetForegroundWindow 认为
        # 当前线程刚收到用户输入，从而绕过 foreground-lock。
        _user32.keybd_event(_VK_MENU, 0, 0, 0)
        _user32.keybd_event(_VK_MENU, 0, _KEYEVENTF_KEYUP, 0)
        try:
            _user32.SetForegroundWindow(hwnd)
        except Exception as exc:
            log.debug("[cs2-window-guard] SetForegroundWindow(alt) failed: %s", exc)
        if _user32.GetForegroundWindow() == hwnd:
            return True

        # ── 方法 2：AttachThreadInput ──
        # 把当前线程的输入队列附加到当前前台线程，
        # 这样 SetForegroundWindow 会被允许。
        try:
            fg_hwnd = _user32.GetForegroundWindow()
            fg_tid = _user32.GetWindowThreadProcessId(fg_hwnd, None)
            our_tid = _kernel32.GetCurrentThreadId()
            if fg_tid and fg_tid != our_tid and _user32.AttachThreadInput(our_tid, fg_tid, True):
                try:
                    _user32.SetForegroundWindow(hwnd)
                    _user32.BringWindowToTop(hwnd)
                    # 让目标窗口收到一次激活消息
                    win32gui.ShowWindow(hwnd, _SW_SHOWNORMAL)
                finally:
                    _user32.AttachThreadInput(our_tid, fg_tid, False)
        except Exception as exc:
            log.debug("[cs2-window-guard] AttachThreadInput path failed: %s", exc)

        return _user32.GetForegroundWindow() == hwnd
    except Exception as exc:
        log.debug("[cs2-window-guard] bring_to_foreground error: %s", exc)
        return False


class Cs2WindowGuard:
    """录制期间持续把 CS2 拉到前台的守护线程。

    用法::

        with Cs2WindowGuard(interval_sec=1.5, enabled=True):
            insight.recording_queue(...)  # 阻塞 7200s
    """

    def __init__(self, interval_sec: float = 1.5, enabled: bool = True,
                 startup_grace_sec: float = 5.0, logger=None):
        self.interval = max(0.5, float(interval_sec))
        self.enabled = bool(enabled)
        self.startup_grace = max(0.0, float(startup_grace_sec))
        self.log = logger or log
        self._stop = threading.Event()
        self._thread = None
        self._first_seen = False

    def __enter__(self):
        if not self.enabled:
            self.log.info("[cs2-window-guard] 已通过配置禁用，跳过启动")
            return self
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="cs2-window-guard", daemon=True
        )
        self._thread.start()
        self.log.info("[cs2-window-guard] 已启动 (interval=%.2fs)", self.interval)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._thread is None:
            return False
        self._stop.set()
        # Event.wait 可中断，线程应在 interval 内退出
        self._thread.join(timeout=max(2.0, self.interval * 2))
        self.log.info("[cs2-window-guard] 已停止")
        return False

    def _run(self):
        import time as _t
        started = _t.monotonic()
        while not self._stop.is_set():
            try:
                hwnd = find_cs2_window()
                if hwnd:
                    if not self._first_seen:
                        self.log.info("[cs2-window-guard] 检测到 CS2 窗口 hwnd=%s", hwnd)
                        self._first_seen = True
                    # 仅在 CS2 不在前台时尝试激活，避免无谓的 SetForegroundWindow 调用
                    if _user32.GetForegroundWindow() != hwnd:
                        ok = bring_to_foreground(hwnd)
                        if not ok:
                            self.log.debug("[cs2-window-guard] 激活失败 hwnd=%s", hwnd)
                else:
                    # 启动宽限期内未发现 CS2 是正常的（Insight 还在拉起 CS2）
                    if _t.monotonic() - started > self.startup_grace and not self._first_seen:
                        self.log.debug("[cs2-window-guard] 尚未检测到 CS2 窗口")
            except Exception as exc:
                # 守护线程不能因任何单次异常退出
                self.log.debug("[cs2-window-guard] 迭代异常: %s", exc)
            # 可中断的等待
            self._stop.wait(self.interval)
