import logging
import re
from typing import Dict, Tuple, Optional

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