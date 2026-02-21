import discord
from discord.ui import View, Button
import logging
import asyncio
import re

from config import Config
from views.message_texts import ErrorMessages
from state import active_firing_requests
from utils.rate_limiter import apply_role_changes, safe_discord_call
from utils.embed_utils import copy_embed, add_officer_field
from services.audit import send_to_audit
from services.action_locks import action_lock
from database import delete_request
from constants import StatusValues, FieldNames, WebhookPatterns

logger = logging.getLogger(__name__)


class FiringView(View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        staff_role = interaction.guild.get_role(Config.FIRING_STAFF_ROLE_ID)
        if staff_role not in interaction.user.roles:
            await interaction.response.send_message(ErrorMessages.NO_PERMISSION, ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ подтвердить увольнение", style=discord.ButtonStyle.danger, custom_id="fire_accept")
    async def accept_firing_button(self, interaction: discord.Interaction, button: Button):
        await self.handle_fire(interaction)

    @discord.ui.button(label="❌ отклонить рапорт", style=discord.ButtonStyle.secondary, custom_id="fire_reject")
    async def reject_firing_button(self, interaction: discord.Interaction, button: Button):
        from modals.firing_reject_reason import FiringRejectReasonModal
        modal = FiringRejectReasonModal(user_id=self.user_id, message_id=interaction.message.id)
        await interaction.response.send_modal(modal)

    def _rebuild_request_data_from_embed(self, message: discord.Message):
        if not message.embeds:
            return None

        embed = message.embeds[0]
        desc = embed.description or ""

        full_name = "Сотрудник"
        reason = "псж"

        m_name = re.search(WebhookPatterns.FIRING["full_name"], desc, re.IGNORECASE)
        if not m_name:
            m_name = re.search(WebhookPatterns.FIRING["full_name_alt"], desc, re.IGNORECASE)
        if m_name:
            full_name = m_name.group(1).strip()

        m_reason = re.search(WebhookPatterns.FIRING["reason"], desc, re.IGNORECASE)
        if m_reason:
            reason = m_reason.group(1).strip()

        return {
            "discord_id": self.user_id,
            "full_name": full_name,
            "reason": reason,
            "message_link": message.jump_url,
        }

    async def handle_fire(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            async with action_lock(interaction.message.id, "подтверждение увольнения"):
                request_data = active_firing_requests.get(interaction.message.id)

                if not request_data:
                    request_data = self._rebuild_request_data_from_embed(interaction.message)
                    if request_data:
                        active_firing_requests[interaction.message.id] = request_data
                        logger.warning(
                            "Увольнение: заявка %s восстановлена из embed (state/БД пусто)",
                            interaction.message.id
                        )

                if not request_data:
                    await interaction.followup.send(ErrorMessages.NOT_FOUND.format(item="заявка"), ephemeral=True)
                    return

                member = interaction.guild.get_member(int(request_data["discord_id"]))
                if not member:
                    await interaction.followup.send(ErrorMessages.NOT_FOUND.format(item="пользователь"), ephemeral=True)
                    return

                full_name = request_data.get("full_name", "Сотрудник")

                roles_to_keep_ids = set(Config.ROLES_TO_KEEP_ON_FIRE)
                roles_to_remove = []
                for role in member.roles:
                    if role.is_default() or role.is_integration() or role.is_bot_managed():
                        continue
                    if role.id not in roles_to_keep_ids:
                        roles_to_remove.append(role)

                if roles_to_remove:
                    await apply_role_changes(member, remove=roles_to_remove)

                fired_role = interaction.guild.get_role(Config.FIRED_ROLE_ID)
                if fired_role:
                    await apply_role_changes(member, add=[fired_role])

                try:
                    parts = full_name.split()
                    if len(parts) >= 2:
                        new_nick = f"{Config.FIRING_NICKNAME_PREFIX} {parts[0]} {parts[1]}"
                    else:
                        new_nick = f"{Config.FIRING_NICKNAME_PREFIX} {full_name}"
                    await safe_discord_call(member.edit, nick=new_nick)
                except Exception as e:
                    logger.error("Ошибка при смене ника: %s", e)
                    new_nick = f"{Config.FIRING_NICKNAME_PREFIX} {full_name}"

                await send_to_audit(
                    interaction,
                    member,
                    Config.ACTION_FIRED,
                    Config.RANK_FIRED,
                    request_data.get("message_link") or interaction.message.jump_url
                )

                try:
                    embed = discord.Embed(
                        title="✅ рапорт об увольнении удовлетворен",
                        color=discord.Color.red(),
                        description=f"**{interaction.guild.name}**\n\nВаш рапорт об увольнении был одобрен.",
                        timestamp=interaction.created_at
                    )
                    embed.add_field(name="ваш новый ник", value=f"`{new_nick}`", inline=False)
                    embed.add_field(name="уволил", value=interaction.user.mention, inline=True)
                    embed.add_field(name="причина", value=request_data.get("reason", "псж"), inline=False)
                    await member.send(embed=embed)
                except discord.Forbidden:
                    await interaction.followup.send(
                        f"⚠️ Не удалось отправить уведомление пользователю {member.mention}",
                        ephemeral=True
                    )

                message = interaction.message
                old_embed = message.embeds[0]
                new_embed = copy_embed(old_embed)
                new_embed = add_officer_field(new_embed, interaction.user.mention)
                new_embed.color = discord.Color.red()

                found = False
                for i, field in enumerate(new_embed.fields):
                    if field.name == FieldNames.STATUS:
                        new_embed.set_field_at(i, name=FieldNames.STATUS, value=StatusValues.FIRED, inline=True)
                        found = True
                        break
                if not found:
                    new_embed.add_field(name=FieldNames.STATUS, value=StatusValues.FIRED, inline=True)

                await message.edit(embed=new_embed, view=None)

                active_firing_requests.pop(interaction.message.id, None)
                await asyncio.to_thread(delete_request, "firing_requests", interaction.message.id)

                await interaction.followup.send(f"✅ Пользователь {member.mention} уволен.", ephemeral=True)
                logger.info("Пользователь %s уволен сотрудником %s", member.id, interaction.user.id)

        except RuntimeError as e:
            if str(e) == "ACTION_ALREADY_IN_PROGRESS":
                await interaction.followup.send("⚠️ Это действие уже выполняется другим нажатием.", ephemeral=True)
                return
            logger.error("Ошибка блокировки действия (увольнение): %s", e, exc_info=True)
            await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)

        except Exception as e:
            logger.error("Ошибка при увольнении: %s", e, exc_info=True)
            await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)