import json
import threading
import queue
from pathlib import Path
from core import init_wechat
from core import wechat_instance
from core import get_instance_from_item
from core import BaseInstance


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
            # 通过实例工厂解析并创建实例
            inst = get_instance_from_item(item)
            instances.append((f"instance_{idx}", inst))
        except Exception as e:
            print(f"创建实例 {idx} 失败: {e}")
            continue

    return instances


def start_instances(instances):
    """使用队列模式：后台线程负责检测并将消息入队，主线程负责出队并调用原始发送方法。"""
    if not instances:
        return

    msg_queue = queue.Queue()
    threads = []
    orig_senders = {}

    for name, inst in instances:
        # 校验类型，确保是 BaseInstance 子类
        if not isinstance(inst, BaseInstance):
            print(f"实例 {name} 不是 BaseInstance 子类，已跳过：{type(inst).__name__}")
            continue
        print(f"准备实例 {name} -> 类型: {type(inst).__name__}")

        # 保存原始发送方法，以便在主线程中调用
        orig_senders[name] = inst.send_message

        # 替换为入队函数（实例中调用 send_message 将只把消息放入队列）
        def make_enqueue(n):
            def enqueue(message):
                msg_queue.put((n, message))
            return enqueue
        inst.send_message = make_enqueue(name)

        # 启动实例的调度循环于后台线程（守护线程）
        t = threading.Thread(target=inst.start, daemon=True)
        t.start()
        threads.append((name, t))

    print("已启动所有实例的检测线程，主线程将消费消息队列并在主线程执行发送操作。")

    try:
        import time
        last_check_time = time.time()
        check_interval = 60  # 每60秒检查一次新消息
        
        while True:
            try:
                # 尝试从队列获取消息，超时 1 秒
                name, message = msg_queue.get(timeout=1)
                
                # 处理发送消息的任务
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
            
            except queue.Empty:
                # 队列空闲时，检查并分发新消息
                current_time = time.time()
                if current_time - last_check_time >= check_interval:
                    print(f"[DEBUG] 开始检查新消息 (每 {check_interval} 秒一次)")
                    try:
                        # 获取所有新消息（兼容 wxauto 和 pywechat）
                        print(f"[DEBUG] 调用 wechat_instance.get_new_messages()")
                        new_msgs = wechat_instance.get_new_messages()
                        print(f"[DEBUG] get_new_messages() 返回: {new_msgs}")
                        print(f"[DEBUG] 新消息数量: {len(new_msgs) if isinstance(new_msgs, dict) else 0}")
                        if new_msgs:
                            print(f"[DEBUG] 分发 {len(new_msgs)} 个聊天对象的消息给实例")
                            for chat_name, msg_list in new_msgs.items():
                                print(f"[DEBUG] 处理来自 {chat_name} 的 {len(msg_list)} 条消息")
                                for msg in msg_list:
                                    print(f"[DEBUG] 消息内容: {msg}")
                                    # 分发给所有实例
                                    print(f"[DEBUG] 分发给 {len(instances)} 个实例")
                                    for name, inst in instances:
                                        try:
                                            print(f"[DEBUG] 调用 {name} 的 handle_message 方法")
                                            inst.handle_message(chat_name, msg)
                                        except Exception as e:
                                            print(f"[DEBUG] 实例 {name} 处理消息失败: {e}")
                    except Exception as e:
                        print(f"[DEBUG] 获取/分发消息时出错: {e}")
                    finally:
                        last_check_time = current_time
                else:
                    # 等待到下一次检查
                    time.sleep(1)
                
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

    try:
        start_instances(instances)
    except KeyboardInterrupt:
        print("\n收到中断，主进程退出")


if __name__ == "__main__":
    main()