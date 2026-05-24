"""
OpenClaw 调用示例 — 通过 cs-Solidarity Bot API 发送微信消息/文件

前提：Bot 进程已运行，API 监听在 http://127.0.0.1:18800
"""

import requests

API = "http://127.0.0.1:18800"


def health():
    """检查 Bot 是否就绪"""
    r = requests.get(f"{API}/health")
    print(r.json())


def send_message(target: str, content: str, at: list = None, at_all: bool = False, force: bool = False):
    """发送文本消息

    Args:
        target: 目标聊天名称
        content: 消息内容
        at: 要@的群成员列表，如 ["张三", "李四"]
        at_all: 是否@所有人
        force: 是否强制发送（绕过维护时间检查）
    """
    payload = {"target": target, "content": content, "force": force}
    if at:
        payload["at"] = at
    if at_all:
        payload["at_all"] = at_all
    r = requests.post(f"{API}/send/message", json=payload)
    print(r.json())


def send_file(target: str, filepath: str, force: bool = False):
    """发送文件/图片

    Args:
        target: 目标聊天名称
        filepath: 文件路径
        force: 是否强制发送（绕过维护时间检查）
    """
    import os
    filename = os.path.basename(filepath)
    with open(filepath, "rb") as f:
        r = requests.post(
            f"{API}/send/file",
            data={"target": target, "force": str(force).lower()},
            files={"file": (filename, f)}
        )
    print(r.json())


if __name__ == "__main__":
    # 1. 健康检查
    health()

    # 2. 发送文本到文件传输助手
    send_message("文件传输助手", "Hello from OpenClaw!")

    # 3. 强制发送文本（绕过维护时间）
    send_message("文件传输助手", "Force message!", force=True)

    # 4. 发送消息并@指定群成员
    # send_message("群名", "大家看看这个", at=["张三", "李四"])

    # 5. 发送消息并@所有人
    # send_message("群名", "重要通知！", at_all=True)

    # 6. 发送文件（替换为实际路径）
    # send_file("文件传输助手", r"D:\path\to\image.png")

    # 7. 强制发送文件（绕过维护时间）
    # send_file("文件传输助手", r"D:\path\to\image.png", force=True)
