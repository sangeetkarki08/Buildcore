"""
BuildCore 2.10 - Copilot.

  Ask for a report   type what you want to see ("cement issued per site last month"); the AI writes a read-only
                     query, BuildCore runs it on this computer within the user's role, and shows the table / chart.
                     Save it as your own report (runs again without the AI), export to Excel, print.
  Write              letters, notices, progress report text, minutes, summaries from BuildCore's data; edit, save
                     as a draft, download as Word, print.
  Extra fields       your own fields on materials, machines, parties, projects, contracts, staff and BOQ items
                     (like Tally's user-defined fields); usable in reports.

Queries run on a separate read-only connection with an authorizer: only SELECT, only the tables of modules the user
may view, password columns hidden, a time limit and a row limit. Nothing the AI writes can change data.
"""
import base64
import io
import json
import os
import pathlib
import re
import sqlite3
import time
import zipfile
from datetime import date
from xml.sax.saxutils import escape as xesc

import core
from core import ApiError, audit, get, ins, now, q, q1, today, upd, val
import api_ai
from api_ai import AI, _conf, _company, _in_company, _start, _text_of, ai_status, _lookup_tool, _run_lookup

SCHEMA = """
CREATE TABLE IF NOT EXISTS cop_reports(id INTEGER PRIMARY KEY, user_id INTEGER, title TEXT, question TEXT, sql TEXT, description TEXT,
  chart TEXT, shared INTEGER DEFAULT 0, created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS cop_drafts(id INTEGER PRIMARY KEY, user_id INTEGER, title TEXT, kind TEXT, body TEXT, contract_id INTEGER,
  project_id INTEGER, created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS custom_fields(id INTEGER PRIMARY KEY, entity TEXT, label TEXT, kind TEXT DEFAULT 'text', options TEXT,
  sort INTEGER DEFAULT 0, active INTEGER DEFAULT 1, created_by INTEGER, created TEXT);
CREATE TABLE IF NOT EXISTS custom_values(entity TEXT, entity_id INTEGER, field_id INTEGER, value TEXT, updated_by INTEGER, updated_at TEXT,
  PRIMARY KEY(entity, entity_id, field_id));
"""

_READY = set()


def _ensure(c):
    k = os.path.normcase(core.DB_PATH)
    if k not in _READY:
        c.executescript(SCHEMA)
        _READY.add(k)


def init_copilot(c):
    c.executescript(SCHEMA)
    _READY.add(os.path.normcase(core.DB_PATH))


def api(name, module=None, action=None):
    def wrap(f):
        def run(c, u, a):
            api_ai._ensure(c)
            _ensure(c)
            return f(c, u, a)
        run.__name__, run.__doc__ = f.__name__, f.__doc__
        api_ai._register(name, module, action)(run)
        return f
    return wrap


# ───────────────────────── which tables each module may read ─────────────────────────
_T = {
    None: "projects parties stores materials staff trades users custom_fields custom_values wbs",
    "inventory": "stock_balances stock_ledger grn grn_lines issues issue_lines returns return_lines transfers transfer_lines mrq mrq_lines "
                 "stock_counts count_lines inv_policy mat_causes material_coefficients",
    "procurement": "pr pr_lines cs cs_quotes po po_lines po_revisions vendor_ratings invoices invoice_lines",
    "accounts": "accounts account_groups vouchers voucher_lines payments budgets fiscal_periods fy_balances fy_close fy_stock tds_rates "
                "tds_rates_fy loans provisions prov_moves oh_budget internal_bills",
    "equipment": "equipment equipment_rates equipment_spares equipment_status_log deployments work_orders maint_plans logbooks logsheets "
                 "log_checks log_fluids log_meters log_service log_tools hire_agreements hire_bills eq_tools operator_violations",
    "project": "activities act_links act_resources dpr dpr_work dpr_labour dpr_equipment dpr_delays dpr_survey tasks events lookahead "
               "sched_calendars sched_holidays sched_baselines sched_baseline_acts check_lists",
    "commercial": "boq_items boq_components measurements measurement_lines ipc ipc_lines variations contracts contract_items "
                  "contract_milestones bids bid_prices ai_docs ai_items",
    "quality": "ncrs qa_tests submittals safety_checks maturity_checks",
    "plant": "plants plant_runs plant_run_lines plant_tests mix_designs mix_lines",
    "assets": "assets asset_acq asset_moves asset_disposals asset_cases fa_register fa_dep fa_components fa_costs fa_leases fa_lease_rows "
              "fa_maint fa_impair fa_tax fa_rates fa_alloc fa_deferred dep_runs",
    "masters": "res_pool res_rates rate_books ra_analyses ra_norms ra_norm_lines rate_analysis",
}
TABLE_MODULE = {t: m for m, ts in _T.items() for t in ts.split()}
HIDDEN_COLS = {"users": {"pw_hash", "salt", "project_ids", "phone", "email"}}

