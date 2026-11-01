"""
BuildCore 2.9 - Help assistant, AI document reader, shortcut keys.

  Help assistant   F1 opens a help panel. Questions are answered from the BuildCore user guide (help_guide.md),
                   the screen the user is on and - if allowed - live figures the user's role may see. Without an
                   AI it still searches the guide.
  Documents        contract / specification documents (PDF, Word, text) are read into pages; the AI makes a
                   contract abstract (terms, dates, preconditions, technical requirements) with clause and page,
                   answers questions from the document; a person approves every item before it is used.
  Shortcuts        every user can make their own keys (open a screen, new entry, command, insert text); an
                   administrator can share a shortcut with everyone.

The AI is either Claude (Anthropic API, cloud) or a local OpenAI-compatible server (e.g. Ollama). Network calls
run in background threads, never while the engine's lock is held, so the AI never slows other users down.
"""
import base64
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from datetime import date, timedelta
from xml.etree import ElementTree

import core
from core import ApiError, audit, get, ins, now, q, q1, today, upd, val
from api_inventory import api as _register

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "vendor"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_config(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS ai_docs(id INTEGER PRIMARY KEY, file_id INTEGER, contract_id INTEGER, project_id INTEGER, title TEXT,
  doc_type TEXT, pages INTEGER DEFAULT 0, chars INTEGER DEFAULT 0, scanned INTEGER DEFAULT 0, status TEXT DEFAULT 'new', error TEXT,
  indexed_at TEXT, abstract_at TEXT, created_by INTEGER, created TEXT);
CREATE TABLE IF NOT EXISTS ai_doc_pages(doc_id INTEGER, page INTEGER, text TEXT, PRIMARY KEY(doc_id, page));
CREATE TABLE IF NOT EXISTS ai_items(id INTEGER PRIMARY KEY, doc_id INTEGER, contract_id INTEGER, category TEXT, title TEXT,
  detail TEXT, value TEXT, due_date TEXT, repeat TEXT, clause TEXT, page INTEGER, precondition_for TEXT, status TEXT DEFAULT 'proposed',
  citem_id INTEGER, source TEXT DEFAULT 'ai', edited_by INTEGER, edited_at TEXT, created TEXT);
CREATE INDEX IF NOT EXISTS ix_ai_items_doc ON ai_items(doc_id);
CREATE TABLE IF NOT EXISTS user_shortcuts(id INTEGER PRIMARY KEY, user_id INTEGER, combo TEXT, kind TEXT, target TEXT, label TEXT,
  everyone INTEGER DEFAULT 0, created TEXT);
CREATE TABLE IF NOT EXISTS ai_log(id INTEGER PRIMARY KEY, ts TEXT, user_id INTEGER, kind TEXT, provider TEXT, model TEXT,
  in_tokens INTEGER DEFAULT 0, out_tokens INTEGER DEFAULT 0, ok INTEGER DEFAULT 1, note TEXT);
"""

DEFAULTS = {"provider": "off", "model": "claude-sonnet-5", "base_url": "https://api.anthropic.com",
            "local_url": "http://127.0.0.1:11434/v1", "local_model": "llama3.1", "data": "1", "docs": "1"}
CATEGORIES = [("terms", "Contract terms"), ("dates", "Dates and milestones"), ("money", "Payment, advance, retention"),
              ("security", "Bonds and insurance"), ("penalty", "Liquidated damages and penalties"),
              ("notice", "Notices and claims"), ("precondition", "Preconditions"), ("technical", "Technical requirements"),
              ("testing", "Tests and inspection"), ("report", "Reports and submissions"), ("other", "Other")]
CAT_KEYS = [k for k, _ in CATEGORIES]
DOC_TYPES = ["Contract agreement", "Conditions of contract (GCC)", "Special conditions (SCC / PCC)", "Technical specifications",
             "Bill of quantities", "Letter of acceptance", "Drawings list", "Minutes / correspondence", "Other"]


def api(name, module=None, action=None, public=False):
    def wrap(f):
        def run(c, u, a):
            _ensure(c)
            return f(c, u, a)
        run.__name__, run.__doc__ = f.__name__, f.__doc__
        _register(name, module, action, public=public)(run) if public else _register(name, module, action)(run)
        return f
    return wrap


_READY = set()


def _ensure(c):
    key = os.path.normcase(core.DB_PATH)
    if key in _READY:
        return
    c.executescript(SCHEMA)
    _READY.add(key)


def init_ai(c):
    c.executescript(SCHEMA)
    _READY.add(os.path.normcase(core.DB_PATH))


# ───────────────────────── configuration ─────────────────────────
def cfg(c, key):
    r = q1(c, "SELECT value FROM ai_config WHERE key=?", (key,))
    return r["value"] if r and r["value"] is not None else DEFAULTS.get(key, "")


def _set_cfg(c, key, value):
    c.execute("INSERT INTO ai_config(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def _conf(c):
    return {k: cfg(c, k) for k in ("provider", "model", "base_url", "local_url", "local_model", "data", "docs", "key")}


def _mask(k):
    return ("•" * 8 + k[-4:]) if k else ""


@api("ai.status")
def ai_status(c, u, a):
    """What the help panel and the document screen may offer this user."""
    p = cfg(c, "provider")
    return {"provider": p, "on": p in ("claude", "local") and (p == "local" or bool(cfg(c, "key"))),
            "data": cfg(c, "data") == "1", "docs": cfg(c, "docs") == "1",
            "model": cfg(c, "model") if p == "claude" else cfg(c, "local_model"),
            "categories": CATEGORIES, "doc_types": DOC_TYPES}


@api("ai.config", "admin", "view")
def ai_config(c, u, a):
    d = _conf(c)
    d["key"] = _mask(d.get("key") or "")
    d["has_key"] = bool(cfg(c, "key"))
    d["usage"] = q(c, "SELECT substr(ts,1,7) month, kind, provider, COUNT(*) calls, SUM(in_tokens) in_tokens, SUM(out_tokens) out_tokens, "
                      "SUM(CASE WHEN ok THEN 0 ELSE 1 END) failed FROM ai_log GROUP BY 1, 2, 3 ORDER BY 1 DESC, 2 LIMIT 36")
    return d


@api("ai.config_save", "admin", "edit")
def ai_config_save(c, u, a):
    r = a.get("row") or {}
    if r.get("provider") not in (None, "off", "claude", "local"):
        raise ApiError("Choose Off, Claude or Local AI.")
    for k in ("provider", "model", "base_url", "local_url", "local_model", "data", "docs"):
        if k in r and r[k] is not None:
            _set_cfg(c, k, str(r[k]).strip())
    if r.get("key"):
        k = str(r["key"]).strip()
        if not k.startswith("•"):
            _set_cfg(c, "key", k)
    if r.get("clear_key"):
        _set_cfg(c, "key", "")
    audit(c, u, "save", "ai_config", None, {k: v for k, v in r.items() if k != "key"})
    return ai_config(c, u, {})


# ───────────────────────── background jobs ─────────────────────────
JOBS = {}
_JL = threading.Lock()
_SEM = threading.Semaphore(3)


def _company():
    try:
        import api_corp
        return api_corp.CUR.get("code") or "main"
    except Exception:
        return "main"


def _in_company(code, fn):
    """Run fn(c) on the company's data file with the engine lock held (short work only)."""
    with core.LOCK:
        try:
            import api_corp
            api_corp.switch(code)
        except Exception:
            pass
        c = core.connect()
        try:
            _ensure(c)
            c.execute("BEGIN IMMEDIATE")
            r = fn(c)
            c.commit()
            return r
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()


def _start(u, kind, work, info=None):
    jid = uuid.uuid4().hex[:16]
    job = {"id": jid, "user_id": u["id"], "kind": kind, "status": "running", "started": time.time(), "result": None,
           "error": None, "step": "Starting…", "info": info or {}}
    with _JL:
        for k in [k for k, j in JOBS.items() if time.time() - j["started"] > 3600]:
            JOBS.pop(k, None)
        JOBS[jid] = job

    def runner():
        with _SEM:
            try:
                job["result"] = work(job)
                job["status"] = "done"
            except ApiError as e:
                job["status"], job["error"] = "failed", str(e)
            except Exception as e:  # pragma: no cover
                job["status"], job["error"] = "failed", "The AI request failed: %s" % e
                try:
                    core.log_error("ai job " + kind) if hasattr(core, "log_error") else None
                except Exception:
                    pass
    threading.Thread(target=runner, daemon=True).start()
    return {"job": jid}


@api("ai.job")
def ai_job(c, u, a):
    j = JOBS.get(a.get("id") or "")
    if not j or j["user_id"] != u["id"]:
        raise ApiError("This request is no longer available. Ask again.")
    return {k: j[k] for k in ("id", "kind", "status", "result", "error", "step")}


# ───────────────────────── talking to the AI ─────────────────────────
def _post(url, body, headers, timeout=180):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=dict(headers, **{"content-type": "application/json"}), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8"))
            msg = (msg.get("error") or {}).get("message") or str(msg)
        except Exception:
            msg = str(e)
        if e.code == 401:
            raise ApiError("The AI key was refused. An administrator checks it in Administration › AI settings.")
        if e.code == 429:
            raise ApiError("The AI service is busy or the account limit is reached. Try again in a minute. (%s)" % msg[:200])
        if e.code == 413 or "too long" in msg.lower() or "too large" in msg.lower():
            raise ApiError("The document is too large for one request: %s" % msg[:200])
        raise ApiError("The AI service answered with an error (%s): %s" % (e.code, msg[:300]))
    except urllib.error.URLError as e:
        raise ApiError("Cannot reach the AI service (%s). Check the internet connection, or the address in AI settings." % getattr(e, "reason", e))
    except TimeoutError:
        raise ApiError("The AI service did not answer in time. Try again.")


class AI:
    """One conversation with the configured AI. Claude: Messages API with tools; local: OpenAI-compatible chat."""

    def __init__(self, conf, company, user_id, kind):
        self.conf, self.company, self.user_id, self.kind = conf, company, user_id, kind
        self.provider = conf.get("provider")
        if self.provider not in ("claude", "local"):
            raise ApiError("The AI is switched off. An administrator switches it on in Administration › AI settings.")
        if self.provider == "claude" and not conf.get("key"):
            raise ApiError("No AI key is set. An administrator enters it in Administration › AI settings.")
        self.tin = self.tout = 0

    def _log(self, ok, note=""):
        try:
            model = self.conf.get("model") if self.provider == "claude" else self.conf.get("local_model")
            _in_company(self.company, lambda c: ins(c, "ai_log", {"ts": now(), "user_id": self.user_id, "kind": self.kind, "provider": self.provider,
                                                                "model": model, "in_tokens": self.tin, "out_tokens": self.tout, "ok": 1 if ok else 0,
                                                                "note": note[:300]}))
        except Exception:
            pass

    def message(self, system, messages, tools=None, tool_choice=None, max_tokens=4000):
        """One call. Returns the content blocks (Claude format) and the stop reason."""
        try:
            if self.provider == "claude":
                body = {"model": self.conf.get("model") or DEFAULTS["model"], "max_tokens": max_tokens,
                        "system": system, "messages": messages}
                if tools:
                    body["tools"] = tools
                if tool_choice:
                    body["tool_choice"] = tool_choice
                url = (self.conf.get("base_url") or DEFAULTS["base_url"]).rstrip("/") + "/v1/messages"
                r = _post(url, body, {"x-api-key": self.conf["key"], "anthropic-version": "2023-06-01"})
                us = r.get("usage") or {}
                self.tin += int(us.get("input_tokens") or 0) + int(us.get("cache_read_input_tokens") or 0) + int(us.get("cache_creation_input_tokens") or 0)
                self.tout += int(us.get("output_tokens") or 0)
                return r.get("content") or [], r.get("stop_reason")
            # local, OpenAI-compatible: text only, no tools, no PDF
            sys_text = system if isinstance(system, str) else "\n\n".join(b.get("text", "") for b in system)
            msgs = [{"role": "system", "content": sys_text}]
            for m in messages:
                cont = m["content"]
                if not isinstance(cont, str):
                    cont = "\n".join(b.get("text", "") if b.get("type") == "text" else
                                     ("[tool result] " + str(b.get("content", ""))) if b.get("type") == "tool_result" else "" for b in cont)
                msgs.append({"role": m["role"], "content": cont})
            if tool_choice and tools:
                msgs[0]["content"] += ("\n\nAnswer ONLY with JSON matching this schema, no other text:\n" +
                                       json.dumps(tools[0]["input_schema"]))
            url = (self.conf.get("local_url") or DEFAULTS["local_url"]).rstrip("/") + "/chat/completions"
            r = _post(url, {"model": self.conf.get("local_model") or DEFAULTS["local_model"], "messages": msgs, "max_tokens": max_tokens,
                            "temperature": 0.2}, {"Authorization": "Bearer local"}, timeout=600)
            us = r.get("usage") or {}
            self.tin += int(us.get("prompt_tokens") or 0)
            self.tout += int(us.get("completion_tokens") or 0)
            text = ((r.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            if tool_choice and tools:
                m = re.search(r"\{.*\}", text, re.S)
                try:
                    return [{"type": "tool_use", "id": "local", "name": tools[0]["name"], "input": json.loads(m.group(0) if m else text)}], "tool_use"
                except Exception:
                    raise ApiError("The local AI did not answer in the expected form. Try a larger local model, or Claude.")
            return [{"type": "text", "text": text}], "end_turn"
        except ApiError as e:
            self._log(False, str(e))
            raise


def _text_of(blocks):
    return "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()


# ───────────────────────── the user guide ─────────────────────────
_GUIDE = {"mtime": None, "topics": [], "text": ""}


def guide():
    p = os.path.join(HERE, "help_guide.md")
    try:
        m = os.path.getmtime(p)
    except OSError:
        return _GUIDE
    if _GUIDE["mtime"] == m:
        return _GUIDE
    with open(p, encoding="utf-8") as f:
        text = f.read()
    topics = []
    for part in re.split(r"\n(?=## )", text):
        if not part.startswith("## "):
            continue
        lines = part.split("\n")
        title = lines[0][3:].strip()
        keys = screens = ""
        body = []
        for ln in lines[1:]:
            if ln.startswith("keys:"):
                keys = ln[5:].strip()
            elif ln.startswith("screens:"):
                screens = ln[8:].strip()
            else:
                body.append(ln)
        topics.append({"id": len(topics) + 1, "title": title, "keys": keys, "screens": [s.strip() for s in screens.split(",") if s.strip()],
                       "body": "\n".join(body).strip()})
    _GUIDE.update(mtime=m, topics=topics, text=text)
    return _GUIDE


_STOP = set("a an the and or of to in on for is are be it this that how do i my we our can what where when which with from by at as "
            "make add new show see get use why not does".split())


def _words(s):
    return [w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if w not in _STOP and len(w) > 1]


def guide_search(question, page=None, n=4):
    ws = _words(question)
    out = []
    for t in guide()["topics"]:
        hay_t = t["title"].lower()
        hay = (t["title"] + " " + t["keys"] + " " + t["body"]).lower()
        s = 0.0
        for w in ws:
            if w in hay_t:
                s += 4
            s += min(hay.count(w), 5)
            if len(w) > 4 and w[:-1] in hay:
                s += 0.5
        if page and page in t["screens"]:
            s += 3
        if s > 0:
            out.append((s, t))
    out.sort(key=lambda x: -x[0])
    return [t for _, t in out[:n]]


@api("help.search")
def help_search(c, u, a):
    return {"topics": guide_search(a.get("q") or "", a.get("page"), int(a.get("n") or 5))}


@api("help.guide")
def help_guide(c, u, a):
    return {"topics": guide()["topics"]}


# ───────────────────────── live figures the assistant may look up ─────────────────────────
LOOKUPS = {
    "stock_by_store": ("store.view", "inventory", False, "Stock on hand by store and kind (consumables, tools, spares); search a material name."),
    "reorder_risk": ("stock.risk", "inventory", True, "Materials below reorder level or running out (needs a project)."),
    "pending_purchase_orders": ("po.pending", "procurement", False, "Purchase orders still to be delivered, late ones first."),
    "approvals_waiting": ("dash.approvals", None, False, "Documents waiting for approval."),
    "store_kpis": ("kpi.store", "inventory", False, "Store and procurement KPIs for the last 90 days."),
    "finance_kpis": ("kpi.finance", "accounts", False, "Cash, receivables, payables, VAT, profit."),
    "contracts_due": ("con.schedule", "commercial", False, "Contract letters, reports, deliveries, milestones due; expiring bonds and insurance."),
    "machines": ("eq.kpi", "equipment", False, "Each machine: status, hours, availability, utilisation, cost."),
    "machine_history": ("eq.history", "equipment", False, "Repairs and maintenance history of machines."),
    "maintenance_due": ("maint.status", "equipment", False, "Services due by hours or days."),
    "work_orders": ("wo.list", "equipment", False, "Breakdowns and work orders."),
    "party_balances": ("rep.party_summary", "accounts", False, "What each vendor / client owes or is owed."),
    "ageing": ("rep.ageing", "accounts", False, "Ageing of receivables and payables."),
    "dpr_list": ("dpr.list", "project", True, "Daily progress reports of a project."),
    "ipc_list": ("ipc.list", "commercial", True, "Client bills (IPC) of a project."),
    "boq_control": ("boq.control", "commercial", True, "BOQ quantities measured, billed and cost of a project."),
    "assets": ("asset.summary", "assets", False, "Asset register summary."),
}


def _lookup_tool():
    return {"name": "buildcore_lookup",
            "description": "Read live figures from this company's BuildCore data (read only, limited to what the user's role may see). "
                           "Reports: " + "; ".join("%s = %s" % (k, v[3]) for k, v in LOOKUPS.items()),
            "input_schema": {"type": "object", "properties": {
                "report": {"type": "string", "enum": list(LOOKUPS)},
                "project": {"type": "string", "description": "Project code or name, for reports that need one."},
                "search": {"type": "string", "description": "Optional word to keep only matching rows (a material, party, machine …)."}},
                "required": ["report"]}}


def _filter(data, word):
    if not word:
        return data
    w = word.lower()
    if isinstance(data, list):
        rows = [r for r in data if w in json.dumps(r, default=str).lower()]
        return rows
    if isinstance(data, dict):
        return {k: (_filter(v, word) if isinstance(v, list) else v) for k, v in data.items()}
    return data


def _run_lookup(company, token, user, inp):
    name = inp.get("report")
    if name not in LOOKUPS:
        return "Unknown report."
    fn, module, needs_project, _d = LOOKUPS[name]
    if module and not core.can(user, module, "view"):
        return "The user's role (%s) may not see %s; say so and suggest asking an administrator." % (user["role"], module)
    args = {}
    if needs_project or inp.get("project"):
        def find(c):
            p = (inp.get("project") or "").strip()
            if p:
                r = q1(c, "SELECT id FROM projects WHERE lower(code)=lower(?) OR lower(name)=lower(?)", (p, p)) or \
                    q1(c, "SELECT id FROM projects WHERE lower(name) LIKE ? OR lower(code) LIKE ?", ("%" + p.lower() + "%", "%" + p.lower() + "%"))
            else:
                r = q1(c, "SELECT id FROM projects ORDER BY id LIMIT 1") if val(c, "SELECT COUNT(*) FROM projects") == 1 else None
            return r["id"] if r else None
        pid = _in_company(company, find)
        if needs_project and not pid:
            names = _in_company(company, lambda c: [r["code"] + " - " + r["name"] for r in q(c, "SELECT code, name FROM projects ORDER BY code LIMIT 30")])
            return "This report needs a project. Projects: " + "; ".join(names)
        if pid:
            args["project_id"] = pid
    if name == "contracts_due":
        args["days"] = 60
    import api_corp
    srv = api_corp._server_mod()
    with core.LOCK:
        api_corp.switch(company)
        try:
            data = srv.call(fn, args, token)
        except ApiError as e:
            return "The report could not be read: %s" % e
        except Exception as e:
            return "The report could not be read: %s" % e
    data = _filter(data, inp.get("search"))
    s = json.dumps(data, default=str, ensure_ascii=False)
    if len(s) > 14000:
        s = s[:14000] + " … (cut: ask the user to narrow the search)"
    return s


# ───────────────────────── Help assistant ─────────────────────────
SYS_HELP = """You are the BuildCore Help assistant inside BuildCore, a construction project control, store, procurement,
accounts (Tally-style) and equipment program used by construction companies in Nepal.

How to answer:
- Answer the user's question about using BuildCore, briefly and practically, in the user's language (English or Nepali).
- Give steps as a short numbered list. Name the exact screen and the keys (BuildCore uses Tally-style keys).
- Link screens as Markdown links to their path, e.g. [Goods received](#/inv/grn). Only use paths that appear in the
  screen list or the guide. Never invent screens, buttons or features; if the guide does not cover it, say so and
  suggest the nearest screen or asking an administrator.
- You only guide and look things up. You cannot post, approve, change or delete anything: tell the user what to do.
- For live figures use the buildcore_lookup tool when it is available, and say the figures come from BuildCore now.
- Accounting, tax and contract questions: explain how BuildCore handles them; you are not a lawyer or tax adviser.
"""


@api("ai.ask")
def ai_ask(c, u, a):
    """Ask the Help assistant. Answers from the guide at once when the AI is off; else starts a background job."""
    question = (a.get("question") or "").strip()
    if not question:
        raise ApiError("Type a question.")
    page = (a.get("page") or "").strip()
    hits = guide_search(question + " " + (a.get("page_title") or ""), page)
    st = ai_status(c, u, {})
    if not st["on"]:
        return {"offline": True, "topics": hits}
    conf = _conf(c)
    company = _company()
    token = a.get("_token")
    user = dict(u)
    screens = a.get("screens") or []
    screen = (a.get("screen_text") or "")[:20000]
    history = [m for m in (a.get("history") or [])[-10:] if m.get("role") in ("user", "assistant") and m.get("text")]

    def work(job):
        ai = AI(conf, company, user["id"], "help")
        g = guide()
        scr = "\n".join("%s | %s | %s" % (s.get("path"), s.get("label"), s.get("group")) for s in screens[:400])
        system = [{"type": "text", "text": SYS_HELP + "\n\n# BuildCore user guide\n" + g["text"] +
                   "\n\n# Screens the user can open (path | name | module)\n" + scr,
                   "cache_control": {"type": "ephemeral"}},
                  {"type": "text", "text": "User: %s, role %s. Today %s. Company data: %s. The user is on screen: %s (%s)." % (
                      user.get("name"), user.get("role"), today(), "can be looked up" if st["data"] else "not available to the assistant",
                      page or "Modules screen", a.get("page_title") or "")}]
        msgs = []
        for m in history:
            if msgs and msgs[-1]["role"] == m["role"]:
                msgs[-1]["content"] += "\n" + m["text"]
            else:
                msgs.append({"role": m["role"], "content": m["text"]})
        while msgs and msgs[0]["role"] != "user":
            msgs.pop(0)
        msgs.append({"role": "user", "content": question + (("\n\n[What is on my screen now - " + (a.get("page_title") or page) + "]\n" + screen) if screen else "")})
        tools = [_lookup_tool()] if (st["data"] and ai.provider == "claude") else None
        looked = []
        for _round in range(6):
            job["step"] = "Thinking…" if not looked else "Reading %s…" % ", ".join(looked[-2:])
            blocks, stop = ai.message(system, msgs, tools=tools, max_tokens=2500)
            if stop != "tool_use":
                break
            msgs.append({"role": "assistant", "content": blocks})
            results = []
            for b in blocks:
                if b.get("type") == "tool_use":
                    looked.append(b.get("input", {}).get("report", "figures"))
                    results.append({"type": "tool_result", "tool_use_id": b["id"], "content": _run_lookup(company, token, user, b.get("input") or {})})
            msgs.append({"role": "user", "content": results})
        answer = _text_of(blocks) or "I could not find an answer. Try asking differently, or look at the guide topics below."
        ai._log(True, question[:120])
        return {"answer": answer, "topics": hits[:3], "looked_up": looked}
    return _start(u, "help", work)


# ───────────────────────── documents: text ─────────────────────────
def _file_path(c, file_id):
    f = q1(c, "SELECT * FROM files WHERE id=?", (file_id,))
    if not f:
        raise ApiError("The file is missing.")
    import api_project
    return f, os.path.join(api_project.FILES_DIR, os.path.basename(f["stored"]))


def extract_pages(path, name):
    """[(page_no, text)] from a PDF, Word (.docx) or text file."""
    ext = os.path.splitext(name or path)[1].lower()
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
        except Exception as e:
            raise ApiError("The PDF reader is missing from this BuildCore (%s). Run the update again." % e)
        rd = PdfReader(path)
        if rd.is_encrypted:
            try:
                rd.decrypt("")
            except Exception:
                raise ApiError("The PDF is password-protected. Save an unprotected copy and upload that.")
        out = []
        for i, pg in enumerate(rd.pages):
            try:
                t = pg.extract_text() or ""
            except Exception:
                t = ""
            out.append((i + 1, re.sub(r"[ \t]+", " ", t).strip()))
        return out
    if ext == ".docx":
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml")
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        root = ElementTree.fromstring(xml)
        paras, pages, cur = [], [], []
        for p in root.iter(ns + "p"):
            texts = []
            brk = False
            for el in p.iter():
                if el.tag == ns + "t" and el.text:
                    texts.append(el.text)
                elif el.tag == ns + "tab":
                    texts.append("\t")
                elif el.tag == ns + "br" and el.get(ns + "type") == "page":
                    brk = True
                elif el.tag == ns + "lastRenderedPageBreak":
                    brk = True
            if brk and cur:
                pages.append("\n".join(cur))
                cur = []
            cur.append("".join(texts))
        if cur:
            pages.append("\n".join(cur))
        # long documents without page marks: about 3500 characters to a page
        out = []
        for t in pages:
            while len(t) > 7000:
                cut = t.rfind("\n", 0, 3500)
                cut = cut if cut > 1000 else 3500
                out.append(t[:cut])
                t = t[cut:]
            out.append(t)
        return [(i + 1, t.strip()) for i, t in enumerate(out)]
    if ext in (".txt", ".md", ".csv"):
        with open(path, "rb") as f:
            raw = f.read()
        try:
            t = raw.decode("utf-8")
        except UnicodeDecodeError:
            t = raw.decode("latin-1")
        chunks = [t[i:i + 3500] for i in range(0, len(t), 3500)] or [""]
        return [(i + 1, x) for i, x in enumerate(chunks)]
    if ext == ".doc":
        raise ApiError("Old Word files (.doc) cannot be read. Open it in Word and save as .docx or PDF, then upload that.")
    raise ApiError("BuildCore reads PDF, Word (.docx) and text files.")


def _index(company, doc_id):
    def load(c):
        d = get(c, "ai_docs", doc_id, "Document")
        f, path = _file_path(c, d["file_id"])
        upd(c, "ai_docs", doc_id, {"status": "indexing", "error": None})
        return d, f, path
    d, f, path = _in_company(company, load)
    try:
        pages = extract_pages(path, f["filename"])
    except ApiError as e:
        _in_company(company, lambda c: upd(c, "ai_docs", doc_id, {"status": "failed", "error": str(e)}))
        raise
    except Exception as e:
        msg = "The document could not be read: %s" % e
        _in_company(company, lambda c: upd(c, "ai_docs", doc_id, {"status": "failed", "error": msg}))
        raise ApiError(msg)
    chars = sum(len(t) for _, t in pages)
    scanned = 1 if pages and chars / max(len(pages), 1) < 80 else 0

    def save(c):
        c.execute("DELETE FROM ai_doc_pages WHERE doc_id=?", (doc_id,))
        c.executemany("INSERT INTO ai_doc_pages(doc_id, page, text) VALUES(?,?,?)", [(doc_id, n, t) for n, t in pages])
        upd(c, "ai_docs", doc_id, {"status": "ready", "pages": len(pages), "chars": chars, "scanned": scanned, "indexed_at": now(), "error": None})
    _in_company(company, save)
    return {"pages": len(pages), "chars": chars, "scanned": scanned}


@api("doc.list", "commercial", "view")
def doc_list(c, u, a):
    cond, p = "1=1", []
    if a.get("contract_id"):
        cond += " AND d.contract_id=?"
        p.append(int(a["contract_id"]))
    rows = q(c, "SELECT d.*, f.filename, f.size, k.title contract, (SELECT COUNT(*) FROM ai_items i WHERE i.doc_id=d.id) items, "
                "(SELECT COUNT(*) FROM ai_items i WHERE i.doc_id=d.id AND i.status='proposed') to_check, "
                "(SELECT COUNT(*) FROM ai_items i WHERE i.doc_id=d.id AND i.status='approved') approved "
                "FROM ai_docs d LEFT JOIN files f ON f.id=d.file_id LEFT JOIN contracts k ON k.id=d.contract_id WHERE " + cond +
             " ORDER BY d.id DESC", p)
    return rows


@api("doc.add", "commercial", "edit")
def doc_add(c, u, a):
    """Register an uploaded file as a document and start reading its text."""
    fid = int(a.get("file_id") or 0)
    f = q1(c, "SELECT * FROM files WHERE id=?", (fid,))
    if not f:
        raise ApiError("Upload the file first.")
    did = ins(c, "ai_docs", {"file_id": fid, "contract_id": int(a["contract_id"]) if a.get("contract_id") else None,
                             "project_id": int(a["project_id"]) if a.get("project_id") else None,
                             "title": (a.get("title") or os.path.splitext(f["filename"])[0])[:200], "doc_type": a.get("doc_type") or "Other",
                             "status": "new", "created_by": u["id"], "created": now()})
    upd(c, "files", fid, {"entity": "ai_doc", "entity_id": did})
    audit(c, u, "add", "ai_docs", did, {"file": f["filename"]})
    company = _company()
    job = _start(u, "index", lambda j: _index(company, did))
    return {"id": did, "job": job["job"]}


@api("doc.reindex", "commercial", "edit")
def doc_reindex(c, u, a):
    d = get(c, "ai_docs", int(a["id"]), "Document")
    company = _company()
    return _start(u, "index", lambda j: _index(company, d["id"]))


@api("doc.update", "commercial", "edit")
def doc_update(c, u, a):
    d = get(c, "ai_docs", int(a["id"]), "Document")
    data = {}
    for k in ("title", "doc_type"):
        if k in a:
            data[k] = a[k]
    if "contract_id" in a:
        data["contract_id"] = int(a["contract_id"]) if a["contract_id"] else None
    upd(c, "ai_docs", d["id"], data)
    if "contract_id" in data:
        c.execute("UPDATE ai_items SET contract_id=? WHERE doc_id=? AND citem_id IS NULL", (data["contract_id"], d["id"]))
    return True


@api("doc.delete", "commercial", "approve")
def doc_delete(c, u, a):
    d = get(c, "ai_docs", int(a["id"]), "Document")
    c.execute("DELETE FROM ai_doc_pages WHERE doc_id=?", (d["id"],))
    c.execute("DELETE FROM ai_items WHERE doc_id=? AND citem_id IS NULL", (d["id"],))
    c.execute("UPDATE ai_items SET doc_id=NULL WHERE doc_id=?", (d["id"],))
    c.execute("DELETE FROM ai_docs WHERE id=?", (d["id"],))
    audit(c, u, "delete", "ai_docs", d["id"], d)
    return True


@api("doc.get", "commercial", "view")
def doc_get(c, u, a):
    d = get(c, "ai_docs", int(a["id"]), "Document")
    d["file"] = q1(c, "SELECT id, filename, size, mime FROM files WHERE id=?", (d["file_id"],))
    d["contract"] = q1(c, "SELECT id, title, ref_no FROM contracts WHERE id=?", (d["contract_id"],)) if d["contract_id"] else None
    d["items"] = q(c, "SELECT * FROM ai_items WHERE doc_id=? ORDER BY CASE status WHEN 'proposed' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END, "
                      "category, page, id", (d["id"],))
    return d


@api("doc.page", "commercial", "view")
def doc_page(c, u, a):
    r = q1(c, "SELECT page, text FROM ai_doc_pages WHERE doc_id=? AND page=?", (int(a["id"]), int(a.get("page") or 1)))
    if not r:
        raise ApiError("No such page.")
    r["pages"] = val(c, "SELECT COUNT(*) FROM ai_doc_pages WHERE doc_id=?", (int(a["id"]),))
    return r


def _search_pages(c, doc_ids, text, n=12):
    ws = _words(text)
    if not ws:
        return []
    marks = ",".join("?" * len(doc_ids))
    rows = q(c, "SELECT p.doc_id, p.page, p.text, d.title FROM ai_doc_pages p JOIN ai_docs d ON d.id=p.doc_id WHERE p.doc_id IN (%s)" % marks, doc_ids)
    out = []
    phrase = (text or "").strip().lower()
    for r in rows:
        low = r["text"].lower()
        s = sum(min(low.count(w), 8) for w in ws) + (10 if len(phrase) > 4 and phrase in low else 0)
        hit = sum(1 for w in ws if w in low)
        if not s:
            continue
        s += hit * 3
        i = -1
        for w in [phrase] + sorted(ws, key=len, reverse=True):
            i = low.find(w)
            if i >= 0:
                break
        a0 = max(0, i - 220)
        snippet = ("…" if a0 else "") + r["text"][a0:a0 + 520].replace("\n", " ") + "…"
        out.append({"doc_id": r["doc_id"], "title": r["title"], "page": r["page"], "score": s, "snippet": snippet})
    out.sort(key=lambda x: -x["score"])
    return out[:n]


@api("doc.search", "commercial", "view")
def doc_search(c, u, a):
    ids = [int(x) for x in (a.get("ids") or ([a["id"]] if a.get("id") else []))] or \
          [r["id"] for r in q(c, "SELECT id FROM ai_docs WHERE status='ready'")]
    if not ids:
        return []
    return _search_pages(c, ids, a.get("q") or "", int(a.get("n") or 15))


# ───────────────────────── documents: AI ─────────────────────────
ITEM_TOOL = {"name": "record_contract_items",
             "description": "Record what the document requires, one item per obligation, right, date, amount, precondition or requirement.",
             "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
                 "category": {"type": "string", "enum": CAT_KEYS},
                 "title": {"type": "string", "description": "Short name, e.g. 'Performance bond', 'Liquidated damages', 'Slump test frequency'."},
                 "detail": {"type": "string", "description": "What the document says, in plain words, with numbers; who must do what, by when."},
                 "value": {"type": "string", "description": "The key figure: amount, percentage, period or limit, e.g. '10% of contract price', '28 days'."},
                 "due_date": {"type": "string", "description": "YYYY-MM-DD only when the document gives or allows working out a date; else empty."},
                 "repeat": {"type": "string", "enum": ["none", "weekly", "fortnightly", "monthly", "quarterly", "yearly"]},
                 "precondition_for": {"type": "string", "description": "For preconditions: what it is required before (e.g. 'start of concreting', 'payment of advance', 'claim for extension')."},
                 "clause": {"type": "string", "description": "Clause / section number as printed, e.g. 'GCC 14.2', 'TS 5.3.1'."},
                 "page": {"type": "integer", "description": "Page number where it is written ([Page n] markers)."}},
                 "required": ["category", "title", "detail"]}}}, "required": ["items"]}}

