#!/bin/sh
# веб-интерфейс на http://localhost:8501
cd "$(dirname "$0")/.." && exec uv run streamlit run pravoved/ui/app.py --server.fileWatcherType none "$@"
