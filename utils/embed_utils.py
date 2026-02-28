import discord
import logging
from constants import FieldNames
from config import Config

def _max_embed_fields():
    return getattr(Config, "MAX_EMBED_FIELDS", 25)

def update_embed_status(embed, new_status: str, color=None):
    if color is not None:
        embed.color = int(color) if isinstance(color, int) else color
    max_fields = _max_embed_fields()
    for i, field in enumerate(embed.fields):
        if (field.name or "").strip().lower() == FieldNames.STATUS.lower():
            embed.set_field_at(i, name=FieldNames.STATUS, value=new_status, inline=True)
            return embed
    

    if len(embed.fields) >= max_fields:

        for i, field in enumerate(embed.fields):
            if (field.name or "").strip().lower() not in [FieldNames.NAME.lower(), FieldNames.SURNAME.lower(), FieldNames.STATIC_ID.lower()]:
                embed.set_field_at(i, name=FieldNames.STATUS, value=new_status, inline=True)
                return embed

        logger = logging.getLogger(__name__)
        logger.error(f"Не удалось добавить статус: достигнут лимит полей ({max_fields})")
        return embed
    
    embed.add_field(name=FieldNames.STATUS, value=new_status, inline=True)
    return embed

def add_officer_field(embed, officer_mention: str):
    max_fields = _max_embed_fields()
    if len(embed.fields) >= max_fields:
        for i, field in enumerate(embed.fields):
            if (field.name or "").strip().lower() == FieldNames.OFFICER.lower():
                embed.set_field_at(i, name=FieldNames.OFFICER, value=officer_mention, inline=True)
                return embed
        logger = logging.getLogger(__name__)
        logger.warning(f"Не удалось добавить офицера: достигнут лимит полей ({max_fields})")
        return embed
    
    embed.add_field(name=FieldNames.OFFICER, value=officer_mention, inline=True)
    return embed

def add_reject_reason(embed, reason: str):
    max_fields = _max_embed_fields()
    if len(embed.fields) >= max_fields:
        for i, field in enumerate(embed.fields):
            if (field.name or "").strip().lower() == FieldNames.REJECT_REASON.lower():
                embed.set_field_at(i, name=FieldNames.REJECT_REASON, value=reason, inline=False)
                return embed
        logger = logging.getLogger(__name__)
        logger.warning(f"Не удалось добавить причину отказа: достигнут лимит полей ({max_fields})")
        return embed
    
    embed.add_field(name=FieldNames.REJECT_REASON, value=reason, inline=False)
    return embed

def copy_embed(embed) -> discord.Embed:
    return discord.Embed.from_dict(embed.to_dict())

def safe_add_field(embed, name: str, value: str, inline: bool = False) -> bool:
    max_fields = _max_embed_fields()
    if len(embed.fields) >= max_fields:
        logger = logging.getLogger(__name__)
        logger.warning(f"Попытка добавить поле '{name}' при достигнутом лимите ({max_fields})")
        return False
    
    embed.add_field(name=name, value=value, inline=inline)
    return True

def get_fields_count(embed) -> int:
    return len(embed.fields)

def has_space_for_fields(embed, needed: int = 1) -> bool:
    return len(embed.fields) + needed <= _max_embed_fields()