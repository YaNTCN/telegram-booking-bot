import asyncio
import datetime as dt
import json

import pytest

from bot.catalog import Catalog, Master, Service
from bot.handlers.booking import _phone
from bot.slots import BUSY, FREE, OFF, PAST, days_board, free_starts, times_board
from bot.storage import CONFIRMED, PENDING, Bookings

from .conftest import NOW, TZ

MASTER = Master("m", "Мастер", frozenset({"s"}), {3: (dt.time(10), dt.time(14))})
SERVICE = Service("s", "Услуга", 60, 1000)
WED = NOW.date()


def at(hour, minute=0, date=WED):
    return dt.datetime.combine(date, dt.time(hour, minute), TZ)


def test_free_starts():
    early = NOW.replace(hour=8)
    assert free_starts(MASTER, SERVICE, WED, [], early, 30, 60) == [
        at(10), at(10, 30), at(11), at(11, 30), at(12), at(12, 30), at(13)]
    busy = [(at(11), at(12))]
    assert free_starts(MASTER, SERVICE, WED, busy, early, 30, 60) == [at(10), at(12), at(12, 30), at(13)]
    assert free_starts(MASTER, SERVICE, WED, [], NOW, 30, 60) == [at(11), at(11, 30), at(12), at(12, 30), at(13)]
    assert free_starts(MASTER, SERVICE, WED + dt.timedelta(days=1), [], early, 30, 60) == []


@pytest.mark.parametrize("text, phone", [
    ("89001234567", "+7 900 123-45-67"),
    ("+7 (900) 123-45-67", "+7 900 123-45-67"),
    ("900 123 45 67", "+7 900 123-45-67"),
    ("12345", None), ("+1 202 555 0100", None), ("телефон", None),
])
def test_phone(text, phone):
    assert _phone(text) == phone


def test_catalog_rejects_unknown_service(tmp_path):
    path = tmp_path / "salon.json"
    path.write_text(json.dumps({"name": "x", "services": [], "masters": [
        {"id": "a", "name": "А", "services": ["nope"], "hours": {"1": "10:00-18:00"}}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="nope"):
        Catalog.from_json(path)


def test_storage_overlap_and_hold():
    async def scenario():
        bookings = Bookings(":memory:", TZ)
        await bookings.open()
        common = dict(user_id=1, service_id="s", master_id="m", name="Н", phone="+7", price=1, now=NOW)
        first = await bookings.create(start=at(11), end=at(12), status=PENDING, hold_minutes=15, **common)
        clash = await bookings.create(start=at(11, 30), end=at(12, 30), status=CONFIRMED, **common)
        later = dict(common, now=NOW + dt.timedelta(minutes=20))
        after_hold = await bookings.create(start=at(11, 30), end=at(12, 30), status=CONFIRMED, **later)
        busy = await bookings.busy(["m"], WED, WED, later["now"])
        await bookings.close()
        return first, clash, after_hold, busy

    first, clash, after_hold, busy = asyncio.run(scenario())
    assert first.status == PENDING and first.start == at(11)
    assert clash is None
    assert after_hold is not None
    assert busy == {"m": [(at(11, 30), at(12, 30))]}


class FakeWorksheet:
    """Минимум API gspread.Worksheet, который использует GoogleSheet."""

    def __init__(self):
        self.rows: list[list] = []

    def row_values(self, index):
        return [str(v) for v in self.rows[index - 1]] if index <= len(self.rows) else []

    def insert_row(self, values, index):
        self.rows.insert(index - 1, list(values))

    def append_row(self, values, value_input_option=None):
        self.rows.append(list(values))

    def col_values(self, col):
        return [str(row[col - 1]) for row in self.rows]

    def update_cell(self, row, col, value):
        self.rows[row - 1][col - 1] = value

    def delete_rows(self, index):
        del self.rows[index - 1]


def test_google_sheet_rows():
    from bot.sheets import HEADER, GoogleSheet

    sheet = GoogleSheet.__new__(GoogleSheet)
    sheet._ws = FakeWorksheet()
    sheet._lock = asyncio.Lock()

    async def scenario():
        for booking_id in (1, 2, 3):
            await sheet.add([booking_id, "", "", "", "", "", "", "", 0, "оплата на месте"])
        await sheet.set_status(2, "отменена")
        await sheet.remove([1, 3])

    asyncio.run(scenario())
    assert sheet._ws.rows == [HEADER, [2, "", "", "", "", "", "", "", 0, "отменена"]]


def test_google_sheet_errors_do_not_break_booking(caplog):
    from bot.sheets import GoogleSheet

    class Broken:
        def row_values(self, index):
            raise ConnectionError("Google недоступен")

    sheet = GoogleSheet.__new__(GoogleSheet)
    sheet._ws = Broken()
    sheet._lock = asyncio.Lock()
    asyncio.run(sheet.add([1]))
    assert "Google Таблица" in caplog.text


def test_boards():
    catalog = Catalog("Салон", "", {"s": SERVICE}, {"m": MASTER}, slot_step=60, min_lead=60, days_ahead=2)
    whole_day = {"m": [(at(10), at(14))]}
    assert days_board(catalog, SERVICE, [MASTER], {}, NOW) == [(WED, FREE), (WED + dt.timedelta(days=1), OFF)]
    assert days_board(catalog, SERVICE, [MASTER], whole_day, NOW)[0] == (WED, BUSY)
    busy = {"m": [(at(12), at(13))]}
    assert times_board(catalog, SERVICE, [MASTER], WED, busy, NOW) == [
        (at(10), PAST), (at(11), FREE), (at(12), BUSY), (at(13), FREE)]


def test_recent_values_and_last_choice():
    async def scenario():
        bookings = Bookings(":memory:", TZ)
        await bookings.open()
        for hour, name, master in ((10, "Аня", "m"), (11, "Оля", "m"), (12, "Аня", "x"), (13, "Вика", "m"), (14, "Катя", "m")):
            await bookings.create(user_id=1, service_id="s", master_id=master, start=at(hour), end=at(hour, 30),
                                  name=name, phone="+7", price=1, status=CONFIRMED, now=NOW)
        result = (await bookings.recent(1, "name"), await bookings.recent(2, "name"),
                  await bookings.last_choice(1), await bookings.last_choice(1, "other"))
        await bookings.close()
        return result

    names, nobody, last, none = asyncio.run(scenario())
    assert names == ["Катя", "Вика", "Аня"]
    assert nobody == []
    assert last == ("s", "m")
    assert none is None
