"""BuildCore 2.51 "Count all the cost" (U2).

Cost that is real but not yet in the books, per project, each line labelled and traceable:
* Material used, not issued: executed quantity (approved DPRs) x material per unit (BOQ material coefficients) less
  what was issued net of returns and what subcontractors used, valued at the issue average (else the standard rate,
  else the project's latest receipt price).  A prompt to the storekeeper: nothing is moved.
* DPR lines with no rate: labour (worker hours with no amount) and, when machines are costed by rate, own machine hours
  with no amount, valued at the company's default rates (or the project's average rate).
* DPRs waiting approval: labour and machines on submitted / checked DPRs, with their age.
* Monthly runs not done: salary, depreciation and small-asset runs missing for months that have ended (after the first
  run ever made), estimated from the last run (depreciation by this project's share of machine hours).
Shown on Commercial > CVR and forecast > "Cost not yet in the books" (display only, on for all).  A cost completeness
score 0-100 per project is shown there, on the dashboard and on the project control room.
Switch ac_on (off on companies that already had data; accounts approve): the month close's accruals also include these
lines (material used not issued, DPR lines with no rate, salary and small-asset runs not done), so they are posted and
reversed with the other close accruals.  With the switch off nothing is posted and no figure on other screens changes.
"""
import json
from datetime import date, timedelta

import core
from core import ApiError, audit, q, q1, setting, today, val
import api_inventory as inv
from api_inventory import api

VERSION = "2.51.0"
FLAG = "_bco251"
EPS = 1e-6


def _CL():
    import api_costlink
    return api_costlink


def _r2(x):
    return round((x or 0) + 0.0, 2)


def _set(c, k, v):
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", (k, str(v)))


def on(c):
    return setting(c, "ac_on") == "1"


def _f(c, k, d=0.0):
    try:
        return float(setting(c, k) or d)
    except (TypeError, ValueError):
        return d


# ───────────────────────── months ─────────────────────────
def _next_month(m):
    y, mm = int(m[:4]), int(m[5:7])
    mm += 1
    if mm > 12:
        y, mm = y + 1, 1
    return "%04d-%02d" % (y, mm)


def _ended(c, m, asof):
    import api_pfp
    try:
        return api_pfp.window_of(c, m)[1] < asof
    except Exception:
        return False


def _missing_months(c, have, asof, limit=6):
    """Months after the first run ever made, up to the last ended month, that have no run."""
    have = sorted({m[:7] for m in have if m})
    if not have:
        return []
    out, m = [], have[0]
    for _ in range(240):
        m = _next_month(m)
        if not _ended(c, m, asof):
            break
        if m not in have:
            out.append(m)
    return out[-limit:]


def _hours_share(c, pid, m):
    """This project's share of each own machine's DPR hours in month m: {equipment_id: share}."""
    import api_pfp
    try:
        frm, to = api_pfp.window_of(c, m)
    except Exception:
        return {}
    rows = q(c, "SELECT e.equipment_id eid, d.project_id pid, SUM(COALESCE(e.hours,0)) h FROM dpr_equipment e JOIN dpr d ON "
                "d.id=e.dpr_id WHERE d.status='approved' AND d.date BETWEEN ? AND ? AND e.equipment_id IS NOT NULL GROUP BY 1, 2",
             (frm, to))
    tot, mine = {}, {}
    for r in rows:
        tot[r["eid"]] = tot.get(r["eid"], 0) + (r["h"] or 0)
        if r["pid"] == pid:
            mine[r["eid"]] = r["h"] or 0
    return {k: mine[k] / tot[k] for k in mine if tot.get(k)}


# ───────────────────────── the lines ─────────────────────────
def _avg_trade_rate(c, pid):
    return val(c, "SELECT AVG(rate_hour) FROM trades WHERE (project_id=? OR project_id IS NULL) AND rate_hour>0", (pid,)) or 0


def _avg_eq_rate(c, pid):
    return val(c, "SELECT SUM(e.amount)/SUM(e.hours) FROM dpr_equipment e JOIN dpr d ON d.id=e.dpr_id WHERE d.project_id=? AND "
                  "e.amount>0 AND e.hours>0", (pid,)) or 0


