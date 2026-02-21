from typing import Dict, List, Any, Tuple, Hashable
from datetime import datetime
import logging
from data.warehouse_items import WAREHOUSE_ITEMS

logger = logging.getLogger(__name__)

# Ключ сессии может быть как user_id (int), так и строковый ключ для спец-сценариев
# (например редактирование чужой заявки без затирания своей корзины)
user_sessions: Dict[Hashable, Dict[str, Any]] = {}


class WarehouseSession:
    """Работа с корзиной пользователя / временной сессией склада"""

    @staticmethod
    def get_session(session_key: Hashable) -> Dict[str, Any]:
        if session_key not in user_sessions:
            user_sessions[session_key] = {
                "items": [],
                "created_at": datetime.now(),
            }
        return user_sessions[session_key]

    @staticmethod
    def set_items(session_key: Hashable, items: List[Dict[str, Any]]):
        """Полностью заменяет содержимое корзины (с копией списка)."""
        session = WarehouseSession.get_session(session_key)
        session["items"] = [dict(item) for item in (items or [])]

    @staticmethod
    def add_item(session_key: Hashable, category: str, item_name: str, quantity: int) -> Tuple[bool, str]:
        session = WarehouseSession.get_session(session_key)

        # Получаем данные из warehouse_items.py
        category_data = WAREHOUSE_ITEMS[category]
        item_limit = category_data["items"][item_name]

        # Определяем максимальное количество для этого предмета
        if isinstance(item_limit, dict):
            max_item = int(item_limit.get("max", 0))
        else:
            max_item = int(item_limit)

        # Считаем сколько уже есть ЭТОГО ЖЕ предмета
        current_qty = 0
        for item in session["items"]:
            if item.get("category") == category and item.get("item") == item_name:
                try:
                    current_qty += int(item.get("quantity", 0))
                except (TypeError, ValueError):
                    continue

        # Проверка лимита конкретного предмета
        if current_qty + quantity > max_item:
            return False, f"❌ Нельзя взять больше **{max_item}** {item_name} в один запрос!"

        # Проверка общего лимита категории (например 3 для оружия, 20 для брони)
        if "max_total" in category_data:
            total_in_category = 0
            for item in session["items"]:
                if item.get("category") == category:
                    try:
                        total_in_category += int(item.get("quantity", 0))
                    except (TypeError, ValueError):
                        continue

            max_total = int(category_data["max_total"])
            if total_in_category + quantity > max_total:
                return False, f"❌ Нельзя взять больше **{max_total}** предметов в категории {category}!"

        # Добавляем в корзину
        session["items"].append({
            "category": category,
            "item": item_name,
            "quantity": quantity,
        })

        return True, ""

    @staticmethod
    def get_items(session_key: Hashable) -> List[Dict[str, Any]]:
        session = WarehouseSession.get_session(session_key)
        return session["items"]

    @staticmethod
    def clear_session(session_key: Hashable):
        user_sessions.pop(session_key, None)

    @staticmethod
    def remove_item(session_key: Hashable, index: int) -> bool:
        session = WarehouseSession.get_session(session_key)
        if 0 <= index < len(session["items"]):
            session["items"].pop(index)
            return True
        return False