"""Сценарии целиком: от нажатий клиента до вызовов Telegram API, базы и таблицы."""

import datetime as dt

from aiogram.methods import (
    AnswerCallbackQuery, AnswerPreCheckoutQuery, EditMessageReplyMarkup, SendInvoice, SendMessage,
)

from bot import jobs, texts
from bot.keyboards import AdminCancelCb, CancelCb, ConfirmCb, DayCb, MasterCb, NoteCb, PickCb, ServiceCb, TimeCb
from bot.storage import CANCELLED, CONFIRMED, EXPIRED, PAID, PENDING

from .conftest import ADMIN, buttons, grid, last_edit, texts_of

DAY = DayCb(date="20261202").pack()


def go_to_confirm(h, service="cut", master="anna", time="1100", user_id=1, name="Мария", phone="89001234567"):
    h.send(texts.BTN_BOOK, user_id)
    h.press(ServiceCb(id=service).pack(), user_id)
    h.press(MasterCb(id=master).pack(), user_id)
    h.press(DAY, user_id)
    h.press(TimeCb(time=time).pack(), user_id)
    h.send(name, user_id)
    return h.send(phone, user_id)


def test_steps_show_only_free_time(harness):
    [menu] = harness.send(texts.BTN_BOOK)
    assert ServiceCb(id="cut").pack() in buttons(menu)

    edit = last_edit(harness.press(ServiceCb(id="cut").pack()))
    assert buttons(edit)[:3] == [MasterCb(id="anna").pack(), MasterCb(id="olga").pack(), MasterCb(id="any").pack()]

    edit = last_edit(harness.press(MasterCb(id="anna").pack()))
    days = grid(edit)
    assert [len(row) for row in days[:-1]] == [2] * 7  # 14 дней в две колонки, потом «Назад»
    assert days[0][0] == ("Сегодня, 2 дек", "success", DAY)
    assert days[0][1] == ("Завтра, 3 дек", "success", DayCb(date="20261203").pack())
    assert days[1][1] == ("сб, 5 дек", "danger", NoteCb(kind="off").pack())  # Анна по субботам не работает

    times = [button for row in grid(last_edit(harness.press(DAY)))[:-1] for button in row]
    # Сейчас 10:00, записаться можно не раньше чем через час: 10:00 и 10:30 неактивны.
    assert times[:3] == [("10:00", "disabled", None), ("10:30", "disabled", None),
                         ("11:00", "success", TimeCb(time="1100").pack())]
    assert times[-1] == ("18:00", "success", TimeCb(time="1800").pack())  # стрижка час, Анна до 19:00


def test_busy_time_is_red_and_explains_itself(harness):
    go_to_confirm(harness, user_id=2, name="Ольга")
    harness.press(ConfirmCb(pay="onsite").pack(), user_id=2)
    harness.send(texts.BTN_BOOK)
    harness.press(ServiceCb(id="cut").pack())
    harness.press(MasterCb(id="anna").pack())
    times = dict((text, (style, data)) for row in grid(last_edit(harness.press(DAY)))[:-1]
                 for text, style, data in row)
    assert times["11:00"] == ("danger", NoteCb(kind="busy").pack())
    assert times["11:30"] == ("danger", NoteCb(kind="busy").pack())  # 11:30-12:30 задевает 11:00-12:00
    assert times["12:00"][0] == "success"
    [toast] = [c for c in harness.press(NoteCb(kind="busy").pack()) if isinstance(c, AnswerCallbackQuery)]
    assert toast.text == texts.NOTE["busy"]


