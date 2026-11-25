"""/start, /cancel, «О салоне» и ответы на всё остальное."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import keyboards, texts
from ..services import Salon


async def start(message: Message, state: FSMContext, salon: Salon) -> None:
    await state.clear()
    await message.answer(texts.WELCOME.format(salon=salon.catalog.name), reply_markup=keyboards.main_menu())


async def cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer(texts.NOTHING_TO_CANCEL, reply_markup=keyboards.main_menu())
        return
    await state.clear()
    await message.answer(texts.CANCELLED_TEXT, reply_markup=keyboards.main_menu())


async def about(message: Message, salon: Salon) -> None:
    await message.answer(texts.about(salon.catalog))


async def unknown(message: Message) -> None:
    await message.answer(texts.UNKNOWN, reply_markup=keyboards.main_menu())


async def stale_button(callback: CallbackQuery) -> None:
    """Кнопка из старого сообщения: шаг уже пройден или бот перезапускался."""
    await callback.answer(texts.STALE_BUTTON, show_alert=True)


def first() -> Router:
    r = Router(name="common")
    r.message.register(start, CommandStart())
    r.message.register(cancel, Command("cancel"))
    r.message.register(about, F.text == texts.BTN_ABOUT)
    return r


def last() -> Router:
    r = Router(name="fallback")
    r.message.register(unknown)
    r.callback_query.register(stale_button)
    return r
