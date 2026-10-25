const TRUST = {
  local: "локальная база",
  official: "официальный",
  authority: "ведомство",
  draft: "законопроект",
  unverified: "непроверенный",
};
const STEPS = {
  retrieve: "Ищу в базе законов",
  grade: "Проверяю, хватает ли найденного",
  web: "Ищу в интернете",
  answer: "Пишу ответ",
  verify: "Проверяю ссылки на статьи",
};
const EXAMPLES = [
  ["Сломался телефон через полгода после покупки. Что делать?", "потребитель"],
  ["Работодатель задерживает зарплату уже вторую неделю", "труд"],
  ["Как вернуть залог за квартиру, если хозяин не отдаёт?", "аренда"],
  ["Какой штраф грозит работодателю за задержку зарплаты?", "труд"],
  ["Какая сейчас ключевая ставка и как она влияет на неустойку?", "расчёты"],
  ["Магазин отказывается принять назад бракованный товар", "потребитель"],
];
const ICON_WARN = '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M10 3 2 17h16L10 3Z"/><path d="M10 8v4M10 14.5v.01"/></svg>';
const ICON_SUN = '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><circle cx="10" cy="10" r="3.5"/><path d="M10 2v2M10 16v2M2 10h2M16 10h2M4.3 4.3l1.4 1.4M14.3 14.3l1.4 1.4M4.3 15.7l1.4-1.4M14.3 5.7l1.4-1.4"/></svg>';
const ICON_MOON = '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M16.5 11.5A6.5 6.5 0 0 1 8.5 3.5a6.5 6.5 0 1 0 8 8Z"/></svg>';

