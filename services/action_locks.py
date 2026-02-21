import asyncio
import logging
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

# message_id -> asyncio.Lock
_locks: dict[int, asyncio.Lock] = {}


def _get_lock(message_id: int) -> asyncio.Lock:
    lock = _locks.get(int(message_id))
    if lock is None:
        lock = asyncio.Lock()
        _locks[int(message_id)] = lock
    return lock


def is_locked(message_id: int) -> bool:
    lock = _locks.get(int(message_id))
    return lock.locked() if lock else False


@asynccontextmanager
async def action_lock(message_id: int, action_name: str = "action"):
    """
    Лок на конкретное сообщение (заявку/рапорт).
    Защищает от двойных нажатий и гонок.
    """
    lock = _get_lock(int(message_id))

    if lock.locked():
        logger.warning(
            "🔒 Повторное действие заблокировано: %s | message_id=%s",
            action_name,
            message_id
        )
        raise RuntimeError("ACTION_ALREADY_IN_PROGRESS")

    await lock.acquire()
    logger.info("🔒 Лок установлен: %s | message_id=%s", action_name, message_id)
    try:
        yield
    finally:
        try:
            lock.release()
            logger.info("🔓 Лок снят: %s | message_id=%s", action_name, message_id)
        except Exception:
            pass