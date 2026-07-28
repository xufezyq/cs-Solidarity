import unittest

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


if __name__ == "__main__":
    unittest.main()
