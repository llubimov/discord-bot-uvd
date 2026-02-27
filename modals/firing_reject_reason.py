import logging
import re

from config import Config
from state import active_firing_requests
from constants import WebhookPatterns
from .base_reject import BaseRejectModal

logger = logging.getLogger(__name__)


class FiringRejectReasonModal(BaseRejectModal):

    @classmethod
    def get_modal_title(cls):
        return "отклонение рапорта об увольнении"

    async def get_staff_role_id(self, interaction):
        return Config.FIRING_STAFF_ROLE_ID

    async def get_request_data(self, message_id):
        return active_firing_requests.get(message_id)

    def get_view_class(self):
        from views.firing_view import FiringView
        return FiringView

    def get_state_dict(self):
        return active_firing_requests

    def get_table_name(self):
        return "firing_requests"

    def get_notification_title(self):
        return "❌ Рапорт об увольнении отклонён"

    def get_item_name(self):
        return "рапорт"

    async def on_submit(self, interaction):
        if self.message_id not in active_firing_requests:
            try:
                msg = await interaction.channel.fetch_message(self.message_id)
                if msg and msg.embeds:
                    embed = msg.embeds[0]
                    desc = embed.description or ""

                    full_name = "Сотрудник"
                    reason = "псж"

                    m_name = re.search(WebhookPatterns.FIRING["full_name"], desc, re.IGNORECASE)
                    if not m_name:
                        m_name = re.search(WebhookPatterns.FIRING["full_name_alt"], desc, re.IGNORECASE)
                    if m_name:
                        full_name = (m_name.group(1) or "").strip() or "Сотрудник"

                    m_reason = re.search(WebhookPatterns.FIRING["reason"], desc, re.IGNORECASE)
                    if m_reason:
                        reason = (m_reason.group(1) or "").strip() or "псж"

                    active_firing_requests[self.message_id] = {
                        "discord_id": self.user_id,
                        "full_name": full_name,
                        "reason": reason,
                        "message_link": msg.jump_url,
                    }

                    logger.warning(
                        "Увольнение (reject): рапорт %s восстановлен из embed (state/БД пусто)",
                        self.message_id
                    )
            except Exception as e:
                logger.warning(
                    "Не удалось восстановить рапорт увольнения %s перед отклонением: %s",
                    self.message_id,
                    e,
                    exc_info=True
                )

        await super().on_submit(interaction)