HINTS = """Notes on the data (SQLite):
- Dates are text 'YYYY-MM-DD' (AD). Use date('now') for today; strftime('%Y-%m', date) for months. Money is NPR.
- The Nepali fiscal year runs from mid-July (Shrawan 1) to mid-July; fiscal_periods(fy, start_date, end_date) has the exact dates.
- Most tables have project_id -> projects(id, code, name). x_id columns point to table x (vendor_id/party_id -> parties, material_id -> materials,
  store_id -> stores, equipment_id -> equipment, account_id -> accounts, boq_item_id -> boq_items, voucher_id -> vouchers).
- Accounts: vouchers(type: journal/purchase/receipt/payment/sales/contra, status) + voucher_lines(debit, credit). Count only vouchers.status='posted'.
  accounts.type is asset/liability/equity/income/expense; accounts.role names special accounts (cash, bank, vat_input, vat_output, tds_payable,
  ap_control, ar_control, material_cost, labour_cost, fuel_cost, repair_cost, contract_revenue …).
- Store: stock_ledger has every movement (qty_in, qty_out, value_in, value_out, doc_type: GRN receipt, MIN issue, MRT return, MTN-IN/MTN-OUT
  transfer, OPENING, PRD production, PSV physical stock adjustment). stock_balances(project_id, store_id, material_id, qty, value) is stock now.
  materials.kind is consumable/tool/spare/other (NULL = consumable). Issues: issues + issue_lines (status 'posted' counts).
- Procurement: po(status: pending_approval/approved/partially_received/received/cancelled, delivery_date) + po_lines(qty, received_qty);
  grn + grn_lines(received_qty, accepted_qty, rejected_qty); invoices(kind purchase/sales, subtotal, vat, tds, total).
- Equipment: equipment(status working/breakdown/under_maintenance/idle, meter); work_orders(downtime_hours, parts_cost, labour_cost, external_cost);
  logbooks = monthly logsheets; dpr_equipment = machine hours per day.
- Site: dpr(date, status draft/submitted/checked/approved) + dpr_work(boq_item_id, location, actual_qty) + dpr_labour + dpr_delays.
- Commercial: boq_items(code, description, unit, qty, rate, executed_qty, location), ipc (client bills), contracts + contract_items (due letters).
- Extra fields: custom_fields(id, entity, label) + custom_values(entity, entity_id, field_id, value), entity is the table name (materials, equipment …).
- users: id, username, name, role only."""


def allowed_tables(user):
    return {t for t, m in TABLE_MODULE.items() if m is None or core.can(user, m, "view")}


_SCHEMA_CACHE = {}


def schema_text(c, user):
    tabs = sorted(allowed_tables(user))
    key = (os.path.normcase(core.DB_PATH), tuple(tabs))
    if key in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[key]
    lines = []
    for t in tabs:
        cols = [r[1] for r in c.execute("PRAGMA table_info(%s)" % t).fetchall()]
        if not cols:
            continue
        cols = [x for x in cols if x not in HIDDEN_COLS.get(t, ())]
        lines.append("%s(%s)" % (t, ", ".join(cols)))
    s = "\n".join(lines)
    _SCHEMA_CACHE[key] = s
    return s


class QueryError(Exception):
    pass


