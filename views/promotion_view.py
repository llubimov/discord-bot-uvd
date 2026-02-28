import discord
from discord.ui import View, Button
import logging
import asyncio
import re

from config import Config
from views.theme import GREEN
from views.message_texts import ErrorMessages
import state
from state import active_promotion_requests
from utils.rate_limiter import apply_role_changes
from utils.embed_utils import copy_embed, add_officer_field, update_embed_status
from services.audit import send_to_audit
from services.action_locks import action_lock
from services.ranks import (
    find_role_id_for_transition,
    get_all_rank_role_ids_from_mapping,
    get_all_rank_names_from_mapping,
    parse_transition_to_new_rank,
)
from database import delete_request
from constants import StatusValues, FieldNames, WebhookPatterns

logger = logging.getLogger(__name__)


def _norm_text(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _is_rank_role_by_name(role_name: str, rank_names: set) -> bool:
    return _norm_text(role_name) in (rank_names or set())


class PromotionView(View):
    def __init__(self, user_id: int, new_rank: str, full_name: str, message_id: int):
        super().__init__(timeout=None)
        self.user_id = int(user_id)
        self.new_rank = str(new_rank or "").strip()
        self.full_name = str(full_name or "сотрудник").strip() or "сотрудник"
        self.message_id = int(message_id)

    @staticmethod
    def _normalize_transition_string(value: str) -> str:
        """
        Нормализует строку перехода звания:
        - убирает лишние пробелы
        - если есть позывной/префикс вида «XXX | ...», оставляет часть,
          в которой содержится переход ранга («... -> ...»), или последнюю часть.
        """
        text = (value or "").strip()
        if not text:
            return text

        if "|" in text:
            parts = [p.strip() for p in text.split("|") if p.strip()]
            arrow_syms = ("->", "→", "➡", "⇒")
            with_arrow = [p for p in parts if any(sym in p for sym in arrow_syms)]
            if with_arrow:
                text = with_arrow[0]
            else:
                text = parts[-1]

        return text

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            await interaction.response.send_message("❌ Команда доступна только на сервере.", ephemeral=True)
            return False

        role_ids = list(Config.PROMOTION_CHANNELS.get(interaction.channel.id, []) or [])
        if not role_ids:
            await interaction.response.send_message("❌ Для этого канала не настроена роль доступа.", ephemeral=True)
            return False

        custom_id = (interaction.data or {}).get("custom_id")

        # Первая роль в списке — «основной кадровик»,
        # только он может одобрять рапорт (кнопка promotion_accept).
        main_role_id = int(role_ids[0])
        extra_role_ids = [int(rid) for rid in role_ids[1:]]

        member_roles = set(interaction.user.roles or [])

        if custom_id == "promotion_accept":
            staff_role = None
            role_cache = getattr(state, "role_cache", None)
            if role_cache:
                staff_role = await role_cache.get_role(interaction.guild.id, main_role_id)
            if staff_role is None:
                staff_role = interaction.guild.get_role(main_role_id)
            if not staff_role or staff_role not in member_roles:
                await interaction.response.send_message(ErrorMessages.NO_PERMISSION, ephemeral=True)
                return False
            return True

        # Для отклонения (promotion_reject) могут использоваться несколько ролей:
        # основная + дополнительные из списка.
        allowed_roles = []
        role_cache = getattr(state, "role_cache", None)
        role_ids_to_fetch = [main_role_id, *extra_role_ids]
        if role_cache:
            allowed_roles = [r for r in await role_cache.get_many_roles(interaction.guild.id, role_ids_to_fetch) if r]
        else:
            for rid in role_ids_to_fetch:
                role = interaction.guild.get_role(int(rid))
                if role:
                    allowed_roles.append(role)

        if not any(r in member_roles for r in allowed_roles):
            await interaction.response.send_message(ErrorMessages.NO_PERMISSION, ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ Одобрить повышение", style=discord.ButtonStyle.success, custom_id="promotion_accept")
    async def accept_promotion_button(self, interaction: discord.Interaction, button: Button):
        await self.handle_accept(interaction)

    @discord.ui.button(label="❌ Отклонить рапорт", style=discord.ButtonStyle.secondary, custom_id="promotion_reject")
    async def reject_promotion_button(self, interaction: discord.Interaction, button: Button):
        from modals.promotion_reject_reason import PromotionRejectReasonModal
        modal = PromotionRejectReasonModal(
            user_id=self.user_id,
            message_id=self.message_id,
            additional_data={"new_rank": self.new_rank, "full_name": self.full_name}
        )
        await interaction.response.send_modal(modal)

    def _rebuild_request_data_from_embed(self, message: discord.Message):
        if not message or not message.embeds:
            return None
        embed = message.embeds[0]

        discord_id = self.user_id
        full_name = self.full_name or "сотрудник"
        rank_transition = ""
        new_rank = self.new_rank

        desc = (embed.description or "")
        if desc:
            m = re.search(WebhookPatterns.PROMOTION.get("user_id_desc", r"<@(\d+)>") , desc)
            if m:
                try:
                    discord_id = int(m.group(1))
                except Exception:
                    pass

            # ожидаемый формат: "👤 <переход ранга> | <ФИО>"
            m = re.search(WebhookPatterns.PROMOTION.get("rank_and_name", r"👤\s*(.+?)\s*\|\s*(.+)"), desc, re.IGNORECASE)
            if m:
                rank_transition = (m.group(1) or "").strip()
                parsed_name = (m.group(2) or "").strip()
                if parsed_name:
                    full_name = parsed_name

        for field in embed.fields:
            fname = (field.name or "").strip().lower()
            fval = (field.value or "").strip()
            if fname in {FieldNames.NEW_RANK.lower(), FieldNames.RANK.lower()} and fval:
                new_rank = fval
            elif fname in {FieldNames.FULL_NAME.lower(), "фио"} and fval:
                full_name = fval

        return {
            "discord_id": discord_id,
            "full_name": full_name,
            "new_rank": new_rank,
            "rank_transition": rank_transition,
            "message_link": getattr(message, "jump_url", ""),
        }

    async def handle_accept(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            async with action_lock(self.message_id, "принятие повышения"):
                if not interaction.guild:
                    await interaction.followup.send("❌ Команда доступна только на сервере.", ephemeral=True)
                    return

                message = interaction.message
                if not message or not message.embeds:
                    await interaction.followup.send("❌ У рапорта отсутствует embed.", ephemeral=True)
                    return

                # Fallback для старых рапортов
                request_data = active_promotion_requests.get(self.message_id)
                if not request_data:
                    request_data = self._rebuild_request_data_from_embed(message)
                    if request_data:
                        active_promotion_requests[self.message_id] = request_data
                        logger.warning(
                            "Повышение: рапорт %s восстановлен из embed (state/БД пусто)",
                            self.message_id
                        )

                if request_data:
                    # Синхронизируем self.* (важно для старых view)
                    try:
                        self.user_id = int(request_data.get("discord_id", self.user_id))
                    except (TypeError, ValueError):
                        pass
                    self.full_name = request_data.get("full_name", self.full_name) or "сотрудник"
                    self.new_rank = request_data.get("new_rank", self.new_rank) or self.new_rank

                # Защита от повторной обработки по статусу embed
                try:
                    for field in message.embeds[0].fields:
                        if (field.name or "").strip() == FieldNames.STATUS:
                            status_text = (field.value or "").strip().lower()
                            if "принят" in status_text or "одоб" in status_text:
                                await interaction.followup.send("⚠️ Этот рапорт уже обработан.", ephemeral=True)
                                return
                            if "отклон" in status_text:
                                await interaction.followup.send("⚠️ Этот рапорт уже отклонён.", ephemeral=True)
                                return
                except Exception:
                    pass

                member = interaction.guild.get_member(self.user_id)
                if not member:
                    try:
                        member = await interaction.guild.fetch_member(self.user_id)
                    except discord.NotFound:
                        member = None
                    except discord.Forbidden:
                        await interaction.followup.send("❌ У бота нет прав получить участника.", ephemeral=True)
                        return
                    except discord.HTTPException as e:
                        logger.warning("Promotion: HTTP ошибка fetch_member %s: %s", self.user_id, e)
                        await interaction.followup.send("❌ Ошибка Discord API при получении пользователя.", ephemeral=True)
                        return

                if not member:
                    await interaction.followup.send(ErrorMessages.NOT_FOUND.format(item="пользователь"), ephemeral=True)
                    return

                # Ключевой фикс: ищем роль сначала по rank_transition, потом по new_rank
                rank_transition = ""
                if request_data:
                    rank_transition = (request_data.get("rank_transition") or "").strip()

                raw_lookup_value = rank_transition or self.new_rank
                role_lookup_value = self._normalize_transition_string(raw_lookup_value)
                new_role_id = find_role_id_for_transition(role_lookup_value)

                if not new_role_id:
                    display_rank = self._normalize_transition_string(self.new_rank or raw_lookup_value)
                    await interaction.followup.send(
                        f"❌ Не настроена роль для повышения: `{display_rank}`. Проверь RANK_ROLE_MAPPING.",
                        ephemeral=True
                    )
                    logger.warning(
                        "Promotion: не найдена роль | raw_lookup='%s' | lookup='%s' | display_rank='%s' | msg_id=%s",
                        raw_lookup_value,
                        role_lookup_value,
                        display_rank,
                        self.message_id,
                    )
                    return

                new_role = None
                role_cache = getattr(state, "role_cache", None)
                if role_cache:
                    new_role = await role_cache.get_role(interaction.guild.id, int(new_role_id))
                if new_role is None:
                    new_role = interaction.guild.get_role(int(new_role_id))
                if not new_role:
                    await interaction.followup.send(
                        f"❌ Роль для повышения не найдена на сервере (role_id={new_role_id}).",
                        ephemeral=True
                    )
                    return

                rank_role_ids = set(getattr(Config, "ALL_RANK_ROLE_IDS", []) or [])
                rank_role_ids |= set(get_all_rank_role_ids_from_mapping())
                rank_names = get_all_rank_names_from_mapping()

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
                    "Повышение: user=%s target_role=%s lookup='%s' remove_roles=%s",
                    member.id,
                    new_role.id,
                    role_lookup_value,
                    [r.id for r in roles_to_remove]
                )

                # Снимаем/выдаем роли
                try:
                    if roles_to_remove:
                        await apply_role_changes(member, remove=roles_to_remove)
                    await apply_role_changes(member, add=[new_role])
                except discord.Forbidden:
                    await interaction.followup.send("❌ У бота нет прав изменить роли пользователя.", ephemeral=True)
                    return
                except discord.HTTPException as e:
                    logger.warning("Promotion: HTTP ошибка изменения ролей user=%s: %s", member.id, e, exc_info=True)
                    await interaction.followup.send("❌ Ошибка Discord API при изменении ролей.", ephemeral=True)
                    return

                # Обновим member после смены ролей
                try:
                    member = await interaction.guild.fetch_member(self.user_id)
                except Exception:
                    pass

                rank_for_audit = self.new_rank
                try:
                    await send_to_audit(
                        interaction,
                        member,
                        Config.ACTION_PROMOTED,
                        rank_for_audit,
                        request_data.get("message_link") if request_data else f"https://discord.com/channels/{interaction.guild.id}/{interaction.channel.id}/{self.message_id}"
                    )
                except discord.Forbidden:
                    logger.warning("Promotion audit: нет прав отправить аудит user=%s", member.id)
                except discord.HTTPException as e:
                    logger.warning("Promotion audit: HTTP ошибка user=%s: %s", member.id, e, exc_info=True)
                except Exception as e:
                    logger.warning("Promotion audit: ошибка user=%s: %s", member.id, e, exc_info=True)

                # После кадрового аудита: при повышении до сержанта выдать роль «прошедший академию»
                role_passed_academy_id = getattr(Config, "ROLE_PASSED_ACADEMY", 0) or 0
                if not role_passed_academy_id:
                    logger.debug("ROLE_PASSED_ACADEMY не задан в .env — роль «прошедший академию» не выдаётся")
                if role_passed_academy_id:
                    rank_transition = (request_data or {}).get("rank_transition") or ""
                    # Переход может быть в rank_transition или в self.new_rank (например из вебхука)
                    transition_str = rank_transition or self.new_rank or ""
                    new_rank_canon = (parse_transition_to_new_rank(transition_str) or "").strip().lower()
                    new_rank_norm = _norm_text(self.new_rank)
                    # Сержант (ровно), не младший и не старший
                    is_sergeant = (
                        new_rank_canon in ("сержант", "сержант полиции")
                        or new_rank_norm in ("сержант", "сержант полиции")
                    )
                    if is_sergeant:
                        role_passed = None
                        role_cache = getattr(state, "role_cache", None)
                        if role_cache:
                            role_passed = await role_cache.get_role(interaction.guild.id, int(role_passed_academy_id))
                        if role_passed is None:
                            role_passed = interaction.guild.get_role(int(role_passed_academy_id))
                        if role_passed and role_passed not in member.roles:
                            try:
                                await apply_role_changes(member, add=[role_passed])
                                logger.info("Повышение до сержанта: выдана роль «прошедший академию» user_id=%s", member.id)
                            except (discord.Forbidden, discord.HTTPException) as e:
                                logger.warning("Не удалось выдать ROLE_PASSED_ACADEMY user=%s: %s", member.id, e)
                        elif role_passed and role_passed in member.roles:
                            logger.info("Повышение до сержанта: роль «прошедший академию» уже есть user_id=%s", member.id)
                        elif not role_passed:
                            logger.warning("ROLE_PASSED_ACADEMY=%s не найден на сервере", role_passed_academy_id)
                    else:
                        logger.debug(
                            "Повышение не до сержанта (роль прошедший академию не выдаём): new_rank=%r transition=%r canon=%r norm=%r",
                            self.new_rank, rank_transition, new_rank_canon, new_rank_norm,
                        )

                # ЛС пользователю
                dm_warning = None
                try:
                    embed = discord.Embed(
                        title="Рапорт на повышение одобрен",
                        color=GREEN,
                        description=f"**{interaction.guild.name}**\n\nВаш рапорт на повышение одобрен.",
                        timestamp=interaction.created_at
                    )
                    embed.add_field(name="Новое звание", value=self.new_rank, inline=True)
                    embed.add_field(name="Принял", value=interaction.user.mention, inline=True)

                    await member.send(embed=embed)
                except discord.Forbidden:
                    dm_warning = f"⚠️ Не удалось отправить уведомление пользователю {member.mention}"
                except discord.HTTPException as e:
                    logger.warning("Promotion DM: HTTP ошибка user=%s: %s", member.id, e)
                    dm_warning = f"⚠️ Не удалось отправить уведомление пользователю {member.mention}"

                # Обновляем сообщение рапорта
                try:
                    message = await interaction.channel.fetch_message(self.message_id)
                except discord.NotFound:
                    await interaction.followup.send("❌ Сообщение рапорта было удалено.", ephemeral=True)
                    return
                except discord.Forbidden:
                    await interaction.followup.send("❌ У бота нет доступа к сообщению рапорта.", ephemeral=True)
                    return
                except discord.HTTPException as e:
                    logger.warning("Promotion: HTTP ошибка fetch_message %s: %s", self.message_id, e)
                    await interaction.followup.send("❌ Ошибка Discord API при получении рапорта.", ephemeral=True)
                    return

                if not message.embeds:
                    await interaction.followup.send("❌ У сообщения рапорта отсутствует embed.", ephemeral=True)
                    return

                new_embed = copy_embed(message.embeds[0])
                new_embed = update_embed_status(new_embed, StatusValues.ACCEPTED, GREEN)
                new_embed = add_officer_field(new_embed, interaction.user.mention)

                try:
                    await message.edit(embed=new_embed, view=None)
                except discord.NotFound:
                    await interaction.followup.send("❌ Сообщение рапорта было удалено.", ephemeral=True)
                    return
                except discord.Forbidden:
                    await interaction.followup.send("❌ У бота нет прав на редактирование рапорта.", ephemeral=True)
                    return
                except discord.HTTPException as e:
                    logger.warning("Promotion: HTTP ошибка edit %s: %s", self.message_id, e, exc_info=True)
                    await interaction.followup.send("❌ Ошибка Discord API при обновлении рапорта.", ephemeral=True)
                    return

                # Чистим state + БД
                active_promotion_requests.pop(self.message_id, None)
                try:
                    await asyncio.to_thread(delete_request, "promotion_requests", self.message_id)
                except Exception as e:
                    logger.warning("Не удалось удалить promotion_request %s из БД: %s", self.message_id, e, exc_info=True)

                await interaction.followup.send(
                    f"✅ Пользователь {member.mention} повышен до {self.new_rank}",
                    ephemeral=True
                )
                if dm_warning:
                    await interaction.followup.send(dm_warning, ephemeral=True)

                logger.info("Рапорт на повышение %s принят сотрудником %s", self.message_id, interaction.user.id)

        except RuntimeError as e:
            if str(e) == "ACTION_ALREADY_IN_PROGRESS":
                await interaction.followup.send("⚠️ Это действие уже выполняется другим нажатием.", ephemeral=True)
                return
            logger.error("Ошибка блокировки действия (повышение): %s", e, exc_info=True)
            await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)

        except Exception as e:
            logger.error("Ошибка при принятии рапорта на повышение: %s", e, exc_info=True)
            await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)