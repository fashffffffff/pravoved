#!/bin/sh
# Запуск llama-server для агента. Использование: scripts/serve_llm.sh путь/к/модели.gguf [порт]
# Агент ходит на http://HOST:PORT/v1 (LLM_BASE_URL в .env), имя модели можно оставить local.
MODEL=${1:?укажите путь к .gguf}
PORT=${2:-8080}

# dev на маке (M4 Pro, 24 ГБ): всё в памяти, --jinja обязателен (tool calling идёт через шаблон чата)
llama-server -m "$MODEL" --jinja -c 16384 --port "$PORT"

# Сервер с 8 ГБ видеопамяти.
# Основная модель, Gemma 4 26B-A4B (MoE): -fit on сам раскладывает слои по GPU и RAM.
# Если не хватает видеопамяти, вместо него можно задать --n-cpu-moe N: эксперты первых N слоёв уходят в
# оперативку. Начните с большого N (например 30) и уменьшайте, пока не упрётесь в нехватку: чем меньше N, тем быстрее.
# llama-server -m "$MODEL" --jinja -ngl 99 -fit on -c 16384 --host 0.0.0.0 --port "$PORT"
# llama-server -m "$MODEL" --jinja -ngl 99 --n-cpu-moe 30 -c 16384 --host 0.0.0.0 --port "$PORT"
#
# Запасная офлайн-модель, T-lite 2.1 8B: целиком на GPU, ничего выносить не нужно.
# llama-server -m "$MODEL" --jinja -ngl 99 -c 16384 --host 0.0.0.0 --port "$PORT"
#
# Для моделей, которые думают перед ответом, в .env стоит LLM_THINKING=false:
# агент передаёт chat_template_kwargs {"enable_thinking": false}.
