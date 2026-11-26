"""Возврат денег при отмене оплаченной записи и клиент API ЮKassa."""

import asyncio
import datetime as dt

from aiohttp import web
from aiogram.methods import SendMessage

from bot import texts
from bot.keyboards import AdminCancelCb, CancelCb, ConfirmCb
from bot.refunds import Refund, YooKassa
from bot.storage import CANCELLED, REFUNDED, Bookings

from .conftest import ADMIN, TZ, Harness, last_edit, texts_of
from .test_flows import go_to_confirm


def paid_booking(h: Harness) -> None:
    """Запись №1 (стрижка, 1500 ₽) оплачена онлайн, до визита больше суток."""
    go_to_confirm(h)
    h.press(ConfirmCb(pay="online").pack())
    h.pay("booking:1", 150000)
    h.now = dt.datetime(2026, 12, 1, 12, 0, tzinfo=TZ)


def to_admin(calls) -> list[str]:
    return [c.text for c in calls if isinstance(c, SendMessage) and c.chat_id == ADMIN]


def test_client_cancel_refunds_in_full(harness):
    paid_booking(harness)
    ask = last_edit(harness.press(CancelCb(id=1).pack()))
    assert ask.text.endswith(texts.ASK_CANCEL_REFUND.format(amount=1500))

    calls = harness.press(CancelCb(id=1, sure=True).pack())
    assert harness.refunder.calls == [("yk-1", 1500)]
    booking = harness.run(harness.bookings.get(1))
    assert (booking.status, booking.refunded) == (REFUNDED, 1500)
    assert harness.sheet.rows[1][-1] == texts.STATUS[REFUNDED]
    assert texts.REFUND_DONE.format(id=1, amount=1500) in texts_of(calls)
    assert texts.ADMIN_REFUNDED.format(id=1, amount=1500) in to_admin(calls)

    harness.press(CancelCb(id=1, sure=True).pack())  # повторное нажатие
    assert len(harness.refunder.calls) == 1


def test_client_cancel_partial_and_zero_percent():
    h = Harness(refund_percent=50)
    try:
        paid_booking(h)
        assert last_edit(h.press(CancelCb(id=1).pack())).text.endswith(texts.ASK_CANCEL_REFUND.format(amount=750))
        h.press(CancelCb(id=1, sure=True).pack())
        assert h.refunder.calls == [("yk-1", 750)]
    finally:
        h.close()

    h = Harness(refund_percent=0)
    try:
        paid_booking(h)
        assert last_edit(h.press(CancelCb(id=1).pack())).text.endswith(texts.ASK_CANCEL_NO_REFUND)
        h.press(CancelCb(id=1, sure=True).pack())
        assert h.refunder.calls == []
        assert h.run(h.bookings.get(1)).status == CANCELLED
    finally:
        h.close()


def test_onsite_booking_cancel_does_not_refund(harness):
    go_to_confirm(harness)
    harness.press(ConfirmCb(pay="onsite").pack())
    harness.now = dt.datetime(2026, 12, 1, 12, 0, tzinfo=TZ)
    assert not last_edit(harness.press(CancelCb(id=1).pack())).text.endswith(texts.ASK_CANCEL_NO_REFUND)
    harness.press(CancelCb(id=1, sure=True).pack())
    assert harness.refunder.calls == []


def test_failed_refund_tells_admin_and_retry_works(harness):
    paid_booking(harness)
    harness.refunder.result = Refund(False, "нет ответа от ЮKassa (ClientConnectorError)")
    calls = harness.press(CancelCb(id=1, sure=True).pack())
    assert harness.run(harness.bookings.get(1)).status == CANCELLED
    assert texts.REFUND_MANUAL.format(id=1, amount=1500) in texts_of(calls)
    [failed] = [t for t in to_admin(calls) if t.startswith("⚠️")]
    assert "<code>yk-1</code>" in failed and "/refund 1" in failed

    assert texts_of(harness.send("/refund 1", user_id=2)) == [texts.UNKNOWN]
    assert texts_of(harness.send("/refund x", user_id=ADMIN)) == [texts.REFUND_USAGE]
    harness.refunder.result = Refund(True)
    calls = harness.send("/refund 1 1000", user_id=ADMIN)
    assert harness.refunder.calls[-1] == ("yk-1", 1000)
    assert harness.run(harness.bookings.get(1)).refunded == 1000
    assert any(isinstance(c, SendMessage) and c.chat_id == 1 and "1000 ₽" in c.text for c in calls)
    assert texts_of(harness.send("/refund 1", user_id=ADMIN)) == [texts.REFUND_NOT_POSSIBLE.format(id=1)]


