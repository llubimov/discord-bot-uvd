import discord
from discord.ui import View, Button, Select
import logging
import re
from datetime import datetime

from config import Config
from views.warehouse_theme import BLUE, GOLD, GREEN, RED
from views.warehouse_embeds import build_cart_embed
from services.warehouse_session import WarehouseSession
from services import warehouse_cooldown
from services.warehouse_audit import WarehouseAudit
from views.warehouse_selectors import CategorySelect, _embed_add_step1
from modals.warehouse_edit import WarehouseEditModal

logger = logging.getLogger(__name__)

# Формат даты/времени в футере заявки (при смене — обновить и regex CREATED_PATTERN ниже)
WAREHOUSE_FOOTER_DATETIME_FMT = "%d.%m.%Y %H:%M"
CREATED_PATTERN = re.compile(r"Создано:\s*(\d{2}\.\d{2}\.\d{4}\s+\d{1,2}:\d{2})")


class ItemSelectForEdit(Select):
    def __init__(
        self,
        items: list,
        owner_id: int,
        session_key=None,
        request_owner_id: int | None = None,
        editing_request_message_id: int | None = None,
        mode: str = "request",
    ):
        options = []
        self.items = items
        self.owner_id = owner_id
        self.session_key = session_key if session_key is not None else owner_id
        self.request_owner_id = request_owner_id
        self.editing_request_message_id = editing_request_message_id
        self.mode = mode if mode in ("request", "issue") else "request"

        for idx, item in enumerate(items):
            options.append(
                discord.SelectOption(
                    label=f"{item['item']} ({item['quantity']} шт)",
                    value=str(idx),
                    description=f"Категория: {item['category']}"
                )
            )

        super().__init__(
            placeholder="Выбери предмет для редактирования...",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Это не ваша корзина.", ephemeral=True)
            return

        try:
            idx = int(self.values[0])
        except (TypeError, ValueError):
            await interaction.response.send_message("❌ Не удалось определить выбранный предмет.", ephemeral=True)
            return

        current_items = WarehouseSession.get_items(self.session_key)
        if not (0 <= idx < len(current_items)):
            await interaction.response.send_message("❌ Список предметов устарел. Открой корзину заново.", ephemeral=True)
            return

        item = current_items[idx]

        modal = WarehouseEditModal(
            allowed_user_id=interaction.user.id,
            session_key=self.session_key,
            category=item['category'],
            item_name=item['item'],
            current_quantity=item['quantity'],
            item_index=idx,
            request_owner_id=self.request_owner_id,
            editing_request_message_id=self.editing_request_message_id,
            mode=self.mode,
        )
        await interaction.response.send_modal(modal)


class WarehouseActionView(View):
    def __init__(
        self,
        session_key=None,
        request_owner_id: int | None = None,
        editing_request_message_id: int | None = None,
        mode: str = "request",
    ):
        super().__init__(timeout=Config.WAREHOUSE_CART_TIMEOUT)
        self.session_key = session_key
        self.request_owner_id = request_owner_id
        self.editing_request_message_id = editing_request_message_id
        self.mode = mode if mode in ("request", "issue") else "request"

        # При редактировании чужой заявки сотрудником (режим issue) скрываем кнопки добавления.
        if self.mode == "issue":
            add_callbacks = (
                self.add_more_button,
                self.grom_kit_button,
                self.common_mid_button,
                self.common_heavy_button,
            )
            for child in list(self.children):
                if isinstance(child, Button) and getattr(child, "callback", None) in add_callbacks:
                    self.remove_item(child)

    def _session_key(self, interaction: discord.Interaction):
        return self.session_key if self.session_key is not None else interaction.user.id

    def _owner_id(self, interaction: discord.Interaction) -> int:
        return self.request_owner_id if self.request_owner_id is not None else interaction.user.id

    async def _add_preset_items(
        self,
        interaction: discord.Interaction,
        session_key,
        items: list[tuple[str, str, int]],
        preset_name: str,
    ):
        added: list[str] = []
        skipped: list[str] = []

        for category, item_name, qty in items:
            success, error_msg = WarehouseSession.add_item(session_key, category, item_name, qty)
            if success:
                added.append(f"{item_name} × {qty}")
            else:
                skipped.append(f"{item_name} × {qty} — {error_msg.replace('❌ ', '')}")

        if not added and skipped:
            embed = discord.Embed(
                title=preset_name,
                description="Не помещается в корзину (лимиты или дубли).",
                color=RED,
            )
            embed.add_field(name="Не добавлено", value="\n".join(f"• {s}" for s in skipped), inline=False)
        else:
            embed = discord.Embed(title=preset_name, color=GREEN if not skipped else GOLD)
            if added:
                embed.add_field(name="✅ Добавлено", value="\n".join(f"• {s}" for s in added), inline=False)
            if skipped:
                embed.add_field(name="⚠️ Не добавлено", value="\n".join(f"• {s}" for s in skipped), inline=False)

        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        return added, skipped

    @discord.ui.button(
        label="ДОБАВИТЬ ЕЩЕ",
        style=discord.ButtonStyle.success,
        emoji="➕",
        row=0
    )
    async def add_more_button(self, interaction: discord.Interaction, button: Button):
        if self.mode == "issue" and self.request_owner_id and interaction.user.id != self.request_owner_id:
            await interaction.response.send_message(
                "❌ Нельзя добавлять новые предметы при редактировании чужой заявки.",
                ephemeral=True,
            )
            return
        session_key = self._session_key(interaction)
        logger.info("Текущая корзина (%s): %s", session_key, WarehouseSession.get_items(session_key))

        embed = _embed_add_step1(session_key)
        view = View(timeout=Config.WAREHOUSE_SUBVIEW_TIMEOUT)
        view.add_item(
            CategorySelect(
                session_key=session_key,
                request_owner_id=self._owner_id(interaction),
                editing_request_message_id=self.editing_request_message_id,
            )
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(
        label="РЕДАКТИРОВАТЬ",
        style=discord.ButtonStyle.secondary,
        emoji="✏️",
        row=0
    )
    async def edit_button(self, interaction: discord.Interaction, button: Button):
        session_key = self._session_key(interaction)
        owner_id = interaction.user.id
        items = WarehouseSession.get_items(session_key)

        if not items:
            await interaction.response.send_message(
                "❌ Корзина пуста! Нечего редактировать.",
                ephemeral=True
            )
            return

        view = View(timeout=Config.WAREHOUSE_SUBVIEW_TIMEOUT)
        view.add_item(
            ItemSelectForEdit(
                items,
                owner_id=owner_id,
                session_key=session_key,
                request_owner_id=self.request_owner_id,
                editing_request_message_id=self.editing_request_message_id,
                mode=self.mode,
            )
        )

        async def back_cb(back_interaction: discord.Interaction):
            if back_interaction.user.id != owner_id:
                await back_interaction.response.send_message(
                    "❌ Только тот, кто открыл редактирование, может нажимать.",
                    ephemeral=True,
                )
                return
            from views.warehouse_request_buttons import build_edit_cart_embed

            is_staff = self.mode == "issue"
            cart_embed = build_edit_cart_embed(session_key, is_staff)
            back_view = WarehouseActionView(
                session_key=session_key,
                request_owner_id=self.request_owner_id,
                editing_request_message_id=self.editing_request_message_id,
                mode=self.mode,
            )
            await back_interaction.response.edit_message(
                content=None,
                embed=cart_embed,
                view=back_view,
            )

        back_btn = Button(
            label="Назад к заявке",
            style=discord.ButtonStyle.secondary,
            emoji="◀️",
            row=1,
        )
        back_btn.callback = back_cb
        view.add_item(back_btn)

        await interaction.response.edit_message(
            content="**✏️ Редактирование**\nВыбери предмет, чтобы изменить количество (или **Назад к заявке** — чтобы вернуться и нажать ОТПРАВИТЬ):",
            embed=None,
            view=view
        )

    @discord.ui.button(
        label="УДАЛИТЬ",
        style=discord.ButtonStyle.secondary,
        emoji="🗑️",
        row=0
    )
    async def delete_button(self, interaction: discord.Interaction, button: Button):
        owner_id = interaction.user.id
        session_key = self._session_key(interaction)
        items = WarehouseSession.get_items(session_key)

        if not items:
            await interaction.response.send_message("❌ Корзина пуста!", ephemeral=True)
            return

        options = []
        for idx, item in enumerate(items):
            options.append(
                discord.SelectOption(
                    label=f"{item['item']} ({item['quantity']} шт)",
                    value=str(idx),
                    description=f"Категория: {item['category']}"
                )
            )

        select = Select(
            placeholder="Выбери предмет для удаления...",
            options=options,
            min_values=1,
            max_values=1
        )

        async def delete_callback(select_interaction: discord.Interaction):
            if select_interaction.user.id != owner_id:
                await select_interaction.response.send_message("❌ Это не ваша корзина.", ephemeral=True)
                return

            try:
                idx = int(select.values[0])
            except (TypeError, ValueError):
                await select_interaction.response.send_message("❌ Не удалось определить выбранный предмет.", ephemeral=True)
                return

            current_items = WarehouseSession.get_items(session_key)
            if not (0 <= idx < len(current_items)):
                await select_interaction.response.send_message(
                    "❌ Предмет уже удалён или список устарел. Открой корзину заново.",
                    ephemeral=True,
                )
                return

            removed = current_items.pop(idx)

            if not current_items:
                await select_interaction.response.edit_message(
                    content="🗑️ Предмет удалён. Корзина пуста.",
                    embed=None,
                    view=None
                )
            else:
                embed = discord.Embed(
                    title="🛒 Корзина обновлена",
                    description="Текущий состав",
                    color=BLUE,
                )
                for it in current_items:
                    embed.add_field(
                        name=it['item'],
                        value=f"**{it['quantity']}** шт",
                        inline=False
                    )
                await select_interaction.response.edit_message(
                    content=f"Удалено: **{removed['item']}**",
                    embed=embed,
                    view=self
                )

            logger.info("%s удалил %s из сессии %s", owner_id, removed['item'], session_key)

        select.callback = delete_callback
        view = View(timeout=Config.WAREHOUSE_SUBVIEW_TIMEOUT)
        view.add_item(select)

        await interaction.response.edit_message(
            content="**🗑️ Удаление**\nВыбери предмет для удаления из корзины:",
            embed=None,
            view=view
        )

    @discord.ui.button(
        label="⚡ КОМПЛЕКТ ГРОМ",
        style=discord.ButtonStyle.secondary,
        emoji="⚡",
        row=2
    )
    async def grom_kit_button(self, interaction: discord.Interaction, button: Button):
        if self.mode == "issue" and self.request_owner_id and interaction.user.id != self.request_owner_id:
            await interaction.response.send_message(
                "❌ Нельзя добавлять быстрые комплекты при редактировании чужой заявки.",
                ephemeral=True,
            )
            return
        session_key = self._session_key(interaction)
        items = [
            ("💊 медикаменты", "Обезболивающее", 8),
            ("💊 медикаменты", "Аптечка", 10),
            ("🛡️ бронежилеты", "Тяжелый бронежилет", 10),
            ("🔫 оружие", "Пулемет M249", 1),
        ]
        await interaction.response.defer(ephemeral=True)
        await self._add_preset_items(interaction, session_key, items, "⚡ Экстренный комплект ГРОМа")
        cart_embed = build_cart_embed(WarehouseSession.get_items(session_key), is_request=True)
        try:
            await interaction.message.edit(embed=cart_embed, view=self)
        except discord.HTTPException:
            pass

    @discord.ui.button(
        label="10 средних + Канада",
        style=discord.ButtonStyle.secondary,
        emoji="🚑",
        row=2
    )
    async def common_mid_button(self, interaction: discord.Interaction, button: Button):
        if self.mode == "issue" and self.request_owner_id and interaction.user.id != self.request_owner_id:
            await interaction.response.send_message(
                "❌ Нельзя добавлять быстрые комплекты при редактировании чужой заявки.",
                ephemeral=True,
            )
            return
        session_key = self._session_key(interaction)
        items = [
            ("💊 медикаменты", "Обезболивающее", 5),
            ("💊 медикаменты", "Аптечка", 5),
            ("🛡️ бронежилеты", "Средний бронежилет", 10),
            ("🔫 оружие", "Канада", 1),
        ]
        await interaction.response.defer(ephemeral=True)
        await self._add_preset_items(interaction, session_key, items, "🚑 Общий: 10 средних + Канада")
        cart_embed = build_cart_embed(WarehouseSession.get_items(session_key), is_request=True)
        try:
            await interaction.message.edit(embed=cart_embed, view=self)
        except discord.HTTPException:
            pass

    @discord.ui.button(
        label="5 тяжёлых + M16",
        style=discord.ButtonStyle.secondary,
        emoji="🚑",
        row=2
    )
    async def common_heavy_button(self, interaction: discord.Interaction, button: Button):
        if self.mode == "issue" and self.request_owner_id and interaction.user.id != self.request_owner_id:
            await interaction.response.send_message(
                "❌ Нельзя добавлять быстрые комплекты при редактировании чужой заявки.",
                ephemeral=True,
            )
            return
        session_key = self._session_key(interaction)
        items = [
            ("💊 медикаменты", "Обезболивающее", 5),
            ("💊 медикаменты", "Аптечка", 5),
            ("🛡️ бронежилеты", "Тяжелый бронежилет", 5),
            ("🔫 оружие", "Кольт M16", 1),
        ]
        await interaction.response.defer(ephemeral=True)
        await self._add_preset_items(interaction, session_key, items, "🚑 Общий: 5 тяжёлых + M16")
        cart_embed = build_cart_embed(WarehouseSession.get_items(session_key), is_request=True)
        try:
            await interaction.message.edit(embed=cart_embed, view=self)
        except discord.HTTPException:
            pass

    @discord.ui.button(
        label="ОТПРАВИТЬ",
        style=discord.ButtonStyle.primary,
        emoji="📨",
        row=1
    )
    async def send_request_button(self, interaction: discord.Interaction, button: Button):
        session_key = self._session_key(interaction)
        requester_id = self._owner_id(interaction)
        editor_id = interaction.user.id
        items = WarehouseSession.get_items(session_key)

        if not items:
            await interaction.response.send_message("❌ Корзина пуста!", ephemeral=True)
            return

        requester_member = None
        if interaction.guild:
            requester_member = interaction.guild.get_member(requester_id)
            if requester_member is None:
                try:
                    requester_member = await interaction.guild.fetch_member(requester_id)
                except Exception:
                    requester_member = None

        author_name = requester_member.display_name if requester_member else f"ID {requester_id}"
        author_avatar = requester_member.avatar.url if (requester_member and requester_member.avatar) else None

        embed = discord.Embed(
            title="📋 Заявка на снаряжение",
            color=GOLD,
            timestamp=datetime.now()
        )

        embed.set_author(name=author_name, icon_url=author_avatar)

        by_category = {}
        for item in items:
            cat = item['category']
            by_category.setdefault(cat, []).append(item)

        for cat, cat_items in by_category.items():
            value = ""
            for it in cat_items:
                value += f"• {it['item']} — **{it['quantity']}** шт\n"
            embed.add_field(name=cat, value=value, inline=False)

        weapon_count = sum(int(it.get('quantity', 0)) for it in items if "оружие" in str(it.get('category', '')).lower())
        armor_count = sum(int(it.get('quantity', 0)) for it in items if "бронежилеты" in str(it.get('category', '')).lower())
        meds_count = sum(int(it.get('quantity', 0)) for it in items if "медикаменты" in str(it.get('category', '')).lower())

        stats = []
        if weapon_count > 0:
            stats.append(f"🔫 Оружие: {weapon_count} ед")
        if armor_count > 0:
            stats.append(f"🛡️ Броня: {armor_count} шт")
        if meds_count > 0:
            stats.append(f"💊 Медицина: {meds_count} шт")

        if stats:
            embed.add_field(name="📊 Итого", value=" · ".join(stats), inline=False)

        embed.add_field(name="Статус", value="🟡 В очереди", inline=False)

        # Канал склада через кэш, если он инициализирован
        channel = None
        try:
            import state as _state_for_channel  # локальный импорт, чтобы не ломать существующие импорты
            cache = getattr(_state_for_channel, "channel_cache", None)
            if cache is not None:
                channel = cache.get_channel(Config.WAREHOUSE_REQUEST_CHANNEL_ID)
        except Exception:
            channel = None
        if channel is None:
            channel = interaction.client.get_channel(Config.WAREHOUSE_REQUEST_CHANNEL_ID)
        if not channel:
            await interaction.response.send_message("❌ Канал не найден", ephemeral=True)
            return

        old_msg = None
        if self.editing_request_message_id:
            try:
                old_msg = await channel.fetch_message(int(self.editing_request_message_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        now_str = datetime.now().strftime(WAREHOUSE_FOOTER_DATETIME_FMT)
        created_str = now_str
        if old_msg and editor_id != requester_id and old_msg.embeds and old_msg.embeds[0].footer and old_msg.embeds[0].footer.text:
            m = CREATED_PATTERN.search(old_msg.embeds[0].footer.text)
            if m:
                created_str = m.group(1).strip()
        if self.editing_request_message_id and editor_id != requester_id:
            editor_name = interaction.user.display_name
            footer_text = f"Создано: {created_str} | отредактировано: {now_str} | Редактировал: {editor_name}"
        else:
            footer_text = f"Создано: {created_str}"
        embed.set_footer(text=footer_text)

        from database import save_warehouse_request, delete_warehouse_request
        import asyncio
        import state

        staff_role = None
        if interaction.guild:
            try:
                role_cache = getattr(state, "role_cache", None)
            except Exception:
                role_cache = None
            if role_cache is not None:
                staff_role = await role_cache.get_role(interaction.guild.id, Config.WAREHOUSE_STAFF_ROLE_ID)
            else:
                staff_role = interaction.guild.get_role(Config.WAREHOUSE_STAFF_ROLE_ID)
        is_staff = bool(staff_role and staff_role in (interaction.user.roles or []))

        if self.mode == "issue" and self.editing_request_message_id and is_staff:
            if old_msg is None:
                await interaction.response.edit_message(
                    content="❌ Исходная заявка не найдена. Возможно, она уже удалена.",
                    embed=None,
                    view=None,
                )
                return
            original_msg = old_msg
            try:
                audit = WarehouseAudit(interaction.client)
                await audit.log_issue(
                    staff_member=interaction.user,
                    requester_id=requester_id,
                    items=items,
                    message_link=original_msg.jump_url,
                )
            except discord.Forbidden:
                logger.warning(
                    "Склад issue-edit: нет прав для отправки аудита (msg_id=%s)",
                    self.editing_request_message_id,
                )
            except discord.HTTPException as e:
                logger.warning(
                    "Склад issue-edit: HTTP ошибка аудита (msg_id=%s): %s",
                    self.editing_request_message_id,
                    e,
                )
            except Exception as e:
                logger.warning(
                    "Склад issue-edit: ошибка аудита (msg_id=%s): %s",
                    self.editing_request_message_id,
                    e,
                    exc_info=True,
                )

            embed.color = GREEN

            updated_status = False
            for i, field in enumerate(embed.fields):
                if (field.name or "").strip() == "Статус":
                    embed.set_field_at(i, name="Статус", value="🟢 Выдано", inline=False)
                    updated_status = True
                    break
            if not updated_status:
                embed.add_field(name="Статус", value="🟢 Выдано", inline=False)
            embed.add_field(
                name="✅ Выдано (после редактирования)",
                value=(
                    f"Сотрудник: {interaction.user.mention}\n"
                    f"Время: {datetime.now().strftime(WAREHOUSE_FOOTER_DATETIME_FMT)}"
                ),
                inline=False,
            )

            try:
                await original_msg.edit(embed=embed, view=None)
            except discord.NotFound:
                await interaction.response.edit_message(
                    content="❌ Исходная заявка была удалена до обновления.",
                    embed=None,
                    view=None,
                )
                return
            except discord.Forbidden:
                await interaction.response.edit_message(
                    content="❌ У бота нет прав на редактирование исходной заявки.",
                    embed=None,
                    view=None,
                )
                return
            except discord.HTTPException as e:
                logger.warning(
                    "Склад issue-edit: HTTP ошибка edit %s: %s",
                    self.editing_request_message_id,
                    e,
                    exc_info=True,
                )
                await interaction.response.edit_message(
                    content="❌ Ошибка Discord API при обновлении заявки.",
                    embed=None,
                    view=None,
                )
                return

            warehouse_cooldown.register_issue(requester_id)

            try:
                await delete_warehouse_request(int(self.editing_request_message_id))
            except Exception as e:
                logger.warning(
                    "Склад issue-edit: не удалось удалить запись из БД после выдачи: %s",
                    e,
                    exc_info=True,
                )

            if hasattr(state, "warehouse_requests"):
                state.warehouse_requests.pop(int(self.editing_request_message_id), None)

            await interaction.response.edit_message(
                content="✅ Снаряжение выдано с учётом правок. Заявка обновлена.",
                embed=None,
                view=None,
            )

            WarehouseSession.clear_session(session_key)
            logger.info(
                "Склад выдал (issue-edit) %s для %s (old_msg_id=%s)",
                interaction.user.id,
                requester_id,
                self.editing_request_message_id,
            )
            return

        from views.warehouse_request_buttons import WarehouseRequestView
        view = WarehouseRequestView(requester_id, 0)

        staff_role_mention = f"<@&{Config.WAREHOUSE_STAFF_ROLE_ID}>"
        if editor_id != requester_id:
            content = f"{staff_role_mention} • <@{requester_id}>\n✏️ Отредактировал: <@{editor_id}>"
            embed.add_field(
                name="✏️ Редактировал",
                value=f"<@{editor_id}>",
                inline=False,
            )
        else:
            content = f"{staff_role_mention} • <@{requester_id}>"

        sent_message = await channel.send(content=content, embed=embed, view=view)

        request_data = {
            'user_id': requester_id,
            'items': [dict(item) for item in items],
            'message_id': sent_message.id,
            'created_at': datetime.now().isoformat(),
        }
        if self.editing_request_message_id:
            request_data['edited_by'] = editor_id
            request_data['replaces_message_id'] = self.editing_request_message_id

        await save_warehouse_request(sent_message.id, request_data)

        view.message_id = sent_message.id
        await sent_message.edit(view=view)

        if self.editing_request_message_id:
            old_message_id = self.editing_request_message_id
            try:
                old_msg = await channel.fetch_message(old_message_id)
                await old_msg.delete()
                logger.info("Старая заявка %s удалена после успешного пересоздания", old_message_id)
            except discord.NotFound:
                logger.info("Старая заявка %s уже удалена к моменту пересоздания", old_message_id)
            except discord.Forbidden:
                logger.warning("Нет прав удалить старую заявку %s после пересоздания", old_message_id)
            except discord.HTTPException as e:
                logger.warning("HTTP ошибка удаления старой заявки %s после пересоздания: %s", old_message_id, e)

            try:
                await delete_warehouse_request(old_message_id)
            except Exception as e:
                logger.warning("Не удалось удалить старую запись склада %s из БД: %s", old_message_id, e, exc_info=True)

            if hasattr(state, "warehouse_requests"):
                state.warehouse_requests.pop(old_message_id, None)

        if hasattr(state, "warehouse_requests"):
            state.warehouse_requests[sent_message.id] = request_data

        await interaction.response.edit_message(
            content="✅ Запрос отправлен!",
            embed=None,
            view=None
        )

        WarehouseSession.clear_session(session_key)

    @discord.ui.button(
        label="ОЧИСТИТЬ",
        style=discord.ButtonStyle.secondary,
        emoji="♻️",
        row=1
    )
    async def clear_button(self, interaction: discord.Interaction, button: Button):
        session_key = self._session_key(interaction)
        WarehouseSession.clear_session(session_key)

        await interaction.response.edit_message(
            content="🧹 Корзина очищена. Нажми **ДОБАВИТЬ ЕЩЕ** или выбери быстрый комплект.",
            embed=None,
            view=self
        )

    @discord.ui.button(
        label="ОТМЕНИТЬ",
        style=discord.ButtonStyle.secondary,
        emoji="❌",
        row=1
    )
    async def cancel_button(self, interaction: discord.Interaction, button: Button):
        session_key = self._session_key(interaction)
        WarehouseSession.clear_session(session_key)

        if self.editing_request_message_id:
            text = "❌ Редактирование отменено. Исходная заявка не изменена."
            # Возвращаем статус заявки в канале на «В очереди»
            if interaction.channel:
                try:
                    msg = await interaction.channel.fetch_message(self.editing_request_message_id)
                    if msg.embeds:
                        embed = msg.embeds[0]
                        for i, field in enumerate(embed.fields):
                            if (field.name or "").strip() == "Статус":
                                embed.set_field_at(i, name="Статус", value="🟡 В очереди", inline=False)
                                break
                        await msg.edit(embed=embed)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                    logger.warning(
                        "Склад cancel: не удалось вернуть статус сообщения %s: %s",
                        self.editing_request_message_id,
                        e,
                    )
        else:
            text = "❌ Запрос отменен."

        await interaction.response.edit_message(
            content=text,
            embed=None,
            view=None
        )