def run_select(db_path, user, sql, limit=2000, seconds=10):
    """Run one SELECT on a read-only connection, only on tables the user's role may read."""
    s = (sql or "").strip().rstrip(";").strip()
    if not s:
        raise QueryError("Empty query.")
    if not re.match(r"(?is)^\s*(select|with)\b", s):
        raise QueryError("Only SELECT queries are allowed.")
    if ";" in s:
        raise QueryError("One query only.")
    allowed = allowed_tables(user)
    uri = pathlib.Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    denied = []
    real = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')").fetchall()}

    def auth(action, a1, a2, dbname, src):
        if action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            if a1 in allowed:
                return sqlite3.SQLITE_IGNORE if a2 in HIDDEN_COLS.get(a1, ()) else sqlite3.SQLITE_OK
            if a1 and a1 not in real and not a1.startswith("sqlite_"):
                return sqlite3.SQLITE_OK        # a WITH name or sub-query, made of allowed tables
            if a1 and a1.startswith("sqlite_"):
                denied.append(a1)
                return sqlite3.SQLITE_DENY
            denied.append(a1)
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION:
            return sqlite3.SQLITE_DENY if (a2 or "").lower() in ("load_extension", "readfile", "writefile", "edit") else sqlite3.SQLITE_OK
        if action == getattr(sqlite3, "SQLITE_RECURSIVE", 33):
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    start = time.time()
    conn.set_authorizer(auth)
    conn.set_progress_handler(lambda: 1 if time.time() - start > seconds else 0, 20000)
    try:
        cur = conn.execute(s)
        cols = [d[0] for d in cur.description or []]
        rows = cur.fetchmany(limit + 1)
    except sqlite3.DatabaseError as e:
        msg = str(e)
        if "interrupted" in msg:
            raise QueryError("The query took longer than %d seconds. Ask for less (a shorter period, one project)." % seconds)
        if denied or "not authorized" in msg:
            names = sorted(set(x for x in denied if x))
            raise QueryError("Not allowed to read %s for this user's role." % (", ".join(names) or "that"))
        raise QueryError(msg)
    finally:
        conn.close()
    trunc = len(rows) > limit
    rows = [list(r) for r in rows[:limit]]
    return {"columns": cols, "rows": rows, "truncated": trunc, "ms": int((time.time() - start) * 1000)}


def _short(res, n=25):
    return json.dumps({"columns": res["columns"], "rows": res["rows"][:n], "row_count": len(res["rows"]),
                       "truncated": res["truncated"]}, default=str, ensure_ascii=False)[:9000]


QUERY_TOOL = {"name": "run_query", "description": "Run one read-only SQLite SELECT on this company's BuildCore data and see the first rows. "
                                                 "Use it to check the query works and the numbers make sense.",
              "input_schema": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]}}
REPORT_TOOL = {"name": "show_report", "description": "Show the final report to the user.",
               "input_schema": {"type": "object", "properties": {
                   "title": {"type": "string", "description": "Short title, e.g. 'Cement issued per site, September 2026'."},
                   "sql": {"type": "string", "description": "The final SELECT. Readable column names (AS \"Site\", AS \"Qty\"); order the rows sensibly; round money to 2 decimals."},
                   "description": {"type": "string", "description": "One or two sentences: what the report shows, the period, and any assumption made."},
                   "chart": {"type": "string", "enum": ["none", "bar", "line"], "description": "A chart only when it helps (a few categories or a time series)."},
                   "chart_x": {"type": "string", "description": "Column for the chart's labels."},
                   "chart_y": {"type": "string", "description": "Numeric column to chart."}},
                   "required": ["title", "sql", "description"]}}

SYS_REPORT = """You are BuildCore Copilot. You turn a user's request into one read-only SQLite query on BuildCore's data and show it as a report.
Rules:
- Use only the tables and columns listed. Check your query with run_query before showing it; fix errors yourself.
- Join names instead of showing ids (project code/name, material name and unit, party name, machine code).
- If the request is unclear, make a sensible assumption (e.g. current month, all projects) and say it in the description.
- If a table is not available to this user's role, say so in the description instead of guessing.
- Finish by calling show_report exactly once.
"""


