"""Фоновые задачи раз в минуту: снять неоплаченные брони, напомнить о записи, удалить демо-данные.

Состояние хранится в базе (флаг reminded, статусы), поэтому после перезапуска
бот не напомнит дважды и не забудет напомнить.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from . import texts
from .services import Salon
from .storage import EXPIRED

log = logging.getLogger(__name__)


async def tick(bot: Bot, salon: Salon) -> None:
    now = salon.clock()

    for booking in await salon.bookings.expire_holds(now):
        await salon.sheet_status(booking.id, EXPIRED)
        await _send(bot, booking.user_id, texts.PAY_EXPIRED.format(id=booking.id))

    ahead = dt.timedelta(hours=salon.config.remind_hours)
    for booking in await salon.bookings.due_reminders(now, ahead):
        # Записавшимся меньше чем за сутки напоминание не нужно: они только что всё видели.
        if booking.start - booking.created_at > ahead:
            await _send(bot, booking.user_id, texts.REMINDER.format(summary=texts.summary(booking, salon.catalog)))
        await salon.bookings.mark_reminded(booking.id)

    if salon.config.demo_ttl_hours > 0:
        removed = await salon.bookings.purge_created_before(now - dt.timedelta(hours=salon.config.demo_ttl_hours))
        if removed:
            await salon.sheet.remove(removed)
            log.info("Демо: удалено записей %d", len(removed))


async def run(bot: Bot, salon: Salon, every: float = 60) -> None:
    while True:
        try:
            await tick(bot, salon)
        except Exception:
            log.exception("Фоновая задача упала, повторю через минуту")
        await asyncio.sleep(every)


async def _send(bot: Bot, user_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id, text)
    except TelegramAPIError:
        log.info("Не доставлено пользователю %s", user_id)
