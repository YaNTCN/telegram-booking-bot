"""Оплата через платёжного провайдера Telegram (ЮKassa).

Перед списанием Telegram спрашивает бота, можно ли принять платёж (pre_checkout_query).
Здесь последний шанс отказать: если бронь истекла, деньги не спишутся.
"""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import Message, PreCheckoutQuery

from .. import keyboards, texts
from ..services import Salon
from ..storage import PAID, PENDING


def _booking_id(payload: str) -> int | None:
    prefix, _, value = payload.partition(":")
    return int(value) if prefix == "booking" and value.isdigit() else None


async def pre_checkout(query: PreCheckoutQuery, salon: Salon) -> None:
    booking_id = _booking_id(query.invoice_payload)
    booking = await salon.bookings.get(booking_id) if booking_id else None
    ok = (booking is not None and booking.status == PENDING and booking.hold_until is not None
          and booking.hold_until > salon.clock() and query.total_amount == booking.price * 100)
    if ok:
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message=texts.PAY_REFUSED)


async def paid(message: Message, salon: Salon, bot: Bot) -> None:
    payment = message.successful_payment
    booking_id = _booking_id(payment.invoice_payload)
    if booking_id is None:
        return
    await salon.bookings.set_status(booking_id, PAID, payment_id=payment.provider_payment_charge_id)
    booking = await salon.bookings.get(booking_id)
    summary = texts.summary(booking, salon.catalog)
    await message.answer(texts.PAID_OK.format(summary=summary), reply_markup=keyboards.main_menu())
    await salon.sheet_status(booking_id, PAID)
    await salon.notify_admin(
        bot,
        texts.ADMIN_NEW.format(id=booking.id, summary=summary, client=texts.client(booking),
                               status=texts.STATUS[PAID]),
        keyboards.admin_booking(booking.id),
    )


def router() -> Router:
    r = Router(name="payments")
    r.pre_checkout_query.register(pre_checkout)
    r.message.register(paid, F.successful_payment)
    return r