def test_salon_cancel_refunds_in_full_regardless_of_percent():
    h = Harness(refund_percent=0)
    try:
        paid_booking(h)
        calls = h.press(AdminCancelCb(id=1).pack(), user_id=ADMIN)
        assert h.refunder.calls == [("yk-1", 1500)]
        [to_client] = [c.text for c in calls if isinstance(c, SendMessage) and c.chat_id == 1]
        assert to_client.startswith(texts.CANCELLED_BY_SALON.format(id=1))
        assert texts.REFUND_DONE.format(id=1, amount=1500) in to_client
    finally:
        h.close()


def test_without_refunder_admin_refunds_by_hand(harness):
    harness.salon.refunder = None
    paid_booking(harness)
    calls = harness.press(CancelCb(id=1, sure=True).pack())
    assert any("автовозврат не настроен" in t for t in to_admin(calls))


def test_old_database_gets_refunded_column(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE bookings (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, "
                   "service_id TEXT NOT NULL, master_id TEXT NOT NULL, starts_at TEXT NOT NULL, ends_at TEXT NOT NULL, "
                   "name TEXT NOT NULL, phone TEXT NOT NULL, price INTEGER NOT NULL, status TEXT NOT NULL, "
                   "hold_until TEXT, payment_id TEXT, reminded INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)")
        db.execute("INSERT INTO bookings (user_id, service_id, master_id, starts_at, ends_at, name, phone, price, "
                   "status, payment_id, created_at) VALUES (1, 'cut', 'anna', '2026-12-01T08:00:00+00:00', "
                   "'2026-12-01T09:00:00+00:00', 'А', '+7', 1500, 'cancelled', 'yk-9', '2026-11-30T08:00:00+00:00')")

    async def check():
        bookings = Bookings(path, TZ)
        await bookings.open()
        try:
            await bookings.set_refunded(1, 1500)
            return await bookings.get(1)
        finally:
            await bookings.close()

    booking = asyncio.run(check())
    assert (booking.status, booking.refunded, booking.payment_id) == (REFUNDED, 1500, "yk-9")


def run_yookassa(handler, payment_id="pay-1", amount=1500):
    """Поднимает локальный сервер вместо api.yookassa.ru и делает один возврат."""
    seen = {}

    async def endpoint(request):
        seen["auth"] = request.headers.get("Authorization")
        seen["key"] = request.headers.get("Idempotence-Key")
        seen["body"] = await request.json()
        return handler()

    async def go():
        app = web.Application()
        app.router.add_post("/v3/refunds", endpoint)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = runner.addresses[0][1]
        try:
            client = YooKassa("shop", "secret", api=f"http://127.0.0.1:{port}/v3/refunds")
            return await client.refund(payment_id, amount, "Отмена записи №1")
        finally:
            await runner.cleanup()

    return asyncio.run(go()), seen


def test_yookassa_request_and_answers():
    result, seen = run_yookassa(lambda: web.json_response({"id": "r-1", "status": "succeeded"}))
    assert result == Refund(True)
    assert seen["auth"] == "Basic c2hvcDpzZWNyZXQ="  # shop:secret
    assert seen["key"] == "refund-pay-1-1500"
    assert seen["body"] == {"payment_id": "pay-1", "amount": {"value": "1500.00", "currency": "RUB"},
                            "description": "Отмена записи №1"}

    result, _ = run_yookassa(lambda: web.json_response(
        {"type": "error", "description": "Payment not found"}, status=404))
    assert result == Refund(False, "Payment not found")

    result, _ = run_yookassa(lambda: web.json_response(
        {"status": "canceled", "cancellation_details": {"reason": "insufficient_funds"}}))
    assert result == Refund(False, "ЮKassa отклонила возврат: insufficient_funds")

    result, _ = run_yookassa(lambda: web.Response(text="<html>bad gateway</html>", status=502))
    assert result == Refund(False, "ЮKassa ответила HTTP 502")


def test_yookassa_unreachable():
    client = YooKassa("shop", "secret", api="http://127.0.0.1:9/v3/refunds", timeout=2)
    result = asyncio.run(client.refund("pay-1", 100, "x"))
    assert not result.ok and result.error.startswith("нет ответа от ЮKassa")
