"""
LEGACY-ОБЁРТКА:
Старый модуль оставлен для совместимости импортов.

Актуальная реализация:
- services.start_position_manager.StartPositionManager
"""

import logging
from .start_position_manager import StartPositionManager as _NewStartPositionManager

logger = logging.getLogger(__name__)


class StartPositionManager(_NewStartPositionManager):
    """
    Совместимость со старым импортом.
    Использует новую реализацию из start_position_manager.py
    """
    def __init__(self, bot):
        logger.warning(
            "⚠️ Используется legacy-модуль services.start_position. "
            "Рекомендуется импортировать services.start_position_manager"
        )
        super().__init__(bot)