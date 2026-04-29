import json
import threading
import queue
import time
import sys
from collections import OrderedDict
import random
from datetime import datetime, time as dt_time
from pathlib import Path
from core import init_wechat, wechat_instance, get_instance_from_item, BaseInstance
from core.wechat_instance import _send_op_lock
from utils.human_sim import human_delay, human_action_delay, random_poll_interval, random_human_pause
from utils.logger import setup_logger, info, debug, error, warning
from version import VERSION, get_version_info
from bot.chat_server import start_chat_server
import win32gui

# 设置进程名
try:
    import setproctitle
    setproctitle.setproctitle("cs-Solidarity")
except ImportError:
    pass  # 忽略导入失败，兼容没有安装 setproctitle 的环境

import logging

# 强制 UTF-8 输出
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

DEBUG_MODE = False

# 版本信息
APP_VERSION = VERSION
print(f"[cs-Solidarity] 版本：{APP_VERSION}")
info(f"启动 - 版本：{APP_VERSION}")

# 消息发送锁，确保消息发送期间不最小化窗口
_send_lock = threading.Lock()
_last_send_time = 0  # 记录最后一次发送的时间
_is_sending = False  # 是否正在发送消息的标志
_sending_count = 0   # 正在发送的消息数量

# ============================================================
# 维护时间配置
# ============================================================
# 维护时间配置：默认凌晨 0:15-8:00
MAINTENANCE_START = dt_time(0, 15)  # 维护开始时间
MAINTENANCE_END = dt_time(8, 0)     # 维护结束时间
ENABLE_SEND = True                   # 是否允许发送消息
ENABLE_RECEIVE = True                # 是否允许接收消息（处理消息）
ENABLE_FLASH_DETECT = True           # 是否检测新消息（闪烁检测）

# 消息拦截器：用于 Web 聊天页面捕获实例回复
# 回调签名: interceptor(instance_name, message)
_on_message_interceptor = None

# 当前正在处理消息的实例名（供 wechat_instance 拦截器使用）
_current_processing_instance = None

# 全局实例列表（供 Agent handler 访问）
_instances = []

# Web 聊天消息队列：Agent handler → 主循环处理
# 格式: {"content": str, "sender": str, "chat_name": str, "replies": Queue, "event": threading.Event}
web_msg_queue = queue.Queue()

# Web 回复路由表：chat_name → replies_q
_web_replies_map = {}
# Web 消息上下文：chat_name → {"sender", "content"}（当前正在处理的消息）
_web_msg_context = {}
# 已捕获回复的上下文：(instance, target) → {"sender", "content"}
# 拦截器在上下文有效时捕获，_intercepted_wx_send 读取后删除
_captured_reply_contexts = {}
# Web 聊天处理实例映射：chat_name → instance_name（用于异步回复时确定发送者）
_web_processing_instances = {}
# 拦截去重集合：(content, target) 已处理的消息（LRU，最多 200 条）
_intercepted_msg_dedup = OrderedDict()
MOCK_SEND = False                     # 调试模式：拦截所有发送改为打印日志

# ============================================================
# 维护时间检查
# ============================================================
def is_maintenance_time():
    """检查当前是否在维护时间内"""
    if DEBUG_MODE:
        return False
    now = datetime.now().time()
    return MAINTENANCE_START <= now < MAINTENANCE_END

def check_maintenance():
    """维护时间检查接口（供其他模块调用）"""
    return is_maintenance_time()

import core
core.check_maintenance = check_maintenance


# ============================================================
# 微信窗口控制
# ============================================================
def _get_wechat_hwnd():
    return win32gui.FindWindow('WeChatMainWndForPC', None)

