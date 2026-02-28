import discord
from discord.ui import View, Button
import logging

from config import Config
from modals.admin_transfer_modal import AdminTransferModal
from services.department_roles import get_chief_deputy_role_ids
from .base_position import BasePositionManager
from views.message_texts import ErrorMessages

logger = logging.getLogger(__name__)


TITLE = "⚡ АДМИНИСТРАТИВНЫЙ ПЕРЕВОД СОТРУДНИКА"
DESCRIPTION = (
    "Используется для перевода сотрудников в ППС без прохождения стандартной процедуры подачи заявки.\n\n"
    "**ВНИМАНИЕ:** При нажатии кнопки роли сотрудника будут изменены мгновенно.\n\n"
    "⬇️ **ВЫБЕРИТЕ ТЕКУЩИЙ ОТДЕЛ СОТРУДНИКА:**"
)


def _has_any_role(member: discord.Member, role_ids: list[int]) -> bool:
    if not member or not role_ids:
        return False
    guild = member.guild
    for rid in role_ids:
        r = guild.get_role(rid)
        if r and r in member.roles:
            return True
    return False


class AdminTransferView(View):
    timeout = None

    def __init__(self):
        super().__init__(timeout=None)
        for dept, label in [("grom", "👮 ОСН \"ГРОМ\""), ("osb", "🛡️ ОСБ"), ("orls", "📋 ОРЛС")]:
            btn = Button(label=label, style=discord.ButtonStyle.primary, custom_id=f"admin_transfer_{dept}")
            btn.callback = self._make_callback(dept)
            self.add_item(btn)

    def _make_callback(self, from_dept: str):
        async def callback(interaction: discord.Interaction):
            role_ids = get_chief_deputy_role_ids(from_dept)
            if not role_ids:
                await interaction.response.send_message("❌ Роли для этого отдела не настроены.", ephemeral=True)
                return
            if not _has_any_role(interaction.user, role_ids):
                await interaction.response.send_message(ErrorMessages.NO_PERMISSION, ephemeral=True)
                return
            modal = AdminTransferModal(from_dept)
            await interaction.response.send_modal(modal)
        return callback


class AdminTransferPositionManager(BasePositionManager):
    @property
    def channel_id(self) -> int:
        return Config.CHANNEL_ADMIN_TRANSFER

    @property
    def check_interval(self) -> int:

        return 120

    async def get_embed(self) -> discord.Embed:
        embed = discord.Embed(title=TITLE, description=DESCRIPTION, color=discord.Color.blue())
        return embed

    async def get_view(self) -> discord.ui.View:
        return AdminTransferView()

    async def should_keep_message(self, message: discord.Message) -> bool:
        return bool(message.embeds and message.embeds[0].title == TITLE)
