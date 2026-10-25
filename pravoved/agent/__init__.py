from dotenv import load_dotenv

# .env грузим сразу при импорте пакета
load_dotenv()

from pravoved.agent.run import ask  # noqa: E402
