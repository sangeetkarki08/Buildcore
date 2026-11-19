"""BuildCore 2.56 "People and payroll" (D1, D2, D4, D5, D6).

* Payroll (Accounts > Payroll): pay details per staff member (basic, site / field / fuel / mobile / other allowances,
  SSF or provident fund, CIT, insurance, married or single, bank account), monthly inputs (unpaid days, overtime,
  festival allowance, advance recovery, other deductions), Nepal income-tax slabs (editable, check them every budget
  year), salary advances, payslips and the bank transfer list.  A run posts through the existing salary run (same
  tables, same "Pay salaries" step), so everything that reads salary runs keeps working.
  Switch py_on (Setup & switches): OFF on companies that already have data; until it is on, the Staff salaries tab
  posts as before (monthly rate, flat 1 % tax) and the Payroll page only shows what the new run would post.
* Site attendance (Site work > Site attendance): staff and workers marked present / half / absent / leave per day and
  project, with overtime.  Feeds the payroll (unpaid days, overtime, and the split of each salary over the projects
  the person worked on, so site staff cost lands on the project instead of head office) and the
  "Attendance against DPR" check (heads present against heads on the DPR per day).
* One people list (Masters > Staff > One people list): each staff member linked to the worker card (Workers & safety)
  and the user login of the same person, with suggestions by name and phone.
Nothing that is already posted is changed.
"""
import json
from datetime import date, timedelta

import core
from core import ApiError, audit, ins, now, q, q1, setting, today, upd, val
import api_inventory as inv
from api_inventory import api

VERSION = "2.56.0"
FLAG = "_bco256"
EPS = 0.005

SCHEMA = """
CREATE TABLE IF NOT EXISTS py_staff(staff_id INTEGER PRIMARY KEY, marital TEXT DEFAULT 'single', female INTEGER DEFAULT 0, basic REAL,
  allow_site REAL DEFAULT 0, allow_field REAL DEFAULT 0, allow_fuel REAL DEFAULT 0, allow_mobile REAL DEFAULT 0, allow_other REAL DEFAULT 0,
  scheme TEXT DEFAULT 'none', cit REAL DEFAULT 0, life_ins REAL DEFAULT 0, health_ins REAL DEFAULT 0, pan TEXT, bank_name TEXT,
  bank_acno TEXT, worker_id INTEGER, user_id INTEGER, updated TEXT);
CREATE TABLE IF NOT EXISTS py_month(id INTEGER PRIMARY KEY, month TEXT NOT NULL, staff_id INTEGER NOT NULL, unpaid_days REAL,
  ot_hours REAL, festival INTEGER DEFAULT 0, advance_recovery REAL, other_deduction REAL DEFAULT 0, note TEXT, UNIQUE(month, staff_id));
CREATE TABLE IF NOT EXISTS py_run_lines(id INTEGER PRIMARY KEY, run_id INTEGER, staff_id INTEGER, detail TEXT);
CREATE INDEX IF NOT EXISTS ix_py_rl ON py_run_lines(run_id);
CREATE TABLE IF NOT EXISTS py_advances(id INTEGER PRIMARY KEY, staff_id INTEGER, date TEXT, amount REAL, monthly REAL, note TEXT,
  voucher_id INTEGER, created_by INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS py_attendance(id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, date TEXT NOT NULL, kind TEXT NOT NULL,
  person_id INTEGER NOT NULL, trade TEXT, status TEXT NOT NULL, hours REAL, ot_hours REAL DEFAULT 0, user_id INTEGER, ts TEXT,
  UNIQUE(project_id, date, kind, person_id));
CREATE INDEX IF NOT EXISTS ix_py_att ON py_attendance(kind, person_id, date);
"""

NEW_ROLES = [("1215", "Salary Advances", "asset", "A3", "salary_advance"),
             ("2106", "Provident Fund Payable", "liability", "L2", "pf_payable"),
             ("2107", "Gratuity Payable", "liability", "L2", "gratuity_payable"),
             ("2108", "CIT Payable", "liability", "L2", "cit_payable"),
             ("2109", "Salary Deductions Payable", "liability", "L2", "salary_deduction")]

# Nepal, employment income, annual (Income Tax Act 2058 schedule 1 as amended by recent Finance Acts).
DEFAULT_SLABS = {
    "single": [[500000, 1], [200000, 10], [300000, 20], [1000000, 30], [3000000, 36], [None, 39]],
    "married": [[600000, 1], [200000, 10], [300000, 20], [900000, 30], [3000000, 36], [None, 39]],
}
DEFAULTS = {"py_ssf_ee": 11, "py_ssf_er": 20, "py_pf_ee": 10, "py_pf_er": 10, "py_gratuity": 8.33, "py_ret_cap": 500000,
            "py_life_cap": 40000, "py_health_cap": 20000, "py_female_rebate": 10, "py_ot_factor": 1.5, "py_hours_day": 8,
            "py_days_month": 30}
STATUSES = {"P": ("Present", 1.0), "H": ("Half day", 0.5), "A": ("Absent", 0.0), "L": ("Paid leave", 0.0), "O": ("Weekly off / holiday", 0.0)}