def missing_cost(c, pid, asof=None):
    pid = int(pid)
    asof = asof or today()
    CL = _CL()
    ctx = CL.Ctx(c)
    una = ctx.head(pid, "UNA")
    lines = []
    # 1. material used, not issued
    try:
        recon = CL.material_recon(c, pid, asof)
    except Exception:
        recon = []
    for r in recon:
        need = (r["executed"] or 0) * (r["coefficient"] or 0)
        short = need - (r["actual"] or 0)
        if short <= max(EPS, need * 0.02):
            continue
        rate = r["rate"] or 0
        if not rate:
            rate = val(c, "SELECT gl.rate FROM grn_lines gl JOIN grn g ON g.id=gl.grn_id WHERE g.project_id=? AND gl.material_id=? AND "
                          "g.status='posted' ORDER BY g.date DESC, g.id DESC LIMIT 1", (pid, r["material_id"])) or 0
        lines.append({"kind": "material_not_issued", "label": "Material used, not issued",
                      "detail": "%s %s: %.2f %s used on %.2f done (x %g per unit), %.2f issued" % (
                          r["boq_code"], r["mat_name"], need, r["unit"] or "", r["executed"] or 0, r["coefficient"] or 0, r["actual"] or 0),
                      "qty": round(short, 3), "unit": r["unit"], "rate": _r2(rate), "amount": _r2(short * rate),
                      "estimated": not r["rate"], "code_id": ctx.code_for_boq(pid, r["boq_item_id"]) or una, "ctype": "M",
                      "source_type": "material", "source_id": r["material_id"], "boq_item_id": r["boq_item_id"],
                      "link": "inv/issues", "fix": "Make the store issue for this item (or mark it issued at site)."})
    # 2. DPR lines with no rate
    lab_rate = _f(c, "ac_lab_rate") or _avg_trade_rate(c, pid)
    for r in q(c, "SELECT l.trade_id, t.name trade, l.activity_id, SUM(l.count*COALESCE(l.hours,8)) wh, COUNT(DISTINCT d.id) n, "
                  "MIN(d.date) d0, MAX(d.date) d1 FROM dpr_labour l JOIN dpr d ON d.id=l.dpr_id LEFT JOIN trades t ON t.id=l.trade_id "
                  "WHERE d.project_id=? AND d.status='approved' AND d.date<=? AND COALESCE(l.count,0)>0 AND COALESCE(l.amount,0)=0 "
                  "AND l.party_id IS NULL GROUP BY l.trade_id, l.activity_id", (pid, asof)):
        k = ctx.code_for_boq(pid, ctx.act_boq(r["activity_id"])) if r["activity_id"] else una
        lines.append({"kind": "dpr_no_rate", "label": "DPR labour with no rate",
                      "detail": "%s: %.0f worker-hours on %d DPR(s) %s to %s posted no cost" % (r["trade"] or "No trade", r["wh"] or 0, r["n"], r["d0"], r["d1"]),
                      "qty": _r2(r["wh"]), "unit": "worker-hour", "rate": _r2(lab_rate), "amount": _r2((r["wh"] or 0) * lab_rate),
                      "estimated": True, "code_id": k or una, "ctype": "L", "source_type": "trade", "source_id": r["trade_id"],
                      "link": "m/trades", "fix": "Set the trade's hourly rate (Masters > Trades); later DPRs then carry cost."})
    if CL.eq_mode(c) == "rate":
        eq_rate = _f(c, "ac_eq_rate") or _avg_eq_rate(c, pid)
        for r in q(c, "SELECT e.equipment_id, m.code, m.name, e.activity_id, SUM(e.hours) hrs, COUNT(DISTINCT d.id) n FROM dpr_equipment e "
                      "JOIN dpr d ON d.id=e.dpr_id LEFT JOIN equipment m ON m.id=e.equipment_id WHERE d.project_id=? AND d.status='approved' "
                      "AND d.date<=? AND COALESCE(e.hours,0)>0 AND COALESCE(e.amount,0)=0 AND COALESCE(m.ownership,'own')<>'hired' "
                      "GROUP BY e.equipment_id, e.activity_id", (pid, asof)):
            k = ctx.code_for_boq(pid, ctx.act_boq(r["activity_id"])) if r["activity_id"] else una
            lines.append({"kind": "dpr_no_rate", "label": "DPR machine hours with no rate",
                          "detail": "%s %s: %.1f hours on %d DPR(s) posted no cost" % (r["code"] or "", r["name"] or "", r["hrs"] or 0, r["n"]),
                          "qty": _r2(r["hrs"]), "unit": "hour", "rate": _r2(eq_rate), "amount": _r2((r["hrs"] or 0) * eq_rate),
                          "estimated": True, "code_id": k or una, "ctype": "E", "source_type": "equipment", "source_id": r["equipment_id"],
                          "link": "eq/rates", "fix": "Give the machine a rate card."})
    # 3. DPRs waiting approval
    for d in q(c, "SELECT id, no, date, status FROM dpr WHERE project_id=? AND status IN ('submitted','checked') AND date<=? ORDER BY date",
               (pid, asof)):
        lab = q1(c, "SELECT SUM(COALESCE(NULLIF(l.amount,0), l.count*COALESCE(l.hours,8)*COALESCE(NULLIF(l.rate,0), t.rate_hour, 0))) v "
                    "FROM dpr_labour l LEFT JOIN trades t ON t.id=l.trade_id WHERE l.dpr_id=?", (d["id"],))["v"] or 0
        mac = q1(c, "SELECT SUM(COALESCE(NULLIF(amount,0), hours*COALESCE(rate,0))) v FROM dpr_equipment WHERE dpr_id=?", (d["id"],))["v"] or 0
        age = (date.fromisoformat(asof) - date.fromisoformat(d["date"])).days
        if lab + mac > 0.5 or age > 3:
            lines.append({"kind": "dpr_waiting", "label": "DPR waiting approval",
                          "detail": "DPR %s of %s (%s, %d days old): labour %.0f, machines %.0f" % (d["no"] or d["id"], d["date"], d["status"], age, lab, mac),
                          "qty": None, "unit": None, "rate": None, "amount": _r2(lab + mac), "estimated": True, "code_id": None,
                          "ctype": "L", "source_type": "dpr", "source_id": d["id"], "age": age, "link": "p/dpr",
                          "fix": "Check and approve the DPR (Site work > Daily progress)."})
    # 4. monthly runs not done
    sal = [r["month"] for r in q(c, "SELECT month FROM mn_salary_run")] if _has(c, "mn_salary_run") else []
    last_sal = None
    if sal:
        lr = q1(c, "SELECT id, month FROM mn_salary_run ORDER BY month DESC LIMIT 1")
        last_sal = val(c, "SELECT SUM(COALESCE(gross,0)+COALESCE(ssf_employer,0)) FROM mn_salary_lines WHERE run_id=? AND project_id=?",
                       (lr["id"], pid)) or 0
    for m in _missing_months(c, sal, asof):
        if last_sal:
            lines.append({"kind": "run_missing", "label": "Salary run not done",
                          "detail": "Salary for %s not run; estimated from the last run's site staff on this project" % m,
                          "qty": None, "unit": None, "rate": None, "amount": _r2(last_sal), "estimated": True, "code_id": ctx.head(pid, "OH") or una,
                          "ctype": "O", "source_type": "salary", "source_id": None, "month": m, "link": "mn/salary",
                          "fix": "Run the salary for the month (Accounts > Salaries)."})
    dep = [r["month"] for r in q(c, "SELECT DISTINCT month FROM dep_runs")] if _has(c, "dep_runs") else []
    for m in _missing_months(c, dep, asof):
        share = _hours_share(c, pid, m)
        if not share:
            continue
        last = {r["equipment_id"]: r["amount"] or 0 for r in q(c, "SELECT equipment_id, amount FROM dep_runs WHERE month=(SELECT MAX(month) FROM dep_runs)")}
        amt = sum(last.get(k, 0) * s for k, s in share.items())
        if amt > 0.5:
            lines.append({"kind": "run_missing", "label": "Depreciation run not done",
                          "detail": "Machine depreciation for %s not run; this project's share by hours, from the last run" % m,
                          "qty": None, "unit": None, "rate": None, "amount": _r2(amt), "estimated": True, "code_id": None,
                          "ctype": "E", "source_type": "depreciation", "source_id": None, "month": m, "link": "eq/dep", "accrue": False,
                          "fix": "Run machine depreciation for the month (Equipment > Depreciation run)."})
    if _has(c, "sa_runs"):
        sa = [r["month"] for r in q(c, "SELECT DISTINCT month FROM sa_runs WHERE project_id=?", (pid,))]
        last_sa = val(c, "SELECT SUM(amount) FROM sa_runs WHERE project_id=? AND month=(SELECT MAX(month) FROM sa_runs WHERE project_id=?)",
                      (pid, pid)) or 0
        for m in _missing_months(c, sa, asof):
            if last_sa > 0.5:
                lines.append({"kind": "run_missing", "label": "Small-asset hire run not done",
                              "detail": "Scaffolding / tools hire for %s not run; estimated from the last run" % m,
                              "qty": None, "unit": None, "rate": None, "amount": _r2(last_sa), "estimated": True,
                              "code_id": ctx.head(pid, "OH") or una, "ctype": "E", "source_type": "small_assets", "source_id": None,
                              "month": m, "link": "x/pools", "fix": "Run small-asset hire for the month."})
    kinds = {}
    for x in lines:
        kinds[x["kind"]] = _r2(kinds.get(x["kind"], 0) + (x["amount"] or 0))
    total = _r2(sum(x["amount"] or 0 for x in lines))
    return {"project_id": pid, "as_of": asof, "lines": lines, "by_kind": kinds, "total": total,
            "rates": {"labour_hour": _r2(lab_rate), "default_labour_set": bool(_f(c, "ac_lab_rate"))}, "switch_on": on(c)}


