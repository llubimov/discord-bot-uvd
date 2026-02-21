import discord
from discord.ui import Modal, TextInput
import logging
import asyncio
from datetime import datetime

from config import Config
import state

logger = logging.getLogger(__name__)


class WarehouseRejectModal(Modal, title="Причина отказа"):
    def __init__(self, author_id: int, message_id: int):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.message_id = message_id

        self.reason = TextInput(
            label="Укажите причину отказа",
            placeholder="Например: превышен лимит, неверно оформлен запрос и т.д.",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=500
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            staff_role = interaction.guild.get_role(Config.WAREHOUSE_STAFF_ROLE_ID)
            if staff_role not in interaction.user.roles:
                await interaction.response.send_message(
                    "❌ Только сотрудник склада может отказывать!",
                    ephemeral=True
                )
                return

            await interaction.response.defer(ephemeral=True)

            message = await interaction.channel.fetch_message(self.message_id)
            if not message.embeds:
                await interaction.followup.send("❌ Не найден embed заявки.", ephemeral=True)
                return

            embed = message.embeds[0]

            # Защита от повторной обработки: если уже есть статус отказа/выдачи — выходим
            for field in embed.fields:
                fname = (field.name or "").lower()
                if "выдано" in fname or "отказ" in fname:
                    await interaction.followup.send(
                        "⚠️ Эта заявка уже обработана.",
                        ephemeral=True
                    )
                    return

            # Обновляем embed
            embed.color = discord.Color.red()
            embed.add_field(
                name="❌ ОТКАЗАНО",
                value=(
                    f"Сотрудник: {interaction.user.mention}\n"
                    f"Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
                    f"Причина: {self.reason.value}"
                ),
                inline=False
            )

            # Убираем кнопки
            await message.edit(embed=embed, view=None)

            # Удаляем запись из БД и памяти
            try:
                from database import delete_warehouse_request
                await asyncio.to_thread(delete_warehouse_request, self.message_id)
            except Exception as e:
                logger.warning("Склад: не удалось удалить запись из БД после отказа: %s", e)

            if hasattr(state, "warehouse_requests"):
                state.warehouse_requests.pop(self.message_id, None)

            # Пытаемся уведомить автора в ЛС
            member = interaction.guild.get_member(self.author_id)
            if member:
                try:
                    dm_embed = discord.Embed(
                        title="❌ В выдаче склада отказано",
                        color=discord.Color.red(),
                        description=f"Ваш запрос на склад был отклонён на сервере **{interaction.guild.name}**.",
                        timestamp=interaction.created_at
                    )
                    dm_embed.add_field(name="Причина", value=self.reason.value, inline=False)
                    dm_embed.add_field(name="Сотрудник склада", value=interaction.user.mention, inline=False)
                    await member.send(embed=dm_embed)
                except discord.Forbidden:
                    pass
                except Exception as e:
                    logger.warning("Склад: не удалось отправить ЛС об отказе: %s", e)

            await interaction.followup.send("✅ Запрос на склад отклонён.", ephemeral=True)
            logger.info("Склад: отказ | staff=%s requester=%s message_id=%s", interaction.user.id, self.author_id, self.message_id)

        except discord.NotFound:
            if interaction.response.is_done():
                await interaction.followup.send("❌ Сообщение заявки не найдено.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Сообщение заявки не найдено.", ephemeral=True)

        except Exception as e:
            logger.error("Ошибка при отказе склада: %s", e, exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send("❌ Ошибка при отказе в выдаче.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Ошибка при отказе в выдаче.", ephemeral=True)