def _f(x, d=0.0):
    try:
        return float(x) if x not in (None, "") else d
    except (TypeError, ValueError):
        return d


def r2(x):
    return round(_f(x) + 0.0, 2)


def _set(c, k, v):
    c.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))


def _cfg(c, k):
    return _f(setting(c, k), DEFAULTS[k])


def on(c):
    return setting(c, "py_on") == "1"


def slabs(c):
    try:
        s = json.loads(setting(c, "py_slabs") or "")
        if s.get("single") and s.get("married"):
            return s
    except (ValueError, AttributeError):
        pass
    return DEFAULT_SLABS


def _M():
    import api_money
    return api_money


def _window(c, m):
    return _M()._window(c, m)


def _role(c, role):
    return _M()._role_acc(c, role)


def _need(c, u, module, action, what):
    if not core.can(u, module, action):
        raise ApiError("You need the %s %s right to %s." % (module, action, what))


# ───────────────────────── tax ─────────────────────────
def annual_tax(c, taxable, marital, ssf, female):
    """Tax on annual taxable employment income.  SSF contributors do not pay the 1 % social security tax."""
    left, tax, rows = max(0.0, taxable), 0.0, []
    for i, (width, rate) in enumerate(slabs(c)["married" if marital == "married" else "single"]):
        part = left if width is None else min(left, _f(width))
        if part <= 0:
            break
        r = 0.0 if (i == 0 and ssf) else _f(rate)
        tax += part * r / 100
        rows.append({"amount": r2(part), "rate": r})
        left -= part
    rebate = 0.0
    if female and marital != "married":
        rebate = tax * _cfg(c, "py_female_rebate") / 100
    return r2(tax - rebate), rows, r2(rebate)


# ───────────────────────── attendance ─────────────────────────
def att_summary(c, kind, person_id, frm, to):
    rows = q(c, "SELECT project_id, status, COUNT(*) n, SUM(COALESCE(ot_hours,0)) ot FROM py_attendance WHERE kind=? AND person_id=? "
                "AND date BETWEEN ? AND ? GROUP BY project_id, status", (kind, person_id, frm, to))
    by_p, absent, ot, marked = {}, 0.0, 0.0, 0
    for r in rows:
        w = STATUSES.get(r["status"], ("", 0))[1]
        marked += r["n"]
        if w:
            by_p[r["project_id"]] = by_p.get(r["project_id"], 0) + w * r["n"]
        if r["status"] == "A":
            absent += r["n"]
        if r["status"] == "H":
            absent += 0.5 * r["n"]
        ot += _f(r["ot"])
    return {"by_project": by_p, "absent": absent, "ot": ot, "marked": marked}


# ───────────────────────── payroll lines ─────────────────────────
def _details(c):
    return {r["staff_id"]: r for r in q(c, "SELECT * FROM py_staff")}


