"""BuildCore 2.38.0 "Books agree": every cost posted once, and store, assets and books reconcile (or say why not).

Nothing here deletes or renumbers a voucher, document or stock row, and no posted amount is changed. A correction is
a new voucher that waits in the accounts posting queue until an approver posts it.

  2.38.1  one depreciation route (Fixed assets); a machine and month is never depreciated twice, whichever screen
          is used; fa.sync carries the equipment register's history; Fixed assets > Depreciation run > Check
  2.38.2  one machine-charge route (DPR machine lines + Internal hire); Allocation becomes the year-end true-up,
          measured against every recovery; new recoveries go to one account (Equipment Hire Recovery)
  2.38.3  completing a disposal in Lifecycle always posts it (the Fixed asset row is made first when missing)
  2.38.4  store against books: queued vouchers that explain a difference are listed
  2.38.5  one data check list (Accounts > Integrity checks, both tabs), with the new checks
  2.38.6  hire bills count approved logsheet hours only
  2.38.7  resource histogram: rate-analysis labour is in man-days, not hours

Behaviour that can change a figure on an existing company sits behind a switch (Administration > Settings >
Books agree). A new company starts with every switch on; an updated company starts with them off until an
accounts approver confirms each one after seeing its before and after figures.
"""
from datetime import date

import core
from core import ApiError, EPS, audit, get, ins, month_end, now, num, q, q1, r2, setting, today, upd, val
import api_inventory as inv
from api_inventory import api

VERSION_TAG = "2.38.0"

