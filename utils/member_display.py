# Парсинг ника в формате «префикс | имя фамилия» для подстановки в формы

import re
from typing import Tuple

import discord

_SEP = " | "
_SEP_PATTERN = re.compile(r"\s*\|\s*", re.IGNORECASE)


def get_member_name_surname(member: discord.Member | None) -> Tuple[str, str]:
    if not member:
        return "", ""
    raw = (member.display_name or member.name or "").strip()
    if not raw:
        return "", ""
    parts = _SEP_PATTERN.split(raw, 1)
    if len(parts) >= 2:
        name_surname = (parts[1] or "").strip()
    else:
        name_surname = (parts[0] or "").strip()
    if not name_surname:
        return "", ""
    tokens = name_surname.split(None, 1)
    if len(tokens) >= 2:
        return tokens[0].strip(), tokens[1].strip()
    return tokens[0].strip(), ""


def get_member_full_name(member: discord.Member | None) -> str:
    name, surname = get_member_name_surname(member)
    return f"{name} {surname}".strip()