def pay_lines(c, m):
    frm, to = _window(c, m)
    days = (date.fromisoformat(to) - date.fromisoformat(frm)).days + 1
    det = _details(c)
    inputs = {r["staff_id"]: r for r in q(c, "SELECT * FROM py_month WHERE month=?", (m,))}
    see, ser, pee, per, gr = (_cfg(c, k) for k in ("py_ssf_ee", "py_ssf_er", "py_pf_ee", "py_pf_er", "py_gratuity"))
    out = []
    for s in q(c, "SELECT * FROM staff WHERE COALESCE(active,1)=1 ORDER BY code"):
        d = det.get(s["id"]) or {}
        basic = _f(d.get("basic"), _f(s["monthly_rate"]))
        if basic <= 0:
            continue
        allow = {k: _f(d.get("allow_" + k)) for k in ("site", "field", "fuel", "mobile", "other")}
        inp = inputs.get(s["id"]) or {}
        att = att_summary(c, "staff", s["id"], frm, to)
        unpaid = _f(inp.get("unpaid_days"), att["absent"]) if inp.get("unpaid_days") is not None else att["absent"]
        unpaid = min(days, max(0.0, unpaid))
        ot_h = _f(inp.get("ot_hours")) if inp.get("ot_hours") is not None else att["ot"]
        share = (days - unpaid) / days if days else 1
        e_basic = r2(basic * share)
        e_allow = r2(sum(allow.values()) * share)
        ot_rate = basic / _cfg(c, "py_days_month") / _cfg(c, "py_hours_day") * _cfg(c, "py_ot_factor")
        ot_amt = r2(ot_h * ot_rate)
        fest = r2(basic) if inp.get("festival") else 0.0
        gross = r2(e_basic + e_allow + ot_amt + fest)
        scheme = d.get("scheme") or "none"
        ee = r2(e_basic * (see if scheme == "ssf" else pee if scheme == "pf" else 0) / 100)
        er = r2(e_basic * (ser if scheme == "ssf" else per if scheme == "pf" else 0) / 100)
        grat = r2(e_basic * gr / 100) if scheme != "ssf" else 0.0          # the SSF employer share already holds the gratuity
        cit = r2(_f(d.get("cit")))
        # tax: this month projected over the year (festival once), less allowed deductions
        annual = (gross - fest) * 12 + fest + er * 12
        ret = min((ee + er + cit) * 12, annual / 3, _cfg(c, "py_ret_cap"))
        ins_d = min(_f(d.get("life_ins")), _cfg(c, "py_life_cap")) + min(_f(d.get("health_ins")), _cfg(c, "py_health_cap"))
        taxable = max(0.0, annual - ret - ins_d)
        atax, brk, rebate = annual_tax(c, taxable, d.get("marital"), scheme == "ssf", d.get("female"))
        tax = r2(atax / 12)
        adv_open = advance_open(c, s["id"], to)
        adv = inp.get("advance_recovery")
        if adv is None:
            adv = min(adv_open, sum(_f(x["monthly"]) for x in q(c, "SELECT monthly FROM py_advances WHERE staff_id=? AND date<=?", (s["id"], to))))
        adv = r2(min(_f(adv), adv_open))
        other = r2(_f(inp.get("other_deduction")))
        net = r2(gross - ee - cit - tax - adv - other)
        cost = r2(gross + er + grat)
        split = att["by_project"]
        tot = sum(split.values())
        if tot > 0:
            parts = [{"project_id": p, "share": v / tot} for p, v in sorted(split.items(), key=lambda x: (x[0] is None, x[0] or 0))]
            basis = "attendance (%s days)" % ("%g" % tot)
        else:
            parts = [{"project_id": s["project_id"], "share": 1.0}]
            basis = "staff card project" if s["project_id"] else "head office (no project, no attendance)"
        out.append({"staff_id": s["id"], "code": s["code"], "name": s["name"], "designation": s["designation"], "project_id": s["project_id"],
                    "project": _M()._pcode(c, s["project_id"]), "days": days, "unpaid_days": unpaid, "basic": r2(basic), "earned_basic": e_basic,
                    "allowances": e_allow, "ot_hours": r2(ot_h), "ot": ot_amt, "festival": fest, "gross": gross, "scheme": scheme,
                    "ee": ee, "er": er, "gratuity": grat, "cit": cit, "tax": tax, "taxable_annual": r2(taxable), "annual_tax": atax,
                    "rebate": rebate, "advance": adv, "advance_open": r2(adv_open), "other": other, "net": net, "cost": cost,
                    "split": [{"project_id": x["project_id"], "project": _M()._pcode(c, x["project_id"]) or "Head office", "share": round(x["share"], 4)} for x in parts],
                    "split_basis": basis, "bank_name": d.get("bank_name"), "bank_acno": d.get("bank_acno"), "pan": d.get("pan"),
                    "marital": d.get("marital") or "single", "has_details": bool(d), "attendance_marked": att["marked"]})
    return {"month": m, "from": frm, "to": to, "days": days, "lines": out}


def advance_open(c, staff_id, upto=None):
    given = _f(val(c, "SELECT SUM(amount) FROM py_advances WHERE staff_id=? AND date<=?", (staff_id, upto or "9999")))
    if not given:
        return 0.0
    back = 0.0
    for r in q(c, "SELECT l.detail FROM py_run_lines l JOIN mn_salary_run r ON r.id=l.run_id WHERE l.staff_id=?", (staff_id,)):
        try:
            back += _f(json.loads(r["detail"]).get("advance"))
        except ValueError:
            pass
    return max(0.0, given - back)


