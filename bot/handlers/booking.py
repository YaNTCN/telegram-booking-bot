"""Запись: услуга -> мастер -> день -> время -> имя -> телефон -> подтверждение.

Выбор кнопками идёт в одном сообщении, оно редактируется на каждом шаге.
Свободное время пересчитывается при каждом показе и ещё раз при подтверждении:
пока клиент думал, время мог занять другой.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import logging
import re
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, LabeledPrice, Message

from .. import keyboards, slots, texts
from ..keyboards import ANY, BackCb, ConfirmCb, DayCb, MasterCb, NoteCb, PickCb, ServiceCb, TimeCb
from ..services import Salon
from ..storage import CANCELLED, CONFIRMED, PENDING

log = logging.getLogger(__name__)

_PHONE_RE = re.compile(r"^\+?[\d\s()\-]{10,18}$")
_NAME_RE = re.compile(r"^[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё \-]{0,39}$")


class Book(StatesGroup):
    choosing = State()
    name = State()
    phone = State()
    confirm = State()


async def start(message: Message, state: FSMContext, salon: Salon) -> None:
    await state.clear()
    await state.set_state(Book.choosing)
    await message.answer(texts.CHOOSE_SERVICE, reply_markup=await _services_markup(message.from_user.id, salon))


async def service_chosen(callback: CallbackQuery, callback_data: ServiceCb, state: FSMContext, salon: Salon) -> None:
    await state.update_data(service=callback_data.id)
    await _show_masters(callback, callback_data.id, salon)


async def master_chosen(callback: CallbackQuery, callback_data: MasterCb, state: FSMContext, salon: Salon) -> None:
    await state.update_data(master=callback_data.id)
    await _show_days(callback, await state.get_data(), salon)


async def day_chosen(callback: CallbackQuery, callback_data: DayCb, state: FSMContext, salon: Salon) -> None:
    await state.update_data(date=callback_data.date)
    await _show_times(callback, await state.get_data(), salon)


async def time_chosen(callback: CallbackQuery, callback_data: TimeCb, state: FSMContext, salon: Salon) -> None:
    data = await state.get_data()
    start = _start(data["date"], callback_data.time, salon)
    if start not in await _free_starts(data, salon):
        await _show_times(callback, data, salon, gone=True)
        return
    await state.update_data(time=callback_data.time)
    await state.set_state(Book.name)
    await callback.answer()
    service = salon.catalog.services[data["service"]]
    await _edit(callback, f"<b>{service.name}</b>, {texts.when(start)}, {_master_name(data['master'], salon)}")
    names = await salon.bookings.recent(callback.from_user.id, "name")
    await _ask(callback.message, state, "name", names, texts.ASK_NAME_AGAIN if names else texts.ASK_NAME)


async def back(callback: CallbackQuery, callback_data: BackCb, state: FSMContext, salon: Salon) -> None:
    data = await state.get_data()
    if callback_data.to == "service" or "service" not in data:
        await callback.answer()
        await _edit(callback, texts.CHOOSE_SERVICE, await _services_markup(callback.from_user.id, salon))
    elif callback_data.to == "master":
        await _show_masters(callback, data["service"], salon)
    else:
        await _show_days(callback, data, salon)


async def name_typed(message: Message, state: FSMContext, salon: Salon, bot: Bot) -> None:
    name = " ".join((message.text or "").split())
    if not _NAME_RE.match(name):
        await message.answer(texts.BAD_NAME)
        return
    await _drop_suggestions(bot, message.chat.id, state)
    await _accept_name(message, state, salon, message.from_user.id, name)


async def phone_typed(message: Message, state: FSMContext, salon: Salon, bot: Bot) -> None:
    phone = _phone(message.text or "")
    if phone is None:
        await message.answer(texts.BAD_PHONE)
        return
    await _drop_suggestions(bot, message.chat.id, state)
    await _accept_phone(message, state, salon, phone)


async def picked(callback: CallbackQuery, callback_data: PickCb, state: FSMContext, salon: Salon) -> None:
    """Имя или телефон кнопкой из прошлых записей."""
    expected = {"name": Book.name.state, "phone": Book.phone.state}
    values = (await state.get_data()).get(f"{callback_data.kind}_options", [])
    if await state.get_state() != expected.get(callback_data.kind) or callback_data.index >= len(values):
        await callback.answer(texts.STALE_BUTTON, show_alert=True)
        return
    value = values[callback_data.index]
    await callback.answer()
    template = texts.PICKED_NAME if callback_data.kind == "name" else texts.PICKED_PHONE
    await _edit(callback, template.format(value=escape(value)))
    await state.update_data(prompt=None)
    if callback_data.kind == "name":
        await _accept_name(callback.message, state, salon, callback.from_user.id, value)
    else:
        await _accept_phone(callback.message, state, salon, value)


async def note(callback: CallbackQuery, callback_data: NoteCb) -> None:
    await callback.answer(texts.NOTE.get(callback_data.kind, texts.STALE_BUTTON))


async def _accept_name(target: Message, state: FSMContext, salon: Salon, user_id: int, name: str) -> None:
    await state.update_data(name=name)
    await state.set_state(Book.phone)
    phones = await salon.bookings.recent(user_id, "phone")
    await _ask(target, state, "phone", phones, texts.ASK_PHONE_AGAIN if phones else texts.ASK_PHONE)


async def _accept_phone(target: Message, state: FSMContext, salon: Salon, phone: str) -> None:
    await state.update_data(phone=phone)
    await state.set_state(Book.confirm)
    data = await state.get_data()
    start = _start(data["date"], data["time"], salon)
    summary = texts.draft(salon.catalog, data["service"], _master_name(data["master"], salon), start, data["name"], phone)
    template = texts.CONFIRM if salon.config.payments_on else texts.CONFIRM_NO_PAY
    await target.answer(template.format(summary=summary), reply_markup=keyboards.confirm(salon.config.payments_on))


async def _ask(target: Message, state: FSMContext, kind: str, options: list[str], text: str) -> None:
    """Вопрос с подсказками из прошлых записей. Список лежит в FSM, в кнопке только его номер."""
    prompt = await target.answer(text, reply_markup=keyboards.suggestions(kind, options))
    await state.update_data({f"{kind}_options": options, "prompt": prompt.message_id if options else None})


async def _drop_suggestions(bot: Bot, chat_id: int, state: FSMContext) -> None:
    """Клиент написал сам: убрать кнопки-подсказки у вопроса, чтобы их не нажали позже."""
    prompt = (await state.get_data()).get("prompt")
    if prompt:
        with contextlib.suppress(TelegramBadRequest):
            await bot.edit_message_reply_markup(chat_id=chat_id, message_id=prompt, reply_markup=None)
        await state.update_data(prompt=None)


async def _services_markup(user_id: int, salon: Salon):
    last = await salon.bookings.last_choice(user_id)
    return keyboards.services(list(salon.catalog.services.values()), last=last[0] if last else None)


async def confirmed(callback: CallbackQuery, callback_data: ConfirmCb, state: FSMContext, salon: Salon, bot: Bot) -> None:
    data = await state.get_data()
    online = callback_data.pay == "online" and salon.config.payments_on
    service = salon.catalog.services[data["service"]]
    start = _start(data["date"], data["time"], salon)
    now = salon.clock()

    candidates = [data["master"]] if data["master"] != ANY else [
        master.id for master in salon.catalog.masters_for(service.id)]
    booking = None
    for master_id in candidates:
        booking = await salon.bookings.create(
            user_id=callback.from_user.id, service_id=service.id, master_id=master_id, start=start,
            end=start + dt.timedelta(minutes=service.minutes), name=data["name"], phone=data["phone"],
            price=service.price, status=PENDING if online else CONFIRMED, now=now,
            hold_minutes=salon.config.hold_minutes,
        )
        if booking is not None:
            break
    if booking is None:
        await state.set_state(Book.choosing)
        await _show_times(callback, data, salon, gone=True)
        return

    await callback.answer()
    summary = texts.summary(booking, salon.catalog)
    if online:
        try:
            await bot.send_invoice(
                callback.from_user.id,
                title=texts.INVOICE_TITLE.format(id=booking.id),
                description=texts.INVOICE_TEXT.format(service=service.name, when=texts.when(start),
                                                      master=salon.catalog.masters[booking.master_id].name),
                payload=f"booking:{booking.id}",
                currency="RUB",
                prices=[LabeledPrice(label=service.name, amount=service.price * 100)],
                provider_token=salon.config.payment_token,
            )
        except TelegramBadRequest as error:
            # Например PAYMENT_PROVIDER_INVALID: токен оплаты отозван или ещё не активирован.
            # Бронь снимается сразу, чтобы время не висело занятым, клиенту остаётся оплата на месте.
            log.warning("Счёт не выставлен: %s", error.message)
            await salon.bookings.set_status(booking.id, CANCELLED)
            await _edit(callback, texts.PAY_UNAVAILABLE + "\n\n" + summary, keyboards.confirm(False))
            await salon.notify_admin(bot, texts.ADMIN_PAY_BROKEN.format(error=error.message))
            return
        await state.clear()
        await salon.to_sheet(booking)
        await _edit(callback, texts.CONFIRM_NO_PAY.format(summary=summary))
        await callback.message.answer(texts.PAY_HINT.format(minutes=salon.config.hold_minutes))
        return

    await state.clear()
    await salon.to_sheet(booking)
    await _edit(callback, texts.BOOKED.format(summary=summary))
    await salon.notify_admin(
        bot,
        texts.ADMIN_NEW.format(id=booking.id, summary=summary, client=texts.client(booking),
                               status=texts.STATUS[booking.status]),
        keyboards.admin_booking(booking.id),
    )


async def _show_masters(callback: CallbackQuery, service_id: str, salon: Salon) -> None:
    await callback.answer()
    service = salon.catalog.services[service_id]
    last = await salon.bookings.last_choice(callback.from_user.id, service_id)
    await _edit(callback, texts.CHOOSE_MASTER.format(service=service.name),
                keyboards.masters(salon.catalog.masters_for(service_id), last=last[1] if last else None))


async def _show_days(callback: CallbackQuery, data: dict, salon: Salon) -> None:
    await callback.answer()
    now = salon.clock()
    service, masters = _service_and_masters(data, salon)
    busy = await salon.bookings.busy([m.id for m in masters], now.date(),
                                     now.date() + dt.timedelta(days=salon.catalog.days_ahead), now)
    board = slots.days_board(salon.catalog, service, masters, busy, now)
    title = texts.CHOOSE_DAY.format(service=service.name, master=_master_name(data["master"], salon))
    if all(status != slots.FREE for _, status in board):
        title += "\n\n" + texts.NO_DAYS
    await _edit(callback, title, keyboards.days(board, now.date()))


async def _show_times(callback: CallbackQuery, data: dict, salon: Salon, gone: bool = False) -> None:
    await callback.answer()
    now = salon.clock()
    service, masters = _service_and_masters(data, salon)
    date = dt.datetime.strptime(data["date"], "%Y%m%d").date()
    busy = await salon.bookings.busy([m.id for m in masters], date, date, now)
    board = slots.times_board(salon.catalog, service, masters, date, busy, now)
    text = texts.CHOOSE_TIME.format(service=service.name, master=_master_name(data["master"], salon), day=texts.day(date))
    if gone:
        text = texts.SLOT_GONE + "\n\n" + text
    await _edit(callback, text, keyboards.times(board))


async def _free_starts(data: dict, salon: Salon) -> list[dt.datetime]:
    now = salon.clock()
    service, masters = _service_and_masters(data, salon)
    date = dt.datetime.strptime(data["date"], "%Y%m%d").date()
    busy = await salon.bookings.busy([m.id for m in masters], date, date, now)
    return list(slots.starts_on(salon.catalog, service, masters, date, busy, now))


def _service_and_masters(data: dict, salon: Salon):
    service = salon.catalog.services[data["service"]]
    if data["master"] == ANY:
        return service, salon.catalog.masters_for(service.id)
    return service, [salon.catalog.masters[data["master"]]]


def _master_name(master_id: str, salon: Salon) -> str:
    return texts.BTN_ANY_MASTER.lower() if master_id == ANY else salon.catalog.masters[master_id].name


def _start(date: str, time: str, salon: Salon) -> dt.datetime:
    naive = dt.datetime.strptime(date + time, "%Y%m%d%H%M")
    return naive.replace(tzinfo=salon.config.timezone)


def _phone(text: str) -> str | None:
    if not _PHONE_RE.match(text.strip()):
        return None
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and digits[0] in "78":
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return f"+7 {digits[:3]} {digits[3:6]}-{digits[6:8]}-{digits[8:]}"


async def _edit(callback: CallbackQuery, text: str, markup=None) -> None:
    if isinstance(callback.message, Message):
        await callback.message.edit_text(text, reply_markup=markup)


def router() -> Router:
    r = Router(name="booking")
    r.message.register(start, F.text == texts.BTN_BOOK)
    r.callback_query.register(service_chosen, Book.choosing, ServiceCb.filter())
    r.callback_query.register(master_chosen, Book.choosing, MasterCb.filter())
    r.callback_query.register(day_chosen, Book.choosing, DayCb.filter())
    r.callback_query.register(time_chosen, Book.choosing, TimeCb.filter())
    r.callback_query.register(back, StateFilter(Book.choosing), BackCb.filter(F.to.in_({"service", "master", "day"})))
    r.callback_query.register(picked, StateFilter(Book.name, Book.phone), PickCb.filter())
    r.callback_query.register(note, NoteCb.filter())
    r.message.register(name_typed, Book.name, F.text)
    r.message.register(phone_typed, Book.phone, F.text)
    r.callback_query.register(confirmed, Book.confirm, ConfirmCb.filter())
    return r