@api("cop.report")
def cop_report(c, u, a):
    """Ask for a report in plain words; the AI writes the query, BuildCore runs it read-only."""
    question = (a.get("question") or "").strip()
    if not question:
        raise ApiError("Type what you want to see.")
    st = ai_status(c, u, {})
    if not st["on"]:
        raise ApiError("Copilot needs the AI. An administrator switches it on in Administration › AI assistant settings. Saved reports still run.")
    conf, company, user, db = _conf(c), _company(), dict(u), core.DB_PATH
    schema = schema_text(c, u)
    projects = q(c, "SELECT id, code, name FROM projects ORDER BY code LIMIT 60")
    prev = a.get("previous") or {}

    def work(job):
        ai = AI(conf, company, user["id"], "report")
        system = [{"type": "text", "text": SYS_REPORT + "\n" + HINTS + "\n\nTables you may read:\n" + schema, "cache_control": {"type": "ephemeral"}},
                  {"type": "text", "text": "Today is %s. Projects: %s. The user (%s) is working on project id %s." % (
                      today(), "; ".join("%s=%s %s" % (p["id"], p["code"], p["name"]) for p in projects), user.get("role"), a.get("project_id") or "all")}]
        ask = question
        if prev.get("sql"):
            ask = "Earlier report: %s\nIts query:\n%s\n\nChange it: %s" % (prev.get("title") or "", prev["sql"], question)
        msgs = [{"role": "user", "content": ask}]
        final = None
        for rnd in range(8):
            job["step"] = "Writing the query…" if rnd == 0 else "Checking the figures…"
            blocks, stop = ai.message(system, msgs, tools=[QUERY_TOOL, REPORT_TOOL], max_tokens=3000)
            uses = [b for b in blocks if b.get("type") == "tool_use"]
            if not uses:
                break
            msgs.append({"role": "assistant", "content": blocks})
            results = []
            for b in uses:
                inp = b.get("input") or {}
                if b["name"] == "show_report":
                    try:
                        res = run_select(db, user, inp.get("sql"))
                        final = dict(inp, result=res)
                        results.append({"type": "tool_result", "tool_use_id": b["id"], "content": "Shown to the user."})
                    except QueryError as e:
                        results.append({"type": "tool_result", "tool_use_id": b["id"], "content": "Error: %s. Fix the query and call show_report again." % e, "is_error": True})
                else:
                    try:
                        results.append({"type": "tool_result", "tool_use_id": b["id"], "content": _short(run_select(db, user, inp.get("sql"), limit=200))})
                    except QueryError as e:
                        results.append({"type": "tool_result", "tool_use_id": b["id"], "content": "Error: %s" % e, "is_error": True})
            if final:
                break
            msgs.append({"role": "user", "content": results})
        if not final:
            txt = _text_of(blocks) if blocks else ""
            ai._log(False, "no report: " + question[:100])
            raise ApiError(txt or "Copilot could not make this report. Try saying it differently, e.g. which project, which period, which figures.")
        ai._log(True, question[:120])
        return {"title": final.get("title"), "sql": final.get("sql"), "description": final.get("description"),
                "chart": {"type": final.get("chart") or "none", "x": final.get("chart_x"), "y": final.get("chart_y")},
                "columns": final["result"]["columns"], "rows": final["result"]["rows"], "truncated": final["result"]["truncated"]}
    return _start(u, "report", work)


@api("cop.run")
def cop_run(c, u, a):
    """Run a saved (or edited) report query read-only, without the AI."""
    sql = a.get("sql")
    if a.get("id"):
        r = get(c, "cop_reports", int(a["id"]), "Report")
        if r["user_id"] != u["id"] and not r["shared"]:
            raise ApiError("This report belongs to someone else.")
        sql = r["sql"]
    try:
        return run_select(core.DB_PATH, u, sql)
    except QueryError as e:
        raise ApiError(str(e))


@api("cop.reports")
def cop_reports(c, u, a):
    return q(c, "SELECT r.*, (SELECT name FROM users WHERE id=r.user_id) owner FROM cop_reports r WHERE r.user_id=? OR r.shared=1 "
                "ORDER BY r.shared, r.title", (u["id"],))


@api("cop.save_report")
def cop_save_report(c, u, a):
    r = a.get("row") or {}
    if not (r.get("title") or "").strip() or not (r.get("sql") or "").strip():
        raise ApiError("A report needs a title and its query.")
    try:
        run_select(core.DB_PATH, u, r["sql"], limit=1)
    except QueryError as e:
        raise ApiError("The query does not run: %s" % e)
    shared = 1 if r.get("shared") else 0
    if shared and u["role"] != "admin":
        raise ApiError("Only an administrator can share a report with everyone.")
    data = {"title": r["title"][:200], "question": (r.get("question") or "")[:2000], "sql": r["sql"], "description": (r.get("description") or "")[:2000],
            "chart": json.dumps(r.get("chart") or {}), "shared": shared, "updated": now()}
    if r.get("id"):
        old = get(c, "cop_reports", int(r["id"]), "Report")
        if old["user_id"] != u["id"] and u["role"] != "admin":
            raise ApiError("This report belongs to someone else.")
        upd(c, "cop_reports", old["id"], data)
        rid = old["id"]
    else:
        data.update(user_id=u["id"], created=now())
        rid = ins(c, "cop_reports", data)
    audit(c, u, "save", "cop_reports", rid, {"title": data["title"]})
    return q1(c, "SELECT * FROM cop_reports WHERE id=?", (rid,))