SYS_DOC = """You read construction contract documents for a Nepali construction company (contract agreements, GCC/SCC/PCC,
technical specifications, BOQ, letters). Be exact: copy numbers, percentages and periods as written, with the clause and
page. Never invent anything that is not in the text; if a value is not stated, leave it empty. Dates only as YYYY-MM-DD.
Where a date depends on another date (e.g. '28 days after commencement') put the rule in detail and leave due_date empty
unless the commencement date is given."""

ABSTRACT_ASK = """Make a contract abstract of this document by calling record_contract_items. Cover, where the document has them:
- terms: parties, contract price, contract type (item rate / lump sum), scope, governing law, language.
- dates: commencement, completion, milestones, intended completion, extension rules.
- money: mobilisation advance and its recovery, interim payment period, retention %, release of retention, price adjustment, VAT/TDS, final bill.
- security: performance security / bond (amount, validity), advance guarantee, insurance (types, amounts, validity).
- penalty: liquidated damages (rate and maximum), other deductions.
- notice: notices and their time limits (claims, delays, variations, disputes), dispute resolution steps.
- precondition: things that must be done or approved BEFORE something else may happen (before commencement, before
  concreting / a pour, before covering work, before payment of advance or a bill, before a claim or an extension of time).
- technical / testing: material requirements and grades, tests with frequency, tolerances, approvals of samples, method statements.
- report: reports and submissions with their frequency (monthly progress report, programme updates, as-built drawings).
Group nothing together that has different numbers. Use one item per requirement."""


