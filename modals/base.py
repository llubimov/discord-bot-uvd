import discord
from discord.ui import Modal, TextInput
import logging
from typing import Dict, Any, Tuple
from datetime import datetime
from config import Config
from views.message_texts import ErrorMessages, SuccessMessages
from utils.validators import Validators
from state import bot, active_requests
from enums import RequestType
import asyncio
from database import save_request

logger = logging.getLogger(__name__)


def _name_surname_defaults(member) -> Tuple[str, str]:
    if not member:
        return "", ""
    from utils.member_display import get_member_name_surname
    return get_member_name_surname(member)


class BaseRequestModal(Modal):
    def __init__(self, title: str, request_type: RequestType, member=None):
        super().__init__(title=title)
        self.request_type = request_type
        name_default, surname_default = _name_surname_defaults(member)
        min_len = getattr(Config, "MIN_NAME_LENGTH", 2)
        # Discord 400: default (value) не должен быть короче min_length — передаём default только если длина >= min_len
        kw_name = {"label": "Имя", "placeholder": "Введите ваше имя", "max_length": Config.MAX_NAME_LENGTH, "min_length": min_len, "required": True}
        if name_default and len(name_default) >= min_len:
            kw_name["default"] = name_default
        kw_surname = {"label": "Фамилия", "placeholder": "Введите вашу фамилию", "max_length": Config.MAX_NAME_LENGTH, "min_length": min_len, "required": True}
        if surname_default and len(surname_default) >= min_len:
            kw_surname["default"] = surname_default
        self.name = TextInput(**kw_name)
        self.surname = TextInput(**kw_surname)
        self.static_id = TextInput(label='Статик ID', placeholder='Введите 6 цифр (пример: 537123)', max_length=10, min_length=Config.STATIC_ID_LENGTH, required=True)
        self.add_item(self.name)
        self.add_item(self.surname)
        self.add_item(self.static_id)

    async def validate_common(self) -> Tuple[bool, Dict[str, Any]]:
        try:
            validated = {}
            for field, validator, key in [
                (self.name, Validators.validate_name, 'name'),
                (self.surname, Validators.validate_name, 'surname')
            ]:
                valid, result = validator(field.value)
                if not valid:
                    return False, {"error": f"ошибка в {key}: {result}"}
                validated[key] = result
            valid, static = Validators.format_static_id(self.static_id.value)
            if not valid:
                return False, {"error": f"ошибка в static id: {static}"}
            validated['static_id'] = static
            return True, validated
        except Exception as e:
            logger.error(f"ошибка валидации: {e}")
            return False, {"error": "произошла ошибка при проверке данных"}

    async def validate_specific(self, common: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        return True, common

    async def validate_all(self) -> Tuple[bool, Dict[str, Any]]:
        success, common = await self.validate_common()
        if not success:
            return success, common
        return await self.validate_specific(common)

    async def create_embed(self, validated_data: Dict[str, Any], interaction: discord.Interaction) -> discord.Embed:
        raise NotImplementedError

    async def get_additional_data(self) -> Dict[str, Any]:
        return {}

    async def has_active_request(self, user_id: int) -> bool:
        return any(req.get('user_id') == user_id for req in active_requests.values())

    async def save_request(self, interaction: discord.Interaction, message: discord.Message,
                          validated_data: Dict[str, Any], additional_data: Dict[str, Any]):
        data = {
            'user_id': interaction.user.id,
            'message_id': message.id,
            'message_link': message.jump_url,
            'embed': message.embeds[0].to_dict(),
            'request_type': self.request_type.value,
            'created_at': datetime.now().isoformat(),
            **validated_data,
            **additional_data
        }
        active_requests[message.id] = data
        await save_request('requests', message.id, data)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            if await self.has_active_request(interaction.user.id):
                await interaction.response.send_message("❌ У вас уже есть активная заявка!", ephemeral=True)
                return
            success, result = await self.validate_all()
            if not success:
                await interaction.response.send_message(f"❌ {result['error']}", ephemeral=True)
                return
            embed = await self.create_embed(result, interaction)
            additional_data = await self.get_additional_data()
            
            # Импортируем ВНУТРИ метода, чтобы избежать циклического импорта
            from views.request_view import RequestView
            
            view = RequestView(
                user_id=interaction.user.id,
                validated_data=result,
                request_type=self.request_type,
                **additional_data
            )
            channel = bot.get_channel(Config.REQUEST_CHANNEL_ID)
            if not channel:
                logger.error(f"канал заявок {Config.REQUEST_CHANNEL_ID} не найден")
                await interaction.response.send_message("❌ Ошибка конфигурации: канал заявок не найден", ephemeral=True)
                return
            from utils.rate_limiter import safe_send
            message = await safe_send(channel, embed=embed, view=view)
            await self.save_request(interaction, message, result, additional_data)
            await interaction.response.send_message(SuccessMessages.REQUEST_SENT, ephemeral=True)
            logger.info(f"создана новая заявка {self.request_type.value} от {interaction.user.id}")
        except Exception as e:
            logger.error(f"ошибка при отправке заявки: {e}", exc_info=True)
            await interaction.response.send_message(ErrorMessages.GENERIC, ephemeral=True)