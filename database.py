import os
import sqlite3
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any

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


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db():
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS requests (
                message_id INTEGER PRIMARY KEY,
                user_id INTEGER,
                data TEXT,
                created_at TEXT,
                request_type TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS firing_requests (
                message_id INTEGER PRIMARY KEY,
                discord_id INTEGER,
                data TEXT,
                created_at TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS promotion_requests (
                message_id INTEGER PRIMARY KEY,
                discord_id INTEGER,
                data TEXT,
                created_at TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS warehouse_requests (
                message_id INTEGER PRIMARY KEY,
                user_id INTEGER,
                data TEXT,
                created_at TEXT
            )
        """)
        c.execute("""
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
        conn.commit()
    finally:
        conn.close()


def save_request(table: str, message_id: int, data: Dict[str, Any]):
    conn = _connect()
    try:
        c = conn.cursor()
        data_json = json.dumps(data, ensure_ascii=False, default=str)
        created_at = data.get("created_at", datetime.now().isoformat())

        if table == "requests":
            c.execute(
                "INSERT OR REPLACE INTO requests VALUES (?,?,?,?,?)",
                (message_id, data["user_id"], data_json, created_at, data.get("request_type", "")),
            )
        elif table == "firing_requests":
            c.execute(
                "INSERT OR REPLACE INTO firing_requests VALUES (?,?,?,?)",
                (message_id, data["discord_id"], data_json, created_at),
            )
        elif table == "promotion_requests":
            c.execute(
                "INSERT OR REPLACE INTO promotion_requests VALUES (?,?,?,?)",
                (message_id, data["discord_id"], data_json, created_at),
            )
        elif table == "warehouse_requests":
            c.execute(
                "INSERT OR REPLACE INTO warehouse_requests VALUES (?,?,?,?)",
                (message_id, data["user_id"], data_json, created_at),
            )
        else:
            raise ValueError(f"Unknown table: {table}")

        conn.commit()
    finally:
        conn.close()


def delete_request(table: str, message_id: int):
    if table not in {"requests", "firing_requests", "promotion_requests", "warehouse_requests", "department_transfer_requests"}:
        raise ValueError(f"Unknown table: {table}")
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(f"DELETE FROM {table} WHERE message_id = ?", (message_id,))
        conn.commit()
    finally:
        conn.close()


def _load_all(table: str):
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(f"SELECT message_id, data FROM {table}")
        rows = c.fetchall()
        result = {}
        for mid, data in rows:
            try:
                result[mid] = json.loads(data) if data else {}
            except json.JSONDecodeError as e:
                logger.warning("Пропуск битой записи в %s message_id=%s: %s", table, mid, e)
        return result
    finally:
        conn.close()


def load_all_requests():
    return _load_all("requests")


def load_all_firing_requests():
    return _load_all("firing_requests")


def load_all_promotion_requests():
    return _load_all("promotion_requests")


def load_all_warehouse_requests():
    return _load_all("warehouse_requests")


def cleanup_old_requests_db(days: int):
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    conn = _connect()
    try:
        c = conn.cursor()
        for table in ["requests", "firing_requests", "promotion_requests", "warehouse_requests"]:
            c.execute(f"DELETE FROM {table} WHERE created_at < ?", (cutoff,))
        c.execute("DELETE FROM department_transfer_requests WHERE created_at < ?", (cutoff,))
        conn.commit()
    finally:
        conn.close()


# Совместимость со старым кодом (cleanup)
def cleanup_old_requests(days: int):
    cleanup_old_requests_db(days)


def cleanup_old_firing_requests(days: int):
    cleanup_old_requests_db(days)


def cleanup_old_promotion_requests(days: int):
    cleanup_old_requests_db(days)


def cleanup_old_warehouse_requests(days: int):
    cleanup_old_requests_db(days)


# Совместимость со старым кодом (save/delete)
def save_user_request(message_id: int, data: dict):
    save_request("requests", message_id, data)


def delete_user_request(message_id: int):
    delete_request("requests", message_id)


def save_firing_request(message_id: int, data: dict):
    save_request("firing_requests", message_id, data)


def delete_firing_request(message_id: int):
    delete_request("firing_requests", message_id)


def save_promotion_request(message_id: int, data: dict):
    save_request("promotion_requests", message_id, data)


def delete_promotion_request(message_id: int):
    delete_request("promotion_requests", message_id)


def save_warehouse_request(message_id: int, data: dict):
    save_request("warehouse_requests", message_id, data)


def delete_warehouse_request(message_id: int):
    delete_request("warehouse_requests", message_id)


# --- Заявки на перевод между отделами ---

def save_department_transfer_request(message_id: int, payload: Dict[str, Any]):
    conn = _connect()
    try:
        c = conn.cursor()
        data_json = json.dumps(payload.get("data", {}), ensure_ascii=False, default=str)
        from_academy = 1 if payload.get("from_academy") else 0
        c.execute(
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
        conn.commit()
    finally:
        conn.close()


def update_department_transfer_approval(
    message_id: int,
    *,
    approved_source: int | None = None,
    approved_target: int | None = None,
):
    conn = _connect()
    try:
        c = conn.cursor()
        if approved_source is not None:
            c.execute(
                "UPDATE department_transfer_requests SET approved_source = ? WHERE message_id = ?",
                (approved_source, message_id),
            )
        if approved_target is not None:
            c.execute(
                "UPDATE department_transfer_requests SET approved_target = ? WHERE message_id = ?",
                (approved_target, message_id),
            )
        conn.commit()
    finally:
        conn.close()


def load_department_transfer_request(message_id: int) -> Dict[str, Any] | None:
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(
            """SELECT user_id, target_dept, source_dept, from_academy, data, approved_source, approved_target, created_at
               FROM department_transfer_requests WHERE message_id = ?""",
            (message_id,),
        )
        row = c.fetchone()
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
    finally:
        conn.close()


def delete_department_transfer_request(message_id: int):
    delete_request("department_transfer_requests", message_id)


def load_all_department_transfer_requests() -> Dict[int, Dict[str, Any]]:
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(
            """SELECT message_id, user_id, target_dept, source_dept, from_academy, data, approved_source, approved_target, created_at
               FROM department_transfer_requests"""
        )
        rows = c.fetchall()
        result = {}
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
    finally:
        conn.close()