const $ = (id) => document.getElementById(id);
const log = $("log");
const input = $("input");
const pop = $("pop");
let history = JSON.parse(localStorage.getItem("history") || "[]");
let busy = false;
let info = {};

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* markdown: только то, что реально выдаёт модель */
function inline(text, sources) {
  let s = esc(text);
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/(^|[\s(])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
  s = s.replace(/\[(\d+(?:\s*,\s*\d+)*)\]/g, (m, nums) =>
    nums.split(/\s*,\s*/).map((n) => cite(n, sources)).join(""));
  return s;
}

function cite(n, sources) {
  const known = sources.some((x) => String(x.n) === n);
  if (!known) return '<button class="cite bad" type="button" data-n="' + n + '" title="такого источника нет">' + n + "</button>";
  return '<button class="cite" type="button" data-n="' + n + '">' + n + "</button>";
}

function markdown(text, sources) {
  const lines = String(text).replace(/\r/g, "").split("\n");
  let out = "";
  let list = null;
  let para = [];
  const flush = () => {
    if (para.length) out += "<p>" + inline(para.join(" "), sources) + "</p>";
    para = [];
  };
  const close = () => {
    if (list) out += "</" + list + ">";
    list = null;
  };
  for (const raw of lines) {
    const line = raw.trimEnd();
    let m;
    if (!line.trim()) { flush(); continue; }
    if ((m = line.match(/^#{1,4}\s+(.*)$/))) { flush(); close(); out += "<h3>" + inline(m[1], sources) + "</h3>"; continue; }
    if ((m = line.match(/^\s*[-*•]\s+(.*)$/))) {
      flush();
      if (list !== "ul") { close(); out += "<ul>"; list = "ul"; }
      out += "<li>" + inline(m[1], sources) + "</li>";
      continue;
    }
    if ((m = line.match(/^\s*(\d+)[.)]\s+(.*)$/))) {
      flush();
      // нумерацию берём из текста: модель часто перемежает пункты абзацами
      if (list !== "ol") { close(); out += '<ol start="' + m[1] + '">'; list = "ol"; }
      out += "<li>" + inline(m[2], sources) + "</li>";
      continue;
    }
    if ((m = line.match(/^>\s?(.*)$/))) { flush(); close(); out += "<blockquote>" + inline(m[1], sources) + "</blockquote>"; continue; }
    close();
    para.push(line.trim());
  }
  flush();
  close();
  return out;
}

/* сообщения */
function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function trustLabel(t) {
  return '<span class="trust t-' + esc(t) + '">' + esc(TRUST[t] || t) + "</span>";
}

function sourcesHtml(sources) {
  if (!sources || !sources.length) return "";
  const rows = sources.map((s) => {
    const meta = [trustLabel(s.trust)];
    if (s.url) meta.push('<a href="' + esc(s.url) + '" target="_blank" rel="noopener noreferrer">' + esc(s.url) + "</a>");
    if (s.date) meta.push("дата: " + esc(s.date));
    return '<li class="source t-' + esc(s.trust) + '" id="src-%ID%-' + s.n + '"><span class="n">' + s.n + '</span><span class="cit">' +
      esc(s.citation) + '</span><div class="meta">' + meta.join("") + "</div>" +
      (s.via ? '<div class="via">через граф: ' + esc(s.via) + "</div>" : "") + "</li>";
  });
  return '<div class="block"><h3 class="block-title">Источники</h3><ol class="sources" style="list-style:none">' + rows.join("") + "</ol></div>";
}

function warningsHtml(r) {
  const w = [];
  if (r.warning) w.push(["", r.warning]);
  if (r.unverified_cited) w.push(["red", "В ответе есть ссылки на непроверенные источники: " + r.unverified_cited + ". Перед использованием проверьте их вручную."]);
  if (r.unbacked_numbers) w.push(["", "Проверьте цифры: " + r.unbacked_numbers + " чисел в ответе не подтверждены ни расчётом, ни источником."]);
  if (r.invalid) w.push(["red", "Ссылки на несуществующие статьи: " + r.invalid + "."]);
  return w.map(([c, t]) => '<div class="warn ' + c + '">' + ICON_WARN + "<div>" + esc(t) + "</div></div>").join("");
}

function callsHtml(calls) {
  if (!calls || !calls.length) return "";
  const body = calls.map((c) =>
    '<div class="call"><div class="name">' + esc(c.name) + "</div><pre>" + esc(JSON.stringify(c.args, null, 2)) +
    '</pre><pre class="res">' + esc(String(c.result).slice(0, 2000)) + "</pre></div>").join("");
  return '<div class="block"><details class="calc"><summary>Расчёты и вызовы инструментов (' + calls.length + ")</summary>" + body + "</details></div>";
}

function filesHtml(files) {
  if (!files || !files.length) return "";
  return '<div class="block files">' + files.map((f) =>
    '<a class="btn" href="' + esc(f.url) + '" download>Скачать ' + esc(f.name) + "</a>").join("") + "</div>";
}

function botHtml(r, id) {
  const sources = r.sources || [];
  let body;
  if (r.refused) {
    body = '<div class="refusal"><div class="label">Агент не стал отвечать</div><div class="answer">' + markdown(r.answer, sources) + "</div></div>";
  } else {
    body = '<div class="answer">' + markdown(r.answer, sources) + "</div>";
  }
  const tps = r.tokens_per_sec ? ", " + r.tokens_per_sec + " ток/с" : "";
  const html = body + warningsHtml(r) + sourcesHtml(sources).replaceAll("%ID%", id) + callsHtml(r.tool_calls) + filesHtml(r.files) +
    '<div class="footnote">' + (r.seconds || 0).toFixed(1) + " с" + tps + "</div>";
  return html;
}

function showEmpty(on) {
  $("empty").hidden = !on;
}

function addUser(text) {
  const div = el('<div class="msg-user"></div>');
  div.textContent = text;
  log.appendChild(div);
}

function addBot(r, id) {
  const div = el('<div class="msg-bot"></div>');
  div.innerHTML = botHtml(r, id);
  div._res = r;
  div.dataset.id = id;
  log.appendChild(div);
  return div;
}

function render() {
  log.innerHTML = "";
  history.forEach((m, i) => (m.role === "user" ? addUser(m.text) : addBot(m.result, i)));
  showEmpty(history.length === 0);
}

function save() {
  // в историю берём только то, что нужно для показа
  localStorage.setItem("history", JSON.stringify(history.slice(-40)));
}

/* SSE поверх fetch: POST с телом */
async function stream(url, options, on) {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    let msg = "ошибка сервера " + resp.status;
    try { msg = (await resp.json()).detail || msg; } catch (e) { /* не json */ }
    throw new Error(msg);
  }
  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i);
      buf = buf.slice(i + 2);
      const ev = (chunk.match(/^event: (.*)$/m) || [])[1];
      const data = (chunk.match(/^data: (.*)$/m) || [])[1];
      if (ev && data) on(ev, JSON.parse(data));
    }
  }
}