# ───────────────────────── posting ─────────────────────────
def post_run(c, u, m, dt=None):
    M = _M()
    if val(c, "SELECT COUNT(*) FROM mn_salary_run WHERE month=?", (m,)):
        raise ApiError("Salaries for %s are already run." % M._month_label(c, m))
    d = pay_lines(c, m)
    ls = d["lines"]
    if not ls:
        raise ApiError("No active staff with a basic salary.")
    dt = dt or d["to"]
    vl = []
    for x in ls:
        nm = "Salary %s" % x["name"]
        rem_cost, rem_net = x["cost"], x["net"]
        for i, sp in enumerate(x["split"]):
            last = i == len(x["split"]) - 1
            cost = rem_cost if last else r2(x["cost"] * sp["share"])
            net = rem_net if last else r2(x["net"] * sp["share"])
            rem_cost, rem_net = r2(rem_cost - cost), r2(rem_net - net)
            if sp["project_id"]:
                vl.append({"role": "labour_cost", "debit": cost, "project_id": sp["project_id"], "narration": nm})
            else:
                vl.append({"account_id": _role(c, "salary_ho"), "debit": cost, "narration": nm})
            vl.append({"role": "payroll_payable", "credit": net, "project_id": sp["project_id"], "narration": nm})
            sp["cost"], sp["net"] = cost, net
    tot = lambda k: r2(sum(x[k] for x in ls))
    ssf = r2(sum(x["ee"] + x["er"] for x in ls if x["scheme"] == "ssf"))
    pf = r2(sum(x["ee"] + x["er"] for x in ls if x["scheme"] == "pf"))
    vl += [{"role": "tds_payable", "credit": tot("tax"), "narration": "Income tax on salaries (TDS)"},
           {"account_id": _role(c, "ssf_payable"), "credit": ssf, "narration": "SSF"},
           {"account_id": _role(c, "pf_payable"), "credit": pf, "narration": "Provident fund"},
           {"account_id": _role(c, "gratuity_payable"), "credit": tot("gratuity"), "narration": "Gratuity provision"},
           {"account_id": _role(c, "cit_payable"), "credit": tot("cit"), "narration": "CIT"},
           {"account_id": _role(c, "salary_advance"), "credit": tot("advance"), "narration": "Salary advances recovered"},
           {"account_id": _role(c, "salary_deduction"), "credit": tot("other"), "narration": "Other salary deductions"}]
    head = {"gross": tot("gross"), "tax": tot("tax"), "ssf_employee": r2(sum(x["ee"] for x in ls if x["scheme"] == "ssf")),
            "ssf_employer": r2(sum(x["er"] for x in ls if x["scheme"] == "ssf")), "net": tot("net")}
    rid = ins(c, "mn_salary_run", dict(head, month=m, date=dt, status="posted", created_by=u["id"], ts=now()))
    vid = M._post(c, u, "journal", dt, "Staff salaries %s (payroll)" % M._month_label(c, m), vl, source="mn_salary", source_id=rid)
    upd(c, "mn_salary_run", rid, {"voucher_id": vid})
    for x in ls:
        for sp in x["split"]:
            ins(c, "mn_salary_lines", {"run_id": rid, "staff_id": x["staff_id"], "name": x["name"], "project_id": sp["project_id"],
                                       "gross": r2(x["gross"] * sp["share"]), "tax": r2(x["tax"] * sp["share"]),
                                       "ssf_employee": r2(x["ee"] * sp["share"]) if x["scheme"] == "ssf" else 0,
                                       "ssf_employer": r2(x["er"] * sp["share"]) if x["scheme"] == "ssf" else 0, "net": sp["net"]})
        ins(c, "py_run_lines", {"run_id": rid, "staff_id": x["staff_id"], "detail": json.dumps(x)})
    audit(c, u, "payroll_run", "mn_salary_run", rid, {"month": m, "net": head["net"]})
    return dict(head, id=rid, voucher_id=vid)


# ───────────────────────── actions: payroll ─────────────────────────
def _month(c, a):
    return (a.get("month") or _M()._default_month(c))[:7]


@api("py.month", "accounts", "view")
def py_month(c, u, a):
    m = _month(c, a)
    d = pay_lines(c, m)
    M = _M()
    run = q1(c, "SELECT r.*, v.no vno FROM mn_salary_run r LEFT JOIN vouchers v ON v.id=r.voucher_id WHERE r.month=?", (m,))
    d.update({"label": M._month_label(c, m), "months": M._month_list(c), "on": on(c), "run": run,
              "is_payroll_run": bool(run and val(c, "SELECT COUNT(*) FROM py_run_lines WHERE run_id=?", (run["id"],))),
              "inputs": {r["staff_id"]: r for r in q(c, "SELECT * FROM py_month WHERE month=?", (m,))},
              "can_edit": core.can(u, "accounts", "edit")})
    if d["is_payroll_run"]:
        d["lines"] = [json.loads(r["detail"]) for r in q(c, "SELECT detail FROM py_run_lines WHERE run_id=? ORDER BY id", (run["id"],))]
    d["old_run"] = bool(run) and not d["is_payroll_run"]
    for k in ("gross", "tax", "ee", "er", "gratuity", "cit", "advance", "other", "net", "cost"):
        d.setdefault("total", {})[k] = r2(sum(x[k] for x in d["lines"]))
    return d


@api("py.input_save", "accounts", "edit")
def py_input_save(c, u, a):
    m = _month(c, a)
    if val(c, "SELECT COUNT(*) FROM mn_salary_run WHERE month=?", (m,)):
        raise ApiError("Salaries for this month are already run.")
    n = 0
    for r in a.get("rows") or []:
        sid = int(r["staff_id"])
        row = {"month": m, "staff_id": sid}
        for k in ("unpaid_days", "ot_hours", "advance_recovery"):
            row[k] = None if r.get(k) in (None, "") else _f(r.get(k))
        row["other_deduction"] = _f(r.get("other_deduction"))
        row["festival"] = 1 if r.get("festival") in (1, "1", True) else 0
        row["note"] = r.get("note") or None
        ex = q1(c, "SELECT id FROM py_month WHERE month=? AND staff_id=?", (m, sid))
        if ex:
            upd(c, "py_month", ex["id"], row)
        else:
            ins(c, "py_month", row)
        n += 1
    audit(c, u, "save", "py_month", None, {"month": m, "rows": n})
    return {"saved": n}


@api("py.run", "accounts", "edit")
def py_run(c, u, a):
    if not on(c):
        raise ApiError("The new payroll is off on this company. Accounts turns it on in Payroll > Settings (or Setup & switches).")
    return post_run(c, u, _month(c, a), a.get("date"))