def minimize_wechat():
    """最小化微信窗口（带重试，Win11 兼容）

    如果有消息正在发送，跳过最小化以避免中断 @ 操作。
    """
    # 用锁检查发送状态，避免 TOCTOU 竞态
    with _send_lock:
        if _sending_count > 0:
            debug(f"[窗口] 跳过最小化：有 {_sending_count} 条消息正在发送")
            return
        elapsed = time.time() - _last_send_time
    if elapsed < 5:
        debug(f"[窗口] 跳过最小化：距离上次发送仅 {elapsed:.1f}s")
        return
    debug(f"[窗口] 执行最小化")
    try:
        hwnd = _get_wechat_hwnd()
        if not hwnd:
            return
        import ctypes
        user32 = ctypes.windll.user32
        # 再次检查（拿锁后窗口可能已被恢复）
        if user32.IsIconic(hwnd):
            return
        # 先用 Win32 API 最小化（比 win32gui 更可靠）
        user32.ShowWindow(hwnd, 2)  # SW_MINIMIZE
        time.sleep(0.05)
        # 验证是否真的最小化了
        if not user32.IsIconic(hwnd):
            # 重试：先 PostMessage 再 ShowWindow
            user32.PostMessageW(hwnd, 0x0112, 0xF020, 0)  # WM_SYSCOMMAND + SC_MINIMIZE
            time.sleep(0.05)
            if not user32.IsIconic(hwnd):
                # 最终手段：win32gui
                win32gui.ShowWindow(hwnd, 2)
        debug("[窗口] 微信已最小化")
    except Exception as e:
        error(f"[窗口] 最小化失败: {e}")

def restore_wechat():
    """恢复微信窗口并置前（Win11 兼容）"""
    try:
        hwnd = _get_wechat_hwnd()
        if not hwnd:
            return
        import ctypes
        user32 = ctypes.windll.user32
        # SW_RESTORE = 9
        user32.ShowWindow(hwnd, 9)
        time.sleep(0.1)
        # 确保窗口在前台
        user32.SetForegroundWindow(hwnd)
        human_delay(300, 600)
        debug("[窗口] 微信已恢复")
    except Exception as e:
        error(f"[窗口] 恢复失败: {e}")


# ============================================================
# 消息处理
# ============================================================
def process_send_message(name, message, orig_senders, instances=None):
    """发送消息并处理发送期间捕获的新消息"""
    # 检查是否允许发送消息
    if not ENABLE_SEND:
        debug(f"[发送] 跳过：发送功能已禁用 (name={name})")
        return
    
    # 检查是否在维护时间内
    if is_maintenance_time():
        info(f"[发送] 跳过：当前是维护时间 (name={name})")
        return
        
    target = message.get("target", name) if isinstance(message, dict) else name
    debug(f"发送：name={name}, target={target}")
    try:
        human_action_delay()
        sender = orig_senders.get(name)
        if sender:
            # 发送并获取发送期间的新消息
            caught_msgs = sender(message)
            debug("发送完成")

            # 处理捕获的新消息
            if caught_msgs and instances:
                target_chat = message.get("target") if isinstance(message, dict) else name
                info(f"捕获到 {len(caught_msgs)} 条来自 {target_chat} 的新消息")
                for msg in caught_msgs:
                    msg_content = msg.content if hasattr(msg, 'content') else (msg[1] if isinstance(msg, (list, tuple)) and len(msg) > 1 else str(msg))
                    targets = route_message_to_instances(msg_content, instances)
                    for inst_name, inst in targets:
                        try:
                            inst.handle_message(target_chat, msg)
                        except Exception as e:
                            error(f"{inst_name} 处理失败: {e}")
        else:
            warning(f"未知来源: {name}，已跳过")
    except Exception as e:
        error(f"发送失败 ({name}): {e}")

