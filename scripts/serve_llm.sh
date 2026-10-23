#!/bin/sh
# Запуск llama-server для агента. Использование: scripts/serve_llm.sh путь/к/модели.gguf [порт]
# Агент ходит на http://HOST:PORT/v1 (LLM_BASE_URL в .env), имя модели можно оставить local.
MODEL=${1:?укажите путь к .gguf}
PORT=${2:-8080}

# dev на маке (M4 Pro, 24 ГБ): всё в памяти, --jinja обязателен (tool calling идёт через шаблон чата)
llama-server -m "$MODEL" --jinja -c 16384 --port "$PORT"

# Сервер с 8 ГБ видеопамяти (MoE-модели: Qwen3.6-35B-A3B, Gemma 4 26B-A4B, LFM2.5-24B-A2B).
# --n-cpu-moe N выносит эксперты первых N слоёв в оперативку, остальное остаётся на GPU.
# N подбирается под каждую модель: начните с большого значения (например 30), если видеопамять
# свободна - уменьшайте, пока не упрётесь в нехватку. Чем меньше N, тем быстрее.
# llama-server -m "$MODEL" --jinja -ngl 99 --n-cpu-moe 30 -c 16384 --host 0.0.0.0 --port "$PORT"
#
# Для моделей, которые думают перед ответом, в .env стоит LLM_THINKING=false:
# агент передаёт chat_template_kwargs {"enable_thinking": false}.