def _doc_content(company, doc_id, focus=None, limit=300000):
    """Text of the document with [Page n] markers; for long documents, the pages that match the focus."""
    def load(c):
        d = get(c, "ai_docs", doc_id, "Document")
        pages = q(c, "SELECT page, text FROM ai_doc_pages WHERE doc_id=? ORDER BY page", (doc_id,))
        f, path = _file_path(c, d["file_id"])
        return d, pages, f, path
    d, pages, f, path = _in_company(company, load)
    if d["status"] != "ready":
        raise ApiError("The document has not been read yet (%s). Wait for it, or press Read again." % d["status"])
    return d, pages, f, path


def _pdf_block(path):
    size = os.path.getsize(path)
    if size > 30 * 1024 * 1024:
        raise ApiError("This scanned PDF is larger than 30 MB. Split it into parts of up to 100 pages and upload them separately.")
    with open(path, "rb") as fh:
        data = base64.b64encode(fh.read()).decode("ascii")
    return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}


def _chunks(pages, size):
    cur, n, out = [], 0, []
    for p in pages:
        t = "[Page %d]\n%s\n" % (p["page"], p["text"])
        if cur and n + len(t) > size:
            out.append("".join(cur))
            cur, n = [], 0
        cur.append(t)
        n += len(t)
    if cur:
        out.append("".join(cur))
    return out


