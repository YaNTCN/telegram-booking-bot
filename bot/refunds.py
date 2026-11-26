"""Возврат денег через API ЮKassa.

У Telegram нет метода возврата для оплаты картой, деньги возвращает провайдер.
provider_payment_charge_id из successful_payment и есть id платежа в ЮKassa.
"""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass
from typing import Protocol

import aiohttp

API = "https://api.yookassa.ru/v3/refunds"


@dataclass(frozen=True)
class Refund:
    ok: bool
    error: str = ""


class Refunder(Protocol):
    async def refund(self, payment_id: str, amount: int, description: str) -> Refund: ...


class YooKassa:
    def __init__(self, shop_id: str, secret_key: str, api: str = API, timeout: float = 20):
        self._auth = "Basic " + base64.b64encode(f"{shop_id}:{secret_key}".encode()).decode()
        self._api = api
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def refund(self, payment_id: str, amount: int, description: str) -> Refund:
        body = {
            "payment_id": payment_id,
            "amount": {"value": f"{amount}.00", "currency": "RUB"},
            "description": description[:250],
        }
        # Повтор с тем же ключом (двойное нажатие, /refund после сбоя связи) не вернёт деньги дважды.
        headers = {"Authorization": self._auth, "Idempotence-Key": f"refund-{payment_id}-{amount}"}
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(self._api, json=body, headers=headers) as response:
                    status = response.status
                    raw = await response.text()
        except (aiohttp.ClientError, asyncio.TimeoutError) as error:
            return Refund(False, f"нет ответа от ЮKassa ({type(error).__name__})")
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            return Refund(False, f"ЮKassa ответила HTTP {status}")
        if status >= 400:
            return Refund(False, data.get("description") or f"ЮKassa ответила HTTP {status}")
        if data.get("status") == "canceled":
            reason = (data.get("cancellation_details") or {}).get("reason", "без причины")
            return Refund(False, f"ЮKassa отклонила возврат: {reason}")
        return Refund(True)
