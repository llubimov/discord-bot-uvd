import os
import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, Any

from config import Config


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

    conn.commit()
    conn.close()


def save_request(table: str, message_id: int, data: Dict[str, Any]):
    conn = _connect()
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
        conn.close()
        raise ValueError(f"Unknown table: {table}")

    conn.commit()
    conn.close()


def delete_request(table: str, message_id: int):
    conn = _connect()
    c = conn.cursor()

    if table not in {"requests", "firing_requests", "promotion_requests", "warehouse_requests"}:
        conn.close()
        raise ValueError(f"Unknown table: {table}")

    c.execute(f"DELETE FROM {table} WHERE message_id = ?", (message_id,))
    conn.commit()
    conn.close()


def _load_all(table: str):
    conn = _connect()
    c = conn.cursor()
    c.execute(f"SELECT message_id, data FROM {table}")
    rows = c.fetchall()
    conn.close()
    return {mid: json.loads(data) for mid, data in rows}


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
    c = conn.cursor()

    for table in ["requests", "firing_requests", "promotion_requests", "warehouse_requests"]:
        c.execute(f"DELETE FROM {table} WHERE created_at < ?", (cutoff,))

    conn.commit()
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