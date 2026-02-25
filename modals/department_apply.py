from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Tuple

import discord
from discord.ui import Modal, TextInput, View, Button

from config import Config
from database import save_department_transfer_request
from state import active_department_transfers, bot
from services.department_roles import get_chief_deputy_role_ids, get_approval_label_target
from utils.rate_limiter import safe_send, apply_role_changes, safe_discord_call
from utils.validators import Validators
from views.department_approval_view import DepartmentApprovalView
from views.message_texts import ErrorMessages
from services.department_roles import get_dept_and_rank_roles
from services.department_nickname import get_transfer_nickname

logger = logging.getLogger(__name__)


def _rank_default_for_member(member: discord.Member | None) -> str:
    if not member:
        return ""
    from services.ranks import get_member_rank_display
    return (get_member_rank_display(member) or "").strip()


def _name_surname_defaults_for_member(member: discord.Member | None) -> Tuple[str, str]:
    if not member:
        return "", ""
    from utils.member_display import get_member_name_surname
    return get_member_name_surname(member)

_department_apply_temp: dict[int, dict] = {}


class _Step2ContinueView(View):
    def __init__(self, user_id: int, step_type: str):
        super().__init__(timeout=300)
        self._user_id = user_id
        self._step_type = step_type
        btn = Button(label="Заполнить шаг 2", style=discord.ButtonStyle.primary, custom_id="dept_apply_step2")
        btn.callback = self._on_click
        self.add_item(btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self._user_id:
            await interaction.response.send_message("Эта кнопка только для вас.", ephemeral=True)
            return False
        return True

    async def _on_click(self, interaction: discord.Interaction):
        if interaction.user.id != self._user_id:
            return
        if self._step_type == "grom":
            modal = GromApplyModalStep2(self._user_id)
        elif self._step_type == "osb":
            modal = OsbApplyModalStep2(self._user_id)
        elif self._step_type == "orls":
            modal = OrlsApplyModalStep2(self._user_id)
        else:
            await interaction.response.send_message("❌ Неизвестный тип заявки.", ephemeral=True)
            return
        await interaction.response.send_modal(modal)

# Цвета по ТЗ
COLOR_GROM = discord.Color.blue()
COLOR_PPS = discord.Color.green()
COLOR_OSB = discord.Color.red()
COLOR_ORLS = discord.Color.gold()


def _get_mention_role_ids(target_dept: str, source_dept: str) -> list[int]:
    ids = get_chief_deputy_role_ids(target_dept) + get_chief_deputy_role_ids(source_dept)
    return [r for r in ids if r]


def _content_with_mentions(target_dept: str, source_dept: str) -> str:
    ids = _get_mention_role_ids(target_dept, source_dept)
    return " ".join(f"<@&{r}>" for r in ids) if ids else ""


def _is_from_academy(member: discord.Member) -> bool:
    if not getattr(Config, "ROLE_ACADEMY", 0):
        return False
    r = member.guild.get_role(Config.ROLE_ACADEMY)
    return r is not None and r in member.roles


def _modal_title(target_dept: str, source_dept: str, from_academy: bool) -> str:
    target_labels = {"grom": "ГРОМ", "pps": "ППС", "osb": "ОСБ", "orls": "ОРЛС"}
    t = target_labels.get(target_dept, target_dept)
    if from_academy:
        return f"Заявка в {t} (из Академии)"
    src_labels = {"grom": "ГРОМ", "pps": "ППС", "osb": "ОСБ", "orls": "ОРЛС"}
    s = src_labels.get(source_dept, source_dept)
    return f"Заявка в {t} (из {s})"


def _embed_title(target_dept: str, source_dept: str, from_academy: bool) -> str:
    labels = {"grom": "ОСН \"ГРОМ\"", "pps": "ППС", "osb": "ОСБ", "orls": "ОРЛС"}
    t = labels.get(target_dept, target_dept)
    if from_academy:
        return f"📬 ЗАЯВКА В {t.upper()} (из Академии)"
    s = labels.get(source_dept, source_dept)
    return f"📬 ЗАЯВКА В {t.upper()} (из {s})"


# Русские подписи полей в embed заявки (вместо Name, Surname, Rank и т.д.)
_EMBED_FIELD_LABELS = {
    "name": "Имя",
    "surname": "Фамилия",
    "rank": "Звание",
    "age": "Возраст",
    "shooting": "Фиксация стрельбы",
    "interest": "Что заинтересовало в подразделении",
    "ready_test": "Готовы пройти тестирование",
    "why_pps": "Почему хотите в ППС",
    "experience": "Опыт работы",
    "goals": "Цели в отделе",
    "qualities": "Личные качества",
    "why": "Почему хотите попасть в отдел",
}


def _get_apply_channel_id(target_dept: str) -> int:
    mapping = {
        "grom": getattr(Config, "CHANNEL_APPLY_GROM", 0),
        "pps": getattr(Config, "CHANNEL_APPLY_PPS", 0),
        "osb": getattr(Config, "CHANNEL_APPLY_OSB", 0),
        "orls": getattr(Config, "CHANNEL_APPLY_ORLS", 0),
    }
    return int(mapping.get((target_dept or "").strip().lower(), 0) or 0)


# Возраст: только цифры, от 14 до 100
_AGE_MIN, _AGE_MAX = 14, 100


def _validate_apply_fields(name: str, surname: str, rank: str, age: str, from_academy: bool) -> tuple[bool, str | None, dict]:
    ok, res = Validators.validate_name(name)
    if not ok:
        return False, f"**Имя:** {res}", {}
    name_fmt = res
    ok, res = Validators.validate_name(surname)
    if not ok:
        return False, f"**Фамилия:** {res}", {}
    surname_fmt = res
    rank_fmt = rank.strip() if rank else ""
    if not from_academy:
        ok, res = Validators.validate_rank(rank_fmt)
        if not ok:
            return False, f"**Звание:** {res}", {}
        rank_fmt = res
    age_clean = (age or "").strip()
    if not age_clean:
        return False, "**Возраст:** укажите число.", {}
    if not re.match(r"^\d+$", age_clean):
        return False, "**Возраст:** только цифры (например: 18).", {}
    try:
        a = int(age_clean)
        if a < _AGE_MIN or a > _AGE_MAX:
            return False, f"**Возраст:** укажите число от {_AGE_MIN} до {_AGE_MAX}.", {}
    except ValueError:
        return False, "**Возраст:** укажите число.", {}
    return True, None, {"name": name_fmt, "surname": surname_fmt, "rank": rank_fmt, "age": age_clean}


def _build_embed(target_dept: str, form_data: dict, user_id: int, from_academy: bool, source_dept: str) -> discord.Embed:
    colors = {"grom": COLOR_GROM, "pps": COLOR_PPS, "osb": COLOR_OSB, "orls": COLOR_ORLS}
    color = colors.get(target_dept, discord.Color.default())
    title = _embed_title(target_dept, source_dept, from_academy)
    embed = discord.Embed(title=title, color=color)
    embed.add_field(name="**От:**", value=f"<@{user_id}>", inline=False)
    for key, value in (form_data or {}).items():
        if key in ("created_at",):
            continue
        label = _EMBED_FIELD_LABELS.get(key, key.replace("_", " ").title())
        embed.add_field(name=label, value=str(value)[:1024], inline=True)
    return embed


async def _post_application(
    channel: discord.TextChannel,
    user_id: int,
    target_dept: str,
    source_dept: str,
    from_academy: bool,
    form_data: dict,
) -> discord.Message | None:
    content = _content_with_mentions(target_dept, source_dept)
    embed = _build_embed(target_dept, form_data, user_id, from_academy, source_dept)

    if from_academy and target_dept == "pps":
        # Автодобро ППС из Академии: снять роли Академии, выдать роли ППС
        guild = channel.guild
        member = guild.get_member(user_id) or await guild.fetch_member(user_id)
        if member:
            remove_dept, remove_rank = get_dept_and_rank_roles(guild, "academy")
            add_dept, add_rank = get_dept_and_rank_roles(guild, "pps")
            to_remove = [r for r in remove_dept + remove_rank if r]
            to_add = [r for r in add_dept + add_rank if r]
            if to_remove or to_add:
                await apply_role_changes(member, remove=to_remove, add=to_add)
            new_nick = get_transfer_nickname("pps", form_data)
            if new_nick:
                try:
                    await safe_discord_call(member.edit, nick=new_nick)
                except Exception:
                    pass
            try:
                await member.send("✅ Ваша заявка в ППС (из Академии) одобрена. Вам выданы роли ППС.")
            except (discord.Forbidden, discord.HTTPException):
                pass
        embed.add_field(name="Статус", value="✅ Одобрено (заявка из Академии)", inline=False)
        msg = await safe_send(channel, content=content, embed=embed)
        return msg

    view = DepartmentApprovalView(
        message_id=0,
        user_id=user_id,
        target_dept=target_dept,
        source_dept=source_dept,
        from_academy=from_academy,
        form_data=form_data,
        channel_id=channel.id,
    )
    msg = await safe_send(channel, content=content, embed=embed, view=view)
    if msg:
        # Обновить message_id во view для обработчиков
        view.message_id = msg.id
        payload = {
            "user_id": user_id,
            "target_dept": target_dept,
            "source_dept": source_dept,
            "from_academy": from_academy,
            "data": form_data,
            "approved_source": 0,
            "approved_target": 0,
            "created_at": datetime.now().isoformat(),
        }
        await asyncio.to_thread(save_department_transfer_request, msg.id, payload)
        active_department_transfers[msg.id] = {**payload, "message_id": msg.id}
    return msg


# ---- ГРОМ: 7 полей, два модала ----

class GromApplyModalStep1(Modal):
    def __init__(self, target_dept: str, source_dept: str, channel_id: int, from_academy: bool = False, member: discord.Member | None = None):
        title = _modal_title(target_dept, source_dept, from_academy)
        super().__init__(title=title[:45])
        self.target_dept = target_dept
        self.source_dept = source_dept
        self.channel_id = channel_id
        self.from_academy = from_academy
        rank_placeholder = "Сержант (выпускник академии)" if from_academy else None
        rank_default = _rank_default_for_member(member) if not from_academy else "Сержант"
        name_default, surname_default = _name_surname_defaults_for_member(member)
        self.name = TextInput(label="Имя", min_length=Config.MIN_NAME_LENGTH, max_length=Config.MAX_NAME_LENGTH, required=True, default=name_default)
        self.surname = TextInput(label="Фамилия", min_length=Config.MIN_NAME_LENGTH, max_length=Config.MAX_NAME_LENGTH, required=True, default=surname_default)
        self.rank = TextInput(
            label="Ваше звание",
            max_length=Config.MAX_RANK_LENGTH,
            required=True,
            placeholder=rank_placeholder or "например: Сержант",
            default=rank_default,
        )
        self.age = TextInput(label="Ваш возраст", max_length=10, required=True)
        self.shooting = TextInput(label="Фиксация вашей стрельбы", max_length=500, required=True)
        self.add_item(self.name)
        self.add_item(self.surname)
        self.add_item(self.rank)
        self.add_item(self.age)
        self.add_item(self.shooting)

    async def on_submit(self, interaction: discord.Interaction):
        from_academy = _is_from_academy(interaction.user)
        name_raw = self.name.value.strip()
        surname_raw = self.surname.value.strip()
        rank_raw = "Сержант" if from_academy else self.rank.value.strip()
        age_raw = self.age.value.strip()
        ok, err, formatted = _validate_apply_fields(name_raw, surname_raw, rank_raw, age_raw, from_academy)
        if not ok:
            await interaction.response.send_message(f"❌ Проверьте данные:\n{err}", ephemeral=True)
            return
        step1_data = {
            "name": formatted["name"],
            "surname": formatted["surname"],
            "rank": formatted["rank"],
            "age": formatted["age"],
            "shooting": self.shooting.value.strip(),
        }
        _department_apply_temp[interaction.user.id] = {
            "target_dept": self.target_dept,
            "source_dept": self.source_dept if not from_academy else "academy",
            "from_academy": from_academy,
            "channel_id": self.channel_id,
            "step1": step1_data,
        }
        view = _Step2ContinueView(interaction.user.id, "grom")
        await interaction.response.send_message(
            "Шаг 1 сохранён. Нажмите кнопку ниже для заполнения шага 2.",
            view=view,
            ephemeral=True,
        )


class GromApplyModalStep2(Modal):
    def __init__(self, user_id: int):
        super().__init__(title="Заявка в ГРОМ (шаг 2)")
        self.user_id = user_id
        self.interest = TextInput(label="Что заинтересовало в подразделении", style=discord.TextStyle.paragraph, max_length=500, required=True)
        self.ready_test = TextInput(label="Готовы пройти тестирование", max_length=200, required=True)
        self.add_item(self.interest)
        self.add_item(self.ready_test)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            data = _department_apply_temp.pop(interaction.user.id, None)
            if not data:
                await interaction.response.send_message("❌ Сессия истекла. Заполните форму заново.", ephemeral=True)
                return
            form_data = {
                **data["step1"],
                "interest": self.interest.value.strip(),
                "ready_test": self.ready_test.value.strip(),
            }
            channel = bot.get_channel(data["channel_id"])
            if not channel:
                await interaction.response.send_message("❌ Канал не найден.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            msg = await _post_application(
                channel,
                interaction.user.id,
                data["target_dept"],
                data["source_dept"],
                data["from_academy"],
                form_data,
            )
            if msg:
                await interaction.followup.send("✅ Заявка отправлена.", ephemeral=True)
            else:
                await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)
        except Exception as e:
            logger.error("Ошибка отправки заявки ГРОМ: %s", e, exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)
            else:
                await interaction.response.send_message(ErrorMessages.GENERIC, ephemeral=True)