function makeProgress(first) {
  const box = el('<div class="msg-bot"><div class="progress"></div></div>');
  const list = box.firstChild;
  const started = Date.now();
  const clock = el('<div class="step"><span class="clock"></span></div>');
  const tick = () => { clock.firstChild.textContent = ((Date.now() - started) / 1000).toFixed(0) + " с"; };
  tick();
  const timer = setInterval(tick, 1000);
  let live = null;
  const api = {
    box,
    step(label, detail) {
      if (live) live.classList.replace("live", "done");
      live = el('<div class="step live"><span class="dot"></span><span>' + esc(label) +
        '</span><span class="detail">' + esc(detail || "") + "</span></div>");
      clock.remove();
      list.append(live, clock);
    },
    detail(detail) {
      if (live && detail) live.querySelector(".detail").textContent = detail;
    },
    stop() { clearInterval(timer); box.remove(); },
  };
  if (first) api.step(first);
  log.appendChild(box);
  return api;
}

// шаг приходит, когда узел уже закончился, поэтому следующий определяем по его итогу
function nextStep(data) {
  if (data.node === "retrieve") return "grade";
  if (data.node === "web") return "answer";
  if (data.node === "answer") return "verify";
  if (data.node === "grade") {
    if (data.detail.includes("переформулирую")) return "retrieve";
    if (data.detail.includes("мало") && $("web").checked) return "web";
    return "answer";
  }
  return null;
}

async function send(question) {
  if (busy || !question.trim()) return;
  busy = true;
  $("send").disabled = true;
  question = question.trim();
  history.push({ role: "user", text: question });
  showEmpty(false);
  addUser(question);
  input.value = "";
  autosize();

  const pr = makeProgress(STEPS.retrieve);
  scrollDown();
  let result = null;
  let error = null;
  try {
    await stream("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, web: $("web").checked }),
    }, (ev, data) => {
      if (ev === "step") {
        // шаг пришёл, когда узел уже закончился: показываем итог, потом следующий
        pr.detail(data.detail);
        const next = nextStep(data);
        if (next) pr.step(STEPS[next]);
        scrollDown();
      } else if (ev === "result") result = data;
      else if (ev === "error") error = data.message;
    });
  } catch (e) {
    error = e.message;
  }
  pr.stop();
  if (result) {
    history.push({ role: "bot", result });
    const div = addBot(result, history.length - 1);
    div.scrollIntoView({ behavior: "smooth", block: "start" });
  } else {
    log.appendChild(el('<div class="msg-bot"><div class="err">Не получилось ответить: ' + esc(error || "нет ответа от сервера") +
      ". Проверьте, что модель запущена, и повторите вопрос.</div></div>"));
    history.pop();
  }
  save();
  busy = false;
  $("send").disabled = false;
  input.focus();
}

function scrollDown() {
  window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
}

/* подсказка над [n] */
function showPop(btn) {
  const bot = btn.closest(".msg-bot");
  const src = bot && bot._res && bot._res.sources.find((s) => String(s.n) === btn.dataset.n);
  if (!src) {
    pop.innerHTML = '<div class="small">Такого источника в списке нет. Ссылке верить нельзя.</div>';
  } else {
    pop.innerHTML = trustLabel(src.trust) + '<div class="cit">' + esc(src.citation) + "</div>" +
      (src.url ? '<div class="small">' + esc(src.url) + "</div>" : "") +
      (src.date ? '<div class="small">дата: ' + esc(src.date) + "</div>" : "") +
      (src.via ? '<div class="small">через граф: ' + esc(src.via) + "</div>" : "");
  }
  pop.hidden = false;
  const r = btn.getBoundingClientRect();
  const w = pop.offsetWidth;
  const left = Math.max(12, Math.min(r.left + r.width / 2 - w / 2, window.innerWidth - w - 12));
  let top = r.bottom + 8;
  if (top + pop.offsetHeight > window.innerHeight - 12) top = r.top - pop.offsetHeight - 8;
  pop.style.left = left + "px";
  pop.style.top = top + "px";
}

