"""Копия записей в Google Таблице для администратора.

Таблица вторична: если Google недоступен, запись всё равно создаётся,
а ошибка уходит в лог. Библиотека gspread синхронная, поэтому вызовы
выполняются в отдельном потоке и не останавливают бота.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

log = logging.getLogger(__name__)

HEADER = ["№", "Создана", "Дата", "Время", "Услуга", "Мастер", "Клиент", "Телефон", "Цена", "Статус"]


class Sheet(Protocol):
    async def add(self, row: list) -> None: ...
    async def set_status(self, booking_id: int, status: str) -> None: ...
    async def remove(self, booking_ids: list[int]) -> None: ...


class NoSheet:
    """Таблица не подключена."""

    async def add(self, row: list) -> None:
        pass

    async def set_status(self, booking_id: int, status: str) -> None:
        pass

    async def remove(self, booking_ids: list[int]) -> None:
        pass


class GoogleSheet:
    def __init__(self, credentials_file: str, spreadsheet_id: str):
        import gspread

        client = gspread.service_account(filename=credentials_file)
        self._ws = client.open_by_key(spreadsheet_id).sheet1
        self._lock = asyncio.Lock()

    async def add(self, row: list) -> None:
        await self._safe(self._add, row)

    async def set_status(self, booking_id: int, status: str) -> None:
        await self._safe(self._set_status, booking_id, status)

    async def remove(self, booking_ids: list[int]) -> None:
        if booking_ids:
            await self._safe(self._remove, set(booking_ids))

    async def _safe(self, func, *args) -> None:
        async with self._lock:
            try:
                await asyncio.to_thread(func, *args)
            except Exception:
                log.exception("Google Таблица: %s не выполнено", func.__name__)

    def _add(self, row: list) -> None:
        if self._ws.row_values(1) != HEADER:
            self._ws.insert_row(HEADER, 1)
        self._ws.append_row(row, value_input_option="USER_ENTERED")

    def _row_of(self, booking_id: int) -> int | None:
        ids = self._ws.col_values(1)
        return ids.index(str(booking_id)) + 1 if str(booking_id) in ids else None

    def _set_status(self, booking_id: int, status: str) -> None:
        if row := self._row_of(booking_id):
            self._ws.update_cell(row, HEADER.index("Статус") + 1, status)

    def _remove(self, booking_ids: set[int]) -> None:
        ids = self._ws.col_values(1)
        # Снизу вверх, чтобы номера оставшихся строк не сдвигались.
        for index in reversed(range(len(ids))):
            if ids[index].isdigit() and int(ids[index]) in booking_ids:
                self._ws.delete_rows(index + 1)