SWITCHES = {
    "one_dep_route": ("One depreciation route",
                      "Depreciation of machines is posted only from Fixed assets › Depreciation run. Equipment › "
                      "Depreciation shows the result read-only. Fixed assets › Capital register › Sync brings in each "
                      "machine with its depreciation history, method and life from the equipment register."),
    "alloc_trueup_only": ("Allocation is the year-end true-up only",
                          "Machine hours are charged to projects by DPR machine lines and the Internal hire run. "
                          "Fixed assets › Equipment costing no longer charges hours each month; its year-end true-up "
                          "compares actual machine cost with every recovery (DPR, internal hire and allocation)."),
    "one_recovery_account": ("One equipment recovery account",
                             "New allocation and true-up postings credit Equipment Hire Recovery (role "
                             "equipment_recovery), the account DPR and internal hire already use. Old postings stay "
                             "on account 5490."),
    "hire_bill_approved_only": ("Hire bills count approved hours only",
                                "A monthly hire bill counts approved logsheet hours only. Hours still in draft are "
                                "shown beside the total as not yet approved."),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS agree_fixes(id INTEGER PRIMARY KEY, kind TEXT, equipment_id INTEGER, month TEXT,
  amount REAL DEFAULT 0, fa_amount REAL DEFAULT 0, voucher_id INTEGER, status TEXT DEFAULT 'proposed',
  created_by INTEGER, ts TEXT, posted_at TEXT);
CREATE INDEX IF NOT EXISTS ix_agree_fix ON agree_fixes(equipment_id, month);
"""

INVENTORY_ROLES = ("inventory", "inventory_fuel", "inventory_spares")
POSTED = "v.status IN ('posted','reversed')"
_ORIG = {}


def on(c, key):
    return str(setting(c, "agree_" + key) or "0") == "1"


def _has(c, table):
    return bool(val(c, "SELECT COUNT(*) FROM sqlite_master WHERE name=?", (table,)))


def _cols(c, table):
    return {r[1] for r in c.execute("PRAGMA table_info(%s)" % table)}


def _month_of(d):
    return (d or "")[:7]


# ───────────────────────── machines in both registers ─────────────────────────
def fa_of_eq(c, eid):
    if not _has(c, "fa_register"):
        return None
    return q1(c, "SELECT * FROM fa_register WHERE kind='equipment' AND ref_id=? ORDER BY id LIMIT 1", (eid,))


def eq_of_fa(c, fa_id):
    r = q1(c, "SELECT kind, ref_id FROM fa_register WHERE id=?", (fa_id,))
    return r["ref_id"] if r and r["kind"] == "equipment" else None


def fa_dep_of(c, eid, month):
    """Fixed assets depreciation of a machine for a month (all components), with its vouchers."""
    fa = fa_of_eq(c, eid)
    if not fa:
        return 0.0, []
    rows = q(c, "SELECT amount, voucher_id FROM fa_dep WHERE fa_id=? AND month=?", (fa["id"], month))
    return r2(sum(num(x["amount"]) for x in rows)), sorted({x["voucher_id"] for x in rows if x["voucher_id"]})


def dep_done(c, eid, month):
    """True when the machine is depreciated for the month by either route."""
    if q1(c, "SELECT id FROM dep_runs WHERE equipment_id=? AND month=?", (eid, month)):
        return True
    fa = fa_of_eq(c, eid)
    return bool(fa and q1(c, "SELECT id FROM fa_dep WHERE fa_id=? AND month=?", (fa["id"], month)))


def _vno(c, vid):
    return val(c, "SELECT no FROM vouchers WHERE id=?", (vid,), None) if vid else None


METHOD = {"sl": "SL", "wdv": "WDV", "hours": "UOP"}


def history_of(c, eq):
    """What the equipment register knows about a machine, in Fixed assets terms (blank fields are left out)."""
    eq = dict(eq)
    out = {"accumulated": r2(num(eq.get("accumulated_dep")))}
    m = METHOD.get((eq.get("dep_method") or "").lower())
    if m:
        out["method"] = m
    if num(eq.get("life_months")):
        out["life_years"] = r2(num(eq["life_months"]) / 12.0)
    if num(eq.get("est_total_hours")):
        out["life_hours"] = num(eq["est_total_hours"])
    if eq.get("residual_value") not in (None, ""):
        out["residual"] = r2(num(eq["residual_value"]))
    if num(eq.get("wdv_rate")):
        out["wdv_rate"] = num(eq["wdv_rate"]) / 100.0
    return out


def _apply_history(c, fa_id, eq):
    h = history_of(c, eq)
    cols = _cols(c, "fa_register")
    upd(c, "fa_register", fa_id, {k: v for k, v in h.items() if k in cols})
    return h


def _sync_one(c, u, eid):
    """Put one machine in the Fixed assets register (with its history) when it is not there yet."""
    fa = fa_of_eq(c, eid)
    if fa:
        return fa
    before = val(c, "SELECT COALESCE(MAX(id),0) FROM fa_register")
    _ORIG["fa.sync"](c, u, {})
    for r in q(c, "SELECT id, ref_id FROM fa_register WHERE kind='equipment' AND id>?", (before,)):
        if r["ref_id"] == eid or on(c, "one_dep_route"):
            _apply_history(c, r["id"], get(c, "equipment", r["ref_id"]))
    return fa_of_eq(c, eid)


# ───────────────────────── 2.38.1 one depreciation route ─────────────────────────
def dep_run(c, u, a):
    if on(c, "one_dep_route"):
        raise ApiError("Depreciation is posted from Fixed assets › Depreciation.")
    import api_equipment_reports as ER
    m = a.get("month") or ""
    if len(m) != 7:
        raise ApiError("Choose a month.")
    if m >= today()[:7]:
        raise ApiError("Depreciation can be run only for completed months.")
    total, n, skipped = 0, 0, []
    for eq in q(c, "SELECT * FROM equipment WHERE ownership='owned' AND active=1 AND purchase_value>0"):
        if dep_done(c, eq["id"], m):
            if not q1(c, "SELECT id FROM dep_runs WHERE equipment_id=? AND month=?", (eq["id"], m)):
                skipped.append(eq["code"])
            continue
        amt = ER.dep_amount(c, eq, m)
        if amt <= 0:
            continue
        vid = ER.post_voucher(c, u, "journal", month_end(m), "Depreciation %s %s" % (eq["code"], m),
                              [{"role": "depreciation", "debit": amt, "equipment_id": eq["id"],
                                "project_id": eq["project_id"]},
                               {"role": "accum_dep", "credit": amt, "equipment_id": eq["id"]}],
                              project_id=eq["project_id"], source="depreciation", source_id=eq["id"])
        ins(c, "dep_runs", {"equipment_id": eq["id"], "month": m, "amount": amt, "voucher_id": vid})
        upd(c, "equipment", eq["id"], {"accumulated_dep": r2((eq["accumulated_dep"] or 0) + amt)})
        total += amt
        n += 1
    return {"count": n, "total": r2(total), "skipped_fa": skipped}


def dep_preview(c, u, a):
    rows = _ORIG["dep.preview"](c, u, a)
    m = a["month"]
    official = on(c, "one_dep_route")
    for r in rows:
        fa_amt, vids = fa_dep_of(c, r["equipment_id"], m)
        eq_posted = r["posted"]
        r["fa_amount"], r["fa_vouchers"] = fa_amt, [_vno(c, v) for v in vids]
        r["route"] = "both" if (eq_posted and vids) else ("fa" if vids else ("equipment" if eq_posted else None))
        if vids and not eq_posted:
            r["amount"], r["posted"] = fa_amt, True
        r["read_only"] = official
        r["note"] = "Posted by Fixed assets › Depreciation run" if vids else (
            "Waiting for Fixed assets › Depreciation run" if official else "")
    return rows


def _dep_rows(c, month, hours_override=None):
    """Fixed assets' monthly rows, without any machine already depreciated by Equipment › Depreciation."""
    rows = _ORIG["_dep_rows"](c, month, hours_override)
    out = []
    for x in rows:
        eid = eq_of_fa(c, x["fa_id"])
        if eid and q1(c, "SELECT id FROM dep_runs WHERE equipment_id=? AND month=?", (eid, month)):
            continue
        out.append(x)
    return out


def fa_dep_run(c, u, a):
    """As before, with one voucher line per machine (equipment_id), so the ledger shows each machine's share."""
    import api_fa as FA
    month = (a.get("month") or today())[:7]
    end = month_end(month + "-01")
    FA.assert_open(c, u, end)
    rows = FA._dep_rows(c, month, a.get("hours"))
    if not rows:
        raise ApiError("Nothing to depreciate for %s (already posted, or no hours on the logsheets)." % month)
    by_proj = {}
    for x in rows:
        for p, v in x["split"].items():
            by_proj.setdefault(p, []).append((x, v))
    vids = {}
    for p, xs in by_proj.items():
        lines = []
        for x, v in xs:
            eid = eq_of_fa(c, x["fa_id"])
            lines.append({"role": "depreciation", "debit": r2(v), "equipment_id": eid,
                          "narration": "NAS 16 depreciation %s %s" % (x["code"], month)})
            lines.append({"role": "accum_dep", "credit": r2(v), "equipment_id": eid,
                          "narration": "Accumulated depreciation %s" % x["code"]})
        vids[p] = FA._post(c, u, {"date": end, "type": "journal", "project_id": p, "source": "fa_dep", "source_id": None,
                                  "narration": "Depreciation of plant and equipment for " + month}, lines)
    keep_eq = on(c, "one_dep_route")
    for x in rows:
        p0 = list(x["split"])[0]
        ins(c, "fa_dep", {"fa_id": x["fa_id"], "comp_id": x["comp_id"], "month": month, "method": x["method"],
                          "hours": x["hours"], "amount": x["amount"], "project_id": p0, "voucher_id": vids.get(p0),
                          "ts": now()})
        if x["comp_id"]:
            c.execute("UPDATE fa_components SET accumulated=accumulated+? WHERE id=?", (x["amount"], x["comp_id"]))
        c.execute("UPDATE fa_register SET accumulated=accumulated+? WHERE id=?", (x["amount"], x["fa_id"]))
        ins(c, "fa_costs", {"fa_id": x["fa_id"], "date": end, "category": "depreciation", "amount": x["amount"],
                            "project_id": p0, "voucher_id": vids.get(p0), "ref": "DEP " + month, "ts": now()})
        eid = eq_of_fa(c, x["fa_id"])
        if keep_eq and eid:       # the equipment register follows the official route
            c.execute("UPDATE equipment SET accumulated_dep=COALESCE(accumulated_dep,0)+? WHERE id=?", (x["amount"], eid))
    audit(c, u, "dep_run", "fa_register", None, {"month": month, "items": len(rows)})
    return {"month": month, "items": len(rows), "total": r2(sum(x["amount"] for x in rows)),
            "vouchers": [v for v in vids.values() if v]}


def fa_sync(c, u, a):
    before = val(c, "SELECT COALESCE(MAX(id),0) FROM fa_register")
    out = _ORIG["fa.sync"](c, u, a)
    if on(c, "one_dep_route"):
        n = 0
        for r in q(c, "SELECT id, ref_id FROM fa_register WHERE kind='equipment' AND id>?", (before,)):
            eq = q1(c, "SELECT * FROM equipment WHERE id=?", (r["ref_id"],))
            if eq:
                _apply_history(c, r["id"], eq)
                n += 1
        out["history"] = n
    return out


def ledger_accum(c, eid):
    """The machine's share of accumulated depreciation in the ledger: lines that name the machine, plus its part of
    Fixed assets vouchers posted before 2.38 (one line per project, without the machine), taken from fa_dep."""
    named = -val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id "
                    "JOIN accounts x ON x.id=l.account_id WHERE x.role='accum_dep' AND l.equipment_id=? AND " + POSTED, (eid,))
    fa = fa_of_eq(c, eid)
    old = 0
    if fa:
        old = val(c, "SELECT SUM(d.amount) FROM fa_dep d JOIN vouchers v ON v.id=d.voucher_id WHERE d.fa_id=? AND " + POSTED +
                     " AND NOT EXISTS(SELECT 1 FROM voucher_lines l JOIN accounts x ON x.id=l.account_id WHERE "
                     "l.voucher_id=d.voucher_id AND x.role='accum_dep' AND l.equipment_id IS NOT NULL)", (fa["id"],))
    return r2(num(named) + num(old))