@api("doc.abstract", "commercial", "edit")
def doc_abstract(c, u, a):
    """Read the document with the AI and propose contract-abstract items (each to be checked by a person)."""
    did = int(a["id"])
    d = get(c, "ai_docs", did, "Document")
    st = ai_status(c, u, {})
    if not st["on"] or not st["docs"]:
        raise ApiError("The AI document reader is switched off. An administrator switches it on in Administration › AI settings. "
                       "You can still use Search on this document.")
    conf, company, user = _conf(c), _company(), dict(u)

    def work(job):
        d, pages, f, path = _doc_content(company, did)
        ai = AI(conf, company, user["id"], "abstract")
        items = []
        if d["scanned"]:
            if ai.provider != "claude":
                raise ApiError("This PDF is scanned (no text in it). Only the Claude AI can read scanned pages.")
            if d["pages"] > 100:
                raise ApiError("This scanned PDF has %d pages; the AI reads up to 100 pages of scanned PDF at a time. Split it and upload the parts." % d["pages"])
            job["step"] = "Reading the scanned pages…"
            blocks, _s = ai.message(SYS_DOC, [{"role": "user", "content": [_pdf_block(path), {"type": "text", "text": ABSTRACT_ASK + "\nThe page numbers are the PDF's pages."}]}],
                                    tools=[ITEM_TOOL], tool_choice={"type": "tool", "name": ITEM_TOOL["name"]}, max_tokens=12000)
            items += [it for b in blocks if b.get("type") == "tool_use" for it in (b.get("input") or {}).get("items") or []]
        else:
            parts = _chunks(pages, 240000 if ai.provider == "claude" else 24000)
            for i, part in enumerate(parts):
                job["step"] = "Reading part %d of %d…" % (i + 1, len(parts)) if len(parts) > 1 else "Reading the document…"
                ask = ABSTRACT_ASK + ("\n(This is part %d of %d of the document.)" % (i + 1, len(parts)) if len(parts) > 1 else "")
                blocks, _s = ai.message(SYS_DOC, [{"role": "user", "content": [{"type": "text", "text": "Document: %s (%s)\n\n%s" % (d["title"], d["doc_type"], part)},
                                                                               {"type": "text", "text": ask}]}],
                                        tools=[ITEM_TOOL], tool_choice={"type": "tool", "name": ITEM_TOOL["name"]}, max_tokens=12000)
                items += [it for b in blocks if b.get("type") == "tool_use" for it in (b.get("input") or {}).get("items") or []]
        job["step"] = "Saving…"

        def save(c):
            c.execute("DELETE FROM ai_items WHERE doc_id=? AND status='proposed' AND source='ai'", (did,))
            n = 0
            for it in items:
                if not isinstance(it, dict) or not it.get("title"):
                    continue
                dd = (it.get("due_date") or "").strip()
                if not re.match(r"^\d{4}-\d{2}-\d{2}$", dd):
                    dd = None
                try:
                    pg = int(it.get("page")) if it.get("page") not in (None, "") else None
                except (TypeError, ValueError):
                    pg = None
                ins(c, "ai_items", {"doc_id": did, "contract_id": d["contract_id"], "category": it.get("category") if it.get("category") in CAT_KEYS else "other",
                                    "title": str(it.get("title"))[:200], "detail": str(it.get("detail") or "")[:4000], "value": str(it.get("value") or "")[:200],
                                    "due_date": dd, "repeat": it.get("repeat") if it.get("repeat") in ("none", "weekly", "fortnightly", "monthly", "quarterly", "yearly") else "none",
                                    "clause": str(it.get("clause") or "")[:80], "page": pg, "precondition_for": str(it.get("precondition_for") or "")[:200],
                                    "status": "proposed", "source": "ai", "created": now()})
                n += 1
            upd(c, "ai_docs", did, {"abstract_at": now()})
            audit(c, user, "ai_abstract", "ai_docs", did, {"items": n})
            return n
        n = _in_company(company, save)
        ai._log(True, "%s: %d items" % (d["title"], n))
        return {"items": n}
    return _start(u, "abstract", work)


