"""
=====================================================
УПРАВЛЕНИЕ КОРЗИНОЙ
=====================================================
"""

import discord
from discord.ui import View, Button, Select
import logging
from datetime import datetime
from config import Config
from services.warehouse_session import WarehouseSession
from views.warehouse_selectors import CategorySelect
from modals.warehouse_edit import WarehouseEditModal

logger = logging.getLogger(__name__)


class ItemSelectForEdit(Select):
    """Выбор предмета для редактирования"""

    def __init__(self, items: list, owner_id: int, session_key=None):
        options = []
        self.items = items
        self.owner_id = owner_id
        self.session_key = session_key if session_key is not None else owner_id

        for idx, item in enumerate(items):
            options.append(
                discord.SelectOption(
                    label=f"{item['item']} ({item['quantity']} шт)",
                    value=str(idx),
                    description=f"Категория: {item['category']}"
                )
            )

        super().__init__(
            placeholder="🔽 Выбери предмет для редактирования...",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        """Открываем модалку редактирования"""
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
            item_index=idx
        )
        await interaction.response.send_modal(modal)


class WarehouseActionView(View):
    """Кнопки для управления корзиной"""

    def __init__(self, session_key=None, request_owner_id: int | None = None, editing_request_message_id: int | None = None):
        super().__init__(timeout=300)
        self.session_key = session_key
        self.request_owner_id = request_owner_id
        self.editing_request_message_id = editing_request_message_id

    def _session_key(self, interaction: discord.Interaction):
        return self.session_key if self.session_key is not None else interaction.user.id

    def _owner_id(self, interaction: discord.Interaction) -> int:
        return self.request_owner_id if self.request_owner_id is not None else interaction.user.id

    @discord.ui.button(
        label="ДОБАВИТЬ ЕЩЕ",
        style=discord.ButtonStyle.success,
        emoji="➕",
        row=0
    )
    async def add_more_button(self, interaction: discord.Interaction, button: Button):
        """Добавить еще предмет"""
        session_key = self._session_key(interaction)
        items = WarehouseSession.get_items(session_key)
        logger.info("Текущая корзина (%s): %s", session_key, items)

        view = View(timeout=180)
        view.add_item(
            CategorySelect(
                session_key=session_key,
                request_owner_id=self._owner_id(interaction),
                editing_request_message_id=self.editing_request_message_id,
            )
        )

        await interaction.response.edit_message(
            content="**📦 Выбери следующую категорию:**\n*(текущая корзина сохраняется)*",
            embed=None,
            view=view
        )

    @discord.ui.button(
        label="РЕДАКТИРОВАТЬ",
        style=discord.ButtonStyle.secondary,
        emoji="✏️",
        row=0
    )
    async def edit_button(self, interaction: discord.Interaction, button: Button):
        """Редактировать корзину"""
        session_key = self._session_key(interaction)
        owner_id = interaction.user.id  # редактировать корзину может только тот, кто открыл окно
        items = WarehouseSession.get_items(session_key)

        if not items:
            await interaction.response.send_message(
                "❌ Корзина пуста! Нечего редактировать.",
                ephemeral=True
            )
            return

        view = View(timeout=180)
        view.add_item(ItemSelectForEdit(items, owner_id=owner_id, session_key=session_key))

        await interaction.response.edit_message(
            content="**✏️ Редактирование корзины**\nВыбери предмет для изменения количества:",
            embed=None,
            view=view
        )

    @discord.ui.button(
        label="УДАЛИТЬ",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
        row=0
    )
    async def delete_button(self, interaction: discord.Interaction, button: Button):
        """Удалить предмет из корзины"""
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
            placeholder="🔽 Выбери предмет для удаления...",
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
                    content="🗑️ Предмет удален. Корзина пуста.",
                    embed=None,
                    view=None
                )
            else:
                embed = discord.Embed(
                    title="🛒 КОРЗИНА ОБНОВЛЕНА",
                    color=discord.Color.blue(),
                    description="**Текущий состав:**"
                )

                for it in current_items:
                    embed.add_field(
                        name=it['item'],
                        value=f"Количество: **{it['quantity']}** шт",
                        inline=False
                    )

                await select_interaction.response.edit_message(
                    content=f"🗑️ Удалено: {removed['item']}",
                    embed=embed,
                    view=self
                )

            logger.info("%s удалил %s из сессии %s", owner_id, removed['item'], session_key)

        select.callback = delete_callback
        view = View(timeout=180)
        view.add_item(select)

        await interaction.response.edit_message(
            content="**🗑️ Удаление предметов**\nВыбери что удалить:",
            embed=None,
            view=view
        )

    @discord.ui.button(
        label="ОТПРАВИТЬ",
        style=discord.ButtonStyle.primary,
        emoji="📨",
        row=1
    )
    async def send_request_button(self, interaction: discord.Interaction, button: Button):
        """Отправить запрос в канал"""
        session_key = self._session_key(interaction)
        requester_id = self._owner_id(interaction)
        editor_id = interaction.user.id
        items = WarehouseSession.get_items(session_key)

        if not items:
            await interaction.response.send_message("❌ Корзина пуста!", ephemeral=True)
            return

        # Готовим данные автора заявки (если редактирует не автор, сохраняем автора оригинала)
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
            title="📋 ЗАЯВКА НА СНАРЯЖЕНИЕ",
            color=discord.Color.gold(),
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
            embed.add_field(name="📊 Итого", value=" | ".join(stats), inline=False)

        footer_text = f"Запрос создан: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        if self.editing_request_message_id:
            footer_text += f" | ред. #{self.editing_request_message_id}"
        embed.set_footer(text=footer_text)

        channel = interaction.client.get_channel(Config.WAREHOUSE_REQUEST_CHANNEL_ID)
        if not channel:
            await interaction.response.send_message("❌ Канал не найден", ephemeral=True)
            return

        from views.warehouse_request_buttons import WarehouseRequestView
        view = WarehouseRequestView(requester_id, 0)

        staff_role = f"<@&{Config.WAREHOUSE_STAFF_ROLE_ID}>"
        if editor_id != requester_id:
            content = f"{staff_role} • <@{requester_id}>\n✏️ Отредактировал: <@{editor_id}>"
        else:
            content = f"{staff_role} • <@{requester_id}>"

        sent_message = await channel.send(content=content, embed=embed, view=view)

        from database import save_warehouse_request, delete_warehouse_request
        import asyncio
        import state

        request_data = {
            'user_id': requester_id,
            'items': [dict(item) for item in items],
            'message_id': sent_message.id,
            'created_at': datetime.now().isoformat(),
        }
        if self.editing_request_message_id:
            request_data['edited_by'] = editor_id
            request_data['replaces_message_id'] = self.editing_request_message_id

        await asyncio.to_thread(save_warehouse_request, sent_message.id, request_data)

        view.message_id = sent_message.id
        await sent_message.edit(view=view)

        # Если это редактирование уже существующей заявки — удаляем старую ТОЛЬКО после успешной отправки новой
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
                await asyncio.to_thread(delete_warehouse_request, old_message_id)
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
        label="ОТМЕНИТЬ",
        style=discord.ButtonStyle.danger,
        emoji="❌",
        row=1
    )
    async def cancel_button(self, interaction: discord.Interaction, button: Button):
        """Отменить запрос / режим редактирования"""
        session_key = self._session_key(interaction)
        WarehouseSession.clear_session(session_key)

        if self.editing_request_message_id:
            text = "❌ Редактирование отменено. Исходная заявка не изменена."
        else:
            text = "❌ Запрос отменен."

        await interaction.response.edit_message(
            content=text,
            embed=None,
            view=None
        )