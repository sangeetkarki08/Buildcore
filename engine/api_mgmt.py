"""
Accounts, project KPIs and finance on the combined execution model (BuildCore 2.23).

2.19 split one supplier bill between project and trading use; 2.21 added the ways of working (direct labour,
labour-supply / item-rate / back-to-back subcontracts, own and rented equipment), the accounts posting queue,
delays by responsibility and ROA / ROE. This module makes the READING side follow that model, without
changing any posting, account, balance or document:

  1. Ledger tags. Every ledger line gets a "way of working" tag (direct labour, labour supply subcontract,
     item-rate subcontract, back-to-back, our material, own equipment, rented equipment, overheads, trading)
     and a segment (projects, trading, company). Tags live in their own table beside the ledger (mg_tags),
     are worked out from the source document (subcontract bill, hire bill, DPR, store issue, machine ...),
     and can be corrected by accounts line by line. Lines posted before 2.23 stay untagged until accounts
     approves a back-fill (preview first; it can be undone).
  2. Project KPIs count the entries waiting for accounts (2.21 queue) as cost, clearly separated from the
     posted cost; commitments include the unbilled balance of subcontract work orders; trading and company
     cost centres no longer appear as projects on dashboards, the portfolio, the action centre or the radar.
  3. Project cost and exposure: cost by way of working (actual against the execution plan), exposure
     (material with subcontractors, advances, retention, rental deductions not yet recovered), delay money by
     responsibility, capital tied up in the project and its return.
  4. Finance by segment: profit, waiting entries, working capital, assets employed and return for projects,
     trading and company; ROE for the company; trading gross margin and stock turn.
  5. Stock by segment: project stores, trading store, central store and material with subcontractors.
  6. Own equipment recovery: what each owned machine cost (economic view) against what it charged projects,
     and an optional costing switch (off by default) that shows project cost with own machines at their
     rate per hour instead of the running costs that happened to be booked to the project.
"""
from datetime import date

import core
from core import ApiError, EPS, audit, get, need, q, q1, r2, setting, today, val
import api_inventory as inv
from api_inventory import api

VERSION = "2.23.0"
POSTED = "v.status IN ('posted','reversed')"
WAITING = ("(v.status='submitted' AND EXISTS (SELECT 1 FROM post_queue pq WHERE pq.voucher_id=v.id AND "
           "COALESCE(pq.stage,'') NOT IN ('withdrawn','posted')))")

SCHEMA = """
CREATE TABLE IF NOT EXISTS mg_tags(line_id INTEGER PRIMARY KEY, voucher_id INTEGER, mode TEXT, segment TEXT,
  how TEXT DEFAULT 'auto', user_id INTEGER, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_mgt_v ON mg_tags(voucher_id);
CREATE INDEX IF NOT EXISTS ix_mgt_m ON mg_tags(mode);
"""

MODES = [("direct_labour", "Direct labour (own workers)"), ("labour_sc", "Labour supply subcontract"),
         ("supplied_sc", "Item-rate subcontract, our material"), ("b2b_sc", "Back-to-back subcontract"),
         ("sc_other", "Subcontract (type not recorded)"), ("material", "Our material"),
         ("own_eq", "Own equipment"), ("rented_eq", "Rented equipment"), ("overhead", "Site and other overheads"),
         ("trading", "Trading cost of sales")]
MODE_KEYS = [m[0] for m in MODES]
SEGMENTS = [("project", "Projects"), ("trading", "Trading"), ("company", "Company")]
SC_TYPE_MODE = {"labour": "labour_sc", "supplied": "supplied_sc", "b2b": "b2b_sc"}
OWN_EQ_ROLES = ("equipment_cost", "fuel_cost", "repair_cost", "equip_job_cost")
MATERIAL_ROLES = ("material_cost", "price_variance", "inventory_loss", "inv_writedown_exp")
RECOVERY_ROLES = ("equipment_recovery", "equip_recovery")
# roles that are cost or contra-cost in a project's cost (as the 2.16 earned-value engine reads it)
COST_SQL = "(x.type='expense' OR x.role='equipment_recovery')"


def init_mgmt(c):
    c.executescript(SCHEMA)
    if setting(c, "mg_tag_from") in (None, ""):
        mx = val(c, "SELECT MAX(id) FROM voucher_lines") or 0
        _set(c, "mg_tag_from", int(mx))
        _set(c, "mg_tag_scanned", int(mx))
    for k, v in (("mg_kpi_waiting", "1"), ("mg_eq_costing", "actual")):
        if setting(c, k) in (None, ""):
            _set(c, k, v)
    _install()
    try:
        import api_workspace as W
        W.COMPANY_FNS.update({"mg.segments", "mg.stores", "mg.eqpool", "mg.backfill_preview", "mg.backfill_apply",
                              "mg.backfill_undo", "mg.settings_save"})
    except Exception:
        pass


def _set(c, k, v):
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", (k, str(v)))


def _f(v, d=0.0):
    try:
        return float(v) if v not in (None, "") else d
    except (TypeError, ValueError):
        return d


# ───────────────────────────── segments ─────────────────────────────
def _kinds(c):
    return {r["id"]: (r["kind"] or "project") for r in q(c, "SELECT id, COALESCE(kind,'') kind FROM projects")}


def seg_of(kinds, pid):
    if not pid:
        return "company"
    k = kinds.get(int(pid), "project")
    if k in ("", "project"):
        return "project"
    return "trading" if k == "trading" else "company"


def non_project_ids(c):
    return {r["id"] for r in q(c, "SELECT id FROM projects WHERE COALESCE(kind,'') NOT IN ('','project')")}


SEG_SQL = ("CASE WHEN COALESCE(l.project_id, v.project_id) IS NULL THEN 'company' "
           "WHEN COALESCE(pk.kind,'') IN ('','project') THEN 'project' WHEN pk.kind='trading' THEN 'trading' "
           "ELSE 'company' END")
SEG_JOIN = " LEFT JOIN projects pk ON pk.id=COALESCE(l.project_id, v.project_id) "


# ───────────────────────────── ledger tags ─────────────────────────────
class _Ctx:
    def __init__(self, c):
        self.c = c
        self.kinds = _kinds(c)
        self.eq = {r["id"]: (r["ownership"] or "owned") for r in q(c, "SELECT id, ownership FROM equipment")}
        self.inv = {}

    def invoice(self, iid):
        if iid not in self.inv:
            i = q1(self.c, "SELECT id, source FROM invoices WHERE id=?", (iid,)) if iid else None
            mode = None
            if i and i["source"] == "sc_bill":
                o = q1(self.c, "SELECT o.type FROM sc_bills b JOIN sc_orders o ON o.id=b.order_id WHERE b.invoice_id=? "
                               "ORDER BY b.id DESC LIMIT 1", (iid,)) if _has(self.c, "sc_bills") else None
                mode = SC_TYPE_MODE.get((o or {}).get("type"), "sc_other")
            self.inv[iid] = (i["source"] if i else None, mode)
        return self.inv[iid]


