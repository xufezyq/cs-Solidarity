import hashlib
import importlib
import importlib.util
import json
import logging
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
import asyncio
from pathlib import Path

from .config import load_config
from .repository import Repository

log = logging.getLogger(__name__)


def stable_event_key(event: dict) -> str:
    fields = {k: event.get(k) for k in ("round", "tick", "start_tick", "end_tick", "steamid", "kills", "weapon", "victims", "category")}
    raw = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def sanitize_match(item: dict) -> dict:
    summary = item.get("raw_summary") if isinstance(item.get("raw_summary"), dict) else item
    aliases = {"match_id": ("match_id", "id", "matchId"), "map": ("map", "map_name", "mapName", "map_label"),
               "played_at": ("played_at", "started_at", "time", "start_time", "startTime", "date"),
               "score": ("score_text",), "result": ("result", "win", "outcome"),
               "demo_available": ("demo_available", "has_demo", "demoAvailable")}
    out = {}
    for target, keys in aliases.items():
        out[target] = next((item[k] for k in keys if k in item and item[k] is not None), None)
        if out[target] is None and target != "score":
            out[target] = next((summary[k] for k in keys if k in summary and summary[k] is not None), None)
    teams = item.get("teams")
    if out["score"] is None and isinstance(teams, list):
        scores = []
        for team in teams:
            if isinstance(team, dict) and isinstance(team.get("score"), int):
                scores.append(f"{team.get('name') or '?'} {team['score']}")
        if len(scores) == 2:
            out["score"] = " : ".join(scores)
    out["ladder_score"] = summary.get("score") if isinstance(summary.get("score"), (int, float)) else None
    out["is_mvp"] = summary.get("is_mvp") is True
    out["details_loaded"] = bool(item.get("details_loaded"))
    return out


def sanitize_pw_match(item: dict) -> dict:
    """Expose only the fields needed by the video picker from cs2_pw."""
    score1, score2 = item.get("score1"), item.get("score2")
    score = f"{score1} : {score2}" if isinstance(score1, (int, float)) and isinstance(score2, (int, float)) else None
    team, winner = item.get("team"), item.get("winTeam")
    result = None
    if winner in (0, "0"):
        result = "平局"
    elif team is not None and winner is not None:
        result = "胜利" if str(team) == str(winner) else "失利"
    numeric = lambda key: item.get(key) if isinstance(item.get(key), (int, float)) else None
    return {
        "match_id": str(item.get("matchId") or item.get("match_id") or ""),
        "map": item.get("mapName") or item.get("map") or None,
        "played_at": item.get("endTime") or item.get("startTime") or None,
        "score": score,
        "result": result,
        "demo_available": None,
        "ladder_score": item.get("pvpScore") if isinstance(item.get("pvpScore"), (int, float)) else None,
        "ladder_change": numeric("pvpScoreChange"),
        "duration_minutes": numeric("duration"),
        "stats": {
            "kills": numeric("kill"),
            "deaths": numeric("death"),
            "assists": numeric("assist"),
            "rating": numeric("rating"),
            "pw_rating": numeric("pwRating"),
            "we": numeric("we"),
        },
        "is_mvp": item.get("pvpMvp") is True,
        "details_loaded": True,
    }


