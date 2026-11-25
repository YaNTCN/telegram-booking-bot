"""Клавиатуры и данные кнопок (CallbackData с префиксами)."""

from __future__ import annotations

import datetime as dt

from aiogram.enums import ButtonStyle
from aiogram.filters.callback_data import CallbackData
from aiogram.types import DisabledButton, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from . import texts
from .catalog import Master, Service
from .slots import BUSY, FREE, PAST
from .storage import Booking

ANY = "any"


class ServiceCb(CallbackData, prefix="svc"):
    id: str


class MasterCb(CallbackData, prefix="mst"):
    id: str


class DayCb(CallbackData, prefix="day"):
    date: str  # ГГГГММДД


class TimeCb(CallbackData, prefix="tm"):
    time: str  # ЧЧММ: двоеточие занято разделителем CallbackData


class NoteCb(CallbackData, prefix="note"):
    """Кнопка, которая ничего не выбирает, а объясняет: занято, выходной, уже прошло."""

    kind: str


class PickCb(CallbackData, prefix="pick"):
    """Имя или телефон из прошлых записей: номер в списке, сам список лежит в FSM."""

    kind: str
    index: int


class BackCb(CallbackData, prefix="back"):
    to: str


class ConfirmCb(CallbackData, prefix="ok"):
    pay: str  # online | onsite


class CancelCb(CallbackData, prefix="cnl"):
    id: int
    sure: bool = False


class AdminCancelCb(CallbackData, prefix="adm"):
    id: int


def main_menu() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text=texts.BTN_BOOK)
    builder.button(text=texts.BTN_MY)
    builder.button(text=texts.BTN_ABOUT)
    builder.adjust(1, 2)
    return builder.as_markup(resize_keyboard=True, is_persistent=True)


def services(items: list[Service], last: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for service in items:
        label = f"{service.name}, {service.price} ₽"
        builder.button(**_remembered(label, service.id == last), callback_data=ServiceCb(id=service.id))
    builder.adjust(1)
    return builder.as_markup()


def masters(items: list[Master], last: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for master in items:
        builder.button(**_remembered(master.name, master.id == last), callback_data=MasterCb(id=master.id))
    if len(items) > 1:
        builder.button(text=texts.BTN_ANY_MASTER, callback_data=MasterCb(id=ANY))
    builder.adjust(2)
    return _with_back(builder, "service")


def days(board: list[tuple[dt.date, str]], today: dt.date) -> InlineKeyboardMarkup:
    """Две колонки слева направо: зелёный день можно выбрать, красный занят или выходной."""
    builder = InlineKeyboardBuilder()
    for date, status in board:
        label = texts.day_button(date, today)
        if status == FREE:
            builder.button(text=label, style=ButtonStyle.SUCCESS, callback_data=DayCb(date=f"{date:%Y%m%d}"))
        else:
            kind = "full" if status == BUSY else status
            builder.button(text=label, style=ButtonStyle.DANGER, callback_data=NoteCb(kind=kind))
    builder.adjust(2)
    return _with_back(builder, "master")


def times(board: list[tuple[dt.datetime, str]]) -> InlineKeyboardMarkup:
    """Вся сетка дня: свободное зелёное, занятое красное, прошедшее неактивно."""
    builder = InlineKeyboardBuilder()
    for start, status in board:
        label = f"{start:%H:%M}"
        if status == FREE:
            builder.button(text=label, style=ButtonStyle.SUCCESS, callback_data=TimeCb(time=f"{start:%H%M}"))
        elif status == PAST:
            builder.button(text=label, disabled=DisabledButton())  # не нажимается вовсе
        else:
            builder.button(text=label, style=ButtonStyle.DANGER, callback_data=NoteCb(kind=status))
    builder.adjust(4)
    return _with_back(builder, "day")


def suggestions(kind: str, values: list[str]) -> InlineKeyboardMarkup | None:
    if not values:
        return None
    builder = InlineKeyboardBuilder()
    for index, value in enumerate(values):
        builder.button(text=value, callback_data=PickCb(kind=kind, index=index))
    builder.adjust(1)
    return builder.as_markup()


def confirm(payments_on: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if payments_on:
        builder.button(text=texts.BTN_PAY, callback_data=ConfirmCb(pay="online"))
        builder.button(text=texts.BTN_ONSITE, callback_data=ConfirmCb(pay="onsite"))
    else:
        builder.button(text=texts.BTN_CONFIRM, callback_data=ConfirmCb(pay="onsite"))
    builder.adjust(1)
    return builder.as_markup()


def my_booking(booking: Booking) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BTN_CANCEL_BOOKING, callback_data=CancelCb(id=booking.id))
    return builder.as_markup()


def cancel_sure(booking_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BTN_NO, callback_data=BackCb(to="my"))
    builder.button(text=texts.BTN_YES_CANCEL, callback_data=CancelCb(id=booking_id, sure=True))
    return builder.as_markup()


def admin_booking(booking_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BTN_CANCEL_BOOKING, callback_data=AdminCancelCb(id=booking_id))
    return builder.as_markup()


def _remembered(label: str, is_last: bool) -> dict:
    if is_last:
        return {"text": f"⭐ {label}", "style": ButtonStyle.PRIMARY}
    return {"text": label}


def _with_back(builder: InlineKeyboardBuilder, to: str) -> InlineKeyboardMarkup:
    builder.row(InlineKeyboardButton(text=texts.BTN_BACK, callback_data=BackCb(to=to).pack()))
    return builder.as_markup()
