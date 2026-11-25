"""Бот в тестах: настоящий Dispatcher, вместо Telegram сессия, которая записывает вызовы API."""

from __future__ import annotations

import asyncio
import datetime as dt
import itertools
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import GetMe, SendInvoice, SendMessage, TelegramMethod
from aiogram.types import (
    CallbackQuery, Chat, Message, PreCheckoutQuery, SuccessfulPayment, Update, User,
)

from bot.app import build_dispatcher, create_bot
from bot.catalog import Catalog
from bot.config import Config
from bot.services import Salon
from bot.storage import Bookings

SALON = Path(__file__).resolve().parent.parent / "data" / "salon.json"
TZ = ZoneInfo("Europe/Moscow")
NOW = dt.datetime(2026, 12, 2, 10, 0, tzinfo=TZ)  # среда
BOT_USER = User(id=42, is_bot=True, first_name="Demo", username="demo_booking_bot")
ADMIN = 777


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod] = []
        self._ids = itertools.count(1000)
        self.invoice_error: str | None = None

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, SendInvoice) and self.invoice_error:
            raise TelegramBadRequest(method=method, message=self.invoice_error)
        if isinstance(method, GetMe):
            return BOT_USER
        if isinstance(method, (SendMessage, SendInvoice)):
            return Message(message_id=next(self._ids), date=NOW, chat=Chat(id=method.chat_id, type="private"),
                           from_user=BOT_USER, text=getattr(method, "text", None))
        return True

    async def stream_content(self, *args, **kwargs):
        raise NotImplementedError
        yield b""  # pragma: no cover

    async def close(self) -> None:
        pass


class FakeSheet:
    def __init__(self) -> None:
        self.rows: dict[int, list] = {}

    async def add(self, row: list) -> None:
        self.rows[row[0]] = row

    async def set_status(self, booking_id: int, status: str) -> None:
        self.rows[booking_id][-1] = status

    async def remove(self, booking_ids: list[int]) -> None:
        for booking_id in booking_ids:
            self.rows.pop(booking_id, None)


class Harness:
    def __init__(self, payments: bool = True) -> None:
        self.loop = asyncio.new_event_loop()
        self.now = NOW
        self.bookings = Bookings(":memory:", TZ)
        self.run(self.bookings.open())
        self.sheet = FakeSheet()
        config = Config("42:TEST", admin_chat_id=ADMIN, timezone=TZ,
                        payment_token="TEST:provider" if payments else "")
        self.salon = Salon(config, Catalog.from_json(SALON), self.bookings, self.sheet, clock=lambda: self.now)
        self.session = FakeSession()
        self.bot = create_bot("42:TEST", session=self.session)
        self.dp = build_dispatcher(self.salon)
        self._ids = itertools.count(1)

    def run(self, coro):
        return self.loop.run_until_complete(coro)

    def close(self) -> None:
        self.run(self.bookings.close())
        self.loop.close()

    def _feed(self, **event) -> list[TelegramMethod]:
        before = len(self.session.calls)
        self.run(self.dp.feed_update(self.bot, Update(update_id=next(self._ids), **event)))
        return self.session.calls[before:]

    @staticmethod
    def user(user_id: int) -> User:
        return User(id=user_id, is_bot=False, first_name="Клиент")

    def _message(self, user_id: int, **fields) -> Message:
        return Message(message_id=next(self._ids), date=self.now, chat=Chat(id=user_id, type="private"),
                       from_user=self.user(user_id), **fields)

    def send(self, text: str, user_id: int = 1) -> list[TelegramMethod]:
        return self._feed(message=self._message(user_id, text=text))

    def press(self, data: str, user_id: int = 1) -> list[TelegramMethod]:
        message = Message(message_id=500, date=self.now, text="…", chat=Chat(id=user_id, type="private"),
                          from_user=BOT_USER)
        callback = CallbackQuery(id=str(next(self._ids)), from_user=self.user(user_id),
                                 chat_instance="test", data=data, message=message)
        return self._feed(callback_query=callback)

    def pre_checkout(self, payload: str, amount: int, user_id: int = 1) -> list[TelegramMethod]:
        query = PreCheckoutQuery(id=str(next(self._ids)), from_user=self.user(user_id), currency="RUB",
                                 total_amount=amount, invoice_payload=payload)
        return self._feed(pre_checkout_query=query)

    def pay(self, payload: str, amount: int, user_id: int = 1) -> list[TelegramMethod]:
        payment = SuccessfulPayment(currency="RUB", total_amount=amount, invoice_payload=payload,
                                    telegram_payment_charge_id="tg-1", provider_payment_charge_id="yk-1")
        return self._feed(message=self._message(user_id, successful_payment=payment))


@pytest.fixture
def harness():
    h = Harness()
    yield h
    h.close()


@pytest.fixture
def no_payments():
    h = Harness(payments=False)
    yield h
    h.close()


def texts_of(calls) -> list[str]:
    return [call.text for call in calls if isinstance(getattr(call, "text", None), str)]


def buttons(call) -> list[str]:
    return [button.callback_data for row in call.reply_markup.inline_keyboard for button in row]


def grid(call) -> list[list[tuple]]:
    """Клавиатура рядами: (текст, цвет или disabled, callback_data)."""
    return [[(b.text, "disabled" if b.disabled else (b.style.value if hasattr(b.style, "value") else b.style),
              b.callback_data) for b in row] for row in call.reply_markup.inline_keyboard]


def last_edit(calls):
    from aiogram.methods import EditMessageText
    return [call for call in calls if isinstance(call, EditMessageText)][-1]