def test_second_booking_remembers_choices_and_contacts(harness):
    go_to_confirm(harness, name="Мария", phone="89001234567")
    harness.press(ConfirmCb(pay="onsite").pack())
    go_to_confirm(harness, time="1200", name="Анна", phone="89007654321")
    harness.press(ConfirmCb(pay="onsite").pack())

    [menu] = harness.send(texts.BTN_BOOK)
    assert ("⭐ Стрижка, 1500 ₽", "primary", ServiceCb(id="cut").pack()) in grid(menu)[0]
    masters = grid(last_edit(harness.press(ServiceCb(id="cut").pack())))
    assert masters[0][0] == ("⭐ Анна", "primary", MasterCb(id="anna").pack())
    harness.press(MasterCb(id="anna").pack())
    harness.press(DAY)

    [_, _, prompt] = harness.press(TimeCb(time="1300").pack())
    assert prompt.text == texts.ASK_NAME_AGAIN
    assert [row[0][0] for row in grid(prompt)] == ["Анна", "Мария"]  # свежие первыми

    calls = harness.press(PickCb(kind="name", index=1).pack())
    assert last_edit(calls).text == texts.PICKED_NAME.format(value="Мария")
    phone_prompt = calls[-1]
    assert phone_prompt.text == texts.ASK_PHONE_AGAIN
    assert [row[0][0] for row in grid(phone_prompt)] == ["+7 900 765-43-21", "+7 900 123-45-67"]

    calls = harness.press(PickCb(kind="phone", index=1).pack())
    assert "Мария, +7 900 123-45-67" in calls[-1].text
    assert buttons(calls[-1]) == [ConfirmCb(pay="online").pack(), ConfirmCb(pay="onsite").pack()]


def test_typed_name_removes_suggestions_and_old_buttons_are_stale(harness):
    go_to_confirm(harness)
    harness.press(ConfirmCb(pay="onsite").pack())
    harness.send(texts.BTN_BOOK)
    harness.press(ServiceCb(id="cut").pack())
    harness.press(MasterCb(id="anna").pack())
    harness.press(DAY)
    harness.press(TimeCb(time="1300").pack())

    calls = harness.send("Светлана")
    assert any(isinstance(c, EditMessageReplyMarkup) and c.reply_markup is None for c in calls)
    [toast] = [c for c in harness.press(PickCb(kind="name", index=0).pack()) if isinstance(c, AnswerCallbackQuery)]
    assert toast.text == texts.STALE_BUTTON


def test_booking_pay_on_site(harness):
    [confirm] = go_to_confirm(harness)
    assert "Мария, +7 900 123-45-67" in confirm.text
    assert buttons(confirm) == [ConfirmCb(pay="online").pack(), ConfirmCb(pay="onsite").pack()]

    calls = harness.press(ConfirmCb(pay="onsite").pack())
    assert "Готово, вы записаны!" in last_edit(calls).text
    [admin] = [c for c in calls if isinstance(c, SendMessage) and c.chat_id == ADMIN]
    assert "Новая запись №1" in admin.text and buttons(admin) == [AdminCancelCb(id=1).pack()]

    booking = harness.run(harness.bookings.get(1))
    assert (booking.status, booking.master_id, booking.start.hour) == (CONFIRMED, "anna", 11)
    assert harness.sheet.rows[1][2:] == ["02.12.2026", "11:00", "Стрижка", "Анна", "Мария",
                                         "+7 900 123-45-67", 1500, "оплата на месте"]


def test_taken_time_disappears_and_race_is_caught(harness):
    go_to_confirm(harness, user_id=1)
    go_to_confirm(harness, user_id=2, name="Ольга")
    harness.press(ConfirmCb(pay="onsite").pack(), user_id=1)

    # Второй клиент подтверждает то же время: запись не создаётся, ему снова показано время.
    calls = harness.press(ConfirmCb(pay="onsite").pack(), user_id=2)
    edit = last_edit(calls)
    assert edit.text.startswith(texts.SLOT_GONE)
    assert TimeCb(time="1100").pack() not in buttons(edit)
    assert TimeCb(time="1030").pack() not in buttons(edit)  # 10:30-11:30 задевает 11:00
    assert harness.run(harness.bookings.get(2)) is None


def test_any_master_takes_whoever_is_free(harness):
    go_to_confirm(harness, service="brows", master="olga", time="1200", user_id=1)
    harness.press(ConfirmCb(pay="onsite").pack(), user_id=1)
    go_to_confirm(harness, service="brows", master="any", time="1200", user_id=2)
    harness.press(ConfirmCb(pay="onsite").pack(), user_id=2)
    assert harness.run(harness.bookings.get(2)).master_id == "maria"