@api("py.staff", "accounts", "view")
def py_staff_list(c, u, a):
    det = _details(c)
    rows = []
    for s in q(c, "SELECT * FROM staff ORDER BY COALESCE(active,1) DESC, code"):
        d = det.get(s["id"]) or {}
        rows.append(dict(d, staff_id=s["id"], code=s["code"], name=s["name"], designation=s["designation"], active=s["active"],
                         monthly_rate=s["monthly_rate"], project=_M()._pcode(c, s["project_id"]), basic=d.get("basic") if d else None,
                         has_details=bool(d), advance_open=r2(advance_open(c, s["id"]))))
    return {"rows": rows}


@api("py.staff_save", "accounts", "edit")
def py_staff_save(c, u, a):
    sid = int(a["staff_id"])
    if not q1(c, "SELECT id FROM staff WHERE id=?", (sid,)):
        raise ApiError("Staff member not found.")
    row = {"staff_id": sid, "updated": now()}
    for k in ("basic", "allow_site", "allow_field", "allow_fuel", "allow_mobile", "allow_other", "cit", "life_ins", "health_ins"):
        if k in a:
            row[k] = None if (k == "basic" and a.get(k) in (None, "")) else _f(a.get(k))
    for k in ("pan", "bank_name", "bank_acno"):
        if k in a:
            row[k] = (a.get(k) or "").strip() or None
    if "marital" in a:
        row["marital"] = "married" if a.get("marital") == "married" else "single"
    if "female" in a:
        row["female"] = 1 if a.get("female") in (1, "1", True) else 0
    if "scheme" in a:
        if a["scheme"] not in ("ssf", "pf", "none"):
            raise ApiError("Retirement scheme must be SSF, provident fund or none.")
        row["scheme"] = a["scheme"]
    if q1(c, "SELECT staff_id FROM py_staff WHERE staff_id=?", (sid,)):
        sets = ", ".join("%s=?" % k for k in row if k != "staff_id")
        c.execute("UPDATE py_staff SET %s WHERE staff_id=?" % sets, [row[k] for k in row if k != "staff_id"] + [sid])
    else:
        cols = list(row)
        c.execute("INSERT INTO py_staff(%s) VALUES(%s)" % (",".join(cols), ",".join("?" * len(cols))), [row[k] for k in cols])
    audit(c, u, "save", "py_staff", sid, {k: v for k, v in row.items() if k not in ("bank_acno", "pan")})
    return {"staff_id": sid}


@api("py.advance_give", "accounts", "edit")
def py_advance_give(c, u, a):
    M = _M()
    sid = int(a["staff_id"])
    s = q1(c, "SELECT * FROM staff WHERE id=?", (sid,))
    if not s:
        raise ApiError("Staff member not found.")
    amt = r2(a.get("amount"))
    if amt <= 0:
        raise ApiError("Enter the advance amount.")
    bank = M._money_acc(c, a.get("bank_account_id"))
    dt = a.get("date") or today()
    vid = M._post(c, u, "payment", dt, "Salary advance %s" % s["name"],
                  [{"account_id": _role(c, "salary_advance"), "debit": amt, "narration": a.get("note") or "Salary advance"},
                   {"account_id": bank, "credit": amt}], source="py_advance")
    i = ins(c, "py_advances", {"staff_id": sid, "date": dt, "amount": amt, "monthly": r2(a.get("monthly") or amt), "note": a.get("note"),
                               "voucher_id": vid, "created_by": u["id"], "ts": now()})
    audit(c, u, "advance", "py_advances", i, {"amount": amt})
    return {"id": i, "voucher_id": vid}


@api("py.advances", "accounts", "view")
def py_advances(c, u, a):
    rows = q(c, "SELECT a.*, s.code, s.name, v.no vno FROM py_advances a JOIN staff s ON s.id=a.staff_id LEFT JOIN vouchers v ON v.id=a.voucher_id ORDER BY a.date DESC, a.id DESC")
    for r in rows:
        r["open"] = r2(advance_open(c, r["staff_id"]))
    return {"rows": rows}


@api("py.payslips", "accounts", "view")
def py_payslips(c, u, a):
    m = _month(c, a)
    run = q1(c, "SELECT * FROM mn_salary_run WHERE month=?", (m,))
    if run and val(c, "SELECT COUNT(*) FROM py_run_lines WHERE run_id=?", (run["id"],)):
        lines = [json.loads(r["detail"]) for r in q(c, "SELECT detail FROM py_run_lines WHERE run_id=? ORDER BY id", (run["id"],))]
        state = "posted" + (", paid " + run["paid_date"] if run.get("paid_date") else "")
    else:
        lines = pay_lines(c, m)["lines"]
        state = "posted by the earlier salary run: these payslips show the full payroll calculation, not what was paid" if run else "draft (not posted)"
    if a.get("staff_id"):
        lines = [x for x in lines if x["staff_id"] == int(a["staff_id"])]
    co = q1(c, "SELECT value FROM settings WHERE key='company_name'")
    return {"month": m, "label": _M()._month_label(c, m), "state": state, "company": co["value"] if co else "", "lines": lines,
            "bank_list": [{"code": x["code"], "name": x["name"], "bank_name": x.get("bank_name") or "", "bank_acno": x.get("bank_acno") or "",
                           "amount": x["net"]} for x in lines if x["net"] > 0]}


