import asyncio
import discord
from config import Config
import state
from database import (
    load_all_requests,
    load_all_firing_requests,
    load_all_promotion_requests,
    load_all_warehouse_requests,
    load_all_department_transfer_requests,
)

try:
    from services.action_locks import locks_count
except Exception:
    def locks_count() -> int:
        return -1


def _ok(v: bool) -> str:
    return "✅" if v else "❌"


def _safe_name(obj, fallback: str) -> str:
    try:
        return getattr(obj, "name", fallback)
    except Exception:
        return fallback


def _check_channel(guild: discord.Guild, channel_id: int, title: str):
    if not channel_id:
        return f"❌ {title}: ID не задан"

    # Канал через кэш, если он инициализирован
    ch = None
    cache = getattr(state, "channel_cache", None)
    if cache is not None:
        ch = cache.get_channel(int(channel_id))
    if ch is None:
        ch = guild.get_channel(int(channel_id))
    if not ch:
        return f"❌ {title}: канал не найден ({channel_id})"

    me = guild.me or guild.get_member(guild._state.user.id)
    perms = ch.permissions_for(me)
    perms_ok = perms.view_channel and getattr(perms, "send_messages", True) and perms.read_message_history

    if perms_ok:
        return f"✅ {title}: #{_safe_name(ch, 'канал')} ({channel_id})"
    return f"⚠️ {title}: #{_safe_name(ch, 'канал')} ({channel_id}) — не хватает прав"


def _check_role(guild: discord.Guild, role_id: int, title: str, bot_top_role: discord.Role | None):
    if not role_id:
        return f"❌ {title}: ID не задан"

    role = guild.get_role(int(role_id))
    if not role:
        return f"❌ {title}: роль не найдена ({role_id})"

    if bot_top_role and role >= bot_top_role:
        return f"⚠️ {title}: {role.name} ({role_id}) — выше/равна роли бота"

    return f"✅ {title}: {role.name} ({role_id})"


def _state_counts():
    return {
        "Заявки": len(getattr(state, "active_requests", {}) or {}),
        "Увольнения": len(getattr(state, "active_firing_requests", {}) or {}),
        "Повышения": len(getattr(state, "active_promotion_requests", {}) or {}),
        "Склад": len(getattr(state, "warehouse_requests", {}) or {}),
        "Переводы": len(getattr(state, "active_department_transfers", {}) or {}),
    }


def _db_counts():
    req = load_all_requests()
    fir = load_all_firing_requests()
    pro = load_all_promotion_requests()
    wh = load_all_warehouse_requests()
    dept = load_all_department_transfer_requests()
    return {
        "Заявки": len(req),
        "Увольнения": len(fir),
        "Повышения": len(pro),
        "Склад": len(wh),
        "Переводы": len(dept),
    }


def _format_counts(data: dict) -> str:
    return "\n".join([f"• {k}: **{v}**" for k, v in data.items()])


def _truncate_lines(lines: list[str], limit: int = 1000) -> str:
    out = []
    total = 0
    for line in lines:
        add = len(line) + 1
        if total + add > limit:
            out.append("…")
            break
        out.append(line)
        total += add
    return "\n".join(out) if out else "—"


def _service_status_lines() -> list[str]:
    lines = []

    # Фоновые задачи (если ты уже добавил background_tasks в main.py)
    bg_tasks = getattr(state, "background_tasks", None)
    if isinstance(bg_tasks, dict):
        alive = 0
        dead = 0
        names = []
        for name, task in bg_tasks.items():
            try:
                is_alive = task is not None and not task.done()
            except Exception:
                is_alive = False

            if is_alive:
                alive += 1
                names.append(f"✅ {name}")
            else:
                dead += 1
                names.append(f"⚠️ {name}")

        lines.append(f"Фоновые задачи: **{alive}** активных / **{dead}** завершённых")
        if names:
            lines.extend(names[:6])  # чтобы не раздувать embed
    else:
        lines.append("Фоновые задачи: ⚠️ state.background_tasks не инициализирован")

    # Локи действий
    try:
        lc = locks_count()
        if lc >= 0:
            lines.append(f"Локи action_locks: **{lc}**")
        else:
            lines.append("Локи action_locks: ⚠️ недоступно")
    except Exception:
        lines.append("Локи action_locks: ❌ ошибка чтения")

    return lines