def test_online_payment(harness):
    go_to_confirm(harness)
    calls = harness.press(ConfirmCb(pay="online").pack())
    [invoice] = [c for c in calls if isinstance(c, SendInvoice)]
    assert invoice.payload == "booking:1" and invoice.prices[0].amount == 150000
    assert harness.run(harness.bookings.get(1)).status == PENDING
    assert not [c for c in calls if isinstance(c, SendMessage) and c.chat_id == ADMIN]

    [answer] = harness.pre_checkout("booking:1", 150000)
    assert isinstance(answer, AnswerPreCheckoutQuery) and answer.ok
    [wrong_sum] = harness.pre_checkout("booking:1", 100)
    assert not wrong_sum.ok

    calls = harness.pay("booking:1", 150000)
    assert texts_of(calls)[0].startswith("Оплата прошла")
    assert any(c.chat_id == ADMIN and "оплачено" in c.text for c in calls if isinstance(c, SendMessage))
    booking = harness.run(harness.bookings.get(1))
    assert (booking.status, booking.payment_id) == (PAID, "yk-1")
    assert harness.sheet.rows[1][-1] == "оплачено"


def test_unpaid_hold_expires_and_frees_time(harness):
    go_to_confirm(harness, time="1200")
    harness.press(ConfirmCb(pay="online").pack())
    harness.now += dt.timedelta(minutes=16)

    [answer] = harness.pre_checkout("booking:1", 150000)
    assert not answer.ok

    before = len(harness.session.calls)
    harness.run(jobs.tick(harness.bot, harness.salon))
    [notice] = harness.session.calls[before:]
    assert notice.text == texts.PAY_EXPIRED.format(id=1)
    assert harness.run(harness.bookings.get(1)).status == EXPIRED
    assert harness.sheet.rows[1][-1] == "не оплачена"

    harness.send(texts.BTN_BOOK, user_id=2)
    harness.press(ServiceCb(id="cut").pack(), 2)
    harness.press(MasterCb(id="anna").pack(), 2)
    assert TimeCb(time="1200").pack() in buttons(last_edit(harness.press(DAY, 2)))


def test_without_payment_token_only_one_button(no_payments):
    [confirm] = go_to_confirm(no_payments)
    assert buttons(confirm) == [ConfirmCb(pay="onsite").pack()]
    assert texts.CONFIRM_NO_PAY.split("\n")[0] in confirm.text


def test_name_and_phone_validation(harness):
    harness.send(texts.BTN_BOOK)
    harness.press(ServiceCb(id="cut").pack())
    harness.press(MasterCb(id="anna").pack())
    harness.press(DAY)
    harness.press(TimeCb(time="1100").pack())
    assert texts_of(harness.send("12345")) == [texts.BAD_NAME]
    assert texts_of(harness.send("Анна-Мария")) == [texts.ASK_PHONE]
    assert texts_of(harness.send("позвоните мне")) == [texts.BAD_PHONE]
    assert texts_of(harness.send("+1 202 555 0100")) == [texts.BAD_PHONE]
    assert "+7 900 000-00-00" in texts_of(harness.send("+7 (900) 000-00-00"))[0]


def test_menu_button_during_text_step_is_not_a_name(harness):
    harness.send(texts.BTN_BOOK)
    harness.press(ServiceCb(id="cut").pack())
    harness.press(MasterCb(id="anna").pack())
    harness.press(DAY)
    harness.press(TimeCb(time="1100").pack())
    assert texts_of(harness.send(texts.BTN_MY)) == [texts.NO_BOOKINGS]
    assert texts_of(harness.send("Мария")) == [texts.UNKNOWN]


def test_back_buttons(harness):
    harness.send(texts.BTN_BOOK)
    harness.press(ServiceCb(id="cut").pack())
    harness.press(MasterCb(id="anna").pack())
    edit = last_edit(harness.press("back:master"))
    assert MasterCb(id="anna").pack() in buttons(edit)
    edit = last_edit(harness.press("back:service"))
    assert edit.text == texts.CHOOSE_SERVICE


def test_my_bookings_cancel_with_confirmation(harness):
    go_to_confirm(harness)
    harness.press(ConfirmCb(pay="onsite").pack())
    harness.now = dt.datetime(2026, 12, 1, 12, 0, tzinfo=harness.now.tzinfo)

    [listing] = harness.send(texts.BTN_MY)
    assert "№1" in listing.text and buttons(listing) == [CancelCb(id=1).pack()]
    edit = last_edit(harness.press(CancelCb(id=1).pack()))
    assert edit.text.startswith("Отменить запись?")
    assert harness.run(harness.bookings.get(1)).status == CONFIRMED

    calls = harness.press(CancelCb(id=1, sure=True).pack())
    assert last_edit(calls).text == texts.NO_BOOKINGS
    assert harness.run(harness.bookings.get(1)).status == CANCELLED
    assert any(isinstance(c, SendMessage) and c.chat_id == ADMIN and "отменил" in c.text for c in calls)


