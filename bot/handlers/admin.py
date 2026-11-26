"""Администратор (ADMIN_CHAT_ID): записи на день, отмена записи клиента, повтор возврата денег."""

from __future__ import annotations

import datetime as dt

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject, Filter
from aiogram.types import CallbackQuery, Message, TelegramObject

from .. import texts
from ..keyboards import AdminCancelCb
from ..services import Salon
from ..storage import CANCELLED, CONFIRMED, PAID


class IsAdmin(Filter):
    async def __call__(self, event: TelegramObject, salon: Salon) -> bool:
        admin = salon.config.admin_chat_id
        chat = event.message.chat if isinstance(event, CallbackQuery) and event.message else getattr(event, "chat", None)
        user = getattr(event, "from_user", None)
        return admin is not None and (
            (chat is not None and chat.id == admin) or (user is not None and user.id == admin))


async def day(message: Message, command: CommandObject, salon: Salon) -> None:
    """/day или /day 05.12"""
    today = salon.clock().date()
    date = today
    if command.args:
        try:
            parsed = dt.datetime.strptime(command.args.strip(), "%d.%m")
            date = parsed.date().replace(year=today.year)
        except ValueError:
            await message.answer("Формат: /day 05.12")
            return
    await message.answer(texts.admin_day(date, await salon.bookings.on_day(date), salon.catalog))


async def cancel(callback: CallbackQuery, callback_data: AdminCancelCb, salon: Salon, bot: Bot) -> None:
    booking = await salon.bookings.get(callback_data.id)
    if booking is None or booking.status not in (CONFIRMED, PAID):
        await callback.answer("Запись уже не активна", show_alert=True)
        return
    await salon.bookings.set_status(booking.id, CANCELLED)
    await salon.sheet_status(booking.id, CANCELLED)
    await callback.answer(texts.ADMIN_CANCELLED_BY_YOU.format(id=booking.id), show_alert=True)
    await callback.message.edit_reply_markup(reply_markup=None)
    text = texts.CANCELLED_BY_SALON.format(id=booking.id)
    if booking.status == PAID:  # салон отменил сам: возврат всегда полный
        text += "\n\n" + await salon.refund(bot, booking, booking.price)
    await _send(bot, booking.user_id, text)


async def refund(message: Message, command: CommandObject, salon: Salon, bot: Bot) -> None:
    """/refund 12 или /refund 12 1500: повторить возврат, если автоматический не прошёл."""
    parts = (command.args or "").split()
    if not 1 <= len(parts) <= 2 or not all(part.isdigit() for part in parts):
        await message.answer(texts.REFUND_USAGE)
        return
    booking = await salon.bookings.get(int(parts[0]))
    if booking is None or booking.status != CANCELLED or not booking.payment_id:
        await message.answer(texts.REFUND_NOT_POSSIBLE.format(id=parts[0]))
        return
    amount = min(int(parts[1]), booking.price) if len(parts) == 2 else booking.price
    if amount <= 0:
        await message.answer(texts.REFUND_USAGE)
        return
    await _send(bot, booking.user_id, await salon.refund(bot, booking, amount))


async def _send(bot: Bot, user_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id, text)
    except TelegramAPIError:
        pass  # клиент мог заблокировать бота


def router() -> Router:
    r = Router(name="admin")
    r.message.filter(IsAdmin())
    r.callback_query.filter(IsAdmin())
    r.message.register(day, Command("day"))
    r.message.register(refund, Command("refund"))
    r.callback_query.register(cancel, AdminCancelCb.filter())
    return r
