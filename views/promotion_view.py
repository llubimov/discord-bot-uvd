import discord
from discord.ui import View, Button
import logging
import asyncio
import re

from config import Config
from views.message_texts import ErrorMessages
from state import active_promotion_requests
from utils.rate_limiter import apply_role_changes, safe_discord_call
from utils.embed_utils import copy_embed, add_officer_field, update_embed_status
from services.audit import send_to_audit
from services.action_locks import action_lock
from services.ranks import (
    find_role_id_for_transition,
    parse_transition_to_new_rank,
    get_all_rank_role_ids_from_mapping,
)
from database import delete_request
from constants import StatusValues

logger = logging.getLogger(__name__)

_ARROW_RE = re.compile(r"\s*(?:->|→|➡|⇒|=+>)\s*")


def _norm_text(s: str) -> str:
    return " ".join((s or "").strip().lower().replace("ё", "е").split())


def _collect_rank_names_from_mapping():
    rank_names = set()

    raw = getattr(Config, "RANK_ROLE_MAPPING", {}) or {}
    for key in raw.keys():
        parts = _ARROW_RE.split(str(key))
        if len(parts) != 2:
            continue
        left = _norm_text(parts[0])
        right = _norm_text(parts[1])
        if left:
            rank_names.add(left)
        if right:
            rank_names.add(right)

    rank_names.update({
        "рядовой",
        "младший сержант",
        "сержант",
        "старший сержант",
        "старшина",
        "прапорщик",
        "старший прапорщик",
        "младший лейтенант",
        "лейтенант",
        "старший лейтенант",
        "капитан",
        "майор",
        "подполковник",
        "полковник",
    })
    return rank_names


def _is_rank_role_by_name(role_name: str, known_rank_names: set[str]) -> bool:
    rn = _norm_text(role_name)
    if not rn:
        return False

    for rank_name in known_rank_names:
        if rn == rank_name:
            return True
        if rn == f"{rank_name} полиции":
            return True
        if rank_name in rn:
            return True
    return False


