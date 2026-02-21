"""
=====================================================
МОДАЛКА ОТКЛОНЕНИЯ РАПОРТОВ О ПОВЫШЕНИИ
=====================================================
"""

import logging
from config import Config
from state import active_promotion_requests
from .base_reject import BaseRejectModal

logger = logging.getLogger(__name__)


class PromotionRejectReasonModal(BaseRejectModal):
    """Модалка отклонения рапортов о повышении"""

    @classmethod
    def get_modal_title(cls):
        return "отклонение рапорта на повышение"

    async def get_staff_role_id(self, interaction):
        required_role_id = Config.PROMOTION_CHANNELS.get(interaction.channel.id)
        return required_role_id or 0

    async def get_request_data(self, message_id):
        return active_promotion_requests.get(message_id)

    def get_view_class(self):
        from views.promotion_view import PromotionView
        return PromotionView

    def get_state_dict(self):
        return active_promotion_requests

    def get_table_name(self):
        return "promotion_requests"

    def get_notification_title(self):
        return "❌ рапорт на повышение отклонен"

    def get_item_name(self):
        return "рапорт"

    async def get_view_instance(self, interaction, request_data):
        """Специальная логика для promotion view"""
        from views.promotion_view import PromotionView
        view = PromotionView(
            user_id=self.user_id,
            new_rank=self.additional_data.get("new_rank", ""),
            full_name=self.additional_data.get("full_name", ""),
            message_id=self.message_id
        )
        for item in view.children:
            item.disabled = True
        return view

    async def on_submit(self, interaction):
        """
        Fallback для старых рапортов:
        если записи нет в state, собираем минимальные данные из уже известных параметров view.
        """
        if self.message_id not in active_promotion_requests:
            try:
                msg = await interaction.channel.fetch_message(self.message_id)
                active_promotion_requests[self.message_id] = {
                    "discord_id": self.user_id,
                    "full_name": self.additional_data.get("full_name", "") or "сотрудник",
                    "new_rank": self.additional_data.get("new_rank", "") or "",
                    "message_link": getattr(msg, "jump_url", ""),
                }
                logger.warning(
                    "Повышение (reject): рапорт %s восстановлен из view-параметров (state/БД пусто)",
                    self.message_id
                )
            except Exception as e:
                logger.warning(
                    "Не удалось восстановить рапорт повышения %s перед отклонением: %s",
                    self.message_id,
                    e,
                    exc_info=True
                )

        await super().on_submit(interaction)