def classify(ctx, ln):
    """The way of working of one ledger line, from its account and source document. None = not a cost line."""
    role, typ = ln["role"] or "", ln["type"]
    seg = seg_of(ctx.kinds, ln["project_id"] or ln["vproject"])
    if typ not in ("expense", "income") and role != "subcon_material":
        return None, seg
    if role == "cogs_trading" or (seg == "trading" and typ == "expense"):
        return "trading", seg
    if role in RECOVERY_ROLES:
        return "own_eq", seg
    if typ == "income":
        return None, seg
    src = ln["source"] or ""
    isrc, scmode = ctx.invoice(ln["source_id"]) if src == "invoice" else (None, None)
    if scmode:
        return scmode, seg
    if src == "sc_issue" or role in ("subcon_material", "subcon_recovery_margin"):
        return "supplied_sc", seg
    if isrc == "hire":
        return "rented_eq", seg
    if ln["equipment_id"]:
        return ("own_eq" if ctx.eq.get(ln["equipment_id"], "owned") == "owned" else "rented_eq"), seg
    if role == "hire_cost":
        return "rented_eq", seg
    if role in OWN_EQ_ROLES:
        return "own_eq", seg
    if role == "labour_cost":
        return "direct_labour", seg
    if role in MATERIAL_ROLES:
        return "material", seg
    if role == "subcon_cost":
        return "sc_other", seg
    return "overhead", seg


LINE_SQL = ("SELECT l.id, l.voucher_id, l.project_id, l.equipment_id, v.project_id vproject, v.source, v.source_id, "
            "x.role, x.type FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON x.id=l.account_id ")


def sync_tags(c):
    """Tag every ledger line written since 2.23 was installed (and since the last call)."""
    start = int(_f(setting(c, "mg_tag_scanned"), 0))
    rows = q(c, LINE_SQL + "WHERE l.id>? ORDER BY l.id LIMIT 50000", (start,))
    if not rows:
        return 0
    ctx = _Ctx(c)
    t = core.now()
    for ln in rows:
        mode, seg = classify(ctx, ln)
        c.execute("INSERT OR IGNORE INTO mg_tags(line_id, voucher_id, mode, segment, how, ts) VALUES(?,?,?,?,?,?)",
                  (ln["id"], ln["voucher_id"], mode, seg, "auto", t))
    _set(c, "mg_tag_scanned", rows[-1]["id"])
    return len(rows)


