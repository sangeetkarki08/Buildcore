"""
Report generator (BuildCore 2.31).

The 2.29 report builder (Command centre > Report builder, engine api_fcc) is extended, not replaced:
  1. More data. Besides the twelve finance and progress sources of 2.29, every module can now be reported on:
     DPR days, labour, machine and delay lines; stock movements, stock on hand, goods received, material issued,
     material requests; purchase orders, purchase bills and client invoices with their lines, payments and receipts,
     vouchers; machine days (logsheets) and the equipment register; BOQ progress, measurements, variations,
     subcontract orders and bills, events and claims; issues, RFIs, inspections, safety incidents, tasks; vendors and
     clients, materials; the audit log for administrators.
  2. Time. The period can be any of the English presets, a Nepali month, the Nepali fiscal year or quarter (this,
     last or a chosen one) or two dates, and applies to the date the user picks (e.g. a bill's due date instead of
     its date). Any date can also be shown or grouped as week, month, year, Nepali date, Nepali month, fiscal year
     and fiscal quarter. Dates can be printed in English, Nepali or both.
  3. Layout. Columns in any order with the user's own headings, calculated columns (a + b, a - b, a x b, a / b,
     a as % of b, days between two dates), more filters (between, starts with, does not contain), three levels of
     grouping, a summary-only report (one line per group), the first N rows after sorting, CSV besides Excel and print.
  4. In a Project Workspace a report covers the open project unless projects are chosen.
Saved reports stay in fcc_reports (the 2.29 table); a 2.29 definition runs exactly as before. Rights are those of
2.29 ('reports' row in Users and roles) plus the view right of the module each source belongs to, and project
assignments are checked by the engine on every run, export and pick-list. Nothing here writes, posts or changes a
balance; the only writes are saved report definitions and the export entry in the audit trail.
"""
import base64
import csv
import io
import json
import re
from datetime import date, timedelta

from core import ApiError, audit, get, ins, now, q, q1, r2, today, upd, val
import api_inventory as inv
from api_inventory import api

VERSION = "2.31.0"
FLAG = "_bco231"
FC = None          # api_fcc, bound at start-up
SC = None          # sched_calc (Nepali calendar)
_ORIG = {}


def init_rgen(c):
    global FC, SC
    import api_fcc
    import sched_calc
    FC, SC = api_fcc, sched_calc
    if not getattr(FC, FLAG, False):
        _ORIG["run_report"] = FC.run_report
        for k, v in AREA_OF.items():
            if k in FC.DATASETS:
                FC.DATASETS[k].setdefault("area", v)
        for k, ds in NEW_DATASETS.items():
            FC.DATASETS[k] = ds
        FC.run_report = run_report
        FC.PERIODS = PERIODS
        FC.OPS = OPS
        setattr(FC, FLAG, True)
    _install()
    _seed_reports(c)


# ───────────────────────────── helpers ─────────────────────────────
def C(k, label, t="text"):
    return {"k": k, "label": label, "type": t}