# ---- ППС: 5 полей, один модал ----

class PpsApplyModal(Modal):
    def __init__(self, target_dept: str, source_dept: str, channel_id: int, from_academy: bool = False, member: discord.Member | None = None):
        title = _modal_title(target_dept, source_dept, from_academy)
        super().__init__(title=title[:45])
        self.target_dept = target_dept
        self.source_dept = source_dept
        self.channel_id = channel_id
        self.from_academy = from_academy
        rank_placeholder = "Сержант (выпускник академии)" if from_academy else None
        rank_default = _rank_default_for_member(member) if not from_academy else "Сержант"
        name_default, surname_default = _name_surname_defaults_for_member(member)
        self.name = TextInput(label="Имя", min_length=Config.MIN_NAME_LENGTH, max_length=Config.MAX_NAME_LENGTH, required=True, default=name_default)
        self.surname = TextInput(label="Фамилия", min_length=Config.MIN_NAME_LENGTH, max_length=Config.MAX_NAME_LENGTH, required=True, default=surname_default)
        self.rank = TextInput(
            label="Ваше звание",
            max_length=Config.MAX_RANK_LENGTH,
            required=True,
            placeholder=rank_placeholder or "например: Сержант",
            default=rank_default,
        )
        self.age = TextInput(label="Ваш возраст", max_length=10, required=True)
        self.why = TextInput(label="Почему хотите перейти в ППС", style=discord.TextStyle.paragraph, max_length=500, required=True)
        self.add_item(self.name)
        self.add_item(self.surname)
        self.add_item(self.rank)
        self.add_item(self.age)
        self.add_item(self.why)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            from_academy = _is_from_academy(interaction.user)
            source_dept = "academy" if from_academy else self.source_dept
            rank_value = "Сержант" if from_academy else self.rank.value.strip()
            name_raw = self.name.value.strip()
            surname_raw = self.surname.value.strip()
            age_raw = self.age.value.strip()
            ok, err, formatted = _validate_apply_fields(name_raw, surname_raw, rank_value, age_raw, from_academy)
            if not ok:
                await interaction.response.send_message(f"❌ Проверьте данные:\n{err}", ephemeral=True)
                return
            form_data = {
                "name": formatted["name"],
                "surname": formatted["surname"],
                "rank": formatted["rank"],
                "age": formatted["age"],
                "why_pps": self.why.value.strip(),
            }
            channel = bot.get_channel(self.channel_id)
            if not channel:
                await interaction.response.send_message("❌ Канал не найден.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            msg = await _post_application(channel, interaction.user.id, self.target_dept, source_dept, from_academy, form_data)
            if msg:
                await interaction.followup.send("✅ Заявка отправлена.", ephemeral=True)
            else:
                await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)
        except Exception as e:
            logger.error("Ошибка отправки заявки ППС: %s", e, exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)
            else:
                await interaction.response.send_message(ErrorMessages.GENERIC, ephemeral=True)


