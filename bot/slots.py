"""Свободное время: рабочие часы мастера минус занятые записи.

Чистые функции без базы и Telegram, поэтому легко проверяются тестами.
"""

from __future__ import annotations

import datetime as dt
from typing import Iterable

from .catalog import Catalog, Master, Service

Busy = tuple[dt.datetime, dt.datetime]


def free_starts(master: Master, service: Service, date: dt.date, busy: Iterable[Busy],
                now: dt.datetime, step: int, min_lead: int) -> list[dt.datetime]:
    """Начала, в которые услуга целиком помещается в рабочее время и не задевает занятое."""
    earliest = now + dt.timedelta(minutes=min_lead)
    length = dt.timedelta(minutes=service.minutes)
    busy = list(busy)
    return [start for start in day_starts(master, service, date, now.tzinfo, step)
            if start >= earliest and not any(b_start < start + length and start < b_end for b_start, b_end in busy)]


FREE, BUSY, PAST, OFF = "free", "busy", "past", "off"


def day_starts(master: Master, service: Service, date: dt.date, tz, step: int) -> list[dt.datetime]:
    """Все начала по сетке, при которых услуга помещается в рабочее время, без учёта занятости."""
    hours = master.works(date)
    if hours is None:
        return []
    start = dt.datetime.combine(date, hours[0], tz)
    closes = dt.datetime.combine(date, hours[1], tz)
    result = []
    while start + dt.timedelta(minutes=service.minutes) <= closes:
        result.append(start)
        start += dt.timedelta(minutes=step)
    return result


def days_board(catalog: Catalog, service: Service, masters: list[Master],
               busy: dict[str, list[Busy]], now: dt.datetime) -> list[tuple[dt.date, str]]:
    """Каждый день с сегодняшнего: есть свободное время, всё занято или никто не работает."""
    board = []
    for offset in range(catalog.days_ahead):
        date = now.date() + dt.timedelta(days=offset)
        working = [master for master in masters if master.works(date)]
        if not working:
            board.append((date, OFF))
        elif starts_on(catalog, service, working, date, busy, now):
            board.append((date, FREE))
        else:
            board.append((date, BUSY))
    return board


def times_board(catalog: Catalog, service: Service, masters: list[Master], date: dt.date,
                busy: dict[str, list[Busy]], now: dt.datetime) -> list[tuple[dt.datetime, str]]:
    """Вся сетка дня: свободно, занято или уже поздно записываться."""
    free = starts_on(catalog, service, masters, date, busy, now)
    earliest = now + dt.timedelta(minutes=catalog.min_lead)
    grid = sorted({start for master in masters
                   for start in day_starts(master, service, date, now.tzinfo, catalog.slot_step)})
    return [(start, FREE if start in free else PAST if start < earliest else BUSY) for start in grid]


def starts_on(catalog: Catalog, service: Service, masters: list[Master], date: dt.date,
              busy: dict[str, list[Busy]], now: dt.datetime) -> dict[dt.datetime, list[str]]:
    """Время начала -> мастера, свободные в это время (для варианта «любой мастер»)."""
    result: dict[dt.datetime, list[str]] = {}
    for master in masters:
        for start in free_starts(master, service, date, busy.get(master.id, []), now,
                                 catalog.slot_step, catalog.min_lead):
            result.setdefault(start, []).append(master.id)
    return dict(sorted(result.items()))
