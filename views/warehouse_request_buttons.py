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


WAREHOUSE_FIELD_NAMES = {"🔫 оружие", "🛡️ бронежилеты", "💊 медикаменты", "📦 расходуемое"}


class WarehouseRequestView(View):
    """Кнопки для управления запросом"""

    def __init__(self, author_id: int, message_id: int):
        super().__init__(timeout=None)
        self.author_id = author_id
        self.message_id = message_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Проверка прав"""
        if not interaction.guild:
            await interaction.response.send_message("❌ Команда доступна только на сервере.", ephemeral=True)
            return False

        staff_role = interaction.guild.get_role(Config.WAREHOUSE_STAFF_ROLE_ID)
        is_staff = bool(staff_role and staff_role in interaction.user.roles)
        is_author = interaction.user.id == self.author_id

        if not is_staff and not is_author:
            await interaction.response.send_message(
                "❌ Только сотрудник склада или автор могут нажимать эти кнопки!",
                ephemeral=True
            )
            return False
        return True

    def _parse_items_from_embed(self, embed: discord.Embed, include_category: bool = False) -> list[dict]:
        """
        Парсит предметы из embed заявки склада.
        Ожидаемый формат строки:
        • **Название** — **N** шт
        """
        items: list[dict] = []

        for field in (embed.fields or []):
            field_name = (field.name or "").strip()
            if field_name not in WAREHOUSE_FIELD_NAMES:
                continue

            for raw_line in (field.value or "").split("\n"):
                line = raw_line.strip()
                if not line or "—" not in line:
                    continue

                try:
                    left, right = line.split("—", 1)
                    item_name = left.replace("•", "").replace("**", "").strip()

                    qty_raw = (
                        right.replace("**", "")
                        .replace("шт", "")
                        .strip()
                    )
                    quantity = int(qty_raw)

                    row = {
                        "item": item_name,
                        "quantity": quantity,
                    }
                    if include_category:
                        row["category"] = field_name

                    items.append(row)

                except ValueError:
                    logger.warning("Склад: не удалось распарсить количество в строке: %r", line)
                except Exception as e:
                    logger.warning("Склад: ошибка парсинга строки %r: %s", line, e, exc_info=True)

        return items

    async def _fetch_request_message(self, interaction: discord.Interaction) -> discord.Message | None:
        try:
            return await interaction.channel.fetch_message(self.message_id)
        except discord.NotFound:
            return None
        except discord.Forbidden:
            raise
        except discord.HTTPException:
            raise

    @discord.ui.button(
        label="✅ ВЫДАТЬ",
        style=discord.ButtonStyle.success,
        emoji="✅",
        custom_id="warehouse_accept",
        row=0
    )
    async def accept_button(self, interaction: discord.Interaction, button: Button):
        """Выдать снаряжение"""
        if not interaction.guild:
            await interaction.response.send_message("❌ Команда доступна только на сервере.", ephemeral=True)
            return

        staff_role = interaction.guild.get_role(Config.WAREHOUSE_STAFF_ROLE_ID)
        if not staff_role or staff_role not in interaction.user.roles:
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
        if not interaction.guild:
            await interaction.response.send_message("❌ Команда доступна только на сервере.", ephemeral=True)
            return

        staff_role = interaction.guild.get_role(Config.WAREHOUSE_STAFF_ROLE_ID)
        if not staff_role or staff_role not in interaction.user.roles:
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
        can, cooldown_message = warehouse_cooldown.can_issue(self.author_id)
        if not can:
            await interaction.response.send_message(
                f"❌ Этому пользователю нельзя выдать сейчас!\n{cooldown_message}",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            async with action_lock(self.message_id, "выдача склада"):
                # Получаем сообщение заявки
                try:
                    message = await self._fetch_request_message(interaction)
                    if not message:
                        await interaction.followup.send("❌ Сообщение заявки не найдено.", ephemeral=True)
                        return
                except discord.Forbidden:
                    await interaction.followup.send("❌ У бота нет доступа к сообщению заявки.", ephemeral=True)
                    return
                except discord.HTTPException as e:
                    logger.warning("Склад accept: HTTP ошибка fetch_message %s: %s", self.message_id, e)
                    await interaction.followup.send("❌ Ошибка Discord API при получении сообщения.", ephemeral=True)
                    return

                if not message.embeds:
                    await interaction.followup.send("❌ У заявки отсутствует embed.", ephemeral=True)
                    return

                embed = message.embeds[0]

                # Защита от повторной обработки
                for field in embed.fields:
                    fname = (field.name or "").lower()
                    if "выдано" in fname or "отказ" in fname:
                        await interaction.followup.send("⚠️ Эта заявка уже обработана.", ephemeral=True)
                        return

                # Извлекаем предметы из embed
                items = self._parse_items_from_embed(embed, include_category=False)
                if not items:
                    await interaction.followup.send(
                        "❌ Не удалось распознать предметы в заявке. Проверьте формат embed.",
                        ephemeral=True
                    )
                    return

                try:
                    audit = WarehouseAudit(interaction.client)
                    await audit.log_issue(
                        staff_member=interaction.user,
                        requester_id=self.author_id,
                        items=items,
                        message_link=message.jump_url
                    )
                except discord.Forbidden:
                    logger.warning("Склад: нет прав для отправки аудита выдачи (msg_id=%s)", self.message_id)
                except discord.HTTPException as e:
                    logger.warning("Склад: HTTP ошибка аудита выдачи (msg_id=%s): %s", self.message_id, e)
                except Exception as e:
                    logger.warning("Склад: ошибка аудита выдачи (msg_id=%s): %s", self.message_id, e, exc_info=True)

                # Обновляем embed
                embed.color = discord.Color.green()
                embed.add_field(
                    name="✅ ВЫДАНО",
                    value=(
                        f"Сотрудник: {interaction.user.mention}\n"
                        f"Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
                    ),
                    inline=False
                )

                # Кулдаун регистрируем только перед успешным завершением
                warehouse_cooldown.register_issue(self.author_id)

                # Удаляем из БД и памяти
                try:
                    from database import delete_warehouse_request
                    await asyncio.to_thread(delete_warehouse_request, self.message_id)
                except Exception as e:
                    logger.warning("Склад: не удалось удалить запись из БД после выдачи: %s", e, exc_info=True)

                if hasattr(state, "warehouse_requests"):
                    state.warehouse_requests.pop(self.message_id, None)

                # Убираем кнопки
                try:
                    await message.edit(embed=embed, view=None)
                except discord.NotFound:
                    await interaction.followup.send("❌ Сообщение заявки было удалено.", ephemeral=True)
                    return
                except discord.Forbidden:
                    await interaction.followup.send("❌ У бота нет прав на редактирование сообщения.", ephemeral=True)
                    return
                except discord.HTTPException as e:
                    logger.warning("Склад accept: HTTP ошибка edit %s: %s", self.message_id, e)
                    await interaction.followup.send("❌ Ошибка Discord API при обновлении заявки.", ephemeral=True)
                    return

                await interaction.followup.send(
                    "✅ Снаряжение выдано! Данные отправлены в аудит.",
                    ephemeral=True
                )

                logger.info("Склад выдал %s для %s (msg_id=%s)", interaction.user.id, self.author_id, self.message_id)

        except RuntimeError as e:
            if str(e) == "ACTION_ALREADY_IN_PROGRESS":
                await interaction.followup.send("⚠️ Этот запрос уже обрабатывается другим нажатием.", ephemeral=True)
                return
            logger.error("Ошибка блокировки склада (выдача): %s", e, exc_info=True)
            await interaction.followup.send("❌ Ошибка", ephemeral=True)

        except Exception as e:
            logger.error("Ошибка при выдаче склада: %s", e, exc_info=True)
            await interaction.followup.send("❌ Ошибка", ephemeral=True)

    async def handle_edit(self, interaction: discord.Interaction):
        """Редактирование запроса - открывает отдельную корзину редактирования"""
        try:
            async with action_lock(self.message_id, "редактирование запроса склада"):
                # Получаем сообщение заявки
                try:
                    message = await self._fetch_request_message(interaction)
                    if not message:
                        if interaction.response.is_done():
                            await interaction.followup.send("❌ Сообщение заявки не найдено.", ephemeral=True)
                        else:
                            await interaction.response.send_message("❌ Сообщение заявки не найдено.", ephemeral=True)
                        return
                except discord.Forbidden:
                    if interaction.response.is_done():
                        await interaction.followup.send("❌ У бота нет доступа к сообщению заявки.", ephemeral=True)
                    else:
                        await interaction.response.send_message("❌ У бота нет доступа к сообщению заявки.", ephemeral=True)
                    return
                except discord.HTTPException as e:
                    logger.warning("Склад edit: HTTP ошибка fetch_message %s: %s", self.message_id, e)
                    if interaction.response.is_done():
                        await interaction.followup.send("❌ Ошибка Discord API при получении сообщения.", ephemeral=True)
                    else:
                        await interaction.response.send_message("❌ Ошибка Discord API при получении сообщения.", ephemeral=True)
                    return

                if not message.embeds:
                    if interaction.response.is_done():
                        await interaction.followup.send("❌ У заявки отсутствует embed.", ephemeral=True)
                    else:
                        await interaction.response.send_message("❌ У заявки отсутствует embed.", ephemeral=True)
                    return

                embed = message.embeds[0]

                # Защита от повторной обработки (уже выдано/отказано)
                for field in embed.fields:
                    fname = (field.name or "").lower()
                    if "выдано" in fname or "отказ" in fname:
                        if interaction.response.is_done():
                            await interaction.followup.send("⚠️ Эта заявка уже обработана и не может быть отредактирована.", ephemeral=True)
                        else:
                            await interaction.response.send_message("⚠️ Эта заявка уже обработана и не может быть отредактирована.", ephemeral=True)
                        return

                # Парсим предметы из embed
                items = self._parse_items_from_embed(embed, include_category=True)

                if not items:
                    if interaction.response.is_done():
                        await interaction.followup.send("❌ Не удалось загрузить предметы для редактирования", ephemeral=True)
                    else:
                        await interaction.response.send_message("❌ Не удалось загрузить предметы для редактирования", ephemeral=True)
                    return

                # ВАЖНО: используем отдельную временную сессию редактирования, чтобы не затирать обычную корзину пользователя
                edit_session_key = f"warehouse_edit:{interaction.user.id}:{self.message_id}"
                WarehouseSession.set_items(edit_session_key, items)

                cart_embed = discord.Embed(
                    title="🛒 РЕДАКТИРОВАНИЕ ЗАПРОСА",
                    color=discord.Color.blue(),
                    description=(
                        "**Текущий состав:**\n"
                        "После нажатия **ОТПРАВИТЬ** будет создана новая заявка, а старая заменится автоматически."
                    )
                )

                for item in items:
                    cart_embed.add_field(
                        name=item["item"],
                        value=f"Количество: **{item['quantity']}** шт",
                        inline=False
                    )

                view = WarehouseActionView(
                    session_key=edit_session_key,
                    request_owner_id=self.author_id,
                    editing_request_message_id=self.message_id,
                )

                await interaction.response.send_message(
                    embed=cart_embed,
                    view=view,
                    ephemeral=True
                )

                logger.info(
                    "Загружено %s предметов для редактирования | editor=%s | owner=%s | msg_id=%s | session=%s",
                    len(items),
                    interaction.user.id,
                    self.author_id,
                    self.message_id,
                    edit_session_key,
                )

        except RuntimeError as e:
            logger.info("Склад edit lock: %s", e)
            if interaction.response.is_done():
                await interaction.followup.send("⏳ Эта заявка уже редактируется. Попробуйте через пару секунд.", ephemeral=True)
            else:
                await interaction.response.send_message("⏳ Эта заявка уже редактируется. Попробуйте через пару секунд.", ephemeral=True)
        except Exception as e:
            logger.error("Ошибка при редактировании заявки: %s", e, exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send("❌ Ошибка при редактировании заявки", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Ошибка при редактировании заявки", ephemeral=True)