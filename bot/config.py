"""Настройки из переменных окружения (и файла .env, если он есть)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    token: str
    admin_chat_id: int | None = None
    timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo("Europe/Moscow"))
    salon_path: Path = ROOT / "data" / "salon.json"
    db_path: Path = ROOT / "data" / "bookings.sqlite3"
    payment_token: str = ""
    google_credentials: str = ""
    spreadsheet_id: str = ""
    demo_ttl_hours: int = 24
    hold_minutes: int = 15
    remind_hours: int = 24
    cancel_until_hours: int = 2

    @property
    def payments_on(self) -> bool:
        return bool(self.payment_token)


def load_config() -> Config:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Нет BOT_TOKEN: возьмите токен у @BotFather и положите в .env (см. .env.example)")
    admin = os.getenv("ADMIN_CHAT_ID", "").strip()
    defaults = Config(token)
    return Config(
        token=token,
        admin_chat_id=int(admin) if admin else None,
        timezone=ZoneInfo(os.getenv("TIMEZONE") or "Europe/Moscow"),
        salon_path=Path(os.getenv("SALON_PATH") or defaults.salon_path),
        db_path=Path(os.getenv("DB_PATH") or defaults.db_path),
        payment_token=os.getenv("PAYMENT_TOKEN", "").strip(),
        google_credentials=os.getenv("GOOGLE_CREDENTIALS", "").strip(),
        spreadsheet_id=os.getenv("SPREADSHEET_ID", "").strip(),
        demo_ttl_hours=int(os.getenv("DEMO_TTL_HOURS") or defaults.demo_ttl_hours),
    )