def ledger_cost(c, eid):
    return r2(val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id "
                     "JOIN accounts x ON x.id=l.account_id WHERE x.role='fixed_asset' AND l.equipment_id=? AND " + POSTED, (eid,)))


def _history_rows(c):
    out = []
    if not _has(c, "fa_register"):
        return out
    for r in q(c, "SELECT r.id fa_id, r.code, r.name, r.accumulated, r.method, r.life_years, e.id equipment_id, "
                  "e.accumulated_dep, e.dep_method, e.life_months FROM fa_register r JOIN equipment e ON e.id=r.ref_id "
                  "WHERE r.kind='equipment' AND r.status<>'disposed' AND ABS(COALESCE(r.accumulated,0))<0.005 "
                  "AND COALESCE(e.accumulated_dep,0)>0.005 AND NOT EXISTS(SELECT 1 FROM fa_dep d WHERE d.fa_id=r.id) "
                  "ORDER BY r.code"):
        r["dep_runs_total"] = r2(val(c, "SELECT SUM(amount) FROM dep_runs WHERE equipment_id=?", (r["equipment_id"],)))
        r["ledger"] = ledger_accum(c, r["equipment_id"])
        r["after"] = r2(num(r["accumulated_dep"]))
        out.append(r)
    return out


@api("agree.history_preview", "assets", "view")
def history_preview(c, u, a):
    """Machines already in Fixed assets with no depreciation history although the equipment register has some."""
    return _history_rows(c)


@api("agree.history_apply", "assets", "approve")
def history_apply(c, u, a):
    """Copy the history into the Fixed assets register. No voucher: the ledger already holds this depreciation."""
    ids = {int(x) for x in (a.get("ids") or [])}
    n = 0
    for r in _history_rows(c):
        if ids and r["fa_id"] not in ids:
            continue
        h = _apply_history(c, r["fa_id"], get(c, "equipment", r["equipment_id"]))
        audit(c, u, "history", "fa_register", r["fa_id"], h)
        n += 1
    return {"updated": n}


# ── Fixed assets > Depreciation run > Check ──
def _dups(c):
    if not _has(c, "fa_register"):
        return []
    rows = q(c, "SELECT d.id dep_run_id, d.equipment_id, d.month, d.amount, d.voucher_id, e.code, e.name, r.id fa_id "
                "FROM dep_runs d JOIN equipment e ON e.id=d.equipment_id JOIN fa_register r ON r.kind='equipment' "
                "AND r.ref_id=d.equipment_id WHERE EXISTS(SELECT 1 FROM fa_dep f WHERE f.fa_id=r.id AND f.month=d.month) "
                "ORDER BY d.month, e.code")
    for r in rows:
        r["fa_amount"], vids = fa_dep_of(c, r["equipment_id"], r["month"])
        r["voucher_no"] = _vno(c, r["voucher_id"])
        r["fa_vouchers"] = [_vno(c, v) for v in vids]
        fx = q1(c, "SELECT * FROM agree_fixes WHERE kind='dup_dep' AND equipment_id=? AND month=? AND status IN "
                   "('proposed','posted') ORDER BY id DESC", (r["equipment_id"], r["month"]))
        r["fix"] = {"id": fx["id"], "status": fx["status"], "voucher_no": _vno(c, fx["voucher_id"])} if fx else None
    return rows


@api("agree.dup_dep", "assets", "view")
def dup_dep(c, u, a):
    rows = _dups(c)
    return {"rows": rows, "open": len([r for r in rows if not (r["fix"] and r["fix"]["status"] == "posted")])}


def _queue(c, u, vid, label, project_id, amount, source_id):
    """Put a correcting voucher in the accounts posting queue (stage review)."""
    import api_exec as X
    v = q1(c, "SELECT * FROM vouchers WHERE id=?", (vid,))
    if v["no"]:
        X._unnumber(c, v["no"])
    upd(c, "vouchers", vid, {"no": None, "approved_by": None})
    c.execute("INSERT OR REPLACE INTO post_queue(voucher_id, source, source_id, gate, module, stage, label, project_id, "
              "amount, vtype, created_by, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
              (vid, "agree_fix", source_id, "correction", "accounts", "review", label, project_id, amount, "journal",
               u["id"] if u else None, now()))


@api("agree.dup_propose", "accounts", "edit")
def dup_propose(c, u, a):
    """Propose reversing the Equipment › Depreciation posting of a machine and month that Fixed assets also
    depreciated. The reversal waits in the posting queue; nothing changes until an accounts approver posts it."""
    rid = int(a["dep_run_id"])
    r = next((x for x in _dups(c) if x["dep_run_id"] == rid), None)
    if not r:
        raise ApiError("This month is not depreciated twice.")
    if r["fix"]:
        raise ApiError("A reversal is already %s (%s)." % (r["fix"]["status"], r["fix"]["voucher_no"] or "in the posting queue"))
    lines = q(c, "SELECT * FROM voucher_lines WHERE voucher_id=?", (r["voucher_id"],)) if r["voucher_id"] else []
    proj = next((x["project_id"] for x in lines if x["project_id"]), None)
    d = today()
    rl = [{"role": "accum_dep", "debit": r["amount"], "equipment_id": r["equipment_id"], "project_id": proj,
           "narration": "Duplicate depreciation %s %s taken back" % (r["code"], r["month"])},
          {"role": "depreciation", "credit": r["amount"], "equipment_id": r["equipment_id"], "project_id": proj,
           "narration": "Also depreciated by Fixed assets (%s)" % ", ".join(x for x in r["fa_vouchers"] if x)}]
    import api_exec as X
    post = X._ORIG.get("post", core.post_voucher)
    vid = post(c, u, "journal", d, "Reversal of duplicate depreciation %s %s (%s)" % (r["code"], r["month"], r["voucher_no"]),
               rl, project_id=proj, source="agree_fix", source_id=r["dep_run_id"], status="submitted")
    _queue(c, u, vid, "Duplicate depreciation %s %s" % (r["code"], r["month"]), proj, r["amount"], r["dep_run_id"])
    fid = ins(c, "agree_fixes", {"kind": "dup_dep", "equipment_id": r["equipment_id"], "month": r["month"],
                                 "amount": r["amount"], "fa_amount": r["fa_amount"], "voucher_id": vid,
                                 "status": "proposed", "created_by": u["id"], "ts": now()})
    audit(c, u, "propose", "agree_fixes", fid, {"machine": r["code"], "month": r["month"], "amount": r["amount"]})
    return {"id": fid, "voucher_id": vid}


