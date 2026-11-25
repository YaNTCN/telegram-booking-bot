"""Общие действия: уведомить админа, отразить запись в таблице, текущее время."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Callable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup

from . import texts
from .catalog import Catalog
from .config import Config
from .sheets import Sheet
from .storage import Booking, Bookings

log = logging.getLogger(__name__)
Clock = Callable[[], dt.datetime]


@dataclass
class Salon:
    """Всё, что нужно обработчикам. Передаётся в них через контекст диспетчера."""

    config: Config
    catalog: Catalog
    bookings: Bookings
    sheet: Sheet
    clock: Clock

    async def notify_admin(self, bot: Bot, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
        if self.config.admin_chat_id is None:
            return
        try:
            await bot.send_message(self.config.admin_chat_id, text, reply_markup=markup)
        except TelegramAPIError:
            log.warning("Не удалось уведомить администратора", exc_info=True)

    async def to_sheet(self, booking: Booking) -> None:
        service = self.catalog.services[booking.service_id]
        master = self.catalog.masters[booking.master_id]
        await self.sheet.add([
            booking.id, f"{booking.created_at:%d.%m.%Y %H:%M}", f"{booking.start:%d.%m.%Y}",
            f"{booking.start:%H:%M}", service.name, master.name, booking.name, booking.phone,
            booking.price, texts.STATUS[booking.status],
        ])

    async def sheet_status(self, booking_id: int, status: str) -> None:
        await self.sheet.set_status(booking_id, texts.STATUS[status])
