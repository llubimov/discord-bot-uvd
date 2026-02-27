import discord
from discord.ui import Select, View, Button
import logging
from config import Config
from data.warehouse_items import WAREHOUSE_ITEMS
from modals.warehouse_request import QuantityModal
from services.warehouse_session import WarehouseSession
from views.warehouse_theme import BLUE

logger = logging.getLogger(__name__)


def _embed_add_step1(session_key) -> discord.Embed:
    items = WarehouseSession.get_items(session_key)
    n = len(items)
    embed = discord.Embed(
        title="➕ Добавить позицию",
        description="Выбери **категорию**, затем **предмет** и укажи количество в окне ввода.",
        color=BLUE,
    )
    embed.set_footer(text=f"В корзине: {n} позиций" if n else "Корзина пуста")
    return embed


def _embed_add_step2(session_key, category: str) -> discord.Embed:
    items = WarehouseSession.get_items(session_key)
    n = len(items)
    embed = discord.Embed(
        title=f"📋 {category}",
        description="Выбери предмет из списка. Для другой категории нажми **Другая категория**.",
        color=BLUE,
    )
    embed.set_footer(text=f"В корзине: {n} позиций" if n else "Корзина пуста")
    return embed


class CategorySelect(Select):
    def __init__(self, session_key=None, request_owner_id: int | None = None, editing_request_message_id: int | None = None):
        self.session_key = session_key
        self.request_owner_id = request_owner_id
        self.editing_request_message_id = editing_request_message_id

        options = []
        for cat_name in WAREHOUSE_ITEMS.keys():
            options.append(
                discord.SelectOption(
                    label=cat_name,
                    value=cat_name,
                    description=f"Добавить из категории"
                )
            )

        super().__init__(
            placeholder="Выбери категорию...",
            options=options,
            custom_id="warehouse_category"
        )

    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]
        embed = _embed_add_step2(self.session_key, category)
        view = View(timeout=Config.WAREHOUSE_SUBVIEW_TIMEOUT)
        view.add_item(
            ItemSelect(
                category,
                session_key=self.session_key,
                request_owner_id=self.request_owner_id,
                editing_request_message_id=self.editing_request_message_id,
            )
        )

        async def back_cb(btn_interaction: discord.Interaction):
            if btn_interaction.user.id != interaction.user.id:
                await btn_interaction.response.send_message("❌ Только автор выбора может нажимать.", ephemeral=True)
                return
            step1_embed = _embed_add_step1(self.session_key)
            back_view = View(timeout=Config.WAREHOUSE_SUBVIEW_TIMEOUT)
            back_view.add_item(
                CategorySelect(
                    session_key=self.session_key,
                    request_owner_id=self.request_owner_id,
                    editing_request_message_id=self.editing_request_message_id,
                )
            )
            await btn_interaction.response.edit_message(embed=step1_embed, view=back_view)

        back_btn = Button(
            label="Другая категория",
            style=discord.ButtonStyle.secondary,
            emoji="◀️",
            row=1,
        )
        back_btn.callback = back_cb
        view.add_item(back_btn)

        await interaction.response.edit_message(embed=embed, view=view)


class ItemSelect(Select):
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
                    label=item_name,
                    value=item_name,
                    description=description,
                    emoji=emoji
                )
            )

        super().__init__(
            placeholder="Выбери предмет...",
            options=options,
            custom_id="warehouse_item"
        )

    async def callback(self, interaction: discord.Interaction):
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