log.addEventListener("mouseover", (e) => { const b = e.target.closest(".cite"); if (b) showPop(b); });
log.addEventListener("mouseout", (e) => { if (e.target.closest(".cite")) pop.hidden = true; });
log.addEventListener("focusin", (e) => { const b = e.target.closest(".cite"); if (b) showPop(b); });
log.addEventListener("focusout", () => { pop.hidden = true; });
document.addEventListener("scroll", () => { pop.hidden = true; }, { passive: true });
log.addEventListener("click", (e) => {
  const b = e.target.closest(".cite");
  if (!b) return;
  const bot = b.closest(".msg-bot");
  const row = document.getElementById("src-" + bot.dataset.id + "-" + b.dataset.n);
  if (!row) return;
  pop.hidden = true;
  row.scrollIntoView({ behavior: "smooth", block: "center" });
  row.classList.add("flash");
  setTimeout(() => row.classList.remove("flash"), 1600);
});

/* ввод */
function autosize() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, window.innerHeight * 0.4) + "px";
}
input.addEventListener("input", autosize);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    send(input.value);
  }
});
$("form").addEventListener("submit", (e) => { e.preventDefault(); send(input.value); });

$("examples").innerHTML = EXAMPLES.map(([q, tag], i) =>
  '<li><button type="button" data-i="' + i + '"><span class="q">' + esc(q) + '</span><span class="tag">' + esc(tag) + "</span></button></li>").join("");
$("examples").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (b) send(EXAMPLES[b.dataset.i][0]);
});

$("new-chat").addEventListener("click", () => {
  if (busy) return;
  history = [];
  save();
  render();
});

/* тема */
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  localStorage.setItem("theme", t);
  $("theme").innerHTML = t === "dark" ? ICON_SUN : ICON_MOON;
}
$("theme").addEventListener("click", () => applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
applyTheme(document.documentElement.dataset.theme);

$("web").checked = localStorage.getItem("web") !== "off";
$("web").addEventListener("change", () => localStorage.setItem("web", $("web").checked ? "on" : "off"));

/* вкладки */
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll(".tabs button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
  for (const v of ["chat", "contract", "scan"]) $("view-" + v).hidden = v !== b.dataset.view;
  $("dock").hidden = b.dataset.view !== "chat";
  window.scrollTo(0, 0);
}));

/* файлы */
function dropzone(id, fileId, handler) {
  const zone = $(id);
  const file = $(fileId);
  file.addEventListener("change", () => { if (file.files[0]) handler(file.files[0]); file.value = ""; });
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("over");
    if (e.dataTransfer.files[0]) handler(e.dataTransfer.files[0]);
  });
}

function upload(file) {
  const fd = new FormData();
  fd.append("file", file);
  return { method: "POST", body: fd };
}

const COLOR_NAME = { red: "Рискованно", yellow: "Осторожно", green: "Норма" };

function citeLine(c) {
  const text = typeof c === "string" ? c : c.citation || "";
  const url = c && c.url;
  return "<li>" + (url ? '<a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">' + esc(text) + "</a>" : esc(text)) + "</li>";
}

function clauseHtml(c) {
  return '<div class="clause ' + esc(c.color) + '"><div class="head"><b>' + esc(COLOR_NAME[c.color] || c.color) + "</b><span>п. " + esc(c.id) +
    "</span>" + (c.section ? "<span>" + esc(c.section) + "</span>" : "") + '</div><div class="text">' + esc(c.text) + "</div>" +
    (c.reason ? '<div class="why">' + esc(c.reason) + "</div>" : "") +
    (c.cites && c.cites.length ? '<ul class="cites">' + c.cites.map(citeLine).join("") + "</ul>" : "") + "</div>";
}

