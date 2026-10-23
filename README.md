# Правовед

Локальный ассистент по бытовому праву РФ: отвечает на вопросы про защиту прав потребителей,
трудовые отношения, куплю-продажу, аренду и наём жилья со ссылками на конкретные статьи.
Внутри RAG по текстам законов и MCP-сервер с инструментами (расчёты, проверка цитат).

Корпус: Закон «О защите прав потребителей», ТК РФ, ГК РФ (гл. 30 §1-2, 34, 35),
Постановление Пленума ВС РФ №17 от 28.06.2012. Тексты лежат в `data/raw`, источник - consultant.ru.

## Запуск

    uv sync
    cp .env.example .env

    # тексты уже в репозитории; чтобы скачать заново:
    uv run python -m pravoved.corpus.download
    uv run python -m pravoved.corpus.parse        # data/chunks.jsonl и data/refs.jsonl

    uv run python -m pravoved.retrieval build     # индекс (первый раз скачает bge-m3, ~2 ГБ)
    uv run python -m pravoved.retrieval search "магазин не принимает сломанный телефон"

    uv run python eval/retrieval_eval.py          # recall@k и MRR
    uv run pytest

Индекс Qdrant лежит в `data/index/qdrant` (встроенный режим). Для сервера задайте `QDRANT_URL`.
