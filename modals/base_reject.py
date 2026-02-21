"""
=====================================================
БАЗОВЫЙ КЛАСС ДЛЯ ВСЕХ REJECT МОДАЛОК
=====================================================
"""

import discord
from discord.ui import Modal, TextInput
import logging
import asyncio
from config import Config
from views.message_texts import ErrorMessages, MessageConfig
from utils.validators import Validators
from utils.embed_utils import copy_embed, add_officer_field, add_reject_reason
from database import delete_request

logger = logging.getLogger(__name__)

class BaseRejectModal(Modal):
    """
    Базовый класс для всех модалок отклонения.
    
    Наследники должны определить:
    - title (через __init_subclass__ или переопределить)
    - get_staff_role_id() - какая роль может отклонять
    - get_request_data() - получить данные заявки
    - get_view_class() - класс View для отключения кнопок
    - get_state_dict() - словарь состояния (active_requests и т.д.)
    - get_table_name() - название таблицы в БД
    - get_notification_title() - заголовок для уведомления
    - get_item_name() - название типа заявки для сообщений
    """
    
    def __init__(self, user_id: int, message_id: int, **kwargs):
        # Устанавливаем title из класса
        super().__init__(title=self.get_modal_title())
        self.user_id = user_id
        self.message_id = message_id
        self.additional_data = kwargs
        
        self.reason = TextInput(
            label='причина отказа',
            placeholder='укажите причину отклонения',
            max_length=Config.MAX_REASON_LENGTH,
            style=discord.TextStyle.paragraph,
            required=True
        )
        self.add_item(self.reason)
    
    @classmethod
    def get_modal_title(cls):
        """Название модалки - можно переопределить"""
        return "отклонение"
    
    async def get_staff_role_id(self, interaction: discord.Interaction) -> int:
        """Какая роль может отклонять - ОБЯЗАТЕЛЬНО переопределить"""
        raise NotImplementedError
    
    async def get_request_data(self, message_id: int):
        """Получить данные заявки - ОБЯЗАТЕЛЬНО переопределить"""
        raise NotImplementedError
    
    def get_view_class(self):
        """Класс View для отключения кнопок - ОБЯЗАТЕЛЬНО переопределить"""
        raise NotImplementedError
    
    def get_state_dict(self):
        """Словарь состояния (active_requests и т.д.) - ОБЯЗАТЕЛЬНО переопределить"""
        raise NotImplementedError
    
    def get_table_name(self) -> str:
        """Название таблицы в БД - ОБЯЗАТЕЛЬНО переопределить"""
        raise NotImplementedError
    
    def get_notification_title(self) -> str:
        """Заголовок для уведомления - ОБЯЗАТЕЛЬНО переопределить"""
        return "❌ заявка отклонена"
    
    def get_item_name(self) -> str:
        """Название типа заявки для сообщений - ОБЯЗАТЕЛЬНО переопределить"""
        return "заявка"
    
    async def get_view_instance(self, interaction: discord.Interaction, request_data: dict):
        """Создать экземпляр View с отключенными кнопками"""
        view_class = self.get_view_class()
        
        # Создаем экземпляр view с нужными параметрами
        if self.get_table_name() == 'requests':
            from views.request_view import RequestView
            from enums import RequestType
            
            request_type = RequestType(request_data.get('request_type', 'cadet'))
            view = RequestView(
                user_id=self.user_id,
                validated_data=request_data,
                request_type=request_type,
                **{k: v for k, v in request_data.items() 
                   if k not in ['user_id', 'message_id', 'message_link', 'embed', 'request_type', 'created_at', 'name', 'surname', 'static_id']}
            )
        elif self.get_table_name() == 'firing_requests':
            from views.firing_view import FiringView
            view = FiringView(user_id=self.user_id)
        elif self.get_table_name() == 'promotion_requests':
            from views.promotion_view import PromotionView
            view = PromotionView(
                user_id=self.user_id,
                new_rank=self.additional_data.get('new_rank', ''),
                full_name=self.additional_data.get('full_name', ''),
                message_id=self.message_id
            )
        else:
            view = view_class()
        
        # Отключаем все кнопки
        for item in view.children:
            item.disabled = True
        
        return view
    
    async def on_submit(self, interaction: discord.Interaction):
        """Общая логика для всех отклонений"""
        try:
            # 1. Проверка прав
            staff_role_id = await self.get_staff_role_id(interaction)
            staff_role = interaction.guild.get_role(staff_role_id)
            if staff_role not in interaction.user.roles:
                await interaction.response.send_message(ErrorMessages.NO_PERMISSION, ephemeral=True)
                return
            
            # 2. Валидация причины
            valid, reason = Validators.validate_reason(self.reason.value)
            if not valid:
                await interaction.response.send_message(f"❌ {reason}", ephemeral=True)
                return
            
            # 3. Проверка существования заявки
            request_data = await self.get_request_data(self.message_id)
            if not request_data:
                await interaction.response.send_message(
                    ErrorMessages.NOT_FOUND.format(item=self.get_item_name()), 
                    ephemeral=True
                )
                return
            
            # 4. Получаем сообщение и обновляем embed
            message = await interaction.channel.fetch_message(self.message_id)
            
            new_embed = copy_embed(message.embeds[0])
            new_embed = add_officer_field(new_embed, interaction.user.mention)
            new_embed = add_reject_reason(new_embed, reason)
            new_embed.color = discord.Color.light_gray()
            
            # 5. Получаем view с отключенными кнопками
            view = await self.get_view_instance(interaction, request_data)
            await message.edit(embed=new_embed, view=view)
            
            # 6. Уведомление пользователю
            member = interaction.guild.get_member(self.user_id)
            if member:
                try:
                    embed = discord.Embed(
                        title=self.get_notification_title(),
                        color=discord.Color.light_gray(),
                        description=f"**{interaction.guild.name}**\n\nваша {self.get_item_name()} была отклонена.",
                        timestamp=interaction.created_at
                    )
                    embed.add_field(name="причина", value=reason, inline=False)
                    embed.add_field(name="отклонил", value=interaction.user.mention, inline=True)
                    
                    # Добавляем дополнительные поля если есть
                    if self.get_table_name() == 'promotion_requests':
                        embed.add_field(name="звание", value=self.additional_data.get('new_rank', ''), inline=True)
                    
                    await member.send(embed=embed)
                except discord.Forbidden:
                    await interaction.followup.send(
                        f"⚠️ не удалось отправить уведомление пользователю {member.mention}", 
                        ephemeral=True
                    )
            
            # 7. Удаление из state и БД
            state_dict = self.get_state_dict()
            if self.message_id in state_dict:
                del state_dict[self.message_id]
                await asyncio.to_thread(delete_request, self.get_table_name(), self.message_id)
            
            # 8. Ответ
            await interaction.response.send_message(
                f"✅ {self.get_item_name()} отклонена. причина: {reason}", 
                ephemeral=True
            )
            logger.info(f"{self.get_item_name()} {self.message_id} отклонена сотрудником {interaction.user.id}")
            
        except Exception as e:
            logger.error(f"Ошибка при отклонении {self.get_item_name()}: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(ErrorMessages.GENERIC, ephemeral=True)