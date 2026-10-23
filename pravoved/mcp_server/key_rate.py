import json
import re
import urllib.request
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

CBR_URL = "https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx"
FALLBACK_FILE = Path(__file__).parent / "key_rate_history.json"

SOAP_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>'
    '<KeyRate xmlns="http://web.cbr.ru/"><fromDate>{start}</fromDate><ToDate>{end}</ToDate></KeyRate>'
    "</soap:Body></soap:Envelope>"
)

# ставки, полученные с cbr.ru: список (дата начала действия, ставка), по возрастанию дат
_cache: list[tuple[date, Decimal]] | None = None


def load_fallback() -> list[tuple[date, Decimal]]:
    data = json.loads(FALLBACK_FILE.read_text(encoding="utf-8"))
    return [(date.fromisoformat(x["from"]), Decimal(x["rate"])) for x in data]


def fetch_from_cbr(start: date, end: date) -> list[tuple[date, Decimal]]:
    body = SOAP_BODY.format(start=start.isoformat(), end=end.isoformat())
    req = urllib.request.Request(
        CBR_URL,
        body.encode("utf-8"),
        {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": '"http://web.cbr.ru/KeyRate"'},
    )
    xml = urllib.request.urlopen(req, timeout=10).read().decode("utf-8")
    rows = re.findall(r"<DT>(\d{4}-\d\d-\d\d)T.*?<Rate>([\d.]+)</Rate>", xml)
    # cbr отдаёт ставку по каждому дню, оставляем только даты смены
    changes = []
    for d, rate in sorted(rows):
        if not changes or changes[-1][1] != Decimal(rate):
            changes.append((date.fromisoformat(d), Decimal(rate)))
    return changes


def get_history() -> list[tuple[date, Decimal]]:
    global _cache
    if _cache is not None:
        return _cache
    fallback = load_fallback()
    try:
        live = fetch_from_cbr(fallback[0][0], date.today())
        # первая строка - ставка на начало выборки, а не смена
        _cache = [(fallback[0][0], live[0][1])] + live[1:]
    except Exception:
        _cache = fallback
    return _cache


def rate_on(day: date) -> Decimal:
    history = get_history()
    result = history[0][1]
    for start, rate in history:
        if start <= day:
            result = rate
    return result


def key_rate_periods(start: date, end: date) -> list[tuple[date, date, Decimal]]:
    """Периоды [from, to] включительно, в каждом ставка постоянна."""
    periods = []
    day = start
    while day <= end:
        rate = rate_on(day)
        if periods and periods[-1][2] == rate:
            periods[-1] = (periods[-1][0], day, rate)
        else:
            periods.append((day, day, rate))
        day += timedelta(days=1)
    return periods