function contractHtml(r) {
  const n = r.counts || { red: 0, yellow: 0, green: 0 };
  const total = Math.max(1, n.red + n.yellow + n.green);
  const kinds = { rent: "договор найма жилья", labour: "трудовой договор", consumer: "договор с потребителем" };
  const risks = (r.top_risks || []).map((x) => "<li>п. " + esc(x.id) + ": " + esc(x.reason || x.text.slice(0, 100)) + "</li>").join("");
  const rest = r.clauses.filter((c) => c.color === "green");
  const flagged = r.clauses.filter((c) => c.color !== "green");
  return '<div class="summary"><h3>' + esc(r.filename || "Договор") + (kinds[r.kind] ? " — " + kinds[r.kind] : "") + "</h3>" +
    '<div class="bar"><i class="red" style="flex:' + n.red / total + '"></i><i class="yellow" style="flex:' + n.yellow / total +
    '"></i><i class="green" style="flex:' + n.green / total + '"></i></div>' +
    '<div class="counts"><span><b>' + n.red + "</b> рискованных</span><span><b>" + n.yellow + "</b> требуют внимания</span><span><b>" + n.green + "</b> в порядке</span></div>" +
    (risks ? '<div><div class="block-title">Главные риски</div><ul class="risks">' + risks + "</ul></div>" : "") +
    (r.invalid ? '<div class="warn red">' + ICON_WARN + "<div>Неверных ссылок на статьи: " + r.invalid + ".</div></div>" : "") + "</div>" +
    '<div class="clauses">' + flagged.map(clauseHtml).join("") + "</div>" +
    (rest.length ? '<details class="calc fold"><summary>Пункты в порядке (' + rest.length + ')</summary><div class="clauses" style="padding:12px">' +
      rest.map(clauseHtml).join("") + "</div></details>" : "") +
    '<div class="footnote">' + (r.seconds || 0).toFixed(1) + " с</div>";
}

dropzone("contract-drop", "contract-file", async (file) => {
  const out = $("contract-out");
  out.innerHTML = '<div class="progress"><div class="step live"><span class="dot"></span><span id="cp">Читаю ' + esc(file.name) + "</span></div></div>";
  let done = false;
  try {
    await stream("/api/contract", upload(file), (ev, data) => {
      if (ev === "progress") $("cp").textContent = "Проверяю пункты, часть " + data.done + " из " + data.total;
      else if (ev === "result") { out.innerHTML = contractHtml(data); done = true; }
      else if (ev === "error") { out.innerHTML = '<div class="err">' + esc(data.message) + "</div>"; done = true; }
    });
    if (!done) out.innerHTML = '<div class="err">Сервер не вернул результат.</div>';
  } catch (e) {
    out.innerHTML = '<div class="err">' + esc(e.message) + "</div>";
  }
});

dropzone("scan-drop", "scan-file", async (file) => {
  const out = $("scan-out");
  out.innerHTML = '<div class="progress"><div class="step live"><span class="dot"></span><span>Распознаю ' + esc(file.name) + "</span></div></div>";
  try {
    const resp = await fetch("/api/scan", upload(file));
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || data.detail || "ошибка " + resp.status);
    out.innerHTML = '<div class="scan-text"></div><div class="block files"><button class="btn quiet" type="button" id="copy">Скопировать текст</button></div>';
    out.firstChild.textContent = data.text || "Текст не найден.";
    $("copy").addEventListener("click", () => navigator.clipboard.writeText(data.text));
  } catch (e) {
    out.innerHTML = '<div class="err">' + esc(e.message) + "</div>";
  }
});

/* старт */
fetch("/api/info").then((r) => r.json()).then((i) => {
  info = i;
  $("corpus").textContent = i.corpus_date ? "Законы по состоянию на " + i.corpus_date : "";
  $("model").textContent = "Модель: " + i.model;
  $("contract-stub").hidden = i.contract;
  $("scan-stub").hidden = i.scan;
  $("contract-drop").hidden = !i.contract;
  $("scan-drop").hidden = !i.scan;
});
render();
