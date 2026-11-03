"""
Books agree (BuildCore 2.38): one posting per event, store and books reconcile, one data check list.

From the review of 2.37 (buildcore/review/AUDIT_ONE_PLATFORM_2.37.md), findings A1 A2 A3 A5 C1 C2 C4 G:
  1. One depreciation per machine per month. Equipment > Depreciation (dep.run, dep_runs) and Fixed assets >
     Depreciation run (fa.dep_run, fa_dep) each skip a machine and month the other has already posted, and each writes
     its twin record so that the equipment register and the fixed asset register carry the same history.
  2. Fixed assets starts a machine with its history: fa.sync copies accumulated depreciation, method, life, residual and
     WDV rate from the equipment register; machines synced before 2.38 get "bring history across" (preview, apply).
  3. Months already depreciated twice are listed (Fixed assets > Depreciation run > Check). Accounts proposes which
     posting to keep, another accounts approver approves, and one correcting journal is posted. Originals stay.
  4. One charge per machine hour: the Fixed assets allocation counts only logbook hours that neither a DPR nor an
     internal hire bill charged; internal hire skips what the allocation charged. New allocation postings use the
     same accounts as every other machine charge (setting one_recovery = 0 keeps the old ones).
  5. Completing a disposal always posts it (the Fixed asset row is made first when missing).
  6. Store and books: vouchers waiting in the posting queue explain a difference and are named.
  7. Financial data checks and Reports > Integrity carry the same new checks.
  8. Hire bills count approved logsheet hours only.
  9. Defects: rate-analysis labour loads as man-days (histogram 8x too low); the engine function table is restored after
     a start-up re-run (My work no longer doubles after a restore or a company switch).
New table one_dep_fix only. No existing row, id or posted voucher is changed or deleted, except the register totals and
twin records described above.
"""
import sys

import core
from core import ApiError, audit, get, ins, now, q, q1, r2, setting, today, upd, val
import api_inventory as inv
from api_inventory import api

VERSION = "2.38.0"
FLAG = "_bco238"
EPS = 0.005
INV_ROLES = ("inventory", "inventory_fuel", "inventory_spares")

SCHEMA = """
CREATE TABLE IF NOT EXISTS one_dep_fix(id INTEGER PRIMARY KEY, equipment_id INTEGER, fa_id INTEGER, month TEXT,
  keep TEXT, remove TEXT, amount REAL DEFAULT 0, project_id INTEGER, status TEXT DEFAULT 'proposed', voucher_id INTEGER,
  note TEXT, proposed_by INTEGER, proposed_at TEXT, decided_by INTEGER, decided_at TEXT);
CREATE INDEX IF NOT EXISTS ix_odf ON one_dep_fix(equipment_id, month);
"""

_STATE = {"funcs": None}


def _mend(c, m):
    """Last day of a month key: an English month (2026-08), or a Nepali month (2083-05, the month-close days) from 2.39."""
    try:
        if int(str(m)[:4]) >= 2070:
            import api_costlink as CL
            return CL.period_bounds(c, str(m)[:7])[1]
    except ValueError:
        pass
    return core.month_end(str(m)[:7] + "-01")


def _mstart(c, m):
    try:
        if int(str(m)[:4]) >= 2070:
            import api_costlink as CL
            return CL.period_bounds(c, str(m)[:7])[0]
    except ValueError:
        pass
    return str(m)[:7] + "-01"


