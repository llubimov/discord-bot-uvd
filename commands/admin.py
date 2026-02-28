# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timedelta

import discord
from discord import app_commands

import state
from config import Config
from database import delete_request
from services.diag_report import build_diag_embed
from services.health_report import cleanup_orphan_records
from utils.slash_helpers import NO_ROLE_ABOVE_BOT, slash_require_role_above_bot

logger = logging.getLogger(__name__)


def register_admin_commands(bot: discord.ext.commands.Bot) -> None:

    @bot.tree.command(name="ping", description="Задержка бота")
    async def ping_slash(interaction: discord.Interaction):
        if not slash_require_role_above_bot(interaction):
            await interaction.response.send_message(NO_ROLE_ABOVE_BOT, ephemeral=True)
            return
        latency = round(bot.latency * 1000)
        await interaction.response.send_message(f"🏓 Понг! Задержка: {latency}мс")

    @bot.tree.command(name="diag", description="-")
    async def diag_slash(interaction: discord.Interaction):
        if not slash_require_role_above_bot(interaction):
            await interaction.response.send_message(NO_ROLE_ABOVE_BOT, ephemeral=True)
            return
        try:
            await interaction.response.defer(ephemeral=True)
            embed = await build_diag_embed(bot)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error("Ошибка /diag: %s", e, exc_info=True)
            await interaction.followup.send("❌ Ошибка при сборке диагностики.", ephemeral=True)

    @bot.tree.command(name="diag_clean_orphans", description="-")
    async def diag_clean_orphans_slash(interaction: discord.Interaction):
        if not slash_require_role_above_bot(interaction):
            await interaction.response.send_message(NO_ROLE_ABOVE_BOT, ephemeral=True)
            return
        try:
            await interaction.response.defer(ephemeral=True)
            await cleanup_orphan_records(bot, dry_run=False)
            await interaction.followup.send("✅ Очистка лишних записей завершена.", ephemeral=True)
        except Exception as e:
            logger.error("Ошибка /diag_clean_orphans: %s", e, exc_info=True)
            await interaction.followup.send("❌ Ошибка при очистке.", ephemeral=True)

    @bot.tree.command(name="clear_firing", description="-")
    async def clear_firing_slash(interaction: discord.Interaction, days: int = 7):
        if not slash_require_role_above_bot(interaction):
            await interaction.response.send_message(NO_ROLE_ABOVE_BOT, ephemeral=True)
            return
        try:
            await interaction.response.defer(ephemeral=True)
            cutoff_date = datetime.now() - timedelta(days=days)
            to_delete = []
            for msg_id, request in (getattr(state, "active_firing_requests", {}) or {}).items():
                created_at = request.get("created_at")
                if not created_at:
                    to_delete.append(msg_id)
                    continue
                try:
                    if datetime.fromisoformat(created_at) < cutoff_date:
                        to_delete.append(msg_id)
                except Exception:
                    to_delete.append(msg_id)
            deleted_count = 0
            for msg_id in to_delete:
                state.active_firing_requests.pop(msg_id, None)
                await delete_request("firing_requests", int(msg_id))
                deleted_count += 1
            await interaction.followup.send(
                f"✅ Удалено {deleted_count} старых заявок на увольнение (память + БД)",
                ephemeral=True,
            )
            logger.info("Очистка заявок на увольнение /clear_firing: %s", deleted_count)
        except Exception as e:
            logger.error("Ошибка /clear_firing: %s", e, exc_info=True)
            await interaction.followup.send("❌ Ошибка при очистке.", ephemeral=True)
