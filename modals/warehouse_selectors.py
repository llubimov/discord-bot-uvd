"""
Совместимость со старым путём импорта.

Раньше селекторы склада лежали в modals/warehouse_selectors.py,
сейчас актуальная реализация находится в views/warehouse_selectors.py.

Этот файл оставлен как прокладка, чтобы старые импорты не ломались.
"""

from views.warehouse_selectors import CategorySelect, ItemSelect

__all__ = ["CategorySelect", "ItemSelect"]