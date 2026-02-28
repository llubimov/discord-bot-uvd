import re
import discord
from discord.ui import View, Select
import logging
import asyncio

from config import Config
from constants import FieldNames, StatusValues, EmbedTitles
from models import PromotionRequest
import state
from state import active_promotion_requests, orls_draft_reports, orls_last_user_data
from database import save_request, save_orls_draft, load_orls_draft, delete_orls_draft
from services.worker_queue import get_worker
from services.department_roles import get_dept_role_id
from services.ranks import is_promotion_key_allowed_for_member, get_member_rank_display
from utils.promotion_helpers import parse_thanks_lines, send_long, required_count_from_text, normalize_thanks


logger = logging.getLogger(__name__)

# Баллы за один пункт балловой системы ОРЛС (типы 1–12)
ORLS_POINTS_MAP = {
    1: 60,   # Участие в собеседовании (60/час — за 1 ссылку считаем 60)
    2: 10,   # Проверка рапортов
    3: 10,   # Проверка электрон. заявки
    4: 10,   # Принятие звонка о вступлении
    5: 10,   # Проверка пакета документов
    6: 30,   # Патруль с Курсантом
    7: 35,   # Орг. тренировки (от 15 мин)
    8: 40,   # Проведение лекции
    9: 10,   # Проведение присяги
    10: 35,  # Проведение экзамена
    11: 40,  # Строевая подготовка (от 15 мин)
    12: 40,  # Переаттестация
}

ORLS_BONUS_LABELS = [
    (1, "Участие в собеседовании (60/час)"), (2, "Проверка рапортов (10)"),
    (3, "Проверка электрон. заявки (10)"), (4, "Принятие звонка о вступлении (10)"),
    (5, "Проверка пакета документов (10)"), (6, "Патруль с Курсантом (30)"),
    (7, "Организация тренировки (35)"), (8, "Проведение лекции (40)"),
    (9, "Проведение присяги (10)"), (10, "Проведение экзамена (35)"),
    (11, "Строевая подготовка (40)"), (12, "Проведение переаттестации (40)"),
]


PROMOTION_REQUIREMENTS_ORLS = {
    "Сержант -> Старший Сержант": {
        "points": 400,
        "required": [
            "Подача сейфа документов → 1 шт.",
            "Задержание → 1 шт.",
            "Составление административного протокола → 1 шт.",
            "Патруль с младшим по званию → 30 минут",
            "Участие в любом мероприятии от руководства → 1 шт.",
        ],
    },
    "Старший сержант -> Старшина": {
        "points": 500,
        "required": [
            "Задержание → 1 шт.",
            "Составление административного протокола → 2 шт.",
            "Участие в собеседовании → 1 шт.",
            "Проведение лекции → 2 шт.",
            "Проведение экзамена или тренировки → 2 шт.",
        ],
    },
    "Старшина -> Прапорщик": {
        "points": 600,
        "required": [
            "Участие в собеседовании → 1 шт.",
            "Проведение экзамена или тренировки (от 15 мин) → 3 шт.",
            "Проведение лекции → 3 шт.",
            "Проверка электронного заявления → 2 шт.",
        ],
    },
    "Прапорщик -> Старший прапорщик": {
        "points": 700,
        "required": [
            "Участие в любом мероприятии → 1 шт.",
            "Проведение экзамена или тренировки → 2 шт.",
            "Проведение лекции → 2 шт.",
            "Участие в собеседовании → 1 шт.",
        ],
    },
    "Старший прапорщик -> Младший лейтенант": {
        "points": 800,
        "required": [
            "Подача сейфа документов с военным билетом → 1 шт.",
            "Участие в любом мероприятии → 1 шт.",
            "Проверка рапорта на повышение → 2 шт.",
            "Проведение тренировки (от 15 мин) → 2 шт.",
            "Проведение лекции → 2 шт.",
        ],
    },
    "Младший лейтенант -> Лейтенант": {
        "points": 900,
        "required": [
            "Патруль с курсантом академии 30 минут → 2 шт.",
            "Участие в собеседовании → 1 шт.",
            "Проведение лекции → 2 шт.",
            "Проведение экзамена или тренировки (от 15 мин) → 2 шт.",
        ],
    },
    "Лейтенант -> Старший лейтенант": {
        "points": 1000,
        "required": [
            "Участие в собеседовании → 2 шт.",
            "Участие в любом мероприятии от руководства → 1 шт.",
            "Проведение лекции → 3 шт.",
            "Проведение экзамена или тренировки (от 15 мин) → 3 шт.",
            "Проверка рапорта на повышение → 2 шт.",
        ],
    },
    "Старший лейтенант -> Капитан": {
        "points": 1100,
        "required": [
            "Участие в собеседовании → 3 шт.",
            "Участие в любом мероприятии от руководства → 1 шт.",
            "Проведение лекции → 3 шт.",
            "Проведение экзамена или тренировки (от 15 мин) → 3 шт.",
            "Проверка рапорта на повышение → 3 шт.",
        ],
    },
}


ORLS_POINTS_TEXT = (
    "1. Участие в собеседовании → 60/час\n"
    "2. Проверка рапортов → 10\n"
    "3. Проверка электрон. заявки → 10\n"
    "4. Принятие звонка о вступлении → 10\n"
    "5. Проверка пакета документов → 10\n"
    "6. Патруль с Курсантом (Мл.Сержант) → 30\n"
    "7. Организация тренировки → 35 (от 15 минут)\n"
    "8. Проведение лекции → 40\n"
    "9. Проведение присяги → 10\n"
    "10. Проведение экзамена → 35\n"
    "11. Проведение строевой подготовки → 40 (от 15 минут)\n"
    "12. Проведение переаттестации → 40"
)

ORLS_POINTS_FIELDS = [
    ("Типы 1–4", "1. Участие в собеседовании → 60/час\n2. Проверка рапортов → 10\n3. Проверка электрон. заявки → 10\n4. Принятие звонка о вступлении → 10"),
    ("Типы 5–8", "5. Проверка пакета документов → 10\n6. Патруль с Курсантом (Мл.Сержант) → 30\n7. Организация тренировки → 35 (от 15 мин)\n8. Проведение лекции → 40"),
    ("Типы 9–12", "9. Проведение присяги → 10\n10. Проведение экзамена → 35\n11. Строевая подготовка → 40 (от 15 мин)\n12. Переаттестация → 40"),
]


