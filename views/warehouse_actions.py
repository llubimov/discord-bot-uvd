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
    
    def __init__(self, items: list):
        options = []
        self.items = items
        
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
        idx = int(self.values[0])
        item = self.items[idx]
        
        modal = WarehouseEditModal(
            category=item['category'],
            item_name=item['item'],
            current_quantity=item['quantity'],
            item_index=idx
        )
        await interaction.response.send_modal(modal)

class WarehouseActionView(View):
    """Кнопки для управления корзиной"""
    
    def __init__(self):
        super().__init__(timeout=300)
    
    @discord.ui.button(
        label="ДОБАВИТЬ ЕЩЕ",
        style=discord.ButtonStyle.success,
        emoji="➕",
        row=0
    )
    async def add_more_button(self, interaction: discord.Interaction, button: Button):
        """Добавить еще предмет"""
        items = WarehouseSession.get_items(interaction.user.id)
        logger.info(f"Текущая корзина: {items}")
        
        view = View(timeout=180)
        view.add_item(CategorySelect())
        
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
        items = WarehouseSession.get_items(interaction.user.id)
        
        if not items:
            await interaction.response.send_message(
                "❌ Корзина пуста! Нечего редактировать.",
                ephemeral=True
            )
            return
        
        # Создаем View с выбором предмета
        view = View(timeout=180)
        view.add_item(ItemSelectForEdit(items))
        
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
        items = WarehouseSession.get_items(interaction.user.id)
        
        if not items:
            await interaction.response.send_message(
                "❌ Корзина пуста!",
                ephemeral=True
            )
            return
        
        # Показываем список для удаления
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
        
        async def delete_callback(select_interaction):
            idx = int(select.values[0])
            removed = items.pop(idx)
            
            # Если корзина опустела
            if not items:
                await select_interaction.response.edit_message(
                    content="🗑️ Предмет удален. Корзина пуста.",
                    embed=None,
                    view=None
                )
            else:
                # Показываем обновленную корзину
                embed = discord.Embed(
                    title="🛒 КОРЗИНА ОБНОВЛЕНА",
                    color=discord.Color.blue(),
                    description="**Текущий состав:**"
                )
                
                for it in items:
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
            
            logger.info(f"{interaction.user.id} удалил {removed['item']}")
        
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
        items = WarehouseSession.get_items(interaction.user.id)
        
        if not items:
            await interaction.response.send_message(
                "❌ Корзина пуста!",
                ephemeral=True
            )
            return
        
        # Создаем embed запроса
        embed = discord.Embed(
            title="📋 ЗАЯВКА НА СНАРЯЖЕНИЕ",
            color=discord.Color.gold(),
            timestamp=datetime.now()
        )
        
        embed.set_author(
            name=interaction.user.display_name,
            icon_url=interaction.user.avatar.url if interaction.user.avatar else None
        )
        
        # Группируем по категориям
        by_category = {}
        for item in items:
            cat = item['category']
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(item)
        
        for cat, cat_items in by_category.items():
            value = ""
            for it in cat_items:
                value += f"• {it['item']} — **{it['quantity']}** шт\n"
            embed.add_field(name=cat, value=value, inline=False)
        
        # Статистика
        weapon_count = sum(it['quantity'] for it in items if "оружие" in it['category'])
        armor_count = sum(it['quantity'] for it in items if "бронежилеты" in it['category'])
        meds_count = sum(it['quantity'] for it in items if "медикаменты" in it['category'])
        
        stats = []
        if weapon_count > 0:
            stats.append(f"🔫 Оружие: {weapon_count} ед")
        if armor_count > 0:
            stats.append(f"🛡️ Броня: {armor_count} шт")
        if meds_count > 0:
            stats.append(f"💊 Медицина: {meds_count} шт")
        
        if stats:
            embed.add_field(name="📊 Итого", value=" | ".join(stats), inline=False)
        
        embed.set_footer(text=f"Запрос создан: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        
        # Отправляем в канал
        channel = interaction.client.get_channel(Config.WAREHOUSE_REQUEST_CHANNEL_ID)
        if channel:
            from views.warehouse_request_buttons import WarehouseRequestView
            view = WarehouseRequestView(interaction.user.id, 0)
            
            staff_role = f"<@&{Config.WAREHOUSE_STAFF_ROLE_ID}>"
            sent_message = await channel.send(
                content=f"{staff_role} • {interaction.user.mention}",
                embed=embed,
                view=view
            )
            
            # Сохраняем в БД
            from database import save_warehouse_request
            import asyncio
            
            request_data = {
                'user_id': interaction.user.id,
                'items': items,
                'message_id': sent_message.id,
                'created_at': datetime.now().isoformat()
            }
            await asyncio.to_thread(save_warehouse_request, sent_message.id, request_data)
            
            view.message_id = sent_message.id
            await sent_message.edit(view=view)
            
            await interaction.response.edit_message(
                content="✅ Запрос отправлен!",
                embed=None,
                view=None
            )
            
            WarehouseSession.clear_session(interaction.user.id)
        else:
            await interaction.response.send_message("❌ Канал не найден", ephemeral=True)
    
    @discord.ui.button(
        label="ОТМЕНИТЬ",
        style=discord.ButtonStyle.danger,
        emoji="❌",
        row=1
    )
    async def cancel_button(self, interaction: discord.Interaction, button: Button):
        """Отменить запрос"""
        WarehouseSession.clear_session(interaction.user.id)
        await interaction.response.edit_message(
            content="❌ Запрос отменен.",
            embed=None,
            view=None
        )