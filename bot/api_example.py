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


def send_message(target: str, content: str):
    """发送文本消息"""
    r = requests.post(f"{API}/send/message", json={
        "target": target,
        "content": content,
    })
    print(r.json())


def send_file(target: str, filepath: str):
    """发送文件/图片"""
    import os
    filename = os.path.basename(filepath)
    with open(filepath, "rb") as f:
        r = requests.post(f"{API}/send/file", data={"target": target}, files={"file": (filename, f)})
    print(r.json())


if __name__ == "__main__":
    # 1. 健康检查
    health()

    # 2. 发送文本到文件传输助手
    send_message("文件传输助手", "Hello from OpenClaw!")

    # 3. 发送文件（替换为实际路径）
    # send_file("文件传输助手", r"D:\path\to\image.png")
