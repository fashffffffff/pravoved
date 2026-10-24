"""Перекачивает корпус во временную папку и показывает, какие статьи изменились.
С --apply заменяет файлы в data/raw, пересобирает chunks и индекс."""
import argparse
import shutil
import tempfile
from pathlib import Path

from . import download, parse
from .meta import load_meta


def article_texts(path):
    # номер статьи (пункта) -> текст
    result = {}
    for u in parse.file_units(path.stem, path.read_text(encoding="utf-8")):
        result[u["article"]] = result.get(u["article"], "") + u["text"]
    return result


def compare(old_dir, new_dir):
    for new_file in sorted(new_dir.glob("*.txt")):
        old_file = old_dir / new_file.name
        old = article_texts(old_file) if old_file.exists() else {}
        new = article_texts(new_file)
        added = [a for a in new if a not in old]
        removed = [a for a in old if a not in new]
        changed = [a for a in new if a in old and new[a] != old[a]]
        code = new_file.stem
        if not (added or removed or changed):
            print(code + ": без изменений")
            continue
        print("%s: изменено %d, добавлено %d, удалено %d" % (code, len(changed), len(added), len(removed)))
        for label, nums in (("изменены", changed), ("добавлены", added), ("удалены", removed)):
            if nums:
                print("  %s: %s" % (label, ", ".join(nums)))


def compare_meta(old_dir, new_dir):
    old = load_meta(old_dir / "meta.json")
    new = load_meta(new_dir / "meta.json")
    for code, d in new.items():
        was = old.get(code, {}).get("edition")
        if was != d["edition"]:
            print("редакция %s: %s -> %s" % (code, was or "-", d["edition"] or "-"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="заменить data/raw, пересобрать chunks и индекс")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="pravoved_raw_"))
    try:
        download.main(out=tmp)
        compare(download.RAW, tmp)
        compare_meta(download.RAW, tmp)
        if not args.apply:
            print("ничего не заменено, запустите с --apply")
            return
        for f in tmp.iterdir():
            shutil.copy(f, download.RAW / f.name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    parse.main()
    from pravoved.retrieval.index import build
    build()


if __name__ == "__main__":
    main()
