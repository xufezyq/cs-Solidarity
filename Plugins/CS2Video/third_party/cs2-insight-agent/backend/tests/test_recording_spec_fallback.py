import unittest
from unittest.mock import AsyncMock, patch

from app.recording.executor import recording_executor as executor
from app.recording.executor import spec_controller
from app.recording.models import Perspective, RecordingSegment, SourceType


class SpecFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_verified_offset_and_marks_it_for_resync(self):
        slot_switch = AsyncMock(return_value=True)
        verify = AsyncMock(side_effect=[False, False, True])

        with (
            patch.object(executor, "spec_by_slot", slot_switch),
            patch.object(executor, "verify_spec_target", verify),
            patch.object(executor, "get_last_gsi_payload_at", side_effect=[10.0, 11.0, 12.0]),
        ):
            result = await executor._spec_by_slot_with_retry(
                9, "target", "76561198383859685", [], 0,
            )

        self.assertTrue(result.verified)
        self.assertEqual(result.selected_slot, 10)
        self.assertEqual([call.args[0] for call in slot_switch.await_args_list], [9, 8, 10])
        self.assertEqual(
            [call.kwargs["after_payload_at"] for call in verify.await_args_list],
            [10.0, 11.0, 12.0],
        )

    async def test_injection_failure_never_verifies_stale_gsi_data(self):
        slot_switch = AsyncMock(return_value=False)
        name_switch = AsyncMock(return_value=False)
        verify = AsyncMock()

        with (
            patch.object(executor, "spec_by_slot", slot_switch),
            patch.object(executor, "spec_player", name_switch),
            patch.object(executor, "verify_spec_target", verify),
        ):
            result = await executor._spec_by_slot_with_retry(
                9, "target", "76561198383859685", [], 0,
            )

        self.assertFalse(result.verified)
        self.assertEqual(slot_switch.await_count, 7)
        name_switch.assert_awaited_once_with("target")
        verify.assert_not_awaited()

    async def test_silent_gsi_refuses_unverified_pov(self):
        with (
            patch.object(executor, "spec_by_slot", AsyncMock(return_value=True)),
            patch.object(executor, "verify_spec_target", AsyncMock(return_value=None)),
            patch.object(executor, "get_last_gsi_payload_at", return_value=10.0),
        ):
            result = await executor._spec_by_slot_with_retry(
                9, "target", "76561198383859685", [], 0,
            )

        self.assertFalse(result.verified)


class ExecutionCompletionTests(unittest.TestCase):
    def test_partial_capture_is_not_a_success(self):
        segment = RecordingSegment(
            segment_index=0,
            source_type=SourceType.kill,
            start_tick=1,
            end_tick=2,
            target_player_name="target",
            target_steamid64="76561198383859685",
            perspective=Perspective.killer,
            safe_seek_tick=0,
        )
        ok = executor.SegmentResult(0, "ok", 1, 2, Perspective.killer)
        failed = executor.SegmentResult(1, "spec_failed", 3, 4, Perspective.killer)

        self.assertFalse(executor._completed_all_active_segments([segment], [ok, failed]))
        self.assertTrue(executor._completed_all_active_segments([segment], [ok]))


class SpecControllerTests(unittest.IsolatedAsyncioTestCase):
    async def test_name_command_is_quoted_and_reports_delivery(self):
        with patch.object(spec_controller, "inject_console_sequence", return_value=True) as inject:
            delivered = await spec_controller.spec_player("Player Name", settle=0)

        self.assertTrue(delivered)
        inject.assert_called_once_with(["spec_mode 5", 'spec_player "Player Name"'])

    async def test_false_console_delivery_is_propagated(self):
        with patch.object(spec_controller, "inject_console_sequence", return_value=False) as inject:
            delivered = await spec_controller.spec_by_slot(9, settle=0)

        self.assertFalse(delivered)
        inject.assert_called_once_with(["spec_mode 5", "spec_player 9"])


if __name__ == "__main__":
    unittest.main()
