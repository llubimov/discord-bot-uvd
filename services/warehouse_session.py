from typing import Dict, List, Any, Tuple
from datetime import datetime
import logging
from data.warehouse_items import WAREHOUSE_ITEMS

logger = logging.getLogger(__name__)

user_sessions: Dict[int, Dict[str, Any]] = {}

class WarehouseSession:
    """Работа с корзиной пользователя"""
    
    @staticmethod
    def get_session(user_id: int) -> Dict:
        if user_id not in user_sessions:
            user_sessions[user_id] = {
                "items": [],
                "created_at": datetime.now()
            }
        return user_sessions[user_id]
    
    @staticmethod
    def add_item(user_id: int, category: str, item_name: str, quantity: int) -> Tuple[bool, str]:
        session = WarehouseSession.get_session(user_id)
        
        # Получаем данные из warehouse_items.py
        category_data = WAREHOUSE_ITEMS[category]
        item_limit = category_data["items"][item_name]
        
        # Определяем максимальное количество для этого предмета
        if isinstance(item_limit, dict):
            max_item = item_limit["max"]
        else:
            max_item = item_limit  # Вот тут будет 1 для револьвера и пулемета!
        
        # Считаем сколько уже есть ЭТОГО ЖЕ предмета
        текущее_колво = 0
        for item in session["items"]:
            if item["category"] == category and item["item"] == item_name:
                текущее_колво += item["quantity"]
        
        # ПРОВЕРКА: не больше чем в warehouse_items.py
        if текущее_колво + quantity > max_item:
            return False, f"❌ Нельзя взять больше **{max_item}** {item_name} в один запрос!"
        
        # Проверка общего лимита категории (3 для оружия, 20 для брони)
        if "max_total" in category_data:
            общее_в_категории = 0
            for item in session["items"]:
                if item["category"] == category:
                    общее_в_категории += item["quantity"]
            
            if общее_в_категории + quantity > category_data["max_total"]:
                return False, f"❌ Нельзя взять больше **{category_data['max_total']}** предметов в категории {category}!"
        
        # Добавляем в корзину
        session["items"].append({
            "category": category,
            "item": item_name,
            "quantity": quantity
        })
        
        return True, ""
    
    @staticmethod
    def get_items(user_id: int) -> List[Dict]:
        session = WarehouseSession.get_session(user_id)
        return session["items"]
    
    @staticmethod
    def clear_session(user_id: int):
        if user_id in user_sessions:
            del user_sessions[user_id]
    
    @staticmethod
    def remove_item(user_id: int, index: int) -> bool:
        session = WarehouseSession.get_session(user_id)
        if 0 <= index < len(session["items"]):
            session["items"].pop(index)
            return True
        return False