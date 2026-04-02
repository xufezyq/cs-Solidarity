import json
import threading
import queue
import time
import sys
import random
from datetime import datetime, time as dt_time
from pathlib import Path
from core import init_wechat, wechat_instance, get_instance_from_item, BaseInstance
from utils.human_sim import human_delay, human_action_delay, random_poll_interval
from utils.logger import setup_logger, info, debug, error, warning
import win32gui

import logging

# 强制 UTF-8 输出
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

DEBUG_MODE = False

# ============================================================
# 维护时间
# ============================================================
def is_maintenance_time():
    if DEBUG_MODE:
        return False
    now = datetime.now().time()
    return dt_time(0, 15) <= now < dt_time(8, 0)

def check_maintenance():
    return is_maintenance_time()

import core
core.check_maintenance = check_maintenance


# ============================================================
# 微信窗口控制
# ============================================================
def _get_wechat_hwnd():
    return win32gui.FindWindow('WeChatMainWndForPC', None)

def minimize_wechat():
    """最小化微信窗口"""
    try:
        hwnd = _get_wechat_hwnd()
        if hwnd:
            win32gui.ShowWindow(hwnd, 2)  # SW_MINIMIZE
            debug("[窗口] 微信已最小化")
    except Exception as e:
        error(f"[窗口] 最小化失败: {e}")

def restore_wechat():
    """恢复微信窗口并置前"""
    try:
        hwnd = _get_wechat_hwnd()
        if hwnd:
            win32gui.ShowWindow(hwnd, 9)   # SW_RESTORE
            win32gui.SetForegroundWindow(hwnd)
            human_delay(300, 600)
            debug("[窗口] 微信已恢复")
    except Exception as e:
        error(f"[窗口] 恢复失败: {e}")


# ============================================================
# 消息处理
# ============================================================
def process_send_message(name, message, orig_senders, instances=None):
    """发送消息并处理发送期间捕获的新消息"""
    target = message.get("target", name) if isinstance(message, dict) else name
    debug(f"发送: name={name}, target={target}")
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
            human_delay(500, 1500)  # 消息间随机延迟
        except queue.Empty:
            break

    if sent_any:
        # 切回文件传输助手 → 最小化
        wx = wechat_instance.get_wechat()
        if wx:
            try:
                human_delay(300, 600)
                wx.ChatWith('文件传输助手')
                debug("[窗口] 已切换到文件传输助手")
            except Exception as e:
                debug(f"[窗口] 切换失败: {e}")
        human_action_delay()
        minimize_wechat()

    return sent_any


def route_message_to_instances(msg_content, instances):
    for name, inst in instances:
        if hasattr(inst, 'trigger_prefix') and inst.trigger_prefix in msg_content:
            return [(name, inst)]
    return [(name, inst) for name, inst in instances if not hasattr(inst, 'trigger_prefix')]


def process_receive_messages(instances):
    """收消息 + 分发，返回收到的消息数量"""
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
                            error(f"{name} 处理失败: {e}")
            info(f"共处理 {total_count} 条消息")
        else:
            debug("无新消息")
    except Exception as e:
        error(f"收消息失败: {e}")
        import traceback
        traceback.print_exc()
    return total_count


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
    global DEBUG_MODE
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
    DEBUG_MODE = cfg.get('debug_mode', False)
    return cfg

def create_instances(master_cfg):
    if not master_cfg:
        return []
    instances = []
    for idx, item in enumerate(master_cfg.get('instances', []), 1):
        try:
            instances.append((f"instance_{idx}", get_instance_from_item(item)))
            info(f"实例 {idx} 创建成功 ({item.get('type', 'unknown')})")
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

    # 启动时最小化
    human_action_delay()
    minimize_wechat()

    poll_base = 0.3        # 轮询基础间隔
    poll_jitter = 0.15     # 轮询抖动（±秒）
    last_poll_time = 0
    last_flash_time = 0
    wx_is_minimized = True

    info(f"主循环启动（轮询间隔 {poll_base}±{poll_jitter}s，随机抖动）")

    try:
        while True:
            now = time.time()

            # ── 维护时间 ──
            if is_maintenance_time():
                if not wx_is_minimized:
                    minimize_wechat()
                    wx_is_minimized = True
                time.sleep(5)
                continue

            # ── 第一步：处理发送队列（在收消息之前）──
            # send_message 内部会在 ChatWith 之前预捕获目标聊天的未读消息，
            # 所以先发再收不会丢消息。
            if not msg_queue.empty():
                if wx_is_minimized:
                    human_delay(200, 800)
                    restore_wechat()
                    wx_is_minimized = False
                process_all_pending_messages(msg_queue, orig_senders, instances)
                last_flash_time = time.time()
                # 不 continue——继续往下做闪烁检测，同一轮完成收发

            # ── 第二步：闪烁检测 → 收消息 ──
            # 此时所有 ChatWith 都已完成，闪烁状态干净
            current_interval = random_poll_interval(poll_base, poll_jitter)
            if now - last_poll_time < current_interval:
                # 还没到轮询间隔，但窗口已打开 → 空闲超时再最小化
                if not wx_is_minimized:
                    idle = now - last_flash_time
                    idle_timeout = random.uniform(10, 20)
                    if idle > idle_timeout and msg_queue.empty():
                        wx = wechat_instance.get_wechat()
                        if wx:
                            try:
                                wx.ChatWith('文件传输助手')
                            except Exception:
                                pass
                        human_action_delay()
                        minimize_wechat()
                        wx_is_minimized = True
                time.sleep(0.05)
                continue
            last_poll_time = now

            is_flashing = detect_flash()

            if is_flashing:
                last_flash_time = now
                info("检测到微信闪烁，开始收消息...")

                if wx_is_minimized:
                    human_delay(100, 500)
                    restore_wechat()
                    wx_is_minimized = False

                process_receive_messages(instances)

                # 切到文件传输助手 → 最小化
                wx = wechat_instance.get_wechat()
                if wx:
                    try:
                        wx.ChatWith('文件传输助手')
                    except Exception:
                        pass
                human_action_delay()
                minimize_wechat()
                wx_is_minimized = True

            else:
                # 无闪烁：窗口没最小化且空闲久了，最小化
                if not wx_is_minimized:
                    idle = now - last_flash_time
                    idle_timeout = random.uniform(10, 20)
                    if idle > idle_timeout and msg_queue.empty():
                        wx = wechat_instance.get_wechat()
                        if wx:
                            try:
                                wx.ChatWith('文件传输助手')
                            except Exception:
                                pass
                        human_action_delay()
                        minimize_wechat()
                        wx_is_minimized = True

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

    init_wechat()

    master_cfg = load_master_config('config.json')
    instances = create_instances(master_cfg)
    if not instances:
        warning("没有可用实例，退出")
        return

    try:
        start_instances(instances)
    except KeyboardInterrupt:
        info("退出")


if __name__ == "__main__":
    main()