@api("doc.ask", "commercial", "view")
def doc_ask(c, u, a):
    """A question answered from one or more documents, with clause and page."""
    question = (a.get("question") or "").strip()
    if not question:
        raise ApiError("Type a question.")
    ids = [int(x) for x in (a.get("ids") or ([a["id"]] if a.get("id") else []))] or \
          [r["id"] for r in q(c, "SELECT id FROM ai_docs WHERE status='ready'")]
    if not ids:
        raise ApiError("No document has been read yet. Upload one first.")
    hits = _search_pages(c, ids, question, 8)
    st = ai_status(c, u, {})
    if not st["on"] or not st["docs"]:
        return {"offline": True, "hits": hits}
    conf, company, user = _conf(c), _company(), dict(u)

    def work(job):
        ai = AI(conf, company, user["id"], "doc_question")

        def load(c):
            docs = q(c, "SELECT * FROM ai_docs WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)
            pages = q(c, "SELECT doc_id, page, text FROM ai_doc_pages WHERE doc_id IN (%s) ORDER BY doc_id, page" % ",".join("?" * len(ids)), ids)
            return docs, pages
        docs, pages = _in_company(company, load)
        names = {d["id"]: d["title"] for d in docs}
        total = sum(len(p["text"]) for p in pages)
        limit = 280000 if ai.provider == "claude" else 20000
        if total > limit:
            # long: the best matching pages plus their neighbours
            keep = set()
            for h in _in_company(company, lambda c: _search_pages(c, ids, question, 40)):
                for k in (h["page"] - 1, h["page"], h["page"] + 1):
                    keep.add((h["doc_id"], k))
            pages = [p for p in pages if (p["doc_id"], p["page"]) in keep]
            n, cut = 0, []
            for p in pages:
                n += len(p["text"])
                if n > limit:
                    break
                cut.append(p)
            pages = cut
        content = []
        scanned = [d for d in docs if d["scanned"]]
        if scanned and ai.provider == "claude" and len(scanned) == 1 and len(docs) == 1:
            _f, path = _in_company(company, lambda c: _file_path(c, scanned[0]["file_id"]))
            content.append(_pdf_block(path))
        else:
            text, last = [], None
            for p in pages:
                if p["doc_id"] != last:
                    text.append("\n=== Document: %s ===\n" % names.get(p["doc_id"]))
                    last = p["doc_id"]
                text.append("[Page %d]\n%s\n" % (p["page"], p["text"]))
            content.append({"type": "text", "text": "".join(text) or "(no text found)"})
        content.append({"type": "text", "text": "Question: " + question + "\n\nAnswer from the document only. Quote numbers exactly, and give the "
                                                "document, clause and page for each point, e.g. (GCC 14.2, p. 23). If the document does not say, "
                                                "say that clearly. Keep it short."})
        job["step"] = "Reading the document…"
        blocks, _s = ai.message(SYS_DOC, [{"role": "user", "content": content}], max_tokens=2500)
        ai._log(True, question[:120])
        return {"answer": _text_of(blocks), "hits": hits[:5]}
    return _start(u, "doc_question", work)


@api("item.save", "commercial", "edit")
def item_save(c, u, a):
    r = a.get("row") or {}
    data = {k: r.get(k) for k in ("category", "title", "detail", "value", "due_date", "repeat", "clause", "page", "precondition_for", "status") if k in r}
    if data.get("status") and data["status"] not in ("proposed", "approved", "rejected"):
        raise ApiError("Unknown status.")
    if "due_date" in data and data["due_date"] and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(data["due_date"])):
        raise ApiError("Date as YYYY-MM-DD.")
    data["edited_by"], data["edited_at"] = u["id"], now()
    if r.get("id"):
        it = get(c, "ai_items", int(r["id"]), "Item")
        upd(c, "ai_items", it["id"], data)
        rid = it["id"]
    else:
        if not r.get("title"):
            raise ApiError("Title is required.")
        d = get(c, "ai_docs", int(r["doc_id"]), "Document")
        data.update({"doc_id": d["id"], "contract_id": d["contract_id"], "source": "manual", "created": now()})
        data.setdefault("status", "approved")
        rid = ins(c, "ai_items", data)
    audit(c, u, "save", "ai_items", rid, data)
    return q1(c, "SELECT * FROM ai_items WHERE id=?", (rid,))