async def build_diag_embed(bot: discord.Client) -> discord.Embed:
    guild = bot.get_guild(Config.GUILD_ID)

    embed = discord.Embed(
        title="🩺 Диагностика бота УВД",
        color=discord.Color.blue()
    )

    if not guild:
        embed.color = discord.Color.red()
        embed.description = f"❌ Сервер не найден по GUILD_ID={Config.GUILD_ID}"
        return embed

    me = guild.me or guild.get_member(bot.user.id)
    bot_top_role = me.top_role if me else None

    # Общая инфа
    latency_ms = round(bot.latency * 1000)
    embed.add_field(
        name="Общее",
        value=(
            f"• Сервер: **{guild.name}**\n"
            f"• Бот: **{bot.user}**\n"
            f"• Ping: **{latency_ms} мс**\n"
            f"• Верхняя роль бота: **{bot_top_role.name if bot_top_role else 'неизвестно'}**\n"
            f"• Версия: **2.0.0**\n"
            f"• Разработчик: **swazy** <@755585532960047155>"
        ),
        inline=False
    )

    # Память / БД
    state_counts = _state_counts()
    db_counts = await asyncio.to_thread(_db_counts)

    embed.add_field(name="Память (state)", value=_format_counts(state_counts), inline=True)
    embed.add_field(name="База (SQLite)", value=_format_counts(db_counts), inline=True)

    # Сервисное состояние
    embed.add_field(
        name="Сервисное состояние",
        value=_truncate_lines(_service_status_lines()),
        inline=False
    )

    # Права бота
    if me:
        gp = me.guild_permissions
        perms_text = (
            f"{_ok(gp.manage_roles)} Управлять ролями\n"
            f"{_ok(gp.manage_nicknames)} Управлять никами\n"
            f"{_ok(gp.view_channel)} Просмотр каналов\n"
            f"{_ok(gp.send_messages)} Отправка сообщений"
        )
    else:
        perms_text = "❌ Не удалось получить участника бота"
    embed.add_field(name="Права бота", value=perms_text, inline=True)

    # Проверка ключевых каналов
    channel_lines = [
        _check_channel(guild, getattr(Config, "REQUEST_CHANNEL_ID", 0), "Канал заявок"),
        _check_channel(guild, getattr(Config, "FIRING_CHANNEL_ID", 0), "Канал увольнений"),
        _check_channel(guild, getattr(Config, "WAREHOUSE_REQUEST_CHANNEL_ID", 0), "Канал склада"),
        _check_channel(guild, getattr(Config, "ACADEMY_CHANNEL_ID", 0), "Канал академии"),
        _check_channel(guild, getattr(Config, "CHANNEL_APPLY_GROM", 0), "Заявки в ГРОМ"),
        _check_channel(guild, getattr(Config, "CHANNEL_APPLY_PPS", 0), "Заявки в ППС"),
        _check_channel(guild, getattr(Config, "CHANNEL_APPLY_OSB", 0), "Заявки в ОСБ"),
        _check_channel(guild, getattr(Config, "CHANNEL_APPLY_ORLS", 0), "Заявки в ОРЛС"),
        _check_channel(guild, getattr(Config, "CHANNEL_ADMIN_TRANSFER", 0), "Админ-перевод"),
        _check_channel(guild, getattr(Config, "CHANNEL_CADRE_LOG", 0), "Лог кадровых"),
    ]
    embed.add_field(name="Ключевые каналы", value=_truncate_lines(channel_lines), inline=False)

    # Проверка ключевых ролей
    role_lines = [
        _check_role(guild, getattr(Config, "STAFF_ROLE_ID", 0), "Кадровик (общий)", bot_top_role),
        _check_role(guild, getattr(Config, "FIRING_STAFF_ROLE_ID", 0), "Кадровик (увольнение)", bot_top_role),
        _check_role(guild, getattr(Config, "WAREHOUSE_STAFF_ROLE_ID", 0), "Склад", bot_top_role),
        _check_role(guild, getattr(Config, "FIRED_ROLE_ID", 0), "Роль уволенного", bot_top_role),
    ]
    embed.add_field(name="Ключевые роли", value=_truncate_lines(role_lines), inline=False)

    # Сводка по каналам повышений
    promo_map = getattr(Config, "PROMOTION_CHANNELS", {}) or {}
    promo_lines = []
    if promo_map:
        for ch_id, role_ids in promo_map.items():
            ch = guild.get_channel(int(ch_id))
            ch_name = ch.name if ch else ch_id

            if not role_ids:
                promo_lines.append(f"{_warn('нет ролей')} {ch_name} → (ролей не задано)")
                continue

            names = []
            all_ok = True
            for rid in role_ids:
                role = guild.get_role(int(rid))
                if not role:
                    all_ok = False
                    names.append(str(rid))
                else:
                    names.append(role.name)

            arrow = ", ".join(names)
            promo_lines.append(
                f"{_ok(ch is not None and all_ok)} {ch_name} → {arrow}"
            )
    else:
        promo_lines.append("⚠️ PROMOTION_CHANNELS пустой")
    embed.add_field(name="Повышения (канал → роли)", value=_truncate_lines(promo_lines), inline=False)

    embed.set_footer(text="/diag | /diag_clean_orphans | /clear_firing")
    return embed