def _has(c, table):
    return bool(val(c, "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table,)))


def _period(c, a):
    to = a.get("to") or a.get("as_of") or today()
    frm = a.get("from") or _fy_bounds(c, to)[0]
    return frm, to


def _fy_guess(d):
    y = int(d[:4]) - (1 if d[5:] < "07-16" else 0)
    return "%d-07-16" % y


def _fy_bounds(c, d):
    try:
        import api_exec as X
        return X._fy_bounds(c, d)
    except Exception:
        return _fy_guess(d), None, None


def _status_sql(include_waiting):
    return "(" + POSTED + (" OR " + WAITING if include_waiting else "") + ")"


@api("mg.meta")
def mg_meta(c, u, a):
    sync_tags(c)
    frm = int(_f(setting(c, "mg_tag_from"), 0))
    legacy = val(c, "SELECT COUNT(*) FROM voucher_lines l JOIN accounts x ON x.id=l.account_id WHERE l.id<=? AND "
                    "(x.type='expense' OR x.role='equipment_recovery') AND NOT EXISTS "
                    "(SELECT 1 FROM mg_tags t WHERE t.line_id=l.id)", (frm,))
    backfilled = val(c, "SELECT COUNT(*) FROM mg_tags WHERE how='backfill'")
    rights = {m: sorted(a_ for a_ in ("view", "edit", "approve") if core.can(u, m, a_))
              for m in ("accounts", "project", "commercial", "inventory", "equipment")}
    return {"version": VERSION, "modes": MODES, "segments": SEGMENTS, "legacy_untagged": legacy,
            "backfilled": backfilled, "kpi_waiting": setting(c, "mg_kpi_waiting") != "0",
            "eq_costing": setting(c, "mg_eq_costing") or "actual", "rights": rights,
            "fy_from": _fy_bounds(c, today())[0]}


@api("mg.settings_save", "accounts", "approve")
def mg_settings_save(c, u, a):
    if "kpi_waiting" in a:
        _set(c, "mg_kpi_waiting", "1" if a["kpi_waiting"] in (True, 1, "1", "true") else "0")
    if "eq_costing" in a:
        if a["eq_costing"] not in ("actual", "rate"):
            raise ApiError("Own equipment costing is 'actual' or 'rate'.")
        _set(c, "mg_eq_costing", a["eq_costing"])
    audit(c, u, "settings", "mg", 0, {k: a.get(k) for k in ("kpi_waiting", "eq_costing") if k in a})
    return mg_meta(c, u, {})


# ───────────────────────────── costs by way of working ─────────────────────────────
def _allowed(c, u):
    """Projects a project-restricted user may see (None = all), as the 2.20 workspace engine decides."""
    try:
        import api_workspace as W
        return W.allowed_projects(c, u) if u else None
    except Exception:
        return None


def _cost_rows(c, frm, to, project_id=None, segment=None, include_waiting=True, mode=None, account_id=None, allow=None):
    """Cost lines (expense, and the internal equipment recovery as a contra) with their tags."""
    sync_tags(c)
    cond = [COST_SQL, "v.date BETWEEN ? AND ?", _status_sql(include_waiting)]
    p = [frm, to]
    if allow is not None and not project_id:
        cond.append("COALESCE(l.project_id, v.project_id) IN (%s)" % (",".join(str(int(x)) for x in allow) or "NULL"))
    if project_id:
        cond.append("COALESCE(l.project_id, v.project_id)=?")
        p.append(int(project_id))
    if segment:
        cond.append(SEG_SQL + "=?")
        p.append(segment)
    if mode:
        if mode == "untagged":
            cond.append("t.mode IS NULL")
        else:
            cond.append("t.mode=?")
            p.append(mode)
    if account_id:
        cond.append("l.account_id=?")
        p.append(int(account_id))
    return q(c, "SELECT l.id, l.voucher_id, l.account_id, l.debit, l.credit, l.narration, l.project_id, l.boq_item_id, "
                "l.equipment_id, v.no, v.date, v.status, v.source, v.source_id, v.narration vnar, x.code acode, x.name aname, "
                "x.role, COALESCE(l.project_id, v.project_id) pid, t.mode, t.how, " + SEG_SQL + " seg "
                "FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON x.id=l.account_id"
                + SEG_JOIN + "LEFT JOIN mg_tags t ON t.line_id=l.id WHERE " + " AND ".join(cond)
                + " ORDER BY v.date, v.id, l.id", p)


@api("mg.modes", "accounts", "view")
def mg_modes(c, u, a):
    """Expense accounts x way of working (and projects x way of working), posted and waiting for accounts."""
    frm, to = _period(c, a)
    wait = a.get("include_waiting", True) not in (False, 0, "0", "false")
    rows = _cost_rows(c, frm, to, a.get("project_id"), a.get("segment") or None, wait, allow=_allowed(c, u))
    accs, projs, tot, waiting = {}, {}, {}, {}
    for r in rows:
        m = r["mode"] or "untagged"
        amt = (r["debit"] or 0) - (r["credit"] or 0)
        ac = accs.setdefault(r["account_id"], {"account_id": r["account_id"], "code": r["acode"], "name": r["aname"],
                                                "by": {}, "total": 0.0})
        ac["by"][m] = ac["by"].get(m, 0) + amt
        ac["total"] += amt
        tot[m] = tot.get(m, 0) + amt
        if r["status"] == "submitted":
            waiting[m] = waiting.get(m, 0) + amt
        k = r["pid"] or 0
        pr = projs.setdefault(k, {"project_id": r["pid"], "segment": r["seg"], "by": {}, "total": 0.0})
        pr["by"][m] = pr["by"].get(m, 0) + amt
        pr["total"] += amt
    rd = lambda d: {k: r2(v) for k, v in d.items() if abs(v) > 0.004}  # noqa: E731
    out_accs = []
    for ac in sorted(accs.values(), key=lambda x: x["code"] or ""):
        ac["by"], ac["total"] = rd(ac["by"]), r2(ac["total"])
        if ac["by"]:
            out_accs.append(ac)
    codes = {r["id"]: (r["code"], r["name"]) for r in q(c, "SELECT id, code, name FROM projects")}
    out_p = []
    for pr in projs.values():
        pr["by"], pr["total"] = rd(pr["by"]), r2(pr["total"])
        cn = codes.get(pr["project_id"], ("—", "No project (company)"))
        pr["code"], pr["name"] = cn
        if pr["by"]:
            out_p.append(pr)
    out_p.sort(key=lambda x: (x["segment"], x["code"] or ""))
    used = [m for m in MODE_KEYS + ["untagged"] if m in tot and abs(tot[m]) > 0.004]
    return {"from": frm, "to": to, "include_waiting": wait, "modes": MODES + [("untagged", "Not tagged (before 2.23)")],
            "cols": used, "accounts": out_accs, "projects": out_p, "totals": rd(tot), "waiting": rd(waiting),
            "total": r2(sum(tot.values()))}


@api("mg.lines", "accounts", "view")
def mg_lines(c, u, a):
    frm, to = _period(c, a)
    wait = a.get("include_waiting", True) not in (False, 0, "0", "false")
    rows = _cost_rows(c, frm, to, a.get("project_id"), a.get("segment") or None, wait, a.get("mode") or None,
                      a.get("account_id"), allow=_allowed(c, u))
    lim = int(_f(a.get("limit"), 2000))
    codes = {r["id"]: r["code"] for r in q(c, "SELECT id, code FROM projects")}
    for r in rows:
        r["amount"] = r2((r["debit"] or 0) - (r["credit"] or 0))
        r["pcode"] = codes.get(r["pid"]) if r["pid"] else None
        r["waiting"] = r["status"] == "submitted"
    return {"rows": rows[:lim], "count": len(rows), "total": r2(sum(r["amount"] for r in rows))}


@api("mg.retag", "accounts", "edit")
def mg_retag(c, u, a):
    """Accounts corrects the way of working of ledger lines. The amount and account never change."""
    ids = [int(x) for x in (a.get("line_ids") or []) if str(x).strip()]
    mode = a.get("mode") or None
    if not ids:
        raise ApiError("Choose the lines to tag.")
    if mode not in MODE_KEYS and mode is not None:
        raise ApiError("Unknown way of working: %s" % mode)
    sync_tags(c)
    ctx = _Ctx(c)
    t = core.now()
    n = 0
    for lid in ids:
        ln = q1(c, LINE_SQL + "WHERE l.id=?", (lid,))
        if not ln:
            continue
        seg = seg_of(ctx.kinds, ln["project_id"] or ln["vproject"])
        c.execute("INSERT OR REPLACE INTO mg_tags(line_id, voucher_id, mode, segment, how, user_id, ts) VALUES(?,?,?,?,?,?,?)",
                  (lid, ln["voucher_id"], mode, seg, "manual", u["id"] if u else None, t))
        n += 1
    audit(c, u, "retag", "mg_tags", 0, {"lines": ids[:50], "mode": mode})
    return {"tagged": n}


# ── back-fill of lines posted before 2.23 ──
def _legacy(c):
    frm = int(_f(setting(c, "mg_tag_from"), 0))
    return q(c, LINE_SQL + "WHERE l.id<=? AND NOT EXISTS (SELECT 1 FROM mg_tags t WHERE t.line_id=l.id) ORDER BY l.id", (frm,))


@api("mg.backfill_preview", "accounts", "view")
def mg_backfill_preview(c, u, a):
    ctx = _Ctx(c)
    by = {}
    n = 0
    for ln in _legacy(c):
        mode, _seg = classify(ctx, ln)
        n += 1
        if not mode or not (ln["type"] == "expense" or ln["role"] in RECOVERY_ROLES):
            continue  # count cost lines only (a recoverable asset or income line is tagged but is not cost)
        amt = val(c, "SELECT debit-credit FROM voucher_lines WHERE id=?", (ln["id"],))
        b = by.setdefault(mode, {"mode": mode, "lines": 0, "amount": 0.0})
        b["lines"] += 1
        b["amount"] += amt or 0
    rows = [dict(b, amount=r2(b["amount"]), label=dict(MODES)[b["mode"]]) for b in by.values()]
    rows.sort(key=lambda x: MODE_KEYS.index(x["mode"]))
    return {"lines": n, "rows": rows, "backfilled": val(c, "SELECT COUNT(*) FROM mg_tags WHERE how='backfill'")}


@api("mg.backfill_apply", "accounts", "approve")
def mg_backfill_apply(c, u, a):
    ctx = _Ctx(c)
    t = core.now()
    n = 0
    for ln in _legacy(c):
        mode, seg = classify(ctx, ln)
        c.execute("INSERT OR IGNORE INTO mg_tags(line_id, voucher_id, mode, segment, how, user_id, ts) VALUES(?,?,?,?,?,?,?)",
                  (ln["id"], ln["voucher_id"], mode, seg, "backfill", u["id"] if u else None, t))
        n += 1
    audit(c, u, "backfill", "mg_tags", 0, {"lines": n})
    return {"tagged": n}


@api("mg.backfill_undo", "accounts", "approve")
def mg_backfill_undo(c, u, a):
    n = val(c, "SELECT COUNT(*) FROM mg_tags WHERE how='backfill'")
    c.execute("DELETE FROM mg_tags WHERE how='backfill'")
    audit(c, u, "backfill_undo", "mg_tags", 0, {"lines": n})
    return {"removed": n}


# ───────────────────────────── waiting entries and commitments ─────────────────────────────
def waiting_cost(c, pid, asof, boq_item_id=None):
    """Cost of a project (or BOQ item) parked in the accounts posting queue: complete, approved by the site
    but not yet posted. Equipment recovery nets off, as in the earned-value engine."""
    if not _has(c, "post_queue"):
        return 0.0
    cond, p = ["v.date<=?", WAITING], [asof]
    if boq_item_id:
        cond.append("l.boq_item_id=?")
        p.append(boq_item_id)
        cond.append("x.type='expense'")
    else:
        cond.append("l.project_id=?")
        p.append(pid)
        cond.append(COST_SQL)
    return r2(val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x "
                     "ON x.id=l.account_id WHERE " + " AND ".join(cond), p))


def sc_committed(c, pid):
    """Approved subcontract work orders: ordered value not yet billed."""
    if not _has(c, "sc_orders"):
        return 0.0
    out = 0.0
    for o in q(c, "SELECT id FROM sc_orders WHERE project_id=? AND status IN ('approved','active','open')", (pid,)):
        ordered = val(c, "SELECT SUM(qty*rate) FROM sc_order_items WHERE order_id=?", (o["id"],))
        billed = val(c, "SELECT SUM(gross) FROM sc_bills WHERE order_id=? AND status NOT IN ('cancelled','draft')", (o["id"],))
        out += max(0.0, (ordered or 0) - (billed or 0))
    return r2(out)


def _own_eq_delta(c, pid, asof, include_waiting):
    """Rate-per-hour costing: the project carries its own machines at their internal rate (the recovery is not
    netted off) and not the running costs of own machines that happened to be booked to it."""
    st = _status_sql(include_waiting)
    rec = val(c, "SELECT SUM(l.credit-l.debit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x "
                 "ON x.id=l.account_id WHERE x.role='equipment_recovery' AND l.project_id=? AND v.date<=? AND " + st, (pid, asof))
    own = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x "
                 "ON x.id=l.account_id JOIN equipment e ON e.id=l.equipment_id WHERE x.type='expense' AND "
                 "COALESCE(x.role,'') NOT IN ('equipment_cost','equip_job_cost') AND COALESCE(e.ownership,'owned')='owned' "
                 "AND l.project_id=? AND v.date<=? AND " + st, (pid, asof))
    return r2((rec or 0) - (own or 0)), r2(rec or 0), r2(own or 0)


