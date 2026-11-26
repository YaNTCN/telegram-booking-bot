"""Общие действия: уведомить админа, отразить запись в таблице, вернуть деньги, текущее время."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from html import escape
from typing import Callable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup

from . import texts
from .catalog import Catalog
from .config import Config
from .refunds import Refund, Refunder
from .sheets import Sheet
from .storage import REFUNDED, Booking, Bookings

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
    refunder: Refunder | None = None

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

    async def refund(self, bot: Bot, booking: Booking, amount: int) -> str:
        """Возвращает деньги за оплаченную онлайн запись. Ответ: текст для клиента."""
        if self.refunder is None:
            result = Refund(False, "автовозврат не настроен (YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)")
        else:
            service = self.catalog.services[booking.service_id]
            result = await self.refunder.refund(booking.payment_id, amount,
                                                f"Отмена записи №{booking.id}: {service.name}")
        if result.ok:
            await self.bookings.set_refunded(booking.id, amount)
            await self.sheet_status(booking.id, REFUNDED)
            await self.notify_admin(bot, texts.ADMIN_REFUNDED.format(id=booking.id, amount=amount))
            return texts.REFUND_DONE.format(id=booking.id, amount=amount)
        log.warning("Возврат по записи %s не прошёл: %s", booking.id, result.error)
        await self.notify_admin(bot, texts.ADMIN_REFUND_FAILED.format(
            id=booking.id, amount=amount, error=escape(result.error), payment=escape(booking.payment_id)))
        return texts.REFUND_MANUAL.format(id=booking.id, amount=amount)
