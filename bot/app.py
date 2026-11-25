"""Сборка бота: роутеры в нужном порядке и обработчик ошибок."""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

from .handlers import admin, booking, common, my_bookings, payments
from .services import Salon

log = logging.getLogger(__name__)
ERROR_TEXT = "Что-то пошло не так. Попробуйте ещё раз или начните заново: /start"


def create_bot(token: str, **kwargs) -> Bot:
    return Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML), **kwargs)


def build_dispatcher(salon: Salon, storage: BaseStorage | None = None) -> Dispatcher:
    dp = Dispatcher(storage=storage or MemoryStorage(), salon=salon)
    dp.include_routers(
        common.first(),
        payments.router(),
        admin.router(),
        # Кнопки меню раньше шагов записи: «Мои записи» на шаге имени не должно стать именем.
        my_bookings.router(),
        booking.router(),
        common.last(),
    )
    dp.errors.register(on_error)
    return dp


async def on_error(event: ErrorEvent) -> bool:
    log.exception("Ошибка при обработке события %s", event.update.update_id, exc_info=event.exception)
    update = event.update
    try:
        if update.callback_query:
            await update.callback_query.answer(ERROR_TEXT, show_alert=True)
        elif update.message:
            await update.message.answer(ERROR_TEXT)
    except Exception:
        log.warning("Не удалось сообщить пользователю об ошибке", exc_info=True)
    return True
