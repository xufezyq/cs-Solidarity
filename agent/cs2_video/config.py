import json
from pathlib import Path


DEFAULTS = {
    "enabled": True,
    "downloader_config_path": "Plugins/CS2Video/third_party/cs-demo-downloader/config.jsonc",
    "insight_project_dir": "Plugins/CS2Video/third_party/cs2-insight-agent",
    "insight_base_url": "http://127.0.0.1:19871",
    "insight_auto_start": True,
    "bot_base_url": "http://127.0.0.1:18800",
    "demo_dir": "data/cs2-video/demos",
    "export_dir": "data/cs2-video/exports",
    "allowed_player_ids": [],
    "wechat_targets": [],
    "max_active_jobs_per_user": 2,
    "max_events_per_job": 20,
    "max_output_mib": 200,
    "match_query_limit": 10,
    "presets": [
        {"id": "highlight-16x9", "label": "Highlight 16:9", "width": 1920, "height": 1080, "fps": 60},
        {"id": "shorts-9x16", "label": "Shorts 9:16", "width": 1080, "height": 1920, "fps": 60},
    ],
    "packaging_presets": [{"id": "clean", "label": "简洁"}],
    "bgm_presets": [{"id": "none", "label": "无 BGM"}],
    # CS2 录制期间窗口守护：把 CS2 主窗口拉到前台，避免 Win11 对后台窗口
    # 降级渲染（限帧、降 GPU 优先级）导致 Insight 录屏卡顿。
    "cs2_window_guard_enabled": True,
    "cs2_window_guard_interval_sec": 1.5,
    # Do not record a nominal 60 FPS preset while OBS is actually running at
    # 30 FPS.  That produces a valid file, but motion is visibly stuttery.
    "obs_fps_preflight_enabled": True,
}


def load_config(root: Path) -> dict:
    path = root / "instconfig" / "cs2_video_config.json"
    data = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    cfg = {**DEFAULTS, **data}
    for key in ("demo_dir", "export_dir", "downloader_config_path", "insight_project_dir"):
        value = Path(cfg[key])
        cfg[key] = str(value if value.is_absolute() else (root / value).resolve())
    return cfg
