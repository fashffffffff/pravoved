import json
from datetime import date
from pathlib import Path

META = Path(__file__).resolve().parents[2] / "data" / "raw" / "meta.json"


def load_meta(path=None):
    path = path or META
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def corpus_date():
    """Дата, на которую тексты сверены с consultant.ru (самая ранняя из документов). None, если нет meta.json"""
    dates = [d["downloaded"] for d in load_meta().values() if d.get("downloaded")]
    return date.fromisoformat(min(dates)) if dates else None


def editions():
    """код закона -> строка редакции, как её показывает consultant"""
    return {code: d.get("edition", "") for code, d in load_meta().items()}
