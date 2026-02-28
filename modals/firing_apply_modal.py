from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime

import discord
from discord.ui import Modal, TextInput

from config import Config
from database import save_request
from state import active_firing_requests, bot
from views.firing_view import FiringView
from utils.validators import Validators
from utils.rate_limiter import safe_send
from utils.rank_decline import decline_rank_genitive
from constants import FieldNames, StatusValues
from views.theme import RED
from utils.member_display import get_member_full_name

logger = logging.getLogger(__name__)

RECOVERY_OPTIONS = ("с восстановлением", "без восстановления")


def _build_firing_embed(
    discord_id: int,
    full_name: str,
    rank: str,
    photo_link: str,
    with_recovery: bool,
    reason: str,
    created_at: datetime,
    *,
    is_auto_report: bool = False,
    mention: str | None = None,
) -> discord.Embed:
    first_name = full_name.split()[0] if full_name.strip() else "Сотрудник"
    title = f"📬 РАПОРТ НА УВОЛЬНЕНИЕ (от {first_name})"
    recovery_text = "с возможностью восстановления" if with_recovery else "без возможности восстановления"
    date_str = created_at.strftime("%d.%m.%Y")
    time_str = created_at.strftime("%H:%M")
    rank_genitive = decline_rank_genitive(rank)

    officer_display = mention if mention else f"<@!{discord_id}>"

    body = (
        "**РАПОРТ ОБ УВОЛЬНЕНИИ**\n"
        "Начальнику УВД по ЦАО ГУ МВД по г. Москва и Московской области\n"
        "Генерал-полковник полиции Визнер С.В.\n\n"
        f"ОТ {rank_genitive} — {officer_display}\n\n"
        f"Я, **{full_name}**, прошу уволить меня из рядов Управления Внутренних Дел Российской Федерации {recovery_text}.\n\n"
        "🌟 Фото удостоверения:\n"
        f"{photo_link or '—'}\n\n"
        f"{date_str}"
    )

    embed = discord.Embed(title=title, description=body, color=RED)
    embed.add_field(name=FieldNames.OFFICER, value=officer_display, inline=True)
    embed.add_field(name=FieldNames.STATUS, value="⏳ Ожидает рассмотрения", inline=True)
    if is_auto_report:
        embed.add_field(
            name="Примечание",
            value="Автоматический рапорт на увольнение (сотрудник вышел с сервера).",
            inline=False,
        )
    embed.set_footer(text=f"Управление Внутренних Дел • Кадровая служба • {time_str}")
    return embed