def _settle_fixes(c, u):
    """After the posting queue posts: bring the equipment register in step with each correction now in the books."""
    for fx in q(c, "SELECT f.* FROM agree_fixes f JOIN vouchers v ON v.id=f.voucher_id WHERE f.status='proposed' "
                   "AND v.status='posted'"):
        # the machine now carries the Fixed assets depreciation for that month instead of the Equipment one
        c.execute("UPDATE equipment SET accumulated_dep=COALESCE(accumulated_dep,0)-?+? WHERE id=?",
                  (fx["amount"], fx["fa_amount"], fx["equipment_id"]))
        upd(c, "agree_fixes", fx["id"], {"status": "posted", "posted_at": now()})
        audit(c, u, "settle", "agree_fixes", fx["id"], {"equipment_id": fx["equipment_id"], "month": fx["month"]})
    for fx in q(c, "SELECT f.id FROM agree_fixes f LEFT JOIN vouchers v ON v.id=f.voucher_id WHERE f.status='proposed' "
                   "AND v.id IS NULL"):
        upd(c, "agree_fixes", fx["id"], {"status": "withdrawn"})


def pq_post(c, u, a):
    out = _ORIG["pq.post"](c, u, a)
    _settle_fixes(c, u)
    return out


# ───────────────────────── 2.38.2 one machine-charge route ─────────────────────────
def charged_hours(c, eid, pid, month):
    """Hours of a machine on a project in a month already charged by a DPR or by the Internal hire run."""
    dpr = num(val(c, "SELECT SUM(hours) FROM logsheets WHERE equipment_id=? AND project_id=? AND dpr_id IS NOT NULL "
                     "AND date BETWEEN ? AND ?", (eid, pid, month + "-01", month_end(month))))
    ib = num(val(c, "SELECT SUM(hours) FROM internal_bills WHERE equipment_id=? AND project_id=? AND month=?",
                 (eid, pid, month)))
    return dpr, ib


def _alloc_rows(c, month, only=None):
    rows = _ORIG["_alloc_rows"](c, month, only)
    if not on(c, "alloc_trueup_only"):
        return rows
    out = []
    for x in rows:
        eid = eq_of_fa(c, x["fa_id"])
        dpr, ib = charged_hours(c, eid, x["project_id"], month) if eid else (0, 0)
        left = r2(max(0.0, num(x["hours"]) - dpr - ib))
        x.update({"logged_hours": x["hours"], "dpr_hours": r2(dpr), "internal_hours": r2(ib), "hours": left,
                  "amount": r2(left * num(x["rate"]))})
        out.append(x)
    return out


def fa_alloc_run(c, u, a):
    if on(c, "alloc_trueup_only"):
        raise ApiError("Machine hours are charged to projects by DPR machine lines and the Internal hire run "
                       "(Equipment › Depreciation & hire charges). Allocation is used only for the year-end true-up, "
                       "so no hour is charged twice.")
    return _ORIG["fa.alloc_run"](c, u, a)


def fa_trueup_preview(c, u, a):
    if not on(c, "alloc_trueup_only"):
        return _ORIG["fa.trueup_preview"](c, u, a)
    import api_fa as FA
    fy, s, e = FA.fy_bounds(c, a.get("fy"), a.get("on"))
    out = []
    for r in q(c, "SELECT * FROM fa_register WHERE kind='equipment' ORDER BY code"):
        actual = num(val(c, "SELECT SUM(amount) FROM fa_costs WHERE fa_id=? AND date BETWEEN ? AND ?", (r["id"], s, e)))
        charges = {x["project_id"]: num(x["a"]) for x in q(
            c, "SELECT project_id, SUM(amount) a FROM fa_alloc WHERE fa_id=? AND kind='charge' AND month BETWEEN ? "
               "AND ? GROUP BY project_id", (r["id"], s[:7], e[:7]))}
        # every other recovery of this machine in the year: DPR machine lines and internal hire
        for x in q(c, "SELECT l.project_id, SUM(l.credit-l.debit) a FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id "
                      "JOIN accounts x ON x.id=l.account_id WHERE x.role='equipment_recovery' AND l.equipment_id=? AND "
                      "v.date BETWEEN ? AND ? AND v.source NOT IN ('fa_trueup','fa_alloc') AND " + POSTED +
                      " GROUP BY l.project_id", (r["ref_id"], s, e)):
            if x["project_id"]:
                charges[x["project_id"]] = charges.get(x["project_id"], 0) + num(x["a"])
        charges = {k: v for k, v in charges.items() if abs(v) > EPS}
        if not charges or not actual:
            continue
        t = FA.F.true_up(actual, charges)
        t.update({"fa_id": r["id"], "code": r["code"], "name": r["name"], "recovered": r2(sum(charges.values()))})
        out.append(t)
    done = bool(val(c, "SELECT COUNT(*) FROM fa_alloc WHERE kind='true_up' AND fy=?", (fy,)))
    return {"fy": fy, "date": e, "rows": out, "variance": r2(sum(x["variance"] for x in out)), "posted": done,
            "basis": "all recoveries"}


def role_account(c, role):
    if role == "equip_recovery" and on(c, "one_recovery_account"):
        role = "equipment_recovery"
    return _ORIG["role_account"](c, role)


# ───────────────────────── 2.38.3 disposal always posts ─────────────────────────
def disp_advance(c, u, a):
    d = get(c, "asset_disposals", int(a["id"]), "Disposal")
    if not a.get("cancel") and d["status"] == "approved" and _has(c, "fa_register"):
        eq = get(c, "equipment", d["equipment_id"], "Equipment")
        if eq.get("ownership") not in ("rented", "hired", "rental") and num(eq.get("purchase_value")) > 0:
            open_dup = [x for x in _dups(c) if x["equipment_id"] == eq["id"] and not (x["fix"] and x["fix"]["status"] == "posted")]
            if open_dup:
                raise ApiError("%s is depreciated twice for %s. Correct it first in Fixed assets › Depreciation run › "
                               "Check, so the disposal uses the right figures." % (eq["code"], ", ".join(x["month"] for x in open_dup)))
            fa = fa_of_eq(c, eq["id"])
            if fa is None or fa["status"] != "disposed":
                fa = _sync_one(c, u, eq["id"])
                if fa and abs(num(fa["accumulated"])) < 0.005 and num(eq.get("accumulated_dep")) > 0.005 and \
                        not q1(c, "SELECT id FROM fa_dep WHERE fa_id=?", (fa["id"],)):
                    h = _apply_history(c, fa["id"], eq)
                    audit(c, u, "history", "fa_register", fa["id"], h)
    return _ORIG["life.disp_advance"](c, u, a)


def fa_dispose(c, u, a):
    """As before; the disposal voucher's lines now name the machine, so its cost and depreciation clear per machine."""
    res = _ORIG["fa.dispose"](c, u, a)
    eid = eq_of_fa(c, int(a["id"]))
    if eid and res.get("voucher_id"):
        c.execute("UPDATE voucher_lines SET equipment_id=? WHERE voucher_id=? AND equipment_id IS NULL", (eid, res["voucher_id"]))
    return res