@api("cop.delete_report")
def cop_delete_report(c, u, a):
    r = get(c, "cop_reports", int(a["id"]), "Report")
    if r["user_id"] != u["id"] and u["role"] != "admin":
        raise ApiError("This report belongs to someone else.")
    c.execute("DELETE FROM cop_reports WHERE id=?", (r["id"],))
    return True


# ───────────────────────── writing ─────────────────────────
KINDS = {"letter_client": "Letter to the client / employer / engineer", "letter_vendor": "Letter to a supplier or subcontractor",
         "notice": "Notice (delay, claim, variation, extension of time)", "progress": "Monthly progress report text",
         "minutes": "Minutes of a meeting", "summary": "Summary / explanation for management", "other": "Other text"}

SYS_WRITE = """You are BuildCore Copilot writing for a construction company in Nepal. Write clear, correct, professional text the user can send
after checking it. Use facts from BuildCore (look them up with the tools) and from the user's instructions; never invent figures, dates,
names or clause numbers - where something is missing write a placeholder in square brackets like [date] or [reference no.].
Letters: company letter style with Ref. No., Date, addressee, Subject, body, closing - no letterhead (BuildCore adds it).
Contract letters and notices: cite the contract clause only if the user or the data gives it. Keep it as short as the purpose allows.
Write in the language asked (English or Nepali). Output only the text itself in simple Markdown (## headings, - lists, **bold**)."""


@api("cop.write")
def cop_write(c, u, a):
    kind = a.get("kind") if a.get("kind") in KINDS else "other"
    instr = (a.get("instructions") or "").strip()
    if not instr:
        raise ApiError("Say what the text should say.")
    st = ai_status(c, u, {})
    if not st["on"]:
        raise ApiError("Writing needs the AI. An administrator switches it on in Administration › AI assistant settings.")
    conf, company, user, db, token = _conf(c), _company(), dict(u), core.DB_PATH, a.get("_token")
    facts = []
    if a.get("contract_id"):
        k = q1(c, "SELECT k.*, p.name party FROM contracts k LEFT JOIN parties p ON p.id=k.party_id WHERE k.id=?", (int(a["contract_id"]),))
        if k:
            facts.append("Contract: " + json.dumps({x: k[x] for x in k if k[x] not in (None, "")}, default=str, ensure_ascii=False))
            its = q(c, "SELECT category, title, value, detail, clause, page FROM ai_items WHERE contract_id=? AND status='approved' LIMIT 80", (k["id"],))
            if its:
                facts.append("Approved contract conditions: " + json.dumps(its, ensure_ascii=False)[:12000])
    if a.get("project_id"):
        p = q1(c, "SELECT code, name, client, location, contract_value, start_date, end_date, completion_date FROM projects WHERE id=?", (int(a["project_id"]),))
        if p:
            facts.append("Project: " + json.dumps(p, default=str, ensure_ascii=False))
    company_name = val(c, "SELECT value FROM settings WHERE key='company_name'", (), "") or ""
    schema = schema_text(c, u)
    screen = (a.get("screen_text") or "")[:15000]

    def work(job):
        ai = AI(conf, company, user["id"], "write")
        system = [{"type": "text", "text": SYS_WRITE + "\n\nYou can query BuildCore read-only with run_query.\n" + HINTS + "\n\nTables:\n" + schema,
                   "cache_control": {"type": "ephemeral"}},
                  {"type": "text", "text": "Our company: %s. Written by: %s (%s). Today: %s." % (company_name, user.get("name"), user.get("role"), today())}]
        content = "Write: %s.\nLanguage: %s.\nInstructions: %s" % (KINDS[kind], a.get("language") or "English", instr)
        if facts:
            content += "\n\nFacts from BuildCore:\n" + "\n".join(facts)
        if screen:
            content += "\n\nWhat the user has on screen:\n" + screen
        if a.get("previous"):
            content += "\n\nThe current draft to change:\n" + str(a["previous"])[:20000]
        msgs = [{"role": "user", "content": content}]
        tools = [QUERY_TOOL] + ([_lookup_tool()] if st["data"] else [])
        for rnd in range(8):
            job["step"] = "Writing…" if rnd == 0 else "Looking up figures…"
            blocks, stop = ai.message(system, msgs, tools=tools if ai.provider == "claude" else None, max_tokens=4000)
            uses = [b for b in blocks if b.get("type") == "tool_use"]
            if not uses:
                break
            msgs.append({"role": "assistant", "content": blocks})
            res = []
            for b in uses:
                inp = b.get("input") or {}
                if b["name"] == "run_query":
                    try:
                        out = _short(run_select(db, user, inp.get("sql"), limit=200))
                    except QueryError as e:
                        out = "Error: %s" % e
                else:
                    out = _run_lookup(company, token, user, inp)
                res.append({"type": "tool_result", "tool_use_id": b["id"], "content": out})
            msgs.append({"role": "user", "content": res})
        text = _text_of(blocks)
        if not text:
            raise ApiError("Copilot did not write anything. Try again with more detail.")
        ai._log(True, KINDS[kind])
        return {"text": text}
    return _start(u, "write", work)