# ───────────────────────────── wrappers on the existing engine ─────────────────────────────
_ORIG = {}


def _install():
    import api_project as P
    if not getattr(P.boq_figures, "_bco223", False):
        _ORIG["boq_figures"] = P.boq_figures
        P.boq_figures = boq_figures2
    if not getattr(P.project_evm, "_bco223", False):
        _ORIG["project_evm"] = P.project_evm
        P.project_evm = project_evm2
    if hasattr(P, "action_items") and not getattr(P.action_items, "_bco223", False):
        _ORIG["action_items"] = P.action_items
        P.action_items = action_items2
    try:
        import api_insight as I
        if not getattr(I._project_rows, "_bco223", False):
            _ORIG["insight_rows"] = I._project_rows
            I._project_rows = insight_rows2
    except Exception:
        pass
    _wrap("portfolio", _portfolio_w)
    _wrap("dc.radar", _radar_w)
    _wrap("dc.capacity", _capacity_w)
    _wrap("cash.company", _cash_company_w)
    _wrap("kpi.finance", _kpi_finance_w)
    _wrap("rep.ledger", _ledger_w)


def _wrap(name, factory):
    cur = inv.FUNCS.get(name)
    if not cur or getattr(cur[0], "_bco223", False):
        return
    w = factory(cur[0])
    w._bco223 = True
    for flag in ("_bco219", "_bco220", "_bco221"):
        if getattr(cur[0], flag, False):
            setattr(w, flag, True)
    inv.FUNCS[name] = (w, cur[1], cur[2], cur[3])


def _kpi_on(c):
    return setting(c, "mg_kpi_waiting") != "0"


def boq_figures2(c, b, asof):
    r = _ORIG["boq_figures"](c, b, asof)
    if not _kpi_on(c):
        return r
    w = waiting_cost(c, None, asof, b["id"])
    r["ac_posted"], r["ac_waiting"] = r["ac"], w
    if abs(w) < 0.005:
        return r
    ac = r2(r["ac"] + w)
    ex = r["executed_qty"] or 0
    auc = r2(ac / ex) if ex > EPS else None
    rem = max((r["revised_qty"] or 0) - ex, 0)
    etc = r2(rem * (auc if auc is not None else (r["unit_budget"] or 0)))
    eac = r2(ac + etc)
    r.update({"ac": ac, "actual_unit_cost": auc, "etc": etc, "eac": eac,
              "cv": r2(r["ev"] - ac) if r["ev"] is not None else None,
              "cpi": round(r["ev"] / ac, 2) if r["ev"] is not None and ac > EPS else None,
              "forecast_profit": r2((r["forecast_revenue"] or 0) - eac)})
    return r


boq_figures2._bco223 = True


def project_evm2(c, pid, asof):
    ev = _ORIG["project_evm"](c, pid, asof)
    wait_on = _kpi_on(c)
    w_total = waiting_cost(c, pid, asof) if wait_on else 0.0
    w_boq = r2(sum(r.get("ac_waiting") or 0 for r in ev["rows"])) if wait_on else 0.0
    w_other = r2(w_total - w_boq)
    # the original total comes from the posted ledger; its BOQ rows already carry their own waiting part
    ev["ac_posted"] = r2(ev["ac"])
    ev["waiting"] = w_total
    ev["ac"] = r2(ev["ac"] + w_total)
    ev["ac_unallocated"] = r2(ev["ac_unallocated"] + w_other)
    ev["eac"] = r2(ev["eac"] + w_other)
    eq_mode = setting(c, "mg_eq_costing") or "actual"
    ev["eq_costing"] = eq_mode
    if eq_mode == "rate":
        d, rec, own = _own_eq_delta(c, pid, asof, wait_on)
        ev["own_eq_charged"], ev["own_eq_actual"], ev["own_eq_adjustment"] = rec, own, d
        ev["ac"] = r2(ev["ac"] + d)
        ev["ac_unallocated"] = r2(ev["ac_unallocated"] + d)
        ev["eac"] = r2(ev["eac"] + d)
    ev["etc"] = r2(ev["eac"] - ev["ac"])
    fr, er = ev["forecast_revenue"], ev["earned_revenue"]
    ev["forecast_profit"] = r2(fr - ev["eac"])
    ev["current_margin"] = round(100 * (er - ev["ac"]) / er, 1) if er else None
    ev["forecast_margin"] = round(100 * (fr - ev["eac"]) / fr, 1) if fr else None
    tm = ev.get("tender_margin")
    ev["margin_fade"] = round(tm - ev["forecast_margin"], 1) if tm is not None and ev["forecast_margin"] is not None else None
    ac_boq = r2(sum(r["ac"] for r in ev["rows"]))
    ev["ac_boq"] = ac_boq
    if ev.get("ev") is not None:
        ev["cv"] = r2(ev["ev"] - ac_boq)
        if ac_boq > EPS and ev.get("cpi") is not None:
            ev["cpi"] = round(ev["ev"] / ac_boq, 2)
    po = r2(ev.get("committed") or 0)
    sc = sc_committed(c, pid)
    ev["committed_po"], ev["committed_sc"], ev["committed"] = po, sc, r2(po + sc)
    return ev


project_evm2._bco223 = True


def action_items2(c, u, pid=None):
    items = _ORIG["action_items"](c, u, pid)
    np_ = non_project_ids(c)
    if not np_:
        return items
    return [i for i in items if not (i.get("project_id") in np_ and str(i.get("link") or "").startswith("#/p/dpr"))]


action_items2._bco223 = True


def insight_rows2(c, pid=None):
    rows = _ORIG["insight_rows"](c, pid)
    np_ = non_project_ids(c)
    return [r for r in rows if r.get("id") not in np_]


insight_rows2._bco223 = True


def _portfolio_w(orig):
    def portfolio2(c, u, a):
        np_ = non_project_ids(c)
        return [r for r in orig(c, u, a) if r.get("id") not in np_]
    return portfolio2


def _radar_w(orig):
    def radar2(c, u, a):
        r = orig(c, u, a)
        np_ = non_project_ids(c)
        if np_ and isinstance(r, dict) and isinstance(r.get("rows"), list):
            r["rows"] = [x for x in r["rows"] if x.get("id") not in np_]
            if isinstance(r.get("counts"), dict):
                r["counts"] = {b: sum(1 for x in r["rows"] if x.get("band") == b) for b in r["counts"]}
        return r
    return radar2


def _np_codes(c):
    return {r["code"] for r in q(c, "SELECT code FROM projects WHERE COALESCE(kind,'') NOT IN ('','project')")}


