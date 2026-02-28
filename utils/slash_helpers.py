# -*- coding: utf-8 -*-
"""Хелперы для слэш-команд (проверка роли и т.д.)."""
import discord

NO_ROLE_ABOVE_BOT = "❌ Команда доступна только участникам с ролью выше роли бота."


def slash_require_role_above_bot(interaction: discord.Interaction) -> bool:
    """Возвращает True, если у пользователя роль выше роли бота."""
    if not interaction.guild or not interaction.user:
        return False
    if not isinstance(interaction.user, discord.Member):
        return False
    me = interaction.guild.me
    if not me:
        return False
    return interaction.user.top_role.position > me.top_role.position
