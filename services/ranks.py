import logging
import re
from typing import Dict, Tuple, Optional

import discord
from config import Config

logger = logging.getLogger(__name__)

_ARROW_RE = re.compile(r"\s*(?:->|→|➡|⇒|=+>)\s*")


def _canon_rank(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def _canon_transition_key(key: str) -> Optional[Tuple[str, str]]:
    key = (key or "").strip()
    if not key:
        return None

    parts = _ARROW_RE.split(key)
    if len(parts) != 2:
        return None

    a = _canon_rank(parts[0])
    b = _canon_rank(parts[1])
    if not a or not b:
        return None
    return a, b


def build_normalized_rank_mapping() -> Dict[Tuple[str, str], int]:
    raw = getattr(Config, "RANK_ROLE_MAPPING", {}) or {}
    normalized: Dict[Tuple[str, str], int] = {}

    for raw_key, role_id in raw.items():
        canon = _canon_transition_key(str(raw_key))
        if canon is None:
            continue

        try:
            rid = int(role_id)
        except Exception:
            continue

        if canon in normalized and normalized[canon] != rid:
            logger.warning(
                "⚠️ Конфликт RANK_ROLE_MAPPING: '%s' уже %s, новый %s. Оставляю первый.",
                raw_key, normalized[canon], rid
            )
            continue

        normalized[canon] = rid

    return normalized


def find_role_id_for_transition(transition: str) -> Optional[int]:
    canon = _canon_transition_key(transition)
    if not canon:
        return None
    mapping = build_normalized_rank_mapping()
    return mapping.get(canon)


def parse_transition_to_new_rank(transition: str):
    canon = _canon_transition_key(transition)
    if not canon:
        return None
    return canon[1]


def get_all_rank_role_ids_from_mapping():
    mapping = build_normalized_rank_mapping()
    return set(mapping.values())


def _build_role_id_to_display_name() -> Dict[int, str]:
    raw = getattr(Config, "RANK_ROLE_MAPPING", {}) or {}
    result: Dict[int, str] = {}
    for raw_key, role_id in raw.items():
        try:
            rid = int(role_id)
        except Exception:
            continue
        key = str(raw_key).strip()
        for sep in ("->", "→", "➡", "⇒"):
            if sep in key:
                part = key.split(sep, 1)[-1].strip()
                if part:
                    result[rid] = part[0].upper() + part[1:] if len(part) > 1 else part.upper()
                break
    return result


def get_member_rank_display(member: Optional[discord.Member]) -> str:
    if not member or not getattr(member, "roles", None):
        return ""
    all_rank_ids = set(getattr(Config, "ALL_RANK_ROLE_IDS", []) or [])
    all_rank_ids |= get_all_rank_role_ids_from_mapping()
    if not all_rank_ids:
        return ""
    role_to_name = _build_role_id_to_display_name()
    member_rank_roles = [r for r in member.roles if r.id in all_rank_ids]
    if not member_rank_roles:
        return ""
    top = max(member_rank_roles, key=lambda r: r.position)
    return role_to_name.get(top.id, top.name) or ""