def process_all_pending_messages(msg_queue, orig_senders, instances=None):
    """一次性处理队列中所有待发送消息，然后切回文件传输助手并最小化

    发送期间微信已在前台，每个消息都会自动捕获发送期间的新消息。
    """
    sent_any = False
    while True:
        try:
            name, message = msg_queue.get_nowait()
            if is_maintenance_time():
                info("维护时段，跳过发送")
                msg_queue.task_done()
                continue
            process_send_message(name, message, orig_senders, instances)
            sent_any = True
            msg_queue.task_done()
            # 增加延迟，确保 KoriChat 等实例有足够时间完成消息发送
            human_delay(1000, 2000)  # 消息间随机延迟（增加到 1-2 秒）
        except queue.Empty:
            break

    if sent_any:
        # 切回文件传输助手（需要拿锁，防止与 KoriChat Timer 的 ChatWith 冲突）
        # 不在这里最小化——由主循环的空闲检测统一处理，避免与后台发送冲突
        wx = wechat_instance.get_wechat()
        if wx:
            try:
                human_delay(300, 600)
                with _send_op_lock:
                    wx.ChatWith('文件传输助手')
                debug("[窗口] 已切换到文件传输助手")
            except Exception as e:
                debug(f"[窗口] 切换失败: {e}")

    return sent_any


def route_message_to_instances(msg_content, instances):
    for name, inst in instances:
        if hasattr(inst, 'trigger_prefix') and inst.trigger_prefix in msg_content:
            return [(name, inst)]
    return [(name, inst) for name, inst in instances if not hasattr(inst, 'trigger_prefix')]


def process_receive_messages(instances):
    """收消息 + 分发，返回收到的消息数量"""
    # 检查是否允许接收消息
    if not ENABLE_RECEIVE:
        debug("[收消息] 跳过：接收功能已禁用")
        return 0
    
    # 检查是否在维护时间内
    if is_maintenance_time():
        debug("[收消息] 跳过：当前是维护时间")
        return 0
        
    debug("收取消息...")
    total_count = 0
    try:
        new_msgs = wechat_instance.get_new_messages()
        if new_msgs:
            info(f"收到 {len(new_msgs)} 个聊天的消息")
            for chat_name, msg_list in new_msgs.items():
                total_count += len(msg_list)
                for msg in msg_list:
                    msg_content = msg.content if hasattr(msg, 'content') else (msg[1] if isinstance(msg, (list, tuple)) and len(msg) > 1 else str(msg))
                    targets = route_message_to_instances(msg_content, instances)
                    for name, inst in targets:
                        try:
                            inst.handle_message(chat_name, msg)
                        except Exception as e:
                            error(f"{name} 处理失败：{e}")
            info(f"共处理 {total_count} 条消息")
        else:
            debug("无新消息")
    except Exception as e:
        error(f"收消息失败：{e}")
        import traceback
        traceback.print_exc()
    return total_count


def _get_persona_name(instance_name, chat_name):
    """从实例配置获取人设显示名"""
    if instance_name == "korichat":
        try:
            with open("instconfig/korichat_config.json", "r", encoding="utf-8") as f:
                kcfg = json.load(f)
            for gcc in kcfg.get("group_chat_config", []):
                if gcc["groupName"] == chat_name:
                    return Path(gcc["avatar"]).name
            return Path(kcfg.get("avatar_dir", "AI")).name
        except Exception:
            return "AI"
    elif instance_name == "chat":
        return "Chat"
    return instance_name


def _web_reply_interceptor(instance_name, message):
    """持久化拦截器：捕获回复给网页，并记录上下文供 _intercepted_wx_send 使用"""
    global _current_processing_instance
    src = _current_processing_instance or instance_name

    reply_content = ""
    reply_target = ""
    if isinstance(message, dict):
        reply_content = message.get("content", str(message))
        reply_target = message.get("target", "")
    elif isinstance(message, str):
        reply_content = message
    else:
        reply_content = str(message)

    if not reply_content:
        return

    # 去重：同一消息可能被拦截两次（实例直接调用 + 主循环发送），
    # 用 (content, target) 记录已处理的消息，避免重复入队
    dedup_key = (reply_content[:200], reply_target)
    if dedup_key in _intercepted_msg_dedup:
        return
    _intercepted_msg_dedup[dedup_key] = None
    if len(_intercepted_msg_dedup) > 200:
        _intercepted_msg_dedup.popitem(last=False)

    # 在上下文有效时捕获（handle_message 执行期间 _web_msg_context 是正确的）
    ctx = _web_msg_context.get(reply_target)
    if not ctx and len(_web_msg_context) == 1:
        ctx = next(iter(_web_msg_context.values()))
    if ctx:
        _captured_reply_contexts[(src, reply_target)] = ctx

    # 按 target 匹配，或回退到唯一注册的 chat_name
    replies_q = _web_replies_map.get(reply_target)
    if not replies_q and len(_web_replies_map) == 1:
        replies_q = next(iter(_web_replies_map.values()))

    if replies_q:
        persona = _get_persona_name(src, reply_target)
        replies_q.put({
            "id": str(time.time()),
            "chat_name": reply_target,
            "sender": persona,
            "content": reply_content,
            "timestamp": datetime.now().isoformat(),
            "source": "ai",
        })
    else:
        debug(f"[Web聊天] 回复未匹配到队列: target={reply_target!r}, src={src!r}, 已注册={list(_web_replies_map.keys())}")


