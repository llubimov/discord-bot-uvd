# -*- coding: utf-8 -*-
"""Асинхронный доступ к SQLite через aiosqlite."""
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, Dict

import aiosqlite

from config import Config

logger = logging.getLogger(__name__)


def _resolve_db_path() -> str:
    if getattr(Config, "DB_PATH", ""):
        path = Config.DB_PATH
    elif getattr(Config, "DATABASE_URL", ""):
        url = Config.DATABASE_URL
        if "///" in url:
            path = url.split("///", 1)[1]
        else:
            path = "data/bot.db"
    else:
        path = "data/bot.db"

    path = (path or "").strip()
    if not path:
        path = "data/bot.db"

    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    return path


DB_PATH = _resolve_db_path()


@asynccontextmanager
async def _get_conn():
    """
    Контекстный менеджер соединения с PRAGMA.
    Каждый вызов открывает новое соединение; не использовать соединение вне контекста.
    """
    conn = await aiosqlite.connect(DB_PATH)
    try:
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA foreign_keys=ON;")
        yield conn
    finally:
        await conn.close()


async def init_db() -> None:
    async with _get_conn() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS requests (
                message_id INTEGER PRIMARY KEY,
                user_id INTEGER,
                data TEXT,
                created_at TEXT,
                request_type TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS firing_requests (
                message_id INTEGER PRIMARY KEY,
                discord_id INTEGER,
                data TEXT,
                created_at TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS promotion_requests (
                message_id INTEGER PRIMARY KEY,
                discord_id INTEGER,
                data TEXT,
                created_at TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS warehouse_requests (
                message_id INTEGER PRIMARY KEY,
                user_id INTEGER,
                data TEXT,
                created_at TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS department_transfer_requests (
                message_id INTEGER PRIMARY KEY,
                user_id INTEGER,
                target_dept TEXT,
                source_dept TEXT,
                from_academy INTEGER,
                data TEXT,
                approved_source INTEGER,
                approved_target INTEGER,
                created_at TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS orls_draft_reports (
                user_id INTEGER PRIMARY KEY,
                data TEXT NOT NULL,
                updated_at TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS osb_draft_reports (
                user_id INTEGER PRIMARY KEY,
                data TEXT NOT NULL,
                updated_at TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS grom_draft_reports (
                user_id INTEGER PRIMARY KEY,
                data TEXT NOT NULL,
                updated_at TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS pps_draft_reports (
                user_id INTEGER PRIMARY KEY,
                data TEXT NOT NULL,
                updated_at TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS warehouse_sessions (
                session_key TEXT PRIMARY KEY,
                items_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS warehouse_cooldowns (
                user_id INTEGER PRIMARY KEY,
                last_issue_at TEXT NOT NULL
            )
        """)
        await conn.commit()


async def save_request(table: str, message_id: int, data: Dict[str, Any]) -> None:
    data_json = json.dumps(data, ensure_ascii=False, default=str)
    created_at = data.get("created_at", datetime.now().isoformat())

    async with _get_conn() as conn:
        if table == "requests":
            await conn.execute(
                "INSERT OR REPLACE INTO requests VALUES (?,?,?,?,?)",
                (message_id, data["user_id"], data_json, created_at, data.get("request_type", "")),
            )
        elif table == "firing_requests":
            await conn.execute(
                "INSERT OR REPLACE INTO firing_requests VALUES (?,?,?,?)",
                (message_id, data["discord_id"], data_json, created_at),
            )
        elif table == "promotion_requests":
            await conn.execute(
                "INSERT OR REPLACE INTO promotion_requests VALUES (?,?,?,?)",
                (message_id, data["discord_id"], data_json, created_at),
            )
        elif table == "warehouse_requests":
            await conn.execute(
                "INSERT OR REPLACE INTO warehouse_requests VALUES (?,?,?,?)",
                (message_id, data["user_id"], data_json, created_at),
            )
        else:
            raise ValueError(f"Unknown table: {table}")
        await conn.commit()


async def delete_request(table: str, message_id: int) -> None:
    if table not in {"requests", "firing_requests", "promotion_requests", "warehouse_requests", "department_transfer_requests"}:
        raise ValueError(f"Unknown table: {table}")
    async with _get_conn() as conn:
        await conn.execute(f"DELETE FROM {table} WHERE message_id = ?", (message_id,))
        await conn.commit()


async def _load_all(table: str) -> Dict[int, Dict]:
    result = {}
    async with _get_conn() as conn:
        cursor = await conn.execute(f"SELECT message_id, data FROM {table}")
        rows = await cursor.fetchall()
    for mid, data in rows:
        try:
            result[mid] = json.loads(data) if data else {}
        except json.JSONDecodeError as e:
            logger.warning("Пропуск битой записи в %s message_id=%s: %s", table, mid, e)
    return result


async def load_all_requests() -> Dict[int, Dict]:
    return await _load_all("requests")


async def load_all_firing_requests() -> Dict[int, Dict]:
    return await _load_all("firing_requests")


async def load_all_promotion_requests() -> Dict[int, Dict]:
    return await _load_all("promotion_requests")


async def load_all_warehouse_requests() -> Dict[int, Dict]:
    return await _load_all("warehouse_requests")


async def save_orls_draft(user_id: int, draft: Dict[str, Any]) -> None:
    storable = {k: v for k, v in draft.items() if k != "_ephemeral_msg"}
    data_json = json.dumps(storable, ensure_ascii=False, default=str)
    updated_at = datetime.now().isoformat()
    async with _get_conn() as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO orls_draft_reports (user_id, data, updated_at) VALUES (?, ?, ?)",
            (user_id, data_json, updated_at),
        )
        await conn.commit()


async def load_orls_draft(user_id: int) -> Dict[str, Any] | None:
    async with _get_conn() as conn:
        cursor = await conn.execute("SELECT data FROM orls_draft_reports WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
    if not row or not row[0]:
        return None
    try:
        data = json.loads(row[0])
        data["_ephemeral_msg"] = None
        data.setdefault("message_id", None)
        return data
    except json.JSONDecodeError as e:
        logger.warning("Ошибка чтения orls_draft user_id=%s: %s", user_id, e)
        return None


async def delete_orls_draft(user_id: int) -> None:
    async with _get_conn() as conn:
        await conn.execute("DELETE FROM orls_draft_reports WHERE user_id = ?", (user_id,))
        await conn.commit()


async def cleanup_old_orls_drafts(days: int = 14) -> int:
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    async with _get_conn() as conn:
        cursor = await conn.execute("SELECT user_id FROM orls_draft_reports WHERE updated_at < ?", (cutoff,))
        to_delete = await cursor.fetchall()
        for (uid,) in to_delete:
            await conn.execute("DELETE FROM orls_draft_reports WHERE user_id = ?", (uid,))
        await conn.commit()
    return len(to_delete)


async def save_osb_draft(user_id: int, draft: Dict[str, Any]) -> None:
    storable = {k: v for k, v in draft.items() if k != "_ephemeral_msg"}
    data_json = json.dumps(storable, ensure_ascii=False, default=str)
    updated_at = datetime.now().isoformat()
    async with _get_conn() as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO osb_draft_reports (user_id, data, updated_at) VALUES (?, ?, ?)",
            (user_id, data_json, updated_at),
        )
        await conn.commit()


async def load_osb_draft(user_id: int) -> Dict[str, Any] | None:
    async with _get_conn() as conn:
        cursor = await conn.execute("SELECT data FROM osb_draft_reports WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
    if not row or not row[0]:
        return None
    try:
        data = json.loads(row[0])
        data["_ephemeral_msg"] = None
        data.setdefault("message_id", None)
        return data
    except json.JSONDecodeError as e:
        logger.warning("Ошибка чтения osb_draft user_id=%s: %s", user_id, e)
        return None


async def delete_osb_draft(user_id: int) -> None:
    async with _get_conn() as conn:
        await conn.execute("DELETE FROM osb_draft_reports WHERE user_id = ?", (user_id,))
        await conn.commit()


async def cleanup_old_osb_drafts(days: int = 14) -> int:
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    async with _get_conn() as conn:
        cursor = await conn.execute("SELECT user_id FROM osb_draft_reports WHERE updated_at < ?", (cutoff,))
        to_delete = await cursor.fetchall()
        for (uid,) in to_delete:
            await conn.execute("DELETE FROM osb_draft_reports WHERE user_id = ?", (uid,))
        await conn.commit()
    return len(to_delete)


async def save_grom_draft(user_id: int, draft: Dict[str, Any]) -> None:
    storable = {k: v for k, v in draft.items() if k != "_ephemeral_msg"}
    data_json = json.dumps(storable, ensure_ascii=False, default=str)
    updated_at = datetime.now().isoformat()
    async with _get_conn() as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO grom_draft_reports (user_id, data, updated_at) VALUES (?, ?, ?)",
            (user_id, data_json, updated_at),
        )
        await conn.commit()


async def load_grom_draft(user_id: int) -> Dict[str, Any] | None:
    async with _get_conn() as conn:
        cursor = await conn.execute("SELECT data FROM grom_draft_reports WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
    if not row or not row[0]:
        return None
    try:
        data = json.loads(row[0])
        data["_ephemeral_msg"] = None
        data.setdefault("message_id", None)
        return data
    except json.JSONDecodeError as e:
        logger.warning("Ошибка чтения grom_draft user_id=%s: %s", user_id, e)
        return None


async def delete_grom_draft(user_id: int) -> None:
    async with _get_conn() as conn:
        await conn.execute("DELETE FROM grom_draft_reports WHERE user_id = ?", (user_id,))
        await conn.commit()


async def cleanup_old_grom_drafts(days: int = 14) -> int:
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    async with _get_conn() as conn:
        cursor = await conn.execute("SELECT user_id FROM grom_draft_reports WHERE updated_at < ?", (cutoff,))
        to_delete = await cursor.fetchall()
        for (uid,) in to_delete:
            await conn.execute("DELETE FROM grom_draft_reports WHERE user_id = ?", (uid,))
        await conn.commit()
    return len(to_delete)


async def save_pps_draft(user_id: int, draft: Dict[str, Any]) -> None:
    storable = {k: v for k, v in draft.items() if k != "_ephemeral_msg"}
    data_json = json.dumps(storable, ensure_ascii=False, default=str)
    updated_at = datetime.now().isoformat()
    async with _get_conn() as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO pps_draft_reports (user_id, data, updated_at) VALUES (?, ?, ?)",
            (user_id, data_json, updated_at),
        )
        await conn.commit()


async def load_pps_draft(user_id: int) -> Dict[str, Any] | None:
    async with _get_conn() as conn:
        cursor = await conn.execute("SELECT data FROM pps_draft_reports WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
    if not row or not row[0]:
        return None
    try:
        data = json.loads(row[0])
        data["_ephemeral_msg"] = None
        data.setdefault("message_id", None)
        return data
    except json.JSONDecodeError as e:
        logger.warning("Ошибка чтения pps_draft user_id=%s: %s", user_id, e)
        return None


async def delete_pps_draft(user_id: int) -> None:
    async with _get_conn() as conn:
        await conn.execute("DELETE FROM pps_draft_reports WHERE user_id = ?", (user_id,))
        await conn.commit()


async def cleanup_old_pps_drafts(days: int = 14) -> int:
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    async with _get_conn() as conn:
        cursor = await conn.execute("SELECT user_id FROM pps_draft_reports WHERE updated_at < ?", (cutoff,))
        to_delete = await cursor.fetchall()
        for (uid,) in to_delete:
            await conn.execute("DELETE FROM pps_draft_reports WHERE user_id = ?", (uid,))
        await conn.commit()
    return len(to_delete)


async def cleanup_old_requests_db(days: int) -> None:
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    async with _get_conn() as conn:
        for table in ["requests", "firing_requests", "promotion_requests", "warehouse_requests"]:
            await conn.execute(f"DELETE FROM {table} WHERE created_at < ?", (cutoff,))
        await conn.execute("DELETE FROM department_transfer_requests WHERE created_at < ?", (cutoff,))
        await conn.commit()


async def cleanup_old_requests(days: int) -> None:
    await cleanup_old_requests_db(days)


async def cleanup_old_firing_requests(days: int) -> None:
    await cleanup_old_requests_db(days)


async def cleanup_old_promotion_requests(days: int) -> None:
    await cleanup_old_requests_db(days)


async def cleanup_old_warehouse_requests(days: int) -> None:
    await cleanup_old_requests_db(days)


async def save_user_request(message_id: int, data: dict) -> None:
    await save_request("requests", message_id, data)


async def delete_user_request(message_id: int) -> None:
    await delete_request("requests", message_id)


async def save_firing_request(message_id: int, data: dict) -> None:
    await save_request("firing_requests", message_id, data)


async def delete_firing_request(message_id: int) -> None:
    await delete_request("firing_requests", message_id)


async def save_promotion_request(message_id: int, data: dict) -> None:
    await save_request("promotion_requests", message_id, data)


async def delete_promotion_request(message_id: int) -> None:
    await delete_request("promotion_requests", message_id)


async def save_warehouse_request(message_id: int, data: dict) -> None:
    await save_request("warehouse_requests", message_id, data)


async def delete_warehouse_request(message_id: int) -> None:
    await delete_request("warehouse_requests", message_id)


async def save_department_transfer_request(message_id: int, payload: Dict[str, Any]) -> None:
    data_json = json.dumps(payload.get("data", {}), ensure_ascii=False, default=str)
    from_academy = 1 if payload.get("from_academy") else 0
    async with _get_conn() as conn:
        await conn.execute(
            """INSERT OR REPLACE INTO department_transfer_requests
               (message_id, user_id, target_dept, source_dept, from_academy, data, approved_source, approved_target, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                message_id,
                int(payload.get("user_id", 0)),
                str(payload.get("target_dept", "")),
                str(payload.get("source_dept", "")),
                from_academy,
                data_json,
                int(payload.get("approved_source", 0)),
                int(payload.get("approved_target", 0)),
                payload.get("created_at", datetime.now().isoformat()),
            ),
        )
        await conn.commit()


async def update_department_transfer_approval(
    message_id: int,
    *,
    approved_source: int | None = None,
    approved_target: int | None = None,
) -> None:
    async with _get_conn() as conn:
        if approved_source is not None:
            await conn.execute(
                "UPDATE department_transfer_requests SET approved_source = ? WHERE message_id = ?",
                (approved_source, message_id),
            )
        if approved_target is not None:
            await conn.execute(
                "UPDATE department_transfer_requests SET approved_target = ? WHERE message_id = ?",
                (approved_target, message_id),
            )
        await conn.commit()


async def load_department_transfer_request(message_id: int) -> Dict[str, Any] | None:
    async with _get_conn() as conn:
        cursor = await conn.execute(
            """SELECT user_id, target_dept, source_dept, from_academy, data, approved_source, approved_target, created_at
               FROM department_transfer_requests WHERE message_id = ?""",
            (message_id,),
        )
        row = await cursor.fetchone()
    if not row:
        return None
    data = {}
    if row[4]:
        try:
            data = json.loads(row[4])
        except json.JSONDecodeError:
            pass
    return {
        "message_id": message_id,
        "user_id": row[0],
        "target_dept": row[1],
        "source_dept": row[2],
        "from_academy": bool(row[3]),
        "data": data,
        "approved_source": row[5] or 0,
        "approved_target": row[6] or 0,
        "created_at": row[7],
    }


async def delete_department_transfer_request(message_id: int) -> None:
    await delete_request("department_transfer_requests", message_id)


async def load_all_department_transfer_requests() -> Dict[int, Dict[str, Any]]:
    result = {}
    async with _get_conn() as conn:
        cursor = await conn.execute(
            """SELECT message_id, user_id, target_dept, source_dept, from_academy, data, approved_source, approved_target, created_at
               FROM department_transfer_requests"""
        )
        rows = await cursor.fetchall()
    for r in rows:
        try:
            data = json.loads(r[5]) if r[5] else {}
        except json.JSONDecodeError as e:
            logger.warning("Пропуск битой записи department_transfer message_id=%s: %s", r[0], e)
            continue
        result[r[0]] = {
            "message_id": r[0],
            "user_id": r[1],
            "target_dept": r[2],
            "source_dept": r[3],
            "from_academy": bool(r[4]),
            "data": data,
            "approved_source": r[6] or 0,
            "approved_target": r[7] or 0,
            "created_at": r[8],
        }
    return result


# --- Склад: сессии и кулдауны (персистентное состояние) ---

def _session_key_to_str(session_key: Any) -> str:
    """Приводит ключ сессии (int или str) к строке для БД."""
    if isinstance(session_key, str):
        return session_key
    return str(session_key)


async def warehouse_session_get(session_key: Any) -> tuple[list, datetime]:
    """Возвращает (items, created_at) для сессии. Если нет — ([], now)."""
    key = _session_key_to_str(session_key)
    async with _get_conn() as conn:
        cursor = await conn.execute(
            "SELECT items_json, created_at FROM warehouse_sessions WHERE session_key = ?",
            (key,),
        )
        row = await cursor.fetchone()
    if not row:
        return [], datetime.now()
    try:
        items = json.loads(row[0]) if row[0] else []
        created = datetime.fromisoformat(row[1]) if row[1] else datetime.now()
        return items, created
    except (json.JSONDecodeError, ValueError):
        return [], datetime.now()


async def warehouse_session_set(session_key: Any, items: list, created_at: datetime | None = None) -> None:
    key = _session_key_to_str(session_key)
    created = created_at or datetime.now()
    items_json = json.dumps(items, ensure_ascii=False, default=str)
    async with _get_conn() as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO warehouse_sessions (session_key, items_json, created_at) VALUES (?, ?, ?)",
            (key, items_json, created.isoformat()),
        )
        await conn.commit()


async def warehouse_session_delete(session_key: Any) -> None:
    key = _session_key_to_str(session_key)
    async with _get_conn() as conn:
        await conn.execute("DELETE FROM warehouse_sessions WHERE session_key = ?", (key,))
        await conn.commit()


async def warehouse_cooldown_get_all() -> Dict[int, datetime]:
    """Загружает все кулдауны из БД: user_id -> last_issue_at."""
    result = {}
    async with _get_conn() as conn:
        cursor = await conn.execute("SELECT user_id, last_issue_at FROM warehouse_cooldowns")
        rows = await cursor.fetchall()
    for user_id, last_at in rows:
        try:
            result[int(user_id)] = datetime.fromisoformat(last_at) if last_at else datetime.now()
        except (ValueError, TypeError):
            continue
    return result


async def warehouse_cooldown_set(user_id: int, last_issue_at: datetime) -> None:
    async with _get_conn() as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO warehouse_cooldowns (user_id, last_issue_at) VALUES (?, ?)",
            (user_id, last_issue_at.isoformat()),
        )
        await conn.commit()


async def warehouse_cooldown_clear(user_id: int) -> None:
    async with _get_conn() as conn:
        await conn.execute("DELETE FROM warehouse_cooldowns WHERE user_id = ?", (user_id,))
        await conn.commit()


async def warehouse_session_get_all() -> Dict[str, Dict[str, Any]]:
    """Загружает все сессии склада: session_key_str -> {items: list, created_at: datetime}."""
    result = {}
    async with _get_conn() as conn:
        cursor = await conn.execute("SELECT session_key, items_json, created_at FROM warehouse_sessions")
        rows = await cursor.fetchall()
    for key, items_json, created_at in rows:
        try:
            items = json.loads(items_json) if items_json else []
            created = datetime.fromisoformat(created_at) if created_at else datetime.now()
            result[str(key)] = {"items": items, "created_at": created}
        except (json.JSONDecodeError, ValueError):
            continue
    return result