def _d(s):
    try:
        return date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def _f(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _has(c, t):
    return bool(val(c, "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (t,)))


def _admin(u):
    return bool(u and (u.get("role") == "admin" or u.get("system")))


def R(*mods):
    """May see the source when the role has 'view' on any of these modules."""
    return lambda c, u: _admin(u) or any(FC.right(c, u, m, "view") for m in mods)


def R_dpr(c, u):
    return FC._udpr_right(c, u, "view")


def R_adm(c, u):
    return _admin(u)


def _pfilter(c, u, f, col):
    """Rows of the projects this person chose or may see. Rows with no project (company documents) are included only
    when no project was chosen and the person sees every project."""
    al = FC.allowed_projects(c, u)
    if f.get("project_ids") or al is not None:
        return " AND %s IN (%s)" % (col, FC._in(FC._pids_for(c, u, f)))
    return ""


def S(label, area, right, sql, date_col, cols, pcol, order, post=None, extra=None):
    """A source read with one query. date_col is the SQL expression the period applies to when the user keeps the
    source's own date; pcol limits the projects (None: a company list such as vendors); extra(c, u) adds a condition
    that depends on the person."""
    def rows(c, u, f):
        s, args = sql + " WHERE 1=1", []
        if pcol:
            s += _pfilter(c, u, f, pcol)
        if extra:
            s += extra(c, u)
        if date_col and f.get("from"):
            s += " AND substr(%s,1,10)>=?" % date_col
            args.append(f["from"])
        if date_col and f.get("to"):
            s += " AND substr(%s,1,10)<=?" % date_col
            args.append(f["to"])
        out = [dict(r) for r in q(c, s + " ORDER BY " + order + " LIMIT 200000", tuple(args))]
        if post:
            post(c, out)
        return out
    date_key = next((x["k"] for x in cols if x["type"] == "date"), None)
    return {"label": label, "area": area, "right": right, "rows": rows, "date": date_key if date_col else None,
            "sql_date": bool(date_col), "cols": cols, "company_list": not pcol}


P = "LEFT JOIN projects p ON p.id=%s "
MAT = [C("material_code", "Material code"), C("material", "Material"), C("category", "Category"), C("unit", "Unit")]
MATJ = "LEFT JOIN materials m ON m.id=%s "
MATS = "m.code material_code, m.name material, m.category, m.unit"


def _bill_kinds(c, u):
    """Client invoices are an accounts document; purchase bills belong to procurement as well (as in the menus)."""
    return "" if _admin(u) or FC.right(c, u, "accounts", "view") else " AND i.kind='purchase'"


def _post_stock(c, rows):
    for r in rows:
        r["net_qty"] = r2((r.get("qty_in") or 0) - (r.get("qty_out") or 0))
        r["net_value"] = r2((r.get("value_in") or 0) - (r.get("value_out") or 0))


def _post_onhand(c, rows):
    for r in rows:
        qn, v = r.get("qty") or 0, r.get("value") or 0
        r["avg_rate"] = r2(v / qn) if abs(qn) > 1e-9 else None
        lv = r.get("reorder_level") or r.get("min_level")
        r["below_reorder"] = "yes" if lv and qn < lv else ""


def _post_grn(c, rows):
    for r in rows:
        r["amount"] = r2((r.get("accepted_qty") or 0) * (r.get("rate") or 0))


def _post_issue(c, rows):
    for r in rows:
        r["net_qty"] = r2((r.get("qty") or 0) - (r.get("returned_qty") or 0))


def _post_mrq(c, rows):
    for r in rows:
        ap = r.get("approved_qty") if r.get("approved_qty") is not None else r.get("qty")
        r["pending_qty"] = r2(max(0.0, (ap or 0) - (r.get("issued_qty") or 0)))


def _post_po(c, rows):
    for r in rows:
        r["amount"] = r2((r.get("qty") or 0) * (r.get("rate") or 0))
        r["open_qty"] = r2(max(0.0, (r.get("qty") or 0) - (r.get("received_qty") or 0)))
        r["open_value"] = r2(r["open_qty"] * (r.get("rate") or 0))


def _post_lab(c, rows):
    for r in rows:
        r["man_hours"] = r2((r.get("workers") or 0) * (r.get("hours") or 0) + (r.get("workers") or 0) * (r.get("ot_hours") or 0))


def _post_dprday(c, rows):
    if not rows:
        return
    ids = FC._in(r["dpr_id"] for r in rows)
    lab = {x["dpr_id"]: x for x in q(c, "SELECT dpr_id, SUM(count) n, SUM(amount) a FROM dpr_labour WHERE dpr_id IN (%s) GROUP BY dpr_id" % ids)}
    eq = {x["dpr_id"]: x for x in q(c, "SELECT dpr_id, SUM(hours) h, SUM(idle_hours) i, SUM(amount) a FROM dpr_equipment WHERE dpr_id IN (%s) GROUP BY dpr_id" % ids)}
    wk = {x["dpr_id"]: x["n"] for x in q(c, "SELECT dpr_id, COUNT(*) n FROM dpr_work WHERE dpr_id IN (%s) GROUP BY dpr_id" % ids)}
    dl = {x["dpr_id"]: x["h"] for x in q(c, "SELECT dpr_id, SUM(hours) h FROM dpr_delays WHERE dpr_id IN (%s) GROUP BY dpr_id" % ids)}
    for r in rows:
        r["workers"] = (lab.get(r["dpr_id"]) or {}).get("n")
        r["labour_amount"] = (lab.get(r["dpr_id"]) or {}).get("a")
        r["machine_hours"] = (eq.get(r["dpr_id"]) or {}).get("h")
        r["idle_hours"] = (eq.get(r["dpr_id"]) or {}).get("i")
        r["machine_amount"] = (eq.get(r["dpr_id"]) or {}).get("a")
        r["work_lines"] = wk.get(r["dpr_id"], 0)
        r["delay_hours"] = dl.get(r["dpr_id"])
        r["lost_day"] = "yes" if r.get("lost_day") else ""


def _post_boq(c, rows):
    if not rows:
        return
    ids = FC._in(r["boq_id"] for r in rows)
    ms = {x["b"]: x["s"] for x in q(c, "SELECT l.boq_item_id b, SUM(l.qty) s FROM measurement_lines l JOIN measurements m ON m.id=l.measurement_id "
                                        "WHERE l.boq_item_id IN (%s) AND COALESCE(m.status,'') NOT IN ('cancelled','rejected') GROUP BY l.boq_item_id" % ids)}
    bl = {x["b"]: x["s"] for x in q(c, "SELECT l.boq_item_id b, SUM(l.qty) s FROM ipc_lines l JOIN ipc i ON i.id=l.ipc_id "
                                        "WHERE l.boq_item_id IN (%s) AND COALESCE(i.status,'') NOT IN ('cancelled','rejected','draft') GROUP BY l.boq_item_id" % ids)}
    for r in rows:
        qty = r["revised_qty"] if r.get("revised_qty") is not None else r.get("qty")
        rate = r["revised_rate"] if r.get("revised_rate") is not None else r.get("rate")
        r["amount"] = r2((r.get("qty") or 0) * (r.get("rate") or 0))
        r["current_qty"], r["current_rate"] = qty, rate
        r["current_amount"] = r2((qty or 0) * (rate or 0))
        ex = r.get("executed_qty") or 0
        r["executed_value"] = r2(ex * (rate or 0))
        r["executed_pct"] = r2(100.0 * ex / qty) if qty else None
        r["balance_qty"] = r2((qty or 0) - ex)
        r["measured_qty"] = r2(ms.get(r["boq_id"]) or 0)
        r["billed_qty"] = r2(bl.get(r["boq_id"]) or 0)
        r["billed_value"] = r2(r["billed_qty"] * (rate or 0))
        r["done_not_billed_qty"] = r2(ex - r["billed_qty"])


def _post_meas(c, rows):
    for r in rows:
        r["amount"] = r2((r.get("qty") or 0) * (r.get("rate") or 0))


def _post_bool(*keys):
    def f(c, rows):
        for r in rows:
            for k in keys:
                r[k] = "yes" if r.get(k) else ""
    return f


def _post_eq(c, rows):
    t = today()
    for r in rows:
        due = [x for x in (r.get("insurance_expiry"), r.get("registration_expiry"), r.get("operator_cert_expiry")) if x]
        r["next_expiry"] = min(due) if due else None
        r["expired"] = "yes" if due and min(due) < t else ""


def _post_audit(c, rows):
    for r in rows:
        r["date"] = (r.get("ts") or "")[:10]
        r["time"] = (r.get("ts") or "")[11:16]


DPRH = ("FROM dpr d LEFT JOIN projects p ON p.id=d.project_id ")
DPRS = "d.date, p.code project, d.no dpr_no, d.shift, d.status dpr_status, "
DPRC = [C("date", "Date", "date"), C("project", "Project"), C("dpr_no", "DPR"), C("shift", "Shift"), C("dpr_status", "DPR status")]

NEW_DATASETS = {
    # ── progress ──
    "dpr_days": S("DPR days (one line a DPR)", "progress", R_dpr,
                  "SELECT d.id dpr_id, " + DPRS + "d.weather, d.rain_mm, d.weather_lost_hours, d.lost_day, d.site_condition, d.version, d.remarks, "
                  "(SELECT name FROM users WHERE id=d.created_by) prepared_by, (SELECT name FROM users WHERE id=d.approved_by) approved_by, "
                  "substr(d.approved_at,1,10) approved_on " + DPRH, "d.date",
                  DPRC + [C("weather", "Weather"), C("rain_mm", "Rain (mm)", "number"), C("weather_lost_hours", "Hours lost to weather", "number"),
                          C("lost_day", "Lost day"), C("site_condition", "Site condition"), C("work_lines", "Work lines", "number"),
                          C("workers", "Workers", "number"), C("labour_amount", "Labour cost", "money"), C("machine_hours", "Machine hours", "number"),
                          C("idle_hours", "Machine idle hours", "number"), C("machine_amount", "Machine cost", "money"),
                          C("delay_hours", "Delay hours", "number"), C("version", "Revision", "number"), C("prepared_by", "Prepared by"),
                          C("approved_by", "Approved by"), C("approved_on", "Approved on", "date"), C("remarks", "Remarks")],
                  "d.project_id", "d.date, d.no", _post_dprday),
    "dpr_labour": S("DPR labour lines", "progress", R_dpr,
                    "SELECT " + DPRS + "a.code activity, a.name activity_name, t.code trade_code, t.name trade, pt.name gang, l.count workers, l.hours, "
                    "l.ot_hours, l.rate, l.amount " + DPRH + "JOIN dpr_labour l ON l.dpr_id=d.id LEFT JOIN activities a ON a.id=l.activity_id "
                    "LEFT JOIN trades t ON t.id=l.trade_id LEFT JOIN parties pt ON pt.id=l.party_id", "d.date",
                    DPRC + [C("activity", "Activity"), C("activity_name", "Activity name"), C("trade_code", "Trade code"), C("trade", "Trade"),
                            C("gang", "Labour supplier / gang"), C("workers", "Workers", "number"), C("hours", "Hours each", "number"),
                            C("ot_hours", "Overtime hours each", "number"), C("man_hours", "Man-hours", "number"), C("rate", "Rate", "money"),
                            C("amount", "Amount", "money")],
                    "d.project_id", "d.date, d.no, l.id", _post_lab),
    "dpr_machines": S("DPR machine lines", "progress", R_dpr,
                      "SELECT " + DPRS + "a.code activity, a.name activity_name, e.code machine, e.name machine_name, e.ownership, l.operator, "
                      "l.meter_start, l.meter_end, l.hours, l.idle_hours, l.breakdown_hours, l.output_qty, l.rate, l.amount " + DPRH +
                      "JOIN dpr_equipment l ON l.dpr_id=d.id LEFT JOIN activities a ON a.id=l.activity_id LEFT JOIN equipment e ON e.id=l.equipment_id",
                      "d.date",
                      DPRC + [C("activity", "Activity"), C("activity_name", "Activity name"), C("machine", "Machine"), C("machine_name", "Machine name"),
                              C("ownership", "Owned / hired"), C("operator", "Operator"), C("meter_start", "Meter start", "number"),
                              C("meter_end", "Meter end", "number"), C("hours", "Working hours", "number"), C("idle_hours", "Idle hours", "number"),
                              C("breakdown_hours", "Breakdown hours", "number"), C("output_qty", "Output", "number"), C("rate", "Rate", "money"),
                              C("amount", "Amount", "money")],
                      "d.project_id", "d.date, d.no, l.id"),
    "dpr_delays": S("DPR delays", "progress", R_dpr,
                    "SELECT " + DPRS + "a.code activity, a.name activity_name, l.category, l.hours, l.responsibility, l.description, "
                    "ev.no event " + DPRH + "JOIN dpr_delays l ON l.dpr_id=d.id LEFT JOIN activities a ON a.id=l.activity_id "
                    "LEFT JOIN events ev ON ev.id=l.event_id", "d.date",
                    DPRC + [C("activity", "Activity"), C("activity_name", "Activity name"), C("category", "Cause"), C("hours", "Hours", "number"),
                            C("responsibility", "Responsibility"), C("description", "Description"), C("event", "Event")],
                    "d.project_id", "d.date, d.no, l.id"),
    # ── stores ──
    "stock_moves": S("Stock movements (stock card)", "stores", R("inventory"),
                     "SELECT s.date, p.code project, st.name store, " + MATS + ", s.doc_type, s.doc_no, s.qty_in, s.qty_out, s.rate, s.value_in, "
                     "s.value_out, s.batch_no FROM stock_ledger s " + P % "s.project_id" + "LEFT JOIN stores st ON st.id=s.store_id " +
                     MATJ % "s.material_id", "s.date",
                     [C("date", "Date", "date"), C("project", "Project"), C("store", "Store")] + MAT +
                     [C("doc_type", "Document type"), C("doc_no", "Document"), C("qty_in", "Qty in", "number"), C("qty_out", "Qty out", "number"),
                      C("net_qty", "Net qty", "number"), C("rate", "Rate", "money"), C("value_in", "Value in", "money"),
                      C("value_out", "Value out", "money"), C("net_value", "Net value", "money"), C("batch_no", "Batch")],
                     "s.project_id", "s.date, s.id", _post_stock),
    "stock_onhand": S("Stock on hand", "stores", R("inventory"),
                      "SELECT p.code project, st.name store, " + MATS + ", b.qty, b.value, b.last_date, m.min_level, m.reorder_level, "
                      "m.standard_rate FROM stock_balances b " + P % "b.project_id" + "LEFT JOIN stores st ON st.id=b.store_id " +
                      MATJ % "b.material_id", None,
                      [C("project", "Project"), C("store", "Store")] + MAT +
                      [C("qty", "Qty on hand", "number"), C("value", "Value", "money"), C("avg_rate", "Average rate", "money"),
                       C("min_level", "Minimum level", "number"), C("reorder_level", "Reorder level", "number"), C("below_reorder", "Below reorder"),
                       C("standard_rate", "Standard rate", "money"), C("last_date", "Last movement", "date")],
                      "b.project_id", "p.code, st.name, m.code", _post_onhand),
    "grn_lines": S("Goods received (GRN lines)", "stores", R("inventory", "procurement"),
                   "SELECT g.date, p.code project, g.no grn, g.status, v.name supplier, po.no po, st.name store, g.challan_no, g.vehicle_no, "
                   "g.procurement_purpose purpose, " + MATS + ", l.received_qty, l.accepted_qty, l.rejected_qty, l.rate, l.invoiced_qty, l.batch_no, "
                   "l.remarks FROM grn_lines l JOIN grn g ON g.id=l.grn_id " + P % "g.project_id" + "LEFT JOIN parties v ON v.id=g.vendor_id "
                   "LEFT JOIN po ON po.id=g.po_id LEFT JOIN stores st ON st.id=g.store_id " + MATJ % "l.material_id", "g.date",
                   [C("date", "Date", "date"), C("project", "Project"), C("grn", "GRN"), C("status", "Status"), C("supplier", "Supplier"),
                    C("po", "Purchase order"), C("store", "Store"), C("challan_no", "Challan"), C("vehicle_no", "Vehicle"), C("purpose", "Purpose")] + MAT +
                   [C("received_qty", "Received", "number"), C("accepted_qty", "Accepted", "number"), C("rejected_qty", "Rejected", "number"),
                    C("rate", "Rate", "money"), C("amount", "Accepted value", "money"), C("invoiced_qty", "Billed qty", "number"),
                    C("batch_no", "Batch"), C("remarks", "Remarks")],
                   "g.project_id", "g.date, g.no, l.id", _post_grn),
    "issue_lines": S("Material issued to site (issue lines)", "stores", R("inventory"),
                     "SELECT i.date, p.code project, i.no issue, i.status, st.name store, i.issued_to, " + MATS + ", l.qty, l.returned_qty, l.rate, "
                     "l.amount, l.target, b.code boq, b.description boq_description, a.code activity, e.code machine, mq.no mrq "
                     "FROM issue_lines l JOIN issues i ON i.id=l.issue_id " + P % "i.project_id" + "LEFT JOIN stores st ON st.id=i.store_id " +
                     MATJ % "l.material_id" + "LEFT JOIN boq_items b ON b.id=l.boq_item_id LEFT JOIN activities a ON a.id=l.activity_id "
                     "LEFT JOIN equipment e ON e.id=l.equipment_id LEFT JOIN mrq mq ON mq.id=i.mrq_id", "i.date",
                     [C("date", "Date", "date"), C("project", "Project"), C("issue", "Issue"), C("status", "Status"), C("store", "Store"),
                      C("issued_to", "Issued to")] + MAT +
                     [C("qty", "Qty issued", "number"), C("returned_qty", "Qty returned", "number"), C("net_qty", "Net qty used", "number"),
                      C("rate", "Rate", "money"), C("amount", "Amount", "money"), C("target", "Used for"), C("boq", "BOQ item"),
                      C("boq_description", "BOQ description"), C("activity", "Activity"), C("machine", "Machine"), C("mrq", "Request")],
                     "i.project_id", "i.date, i.no, l.id", _post_issue),
    "mrq_lines": S("Material requests", "stores", R("inventory", "procurement"),
                   "SELECT r.date, p.code project, r.no mrq, r.status, st.name store, r.requested_by, " + MATS + ", l.qty, l.approved_qty, "
                   "l.issued_qty, l.pr_qty, b.code boq, l.remarks FROM mrq_lines l JOIN mrq r ON r.id=l.mrq_id " + P % "r.project_id" +
                   "LEFT JOIN stores st ON st.id=r.store_id " + MATJ % "l.material_id" + "LEFT JOIN boq_items b ON b.id=l.boq_item_id", "r.date",
                   [C("date", "Date", "date"), C("project", "Project"), C("mrq", "Request"), C("status", "Status"), C("store", "Store"),
                    C("requested_by", "Requested by")] + MAT +
                   [C("qty", "Requested", "number"), C("approved_qty", "Approved", "number"), C("issued_qty", "Issued", "number"),
                    C("pending_qty", "Still to issue", "number"), C("pr_qty", "Sent to purchase", "number"), C("boq", "BOQ item"), C("remarks", "Remarks")],
                   "r.project_id", "r.date, r.no, l.id", _post_mrq),
    # ── procurement ──
    "po_lines": S("Purchase orders (lines)", "procurement", R("procurement"),
                  "SELECT o.date, o.delivery_date, p.code project, o.no po, o.status, v.name supplier, o.payment_terms, " + MATS + ", "
                  "COALESCE(l.description, m.name) description, l.qty, l.received_qty, l.rate, l.vat_rate, b.code boq FROM po_lines l "
                  "JOIN po o ON o.id=l.po_id " + P % "o.project_id" + "LEFT JOIN parties v ON v.id=o.vendor_id " + MATJ % "l.material_id" +
                  "LEFT JOIN boq_items b ON b.id=l.boq_item_id", "o.date",
                  [C("date", "Date", "date"), C("delivery_date", "Delivery due", "date"), C("project", "Project"), C("po", "Purchase order"),
                   C("status", "Status"), C("supplier", "Supplier"), C("payment_terms", "Payment terms")] + MAT +
                  [C("description", "Description"), C("qty", "Ordered", "number"), C("received_qty", "Received", "number"),
                   C("open_qty", "Still to come", "number"), C("rate", "Rate", "money"), C("vat_rate", "VAT %", "number"),
                   C("amount", "Order value", "money"), C("open_value", "Value still to come", "money"), C("boq", "BOQ item")],
                  "o.project_id", "o.date, o.no, l.id", _post_po),
    "bills": S("Purchase bills and client invoices", "accounts", R("accounts", "procurement"),
               "SELECT i.date, i.due_date, p.code project, i.no, i.kind, i.status, pt.name party, i.party_inv_no, i.subtotal, i.vat, i.tds, "
               "i.retention, i.advance_recovery, i.total, i.payable, i.match_status, i.procurement_purpose purpose, po.no po, i.remarks "
               "FROM invoices i " + P % "i.project_id" + "LEFT JOIN parties pt ON pt.id=i.party_id LEFT JOIN po ON po.id=i.po_id", "i.date",
               [C("date", "Date", "date"), C("due_date", "Due", "date"), C("project", "Project"), C("no", "Number"), C("kind", "Purchase / sales"),
                C("status", "Status"), C("party", "Party"), C("party_inv_no", "Party's bill no"), C("subtotal", "Before VAT", "money"),
                C("vat", "VAT", "money"), C("tds", "TDS", "money"), C("retention", "Retention", "money"), C("advance_recovery", "Advance recovered", "money"),
                C("total", "Total", "money"), C("payable", "Payable / receivable", "money"), C("match_status", "3-way match"), C("purpose", "Purpose"),
                C("po", "Purchase order"), C("remarks", "Remarks")],
               "i.project_id", "i.date, i.no", extra=_bill_kinds),
    "bill_lines": S("Bill and invoice lines", "accounts", R("accounts", "procurement"),
                    "SELECT i.date, p.code project, i.no, i.kind, i.status, pt.name party, " + MATS + ", COALESCE(l.description, m.name) description, "
                    "l.qty, l.rate, l.vat_rate, l.amount, a.code account_code, a.name account, e.code machine, b.code boq FROM invoice_lines l "
                    "JOIN invoices i ON i.id=l.invoice_id " + P % "i.project_id" + "LEFT JOIN parties pt ON pt.id=i.party_id " + MATJ % "l.material_id" +
                    "LEFT JOIN accounts a ON a.id=l.account_id LEFT JOIN equipment e ON e.id=l.equipment_id LEFT JOIN boq_items b ON b.id=l.boq_item_id",
                    "i.date",
                    [C("date", "Date", "date"), C("project", "Project"), C("no", "Number"), C("kind", "Purchase / sales"), C("status", "Status"),
                     C("party", "Party")] + MAT +
                    [C("description", "Description"), C("qty", "Qty", "number"), C("rate", "Rate", "money"), C("vat_rate", "VAT %", "number"),
                     C("amount", "Amount", "money"), C("account_code", "Account code"), C("account", "Account"), C("machine", "Machine"),
                     C("boq", "BOQ item")],
                    "i.project_id", "i.date, i.no, l.id", extra=_bill_kinds),
    "payments": S("Payments and receipts", "accounts", R("accounts"),
                  "SELECT y.date, p.code project, y.no, y.kind, y.status, pt.name party, a.name bank, y.gross, y.tds, y.net, y.advance, y.mode, "
                  "y.cheque_no, y.funding_purpose purpose, y.remarks FROM payments y " + P % "y.project_id" +
                  "LEFT JOIN parties pt ON pt.id=y.party_id LEFT JOIN accounts a ON a.id=y.bank_account_id", "y.date",
                  [C("date", "Date", "date"), C("project", "Project"), C("no", "Number"), C("kind", "Paid / received"), C("status", "Status"),
                   C("party", "Party"), C("bank", "Bank or cash"), C("gross", "Gross", "money"), C("tds", "TDS", "money"), C("net", "Net", "money"),
                   C("advance", "Advance"), C("mode", "Mode"), C("cheque_no", "Cheque"), C("purpose", "Funding"), C("remarks", "Remarks")],
                  "y.project_id", "y.date, y.no"),
    "vouchers": S("Vouchers", "accounts", R("accounts"),
                  "SELECT v.date, v.no, v.type, v.status, p.code project, pt.name party, v.ref_no, v.total, v.narration, v.source, "
                  "(SELECT name FROM users WHERE id=v.created_by) created_by, (SELECT name FROM users WHERE id=v.approved_by) approved_by "
                  "FROM vouchers v " + P % "v.project_id" + "LEFT JOIN parties pt ON pt.id=v.party_id", "v.date",
                  [C("date", "Date", "date"), C("no", "Voucher"), C("type", "Type"), C("status", "Status"), C("project", "Project"), C("party", "Party"),
                   C("ref_no", "Reference"), C("total", "Amount", "money"), C("narration", "Narration"), C("source", "Made from"),
                   C("created_by", "Entered by"), C("approved_by", "Approved by")],
                  "v.project_id", "v.date, v.id"),
    # ── equipment ──
    "machine_days": S("Machine days (logsheets)", "equipment", R("equipment"),
                      "SELECT l.date, p.code project, e.code machine, e.name machine_name, e.category, e.ownership, l.shift, l.operator, "
                      "l.meter_start, l.meter_end, l.hours, l.idle_hours, l.breakdown_hours, l.standby_hours, l.km_run, l.trips, l.fuel_qty, "
                      "l.work, a.code activity, b.code boq, l.status, d.no dpr_no, l.down_reason, l.cost_code FROM logsheets l "
                      + P % "l.project_id" + "LEFT JOIN equipment e ON e.id=l.equipment_id LEFT JOIN activities a ON a.id=l.activity_id "
                      "LEFT JOIN boq_items b ON b.id=l.boq_item_id LEFT JOIN dpr d ON d.id=l.dpr_id", "l.date",
                      [C("date", "Date", "date"), C("project", "Project"), C("machine", "Machine"), C("machine_name", "Machine name"),
                       C("category", "Category"), C("ownership", "Owned / hired"), C("shift", "Shift"), C("operator", "Operator"),
                       C("meter_start", "Meter start", "number"), C("meter_end", "Meter end", "number"), C("hours", "Working hours", "number"),
                       C("idle_hours", "Idle hours", "number"), C("breakdown_hours", "Breakdown hours", "number"),
                       C("standby_hours", "Standby hours", "number"), C("km_run", "Km run", "number"), C("trips", "Trips", "number"),
                       C("fuel_qty", "Fuel (litres)", "number"), C("work", "Work done"), C("activity", "Activity"), C("boq", "BOQ item"),
                       C("status", "Status"), C("dpr_no", "DPR"), C("down_reason", "Breakdown reason"), C("cost_code", "Cost code")],
                      "l.project_id", "l.date, e.code, l.id"),
    "equipment_list": S("Equipment register", "equipment", R("equipment"),
                        "SELECT e.code, e.name, e.category, e.make, e.model, e.serial, e.reg_no, e.ownership, e.status, p.code project, "
                        "e.operator, e.responsible_person, e.location, e.purchase_date, e.purchase_value, e.accumulated_dep, e.meter, e.meter_type, "
                        "e.fuel_norm, e.internal_rate, e.insurance_expiry, e.registration_expiry, e.operator_cert_expiry, v.name owner "
                        "FROM equipment e " + P % "e.project_id" + "LEFT JOIN parties v ON v.id=e.vendor_id", None,
                        [C("code", "Machine"), C("name", "Name"), C("category", "Category"), C("make", "Make"), C("model", "Model"),
                         C("serial", "Serial"), C("reg_no", "Registration"), C("ownership", "Owned / hired"), C("owner", "Hired from"),
                         C("status", "Status"), C("project", "Project now"), C("operator", "Operator"), C("responsible_person", "Responsible"),
                         C("location", "Location"), C("purchase_date", "Bought on", "date"), C("purchase_value", "Purchase value", "money"),
                         C("accumulated_dep", "Depreciation to date", "money"), C("meter", "Meter reading", "number"), C("meter_type", "Meter"),
                         C("fuel_norm", "Fuel norm", "number"), C("internal_rate", "Internal rate", "money"),
                         C("insurance_expiry", "Insurance expires", "date"), C("registration_expiry", "Registration expires", "date"),
                         C("operator_cert_expiry", "Operator licence expires", "date"), C("next_expiry", "Next expiry", "date"),
                         C("expired", "Something expired")],
                        "e.project_id", "e.code", _post_eq),
    # ── commercial ──
    "boq_progress": S("BOQ items and progress", "commercial", R("commercial", "project"),
                      "SELECT b.id boq_id, p.code project, b.code, b.description, b.unit, b.qty, b.rate, b.revised_qty, b.revised_rate, "
                      "b.executed_qty, b.location, w.code wbs FROM boq_items b " + P % "b.project_id" + "LEFT JOIN wbs w ON w.id=b.wbs_id", None,
                      [C("project", "Project"), C("code", "BOQ item"), C("description", "Description"), C("unit", "Unit"), C("wbs", "WBS"),
                       C("location", "Location"), C("qty", "Contract qty", "number"), C("rate", "Contract rate", "money"),
                       C("amount", "Contract amount", "money"), C("current_qty", "Current qty", "number"), C("current_rate", "Current rate", "money"),
                       C("current_amount", "Current amount", "money"), C("executed_qty", "Done qty", "number"),
                       C("executed_value", "Done value", "money"), C("executed_pct", "Done %", "number"), C("balance_qty", "Balance qty", "number"),
                       C("measured_qty", "Measured qty", "number"), C("billed_qty", "Billed qty", "number"), C("billed_value", "Billed value", "money"),
                       C("done_not_billed_qty", "Done, not billed qty", "number")],
                      "b.project_id", "p.code, b.code", _post_boq),
    "measure_lines": S("Measurements (lines)", "commercial", R("commercial", "project"),
                       "SELECT m.date, p.code project, m.no, m.status, b.code boq, b.description, b.unit, l.qty, "
                       "COALESCE(b.revised_rate, b.rate) rate, l.location, l.remarks FROM measurement_lines l JOIN measurements m ON m.id=l.measurement_id "
                       + P % "m.project_id" + "LEFT JOIN boq_items b ON b.id=l.boq_item_id", "m.date",
                       [C("date", "Date", "date"), C("project", "Project"), C("no", "Measurement"), C("status", "Status"), C("boq", "BOQ item"),
                        C("description", "Description"), C("unit", "Unit"), C("qty", "Qty", "number"), C("rate", "Rate", "money"),
                        C("amount", "Amount", "money"), C("location", "Location"), C("remarks", "Remarks")],
                       "m.project_id", "m.date, m.no, l.id", _post_meas),
    "variations": S("Variations", "commercial", R("commercial"),
                    "SELECT v.date, p.code project, v.no, v.title, v.status, b.code boq, COALESCE(v.new_description, b.description) description, "
                    "COALESCE(v.new_unit, b.unit) unit, v.var_qty, v.new_rate, v.est_value, v.time_impact_days, v.approved_date, v.reason, "
                    "v.instruction_ref FROM variations v " + P % "v.project_id" + "LEFT JOIN boq_items b ON b.id=v.boq_item_id", "v.date",
                    [C("date", "Date", "date"), C("project", "Project"), C("no", "Variation"), C("title", "Title"), C("status", "Status"),
                     C("boq", "BOQ item"), C("description", "Description"), C("unit", "Unit"), C("var_qty", "Qty", "number"),
                     C("new_rate", "Rate", "money"), C("est_value", "Estimated value", "money"), C("time_impact_days", "Time impact (days)", "number"),
                     C("approved_date", "Approved", "date"), C("reason", "Reason"), C("instruction_ref", "Instruction")],
                    "v.project_id", "v.date, v.no"),
    "sc_orders": S("Subcontract work orders", "commercial", R("commercial"),
                   "SELECT o.date, o.start_date, o.end_date, p.code project, o.no, o.title, o.type, o.status, pt.name subcontractor, "
                   "o.retention_pct, o.advance, o.vat_rate FROM sc_orders o " + P % "o.project_id" + "LEFT JOIN parties pt ON pt.id=o.party_id",
                   "o.date",
                   [C("date", "Date", "date"), C("start_date", "Start", "date"), C("end_date", "Finish", "date"), C("project", "Project"),
                    C("no", "Work order"), C("title", "Title"), C("type", "Type"), C("status", "Status"), C("subcontractor", "Subcontractor"),
                    C("retention_pct", "Retention %", "number"), C("advance", "Advance", "money"), C("vat_rate", "VAT %", "number")],
                   "o.project_id", "o.date, o.no"),
    "sc_bills": S("Subcontract bills", "commercial", R("commercial"),
                  "SELECT b.date, b.period_to, p.code project, b.no, o.no work_order, pt.name subcontractor, b.party_bill_no, b.status, b.gross, "
                  "b.material_recovery, b.equipment_recovery, b.other_deduction, b.advance_recovery, b.retention, b.vat, b.net FROM sc_bills b "
                  + P % "b.project_id" + "LEFT JOIN sc_orders o ON o.id=b.order_id LEFT JOIN parties pt ON pt.id=b.party_id", "b.date",
                  [C("date", "Date", "date"), C("period_to", "Work up to", "date"), C("project", "Project"), C("no", "Bill"),
                   C("work_order", "Work order"), C("subcontractor", "Subcontractor"), C("party_bill_no", "Their bill no"), C("status", "Status"),
                   C("gross", "Gross", "money"), C("material_recovery", "Material recovered", "money"),
                   C("equipment_recovery", "Equipment recovered", "money"), C("other_deduction", "Other deductions", "money"),
                   C("advance_recovery", "Advance recovered", "money"), C("retention", "Retention", "money"), C("vat", "VAT", "money"),
                   C("net", "Net", "money")],
                  "b.project_id", "b.date, b.no"),
    "events": S("Events and claims", "commercial", R("commercial"),
                "SELECT e.date, p.code project, e.no, e.type, e.title, e.status, e.responsibility, e.responsible_party, e.clause, e.delay_days, "
                "e.cost_impact, e.notice_deadline, e.notice_sent, e.eot_claimed, e.eot_granted, e.claim_value, e.prolongation_cost, e.excusable, "
                "e.compensable FROM events e " + P % "e.project_id", "e.date",
                [C("date", "Date", "date"), C("project", "Project"), C("no", "Event"), C("type", "Type"), C("title", "Title"), C("status", "Status"),
                 C("responsibility", "Responsibility"), C("responsible_party", "Responsible party"), C("clause", "Clause"),
                 C("delay_days", "Delay (days)", "number"), C("cost_impact", "Cost impact", "money"), C("notice_deadline", "Notice due", "date"),
                 C("notice_sent", "Notice sent"), C("eot_claimed", "EOT claimed (days)", "number"), C("eot_granted", "EOT granted (days)", "number"),
                 C("claim_value", "Claim value", "money"), C("prolongation_cost", "Prolongation cost", "money"), C("excusable", "Excusable"),
                 C("compensable", "Compensable")],
                "e.project_id", "e.date, e.no", _post_bool("excusable", "compensable")),
    # ── quality and safety ──
    "field_issues": S("Issues and punch list", "quality", R("project", "quality"),
                      "SELECT substr(i.ts,1,10) date, p.code project, i.no, i.type, i.title, i.location, i.priority, i.status, "
                      "COALESCE(i.assignee, (SELECT name FROM users WHERE id=i.assignee_user_id)) assignee, pt.name party, i.due_date, i.closed_on, "
                      "i.root_cause, i.cost FROM fld_issues i " + P % "i.project_id" + "LEFT JOIN parties pt ON pt.id=i.party_id", "i.ts",
                      [C("date", "Raised", "date"), C("project", "Project"), C("no", "Issue"), C("type", "Type"), C("title", "Title"),
                       C("location", "Location"), C("priority", "Priority"), C("status", "Status"), C("assignee", "Assigned to"),
                       C("party", "Party"), C("due_date", "Due", "date"), C("closed_on", "Closed", "date"), C("root_cause", "Root cause"),
                       C("cost", "Cost", "money")],
                      "i.project_id", "i.ts, i.no"),
    "rfis": S("RFIs", "quality", R("project", "quality"),
              "SELECT substr(r.ts,1,10) date, p.code project, r.no, r.subject, r.discipline, r.priority, r.status, r.ball_in_court, "
              "COALESCE(r.assignee, (SELECT name FROM users WHERE id=r.assignee_user_id)) assignee, r.due_date, r.sent_on, r.answered_on, "
              "r.closed_on, r.cost_impact, r.schedule_impact FROM fld_rfis r " + P % "r.project_id", "r.ts",
              [C("date", "Raised", "date"), C("project", "Project"), C("no", "RFI"), C("subject", "Subject"), C("discipline", "Discipline"),
               C("priority", "Priority"), C("status", "Status"), C("ball_in_court", "Ball in court"), C("assignee", "Assigned to"),
               C("due_date", "Due", "date"), C("sent_on", "Sent", "date"), C("answered_on", "Answered", "date"), C("closed_on", "Closed", "date"),
               C("cost_impact", "Cost impact"), C("schedule_impact", "Schedule impact")],
              "r.project_id", "r.ts, r.no"),
    "inspections": S("Inspections", "quality", R("project", "quality"),
                     "SELECT i.date, p.code project, i.no, i.title, i.location, a.code activity, pt.name party, i.inspector, i.result, i.failed, "
                     "i.status, i.remarks FROM fld_inspections i " + P % "i.project_id" +
                     "LEFT JOIN activities a ON a.id=i.activity_id LEFT JOIN parties pt ON pt.id=i.party_id", "i.date",
                     [C("date", "Date", "date"), C("project", "Project"), C("no", "Inspection"), C("title", "Title"), C("location", "Location"),
                      C("activity", "Activity"), C("party", "Party"), C("inspector", "Inspector"), C("result", "Result"),
                      C("failed", "Items failed", "number"), C("status", "Status"), C("remarks", "Remarks")],
                     "i.project_id", "i.date, i.no"),
    "incidents": S("Safety incidents", "quality", R("project"),
                   "SELECT i.date, p.code project, i.no, i.kind, i.location, i.person, pt.name party, i.injury, i.days_lost, i.cause, i.status, "
                   "i.action_owner, i.action_due, i.cost, i.insurance_claim FROM hs_incidents i " + P % "i.project_id" +
                   "LEFT JOIN parties pt ON pt.id=i.party_id", "i.date",
                   [C("date", "Date", "date"), C("project", "Project"), C("no", "Incident"), C("kind", "Kind"), C("location", "Location"),
                    C("person", "Person"), C("party", "Employer / subcontractor"), C("injury", "Injury"), C("days_lost", "Days lost", "number"),
                    C("cause", "Cause"), C("status", "Status"), C("action_owner", "Action owner"), C("action_due", "Action due", "date"),
                    C("cost", "Cost", "money"), C("insurance_claim", "Insurance claim")],
                   "i.project_id", "i.date, i.no"),
    "tasks": S("Tasks", "quality", R("project"),
               "SELECT substr(t.ts,1,10) date, p.code project, t.title, t.priority, t.status, (SELECT name FROM users WHERE id=t.assigned_to) assigned_to, "
               "t.due_date, substr(t.done_at,1,10) done_on, t.source_type FROM tasks t " + P % "t.project_id", "t.ts",
               [C("date", "Made", "date"), C("project", "Project"), C("title", "Task"), C("priority", "Priority"), C("status", "Status"),
                C("assigned_to", "Assigned to"), C("due_date", "Due", "date"), C("done_on", "Done", "date"), C("source_type", "From")],
               "t.project_id", "t.ts, t.id"),
    # ── master data ──
    "parties": S("Vendors, subcontractors and clients", "masters", R("masters", "procurement", "accounts"),
                 "SELECT x.code, x.name, x.kind, x.pan, x.vat_registered, x.phone, x.email, x.address, x.credit_days, x.categories, x.blacklisted, "
                 "x.active FROM parties x", None,
                 [C("code", "Code"), C("name", "Name"), C("kind", "Kind"), C("pan", "PAN"), C("vat_registered", "VAT registered"), C("phone", "Phone"),
                  C("email", "Email"), C("address", "Address"), C("credit_days", "Credit days", "number"), C("categories", "Supplies"),
                  C("blacklisted", "Blacklisted"), C("active", "Active")],
                 None, "x.kind, x.code", _post_bool("vat_registered", "blacklisted", "active")),
    "materials": S("Materials", "masters", R("masters", "inventory", "procurement"),
                   "SELECT x.code material_code, x.name material, x.local_name, x.category, x.unit, x.spec, x.standard_rate, x.min_level, "
                   "x.reorder_level, x.reorder_qty, x.lead_days, x.active FROM materials x", None,
                   MAT + [C("local_name", "Local name"), C("spec", "Specification"), C("standard_rate", "Standard rate", "money"),
                          C("min_level", "Minimum level", "number"), C("reorder_level", "Reorder level", "number"),
                          C("reorder_qty", "Reorder qty", "number"), C("lead_days", "Lead days", "number"), C("active", "Active")],
                   None, "x.category, x.code", _post_bool("active")),
    "audit_log": S("Audit log (who did what)", "admin", R_adm,
                   "SELECT a.ts, COALESCE(us.name, us.username) user, a.action, a.entity, a.entity_id FROM audit a LEFT JOIN users us ON us.id=a.user_id",
                   "a.ts",
                   [C("date", "Date", "date"), C("time", "Time"), C("user", "User"), C("action", "Action"), C("entity", "Record type"),
                    C("entity_id", "Record id", "number")],
                   None, "a.ts, a.id", _post_audit),
}
for _k, _ds in NEW_DATASETS.items():
    _ds["key"] = _k

AREAS = [("progress", "Site progress (DPR)"), ("stores", "Store and materials"), ("procurement", "Procurement"),
         ("accounts", "Accounts"), ("finance", "Cash and finance"), ("equipment", "Equipment"), ("commercial", "Commercial and contracts"),
         ("quality", "Quality, safety and tasks"), ("masters", "Master data"), ("admin", "Administration")]
AREA_OF = {"dpr": "progress", "labour": "progress", "equipment": "equipment", "cash_weeks": "finance", "cash_lines": "finance",
           "receivables": "finance", "ipcs": "finance", "payables": "finance", "projects": "finance", "ledger": "accounts",
           "alerts": "finance", "commitments": "procurement"}


_TABLES = {"dpr_days": "dpr", "dpr_labour": "dpr_labour", "dpr_machines": "dpr_equipment", "dpr_delays": "dpr_delays",
           "stock_moves": "stock_ledger", "stock_onhand": "stock_balances", "grn_lines": "grn_lines", "issue_lines": "issue_lines",
           "mrq_lines": "mrq_lines", "po_lines": "po_lines", "bills": "invoices", "bill_lines": "invoice_lines", "payments": "payments",
           "vouchers": "vouchers", "machine_days": "logsheets", "equipment_list": "equipment", "boq_progress": "boq_items",
           "measure_lines": "measurement_lines", "variations": "variations", "sc_orders": "sc_orders", "sc_bills": "sc_bills",
           "events": "events", "field_issues": "fld_issues", "rfis": "fld_rfis", "inspections": "fld_inspections", "incidents": "hs_incidents",
           "tasks": "tasks", "parties": "parties", "materials": "materials", "audit_log": "audit"}


def dataset_ok(c, u, key):
    ds = FC.DATASETS.get(key)
    if not ds:
        return False
    if key in NEW_DATASETS:
        if not _has(c, _TABLES.get(key, "projects")):
            return False
        return bool(ds["right"](c, u))
    return _ORIG_DATASET_OK(c, u, key)


_ORIG_DATASET_OK = None


# ───────────────────────────── time ─────────────────────────────
TIME_PARTS = [("week", "week (from Sunday)", "date"), ("month", "month", "text"), ("year", "year", "text"), ("bs", "Nepali date", "text"),
              ("bsmonth", "Nepali month", "text"), ("fy", "fiscal year", "text"), ("fyq", "fiscal quarter", "text")]
_BS = {}


def bs_of(s):
    s = str(s)[:10]
    if s not in _BS:
        try:
            _BS[s] = SC.ad_to_bs(s)
        except Exception:
            _BS[s] = None
    return _BS[s]


def _fy_of(b):
    y, m = b[0], b[1]
    fy = y if m >= 4 else y - 1
    return fy


def _fy_label(fy):
    return "%d/%02d" % (fy, (fy + 1) % 100)


def part(v, p):
    d = _d(v)
    if not d:
        return None
    if p == "week":
        return (d - timedelta(days=(d.weekday() + 1) % 7)).isoformat()
    if p == "month":
        return d.isoformat()[:7]
    if p == "year":
        return str(d.year)
    b = bs_of(d.isoformat())
    if not b:
        return None
    if p == "bs":
        return "%d-%02d-%02d" % b
    if p == "bsmonth":
        return "%d-%02d %s" % (b[0], b[1], SC.BS_MONTHS[b[1] - 1])
    fy = _fy_of(b)
    if p == "fy":
        return _fy_label(fy)
    if p == "fyq":
        return "%s Q%d" % (_fy_label(fy), {4: 1, 5: 1, 6: 1, 7: 2, 8: 2, 9: 2, 10: 3, 11: 3, 12: 3, 1: 4, 2: 4, 3: 4}[b[1]])
    return None


def _bs_month_range(y, m):
    lens = SC._lens(y)
    return SC.bs_to_ad(y, m, 1).isoformat(), SC.bs_to_ad(y, m, lens[m - 1]).isoformat()


def _fy_range(fy):
    return SC.bs_to_ad(fy, 4, 1).isoformat(), _bs_month_range(fy + 1, 3)[1]


PERIODS = [("custom", "Dates below"), ("today", "Today"), ("yesterday", "Yesterday"), ("this_week", "This week (from Sunday)"),
           ("last_week", "Last week"), ("last_7", "Last 7 days"), ("last_30", "Last 30 days"), ("last_90", "Last 90 days"),
           ("this_month", "This month"), ("last_month", "Last month"), ("this_year", "This calendar year"),
           ("this_bs_month", "This Nepali month"), ("last_bs_month", "Last Nepali month"), ("bs_month", "A Nepali month (choose)"),
           ("this_fyq", "This fiscal quarter (Nepali)"), ("last_fyq", "Last fiscal quarter (Nepali)"),
           ("this_fy", "This fiscal year (Shrawan to Asar)"), ("last_fy", "Last fiscal year"), ("fy", "A fiscal year (choose)"),
           ("all", "All dates")]


def period_dates(d):
    p = d.get("period")
    t = _d(today())
    if p in ("today", "yesterday"):
        x = t if p == "today" else t - timedelta(days=1)
        return x.isoformat(), x.isoformat()
    if p in ("this_week", "last_week"):
        s = t - timedelta(days=(t.weekday() + 1) % 7)
        if p == "last_week":
            s -= timedelta(days=7)
            return s.isoformat(), (s + timedelta(days=6)).isoformat()
        return s.isoformat(), t.isoformat()
    if p in ("this_bs_month", "last_bs_month", "bs_month"):
        if p == "bs_month":
            try:
                y, m = [int(x) for x in str(d.get("bs_month") or "").split("-")[:2]]
            except ValueError:
                raise ApiError("Choose the Nepali month (year and month).")
        else:
            y, m, _ = bs_of(t.isoformat())
            if p == "last_bs_month":
                y, m = (y, m - 1) if m > 1 else (y - 1, 12)
        try:
            a, b = _bs_month_range(y, m)
        except Exception:
            raise ApiError("That Nepali month is outside the calendar BuildCore knows (2070 to 2090).")
        return a, (min(b, t.isoformat()) if p == "this_bs_month" else b)
    if p in ("this_fy", "last_fy", "fy"):
        if p == "fy":
            try:
                fy = int(str(d.get("fy") or "").split("/")[0])
            except ValueError:
                raise ApiError("Choose the fiscal year.")
        else:
            fy = _fy_of(bs_of(t.isoformat())) - (1 if p == "last_fy" else 0)
        try:
            a, b = _fy_range(fy)
        except Exception:
            raise ApiError("That fiscal year is outside the calendar BuildCore knows (2070 to 2090).")
        return a, (min(b, t.isoformat()) if p == "this_fy" else b)
    if p in ("this_fyq", "last_fyq"):
        y, m, _ = bs_of(t.isoformat())
        fy = _fy_of((y, m))
        qn = {4: 0, 5: 0, 6: 0, 7: 1, 8: 1, 9: 1, 10: 2, 11: 2, 12: 2, 1: 3, 2: 3, 3: 3}[m]
        if p == "last_fyq":
            qn -= 1
            if qn < 0:
                qn, fy = 3, fy - 1
        ms = [(fy, 4 + 3 * qn + i) if qn < 3 else (fy + 1, 1 + i) for i in range(3)]
        a = _bs_month_range(*ms[0])[0]
        b = _bs_month_range(*ms[2])[1]
        return a, (min(b, t.isoformat()) if p == "this_fyq" else b)
    return FC.period_dates(p, d.get("from"), d.get("to"))


# ───────────────────────────── running a report ─────────────────────────────
OPS = ("eq", "ne", "contains", "not_contains", "starts", "gt", "gte", "lt", "lte", "between", "in", "empty", "notempty")
CALC_OPS = {"add": "+", "sub": "-", "mul": "×", "div": "÷", "pct": "as % of", "days": "days from … to"}
DATE_STYLES = ("ad", "bs", "both")


def _cmp(v, op, x, x2, typ):
    if op == "not_contains":
        return v in (None, "") or str(x or "").lower() not in str(v).lower()
    if op == "starts":
        return v not in (None, "") and str(v).lower().startswith(str(x or "").lower())
    if op == "between":
        if v in (None, ""):
            return False
        lo, hi = x, x2
        if typ in ("number", "money"):
            try:
                fv = float(v)
                return (lo in (None, "") or fv >= float(lo)) and (hi in (None, "") or fv <= float(hi))
            except (TypeError, ValueError):
                return False
        sv = str(v)[:10] if typ == "date" else str(v).lower()
        lo = str(lo or "").lower()
        hi = str(hi or "").lower()
        return (not lo or sv >= lo) and (not hi or sv <= hi)
    if typ == "date" and op in ("gt", "gte", "lt", "lte", "eq", "ne") and v not in (None, ""):
        v = str(v)[:10]
    return FC._cmp(v, op, x, typ)


def _calc(r, cdef):
    a = r.get(cdef.get("a"))
    op = cdef.get("op")
    if op == "days":
        da, db = _d(a), _d(r.get(cdef.get("b")))
        return (db - da).days if da and db else None
    b = r.get(cdef["b"]) if cdef.get("b") else cdef.get("num")
    fa, fb = _f(a), _f(b)
    if fa is None or fb is None:
        return None
    if op == "add":
        return r2(fa + fb)
    if op == "sub":
        return r2(fa - fb)
    if op == "mul":
        return r2(fa * fb)
    if op in ("div", "pct"):
        if abs(fb) < 1e-12:
            return None
        return r2(fa / fb * (100.0 if op == "pct" else 1.0))
    return None


def _ds_meta(c, u, key, ds):
    """All columns the person may pick for this source: its own, the time parts of each date and nothing else."""
    cols = list(ds["cols"])
    dates = [x for x in cols if x["type"] == "date"]
    time_cols = []
    for x in dates:
        for p, lab, typ in TIME_PARTS:
            time_cols.append({"k": "%s__%s" % (x["k"], p), "label": "%s: %s" % (x["label"], lab), "type": typ, "time": True, "of": x["k"]})
    return cols, dates, time_cols


def prepare(c, u, d):
    """Rows of a definition with time parts and calculated columns added, after the period but before the filters."""
    key = d.get("dataset")
    if key not in FC.DATASETS:
        raise ApiError("Choose what the report is about.")
    if not dataset_ok(c, u, key):
        raise ApiError("Your role cannot see %s." % FC.DATASETS[key]["label"].lower())
    ds = FC.DATASETS[key]
    if ds.get("company") and not FC.all_projects(c, u):
        raise ApiError("PROJECT_DENIED: %s is company-wide and needs access to every project." % ds["label"])
    frm, to = period_dates(d)
    base_cols, dates, time_cols = _ds_meta(c, u, key, ds)
    date_keys = [x["k"] for x in dates]
    df = d.get("date_field") if d.get("date_field") in date_keys else ds.get("date")
    own_sql = key in ("dpr", "ledger") or ds.get("sql_date")
    f = {"from": frm, "to": to, "project_ids": d.get("project_ids") or [], "attachments": bool(d.get("attachments"))}
    if own_sql and df != ds.get("date"):
        f["from"] = f["to"] = None          # read every date, then keep the chosen date's period below
    rows = ds["rows"](c, u, f)
    cols = list(base_cols)
    if ds.get("dynamic"):
        seen = []
        for r in rows:
            for k in r:
                if k.startswith(ds["dynamic"]) and k not in seen:
                    seen.append(k)
        cols += [C(k, "Field: " + k[len(ds["dynamic"]):]) for k in seen]
    if not f["attachments"]:
        cols = [x for x in cols if x["k"] != "attachments"]
    cols += time_cols
    cmap = {x["k"]: x for x in cols}
    # the period on the chosen date (rows a source did not already limit itself)
    if df and (frm or to) and (not own_sql or df != ds.get("date")):
        rows = [r for r in rows if r.get(df) and (not frm or str(r[df])[:10] >= frm) and (not to or str(r[df])[:10] <= to)]
    # time parts that are used
    used = set(d.get("columns") or []) | set(d.get("group_by") or []) | {x.get("field") for x in d.get("filters") or []} | \
        {x.get("field") for x in d.get("sort") or []} | set((d.get("summaries") or {}).keys()) | \
        {x.get(k) for x in d.get("calc") or [] for k in ("a", "b")}
    for k in used:
        if k and "__" in str(k) and k in cmap and cmap[k].get("time"):
            src, p = k.rsplit("__", 1)
            for r in rows:
                r[k] = part(r.get(src), p)
    # calculated columns
    for i, cd in enumerate(d.get("calc") or []):
        ck = cd.get("k") or "calc_%d" % (i + 1)
        if not re.match(r"^calc_[0-9a-z_]{1,20}$", ck):
            raise ApiError("A calculated column has a wrong name.")
        if cd.get("op") not in CALC_OPS or cd.get("a") not in cmap or (cd.get("b") and cd["b"] not in cmap) or \
                (not cd.get("b") and cd.get("op") != "days" and _f(cd.get("num")) is None) or (cd.get("op") == "days" and not cd.get("b")):
            raise ApiError("Calculated column '%s' needs two columns, or a column and a number." % (cd.get("label") or ck))
        ta = cmap[cd["a"]]["type"]
        tb = cmap[cd["b"]]["type"] if cd.get("b") else "number"
        typ = "number" if cd["op"] in ("pct", "days") else ("money" if "money" in (ta, tb) and cd["op"] != "div" else "number")
        cmap[ck] = {"k": ck, "label": (cd.get("label") or "Calculated %d" % (i + 1))[:60], "type": typ, "calc": True}
        cols.append(cmap[ck])
        for r in rows:
            r[ck] = _calc(r, dict(cd, k=ck))
    return ds, key, rows, cols, cmap, frm, to, df, f


def _fmt_date(v, style):
    if v in (None, "") or style == "ad":
        return v
    b = bs_of(v)
    if not b:
        return v
    t = "%d-%02d-%02d" % b
    return t if style == "bs" else "%s (%s)" % (str(v)[:10], t)


def run_report(c, u, d, limit=5000):
    ds, key, rows, cols, cmap, frm, to, df, f = prepare(c, u, d)
    for flt in d.get("filters") or []:
        k, op = flt.get("field"), flt.get("op") or "eq"
        if k not in cmap or op not in OPS:
            raise ApiError("Unknown filter %s %s." % (k, op))
        rows = [r for r in rows if _cmp(r.get(k), op, flt.get("value"), flt.get("value2"), cmap[k]["type"])]
    sel = [k for k in (d.get("columns") or []) if k in cmap] or [x["k"] for x in ds["cols"][:8]]
    for srt in reversed(d.get("sort") or []):
        k = srt.get("field")
        if k in cmap:
            num = cmap[k]["type"] in ("number", "money")
            rows.sort(key=lambda r: ((r.get(k) is None), (_f(r.get(k)) or 0) if num else str(r.get(k) or "").lower()),
                      reverse=srt.get("dir") == "desc")
    top = d.get("top")
    try:
        top = int(top) if top not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        top = None
    if top and top > 0:
        rows = rows[:top]
    groups = [g for g in (d.get("group_by") or []) if g in cmap][:3]
    if groups:
        rows.sort(key=lambda r: tuple(str(r.get(g) if r.get(g) is not None else "") for g in groups))
    summ = {k: v for k, v in (d.get("summaries") or {}).items() if k in cmap and v in ("sum", "avg", "min", "max", "count")}
    only = bool(d.get("summary_only")) and bool(groups)
    style = d.get("date_style") if d.get("date_style") in DATE_STYLES else "ad"
    dcols = {k for k in cmap if cmap[k]["type"] == "date"}
    total_rows = len(rows)
    truncated = total_rows > limit and not only

    def fv(k, v):
        return _fmt_date(v, style) if k in dcols else v

    def agg(rs):
        out = {}
        for k, how in summ.items():
            vals = [r.get(k) for r in rs if r.get(k) not in (None, "")]
            if how == "count":
                out[k] = len(vals)
                continue
            nums = [x for x in (_f(v) for v in vals) if x is not None]
            if not nums:
                out[k] = None
            elif how == "sum":
                out[k] = r2(sum(nums))
            elif how == "avg":
                out[k] = r2(sum(nums) / len(nums))
            elif how == "min":
                out[k] = min(nums)
            else:
                out[k] = max(nums)
        return out

    lines = []
    shown = rows if only else rows[:limit]

    def label(g, v):
        return fv(g, v) if v not in (None, "") else "(none)"

    def emit(rs, level, keys):
        if level >= len(groups):
            if not only:
                for r in rs:
                    lines.append({"type": "row", "values": {k: fv(k, r.get(k)) for k in sel}})
            return
        g = groups[level]
        cur, buf = object(), []

        def flush():
            if not buf:
                return
            gv = buf[0].get(g)
            here = dict(keys, **{g: fv(g, gv)})
            if not only:
                lines.append({"type": "group", "level": level, "label": "%s: %s" % (cmap[g]["label"], label(g, gv))})
            emit(buf, level + 1, here)
            if summ or only:
                vals = agg(buf)
                for k2, v2 in (here.items() if only else ()):
                    if k2 in sel and k2 not in summ:
                        vals[k2] = v2
                lines.append({"type": "subtotal", "level": level, "label": ("" if only else "Total ") + str(label(g, gv)),
                              "values": vals, "count": len(buf)})

        for r in rs:
            kv = r.get(g)
            if buf and kv != cur:
                flush()
                buf = []
            cur = kv
            buf.append(r)
        flush()

    emit(shown, 0, {})
    if summ or only:
        lines.append({"type": "total", "label": "Total", "values": agg(rows), "count": total_rows})
    labels = d.get("labels") or {}
    out_cols = []
    for k in sel:
        x = dict(cmap[k])
        if labels.get(k):
            x["label"] = str(labels[k])[:60]
        out_cols.append(x)
    dlab = cmap[df]["label"] if df in cmap else None
    plab = None
    if frm or to:
        plab = "%s to %s" % (_fmt_date(frm, style) or "start", _fmt_date(to, style) or "today")
        if style == "ad" and (frm and bs_of(frm)) and (to and bs_of(to)):
            plab += " (Nepali %s to %s)" % (_fmt_date(frm, "bs"), _fmt_date(to, "bs"))
    projs = ", ".join(val(c, "SELECT code FROM projects WHERE id=?", (int(p),), "") for p in f["project_ids"]) or "All you may see"
    return {"title": d.get("title") or d.get("name") or ds["label"], "dataset": key, "dataset_label": ds["label"],
            "columns": out_cols, "all_columns": cols, "lines": lines, "rows": total_rows, "truncated": truncated,
            "limit": limit, "from": frm, "to": to, "date_field": df, "date_label": dlab, "period_label": plab,
            "orientation": d.get("orientation") or "portrait", "header": d.get("header") or "", "footer": d.get("footer") or "",
            "summaries": summ, "group_by": groups, "summary_only": only, "date_style": style, "projects": projs,
            "generated": now(), "by": u.get("name")}


# ───────────────────────────── endpoints ─────────────────────────────
KEEP = ("dataset", "period", "from", "to", "project_ids", "columns", "filters", "group_by", "sort", "summaries", "orientation", "header",
        "footer", "title", "attachments", "date_field", "bs_month", "fy", "calc", "labels", "summary_only", "top", "date_style")


def _ws_default(a):
    """In a Project Workspace the engine passes the open project; a report then covers it unless projects were chosen."""
    a = dict(a or {})
    pid = a.get("project_id")
    d = dict(a.get("definition") or {})
    if pid and not d.get("project_ids"):
        d["project_ids"] = [int(pid)]
        a["definition"] = d
    return a


def _wrap(name, factory):
    cur = inv.FUNCS.get(name)
    if not cur or getattr(cur[0], FLAG, False):
        return
    w = factory(cur[0])
    for k in dir(cur[0]):
        if k.startswith("_bco") and getattr(cur[0], k, False):
            setattr(w, k, True)
    setattr(w, FLAG, True)
    w.__name__ = getattr(cur[0], "__name__", name)
    inv.FUNCS[name] = (w, cur[1], cur[2], cur[3])


def _install():
    global _ORIG_DATASET_OK
    if _ORIG_DATASET_OK is None:
        _ORIG_DATASET_OK = FC.dataset_ok
        FC.dataset_ok = dataset_ok

    def meta(orig):
        def run(c, u, a):
            r = orig(c, u, a)
            byk = {x["key"]: x for x in r["datasets"]}
            out = []
            for k, ds in FC.DATASETS.items():
                if k not in byk:
                    continue
                x = byk[k]
                cols, dates, time_cols = _ds_meta(c, u, k, ds)
                x.update(area=ds.get("area") or "finance", dates=[{"k": y["k"], "label": y["label"]} for y in dates], time_cols=time_cols,
                         period=bool(dates or ds.get("period")), default_date=ds.get("date"))
                out.append(x)
            r["datasets"] = out
            t = today()
            b = bs_of(t)
            r.update(areas=AREAS, calc_ops=CALC_OPS, date_styles=DATE_STYLES, version=VERSION,
                     bs={"y": b[0], "m": b[1], "names": SC.BS_MONTHS, "years": sorted(SC.BS), "fy": _fy_of(b)} if b else None,
                     workspace_project=int(a["project_id"]) if a.get("project_id") else None)
            return r
        return run
    _wrap("fcc.report_meta", meta)

    def ws(orig):
        def run(c, u, a):
            return orig(c, u, _ws_default(a))
        return run
    _wrap("fcc.report_run", ws)
    inv.FUNCS["fcc.report_xlsx"] = (report_xlsx, None, None, False)
    setattr(report_xlsx, FLAG, True)
    inv.FUNCS["fcc.report_save"] = (report_save, None, None, False)
    setattr(report_save, FLAG, True)


def report_save(c, u, a):
    FC.need(c, u, "reports", "create", "save reports")
    d = a.get("definition") or {}
    name = (a.get("name") or d.get("title") or "").strip()
    if not name:
        raise ApiError("Give the report a name.")
    if d.get("dataset") not in FC.DATASETS or not dataset_ok(c, u, d["dataset"]):
        raise ApiError("Choose what the report is about.")
    run_report(c, u, d, 1)          # refuses a definition this person could not run
    shared = 1 if a.get("shared") else 0
    if shared and not FC.right(c, u, "reports", "approve"):
        raise ApiError("Your role cannot share reports with everyone (needs 'approve' on reports).")
    clean = {k: d.get(k) for k in KEEP if k in d}
    rid = FC._int(a.get("id"))
    if rid:
        r = dict(get(c, "fcc_reports", rid, "Report"))
        if r["builtin"]:
            raise ApiError("A built-in template cannot be changed; save it under a new name.")
        if not (r["owner_id"] == u.get("id") or (r["shared"] and FC.right(c, u, "reports", "approve")) or u.get("role") == "admin"):
            raise ApiError("Only the person who made this report can change it.")
        upd(c, "fcc_reports", rid, {"name": name[:120], "dataset": d["dataset"], "definition": json.dumps(clean), "shared": shared,
                                    "updated_at": now()})
        audit(c, u, "edit", "fcc_reports", rid, {"was": r["definition"], "now": clean})
    else:
        rid = ins(c, "fcc_reports", {"name": name[:120], "dataset": d["dataset"], "definition": json.dumps(clean), "owner_id": u.get("id"),
                                     "shared": shared, "builtin": 0, "active": 1, "created_at": now(), "updated_at": now()})
        audit(c, u, "create", "fcc_reports", rid, clean)
    return {"id": rid}


def _definition(c, u, a):
    a = _ws_default(a)
    d = a.get("definition") or {}
    if a.get("id"):
        r = dict(get(c, "fcc_reports", int(a["id"]), "Report"))
        if not FC._report_visible(c, u, r):
            raise ApiError("You cannot open this report.")
        d = dict(json.loads(r["definition"]), **{k: v for k, v in d.items() if v not in (None, "", [])})
        d.setdefault("name", r["name"])
    return d


def _flat(res, blank=None):
    """Header and lines of a result as plain rows (Excel, CSV). Group and total labels go in the first column; in a
    summary-only report the group's own value stays there when the first column is the group."""
    cols = res["columns"]
    out = []
    for ln in res["lines"]:
        if ln["type"] == "row":
            out.append([ln["values"].get(x["k"]) for x in cols])
        elif ln["type"] == "group":
            out.append([("  " * ln["level"]) + ln["label"]] + [blank] * (len(cols) - 1))
        else:
            row = [ln["values"].get(x["k"], blank) for x in cols]
            if not res["summary_only"] or row[0] in (None, "") or ln["type"] == "total":
                row[0] = ln["label"] + (" (%d)" % ln["count"] if ln.get("count") is not None else "")
            out.append(row)
    return out


def _fname(res, ext):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", res["title"])[:80] + ext


def report_xlsx(c, u, a):
    FC.need(c, u, "reports", "export", "export reports")
    res = run_report(c, u, _definition(c, u, a), 50000)
    import api_copilot as CP
    title = res["title"] + (" " + res["period_label"] if res.get("period_label") else "")
    data = CP.make_xlsx(title[:120], [x["label"] for x in res["columns"]], _flat(res))
    audit(c, u, "export", "fcc_report", a.get("id"), {"dataset": res["dataset"], "rows": res["rows"]})
    return {"filename": _fname(res, ".xlsx"), "b64": base64.b64encode(data).decode("ascii"), "rows": res["rows"]}


@api("rg.values")
def rg_values(c, u, a):
    """The values a column takes in this report's data (for the filter pick-list), at most 300."""
    FC.need(c, u, "reports", "view", "run reports")
    d = _definition(c, u, a)
    k = a.get("field")
    _ds, _key, rows, _cols, cmap, *_ = prepare(c, u, dict(d, columns=[k], filters=[]))
    if k not in cmap:
        raise ApiError("Unknown column.")
    seen = {}
    for r in rows:
        v = r.get(k)
        if v not in (None, ""):
            seen[str(v)] = seen.get(str(v), 0) + 1
    vals = sorted(seen, key=lambda s: (_f(s) is None, _f(s) or 0, s.lower()))
    return {"field": k, "values": vals[:300], "more": len(vals) > 300}


@api("rg.csv")
def rg_csv(c, u, a):
    FC.need(c, u, "reports", "export", "export reports")
    res = run_report(c, u, _definition(c, u, a), 50000)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([x["label"] for x in res["columns"]])
    w.writerows(_flat(res, ""))
    audit(c, u, "export", "fcc_report", a.get("id"), {"dataset": res["dataset"], "rows": res["rows"], "as": "csv"})
    data = ("\ufeff" + buf.getvalue()).encode("utf-8")
    return {"filename": _fname(res, ".csv"), "b64": base64.b64encode(data).decode("ascii"), "rows": res["rows"]}


# ───────────────────────────── ready-made templates ─────────────────────────────
BUILTIN = [
    ("rg_stock_card", "Stock movements by material", {"dataset": "stock_moves", "period": "this_bs_month",
     "columns": ["date", "store", "material", "unit", "doc_type", "doc_no", "qty_in", "qty_out", "rate", "net_value"], "group_by": ["material"],
     "summaries": {"qty_in": "sum", "qty_out": "sum", "net_value": "sum"}, "orientation": "landscape"}),
    ("rg_stock_onhand", "Stock on hand and reorder", {"dataset": "stock_onhand", "period": "all",
     "columns": ["project", "store", "material_code", "material", "unit", "qty", "avg_rate", "value", "reorder_level", "below_reorder"],
     "group_by": ["store"], "summaries": {"value": "sum"}}),
    ("rg_issue_boq", "Material used by BOQ item", {"dataset": "issue_lines", "period": "this_bs_month",
     "columns": ["boq", "material", "unit", "net_qty", "amount"], "group_by": ["boq", "material"], "summary_only": True,
     "summaries": {"net_qty": "sum", "amount": "sum"}}),
    ("rg_grn_supplier", "Goods received by supplier", {"dataset": "grn_lines", "period": "this_bs_month",
     "columns": ["date", "grn", "po", "material", "unit", "accepted_qty", "rate", "amount"], "group_by": ["supplier"],
     "summaries": {"amount": "sum"}, "orientation": "landscape"}),
    ("rg_po_open", "Purchase orders still to come", {"dataset": "po_lines", "period": "all",
     "columns": ["po", "date", "delivery_date", "supplier", "description", "qty", "received_qty", "open_qty", "open_value"],
     "filters": [{"field": "open_qty", "op": "gt", "value": "0"}], "group_by": ["supplier"], "summaries": {"open_value": "sum"},
     "sort": [{"field": "delivery_date", "dir": "asc"}], "orientation": "landscape"}),
    ("rg_machine_month", "Machine hours by month", {"dataset": "machine_days", "period": "this_fy",
     "columns": ["machine", "date__bsmonth", "hours", "idle_hours", "breakdown_hours", "fuel_qty"],
     "group_by": ["machine", "date__bsmonth"], "summary_only": True,
     "summaries": {"hours": "sum", "idle_hours": "sum", "breakdown_hours": "sum", "fuel_qty": "sum"}, "orientation": "landscape"}),
    ("rg_labour_trade", "DPR labour by trade", {"dataset": "dpr_labour", "period": "this_bs_month",
     "columns": ["trade", "workers", "man_hours", "amount"], "group_by": ["trade"], "summary_only": True,
     "summaries": {"workers": "sum", "man_hours": "sum", "amount": "sum"}}),
    ("rg_boq_progress", "BOQ progress and billing", {"dataset": "boq_progress", "period": "all",
     "columns": ["project", "code", "description", "unit", "current_qty", "executed_qty", "executed_pct", "billed_qty", "done_not_billed_qty",
                 "executed_value", "billed_value"], "group_by": ["project"], "summaries": {"executed_value": "sum", "billed_value": "sum"},
     "orientation": "landscape"}),
    ("rg_payments_party", "Payments and receipts by party", {"dataset": "payments", "period": "this_fy",
     "columns": ["date", "no", "kind", "bank", "gross", "tds", "net"], "group_by": ["party"],
     "summaries": {"gross": "sum", "tds": "sum", "net": "sum"}}),
    ("rg_bills_due", "Bills by due date", {"dataset": "bills", "period": "all",
     "columns": ["due_date", "no", "kind", "party", "project", "total", "payable"], "group_by": ["kind", "due_date__bsmonth"],
     "summaries": {"total": "sum", "payable": "sum"}, "sort": [{"field": "due_date", "dir": "asc"}], "date_field": "due_date"}),
]


def _seed_reports(c):
    if not _has(c, "fcc_reports"):
        return
    for code, name, d in BUILTIN:
        if q1(c, "SELECT id FROM fcc_reports WHERE code=? AND builtin=1", (code,)):
            continue
        ins(c, "fcc_reports", {"name": name, "dataset": d["dataset"], "definition": json.dumps(d), "owner_id": None, "shared": 1,
                               "builtin": 1, "code": code, "active": 1, "created_at": now(), "updated_at": now()})