def process_web_messages(instances):
    """处理 Web 聊天消息队列，与 process_receive_messages 逻辑一致"""
    global _on_message_interceptor, _current_processing_instance

    # 确保持久化拦截器已注册
    if _on_message_interceptor is not _web_reply_interceptor:
        _on_message_interceptor = _web_reply_interceptor

    processed = 0
    while not web_msg_queue.empty():
        try:
            web_msg = web_msg_queue.get_nowait()
        except queue.Empty:
            break

        content = web_msg.get("content", "")
        sender = web_msg.get("sender", "WebUser")
        chat_name = web_msg.get("chat_name", "网页聊天室")
        replies_q = web_msg.get("replies")

        if not content:
            continue

        # 注册回复路由和消息上下文
        if replies_q:
            _web_replies_map[chat_name] = replies_q
        _web_msg_context[chat_name] = {"sender": sender, "content": content}

        # 创建消息对象（与 wxauto FriendMessage 接口兼容）
        class WebMessage:
            def __init__(self, content, sender):
                self.content = content
                self.sender = sender
                self.id = str(time.time())
                self.type = "text"
                self.from_web = True

        msg_obj = WebMessage(content, sender)

        try:
            # 路由到实例（与 process_receive_messages 逻辑完全一致）
            targets = route_message_to_instances(content, instances)
            for name, inst in targets:
                _current_processing_instance = name
                _web_processing_instances[chat_name] = name
                try:
                    inst.handle_message(chat_name, msg_obj)
                except Exception as e:
                    error(f"[Web聊天] {name} 处理失败：{e}")
            processed += 1
        finally:
            _current_processing_instance = None
            # 不在这里清理 _web_replies_map 和 _web_msg_context
            # 因为 KoriChat 等实例是异步回复的，清理太早会导致拦截器找不到回复队列
            # 下次同 chat_name 的消息会覆盖旧值

    return processed


# ============================================================
# 通知检测
# ============================================================
def detect_flash():
    """检测微信是否有未读通知（托盘图标 tooltip）"""
    try:
        from utils.flash_detector import is_wechat_flashing
        return is_wechat_flashing()
    except Exception:
        return None


# ============================================================
# 配置
# ============================================================
def load_master_config(config_file):
    global DEBUG_MODE, MAINTENANCE_START, MAINTENANCE_END
    global ENABLE_SEND, ENABLE_RECEIVE, ENABLE_FLASH_DETECT, MOCK_SEND
    if not Path(config_file).exists():
        return {}
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception:
        return {}
    if not isinstance(cfg, dict) or 'instances' not in cfg:
        return {}
    if not cfg.get('instances'):
        return {}
    
    # 加载配置
    DEBUG_MODE = cfg.get('debug_mode', False)
    
    # 加载维护时间配置
    maintenance = cfg.get('maintenance', {})
    if maintenance:
        start_hour = maintenance.get('start_hour', 0)
        start_minute = maintenance.get('start_minute', 15)
        end_hour = maintenance.get('end_hour', 8)
        end_minute = maintenance.get('end_minute', 0)
        MAINTENANCE_START = dt_time(start_hour, start_minute)
        MAINTENANCE_END = dt_time(end_hour, end_minute)
    
    # 加载开关配置
    ENABLE_SEND = cfg.get('enable_send', True)
    ENABLE_RECEIVE = cfg.get('enable_receive', True)
    ENABLE_FLASH_DETECT = cfg.get('enable_flash_detect', True)
    MOCK_SEND = cfg.get('mock_send', False)
    
    return cfg

