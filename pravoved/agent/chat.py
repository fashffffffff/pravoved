import re
from pathlib import Path

from pravoved.agent import run
from pravoved.agent.claim import ClaimSession, is_claim_request
from pravoved.agent.contract import read_file

CONTRACT_WORDS = re.compile(r"договор", re.IGNORECASE)
CHECK_VERBS = re.compile(r"провер|проанализир|посмотр|оцен|разбер", re.IGNORECASE)
FILE_NAME = re.compile(r"\S+\.(?:txt|docx|pdf|jpe?g|png)\b", re.IGNORECASE)
LONG_TEXT = 400


def is_contract_request(text):
    return bool(CONTRACT_WORDS.search(text) and CHECK_VERBS.search(text))


def find_file(text):
    for m in FILE_NAME.finditer(text):
        path = Path(m.group(0).strip("\"'«»")).expanduser()
        if path.is_file():
            return path
    return None


class Chat:
    """Состояние диалога: обычные вопросы, составление претензии и проверка договора."""

    def __init__(self, graph):
        self.graph = graph
        self.claim = None
        self.wait_contract = False

    async def turn(self, text, on_step=None, on_progress=None):
        """-> {"kind": "answer" | "claim" | "contract" | "text", ...}"""
        if self.claim is None and is_claim_request(text):
            self.claim = ClaimSession(run.kit["llm"], run.kit["tools"])
        if self.claim is not None:
            reply = await self.claim.step(text)
            if self.claim.done:
                self.claim = None
            return {"kind": "claim", **reply}
        if self.wait_contract or is_contract_request(text):
            return await self.turn_contract(text, on_progress)
        return {"kind": "answer", **await run.ask(self.graph, text, on_step)}

    async def turn_contract(self, text, on_progress):
        path = find_file(text)
        if path is not None:
            contract_text = await read_file(path, run.kit["tools"])
            name = path.name
        elif len(text) > LONG_TEXT:
            contract_text, name = text, ""
        elif self.wait_contract and not is_contract_request(text):
            # человек передумал и задал другой вопрос
            self.wait_contract = False
            return {"kind": "answer", **await run.ask(self.graph, text)}
        else:
            self.wait_contract = True
            return {"kind": "text", "text": "Пришлите путь к файлу договора (txt, docx, pdf, jpg) или вставьте его текст."}
        self.wait_contract = False
        res = await run.check_contract_text(contract_text, name, on_progress)
        return {"kind": "contract", "result": res}