@api("item.status", "commercial", "edit")
def item_status(c, u, a):
    st = a.get("status")
    if st not in ("proposed", "approved", "rejected"):
        raise ApiError("Unknown status.")
    ids = [int(x) for x in a.get("ids") or []]
    for i in ids:
        upd(c, "ai_items", i, {"status": st, "edited_by": u["id"], "edited_at": now()})
    audit(c, u, st, "ai_items", None, {"ids": ids})
    return len(ids)


KIND_OF = {"security": "other", "notice": "notice", "report": "report", "dates": "milestone", "money": "payment", "testing": "other",
           "precondition": "other", "penalty": "other", "technical": "other", "terms": "other", "other": "other"}


@api("item.to_schedule", "commercial", "edit")
def item_to_schedule(c, u, a):
    """Approved items with a date (or a repeat) go into the contract's letters / reports / deliveries schedule."""
    ids = [int(x) for x in a.get("ids") or []]
    made, skipped = 0, []
    for i in ids:
        it = get(c, "ai_items", i, "Item")
        cid = it["contract_id"] or (int(a["contract_id"]) if a.get("contract_id") else None) or \
            (val(c, "SELECT contract_id FROM ai_docs WHERE id=?", (it["doc_id"],), None) if it["doc_id"] else None)
        if not cid:
            skipped.append("%s: link the document to a contract first" % it["title"])
            continue
        if it["status"] != "approved":
            skipped.append("%s: approve it first" % it["title"])
            continue
        if it["citem_id"]:
            skipped.append("%s: already in the schedule" % it["title"])
            continue
        if not it["due_date"]:
            skipped.append("%s: has no date" % it["title"])
            continue
        remark = "%s%s%s" % (it["detail"] or "", (" — " + it["clause"]) if it["clause"] else "", (" p." + str(it["page"])) if it["page"] else "")
        ci = ins(c, "contract_items", {"contract_id": cid, "kind": KIND_OF.get(it["category"], "other"), "title": it["title"][:200],
                                       "due_date": it["due_date"], "repeat": it["repeat"] or "none", "direction": "we_send", "status": "pending",
                                       "remarks": remark[:1000]})
        upd(c, "ai_items", i, {"citem_id": ci, "contract_id": cid})
        made += 1
    # bonds and insurance dates also go onto the contract card when it has none
    audit(c, u, "to_schedule", "ai_items", None, {"ids": ids, "made": made})
    return {"made": made, "skipped": skipped}