# ───────────────────────── 2.38.6 hire bills: approved hours only ─────────────────────────
def hire_bill(c, u, a):
    if not on(c, "hire_bill_approved_only"):
        return _ORIG["hire.bill"](c, u, a)
    import api_life as L
    core.need(a, "agreement_id", "month")
    L.ensure(c)
    ag = get(c, "hire_agreements", int(a["agreement_id"]), "Hire agreement")
    m = a["month"]
    if q1(c, "SELECT id FROM hire_bills WHERE agreement_id=? AND month=?", (ag["id"], m)):
        raise ApiError("This month is already billed.")
    start, end = m + "-01", month_end(m)
    logs = q(c, "SELECT date, hours, status FROM logsheets WHERE equipment_id=? AND project_id=? AND date BETWEEN ? AND ?",
             (ag["equipment_id"], ag["project_id"], start, end))
    ok = [x for x in logs if x["status"] == "approved"]
    draft_h = r2(sum(num(x["hours"]) for x in logs if x["status"] != "approved"))
    draft_n = len([x for x in logs if x["status"] != "approved"])
    if ag["unit"] == "hour":
        units = sum(num(x["hours"]) for x in ok)
    elif ag["unit"] == "day":
        units = len({x["date"] for x in ok if num(x["hours"]) > 0})
    else:
        units = 1
    billed = max(units, ag["min_units"] or 0)
    first = not val(c, "SELECT COUNT(*) FROM hire_bills WHERE agreement_id=?", (ag["id"],))
    amount = r2(billed * ag["rate"])
    eq = get(c, "equipment", ag["equipment_id"])
    acc = val(c, "SELECT id FROM accounts WHERE role='hire_cost'")
    if not acc:
        raise ApiError("Set an account with role 'hire_cost'.")
    note = "; %s h on %d logsheet(s) not yet approved, not billed" % (draft_h, draft_n) if draft_n else ""
    iid = ins(c, "invoices", {"kind": "purchase", "party_id": ag["vendor_id"], "project_id": ag["project_id"],
                              "date": end, "party_inv_no": a.get("party_inv_no"), "status": "draft",
                              "source": "hire", "remarks": ("Hire of %s for %s%s" % (eq["name"], m, note))[:500],
                              "created_by": u["id"]})
    ins(c, "invoice_lines", {"invoice_id": iid, "description": "%s %s: %s %s (approved %s%s)" %
                             (eq["code"], m, r2(billed), ag["unit"], r2(units), note), "qty": r2(billed),
                             "rate": ag["rate"], "vat_rate": ag["vat_rate"] or 0, "amount": amount,
                             "account_id": acc, "equipment_id": eq["id"]})
    if first and ag["mob_cost"]:
        ins(c, "invoice_lines", {"invoice_id": iid, "description": "Mobilisation %s" % eq["code"], "qty": 1,
                                 "rate": ag["mob_cost"], "vat_rate": ag["vat_rate"] or 0, "amount": ag["mob_cost"],
                                 "account_id": acc, "equipment_id": eq["id"]})
    ins(c, "hire_bills", {"agreement_id": ag["id"], "month": m, "units": r2(units), "billed_units": r2(billed),
                          "amount": amount, "invoice_id": iid})
    out = {"invoice_id": iid, "units": r2(units), "billed": r2(billed), "draft_hours": draft_h, "draft_logsheets": draft_n}
    if ag["unit"] == "hour":      # attachments at their own hire rate (as in 2.x), approved sheets only
        added = 0.0
        for x in q(c, "SELECT x.name, x.hire_rate_hr, SUM(t.hours) h FROM log_tools t JOIN eq_tools x ON x.id=t.tool_id "
                      "JOIN logsheets l ON l.id=t.log_id WHERE l.equipment_id=? AND l.project_id=? AND l.date BETWEEN ? AND ? "
                      "AND l.status='approved' AND x.hire_rate_hr>0 GROUP BY x.id",
                   (ag["equipment_id"], ag["project_id"], start, end)):
            diff = r2((x["hire_rate_hr"] - (ag["rate"] or 0)) * x["h"])
            if abs(diff) < 0.005:
                continue
            ins(c, "invoice_lines", {"invoice_id": iid, "description": "%s: %s h at %s instead of %s" % (
                x["name"], r2(x["h"]), x["hire_rate_hr"], ag["rate"]), "qty": r2(x["h"]),
                "rate": r2(x["hire_rate_hr"] - (ag["rate"] or 0)), "vat_rate": ag["vat_rate"] or 0, "amount": diff,
                "account_id": acc, "equipment_id": ag["equipment_id"]})
            added += diff
        if added:
            c.execute("UPDATE hire_bills SET amount=amount+? WHERE agreement_id=? AND month=?", (added, ag["id"], m))
            out["attachment_extra"] = r2(added)
    return out


# ───────────────────────── 2.38.7 histogram labour in man-days ─────────────────────────
def _fix_res_units(c, pid=None):
    if not _has(c, "act_resources"):
        return 0
    cond, p = "", []
    if pid:
        cond, p = " AND project_id=?", [pid]
    cur = c.execute("UPDATE act_resources SET unit='day' WHERE kind='L' AND source='rate_analysis' AND unit='hr'" + cond, p)
    return cur.rowcount or 0


def res_load(c, u, a):
    out = _ORIG["res.load"](c, u, a)
    _fix_res_units(c, int(a["project_id"]) if a.get("project_id") else None)
    return out


# ───────────────────────── 2.38.4 / 2.38.5 one data check list ─────────────────────────
def _role_bal(c, roles, project_id=None, status=POSTED):
    cond, p = "", list(roles)
    if project_id:
        cond = " AND l.project_id=?"
        p.append(project_id)
    return r2(val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts a "
                     "ON a.id=l.account_id WHERE a.role IN (%s) AND %s%s" % (",".join("?" * len(roles)), status, cond), p))


def _m(x):
    return "{:,.2f}".format(num(x))


