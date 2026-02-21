import discord
from discord.ui import Select, View
import logging
from data.warehouse_items import WAREHOUSE_ITEMS, CATEGORY_EMOJIS
from modals.warehouse_request import QuantityModal

logger = logging.getLogger(__name__)

class CategorySelect(Select):
    """Выбор категории"""
    
    def __init__(self):
        options = []
        for cat_name in WAREHOUSE_ITEMS.keys():
            emoji = CATEGORY_EMOJIS.get(cat_name, "📦")
            options.append(
                discord.SelectOption(
                    label=cat_name,
                    value=cat_name,
                    emoji=emoji,
                    description=f"Выбрать {cat_name.lower()}"
                )
            )
        
        super().__init__(
            placeholder="🔽 1. Выбери категорию...",
            options=options,
            custom_id="warehouse_category"
        )
    
    async def callback(self, interaction: discord.Interaction):
        """Когда выбрали категорию - показываем предметы"""
        category = self.values[0]
        
        # Создаем новый View с выбором предметов
        view = View(timeout=180)
        view.add_item(ItemSelect(category))
        
        await interaction.response.edit_message(
            content=f"**Категория: {category}**\nТеперь выбери предмет:",
            view=view
        )

class ItemSelect(Select):
    """Выбор предмета в категории"""
    
    def __init__(self, category: str):
        self.category = category
        options = []
        
        for item_name in WAREHOUSE_ITEMS[category]["items"].keys():
            # Получаем лимит для подписи
            item_data = WAREHOUSE_ITEMS[category]["items"][item_name]
            if isinstance(item_data, int):
                limit = f"макс {item_data}"
            else:
                limit = f"макс {item_data.get('max')} {item_data.get('unit', 'шт')}"
            
            options.append(
                discord.SelectOption(
                    label=item_name,
                    value=item_name,
                    description=limit
                )
            )
        
        super().__init__(
            placeholder="🔽 2. Выбери предмет...",
            options=options,
            custom_id="warehouse_item"
        )
    
    async def callback(self, interaction: discord.Interaction):
        """Когда выбрали предмет - открываем модалку с количеством"""
        item_name = self.values[0]
        
        # Открываем модалку для ввода количества
        modal = QuantityModal(self.category, item_name)
        await interaction.response.send_modal(modal)