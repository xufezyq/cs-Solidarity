import asyncio
import logging

logger = logging.getLogger(__name__)

try:
    from ...win_cs2_console import inject_console_sequence
except ImportError:
    def inject_console_sequence(lines): pass


def _console_player_name(player_name: str) -> str:
    """Return one quoted CS2 console argument for a demo player name."""
    return '"' + player_name.replace("\\", "\\\\").replace('"', '\\"') + '"'


async def spec_player(player_name: str, mode: int = 5, settle: float = 0.8) -> bool:
    """
    Send spec_mode + spec_player-by-name commands to CS2.
    mode: 5 = first-person (POV), 4 = chase/third-person, 1 = free

    ``True`` only means the commands were delivered to a focused CS2 window.
    Callers must still verify the POV through GSI before recording.
    """
    name = (player_name or "").strip()
    if not name:
        logger.warning("spec_player name is empty; command not sent")
        return False

    cmds = [f"spec_mode {int(mode)}", f"spec_player {_console_player_name(name)}"]
    try:
        injected = await asyncio.to_thread(inject_console_sequence, cmds)
    except Exception as e:
        logger.warning("spec_player %s failed: %s", player_name, e)
        return False
    if injected is not True:
        logger.warning("spec_player name injection returned false for %r", name)
        return False
    if settle > 0:
        await asyncio.sleep(settle)
    return True


async def spec_by_slot(slot: int, mode: int = 5, settle: float = 0.8) -> bool:
    """Send spec_mode + spec_player by numeric slot and report injection status."""
    cmds = [f"spec_mode {mode}", f"spec_player {int(slot)}"]
    try:
        injected = await asyncio.to_thread(inject_console_sequence, cmds)
    except Exception as e:
        logger.warning("spec_player slot %s failed: %s", slot, e)
        return False
    if injected is not True:
        logger.warning("spec_player slot injection returned false for %s", slot)
        return False
    if settle > 0:
        await asyncio.sleep(settle)
    return True
