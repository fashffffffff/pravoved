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
    ("expected_hit_any", "нужная ст."),
    ("expected_recall", "recall ст."),
    ("refusal_on_out_of_scope", "отказ вне базы"),
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
    table = Table()
    table.add_column("прогон")
    table.add_column("n")
    for _, title in COLUMNS:
        table.add_column(title, justify="right")
    for r in runs:
        m = r["metrics"]
        n = "%s+%s" % (m.get("n_questions", 0), m.get("n_tool_cases", 0))
        table.add_row(r["tag"], n, *[str(m.get(key, "-")) for key, _ in COLUMNS])
    Console().print(table)


if __name__ == "__main__":
    main()
