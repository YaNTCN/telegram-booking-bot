"""«Мои записи»: список предстоящих и отмена с подтверждением."""

from __future__ import annotations

import datetime as dt

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import texts
from ..keyboards import BackCb, CancelCb, cancel_sure
from ..services import Salon
from ..storage import CANCELLED, CONFIRMED, PAID


async def my_bookings(message: Message, state: FSMContext, salon: Salon) -> None:
    await state.clear()
    text, markup = await _view(message.from_user.id, salon)
    await message.answer(text, reply_markup=markup)


async def back_to_list(callback: CallbackQuery, salon: Salon) -> None:
    await callback.answer()
    text, markup = await _view(callback.from_user.id, salon)
    await callback.message.edit_text(text, reply_markup=markup)


async def cancel(callback: CallbackQuery, callback_data: CancelCb, salon: Salon, bot: Bot) -> None:
    booking = await salon.bookings.get(callback_data.id)
    if booking is None or booking.user_id != callback.from_user.id or booking.status not in (CONFIRMED, PAID):
        await callback.answer(texts.NO_BOOKINGS, show_alert=True)
        return
    if booking.start - salon.clock() < dt.timedelta(hours=salon.config.cancel_until_hours):
        await callback.answer(texts.CANCEL_TOO_LATE.format(hours=salon.config.cancel_until_hours), show_alert=True)
        return
    summary = texts.summary(booking, salon.catalog)
    refund = booking.price * salon.config.refund_percent // 100 if booking.status == PAID else 0
    if not callback_data.sure:
        text = texts.ASK_CANCEL.format(summary=summary)
        if booking.status == PAID:
            text += texts.ASK_CANCEL_REFUND.format(amount=refund) if refund else texts.ASK_CANCEL_NO_REFUND
        await callback.answer()
        await callback.message.edit_text(text, reply_markup=cancel_sure(booking.id))
        return

    # Статус меняется до возврата: второе нажатие «Да, отменить» уже не пройдёт проверку выше.
    await salon.bookings.set_status(booking.id, CANCELLED)
    await callback.answer(texts.CANCEL_DONE.format(id=booking.id))
    text, markup = await _view(callback.from_user.id, salon)
    await callback.message.edit_text(text, reply_markup=markup)
    await salon.sheet_status(booking.id, CANCELLED)
    await salon.notify_admin(bot, texts.ADMIN_CANCELLED.format(id=booking.id, summary=summary))
    if refund:
        await callback.message.answer(await salon.refund(bot, booking, refund))


async def _view(user_id: int, salon: Salon) -> tuple[str, InlineKeyboardMarkup | None]:
    bookings = await salon.bookings.upcoming(user_id, salon.clock())
    if not bookings:
        return texts.NO_BOOKINGS, None
    builder = InlineKeyboardBuilder()
    for booking in bookings:
        builder.button(text=f"{texts.BTN_CANCEL_BOOKING} №{booking.id}", callback_data=CancelCb(id=booking.id))
    builder.adjust(1)
    body = "\n\n".join(texts.summary(booking, salon.catalog) for booking in bookings)
    return f"{texts.MY_BOOKINGS}\n\n{body}", builder.as_markup()


def router() -> Router:
    r = Router(name="my_bookings")
    r.message.register(my_bookings, F.text == texts.BTN_MY)
    r.callback_query.register(cancel, CancelCb.filter())
    r.callback_query.register(back_to_list, BackCb.filter(F.to == "my"))
    return r
