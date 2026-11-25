"""Все тексты, которые видит пользователь. Разметка HTML."""

from __future__ import annotations

import datetime as dt
from html import escape

from .catalog import Catalog
from .storage import CANCELLED, CONFIRMED, EXPIRED, PAID, PENDING, Booking

BTN_BOOK = "Записаться"
BTN_MY = "Мои записи"
BTN_ABOUT = "О салоне"
BTN_BACK = "« Назад"
BTN_ANY_MASTER = "Любой мастер"
BTN_PAY = "Оплатить онлайн"
BTN_ONSITE = "Оплачу на месте"
BTN_CANCEL_BOOKING = "Отменить запись"
BTN_YES_CANCEL = "Да, отменить"
BTN_NO = "Нет"

WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля",
          "августа", "сентября", "октября", "ноября", "декабря")
STATUS = {PENDING: "ждёт оплаты", CONFIRMED: "оплата на месте", PAID: "оплачено",
          CANCELLED: "отменена", EXPIRED: "не оплачена"}

DEMO_NOTE = (
    "<i>Это демо-бот. Вводите любое имя и выдуманный номер: записи удаляются сами через сутки, "
    "оплата тестовая, деньги не списываются.</i>"
)
WELCOME = "Здравствуйте! Я помогу записаться в {salon}.\n\n" + DEMO_NOTE
CHOOSE_SERVICE = "Выберите услугу:"
CHOOSE_MASTER = "<b>{service}</b>\nВыберите мастера:"
CHOOSE_DAY = "<b>{service}</b>, {master}\nВыберите день:"
CHOOSE_TIME = "<b>{service}</b>, {master}\n{day}. Выберите время:"
NO_DAYS = "К сожалению, в ближайшие две недели свободного времени нет. Попробуйте другого мастера."
SLOT_GONE = "Это время только что заняли. Выберите другое:"
ASK_NAME = "Как вас зовут?\n\nПередумали: /cancel"
ASK_NAME_AGAIN = "На чьё имя записать? Выберите из прошлых записей или напишите новое.\n\nПередумали: /cancel"
ASK_PHONE = "Номер телефона для связи, например <code>+7 900 000-00-00</code>\n\nПередумали: /cancel"
ASK_PHONE_AGAIN = "Номер для связи: выберите из прошлых записей или напишите новый.\n\nПередумали: /cancel"
STALE_BUTTON = "Эта кнопка уже не работает. Начните заново: «Записаться»."
PICKED_NAME = "Имя: <b>{value}</b>"
PICKED_PHONE = "Телефон: <b>{value}</b>"
NOTE = {
    "busy": "Это время уже занято, выберите зелёное.",
    "off": "В этот день мастер не работает.",
    "full": "На этот день всё занято, выберите зелёный день.",
}
BAD_NAME = "Напишите имя буквами, до 40 символов."
BAD_PHONE = "Не похоже на номер. Пример: <code>+7 900 000-00-00</code>"
CONFIRM = "Проверьте запись:\n\n{summary}\n\nКак будете платить?"
CONFIRM_NO_PAY = "Проверьте запись:\n\n{summary}"
BTN_CONFIRM = "Записаться"
BOOKED = "Готово, вы записаны!\n\n{summary}\n\nНапомню за день. Отменить можно в «Мои записи»."
INVOICE_TITLE = "Запись №{id}"
INVOICE_TEXT = "{service}, {when}. Мастер: {master}"
PAY_HINT = "Время держится за вами {minutes} минут. Тестовая карта: <code>1111 1111 1111 1026</code>, срок <code>12/30</code>, CVC <code>000</code>."
PAID_OK = "Оплата прошла, спасибо!\n\n{summary}\n\nНапомню за день."
PAY_EXPIRED = "Время на оплату вышло, запись №{id} снята. Можно записаться снова."
PAY_UNAVAILABLE = "Онлайн-оплата сейчас не работает, время не занято. Можно записаться с оплатой на месте:"
PAY_REFUSED = "Запись уже не ждёт оплаты. Пожалуйста, запишитесь заново."
CANCELLED_TEXT = "Отменил, ничего не записано."
NOTHING_TO_CANCEL = "Отменять нечего."
NO_BOOKINGS = "У вас нет предстоящих записей."
MY_BOOKINGS = "Ваши записи:"
ASK_CANCEL = "Отменить запись?\n\n{summary}"
CANCEL_DONE = "Запись №{id} отменена."
CANCEL_TOO_LATE = "Отменить онлайн можно не позже чем за {hours} ч. Позвоните в салон."
REMINDER = "Напоминаю: завтра у вас запись.\n\n{summary}\n\nЕсли планы изменились, отмените в «Мои записи»."
CANCELLED_BY_SALON = "Салон отменил вашу запись №{id}. Приносим извинения, выберите, пожалуйста, другое время."
ABOUT = "<b>{salon}</b>\n{address}\n\n{services}"
UNKNOWN = "Выберите действие кнопкой внизу."
NOT_ADMIN = UNKNOWN
DAY_EMPTY = "На {day} записей нет."