def _parse_required_links(text: str, max_requirement: int) -> dict[int, list[str]]:
    result: dict[int, list[str]] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) >= 2:
            first = parts[0].rstrip(".)")
            if first.isdigit():
                num = min(max(1, int(first)), max_requirement)
                rest = parts[1].strip()
            else:
                num = 1
                rest = line
        else:
            num = 1
            rest = line
        if rest and (rest.startswith("http://") or rest.startswith("https://")):
            result.setdefault(num, []).append(rest)
    return result


def _parse_bonus_links(text: str) -> tuple[list[str], dict[int, list[str]], int]:
    all_urls: list[str] = []
    by_type: dict[int, list[str]] = {}
    total_points = 0
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) >= 2 and parts[0].isdigit():
            num = int(parts[0])
            rest = parts[1].strip()
            if 1 <= num <= 12 and rest and (rest.startswith("http://") or rest.startswith("https://")):
                by_type.setdefault(num, []).append(rest)
                total_points += ORLS_POINTS_MAP.get(num, 0)
                all_urls.append(rest)
                continue
        if line.startswith("http://") or line.startswith("https://"):
            all_urls.append(line)
    return all_urls, by_type, total_points


def _sort_int_like(keys):
    """Сортировка ключей, которые могут быть int или str (например из JSON)."""
    return sorted(keys, key=lambda k: int(k) if str(k).isdigit() else -1)


def _build_collector_embed(draft: dict) -> discord.Embed:
    promotion_key = draft.get("promotion_key", "")
    full_name = draft.get("full_name", "")
    req_links = draft.get("requirement_links") or {}
    bonus_links = draft.get("bonus_links") or {}
    info = PROMOTION_REQUIREMENTS_ORLS.get(promotion_key, {})
    required_list = info.get("required", [])
    points_required = info.get("points", 0)

    fulfilled = 0
    for idx, req in enumerate(required_list, start=1):
        need = required_count_from_text(req)
        if len(req_links.get(idx, [])) >= need:
            fulfilled += 1
    total_bonus = sum(ORLS_POINTS_MAP.get(int(t) if str(t).isdigit() else t, 0) * len(urls) for t, urls in (bonus_links or {}).items())
    thanks = normalize_thanks(draft.get("thanks_links") or [])
    total_bonus += sum(p for p, u in thanks)
    req_ok = fulfilled >= len(required_list) if required_list else True
    points_ok = total_bonus >= points_required
    can_submit = req_ok and points_ok

    if can_submit:
        color = discord.Color.green()
    elif fulfilled > 0 or total_bonus > 0:
        color = discord.Color.gold()
    else:
        color = discord.Color.from_rgb(128, 128, 128)

    points_bar_len = 10
    if points_required > 0:
        pct = min(100, int(100 * total_bonus / points_required))
        filled = int(points_bar_len * min(1.0, total_bonus / points_required))
        bar = "█" * filled + "░" * (points_bar_len - filled)
        points_progress = "[%s] %s/%s б. (%s%%)" % (bar, total_bonus, points_required, pct)
    else:
        points_progress = "%s б." % total_bonus
    bonus_status = "✓ хватает" if points_ok else "✗ ещё %s б." % (points_required - total_bonus)

    summary_parts = []
    summary_parts.append("Обязательные: **%s/%s** %s" % (fulfilled, len(required_list), "✓" if req_ok else "✗"))
    summary_parts.append("Баллы: **%s** %s" % (points_progress, "✓" if points_ok else "✗"))
    summary_parts.append("**Можно отправлять**" if can_submit else "Пока не готово")
    one_line = " · ".join(summary_parts)

    embed = discord.Embed(
        title="Добавьте ссылки по требованиям",
        description="**%s** · %s\n\n%s\n\nВыберите требование или тип баллов и добавьте ссылки." % (full_name, promotion_key, one_line),
        color=color,
    )
    embed.add_field(
        name="Баллы (автоподсчёт)",
        value="Нужно для звания: **%s** б. · Сейчас: **%s** б. · %s" % (points_required, total_bonus, bonus_status),
        inline=False,
    )
    lines = []
    for idx, req in enumerate(required_list, start=1):
        need = required_count_from_text(req)
        count = len(req_links.get(idx, []))
        ok = "✓" if count >= need else "✗ (нужно %s)" % need
        short = (req.split("→")[0] if "→" in req else req.split("->")[0]).strip()[:40]
        lines.append("**%s. %s** — %s ссылок %s" % (idx, short, count, ok))
    if lines:
        embed.add_field(name="Обязательные", value="\n".join(lines), inline=False)
    bonus_parts = []
    for t in _sort_int_like(bonus_links.keys()):
        urls = bonus_links[t]
        pts = ORLS_POINTS_MAP.get(int(t) if str(t).isdigit() else t, 0) * len(urls)
        bonus_parts.append("Тип %s: %s шт. = %s б." % (t, len(urls), pts))
    if bonus_parts:
        embed.add_field(name="Балловые", value="\n".join(bonus_parts) + "\n**Итого: %s б.**" % total_bonus, inline=False)
    thanks = normalize_thanks(draft.get("thanks_links") or [])
    if thanks:
        thanks_parts = ["%s б.: %s" % (p, u) for p, u in thanks]
        embed.add_field(name="Благодарности и поощрения", value="\n".join(thanks_parts) + "\n**Всего: %s б.**" % sum(p for p, u in thanks), inline=False)
    embed.set_footer(text='Когда всё добавлено — нажмите «Готово, отправить рапорт». Справка: кнопка «Как считаются баллы?»')
    return embed


