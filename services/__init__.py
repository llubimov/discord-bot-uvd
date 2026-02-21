"""
Глобальные сервисы
"""
from .warehouse_cooldown import WarehouseCooldown

# Создаем глобальный экземпляр кулдауна
warehouse_cooldown = WarehouseCooldown()