def stock_vs_books(c):
    """Per project: stock value, books, and the queued vouchers that explain the difference."""
    out = []
    for p in q(c, "SELECT id, code FROM projects ORDER BY code"):
        stock = r2(val(c, "SELECT SUM(value) FROM stock_balances WHERE project_id=?", (p["id"],)))
        books = _role_bal(c, INVENTORY_ROLES, p["id"])
        diff = r2(stock - books)
        queued = q(c, "SELECT v.id, v.date, COALESCE(pq.label, v.narration) label, SUM(l.debit-l.credit) amt FROM voucher_lines l "
                      "JOIN vouchers v ON v.id=l.voucher_id JOIN accounts a ON a.id=l.account_id LEFT JOIN post_queue pq "
                      "ON pq.voucher_id=v.id WHERE a.role IN (%s) AND l.project_id=? AND v.status='submitted' "
                      "GROUP BY v.id ORDER BY v.date" % ",".join("?" * len(INVENTORY_ROLES)),
                   list(INVENTORY_ROLES) + [p["id"]]) if _has(c, "post_queue") else []
        explained = r2(sum(num(x["amt"]) for x in queued))
        left = r2(diff - explained)
        if abs(stock) < 0.5 and abs(books) < 0.5 and not queued:
            continue
        out.append({"project_id": p["id"], "code": p["code"], "stock": stock, "books": books, "difference": diff,
                    "queued": [{"ref": x["label"], "date": x["date"], "amount": r2(x["amt"])} for x in queued],
                    "explained": explained, "unexplained": left})
    return out


def _stock_detail(r):
    t = "Store %s, books %s, difference %s" % (_m(r["stock"]), _m(r["books"]), _m(r["difference"]))
    if r["queued"]:
        t += " = %d voucher(s) waiting in the posting queue (%s)" % (
            len(r["queued"]), ", ".join(x["ref"] or "" for x in r["queued"][:3]))
        if abs(r["unexplained"]) >= 1:
            t += ", %s not explained" % _m(r["unexplained"])
    return t


def extra_checks(c, add):
    # store against books, with the posting queue explained
    sv = stock_vs_books(c)
    bad = [r for r in sv if abs(r["unexplained"]) >= 1]
    queued = [r for r in sv if r["queued"] and abs(r["unexplained"]) < 1 and abs(r["difference"]) >= 1]
    detail = "; ".join("%s: %s" % (r["code"], _stock_detail(r)) for r in (bad or queued)[:4]) or "Every project agrees"
    add("Stock", "Stock value = inventory accounts, project by project", "error", not bad, detail,
        [{"ref": r["code"], "date": "", "amount": r["unexplained"], "detail": _stock_detail(r)} for r in bad + queued],
        "Inventory › Stock ledger and Accounts › Posting queue", amount=r2(sum(r["unexplained"] for r in bad)))
    if queued and not bad:
        out_q = [r for r in sv if r["queued"]]
        add("Stock", "Store and books differ only by vouchers waiting in the posting queue", "warning", False,
            "; ".join("%s: difference explained by %d queued voucher(s)" % (r["code"], len(r["queued"])) for r in out_q),
            [{"ref": x["ref"], "date": x["date"], "amount": x["amount"], "detail": r["code"]} for r in out_q for x in r["queued"]],
            "Accounts › Posting queue")

    if _has(c, "fa_register"):
        # Fixed assets register = ledger
        cost = r2(val(c, "SELECT SUM(cost) FROM fa_register WHERE status<>'disposed'"))
        acc = r2(val(c, "SELECT SUM(accumulated) FROM fa_register WHERE status<>'disposed'"))
        l_cost = _role_bal(c, ("fixed_asset",)) + r2(val(c, "SELECT SUM(opening_balance) FROM accounts WHERE role='fixed_asset'"))
        l_acc = -(_role_bal(c, ("accum_dep",)) + r2(val(c, "SELECT SUM(opening_balance) FROM accounts WHERE role='accum_dep'")))
        by_class = q(c, "SELECT klass, SUM(cost) cost, SUM(accumulated) acc FROM fa_register WHERE status<>'disposed' "
                        "GROUP BY klass ORDER BY klass")
        ok = abs(cost - l_cost) < 1 and abs(acc - l_acc) < 1
        add("Fixed assets", "Fixed asset register cost and accumulated depreciation = ledger", "warning", ok,
            "Register cost %s, ledger %s; register depreciation %s, ledger %s (the ledger has one account each, so "
            "classes are listed from the register)" % (_m(cost), _m(l_cost), _m(acc), _m(l_acc)),
            [{"ref": x["klass"] or "-", "date": "", "amount": r2(x["cost"]), "detail": "accumulated %s" % _m(x["acc"])}
             for x in by_class], "Fixed assets › Capital register", amount=r2(cost - l_cost))
        # equipment register = FA register
        diff = []
        for r in q(c, "SELECT r.code, r.cost, r.accumulated, e.purchase_value, e.accumulated_dep FROM fa_register r "
                      "JOIN equipment e ON e.id=r.ref_id WHERE r.kind='equipment' AND r.status<>'disposed' ORDER BY r.code"):
            if abs(num(r["cost"]) - num(r["purchase_value"])) >= 1 or abs(num(r["accumulated"]) - num(r["accumulated_dep"])) >= 1:
                diff.append({"ref": r["code"], "date": "", "amount": r2(num(r["accumulated"]) - num(r["accumulated_dep"])),
                             "detail": "cost %s / %s, depreciation %s / %s (Fixed assets / Equipment)" % (
                                 _m(r["cost"]), _m(r["purchase_value"]), _m(r["accumulated"]), _m(r["accumulated_dep"]))})
        add("Fixed assets", "Equipment register = Fixed asset register (cost and depreciation)", "warning", not diff,
            "%d machine(s) differ" % len(diff) if diff else "All machines agree", diff,
            "Fixed assets › Depreciation run › Check (Bring history across)")
        # no machine and month depreciated twice
        dups = [r for r in _dups(c) if not (r["fix"] and r["fix"]["status"] == "posted")]
        add("Fixed assets", "No machine and month depreciated twice", "error", not dups,
            "%d machine-month(s) depreciated by both Equipment and Fixed assets" % len(dups) if dups else "None",
            [{"ref": "%s %s" % (r["code"], r["month"]), "date": r["month"], "amount": r["amount"],
              "detail": "%s and %s" % (r["voucher_no"], ", ".join(x for x in r["fa_vouchers"] if x))} for r in dups],
            "Fixed assets › Depreciation run › Check")
        # no machine hours charged twice
        twice = []
        for x in q(c, "SELECT r.ref_id equipment_id, r.code, a.project_id, a.month, SUM(a.hours) h FROM fa_alloc a JOIN "
                      "fa_register r ON r.id=a.fa_id WHERE a.kind='charge' AND r.kind='equipment' "
                      "GROUP BY r.ref_id, a.project_id, a.month"):
            dpr, ib = charged_hours(c, x["equipment_id"], x["project_id"], x["month"])
            logged = num(val(c, "SELECT SUM(hours) FROM logsheets WHERE equipment_id=? AND project_id=? AND date BETWEEN ? AND ?",
                             (x["equipment_id"], x["project_id"], x["month"] + "-01", month_end(x["month"]))))
            charged = num(x["h"]) + dpr + ib
            if dpr + ib > EPS and charged > logged + 0.01:
                twice.append({"ref": "%s %s" % (x["code"], x["month"]), "date": x["month"], "amount": r2(charged - logged),
                              "detail": "logged %s h, charged %s h (allocation %s, DPR %s, internal hire %s)" % (
                                  r2(logged), r2(charged), r2(x["h"]), r2(dpr), r2(ib))})
        add("Equipment", "No machine hours charged twice (DPR, internal hire, allocation)", "error", not twice,
            "%d machine-month(s) charged more hours than logged" % len(twice) if twice else "None", twice,
            "Fixed assets › Equipment costing")

    # wages payable per project = DPR labour accrued - wages paid
    wages = []
    for p in q(c, "SELECT id, code FROM projects ORDER BY code"):
        accrued = r2(val(c, "SELECT SUM(l.amount) FROM dpr_labour l JOIN dpr d ON d.id=l.dpr_id WHERE d.project_id=? AND "
                            "l.party_id IS NULL AND EXISTS(SELECT 1 FROM vouchers v WHERE v.source='dpr' AND v.source_id=d.id "
                            "AND v.status='posted')", (p["id"],)))
        paid = r2(val(c, "SELECT SUM(l.debit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts a "
                         "ON a.id=l.account_id WHERE a.role='payroll_payable' AND l.project_id=? AND " + POSTED, (p["id"],)))
        bal = -_role_bal(c, ("payroll_payable",), p["id"])
        if abs(accrued) < 0.5 and abs(bal) < 0.5:
            continue
        if abs(bal - (accrued - paid)) >= 1:
            wages.append({"ref": p["code"], "date": "", "amount": r2(bal - (accrued - paid)),
                          "detail": "payable %s, DPR labour accrued %s, paid %s" % (_m(bal), _m(accrued), _m(paid))})
    add("Payroll", "Wages payable per project = DPR labour accrued − wages paid", "warning", not wages,
        "%d project(s) differ" % len(wages) if wages else "Every project agrees", wages, "Project › DPR and Accounts › Ledger")

    # loans = ledger
    loans = []
    if _has(c, "eq_finance"):
        typed = r2(val(c, "SELECT SUM(loan_amount) FROM eq_finance"))
        if typed:
            led = -_role_bal(c, ("equipment_loan",))
            loans.append({"ref": "Equipment loans", "date": "", "amount": r2(led),
                          "detail": "ledger balance %s (loans taken %s)" % (_m(led), _m(typed))})
    if _has(c, "loans"):
        for x in q(c, "SELECT name, lender, balance FROM loans WHERE active=1 ORDER BY name"):
            led = -r2(val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN "
                             "accounts a ON a.id=l.account_id WHERE a.type='liability' AND LOWER(a.name) LIKE ? AND " + POSTED,
                          ("%" + (x["name"] or "").lower() + "%",)))
            if abs(led - num(x["balance"])) >= 1:
                loans.append({"ref": x["name"], "date": "", "amount": r2(num(x["balance"]) - led),
                              "detail": "typed %s, ledger account of the same name %s" % (_m(x["balance"]), _m(led))})
    bad_loans = [x for x in loans if x["ref"] != "Equipment loans"]
    add("Loans", "Each loan's balance = its ledger account", "warning", not bad_loans,
        "%d loan(s) differ from the ledger" % len(bad_loans) if bad_loans else "Loans agree (or have no ledger account by name)",
        loans, "Cash › Loans")

    # every disposal has a voucher
    if _has(c, "asset_disposals"):
        nov = q(c, "SELECT d.no, d.completed_on, d.proceeds, e.code FROM asset_disposals d JOIN equipment e ON e.id=d.equipment_id "
                   "WHERE d.status='completed' AND d.voucher_id IS NULL AND COALESCE(e.purchase_value,0)>0")
        add("Fixed assets", "Every equipment disposal has a voucher", "error", not nov,
            "%d disposal(s) without a voucher" % len(nov) if nov else "All posted",
            [{"ref": "%s %s" % (x["no"], x["code"]), "date": x["completed_on"], "amount": x["proceeds"]} for x in nov],
            "Equipment › Lifecycle › Disposal")


