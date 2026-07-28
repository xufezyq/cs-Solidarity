import asyncio
import logging
from typing import Optional

from ...gsi_ready import gsi_status

logger = logging.getLogger(__name__)

class SpecVerifyError(Exception):
    pass


def _steamid_from_payload(payload: dict) -> Optional[str]:
    """Read the POV SteamID from one GSI payload."""
    # ``player.steamid`` is the current POV in demo playback.  ``allplayers``
    # observer slots describe the roster and are not a reliable POV signal.
    player = payload.get("player")
    if isinstance(player, dict):
        for key in ("steamid", "steam_id", "xuid", "id"):
            val = player.get(key)
            if val and str(val).strip():
                return str(val).strip()

    # Some GSI payload variants omit player.steamid.  Retain this as a
    # best-effort fallback only; it must never override player.steamid.
    allplayers = payload.get("allplayers")
    if isinstance(allplayers, dict):
        for pid, row in allplayers.items():
            if not isinstance(row, dict):
                continue
            obs = row.get("observer_slot", row.get("observerSlot"))
            if obs == 0 or obs == "0":  # slot 0 = currently spectated
                for key in ("steamid", "steam_id", "xuid", "id"):
                    val = row.get(key)
                    if val and str(val).strip():
                        return str(val).strip()
                if str(pid).strip():
                    return str(pid).strip()
    return None


def get_last_gsi_payload_at() -> Optional[float]:
    """Return the monotonic timestamp of the latest GSI payload, if available."""
    status = gsi_status()
    if not isinstance(status, dict):
        return None
    try:
        value = float(status.get("last_payload_at") or 0.0)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


async def get_current_player_steamid() -> Optional[str]:
    """Read the current spectated player's SteamID from the latest GSI payload."""
    status = gsi_status()
    if not isinstance(status, dict):
        return None
    payload = status.get("last_payload", {})
    if not isinstance(payload, dict) or not payload:
        return None
    return _steamid_from_payload(payload)


async def verify_spec_target(
    expected_steamid64: str,
    max_retries: int = 8,
    retry_interval_sec: float = 0.4,
    *,
    after_payload_at: Optional[float] = None,
) -> "bool | None":
    """
    Poll GSI to verify the current spectated player matches expected_steamid64.

    Returns:
        True  — GSI confirmed we are spectating expected_steamid64
        None  — GSI was silent for all retries (inconclusive; demo may be paused)
        False — GSI returned data but confirmed a different player (wrong spectate)

    ``after_payload_at`` requires a fresh GSI update after the command was
    sent. This prevents a prior correct POV payload from approving a later
    spec_player command that actually changed to the wrong player.
    """
    if not expected_steamid64:
        return True
    last_seen: "str | None" = None
    saw_fresh_payload = after_payload_at is None
    for attempt in range(max_retries):
        status = gsi_status()
        payload = status.get("last_payload", {}) if isinstance(status, dict) else {}
        try:
            payload_at = float(status.get("last_payload_at") or 0.0) if isinstance(status, dict) else 0.0
        except (TypeError, ValueError):
            payload_at = 0.0
        if after_payload_at is not None and payload_at <= after_payload_at:
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_interval_sec)
            continue

        saw_fresh_payload = True
        current = _steamid_from_payload(payload) if isinstance(payload, dict) else None
        if current:
            last_seen = current
            if current == expected_steamid64:
                logger.info(
                    "spec verify passed: expected=%s payload_at=%.6f fresh_after=%s",
                    expected_steamid64,
                    payload_at,
                    after_payload_at,
                )
                return True
            # GSI returned a different player — keep retrying; spec_player may not have
            # taken effect yet even after the initial settle sleep
        if attempt < max_retries - 1:
            await asyncio.sleep(retry_interval_sec)
    # All retries exhausted.
    if last_seen is not None:
        # At least one GSI response consistently showed a different player
        logger.warning(
            "spec verify failed: expected %s, last seen %s after %d retries",
            expected_steamid64, last_seen, max_retries,
        )
        return False
    if after_payload_at is not None and not saw_fresh_payload:
        logger.warning(
            "spec verify failed: no fresh GSI payload after command for %s after %d retries",
            expected_steamid64, max_retries,
        )
        return False
    # GSI was silent throughout (demo paused or GSI not updating)
    logger.debug(
        "spec verify inconclusive for %s: GSI silent after %d retries",
        expected_steamid64, max_retries,
    )
    return None