@api("cop.drafts")
def cop_drafts(c, u, a):
    return q(c, "SELECT id, title, kind, contract_id, project_id, created, updated, length(body) size FROM cop_drafts WHERE user_id=? ORDER BY updated DESC", (u["id"],))


@api("cop.draft")
def cop_draft(c, u, a):
    d = get(c, "cop_drafts", int(a["id"]), "Draft")
    if d["user_id"] != u["id"]:
        raise ApiError("This draft belongs to someone else.")
    return d


@api("cop.draft_save")
def cop_draft_save(c, u, a):
    r = a.get("row") or {}
    data = {"title": (r.get("title") or "Untitled")[:200], "kind": r.get("kind") or "other", "body": r.get("body") or "",
            "contract_id": int(r["contract_id"]) if r.get("contract_id") else None, "project_id": int(r["project_id"]) if r.get("project_id") else None,
            "updated": now()}
    if r.get("id"):
        d = get(c, "cop_drafts", int(r["id"]), "Draft")
        if d["user_id"] != u["id"]:
            raise ApiError("This draft belongs to someone else.")
        upd(c, "cop_drafts", d["id"], data)
        rid = d["id"]
    else:
        data.update(user_id=u["id"], created=now())
        rid = ins(c, "cop_drafts", data)
    return {"id": rid}


@api("cop.draft_delete")
def cop_draft_delete(c, u, a):
    d = get(c, "cop_drafts", int(a["id"]), "Draft")
    if d["user_id"] != u["id"]:
        raise ApiError("This draft belongs to someone else.")
    c.execute("DELETE FROM cop_drafts WHERE id=?", (d["id"],))
    return True


# ───────────────────────── Word and Excel files ─────────────────────────
def _runs(text):
    """Word runs for **bold** inside a line."""
    out = []
    for i, part in enumerate(re.split(r"\*\*", text)):
        if not part:
            continue
        rpr = "<w:rPr><w:b/></w:rPr>" if i % 2 else ""
        out.append('<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (rpr, xesc(part)))
    return "".join(out)


def make_docx(title, body, company="", heading=True):
    paras = []
    if company:
        paras.append('<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:b/><w:sz w:val="32"/></w:rPr><w:t>%s</w:t></w:r></w:p>' % xesc(company))
    if heading and title:
        paras.append('<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>%s</w:p>' % _runs(title))
    for ln in (body or "").replace("\r\n", "\n").split("\n"):
        t = ln.rstrip()
        m = re.match(r"^(#{1,4})\s+(.*)$", t)
        if m:
            paras.append('<w:p><w:pPr><w:pStyle w:val="Heading%d"/></w:pPr>%s</w:p>' % (min(len(m.group(1)) + 1, 4), _runs(m.group(2))))
        elif re.match(r"^\s*[-*•]\s+", t):
            paras.append('<w:p><w:pPr><w:pStyle w:val="ListBullet"/></w:pPr>%s</w:p>' % _runs(re.sub(r"^\s*[-*•]\s+", "", t)))
        else:
            paras.append("<w:p>%s</w:p>" % _runs(t))
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>%s'
           '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1418" w:header="709" w:footer="709" w:gutter="0"/></w:sectPr>'
           '</w:body></w:document>') % "".join(paras)
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
              '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Mangal" w:eastAsia="Calibri"/><w:sz w:val="22"/></w:rPr></w:rPrDefault>'
              '<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
              '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
              '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="240"/></w:pPr><w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>'
              '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="200"/></w:pPr><w:rPr><w:b/><w:sz w:val="25"/></w:rPr></w:style>'
              '<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="23"/></w:rPr></w:style>'
              '<w:style w:type="paragraph" w:styleId="Heading4"><w:name w:val="heading 4"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:i/></w:rPr></w:style>'
              '<w:style w:type="paragraph" w:styleId="ListBullet"><w:name w:val="List Bullet"/><w:basedOn w:val="Normal"/><w:pPr><w:ind w:left="567" w:hanging="283"/></w:pPr></w:style>'
              '</w:styles>')
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
          '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
    drels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
             '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", styles)
        z.writestr("word/_rels/document.xml.rels", drels)
    return buf.getvalue()


