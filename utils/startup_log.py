
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Ширина баннера (подгон под консоль)
_WIDTH = 52


def _line_top() -> str:
    return "╔" + "═" * (_WIDTH - 2) + "╗"


def _line_bottom() -> str:
    return "╚" + "═" * (_WIDTH - 2) + "╝"


def _pad(text: str, width: int) -> str:
    if len(text) > width:
        return text[: width - 2] + ".."
    return text.ljust(width)


def banner_start() -> None:
    logger.info(_line_top())
    logger.info("║ %s ║", _pad("БОТ УВД — ЗАПУСК", _WIDTH - 4))
    logger.info(_line_bottom())


def section(title: str) -> None:
    logger.info("")
    logger.info("  ▶ %s", title)
    logger.info("  %s", "─" * (_WIDTH - 2))


def step(message: str, detail: Optional[str] = None) -> None:
    if detail:
        logger.info("    • %s — %s", message, detail)
    else:
        logger.info("    • %s", message)


def banner_ready(bot_user: str, guild_name: Optional[str] = None, guild_id: Optional[int] = None) -> None:
    inner_w = _WIDTH - 4
    logger.info("")
    logger.info(_line_top())
    logger.info("║ %s ║", _pad("БОТ ГОТОВ К РАБОТЕ", inner_w))
    logger.info("║ %s ║", " " * inner_w)
    logger.info("║ %s ║", _pad(bot_user, inner_w))
    if guild_name or guild_id:
        server = guild_name or "Сервер"
        if guild_id:
            server += f" (ID: {guild_id})"
        logger.info("║ %s ║", _pad(server, inner_w))
    logger.info(_line_bottom())
