"""Сводная таблица по сохранённым прогонам: uv run python eval/compare.py"""
import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

RESULTS = Path(__file__).resolve().parent / "results"

COLUMNS = [
    ("citation_precision", "точн. ссылок"),
    ("invalid_per_answer", "невер./ответ"),
    ("no_citation_answers", "без ссылок"),
    ("unbacked_numbers_per_answer", "цифры без опоры"),
    ("expected_hit_any", "нужная ст."),
    ("expected_recall", "recall ст."),
    ("refusal_on_out_of_scope", "отказ вне базы"),
    ("web_ok_answered", "ответ по вебу"),
    ("false_refusal_rate", "ложн. отказ"),
    ("tool_selection_acc", "tool выбор"),
    ("tool_args_acc", "tool арг."),
    ("avg_latency_s", "сек/вопрос"),
    ("avg_tokens_per_sec", "ток/с"),
    ("errors", "ошибки"),
]


def main():
    runs = [json.load(open(p, encoding="utf-8")) for p in sorted(RESULTS.glob("*.json"))]
    if not runs:
        print("в eval/results нет сохранённых прогонов (запустите answer_eval.py --tag ...)")
        return
    # метрики строками, прогоны столбцами - так помещается много моделей
    table = Table()
    table.add_column("метрика")
    for r in runs:
        table.add_column(r["tag"], justify="right")
    table.add_row("вопросов + tool-кейсов", *["%s+%s" % (r["metrics"].get("n_questions", 0), r["metrics"].get("n_tool_cases", 0)) for r in runs])
    for key, title in COLUMNS:
        table.add_row(title, *[str(r["metrics"].get(key, "-")) for r in runs])
    Console().print(table)


if __name__ == "__main__":
    main()