def _capacity_w(orig):
    def capacity2(c, u, a):
        r = orig(c, u, a)
        codes = _np_codes(c)
        if codes and isinstance(r, dict) and isinstance(r.get("commitments"), list):
            r["commitments"] = [x for x in r["commitments"] if x.get("project") not in codes]
        return r
    return capacity2


def _cash_company_w(orig):
    def cash_company2(c, u, a):
        r = orig(c, u, a)
        codes = _np_codes(c)
        if not codes or not isinstance(r, dict):
            return r
        zero = lambda x: all(abs(v or 0) < 0.005 for v in x.get("values") or [])  # noqa: E731
        r["lines"] = [x for x in r.get("lines") or [] if not (zero(x) and any(
            x.get("label") in ("Receipts: " + k, "Payments: " + k) for k in codes))]
        r["projects"] = [x for x in r.get("projects") or [] if x.get("code") not in codes]
        return r
    return cash_company2


def _ledger_w(orig):
    def rep_ledger2(c, u, a):
        r = orig(c, u, a)
        if not isinstance(r, dict) or not isinstance(r.get("rows"), list):
            return r
        sync_tags(c)
        ids = [x["id"] for x in r["rows"] if x.get("id")]
        tags = {}
        for i in range(0, len(ids), 500):
            ch = ids[i:i + 500]
            for t in q(c, "SELECT line_id, mode, segment FROM mg_tags WHERE line_id IN (%s)" % ",".join("?" * len(ch)), ch):
                tags[t["line_id"]] = t
        lab = dict(MODES)
        for x in r["rows"]:
            t = tags.get(x.get("id")) or {}
            x["work_mode"], x["segment"] = t.get("mode"), t.get("segment")
            x["work_mode_label"] = lab.get(t.get("mode")) if t.get("mode") else None
        want_m, want_s = a.get("work_mode"), a.get("segment")
        if want_m or want_s:
            keep = [x for x in r["rows"] if (not want_m or (x["work_mode"] or "untagged") == want_m)
                    and (not want_s or x["segment"] == want_s)]
            bal = 0.0
            for x in keep:
                bal += (x["debit"] or 0) - (x["credit"] or 0)
                x["balance"] = r2(bal)
            r.update(rows=keep, opening=0.0, closing=r2(bal), filtered=True)
        return r
    return rep_ledger2


# ───────────────────────────── finance KPIs ─────────────────────────────
def _role_bal(c, roles, to, seg=None, pid=None, include_opening=True):
    cond, p = ["x.role IN (%s)" % ",".join("?" * len(roles)), POSTED, "v.date<=?"], list(roles) + [to]
    if pid:
        cond.append("COALESCE(l.project_id, v.project_id)=?")
        p.append(pid)
    if seg:
        cond.append(SEG_SQL + "=?")
        p.append(seg)
    b = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x "
               "ON x.id=l.account_id" + SEG_JOIN + "WHERE " + " AND ".join(cond), p) or 0
    if include_opening and not pid and (seg in (None, "company")):
        b += val(c, "SELECT SUM(opening_balance) FROM accounts WHERE role IN (%s)" % ",".join("?" * len(roles)), list(roles)) or 0
    return r2(b)


def _seg_pl(c, frm, to, seg, include_waiting=False):
    st = _status_sql(include_waiting)
    rows = q(c, "SELECT x.type, x.role, SUM(l.debit-l.credit) amt FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id "
                "JOIN accounts x ON x.id=l.account_id" + SEG_JOIN + "WHERE x.type IN ('income','expense') AND v.date BETWEEN ? AND ? "
                "AND " + st + " AND " + SEG_SQL + "=? GROUP BY x.type, x.role", (frm, to, seg))
    inc = exp = 0.0
    for r in rows:
        if r["type"] == "income" and r["role"] not in RECOVERY_ROLES:
            inc += -(r["amt"] or 0)
        else:  # internal equipment recovery is a contra-cost, as in project cost
            exp += (r["amt"] or 0)
    return r2(inc), r2(exp)


def _waiting_seg(c, to, seg):
    if not _has(c, "post_queue"):
        return 0.0
    return r2(val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x "
                     "ON x.id=l.account_id" + SEG_JOIN + "WHERE " + COST_SQL + " AND v.date<=? AND " + WAITING + " AND "
                     + SEG_SQL + "=?", (to, seg)))


def _kpi_finance_w(orig):
    def kpi_finance2(c, u, a):
        r = orig(c, u, a)
        if not isinstance(r, dict) or not isinstance(r.get("kpis"), list):
            return r
        try:
            to = r.get("as_of") or today()
            frm = r.get("from") or _fy_bounds(c, to)[0]
            k = r["kpis"]
            g = "Combined model (2.23)"

            def add(label, value, unit="NPR", note="", status="info", fmt="money"):
                k.append({"group": g, "label": label, "value": value, "unit": unit, "note": note, "status": status, "fmt": fmt})
            nq = val(c, "SELECT COUNT(*) FROM post_queue pq JOIN vouchers v ON v.id=pq.voucher_id WHERE v.status='submitted' "
                        "AND COALESCE(pq.stage,'') NOT IN ('withdrawn','posted')") if _has(c, "post_queue") else 0
            wt = r2(sum(_waiting_seg(c, to, s) for s, _ in SEGMENTS))
            add("Costs waiting for accounts", wt, note="%d entries approved by site but not yet posted; outside every balance until posted." % nq,
                status="warn" if nq else "good")
            for s, lab in SEGMENTS:
                inc, exp = _seg_pl(c, frm, to, s)
                if abs(inc) > 0.004 or abs(exp) > 0.004:
                    add("Profit: %s (this FY)" % lab.lower(), r2(inc - exp), note="Income %s, cost %s." % (_m(inc), _m(exp)),
                        status="good" if inc - exp >= 0 else "bad")
            loans = -_role_bal(c, ("equipment_loan",), to)
            if abs(loans) > 0.004:
                emi = val(c, "SELECT SUM(emi) FROM eq_finance WHERE COALESCE(loan_amount,0)>0") if _has(c, "eq_finance") else 0
                add("Equipment loans outstanding", loans, note="Monthly EMIs on record %s." % _m(emi or 0))
            mat = _role_bal(c, ("subcon_material",), to)
            if abs(mat) > 0.004:
                add("Material with subcontractors", mat, note="Issued to item-rate subcontractors, to be recovered in their bills.", status="warn")
            try:
                import api_exec as X
                rc = X.ret_company(c, u, {"to": to})["fy"]
                add("Return on assets (FY to date)", rc.get("roa_pct"), "%", "Annualised.", fmt="num")
                add("Return on equity (FY to date)", rc.get("roe_pct"), "%", "Annualised.", fmt="num")
            except Exception:
                pass
        except Exception:
            pass
        return r
    return kpi_finance2


def _m(v):
    return "{:,.0f}".format(v or 0)