@api("py.settings", "accounts", "view")
def py_settings(c, u, a):
    return {"on": on(c), "slabs": slabs(c), "values": {k: _cfg(c, k) for k in DEFAULTS}, "defaults": DEFAULTS,
            "note": "Tax slabs are those of the Finance Act in force when 2.56 was made. Check them each budget (Jestha) and change them here."}


@api("py.settings_save", "accounts", "approve")
def py_settings_save(c, u, a):
    for k in DEFAULTS:
        if k in a and a[k] not in (None, ""):
            _set(c, k, str(_f(a[k])))
    if a.get("slabs"):
        s = a["slabs"]
        for kind in ("single", "married"):
            rows = s.get(kind) or []
            if not rows or rows[-1][0] not in (None, "", 0):
                raise ApiError("The last %s slab must be open-ended (no width)." % kind)
            s[kind] = [[None if (i == len(rows) - 1) else _f(w), _f(r)] for i, (w, r) in enumerate(rows)]
        _set(c, "py_slabs", json.dumps({"single": s["single"], "married": s["married"]}))
    if "on" in a:
        _set(c, "py_on", "1" if a["on"] in (1, "1", True) else "0")
    audit(c, u, "save", "settings", None, {"py": {k: a[k] for k in a if k != "slabs"}})
    return py_settings(c, u, {})


# ───────────────────────── actions: attendance ─────────────────────────
def _people(c, pid):
    staff = q(c, "SELECT id, code, name, designation trade FROM staff WHERE COALESCE(active,1)=1 AND (project_id=? OR id IN "
                 "(SELECT person_id FROM py_attendance WHERE kind='staff' AND project_id=?)) ORDER BY code", (pid, pid))
    workers = q(c, "SELECT id, code, name, trade FROM hs_workers WHERE COALESCE(active,1)=1 AND left_on IS NULL AND project_id=? ORDER BY code, name", (pid,)) \
        if q1(c, "SELECT name FROM sqlite_master WHERE name='hs_workers'") else []
    return staff, workers


@api("py.att_day", "project", "view")
def py_att_day(c, u, a):
    pid = int(a.get("project_id") or 0)
    if not pid:
        raise ApiError("Choose a project.")
    d = a.get("date") or today()
    staff, workers = _people(c, pid)
    marks = {(r["kind"], r["person_id"]): r for r in q(c, "SELECT * FROM py_attendance WHERE project_id=? AND date=?", (pid, d))}
    rows = []
    for kind, lst in (("staff", staff), ("worker", workers)):
        for p in lst:
            mk = marks.get((kind, p["id"])) or {}
            rows.append({"kind": kind, "person_id": p["id"], "code": p["code"], "name": p["name"], "trade": p["trade"],
                         "status": mk.get("status"), "ot_hours": mk.get("ot_hours") or 0})
    dpr = q1(c, "SELECT SUM(l.count) heads FROM dpr_labour l JOIN dpr r ON r.id=l.dpr_id WHERE r.project_id=? AND r.date=?", (pid, d))
    return {"date": d, "project_id": pid, "rows": rows, "statuses": [[k, v[0]] for k, v in STATUSES.items()],
            "dpr_heads": _f(dpr["heads"]) if dpr else 0, "present": sum(STATUSES.get(r["status"] or "", ("", 0))[1] for r in rows),
            "can_edit": core.can(u, "project", "edit")}


@api("py.att_save", "project", "edit")
def py_att_save(c, u, a):
    pid = int(a.get("project_id") or 0)
    d = a.get("date") or today()
    if not pid:
        raise ApiError("Choose a project.")
    if d > today():
        raise ApiError("Attendance cannot be marked for a future date.")
    n = 0
    for r in a.get("rows") or []:
        kind, person = r.get("kind"), int(r.get("person_id") or 0)
        if kind not in ("staff", "worker") or not person:
            continue
        st = r.get("status") or ""
        if not st:
            c.execute("DELETE FROM py_attendance WHERE project_id=? AND date=? AND kind=? AND person_id=?", (pid, d, kind, person))
            continue
        if st not in STATUSES:
            raise ApiError("Unknown attendance mark '%s'." % st)
        if kind == "staff":
            other = q1(c, "SELECT p.code FROM py_attendance a JOIN projects p ON p.id=a.project_id WHERE a.kind='staff' AND a.person_id=? "
                          "AND a.date=? AND a.project_id<>? AND a.status IN ('P','H')", (person, d, pid))
            if other and st in ("P", "H") and STATUSES[st][1] >= 1:
                raise ApiError("%s is already marked present on %s that day." % (r.get("name") or "This person", other["code"]))
        c.execute("INSERT INTO py_attendance(project_id, date, kind, person_id, trade, status, ot_hours, user_id, ts) VALUES(?,?,?,?,?,?,?,?,?) "
                  "ON CONFLICT(project_id, date, kind, person_id) DO UPDATE SET status=excluded.status, ot_hours=excluded.ot_hours, "
                  "trade=excluded.trade, user_id=excluded.user_id, ts=excluded.ts",
                  (pid, d, kind, person, r.get("trade"), st, _f(r.get("ot_hours")), u["id"], now()))
        n += 1
    audit(c, u, "attendance", "py_attendance", None, {"project_id": pid, "date": d, "rows": n})
    return {"saved": n}