def _col(n):
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def make_xlsx(title, columns, rows):
    def cell(ref, v, style=0):
        if v is None or v == "":
            return ""
        if isinstance(v, bool):
            v = int(v)
        if isinstance(v, (int, float)):
            return '<c r="%s"%s><v>%s</v></c>' % (ref, ' s="%d"' % style if style else "", repr(v) if isinstance(v, float) else v)
        return '<c r="%s" t="inlineStr"%s><is><t xml:space="preserve">%s</t></is></c>' % (ref, ' s="%d"' % style if style else "", xesc(str(v)))
    out = ['<row r="1">%s</row>' % cell("A1", title, 1)]
    out.append('<row r="3">%s</row>' % "".join(cell("%s3" % _col(i), c, 1) for i, c in enumerate(columns)))
    for ri, r in enumerate(rows):
        n = ri + 4
        out.append('<row r="%d">%s</row>' % (n, "".join(cell("%s%d" % (_col(i), n), v) for i, v in enumerate(r))))
    def wid(i, c):
        m = max([len(str(c))] + [len(("%.2f" % r[i]) if isinstance(r[i], float) else str(r[i])) for r in rows[:300] if i < len(r) and r[i] is not None])
        return min(max(m + 3, 10), 60)
    widths = "".join('<col min="%d" max="%d" width="%d" customWidth="1"/>' % (i + 1, i + 1, wid(i, c)) for i, c in enumerate(columns))
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<cols>%s</cols><sheetData>%s</sheetData></worksheet>') % (widths or '<col min="1" max="1" width="14" customWidth="1"/>', "".join(out))
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
              '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
              '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
              '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
              '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
              '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
    wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Report" sheetId="1" r:id="rId1"/></sheets></workbook>')
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
          '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    wrels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
             '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
             '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", wrels)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        z.writestr("xl/styles.xml", styles)
    return buf.getvalue()


def _fname(title, ext):
    base = re.sub(r"[^A-Za-z0-9 _.-]+", "", title or "BuildCore").strip()[:60] or "BuildCore"
    return base + ext


@api("cop.docx")
def cop_docx(c, u, a):
    company = val(c, "SELECT value FROM settings WHERE key='company_name'", (), "") or ""
    data = make_docx(a.get("title") or "", a.get("body") or "", company if a.get("letterhead", True) else "", heading=bool(a.get("heading")))
    return {"filename": _fname(a.get("title"), ".docx"), "b64": base64.b64encode(data).decode("ascii")}


@api("cop.xlsx")
def cop_xlsx(c, u, a):
    cols = a.get("columns") or []
    rows = a.get("rows") or []
    if len(rows) > 50000:
        raise ApiError("Too many rows for one file.")
    data = make_xlsx(a.get("title") or "Report", cols, rows)
    return {"filename": _fname(a.get("title"), ".xlsx"), "b64": base64.b64encode(data).decode("ascii")}


# ───────────────────────── extra fields (user-defined) ─────────────────────────
CF_ENTITIES = {
    "materials": ("Materials", "masters", "code", "name", "SELECT id, code, name || COALESCE(' (' || unit || ')', '') name FROM materials WHERE COALESCE(active,1)=1"),
    "equipment": ("Machines", "equipment", "code", "name", "SELECT id, code, name FROM equipment WHERE COALESCE(active,1)=1"),
    "parties": ("Vendors, clients and subcontractors", "masters", "code", "name", "SELECT id, code, name FROM parties WHERE COALESCE(active,1)=1"),
    "projects": ("Projects", "masters", "code", "name", "SELECT id, code, name FROM projects"),
    "contracts": ("Contracts", "commercial", "ref_no", "title", "SELECT id, ref_no code, title name FROM contracts"),
    "staff": ("Staff", "masters", "code", "name", "SELECT id, NULL code, name FROM staff"),
    "boq_items": ("BOQ items", "commercial", "code", "description", "SELECT id, code, description name FROM boq_items"),
}
CF_KINDS = ("text", "number", "date", "choice", "yesno")


