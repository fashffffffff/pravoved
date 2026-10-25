#!/bin/sh
# веб-интерфейс на http://localhost:8000
cd "$(dirname "$0")/.." && exec uv run python -m pravoved.web "$@"