@api("py.att_month", "project", "view")
def py_att_month(c, u, a):
    pid = int(a.get("project_id") or 0)
    m = _month(c, a)
    frm, to = _window(c, m)
    rows = q(c, "SELECT a.kind, a.person_id, COALESCE(s.code, w.code) code, COALESCE(s.name, w.name) name, "
                "SUM(a.status='P') p, SUM(a.status='H') hd, SUM(a.status='A') ab, SUM(a.status='L') lv, SUM(a.status='O') off, "
                "SUM(COALESCE(a.ot_hours,0)) ot FROM py_attendance a LEFT JOIN staff s ON a.kind='staff' AND s.id=a.person_id "
                "LEFT JOIN hs_workers w ON a.kind='worker' AND w.id=a.person_id WHERE a.project_id=? AND a.date BETWEEN ? AND ? "
                "GROUP BY a.kind, a.person_id ORDER BY a.kind, code", (pid, frm, to)) \
        if q1(c, "SELECT name FROM sqlite_master WHERE name='hs_workers'") else []
    for r in rows:
        r["days"] = (r["p"] or 0) + 0.5 * (r["hd"] or 0)
    return {"month": m, "label": _M()._month_label(c, m), "from": frm, "to": to, "rows": rows, "months": _M()._month_list(c)}


@api("py.att_vs_dpr", "project", "view")
def py_att_vs_dpr(c, u, a):
    """Heads present by attendance against heads on the DPR (own gangs), day by day (D6)."""
    pid = int(a.get("project_id") or 0)
    m = _month(c, a)
    frm, to = _window(c, m)
    att = {r["date"]: r for r in q(c, "SELECT date, SUM(CASE status WHEN 'P' THEN 1 WHEN 'H' THEN 0.5 ELSE 0 END) heads, COUNT(*) marked "
                                      "FROM py_attendance WHERE project_id=? AND kind='worker' AND date BETWEEN ? AND ? GROUP BY date", (pid, frm, to))}
    dpr = {r["date"]: r for r in q(c, "SELECT r.date, SUM(l.count) heads, SUM(l.amount) amount FROM dpr_labour l JOIN dpr r ON r.id=l.dpr_id "
                                      "WHERE r.project_id=? AND r.date BETWEEN ? AND ? AND l.party_id IS NULL AND r.status<>'void' GROUP BY r.date", (pid, frm, to))}
    rows = []
    for d in sorted(set(att) | set(dpr)):
        a_h = _f((att.get(d) or {}).get("heads"))
        d_h = _f((dpr.get(d) or {}).get("heads"))
        rows.append({"date": d, "attendance": a_h, "dpr": d_h, "difference": r2(d_h - a_h), "dpr_amount": r2((dpr.get(d) or {}).get("amount")),
                     "flag": "no attendance" if d not in att else "no DPR" if d not in dpr else ("DPR higher" if d_h - a_h > 0.5 else "DPR lower" if a_h - d_h > 0.5 else "")})
    paid = _f(val(c, "SELECT SUM(net + advance_recovery + tax + other_deduction) FROM mn_wage_sheet WHERE project_id=? AND month=?", (pid, m)))
    return {"month": m, "label": _M()._month_label(c, m), "rows": rows, "months": _M()._month_list(c),
            "dpr_heads": r2(sum(r["dpr"] for r in rows)), "att_heads": r2(sum(r["attendance"] for r in rows)),
            "dpr_amount": r2(sum(r["dpr_amount"] for r in rows)), "wage_sheet": r2(paid) if paid else None,
            "note": "Workers only (staff are salaried). A DPR count higher than the heads present means wages may be over-stated; lower means gangs worked without being reported."}


# ───────────────────────── actions: one people list ─────────────────────────
def _norm(s):
    return " ".join("".join(ch for ch in (s or "").lower() if ch.isalnum() or ch == " ").split())


