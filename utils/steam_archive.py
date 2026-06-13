"""Steam season data archive helpers."""

import json
from datetime import datetime
from pathlib import Path


def archive_pw_season_data(data_path: str) -> str:
    """Archive PW season stats from steam_data.json and return archive path."""
    data_file = Path(data_path)
    archive_dir = data_file.parent / "steam_data_archives"
    archive_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = archive_dir / f"season_{timestamp}.json"

    config = {}
    if data_file.exists():
        with open(data_file, "r", encoding="utf-8") as f:
            config = json.load(f)

    archive_data = {
        "archived_at": datetime.now().isoformat(),
        "friend_pw_history_stats": config.get("friend_pw_history_stats", {}),
        "friend_pw_leaderboard": config.get("friend_pw_leaderboard", {}),
        "friend_5e_history_stats": config.get("friend_5e_history_stats", {}),
        "friend_official_history_stats": config.get("friend_official_history_stats", {}),
    }

    with open(archive_path, "w", encoding="utf-8") as f:
        json.dump(archive_data, f, ensure_ascii=False, indent=2)

    return str(archive_path)
