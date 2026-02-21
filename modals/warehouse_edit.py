import discord
from discord.ui import Modal, TextInput, Select, View
import logging
from data.warehouse_items import WAREHOUSE_ITEMS
from services.warehouse_session import WarehouseSession

logger = logging.getLogger(__name__)

class WarehouseEditModal(Modal):
    """Модалка для редактирования количества"""
    
    def __init__(self, category: str, item_name: str, current_quantity: int, item_index: int):
        super().__init__(title=f"✏️ Редактирование: {item_name}")
        self.category = category
        self.item_name = item_name
        self.item_index = item_index
        self.current_quantity = current_quantity
        
        # Получаем максимальное количество
        item_data = WAREHOUSE_ITEMS[category]["items"][item_name]
        if isinstance(item_data, int):
            max_value = item_data
        else:
            max_value = item_data.get("max", 999)
        
        self.quantity = TextInput(
            label=f"Количество (макс {max_value}):",
            placeholder=f"Текущее: {current_quantity}",
            default=str(current_quantity),
            required=True,
            min_length=1,
            max_length=4
        )
        self.add_item(self.quantity)
    
    async def on_submit(self, interaction: discord.Interaction):
        """Сохраняем изменения"""
        try:
            new_quantity = int(self.quantity.value)
            
            # Проверяем лимиты
            item_data = WAREHOUSE_ITEMS[self.category]["items"][self.item_name]
            if isinstance(item_data, int):
                max_value = item_data
            else:
                max_value = item_data.get("max", 999)
            
            if new_quantity > max_value:
                await interaction.response.send_message(
                    f"❌ Нельзя больше {max_value}!",
                    ephemeral=True
                )
                return
            
            if new_quantity < 1:
                await interaction.response.send_message(
                    "❌ Количество должно быть хотя бы 1",
                    ephemeral=True
                )
                return
            
            # Получаем корзину
            items = WarehouseSession.get_items(interaction.user.id)
            
            # Обновляем количество
            if 0 <= self.item_index < len(items):
                items[self.item_index]["quantity"] = new_quantity
                logger.info(f"✅ {interaction.user.id} изменил {self.item_name} с {self.current_quantity} на {new_quantity}")
                
                await interaction.response.send_message(
                    f"✅ Количество изменено: {self.item_name} → {new_quantity} шт",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "❌ Ошибка: предмет не найден",
                    ephemeral=True
                )
            
        except ValueError:
            await interaction.response.send_message("❌ Введи число!", ephemeral=True)
        except Exception as e:
            logger.error(f"Ошибка при редактировании: {e}")
            await interaction.response.send_message("❌ Ошибка", ephemeral=True)