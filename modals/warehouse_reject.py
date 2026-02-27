import discord
from discord.ui import Modal, TextInput
import logging
import asyncio
from datetime import datetime

from config import Config
from views.warehouse_theme import RED
import state
from services.action_locks import action_lock

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
            if not staff_role or staff_role not in interaction.user.roles:
                await interaction.response.send_message(
                    "❌ Только сотрудник склада может отказывать!",
                    ephemeral=True
                )
                return

            await interaction.response.defer(ephemeral=True)

            async with action_lock(self.message_id, "отказ склада"):
                try:
                    message = await interaction.channel.fetch_message(self.message_id)
                except discord.NotFound:
                    await interaction.followup.send("❌ Сообщение заявки не найдено.", ephemeral=True)
                    return
                except discord.Forbidden:
                    await interaction.followup.send("❌ У бота нет доступа к сообщению заявки.", ephemeral=True)
                    return
                except discord.HTTPException as e:
                    logger.warning("Склад reject: HTTP ошибка fetch_message %s: %s", self.message_id, e)
                    await interaction.followup.send("❌ Ошибка Discord API при получении сообщения.", ephemeral=True)
                    return

                if not message.embeds:
                    await interaction.followup.send("❌ Не найден embed заявки.", ephemeral=True)
                    return

                embed = message.embeds[0]

                for field in embed.fields:
                    fname = (field.name or "").lower()
                    if "выдано" in fname or "отказ" in fname:
                        await interaction.followup.send("⚠️ Эта заявка уже обработана.", ephemeral=True)
                        return

                updated_status = False
                for i, field in enumerate(embed.fields):
                    if (field.name or "").strip() == "Статус":
                        embed.set_field_at(i, name="Статус", value="🔴 Отказано", inline=False)
                        updated_status = True
                        break
                if not updated_status:
                    embed.add_field(name="Статус", value="🔴 Отказано", inline=False)

                embed.color = RED
                embed.add_field(
                    name="❌ Отказано",
                    value=(
                        f"Сотрудник: {interaction.user.mention}\n"
                        f"Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
                        f"Причина: {self.reason.value}"
                    ),
                    inline=False
                )

                try:
                    await message.edit(embed=embed, view=None)
                except discord.NotFound:
                    await interaction.followup.send("❌ Сообщение заявки было удалено.", ephemeral=True)
                    return
                except discord.Forbidden:
                    await interaction.followup.send("❌ У бота нет прав на редактирование сообщения.", ephemeral=True)
                    return
                except discord.HTTPException as e:
                    logger.warning("Склад reject: HTTP ошибка edit %s: %s", self.message_id, e)
                    await interaction.followup.send("❌ Ошибка Discord API при обновлении заявки.", ephemeral=True)
                    return

                try:
                    from database import delete_warehouse_request
                    await asyncio.to_thread(delete_warehouse_request, self.message_id)
                except Exception as e:
                    logger.warning("Склад: не удалось удалить запись из БД после отказа: %s", e, exc_info=True)

                if hasattr(state, "warehouse_requests"):
                    state.warehouse_requests.pop(self.message_id, None)

                member = interaction.guild.get_member(self.author_id)
                dm_warning = None
                if member:
                    try:
                        dm_embed = discord.Embed(
                            title="❌ В выдаче склада отказано",
                            color=RED,
                            description=f"Ваш запрос на склад был отклонён на сервере **{interaction.guild.name}**.",
                            timestamp=interaction.created_at
                        )
                        dm_embed.add_field(name="Причина", value=self.reason.value, inline=False)
                        dm_embed.add_field(name="Сотрудник склада", value=interaction.user.mention, inline=False)
                        await member.send(embed=dm_embed)
                    except discord.Forbidden:
                        dm_warning = f"⚠️ Не удалось отправить ЛС пользователю {member.mention}"
                    except discord.HTTPException as e:
                        logger.warning("Склад: HTTP ошибка при отправке ЛС об отказе: %s", e)
                        dm_warning = f"⚠️ Не удалось отправить ЛС пользователю {member.mention}"
                    except Exception as e:
                        logger.warning("Склад: не удалось отправить ЛС об отказе: %s", e, exc_info=True)
                        dm_warning = f"⚠️ Не удалось отправить ЛС пользователю {member.mention}"

                await interaction.followup.send("✅ Запрос на склад отклонён.", ephemeral=True)
                if dm_warning:
                    await interaction.followup.send(dm_warning, ephemeral=True)

                logger.info(
                    "Склад: отказ | staff=%s requester=%s message_id=%s",
                    interaction.user.id,
                    self.author_id,
                    self.message_id
                )

        except RuntimeError as e:
            if str(e) == "ACTION_ALREADY_IN_PROGRESS":
                if interaction.response.is_done():
                    await interaction.followup.send("⚠️ Этот запрос уже обрабатывается другим нажатием.", ephemeral=True)
                else:
                    await interaction.response.send_message("⚠️ Этот запрос уже обрабатывается другим нажатием.", ephemeral=True)
                return

            logger.error("Ошибка блокировки склада (отказ): %s", e, exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send("❌ Ошибка при отказе в выдаче.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Ошибка при отказе в выдаче.", ephemeral=True)

        except Exception as e:
            logger.error("Ошибка при отказе склада: %s", e, exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send("❌ Ошибка при отказе в выдаче.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Ошибка при отказе в выдаче.", ephemeral=True)