# ---- ОСБ: 6 полей, два модала ----

class OsbApplyModalStep1(Modal):
    def __init__(self, target_dept: str, source_dept: str, channel_id: int, from_academy: bool = False, member: discord.Member | None = None):
        title = _modal_title(target_dept, source_dept, from_academy)
        super().__init__(title=title[:45])
        self.target_dept = target_dept
        self.source_dept = source_dept
        self.channel_id = channel_id
        self.from_academy = from_academy
        rank_placeholder = "Сержант (выпускник академии)" if from_academy else None
        rank_default = _rank_default_for_member(member) if not from_academy else "Сержант"
        name_default, surname_default = _name_surname_defaults_for_member(member)
        self.name = TextInput(label="Имя", min_length=Config.MIN_NAME_LENGTH, max_length=Config.MAX_NAME_LENGTH, required=True, default=name_default)
        self.surname = TextInput(label="Фамилия", min_length=Config.MIN_NAME_LENGTH, max_length=Config.MAX_NAME_LENGTH, required=True, default=surname_default)
        self.rank = TextInput(
            label="Ваше звание",
            max_length=Config.MAX_RANK_LENGTH,
            required=True,
            placeholder=rank_placeholder or "например: Сержант",
            default=rank_default,
        )
        self.age = TextInput(label="Ваш возраст", max_length=10, required=True)
        self.experience = TextInput(label="Опыт работы", style=discord.TextStyle.paragraph, max_length=500, required=True)
        self.add_item(self.name)
        self.add_item(self.surname)
        self.add_item(self.rank)
        self.add_item(self.age)
        self.add_item(self.experience)

    async def on_submit(self, interaction: discord.Interaction):
        from_academy = _is_from_academy(interaction.user)
        name_raw = self.name.value.strip()
        surname_raw = self.surname.value.strip()
        rank_raw = "Сержант" if from_academy else self.rank.value.strip()
        age_raw = self.age.value.strip()
        ok, err, formatted = _validate_apply_fields(name_raw, surname_raw, rank_raw, age_raw, from_academy)
        if not ok:
            await interaction.response.send_message(f"❌ Проверьте данные:\n{err}", ephemeral=True)
            return
        _department_apply_temp[interaction.user.id] = {
            "target_dept": self.target_dept,
            "source_dept": "academy" if from_academy else self.source_dept,
            "from_academy": from_academy,
            "channel_id": self.channel_id,
            "step1": {
                "name": formatted["name"],
                "surname": formatted["surname"],
                "rank": formatted["rank"],
                "age": formatted["age"],
                "experience": self.experience.value.strip(),
            },
        }
        view = _Step2ContinueView(interaction.user.id, "osb")
        await interaction.response.send_message(
            "Шаг 1 сохранён. Нажмите кнопку ниже для заполнения шага 2.",
            view=view,
            ephemeral=True,
        )


