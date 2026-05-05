"""
cs-Solidarity Agent — 请求处理器

处理 Web Server 发来的各类请求，读写配置文件、获取状态、控制 bot 进程。
"""

import json
import os
import shutil
import subprocess
import sys
import glob
import logging
import uuid
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, List

log = logging.getLogger(__name__)


class AgentHandler:
    """处理 Web Server 发来的请求"""

    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir).resolve()
        self.pid_file = self.root_dir / ".bot.pid"
        self._chat_history_file = self.root_dir / "instconfig" / "chat_history.json"
        self._chat_history: List[Dict[str, Any]] = []
        self._chat_history_max = 500  # 最大历史条数
        self._chat_lock = threading.Lock()
        self._load_chat_history()
        log.info(f"AgentHandler 初始化，项目根目录: {self.root_dir}")

    def _git_pull(self):
        """执行 git pull，暂存本地修改后拉取，再恢复暂存"""
        try:
            # 检查是否是 git 仓库
            git_dir = self.root_dir / ".git"
            if not git_dir.is_dir():
                log.debug("非 git 仓库，跳过拉取")
                return

            # git stash push -u: 暂存本地修改（含未跟踪文件）
            stash_result = subprocess.run(
                ["git", "stash", "push", "-u"],
                cwd=str(self.root_dir),
                capture_output=True,
                text=True,
                encoding='utf-8',
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
                cwd=str(self.root_dir),
                capture_output=True,
                text=True,
                encoding='utf-8',
            )
            if pull_result.returncode == 0:
                log.info("✅ Git 拉取成功")
            else:
                log.warning(f"⚠️ Git 拉取失败: {pull_result.stderr.strip()}")
                # 尝试普通的 git pull（非 rebase）
                log.info("尝试普通 git pull...")
                pull_result2 = subprocess.run(
                    ["git", "pull"],
                    cwd=str(self.root_dir),
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                )
                if pull_result2.returncode == 0:
                    log.info("✅ 普通 Git 拉取成功")
                else:
                    log.error(f"❌ 普通 Git 拉取也失败: {pull_result2.stderr.strip()}")

            # git stash pop: 恢复本地修改
            if has_stash:
                stash_pop_result = subprocess.run(
                    ["git", "stash", "pop"],
                    cwd=str(self.root_dir),
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                )
                if stash_pop_result.returncode == 0:
                    log.info("本地修改已恢复")
                else:
                    log.warning(f"⚠️ 恢复本地修改失败（可能有冲突，请手动检查）: {stash_pop_result.stderr.strip()}")

        except FileNotFoundError:
            log.warning("git 命令未找到，跳过拉取")
        except Exception as e:
            log.warning(f"Git 拉取出错: {e}")

    def handle(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """分发请求到对应的处理方法"""
        handlers = {
            "config.read": self._config_read,
            "config.write": self._config_write,
            "config.list": self._config_list,
            "config.backup": self._config_backup,
            "config.backups": self._config_backups,
            "config.restore": self._config_restore,
            "log.read": self._log_read,
            "log.list": self._log_list,
            "status.overview": self._status_overview,
            "status.instances": self._status_instances,
            "steam.friends_status": self._steam_friends_status,
            "files.list": self._files_list,
            "files.upload": self._files_upload,
            "files.delete": self._files_delete,
            "files.download": self._files_download,
            "bot.start": self._bot_start,
            "bot.stop": self._bot_stop,
            "bot.restart": self._bot_restart,
            "chat.send": self._chat_send,
            "chat.history": self._chat_history_get,
        }

        handler = handlers.get(action)
        if not handler:
            return {"success": False, "error": f"未知操作: {action}"}

        try:
            return handler(params)
        except Exception as e:
            log.error(f"处理 {action} 失败: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    # ── 路径安全检查 ──

    def _safe_path(self, relative_path: str) -> Path:
        """解析路径并检查是否在项目目录内（Windows 大小写安全）"""
        full = (self.root_dir / relative_path).resolve()
        # 用 os.path.commonpath 做比较，比 startswith 更可靠
        # 统一转小写处理 Windows 驱动器号大小写不一致
        full_str = str(full).lower()
        root_str = str(self.root_dir).lower()
        # commonpath 要求两个路径类型一致（都是绝对路径）
        try:
            common = os.path.commonpath([full_str, root_str])
            if common != root_str:
                raise ValueError(f"路径越权访问: {relative_path}")
        except ValueError:
            # commonpath 在不同驱动器时抛 ValueError
            raise ValueError(f"路径越权访问: {relative_path}")
        return full

    # ── 配置读写 ──

    def _config_read(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """读取配置文件"""
        file_path = self._safe_path(params.get("file", "config.json"))
        if not file_path.exists():
            return {"success": False, "error": f"文件不存在: {file_path.name}"}

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        return {
            "success": True,
            "data": {
                "file": params.get("file", "config.json"),
                "content": content,
                "modified": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
                "size": file_path.stat().st_size,
            }
        }

    def _config_write(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """写入配置文件（写入前自动备份）"""
        file_path = self._safe_path(params.get("file", ""))
        content = params.get("content", "")

        if not file_path.name:
            return {"success": False, "error": "未指定文件名"}

        # 写入前自动备份
        if file_path.exists():
            self._do_backup(file_path)

        # 验证 JSON 格式
        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"JSON 格式错误: {e}"}

        # 确保目录存在
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        log.info(f"配置已写入: {file_path.name}")
        return {"success": True, "data": {"file": params.get("file"), "message": "保存成功"}}

    def _config_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """列出所有配置文件"""
        files = []

        # 主配置
        main_config = self.root_dir / "config.json"
        if main_config.exists():
            files.append({
                "name": "config.json",
                "path": "config.json",
                "type": "main",
                "size": main_config.stat().st_size,
                "modified": datetime.fromtimestamp(main_config.stat().st_mtime).isoformat(),
            })

        # 实例配置
        instconfig_dir = self.root_dir / "instconfig"
        if instconfig_dir.is_dir():
            for f in sorted(instconfig_dir.glob("*.json")):
                files.append({
                    "name": f.name,
                    "path": f"instconfig/{f.name}",
                    "type": "instance",
                    "size": f.stat().st_size,
                    "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                })

        return {"success": True, "data": {"files": files}}

    def _config_backup(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """手动备份配置文件"""
        file_path = self._safe_path(params.get("file", ""))
        if not file_path.exists():
            return {"success": False, "error": f"文件不存在: {file_path.name}"}

        backup_path = self._do_backup(file_path)
        return {
            "success": True,
            "data": {
                "backup_file": backup_path.name,
                "message": f"已备份: {backup_path.name}"
            }
        }

    def _config_backups(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """列出所有备份"""
        backup_dir = self.root_dir / "backups"
        if not backup_dir.is_dir():
            return {"success": True, "data": {"backups": []}}

        backups = []
        for f in sorted(backup_dir.glob("*.json"), reverse=True):
            backups.append({
                "name": f.name,
                "size": f.stat().st_size,
                "created": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })

        return {"success": True, "data": {"backups": backups}}

    def _config_restore(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """从备份恢复配置"""
        backup_name = params.get("backup_file", "")
        target_file = params.get("target", "")

        backup_path = self._safe_path(f"backups/{backup_name}")
        target_path = self._safe_path(target_file)

        if not backup_path.exists():
            return {"success": False, "error": f"备份不存在: {backup_name}"}

        # 恢复前也备份当前文件
        if target_path.exists():
            self._do_backup(target_path)

        shutil.copy2(backup_path, target_path)
        log.info(f"已从备份恢复: {backup_name} → {target_file}")

        return {
            "success": True,
            "data": {"message": f"已恢复: {backup_name} → {target_file}"}
        }

    def _do_backup(self, file_path: Path) -> Path:
        """执行备份操作"""
        backup_dir = self.root_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{file_path.stem}_{timestamp}{file_path.suffix}"
        backup_path = backup_dir / backup_name

        shutil.copy2(file_path, backup_path)
        log.debug(f"备份: {file_path.name} → {backup_name}")

        # 清理超过 30 天的备份
        self._cleanup_old_backups(backup_dir)

        return backup_path

    def _cleanup_old_backups(self, backup_dir: Path, max_age_days: int = 30):
        """清理过期备份"""
        cutoff = datetime.now().timestamp() - (max_age_days * 86400)
        for f in backup_dir.glob("*.json"):
            if f.stat().st_mtime < cutoff:
                f.unlink()
                log.debug(f"清理过期备份: {f.name}")

    # ── 日志 ──

    def _log_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """列出可用日志文件"""
        log_dir = self.root_dir / "logs"
        if not log_dir.is_dir():
            return {"success": True, "data": {"files": []}}

        files = []
        for f in sorted(log_dir.glob("*.log"), reverse=True):
            files.append({
                "date": f.stem,  # 2026-04-02
                "filename": f.name,
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })

        return {"success": True, "data": {"files": files}}

    def _log_read(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """读取日志文件（流式处理，避免大文件一次性加载）"""
        date = params.get("date", datetime.now().strftime("%Y-%m-%d"))
        level_filter = params.get("level", "").upper()
        keyword = params.get("keyword", "")
        page = params.get("page", 1)
        page_size = min(params.get("page_size", 200), 500)  # 最大 500 条/页

        log_file = self._safe_path(f"logs/{date}.log")
        if not log_file.exists():
            return {"success": True, "data": {"lines": [], "total": 0, "date": date}}

        # 流式过滤，不一次性加载全部行
        filtered = []
        total_lines = 0
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    total_lines += 1
                    line = line.rstrip("\n")
                    if not line:
                        continue
                    if level_filter and level_filter not in line:
                        continue
                    if keyword and keyword.lower() not in line.lower():
                        continue
                    filtered.append(line)
        except Exception as e:
            return {"success": False, "error": f"读取日志失败: {e}"}

        # 分页
        total = len(filtered)
        start = (page - 1) * page_size
        end = start + page_size
        page_lines = filtered[start:end]

        return {
            "success": True,
            "data": {
                "date": date,
                "lines": page_lines,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size,
            }
        }

    # ── 状态 ──

    def _status_overview(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """获取总体状态"""
        # 检查 bot 进程
        bot_running = False
        bot_pid = None
        if self.pid_file.exists():
            try:
                bot_pid = int(self.pid_file.read_text().strip())
                # Windows 下检查进程是否存在
                import ctypes
                kernel32 = ctypes.windll.kernel32
                SYNCHRONIZE = 0x00100000
                handle = kernel32.OpenProcess(SYNCHRONIZE, False, bot_pid)
                if handle:
                    bot_running = True
                    kernel32.CloseHandle(handle)
            except (ValueError, Exception):
                pass

        # 读取配置获取实例数
        instance_count = 0
        debug_mode = False
        config_file = self.root_dir / "config.json"
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                instance_count = len(cfg.get("instances", []))
                debug_mode = cfg.get("debug_mode", False)
            except Exception:
                pass

        # 检查维护时段
        from datetime import time as dt_time
        now = datetime.now().time()
        is_maintenance = dt_time(0, 15) <= now < dt_time(8, 0) and not debug_mode

        # 最近日志
        recent_logs = []
        today_log = self.root_dir / "logs" / f"{datetime.now().strftime('%Y-%m-%d')}.log"
        if today_log.exists():
            try:
                with open(today_log, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                recent_logs = [l.rstrip() for l in lines[-10:]]
            except Exception:
                pass

        # 硬件信息
        hardware = {}
        try:
            import psutil
            cpu_percent = psutil.cpu_percent(interval=0.3)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            hardware = {
                "cpu_percent": cpu_percent,
                "cpu_count": psutil.cpu_count(),
                "memory_total": memory.total,
                "memory_used": memory.used,
                "memory_percent": memory.percent,
                "disk_total": disk.total,
                "disk_used": disk.used,
                "disk_percent": disk.percent,
            }
        except Exception:
            pass

        return {
            "success": True,
            "data": {
                "bot_running": bot_running,
                "bot_pid": bot_pid,
                "instance_count": instance_count,
                "debug_mode": debug_mode,
                "is_maintenance": is_maintenance,
                "project_root": str(self.root_dir),
                "hostname": os.environ.get("COMPUTERNAME", "unknown"),
                "recent_logs": recent_logs,
                "hardware": hardware,
            }
        }

    def _status_instances(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """获取实例列表及状态"""
        config_file = self.root_dir / "config.json"
        if not config_file.exists():
            return {"success": False, "error": "config.json 不存在"}

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            return {"success": False, "error": f"读取配置失败: {e}"}

        instances = []
        for idx, item in enumerate(cfg.get("instances", []), 1):
            inst_type = item.get("type", "unknown")
            inst_config_path = item.get("config", "")

            # 读取实例详细配置
            inst_detail = {}
            if inst_config_path:
                detail_file = self.root_dir / inst_config_path
                if detail_file.exists():
                    try:
                        with open(detail_file, "r", encoding="utf-8") as f:
                            inst_detail = json.load(f)
                    except Exception:
                        pass

                # steam 实例：合并数据文件（运行时数据与配置分离）
                if inst_type == "steam":
                    data_file = detail_file.parent / "steam_data.json"
                    if data_file.exists():
                        try:
                            with open(data_file, "r", encoding="utf-8") as f:
                                inst_detail.update(json.load(f))
                        except Exception:
                            pass

            # 根据类型提取摘要信息
            summary = self._instance_summary(inst_type, inst_detail, item)

            instances.append({
                "index": idx,
                "type": inst_type,
                "config_path": inst_config_path,
                "summary": summary,
                "detail": inst_detail,
            })

        return {"success": True, "data": {"instances": instances}}

    def _instance_summary(self, inst_type: str, detail: dict, item: dict) -> dict:
        """生成实例摘要"""
        if inst_type == "steam":
            return {
                "groups": detail.get("wechat_groups", []),
                "monitored_friends": len(detail.get("monitored_friends", [])),
                "check_interval": detail.get("check_interval", 60),
            }
        elif inst_type == "daily":
            return {
                "groups": detail.get("wechat_groups", item.get("wechat_groups", [])),
                "time": detail.get("time", item.get("time", "")),
                "message": (detail.get("message", item.get("message", "")))[:50],
            }
        elif inst_type == "chat":
            return {
                "trigger_prefix": detail.get("trigger_prefix", ""),
                "model": detail.get("model", ""),
                "base_url": detail.get("base_url", ""),
                "allowed_groups": detail.get("allowed_groups", []),
            }
        elif inst_type == "korichat":
            return {
                "groups": [g.get("groupName", "") for g in detail.get("group_chat_config", [])],
                "private_chats": len(detail.get("private_chat_config", [])),
            }
        elif inst_type == "infopush":
            return {
                "groups": detail.get("wechat_groups", []),
                "push_times": detail.get("push_times", []),
            }
        return {}

    # ── Bot 控制 ──

    def _bot_start(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """启动 bot"""
        if self.pid_file.exists():
            try:
                pid = int(self.pid_file.read_text().strip())
                import ctypes
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(0x00100000, False, pid)
                if handle:
                    kernel32.CloseHandle(handle)
                    return {"success": False, "error": f"Bot 已在运行 (PID: {pid})"}
            except Exception:
                pass

        # 启动前先拉取最新代码
        self._git_pull()

        main_py = self.root_dir / "main.py"
        if not main_py.exists():
            return {"success": False, "error": "main.py 不存在"}

        try:
            proc = subprocess.Popen(
                [sys.executable, str(main_py)],
                cwd=str(self.root_dir),
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            self.pid_file.write_text(str(proc.pid))
            log.info(f"Bot 已启动, PID: {proc.pid}")
            return {
                "success": True,
                "data": {"pid": proc.pid, "message": "Bot 已启动"}
            }
        except Exception as e:
            return {"success": False, "error": f"启动失败: {e}"}

    def _bot_stop(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """停止 bot（先尝试优雅关闭，超时后强杀）"""
        if not self.pid_file.exists():
            return {"success": False, "error": "Bot 未在运行（无 PID 文件）"}

        try:
            pid = int(self.pid_file.read_text().strip())
            import ctypes
            import time
            kernel32 = ctypes.windll.kernel32

            PROCESS_TERMINATE = 0x0001
            SYNCHRONIZE = 0x00100000

            handle = kernel32.OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, False, pid)
            if not handle:
                self.pid_file.unlink()
                return {"success": False, "error": f"进程 {pid} 不存在，已清理 PID 文件"}

            # 先尝试用 GenerateConsoleCtrlEvent 发送 Ctrl+C（优雅关闭）
            # 注意：仅对控制台进程有效，GUI 进程可能无响应
            try:
                kernel32.GenerateConsoleCtrlEvent(0, pid)  # CTRL_C_EVENT
            except Exception:
                pass

            # 等待最多 5 秒让进程自行退出
            WAIT_OBJECT_0 = 0
            result = kernel32.WaitForSingleObject(handle, 5000)  # 5000ms

            if result == WAIT_OBJECT_0:
                # 进程已自行退出
                kernel32.CloseHandle(handle)
                self.pid_file.unlink()
                log.info(f"Bot 已优雅停止 (PID: {pid})")
                return {"success": True, "data": {"message": f"Bot 已停止 (PID: {pid})"}}

            # 超时，强杀
            log.warning(f"Bot 未响应优雅关闭，强制终止 (PID: {pid})")
            kernel32.TerminateProcess(handle, 0)
            kernel32.CloseHandle(handle)
            self.pid_file.unlink()
            return {"success": True, "data": {"message": f"Bot 已强制停止 (PID: {pid})"}}

        except Exception as e:
            return {"success": False, "error": f"停止失败: {e}"}

    def _bot_restart(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """重启 bot"""
        self._bot_stop(params)
        import time
        time.sleep(2)
        return self._bot_start(params)

    # ── Steam 好友状态 ──

    def _steam_friends_status(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """获取 Steam 好友在线状态"""
        import time

        data_file = self.root_dir / "instconfig" / "steam_data.json"
        config_file = self.root_dir / "instconfig" / "steam_account.json"
        # 优先从数据文件读取，回退到配置文件（兼容未迁移的情况）
        read_file = data_file if data_file.exists() else config_file
        if not read_file.exists():
            return {"success": False, "error": "steam_data.json 不存在"}

        try:
            with open(read_file, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            return {"success": False, "error": f"读取配置失败: {e}"}

        friends = config.get("monitored_friends", [])
        now = time.time()

        state_text = {0: "离线", 1: "在线", 2: "游戏中", 3: "离开"}
        state_class = {0: "offline", 1: "online", 2: "ingame", 3: "away"}

        def time_ago(ts):
            if not ts:
                return None
            diff = now - ts
            if diff < 60:
                return "刚刚"
            if diff < 3600:
                return f"{int(diff / 60)}分钟前"
            if diff < 86400:
                return f"{int(diff / 3600)}小时前"
            return f"{int(diff / 86400)}天前"

        result = []
        for f in friends:
            personastate = f.get("personastate", 0)
            lastlogoff = f.get("lastlogoff")

            # 构建显示文本（状态 + 详情）
            game_info = f.get("gameextrainfo") or ""

            if game_info and game_info != "未游玩游戏" and personastate in (1, 2):
                # 在线(1)或忙碌(2)且有游戏信息 → 游戏中
                display_text = f"游戏中 · {game_info}"
                effective_state = 2
            elif personastate == 0:
                time_str = time_ago(lastlogoff) if lastlogoff else ""
                display_text = f"离线 · {time_str}" if time_str else "离线"
                effective_state = 0
            elif personastate == 1:
                display_text = "在线"
                effective_state = 1
            elif personastate == 3:
                display_text = "离开"
                effective_state = 3
            else:
                display_text = ""
                effective_state = personastate

            friend_info = {
                "personaname": f.get("personaname") or f.get("nickname", "未知"),
                "personastate": personastate,
                "personastate_text": state_text.get(effective_state, "未知"),
                "state_class": state_class.get(effective_state, "offline"),
                "gameextrainfo": display_text,
            }
            result.append(friend_info)

        return {
            "success": True,
            "data": {
                "friends": result,
                "last_update": datetime.now().isoformat()
            }
        }

    # ── 文件管理 ──

    def _get_shared_dir(self) -> Path:
        """获取共享文件目录（相对于 agent/ 目录）"""
        shared_dir = Path(__file__).resolve().parent / "shared_files"
        shared_dir.mkdir(parents=True, exist_ok=True)
        return shared_dir

    def _files_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """列出共享文件"""
        shared_dir = self._get_shared_dir()
        files = []
        total_size = 0

        for f in sorted(shared_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if f.is_file() and not f.name.endswith(".meta.json"):
                stat = f.stat()
                meta_path = f.parent / f"{f.name}.meta.json"
                uploader = "unknown"
                if meta_path.exists():
                    try:
                        meta = json.loads(meta_path.read_text(encoding="utf-8"))
                        uploader = meta.get("uploader", "unknown")
                    except Exception:
                        pass
                files.append({
                    "filename": f.name,
                    "size": stat.st_size,
                    "size_text": self._format_size(stat.st_size),
                    "uploader": uploader,
                    "uploaded_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
                total_size += stat.st_size

        return {"success": True, "data": {"files": files, "total_size": total_size}}

    def _files_upload(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """上传文件（分块接收）"""
        filename = params.get("filename", "")
        chunk_data = params.get("chunk", "")
        chunk_index = params.get("chunk_index", 0)
        total_chunks = params.get("total_chunks", 1)
        uploader = params.get("uploader", "unknown")
        file_size = params.get("file_size", 0)

        if not filename:
            return {"success": False, "error": "文件名不能为空"}

        # 安全检查：防止路径穿越
        if ".." in filename or "/" in filename or "\\" in filename:
            return {"success": False, "error": "文件名无效"}

        import base64
        shared_dir = self._get_shared_dir()

        if chunk_index == 0:
            # 首次上传，创建文件
            file_path = shared_dir / filename
            # 如果文件已存在，添加时间戳
            if file_path.exists():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                stem = file_path.stem
                ext = file_path.suffix
                file_path = file_path.parent / f"{stem}_{timestamp}{ext}"

            # 记录进行中的上传（文件路径，uploader）
            if not hasattr(self, '_upload_progress'):
                self._upload_progress = {}
            self._upload_progress[filename] = {"file_path": file_path, "uploader": uploader, "chunks": {}}

            # 创建空文件准备接收
            file_path.touch()
        else:
            # 验证进行中的上传
            if not hasattr(self, '_upload_progress') or filename not in self._upload_progress:
                return {"success": False, "error": "上传上下文无效，请从头开始"}
            file_path = self._upload_progress[filename]["file_path"]

        # 解码并写入块
        try:
            chunk_bytes = base64.b64decode(chunk_data)
        except Exception as e:
            return {"success": False, "error": f"块数据解码失败: {e}"}

        # 追加到文件
        with open(file_path, "ab") as f:
            f.write(chunk_bytes)
        self._upload_progress[filename]["chunks"][chunk_index] = len(chunk_bytes)

        # 检查是否完成
        received_chunks = len(self._upload_progress[filename]["chunks"])
        if received_chunks >= total_chunks:
            # 完成：写入元数据
            actual_size = file_path.stat().st_size
            meta_path = file_path.parent / f"{file_path.name}.meta.json"
            meta = {
                "uploader": self._upload_progress[filename]["uploader"],
                "uploaded_at": datetime.now().isoformat(),
                "file_size": actual_size,
            }
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False)
            del self._upload_progress[filename]
            log.info(f"文件已上传: {file_path.name} (uploader={meta['uploader']})")
            return {"success": True, "data": {"filename": file_path.name, "size": actual_size}}
        else:
            return {"success": True, "data": {"chunk_received": chunk_index + 1, "total_chunks": total_chunks}}

    def _files_delete(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """删除文件"""
        filename = params.get("filename", "")

        if not filename:
            return {"success": False, "error": "文件名不能为空"}

        file_path = self._get_shared_dir() / filename

        if not file_path.exists():
            return {"success": False, "error": "文件不存在"}

        # 删除元数据文件（如果存在）
        meta_path = file_path.parent / f"{file_path.name}.meta.json"
        if meta_path.exists():
            meta_path.unlink()

        file_path.unlink()
        log.info(f"文件已删除: {filename}")
        return {"success": True, "data": {"message": f"{filename} 已删除"}}

    def _files_download(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """下载文件（先返回元信息，再异步推送 chunk）"""
        filename = params.get("filename", "")
        chunk_size = params.get("chunk_size", 1024 * 1024)
        download_id = params.get("download_id", str(uuid.uuid4())[:8])

        if not filename:
            return {"success": False, "error": "文件名不能为空"}

        file_path = self._get_shared_dir() / filename

        if not file_path.exists():
            return {"success": False, "error": "文件不存在"}

        file_size = file_path.stat().st_size
        total_chunks = (file_size + chunk_size - 1) // chunk_size

        # 异步推送 chunk（在后台线程中执行，不阻塞 response）
        def _push_chunks():
            import base64 as b64mod
            with open(file_path, "rb") as f:
                for i in range(total_chunks):
                    chunk_bytes = f.read(chunk_size)
                    chunk_b64 = b64mod.b64encode(chunk_bytes).decode("utf-8")
                    if hasattr(self, '_push_callback'):
                        import asyncio
                        loop = getattr(self, '_event_loop', None)
                        if loop and loop.is_running():
                            future = asyncio.run_coroutine_threadsafe(
                                self._push_callback("file.chunk", {
                                    "download_id": download_id,
                                    "filename": filename,
                                    "chunk_index": i,
                                    "total_chunks": total_chunks,
                                    "chunk": chunk_b64,
                                    "file_size": file_size,
                                }),
                                loop
                            )
                            future.result(timeout=30)
                    else:
                        log.warning("无可用推送回调，跳过块发送")
            # 推送完成标记
            if hasattr(self, '_push_callback'):
                import asyncio
                loop = getattr(self, '_event_loop', None)
                if loop and loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self._push_callback("file.chunk", {
                            "download_id": download_id,
                            "chunk_index": -1,
                            "total_chunks": total_chunks,
                            "chunk": None,
                            "file_size": file_size,
                        }),
                        loop
                    )

        import threading
        t = threading.Thread(target=_push_chunks, daemon=True)
        t.start()

        # 立即返回元信息，不等待 chunk 推送完成
        return {
            "success": True,
            "data": {
                "download_id": download_id,
                "filename": filename,
                "size": file_size,
                "chunks": total_chunks,
            }
        }

    # ── 聊天 ──

    def _chat_send(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理 Web 聊天消息：通过 TCP 发送到 Bot 主循环处理"""
        content = params.get("content", "").strip()
        sender = params.get("sender", "WebUser")
        chat_name = params.get("chat_name", "网页聊天室")

        if not content:
            return {"success": False, "error": "消息内容不能为空"}

        # 记录用户消息到历史
        msg_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now().isoformat()
        user_msg = {
            "id": msg_id,
            "chat_name": chat_name,
            "sender": sender,
            "content": content,
            "timestamp": timestamp,
            "source": "user",
        }
        self._add_chat_history(user_msg)

        # 通过 TCP 发送到 Bot 进程
        try:
            from bot.chat_server import send_chat_to_bot
            result = send_chat_to_bot(params, timeout=65)
        except ImportError:
            return {"success": False, "error": "bot.chat_server 模块未加载"}
        except Exception as e:
            log.error(f"TCP 聊天请求失败: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

        if not result.get("success"):
            return result

        # 记录回复到历史，逐条延迟推送到 Web 客户端（模拟真人节奏）
        replies = result.get("data", {}).get("replies", [])
        for i, reply in enumerate(replies):
            self._add_chat_history(reply)
            if hasattr(self, '_push_callback'):
                import asyncio
                import random
                loop = getattr(self, '_event_loop', None)
                if loop and loop.is_running():
                    delay = 0 if i == 0 else random.uniform(2, 4)
                    if delay > 0:
                        async def _delayed_push(d, event, data):
                            await asyncio.sleep(d)
                            await self._push_callback(event, data)
                        asyncio.run_coroutine_threadsafe(
                            _delayed_push(delay, "chat.message", reply),
                            loop,
                        )
                    else:
                        asyncio.run_coroutine_threadsafe(
                            self._push_callback("chat.message", reply),
                            loop,
                        )

        return result

    def _chat_history_get(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """获取聊天历史"""
        limit = min(params.get("limit", 100), self._chat_history_max)
        with self._chat_lock:
            history = self._chat_history[-limit:]
        return {"success": True, "data": {"messages": history}}

    def _add_chat_history(self, msg: Dict[str, Any]):
        """添加消息到历史记录"""
        with self._chat_lock:
            self._chat_history.append(msg)
            if len(self._chat_history) > self._chat_history_max:
                self._chat_history = self._chat_history[-self._chat_history_max:]
            self._save_chat_history()

    def _load_chat_history(self):
        """从文件加载聊天历史"""
        try:
            if self._chat_history_file.exists():
                with open(self._chat_history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._chat_history = data[-self._chat_history_max:]
                    log.info(f"已加载 {len(self._chat_history)} 条聊天历史")
        except Exception as e:
            log.warning(f"加载聊天历史失败: {e}")

    def _save_chat_history(self):
        """将聊天历史写入文件（调用方需持有 _chat_lock）"""
        try:
            with open(self._chat_history_file, "w", encoding="utf-8") as f:
                json.dump(self._chat_history, f, ensure_ascii=False)
        except Exception as e:
            log.warning(f"保存聊天历史失败: {e}")

    def _format_size(self, size: int) -> str:
        """格式化文件大小"""
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
