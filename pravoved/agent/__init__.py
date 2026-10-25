from dotenv import load_dotenv

# .env нужен до импорта поиска: он читает QDRANT_URL при импорте
load_dotenv()

from pravoved.agent.run import ask  # noqa: E402