# the checks of the first tab not already in the financial data checks
_CARRY = ("GRN clearing", "No negative stock", "No transfers in transit", "Every posting role has an account",
          "Balance sheet balances")


def fc_checks(c, u, a):
    d = _ORIG["fc.checks"](c, u, a)
    out = d["checks"]

    def add(area, name, sev, ok, detail, items=None, fix=None, amount=None):
        out.append({"area": area, "check": name, "ok": bool(ok), "severity": "ok" if ok else sev, "detail": detail,
                    "items": (items or [])[:50], "count": len(items or []), "fix": None if ok else fix, "amount": amount})
    extra_checks(c, add)
    for r in _ORIG["rep.integrity"](c, u, {}):
        if r["check"].startswith(_CARRY):
            add("Stores and ledger", r["check"], "warning" if r["check"].startswith(("No transfers", "No negative")) else "error",
                r["ok"], r["detail"], fix="Accounts › Integrity checks")
    d["summary"] = {"error": len([x for x in out if x["severity"] == "error"]),
                    "warning": len([x for x in out if x["severity"] == "warning"]), "ok": len([x for x in out if x["ok"]])}
    return d


def rep_integrity(c, u, a):
    """Accounts › Integrity checks shows the same single list (first tab), in its own layout."""
    d = inv.FUNCS["fc.checks"][0](c, u, a)
    return [{"check": "%s: %s" % (x["area"], x["check"]), "ok": x["ok"],
             "detail": x["detail"] + ("  (correct in %s)" % x["fix"] if x.get("fix") else "")} for x in d["checks"]]