# ───────────────────────────── project: capital employed and return ─────────────────────────────
def project_capital(c, pid, asof, ev=None):
    """Money tied up in one project at a date: work done not yet billed, receivables, retention, stock at the
    project's stores, material with subcontractors, advances paid, own machines and small assets at the
    project; less what others finance (payables, client advances, retention held)."""
    if ev is None:
        import api_project as P
        ev = P.project_evm(c, pid, asof)
    billed = -_role_bal(c, ("contract_revenue",), asof, pid=pid)
    wip = r2(max(0.0, (ev.get("earned_revenue") or 0) - billed))
    parts = [("Work done not yet billed", wip),
             ("Receivable from client", _role_bal(c, ("ar_control",), asof, pid=pid)),
             ("Retention receivable", _role_bal(c, ("retention_receivable",), asof, pid=pid)),
             ("Stock at project stores", r2(val(c, "SELECT SUM(value) FROM stock_balances WHERE project_id=?", (pid,)) or 0)),
             ("Material with subcontractors", _role_bal(c, ("subcon_material",), asof, pid=pid)),
             ("Advances to suppliers and subcontractors", _role_bal(c, ("supplier_advance", "subcon_advance"), asof, pid=pid))]
    eq_nbv = 0.0
    try:
        import api_exec as X
        for e in q(c, "SELECT * FROM equipment WHERE project_id=? AND COALESCE(ownership,'owned')='owned' AND COALESCE(active,1)=1", (pid,)):
            eq_nbv += X._nbv(c, e, asof)
    except Exception:
        pass
    parts.append(("Own machines at the project (book value)", r2(eq_nbv)))
    sa = 0.0
    try:
        import api_exec as X
        if _has(c, "sa_pools"):
            rep = {r_["pool_id"]: r_ for r_ in X.sa_report(c, None, {"to": asof})["rows"]}
            for p_ in q(c, "SELECT * FROM sa_pools WHERE COALESCE(active,1)=1"):
                dep = X._deployed(c, p_["id"], asof, pid)
                owned = (p_["qty"] or 0) + (val(c, "SELECT SUM(qty) FROM sa_moves WHERE pool_id=? AND kind='buy'", (p_["id"],)) or 0)
                nbv = (rep.get(p_["id"]) or {}).get("nbv") or 0
                if owned > EPS and dep:
                    sa += nbv * dep / owned
    except Exception:
        pass
    parts.append(("Small assets at the project (book value)", r2(sa)))
    less = [("Payable to suppliers and subcontractors", -_role_bal(c, ("ap_control",), asof, pid=pid)),
            ("Advance from client", -_role_bal(c, ("client_advance",), asof, pid=pid)),
            ("Retention held from subcontractors", -_role_bal(c, ("retention_payable",), asof, pid=pid))]
    gross = r2(sum(v for _, v in parts))
    net = r2(gross - sum(v for _, v in less))
    return {"assets": [{"label": k, "amount": r2(v)} for k, v in parts],
            "less": [{"label": k, "amount": r2(v)} for k, v in less], "gross": gross, "net": net}


def project_return(c, pid, asof, ev, cap):
    """Return on the money tied up in a project: margin earned to date (earned value less cost, waiting entries
    included) per year of the project's life so far, over the net capital employed today."""
    p = get(c, "projects", pid)
    start = p.get("start_date") or val(c, "SELECT MIN(v.date) FROM vouchers v JOIN voucher_lines l ON l.voucher_id=v.id "
                                          "WHERE l.project_id=?", (pid,))
    try:
        months = max(1.0, (date.fromisoformat(asof) - date.fromisoformat(start)).days / 30.44)
    except (TypeError, ValueError):
        months = 12.0
    margin = r2((ev.get("earned_revenue") or 0) - (ev.get("ac") or 0))
    yearly = margin * 12.0 / months
    base = cap["net"] if cap["net"] > EPS else None
    return {"margin_to_date": margin, "months": round(months, 1), "margin_per_year": r2(yearly),
            "roce_pct": r2(yearly / base * 100) if base else None,
            "roa_pct": r2(yearly / cap["gross"] * 100) if cap["gross"] > EPS else None}


@api("mg.project", "commercial", "view")
def mg_project(c, u, a):
    """One project on the combined model: cost (posted and waiting), commitments, cost by way of working against
    the execution plan, exposure, delays in money, capital employed and return."""
    need(a, "project_id")
    pid = int(a["project_id"])
    asof = a.get("as_of") or today()
    p = get(c, "projects", pid, "Project")
    import api_project as P
    ev = P.project_evm(c, pid, asof)
    rows = _cost_rows(c, "0000-01-01", asof, pid, None, True)
    by, wby = {}, {}
    for r in rows:
        m = r["mode"] or "untagged"
        amt = (r["debit"] or 0) - (r["credit"] or 0)
        by[m] = by.get(m, 0) + amt
        if r["status"] == "submitted":
            wby[m] = wby.get(m, 0) + amt
    tot = sum(by.values())
    modes = [{"mode": m, "label": dict(MODES + [("untagged", "Not tagged (before 2.23)")]).get(m, m), "amount": r2(v),
              "waiting": r2(wby.get(m, 0)), "share_pct": r2(100 * v / tot) if abs(tot) > EPS else None}
             for m, v in sorted(by.items(), key=lambda kv: (MODE_KEYS + ["untagged"]).index(kv[0]) if kv[0] in MODE_KEYS + ["untagged"] else 99)
             if abs(v) > 0.004]
    plan = None
    try:
        import api_exec as X
        pl = X.exec_plan(c, u, {"project_id": pid})
        tv = sum(pl["summary"].values())
        plan = [{"mode": k, "value": v, "share_pct": r2(100 * v / tv) if tv else None} for k, v in pl["summary"].items()]
    except Exception:
        plan = None
    rd = q(c, "SELECT SUM(d.amount) amt, COUNT(*) n FROM rent_deductions d JOIN hire_agreements h ON h.id=d.agreement_id "
              "WHERE h.project_id=? AND d.status='open'", (pid,)) if _has(c, "rent_deductions") else [{"amt": 0, "n": 0}]
    exposure = [
        {"label": "Material with subcontractors (to recover)", "amount": _role_bal(c, ("subcon_material",), asof, pid=pid), "link": "#/x/sub"},
        {"label": "Advances to subcontractors", "amount": _role_bal(c, ("subcon_advance",), asof, pid=pid), "link": "#/x/sub"},
        {"label": "Advances to suppliers", "amount": _role_bal(c, ("supplier_advance",), asof, pid=pid), "link": "#/acc/payments"},
        {"label": "Rental deductions not yet recovered", "amount": r2(rd[0]["amt"] or 0), "link": "#/x/rent"},
        {"label": "Retention receivable from client", "amount": _role_bal(c, ("retention_receivable",), asof, pid=pid), "link": "#/acc/sales"},
        {"label": "Retention held from subcontractors", "amount": -_role_bal(c, ("retention_payable",), asof, pid=pid), "link": "#/acc/party"},
        {"label": "Receivable from client", "amount": _role_bal(c, ("ar_control",), asof, pid=pid), "link": "#/acc/ageing"},
    ]
    delays = None
    try:
        import api_exec as X
        ds = X.delay_summary(c, u, {"project_id": pid, "to": asof})
        byr = {b["resp"]: b for b in ds["by"]}
        delays = {"employer_days": ds["employer_days"], "own_days": ds["own_days"],
                  "neutral_days": r2((byr.get("neutral") or {}).get("event_days") or (byr.get("neutral") or {}).get("days") or 0),
                  "claimable_idle_cost": ds["claimable_idle_cost"], "prolongation_cost": ds["prolongation_cost"],
                  "ld_exposure": ds["ld_exposure"], "claimed_cost": r2((byr.get("employer") or {}).get("cost_impact") or 0)}
    except Exception:
        delays = None
    cap = project_capital(c, pid, asof, ev)
    ret = project_return(c, pid, asof, ev, cap)
    nq = val(c, "SELECT COUNT(*) FROM post_queue pq JOIN vouchers v ON v.id=pq.voucher_id WHERE pq.project_id=? AND "
                "v.status='submitted' AND COALESCE(pq.stage,'') NOT IN ('withdrawn','posted')", (pid,)) if _has(c, "post_queue") else 0
    keys = ("contract_revenue", "forecast_revenue", "earned_revenue", "progress_value_pct", "ac", "ac_posted", "waiting",
            "ac_boq", "ac_unallocated", "eac", "etc", "forecast_profit", "current_margin", "forecast_margin", "tender_margin",
            "margin_fade", "cpi", "spi", "bac", "ev", "pv", "cv", "committed", "committed_po", "committed_sc", "eq_costing",
            "own_eq_charged", "own_eq_actual", "own_eq_adjustment")
    return {"project": {"id": p["id"], "code": p["code"], "name": p["name"], "kind": p.get("kind") or "project"},
            "as_of": asof, "evm": {k: ev.get(k) for k in keys}, "waiting_entries": nq, "modes": modes, "plan": plan,
            "exposure": exposure, "delays": delays, "capital": cap, "return": ret,
            "kpi_waiting": _kpi_on(c)}