@api("cf.entities")
def cf_entities(c, u, a):
    return [{"entity": k, "label": v[0], "can_edit": core.can(u, v[1], "edit"), "can_view": core.can(u, v[1], "view")}
            for k, v in CF_ENTITIES.items()]


@api("cf.defs")
def cf_defs(c, u, a):
    cond, p = "1=1", []
    if a.get("entity"):
        cond += " AND entity=?"
        p.append(a["entity"])
    if not a.get("all"):
        cond += " AND active=1"
    return q(c, "SELECT * FROM custom_fields WHERE " + cond + " ORDER BY entity, sort, id", p)


@api("cf.def_save", "admin", "edit")
def cf_def_save(c, u, a):
    r = a.get("row") or {}
    if r.get("entity") not in CF_ENTITIES:
        raise ApiError("Choose what the field belongs to.")
    if not (r.get("label") or "").strip():
        raise ApiError("Give the field a name.")
    if r.get("kind") not in CF_KINDS:
        raise ApiError("Choose the type of field.")
    data = {"entity": r["entity"], "label": r["label"].strip()[:80], "kind": r["kind"], "options": (r.get("options") or "")[:2000],
            "sort": int(r.get("sort") or 0), "active": 0 if str(r.get("active")) == "0" else 1}
    if r.get("id"):
        upd(c, "custom_fields", int(r["id"]), data)
        rid = int(r["id"])
    else:
        data.update(created_by=u["id"], created=now())
        rid = ins(c, "custom_fields", data)
    audit(c, u, "save", "custom_fields", rid, data)
    return q1(c, "SELECT * FROM custom_fields WHERE id=?", (rid,))


@api("cf.grid")
def cf_grid(c, u, a):
    ent = a.get("entity")
    if ent not in CF_ENTITIES:
        raise ApiError("Unknown list.")
    label, module, _c, _n, sql = CF_ENTITIES[ent]
    if not core.can(u, module, "view"):
        raise ApiError("Your role cannot see %s." % label.lower())
    fields = q(c, "SELECT * FROM custom_fields WHERE entity=? AND active=1 ORDER BY sort, id", (ent,))
    rows = q(c, sql + " ORDER BY 2, 3 LIMIT 5000")
    vals = {}
    for v in q(c, "SELECT entity_id, field_id, value FROM custom_values WHERE entity=?", (ent,)):
        vals.setdefault(v["entity_id"], {})[str(v["field_id"])] = v["value"]
    for r in rows:
        r["values"] = vals.get(r["id"], {})
    return {"fields": fields, "rows": rows, "can_edit": core.can(u, module, "edit"), "label": label}


@api("cf.set")
def cf_set(c, u, a):
    ent = a.get("entity")
    if ent not in CF_ENTITIES:
        raise ApiError("Unknown list.")
    module = CF_ENTITIES[ent][1]
    core.require(u, module, "edit")
    f = get(c, "custom_fields", int(a["field_id"]), "Field")
    if f["entity"] != ent:
        raise ApiError("This field belongs to another list.")
    v = a.get("value")
    v = "" if v is None else str(v).strip()
    if v and f["kind"] == "number":
        try:
            float(v.replace(",", ""))
            v = v.replace(",", "")
        except ValueError:
            raise ApiError("%s must be a number." % f["label"])
    if v and f["kind"] == "date" and not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
        raise ApiError("%s: date as YYYY-MM-DD." % f["label"])
    if v and f["kind"] == "choice":
        opts = [x.strip() for x in (f["options"] or "").split(",") if x.strip()]
        if opts and v not in opts:
            raise ApiError("%s must be one of: %s" % (f["label"], ", ".join(opts)))
    eid = int(a["entity_id"])
    if v == "":
        c.execute("DELETE FROM custom_values WHERE entity=? AND entity_id=? AND field_id=?", (ent, eid, f["id"]))
    else:
        c.execute("INSERT INTO custom_values(entity, entity_id, field_id, value, updated_by, updated_at) VALUES(?,?,?,?,?,?) "
                  "ON CONFLICT(entity, entity_id, field_id) DO UPDATE SET value=excluded.value, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
                  (ent, eid, f["id"], v, u["id"], now()))
    return {"value": v}