def _has(c, t):
    return bool(q1(c, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)))


# ───────────────────────── completeness score ─────────────────────────
def score(c, pid, asof=None, mc=None):
    pid = int(pid)
    asof = asof or today()
    CL = _CL()
    import api_pfp
    try:
        pos = api_pfp.position(c, pid, asof)
    except Exception:
        pos = None
    mc = mc or missing_cost(c, pid, asof)
    parts = []

    def add(key, label, weight, got, detail, link):
        got = max(0.0, min(1.0, got))
        parts.append({"key": key, "label": label, "weight": weight, "points": round(weight * got, 1), "ok": got >= 0.999,
                      "detail": detail, "link": link})
    has_budget = bool(CL.current_version(c, pid))
    add("budget", "Approved control budget", 10, 1 if has_budget else 0, "approved" if has_budget else "none approved", "cl/budget")
    boq = q(c, "SELECT id, unit, COALESCE(revised_qty, qty)*COALESCE(revised_rate, rate) v FROM boq_items WHERE project_id=?", (pid,))
    tot = sum(b["v"] or 0 for b in boq)
    if pos:
        nofc = pos["forecast"].get("revenue_without_cost") or sum(x.get("revenue") or 0 for x in pos["forecast"].get("no_forecast") or [])
        cov = 1 - (nofc / tot) if tot else 0
    else:
        cov = 0
    add("estimate", "Cost estimate on BOQ value", 15, cov, "%.0f%% of BOQ value has a cost estimate" % (100 * cov), "rp/ra")
    coef = {r["boq_item_id"] for r in q(c, "SELECT DISTINCT mc.boq_item_id FROM material_coefficients mc JOIN boq_items b ON b.id=mc.boq_item_id "
                                           "WHERE b.project_id=?", (pid,))}
    work = [b for b in boq if (b["unit"] or "").strip().lower() not in ("ls", "l.s.", "lump sum", "item", "job", "sum", "month", "months", "p.s.", "ps")]
    wv = sum(b["v"] or 0 for b in work)
    cv = sum(b["v"] or 0 for b in work if b["id"] in coef)
    add("coef", "Material per unit on BOQ items", 10, (cv / wv / 0.6) if wv else 0,
        "%.0f%% of work value has material per unit (60%% counts as full)" % (100 * cv / wv if wv else 0), "inv/recon")
    used = q(c, "SELECT DISTINCT l.trade_id, t.rate_hour FROM dpr_labour l JOIN dpr d ON d.id=l.dpr_id LEFT JOIN trades t ON t.id=l.trade_id "
                "WHERE d.project_id=? AND l.party_id IS NULL", (pid,))
    tr = sum(1 for r in used if (r["rate_hour"] or 0) > 0) / len(used) if used else 1
    add("rates", "Trade rates set", 10, tr, "%d of %d trades used in DPRs have a rate" % (sum(1 for r in used if (r["rate_hour"] or 0) > 0), len(used)) if used else "no labour in DPRs", "m/trades")
    late = [x for x in mc["lines"] if x["kind"] == "dpr_waiting" and (x.get("age") or 0) > 3]
    add("dpr", "DPRs approved within 3 days", 10, 1 if not late else max(0, 1 - len(late) / 5), "%d DPR(s) waiting more than 3 days" % len(late), "p/dpr")
    runs = [x for x in mc["lines"] if x["kind"] == "run_missing"]
    add("runs", "Monthly runs done", 10, 1 if not runs else 0, "%d run(s) missing" % len(runs) if runs else "all done", "admin/setup")
    cost = (pos or {}).get("cost", {}).get("total") or 0
    miss = mc["total"]
    pct = miss / cost if cost else (0 if not miss else 1)
    add("missing", "Cost not yet in the books under 2% of cost", 15, 1 if pct <= 0.02 else max(0, 1 - (pct - 0.02) / 0.08),
        "%.1f%% of cost to date is missing" % (100 * pct), "cl/cvr")
    last = val(c, "SELECT MAX(cutoff_date) FROM cl_closes WHERE project_id=? AND status='locked'", (pid,))
    recent = bool(last and last >= (date.fromisoformat(asof) - timedelta(days=45)).isoformat())
    add("close", "Last month closed and locked", 10, 1 if recent else 0, "last locked close %s" % last if last else "no locked close", "cl/close")
    mt = (pos or {}).get("margin", {}).get("certified_pct")
    mf = (pos or {}).get("forecast", {}).get("margin_pct")
    plaus = 1 if mt is None or mf is None or abs(mt - mf) <= 25 else 0
    add("plausible", "Margin to date close to the forecast margin", 10, plaus,
        "margin to date %s%%, forecast %s%%" % (mt, mf) + ("" if plaus else ": cost is probably missing"), "cl/cvr")
    s = round(sum(p["points"] for p in parts))
    return {"project_id": pid, "score": s, "parts": parts, "missing_total": miss}