class OrlsLinksModal(discord.ui.Modal, title="Ссылки"):
    def __init__(self, label: str, requirement_index: int | None, bonus_type: int | None, user_id: int):
        super().__init__(timeout=None)
        self.requirement_index = requirement_index
        self.bonus_type = bonus_type
        self.user_id = user_id
        if requirement_index is not None:
            placeholder = "По одной ссылке в строку."
        elif bonus_type is not None:
            placeholder = "Можно вставить много ссылок сразу — каждая с новой строки, все пойдут в выбранный тип."
            if "списком" in label:
                placeholder = "В каждой строке: номер типа 1-12 и ссылка. Пример: 8 https://..."
        else:
            placeholder = "По одной в строке."
        if len(placeholder) > 100:
            placeholder = placeholder[:97] + "..."
        self.links_field = discord.ui.TextInput(
            label=label[:45],
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=2000,
            placeholder=placeholder[:100],
        )
        self.add_item(self.links_field)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            if interaction.user and interaction.user.id != self.user_id:
                await interaction.response.send_message("❌ Это не ваш черновик.", ephemeral=True)
                return
            draft = orls_draft_reports.get(self.user_id)
            if not draft:
                draft = await get_worker().submit(load_orls_draft, self.user_id)
                if draft:
                    orls_draft_reports[self.user_id] = draft
            if not draft:
                await interaction.response.send_message("Сессия истекла. Начните рапорт заново или нажмите «Продолжить мой рапорт».", ephemeral=True)
                return
            raw = (self.links_field.value or "").strip()
            added = 0
            if self.requirement_index is not None:
                urls = [s.strip() for s in raw.splitlines() if s.strip() and (s.strip().startswith("http://") or s.strip().startswith("https://"))]
                draft.setdefault("requirement_links", {})[self.requirement_index] = draft.get("requirement_links", {}).get(self.requirement_index, []) + urls
                added = len(urls)
            elif self.bonus_type is not None:
                for line in raw.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(None, 1)
                    typ = self.bonus_type
                    rest = line
                    if len(parts) >= 2 and parts[0].isdigit():
                        n = int(parts[0])
                        if 1 <= n <= 12:
                            typ = n
                            rest = parts[1].strip()
                    if rest and (rest.startswith("http://") or rest.startswith("https://")):
                        draft.setdefault("bonus_links", {})[typ] = draft.get("bonus_links", {}).get(typ, []) + [rest]
                        added += 1
            ch_id = draft.get("channel_id")
            msg_id = draft.get("message_id")
            ephemeral_msg = draft.get("_ephemeral_msg")
            snapshot = {k: v for k, v in draft.items() if k != "_ephemeral_msg"}
            get_worker().submit_fire(save_orls_draft, self.user_id, snapshot)
            if not ephemeral_msg and ch_id and msg_id and interaction.guild:
                ch = None
                cache = getattr(state, "channel_cache", None)
                if cache:
                    ch = cache.get_channel(ch_id)
                if ch is None:
                    ch = interaction.guild.get_channel(ch_id)
                if ch:
                    try:
                        msg = await ch.fetch_message(msg_id)
                        await msg.edit(embed=_build_collector_embed(draft))
                    except Exception as e:
                        logger.warning("Не обновить сообщение сбора: %s", e)
            embed = _build_collector_embed(draft)
            view = OrlsCollectorView(draft.get("promotion_key", ""), self.user_id)
            await interaction.response.defer(ephemeral=True)
            content_full = "Добавлено ссылок: **%s**. Баллы пересчитаны. Ниже — актуальное состояние." % added
            if interaction.message:
                try:
                    await interaction.message.edit(content=content_full, embed=embed, view=view)
                except Exception:
                    await interaction.followup.send(content=content_full, embed=embed, view=view, ephemeral=True)
            else:
                await interaction.followup.send("Добавлено ссылок: **%s**. Закройте это уведомление. Состояние обновится при следующем действии в сборщике." % added, ephemeral=True)
        except Exception as e:
            logger.error("Ошибка OrlsLinksModal: %s", e, exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("Ошибка.", ephemeral=True)


class OrlsThanksModal(discord.ui.Modal, title="Благодарности и поощрения (ОРЛС)"):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.links_field = discord.ui.TextInput(
            label="Баллы и ссылки",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=2000,
            placeholder="В каждой строке: баллы и ссылка. Пример: 10 https://...",
        )
        self.add_item(self.links_field)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            if interaction.user and interaction.user.id != self.user_id:
                await interaction.response.send_message("❌ Это не ваш черновик.", ephemeral=True)
                return
            draft = orls_draft_reports.get(self.user_id)
            if not draft:
                draft = await get_worker().submit(load_orls_draft, self.user_id)
                if draft:
                    orls_draft_reports[self.user_id] = draft
            if not draft:
                await interaction.response.send_message("Сессия истекла. Начните рапорт заново.", ephemeral=True)
                return
            raw = (self.links_field.value or "").strip()
            if raw:
                draft["thanks_links"] = parse_thanks_lines(raw)
            else:
                draft["thanks_links"] = []
            snapshot = {k: v for k, v in draft.items() if k != "_ephemeral_msg"}
            get_worker().submit_fire(save_orls_draft, self.user_id, snapshot)
            embed = _build_collector_embed(draft)
            view = OrlsCollectorView(draft.get("promotion_key", ""), self.user_id)
            await interaction.response.defer(ephemeral=True)
            content_full = "Благодарности сохранены. Ниже — актуальное состояние."
            if interaction.message:
                try:
                    await interaction.message.edit(content=content_full, embed=embed, view=view)
                except Exception:
                    await interaction.followup.send(content=content_full, embed=embed, view=view, ephemeral=True)
            else:
                await interaction.followup.send("Благодарности сохранены. Закройте это уведомление. Состояние обновится при следующем действии в сборщике.", ephemeral=True)
        except Exception as e:
            logger.error("Ошибка OrlsThanksModal: %s", e, exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("Ошибка.", ephemeral=True)


async def _do_submit_report(draft: dict, interaction: discord.Interaction) -> None:
    """Отправка рапорта и создание ветки."""
    ch = None
    if interaction.guild:
        ch_id = draft.get("channel_id")
        if ch_id:
            cache = getattr(state, "channel_cache", None)
            if cache:
                ch = cache.get_channel(ch_id)
            if ch is None:
                ch = interaction.guild.get_channel(ch_id)
    if not ch or not isinstance(ch, discord.TextChannel):
        await interaction.followup.send("Канал не найден.", ephemeral=True)
        return
    try:
        user_id_int = int(draft.get("discord_id", 0))
    except (TypeError, ValueError):
        await interaction.followup.send("Некорректные данные.", ephemeral=True)
        return
    full_name = draft.get("full_name", "—")
    promotion_key = draft.get("promotion_key", "")
    passport = draft.get("passport", "—")
    requirement_links = draft.get("requirement_links") or {}
    bonus_links = draft.get("bonus_links") or {}
    info = PROMOTION_REQUIREMENTS_ORLS.get(promotion_key, {})
    required_list = info.get("required", [])
    points_required = info.get("points", 0)
    embed = discord.Embed(title=EmbedTitles.PROMOTION, color=discord.Color.gold(), description="Рапорт на повышение в ОРЛС\n\n👤 %s | %s\nDiscord: <@%s> (%s)" % (full_name, promotion_key, user_id_int, user_id_int), timestamp=interaction.created_at)
    embed.add_field(name=FieldNames.FULL_NAME, value=full_name, inline=False)
    embed.add_field(name=FieldNames.NEW_RANK, value=promotion_key, inline=True)
    embed.add_field(name="Паспорт", value=passport, inline=True)
    if points_required:
        embed.add_field(name="Необходимые баллы", value=str(points_required), inline=False)
    embed.add_field(name=FieldNames.STATUS, value=StatusValues.PENDING, inline=True)
    embed.set_footer(text=interaction.user.display_name if interaction.user else "", icon_url=getattr(interaction.user.display_avatar, "url", None) if interaction.user else None)
    from views.promotion_view import PromotionView
    view = PromotionView(user_id=user_id_int, new_rank=promotion_key, full_name=full_name, message_id=0)
    message = await ch.send(embed=embed, view=view)
    promo_request = PromotionRequest(discord_id=user_id_int, full_name=full_name, new_rank=promotion_key, message_link=message.jump_url)
    active_promotion_requests[message.id] = promo_request.to_dict()
    get_worker().submit_fire(save_request, "promotion_requests", message.id, promo_request.to_dict())
    view.message_id = message.id
    try:
        await message.edit(view=view)
    except Exception as e:
        logger.warning("Не обновить view рапорта: %s", e)
    cid, mid = draft.get("channel_id"), draft.get("message_id")
    if cid and mid and interaction.guild:
        try:
            coll_ch = None
            cache = getattr(state, "channel_cache", None)
            if cache:
                coll_ch = cache.get_channel(cid)
            if coll_ch is None:
                coll_ch = interaction.guild.get_channel(cid)
            if coll_ch:
                msg = await coll_ch.fetch_message(mid)
                await msg.delete()
        except Exception as err:
            logger.warning("Не удалить сообщение-сборщик: %s", err)
    try:
        thread = await message.create_thread(name="ОРЛС • %s • %s" % (full_name[:80], promotion_key[:30]))
    except discord.HTTPException:
        thread = getattr(message, "thread", None)
        if not thread and interaction.guild:
            try:
                refetched = await ch.fetch_message(message.id)
                thread = getattr(refetched, "thread", None)
            except Exception:
                pass
    thanks_links = normalize_thanks(draft.get("thanks_links") or [])
    if thread and (required_list or requirement_links or bonus_links or thanks_links):
        intro = discord.Embed(
            title="📋 Рапорт на повышение ОРЛС",
            description=(
                "**%s**\n"
                "Повышение: **%s**\n"
                "Порог баллов: **%s**"
            ) % (full_name, promotion_key, points_required),
            color=discord.Color.blue(),
        )
        intro.set_footer(text="Ниже — обязательные требования и балловые ссылки.")
        await thread.send(embed=intro)
        header = "**📌 Обязательные требования** (%s баллов для звания)\n" % points_required
        fulfilled = 0
        blocks = []
        for idx, req in enumerate(required_list, start=1):
            need = required_count_from_text(req)
            urls = requirement_links.get(idx, [])
            count = len(urls)
            ok = count >= need
            if ok:
                fulfilled += 1
            icon = "✅" if ok else "❌"
            status = "" if ok else " (нужно ещё %s)" % need
            lines = ["%s **%s.** %s — %s ссылок%s" % (icon, idx, req, count, status)]
            lines += ["   └ %s. %s" % (i, u) for i, u in enumerate(urls, start=1)] if urls else ["   └ ссылок нет"]
            blocks.append("\n".join(lines))
        body = "**Подсчёт:** %s/%s выполнено\n\n" % (fulfilled, len(required_list)) + "\n".join(blocks)
        await send_long(thread, body, header)
    if thread and bonus_links:
        type_names = {int(typ): name for typ, name in ORLS_BONUS_LABELS}
        total_bonus = 0
        for t in _sort_int_like(bonus_links.keys()):
            urls = bonus_links[t]
            total_bonus += ORLS_POINTS_MAP.get(int(t) if str(t).isdigit() else t, 0) * len(urls)
        total_bonus += sum(p for p, u in thanks_links)
        if bonus_links:
            # Ветка: по каждому типу — название и список ссылок (как в ОСБ/ГРОМ/ППС)
            body_parts = []
            for t in _sort_int_like(bonus_links.keys()):
                urls = bonus_links[t]
                label = type_names.get(int(t) if str(t).isdigit() else t, "Тип %s" % t)
                body_parts.append("**%s**: %s шт.\n%s" % (label, len(urls), "\n".join(urls) if urls else "—"))
            if body_parts:
                body_text = "\n\n".join(body_parts)
                await send_long(thread, body_text, header="**📎 Балловые ссылки**\n")
            detail_parts = []
            for t in _sort_int_like(bonus_links.keys()):
                cnt = len(bonus_links[t])
                pts = ORLS_POINTS_MAP.get(int(t) if str(t).isdigit() else t, 0) * cnt
                label = type_names.get(int(t) if str(t).isdigit() else t, "Тип %s" % t)
                detail_parts.append("**%s**: %s шт. → **%s** б." % (label, cnt, pts))
            summary_embed = discord.Embed(
                title="📊 Подсчёт баллов",
                color=discord.Color.gold(),
                description="\n".join(detail_parts) + "\n\n**Итого: %s б.**" % total_bonus,
            )
            enough = total_bonus >= points_required
            summary_embed.add_field(
                name="Порог для звания",
                value="%s б." % points_required,
                inline=True,
            )
            summary_embed.add_field(
                name="Набрано",
                value="%s б." % total_bonus,
                inline=True,
            )
            summary_embed.add_field(
                name="Статус",
                value="✅ Достаточно" if enough else "❌ Не хватает (%s б.)" % (points_required - total_bonus),
                inline=True,
            )
            await thread.send(embed=summary_embed)
        help_embed = discord.Embed(
            title="📖 Справка по баллам ОРЛС",
            description=ORLS_POINTS_TEXT,
            color=discord.Color.dark_grey(),
        )
        await thread.send(embed=help_embed)
    if thread and thanks_links:
        header_thanks = "**🙏 Благодарности и поощрения от начальства**\n"
        body_thanks = "\n".join("%s б.: %s" % (p, u) for p, u in thanks_links)
        await send_long(thread, body_thanks, header_thanks)
    if thread and not bonus_links:
        help_embed = discord.Embed(
            title="📖 Справка по баллам ОРЛС",
            description=ORLS_POINTS_TEXT,
            color=discord.Color.dark_grey(),
        )
        await thread.send(embed=help_embed)
    await interaction.followup.send("Рапорт отправлен. Ветка со ссылками создана.", ephemeral=True)
    logger.info("Рапорт ОРЛС отправлен: user_id=%s, msg_id=%s", user_id_int, message.id)


class OrlsConfirmSubmitView(View):
    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id
        yes_btn = discord.ui.Button(label="Да, отправить", style=discord.ButtonStyle.danger, custom_id="orls_confirm_yes")
        yes_btn.callback = self._cb_yes
        no_btn = discord.ui.Button(label="Нет, вернуться", style=discord.ButtonStyle.secondary, custom_id="orls_confirm_no")
        no_btn.callback = self._cb_no
        self.add_item(yes_btn)
        self.add_item(no_btn)

    async def _cb_yes(self, interaction: discord.Interaction):
        if interaction.user and interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Это не ваш черновик.", ephemeral=True)
            return
        draft = orls_draft_reports.pop(self.user_id, None)
        if not draft:
            draft = await get_worker().submit(load_orls_draft, self.user_id)
        if not draft:
            await interaction.response.send_message("Сессия истекла. Начните рапорт заново.", ephemeral=True)
            return
        get_worker().submit_fire(delete_orls_draft, self.user_id)
        await interaction.response.defer(ephemeral=True)
        await _do_submit_report(draft, interaction)

    async def _cb_no(self, interaction: discord.Interaction):
        await interaction.response.send_message("Добавьте ещё ссылок и нажмите «Готово» снова.", ephemeral=True)


def _build_remove_link_options(draft: dict, promotion_key: str, max_options: int = 25):
    req_links = draft.get("requirement_links") or {}
    bonus_links = draft.get("bonus_links") or {}
    thanks_links = normalize_thanks(draft.get("thanks_links") or [])
    info = PROMOTION_REQUIREMENTS_ORLS.get(promotion_key, {})
    req_list = info.get("required", [])
    options = []
    for idx in _sort_int_like(req_links.keys()):
        urls = req_links[idx]
        i = int(idx) if str(idx).isdigit() else idx
        short = (req_list[i - 1].split("→")[0] if i <= len(req_list) else "Пункт %s" % idx).strip()[:30]
        for i, u in enumerate(urls):
            if len(options) >= max_options:
                return options
            label = "Обяз. %s: %s…" % (idx, (u[:40] + "…") if len(u) > 40 else u)
            options.append((label[:100], "r_%s_%s" % (idx, i)))
    type_names = {1:"Собесед.",2:"Рапорты",3:"Заявка",4:"Звонок",5:"Док.",6:"Патруль",7:"Трен.",8:"Лекция",9:"Присяга",10:"Экзамен",11:"Строй",12:"Переатт."}
    for t in _sort_int_like(bonus_links.keys()):
        urls = bonus_links[t]
        tn = type_names.get(int(t) if str(t).isdigit() else t, "Тип %s" % t)
        for i, u in enumerate(urls):
            if len(options) >= max_options:
                return options
            label = "Баллы %s (%s): %s…" % (t, tn, (u[:35] + "…") if len(u) > 35 else u)
            options.append((label[:100], "b_%s_%s" % (t, i)))
    for i, (p, u) in enumerate(thanks_links):
        if len(options) >= max_options:
            return options
        label = "Благод. %s б.: %s…" % (p, (u[:40] + "…") if len(u) > 40 else u)
        options.append((label[:100], "t_%s" % i))
    return options


class OrlsRemoveLinkView(View):
    """Одноразовый селект: выбор ссылки для удаления."""

    def __init__(self, owner_id: int, options: list):
        super().__init__(timeout=60)
        self.owner_id = owner_id
        if not options:
            return
        select_opts = [discord.SelectOption(label=l, value=v) for l, v in options]
        sel = discord.ui.Select(placeholder="Выберите ссылку для удаления", min_values=1, max_values=1, options=select_opts, custom_id="orls_remove_sel")
        sel.callback = self._cb_remove
        self.add_item(sel)

    async def _cb_remove(self, interaction: discord.Interaction):
        if not interaction.user:
            return
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Это не ваш черновик.", ephemeral=True)
            return
        owner_id = self.owner_id
        vals = interaction.data.get("values", []) if interaction.data else []
        if not vals:
            await interaction.response.send_message("Ничего не выбрано.", ephemeral=True)
            return
        value = vals[0]
        draft = orls_draft_reports.get(owner_id)
        if not draft:
            draft = await get_worker().submit(load_orls_draft, owner_id)
            if draft:
                orls_draft_reports[owner_id] = draft
        if not draft:
            await interaction.response.send_message("Сессия истекла. Нажмите «Продолжить мой рапорт» и попробуйте снова.", ephemeral=True)
            return
        parts = value.split("_")
        if len(parts) < 2:
            await interaction.response.send_message("Ошибка формата.", ephemeral=True)
            return
        try:
            kind = parts[0]
            if kind == "t":
                idx = int(parts[1])
                thanks = normalize_thanks(draft.get("thanks_links") or [])
                if 0 <= idx < len(thanks):
                    thanks.pop(idx)
                    draft["thanks_links"] = thanks
            else:
                if len(parts) != 3:
                    await interaction.response.send_message("Ошибка формата.", ephemeral=True)
                    return
                first, second = int(parts[1]), int(parts[2])
                if kind == "r":
                    req = draft.get("requirement_links") or {}
                    key_r = first if first in req else (str(first) if str(first) in req else None)
                    if key_r is not None and 0 <= second < len(req[key_r]):
                        req[key_r].pop(second)
                        if not req[key_r]:
                            del req[key_r]
                elif kind == "b":
                    bonus = draft.get("bonus_links") or {}
                    key_b = first if first in bonus else (str(first) if str(first) in bonus else None)
                    if key_b is not None and 0 <= second < len(bonus[key_b]):
                        bonus[key_b].pop(second)
                        if not bonus[key_b]:
                            del bonus[key_b]
                else:
                    await interaction.response.send_message("Ошибка формата.", ephemeral=True)
                    return
        except (ValueError, IndexError):
            await interaction.response.send_message("Ошибка формата.", ephemeral=True)
            return
        cid, mid = draft.get("channel_id"), draft.get("message_id")
        ephemeral_msg = draft.get("_ephemeral_msg")
        snapshot = {k: v for k, v in draft.items() if k != "_ephemeral_msg"}
        get_worker().submit_fire(save_orls_draft, owner_id, snapshot)
        if not ephemeral_msg and cid and mid and interaction.guild:
            try:
                ch = None
                cache = getattr(state, "channel_cache", None)
                if cache:
                    ch = cache.get_channel(cid)
                if ch is None:
                    ch = interaction.guild.get_channel(cid)
                if ch:
                    msg = await ch.fetch_message(mid)
                    await msg.edit(embed=_build_collector_embed(draft))
            except Exception as e:
                logger.warning("Не обновить сообщение после удаления ссылки: %s", e)
        embed = _build_collector_embed(draft)
        view = OrlsCollectorView(draft.get("promotion_key", ""), owner_id)
        await interaction.response.defer(ephemeral=True)
        content_full = "Ссылка удалена. Ниже — актуальное состояние."
        if interaction.message:
            try:
                await interaction.message.edit(content=content_full, embed=embed, view=view)
            except Exception:
                await interaction.followup.send(content=content_full, embed=embed, view=view, ephemeral=True)
        else:
            await interaction.followup.send("Ссылка удалена. Закройте это уведомление. Состояние обновится при следующем действии в сборщике.", ephemeral=True)


class OrlsCollectorView(View):
    def __init__(self, promotion_key: str, owner_id: int):
        super().__init__(timeout=604800)
        self.promotion_key = promotion_key
        self.owner_id = owner_id
        info = PROMOTION_REQUIREMENTS_ORLS.get(promotion_key, {})
        req_list = info.get("required", [])
        req_opts = [discord.SelectOption(label=("%s. %s" % (i, (r.split("→")[0] if "→" in r else r.split("->")[0]).strip()[:80])), value=str(i), description="Добавить ссылки") for i, r in enumerate(req_list, start=1)]
        self.req_select = discord.ui.Select(placeholder="Добавить ссылки по требованию", min_values=1, max_values=1, options=req_opts, custom_id="orls_req_sel")
        self.req_select.callback = self._cb_req
        self.add_item(self.req_select)
        bonus_opts = [discord.SelectOption(label=f"{t}. {n}", value=str(t)) for t, n in [(1,"Собеседование (60)"),(2,"Рапорты (10)"),(3,"Заявка (10)"),(4,"Звонок (10)"),(5,"Документы (10)"),(6,"Патруль (30)"),(7,"Тренировка (35)"),(8,"Лекция (40)"),(9,"Присяга (10)"),(10,"Экзамен (35)"),(11,"Строевая (40)"),(12,"Переаттестация (40)")]]
        self.bonus_select = discord.ui.Select(placeholder="Добавить балловые ссылки", min_values=1, max_values=1, options=bonus_opts, custom_id="orls_bonus_sel")
        self.bonus_select.callback = self._cb_bonus
        self.add_item(self.bonus_select)
        bulk_btn = discord.ui.Button(label="Баллы: вставить списком", style=discord.ButtonStyle.primary, custom_id="orls_bonus_bulk")
        bulk_btn.callback = self._cb_bonus_bulk
        self.add_item(bulk_btn)
        done_btn = discord.ui.Button(label="Готово, отправить рапорт", style=discord.ButtonStyle.success, custom_id="orls_done")
        done_btn.callback = self._cb_done
        self.add_item(done_btn)
        thanks_btn = discord.ui.Button(label="Благодарности и поощрения", style=discord.ButtonStyle.secondary, custom_id="orls_thanks")
        thanks_btn.callback = self._cb_thanks
        self.add_item(thanks_btn)
        help_btn = discord.ui.Button(label="Как считаются баллы?", style=discord.ButtonStyle.secondary, custom_id="orls_help_points")
        help_btn.callback = self._cb_help_points
        self.add_item(help_btn)
        remove_btn = discord.ui.Button(label="Удалить ссылку", style=discord.ButtonStyle.danger, custom_id="orls_remove_link")
        remove_btn.callback = self._cb_remove_link
        self.add_item(remove_btn)

    async def _cb_req(self, interaction: discord.Interaction):
        if not interaction.user:
            return
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Это не ваш черновик.", ephemeral=True)
            return
        owner_id = interaction.user.id
        draft = orls_draft_reports.get(owner_id)
        if not draft:
            draft = await get_worker().submit(load_orls_draft, owner_id)
            if draft:
                orls_draft_reports[owner_id] = draft
        if not draft:
            await interaction.response.send_message("Черновик не найден. Начните рапорт заново через «Подать рапорт».", ephemeral=True)
            return
        draft["_ephemeral_msg"] = interaction.message
        vals = interaction.data.get("values", []) if interaction.data else []
        idx = int(vals[0]) if vals else 1
        info = PROMOTION_REQUIREMENTS_ORLS.get(draft.get("promotion_key", ""), {})
        reqs = info.get("required", [])
        label = reqs[idx - 1] if idx <= len(reqs) else "Требование %s" % idx
        await interaction.response.send_modal(OrlsLinksModal(label, requirement_index=idx, bonus_type=None, user_id=interaction.user.id))

    async def _cb_bonus(self, interaction: discord.Interaction):
        if not interaction.user:
            return
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Это не ваш черновик.", ephemeral=True)
            return
        owner_id = interaction.user.id
        draft = orls_draft_reports.get(owner_id)
        if not draft:
            draft = await get_worker().submit(load_orls_draft, owner_id)
            if draft:
                orls_draft_reports[owner_id] = draft
        if not draft:
            await interaction.response.send_message("Черновик не найден. Начните рапорт заново через «Подать рапорт».", ephemeral=True)
            return
        draft["_ephemeral_msg"] = interaction.message
        vals = interaction.data.get("values", []) if interaction.data else []
        t = int(vals[0]) if vals else 1
        await interaction.response.send_modal(OrlsLinksModal("Баллы: тип %s" % t, requirement_index=None, bonus_type=t, user_id=interaction.user.id))

    async def _cb_bonus_bulk(self, interaction: discord.Interaction):
        """Одно поле: в каждой строке «номер типа 1-12» и ссылка. Без номера — тип 1."""
        if not interaction.user:
            return
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Это не ваш черновик.", ephemeral=True)
            return
        owner_id = interaction.user.id
        draft = orls_draft_reports.get(owner_id)
        if not draft:
            draft = await get_worker().submit(load_orls_draft, owner_id)
            if draft:
                orls_draft_reports[owner_id] = draft
        if not draft:
            await interaction.response.send_message("Черновик не найден. Начните рапорт заново через «Подать рапорт».", ephemeral=True)
            return
        draft["_ephemeral_msg"] = interaction.message
        await interaction.response.send_modal(OrlsLinksModal(
            "Баллы: вставьте списком (в строке: тип и ссылка)",
            requirement_index=None,
            bonus_type=1,
            user_id=interaction.user.id,
        ))

    async def _cb_help_points(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Как считаются баллы", description="ОРЛС", color=discord.Color.blue())
        for name, value in ORLS_POINTS_FIELDS:
            embed.add_field(name=name, value=value, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _cb_thanks(self, interaction: discord.Interaction):
        if not interaction.user or interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Это не ваш черновик.", ephemeral=True)
            return
        draft = orls_draft_reports.get(self.owner_id)
        if not draft:
            draft = await get_worker().submit(load_orls_draft, self.owner_id)
            if draft:
                orls_draft_reports[self.owner_id] = draft
        if not draft:
            await interaction.response.send_message("Черновик не найден.", ephemeral=True)
            return
        await interaction.response.send_modal(OrlsThanksModal(user_id=self.owner_id))

    async def _cb_remove_link(self, interaction: discord.Interaction):
        if not interaction.user:
            return
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Это не ваш черновик.", ephemeral=True)
            return
        owner_id = interaction.user.id
        draft = orls_draft_reports.get(owner_id)
        if not draft:
            draft = await get_worker().submit(load_orls_draft, owner_id)
            if draft:
                orls_draft_reports[owner_id] = draft
        if not draft:
            await interaction.response.send_message("Черновик не найден. Начните рапорт заново через «Подать рапорт».", ephemeral=True)
            return
        draft["_ephemeral_msg"] = interaction.message
        options = _build_remove_link_options(draft, draft.get("promotion_key", ""))
        if not options:
            await interaction.response.send_message("Нет добавленных ссылок для удаления.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Выберите ссылку, которую нужно удалить:",
            view=OrlsRemoveLinkView(owner_id, options),
            ephemeral=True,
        )

    async def _cb_done(self, interaction: discord.Interaction):
        uid = interaction.user.id if interaction.user else 0
        if not uid:
            return
        if uid != self.owner_id:
            await interaction.response.send_message("❌ Это не ваш черновик.", ephemeral=True)
            return
        draft = orls_draft_reports.get(uid)
        if not draft:
            draft = await get_worker().submit(load_orls_draft, uid)
            if draft:
                orls_draft_reports[uid] = draft
        if not draft:
            await interaction.response.send_message("Черновик не найден. Начните заново через «Подать рапорт».", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        info = PROMOTION_REQUIREMENTS_ORLS.get(draft.get("promotion_key", ""), {})
        required_list = info.get("required", [])
        points_required = info.get("points", 0)
        req_links = draft.get("requirement_links") or {}
        bonus_links = draft.get("bonus_links") or {}
        fulfilled = 0
        for idx, req in enumerate(required_list, start=1):
            if len(req_links.get(idx, [])) >= required_count_from_text(req):
                fulfilled += 1
        total_bonus = sum(ORLS_POINTS_MAP.get(int(t) if str(t).isdigit() else t, 0) * len(urls) for t, urls in bonus_links.items())
        thanks = normalize_thanks(draft.get("thanks_links") or [])
        total_bonus += sum(p for p, u in thanks)
        req_ok = fulfilled >= len(required_list) if required_list else True
        points_ok = total_bonus >= points_required
        if req_ok and points_ok:
            orls_draft_reports.pop(uid, None)
            get_worker().submit_fire(delete_orls_draft, uid)
            await _do_submit_report(draft, interaction)
        else:
            missing = []
            if not req_ok:
                missing.append("обязательные %s/%s" % (fulfilled, len(required_list)))
            if not points_ok:
                missing.append("баллов %s/%s" % (total_bonus, points_required))
            await interaction.followup.send(
                "Не выполнено: " + ", ".join(missing) + ". Всё равно отправить?",
                view=OrlsConfirmSubmitView(uid),
                ephemeral=True,
            )


class OrlsPromotionModal(discord.ui.Modal, title="Рапорт на повышение ОРЛС"):
    """Первая модалка: ФИО, Discord ID, паспорт. Подставляются последние данные и ID пользователя."""

    def __init__(self, promotion_key: str, user_id: int | None = None):
        super().__init__(timeout=None)
        self.promotion_key = promotion_key
        last = orls_last_user_data.get(user_id or 0) or {}
        discord_default = str(user_id) if user_id else ""
        self.full_name = discord.ui.TextInput(
            label="Имя Фамилия",
            max_length=Config.MAX_NAME_LENGTH,
            required=True,
            default=last.get("full_name", "")[:Config.MAX_NAME_LENGTH],
        )
        self.discord_id = discord.ui.TextInput(
            label="Discord ID",
            max_length=32,
            required=True,
            placeholder="Числовой ID",
            default=last.get("discord_id") or discord_default,
        )
        self.passport = discord.ui.TextInput(
            label="Номер паспорта",
            max_length=Config.STATIC_ID_LENGTH,
            required=True,
            default=last.get("passport", "")[:Config.STATIC_ID_LENGTH],
        )
        self.add_item(self.full_name)
        self.add_item(self.discord_id)
        self.add_item(self.passport)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            if isinstance(interaction.user, discord.Member) and interaction.guild:
                dept_role_id = get_dept_role_id("orls")
                role = None
                role_cache = getattr(state, "role_cache", None)
                if role_cache and dept_role_id:
                    role = await role_cache.get_role(interaction.guild.id, dept_role_id)
                if role is None and dept_role_id:
                    role = interaction.guild.get_role(dept_role_id) if interaction.guild else None
                if role and role not in interaction.user.roles:
                    await interaction.response.send_message(
                        "❌ Подать рапорт на повышение ОРЛС может только сотрудник отдела ОРЛС.",
                        ephemeral=True,
                    )
                    return
            if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
                await interaction.response.send_message("Рапорт можно подать только в текстовом канале.", ephemeral=True)
                return
            if isinstance(Config.PROMOTION_CHANNELS, dict) and interaction.channel.id not in Config.PROMOTION_CHANNELS:
                await interaction.response.send_message("Этот канал не для рапортов ОРЛС.", ephemeral=True)
                return
            try:
                user_id = int(str(self.discord_id.value).strip())
            except ValueError:
                await interaction.response.send_message("Некорректный Discord ID.", ephemeral=True)
                return
            draft = {
                "channel_id": interaction.channel.id,
                "promotion_key": self.promotion_key,
                "full_name": self.full_name.value.strip(),
                "discord_id": str(user_id),
                "passport": self.passport.value.strip(),
                "requirement_links": {},
                "bonus_links": {},
                "thanks_links": [],
            }
            collector_embed = _build_collector_embed(draft)
            collector_view = OrlsCollectorView(self.promotion_key, interaction.user.id)
            await interaction.response.send_message(
                content="Данные приняты. Добавляйте ссылки и нажмите «Готово, отправить рапорт».",
                embed=collector_embed,
                view=collector_view,
                ephemeral=True,
            )
            draft["message_id"] = None
            draft["channel_id"] = interaction.channel.id
            orls_draft_reports[interaction.user.id] = draft
            snapshot = {k: v for k, v in draft.items() if k != "_ephemeral_msg"}
            get_worker().submit_fire(save_orls_draft, interaction.user.id, snapshot)
            orls_last_user_data[interaction.user.id] = {
                "full_name": draft["full_name"],
                "discord_id": draft["discord_id"],
                "passport": draft["passport"],
            }
        except Exception as e:
            logger.error("Ошибка OrlsPromotionModal: %s", e, exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("Ошибка при отправке.", ephemeral=True)


class OrlsPromotionSelect(Select):
    def __init__(self):
        options = [discord.SelectOption(label=key, value=key, description="Баллы: %s" % info["points"]) for key, info in PROMOTION_REQUIREMENTS_ORLS.items()]
        super().__init__(placeholder="Выберите повышение ОРЛС", min_values=1, max_values=1, options=options, custom_id="orls_promotion_select")

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            if isinstance(interaction.user, discord.Member) and interaction.guild:
                dept_role_id = get_dept_role_id("orls")
                role = None
                role_cache = getattr(state, "role_cache", None)
                if role_cache and dept_role_id:
                    role = await role_cache.get_role(interaction.guild.id, dept_role_id)
                if role is None and dept_role_id:
                    role = interaction.guild.get_role(dept_role_id) if interaction.guild else None
                if role and role not in interaction.user.roles:
                    await interaction.response.send_message(
                        "❌ Подать рапорт на повышение ОРЛС может только сотрудник отдела ОРЛС.",
                        ephemeral=True,
                    )
                    return
            promotion_key = self.values[0]
            if not is_promotion_key_allowed_for_member(interaction.user, promotion_key):
                current = get_member_rank_display(interaction.user) or "не определено"
                await interaction.response.send_message(
                    "Рапорт можно подать только на следующее звание. Ваше текущее звание: **%s**. Выберите повышение, соответствующее вашему званию." % current,
                    ephemeral=True,
                )
                return
            user_id = interaction.user.id if interaction.user else None
            await interaction.response.send_modal(OrlsPromotionModal(promotion_key=promotion_key, user_id=user_id))
        except Exception as e:
            logger.error("Ошибка открытия модала ОРЛС: %s", e, exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send("Ошибка.", ephemeral=True)
            else:
                await interaction.response.send_message("Ошибка.", ephemeral=True)


class OrlsPromotionApplyView(View):
    timeout = None

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(OrlsPromotionSelect())
        resume_btn = discord.ui.Button(label="Продолжить мой рапорт", style=discord.ButtonStyle.secondary, custom_id="orls_resume_draft")
        resume_btn.callback = self._cb_resume_draft
        self.add_item(resume_btn)

    async def _cb_resume_draft(self, interaction: discord.Interaction):
        if not interaction.user:
            return
        if isinstance(interaction.user, discord.Member) and interaction.guild:
            dept_role_id = get_dept_role_id("orls")
            role = None
            role_cache = getattr(state, "role_cache", None)
            if role_cache and dept_role_id:
                role = await role_cache.get_role(interaction.guild.id, dept_role_id)
            if role is None and dept_role_id:
                role = interaction.guild.get_role(dept_role_id)
            if role and role not in interaction.user.roles:
                await interaction.response.send_message(
                    "❌ Продолжить рапорт ОРЛС может только сотрудник отдела ОРЛС.",
                    ephemeral=True,
                )
                return
        uid = interaction.user.id
        draft = orls_draft_reports.get(uid)
        if not draft:
            draft = await get_worker().submit(load_orls_draft, uid)
        if not draft:
            await interaction.response.send_message("У вас нет черновика рапорта. Выберите повышение выше, чтобы начать новый рапорт.", ephemeral=True)
            return
        orls_draft_reports[uid] = draft
        promotion_key = draft.get("promotion_key", "")
        collector_embed = _build_collector_embed(draft)
        collector_view = OrlsCollectorView(promotion_key, uid)
        await interaction.response.send_message(embed=collector_embed, view=collector_view, ephemeral=True)

