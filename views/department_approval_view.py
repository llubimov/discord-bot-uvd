from __future__ import annotations

import asyncio
import logging

import discord
from discord.ui import View, Button

from config import Config
from database import (
    update_department_transfer_approval,
    delete_department_transfer_request,
)
from state import active_department_transfers
from views.message_texts import ErrorMessages
from utils.rate_limiter import apply_role_changes, safe_discord_call
from services.department_roles import (
    get_chief_deputy_role_ids,
    get_dept_and_rank_roles,
    get_all_dept_and_rank_roles,
    get_base_rank_role,
    get_approval_label_source,
    get_approval_label_target,
)
from services.department_nickname import get_transfer_nickname
from services.action_locks import action_lock

logger = logging.getLogger(__name__)


def _has_any_role(member: discord.Member, role_ids: list[int]) -> bool:
    if not member or not role_ids:
        return False
    guild = member.guild
    for rid in role_ids:
        r = guild.get_role(rid)
        if r and r in member.roles:
            return True
    return False


class DepartmentApprovalView(View):
    timeout = None

    def __init__(
        self,
        message_id: int,
        user_id: int,
        target_dept: str,
        source_dept: str,
        from_academy: bool,
        form_data: dict,
        approved_source: int = 0,
        approved_target: int = 0,
        channel_id: int = 0,
    ):
        super().__init__(timeout=None)
        self.message_id = int(message_id)
        self.user_id = int(user_id)
        self.target_dept = (target_dept or "").strip().lower()
        self.source_dept = (source_dept or "").strip().lower()
        self.from_academy = bool(from_academy)
        self.form_data = dict(form_data or {})
        self.approved_source = int(approved_source or 0)
        self.approved_target = int(approved_target or 0)
        self.channel_id = int(channel_id or 0)

        label_src = get_approval_label_source(self.source_dept)
        label_tgt = get_approval_label_target(self.target_dept)

        if not self.from_academy:
            if self.approved_source:
                self.add_item(
                    Button(
                        label=f"✅ Одобрено {label_src}",
                        style=discord.ButtonStyle.secondary,
                        custom_id="approve_source",
                        disabled=True,
                    )
                )
                b_reject_src_dis = Button(
                    label=f"Отклонить ({label_src})",
                    style=discord.ButtonStyle.danger,
                    custom_id="reject_source",
                )
                b_reject_src_dis.callback = self._handle_reject
                self.add_item(b_reject_src_dis)
            else:
                b_accept_src = Button(
                    label=f"Принять ({label_src})",
                    style=discord.ButtonStyle.success,
                    custom_id="approve_source",
                )
                b_accept_src.callback = self._handle_approve_source
                self.add_item(b_accept_src)
                b_reject_src = Button(
                    label=f"Отклонить ({label_src})",
                    style=discord.ButtonStyle.danger,
                    custom_id="reject_source",
                )
                b_reject_src.callback = self._handle_reject
                self.add_item(b_reject_src)

        if self.approved_target:
            self.add_item(
                Button(
                    label=f"✅ Одобрено {label_tgt}",
                    style=discord.ButtonStyle.secondary,
                    custom_id="approve_target",
                    disabled=True,
                )
            )
            self.add_item(
                Button(
                    label=f"Отклонить ({label_tgt})",
                    style=discord.ButtonStyle.danger,
                    custom_id="reject_target",
                    disabled=True,
                )
            )
        else:
            b_accept_tgt = Button(
                label=f"Принять ({label_tgt})",
                style=discord.ButtonStyle.success,
                custom_id="approve_target",
            )
            b_accept_tgt.callback = self._handle_approve_target
            self.add_item(b_accept_tgt)
            b_reject_tgt = Button(
                label=f"Отклонить ({label_tgt})",
                style=discord.ButtonStyle.danger,
                custom_id="reject_target",
            )
            b_reject_tgt.callback = self._handle_reject
            self.add_item(b_reject_tgt)

    async def _handle_reject(self, interaction: discord.Interaction):
        from modals.department_reject_modal import DepartmentRejectModal
        modal = DepartmentRejectModal(
            message_id=self.message_id,
            user_id=self.user_id,
            target_dept=self.target_dept,
        )
        await interaction.response.send_modal(modal)

    def _role_ids_for_button(self, custom_id: str) -> list[int]:
        if custom_id == "approve_source" or custom_id == "reject_source":
            return get_chief_deputy_role_ids(self.source_dept)
        if custom_id == "approve_target" or custom_id == "reject_target":
            return get_chief_deputy_role_ids(self.target_dept)
        return []

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            await interaction.response.send_message("❌ Только на сервере.", ephemeral=True)
            return False
        custom_id = (interaction.data or {}).get("custom_id")
        if not custom_id:
            return True
        role_ids = self._role_ids_for_button(custom_id)
        if not role_ids and custom_id not in ("reject_source", "reject_target"):
            await interaction.response.send_message("❌ Не настроены роли для этого действия.", ephemeral=True)
            return False
        if not _has_any_role(interaction.user, role_ids):
            await interaction.response.send_message(ErrorMessages.NO_PERMISSION, ephemeral=True)
            return False
        return True

    async def _handle_approve_source(self, interaction: discord.Interaction):
        if self.approved_source:
            await interaction.response.send_message("⚠️ Уже одобрено.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            async with action_lock(self.message_id, "одобрение заявки перевод"):
                role_ids = get_chief_deputy_role_ids(self.source_dept)
                who = interaction.user
                approved_role = next((rid for rid in role_ids if who.guild.get_role(rid) in who.roles), role_ids[0] if role_ids else 0)
                self.approved_source = approved_role
                update_department_transfer_approval(self.message_id, approved_source=approved_role)
                active_department_transfers[self.message_id] = {
                    "message_id": self.message_id,
                    "user_id": self.user_id,
                    "target_dept": self.target_dept,
                    "source_dept": self.source_dept,
                    "from_academy": self.from_academy,
                    "data": self.form_data,
                    "approved_source": self.approved_source,
                    "approved_target": self.approved_target,
                }
                new_view = DepartmentApprovalView(
                    self.message_id,
                    self.user_id,
                    self.target_dept,
                    self.source_dept,
                    self.from_academy,
                    self.form_data,
                    approved_source=self.approved_source,
                    approved_target=self.approved_target,
                    channel_id=self.channel_id,
                )
                try:
                    msg = await interaction.channel.fetch_message(self.message_id)
                    await msg.edit(view=new_view)
                except Exception as e:
                    logger.warning("Не удалось обновить сообщение заявки %s: %s", self.message_id, e)
                await interaction.followup.send("✅ Одобрение источника зафиксировано.", ephemeral=True)
        except RuntimeError as e:
            if str(e) == "ACTION_ALREADY_IN_PROGRESS":
                await interaction.followup.send("⚠️ Действие уже выполняется.", ephemeral=True)
                return
            raise
        except Exception as e:
            logger.error("Ошибка одобрения источника заявки: %s", e, exc_info=True)
            await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)

    async def _handle_approve_target(self, interaction: discord.Interaction):
        if self.approved_target:
            await interaction.response.send_message("⚠️ Уже одобрено.", ephemeral=True)
            return
        if not self.from_academy and not self.approved_source:
            await interaction.response.send_message(
                "❌ Сначала должен одобрить начальник (или зам) отдела-источника.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        try:
            async with action_lock(self.message_id, "одобрение заявки перевод"):
                guild = interaction.guild
                member = guild.get_member(self.user_id) or await guild.fetch_member(self.user_id)
                if not member:
                    await interaction.followup.send(ErrorMessages.NOT_FOUND.format(item="пользователь"), ephemeral=True)
                    return

                # Снять все роли отделов и их рангов (ГРОМ/ППС/ОРЛС/ОСБ/Академия),
                # затем выдать только роли целевого подразделения
                all_dept_roles, all_rank_roles = get_all_dept_and_rank_roles(guild)
                remove_dept = [r for r in all_dept_roles if r]
                remove_rank = [r for r in all_rank_roles if r]

                # Выдаём роль отдела и только одну базовую должность (стажёр)
                add_dept, _ = get_dept_and_rank_roles(guild, self.target_dept)
                base_rank = get_base_rank_role(guild, self.target_dept)

                to_remove = [r for r in remove_dept + remove_rank if r]
                # При переводе из Академии в подразделение снять роль «прошедший академию»
                if self.from_academy:
                    role_passed_id = getattr(Config, "ROLE_PASSED_ACADEMY", 0) or 0
                    if role_passed_id:
                        role_passed = guild.get_role(int(role_passed_id))
                        if role_passed:
                            to_remove.append(role_passed)
                to_add = [r for r in add_dept if r]
                if base_rank:
                    to_add.append(base_rank)

                if not to_add:
                    await interaction.followup.send(
                        "❌ Не настроены роли целевого отдела. Перевод отменён. Проверьте конфиг (роль отдела и ранги).",
                        ephemeral=True,
                    )
                    return

                await apply_role_changes(member, remove=to_remove, add=to_add)

                verify_failed_msg = None
                try:
                    member = await guild.fetch_member(self.user_id)
                except Exception as e:
                    logger.warning("Не удалось обновить данные участника после смены ролей: %s", e)
                else:
                    # Для проверки «старых ролей» игнорируем роли целевого отдела,
                    # т.к. мы специально их снимаем и тут же выдаём заново.
                    target_roles_set = set(to_add)
                    still_has_old = [r for r in to_remove if r in member.roles and r not in target_roles_set]
                    missing_new = [r for r in to_add if r not in member.roles]
                    if still_has_old or missing_new:
                        msg_parts = []
                        if still_has_old:
                            msg_parts.append(
                                f"остались снятые роли ({len(still_has_old)}): {', '.join(r.name for r in still_has_old)}"
                            )
                        if missing_new:
                            msg_parts.append(
                                f"не выданы роли отдела ({len(missing_new)}): {', '.join(r.name for r in missing_new)}"
                            )
                        logger.warning(
                            "Проверка после перевода не прошла: user_id=%s target=%s to_remove=%s to_add=%s | %s",
                            self.user_id,
                            self.target_dept,
                            [r.name for r in to_remove],
                            [r.name for r in to_add],
                            "; ".join(msg_parts),
                        )
                        verify_failed_msg = "; ".join(msg_parts)

                # Ник по формату отдела
                new_nick = get_transfer_nickname(self.target_dept, self.form_data)
                if new_nick:
                    try:
                        await safe_discord_call(member.edit, nick=new_nick)
                    except Exception as e:
                        logger.warning("Не удалось сменить ник при переводе: %s", e)

                # Уведомление в ЛС
                try:
                    label = get_approval_label_target(self.target_dept)
                    await member.send(
                        f"✅ Ваша заявка одобрена. Вы переведены в **{label}**."
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass

                # Обновить сообщение: обе кнопки серые
                approver_role_ids = get_chief_deputy_role_ids(self.target_dept)
                who = interaction.user
                self.approved_target = next(
                    (rid for rid in approver_role_ids if guild.get_role(rid) in who.roles),
                    approver_role_ids[0] if approver_role_ids else 1,
                )
                update_department_transfer_approval(self.message_id, approved_target=self.approved_target)
                final_view = DepartmentApprovalView(
                    self.message_id,
                    self.user_id,
                    self.target_dept,
                    self.source_dept,
                    self.from_academy,
                    self.form_data,
                    approved_source=self.approved_source,
                    approved_target=self.approved_target,
                    channel_id=self.channel_id,
                )
                try:
                    msg = await interaction.channel.fetch_message(self.message_id)
                    await msg.edit(view=final_view)
                except Exception as e:
                    logger.warning("Не удалось обновить сообщение заявки %s: %s", self.message_id, e)

                active_department_transfers.pop(self.message_id, None)
                await asyncio.to_thread(delete_department_transfer_request, self.message_id)

                if verify_failed_msg:
                    await interaction.followup.send(
                        f"✅ Заявка одобрена, роли обновлены. ⚠️ Проверка не прошла: {verify_failed_msg}. Проверьте участника вручную.",
                        ephemeral=True,
                    )
                else:
                    await interaction.followup.send("✅ Заявка одобрена, роли обновлены.", ephemeral=True)
        except RuntimeError as e:
            if str(e) == "ACTION_ALREADY_IN_PROGRESS":
                await interaction.followup.send("⚠️ Действие уже выполняется.", ephemeral=True)
                return
            raise
        except Exception as e:
            logger.error("Ошибка одобрения целевого отдела: %s", e, exc_info=True)
            await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)
