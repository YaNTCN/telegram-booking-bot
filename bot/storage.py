"""Записи в SQLite.

Время хранится в UTC строками ISO одинакового вида, поэтому их можно сравнивать в SQL.
Двойная запись на одно время исключена: проверка пересечения и вставка идут под одной
блокировкой, между ними не может вклиниться другой обработчик.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import aiosqlite

PENDING, CONFIRMED, PAID, CANCELLED, EXPIRED = "pending_payment", "confirmed", "paid", "cancelled", "expired"
REFUNDED = "refunded"  # отменена, деньги за онлайн-оплату возвращены
ACTIVE = (PENDING, CONFIRMED, PAID)
UTC = dt.timezone.utc

SCHEMA = """
CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    service_id TEXT NOT NULL,
    master_id TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    price INTEGER NOT NULL,
    status TEXT NOT NULL,
    hold_until TEXT,
    payment_id TEXT,
    refunded INTEGER,
    reminded INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS bookings_master_start ON bookings (master_id, starts_at);
CREATE INDEX IF NOT EXISTS bookings_user ON bookings (user_id);
"""


@dataclass(frozen=True)
class Booking:
    id: int
    user_id: int
    service_id: str
    master_id: str
    start: dt.datetime
    end: dt.datetime
    name: str
    phone: str
    price: int
    status: str
    hold_until: dt.datetime | None
    payment_id: str | None
    reminded: bool
    created_at: dt.datetime
    refunded: int | None = None  # сколько рублей вернули


def _iso(moment: dt.datetime) -> str:
    return moment.astimezone(UTC).replace(microsecond=0).isoformat()


class Bookings:
    def __init__(self, path: str | Path, tz: ZoneInfo):
        self._path = str(path)
        self._tz = tz
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def open(self) -> None:
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        async with self._db.execute("PRAGMA table_info(bookings)") as cursor:
            columns = {row["name"] async for row in cursor}
        if "refunded" not in columns:  # база от версии без возвратов
            await self._db.execute("ALTER TABLE bookings ADD COLUMN refunded INTEGER")
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Bookings.open() не вызван")
        return self._db

    async def create(self, *, user_id: int, service_id: str, master_id: str, start: dt.datetime,
                     end: dt.datetime, name: str, phone: str, price: int, status: str,
                     now: dt.datetime, hold_minutes: int = 15) -> Booking | None:
        """Новая запись или None, если время у мастера уже занято."""
        hold_until = _iso(now + dt.timedelta(minutes=hold_minutes)) if status == PENDING else None
        async with self._lock:
            if await self._overlaps(master_id, start, end, now):
                return None
            cursor = await self.db.execute(
                "INSERT INTO bookings (user_id, service_id, master_id, starts_at, ends_at, name, phone, price, "
                "status, hold_until, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, service_id, master_id, _iso(start), _iso(end), name, phone, price,
                 status, hold_until, _iso(now)),
            )
            await self.db.commit()
        return await self.get(cursor.lastrowid)

    async def _overlaps(self, master_id: str, start: dt.datetime, end: dt.datetime, now: dt.datetime) -> bool:
        async with self.db.execute(
            f"SELECT 1 FROM bookings WHERE master_id = ? AND starts_at < ? AND ends_at > ? AND {self._active_sql()} LIMIT 1",
            (master_id, _iso(end), _iso(start), _iso(now)),
        ) as cursor:
            return await cursor.fetchone() is not None

    @staticmethod
    def _active_sql() -> str:
        # Неоплаченная запись держит время только до hold_until.
        return "(status IN ('confirmed', 'paid') OR (status = 'pending_payment' AND hold_until > ?))"

    async def busy(self, master_ids: list[str], date_from: dt.date, date_to: dt.date,
                   now: dt.datetime) -> dict[str, list[tuple[dt.datetime, dt.datetime]]]:
        start = dt.datetime.combine(date_from, dt.time(), self._tz)
        end = dt.datetime.combine(date_to + dt.timedelta(days=1), dt.time(), self._tz)
        marks = ",".join("?" * len(master_ids))
        result: dict[str, list] = {master: [] for master in master_ids}
        async with self.db.execute(
            f"SELECT master_id, starts_at, ends_at FROM bookings WHERE master_id IN ({marks}) "
            f"AND starts_at < ? AND ends_at > ? AND {self._active_sql()}",
            (*master_ids, _iso(end), _iso(start), _iso(now)),
        ) as cursor:
            async for row in cursor:
                result[row["master_id"]].append((self._time(row["starts_at"]), self._time(row["ends_at"])))
        return result

    async def get(self, booking_id: int) -> Booking | None:
        async with self.db.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)) as cursor:
            row = await cursor.fetchone()
        return self._booking(row) if row else None

    async def upcoming(self, user_id: int, now: dt.datetime) -> list[Booking]:
        return await self._select(
            "user_id = ? AND ends_at > ? AND status IN ('confirmed', 'paid') ORDER BY starts_at", user_id, _iso(now))

    async def on_day(self, date: dt.date) -> list[Booking]:
        start = dt.datetime.combine(date, dt.time(), self._tz)
        return await self._select(
            "starts_at >= ? AND starts_at < ? AND status IN ('confirmed', 'paid') ORDER BY starts_at",
            _iso(start), _iso(start + dt.timedelta(days=1)))

    async def recent(self, user_id: int, column: str, limit: int = 3) -> list[str]:
        """Последние разные имена или телефоны, которые клиент вводил, свежие первыми."""
        if column not in ("name", "phone"):
            raise ValueError(column)
        async with self.db.execute(
            f"SELECT {column} FROM bookings WHERE user_id = ? GROUP BY {column} ORDER BY MAX(id) DESC LIMIT ?",
            (user_id, limit),
        ) as cursor:
            return [row[0] async for row in cursor]

    async def last_choice(self, user_id: int, service_id: str | None = None) -> tuple[str, str] | None:
        """(услуга, мастер) из последней записи клиента; с service_id только по этой услуге."""
        where, params = "user_id = ? AND status IN ('confirmed', 'paid', 'cancelled', 'refunded')", [user_id]
        if service_id is not None:
            where += " AND service_id = ?"
            params.append(service_id)
        async with self.db.execute(
            f"SELECT service_id, master_id FROM bookings WHERE {where} ORDER BY id DESC LIMIT 1", params,
        ) as cursor:
            row = await cursor.fetchone()
        return (row[0], row[1]) if row else None

    async def set_status(self, booking_id: int, status: str, payment_id: str | None = None) -> None:
        await self.db.execute(
            "UPDATE bookings SET status = ?, payment_id = COALESCE(?, payment_id), hold_until = NULL WHERE id = ?",
            (status, payment_id, booking_id))
        await self.db.commit()

    async def set_refunded(self, booking_id: int, amount: int) -> None:
        await self.db.execute("UPDATE bookings SET status = 'refunded', refunded = ? WHERE id = ?", (amount, booking_id))
        await self.db.commit()

    async def expire_holds(self, now: dt.datetime) -> list[Booking]:
        expired = await self._select("status = 'pending_payment' AND hold_until <= ?", _iso(now))
        if expired:
            await self.db.execute(
                "UPDATE bookings SET status = 'expired' WHERE status = 'pending_payment' AND hold_until <= ?",
                (_iso(now),))
            await self.db.commit()
        return expired

    async def due_reminders(self, now: dt.datetime, ahead: dt.timedelta) -> list[Booking]:
        return await self._select(
            "reminded = 0 AND status IN ('confirmed', 'paid') AND starts_at > ? AND starts_at <= ? ORDER BY starts_at",
            _iso(now), _iso(now + ahead))

    async def mark_reminded(self, booking_id: int) -> None:
        await self.db.execute("UPDATE bookings SET reminded = 1 WHERE id = ?", (booking_id,))
        await self.db.commit()

    async def purge_created_before(self, moment: dt.datetime) -> list[int]:
        """Удаляет записи целиком, вместе с именем и телефоном."""
        async with self.db.execute("SELECT id FROM bookings WHERE created_at < ?", (_iso(moment),)) as cursor:
            ids = [row["id"] async for row in cursor]
        if ids:
            await self.db.execute("DELETE FROM bookings WHERE created_at < ?", (_iso(moment),))
            await self.db.commit()
        return ids

    async def _select(self, where: str, *params) -> list[Booking]:
        async with self.db.execute(f"SELECT * FROM bookings WHERE {where}", params) as cursor:
            return [self._booking(row) async for row in cursor]

    def _time(self, value: str | None) -> dt.datetime | None:
        return dt.datetime.fromisoformat(value).astimezone(self._tz) if value else None

    def _booking(self, row: aiosqlite.Row) -> Booking:
        return Booking(
            id=row["id"], user_id=row["user_id"], service_id=row["service_id"], master_id=row["master_id"],
            start=self._time(row["starts_at"]), end=self._time(row["ends_at"]), name=row["name"], phone=row["phone"],
            price=row["price"], status=row["status"], hold_until=self._time(row["hold_until"]),
            payment_id=row["payment_id"], reminded=bool(row["reminded"]), created_at=self._time(row["created_at"]),
            refunded=row["refunded"],
        )