class OsbApplyModalStep2(Modal):
    def __init__(self, user_id: int):
        super().__init__(title="Заявка в ОСБ (шаг 2)")
        self.user_id = user_id
        self.goals = TextInput(label="Ваши цели в отделе", style=discord.TextStyle.paragraph, max_length=500, required=True)
        self.add_item(self.goals)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            data = _department_apply_temp.pop(interaction.user.id, None)
            if not data:
                await interaction.response.send_message("❌ Сессия истекла. Заполните форму заново.", ephemeral=True)
                return
            form_data = {**data["step1"], "goals": self.goals.value.strip()}
            channel = bot.get_channel(data["channel_id"])
            if not channel:
                await interaction.response.send_message("❌ Канал не найден.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            msg = await _post_application(
                channel, interaction.user.id, data["target_dept"], data["source_dept"], data["from_academy"], form_data
            )
            if msg:
                await interaction.followup.send("✅ Заявка отправлена.", ephemeral=True)
            else:
                await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)
        except Exception as e:
            logger.error("Ошибка отправки заявки ОСБ: %s", e, exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)
            else:
                await interaction.response.send_message(ErrorMessages.GENERIC, ephemeral=True)


# ---- ОРЛС: 7 полей, два модала ----

class OrlsApplyModalStep1(Modal):
    def __init__(self, target_dept: str, source_dept: str, channel_id: int, from_academy: bool = False, member: discord.Member | None = None):
        title = _modal_title(target_dept, source_dept, from_academy)
        super().__init__(title=title[:45])
        self.target_dept = target_dept
        self.source_dept = source_dept
        self.channel_id = channel_id
        self.from_academy = from_academy
        rank_placeholder = "Сержант (выпускник академии)" if from_academy else None
        rank_default = _rank_default_for_member(member) if not from_academy else "Сержант"
        name_default, surname_default = _name_surname_defaults_for_member(member)
        self.name = TextInput(label="Имя", min_length=Config.MIN_NAME_LENGTH, max_length=Config.MAX_NAME_LENGTH, required=True, default=name_default)
        self.surname = TextInput(label="Фамилия", min_length=Config.MIN_NAME_LENGTH, max_length=Config.MAX_NAME_LENGTH, required=True, default=surname_default)
        self.rank = TextInput(
            label="Ваше звание",
            max_length=Config.MAX_RANK_LENGTH,
            required=True,
            placeholder=rank_placeholder or "например: Сержант",
            default=rank_default,
        )
        self.age = TextInput(label="Ваш возраст", max_length=10, required=True)
        self.experience = TextInput(label="Опыт работы с кадрами", style=discord.TextStyle.paragraph, max_length=500, required=True)
        self.add_item(self.name)
        self.add_item(self.surname)
        self.add_item(self.rank)
        self.add_item(self.age)
        self.add_item(self.experience)

    async def on_submit(self, interaction: discord.Interaction):
        from_academy = _is_from_academy(interaction.user)
        name_raw = self.name.value.strip()
        surname_raw = self.surname.value.strip()
        rank_raw = "Сержант" if from_academy else self.rank.value.strip()
        age_raw = self.age.value.strip()
        ok, err, formatted = _validate_apply_fields(name_raw, surname_raw, rank_raw, age_raw, from_academy)
        if not ok:
            await interaction.response.send_message(f"❌ Проверьте данные:\n{err}", ephemeral=True)
            return
        _department_apply_temp[interaction.user.id] = {
            "target_dept": self.target_dept,
            "source_dept": "academy" if from_academy else self.source_dept,
            "from_academy": from_academy,
            "channel_id": self.channel_id,
            "step1": {
                "name": formatted["name"],
                "surname": formatted["surname"],
                "rank": formatted["rank"],
                "age": formatted["age"],
                "experience": self.experience.value.strip(),
            },
        }
        view = _Step2ContinueView(interaction.user.id, "orls")
        await interaction.response.send_message(
            "Шаг 1 сохранён. Нажмите кнопку ниже для заполнения шага 2.",
            view=view,
            ephemeral=True,
        )