# ───────────────────────────── finance by segment ─────────────────────────────
def _seg_balance(c, seg, to):
    stock = val(c, "SELECT SUM(b.value) FROM stock_balances b LEFT JOIN projects p ON p.id=b.project_id WHERE "
                   "CASE WHEN p.id IS NULL THEN 'company' WHEN COALESCE(p.kind,'') IN ('','project') THEN 'project' "
                   "WHEN p.kind='trading' THEN 'trading' ELSE 'company' END=?", (seg,)) or 0
    eq_nbv = 0.0
    try:
        import api_exec as X
        kinds = _kinds(c)
        for e in q(c, "SELECT * FROM equipment WHERE COALESCE(ownership,'owned')='owned' AND COALESCE(active,1)=1"):
            if seg_of(kinds, e["project_id"]) == seg:
                eq_nbv += X._nbv(c, e, to)
    except Exception:
        pass
    assets = [("Receivables", _role_bal(c, ("ar_control",), to, seg)),
              ("Retention receivable", _role_bal(c, ("retention_receivable",), to, seg)),
              ("Stock", r2(stock)),
              ("Material with subcontractors", _role_bal(c, ("subcon_material",), to, seg)),
              ("Advances paid", _role_bal(c, ("supplier_advance", "subcon_advance"), to, seg)),
              ("Own machines (book value)", r2(eq_nbv))]
    if seg == "company":  # treasury and head-office assets sit with the company, not with any project
        fa = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON "
                    "x.id=l.account_id WHERE x.type='asset' AND COALESCE(x.role,'') IN ('fixed_asset','accum_dep','fa_cost','fa_accum',"
                    "'ppe_accum','rou_asset','rou_accum') AND l.equipment_id IS NULL AND v.date<=? AND " + POSTED, (to,)) or 0
        fa += val(c, "SELECT SUM(opening_balance) FROM accounts WHERE type='asset' AND COALESCE(role,'') IN ('fixed_asset','accum_dep')") or 0
        assets += [("Cash and bank", _role_bal(c, ("cash", "bank"), to)), ("Other fixed assets (book value)", r2(fa))]
    liab = [("Payables", -_role_bal(c, ("ap_control",), to, seg)),
            ("Advances received", -_role_bal(c, ("client_advance",), to, seg)),
            ("Retention held", -_role_bal(c, ("retention_payable",), to, seg))]
    gross = r2(sum(v for _, v in assets))
    return {"assets": [{"label": k, "amount": r2(v)} for k, v in assets],
            "liabilities": [{"label": k, "amount": r2(v)} for k, v in liab],
            "gross": gross, "net": r2(gross - sum(v for _, v in liab))}


def _trading(c, frm, to):
    st = POSTED
    g = lambda roles, sign=1: r2(sign * (val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id "  # noqa: E731
                                                "JOIN accounts x ON x.id=l.account_id WHERE x.role IN (%s) AND v.date BETWEEN ? AND ? AND %s"
                                                % (",".join("?" * len(roles)), st), list(roles) + [frm, to]) or 0))
    sales = g(("trading_sales",), -1)
    returns = g(("trading_returns",))
    cogs = g(("cogs_trading",))
    net = r2(sales - returns)
    stock = r2(val(c, "SELECT SUM(b.value) FROM stock_balances b JOIN projects p ON p.id=b.project_id WHERE p.kind='trading'") or 0)
    days = (date.fromisoformat(to) - date.fromisoformat(frm)).days + 1
    ann = 365.0 / days if days > 0 else 1
    turns = r2(cogs * ann / stock) if stock > EPS else None
    return {"sales": sales, "returns": returns, "net_sales": net, "cogs": cogs, "gross_profit": r2(net - cogs),
            "gp_pct": r2(100 * (net - cogs) / net) if net > EPS else None, "stock": stock, "turns": turns,
            "days_on_hand": r2(365.0 / turns) if turns else None}


@api("mg.segments", "accounts", "view")
def mg_segments(c, u, a):
    """Projects, trading and company side by side: profit (posted), costs waiting for accounts, working capital,
    assets employed and return; ROE for the company; every project's capital and return."""
    frm, to = _period(c, a)
    days = (date.fromisoformat(to) - date.fromisoformat(frm)).days + 1
    ann = 365.0 / days if days > 0 else 1
    sync_tags(c)
    segs = []
    for s, lab in SEGMENTS:
        inc, exp = _seg_pl(c, frm, to, s)
        bal = _seg_balance(c, s, to)
        prof = r2(inc - exp)
        modes = {}
        for r in q(c, "SELECT t.mode, SUM(l.debit-l.credit) amt FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN "
                      "accounts x ON x.id=l.account_id" + SEG_JOIN + "LEFT JOIN mg_tags t ON t.line_id=l.id WHERE " + COST_SQL +
                      " AND v.date BETWEEN ? AND ? AND " + POSTED + " AND " + SEG_SQL + "=? GROUP BY t.mode", (frm, to, s)):
            if abs(r["amt"] or 0) > 0.004:
                modes[r["mode"] or "untagged"] = r2(r["amt"])
        segs.append({"segment": s, "label": lab, "income": inc, "cost": exp, "profit": prof,
                     "margin_pct": r2(100 * prof / inc) if inc > EPS else None, "waiting": _waiting_seg(c, to, s),
                     "balance": bal, "modes": modes,
                     "roa_pct": r2(prof * ann / bal["gross"] * 100) if bal["gross"] > EPS else None,
                     "roce_pct": r2(prof * ann / bal["net"] * 100) if bal["net"] > EPS else None})
    company = None
    try:
        import api_exec as X
        company = X._ret_period(c, frm, to)
    except Exception:
        company = None
    import api_project as P
    projects = []
    for p in q(c, "SELECT * FROM projects WHERE COALESCE(kind,'') IN ('','project') AND COALESCE(status,'active') "
                  "NOT IN ('closed','cancelled') ORDER BY code"):
        try:
            ev = P.project_evm(c, p["id"], to)
            cap = project_capital(c, p["id"], to, ev)
            ret = project_return(c, p["id"], to, ev, cap)
        except Exception as e:
            projects.append({"id": p["id"], "code": p["code"], "name": p["name"], "error": str(e)})
            continue
        projects.append({"id": p["id"], "code": p["code"], "name": p["name"], "status": p["status"],
                         "earned": ev.get("earned_revenue"), "cost": ev.get("ac"), "waiting": ev.get("waiting"),
                         "margin": ret["margin_to_date"], "forecast_margin": ev.get("forecast_margin"),
                         "committed": ev.get("committed"), "capital_gross": cap["gross"], "capital_net": cap["net"],
                         "roa_pct": ret["roa_pct"], "roce_pct": ret["roce_pct"], "months": ret["months"]})
    return {"from": frm, "to": to, "segments": segs, "company": company, "projects": projects,
            "trading": _trading(c, frm, to), "modes": MODES + [("untagged", "Not tagged (before 2.23)")]}