def create_instances(master_cfg):
    if not master_cfg:
        return []
    instances = []
    for idx, item in enumerate(master_cfg.get('instances', []), 1):
        try:
            inst_type = item.get('type', f'instance_{idx}')
            instances.append((inst_type, get_instance_from_item(item)))
            info(f"实例 {idx} ({inst_type}) 创建成功")
        except Exception as e:
            error(f"创建实例 {idx} 失败: {e}")
    return instances


# ============================================================
# 主循环 —— 闪烁驱动
# ============================================================
def start_instances(instances):
    """闪烁驱动主循环：

    1. 启动时最小化微信
    2. 有发送任务 → 先处理所有发送（send_message 内部已预捕获未读消息）
    3. 再检测闪烁 → 收消息 → 分发
    4. 每次操作后切到文件传输助手再最小化

    关键：发送在收消息之前处理，避免 ChatWith 清掉其他聊天的闪烁状态。
    """
    if not instances:
        return

    msg_queue = queue.Queue()
    orig_senders = {}

    for name, inst in instances:
        if not isinstance(inst, BaseInstance):
            continue
        orig_senders[name] = inst.send_message

        def make_enqueue(n):
            def enqueue(message):
                msg_queue.put((n, message))
            return enqueue
        inst.send_message = make_enqueue(name)

        threading.Thread(target=inst.start, daemon=True).start()
        info(f"实例 {name} ({type(inst).__name__}) 已启动")

    # 拦截 wechat_instance.send_message（所有消息发往微信的唯一出口）
    _orig_wx_send = wechat_instance.send_message
    def _intercepted_wx_send(message, group, at=None, at_all=False):
        global _on_message_interceptor, _current_processing_instance
        # 确定发送实例名：_current_processing_instance → _web_processing_instances → "wechat"
        src = _current_processing_instance or _web_processing_instances.get(group) or "wechat"
        # 拦截器始终触发，去重逻辑在 _web_reply_interceptor 内部处理
        if _on_message_interceptor:
            try:
                _on_message_interceptor(src, message)
            except Exception as e:
                error(f"微信发送拦截器错误: {e}")
        # 统一补充上下文：从 _captured_reply_contexts 读取（拦截器在 handle_message 期间已捕获）
        ctx = _captured_reply_contexts.pop((src, group), None)
        if ctx:
            prefix = f"【网页提问】{ctx['sender']}: {ctx['content']}\n"
            if isinstance(message, dict):
                message = {**message, "content": prefix + message.get("content", "")}
            elif isinstance(message, str):
                message = prefix + message
        return _orig_wx_send(message, group, at=at, at_all=at_all)
    wechat_instance.send_message = _intercepted_wx_send

    # 同时拦截 send_messages（批量发送，KoriChat 的 $ 分割回复走此路径）
    _orig_wx_sends = wechat_instance.send_messages
    def _intercepted_wx_sends(messages, group, at=None, at_all=False):
        global _on_message_interceptor, _current_processing_instance
        src = _current_processing_instance or _web_processing_instances.get(group) or "wechat"
        if _on_message_interceptor:
            for msg in messages:
                try:
                    _on_message_interceptor(src, msg)
                except Exception as e:
                    error(f"微信发送拦截器错误: {e}")
        ctx = _captured_reply_contexts.pop((src, group), None)
        if ctx:
            prefix = f"【网页提问】{ctx['sender']}: {ctx['content']}\n"
            messages = [prefix + m for m in messages]
        return _orig_wx_sends(messages, group, at=at, at_all=at_all)
    wechat_instance.send_messages = _intercepted_wx_sends

    # MOCK_SEND 模式下不操作微信，实例后台任务继续运行
    if MOCK_SEND:
        info("MOCK_SEND 已开启，跳过微信 GUI 操作，实例后台任务运行中...")
        while True:
            if not web_msg_queue.empty():
                process_web_messages(instances)
            time.sleep(1)

    # 启动时先切换到文件传输助手，然后最小化
    wx = wechat_instance.get_wechat()
    if wx:
        try:
            with _send_op_lock:
                wx.ChatWith('文件传输助手')
            info("已切换到文件传输助手")
        except Exception as e:
            warning(f"切换到文件传输助手失败：{e}")
    human_action_delay()
    minimize_wechat()

    global _is_sending, _last_send_time, _sending_count
    poll_base = 2.0        # 轮询基础间隔（秒）— 从 0.3s 提高到 2s
    poll_jitter = 1.5      # 轮询抖动幅度
    last_poll_time = 0
    last_flash_time = 0
    wx_is_minimized = True
    idle_cycle_count = 0   # 连续空闲轮询次数

    info(f"主循环启动（轮询间隔 {poll_base}s 对数正态分布）")

    try:
        while True:
            now = time.time()

            # ── 第零步：处理 Web 聊天消息（与微信收发无关，维护时间也处理）──
            if not web_msg_queue.empty():
                process_web_messages(instances)

            # ── 维护时间 ──
            if is_maintenance_time():
                if not wx_is_minimized:
                    minimize_wechat()
                    wx_is_minimized = True
                time.sleep(random.uniform(30, 120))  # 维护期间大幅降低检查频率
                continue

            # 用 Win32 API 检测窗口实际状态（不依赖本地变量，避免后台定时器恢复窗口后状态漂移）
            _real_hwnd = win32gui.FindWindow('WeChatMainWndForPC', None)
            wx_is_minimized = bool(win32gui.IsIconic(_real_hwnd)) if _real_hwnd else True

            # ── 第一步：处理发送队列（在收消息之前）──
            # send_message 内部会在 ChatWith 之前预捕获目标聊天的未读消息，
            # 所以先发再收不会丢消息。
            if not msg_queue.empty():
                if wx_is_minimized:
                    human_delay(300, 1200)
                    restore_wechat()
                    wx_is_minimized = False
                # 更新时间戳，确保 15 秒内不会最小化窗口
                # 计数器由各个实例（如 KoriChat）自己管理
                with _send_lock:
                    _last_send_time = time.time()
                process_all_pending_messages(msg_queue, orig_senders, instances)
                last_flash_time = time.time()
                idle_cycle_count = 0
                # 队列处理完成后，等待一小段时间确保所有后台发送完成
                human_delay(500, 1000)
                # 不立即设置 wx_is_minimized = True，因为 KoriChat 等实例可能还在发送消息
                # 让后续的闪烁检测逻辑来处理窗口最小化
                # 不 continue——继续往下做闪烁检测，同一轮完成收发

            # ── 第二步：闪烁检测 → 收消息 ──
            # 此时所有 ChatWith 都已完成，闪烁状态干净
            current_interval = random_poll_interval(poll_base, poll_jitter)
            if now - last_poll_time < current_interval:
                # 还没到轮询间隔，但窗口已打开 → 空闲超时再最小化
                if not wx_is_minimized:
                    idle = now - last_flash_time
                    # 检查是否有消息正在发送（通过计数器和时间戳判断）
                    recent_send = (now - _last_send_time) < 15  # 15 秒内有发送
                    
                    # 只有在没有发送、最近也没有发送、且队列为空时才考虑最小化
                    if _sending_count <= 0 and not recent_send and msg_queue.empty():
                        idle_timeout = random.uniform(5, 10)
                        if idle > idle_timeout:
                            wx = wechat_instance.get_wechat()
                            if wx:
                                try:
                                    with _send_op_lock:
                                        wx.ChatWith('文件传输助手')
                                except Exception:
                                    pass
                            human_action_delay()
                            minimize_wechat()
                            wx_is_minimized = True
                time.sleep(0.1)
                continue
            last_poll_time = now

            # 检查是否允许检测新消息
            if not ENABLE_FLASH_DETECT:
                if idle_cycle_count % 10 == 0:  # 每 10 次循环打印一次日志
                    # debug("[闪烁检测] 跳过：检测功能已禁用")
                    pass
                time.sleep(0.1)
                continue
            
            is_flashing = detect_flash()
            idle_cycle_count += 1

            if is_flashing:
                last_flash_time = now
                idle_cycle_count = 0
                
                # 检查是否允许接收消息
                if not ENABLE_RECEIVE:
                    debug("[闪烁检测] 检测到新消息，但接收功能已禁用，不恢复窗口")
                else:
                    # 检查是否在维护时间内
                    if is_maintenance_time():
                        debug("[闪烁检测] 检测到新消息，但当前是维护时间，不恢复窗口")
                    else:
                        info("检测到微信闪烁，开始收消息...")
                        
                        if wx_is_minimized:
                            human_delay(200, 800)
                            restore_wechat()
                            wx_is_minimized = False
                        
                        process_receive_messages(instances)

                # 切到文件传输助手 → 最小化
                wx = wechat_instance.get_wechat()
                if wx:
                    try:
                        with _send_op_lock:
                            wx.ChatWith('文件传输助手')
                    except Exception:
                        pass
                human_action_delay()
                minimize_wechat()
                wx_is_minimized = True

                # 收到消息后，模拟人类"看一眼消息后思考"
                if random.random() < 0.3:
                    random_human_pause()

            else:
                # 无闪烁：窗口没最小化 → 最小化
                # 注意：后台定时器（如 KoriChat 的消息队列）可能在主循环之外恢复窗口，
                # 所以每次迭代都用 IsIconic 检查真实状态，不依赖 wx_is_minimized 变量。
                if not wx_is_minimized:
                    idle = now - last_flash_time
                    # 空闲超过 5s 或没有待发消息时立即最小化（之前是 15-30s，太慢）
                    if idle > 5 and msg_queue.empty():
                        wx = wechat_instance.get_wechat()
                        if wx:
                            try:
                                with _send_op_lock:
                                    wx.ChatWith('文件传输助手')
                            except Exception:
                                pass
                        human_action_delay()
                        minimize_wechat()
                        wx_is_minimized = True

                # 连续空闲时，偶尔做一次长暂停（模拟人类去做别的事）
                if idle_cycle_count > 0 and idle_cycle_count % random.randint(8, 20) == 0:
                    pause = random.uniform(5, 15)
                    info(f"模拟人类空闲暂停 {pause:.0f}s...")
                    if not wx_is_minimized:
                        wx = wechat_instance.get_wechat()
                        if wx:
                            try:
                                with _send_op_lock:
                                    wx.ChatWith('文件传输助手')
                            except Exception:
                                pass
                        human_action_delay()
                        minimize_wechat()
                        wx_is_minimized = True
                    time.sleep(pause)

    except KeyboardInterrupt:
        info("收到中断，退出")


# ============================================================
# 入口
# ============================================================
def main():
    # 初始化日志
    setup_logger(log_dir="logs", level=logging.DEBUG)
    info("=" * 50)
    info("cs-Solidarity 启动")
    info("=" * 50)

    global _instances
    master_cfg = load_master_config('config.json')
    init_wechat()
    instances = create_instances(master_cfg)
    _instances = instances
    if not instances:
        warning("没有可用实例，退出")
        return

    # 启动聊天 TCP 服务器，让 Agent handler 可以通过 TCP 发送聊天消息
    chat_server = start_chat_server()
    if chat_server:
        chat_server.set_context(instances, process_web_messages, web_msg_queue)

    try:
        start_instances(instances)
    except KeyboardInterrupt:
        info("退出")


if __name__ == "__main__":
    main()
