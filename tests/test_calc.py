from datetime import date
from decimal import Decimal

import pytest

from pravoved.mcp_server import calc, key_rate


@pytest.fixture(autouse=True)
def offline_rates(monkeypatch):
    # тесты не ходят на cbr.ru, берём таблицу из json
    monkeypatch.setattr(key_rate, "_cache", key_rate.load_fallback())


def test_key_rate_on_dates():
    assert key_rate.rate_on(date(2023, 1, 15)) == Decimal("7.5")
    assert key_rate.rate_on(date(2024, 10, 28)) == Decimal("21")
    assert key_rate.rate_on(date(2026, 7, 27)) == Decimal("14")


def test_key_rate_periods_split():
    periods = key_rate.key_rate_periods(date(2023, 8, 10), date(2023, 8, 20))
    assert periods == [
        (date(2023, 8, 10), date(2023, 8, 14), Decimal("8.5")),
        (date(2023, 8, 15), date(2023, 8, 20), Decimal("12")),
    ]


def test_salary_delay_over_rate_change():
    # срок 10.07.2026, выплата 05.08.2026, просрочка с 11.07 по 05.08
    # 11.07..26.07 - 16 дней по 14.25%: 50000 * 0.1425 / 150 = 47.50 в день -> 760.00
    # 27.07..05.08 - 10 дней по 14%: 50000 * 0.14 / 150 = 46.6667 в день -> 466.67
    res = calc.salary_delay(50000, date(2026, 7, 10), date(2026, 8, 5))
    assert [p["days"] for p in res["periods"]] == [16, 10]
    assert res["periods"][0]["amount"] == "760.00"
    assert res["periods"][1]["amount"] == "466.67"
    assert res["compensation"] == "1226.67"


def test_salary_delay_one_rate():
    # 10 дней по 16%: 30000 * 0.16 / 150 = 32 в день -> 320.00
    res = calc.salary_delay(30000, date(2026, 1, 10), date(2026, 1, 20))
    assert res["compensation"] == "320.00"


def test_salary_not_late():
    res = calc.salary_delay(30000, date(2026, 1, 10), date(2026, 1, 10))
    assert res["compensation"] == "0.00"


def test_penalty_goods_defect():
    # 1% от 20000 = 200 в день, 7 дней
    res = calc.penalty(20000, 7, "goods_defect")
    assert res["penalty"] == "1400.00"
    assert not res["capped"]


def test_penalty_goods_defect_capped():
    # с 01.02.2026 неустойка по ст. 23 не больше уплаченной суммы: 200 дней * 1% = 200% цены -> 1000
    res = calc.penalty(1000, 200, "goods_defect")
    assert res["penalty"] == "1000.00"
    assert res["uncapped"] == "2000.00"
    assert res["capped"]
    assert "ограничено суммой, уплаченной за товар" in res["breakdown"]


def test_penalty_goods_defect_paid_less_than_price():
    # цена 20000, но заплачено 15000 (скидка, часть оплачена бонусами): потолок 15000
    res = calc.penalty(20000, 100, "goods_defect", paid=15000)
    assert res["penalty"] == "15000.00"
    assert res["cap"] == "15000.00"


def test_penalty_prepaid_cap():
    # 0.5% от 10000 = 50 в день, 300 дней = 15000, но не больше 10000
    res = calc.penalty(10000, 300, "prepaid_delivery")
    assert res["penalty"] == "10000.00"
    assert res["uncapped"] == "15000.00"
    assert res["capped"]


def test_penalty_service_cap():
    # 3% от 5000 = 150 в день; 10 дней = 1500 (меньше цены); 40 дней = 6000 -> 5000
    assert calc.penalty(5000, 10, "service_delay")["penalty"] == "1500.00"
    assert calc.penalty(5000, 40, "service_delay")["penalty"] == "5000.00"


def test_penalty_kopecks():
    # 0.5% от 99.99 = 0.49995 -> за 3 дня 1.49985 -> 1.50
    assert calc.penalty("99.99", 3, "prepaid_delivery")["penalty"] == "1.50"


def test_penalty_bad_kind():
    with pytest.raises(ValueError):
        calc.penalty(100, 1, "something")


def test_deadline_calendar():
    # 05.10.2026 (пн) + 10 дней = 15.10 (чт)
    res = calc.deadline(date(2026, 10, 5), None, "demand_10")
    assert res["deadline"] == "2026-10-15"
    assert not res["moved_by_art_193"]


def test_deadline_falls_on_weekend():
    # 07.10.2026 (ср) + 10 = 17.10 (сб) -> переносится на пн 19.10
    res = calc.deadline(date(2026, 10, 7), None, "demand_10")
    assert res["deadline"] == "2026-10-19"
    assert res["moved_by_art_193"]


def test_deadline_falls_on_holiday():
    # 24.10.2026 (сб) + 11 = 04.11 (ср, праздник) -> 05.11 (чт)
    res = calc.deadline(date(2026, 10, 24), 11, "custom")
    assert res["deadline"] == "2026-11-05"


def test_deadline_working_days():
    # 30.10.2026 (пт) + 3 рабочих дня: пн 02.11, вт 03.11, ср 04.11 - праздник, значит чт 05.11
    res = calc.deadline(date(2026, 10, 30), 3, "custom", working_days=True)
    assert res["deadline"] == "2026-11-05"


def test_deadline_complex_goods():
    # 15 дней с 01.09.2026 (вт) -> 16.09 (ср)
    assert calc.deadline(date(2026, 9, 1), None, "complex_goods_15")["deadline"] == "2026-09-16"


def test_deadline_custom_needs_days():
    with pytest.raises(ValueError):
        calc.deadline(date(2026, 9, 1), None, "custom")
