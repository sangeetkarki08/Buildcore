"""Auth, masters, generic document storage and the inventory module."""
from core import (ApiError, EPS, LOCK, ROLES, audit, balance, can, check_store, ensure_project_stores,
                  get, hash_pw, ins, inventory_role, consumption_role, material, need, next_no, now, num,
                  post_voucher, q, q1, r2, r4, require, reverse_voucher, setting, fsetting, stock_in,
                  stock_out, today, transit_store, upd, val)
import secrets

FUNCS = {}


def api(name, module=None, action=None, public=False):
    def deco(f):
        FUNCS[name] = (f, module, action, public)
        return f
    return deco


# ───────────────────────── auth ─────────────────────────
@api("auth.status", public=True)
def auth_status(c, u, a):
    return {"needs_setup": val(c, "SELECT COUNT(*) FROM users") == 0,
            "company": setting(c, "company_name")}


@api("auth.setup", public=True)
def auth_setup(c, u, a):
    if val(c, "SELECT COUNT(*) FROM users"):
        raise ApiError("Setup is already complete.")
    need(a, "username", "password", "name")
    if len(a["password"]) < 6:
        raise ApiError("Password must have at least 6 characters.")
    h, s = hash_pw(a["password"])
    uid = ins(c, "users", {"username": a["username"].strip().lower(), "name": a["name"], "pw_hash": h,
                           "salt": s, "role": "admin", "active": 1})
    if a.get("company_name"):
        c.execute("UPDATE settings SET value=? WHERE key='company_name'", (a["company_name"],))
    if a.get("site_name"):
        c.execute("INSERT INTO settings(key,value) VALUES('site_name',?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (a["site_name"],))
    return login_user(c, uid, a.get("_ip"), a.get("_device"))


def login_user(c, uid, ip=None, device=None):
    token = secrets.token_hex(24)
    ins(c, "sessions", {"token": token, "user_id": uid, "created": now(), "last_seen": now(),
                        "ip": ip, "device": device})
    return {"token": token}


@api("auth.login", public=True)
def auth_login(c, u, a):
    from datetime import datetime, timedelta
    name = (a.get("username") or "").strip().lower()
    ip = a.get("_ip")
    try:
        lock_min = int(float(setting(c, "lock_minutes") or 10))
    except ValueError:
        lock_min = 10
    since = (datetime.now() - timedelta(minutes=lock_min)).isoformat(timespec="seconds")
    recent = q(c, "SELECT ok FROM login_attempts WHERE username=? AND ts>=? ORDER BY id DESC LIMIT 5", (name, since))
    if len(recent) == 5 and not any(r["ok"] for r in recent):
        raise ApiError("Too many wrong passwords for '%s'. Wait %d minutes, or ask your administrator "
                       "to set a new password." % (name, lock_min))
    usr = q1(c, "SELECT * FROM users WHERE username=? AND active=1", (name,))
    ok = bool(usr) and hash_pw(a.get("password") or "", usr["salt"])[0] == usr["pw_hash"]
    ins(c, "login_attempts", {"ts": now(), "username": name, "ip": ip, "ok": 1 if ok else 0})
    if not ok:
        c.commit()   # keep the record of the wrong password; nothing else has happened in this request
        raise ApiError("Wrong username or password.")
    audit(c, usr, "login", "users", usr["id"])
    return login_user(c, usr["id"], ip, a.get("_device"))


@api("auth.logout")
def auth_logout(c, u, a):
    c.execute("DELETE FROM sessions WHERE token=?", (a.get("_token"),))
    return True


@api("auth.me")
def auth_me(c, u, a):
    perms = {m: sorted(list(acts)) for m, acts in ROLES.get(u["role"], {}).items()}
    return {"id": u["id"], "username": u["username"], "name": u["name"], "role": u["role"], "perms": perms,
            "location": u["location"] if "location" in u.keys() else None,
            "site_name": setting(c, "site_name"), "site_code": setting(c, "site_code")}


@api("auth.password")
def auth_password(c, u, a):
    if hash_pw(a.get("old") or "", u["salt"])[0] != u["pw_hash"]:
        raise ApiError("Current password is wrong.")
    if len(a.get("new") or "") < 6:
        raise ApiError("New password must have at least 6 characters.")
    h, s = hash_pw(a["new"])
    upd(c, "users", u["id"], {"pw_hash": h, "salt": s})
    return True


# ───────────────────────── masters (generic CRUD) ─────────────────────────
MASTERS = {
    "projects": ("masters", ["code", "name", "client", "location", "contract_value", "start_date",
                             "end_date", "status"], ["code", "name"],
                 [("stores", "project_id"), ("grn", "project_id"), ("vouchers", "project_id")]),
    "parties": ("masters", ["code", "name", "kind", "pan", "vat_registered", "phone", "email", "address",
                            "bank", "bank_acno", "credit_days", "categories", "blacklisted", "active", "notes"],
                ["code", "name", "kind"],
                [("invoices", "party_id"), ("po", "vendor_id"), ("grn", "vendor_id"), ("payments", "party_id")]),
    "staff": ("masters", ["code", "name", "designation", "phone", "daily_rate", "monthly_rate",
                          "project_id", "active"], ["name"], []),
    "boq_items": ("masters", ["project_id", "code", "description", "unit", "qty", "rate", "executed_qty"],
                  ["project_id", "code", "description"], [("issue_lines", "boq_item_id")]),
    "material_coefficients": ("masters", ["boq_item_id", "material_id", "qty_per_unit", "wastage_pct"],
                              ["boq_item_id", "material_id", "qty_per_unit"], []),
    "materials": ("masters", ["code", "name", "local_name", "category", "unit", "spec", "min_level",
                              "reorder_level", "reorder_qty", "lead_days", "standard_rate", "batch_tracked",
                              "active"], ["code", "name", "unit"],
                  [("stock_ledger", "material_id"), ("po_lines", "material_id"), ("mrq_lines", "material_id")]),
    "stores": ("inventory", ["project_id", "code", "name", "type", "parent_id", "keeper", "active"],
               ["project_id", "name"], [("stock_ledger", "store_id")]),
    "accounts": ("accounts", ["code", "name", "type", "group_id", "role", "opening_balance", "bank_name",
                              "bank_acno", "active"], ["code", "name", "type", "group_id"],
                 [("voucher_lines", "account_id")]),
    "account_groups": ("accounts", ["code", "name", "type", "parent_id"], ["code", "name", "type"],
                       [("accounts", "group_id"), ("account_groups", "parent_id")]),
    "tds_rates": ("accounts", ["section", "description", "rate", "threshold", "active"],
                  ["description", "rate"], [("payments", "tds_rate_id")]),
    "budgets": ("accounts", ["project_id", "account_id", "boq_item_id", "amount", "remarks"],
                ["project_id", "account_id", "amount"], []),
    "fiscal_periods": ("accounts", ["fy", "code", "start_date", "end_date"],
                       ["fy", "code", "start_date", "end_date"], []),
    "equipment": ("equipment", ["code", "name", "category", "make", "model", "serial", "reg_no", "ownership",
                                "vendor_id", "purchase_date", "purchase_value", "residual_value", "life_months",
                                "dep_method", "wdv_rate", "est_total_hours", "accumulated_dep", "meter_type",
                                "meter", "fuel_norm", "internal_rate", "insurance_expiry",
                                "registration_expiry", "operator", "notes", "active",
                                "meters", "checklist_id", "rating", "owner_name"],
                  ["code", "name"], [("logsheets", "equipment_id"), ("voucher_lines", "equipment_id")]),
    "maint_plans": ("equipment", ["equipment_id", "title", "interval_type", "interval", "last_date",
                                  "last_meter", "checklist", "active"],
                    ["equipment_id", "title", "interval"], [("work_orders", "plan_id")]),
    "hire_agreements": ("equipment", ["equipment_id", "vendor_id", "project_id", "rate", "unit", "min_units",
                                      "mob_cost", "vat_rate", "start_date", "end_date", "active", "remarks"],
                        ["equipment_id", "vendor_id", "project_id", "rate", "unit"],
                        [("hire_bills", "agreement_id")]),
    "vendor_ratings": ("procurement", ["vendor_id", "po_id", "quality", "delivery", "price", "service",
                                       "remarks", "date"], ["vendor_id"], []),
}
NUMERIC = {"contract_value", "vat_registered", "credit_days", "blacklisted", "active", "daily_rate",
           "monthly_rate", "qty", "rate", "executed_qty", "qty_per_unit", "wastage_pct", "min_level",
           "reorder_level", "reorder_qty", "lead_days", "standard_rate", "batch_tracked", "opening_balance",
           "threshold", "amount", "purchase_value", "residual_value", "life_months", "wdv_rate",
           "est_total_hours", "accumulated_dep", "meter", "fuel_norm", "internal_rate", "interval",
           "last_meter", "min_units", "mob_cost", "vat_rate", "quality", "delivery", "price", "service"}
ID_FIELDS = {"project_id", "group_id", "parent_id", "boq_item_id", "material_id", "account_id",
             "equipment_id", "vendor_id", "po_id", "checklist_id", "owner_party_id", "hirer_party_id"}


def clean_value(k, v):
    if v == "" or v is None:
        return None if (k in ID_FIELDS or k not in NUMERIC) else 0
    if k in ID_FIELDS:
        return int(v)
    if k in NUMERIC:
        return num(v, k)
    return str(v).strip()


@api("master.list")
def master_list(c, u, a):
    t = a.get("table")
    if t not in MASTERS:
        raise ApiError("Unknown list.")
    require(u, MASTERS[t][0], "view")
    where, p = [], []
    for k in ("project_id", "equipment_id", "boq_item_id", "kind"):
        if a.get(k):
            where.append("%s=?" % k)
            p.append(a[k])
    sql = "SELECT * FROM %s%s ORDER BY %s" % (t, " WHERE " + " AND ".join(where) if where else "",
                                            "code" if t in ("projects", "parties", "materials", "accounts",
                                                            "equipment", "account_groups", "boq_items") else "id")
    return q(c, sql, p)


@api("master.save")
def master_save(c, u, a):
    t = a.get("table")
    if t not in MASTERS:
        raise ApiError("Unknown list.")
    module, fields, required, _refs = MASTERS[t]
    require(u, module, "edit")
    row = a.get("row") or {}
    data = {k: clean_value(k, row.get(k)) for k in fields if k in row}
    rid = row.get("id")
    if not rid:
        for k in required:
            if data.get(k) in (None, ""):
                raise ApiError("%s is required." % k.replace("_", " ").capitalize())
    if "code" in data and data["code"] and t in ("projects", "parties", "materials", "accounts",
                                                  "equipment", "account_groups"):
        dup = q1(c, "SELECT id FROM %s WHERE code=? AND id<>?" % t, (data["code"], rid or 0))
        if dup:
            raise ApiError("Code %s is already used." % data["code"])
    if t == "accounts" and rid and "type" in data:
        old = get(c, "accounts", rid)
        if old["type"] != data["type"] and val(c, "SELECT COUNT(*) FROM voucher_lines WHERE account_id=?", (rid,)):
            raise ApiError("This account has postings; its type cannot change.")
    if t == "stores" and data.get("type") == "transit" and not rid:
        raise ApiError("Transit stores are created automatically.")
    if t == "fiscal_periods" and data.get("start_date", "1") > data.get("end_date", "2"):
        raise ApiError("Start date must be before end date.")
    if t == "material_coefficients" or t == "maint_plans":
        pass
    if rid:
        upd(c, t, rid, data)
    else:
        if t == "equipment":
            data.setdefault("status", "working")
        rid = ins(c, t, data)
    if t == "projects":
        ensure_project_stores(c, rid)
    audit(c, u, "save", t, rid, data)
    return q1(c, "SELECT * FROM %s WHERE id=?" % t, (rid,))


@api("master.delete")
def master_delete(c, u, a):
    t = a.get("table")
    if t not in MASTERS:
        raise ApiError("Unknown list.")
    module, _f, _r, refs = MASTERS[t]
    require(u, module, "edit")
    rid = a.get("id")
    row = get(c, t, rid)
    for rt, col in refs:
        if val(c, "SELECT COUNT(*) FROM %s WHERE %s=?" % (rt, col), (rid,)):
            raise ApiError("This record is already used in %s. Mark it inactive instead." % rt.replace("_", " "))
    if t == "stores" and val(c, "SELECT COUNT(*) FROM stock_balances WHERE store_id=? AND ABS(qty)>0.0001", (rid,)):
        raise ApiError("This store still holds stock.")
    if t == "fiscal_periods" and row.get("status") != "open":
        raise ApiError("Only open periods can be deleted.")
    c.execute("DELETE FROM %s WHERE id=?" % t, (rid,))
    audit(c, u, "delete", t, rid, row)
    return True


@api("lookups")
def lookups(c, u, a):
    return {
        "projects": q(c, "SELECT id, code, name, status FROM projects ORDER BY code"),
        "stores": q(c, "SELECT id, project_id, code, name, type, active FROM stores ORDER BY project_id, type, name"),
        "materials": q(c, "SELECT id, code, name, category, unit, standard_rate, reorder_level, active "
                          "FROM materials ORDER BY code"),
        "parties": q(c, "SELECT id, code, name, kind, pan, vat_registered, active, blacklisted FROM parties ORDER BY name"),
        "accounts": q(c, "SELECT id, code, name, type, role, group_id, active FROM accounts ORDER BY code"),
        "groups": q(c, "SELECT * FROM account_groups ORDER BY code"),
        "equipment": q(c, "SELECT id, code, name, category, status, project_id, meter_type, meter, ownership, "
                          "reg_no, model, operator, meters, checklist_id, owner_name, vendor_id, active "
                          "FROM equipment ORDER BY code"),
        "checklists": q(c, "SELECT id, code, name, category, items FROM check_lists WHERE active=1 ORDER BY name"),
        "boq": q(c, "SELECT id, project_id, code, description, unit FROM boq_items ORDER BY project_id, code"),
        "staff": q(c, "SELECT id, code, name, designation FROM staff WHERE active=1 ORDER BY name"),
        "tds": q(c, "SELECT * FROM tds_rates WHERE active=1"),
        "users": q(c, "SELECT id, name FROM users"),
        "settings": {r["key"]: r["value"] for r in q(c, "SELECT * FROM settings")},
    }


# ───────────────────────── generic documents ─────────────────────────
DOCS = {
    # type: table, lines table, fk, module, number prefix, number-at, header fields, line fields
    "mrq": ("mrq", "mrq_lines", "mrq_id", "inventory", "MRQ", "create",
            ["project_id", "date", "store_id", "requested_by", "remarks"],
            ["material_id", "qty", "boq_item_id", "remarks"]),
    "grn": ("grn", "grn_lines", "grn_id", "inventory", "GRN", "post",
            ["project_id", "store_id", "vendor_id", "po_id", "date", "challan_no", "vehicle_no", "freight",
             "remarks"],
            ["po_line_id", "material_id", "received_qty", "accepted_qty", "rate", "batch_no", "remarks"]),
    "issue": ("issues", "issue_lines", "issue_id", "inventory", "MIN", "post",
              ["project_id", "store_id", "date", "issued_to", "mrq_id", "wo_id", "remarks"],
              ["material_id", "qty", "target", "boq_item_id", "equipment_id", "mrq_line_id"]),
    "return": ("returns", "return_lines", "return_id", "inventory", "MRT", "post",
               ["project_id", "store_id", "date", "returned_by", "remarks"],
               ["material_id", "issue_line_id", "qty", "condition", "boq_item_id", "equipment_id"]),
    "transfer": ("transfers", "transfer_lines", "transfer_id", "inventory", "MTN", "post",
                 ["from_project", "from_store", "to_project", "to_store", "date", "vehicle_no", "remarks"],
                 ["material_id", "qty"]),
    "count": ("stock_counts", "count_lines", "count_id", "inventory", "PSV", "post",
              ["project_id", "store_id", "date", "remarks"],
              ["material_id", "system_qty", "counted_qty", "reason"]),
    "pr": ("pr", "pr_lines", "pr_id", "procurement", "PR", "create",
           ["project_id", "date", "required_by", "priority", "remarks"],
           ["material_id", "description", "qty", "unit", "est_rate", "boq_item_id", "mrq_line_id"]),
    "po": ("po", "po_lines", "po_id", "procurement", "PO", "create",
           ["project_id", "vendor_id", "date", "delivery_date", "store_id", "pr_id", "payment_terms", "freight",
            "terms", "remarks"],
           ["pr_line_id", "material_id", "description", "qty", "unit", "rate", "vat_rate", "boq_item_id"]),
    "invoice": ("invoices", "invoice_lines", "invoice_id", "procurement", "INV", "post",
                ["kind", "party_id", "project_id", "date", "party_inv_no", "due_date", "po_id", "tds", "retention",
                 "advance_recovery", "remarks"],
                ["grn_line_id", "material_id", "description", "qty", "rate", "vat_rate", "account_id",
                 "equipment_id", "boq_item_id"]),
}
DOC_ID = ID_FIELDS | {"store_id", "from_project", "from_store", "to_project", "to_store", "mrq_id", "wo_id",
                      "po_line_id", "issue_line_id", "pr_id", "pr_line_id", "mrq_line_id", "grn_line_id",
                      "party_id"}
DOC_NUM = {"freight", "qty", "received_qty", "accepted_qty", "rate", "system_qty", "counted_qty", "est_rate",
           "vat_rate", "tds", "retention", "advance_recovery"}


def doc_module(t, row=None):
    if t == "invoice" and row and row.get("kind") == "sales":
        return "accounts"
    return DOCS[t][3]


def dval(k, v):
    if v in ("", None):
        return None if k in DOC_ID or k not in DOC_NUM else 0
    if k in DOC_ID:
        return int(v)
    if k in DOC_NUM:
        return num(v, k)
    return str(v).strip()


def load_doc(c, t, rid):
    table, lt, fk = DOCS[t][:3]
    h = get(c, table, rid, "Document")
    h["lines"] = q(c, "SELECT * FROM %s WHERE %s=? ORDER BY id" % (lt, fk), (rid,))
    return h


@api("doc.get")
def doc_get(c, u, a):
    t = a.get("type")
    if t not in DOCS:
        raise ApiError("Unknown document.")
    d = load_doc(c, t, a.get("id"))
    require(u, doc_module(t, d), "view")
    if t == "invoice":
        d["paid"] = invoice_paid(c, d["id"])
    return d


@api("doc.list")
def doc_list(c, u, a):
    t = a.get("type")
    if t not in DOCS:
        raise ApiError("Unknown document.")
    table = DOCS[t][0]
    require(u, "accounts" if (t == "invoice" and a.get("kind") == "sales") else DOCS[t][3], "view")
    where, p = [], []
    if a.get("project_id"):
        if t == "transfer":
            where.append("(from_project=? OR to_project=?)")
            p += [a["project_id"], a["project_id"]]
        else:
            where.append("project_id=?")
            p.append(a["project_id"])
    for k in ("status", "kind", "party_id", "vendor_id", "store_id"):
        if a.get(k):
            where.append("%s=?" % k)
            p.append(a[k])
    if a.get("from"):
        where.append("date>=?")
        p.append(a["from"])
    if a.get("to"):
        where.append("date<=?")
        p.append(a["to"])
    rows = q(c, "SELECT * FROM %s%s ORDER BY date DESC, id DESC LIMIT %d" %
             (table, " WHERE " + " AND ".join(where) if where else "", int(a.get("limit") or 500)), p)
    if t == "invoice":
        for r in rows:
            r["paid"] = invoice_paid(c, r["id"])
            r["balance"] = r2(r["payable"] - r["paid"]) if r["status"] == "posted" else 0
    if t == "po":
        for r in rows:
            r["received_pct"] = po_received_pct(c, r["id"])
    return rows


def po_received_pct(c, po_id):
    t = q1(c, "SELECT SUM(qty) q, SUM(MIN(received_qty, qty)) r FROM po_lines WHERE po_id=?", (po_id,))
    return round(100 * (t["r"] or 0) / t["q"], 1) if t and t["q"] else 0


def invoice_paid(c, inv_id):
    return r2(val(c, "SELECT SUM(amount) FROM allocations WHERE invoice_id=? AND active=1", (inv_id,)))


@api("doc.save")
def doc_save(c, u, a):
    """Create or update a draft document. Lines keep their ids so references survive edits."""
    t = a.get("type")
    if t not in DOCS:
        raise ApiError("Unknown document.")
    table, lt, fk, _m, prefix, number_at, hf, lf = DOCS[t]
    h = a.get("header") or {}
    rid = h.get("id")
    old = get(c, table, rid, "Document") if rid else None
    probe = dict(old or {})
    probe.update(h)
    require(u, doc_module(t, probe), "edit")
    if old and old["status"] != "draft":
        raise ApiError("Only draft documents can be edited (this one is %s)." % old["status"])
    data = {k: dval(k, h.get(k)) for k in hf if k in h}
    if not data.get("date") and not (old and old.get("date")):
        data["date"] = today()
    if t == "invoice":
        data["kind"] = (old or {}).get("kind") or data.get("kind") or "purchase"
    proj = data.get("project_id") or data.get("from_project") or (old or {}).get("project_id") or \
        (old or {}).get("from_project")
    if not proj:
        raise ApiError("Select a project.")
    if t == "transfer":
        need(data, "from_store", "to_project", "to_store")
        check_store(c, data["from_store"], data["from_project"])
        check_store(c, data["to_store"], data["to_project"])
        if data["from_store"] == data["to_store"]:
            raise ApiError("Source and destination store are the same.")
    elif data.get("store_id"):
        check_store(c, data["store_id"], proj)
    lines = a.get("lines") or []
    clean = []
    for ln in lines:
        x = {k: dval(k, ln.get(k)) for k in lf if k in ln}
        x["id"] = ln.get("id")
        qty_key = {"grn": "received_qty", "count": "counted_qty"}.get(t, "qty")
        if t != "count" and not x.get("material_id") and not x.get("description") and not x.get("account_id") \
                and not x.get("grn_line_id"):
            continue
        if t == "count":
            if not x.get("material_id"):
                continue
        elif (x.get(qty_key) or 0) <= 0:
            raise ApiError("Every line needs a quantity above zero.")
        if t == "issue":
            x["target"] = x.get("target") or "boq"
        if t == "return":
            x["condition"] = x.get("condition") or "usable"
        clean.append(x)
    if not clean and t not in ("count",):
        raise ApiError("Add at least one line.")
    if old:
        upd(c, table, rid, data)
    else:
        data["status"] = "draft"
        data["created_by"] = u["id"]
        if number_at == "create":
            data["no"] = next_no(c, prefix, data["date"])
        else:
            data["no"] = None
        rid = ins(c, table, data)
    keep = set()
    for x in clean:
        lid = x.pop("id", None)
        if lid and q1(c, "SELECT id FROM %s WHERE id=? AND %s=?" % (lt, fk), (lid, rid)):
            upd(c, lt, lid, x)
            keep.add(lid)
        else:
            x[fk] = rid
            keep.add(ins(c, lt, x))
    for ex in q(c, "SELECT id FROM %s WHERE %s=?" % (lt, fk), (rid,)):
        if ex["id"] not in keep:
            if t == "po" and val(c, "SELECT COUNT(*) FROM grn_lines WHERE po_line_id=?", (ex["id"],)):
                raise ApiError("A PO line that has deliveries cannot be removed.")
            c.execute("DELETE FROM %s WHERE id=?" % lt, (ex["id"],))
    if t == "po":
        recalc_po(c, rid)
    audit(c, u, "save", table, rid, {"header": data, "lines": clean})
    return load_doc(c, t, rid)


@api("doc.delete")
def doc_delete(c, u, a):
    t = a.get("type")
    if t not in DOCS:
        raise ApiError("Unknown document.")
    table, lt, fk = DOCS[t][:3]
    d = get(c, table, a.get("id"), "Document")
    require(u, doc_module(t, d), "edit")
    if d["status"] != "draft":
        raise ApiError("Only drafts can be deleted. Use Cancel for posted documents.")
    if t == "po" and d.get("revision"):
        raise ApiError("A revised PO cannot be deleted; cancel or close it.")
    c.execute("DELETE FROM %s WHERE %s=?" % (lt, fk), (d["id"],))
    c.execute("DELETE FROM %s WHERE id=?" % table, (d["id"],))
    audit(c, u, "delete", table, d["id"], d)
    return True


def draft_doc(c, t, rid):
    d = load_doc(c, t, rid)
    if d["status"] != "draft":
        raise ApiError("This document is already %s." % d["status"])
    return d


# ───────────────────────── inventory: MRQ ─────────────────────────
@api("mrq.submit", "inventory", "edit")
def mrq_submit(c, u, a):
    draft_doc(c, "mrq", a["id"])
    upd(c, "mrq", a["id"], {"status": "submitted"})
    return True


@api("mrq.approve", "inventory", "approve")
def mrq_approve(c, u, a):
    d = load_doc(c, "mrq", a["id"])
    if d["status"] != "submitted":
        raise ApiError("Only submitted requisitions can be approved.")
    appr = {int(k): num(v) for k, v in (a.get("approved") or {}).items()}
    for ln in d["lines"]:
        upd(c, "mrq_lines", ln["id"], {"approved_qty": appr.get(ln["id"], ln["qty"])})
    upd(c, "mrq", d["id"], {"status": "approved", "approved_by": u["id"]})
    audit(c, u, "approve", "mrq", d["id"], appr)
    return True


@api("mrq.reject", "inventory", "approve")
def mrq_reject(c, u, a):
    d = get(c, "mrq", a["id"])
    if d["status"] != "submitted":
        raise ApiError("Only submitted requisitions can be rejected.")
    upd(c, "mrq", d["id"], {"status": "rejected", "remarks": ((d["remarks"] or "") + " | Rejected: " +
                                                             (a.get("reason") or "")).strip(" |")})
    return True


@api("mrq.close", "inventory", "edit")
def mrq_close(c, u, a):
    upd(c, "mrq", a["id"], {"status": "closed"})
    return True


def mrq_refresh(c, mrq_id):
    if not mrq_id:
        return
    d = load_doc(c, "mrq", mrq_id)
    if d["status"] not in ("approved", "partially_issued", "issued"):
        return
    need_ = sum((l["approved_qty"] or 0) for l in d["lines"])
    done = sum(min(l["issued_qty"] or 0, l["approved_qty"] or 0) for l in d["lines"])
    st = "approved" if done <= EPS else ("issued" if done + EPS >= need_ else "partially_issued")
    upd(c, "mrq", mrq_id, {"status": st})


def project_available(c, project_id, material_id):
    return val(c, "SELECT SUM(b.qty) FROM stock_balances b JOIN stores s ON s.id=b.store_id "
                  "WHERE b.project_id=? AND b.material_id=? AND s.type<>'transit'", (project_id, material_id))


@api("mrq.to_pr", "procurement", "edit")
def mrq_to_pr(c, u, a):
    d = load_doc(c, "mrq", a["id"])
    if d["status"] not in ("approved", "partially_issued"):
        raise ApiError("Only approved requisitions can raise a purchase request.")
    lines = []
    for ln in d["lines"]:
        pending = (ln["approved_qty"] or 0) - (ln["issued_qty"] or 0) - (ln["pr_qty"] or 0)
        short = pending - max(0, project_available(c, d["project_id"], ln["material_id"]))
        if short > EPS:
            m = material(c, ln["material_id"])
            lines.append((ln, m, r4(short)))
    if not lines:
        raise ApiError("Stock on hand covers this requisition. Issue it from the store instead.")
    no = next_no(c, "PR", today())
    pid = ins(c, "pr", {"no": no, "project_id": d["project_id"], "date": today(), "source": "mrq",
                        "mrq_id": d["id"], "status": "draft", "priority": "normal",
                        "remarks": "From %s" % d["no"], "created_by": u["id"]})
    for ln, m, qty in lines:
        ins(c, "pr_lines", {"pr_id": pid, "material_id": m["id"], "description": m["name"], "qty": qty,
                            "unit": m["unit"], "est_rate": m["standard_rate"], "boq_item_id": ln["boq_item_id"],
                            "mrq_line_id": ln["id"]})
        upd(c, "mrq_lines", ln["id"], {"pr_qty": (ln["pr_qty"] or 0) + qty})
    audit(c, u, "create", "pr", pid, {"from_mrq": d["id"]})
    return {"id": pid, "no": no}


# ───────────────────────── inventory: GRN ─────────────────────────
def recalc_po(c, po_id):
    lines = q(c, "SELECT * FROM po_lines WHERE po_id=?", (po_id,))
    po = get(c, "po", po_id)
    sub = r2(sum(r2(l["qty"] * l["rate"]) for l in lines))
    vat = r2(sum(r2(l["qty"] * l["rate"]) * (l["vat_rate"] or 0) / 100 for l in lines))
    upd(c, "po", po_id, {"subtotal": sub, "vat": vat, "total": r2(sub + vat + (po["freight"] or 0))})


def po_refresh_status(c, po_id):
    po = get(c, "po", po_id)
    if po["status"] not in ("approved", "partially_received", "received"):
        return
    lines = q(c, "SELECT qty, received_qty FROM po_lines WHERE po_id=?", (po_id,))
    rec = sum(l["received_qty"] or 0 for l in lines)
    full = all((l["received_qty"] or 0) + EPS >= l["qty"] for l in lines)
    st = "received" if full else ("partially_received" if rec > EPS else "approved")
    upd(c, "po", po_id, {"status": st})


@api("grn.from_po", "inventory", "view")
def grn_from_po(c, u, a):
    po = load_doc(c, "po", a["po_id"])
    if po["status"] not in ("approved", "partially_received"):
        raise ApiError("This PO is %s; goods can be received only against approved POs." % po["status"])
    lines = []
    for l in po["lines"]:
        pend = r4(l["qty"] - (l["received_qty"] or 0))
        if pend > EPS and l["material_id"]:
            lines.append({"po_line_id": l["id"], "material_id": l["material_id"], "received_qty": pend,
                          "accepted_qty": pend, "rate": l["rate"]})
    return {"header": {"project_id": po["project_id"], "store_id": po["store_id"], "vendor_id": po["vendor_id"],
                       "po_id": po["id"]}, "lines": lines}


@api("grn.post", "inventory", "edit")
def grn_post(c, u, a):
    g = draft_doc(c, "grn", a["id"])
    need(g, "project_id", "store_id", "vendor_id", "date")
    check_store(c, g["store_id"], g["project_id"])
    vendor = get(c, "parties", g["vendor_id"], "Vendor")
    if vendor["blacklisted"]:
        raise ApiError("Vendor %s is blacklisted." % vendor["name"])
    po = None
    if g["po_id"]:
        po = get(c, "po", g["po_id"], "PO")
        if po["status"] not in ("approved", "partially_received"):
            raise ApiError("PO %s is %s." % (po["no"], po["status"]))
        if po["vendor_id"] != g["vendor_id"] or po["project_id"] != g["project_id"]:
            raise ApiError("GRN vendor/project must match the PO.")
    tol = fsetting(c, "over_receipt_pct")
    lines = g["lines"]
    if not lines:
        raise ApiError("Add at least one line.")
    prepared = []
    for l in lines:
        m = material(c, l["material_id"])
        rec = num(l["received_qty"])
        acc = rec if l["accepted_qty"] is None else num(l["accepted_qty"])
        if acc < 0 or acc > rec + EPS:
            raise ApiError("%s: accepted quantity must be between 0 and received quantity." % m["name"])
        rate = num(l["rate"])
        if po:
            if not l["po_line_id"]:
                raise ApiError("%s: pick the PO line it belongs to." % m["name"])
            pl = get(c, "po_lines", l["po_line_id"], "PO line")
            if pl["po_id"] != po["id"] or pl["material_id"] != l["material_id"]:
                raise ApiError("%s does not match its PO line." % m["name"])
            if (pl["received_qty"] or 0) + acc > pl["qty"] * (1 + tol / 100) + EPS:
                raise ApiError("%s: receiving %s would exceed PO quantity %s (+%s%% tolerance). Already received %s." %
                               (m["name"], acc, pl["qty"], tol, pl["received_qty"] or 0))
            rate = pl["rate"]
        if rate <= 0 and acc > 0:
            raise ApiError("%s: rate is required." % m["name"])
        prepared.append((l, m, rec, acc, rate))
    base = sum(acc * rate for _l, _m, _r, acc, rate in prepared)
    freight = num(g["freight"])
    if freight > 0 and base <= 0:
        raise ApiError("Freight needs at least one accepted line with value.")
    no = next_no(c, "GRN", g["date"])
    by_role = {}
    total_val = 0.0
    for l, m, rec, acc, rate in prepared:
        share = (acc * rate / base * freight) if base > 0 else 0
        landed = rate + (share / acc if acc > EPS else 0)
        upd(c, "grn_lines", l["id"], {"accepted_qty": acc, "rejected_qty": r4(rec - acc), "rate": rate,
                                      "landed_rate": r4(landed)})
        v = stock_in(c, u, g["project_id"], g["store_id"], m["id"], acc, landed, g["date"], "GRN", g["id"], no,
                     l["batch_no"])
        role = inventory_role(m)
        by_role[role] = by_role.get(role, 0) + v
        total_val += v
        if po:
            c.execute("UPDATE po_lines SET received_qty=COALESCE(received_qty,0)+? WHERE id=?", (acc, l["po_line_id"]))
    vl = [{"role": r, "debit": v} for r, v in by_role.items()]
    if freight > 0:
        vl.append({"role": "freight_clearing", "credit": freight, "narration": "Freight on " + no})
    vl.append({"role": "grni", "credit": r2(total_val - freight), "party_id": g["vendor_id"]})
    vid = post_voucher(c, u, "journal", g["date"], "Goods received %s from %s" % (no, vendor["name"]), vl,
                       project_id=g["project_id"], source="grn", source_id=g["id"], party_id=g["vendor_id"],
                       ref_no=g["challan_no"])
    upd(c, "grn", g["id"], {"status": "posted", "no": no, "voucher_id": vid})
    if po:
        po_refresh_status(c, po["id"])
    audit(c, u, "post", "grn", g["id"], {"no": no})
    return {"no": no}


@api("grn.cancel", "inventory", "approve")
def grn_cancel(c, u, a):
    g = load_doc(c, "grn", a["id"])
    if g["status"] != "posted":
        raise ApiError("Only posted GRNs can be cancelled.")
    if any((l["invoiced_qty"] or 0) > EPS for l in g["lines"]):
        raise ApiError("This GRN is already invoiced. Cancel the invoice first.")
    for l in g["lines"]:
        if (l["accepted_qty"] or 0) > EPS:
            stock_out(c, u, g["project_id"], g["store_id"], l["material_id"], l["accepted_qty"], today(),
                      "GRN-CANCEL", g["id"], g["no"], rate=l["landed_rate"])
            if l["po_line_id"]:
                c.execute("UPDATE po_lines SET received_qty=received_qty-? WHERE id=?",
                          (l["accepted_qty"], l["po_line_id"]))
    reverse_voucher(c, u, g["voucher_id"], today(), a.get("reason") or "GRN cancelled")
    upd(c, "grn", g["id"], {"status": "cancelled", "remarks": ((g["remarks"] or "") + " | Cancelled: " +
                                                             (a.get("reason") or "")).strip(" |")})
    if g["po_id"]:
        po_refresh_status(c, g["po_id"])
    audit(c, u, "cancel", "grn", g["id"], a.get("reason"))
    return True


# ───────────────────────── inventory: issue ─────────────────────────
def check_boq(c, boq_id, project_id):
    b = get(c, "boq_items", boq_id, "BOQ item")
    if b["project_id"] != project_id:
        raise ApiError("BOQ item %s belongs to another project." % b["code"])
    return b


@api("issue.from_mrq", "inventory", "view")
def issue_from_mrq(c, u, a):
    d = load_doc(c, "mrq", a["mrq_id"])
    if d["status"] not in ("approved", "partially_issued"):
        raise ApiError("Only approved requisitions can be issued.")
    lines = []
    for l in d["lines"]:
        pend = r4((l["approved_qty"] or 0) - (l["issued_qty"] or 0))
        if pend > EPS:
            lines.append({"material_id": l["material_id"], "qty": pend, "target": "boq" if l["boq_item_id"] else
                          "overhead", "boq_item_id": l["boq_item_id"], "mrq_line_id": l["id"]})
    return {"header": {"project_id": d["project_id"], "store_id": d["store_id"], "mrq_id": d["id"],
                       "issued_to": d["requested_by"]}, "lines": lines}


@api("issue.post", "inventory", "edit")
def issue_post(c, u, a):
    d = draft_doc(c, "issue", a["id"])
    need(d, "project_id", "store_id", "date", "issued_to")
    check_store(c, d["store_id"], d["project_id"])
    if not d["lines"]:
        raise ApiError("Add at least one line.")
    no = next_no(c, "MIN", d["date"])
    vl = []
    for l in d["lines"]:
        m = material(c, l["material_id"])
        tgt = l["target"] or "boq"
        if tgt == "boq":
            if not l["boq_item_id"]:
                raise ApiError("%s: choose the BOQ item it is used for." % m["name"])
            check_boq(c, l["boq_item_id"], d["project_id"])
        if tgt == "equipment" and not l["equipment_id"]:
            raise ApiError("%s: choose the equipment." % m["name"])
        rate, value = stock_out(c, u, d["project_id"], d["store_id"], m["id"], l["qty"], d["date"], "MIN",
                                d["id"], no)
        upd(c, "issue_lines", l["id"], {"rate": r4(rate), "amount": value, "target": tgt})
        dims = {"boq_item_id": l["boq_item_id"] if tgt == "boq" else None,
                "equipment_id": l["equipment_id"] if tgt == "equipment" else None}
        vl.append(dict(role=consumption_role(m, tgt), debit=value, narration=m["name"], **dims))
        vl.append({"role": inventory_role(m), "credit": value, "narration": m["name"]})
        if l["mrq_line_id"]:
            c.execute("UPDATE mrq_lines SET issued_qty=COALESCE(issued_qty,0)+? WHERE id=?", (l["qty"], l["mrq_line_id"]))
    vid = post_voucher(c, u, "journal", d["date"], "Material issue %s to %s" % (no, d["issued_to"]), vl,
                       project_id=d["project_id"], source="issue", source_id=d["id"])
    upd(c, "issues", d["id"], {"status": "posted", "no": no, "voucher_id": vid})
    mrq_refresh(c, d["mrq_id"])
    audit(c, u, "post", "issues", d["id"], {"no": no})
    return {"no": no}


@api("issue.cancel", "inventory", "approve")
def issue_cancel(c, u, a):
    d = load_doc(c, "issue", a["id"])
    if d["status"] != "posted":
        raise ApiError("Only posted issues can be cancelled.")
    if any((l["returned_qty"] or 0) > EPS for l in d["lines"]):
        raise ApiError("Some material from this issue was returned. Cancel the return first.")
    for l in d["lines"]:
        stock_in(c, u, d["project_id"], d["store_id"], l["material_id"], l["qty"], l["rate"], today(),
                 "MIN-CANCEL", d["id"], d["no"])
        if l["mrq_line_id"]:
            c.execute("UPDATE mrq_lines SET issued_qty=issued_qty-? WHERE id=?", (l["qty"], l["mrq_line_id"]))
    reverse_voucher(c, u, d["voucher_id"], today(), a.get("reason") or "Issue cancelled")
    upd(c, "issues", d["id"], {"status": "cancelled"})
    mrq_refresh(c, d["mrq_id"])
    audit(c, u, "cancel", "issues", d["id"], a.get("reason"))
    return True


# ───────────────────────── inventory: returns ─────────────────────────
STOCKABLE = ("usable", "repairable")


@api("return.post", "inventory", "edit")
def return_post(c, u, a):
    d = draft_doc(c, "return", a["id"])
    need(d, "project_id", "store_id", "date")
    check_store(c, d["store_id"], d["project_id"])
    no = next_no(c, "MRT", d["date"])
    vl = []
    for l in d["lines"]:
        m = material(c, l["material_id"])
        boq, eq, tgt = l["boq_item_id"], l["equipment_id"], "boq"
        if l["issue_line_id"]:
            il = get(c, "issue_lines", l["issue_line_id"], "Issue line")
            iss = get(c, "issues", il["issue_id"])
            if iss["status"] != "posted" or il["material_id"] != m["id"] or iss["project_id"] != d["project_id"]:
                raise ApiError("%s: the linked issue does not match." % m["name"])
            if (il["returned_qty"] or 0) + l["qty"] > il["qty"] + EPS:
                raise ApiError("%s: return quantity exceeds what was issued on %s." % (m["name"], iss["no"]))
            rate, boq, eq, tgt = il["rate"], il["boq_item_id"], il["equipment_id"], il["target"]
            c.execute("UPDATE issue_lines SET returned_qty=COALESCE(returned_qty,0)+? WHERE id=?", (l["qty"], il["id"]))
        else:
            bq, bv = balance(c, d["project_id"], d["store_id"], m["id"])
            rate = (bv / bq) if bq > EPS else m["standard_rate"]
            tgt = "equipment" if eq else ("boq" if boq else "overhead")
        amount = r2(l["qty"] * rate)
        upd(c, "return_lines", l["id"], {"rate": r4(rate), "amount": amount, "boq_item_id": boq,
                                         "equipment_id": eq})
        if l["condition"] in STOCKABLE:
            stock_in(c, u, d["project_id"], d["store_id"], m["id"], l["qty"], rate, d["date"], "MRT", d["id"], no)
            vl.append({"role": inventory_role(m), "debit": amount, "narration": m["name"]})
            vl.append({"role": consumption_role(m, tgt), "credit": amount, "boq_item_id": boq,
                       "equipment_id": eq, "narration": m["name"]})
    vid = post_voucher(c, u, "journal", d["date"], "Material return %s" % no, vl, project_id=d["project_id"],
                       source="return", source_id=d["id"]) if vl else None
    upd(c, "returns", d["id"], {"status": "posted", "no": no, "voucher_id": vid})
    audit(c, u, "post", "returns", d["id"], {"no": no})
    return {"no": no}


@api("return.cancel", "inventory", "approve")
def return_cancel(c, u, a):
    d = load_doc(c, "return", a["id"])
    if d["status"] != "posted":
        raise ApiError("Only posted returns can be cancelled.")
    for l in d["lines"]:
        if l["condition"] in STOCKABLE:
            stock_out(c, u, d["project_id"], d["store_id"], l["material_id"], l["qty"], today(), "MRT-CANCEL",
                      d["id"], d["no"], rate=l["rate"])
        if l["issue_line_id"]:
            c.execute("UPDATE issue_lines SET returned_qty=returned_qty-? WHERE id=?", (l["qty"], l["issue_line_id"]))
    reverse_voucher(c, u, d["voucher_id"], today(), "Return cancelled")
    upd(c, "returns", d["id"], {"status": "cancelled"})
    return True


# ───────────────────────── inventory: transfers ─────────────────────────
@api("transfer.dispatch", "inventory", "edit")
def transfer_dispatch(c, u, a):
    d = draft_doc(c, "transfer", a["id"])
    need(d, "from_project", "from_store", "to_project", "to_store", "date")
    tr = transit_store(c, d["from_project"])
    no = next_no(c, "MTN", d["date"])
    for l in d["lines"]:
        rate, _v = stock_out(c, u, d["from_project"], d["from_store"], l["material_id"], l["qty"], d["date"],
                             "MTN-OUT", d["id"], no)
        stock_in(c, u, d["from_project"], tr, l["material_id"], l["qty"], rate, d["date"], "MTN-TRANSIT", d["id"], no)
        upd(c, "transfer_lines", l["id"], {"rate": r4(rate)})
    upd(c, "transfers", d["id"], {"status": "in_transit", "no": no})
    audit(c, u, "dispatch", "transfers", d["id"], {"no": no})
    return {"no": no}


@api("transfer.receive", "inventory", "edit")
def transfer_receive(c, u, a):
    d = load_doc(c, "transfer", a["id"])
    if d["status"] != "in_transit":
        raise ApiError("Only dispatched transfers can be received.")
    rd = a.get("date") or today()
    if rd < d["date"]:
        raise ApiError("Receipt date cannot be before dispatch date.")
    got = {int(k): num(v) for k, v in (a.get("received") or {}).items()}
    tr = transit_store(c, d["from_project"])
    vl = []
    for l in d["lines"]:
        m = material(c, l["material_id"])
        rq = got.get(l["id"], l["qty"])
        if rq < 0 or rq > l["qty"] + EPS:
            raise ApiError("%s: received quantity must be between 0 and %s." % (m["name"], l["qty"]))
        stock_out(c, u, d["from_project"], tr, m["id"], l["qty"], rd, "MTN-TRANSIT", d["id"], d["no"], rate=l["rate"])
        v_in = stock_in(c, u, d["to_project"], d["to_store"], m["id"], rq, l["rate"], rd, "MTN-IN", d["id"], d["no"])
        upd(c, "transfer_lines", l["id"], {"received_qty": rq})
        role = inventory_role(m)
        if d["to_project"] != d["from_project"] and v_in:
            vl.append({"role": role, "debit": v_in, "project_id": d["to_project"], "narration": m["name"]})
            vl.append({"role": role, "credit": v_in, "project_id": d["from_project"], "narration": m["name"]})
        short = r2((l["qty"] - rq) * l["rate"])
        if short > 0:
            vl.append({"role": "inventory_loss", "debit": short, "project_id": d["from_project"],
                       "narration": "Transit shortage " + m["name"]})
            vl.append({"role": role, "credit": short, "project_id": d["from_project"]})
    vid = post_voucher(c, u, "journal", rd, "Stock transfer %s received" % d["no"], vl,
                       project_id=d["to_project"], source="transfer", source_id=d["id"]) if vl else None
    upd(c, "transfers", d["id"], {"status": "received", "received_date": rd, "voucher_id": vid})
    audit(c, u, "receive", "transfers", d["id"], got)
    return True


@api("transfer.cancel", "inventory", "approve")
def transfer_cancel(c, u, a):
    d = load_doc(c, "transfer", a["id"])
    if d["status"] != "in_transit":
        raise ApiError("Only transfers still in transit can be cancelled.")
    tr = transit_store(c, d["from_project"])
    for l in d["lines"]:
        stock_out(c, u, d["from_project"], tr, l["material_id"], l["qty"], today(), "MTN-CANCEL", d["id"], d["no"],
                  rate=l["rate"])
        stock_in(c, u, d["from_project"], d["from_store"], l["material_id"], l["qty"], l["rate"], today(),
                 "MTN-CANCEL", d["id"], d["no"])
    upd(c, "transfers", d["id"], {"status": "cancelled"})
    return True


# ───────────────────────── inventory: stock count & opening ─────────────────────────
@api("count.prefill", "inventory", "view")
def count_prefill(c, u, a):
    rows = q(c, "SELECT b.material_id, b.qty, b.value FROM stock_balances b JOIN materials m ON m.id=b.material_id "
                "WHERE b.project_id=? AND b.store_id=? AND ABS(b.qty)>0.0001 ORDER BY m.code",
             (a["project_id"], a["store_id"]))
    return [{"material_id": r["material_id"], "system_qty": r4(r["qty"]), "counted_qty": r4(r["qty"])} for r in rows]


@api("count.post", "inventory", "approve")
def count_post(c, u, a):
    d = draft_doc(c, "count", a["id"])
    need(d, "project_id", "store_id", "date")
    check_store(c, d["store_id"], d["project_id"])
    no = next_no(c, "PSV", d["date"])
    vl = []
    for l in d["lines"]:
        m = material(c, l["material_id"])
        bq, bv = balance(c, d["project_id"], d["store_id"], m["id"])
        diff = r4(num(l["counted_qty"]) - bq)
        rate = (bv / bq) if bq > EPS else m["standard_rate"]
        upd(c, "count_lines", l["id"], {"system_qty": r4(bq), "rate": r4(rate)})
        if diff > EPS:
            v = stock_in(c, u, d["project_id"], d["store_id"], m["id"], diff, rate, d["date"], "PSV", d["id"], no)
            vl += [{"role": inventory_role(m), "debit": v, "narration": m["name"]},
                   {"role": "stock_gain", "credit": v, "narration": "Count gain " + m["name"]}]
        elif diff < -EPS:
            _r, v = stock_out(c, u, d["project_id"], d["store_id"], m["id"], -diff, d["date"], "PSV", d["id"], no)
            vl += [{"role": "inventory_loss", "debit": v, "narration": "Count loss " + m["name"]},
                   {"role": inventory_role(m), "credit": v, "narration": m["name"]}]
    vid = post_voucher(c, u, "journal", d["date"], "Physical stock verification %s" % no, vl,
                       project_id=d["project_id"], source="count", source_id=d["id"]) if vl else None
    upd(c, "stock_counts", d["id"], {"status": "posted", "no": no, "voucher_id": vid})
    audit(c, u, "post", "stock_counts", d["id"], {"no": no})
    return {"no": no}


@api("stock.opening", "inventory", "approve")
def stock_opening(c, u, a):
    need(a, "project_id", "store_id", "date")
    check_store(c, a["store_id"], a["project_id"])
    lines = [l for l in (a.get("lines") or []) if l.get("material_id") and num(l.get("qty")) > 0]
    if not lines:
        raise ApiError("Add at least one line with quantity.")
    no = next_no(c, "OPN", a["date"])
    by_role = {}
    for l in lines:
        m = material(c, int(l["material_id"]))
        v = stock_in(c, u, int(a["project_id"]), int(a["store_id"]), m["id"], num(l["qty"]), num(l.get("rate")),
                     a["date"], "OPENING", 0, no)
        by_role[inventory_role(m)] = by_role.get(inventory_role(m), 0) + v
    vl = [{"role": r, "debit": v} for r, v in by_role.items()]
    vl.append({"role": "capital", "credit": r2(sum(by_role.values())), "narration": "Opening stock"})
    post_voucher(c, u, "journal", a["date"], "Opening stock %s" % no, vl, project_id=int(a["project_id"]),
                 source="opening_stock")
    audit(c, u, "opening_stock", "stock_ledger", None, a)
    return {"no": no, "lines": len(lines)}


# ───────────────────────── inventory: reports ─────────────────────────
@api("stock.available", "inventory", "view")
def stock_available(c, u, a):
    rows = q(c, "SELECT material_id, qty, value FROM stock_balances WHERE project_id=? AND store_id=?",
             (a.get("project_id"), a.get("store_id")))
    return {str(r["material_id"]): {"qty": r4(r["qty"]), "rate": r4(r["value"] / r["qty"]) if r["qty"] > EPS else 0}
            for r in rows}


@api("stock.report", "inventory", "view")
def stock_report(c, u, a):
    where, p = ["ABS(b.qty)>0.0001 OR ABS(b.value)>0.005"], []
    sql = ("SELECT b.*, m.code, m.name, m.category, m.unit, m.reorder_level, m.min_level, s.name store_name, "
           "s.type store_type, pr.code project_code FROM stock_balances b JOIN materials m ON m.id=b.material_id "
           "JOIN stores s ON s.id=b.store_id JOIN projects pr ON pr.id=b.project_id")
    cond = ["(" + where[0] + ")"]
    if a.get("project_id"):
        cond.append("b.project_id=?")
        p.append(a["project_id"])
    if a.get("store_id"):
        cond.append("b.store_id=?")
        p.append(a["store_id"])
    if a.get("category"):
        cond.append("m.category=?")
        p.append(a["category"])
    rows = q(c, sql + " WHERE " + " AND ".join(cond) + " ORDER BY pr.code, s.name, m.code", p)
    for r in rows:
        r["qty"] = r4(r["qty"])
        r["rate"] = r4(r["value"] / r["qty"]) if r["qty"] > EPS else 0
    group = a.get("group") or "store"
    if group == "material":
        agg = {}
        for r in rows:
            if r["store_type"] == "transit" and not a.get("include_transit"):
                continue
            k = (r["project_id"], r["material_id"])
            x = agg.setdefault(k, dict(r, qty=0, value=0, store_name="All stores"))
            x["qty"] += r["qty"]
            x["value"] += r["value"]
        rows = list(agg.values())
        for r in rows:
            r["qty"] = r4(r["qty"])
            r["value"] = r2(r["value"])
            r["rate"] = r4(r["value"] / r["qty"]) if r["qty"] > EPS else 0
            r["flag"] = "negative" if r["qty"] < -EPS else ("reorder" if r["reorder_level"] and
                                                            r["qty"] <= r["reorder_level"] else "")
    return rows


@api("stock.card", "inventory", "view")
def stock_card(c, u, a):
    need(a, "project_id", "material_id")
    p = [a["project_id"], a["material_id"]]
    cond = "project_id=? AND material_id=?"
    if a.get("store_id"):
        cond += " AND store_id=?"
        p.append(a["store_id"])
    else:
        cond += " AND store_id NOT IN (SELECT id FROM stores WHERE type='transit')"
    frm = a.get("from") or "0000-00-00"
    op = q1(c, "SELECT SUM(qty_in-qty_out) q, SUM(value_in-value_out) v FROM stock_ledger WHERE " + cond +
            " AND date<?", p + [frm])
    rows = q(c, "SELECT l.*, s.name store_name FROM stock_ledger l JOIN stores s ON s.id=l.store_id WHERE " +
             cond.replace("project_id", "l.project_id").replace("material_id", "l.material_id")
             .replace("store_id", "l.store_id") +
             " AND l.date>=? AND l.date<=? ORDER BY l.date, l.id", p + [frm, a.get("to") or "9999-12-31"])
    bq, bv = (op["q"] or 0), (op["v"] or 0)
    for r in rows:
        bq += r["qty_in"] - r["qty_out"]
        bv += r["value_in"] - r["value_out"]
        r["bal_qty"], r["bal_value"] = r4(bq), r2(bv)
    return {"opening_qty": r4(op["q"] or 0), "opening_value": r2(op["v"] or 0), "rows": rows}


@api("stock.reorder_run", "inventory", "edit")
def reorder_run(c, u, a):
    return auto_reorder(c, u)


def auto_reorder(c, u):
    created = []
    mats = q(c, "SELECT * FROM materials WHERE active=1 AND reorder_level>0")
    for p in q(c, "SELECT id FROM projects WHERE status='active'"):
        used = {r["material_id"] for r in q(c, "SELECT DISTINCT material_id FROM stock_ledger WHERE project_id=?",
                                            (p["id"],))}
        lines = []
        for m in mats:
            if m["id"] not in used:
                continue
            have = project_available(c, p["id"], m["id"])
            if have > m["reorder_level"]:
                continue
            open_ = val(c, "SELECT COUNT(*) FROM mrq_lines l JOIN mrq r ON r.id=l.mrq_id WHERE r.project_id=? AND "
                           "l.material_id=? AND r.status IN ('draft','submitted','approved','partially_issued')",
                        (p["id"], m["id"]))
            open_ += val(c, "SELECT COUNT(*) FROM pr_lines l JOIN pr r ON r.id=l.pr_id WHERE r.project_id=? AND "
                            "l.material_id=? AND r.status IN ('draft','submitted','approved','partially_ordered')",
                         (p["id"], m["id"]))
            if open_:
                continue
            qty = m["reorder_qty"] or max(m["reorder_level"] * 2 - have, m["reorder_level"])
            lines.append((m, r4(qty)))
        if lines:
            store = val(c, "SELECT id FROM stores WHERE project_id=? AND type='main'", (p["id"],))
            no = next_no(c, "MRQ", today())
            mid = ins(c, "mrq", {"no": no, "project_id": p["id"], "date": today(), "store_id": store,
                                 "requested_by": "Auto reorder", "status": "submitted", "auto": 1,
                                 "remarks": "Stock at or below reorder level", "created_by": u["id"] if u else None})
            for m, qty in lines:
                ins(c, "mrq_lines", {"mrq_id": mid, "material_id": m["id"], "qty": qty})
            created.append(no)
    return {"created": created}


@api("stock.reconciliation", "inventory", "view")
def stock_reconciliation(c, u, a):
    need(a, "project_id")
    rows = q(c, "SELECT mc.*, b.code boq_code, b.description, b.unit boq_unit, b.executed_qty, m.code mat_code, "
                "m.name mat_name, m.unit FROM material_coefficients mc JOIN boq_items b ON b.id=mc.boq_item_id "
                "JOIN materials m ON m.id=mc.material_id WHERE b.project_id=? ORDER BY b.code, m.code",
             (a["project_id"],))
    tol = num(a.get("tolerance") or 3)
    for r in rows:
        issued = val(c, "SELECT SUM(l.qty) FROM issue_lines l JOIN issues i ON i.id=l.issue_id WHERE i.status='posted' "
                        "AND l.boq_item_id=? AND l.material_id=?", (r["boq_item_id"], r["material_id"]))
        returned = val(c, "SELECT SUM(l.qty) FROM return_lines l JOIN returns x ON x.id=l.return_id WHERE "
                          "x.status='posted' AND l.condition IN ('usable','repairable') AND l.boq_item_id=? AND "
                          "l.material_id=?", (r["boq_item_id"], r["material_id"]))
        r["theoretical"] = r4((r["executed_qty"] or 0) * r["qty_per_unit"] * (1 + (r["wastage_pct"] or 0) / 100))
        r["actual"] = r4(issued - returned)
        r["variance"] = r4(r["actual"] - r["theoretical"])
        r["variance_pct"] = round(100 * r["variance"] / r["theoretical"], 2) if r["theoretical"] else None
        r["flag"] = bool(r["variance_pct"] is not None and abs(r["variance_pct"]) > tol) or \
            (not r["theoretical"] and r["actual"] > 0)
    return rows


@api("issue.returnable", "inventory", "view")
def issue_returnable(c, u, a):
    return q(c, "SELECT l.id, l.material_id, l.qty-l.returned_qty open_qty, l.rate, l.boq_item_id, l.equipment_id, "
                "i.no, i.date FROM issue_lines l JOIN issues i ON i.id=l.issue_id WHERE i.status='posted' AND "
                "i.project_id=? AND l.qty-l.returned_qty>0.0001 ORDER BY i.date DESC LIMIT 400", (a["project_id"],))
