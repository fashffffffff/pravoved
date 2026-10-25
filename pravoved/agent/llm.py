import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()


def make_llm(thinking=None):
    # модель меняется только через .env: LLM_BASE_URL, LLM_MODEL, LLM_API_KEY, LLM_THINKING
    # LLM_THINKING=answer - рассуждения только на шаге ответа, служебные вызовы без них
    if thinking is None:
        thinking = os.environ.get("LLM_THINKING", "false").lower() == "true"
    extra = None if thinking else {"chat_template_kwargs": {"enable_thinking": False}}
    return ChatOpenAI(
        base_url=os.environ.get("LLM_BASE_URL", "http://localhost:8080/v1"),
        model=os.environ.get("LLM_MODEL", "local"),
        api_key=os.environ.get("LLM_API_KEY") or "none",
        temperature=float(os.environ.get("LLM_TEMPERATURE", "0.1")),
        max_tokens=int(os.environ.get("LLM_MAX_TOKENS", "1500")),
        extra_body=extra,
        timeout=600,
        max_retries=1,
    )
