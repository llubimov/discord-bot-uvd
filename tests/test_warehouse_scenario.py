# -*- coding: utf-8 -*-
"""Базовые сценарии склада (WarehouseSession) без Discord."""
import pytest
from datetime import datetime

# Минимальный конфиг предметов для теста
WAREHOUSE_ITEMS_MOCK = {
    "weapons": {
        "items": {"pistol": 1},
        "max_total": 10,
    },
}


@pytest.fixture
def warehouse_items_mock(monkeypatch):
    import data.warehouse_items as wh_data
    monkeypatch.setattr(wh_data, "WAREHOUSE_ITEMS", WAREHOUSE_ITEMS_MOCK)


def test_warehouse_session_get_session_creates_new(warehouse_items_mock):
    """get_session для нового ключа создаёт сессию с пустой корзиной."""
    from services.warehouse_session import WarehouseSession, user_sessions
    user_sessions.clear()
    session = WarehouseSession.get_session(99999)
    assert session["items"] == []
    assert "created_at" in session
    assert 99999 in user_sessions or "99999" in user_sessions


def test_warehouse_session_add_item_appends(warehouse_items_mock):
    """add_item добавляет предмет в корзину и возвращает (True, '')."""
    from services.warehouse_session import WarehouseSession, user_sessions
    user_sessions.clear()
    key = 88888
    ok, msg = WarehouseSession.add_item(key, "weapons", "pistol", 1)
    assert ok is True
    assert msg == ""
    items = WarehouseSession.get_items(key)
    assert len(items) == 1
    assert items[0]["category"] == "weapons" and items[0]["item"] == "pistol" and items[0]["quantity"] == 1
