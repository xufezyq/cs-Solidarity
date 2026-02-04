import json
import threading
import queue
import time
from pathlib import Path
from steam import SteamAuto
from core import init_wechat


def load_master_config(config_file):
    """加载主配置，读取失败或格式不对时返回空字典。"""
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

    return master_cfg


def create_instances(master_cfg):
    """根据主配置创建实例列表，失败的项只打印错误并跳过。"""
    if not master_cfg:
        return []

    instances = []
    for idx, item in enumerate(master_cfg.get('instances', []), 1):
        try:
            inst = SteamAuto.create_from_config(item)
            instances.append((f"instance_{idx}", inst))
        except Exception as e:
            print(f"创建实例 {idx} 失败: {e}")
            continue

    return instances


def start_instances(instances, check_interval):
    """使用队列模式：后台线程负责检测并将消息入队，主线程负责出队并调用原始发送方法。"""
    if not instances:
        return

    msg_queue = queue.Queue()
    threads = []
    orig_senders = {}

    for name, inst in instances:
        print(f"准备实例 {name} -> Steam ID: {inst.steam_id}")
        # 保存原始发送方法，以便在主线程中调用
        orig_senders[name] = inst.send_message

        # 替换为入队函数（实例中调用 send_message 将只把消息放入队列）
        def make_enqueue(n):
            def enqueue(message):
                msg_queue.put((n, message))
            return enqueue

        inst.send_message = make_enqueue(name)

        # 启动实例的调度循环于后台线程（守护线程）
        t = threading.Thread(target=inst.start, kwargs={'check_interval': check_interval}, daemon=True)
        t.start()
        threads.append((name, t))

    print("已启动所有实例的检测线程；主线程将消费消息队列并在主线程执行发送操作。按 Ctrl+C 退出。")

    try:
        while True:
            name, message = msg_queue.get()
            try:
                sender = orig_senders.get(name)
                if sender:
                    sender(message)
                else:
                    print(f"未知来源的消息：{name}，已跳过")
            except Exception as e:
                print(f"发送来自 {name} 的消息失败: {e}")
            finally:
                msg_queue.task_done()
    except KeyboardInterrupt:
        print("\n收到中断，主进程退出，守护线程将随之终止")

    return


def main():
    config_file = 'config.json'

    init_wechat()
    master_cfg = load_master_config(config_file)
    instances = create_instances(master_cfg)
    if not instances:
        return
    
    check_interval = master_cfg.get('check_interval', 60) if master_cfg else 60

    try:
        start_instances(instances, check_interval)
    except KeyboardInterrupt:
        print("\n收到中断，主进程退出")


if __name__ == "__main__":
    main()