@api("item.delete", "commercial", "edit")
def item_delete(c, u, a):
    c.execute("DELETE FROM ai_items WHERE id=?", (int(a["id"]),))
    return True


@api("item.all", "commercial", "view")
def item_all(c, u, a):
    """Approved items of every document (or of one contract): the company's register of contract conditions."""
    cond, p = "i.status='approved'", []
    if a.get("contract_id"):
        cond += " AND i.contract_id=?"
        p.append(int(a["contract_id"]))
    if a.get("category"):
        cond += " AND i.category=?"
        p.append(a["category"])
    return q(c, "SELECT i.*, d.title document, k.title contract FROM ai_items i LEFT JOIN ai_docs d ON d.id=i.doc_id "
                "LEFT JOIN contracts k ON k.id=i.contract_id WHERE " + cond + " ORDER BY i.category, k.title, i.page", p)


@api("ai.test", "admin", "edit")
def ai_test(c, u, a):
    conf, company, user = _conf(c), _company(), dict(u)

    def work(job):
        ai = AI(conf, company, user["id"], "test")
        blocks, _s = ai.message("Reply with exactly: BuildCore AI is working.", [{"role": "user", "content": "Test"}], max_tokens=50)
        ai._log(True, "test")
        return {"answer": _text_of(blocks)}
    return _start(u, "test", work)


