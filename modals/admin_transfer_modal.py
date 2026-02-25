"""
Модал административного перевода сотрудника в ППС (без заявки).
"""
from __future__ import annotations

import logging

import discord
from discord.ui import Modal, TextInput

from config import Config
from state import bot
from services.department_roles import get_dept_and_rank_roles, get_approval_label_target
from utils.rate_limiter import apply_role_changes
from views.message_texts import ErrorMessages

logger = logging.getLogger(__name__)


class AdminTransferModal(Modal):
    def __init__(self, from_dept: str):
        # from_dept: grom | osb | orls
        titles = {"grom": "ГРОМ", "osb": "ОСБ", "orls": "ОРЛС"}
        label = titles.get((from_dept or "").strip().lower(), from_dept)
        super().__init__(title=f"Перевод сотрудника из {label} в ППС"[:45])
        self.from_dept = (from_dept or "").strip().lower()
        self.user_id_input = TextInput(
            label="ID сотрудника",
            placeholder="Числовой Discord ID",
            max_length=20,
            required=True,
        )
        self.reason_input = TextInput(
            label="Причина перевода",
            placeholder="Необязательно",
            max_length=Config.MAX_REASON_LENGTH,
            style=discord.TextStyle.paragraph,
            required=False,
        )
        self.add_item(self.user_id_input)
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("❌ Только на сервере.", ephemeral=True)
                return

            raw_id = (self.user_id_input.value or "").strip()
            try:
                target_id = int(raw_id)
            except ValueError:
                await interaction.followup.send("❌ Укажите числовой ID сотрудника.", ephemeral=True)
                return

            if target_id == interaction.user.id:
                await interaction.followup.send("❌ Нельзя перевести самого себя.", ephemeral=True)
                return

            member = guild.get_member(target_id) or await guild.fetch_member(target_id)
            if not member:
                await interaction.followup.send("❌ Пользователь с таким ID не найден на сервере.", ephemeral=True)
                return

            remove_dept, remove_rank = get_dept_and_rank_roles(guild, self.from_dept)
            to_remove = [r for r in remove_dept + remove_rank if r]
            has_dept_role = any(r in member.roles for r in to_remove)
            if not has_dept_role:
                label = get_approval_label_target(self.from_dept)
                await interaction.followup.send(f"❌ Указанный сотрудник не состоит в {label}.", ephemeral=True)
                return

            add_dept, add_rank = get_dept_and_rank_roles(guild, "pps")
            to_add = [r for r in add_dept + add_rank if r]
            if any(r in member.roles for r in to_add):
                await interaction.followup.send("❌ Сотрудник уже находится в ППС.", ephemeral=True)
                return

            await apply_role_changes(member, remove=to_remove, add=to_add)

            reason = (self.reason_input.value or "").strip() or "Не указана"
            log_channel_id = getattr(Config, "CHANNEL_CADRE_LOG", 0)
            if log_channel_id:
                log_channel = guild.get_channel(log_channel_id)
                if log_channel:
                    from_dept_label = get_approval_label_target(self.from_dept)
                    embed = discord.Embed(
                        title="📋 Административный перевод в ППС",
                        color=discord.Color.blue(),
                    )
                    embed.add_field(name="Инициатор", value=interaction.user.mention, inline=True)
                    embed.add_field(name="Сотрудник", value=f"{member.mention} (ID: {member.id})", inline=True)
                    embed.add_field(name="Старый отдел", value=from_dept_label, inline=True)
                    embed.add_field(name="Новый отдел", value="ППС", inline=True)
                    embed.add_field(name="Причина", value=reason[:1024], inline=False)
                    try:
                        await log_channel.send(embed=embed)
                    except (discord.Forbidden, discord.HTTPException) as e:
                        logger.warning("Не удалось отправить лог перевода в канал %s: %s", log_channel_id, e)

            await interaction.followup.send("✅ Перевод выполнен. Роли обновлены.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ Недостаточно прав для изменения ролей.", ephemeral=True)
        except Exception as e:
            logger.error("Ошибка админ-перевода: %s", e, exc_info=True)
            await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)