@api("py.people", "masters", "view")
def py_people(c, u, a):
    det = _details(c)
    has_w = bool(q1(c, "SELECT name FROM sqlite_master WHERE name='hs_workers'"))
    workers = q(c, "SELECT id, code, name, phone, trade, ssf_no, bank_name, bank_acno FROM hs_workers") if has_w else []
    ucols = [r[1] for r in c.execute("PRAGMA table_info(users)")]
    users = q(c, "SELECT id, username, COALESCE(NULLIF(%s,''), username) full_name, role FROM users" % ("name" if "name" in ucols else "username"))
    wb = {}
    for w in workers:
        wb.setdefault(_norm(w["name"]), []).append(w)
    ub = {}
    for x in users:
        ub.setdefault(_norm(x["full_name"]), []).append(x)
    rows = []
    for s in q(c, "SELECT * FROM staff ORDER BY COALESCE(active,1) DESC, code"):
        d = det.get(s["id"]) or {}
        w = next((x for x in workers if x["id"] == d.get("worker_id")), None)
        us = next((x for x in users if x["id"] == d.get("user_id")), None)
        sw = None if w else next((x for x in wb.get(_norm(s["name"]), [])), None) or \
            next((x for x in workers if s["phone"] and x["phone"] and x["phone"].replace(" ", "")[-8:] == s["phone"].replace(" ", "")[-8:]), None)
        su = None if us else next((x for x in ub.get(_norm(s["name"]), [])), None)
        rows.append({"staff_id": s["id"], "code": s["code"], "name": s["name"], "designation": s["designation"], "phone": s["phone"],
                     "project": _M()._pcode(c, s["project_id"]), "active": s["active"],
                     "worker": w, "user": us, "suggest_worker": sw, "suggest_user": su,
                     "pay_details": bool(d), "bank": bool(d.get("bank_acno") or (w or {}).get("bank_acno"))})
    linked_w = {r["worker"]["id"] for r in rows if r["worker"]}
    return {"rows": rows, "workers_unlinked": len([w for w in workers if w["id"] not in linked_w]), "users": len(users),
            "workers": [{"id": w["id"], "label": (w["code"] or "") + " " + w["name"]} for w in workers],
            "user_list": [{"id": x["id"], "label": x["full_name"] + " (" + x["username"] + ")"} for x in users]}


@api("py.people_link", "masters", "edit")
def py_people_link(c, u, a):
    sid = int(a["staff_id"])
    if not q1(c, "SELECT id FROM staff WHERE id=?", (sid,)):
        raise ApiError("Staff member not found.")
    if not q1(c, "SELECT staff_id FROM py_staff WHERE staff_id=?", (sid,)):
        c.execute("INSERT INTO py_staff(staff_id, updated) VALUES(?, ?)", (sid, now()))
    ch = {}
    for k in ("worker_id", "user_id"):
        if k in a:
            ch[k] = int(a[k]) if a.get(k) else None
    if ch.get("worker_id"):
        w = q1(c, "SELECT * FROM hs_workers WHERE id=?", (ch["worker_id"],))
        if not w:
            raise ApiError("Worker card not found.")
        cur = q1(c, "SELECT bank_name, bank_acno FROM py_staff WHERE staff_id=?", (sid,))
        if not cur["bank_acno"] and w["bank_acno"]:
            ch["bank_name"], ch["bank_acno"] = w["bank_name"], w["bank_acno"]       # one place: the bank account from the worker card
    if ch:
        c.execute("UPDATE py_staff SET %s, updated=? WHERE staff_id=?" % ", ".join("%s=?" % k for k in ch), list(ch.values()) + [now(), sid])
        audit(c, u, "link", "py_staff", sid, {k: v for k, v in ch.items() if k != "bank_acno"})
    return {"staff_id": sid}


# ───────────────────────── existing salary tab follows the switch ─────────────────────────
def _wrap(name, factory):
    cur = inv.FUNCS.get(name)
    if not cur or getattr(cur[0], FLAG, False):
        return
    w = factory(cur[0])
    for f in [x for x in dir(cur[0]) if x.startswith("_bco")]:
        setattr(w, f, getattr(cur[0], f))
    setattr(w, FLAG, True)
    w._orig = cur[0]
    inv.FUNCS[name] = (w, cur[1], cur[2], cur[3])


def _w_salary(orig):
    def mn_salary(c, u, a):
        d = orig(c, u, a)
        if on(c):
            p = pay_lines(c, d["month"])["lines"]
            d["lines"] = [{"staff_id": x["staff_id"], "code": x["code"], "name": x["name"], "project_id": x["project_id"],
                           "project": ", ".join(s["project"] for s in x["split"]), "gross": x["gross"], "tax": x["tax"],
                           "ssf_employee": x["ee"], "ssf_employer": x["er"], "net": x["net"]} for x in p]
            d["payroll"] = True
        return d
    return mn_salary


def _w_salary_run(orig):
    def mn_salary_run(c, u, a):
        if on(c):
            return post_run(c, u, (a.get("month") or "")[:7] or _M()._default_month(c), a.get("date"))
        return orig(c, u, a)
    return mn_salary_run


def init_pay(c):
    c.executescript(SCHEMA)
    used = val(c, "SELECT COUNT(*) FROM vouchers") or val(c, "SELECT COUNT(*) FROM mn_salary_run")
    if not q1(c, "SELECT 1 FROM settings WHERE key='py_on'"):
        _set(c, "py_on", "0" if used else "1")
    c.commit()
    M = _M()
    have = {r[4] for r in M.ROLES}
    for r in NEW_ROLES:
        if r[4] not in have:
            M.ROLES.append(r)
    _wrap("mn.salary", _w_salary)
    _wrap("mn.salary_run", _w_salary_run)
    try:
        import api_safe
        if "py_on" not in {s[0] for s in getattr(api_safe, "SWITCHES", [])}:
            api_safe.SWITCHES.append(("py_on", "Full payroll (2.56)", "Tax slabs, allowances, overtime, SSF / PF / CIT, advances, payslips and salary split by site attendance.",
                                      lambda v: v == "1", "#/py/payroll", "accounts approve", 10))
    except Exception:
        pass
