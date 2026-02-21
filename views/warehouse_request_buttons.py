import discord
from discord.ui import View, Button
import logging
from datetime import datetime
import asyncio

from config import Config
from services import warehouse_cooldown
from services.warehouse_session import WarehouseSession
from services.warehouse_audit import WarehouseAudit
from views.warehouse_actions import WarehouseActionView
from services.action_locks import action_lock
import state

logger = logging.getLogger(__name__)


class WarehouseRequestView(View):
    """Кнопки для управления запросом"""

    def __init__(self, author_id: int, message_id: int):
        super().__init__(timeout=None)
        self.author_id = author_id
        self.message_id = message_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Проверка прав"""
        staff_role = interaction.guild.get_role(Config.WAREHOUSE_STAFF_ROLE_ID)
        is_staff = staff_role in interaction.user.roles
        is_author = interaction.user.id == self.author_id

        if not is_staff and not is_author:
            await interaction.response.send_message(
                "❌ Только сотрудник склада или автор могут нажимать эти кнопки!",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(
        label="✅ ВЫДАТЬ",
        style=discord.ButtonStyle.success,
        emoji="✅",
        custom_id="warehouse_accept",
        row=0
    )
    async def accept_button(self, interaction: discord.Interaction, button: Button):
        """Выдать снаряжение"""
        staff_role = interaction.guild.get_role(Config.WAREHOUSE_STAFF_ROLE_ID)
        if staff_role not in interaction.user.roles:
            await interaction.response.send_message(
                "❌ Только сотрудник склада может выдавать!",
                ephemeral=True
            )
            return

        await self.handle_accept(interaction)

    @discord.ui.button(
        label="❌ ОТКАЗАТЬ",
        style=discord.ButtonStyle.danger,
        emoji="❌",
        custom_id="warehouse_reject",
        row=0
    )
    async def reject_button(self, interaction: discord.Interaction, button: Button):
        """Отказать в выдаче"""
        staff_role = interaction.guild.get_role(Config.WAREHOUSE_STAFF_ROLE_ID)
        if staff_role not in interaction.user.roles:
            await interaction.response.send_message(
                "❌ Только сотрудник склада может отказывать!",
                ephemeral=True
            )
            return

        from modals.warehouse_reject import WarehouseRejectModal
        modal = WarehouseRejectModal(self.author_id, self.message_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="✏️ РЕДАКТИРОВАТЬ",
        style=discord.ButtonStyle.secondary,
        emoji="✏️",
        custom_id="warehouse_edit",
        row=0
    )
    async def edit_button(self, interaction: discord.Interaction, button: Button):
        """Редактировать запрос"""
        await self.handle_edit(interaction)

    async def handle_accept(self, interaction: discord.Interaction):
        """Обработка выдачи"""
        can, message = warehouse_cooldown.can_issue(self.author_id)
        if not can:
            await interaction.response.send_message(
                f"❌ Этому пользователю нельзя выдать сейчас!\n{message}",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            async with action_lock(self.message_id, "выдача склада"):
                message = await interaction.channel.fetch_message(self.message_id)
                embed = message.embeds[0]

                # Извлекаем предметы из embed
                items = []
                for field in embed.fields:
                    if field.name in ["🔫 оружие", "🛡️ бронежилеты", "💊 медикаменты", "📦 расходуемое"]:
                        lines = field.value.split('\n')
                        for line in lines:
                            if '—' in line:
                                parts = line.split('—')
                                item_name = parts[0].replace('•', '').replace('**', '').strip()
                                quantity = parts[1].replace('**', '').replace('шт', '').strip()
                                items.append({
                                    'item': item_name,
                                    'quantity': int(quantity)
                                })

                # Аудит
                audit = WarehouseAudit(interaction.client)
                await audit.log_issue(
                    staff_member=interaction.user,
                    requester_id=self.author_id,
                    items=items,
                    message_link=message.jump_url
                )

                # Обновляем embed
                embed.color = discord.Color.green()
                embed.add_field(
                    name="✅ ВЫДАНО",
                    value=f"Сотрудник: {interaction.user.mention}\nВремя: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
                    inline=False
                )

                # Кулдаун
                warehouse_cooldown.register_issue(self.author_id)

                # Удаляем из БД и памяти
                from database import delete_warehouse_request
                await asyncio.to_thread(delete_warehouse_request, self.message_id)
                if hasattr(state, "warehouse_requests"):
                    state.warehouse_requests.pop(self.message_id, None)

                # Убираем кнопки
                await message.edit(embed=embed, view=None)

                await interaction.followup.send(
                    "✅ Снаряжение выдано! Данные отправлены в аудит.",
                    ephemeral=True
                )

                logger.info(f"Склад выдал {interaction.user.id} для {self.author_id}")

        except RuntimeError as e:
            if str(e) == "ACTION_ALREADY_IN_PROGRESS":
                await interaction.followup.send("⚠️ Этот запрос уже обрабатывается другим нажатием.", ephemeral=True)
                return
            logger.error("Ошибка блокировки склада (выдача): %s", e, exc_info=True)
            await interaction.followup.send("❌ Ошибка", ephemeral=True)

        except Exception as e:
            logger.error(f"Ошибка при выдаче: {e}", exc_info=True)
            await interaction.followup.send("❌ Ошибка", ephemeral=True)

    async def handle_edit(self, interaction: discord.Interaction):
        """Редактирование запроса - удаляет старый и создает новый"""
        try:
            async with action_lock(self.message_id, "редактирование запроса склада"):
                message = await interaction.channel.fetch_message(self.message_id)
                embed = message.embeds[0]

                # Парсим предметы из embed
                items = []
                for field in embed.fields:
                    if field.name in ["🔫 оружие", "🛡️ бронежилеты", "💊 медикаменты", "📦 расходуемое"]:
                        lines = field.value.split('\n')
                        for line in lines:
                            if '—' in line:
                                parts = line.split('—')
                                item_name = parts[0].replace('•', '').replace('**', '').strip()
                                quantity = parts[1].replace('**', '').replace('шт', '').strip()

                                items.append({
                                    'category': field.name,
                                    'item': item_name,
                                    'quantity': int(quantity)
                                })

                if not items:
                    await interaction.response.send_message(
                        "❌ Не удалось загрузить предметы для редактирования",
                        ephemeral=True
                    )
                    return

                # Удаляем старую заявку из БД и памяти ДО удаления сообщения
                try:
                    from database import delete_warehouse_request
                    await asyncio.to_thread(delete_warehouse_request, self.message_id)
                except Exception as e:
                    logger.warning("Склад: не удалось удалить старую запись из БД при редактировании: %s", e)

                if hasattr(state, "warehouse_requests"):
                    state.warehouse_requests.pop(self.message_id, None)

                # Удаляем старое сообщение
                await message.delete()
                logger.info(f"Старая заявка {self.message_id} удалена при редактировании")

                # Загружаем предметы в сессию пользователя
                session = WarehouseSession.get_session(interaction.user.id)
                session["items"] = items

                # Показываем корзину
                embed = discord.Embed(
                    title="🛒 РЕДАКТИРОВАНИЕ ЗАПРОСА",
                    color=discord.Color.blue(),
                    description="**Текущий состав:**"
                )

                for item in items:
                    embed.add_field(
                        name=item['item'],
                        value=f"Количество: **{item['quantity']}** шт",
                        inline=False
                    )

                view = WarehouseActionView()

                await interaction.response.send_message(
                    embed=embed,
                    view=view,
                    ephemeral=True
                )

                logger.info(f"Загружено {len(items)} предметов для редактирования пользователем {interaction.user.id}")

        except RuntimeError as e:
            if str(e) == "ACTION_ALREADY_IN_PROGRESS":
                # здесь response может быть уже не отвечен, поэтому проверяем
                if interaction.response.is_done():
                    await interaction.followup.send("⚠️ Этот запрос уже обрабатывается другим нажатием.", ephemeral=True)
                else:
                    await interaction.response.send_message("⚠️ Этот запрос уже обрабатывается другим нажатием.", ephemeral=True)
                return

            logger.error("Ошибка блокировки склада (редактирование): %s", e, exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send("❌ Ошибка при загрузке запроса для редактирования", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Ошибка при загрузке запроса для редактирования", ephemeral=True)

        except Exception as e:
            logger.error(f"Ошибка при загрузке редактирования: {e}", exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send("❌ Ошибка при загрузке запроса для редактирования", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Ошибка при загрузке запроса для редактирования", ephemeral=True)