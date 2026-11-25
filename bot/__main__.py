"""Запуск: python -m bot"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging

from aiogram.types import BotCommand

from . import jobs
from .app import build_dispatcher, create_bot
from .catalog import Catalog
from .config import load_config
from .services import Salon
from .sheets import GoogleSheet, NoSheet
from .storage import Bookings

log = logging.getLogger("bot")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = load_config()
    catalog = Catalog.from_json(config.salon_path)
    bookings = Bookings(config.db_path, config.timezone)
    await bookings.open()

    sheet = NoSheet()
    if config.google_credentials and config.spreadsheet_id:
        sheet = GoogleSheet(config.google_credentials, config.spreadsheet_id)
        log.info("Google Таблица подключена")
    payments = "нет"
    if config.payments_on:
        payments = "тестовая" if ":TEST:" in config.payment_token else "боевая (настоящие деньги)"
    log.info("Оплата онлайн: %s, админ: %s", payments, config.admin_chat_id or "не задан")

    salon = Salon(config, catalog, bookings, sheet, clock=lambda: dt.datetime.now(config.timezone))
    bot = create_bot(config.token)
    dp = build_dispatcher(salon)
    background = asyncio.create_task(jobs.run(bot, salon))
    try:
        with contextlib.suppress(Exception):
            await bot.set_my_commands([BotCommand(command="start", description="Главное меню"),
                                       BotCommand(command="cancel", description="Отменить ввод")])
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        background.cancel()
        await bookings.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