class FiringApplyModal(Modal):
    def __init__(self, member: discord.Member | None = None):
        super().__init__(title=Config.FIRING_MODAL_TITLE)
        from services.ranks import get_member_rank_display
        rank_default = (get_member_rank_display(member) or "").strip()
        full_name_default = get_member_full_name(member)
        self.full_name_input = TextInput(
            label="Ваше имя и фамилия",
            min_length=Config.MIN_NAME_LENGTH,
            max_length=Config.MAX_NAME_LENGTH * 2 + 1,
            required=True,
            placeholder="Имя Фамилия",
            default=full_name_default,
        )
        self.photo_input = TextInput(
            label="Фотография служебного удостоверения",
            max_length=500,
            required=False,
            placeholder="Ссылка на фото (Discord, imgur и т.д.). Можно оставить пустым.",
        )
        self.rank_input = TextInput(
            label="Ваше звание",
            max_length=Config.MAX_RANK_LENGTH,
            required=True,
            placeholder="Например: Рядовой полиции",
            default=rank_default,
        )
        self.recovery_input = TextInput(
            label="С восстановлением или без",
            max_length=50,
            required=True,
            placeholder="С восстановлением / Без восстановления",
        )
        self.reason_input = TextInput(
            label="Причина увольнения (ПСЖ)",
            style=discord.TextStyle.paragraph,
            max_length=Config.MAX_REASON_LENGTH,
            required=True,
            placeholder="Укажите причину или пожелание",
        )
        self.add_item(self.full_name_input)
        self.add_item(self.photo_input)
        self.add_item(self.rank_input)
        self.add_item(self.recovery_input)
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.user or not interaction.guild:
            await interaction.response.send_message("❌ Ошибка контекста.", ephemeral=True)
            return

        raw_name = self.full_name_input.value.strip()

        parts = raw_name.split(None, 1)
        if len(parts) >= 2:
            ok1, name = Validators.validate_name(parts[0])
            ok2, surname = Validators.validate_name(parts[1])
            if not ok1:
                await interaction.response.send_message(f"❌ Имя: {name}", ephemeral=True)
                return
            if not ok2:
                await interaction.response.send_message(f"❌ Фамилия: {surname}", ephemeral=True)
                return
            full_name = f"{name} {surname}"
        else:
            ok, res = Validators.validate_name(raw_name)
            if not ok:
                await interaction.response.send_message(f"❌ Имя и фамилия: {res}", ephemeral=True)
                return
            full_name = res + " (укажите фамилию)"

        recovery_raw = (self.recovery_input.value or "").strip().lower()
        if recovery_raw not in RECOVERY_OPTIONS:
            await interaction.response.send_message(
                "❌ Укажите: **С восстановлением** или **Без восстановления**.",
                ephemeral=True,
            )
            return
        with_recovery = recovery_raw == RECOVERY_OPTIONS[0]

        ok, reason = Validators.validate_reason(self.reason_input.value)
        if not ok:
            await interaction.response.send_message(f"❌ Причина: {reason}", ephemeral=True)
            return

        photo_link = (self.photo_input.value or "").strip()
        if photo_link and Config.URL_PATTERN and not re.match(Config.URL_PATTERN, photo_link):
            await interaction.response.send_message(
                "❌ Укажите корректную ссылку на фотографию удостоверения или оставьте поле пустым.",
                ephemeral=True,
            )
            return

        rank = (self.rank_input.value or "").strip()
        if not rank:
            await interaction.response.send_message("❌ Укажите звание.", ephemeral=True)
            return

        discord_id = interaction.user.id
        created_at = datetime.now()
        embed = _build_firing_embed(
            discord_id=discord_id,
            full_name=full_name,
            rank=rank,
            photo_link=photo_link,
            with_recovery=with_recovery,
            reason=reason,
            created_at=created_at,
            mention=interaction.user.mention,
        )

        role_mention = f"<@&{Config.FIRING_STAFF_ROLE_ID}>" if getattr(Config, "FIRING_STAFF_ROLE_ID", 0) else ""
        view = FiringView(user_id=discord_id)


        channel = None
        try:
            import state as _state_for_channel  # локальный импорт, чтобы избежать циклов
            cache = getattr(_state_for_channel, "channel_cache", None)
            if cache is not None:
                channel = cache.get_channel(Config.FIRING_CHANNEL_ID)
        except Exception:
            channel = None
        if channel is None:
            channel = bot.get_channel(Config.FIRING_CHANNEL_ID)
        if not channel:
            await interaction.response.send_message("❌ Канал рапортов не найден.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            msg = await safe_send(channel, content=role_mention, embed=embed, view=view)
        except Exception as e:
            logger.error("Ошибка отправки рапорта на увольнение: %s", e, exc_info=True)
            await interaction.followup.send("❌ Не удалось отправить рапорт в канал.", ephemeral=True)
            return

        if msg:
            request_data = {
                "discord_id": discord_id,
                "full_name": full_name,
                "rank": rank,
                "reason": reason,
                "photo_link": photo_link,
                "recovery_option": "с возможностью восстановления" if with_recovery else "без возможности восстановления",
                "message_link": msg.jump_url,
            }
            active_firing_requests[msg.id] = request_data
            await save_request("firing_requests", msg.id, request_data)
            await interaction.followup.send("✅ Рапорт на увольнение отправлен в канал.", ephemeral=True)
        else:
            await interaction.followup.send("❌ Не удалось отправить рапорт.", ephemeral=True)


async def post_auto_firing_report(member: discord.Member) -> bool:
    if not member or not member.guild:
        return False

    channel = None
    try:
        import state as _state_for_channel  # локальный импорт, чтобы избежать циклов
        cache = getattr(_state_for_channel, "channel_cache", None)
        if cache is not None:
            channel = cache.get_channel(Config.FIRING_CHANNEL_ID)
    except Exception:
        channel = None
    if channel is None:
        channel = bot.get_channel(Config.FIRING_CHANNEL_ID)
    if not channel:
        logger.warning("FIRING_CHANNEL_ID не задан или канал не найден для авто-рапорта при выходе")
        return False
    full_name = member.display_name or member.name or "Сотрудник"
    created_at = datetime.now()
    embed = _build_firing_embed(
        discord_id=member.id,
        full_name=full_name,
        rank="—",
        photo_link="—",
        with_recovery=False,
        reason=Config.FIRING_AUTO_REASON,
        created_at=created_at,
        is_auto_report=True,
        mention=member.mention,
    )
    role_mention = f"<@&{Config.FIRING_STAFF_ROLE_ID}>" if getattr(Config, "FIRING_STAFF_ROLE_ID", 0) else ""
    view = FiringView(user_id=member.id)
    try:
        msg = await safe_send(channel, content=role_mention, embed=embed, view=view)
    except Exception as e:
        logger.error("Ошибка отправки авто-рапорта при выходе: %s", e, exc_info=True)
        return False
    if not msg:
        return False
    request_data = {
        "discord_id": member.id,
        "full_name": full_name,
        "rank": "—",
        "reason": Config.FIRING_AUTO_REASON,
        "photo_link": "—",
        "recovery_option": "без возможности восстановления",
        "message_link": msg.jump_url,
    }
    active_firing_requests[msg.id] = request_data
    await save_request("firing_requests", msg.id, request_data)
    logger.info("Отправлен авто-рапорт на увольнение при выходе user_id=%s", member.id)
    return True
