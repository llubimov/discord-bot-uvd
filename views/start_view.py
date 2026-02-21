import discord
from discord.ui import View, Button
import logging
from modals import CadetModal, TransferModal, GovModal
from views.message_texts import ErrorMessages, StartMessages

logger = logging.getLogger(__name__)

class StartView(View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        logger.error(f"Ошибка в StartView: {error}", exc_info=True)
        await interaction.response.send_message(MessageConfig.ERR_GENERIC, ephemeral=True)

    @discord.ui.button(label="🟢 курсант", style=discord.ButtonStyle.success, custom_id="cadet_role")
    async def cadet_button(self, interaction: discord.Interaction, button: Button):
        try:
            modal = CadetModal()
            await interaction.response.send_modal(modal)
        except Exception as e:
            logger.error(f"Ошибка в cadet_button: {e}", exc_info=True)
            await interaction.response.send_message(MessageConfig.ERR_GENERIC, ephemeral=True)

    @discord.ui.button(label="🔵 перевод", style=discord.ButtonStyle.primary, custom_id="transfer_role")
    async def transfer_button(self, interaction: discord.Interaction, button: Button):
        try:
            modal = TransferModal()
            await interaction.response.send_modal(modal)
        except Exception as e:
            logger.error(f"Ошибка в transfer_button: {e}", exc_info=True)
            await interaction.response.send_message(MessageConfig.ERR_GENERIC, ephemeral=True)

    @discord.ui.button(label="⚪ гос сотрудник", style=discord.ButtonStyle.secondary, custom_id="gov_role")
    async def gov_button(self, interaction: discord.Interaction, button: Button):
        try:
            modal = GovModal()
            await interaction.response.send_modal(modal)
        except Exception as e:
            logger.error(f"Ошибка в gov_button: {e}", exc_info=True)
            await interaction.response.send_message(MessageConfig.ERR_GENERIC, ephemeral=True)