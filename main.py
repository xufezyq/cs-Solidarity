import json
import threading
import time
from pathlib import Path
import json
import threading
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
    """启动实例线程并返回线程列表。"""
    threads = []
    for name, inst in instances:
        print(f"启动 {name} -> Steam ID: {inst.steam_id}")
        t = threading.Thread(target=inst.start, kwargs={'check_interval': check_interval}, daemon=True)
        t.start()
        threads.append((name, t))

    return threads


def main():
    config_file = 'config.json'

    init_wechat()
    master_cfg = load_master_config(config_file)
    instances = create_instances(master_cfg)
    if not instances:
        return
    
    check_interval = master_cfg.get('check_interval', 60) if master_cfg else 60
    start_instances(instances, check_interval)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n收到中断，主进程退出，守护线程将随之终止")


if __name__ == "__main__":
    main()