# ───────────────────────── switches (Administration › Settings › Books agree) ─────────────────────────
def _impact(c, key):
    """Before and after figures for one switch, from the current data."""
    import api_equipment_reports as ER
    m = (date.today().replace(day=1).toordinal() - 1)
    month = date.fromordinal(m).isoformat()[:7]           # last completed month
    rows = []
    if key == "one_dep_route":
        fa_rows = {}
        if _has(c, "fa_register"):
            import api_fa as FA
            try:
                for x in _ORIG["_dep_rows"](c, month, None):
                    fa_rows[x["fa_id"]] = fa_rows.get(x["fa_id"], 0) + x["amount"]
            except Exception:
                fa_rows = {}
        for eq in q(c, "SELECT * FROM equipment WHERE ownership='owned' AND active=1 AND purchase_value>0 ORDER BY code"):
            fa = fa_of_eq(c, eq["id"])
            before = ER.dep_amount(c, eq, month)
            after = r2(fa_rows.get(fa["id"], 0)) if fa else 0
            rows.append({"item": eq["code"], "before": before, "after": after,
                         "note": "not in the Fixed assets register yet: Sync first" if not fa else ""})
        return {"label": "Depreciation for %s per machine (Equipment route, then Fixed assets route)" % month, "rows": rows}
    if key == "alloc_trueup_only":
        if _has(c, "fa_register"):
            for r in q(c, "SELECT a.month, r.code, r.ref_id, a.project_id, SUM(a.hours) h, SUM(a.amount) amt FROM fa_alloc a "
                          "JOIN fa_register r ON r.id=a.fa_id WHERE a.kind='charge' GROUP BY a.month, r.id, a.project_id "
                          "ORDER BY a.month DESC LIMIT 24"):
                dpr, ib = charged_hours(c, r["ref_id"], r["project_id"], r["month"]) if r["ref_id"] else (0, 0)
                rows.append({"item": "%s %s" % (r["code"], r["month"]), "before": r2(r["amt"]), "after": 0,
                             "note": "%s h allocated, of which %s h also charged by DPR/internal hire" % (
                                 r2(r["h"]), r2(min(num(r["h"]), dpr + ib)))})
        return {"label": "Monthly allocation charges already posted (stay posted); after: no new monthly charges", "rows": rows}
    if key == "one_recovery_account":
        for r in q(c, "SELECT code, name, role FROM accounts WHERE role IN ('equip_recovery','equipment_recovery') ORDER BY code"):
            rows.append({"item": "%s %s" % (r["code"], r["name"]), "before": _role_bal(c, (r["role"],)),
                         "after": _role_bal(c, (r["role"],)),
                         "note": "receives new recoveries" if r["role"] == "equipment_recovery" else "keeps its balance; no new postings"})
        return {"label": "Balances do not move; new postings go to one account", "rows": rows}
    if key == "hire_bill_approved_only" and _has(c, "hire_agreements"):
        for ag in q(c, "SELECT h.*, e.code FROM hire_agreements h JOIN equipment e ON e.id=h.equipment_id ORDER BY e.code"):
            if ag["unit"] != "hour":
                continue
            for mm in sorted({x["m"] for x in q(c, "SELECT substr(date,1,7) m FROM logsheets WHERE equipment_id=? AND project_id=?",
                                               (ag["equipment_id"], ag["project_id"]))})[-3:]:
                if q1(c, "SELECT id FROM hire_bills WHERE agreement_id=? AND month=?", (ag["id"], mm)):
                    continue
                allh = num(val(c, "SELECT SUM(hours) FROM logsheets WHERE equipment_id=? AND project_id=? AND substr(date,1,7)=?",
                               (ag["equipment_id"], ag["project_id"], mm)))
                okh = num(val(c, "SELECT SUM(hours) FROM logsheets WHERE equipment_id=? AND project_id=? AND substr(date,1,7)=? "
                                 "AND status='approved'", (ag["equipment_id"], ag["project_id"], mm)))
                rows.append({"item": "%s %s" % (ag["code"], mm), "before": r2(max(allh, ag["min_units"] or 0) * ag["rate"]),
                             "after": r2(max(okh, ag["min_units"] or 0) * ag["rate"]),
                             "note": "%s h logged, %s h approved" % (r2(allh), r2(okh))})
        return {"label": "Hire bills not yet made: amount counting all hours, then approved hours only", "rows": rows}
    return {"label": "", "rows": rows}


@api("agree.switches", "accounts", "view")
def switches(c, u, a):
    out = []
    for k, (label, text) in SWITCHES.items():
        r = {"key": k, "label": label, "text": text, "on": on(c, k),
             "confirmed_by": setting(c, "agree_%s_by" % k) or None}
        if a.get("detail"):
            r["impact"] = _impact(c, k)
        out.append(r)
    return {"version": VERSION_TAG, "switches": out}


@api("agree.switch_set", "accounts", "approve")
def switch_set(c, u, a):
    k = a.get("key")
    if k not in SWITCHES:
        raise ApiError("Unknown setting.")
    v = "1" if a.get("on") in (1, "1", True) else "0"
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", ("agree_" + k, v))
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)",
              ("agree_%s_by" % k, "%s, %s" % (u.get("name") or u.get("username"), today()) if v == "1" else ""))
    audit(c, u, "switch", "settings", None, {"key": k, "on": v})
    return switches(c, u, {})


# ───────────────────────── wiring ─────────────────────────
_DONE = set()


def _wrap(name, fn):
    """Install once per process: start-up can run again (restore, another company) after other modules re-wrapped."""
    cur = inv.FUNCS.get(name)
    if not cur or name in _DONE or getattr(cur[0], "_bco238", False):
        return
    _DONE.add(name)
    _ORIG[name] = cur[0]
    fn._bco238 = True
    inv.FUNCS[name] = (fn, cur[1], cur[2], cur[3])


def _install():
    if getattr(core.role_account, "_bco238", False):
        pass
    else:
        _ORIG["role_account"] = core.role_account
        role_account._bco238 = True
        core.role_account = role_account
    try:
        import api_fa as FA
        if not getattr(FA._dep_rows, "_bco238", False):
            _ORIG["_dep_rows"] = FA._dep_rows
            _dep_rows._bco238 = True
            FA._dep_rows = _dep_rows
        if not getattr(FA._alloc_rows, "_bco238", False):
            _ORIG["_alloc_rows"] = FA._alloc_rows
            _alloc_rows._bco238 = True
            FA._alloc_rows = _alloc_rows
        _wrap("fa.trueup_preview", fa_trueup_preview)
        if FA.fa_trueup_preview is _ORIG.get("fa.trueup_preview"):
            FA.fa_trueup_preview = fa_trueup_preview          # fa.trueup_run reads the preview by this name
        _wrap("fa.dep_run", fa_dep_run)
        _wrap("fa.sync", fa_sync)
        _wrap("fa.alloc_run", fa_alloc_run)
        _wrap("fa.dispose", fa_dispose)
    except ImportError:
        pass
    _wrap("dep.run", dep_run)
    _wrap("dep.preview", dep_preview)
    _wrap("hire.bill", hire_bill)
    _wrap("life.disp_advance", disp_advance)
    _wrap("pq.post", pq_post)
    _wrap("res.load", res_load)
    if "rep.integrity" in inv.FUNCS and not getattr(inv.FUNCS["rep.integrity"][0], "_bco238", False):
        _ORIG["rep.integrity"] = inv.FUNCS["rep.integrity"][0]
    _wrap("fc.checks", fc_checks)
    _wrap("rep.integrity", rep_integrity)


def init_agree(c):
    c.executescript(SCHEMA)
    fresh = not val(c, "SELECT COUNT(*) FROM vouchers")
    for k in SWITCHES:
        if not q1(c, "SELECT 1 FROM settings WHERE key=?", ("agree_" + k,)):
            # a new company starts with the corrected behaviour; an updated one waits for the accountant
            c.execute("INSERT INTO settings(key, value) VALUES(?,?)", ("agree_" + k, "1" if fresh else "0"))
    if not q1(c, "SELECT 1 FROM settings WHERE key='agree_res_units'"):
        n = _fix_res_units(c)
        c.execute("INSERT INTO settings(key, value) VALUES('agree_res_units', ?)", (str(n),))
    _install()