def _has(c, t):
    return bool(val(c, "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (t,)))


def _num(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _wrap(name, factory):
    cur = inv.FUNCS.get(name)
    if not cur or getattr(cur[0], FLAG, False):
        return
    w = factory(cur[0])
    setattr(w, FLAG, True)
    w._orig = cur[0]
    for f in ("_bco219", "_bco220", "_bco221", "_bco223"):
        if getattr(cur[0], f, False):
            setattr(w, f, True)
    inv.FUNCS[name] = (w, cur[1], cur[2], cur[3])


def _right(u, module, action):
    return bool(u) and (u.get("role") == "admin" or core.can(u, module, action))


# ───────────────────────────── 1-2. depreciation: one route, both registers ─────────────────────────────
def _fa_of(c, eq_id):
    if not _has(c, "fa_register"):
        return None
    return q1(c, "SELECT * FROM fa_register WHERE kind='equipment' AND ref_id=? ORDER BY id LIMIT 1", (eq_id,))


def _fa_month_done(c, fa_id, month):
    return bool(val(c, "SELECT COUNT(*) FROM fa_dep WHERE fa_id=? AND month=?", (fa_id, month)))


def _eq_month_done(c, eq_id, month):
    return bool(val(c, "SELECT COUNT(*) FROM dep_runs WHERE equipment_id=? AND month=?", (eq_id, month)))


def _vproject(c, vid, default=None):
    return val(c, "SELECT project_id FROM vouchers WHERE id=?", (vid,), None) if vid else default


def _mirror_to_fa(c, eq_id, month, amount, voucher_id, method="EQ"):
    """Equipment depreciation for a month -> the twin line in the fixed asset register (no voucher)."""
    fa = _fa_of(c, eq_id)
    if not fa or _fa_month_done(c, fa["id"], month):
        return False
    pid = _vproject(c, voucher_id, fa["project_id"])
    ins(c, "fa_dep", {"fa_id": fa["id"], "comp_id": 0, "month": month, "method": method, "hours": 0, "amount": r2(amount),
                      "project_id": pid, "voucher_id": voucher_id, "ts": now()})
    c.execute("UPDATE fa_register SET accumulated=COALESCE(accumulated,0)+? WHERE id=?", (r2(amount), fa["id"]))
    ins(c, "fa_costs", {"fa_id": fa["id"], "date": _mend(c, month), "category": "depreciation",
                        "amount": r2(amount), "project_id": pid, "voucher_id": voucher_id, "ref": "DEP " + month,
                        "remarks": "Equipment depreciation (2.38 twin record)", "ts": now()})
    return True


def _mirror_to_eq(c, fa, month, amount, voucher_id):
    """Fixed asset depreciation of a machine -> the twin line in the equipment register (no voucher)."""
    if fa["kind"] != "equipment" or not fa["ref_id"] or _eq_month_done(c, fa["ref_id"], month):
        return False
    ins(c, "dep_runs", {"equipment_id": fa["ref_id"], "month": month, "amount": r2(amount), "voucher_id": voucher_id})
    c.execute("UPDATE equipment SET accumulated_dep=COALESCE(accumulated_dep,0)+? WHERE id=?", (r2(amount), fa["ref_id"]))
    return True


def _patch_dep_amount():
    import api_equipment_reports as ER
    if getattr(ER.dep_amount, FLAG, False):
        return
    orig = ER.dep_amount

    def dep_amount(c, eq, m):
        fa = _fa_of(c, eq["id"])
        if fa and _fa_month_done(c, fa["id"], m):
            return 0
        return orig(c, eq, m)
    setattr(dep_amount, FLAG, True)
    dep_amount._orig = orig
    ER.dep_amount = dep_amount


def _patch_fa_rows():
    import api_fa as FA
    if getattr(FA._dep_rows, FLAG, False):
        return
    orig = FA._dep_rows

    def _dep_rows(c, month, hours_override=None):
        out = []
        for x in orig(c, month, hours_override):
            r = q1(c, "SELECT kind, ref_id FROM fa_register WHERE id=?", (x["fa_id"],))
            if r and r["kind"] == "equipment" and r["ref_id"] and _eq_month_done(c, r["ref_id"], month):
                continue          # already depreciated by Equipment > Depreciation for this month
            out.append(x)
        return out
    setattr(_dep_rows, FLAG, True)
    _dep_rows._orig = orig
    FA._dep_rows = _dep_rows


def _w_dep_run(orig):
    def dep_run(c, u, a):
        last = val(c, "SELECT COALESCE(MAX(id),0) FROM dep_runs")
        res = orig(c, u, a)
        for r in q(c, "SELECT * FROM dep_runs WHERE id>?", (last,)):
            _mirror_to_fa(c, r["equipment_id"], r["month"], r["amount"], r["voucher_id"])
        return res
    return dep_run


def _w_dep_preview(orig):
    def dep_preview(c, u, a):
        rows = orig(c, u, a)
        m = a.get("month") or ""
        for r in rows or []:
            fa = _fa_of(c, r["equipment_id"])
            if fa and not r.get("posted") and _fa_month_done(c, fa["id"], m):
                r["posted"] = True
                r["amount"] = r2(val(c, "SELECT SUM(amount) FROM fa_dep WHERE fa_id=? AND month=?", (fa["id"], m)))
                r["note"] = "Posted in Fixed assets › Depreciation run"
        return rows
    return dep_preview


def _w_fa_dep_run(orig):
    def fa_dep_run(c, u, a):
        last = val(c, "SELECT COALESCE(MAX(id),0) FROM fa_dep")
        res = orig(c, u, a)
        for r in q(c, "SELECT d.*, f.kind, f.ref_id FROM fa_dep d JOIN fa_register f ON f.id=d.fa_id WHERE d.id>?", (last,)):
            _mirror_to_eq(c, r, r["month"], r["amount"], r["voucher_id"])
        return res
    return fa_dep_run


def _w_fa_dep_reverse(orig):
    def fa_dep_reverse(c, u, a):
        month = (a.get("month") or "")[:7]
        rows = q(c, "SELECT d.amount, f.ref_id FROM fa_dep d JOIN fa_register f ON f.id=d.fa_id WHERE d.month=? AND "
                    "f.kind='equipment' AND f.ref_id IS NOT NULL", (month,))
        res = orig(c, u, a)
        for r in rows:
            if _eq_month_done(c, r["ref_id"], month):
                c.execute("UPDATE equipment SET accumulated_dep=COALESCE(accumulated_dep,0)-? WHERE id=?", (r["amount"], r["ref_id"]))
                c.execute("DELETE FROM dep_runs WHERE equipment_id=? AND month=?", (r["ref_id"], month))
        if rows:
            audit(c, u, "dep_reverse_twin", "equipment", None, {"month": month, "machines": len(rows)})
        return res
    return fa_dep_reverse


METHOD = {"sl": "SL", "slm": "SL", "wdv": "WDV", "hours": "UOP"}


def carry_plan(c, fa):
    """What 'bring history across' would do for one machine row of the fixed asset register."""
    eq = q1(c, "SELECT * FROM equipment WHERE id=?", (fa["ref_id"],))
    if not eq:
        return None
    eq_months = {r["month"]: r for r in q(c, "SELECT * FROM dep_runs WHERE equipment_id=?", (eq["id"],))}
    fa_months = {}
    for r in q(c, "SELECT month, SUM(amount) amount, MIN(voucher_id) voucher_id FROM fa_dep WHERE fa_id=? GROUP BY month", (fa["id"],)):
        fa_months[r["month"]] = r
    doubles = sorted(m for m in eq_months if m in fa_months and fa_months[m]["voucher_id"] != eq_months[m]["voucher_id"])
    to_fa = sorted(m for m in eq_months if m not in fa_months)
    to_eq = sorted(m for m in fa_months if m not in eq_months)
    eq_acc = r2(_num(eq["accumulated_dep"]) + sum(_num(fa_months[m]["amount"]) for m in to_eq))
    has_own = bool(val(c, "SELECT COUNT(*) FROM fa_dep WHERE fa_id=? AND COALESCE(method,'')<>'EQ'", (fa["id"],)))
    life = (_num(eq["life_months"]) / 12.0) if eq["life_months"] else None
    meth = METHOD.get((eq["dep_method"] or "sl").lower(), "SL")
    policy = None
    if not has_own:
        policy = {"method": meth, "life_years": round(life, 4) if life else fa["life_years"],
                  "life_hours": _num(eq["est_total_hours"]) or fa["life_hours"], "residual": _num(eq["residual_value"]),
                  "wdv_rate": (_num(eq["wdv_rate"]) / 100.0) if meth == "WDV" and eq["wdv_rate"] else fa["wdv_rate"]}
    return {"fa_id": fa["id"], "equipment_id": eq["id"], "code": fa["code"], "name": fa["name"],
            "fa_accumulated": r2(_num(fa["accumulated"])), "equipment_accumulated": r2(_num(eq["accumulated_dep"])),
            "after": eq_acc, "months_to_fixed_assets": to_fa, "months_to_equipment": to_eq, "double_months": doubles,
            "policy": policy, "fa_policy": {"method": fa["method"], "life_years": fa["life_years"], "residual": fa["residual"]},
            "needed": bool(to_fa or to_eq or abs(_num(fa["accumulated"]) - eq_acc) > EPS or
                           (policy and (policy["method"] != fa["method"] or abs(_num(policy["residual"]) - _num(fa["residual"])) > EPS)))}


def carry_apply(c, fa_id):
    fa = q1(c, "SELECT * FROM fa_register WHERE id=?", (fa_id,))
    p = carry_plan(c, fa)
    if not p or p["double_months"]:
        return p
    for m in p["months_to_equipment"]:
        r = q1(c, "SELECT SUM(amount) amount, MIN(voucher_id) voucher_id FROM fa_dep WHERE fa_id=? AND month=?", (fa_id, m))
        _mirror_to_eq(c, fa, m, r["amount"], r["voucher_id"])
    for m in p["months_to_fixed_assets"]:
        r = q1(c, "SELECT * FROM dep_runs WHERE equipment_id=? AND month=?", (fa["ref_id"], m))
        fa_now = q1(c, "SELECT * FROM fa_register WHERE id=?", (fa_id,))
        pid = _vproject(c, r["voucher_id"], fa_now["project_id"])
        ins(c, "fa_dep", {"fa_id": fa_id, "comp_id": 0, "month": m, "method": "EQ", "hours": 0, "amount": r2(r["amount"]),
                          "project_id": pid, "voucher_id": r["voucher_id"], "ts": now()})
        ins(c, "fa_costs", {"fa_id": fa_id, "date": _mend(c, m), "category": "depreciation", "amount": r2(r["amount"]),
                            "project_id": pid, "voucher_id": r["voucher_id"], "ref": "DEP " + m,
                            "remarks": "Equipment depreciation (2.38 history)", "ts": now()})
    eq_acc = r2(val(c, "SELECT accumulated_dep FROM equipment WHERE id=?", (fa["ref_id"],)))
    sets = {"accumulated": eq_acc}
    if p["policy"]:
        sets.update({k: v for k, v in p["policy"].items() if v is not None})
    upd(c, "fa_register", fa_id, sets)
    return carry_plan(c, q1(c, "SELECT * FROM fa_register WHERE id=?", (fa_id,)))


def _w_fa_sync(orig):
    def fa_sync(c, u, a):
        last = val(c, "SELECT COALESCE(MAX(id),0) FROM fa_register")
        res = orig(c, u, a)
        carried = 0
        for fa in q(c, "SELECT * FROM fa_register WHERE id>? AND kind='equipment' AND ref_id IS NOT NULL", (last,)):
            p = carry_apply(c, fa["id"])
            carried += 1 if p else 0
        res = dict(res or {})
        res["history_carried"] = carried
        return res
    return fa_sync


def ensure_fa(c, u, eq_id):
    """The fixed asset row of one owned machine, made (with its history) when missing."""
    fa = _fa_of(c, eq_id)
    if fa:
        return fa
    import api_fa as FA
    e = q1(c, "SELECT * FROM equipment WHERE id=?", (eq_id,))
    if not e or (e["ownership"] or "owned") in ("rented", "hired", "rental"):
        return None
    k = FA._guess_class(e["category"] or e["name"])
    d = FA._defaults(k)
    cost = _num(e["purchase_value"])
    fid = ins(c, "fa_register", {"kind": "equipment", "ref_id": e["id"], "code": e["code"], "name": e["name"], "klass": k,
                                 "method": d["method"], "life_years": d["life_years"], "life_hours": d["life_hours"],
                                 "cost": cost, "residual": r2(cost * d["resid_pct"]), "in_use_date": e["purchase_date"],
                                 "project_id": e["project_id"], "tax_pool": d["tax_pool"], "abc_class": d["abc_class"],
                                 "hour_reading": _num(e["meter"]), "created": now(), "status": "active"})
    carry_apply(c, fid)
    audit(c, u, "create", "fa_register", fid, {"from": "disposal", "equipment_id": eq_id})
    return q1(c, "SELECT * FROM fa_register WHERE id=?", (fid,))


# ───────────────────────────── 3. months depreciated twice ─────────────────────────────
def doubles(c):
    if not _has(c, "fa_register"):
        return []
    out = []
    for r in q(c, "SELECT dr.id dr_id, dr.equipment_id, dr.month, dr.amount eq_amount, dr.voucher_id eq_voucher, "
                  "f.id fa_id, f.code, f.name FROM dep_runs dr JOIN fa_register f ON f.kind='equipment' AND f.ref_id=dr.equipment_id "
                  "ORDER BY dr.month, f.code"):
        fd = q1(c, "SELECT SUM(amount) amount, MIN(voucher_id) voucher_id, MIN(project_id) project_id FROM fa_dep "
                   "WHERE fa_id=? AND month=?", (r["fa_id"], r["month"]))
        if not fd or fd["amount"] is None or fd["voucher_id"] == r["eq_voucher"]:
            continue
        fix = q1(c, "SELECT * FROM one_dep_fix WHERE equipment_id=? AND month=? AND status IN ('proposed','posted') "
                    "ORDER BY id DESC LIMIT 1", (r["equipment_id"], r["month"]))
        if fix and fix["status"] == "posted":
            continue
        ev = q1(c, "SELECT no, project_id FROM vouchers WHERE id=?", (r["eq_voucher"],)) or {}
        fv = q1(c, "SELECT no, project_id FROM vouchers WHERE id=?", (fd["voucher_id"],)) or {}
        keep = "equipment" if (r["eq_voucher"] or 0) <= (fd["voucher_id"] or 0) else "fixed_assets"
        out.append({"equipment_id": r["equipment_id"], "fa_id": r["fa_id"], "code": r["code"], "name": r["name"],
                    "month": r["month"], "equipment_amount": r2(r["eq_amount"]), "equipment_voucher": ev.get("no"),
                    "fixed_assets_amount": r2(fd["amount"]), "fixed_assets_voucher": fv.get("no"),
                    "suggest_keep": keep, "proposal": dict(fix) if fix else None})
    return out


@api("one.dep_check", "accounts", "view")
def one_dep_check(c, u, a):
    rows = []
    if _has(c, "fa_register"):
        for fa in q(c, "SELECT * FROM fa_register WHERE kind='equipment' AND ref_id IS NOT NULL AND status<>'disposed' ORDER BY code"):
            p = carry_plan(c, fa)
            if p:
                rows.append(p)
    dl = doubles(c)
    return {"doubles": dl, "history": rows, "needs_history": [x for x in rows if x["needed"]],
            "can_propose": _right(u, "accounts", "edit"), "can_approve": _right(u, "accounts", "approve")}


@api("one.dep_history_apply", "accounts", "edit")
def one_dep_history_apply(c, u, a):
    ids = [int(x) for x in (a.get("fa_ids") or [])] or [x["fa_id"] for x in one_dep_check(c, u, {})["needs_history"]]
    done, skipped = [], []
    for fid in ids:
        fa = q1(c, "SELECT * FROM fa_register WHERE id=? AND kind='equipment'", (fid,))
        if not fa:
            continue
        p = carry_plan(c, fa)
        if p and p["double_months"]:
            skipped.append({"code": p["code"], "reason": "months depreciated twice: correct them first (%s)" % ", ".join(p["double_months"])})
            continue
        carry_apply(c, fid)
        done.append(fa["code"])
    audit(c, u, "history_apply", "fa_register", None, {"done": done, "skipped": skipped})
    return {"done": done, "skipped": skipped}


@api("one.dep_fix_propose", "accounts", "edit")
def one_dep_fix_propose(c, u, a):
    eq_id, month = int(a["equipment_id"]), (a.get("month") or "")[:7]
    keep = a.get("keep")
    if keep not in ("equipment", "fixed_assets"):
        raise ApiError("Choose which posting to keep: Equipment or Fixed assets.")
    row = next((x for x in doubles(c) if x["equipment_id"] == eq_id and x["month"] == month), None)
    if not row:
        raise ApiError("This machine and month is not depreciated twice.")
    c.execute("UPDATE one_dep_fix SET status='cancelled', decided_by=?, decided_at=? WHERE equipment_id=? AND month=? AND status='proposed'",
              (u["id"], now(), eq_id, month))
    remove = "fixed_assets" if keep == "equipment" else "equipment"
    amount = row["fixed_assets_amount"] if remove == "fixed_assets" else row["equipment_amount"]
    fid = ins(c, "one_dep_fix", {"equipment_id": eq_id, "fa_id": row["fa_id"], "month": month, "keep": keep, "remove": remove,
                                 "amount": amount, "status": "proposed", "note": (a.get("note") or "")[:300],
                                 "proposed_by": u["id"], "proposed_at": now()})
    audit(c, u, "propose", "one_dep_fix", fid, {"month": month, "keep": keep, "amount": amount})
    return {"id": fid, "amount": amount}


@api("one.dep_fix_decide", "accounts", "approve")
def one_dep_fix_decide(c, u, a):
    f = get(c, "one_dep_fix", int(a["id"]), "Correction")
    if f["status"] != "proposed":
        raise ApiError("This correction is already %s." % f["status"])
    if a.get("action") == "reject":
        upd(c, "one_dep_fix", f["id"], {"status": "cancelled", "decided_by": u["id"], "decided_at": now()})
        return {"status": "cancelled"}
    if f["proposed_by"] == u["id"] and u.get("role") != "admin":
        raise ApiError("Another accounts approver must approve a correction you proposed.")
    eq_id, month = f["equipment_id"], f["month"]
    dr = q1(c, "SELECT * FROM dep_runs WHERE equipment_id=? AND month=?", (eq_id, month))
    fa = q1(c, "SELECT * FROM fa_register WHERE id=?", (f["fa_id"],))
    fd = q1(c, "SELECT * FROM fa_dep WHERE fa_id=? AND month=? ORDER BY comp_id LIMIT 1", (fa["id"], month))
    fa_amt = r2(val(c, "SELECT SUM(amount) FROM fa_dep WHERE fa_id=? AND month=?", (fa["id"], month)))
    if not dr or not fd:
        raise ApiError("The two postings are no longer both there; nothing to correct.")
    if f["remove"] == "fixed_assets":
        amount, pid, vid_removed = fa_amt, fd["project_id"], fd["voucher_id"]
    else:
        amount, pid, vid_removed = r2(dr["amount"]), _vproject(c, dr["voucher_id"]), dr["voucher_id"]
    d = _mend(c, month)
    per = core.period_for(c, d)
    if per and per["status"] != "open":
        d = today()
    vno = val(c, "SELECT no FROM vouchers WHERE id=?", (vid_removed,), "")
    vid = core.post_voucher(c, u, "journal", d, "Depreciation of %s for %s posted twice: %s taken back" % (fa["code"], month, vno),
                            [{"role": "accum_dep", "debit": amount, "equipment_id": eq_id, "project_id": pid},
                             {"role": "depreciation", "credit": amount, "equipment_id": eq_id, "project_id": pid}],
                            project_id=pid, source="dep_fix", source_id=f["id"])
    if f["remove"] == "fixed_assets":
        # the fixed asset register now carries the equipment posting for that month
        c.execute("UPDATE fa_register SET accumulated=COALESCE(accumulated,0)-?+? WHERE id=?", (fa_amt, r2(dr["amount"]), fa["id"]))
        c.execute("DELETE FROM fa_dep WHERE fa_id=? AND month=? AND id<>?", (fa["id"], month, fd["id"]))
        upd(c, "fa_dep", fd["id"], {"amount": r2(dr["amount"]), "voucher_id": dr["voucher_id"], "method": "EQ",
                                    "project_id": _vproject(c, dr["voucher_id"], fd["project_id"])})
        c.execute("UPDATE fa_costs SET amount=?, voucher_id=? WHERE fa_id=? AND category='depreciation' AND ref=?",
                  (r2(dr["amount"]), dr["voucher_id"], fa["id"], "DEP " + month))
    else:
        c.execute("UPDATE equipment SET accumulated_dep=COALESCE(accumulated_dep,0)-?+? WHERE id=?", (r2(dr["amount"]), fa_amt, eq_id))
        upd(c, "dep_runs", dr["id"], {"amount": fa_amt, "voucher_id": fd["voucher_id"]})
    upd(c, "one_dep_fix", f["id"], {"status": "posted", "voucher_id": vid, "amount": amount, "project_id": pid,
                                    "decided_by": u["id"], "decided_at": now()})
    audit(c, u, "approve", "one_dep_fix", f["id"], {"voucher_id": vid, "amount": amount})
    # with no double month left, bring the two registers into line
    p = carry_plan(c, q1(c, "SELECT * FROM fa_register WHERE id=?", (fa["id"],)))
    if p and not p["double_months"]:
        carry_apply(c, fa["id"])
    return {"status": "posted", "voucher_id": vid, "amount": amount}


# ───────────────────────────── 4. one charge per machine hour ─────────────────────────────
def _alloc_hours(c, fa_row, month):
    """Logbook hours of a machine in a month, per project, that no DPR and no internal hire bill has charged."""
    if fa_row["kind"] != "equipment" or not fa_row["ref_id"] or not _has(c, "logbooks"):
        return {}
    rows = q(c, "SELECT b.project_id, SUM(l.hours) h FROM logsheets l JOIN logbooks b ON b.id=l.book_id WHERE b.equipment_id=? "
                "AND b.period=? AND l.dpr_id IS NULL AND b.sheet_type IN ('owned','hired_out','vehicle','genset','drilling',"
                "'dewatering','hoist') GROUP BY b.project_id", (fa_row["ref_id"], month[:7]))
    out = {}
    for x in rows:
        h = _num(x["h"]) - _num(val(c, "SELECT SUM(hours) FROM internal_bills WHERE equipment_id=? AND project_id=? AND month=?",
                                     (fa_row["ref_id"], x["project_id"], month[:7])))
        if h > EPS:
            out[x["project_id"]] = h
    return out


def _patch_alloc_rows():
    import api_fa as FA
    if getattr(FA._alloc_rows, FLAG, False):
        return

    def _alloc_rows(c, month, only=None):
        out = []
        last = core.month_end(month + "-01")
        for r in q(c, "SELECT * FROM fa_register WHERE kind='equipment' AND status='active' ORDER BY code"):
            if only and r["id"] not in only:
                continue
            if val(c, "SELECT id FROM fa_alloc WHERE fa_id=? AND month=? AND kind='charge'", (r["id"], month), None):
                continue
            rate = FA._rate_on(c, r["id"], last)
            for pid, h in _alloc_hours(c, r, month).items():
                out.append({"fa_id": r["id"], "code": r["code"], "name": r["name"], "project_id": pid, "hours": r2(h),
                            "rate": rate, "amount": r2(h * rate), "no_rate": not rate})
        return out
    setattr(_alloc_rows, FLAG, True)
    FA._alloc_rows = _alloc_rows


def _patch_fa_post():
    import api_fa as FA
    if getattr(FA._post, FLAG, False):
        return
    orig = FA._post
    MAP = {"equip_recovery": "equipment_recovery", "equip_job_cost": "equipment_cost"}

    def _post(c, u, head, lines):
        if setting(c, "one_recovery") != "0" and (head or {}).get("source") in ("fa_alloc", "fa_trueup", "fa_true_up"):
            lines = [dict(x, role=MAP.get(x.get("role"), x.get("role"))) for x in lines]
        return orig(c, u, head, lines)
    setattr(_post, FLAG, True)
    _post._orig = orig
    FA._post = _post


def _patch_internal_preview():
    import api_equipment_reports as ER
    if getattr(ER.internal_preview, FLAG, False):
        return
    orig = ER.internal_preview

    def internal_preview(c, u, a):
        rows = orig(c, u, a)
        m = (a.get("month") or "")[:7]
        if not _has(c, "fa_alloc"):
            return rows
        for r in rows or []:
            if r.get("posted"):
                continue
            fa = _fa_of(c, r["equipment_id"])
            if fa and val(c, "SELECT COUNT(*) FROM fa_alloc WHERE fa_id=? AND month=? AND project_id=? AND kind='charge'",
                          (fa["id"], m, r["project_id"])):
                r["posted"] = True
                r["note"] = "Charged by Fixed assets › Allocation"
        return rows
    setattr(internal_preview, FLAG, True)
    internal_preview._orig = orig
    ER.internal_preview = internal_preview
    cur = inv.FUNCS.get("internal.preview")
    if cur and cur[0] is orig:
        inv.FUNCS["internal.preview"] = (internal_preview, cur[1], cur[2], cur[3])


# ───────────────────────────── 5. disposal always posts ─────────────────────────────
def _w_disp_advance(orig):
    def disp_advance(c, u, a):
        rid = a.get("id")
        d = q1(c, "SELECT * FROM asset_disposals WHERE id=?", (int(rid),)) if rid and _has(c, "asset_disposals") else None
        if d and d["status"] == "approved" and not a.get("cancel") and d["equipment_id"]:
            ensure_fa(c, u, d["equipment_id"])          # completing it: the disposal must post
        return orig(c, u, a)
    return disp_advance


# ───────────────────────────── 6-7. checks ─────────────────────────────
def _gl(c, roles, pid=None, statuses=("posted", "reversed")):
    w = "a.role IN (%s) AND v.status IN (%s)" % (",".join("?" * len(roles)), ",".join("?" * len(statuses)))
    p = list(roles) + list(statuses)
    if pid:
        w += " AND l.project_id=?"
        p.append(pid)
    b = _num(val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts a "
                    "ON a.id=l.account_id WHERE " + w, p))
    if not pid and statuses == ("posted", "reversed"):
        b += _num(val(c, "SELECT SUM(opening_balance) FROM accounts WHERE role IN (%s)" % ",".join("?" * len(roles)), list(roles)))
    return r2(b)


DOC_TABLES = {"issue": "issues", "grn": "grn", "return": "returns", "transfer": "transfers", "count": "stock_counts",
              "invoice": "invoices", "dpr": "dpr"}


def _doc_ref(c, vid):
    """A waiting voucher has no number yet: name it by its source document."""
    v = q1(c, "SELECT source, source_id FROM vouchers WHERE id=?", (vid,))
    t = DOC_TABLES.get((v or {}).get("source") or "")
    no = val(c, "SELECT no FROM %s WHERE id=?" % t, (v["source_id"],), None) if t and v["source_id"] else None
    return (no or ("%s entry" % ((v or {}).get("source") or "voucher"))) + " (waiting)"


def stock_rows(c):
    out = []
    for p in q(c, "SELECT id, code FROM projects ORDER BY code"):
        stock = r2(val(c, "SELECT SUM(value) FROM stock_balances WHERE project_id=?", (p["id"],)))
        books = _gl(c, INV_ROLES, p["id"])
        waiting = q(c, "SELECT v.id, v.no, v.source, v.date, ROUND(SUM(l.debit-l.credit),2) amt FROM voucher_lines l JOIN vouchers v "
                       "ON v.id=l.voucher_id JOIN accounts a ON a.id=l.account_id WHERE a.role IN ('inventory','inventory_fuel',"
                       "'inventory_spares') AND v.status='submitted' AND l.project_id=? GROUP BY v.id ORDER BY v.id", (p["id"],))
        wsum = r2(sum(_num(x["amt"]) for x in waiting))
        diff = r2(stock - books)
        out.append({"project_id": p["id"], "code": p["code"], "stock": stock, "books": books, "waiting": wsum,
                    "waiting_items": [{"ref": x["no"] or _doc_ref(c, x["id"]), "date": x["date"], "amount": x["amt"]}
                                      for x in waiting],
                    "difference": diff, "unexplained": r2(diff - wsum)})
    return out


def _stock_detail(r):
    if abs(r["difference"]) < 1:
        return "Stores %s, books %s" % (r["stock"], r["books"])
    s = "Stores %s, books %s, difference %s" % (r["stock"], r["books"], r["difference"])
    if r["waiting_items"]:
        s += " = %d entr%s waiting in the accounts posting queue (%s)" % (
            len(r["waiting_items"]), "y" if len(r["waiting_items"]) == 1 else "ies",
            ", ".join(x["ref"] for x in r["waiting_items"][:5]))
        if abs(r["unexplained"]) >= 1:
            s += "; %s not explained" % r["unexplained"]
    return s


def _asset_registers(c):
    eq_cost = eq_acc = 0.0
    for e in q(c, "SELECT * FROM equipment WHERE COALESCE(ownership,'owned') NOT IN ('rented','hired','rental') "
                  "AND COALESCE(status,'')<>'disposed'"):
        eq_cost += _num(e["purchase_value"])
        eq_acc += _num(e["accumulated_dep"])
    as_cost = as_acc = 0.0
    if _has(c, "assets"):
        for s in q(c, "SELECT * FROM assets WHERE COALESCE(status,'active')<>'disposed'"):
            as_cost += _num(s["purchase_value"])
            as_acc += _num(s["accumulated_dep"]) if "accumulated_dep" in s.keys() else 0
    other_cost = other_acc = 0.0
    if _has(c, "fa_register"):
        for f in q(c, "SELECT * FROM fa_register WHERE kind NOT IN ('equipment','asset') AND status<>'disposed'"):
            other_cost += _num(f["cost"])
            other_acc += _num(f["accumulated"])
    return r2(eq_cost + as_cost + other_cost), r2(eq_acc + as_acc + other_acc)


def charged_twice(c):
    """Machine, project and month charged by the fixed asset allocation and also by a DPR or an internal hire bill."""
    if not _has(c, "fa_alloc"):
        return []
    out = []
    for r in q(c, "SELECT a.month, a.project_id, a.hours, f.ref_id equipment_id, f.code FROM fa_alloc a JOIN fa_register f "
                  "ON f.id=a.fa_id WHERE a.kind='charge' AND f.kind='equipment'"):
        ib = q1(c, "SELECT hours FROM internal_bills WHERE equipment_id=? AND project_id=? AND month=?",
                (r["equipment_id"], r["project_id"], r["month"]))
        dpr_h = _num(val(c, "SELECT SUM(l.hours) FROM logsheets l JOIN logbooks b ON b.id=l.book_id WHERE b.equipment_id=? "
                            "AND b.project_id=? AND b.period=? AND l.dpr_id IS NOT NULL", (r["equipment_id"], r["project_id"], r["month"]))) \
            if _has(c, "logbooks") else 0
        alloc_cnt = _num(val(c, "SELECT COUNT(*) FROM fa_alloc a JOIN fa_register f ON f.id=a.fa_id WHERE f.ref_id=? AND a.project_id=? "
                                "AND a.month=? AND a.kind='charge'", (r["equipment_id"], r["project_id"], r["month"])))
        book_h = _num(val(c, "SELECT SUM(l.hours) FROM logsheets l JOIN logbooks b ON b.id=l.book_id WHERE b.equipment_id=? "
                             "AND b.project_id=? AND b.period=?", (r["equipment_id"], r["project_id"], r["month"]))) \
            if _has(c, "logbooks") else 0
        over = _num(r["hours"]) + (_num(ib["hours"]) if ib else 0) + dpr_h - book_h
        if (ib or alloc_cnt > 1 or over > 0.01) and over > 0.01:
            out.append({"ref": "%s %s" % (r["code"], r["month"]), "project_id": r["project_id"], "amount": r2(over),
                        "detail": "allocation %s h, internal hire %s h, DPR %s h, logged %s h" %
                                  (r2(r["hours"]), r2(ib["hours"]) if ib else 0, r2(dpr_h), r2(book_h))})
    return out


def hire_over(c):
    out = []
    for b in q(c, "SELECT b.*, g.equipment_id, g.project_id, g.unit FROM hire_bills b JOIN hire_agreements g ON g.id=b.agreement_id "
                  "WHERE g.unit='hour'"):
        appr = _num(val(c, "SELECT SUM(hours) FROM logsheets WHERE equipment_id=? AND project_id=? AND date BETWEEN ? AND ? "
                           "AND status='approved'", (b["equipment_id"], b["project_id"], _mstart(c, b["month"]), _mend(c, b["month"]))))
        if _num(b["units"]) > appr + 0.01:
            out.append({"ref": "Hire bill %s" % b["month"], "amount": r2(_num(b["units"]) - appr),
                        "detail": "billed on %s h, approved %s h" % (r2(b["units"]), r2(appr))})
    return out


def checks(c):
    """The 2.38 checks, in the Financial data checks format."""
    out = []

    def add(area, name, sev, ok, detail, items=None, fix=None, amount=None):
        out.append({"area": area, "check": name, "ok": bool(ok), "severity": "ok" if ok else sev, "detail": detail,
                    "items": (items or [])[:50], "count": len(items or []), "fix": None if ok else fix, "amount": amount})
    for r in stock_rows(c):
        ok = abs(r["unexplained"]) < 1
        add("Stock and store", "Stock value = inventory accounts (%s)" % r["code"], "error", ok, _stock_detail(r),
            r["waiting_items"] if abs(r["difference"]) >= 1 else [], "Accounts › Posting queue" if r["waiting_items"] else "Inventory › Stock report",
            r["difference"])
    cost_reg, acc_reg = _asset_registers(c)
    cost_gl = _gl(c, ("fixed_asset",))
    acc_gl = r2(-_gl(c, ("accum_dep",)))
    add("Fixed assets", "Machine and asset cost: registers = ledger", "warn", abs(cost_reg - cost_gl) < 1,
        "Registers %s, ledger %s" % (cost_reg, cost_gl), fix="Fixed assets › Capital register", amount=r2(cost_reg - cost_gl))
    add("Fixed assets", "Accumulated depreciation: registers = ledger", "warn", abs(acc_reg - acc_gl) < 1,
        "Registers %s, ledger %s" % (acc_reg, acc_gl), fix="Fixed assets › Depreciation run › Check", amount=r2(acc_reg - acc_gl))
    mism = []
    if _has(c, "fa_register"):
        for f in q(c, "SELECT f.code, f.cost, f.accumulated, e.purchase_value, e.accumulated_dep FROM fa_register f JOIN equipment e "
                      "ON e.id=f.ref_id WHERE f.kind='equipment' AND f.status<>'disposed'"):
            if abs(_num(f["cost"]) - _num(f["purchase_value"])) >= 1 or abs(_num(f["accumulated"]) - _num(f["accumulated_dep"])) >= 1:
                mism.append({"ref": f["code"], "amount": r2(_num(f["accumulated"]) - _num(f["accumulated_dep"])),
                             "detail": "cost %s / %s, depreciation %s / %s (fixed assets / equipment)" %
                                       (r2(f["cost"]), r2(f["purchase_value"]), r2(f["accumulated"]), r2(f["accumulated_dep"]))})
    add("Fixed assets", "Equipment register = fixed asset register", "warn", not mism,
        "%d machine(s) differ" % len(mism) if mism else "Every machine agrees", mism, "Fixed assets › Depreciation run › Check")
    dl = doubles(c)
    add("Fixed assets", "No machine depreciated twice in a month", "error", not dl,
        "%d machine-month(s) posted by both Equipment and Fixed assets" % len(dl) if dl else "None",
        [{"ref": "%s %s" % (x["code"], x["month"]), "amount": min(x["equipment_amount"], x["fixed_assets_amount"])} for x in dl],
        "Fixed assets › Depreciation run › Check")
    tw = charged_twice(c)
    add("Fixed assets", "No machine hours charged twice", "error", not tw, "%d case(s)" % len(tw) if tw else "None", tw,
        "Fixed assets › Equipment costing")
    nov = q(c, "SELECT d.no, e.code FROM asset_disposals d LEFT JOIN equipment e ON e.id=d.equipment_id WHERE d.status='completed' "
               "AND d.voucher_id IS NULL") if _has(c, "asset_disposals") else []
    add("Fixed assets", "Every completed machine disposal has a voucher", "warn", not nov,
        "%d without a voucher" % len(nov) if nov else "All posted",
        [{"ref": "%s %s" % (x["no"] or "", x["code"] or "")} for x in nov], "Equipment › Lifecycle › Disposals")
    ho = hire_over(c)
    add("Payables", "Hire bills are not above approved logsheet hours", "warn", not ho, "%d bill(s)" % len(ho) if ho else "None",
        ho, "Equipment › Hire bills")
    return out


def _w_fc_checks(orig):
    def fc_checks(c, u, a):
        res = orig(c, u, a)
        if isinstance(res, dict) and isinstance(res.get("checks"), list):
            res["checks"].extend(checks(c))
            if "ok" in res and isinstance(res.get("ok"), (int, bool)):
                res["ok"] = all(x["ok"] for x in res["checks"])
        return res
    return fc_checks


def _w_integrity(orig):
    def rep_integrity(c, u, a):
        res = orig(c, u, a)
        new = checks(c)
        stock = {x["check"]: x for x in new if x["area"] == "Stock and store"}
        out = []
        for x in res:
            if x.get("check") in stock:
                s = stock[x["check"]]
                out.append({"check": x["check"], "ok": s["ok"], "detail": s["detail"]})
            else:
                out.append(x)
        have = {x["check"] for x in out}
        for x in new:
            if x["check"] not in have:
                out.append({"check": x["check"], "ok": x["ok"], "detail": x["detail"] + (
                    ": " + ", ".join(i.get("ref", "") for i in x["items"][:8]) if x["items"] and not x["ok"] else "")})
        return out
    return rep_integrity


# ───────────────────────────── 8. hire bills: approved hours ─────────────────────────────
def _w_hire_bill(orig):
    def hire_bill(c, u, a):
        res = orig(c, u, a)
        ag = q1(c, "SELECT * FROM hire_agreements WHERE id=?", (int(a["agreement_id"]),))
        m = a["month"]
        b = q1(c, "SELECT * FROM hire_bills WHERE agreement_id=? AND month=?", (ag["id"], m))
        if not b or not b["invoice_id"]:
            return res
        start, end = m + "-01", core.month_end(m)
        logs = q(c, "SELECT date, hours, status FROM logsheets WHERE equipment_id=? AND project_id=? AND date BETWEEN ? AND ?",
                 (ag["equipment_id"], ag["project_id"], start, end))
        ok = [x for x in logs if x["status"] == "approved"]
        pending = r2(sum(_num(x["hours"]) for x in logs if x["status"] != "approved"))
        if ag["unit"] == "hour":
            units = r2(sum(_num(x["hours"]) for x in ok))
        elif ag["unit"] == "day":
            units = len({x["date"] for x in ok if _num(x["hours"]) > 0})
        else:
            return res
        if abs(units - _num(b["units"])) < 0.001:
            return res
        billed = max(units, _num(ag["min_units"]))
        amount = r2(billed * _num(ag["rate"]))
        eq = get(c, "equipment", ag["equipment_id"])
        line = q1(c, "SELECT * FROM invoice_lines WHERE invoice_id=? ORDER BY id LIMIT 1", (b["invoice_id"],))
        if line:
            upd(c, "invoice_lines", line["id"], {"qty": r2(billed), "amount": amount, "description": "%s %s: %s %s (approved %s; %s h not yet approved, not billed)" %
                                                 (eq["code"], m, r2(billed), ag["unit"], r2(units), pending)})
        upd(c, "hire_bills", b["id"], {"units": r2(units), "billed_units": r2(billed), "amount": amount})
        res = dict(res or {})
        res.update({"units": r2(units), "billed": r2(billed), "not_approved_hours": pending})
        return res
    return hire_bill


# ───────────────────────────── 9. defects ─────────────────────────────
def _fix_res_units(c, pid=None):
    if not _has(c, "act_resources"):
        return 0
    w, p = "kind='L' AND source='rate_analysis' AND unit='hr'", []
    if pid:
        w += " AND project_id=?"
        p.append(pid)
    n = val(c, "SELECT COUNT(*) FROM act_resources WHERE " + w, p)
    if n:
        c.execute("UPDATE act_resources SET unit='man-day' WHERE " + w, p)
    return n


def _w_res_load(orig):
    def res_load(c, u, a):
        res = orig(c, u, a)
        _fix_res_units(c, int(a["project_id"]) if a.get("project_id") else None)
        return res
    return res_load


def _patch_reinit():
    """A second start-up (restore, company switch) must not wrap the engine functions again."""
    if getattr(core.init_db, FLAG, False):
        return
    orig = core.init_db

    def init_db(*a, **k):
        before = dict(inv.FUNCS) if _STATE["funcs"] is not None else None
        try:
            return orig(*a, **k)
        finally:
            if before is not None:
                for name, entry in before.items():
                    inv.FUNCS[name] = entry
            _STATE["funcs"] = True
    setattr(init_db, FLAG, True)
    _STATE["funcs"] = True          # this start-up is the first one; later ones restore the table
    core.init_db = init_db
    for mn in ("server", "__main__"):
        m = sys.modules.get(mn)
        if m is not None and getattr(m, "init_db", None) is orig:
            m.init_db = init_db


# ───────────────────────────── start-up ─────────────────────────────
def init_one(c):
    c.executescript(SCHEMA)
    if not val(c, "SELECT COUNT(*) FROM settings WHERE key='one_recovery'"):
        c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES('one_recovery', '1')")
    if not val(c, "SELECT COUNT(*) FROM settings WHERE key='one_res_units_done'"):
        _fix_res_units(c)
        c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES('one_res_units_done', ?)", (now(),))
    c.commit()
    _patch_dep_amount()
    _patch_fa_rows()
    _patch_alloc_rows()
    _patch_fa_post()
    _patch_internal_preview()
    _wrap("dep.run", _w_dep_run)
    _wrap("dep.preview", _w_dep_preview)
    _wrap("fa.dep_run", _w_fa_dep_run)
    _wrap("fa.dep_reverse", _w_fa_dep_reverse)
    _wrap("fa.sync", _w_fa_sync)
    _wrap("life.disp_advance", _w_disp_advance)
    _wrap("fc.checks", _w_fc_checks)
    _wrap("rep.integrity", _w_integrity)
    _wrap("hire.bill", _w_hire_bill)
    _wrap("res.load", _w_res_load)
    _patch_reinit()
