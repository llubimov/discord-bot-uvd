import discord
from discord.ui import Modal, TextInput
import logging
from data.warehouse_items import WAREHOUSE_ITEMS

logger = logging.getLogger(__name__)


class QuantityModal(Modal):
    """Модалка для ввода количества"""

    def __init__(
        self,
        category: str,
        item_name: str,
        session_key=None,
        request_owner_id: int | None = None,
        editing_request_message_id: int | None = None,
    ):
        category_emojis = {
            "оружие": "🔫",
            "бронежилеты": "🛡️",
            "медикаменты": "💊",
            "расходуемое": "📦"
        }
        emoji = category_emojis.get(category.lower(), "📦")

        super().__init__(title=f"{emoji} {category} • {item_name}")
        self.category = category
        self.item_name = item_name
        self.session_key = session_key
        self.request_owner_id = request_owner_id
        self.editing_request_message_id = editing_request_message_id

        item_data = WAREHOUSE_ITEMS[category]["items"][item_name]

        if isinstance(item_data, int):
            max_value = item_data
            unit = "шт"
        else:
            max_value = item_data.get("max", 999)
            unit = item_data.get("unit", "шт")

        self.quantity = TextInput(
            label=f"Количество (макс {max_value} {unit}):",
            placeholder=f"Введи число от 1 до {max_value}...",
            required=True,
            min_length=1,
            max_length=4
        )
        self.add_item(self.quantity)

    async def on_submit(self, interaction: discord.Interaction):
        """Сохраняем выбранный предмет в корзину"""
        try:
            quantity = int(self.quantity.value)

            item_data = WAREHOUSE_ITEMS[self.category]["items"][self.item_name]
            if isinstance(item_data, int):
                max_value = item_data
            else:
                max_value = item_data.get("max", 999)

            if quantity > max_value:
                await interaction.response.send_message(
                    f"❌ **Ошибка:** нельзя взять больше {max_value}!",
                    ephemeral=True
                )
                return

            if quantity < 1:
                await interaction.response.send_message(
                    "❌ **Ошибка:** количество должно быть хотя бы 1",
                    ephemeral=True
                )
                return

            from services.warehouse_session import WarehouseSession

            session_key = self.session_key if self.session_key is not None else interaction.user.id

            success, error_msg = WarehouseSession.add_item(
                session_key,
                self.category,
                self.item_name,
                quantity
            )

            if not success:
                await interaction.response.send_message(error_msg, ephemeral=True)
                return

            if self.editing_request_message_id:
                await interaction.response.send_message(
                    f"✅ **{self.item_name}** x{quantity} добавлено в корзину редактирования!\n"
                    f"🛒 Открой окно корзины редактирования и продолжай изменения.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"✅ **{self.item_name}** x{quantity} добавлено в корзину!\n"
                    f"🛒 Чтобы посмотреть корзину или отправить запрос - нажми кнопку **«МОЯ КОРЗИНА»** в канале.",
                    ephemeral=True
                )

        except ValueError:
            await interaction.response.send_message(
                "❌ **Ошибка:** введи число!",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Ошибка: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ **Ошибка:** что-то пошло не так",
                ephemeral=True
            )