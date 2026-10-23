# Правовед

Локальный ассистент по бытовому праву РФ: отвечает на вопросы про защиту прав потребителей,
трудовые отношения, куплю-продажу, аренду и наём жилья со ссылками на конкретные статьи.
Внутри RAG по текстам законов, MCP-сервер с инструментами (расчёты, ключевая ставка, сроки)
и агент на LangGraph, который отвечает только со ссылками на найденные статьи.

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

## Агент

Граф (`pravoved/agent/graph.py`), промпты в `pravoved/agent/prompts.py`:

    retrieve -> grade -> answer -> verify
                  |  ^                |
                  v  |                +-> answer (один раз, строже, если нет верных ссылок)
               (новый запрос, до 2 раз)
                  |
                  +-> refuse (нет ответа в базе или вопрос вне базы)

- retrieve: гибридный поиск `search(question, k=8)`, при повторе результаты склеиваются.
- grade: LLM решает, хватает ли найденного; если нет - переписывает запрос языком закона и ищем ещё.
  После двух попыток или для вопросов вне базы (налоги, уголовка...) - честный отказ.
- answer: источники нумеруются [1]..[n], каждое утверждение со ссылкой; суммы и сроки только через
  инструменты MCP-сервера (цикл вызова инструментов).
- verify: проверяет [n] и упоминания «ст. N». Ссылка верна, если указывает на найденный источник
  (статью по номеру ещё и проверяем через `get_article`). Неверные убираются или помечаются,
  счётчики `cited` и `invalid` идут в метрики.

Модель задаётся только через `.env` (`LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_THINKING`).
Инструменты по умолчанию запускаются как подпроцесс (stdio); чтобы ходить на уже запущенный сервер:
`python -m pravoved.mcp_server --http --port 8765` и `MCP_URL=http://127.0.0.1:8765/mcp`.

    scripts/serve_llm.sh ~/models/Qwen3.5-4B-Q4_K_M.gguf     # llama-server на :8080
    uv run python -m pravoved ask "Купил телефон, сломался через неделю, что делать?"
    uv run python -m pravoved ask --debug "..."              # шаги графа
    uv run python -m pravoved chat

## Бенчмарк модели

    # поменяйте LLM_BASE_URL / LLM_MODEL в .env (или переменные окружения), поднимите сервер
    uv run python eval/answer_eval.py --tag qwen3.6-35b-a3b            # весь прогон
    uv run python eval/answer_eval.py --tag test --limit 15            # быстрый, вопросы берутся равномерно
    uv run python eval/compare.py                                      # таблица по всем прогонам

Вопросы - `eval/questions.jsonl` (57, из них 6 вне базы), задачи на инструменты - `eval/tool_cases.jsonl` (12).
Метрики: точность ссылок, неверные ссылки на ответ, попадание в нужную статью, ответы без ссылок,
отказы вне базы и ложные отказы, выбор инструмента и его аргументы, время и токены в секунду.
Сырые ответы и метрики лежат в `eval/results/TAG.json`.
