import discord
from discord.ui import Modal, TextInput
import logging

from views.message_texts import ErrorMessages
from services.warehouse_session import WarehouseSession
from data.warehouse_items import WAREHOUSE_ITEMS

logger = logging.getLogger(__name__)


def _find_item_limit(item_name: str):
    """
    Возвращает лимит предмета из WAREHOUSE_ITEMS (int) или None.
    Поддерживает форматы:
    - "Предмет": 3
    - "Предмет": {"max": 2, ...}
    - "Предмет": {"max_quantity": 2, ...}
    """
    try:
        for category_data in WAREHOUSE_ITEMS.values():
            if not isinstance(category_data, dict):
                continue

            items = category_data.get("items", {})
            if item_name not in items:
                continue

            raw = items[item_name]

            if isinstance(raw, int):
                return raw

            if isinstance(raw, dict):
                max_q = raw.get("max_quantity")
                if isinstance(max_q, int):
                    return max_q

                max_q = raw.get("max")
                if isinstance(max_q, int):
                    return max_q

            return None
    except Exception:
        return None

    return None


class WarehouseEditModal(Modal):
    def __init__(
        self,
        user_id: int | None = None,
        item_index: int | None = None,
        category: str | None = None,
        item_name: str | None = None,
        current_quantity: int | None = None,
        session_key=None,
        allowed_user_id: int | None = None,
        **kwargs,
    ):
        """
        Совместим со старым и новым вызовом.

        Новый безопасный вариант:
        WarehouseEditModal(
            allowed_user_id=interaction.user.id,
            session_key=<ключ сессии>,
            ...
        )
        """
        # user_id оставляем для обратной совместимости
        self.allowed_user_id = allowed_user_id if allowed_user_id is not None else user_id
        self.session_key = session_key if session_key is not None else user_id
        self.item_index = item_index

        # fallback-данные для старого вызова
        self.fallback_category = category
        self.fallback_item_name = item_name
        self.fallback_quantity = int(current_quantity or 1)

        self.current_item = None

        # Если ключ сессии уже известен, пробуем взять актуальный предмет из корзины
        if self.session_key is not None and item_index is not None:
            items = WarehouseSession.get_items(self.session_key)
            if 0 <= item_index < len(items):
                self.current_item = items[item_index]

        # Если не получилось — используем данные из старого вызова
        if self.current_item is None and category and item_name:
            self.current_item = {
                "category": category,
                "item": item_name,
                "quantity": self.fallback_quantity,
            }

        super().__init__(title="✏️ РЕДАКТИРОВАТЬ ПРЕДМЕТ")

        if self.current_item:
            self.quantity = TextInput(
                label=f"Количество ({self.current_item['item']})",
                default=str(self.current_item.get("quantity", 1)),
                placeholder="Введите новое количество",
                max_length=6,
                required=True,
            )
            self.add_item(self.quantity)

    def _resolve_item_index(self, session_key) -> int | None:
        """Пытается определить актуальный индекс предмета в корзине."""
        items = WarehouseSession.get_items(session_key)

        if isinstance(self.item_index, int) and 0 <= self.item_index < len(items):
            return self.item_index

        for idx, it in enumerate(items):
            if (
                it.get("category") == self.fallback_category
                and it.get("item") == self.fallback_item_name
            ):
                return idx

        return None

    async def on_submit(self, interaction: discord.Interaction):
        try:
            if self.allowed_user_id is None:
                self.allowed_user_id = interaction.user.id

            if self.session_key is None:
                # На старом коде работаем через user_id пользователя
                self.session_key = interaction.user.id

            if interaction.user.id != self.allowed_user_id:
                await interaction.response.send_message("❌ Это не ваша корзина.", ephemeral=True)
                return

            if not self.current_item:
                await interaction.response.send_message("❌ Предмет не найден в корзине.", ephemeral=True)
                return

            qty_text = str(self.quantity.value).strip()
            if not qty_text.isdigit():
                await interaction.response.send_message("❌ Количество должно быть числом.", ephemeral=True)
                return

            new_qty = int(qty_text)
            if new_qty <= 0:
                await interaction.response.send_message("❌ Количество должно быть больше 0.", ephemeral=True)
                return

            resolved_index = self._resolve_item_index(self.session_key)
            if resolved_index is None:
                await interaction.response.send_message(
                    "❌ Не удалось найти предмет в вашей корзине.",
                    ephemeral=True,
                )
                return

            self.item_index = resolved_index

            items = WarehouseSession.get_items(self.session_key)
            if not (0 <= self.item_index < len(items)):
                await interaction.response.send_message("❌ Предмет больше не найден в корзине.", ephemeral=True)
                return

            actual_item = items[self.item_index]
            item_name = actual_item.get("item")
            category_name = actual_item.get("category")

            if not item_name or not category_name:
                await interaction.response.send_message("❌ Некорректные данные предмета в корзине.", ephemeral=True)
                return

            max_item = _find_item_limit(item_name)
            if isinstance(max_item, int) and new_qty > max_item:
                await interaction.response.send_message(
                    f"❌ Для предмета **{item_name}** максимум: **{max_item}** шт.",
                    ephemeral=True,
                )
                return

            category_cfg = WAREHOUSE_ITEMS.get(category_name, {})
            max_total = None
            if isinstance(category_cfg, dict):
                max_total = category_cfg.get("max_total")

            if isinstance(max_total, int):
                category_total_without_current = 0
                for idx, it in enumerate(items):
                    if idx == self.item_index:
                        continue
                    if it.get("category") == category_name:
                        try:
                            category_total_without_current += int(it.get("quantity", 0))
                        except (TypeError, ValueError):
                            continue

                new_category_total = category_total_without_current + new_qty
                if new_category_total > max_total:
                    await interaction.response.send_message(
                        f"❌ Превышен лимит категории **{category_name}**: "
                        f"максимум **{max_total}** шт. "
                        f"(сейчас будет **{new_category_total}**).",
                        ephemeral=True,
                    )
                    return

            items[self.item_index]["quantity"] = new_qty

            await interaction.response.send_message(
                f"✅ Обновлено: **{item_name}** — теперь **{new_qty}** шт.",
                ephemeral=True,
            )

        except Exception as e:
            logger.error("Ошибка в WarehouseEditModal.on_submit: %s", e, exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)
            else:
                await interaction.response.send_message(ErrorMessages.GENERIC, ephemeral=True)