import discord
from discord.ui import View, Button
import logging
from modals import CadetModal, TransferModal, GovModal
from views.message_texts import ErrorMessages

logger = logging.getLogger(__name__)


class StartView(View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        logger.error("Ошибка в StartView: %s", error, exc_info=True)
        if interaction.response.is_done():
            await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)
        else:
            await interaction.response.send_message(ErrorMessages.GENERIC, ephemeral=True)

    @discord.ui.button(label="🟢 Курсант", style=discord.ButtonStyle.success, custom_id="cadet_role")
    async def cadet_button(self, interaction: discord.Interaction, button: Button):
        try:
            await interaction.response.send_modal(CadetModal())
        except Exception as e:
            logger.error("Ошибка в cadet_button: %s", e, exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)
            else:
                await interaction.response.send_message(ErrorMessages.GENERIC, ephemeral=True)

    @discord.ui.button(label="🔵 Перевод", style=discord.ButtonStyle.primary, custom_id="transfer_role")
    async def transfer_button(self, interaction: discord.Interaction, button: Button):
        try:
            await interaction.response.send_modal(TransferModal())
        except Exception as e:
            logger.error("Ошибка в transfer_button: %s", e, exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)
            else:
                await interaction.response.send_message(ErrorMessages.GENERIC, ephemeral=True)

    @discord.ui.button(label="⚪ Гос. Сотрудник", style=discord.ButtonStyle.secondary, custom_id="gov_role")
    async def gov_button(self, interaction: discord.Interaction, button: Button):
        try:
            await interaction.response.send_modal(GovModal())
        except Exception as e:
            logger.error("Ошибка в gov_button: %s", e, exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)
            else:
                await interaction.response.send_message(ErrorMessages.GENERIC, ephemeral=True)