# ───────────────────────── shortcut keys of each user ─────────────────────────
SC_KINDS = ("screen", "new", "command", "text")


@api("sc.list")
def sc_list(c, u, a):
    _ensure(c)
    return q(c, "SELECT s.*, (SELECT name FROM users WHERE id=s.user_id) owner FROM user_shortcuts s "
                "WHERE s.user_id=? OR s.everyone=1 ORDER BY s.everyone, s.combo", (u["id"],))


@api("sc.save")
def sc_save(c, u, a):
    r = a.get("row") or {}
    combo = (r.get("combo") or "").strip()
    if not combo:
        raise ApiError("Press the key you want.")
    if r.get("kind") not in SC_KINDS:
        raise ApiError("Choose what the key does.")
    if not (r.get("target") or "").strip():
        raise ApiError("Choose the screen, entry, command or text.")
    if combo in ("Escape", "Enter", "Tab", "Space", "Backspace", "Delete") or re.match(r"^(Shift\+)?[A-Z0-9]$", combo):
        raise ApiError("Use a key with Ctrl or Alt (e.g. Ctrl+Alt+G, Alt+1) or a function key (F1-F12); single letters are for typing.")
    everyone = 1 if r.get("everyone") else 0
    if everyone and u["role"] != "admin":
        raise ApiError("Only an administrator can share a shortcut with everyone.")
    data = {"combo": combo, "kind": r["kind"], "target": r["target"].strip()[:2000], "label": (r.get("label") or "")[:120], "everyone": everyone}
    if r.get("id"):
        s = get(c, "user_shortcuts", int(r["id"]), "Shortcut")
        if s["user_id"] != u["id"] and u["role"] != "admin":
            raise ApiError("This is someone else's shortcut.")
        upd(c, "user_shortcuts", s["id"], data)
        rid = s["id"]
    else:
        old = q1(c, "SELECT id FROM user_shortcuts WHERE user_id=? AND combo=? AND everyone=?", (u["id"], combo, everyone))
        if old:
            upd(c, "user_shortcuts", old["id"], data)
            rid = old["id"]
        else:
            data.update(user_id=u["id"], created=now())
            rid = ins(c, "user_shortcuts", data)
    return q1(c, "SELECT * FROM user_shortcuts WHERE id=?", (rid,))


@api("sc.delete")
def sc_delete(c, u, a):
    s = get(c, "user_shortcuts", int(a["id"]), "Shortcut")
    if s["user_id"] != u["id"] and u["role"] != "admin":
        raise ApiError("This is someone else's shortcut.")
    c.execute("DELETE FROM user_shortcuts WHERE id=?", (s["id"],))
    return True
