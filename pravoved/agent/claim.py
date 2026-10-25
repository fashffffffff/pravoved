import re
from datetime import date

from langchain_core.messages import HumanMessage, SystemMessage

from pravoved.agent import prompts
from pravoved.agent.graph import parse_json, strip_think
from pravoved.agent.tools import call_tool

CLAIM_INTENT = re.compile(r"претензи\w*", re.IGNORECASE)
CLAIM_VERB = re.compile(r"состав|напиш|подготов|сдела|оформ|нужн|помоги|написать", re.IGNORECASE)
YES = re.compile(r"^\s*(да|ага|давай|добав|конечно|угу|ок|хорошо)", re.IGNORECASE)
CANCEL = re.compile(r"^\s*(отмена|отменить|не надо|стоп)\s*[.!]?\s*$", re.IGNORECASE)

KINDS = ("consumer_refund", "consumer_penalty", "salary_delay")
ALWAYS = ["sender_name", "sender_address", "recipient", "recipient_address", "facts", "demand", "price"]
ANSWER_DAYS = 10


def is_claim_request(text):
    return bool(CLAIM_INTENT.search(text) and CLAIM_VERB.search(text))


def missing_fields(fields):
    need = list(ALWAYS)
    # срок нужен только там, где считается неустойка или компенсация
    if fields.get("kind") in ("consumer_penalty", "salary_delay"):
        need.append("due_date")
    return [f for f in need if not fields.get(f)]


def merge(fields, new):
    for key, value in new.items():
        if value in (None, "", "null"):
            continue
        if key == "kind" and value not in KINDS:
            continue
        fields[key] = value
    return fields


class ClaimSession:
    def __init__(self, llm, tools):
        self.llm = llm
        self.tools = tools
        self.fields = {}
        self.deadline = None
        self.recipient = ""
        self.waiting_calendar = False
        self.done = False

    async def extract(self, text):
        system = prompts.CLAIM_EXTRACT.format(today=date.today().strftime("%d.%m.%Y"), known=self.fields or "ничего")
        msg = await self.llm.ainvoke([SystemMessage(system), HumanMessage(text)])
        data = parse_json(strip_think(msg.content)) or {}
        merge(self.fields, data)

    async def step(self, text):
        """Один ход диалога. -> {"text": ответ, "path": файл или None}"""
        if CANCEL.match(text):
            self.done = True
            return {"text": "Хорошо, претензию не составляю."}
        if self.waiting_calendar:
            return await self.calendar_step(text)
        await self.extract(text)
        if not self.fields.get("kind"):
            return {"text": "Какая у вас ситуация: товар с недостатком и нужно вернуть деньги, просрочка доставки "
                            "или задержка зарплаты?"}
        missing = missing_fields(self.fields)
        if missing:
            return {"text": "Для претензии не хватает данных. Напишите, пожалуйста: "
                            + "; ".join(prompts.CLAIM_LABELS[f] for f in missing) + "."}
        return await self.draft()

    async def calculate(self):
        f = self.fields
        today = date.today().isoformat()
        if f["kind"] == "consumer_penalty":
            res = await call_tool(self.tools, "calc_consumer_penalty", {
                "price": float(f["price"]), "due_date": f["due_date"], "actual_date": f.get("actual_date") or today})
            return res.get("penalty"), res.get("breakdown", "")
        if f["kind"] == "salary_delay":
            res = await call_tool(self.tools, "calc_salary_delay", {
                "amount": float(f["price"]), "due_date": f["due_date"], "paid_date": f.get("actual_date") or today})
            return res.get("compensation"), res.get("breakdown", "")
        return None, ""

    async def draft(self):
        f = self.fields
        amount, breakdown = await self.calculate()
        if amount:
            sum_text = "%s руб." % amount
            f["demand"] = f["demand"].rstrip(".") + ". Сумма по расчёту: " + sum_text
        else:
            sum_text = "%s руб." % f["price"]
        args = {"kind": f["kind"], "sender_name": f["sender_name"], "sender_address": f["sender_address"],
                "sender_phone": f.get("sender_phone") or "", "recipient": f["recipient"],
                "recipient_address": f["recipient_address"], "facts": f["facts"], "demand": f["demand"],
                "amount": sum_text, "calc_breakdown": breakdown, "answer_days": ANSWER_DAYS}
        res = await call_tool(self.tools, "draft_claim", args)
        if res.get("missing"):
            # инструмент не принял поля: спрашиваем ровно их
            return {"text": "Не хватает: " + ", ".join(res["missing"]) + ". Напишите их."}
        if "path" not in res:
            self.done = True
            return {"text": "Не получилось составить претензию: %s" % res.get("error", "ошибка")}
        dl = await call_tool(self.tools, "calc_deadline", {
            "event_date": date.today().isoformat(), "days": ANSWER_DAYS, "kind": "demand_10"})
        self.deadline = dl.get("deadline")
        self.recipient = f["recipient"]
        self.waiting_calendar = True
        reply = "Претензия готова: %s\n\n%s" % (res["path"], res["preview"])
        if amount:
            reply += "\n\nСумма посчитана калькулятором: %s" % sum_text
        reply += ("\n\nСрок ответа - %d дней, до %s (если вручить претензию сегодня). "
                  "Добавить этот срок в календарь? (да/нет)" % (ANSWER_DAYS, self.deadline))
        return {"text": reply, "path": res["path"]}

    async def calendar_step(self, text):
        self.done = True
        if not YES.match(text):
            return {"text": "Хорошо, без напоминания."}
        res = await call_tool(self.tools, "add_to_calendar", {
            "title": "Срок ответа на претензию: " + self.recipient, "date": self.deadline,
            "description": "Если ответа нет, можно идти в суд и Роспотребнадзор (или трудовую инспекцию).",
            "remind_days_before": 1})
        if "path" not in res:
            return {"text": "Не получилось создать событие: %s" % res.get("error", "ошибка")}
        return {"text": "Событие сохранено: %s (откройте файл, чтобы добавить его в календарь)" % res["path"],
                "path": res["path"]}
