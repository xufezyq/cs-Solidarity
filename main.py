import json
import threading
import queue
import time
import sys
from datetime import datetime, time as dt_time
from pathlib import Path
from core import init_wechat
from core import wechat_instance
from core import get_instance_from_item
from core import BaseInstance
from core import WeChatFlashMonitor

# 强制 UTF-8 输出，避免 Windows GBK 编码遇到 emoji 崩溃
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# 调试模式标志
DEBUG_MODE = False

# 闪存事件：闪存监听线程设置，主线程等待
flash_event = threading.Event()

# 闪存监听器
flash_monitor = None

def is_maintenance_time():
    """检查当前时间是否在维护时间（00:15-08:00）"""
    # 如果是调试模式，直接返回 False（不进入维护时间）
    if DEBUG_MODE:
        return False
    
    now = datetime.now().time()
    start_time = dt_time(0, 15)
    end_time = dt_time(8, 0)
    return start_time <= now < end_time


# 暴露给实例模块使用的维护时间检查函数
def check_maintenance():
    """供外部模块调用的维护时间检查"""
    return is_maintenance_time()


# 注册到 core 包，方便实例导入
import core
core.check_maintenance = check_maintenance


def process_send_message(name, message, orig_senders):
    """处理发送消息的逻辑"""
    print(f"[DEBUG] [{time.strftime('%H:%M:%S')}] 准备发送消息：name={name}, message={message}")
    try:
        sender = orig_senders.get(name)
        if sender:
            print(f"[DEBUG] [{time.strftime('%H:%M:%S')}] 调用发送方法：{name}")
            sender(message)
            print(f"[DEBUG] [{time.strftime('%H:%M:%S')}] 消息发送成功")
        else:
            print(f"未知来源的消息：{name}，已跳过")
    except Exception as e:
        print(f"发送来自 {name} 的消息失败：{e}")


def route_message_to_instances(msg_content, instances):
    """
    根据消息内容路由到目标实例
    
    规则：
    1. 如果消息包含某个实例的 trigger_prefix（如 /claw），只分发给该实例
    2. 否则分发给所有没有 trigger_prefix 的实例
    
    Args:
        msg_content: 消息内容
        instances: 实例列表 [(name, instance), ...]
        
    Returns:
        目标实例列表 [(name, instance), ...]
    """
    # 检查是否包含某个实例的 trigger_prefix
    for name, inst in instances:
        if hasattr(inst, 'trigger_prefix') and inst.trigger_prefix in msg_content:
            # 消息包含触发词，只分发给这个实例
            return [(name, inst)]
    
    # 没有匹配到触发词，分发给所有没有 trigger_prefix 的实例
    return [(name, inst) for name, inst in instances if not hasattr(inst, 'trigger_prefix')]


def process_receive_messages(instances):
    """处理接收和分发新消息的逻辑"""
    print(f"[DEBUG] [{time.strftime('%H:%M:%S')}] 开始检查新消息...")
    try:
        new_msgs = wechat_instance.get_new_messages()
        print(f"[DEBUG] get_new_messages() 返回：{new_msgs}")
        
        if new_msgs:
            print(f"[DEBUG] 收到来自 {len(new_msgs)} 个聊天对象的消息:")
            for chat_name, msg_list in new_msgs.items():
                print(f"[DEBUG]   - {chat_name}: {len(msg_list)} 条消息，msg_list 类型：{type(msg_list)}")
                for i, msg in enumerate(msg_list):
                    print(f"[DEBUG]     消息 {i+1}: {msg}, 类型：{type(msg)}")
                    
            for chat_name, msg_list in new_msgs.items():
                for msg in msg_list:
                    # 提取消息内容
                    msg_content = ""
                    if hasattr(msg, 'content'):
                        msg_content = msg.content
                    elif isinstance(msg, (list, tuple)) and len(msg) > 1:
                        msg_content = msg[1]
                    else:
                        msg_content = str(msg)
                    
                    # 使用路由函数分发消息
                    target_instances = route_message_to_instances(msg_content, instances)
                    
                    print(f"[DEBUG] [消息路由] '{msg_content[:20]}...' -> {[name for name, _ in target_instances]}")
                    
                    # 分发给目标实例
                    for name, inst in target_instances:
                        try:
                            print(f"[DEBUG] 调用 {name}({type(inst).__name__}) 的 handle_message 方法")
                            print(f"[DEBUG]   参数：chat_name={chat_name}, msg={msg}, msg 类型：{type(msg)}")
                            inst.handle_message(chat_name, msg)
                            print(f"[DEBUG] {name} handle_message 执行完成")
                        except Exception as e:
                            print(f"[ERROR] 实例 {name} 处理消息失败：{e}")
        else:
            print(f"[DEBUG] 没有新消息")
    except Exception as e:
        print(f"[ERROR] 获取/分发消息时出错：{e}")
        import traceback
        traceback.print_exc()


def load_master_config(config_file):
    """加载主配置，读取失败或格式不对时返回空字典。"""
    global DEBUG_MODE
    
    if not Path(config_file).exists():
        return {}

    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            master_cfg = json.load(f)
    except Exception as e:
        return {}

    if not isinstance(master_cfg, dict) or 'instances' not in master_cfg:
        return {}

    if not master_cfg.get('instances'):
        return {}
    
    # 读取调试模式配置
    DEBUG_MODE = master_cfg.get('debug_mode', False)
    if DEBUG_MODE:
        print(f"[DEBUG] 调试模式已启用，维护时间检查将被忽略")

    return master_cfg


