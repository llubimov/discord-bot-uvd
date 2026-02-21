"""
=====================================================
МОДАЛКА ОТКЛОНЕНИЯ ОБЫЧНЫХ ЗАЯВОК (курсант/перевод/гос)
=====================================================
"""

import discord
from discord.ui import Modal, TextInput
import logging
import asyncio
from config import Config
from views.message_texts import ErrorMessages
from enums import RequestType
from state import active_requests, bot
from utils.validators import Validators
from utils.embed_utils import copy_embed, add_officer_field, add_reject_reason
from database import delete_request
from constants import StatusValues

logger = logging.getLogger(__name__)

class RejectReasonModal(Modal, title='отклонение заявки'):
    def __init__(self, user_id: int, request_type: RequestType, message_id: int):
        super().__init__()
        self.user_id = user_id
        self.request_type = request_type
        self.message_id = message_id
        self.reason = TextInput(
            label='причина отказа',
            placeholder='укажите причину отклонения заявки',
            max_length=Config.MAX_REASON_LENGTH,
            style=discord.TextStyle.paragraph,
            required=True
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            staff_role = interaction.guild.get_role(self.request_type.get_staff_role_id())
            if staff_role not in interaction.user.roles:
                await interaction.response.send_message(ErrorMessages.NO_PERMISSION, ephemeral=True)
                return

            valid, reason = Validators.validate_reason(self.reason.value)
            if not valid:
                await interaction.response.send_message(f"❌ {reason}", ephemeral=True)
                return

            request_data = active_requests.get(self.message_id)
            if not request_data:
                await interaction.response.send_message(ErrorMessages.NOT_FOUND.format(item="заявка"), ephemeral=True)
                return

            member = interaction.guild.get_member(self.user_id)
            message = await interaction.channel.fetch_message(self.message_id)

            embed = copy_embed(message.embeds[0])
            embed = add_officer_field(embed, interaction.user.mention)
            embed = add_reject_reason(embed, reason)
            embed.color = discord.Color.red()

            # 🔥 ПОЛНОСТЬЮ УБИРАЕМ КНОПКИ (view=None)
            await message.edit(embed=embed, view=None)

            if member:
                try:
                    notification = discord.Embed(
                        title="❌ заявка отклонена",
                        color=discord.Color.red(),
                        description=f"**{interaction.guild.name}**\n\nваша заявка была отклонена.",
                        timestamp=interaction.created_at
                    )
                    notification.add_field(name="причина", value=reason, inline=False)
                    notification.add_field(name="отклонил", value=interaction.user.mention, inline=True)
                    await member.send(embed=notification)
                except discord.Forbidden:
                    await interaction.followup.send(f"⚠️ не удалось отправить уведомление пользователю {member.mention}", ephemeral=True)

            if self.message_id in active_requests:
                del active_requests[self.message_id]
                await asyncio.to_thread(delete_request, 'requests', self.message_id)

            await interaction.response.send_message(f"✅ заявка отклонена. причина: {reason}", ephemeral=True)
            logger.info(f"Заявка {self.message_id} отклонена сотрудником {interaction.user.id}")

        except Exception as e:
            logger.error(f"Ошибка при отклонении заявки: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(ErrorMessages.GENERIC, ephemeral=True)