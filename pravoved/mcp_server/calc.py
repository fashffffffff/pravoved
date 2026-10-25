from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from pravoved.mcp_server.key_rate import key_rate_periods

KOPECK = Decimal("0.01")

# kind -> (доля цены в день, основание, чем ограничена сумма)
# с 01.02.2026 (ФЗ от 28.12.2025 N 500-ФЗ) неустойка по ст. 23 тоже ограничена
PENALTY_KINDS = {
    "goods_defect": (
        Decimal("0.01"),
        "ст. 23 п. 1 Закона о защите прав потребителей (за нарушение сроков по ст. 20, 21, 22); "
        "сумма неустойки не может превышать сумму, уплаченную потребителем за товар",
        "ограничено суммой, уплаченной за товар",
    ),
    "prepaid_delivery": (
        Decimal("0.005"),
        "ст. 23.1 п. 3 Закона о защите прав потребителей",
        "ограничено суммой предварительной оплаты",
    ),
    "service_delay": (
        Decimal("0.03"),
        "ст. 28 п. 5 Закона о защите прав потребителей",
        "ограничено ценой работы (услуги)",
    ),
}


def money(x) -> Decimal:
    return Decimal(x).quantize(KOPECK, rounding=ROUND_HALF_UP)


def penalty(price, days: int, kind: str, paid=None, grace_days: int = 0) -> dict:
    if kind not in PENALTY_KINDS:
        raise ValueError(f"неизвестный kind: {kind}, допустимо: {', '.join(PENALTY_KINDS)}")
    if days < 0:
        raise ValueError("days не может быть отрицательным")
    # grace_days - срок, который закон даёт на исполнение (10 дней по ст. 22); неустойка идёт только за дни сверх него
    all_days = days
    days = max(days - grace_days, 0)
    price = Decimal(str(price))
    share, basis, cap_note = PENALTY_KINDS[kind]
    # потолок - уплаченная сумма, а если её не передали, то цена
    cap = money(Decimal(str(paid)) if paid is not None else price)
    raw = money(price * share * days)
    total = min(raw, cap)
    breakdown = f"{price} x {share * 100}% x {days} дн. = {raw}"
    if grace_days:
        breakdown = f"{all_days} дн. - {grace_days} дн. на исполнение = {days} дн.; " + breakdown
    if raw > total:
        breakdown += f"; {cap_note} ({cap}), поэтому {total}"
    return {
        "penalty": str(total),
        "uncapped": str(raw),
        "capped": total != raw,
        "cap": str(cap),
        "days": days,
        "rate_per_day_percent": str(share * 100),
        "breakdown": breakdown,
        "legal_basis": basis,
    }


def salary_delay(amount, due_date: date, paid_date: date) -> dict:
    amount = Decimal(str(amount))
    if paid_date <= due_date:
        return {
            "compensation": "0.00",
            "days": 0,
            "periods": [],
            "breakdown": "просрочки нет",
            "legal_basis": "ст. 236 ТК РФ",
        }
    start = due_date + timedelta(days=1)
    periods = []
    total = Decimal("0")
    for p_from, p_to, rate in key_rate_periods(start, paid_date):
        days = (p_to - p_from).days + 1
        part = amount * rate / 100 / 150 * days
        total += part
        periods.append({
            "from": p_from.isoformat(),
            "to": p_to.isoformat(),
            "days": days,
            "key_rate": str(rate),
            "amount": str(money(part)),
        })
    total = money(total)
    all_days = (paid_date - due_date).days
    lines = [f"{p['from']}..{p['to']}: {money(amount)} x {p['key_rate']}% / 150 x {p['days']} дн. = {p['amount']}" for p in periods]
    return {
        "compensation": str(total),
        "days": all_days,
        "periods": periods,
        "breakdown": "; ".join(lines) + f"; итого {total}",
        "legal_basis": "ст. 236 ТК РФ: не менее 1/150 ключевой ставки ЦБ РФ за каждый день задержки, "
                       "начиная со следующего дня после установленного срока по день фактической выплаты включительно",
    }


# нерабочие дни РФ в 2026 году (постановление Правительства о переносах выходных)
HOLIDAYS_2026 = {
    date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3), date(2026, 1, 4), date(2026, 1, 5),
    date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8), date(2026, 1, 9),
    date(2026, 2, 23),
    date(2026, 3, 9),
    date(2026, 5, 1), date(2026, 5, 11),
    date(2026, 6, 12),
    date(2026, 11, 4),
    date(2026, 12, 31),
}

DEADLINE_KINDS = {
    "demand_10": (10, "ст. 22 Закона о защите прав потребителей: требование о возврате денег за товар - 10 дней"),
    "exchange_14": (14, "ст. 25 Закона о защите прав потребителей: возврат/обмен товара надлежащего качества - 14 дней"),
    "complex_goods_15": (15, "ст. 18 Закона о защите прав потребителей: технически сложный товар - 15 дней"),
    "custom": (None, "срок задан вручную"),
}


def is_working_day(d: date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS_2026


def add_days(start: date, days: int, working: bool) -> date:
    if not working:
        return start + timedelta(days=days)
    d = start
    while days > 0:
        d += timedelta(days=1)
        if is_working_day(d):
            days -= 1
    return d


def deadline(start: date, days: int | None, kind: str, working_days: bool = False) -> dict:
    if kind not in DEADLINE_KINDS:
        raise ValueError(f"неизвестный kind: {kind}, допустимо: {', '.join(DEADLINE_KINDS)}")
    default_days, basis = DEADLINE_KINDS[kind]
    if days is None:
        days = default_days
    if days is None:
        raise ValueError("для kind=custom нужно указать days")
    end = add_days(start, days, working_days)
    moved = False
    # ст. 193 ГК РФ: если последний день срока нерабочий, срок истекает в ближайший рабочий день
    while not is_working_day(end):
        end += timedelta(days=1)
        moved = True
    breakdown = f"{start.isoformat()} + {days} {'раб.' if working_days else 'календ.'} дн. = {end.isoformat()}"
    if moved:
        breakdown += " (последний день пришёлся на нерабочий, перенесён на следующий рабочий по ст. 193 ГК РФ)"
    return {
        "deadline": end.isoformat(),
        "weekday": ["пн", "вт", "ср", "чт", "пт", "сб", "вс"][end.weekday()],
        "days": days,
        "moved_by_art_193": moved,
        "breakdown": breakdown,
        "legal_basis": basis + "; ст. 191, 193 ГК РФ (отсчёт со дня, следующего за начальным)",
    }
