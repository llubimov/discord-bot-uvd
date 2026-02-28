import discord
from discord.ui import View, Button
import logging
import asyncio
import re

from config import Config
from views.theme import RED
from views.message_texts import ErrorMessages
from state import active_firing_requests
from utils.rate_limiter import apply_role_changes, safe_discord_call
from utils.embed_utils import copy_embed, add_officer_field
from services.audit import send_to_audit
from services.action_locks import action_lock
from database import delete_request
from constants import StatusValues, FieldNames, WebhookPatterns
from services.firing_fsm import can_approve

logger = logging.getLogger(__name__)


def _set_firing_status_in_embed(embed: discord.Embed, status_value: str) -> None:
    for i, field in enumerate(embed.fields):
        if (field.name or "").strip() == FieldNames.STATUS:
            embed.set_field_at(i, name=FieldNames.STATUS, value=status_value, inline=field.inline)
            return
    embed.add_field(name=FieldNames.STATUS, value=status_value, inline=True)


class FiringView(View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            await interaction.response.send_message("❌ Команда доступна только на сервере.", ephemeral=True)
            return False

        # Роль кадровика (увольнение) через кэш, если он инициализирован
        staff_role = None
        try:
            import state as _state_for_roles  # локальный импорт, чтобы избежать циклов
            cache = getattr(_state_for_roles, "role_cache", None)
        except Exception:
            cache = None
        if cache is not None:
            staff_role = await cache.get_role(interaction.guild.id, Config.FIRING_STAFF_ROLE_ID)
        else:
            staff_role = interaction.guild.get_role(Config.FIRING_STAFF_ROLE_ID)
        if not staff_role or staff_role not in interaction.user.roles:
            await interaction.response.send_message(ErrorMessages.NO_PERMISSION, ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Уволить", style=discord.ButtonStyle.danger, custom_id="fire_accept")
    async def accept_firing_button(self, interaction: discord.Interaction, button: Button):
        await self.handle_fire(interaction)

    @discord.ui.button(label="Отклонить с причиной", style=discord.ButtonStyle.secondary, custom_id="fire_reject")
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

        # Новый формат: "Я, **Имя Фамилия**, прошу"
        m_name = re.search(r"Я,\s*\*\*([^*]+)\*\*,\s*прошу", desc, re.IGNORECASE)
        if m_name:
            full_name = (m_name.group(1) or "").strip() or "Сотрудник"
        if not m_name:
            m_name = re.search(WebhookPatterns.FIRING["full_name"], desc, re.IGNORECASE)
        if not m_name:
            m_name = re.search(WebhookPatterns.FIRING["full_name_alt"], desc, re.IGNORECASE)
        if m_name and not full_name or full_name == "Сотрудник":
            try:
                full_name = (m_name.group(1) or "").strip() or "Сотрудник"
            except Exception:
                pass

        m_reason = re.search(WebhookPatterns.FIRING["reason"], desc, re.IGNORECASE)
        if m_reason:
            try:
                reason = (m_reason.group(1) or "").strip() or "псж"
            except Exception:
                pass

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
                if not interaction.guild:
                    await interaction.followup.send("❌ Команда доступна только на сервере.", ephemeral=True)
                    return

                if not interaction.message.embeds:
                    await interaction.followup.send("❌ У рапорта отсутствует embed.", ephemeral=True)
                    return

                request_data = active_firing_requests.get(interaction.message.id)

                # Fallback для старых рапортов
                if not request_data:
                    request_data = self._rebuild_request_data_from_embed(interaction.message)
                    if request_data:
                        active_firing_requests[interaction.message.id] = request_data
                        logger.warning(
                            "Увольнение: заявка %s восстановлена из embed (state/БД пусто)",
                            interaction.message.id
                        )

                if not request_data:
                    await interaction.followup.send(ErrorMessages.NOT_FOUND.format(item="рапорт"), ephemeral=True)
                    return

                if not can_approve(request_data):
                    await interaction.followup.send("⚠️ Этот рапорт уже обработан.", ephemeral=True)
                    return

                # Защита от уже обработанного рапорта (по embed статусу)
                try:
                    for field in interaction.message.embeds[0].fields:
                        fname = (field.name or "").strip()
                        fval = (field.value or "").strip().lower()
                        if fname == FieldNames.STATUS and ("уволен" in fval or "удовлетворен" in fval):
                            await interaction.followup.send("⚠️ Этот рапорт уже обработан.", ephemeral=True)
                            return
                except Exception:
                    pass

                try:
                    member = interaction.guild.get_member(int(request_data.get("discord_id", 0)))
                    if not member:
                        member = await interaction.guild.fetch_member(int(request_data.get("discord_id", 0)))
                except (TypeError, ValueError, discord.NotFound):
                    member = None

                full_name = request_data.get("full_name", "Сотрудник")

                if not member:
                    # Сотрудник уже покинул сервер: фиксируем рапорт, без дополнительного сообщения в канал
                    new_embed = copy_embed(interaction.message.embeds[0])
                    new_embed = add_officer_field(new_embed, interaction.user.mention)
                    new_embed.color = RED
                    _set_firing_status_in_embed(new_embed, StatusValues.FIRED)
                    try:
                        await interaction.message.edit(embed=new_embed, view=None)
                    except Exception as e:
                        logger.warning("Не удалось обновить рапорт (member left): %s", e)

                    # Попытка отправить в кадровый аудит, даже если участник уже не в гильдии
                    class _StubMember:
                        def __init__(self, uid: int):
                            self.id = uid

                    try:
                        await send_to_audit(
                            interaction,
                            _StubMember(int(request_data.get("discord_id", 0))),
                            Config.ACTION_FIRED,
                            Config.RANK_FIRED,
                            request_data.get("message_link") or interaction.message.jump_url,
                        )
                    except Exception as e:
                        logger.warning(
                            "Ошибка аудита увольнения (member left, user_id=%s): %s",
                            request_data.get("discord_id", 0),
                            e,
                            exc_info=True,
                        )

                    active_firing_requests.pop(interaction.message.id, None)
                    try:
                        await delete_request("firing_requests", interaction.message.id)
                    except Exception as e:
                        logger.warning("Не удалось удалить firing_request из БД: %s", e)

                    try:
                        from services.promotion_draft_cleanup import clear_promotion_draft_for_user
                        clear_promotion_draft_for_user(int(request_data.get("discord_id", 0)))
                    except Exception:
                        pass

                    await interaction.followup.send(
                        f"✅ Рапорт зафиксирован. Сотрудник **{full_name}** уже покинул сервер.",
                        ephemeral=True,
                    )
                    return

                # Снимаем роли
                roles_to_keep_ids = set(Config.ROLES_TO_KEEP_ON_FIRE)
                roles_to_remove = []
                for role in member.roles:
                    if role.is_default() or role.is_integration() or role.is_bot_managed():
                        continue
                    if role.id not in roles_to_keep_ids:
                        roles_to_remove.append(role)

                if roles_to_remove:
                    try:
                        await apply_role_changes(member, remove=roles_to_remove)
                    except discord.Forbidden:
                        await interaction.followup.send("❌ У бота нет прав снять роли.", ephemeral=True)
                        return
                    except discord.HTTPException as e:
                        logger.warning("HTTP ошибка при снятии ролей (firing): %s", e, exc_info=True)
                        await interaction.followup.send("❌ Ошибка Discord API при снятии ролей.", ephemeral=True)
                        return

                # Выдаём роль уволенного (через кэш, если есть)
                fired_role = None
                try:
                    import state as _state_for_roles  # локальный импорт, чтобы избежать циклов
                    cache = getattr(_state_for_roles, "role_cache", None)
                except Exception:
                    cache = None
                if cache is not None:
                    fired_role = await cache.get_role(interaction.guild.id, Config.FIRED_ROLE_ID)
                else:
                    fired_role = interaction.guild.get_role(Config.FIRED_ROLE_ID)
                if fired_role:
                    try:
                        await apply_role_changes(member, add=[fired_role])
                    except discord.Forbidden:
                        await interaction.followup.send("❌ У бота нет прав выдать роль уволенного.", ephemeral=True)
                        return
                    except discord.HTTPException as e:
                        logger.warning("HTTP ошибка при выдаче роли уволенного: %s", e, exc_info=True)
                        await interaction.followup.send("❌ Ошибка Discord API при выдаче роли.", ephemeral=True)
                        return

                # Меняем ник: убираем префикс отдела/курсанта из full_name (мог прийти «ППС | Имя Фамилия»), ставим только «Уволен | Имя Фамилия»
                name_for_nick = (full_name or "").strip()
                if " | " in name_for_nick:
                    name_for_nick = name_for_nick.split(" | ", 1)[-1].strip()
                if not name_for_nick:
                    name_for_nick = full_name or "Сотрудник"
                prefix = (Config.FIRING_NICKNAME_PREFIX or "Уволен |").strip()
                try:
                    parts = name_for_nick.split(None, 1)
                    if len(parts) >= 2:
                        new_nick = f"{prefix} {parts[0]} {parts[1]}"
                    else:
                        new_nick = f"{prefix} {name_for_nick}"
                    await safe_discord_call(member.edit, nick=new_nick)
                except discord.Forbidden:
                    logger.warning("Нет прав на смену ника пользователя %s", member.id)
                    new_nick = f"{prefix} {name_for_nick}"
                except discord.HTTPException as e:
                    logger.warning("HTTP ошибка при смене ника пользователя %s: %s", member.id, e, exc_info=True)
                    new_nick = f"{prefix} {name_for_nick}"
                except Exception as e:
                    logger.error("Ошибка при смене ника: %s", e, exc_info=True)
                    new_nick = f"{prefix} {name_for_nick}"

                try:
                    await send_to_audit(
                        interaction,
                        member,
                        Config.ACTION_FIRED,
                        Config.RANK_FIRED,
                        request_data.get("message_link") or interaction.message.jump_url
                    )
                except discord.Forbidden:
                    logger.warning("Нет прав на отправку аудита увольнения (user=%s)", member.id)
                except discord.HTTPException as e:
                    logger.warning("HTTP ошибка аудита увольнения (user=%s): %s", member.id, e, exc_info=True)
                except Exception as e:
                    logger.warning("Ошибка аудита увольнения (user=%s): %s", member.id, e, exc_info=True)

                # ЛС пользователю
                dm_warning = None
                try:
                    embed = discord.Embed(
                        title="Рапорт об увольнении удовлетворён",
                        color=RED,
                        description=f"**{interaction.guild.name}**\n\nРапорт об увольнении одобрен.",
                        timestamp=interaction.created_at
                    )
                    embed.add_field(name="Ваш новый ник", value=f"`{new_nick}`", inline=False)
                    embed.add_field(name="Уволил", value=interaction.user.mention, inline=True)
                    embed.add_field(name="Причина", value=request_data.get("reason", "псж"), inline=False)
                    await member.send(embed=embed)
                except discord.Forbidden:
                    dm_warning = f"⚠️ Не удалось отправить уведомление пользователю {member.mention}"
                except discord.HTTPException as e:
                    logger.warning("HTTP ошибка при ЛС об увольнении пользователю %s: %s", member.id, e)
                    dm_warning = f"⚠️ Не удалось отправить уведомление пользователю {member.mention}"

                # Обновляем сообщение рапорта
                message = interaction.message
                old_embed = message.embeds[0]
                new_embed = copy_embed(old_embed)
                new_embed = add_officer_field(new_embed, interaction.user.mention)
                new_embed.color = RED
                _set_firing_status_in_embed(new_embed, StatusValues.FIRED)

                try:
                    await message.edit(embed=new_embed, view=None)
                except discord.NotFound:
                    await interaction.followup.send("❌ Сообщение рапорта было удалено.", ephemeral=True)
                    return
                except discord.Forbidden:
                    await interaction.followup.send("❌ У бота нет прав на редактирование рапорта.", ephemeral=True)
                    return
                except discord.HTTPException as e:
                    logger.warning("HTTP ошибка при обновлении рапорта увольнения %s: %s", message.id, e, exc_info=True)
                    await interaction.followup.send("❌ Ошибка Discord API при обновлении рапорта.", ephemeral=True)
                    return

                # Сообщение в канал не отправляем — рапорт уже обновлён, лишняя запись не нужна

                # Чистим state + БД
                active_firing_requests.pop(interaction.message.id, None)
                try:
                    await delete_request("firing_requests", interaction.message.id)
                except Exception as e:
                    logger.warning("Не удалось удалить firing_request %s из БД: %s", interaction.message.id, e, exc_info=True)

                try:
                    from services.promotion_draft_cleanup import clear_promotion_draft_for_user
                    clear_promotion_draft_for_user(member.id)
                except Exception:
                    pass

                await interaction.followup.send(f"✅ Пользователь {member.mention} уволен.", ephemeral=True)
                if dm_warning:
                    await interaction.followup.send(dm_warning, ephemeral=True)

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