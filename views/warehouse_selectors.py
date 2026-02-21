import discord
from discord.ui import Select, View
import logging
from data.warehouse_items import WAREHOUSE_ITEMS, CATEGORY_EMOJIS
from modals.warehouse_request import QuantityModal

logger = logging.getLogger(__name__)


class CategorySelect(Select):
    """Выбор категории"""

    def __init__(self, session_key=None, request_owner_id: int | None = None, editing_request_message_id: int | None = None):
        self.session_key = session_key
        self.request_owner_id = request_owner_id
        self.editing_request_message_id = editing_request_message_id

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

        view = View(timeout=180)
        view.add_item(
            ItemSelect(
                category,
                session_key=self.session_key,
                request_owner_id=self.request_owner_id,
                editing_request_message_id=self.editing_request_message_id,
            )
        )

        await interaction.response.edit_message(
            content=f"**Категория: {category}**\nТеперь выбери предмет:",
            view=view
        )


class ItemSelect(Select):
    """Выбор предмета в категории"""

    def __init__(self, category: str, session_key=None, request_owner_id: int | None = None, editing_request_message_id: int | None = None):
        self.category = category
        self.session_key = session_key
        self.request_owner_id = request_owner_id
        self.editing_request_message_id = editing_request_message_id

        options = []

        item_emojis = {
            "Кольт M16": "🔫",
            "AK-12": "🔫",
            "Канада": "🔫",
            "Револьвер MK2": "🔫",
            "Пулемет M249": "🔫",
            "Средний бронежилет": "🛡️",
            "Тяжелый бронежилет": "🛡️",
            "Аптечка": "💊",
            "Обезболивающее": "💊",
            "Дефибриллятор": "⚡",
            "Патроны (стак 360)": "🔴",
            "Бодикамера": "📹",
            "Материалы": "🔧"
        }

        for item_name in WAREHOUSE_ITEMS[category]["items"].keys():
            item_data = WAREHOUSE_ITEMS[category]["items"][item_name]
            emoji = item_emojis.get(item_name, "📦")

            if isinstance(item_data, int):
                description = f"Доступно: {item_data} шт"
            else:
                description = item_data.get('description', f"Доступно: {item_data.get('max')} {item_data.get('unit', 'шт')}")

            options.append(
                discord.SelectOption(
                    label=f"{emoji} {item_name}",
                    value=item_name,
                    description=description,
                    emoji=emoji
                )
            )

        super().__init__(
            placeholder="📋 Выбери предмет из списка...",
            options=options,
            custom_id="warehouse_item"
        )

    async def callback(self, interaction: discord.Interaction):
        """Когда выбрали предмет - открываем модалку с количеством"""
        item_name = self.values[0]
        logger.info(f"Выбран предмет: {item_name}")

        modal = QuantityModal(
            self.category,
            item_name,
            session_key=self.session_key,
            request_owner_id=self.request_owner_id,
            editing_request_message_id=self.editing_request_message_id,
        )
        await interaction.response.send_modal(modal)