class OrlsApplyModalStep2(Modal):
    def __init__(self, user_id: int):
        super().__init__(title="Заявка в ОРЛС (шаг 2)")
        self.user_id = user_id
        self.qualities = TextInput(label="Личные качества", style=discord.TextStyle.paragraph, max_length=500, required=True)
        self.why = TextInput(label="Почему хотите попасть в отдел", style=discord.TextStyle.paragraph, max_length=500, required=True)
        self.add_item(self.qualities)
        self.add_item(self.why)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            data = _department_apply_temp.pop(interaction.user.id, None)
            if not data:
                await interaction.response.send_message("❌ Сессия истекла. Заполните форму заново.", ephemeral=True)
                return
            form_data = {
                **data["step1"],
                "qualities": self.qualities.value.strip(),
                "why": self.why.value.strip(),
            }
            channel = bot.get_channel(data["channel_id"])
            if not channel:
                await interaction.response.send_message("❌ Канал не найден.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            msg = await _post_application(
                channel, interaction.user.id, data["target_dept"], data["source_dept"], data["from_academy"], form_data
            )
            if msg:
                await interaction.followup.send("✅ Заявка отправлена.", ephemeral=True)
            else:
                await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)
        except Exception as e:
            logger.error("Ошибка отправки заявки ОРЛС: %s", e, exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send(ErrorMessages.GENERIC, ephemeral=True)
            else:
                await interaction.response.send_message(ErrorMessages.GENERIC, ephemeral=True)


def open_apply_modal(interaction: discord.Interaction, target_dept: str, source_dept: str):
    if not interaction.channel_id:
        return
    target_dept = (target_dept or "").strip().lower()
    source_dept = (source_dept or "").strip().lower()
    from_academy = _is_from_academy(interaction.user)
    if from_academy:
        source_dept = "academy"
    apply_channel_id = _get_apply_channel_id(target_dept)
    if not apply_channel_id:
        return None
    member = interaction.user if isinstance(interaction.user, discord.Member) else None
    if target_dept == "grom":
        return GromApplyModalStep1(target_dept, source_dept, apply_channel_id, from_academy, member)
    elif target_dept == "pps":
        return PpsApplyModal(target_dept, source_dept, apply_channel_id, from_academy, member)
    elif target_dept == "osb":
        return OsbApplyModalStep1(target_dept, source_dept, apply_channel_id, from_academy, member)
    elif target_dept == "orls":
        return OrlsApplyModalStep1(target_dept, source_dept, apply_channel_id, from_academy, member)
    return None
