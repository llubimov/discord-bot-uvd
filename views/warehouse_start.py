import discord
from discord.ui import View, Button
import logging

from views.message_texts import ErrorMessages
from views.warehouse_embeds import build_cart_embed
from services.warehouse_session import WarehouseSession

logger = logging.getLogger(__name__)


class WarehouseStartView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="ЗАПРОСИТЬ СНАРЯЖЕНИЕ",
        style=discord.ButtonStyle.primary,
        custom_id="warehouse_request_button",
        emoji="📦",
        row=0
    )
    async def request_button(self, interaction: discord.Interaction, button: Button):
        try:
            items = WarehouseSession.get_items(interaction.user.id)
            embed = build_cart_embed(items, is_request=True)

            from views.warehouse_actions import WarehouseActionView
            view = WarehouseActionView()

            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            logger.error("Ошибка в request_button: %s", e, exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)
            else:
                await interaction.response.send_message(ErrorMessages.GENERIC, ephemeral=True)

    @discord.ui.button(
        label="🛒 МОЯ КОРЗИНА",
        style=discord.ButtonStyle.secondary,
        custom_id="warehouse_cart_button",
        emoji="🛒",
        row=0
    )
    async def cart_button(self, interaction: discord.Interaction, button: Button):
        try:
            items = WarehouseSession.get_items(interaction.user.id)

            if not items:
                await interaction.response.send_message(
                    "🛒 Корзина пуста. Нажми **«ЗАПРОСИТЬ СНАРЯЖЕНИЕ»**, чтобы начать.",
                    ephemeral=True
                )
                return

            embed = build_cart_embed(items, is_request=False)

            from views.warehouse_actions import WarehouseActionView
            view = WarehouseActionView()

            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            logger.error("Ошибка в корзине: %s", e, exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)
            else:
                await interaction.response.send_message(ErrorMessages.GENERIC, ephemeral=True)