import unittest
from pathlib import Path

from agent.cs2_video.repository import Repository
from agent.cs2_video.service import sanitize_match, sanitize_pw_match, stable_event_key
from bot.api_server import _allowed_export_file


class CS2VideoTests(unittest.TestCase):
    def test_stable_event_key_ignores_random_clip_id(self):
        base = {"round": 4, "start_tick": 100, "end_tick": 200, "kills": 3, "weapon": "ak47"}
        self.assertEqual(stable_event_key({**base, "clip_id": "a"}), stable_event_key({**base, "clip_id": "b"}))
        self.assertNotEqual(stable_event_key(base), stable_event_key({**base, "round": 5}))

    def test_match_is_allowlisted(self):
        match = sanitize_match({"matchId": "secret-id", "mapName": "de_mirage", "token": "do-not-leak", "signature": "no"})
        self.assertEqual(set(match), {"match_id", "map", "played_at", "score", "result", "demo_available", "ladder_score", "is_mvp", "details_loaded"})
        self.assertNotIn("token", str(match))

    def test_match_does_not_treat_mvp_as_win(self):
        match = sanitize_match({"raw_summary": {"match": "m", "is_mvp": True}, "match_id": "m"})
        self.assertIsNone(match["result"])
        self.assertTrue(match["is_mvp"])

    def test_match_uses_report_team_scores(self):
        match = sanitize_match({
            "match_id": "m", "details_loaded": True,
            "teams": [{"name": "T", "score": 13}, {"name": "CT", "score": 11}],
        })
        self.assertEqual(match["score"], "T 13 : CT 11")

    def test_pw_match_exposes_map_score_and_player_result(self):
        match = sanitize_pw_match({"matchId": "m", "mapName": "炼狱小镇", "score1": 13, "score2": 8,
                                   "team": 2, "winTeam": 2, "endTime": "2026-07-26 12:00:00", "pvpScore": 2040,
                                   "pvpScoreChange": 18, "duration": 39, "kill": 21, "death": 14, "assist": 6,
                                   "rating": 1.18, "pwRating": 1.27, "we": 14.6})
        self.assertEqual(match["map"], "炼狱小镇")
        self.assertEqual(match["score"], "13 : 8")
        self.assertEqual(match["result"], "胜利")
        self.assertEqual(match["stats"], {"kills": 21, "deaths": 14, "assists": 6, "rating": 1.18, "pw_rating": 1.27, "we": 14.6})
        self.assertEqual(match["ladder_change"], 18)

    def test_repository_owner_filter(self):
        repo = Repository(Path(":memory:"))
        repo.create_query("q", "alice", "1")
        repo.finish_query("q", [{"match_id": "m"}])
        repo.create_job("j", "alice", "q", "m", "1")
        self.assertEqual(len(repo.list_jobs("alice")), 1)
        self.assertEqual(repo.list_jobs("bob"), [])

    def test_local_file_rejects_outside_export_dir(self):
        with self.assertRaises(ValueError):
            _allowed_export_file(str(Path(__file__).resolve()))


if __name__ == "__main__":
    unittest.main()