class CS2VideoService:
    def __init__(self, root: Path, push=None):
        self.root = Path(root).resolve()
        downloader_src = self.root / "Plugins" / "CS2Video" / "third_party" / "cs-demo-downloader" / "src"
        if downloader_src.is_dir() and str(downloader_src) not in sys.path:
            sys.path.insert(0, str(downloader_src))
        self.config = load_config(self.root)
        self.repo = Repository(self.root / "data" / "cs2-video" / "jobs.sqlite3")
        self.push = push
        self._query_metadata = {}
        self._insight_process = None
        self._health_lock = threading.Lock()
        self._health_snapshot = {"downloader": False, "insight": None, "bot": None}
        self._health_refreshing = False
        Path(self.config["demo_dir"]).mkdir(parents=True, exist_ok=True)
        Path(self.config["export_dir"]).mkdir(parents=True, exist_ok=True)
        self._ensure_insight()
        self._refresh_health_async()

    def _ensure_insight(self):
        if not self.config.get("insight_auto_start") or self._health(self.config["insight_base_url"]):
            return
        launcher = Path(self.config["insight_project_dir"]) / "backend" / "app" / "run_server.py"
        if not launcher.is_file():
            log.warning("Integrated Insight launcher not found: %s", launcher)
            return
        env = os.environ.copy()
        env.setdefault("CS2_INSIGHT_HOST", "127.0.0.1")
        env.setdefault("CS2_INSIGHT_PORT", "19871")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._insight_process = subprocess.Popen(
                [sys.executable, str(launcher)], cwd=str(Path(self.config["insight_project_dir"])),
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags,
            )
        except Exception as exc:
            log.warning("Unable to start integrated Insight backend: %s", exc)

    def _players(self):
        path = self.root / "instconfig" / "steam_data.json"
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        allowed = set(map(str, self.config.get("allowed_player_ids") or []))
        result = []
        for p in data.get("monitored_friends", []):
            sid = str(p.get("steamid", ""))
            if sid and (not allowed or sid in allowed):
                result.append({"steamid": sid, "nickname": p.get("pw_nickname") or p.get("personaname") or sid,
                               "steam_name": p.get("personaname", ""), "avatar": p.get("avatar", "")})
        return result

    def bootstrap(self):
        self._refresh_health_async()
        with self._health_lock:
            health = dict(self._health_snapshot)
        return {"enabled": self.config["enabled"], "players": self._players(), "wechat_targets": self.config["wechat_targets"],
                "presets": self.config["presets"], "packaging_presets": self.config["packaging_presets"],
                "bgm_presets": self.config["bgm_presets"], "health": health}

    def _refresh_health_async(self):
        with self._health_lock:
            if self._health_refreshing:
                return
            self._health_refreshing = True
        threading.Thread(target=self._refresh_health, daemon=True, name="cs2-video-health").start()

    def _refresh_health(self):
        try:
            snapshot = {
                "downloader": importlib.util.find_spec("cs_demo_downloader") is not None,
                "insight": self._health(self.config["insight_base_url"]),
                "bot": self._health(self.config["bot_base_url"]),
            }
            with self._health_lock:
                self._health_snapshot = snapshot
        finally:
            with self._health_lock:
                self._health_refreshing = False

    @staticmethod
    def _health(base):
        for health_path in ("/health", "/api/health"):
            try:
                with urllib.request.urlopen(base.rstrip("/") + health_path, timeout=1.5) as res:
                    if 200 <= res.status < 300:
                        return True
            except Exception:
                continue
        return False

    def query_matches(self, owner, player_id):
        self._require_player(player_id)
        query_id = uuid.uuid4().hex
        row = self.repo.create_query(query_id, owner, player_id)
        threading.Thread(target=self._run_query, args=(query_id, player_id), daemon=True).start()
        return row

    def _run_query(self, query_id, player_id):
        try:
            from cs_demo_downloader.core.config import load_config as load_downloader_config
            from cs2_platforms.cs2_pw.request import PerfectWorldApi
            cfg = load_downloader_config(self.config["downloader_config_path"])
            configured_users = cfg.get_users_pwa()
            target = next((user for user in configured_users if str(user.steamid) == str(player_id)), None)
            credential = target or next((user for user in configured_users if user.access_token), None)
            if credential is None:
                raise ValueError("下载器配置中没有可用的完美平台授权账号")
            limit = max(1, int(self.config.get("match_query_limit", 10)))
            api = PerfectWorldApi(uid=str(credential.request_steamid), token=credential.access_token)
            response = asyncio.run(api.get_csgopfmatch(str(player_id), csgoSeasonId=3, type=-1))
            if not isinstance(response, dict):
                raise RuntimeError("完美平台对局列表请求失败")
            data = response.get("data")
            rows = data.get("matchList", []) if isinstance(data, dict) else []
            if not isinstance(rows, list):
                raise RuntimeError("完美平台未返回对局列表")
            rows = [row for row in rows if isinstance(row, dict) and row.get("matchId")][:limit]
            self._query_metadata[query_id] = {str(item["matchId"]): item for item in rows}
            matches = [sanitize_pw_match(item) for item in rows]
            self.repo.finish_query(query_id, matches=matches)
        except Exception as exc:
            log.warning("CS2 match query failed: %s", exc)
            self.repo.finish_query(query_id, error=str(exc))

    def get_query(self, query_id, owner, admin=False):
        row = self.repo.get_query(query_id)
        self._owned(row, owner, admin)
        return row

    def create_job(self, owner, query_id, match_id):
        query = self.get_query(query_id, owner)
        if query["status"] != "completed" or not any(str(m.get("match_id")) == str(match_id) for m in query["matches"]):
            raise ValueError("比赛不在有效查询结果中")
        if self.repo.active_count(owner) >= int(self.config["max_active_jobs_per_user"]):
            raise ValueError("未完成任务数量已达上限")
        job = self.repo.create_job(uuid.uuid4().hex, owner, query_id, str(match_id), query["player_id"])
        threading.Thread(target=self._prepare_job, args=(job["id"],), daemon=True).start()
        return job

    def _prepare_job(self, job_id):
        try:
            job = self.repo.get_job(job_id)
            if not job:
                raise ValueError("任务不存在")
            self.repo.update_job(job_id, status="downloading", progress=10, error=None)
            from cs_demo_downloader.cli import build_pwa_demo_url_signer, build_pwa_et_decryptor
            from cs_demo_downloader.core.config import load_config as load_downloader_config
            from cs_demo_downloader.core.downloader_pwa import build_download_headers, get_demo_url, get_match_list_records
            from cs_demo_downloader.core.utils import download_and_extract

            cfg = load_downloader_config(self.config["downloader_config_path"])
            users = cfg.get_users_pwa()
            credential = next((u for u in users if str(u.steamid) == str(job["player_id"])), None)
            credential = credential or next((u for u in users if u.access_token), None)
            if credential is None:
                raise RuntimeError("下载器配置中没有可用的完美平台授权账号")
            signer = build_pwa_demo_url_signer(cfg)
            # cs2_pw identifies Perfect World matches as ``PVP@<numeric-id>``;
            # the demo endpoint accepts only the numeric component.
            download_match_id = str(job["match_id"]).split("@", 1)[-1]
            if not download_match_id.isdigit():
                raise RuntimeError("比赛 ID 格式无效，无法下载 Demo")
            # Reuse the downloader's PWA list lookup so cup_id matches the
            # selected match. cup_id=0 is not valid for every PVP match.
            pwa_matches = get_match_list_records(
                steamid=str(job["player_id"]), access_token=credential.access_token, size=50,
                signer=signer, et_decryptor=build_pwa_et_decryptor(cfg), auth_steamid=credential.request_steamid,
            )
            pwa_match = next(
                (row for row in pwa_matches if str(row.get("match") or "").split("@", 1)[-1] == download_match_id),
                None,
            )
            if pwa_match is None:
                raise RuntimeError("下载器未在完美平台列表中找到该场比赛，无法取得 Demo 下载参数")
            try:
                cup_id = int(pwa_match.get("cup_id") or 0)
            except (TypeError, ValueError):
                cup_id = 0
            demo_url = get_demo_url(download_match_id, credential.access_token, cup_id=cup_id, signer=signer)
            if not download_and_extract(
                demo_url, self.config["demo_dir"], headers=build_download_headers(credential.request_steamid),
            ):
                raise RuntimeError("Demo 下载或解压失败，请检查完美平台授权和该场 Demo 是否可用")
            demo_candidates = sorted(Path(self.config["demo_dir"]).glob(f"{download_match_id}*.dem"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not demo_candidates:
                raise RuntimeError("Demo 下载完成后未找到 .dem 文件")
            demo_path = demo_candidates[0].resolve()
            self.repo.update_job(job_id, status="ingesting", progress=25)
            target = next((p for p in self._players() if str(p["steamid"]) == str(job["player_id"])), None)
            if not target or not target.get("nickname"):
                raise RuntimeError("未找到该玩家的完美平台昵称，无法分析 Demo")
            self.repo.update_job(job_id, status="analyzing", progress=50)
            result = self._insight_json(
                "/api/demo/parse-multi?filename=" + urllib.parse.quote(demo_path.name)
                + "&path=" + urllib.parse.quote(str(demo_path)),
                {"target_players": [target["nickname"]], "locale": "zh"}, timeout=600,
            )
            players = result.get("players") if isinstance(result, dict) else {}
            analyzed = players.get(target["nickname"]) if isinstance(players, dict) else None
            if not isinstance(analyzed, dict):
                raise RuntimeError("Insight 未在 Demo 中找到该玩家，请确认完美昵称与 Demo 一致")
            clips = analyzed.get("clips") if isinstance(analyzed.get("clips"), list) else []
            events = []
            for clip in clips:
                if not isinstance(clip, dict):
                    continue
                event = {
                    "round": clip.get("round"), "start_tick": clip.get("start_tick"), "end_tick": clip.get("end_tick"),
                    "category": clip.get("category"), "kills": clip.get("kill_count"), "weapon": clip.get("weapon_used"),
                    "victims": clip.get("victims") or [], "tags": clip.get("context_tags") or [],
                    "comment": clip.get("ai_commentary") or "", "raw_clip": clip,
                    "score_own": clip.get("score_own"), "score_opp": clip.get("score_opp"),
                    "round_won": clip.get("round_won"), "kill_ticks": clip.get("kill_ticks") or [],
                    "source_rounds": clip.get("source_rounds") or [], "killer_name": clip.get("killer_name"),
                }
                event["event_key"] = stable_event_key(event)
                events.append(event)
            self.repo.update_job(job_id, status="awaiting_clip_selection", progress=55, events=events)
        except Exception as exc:
            self.repo.update_job(job_id, status="failed", error=str(exc))

    def _insight_json(self, path, payload, timeout=60):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.config["insight_base_url"].rstrip("/") + path, data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Insight 请求失败 ({exc.code}): {detail}") from exc

    def insight_settings(self):
        request = urllib.request.Request(self.config["insight_base_url"].rstrip("/") + "/api/config")
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = json.loads(response.read().decode("utf-8"))
        keys = ("cs2_path", "ffmpeg_path", "ai_mode", "locale", "recording_global_pacing", "default_record_warmup",
                "obs_transition_enabled", "obs_transition_name", "obs_transition_duration_ms", "kb_overlay_enabled",
                "kb_overlay_tick_offset", "kb_overlay_position", "kill_fx_enabled", "kill_fx_tick_offset", "montage_encoder")
        return {key: raw.get(key) for key in keys}

    def update_insight_settings(self, values):
        allowed = {"cs2_path", "ffmpeg_path", "ai_mode", "locale", "recording_global_pacing", "default_record_warmup",
                   "obs_transition_enabled", "obs_transition_name", "obs_transition_duration_ms", "kb_overlay_enabled",
                   "kb_overlay_tick_offset", "kb_overlay_position", "kill_fx_enabled", "kill_fx_tick_offset", "montage_encoder"}
        payload = {key: value for key, value in values.items() if key in allowed}
        if not payload:
            raise ValueError("没有可保存的视频制作设置")
        return self._insight_request("/api/config", payload, "PUT")

    def _insight_request(self, path, payload, method):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.config["insight_base_url"].rstrip("/") + path, data=body,
                                         headers={"Content-Type": "application/json"}, method=method)
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))

    def render(self, job_id, owner, payload):
        job = self.get_job(job_id, owner)
        if job["status"] != "awaiting_clip_selection": raise ValueError("任务当前不能提交片段")
        keys = payload.get("event_keys") or []
        valid = {e["event_key"] for e in job["events"]}
        if not keys or len(keys) > int(self.config["max_events_per_job"]) or any(k not in valid for k in keys):
            raise ValueError("片段选择无效或超过数量限制")
        preset_ids = {p["id"] for p in self.config["presets"]}
        targets = {t["id"] if isinstance(t, dict) else t for t in self.config["wechat_targets"]}
        if payload.get("preset_id") not in preset_ids or payload.get("wechat_target") not in targets:
            raise ValueError("输出预设或微信目标不在白名单中")
        return self.repo.update_job(job_id, status="queued_recording", progress=60, selection=keys, output=payload)

    def cancel(self, job_id, owner, admin=False):
        job = self.get_job(job_id, owner, admin)
        if job["status"] in {"completed", "cancelled"}: return job
        return self.repo.update_job(job_id, status="cancelled", error=None)

    def retry(self, job_id, owner, admin=False):
        job = self.get_job(job_id, owner, admin)
        if job["status"] not in {"failed", "sending_unknown"}: raise ValueError("任务当前不可重试")
        self.repo.update_job(job_id, status="downloading", progress=5, error=None)
        threading.Thread(target=self._prepare_job, args=(job_id,), daemon=True).start()
        return self.repo.get_job(job_id)

    def get_job(self, job_id, owner, admin=False):
        row = self.repo.get_job(job_id); self._owned(row, owner, admin); return row

    def list_jobs(self, owner, admin=False): return self.repo.list_jobs(None if admin else owner)

    def _require_player(self, player_id):
        if str(player_id) not in {p["steamid"] for p in self._players()}: raise ValueError("玩家不在允许列表中")

    @staticmethod
    def _owned(row, owner, admin):
        if not row: raise KeyError("记录不存在")
        if not admin and row["owner"] != owner: raise PermissionError("无权访问此记录")
