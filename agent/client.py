"""
cs-Solidarity Agent — WebSocket 客户端

主动连接到 Web Server，接收请求并转发给 handler 处理，同时通过 watcher 推送日志。

用法：
    python -m agent.client --server ws://B_IP:11029/ws/agent --token xxx --root D:\code\cs-Solidarity
"""

import asyncio
import argparse
import json
import logging
import os
import subprocess
import sys
import signal
from datetime import datetime
from pathlib import Path

import websockets

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.protocol import make_response, make_push, make_ping, make_pong, parse_message
from agent.handler import AgentHandler
from agent.watcher import LogWatcher

# ── 日志配置 ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("agent")


class AgentClient:
    """Agent WebSocket 客户端"""

    def __init__(self, server_url: str, token: str, root_dir: str):
        self.server_url = server_url
        self.token = token
        self.root_dir = root_dir
        self.handler = AgentHandler(root_dir)
        self.watcher = LogWatcher(root_dir, push_callback=self._on_push)
        self.ws = None
        self._running = False
        self._push_queue: asyncio.Queue = asyncio.Queue()

    async def _on_push(self, event: str, data: dict):
        """Watcher 回调：将推送消息放入队列"""
        await self._push_queue.put(make_push(event, data))

    def _git_pull(self):
        """执行 git pull，暂存本地修改后拉取，再恢复暂存"""
        try:
            # 检查是否是 git 仓库
            git_dir = Path(self.root_dir) / ".git"
            if not git_dir.is_dir():
                log.debug("非 git 仓库，跳过拉取")
                return

            # git stash push -u: 暂存本地修改（含未跟踪文件）
            stash_result = subprocess.run(
                ["git", "stash", "push", "-u"],
                cwd=self.root_dir,
                capture_output=True,
                text=True,
            )
            # 检查是否真的有修改被暂存（返回码为 0 但可能是因为无修改）
            has_stash = stash_result.returncode == 0 and "No local changes to save" not in stash_result.stderr
            if has_stash:
                log.info("本地修改已暂存")
            else:
                log.debug("无本地修改需要暂存")

            # git pull --rebase
            pull_result = subprocess.run(
                ["git", "pull", "--rebase"],
                cwd=self.root_dir,
                capture_output=True,
                text=True,
            )
            if pull_result.returncode == 0:
                log.info("✅ Git 拉取成功")
            else:
                log.warning(f"⚠️ Git 拉取失败: {pull_result.stderr.strip()}")
                # 尝试普通的 git pull（非 rebase）
                log.info("尝试普通 git pull...")
                pull_result2 = subprocess.run(
                    ["git", "pull"],
                    cwd=self.root_dir,
                    capture_output=True,
                    text=True,
                )
                if pull_result2.returncode == 0:
                    log.info("✅ 普通 Git 拉取成功")
                else:
                    log.error(f"❌ 普通 Git 拉取也失败: {pull_result2.stderr.strip()}")

            # git stash pop: 恢复本地修改
            if has_stash:
                stash_pop_result = subprocess.run(
                    ["git", "stash", "pop"],
                    cwd=self.root_dir,
                    capture_output=True,
                    text=True,
                )
                if stash_pop_result.returncode == 0:
                    log.info("本地修改已恢复")
                else:
                    log.warning(f"⚠️ 恢复本地修改失败（可能有冲突，请手动检查）: {stash_pop_result.stderr.strip()}")

        except FileNotFoundError:
            log.warning("git 命令未找到，跳过拉取")
        except Exception as e:
            log.warning(f"Git 拉取出错: {e}")

    async def run(self):
        """主循环：连接 → 处理消息 → 断线重连"""
        self._running = True
        reconnect_delay = 1

        while self._running:
            try:
                # 拉取最新代码（保留本地 JSON 修改），在后台线程执行避免阻塞事件循环
                await asyncio.get_event_loop().run_in_executor(None, self._git_pull)
                log.info(f"正在连接 Server: {self.server_url}")
                async with websockets.connect(
                    self.server_url,
                    additional_headers={"Authorization": f"Bearer {self.token}"},
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    self.ws = ws
                    reconnect_delay = 1  # 连接成功，重置重连间隔
                    log.info("✅ 已连接到 Server")

                    # 启动日志监听
                    watcher_task = asyncio.create_task(self.watcher.watch())
                    # 启动推送任务
                    push_task = asyncio.create_task(self._push_loop())

                    try:
                        async for message in ws:
                            await self._handle_message(message)
                    except websockets.ConnectionClosed as e:
                        log.warning(f"连接断开: {e}")
                    finally:
                        watcher_task.cancel()
                        push_task.cancel()
                        try:
                            await watcher_task
                        except asyncio.CancelledError:
                            pass
                        try:
                            await push_task
                        except asyncio.CancelledError:
                            pass

            except websockets.InvalidHandshake as e:
                log.error(f"握手失败（检查 token）: {e}")
            except ConnectionRefusedError:
                log.error(f"连接被拒绝（检查 Server 是否启动）: {e}")
            except Exception as e:
                log.error(f"连接异常: {e}")

            if self._running:
                log.info(f"⏳ {reconnect_delay}s 后重连...")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 60)  # 指数退避，最大 60s

    async def _handle_message(self, raw: str):
        """处理 Server 发来的消息"""
        msg = parse_message(raw)
        if not msg:
            log.warning(f"收到无效消息: {raw[:100]}")
            return

        msg_type = msg.get("type")

        if msg_type == "ping":
            # 心跳响应
            if self.ws:
                await self.ws.send(make_pong())
            return

        if msg_type == "request":
            req_id = msg.get("id", "")
            action = msg.get("action", "")
            params = msg.get("params", {})

            log.debug(f"收到请求: {action} (id={req_id[:8]})")

            # 在线程池中处理，避免阻塞事件循环（文件 I/O、subprocess 等）
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self.handler.handle, action, params
            )
            response = make_response(
                req_id=req_id,
                success=result.get("success", False),
                data=result.get("data"),
                error=result.get("error"),
            )

            if self.ws:
                await self.ws.send(response)

            return

        log.debug(f"收到其他消息: {msg_type}")

    async def _push_loop(self):
        """从队列取出推送消息并发送"""
        while self._running:
            try:
                msg = await asyncio.wait_for(self._push_queue.get(), timeout=1.0)
                if self.ws:
                    await self.ws.send(msg)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                log.error(f"推送失败: {e}")

    def stop(self):
        """停止 Agent"""
        self._running = False
        self.watcher.stop()


def main():
    parser = argparse.ArgumentParser(description="cs-Solidarity Agent")
    parser.add_argument("--server", required=True, help="WebSocket 服务器地址，如 ws://1.2.3.4:11029/ws/agent")
    parser.add_argument("--token", required=True, help="Agent 连接令牌")
    parser.add_argument("--root", default=".", help="cs-Solidarity 项目根目录（默认当前目录）")
    parser.add_argument("--debug", action="store_true", help="启用调试日志")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # 验证根目录
    root = Path(args.root).resolve()
    if not root.is_dir():
        log.error(f"项目根目录不存在: {root}")
        sys.exit(1)

    log.info(f"cs-Solidarity Agent 启动")
    log.info(f"  Server: {args.server}")
    log.info(f"  Root:   {root}")

    client = AgentClient(args.server, args.token, str(root))

    # Windows 下处理 Ctrl+C
    def signal_handler(sig, frame):
        log.info("收到退出信号，正在关闭...")
        client.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        log.info("Agent 已退出")


if __name__ == "__main__":
    main()