# ───────────────────────── close accruals (switch) ─────────────────────────
ACC_ROLES = {"material_not_issued": "material_cost", "dpr_no_rate_labour": "labour_cost", "dpr_no_rate_machine": "equipment_cost",
             "salary_not_run": "overhead", "small_assets_not_run": "equipment_cost"}


def _wrap_accruals():
    CL = _CL()
    cur = CL.accruals
    if getattr(cur, FLAG, False):
        return

    def accruals(c, pid, asof, close=None):
        out = cur(c, pid, asof, close)
        if not on(c):
            return out
        try:
            mc = missing_cost(c, pid, asof)
        except Exception:
            return out
        for x in mc["lines"]:
            if x["kind"] not in ("material_not_issued", "dpr_no_rate", "run_missing") or x.get("accrue") is False:
                continue
            if (x["amount"] or 0) <= 0.5:
                continue
            kind = x["kind"]
            if kind == "dpr_no_rate":
                kind = "dpr_no_rate_machine" if x["ctype"] == "E" else "dpr_no_rate_labour"
            elif kind == "run_missing":
                kind = "salary_not_run" if x["source_type"] == "salary" else "small_assets_not_run"
            out.append({"kind": kind, "side": "cost", "source_type": x["source_type"], "source_id": x["source_id"],
                        "code_id": x["code_id"], "amount": x["amount"], "ctype": x["ctype"], "detail": x["detail"] + " (estimated, 2.51)"})
        return out
    for k, role in ACC_ROLES.items():
        CL.ACCRUAL_ROLE.setdefault(k, role)
    for _k in [k for k in getattr(cur, "__dict__", {}) if k.startswith("_bco")]:
        setattr(accruals, _k, getattr(cur, _k))
    setattr(accruals, FLAG, True)
    accruals._orig = cur
    CL.accruals = accruals