class PromotionView(View):
    def __init__(self, user_id: int, new_rank: str, full_name: str, message_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.new_rank = new_rank
        self.full_name = full_name
        self.message_id = message_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        required_role_id = Config.PROMOTION_CHANNELS.get(interaction.channel.id)
        if not required_role_id:
            await interaction.response.send_message("❌ Этот канал не настроен для повышений.", ephemeral=True)
            return False

        staff_role = interaction.guild.get_role(required_role_id)
        if staff_role not in interaction.user.roles:
            await interaction.response.send_message(ErrorMessages.NO_PERMISSION, ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ принять", style=discord.ButtonStyle.success, custom_id="promotion_accept")
    async def accept_button(self, interaction: discord.Interaction, button: Button):
        await self.handle_accept(interaction)

    @discord.ui.button(label="❌ отклонить", style=discord.ButtonStyle.danger, custom_id="promotion_reject")
    async def reject_button(self, interaction: discord.Interaction, button: Button):
        from modals.promotion_reject_reason import PromotionRejectReasonModal
        modal = PromotionRejectReasonModal(
            user_id=self.user_id,
            message_id=self.message_id,
            new_rank=self.new_rank,
            full_name=self.full_name
        )
        await interaction.response.send_modal(modal)

    async def handle_accept(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            async with action_lock(self.message_id, "принятие повышения"):
                member = interaction.guild.get_member(self.user_id)
                if not member:
                    await interaction.followup.send(ErrorMessages.NOT_FOUND.format(item="пользователь"), ephemeral=True)
                    return

                new_role_id = find_role_id_for_transition(self.new_rank)
                if not new_role_id:
                    await interaction.followup.send(
                        f"❌ Не настроена роль для повышения: `{self.new_rank}`. Проверь RANK_ROLE_MAPPING.",
                        ephemeral=True
                    )
                    return

                new_role = interaction.guild.get_role(int(new_role_id))
                if not new_role:
                    await interaction.followup.send(
                        f"❌ Роль для повышения не найдена на сервере (role_id={new_role_id}).",
                        ephemeral=True
                    )
                    return

                rank_role_ids = set(getattr(Config, "ALL_RANK_ROLE_IDS", []) or [])
                rank_role_ids |= set(get_all_rank_role_ids_from_mapping())
                rank_names = _collect_rank_names_from_mapping()

                roles_to_remove = []
                for role in member.roles:
                    if role.is_default() or role.is_integration() or role.is_bot_managed():
                        continue
                    if role.id in Config.ROLES_TO_KEEP_ON_PROMOTION:
                        continue
                    if role.id == new_role.id:
                        continue

                    if role.id in rank_role_ids or _is_rank_role_by_name(role.name, rank_names):
                        roles_to_remove.append(role)

                logger.info(
                    "Повышение: user=%s target_role=%s remove_roles=%s remove_role_names=%s",
                    member.id,
                    new_role.id,
                    [r.id for r in roles_to_remove],
                    [r.name for r in roles_to_remove]
                )

                if roles_to_remove:
                    await apply_role_changes(member, remove=roles_to_remove)

                await apply_role_changes(member, add=[new_role])

                try:
                    member = await interaction.guild.fetch_member(self.user_id)
                    logger.info("Повышение: роли после изменения у %s: %s", member.id, [r.name for r in member.roles])
                except Exception:
                    pass

                if interaction.channel.id == Config.ACADEMY_CHANNEL_ID:
                    await self._handle_academy_promotion(member, interaction)

                rank_for_audit = parse_transition_to_new_rank(self.new_rank) or self.new_rank

                await send_to_audit(
                    interaction,
                    member,
                    Config.ACTION_PROMOTED,
                    rank_for_audit,
                    f"https://discord.com/channels/{interaction.guild.id}/{interaction.channel.id}/{self.message_id}"
                )

                try:
                    embed = discord.Embed(
                        title="✅ рапорт на повышение одобрен",
                        color=discord.Color.green(),
                        description=f"**{interaction.guild.name}**\n\nВаш рапорт на повышение был одобрен.",
                        timestamp=interaction.created_at
                    )
                    embed.add_field(name="новое звание", value=self.new_rank, inline=True)
                    embed.add_field(name="принял", value=interaction.user.mention, inline=True)

                    if interaction.channel.id == Config.ACADEMY_CHANNEL_ID:
                        is_non_pps = any(rank in self.new_rank.lower() for rank in Config.NON_PPS_RANKS)
                        if not is_non_pps:
                            embed.add_field(
                                name="новый ник",
                                value=f"`{Config.PPS_NICKNAME_PREFIX} {self.full_name}`",
                                inline=False
                            )

                    await member.send(embed=embed)
                except discord.Forbidden:
                    await interaction.followup.send(
                        f"⚠️ Не удалось отправить уведомление пользователю {member.mention}",
                        ephemeral=True
                    )

                message = await interaction.channel.fetch_message(self.message_id)
                new_embed = copy_embed(message.embeds[0])
                new_embed = update_embed_status(new_embed, StatusValues.ACCEPTED, discord.Color.green())
                new_embed = add_officer_field(new_embed, interaction.user.mention)
                await message.edit(embed=new_embed, view=None)

                if self.message_id in active_promotion_requests:
                    del active_promotion_requests[self.message_id]
                    await asyncio.to_thread(delete_request, "promotion_requests", self.message_id)

                await interaction.followup.send(
                    f"✅ Пользователь {member.mention} повышен до {self.new_rank}",
                    ephemeral=True
                )
                logger.info("Рапорт %s принят сотрудником %s", self.message_id, interaction.user.id)

        except RuntimeError as e:
            if str(e) == "ACTION_ALREADY_IN_PROGRESS":
                await interaction.followup.send("⚠️ Это действие уже выполняется другим нажатием.", ephemeral=True)
                return
            logger.error("Ошибка блокировки действия (повышение): %s", e, exc_info=True)
            await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)

        except Exception as e:
            logger.error("Ошибка при принятии рапорта: %s", e, exc_info=True)
            await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)

    async def _handle_academy_promotion(self, member: discord.Member, interaction: discord.Interaction):
        is_non_pps = any(rank in self.new_rank.lower() for rank in Config.NON_PPS_RANKS)
        if not is_non_pps:
            academy_roles = [interaction.guild.get_role(rid) for rid in Config.CADET_ROLES_TO_GIVE if interaction.guild.get_role(rid)]
            if academy_roles:
                await apply_role_changes(member, remove=academy_roles)

            pps_roles = [interaction.guild.get_role(rid) for rid in Config.PPS_ROLE_IDS if interaction.guild.get_role(rid)]
            if pps_roles:
                await apply_role_changes(member, add=pps_roles)

            try:
                new_nick = f"{Config.PPS_NICKNAME_PREFIX} {self.full_name}"
                await safe_discord_call(member.edit, nick=new_nick)
            except Exception as e:
                logger.error("Ошибка при смене ника на ППС: %s", e)