def create_instances(master_cfg):
    """根据主配置创建实例列表，失败的项只打印错误并跳过。"""
    if not master_cfg:
        return []
    
    # 将主配置的 debug_mode 传递到所有实例配置中
    debug_mode = master_cfg.get('debug_mode', False)

    instances = []
    for idx, item in enumerate(master_cfg.get('instances', []), 1):
        try:
            # 通过实例工厂解析并创建实例
            inst = get_instance_from_item(item)
            instances.append((f"instance_{idx}", inst))
        except Exception as e:
            print(f"创建实例 {idx} 失败：{e}")
            continue

    return instances


def on_wechat_flash():
    """微信闪存回调：由闪存监听线程调用，通知主线程有新消息"""
    print(f"[Flash] 检测到微信闪存，设置新消息事件")
    flash_event.set()


def start_instances(instances):
    """使用队列模式 + 闪存监听驱动消息检查。"""
    global flash_monitor

    if not instances:
        return

    msg_queue = queue.Queue()
    threads = []
    orig_senders = {}

    for name, inst in instances:
        if not isinstance(inst, BaseInstance):
            print(f"实例 {name} 不是 BaseInstance 子类，已跳过：{type(inst).__name__}")
            continue
        print(f"准备实例 {name} -> 类型: {type(inst).__name__}")

        orig_senders[name] = inst.send_message

        def make_enqueue(n):
            def enqueue(message):
                print(f"[DEBUG] [enqueue] 消息入队：n={n}, message={message}")
                msg_queue.put((n, message))
            return enqueue
        inst.send_message = make_enqueue(name)

        t = threading.Thread(target=inst.start, daemon=True)
        t.start()
        threads.append((name, t))

    print("已启动所有实例的检测线程。")

    # ========== 启动闪存监听 ==========
    flash_monitor = WeChatFlashMonitor(
        on_flash_callback=on_wechat_flash,
        cooldown=3.0  # 3 秒内不重复触发
    )

    if flash_monitor.start():
        print("[Main] 闪存监听启动成功，等待微信新消息闪存事件...")
    else:
        print("[Main] 闪存监听启动失败，降级为每 30 秒轮询检测")

    # 发送启动消息后最小化微信
    time.sleep(3)
    wechat_instance.minimize_window()
    print("[Main] 微信窗口已最小化")

    # ========== 主循环 ==========
    # 首次启动：主动检查一次消息（初始化状态）
    try:
        if not is_maintenance_time():
            print("[Main] 首次检查新消息...")
            wechat_instance.restore_window()
            time.sleep(0.5)
            process_receive_messages(instances)
            wechat_instance.minimize_window()
    except Exception as e:
        print(f"[Main] 首次消息检查出错: {e}")

    # 降级轮询间隔（闪存监听失败时使用）
    fallback_interval = 30
    last_fallback_check = time.time()

    try:
        while True:
            # ---- 处理发送队列 ----
            try:
                name, message = msg_queue.get(timeout=1)

                if is_maintenance_time():
                    print(f"[INFO] 维护时段，跳过发送消息")
                    msg_queue.task_done()
                    continue

                # 发送前恢复窗口
                was_minimized = wechat_instance.is_window_minimized()
                if was_minimized:
                    wechat_instance.restore_window()
                    time.sleep(0.5)

                process_send_message(name, message, orig_senders)

                # 发送完最小化
                if was_minimized:
                    time.sleep(0.3)
                    wechat_instance.minimize_window()

                msg_queue.task_done()
                continue  # 发送了消息，直接进入下一轮

            except queue.Empty:
                pass

            # ---- 检查新消息（闪存驱动 或 降级轮询）----
            should_check = False

            if flash_event.is_set():
                # 闪存触发
                should_check = True
                flash_event.clear()
                print("[Main] 闪存事件触发，检查新消息...")
            elif not flash_monitor.is_running():
                # 闪存监听未运行，降级轮询
                current_time = time.time()
                if current_time - last_fallback_check >= fallback_interval:
                    should_check = True
                    last_fallback_check = current_time
                    print("[Main] 降级轮询触发，检查新消息...")

            if should_check:
                if is_maintenance_time():
                    print("[INFO] 维护时段，跳过消息检查")
                    continue

                # 恢复窗口 → 检查 → 最小化
                was_minimized = wechat_instance.is_window_minimized()
                if was_minimized:
                    wechat_instance.restore_window()
                    time.sleep(0.5)

                process_receive_messages(instances)

                if was_minimized:
                    time.sleep(0.3)
                    wechat_instance.minimize_window()

                last_fallback_check = time.time()

    except KeyboardInterrupt:
        print("\n收到中断，正在清理...")
        if flash_monitor:
            flash_monitor.stop()
        print("主进程退出，守护线程将随之终止")

    return


def main():
    config_file = 'config.json'

    init_wechat()
    
    master_cfg = load_master_config(config_file)
    instances = create_instances(master_cfg)
    if not instances:
        return

    try:
        start_instances(instances)
    except KeyboardInterrupt:
        print("\n收到中断，主进程退出")


if __name__ == "__main__":
    main()