# ───────────────────────── actions ─────────────────────────
def _check(c, u, pid):
    try:
        _CL()._check_project(c, u, int(pid))
    except AttributeError:
        pass


@api("ac.missing", "project", "view")
def ac_missing(c, u, a):
    core.need(a, "project_id")
    _check(c, u, a["project_id"])
    mc = missing_cost(c, a["project_id"], a.get("as_of"))
    mc["score"] = score(c, a["project_id"], a.get("as_of"), mc)
    return mc


@api("ac.scores", "project", "view")
def ac_scores(c, u, a):
    out = []
    ids = [int(a["project_id"])] if a.get("project_id") else [r["id"] for r in q(
        c, "SELECT id FROM projects WHERE status='active' AND COALESCE(kind,'project') NOT IN ('trading','general') ORDER BY code")]
    allow = None
    try:
        import api_workspace
        allow = api_workspace.allowed_projects(c, u) if hasattr(api_workspace, "allowed_projects") else None
    except Exception:
        allow = None
    for pid in ids[:60]:
        if allow is not None and pid not in allow:
            continue
        p = q1(c, "SELECT code, name FROM projects WHERE id=?", (pid,))
        try:
            s = score(c, pid)
        except Exception as e:
            s = {"score": None, "parts": [], "missing_total": 0, "error": str(e)}
        out.append({"project_id": pid, "code": p["code"], "name": p["name"], "score": s["score"], "missing_total": s["missing_total"],
                    "weakest": [x["label"] for x in sorted(s["parts"], key=lambda x: x["points"] - x["weight"]) if not x["ok"]][:3]})
    return {"projects": out}


