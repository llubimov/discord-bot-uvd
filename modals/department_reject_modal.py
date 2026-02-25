"""
Модал отклонения заявки на перевод (из Академии в ГРОМ/ОРЛС/ОСБ).
"""
from __future__ import annotations

import asyncio
import logging

import discord
from discord.ui import Modal, TextInput

from config import Config
from database import delete_department_transfer_request
from state import active_department_transfers
from utils.embed_utils import copy_embed, update_embed_status

logger = logging.getLogger(__name__)


class DepartmentRejectModal(Modal, title="Отклонение заявки"):
    def __init__(self, message_id: int, user_id: int, target_dept: str):
        super().__init__()
        self.message_id = int(message_id)
        self.user_id = int(user_id)
        self.target_dept = (target_dept or "").strip().lower()
        self.reason = TextInput(
            label="Причина отклонения",
            placeholder="Укажите причину отказа",
            max_length=Config.MAX_REASON_LENGTH,
            style=discord.TextStyle.paragraph,
            required=True,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("❌ Только на сервере.", ephemeral=True)
                return

            try:
                msg = await interaction.channel.fetch_message(self.message_id)
            except (discord.NotFound, discord.Forbidden):
                await interaction.followup.send("❌ Сообщение заявки не найдено.", ephemeral=True)
                return

            if not msg.embeds:
                await interaction.followup.send("❌ У сообщения нет embed.", ephemeral=True)
                return

            reason_text = (self.reason.value or "").strip() or "Не указана"
            embed = copy_embed(msg.embeds[0])
            embed = update_embed_status(embed, "❌ Отклонено", discord.Color.red())
            embed.add_field(name="Причина отказа", value=reason_text[:1024], inline=False)
            embed.add_field(name="Отклонил", value=interaction.user.mention, inline=False)

            await msg.edit(embed=embed, view=None)

            member = guild.get_member(self.user_id) or await guild.fetch_member(self.user_id)
            if member:
                try:
                    await member.send(
                        f"❌ Ваша заявка на перевод была отклонена.\n**Причина:** {reason_text}"
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass

            active_department_transfers.pop(self.message_id, None)
            await asyncio.to_thread(delete_department_transfer_request, self.message_id)

            await interaction.followup.send("✅ Заявка отклонена, пользователь уведомлён.", ephemeral=True)
        except Exception as e:
            logger.error("Ошибка отклонения заявки: %s", e, exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send("❌ Ошибка при отклонении.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Ошибка при отклонении.", ephemeral=True)
