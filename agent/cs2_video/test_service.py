import unittest
import json
import tempfile
from pathlib import Path
from unittest import mock

from agent.cs2_video.service import CS2VideoService


class _Repo:
    def get_query(self, _query_id):
        return {
            "matches": [{
                "match_id": "PVP@42",
                "map": "de_mirage",
                "score": "13 : 9",
                "result": "胜利",
                "stats": {"kills": 20, "deaths": 11, "assists": 7, "rating": 1.23, "we": 8.5},
            }],
        }


class CS2VideoServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = CS2VideoService.__new__(CS2VideoService)
        self.service.root = __import__("pathlib").Path("D:/code/cs-Solidarity")
        self.service.repo = _Repo()
        self.service.config = {
            "bot_base_url": "http://127.0.0.1:18800",
            "packaging_presets": [{
                "id": "branded",
                "intro_path": "assets/intro.mp4",
                "outro_path": "assets/outro.mp4",
                "theme_id": "match",
            }],
            "bgm_presets": [{"id": "rock", "path": "assets/bgm.mp3", "bgm_volume": 0.35}],
        }
        self.service._players = lambda: [{"steamid": "765", "nickname": "皮干侠"}]

    def test_export_selection_becomes_montage_options(self):
        result = self.service._export_options({"packaging_id": "branded", "bgm_id": "rock"})

        self.assertEqual(result["theme_id"], "match")
        self.assertEqual(result["bgm_volume"], 0.35)
        self.assertTrue(result["bgm_path"].endswith("assets\\bgm.mp3"))
        self.assertTrue(result["intro_path"].endswith("assets\\intro.mp4"))

    def test_players_prefer_steam_avatar_and_fall_back_to_perfect_world(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "instconfig").mkdir()
            (root / "instconfig" / "steam_data.json").write_text(json.dumps({
                "monitored_friends": [
                    {"steamid": "1", "personaname": "Steam", "avatar": "steam-avatar"},
                    {"steamid": "2", "personaname": "PW", "avatar": ""},
                ],
                "friend_pw_history_stats": {
                    "1": {"avatar": "pw-avatar"},
                    "2": {"avatar": "pw-fallback"},
                },
            }), encoding="utf-8")
            self.service.root = root
            self.service.config["allowed_player_ids"] = []
            self.service._players = CS2VideoService._players.__get__(self.service)

            players = self.service._players()

        self.assertEqual(players[0]["avatar"], "steam-avatar")
        self.assertEqual(players[1]["avatar"], "pw-fallback")

    def test_demo_player_name_uses_roster_steam_id(self):
        self.service._insight_json = lambda *_args, **_kwargs: {
            "uploads": [{"players": [
                {"name": "Current Demo Name", "steam_id": "765"},
                {"name": "Another Player", "steam_id": "999"},
            ]}],
        }

        self.assertEqual(
            self.service._demo_player_name("fixture.dem", "765"),
            "Current Demo Name",
        )

    def test_demo_player_name_rejects_missing_steam_id(self):
        self.service._insight_json = lambda *_args, **_kwargs: {
            "uploads": [{"players": [{"name": "Wrong Player", "steam_id": "999"}]}],
        }

        with self.assertRaisesRegex(RuntimeError, "765"):
            self.service._demo_player_name("fixture.dem", "765")

    @mock.patch("agent.cs2_video.service.time.sleep")
    def test_wait_for_insight_starts_service_and_waits_until_ready(self, _sleep):
        self.service.config["insight_base_url"] = "http://127.0.0.1:19871"
        self.service._health = mock.Mock(side_effect=[False, False, True])
        self.service._ensure_insight = mock.Mock()

        self.service._wait_for_insight(timeout=1)

        self.service._ensure_insight.assert_called_once_with()
        _sleep.assert_called_once_with(0.25)

    def test_wait_for_insight_reports_clear_error_when_unavailable(self):
        self.service.config["insight_base_url"] = "http://127.0.0.1:19871"
        self.service._health = mock.Mock(return_value=False)
        self.service._ensure_insight = mock.Mock()

        with self.assertRaisesRegex(RuntimeError, "Insight 服务未就绪"):
            self.service._wait_for_insight(timeout=0)

    def test_delivery_summary_contains_requested_traceability(self):
        summary = self.service._delivery_summary({
            "owner": "alice",
            "query_id": "query-1",
            "match_id": "PVP@42",
            "player_id": "765",
            "selection": ["event-1"],
            "events": [{
                "event_key": "event-1",
                "round": 8,
                "category": "highlight",
                "kills": 3,
                "weapon": "AK-47",
                "victims": ["Bob", "Carol"],
                "comment": "残局三杀",
            }],
        })

        for expected in ("alice", "PVP@42", "皮干侠", "20 / 11 / 7", "RT：1.23", "WE：8.5", "第 8 回合", "残局三杀"):
            self.assertIn(expected, summary)

    @mock.patch("agent.cs2_video.service.urllib.request.urlopen")
    def test_video_summary_is_forced_during_maintenance(self, urlopen):
        response = mock.MagicMock()
        response.read.return_value = b'{"success": true}'
        urlopen.return_value.__enter__.return_value = response

        self.service._send_text("target", "summary")

        request = urlopen.call_args.args[0]
        self.assertIs(json.loads(request.data)["force"], True)

    @mock.patch("agent.cs2_video.service.urllib.request.urlopen")
    def test_video_file_is_forced_during_maintenance(self, urlopen):
        response = mock.MagicMock()
        response.read.return_value = b'{"success": true}'
        urlopen.return_value.__enter__.return_value = response
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "clip.mp4"
            video.write_bytes(b"video")

            self.service._send_video("target", str(video))

        request = urlopen.call_args.args[0]
        self.assertIn(b'name="force"\r\n\r\ntrue\r\n', request.data)


if __name__ == "__main__":
    unittest.main()