@api("ac.settings", "accounts", "view")
def ac_settings(c, u, a):
    return {"on": on(c), "lab_rate": _f(c, "ac_lab_rate"), "eq_rate": _f(c, "ac_eq_rate"), "version": VERSION}


@api("ac.save", "accounts", "approve")
def ac_save(c, u, a):
    before = ac_settings(c, u, {})
    if "on" in a:
        _set(c, "ac_on", "1" if a["on"] else "0")
    for k in ("lab_rate", "eq_rate"):
        if k in a:
            v = float(a[k] or 0)
            if v < 0:
                raise ApiError("A rate cannot be negative.")
            _set(c, "ac_" + k, v)
    after = ac_settings(c, u, {})
    audit(c, u, "settings", "cost not in the books", None, {"before": before, "after": after})
    return after


def init_allcost(c):
    if not q1(c, "SELECT 1 FROM settings WHERE key='ac_on'"):
        used = val(c, "SELECT COUNT(*) FROM vouchers") or val(c, "SELECT COUNT(*) FROM dpr")
        _set(c, "ac_on", "0" if used else "1")
        c.commit()
    _wrap_accruals()
    try:
        import api_safe
        if not any(s[0] == "ac_on" for s in getattr(api_safe, "SWITCHES", [])) and hasattr(api_safe, "SWITCHES"):
            api_safe.SWITCHES.append(("ac_on", "Count cost not yet in the books at the close",
                                      "Material used not issued, DPR lines with no rate and missing salary / small-asset runs are accrued at the month close.",
                                      lambda v: v == "1", "#/cl/cvr", "accounts approve", 3))
    except Exception:
        pass