ADMIN_NEW = "🆕 Новая запись №{id}\n\n{summary}\n{client}\nОплата: {status}"
ADMIN_PAID = "💳 Запись №{id} оплачена онлайн ({price} ₽)."
ADMIN_CANCELLED = "❌ Клиент отменил запись №{id}\n\n{summary}"
ADMIN_PAY_BROKEN = "⚠️ Онлайн-оплата не работает: {error}\nКлиентам предлагается оплата на месте. Проверьте PAYMENT_TOKEN."
ADMIN_CANCELLED_BY_YOU = "Запись №{id} отменена, клиенту отправлено сообщение."


def day(date: dt.date) -> str:
    return f"{WEEKDAYS[date.weekday()]}, {date.day} {MONTHS[date.month - 1]}"


def day_button(date: dt.date, today: dt.date) -> str:
    """«Сегодня, 2 дек», «Завтра, 3 дек», «пт, 4 дек»."""
    label = {0: "Сегодня", 1: "Завтра"}.get((date - today).days, WEEKDAYS[date.weekday()])
    return f"{label}, {date.day} {MONTHS[date.month - 1][:3]}"


def when(start: dt.datetime) -> str:
    return f"{day(start.date())}, {start:%H:%M}"


def summary(booking: Booking, catalog: Catalog) -> str:
    service = catalog.services[booking.service_id]
    master = catalog.masters[booking.master_id]
    return (f"№{booking.id} <b>{escape(service.name)}</b>\n"
            f"{when(booking.start)}, мастер {escape(master.name)}\n"
            f"{service.price} ₽")


def draft(catalog: Catalog, service_id: str, master_name: str, start: dt.datetime, name: str, phone: str) -> str:
    service = catalog.services[service_id]
    return (f"<b>{escape(service.name)}</b>, {service.price} ₽\n"
            f"{when(start)}, мастер {escape(master_name)}\n"
            f"{escape(name)}, {escape(phone)}")


def client(booking: Booking) -> str:
    return f"Клиент: {escape(booking.name)}, {escape(booking.phone)}"


def about(catalog: Catalog) -> str:
    services = "\n".join(f"{escape(s.name)}: {s.minutes} мин, {s.price} ₽" for s in catalog.services.values())
    return ABOUT.format(salon=escape(catalog.name), address=escape(catalog.address), services=services)


def admin_day(date: dt.date, bookings: list[Booking], catalog: Catalog) -> str:
    if not bookings:
        return DAY_EMPTY.format(day=day(date))
    lines = [f"<b>Записи на {day(date)}</b>"]
    for booking in bookings:
        service = catalog.services[booking.service_id].name
        master = catalog.masters[booking.master_id].name
        lines.append(f"{booking.start:%H:%M} {escape(master)}: {escape(service)}, "
                     f"{escape(booking.name)} {escape(booking.phone)} ({STATUS[booking.status]})")
    return "\n".join(lines)
