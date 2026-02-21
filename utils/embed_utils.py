import discord
import logging
from constants import FieldNames

# Константа лимита Discord
MAX_EMBED_FIELDS = 25

def update_embed_status(embed, new_status: str, color: discord.Color = None):
    """Обновляет статус в embed"""
    if color:
        embed.color = color
    for i, field in enumerate(embed.fields):
        if field.name == FieldNames.STATUS:
            embed.set_field_at(i, name=FieldNames.STATUS, value=new_status, inline=True)
            return embed
    
    # Проверяем лимит перед добавлением нового поля
    if len(embed.fields) >= MAX_EMBED_FIELDS:
        # Если лимит достигнут, ищем поле для замены
        for i, field in enumerate(embed.fields):
            if field.name not in [FieldNames.NAME, FieldNames.SURNAME, FieldNames.STATIC_ID]:
                embed.set_field_at(i, name=FieldNames.STATUS, value=new_status, inline=True)
                return embed
        # Если ничего не нашли - логируем ошибку
        logger = logging.getLogger(__name__)
        logger.error(f"Не удалось добавить статус: достигнут лимит полей ({MAX_EMBED_FIELDS})")
        return embed
    
    embed.add_field(name=FieldNames.STATUS, value=new_status, inline=True)
    return embed

def add_officer_field(embed, officer_mention: str):
    """Добавляет информацию о сотруднике"""
    # Проверяем лимит
    if len(embed.fields) >= MAX_EMBED_FIELDS:
        # Ищем поле для замены (например, заменяем предыдущего офицера)
        for i, field in enumerate(embed.fields):
            if field.name == FieldNames.OFFICER:
                embed.set_field_at(i, name=FieldNames.OFFICER, value=officer_mention, inline=True)
                return embed
        # Если нет поля офицера, но лимит достигнут - ничего не делаем
        logger = logging.getLogger(__name__)
        logger.warning(f"Не удалось добавить офицера: достигнут лимит полей ({MAX_EMBED_FIELDS})")
        return embed
    
    embed.add_field(name=FieldNames.OFFICER, value=officer_mention, inline=True)
    return embed

def add_reject_reason(embed, reason: str):
    """Добавляет причину отказа"""
    # Проверяем лимит
    if len(embed.fields) >= MAX_EMBED_FIELDS:
        # Ищем поле для замены (например, заменяем старую причину)
        for i, field in enumerate(embed.fields):
            if field.name == FieldNames.REJECT_REASON:
                embed.set_field_at(i, name=FieldNames.REJECT_REASON, value=reason, inline=False)
                return embed
        # Если нет поля причины, но лимит достигнут - ничего не делаем
        logger = logging.getLogger(__name__)
        logger.warning(f"Не удалось добавить причину отказа: достигнут лимит полей ({MAX_EMBED_FIELDS})")
        return embed
    
    embed.add_field(name=FieldNames.REJECT_REASON, value=reason, inline=False)
    return embed

def copy_embed(embed) -> discord.Embed:
    """Создает копию embed"""
    return discord.Embed.from_dict(embed.to_dict())

def safe_add_field(embed, name: str, value: str, inline: bool = False) -> bool:
    """
    Безопасно добавляет поле с проверкой лимита
    Возвращает True если поле добавлено, False если лимит достигнут
    """
    if len(embed.fields) >= MAX_EMBED_FIELDS:
        logger = logging.getLogger(__name__)
        logger.warning(f"Попытка добавить поле '{name}' при достигнутом лимите ({MAX_EMBED_FIELDS})")
        return False
    
    embed.add_field(name=name, value=value, inline=inline)
    return True

def get_fields_count(embed) -> int:
    """Возвращает количество полей"""
    return len(embed.fields)

def has_space_for_fields(embed, needed: int = 1) -> bool:
    """Проверяет, есть ли место для нужного количества полей"""
    return len(embed.fields) + needed <= MAX_EMBED_FIELDS