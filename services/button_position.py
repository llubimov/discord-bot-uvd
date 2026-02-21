"""
LEGACY-ОБЁРТКА:
Старый модуль оставлен для совместимости импортов.

Актуальная реализация:
- services.warehouse_position_manager.WarehousePositionManager
"""

import logging
from .warehouse_position_manager import WarehousePositionManager as _NewWarehousePositionManager

logger = logging.getLogger(__name__)


class ButtonPositionManager(_NewWarehousePositionManager):
    """
    Совместимость со старым именем класса ButtonPositionManager.
    Использует новую реализацию склада из warehouse_position_manager.py
    """
    def __init__(self, bot):
        logger.warning(
            "⚠️ Используется legacy-модуль services.button_position. "
            "Рекомендуется импортировать services.warehouse_position_manager"
        )
        super().__init__(bot)