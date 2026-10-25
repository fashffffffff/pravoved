import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pravoved.agent import run as agent_run
from pravoved.corpus.meta import corpus_date

ROOT = Path(__file__).resolve().parents[2]
STATIC = Path(__file__).parent / "static"
OUT_DIR = (ROOT / "data" / "out").resolve()
MAX_UPLOAD = 20 * 1024 * 1024
FILE_EXTS = (".docx", ".ics")

state = {}


@asynccontextmanager
async def lifespan(app):
    # граф и MCP-клиент создаём один раз, они живут в event loop сервера
    state["graph"] = await agent_run.make_agent()
    state["lock"] = asyncio.Lock()
    yield


app = FastAPI(title="Правовед", lifespan=lifespan)


class Question(BaseModel):
    question: str
    web: bool = True


def sse(event, data):
    return "event: %s\ndata: %s\n\n" % (event, json.dumps(data, ensure_ascii=False, default=str))


def describe_step(node, update):
    """Короткая подпись шага для ленты на фронте"""
    if node == "retrieve":
        return "найдено фрагментов: %d" % len(update.get("hits", []))
    if node == "grade":
        if update.get("out_of_scope"):
            return "вопрос вне области"
        if update.get("retry"):
            return "мало данных, переформулирую запрос"
        return "найденного достаточно" if update.get("enough") else "найденного мало"
    if node == "web":
        return "веб-источников: %d" % len(update.get("web_sources", []))
    if node == "answer":
        n = len(update.get("tool_calls", []))
        return "вызвано калькуляторов: %d" % n if n else ""
    if node == "verify":
        return "ссылок проверено: %s, неверных: %s" % (update.get("cited", 0), update.get("invalid", 0))
    return ""


def result_files(res):
    """Файлы .docx/.ics, которые создали инструменты, как ссылки на скачивание"""
    files = []
    for c in res.get("tool_calls", []):
        try:
            data = json.loads(str(c.get("result", "")))
        except ValueError:
            continue
        path = data.get("path") if isinstance(data, dict) else None
        if not path or not str(path).endswith(FILE_EXTS):
            continue
        name = Path(path).name
        if (OUT_DIR / name).is_file() and name not in [f["name"] for f in files]:
            files.append({"name": name, "url": "/api/files/" + name})
    return files


async def stream_task(make_coro):
    """Запускает корутину и отдаёт события из очереди как SSE. make_coro(emit) -> корутина"""
    queue = asyncio.Queue()

    def emit(event, data):
        queue.put_nowait((event, data))

    async def worker():
        try:
            res = await make_coro(emit)
            emit("result", res)
        except Exception as e:
            emit("error", {"message": str(e) or e.__class__.__name__})
        emit("done", {})

    task = asyncio.create_task(worker())
    try:
        while True:
            event, data = await queue.get()
            yield sse(event, data)
            if event == "done":
                break
    finally:
        # если вкладку закрыли посреди ответа, не держим модель зря
        if not task.done():
            task.cancel()


def sse_response(gen):
    return StreamingResponse(gen, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/info")
async def info():
    d = corpus_date()
    return {
        "corpus_date": d.strftime("%d.%m.%Y") if d else None,
        "model": os.environ.get("LLM_MODEL", "local"),
        "contract": hasattr(agent_run, "check_contract"),
        "scan": hasattr(agent_run, "read_scan"),
    }


@app.post("/api/ask")
async def ask(q: Question):
    question = q.question.strip()
    if not question:
        raise HTTPException(400, "пустой вопрос")

    async def job(emit):
        # WEB_ENABLED читается из окружения, поэтому вопросы идут по одному
        async with state["lock"]:
            os.environ["WEB_ENABLED"] = "true" if q.web else "false"

            def on_step(node, update):
                emit("step", {"node": node, "detail": describe_step(node, update)})

            res = await agent_run.ask(state["graph"], question, on_step)
        res["files"] = result_files(res)
        return res

    return sse_response(stream_task(job))


async def read_upload(file):
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "файл больше 20 МБ")
    if not data:
        raise HTTPException(400, "файл пустой")
    return data


@app.post("/api/contract")
async def contract(file: UploadFile = File(...)):
    if not hasattr(agent_run, "check_contract"):
        raise HTTPException(501, "проверка договоров ещё не подключена")
    data = await read_upload(file)
    name = file.filename or "contract.txt"

    async def job(emit):
        def on_progress(done, total):
            emit("progress", {"done": done, "total": total})

        async with state["lock"]:
            return await agent_run.check_contract(state["graph"], name, data, on_progress)

    return sse_response(stream_task(job))


@app.post("/api/scan")
async def scan(file: UploadFile = File(...)):
    if not hasattr(agent_run, "read_scan"):
        raise HTTPException(501, "распознавание сканов ещё не подключено")
    data = await read_upload(file)
    try:
        text = await agent_run.read_scan(file.filename or "scan.jpg", data)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=422)
    return {"text": text}


@app.get("/api/files/{name}")
async def get_file(name: str):
    path = (OUT_DIR / name).resolve()
    if path.parent != OUT_DIR or path.suffix not in FILE_EXTS or not path.is_file():
        raise HTTPException(404, "файл не найден")
    return FileResponse(path, filename=path.name)


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