def test_cancel_too_late_and_foreign_booking(harness):
    go_to_confirm(harness)
    harness.press(ConfirmCb(pay="onsite").pack())
    [toast] = [c for c in harness.press(CancelCb(id=1).pack(), user_id=2) if isinstance(c, AnswerCallbackQuery)]
    assert toast.text == texts.NO_BOOKINGS
    harness.now = dt.datetime(2026, 12, 2, 9, 30, tzinfo=harness.now.tzinfo)
    [toast] = [c for c in harness.press(CancelCb(id=1, sure=True).pack()) if isinstance(c, AnswerCallbackQuery)]
    assert toast.text == texts.CANCEL_TOO_LATE.format(hours=2)
    assert harness.run(harness.bookings.get(1)).status == CONFIRMED


def test_admin_day_and_cancel(harness):
    go_to_confirm(harness)
    harness.press(ConfirmCb(pay="onsite").pack())
    [day] = texts_of(harness.send("/day", user_id=ADMIN))
    assert "11:00 Анна: Стрижка, Мария +7 900 123-45-67" in day
    assert texts_of(harness.send("/day", user_id=1)) == [texts.UNKNOWN]

    calls = harness.press(AdminCancelCb(id=1).pack(), user_id=ADMIN)
    assert any(isinstance(c, SendMessage) and c.chat_id == 1 for c in calls)
    assert harness.run(harness.bookings.get(1)).status == CANCELLED


def test_reminder_once_and_demo_cleanup(harness):
    # Запись на пятницу, сделанная в среду: напоминание в четверг.
    harness.send(texts.BTN_BOOK)
    harness.press(ServiceCb(id="cut").pack())
    harness.press(MasterCb(id="anna").pack())
    harness.press(DayCb(date="20261204").pack())
    harness.press(TimeCb(time="1200").pack())
    harness.send("Мария")
    harness.send("9001234567")
    harness.press(ConfirmCb(pay="onsite").pack())

    def tick():
        before = len(harness.session.calls)
        harness.run(jobs.tick(harness.bot, harness.salon))
        return harness.session.calls[before:]

    assert tick() == []
    harness.now = dt.datetime(2026, 12, 3, 12, 30, tzinfo=harness.now.tzinfo)
    [reminder] = tick()
    assert reminder.text.startswith("Напоминаю")
    assert tick() == []

    harness.now = dt.datetime(2026, 12, 3, 10, 1, tzinfo=harness.now.tzinfo)
    tick()
    assert harness.run(harness.bookings.get(1)) is None
    assert harness.sheet.rows == {}


def test_stale_button_and_unknown_text(harness):
    [toast] = [c for c in harness.press(TimeCb(time="1100").pack()) if isinstance(c, AnswerCallbackQuery)]
    assert toast.show_alert
    assert texts_of(harness.send("привет")) == [texts.UNKNOWN]
    assert "Это демо-бот" in texts_of(harness.send("/start"))[0]


def test_broken_payment_token_frees_time_and_offers_onsite(harness):
    harness.session.invoice_error = "Bad Request: PAYMENT_PROVIDER_INVALID"
    go_to_confirm(harness)
    calls = harness.press(ConfirmCb(pay="online").pack())
    edit = last_edit(calls)
    assert edit.text.startswith(texts.PAY_UNAVAILABLE)
    assert buttons(edit) == [ConfirmCb(pay="onsite").pack()]
    assert any(isinstance(c, SendMessage) and c.chat_id == ADMIN and "PAYMENT_PROVIDER_INVALID" in c.text
               for c in calls)
    assert harness.run(harness.bookings.get(1)).status == CANCELLED
    assert harness.sheet.rows == {}

    harness.press(ConfirmCb(pay="onsite").pack())
    booking = harness.run(harness.bookings.get(2))
    assert (booking.status, booking.start.hour) == (CONFIRMED, 11)