# ───────────────────────────── stock by segment ─────────────────────────────
@api("mg.stores", "inventory", "view")
def mg_stores(c, u, a):
    """Stock by where it belongs: project stores, the trading store, the central (company) store, and material
    lying with subcontractors; issues, turnover and days on hand per segment."""
    frm, to = _period(c, a)
    days = (date.fromisoformat(to) - date.fromisoformat(frm)).days + 1
    ann = 365.0 / days if days > 0 else 1
    kinds = _kinds(c)
    rows = q(c, "SELECT s.id store_id, s.code scode, s.name sname, p.id project_id, p.code pcode, p.name pname, "
                "COALESCE(p.kind,'') kind, COUNT(CASE WHEN ABS(b.qty)>0.0001 THEN 1 END) items, SUM(b.value) value "
                "FROM stores s JOIN projects p ON p.id=s.project_id LEFT JOIN stock_balances b ON b.store_id=s.id "
                "GROUP BY s.id ORDER BY p.code, s.code")
    issued = {r["store_id"]: r["v"] or 0 for r in q(c, "SELECT store_id, SUM(value_out) v FROM stock_ledger WHERE date BETWEEN ? AND ? "
                                                         "AND qty_out>0 AND COALESCE(doc_type,'') NOT IN ('transfer','MTN','count','PSV') "
                                                         "GROUP BY store_id", (frm, to))}
    out, seg_tot = [], {s: {"segment": s, "label": l_, "value": 0.0, "issued": 0.0, "stores": 0} for s, l_ in SEGMENTS}
    for r in rows:
        s = seg_of(kinds, r["project_id"])
        v = r2(r["value"] or 0)
        iss = r2(issued.get(r["store_id"], 0))
        turns = r2(iss * ann / v) if v > EPS else None
        out.append({"store_id": r["store_id"], "store": (r["scode"] or "") + " " + (r["sname"] or ""), "project_id": r["project_id"],
                    "pcode": r["pcode"], "pname": r["pname"], "segment": s, "location": "store", "items": r["items"],
                    "value": v, "issued": iss, "turns": turns, "days_on_hand": r2(365.0 / turns) if turns else None})
        seg_tot[s]["value"] += v
        seg_tot[s]["issued"] += iss
        seg_tot[s]["stores"] += 1
    subs = []
    if _has(c, "sc_orders"):
        for r in q(c, "SELECT COALESCE(l.project_id, v.project_id) pid, SUM(l.debit-l.credit) amt FROM voucher_lines l JOIN vouchers v "
                      "ON v.id=l.voucher_id JOIN accounts x ON x.id=l.account_id WHERE x.role='subcon_material' AND v.date<=? AND "
                      + POSTED + " GROUP BY 1", (to,)):
            if abs(r["amt"] or 0) > 0.004:
                p = q1(c, "SELECT code, name FROM projects WHERE id=?", (r["pid"],)) or {"code": "—", "name": ""}
                subs.append({"project_id": r["pid"], "pcode": p["code"], "pname": p["name"], "value": r2(r["amt"]),
                             "segment": seg_of(kinds, r["pid"])})
    for s in subs:
        seg_tot[s["segment"]]["with_subcontractors"] = r2(seg_tot[s["segment"]].get("with_subcontractors", 0) + s["value"])
    segs = []
    for s, _ in SEGMENTS:
        t = seg_tot[s]
        t["value"], t["issued"] = r2(t["value"]), r2(t["issued"])
        t["turns"] = r2(t["issued"] * ann / t["value"]) if t["value"] > EPS else None
        t["days_on_hand"] = r2(365.0 / t["turns"]) if t["turns"] else None
        segs.append(t)
    return {"from": frm, "to": to, "stores": out, "segments": segs, "with_subcontractors": subs,
            "trading": _trading(c, frm, to)}


# ───────────────────────────── own equipment recovery ─────────────────────────────
@api("mg.eqpool", "equipment", "view")
def mg_eqpool(c, u, a):
    """Every owned machine: what it cost (economic view: running cost, depreciation, loan interest) against what it
    charged the projects at its rate per hour; over- or under-recovery. Per project: own machines at rate against
    the running costs booked to that project."""
    frm, to = _period(c, a)
    import api_exec as X
    rows = []
    for e in q(c, "SELECT * FROM equipment WHERE COALESCE(ownership,'owned')='owned' AND COALESCE(active,1)=1 ORDER BY code"):
        r = X.eq_cost_row(c, e, frm, to)
        charged = r2(r["earned"])
        econ = r2(r["economic_cost"])
        rows.append({"equipment_id": e["id"], "code": e["code"], "name": e["name"], "hours": r["hours"],
                     "utilisation_pct": r["utilisation_pct"], "rate": r["internal_rate"], "economic_cost": econ,
                     "economic_per_unit": r["economic_per_unit"], "charged": charged, "over_under": r2(charged - econ),
                     "recovery_pct": r2(100 * charged / econ) if econ > EPS else None})
    st = POSTED
    proj = []
    for p in q(c, "SELECT DISTINCT l.project_id pid FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN equipment e "
                  "ON e.id=l.equipment_id WHERE COALESCE(e.ownership,'owned')='owned' AND l.project_id IS NOT NULL AND "
                  "v.date BETWEEN ? AND ? AND " + st, (frm, to)):
        pid = p["pid"]
        rec = val(c, "SELECT SUM(l.credit-l.debit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON "
                     "x.id=l.account_id WHERE x.role='equipment_recovery' AND l.project_id=? AND v.date BETWEEN ? AND ? AND " + st,
                  (pid, frm, to)) or 0
        own = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON "
                     "x.id=l.account_id JOIN equipment e ON e.id=l.equipment_id WHERE x.type='expense' AND COALESCE(x.role,'') NOT IN "
                     "('equipment_cost','equip_job_cost') AND COALESCE(e.ownership,'owned')='owned' AND l.project_id=? AND "
                     "v.date BETWEEN ? AND ? AND " + st, (pid, frm, to)) or 0
        pr = q1(c, "SELECT code, name FROM projects WHERE id=?", (pid,)) or {"code": "—", "name": ""}
        proj.append({"project_id": pid, "pcode": pr["code"], "pname": pr["name"], "at_rate": r2(rec), "actual_booked": r2(own),
                     "difference": r2(rec - own)})
    proj.sort(key=lambda x: x["pcode"] or "")
    return {"from": frm, "to": to, "machines": rows, "projects": proj, "eq_costing": setting(c, "mg_eq_costing") or "actual",
            "totals": {"economic_cost": r2(sum(r["economic_cost"] for r in rows)), "charged": r2(sum(r["charged"] for r in rows)),
                       "over_under": r2(sum(r["over_under"] for r in rows))}}
