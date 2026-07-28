import asyncio
import unittest
from unittest.mock import patch

from app.recording.executor import gsi_verifier


class GSIVerifierTests(unittest.TestCase):
    def test_current_player_prefers_player_steamid_over_observer_slot(self):
        with patch.object(
            gsi_verifier,
            "gsi_status",
            return_value={
                "last_payload": {
                    "player": {"steamid": "76561198000000001"},
                    "allplayers": {
                        "76561198000000002": {"observer_slot": 0, "name": "POV"},
                    },
                },
            },
        ):
            actual = asyncio.run(gsi_verifier.get_current_player_steamid())

        self.assertEqual(actual, "76561198000000001")

    def test_current_player_uses_observed_allplayer_key_when_player_is_missing(self):
        with patch.object(
            gsi_verifier,
            "gsi_status",
            return_value={
                "last_payload": {
                    "allplayers": {
                        "76561198000000002": {"observerSlot": "0", "name": "POV"},
                    },
                },
            },
        ):
            actual = asyncio.run(gsi_verifier.get_current_player_steamid())

        self.assertEqual(actual, "76561198000000002")

    def test_verify_rejects_correct_but_stale_payload(self):
        with patch.object(
            gsi_verifier,
            "gsi_status",
            return_value={
                "last_payload_at": 100.0,
                "last_payload": {"player": {"steamid": "76561198000000001"}},
            },
        ):
            verified = asyncio.run(
                gsi_verifier.verify_spec_target(
                    "76561198000000001", max_retries=1, after_payload_at=100.0,
                )
            )

        self.assertFalse(verified)

    def test_verify_accepts_new_payload_after_command(self):
        with patch.object(
            gsi_verifier,
            "gsi_status",
            return_value={
                "last_payload_at": 101.0,
                "last_payload": {"player": {"steamid": "76561198000000001"}},
            },
        ):
            verified = asyncio.run(
                gsi_verifier.verify_spec_target(
                    "76561198000000001", max_retries=1, after_payload_at=100.0,
                )
            )

        self.assertTrue(verified)


if __name__ == "__main__":
    unittest.main()
