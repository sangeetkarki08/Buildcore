"""BuildCore 2.38.0 "Books agree" - acceptance kit R1-R7 (and G1).

Runs the engine on SQLite (as the desktop does) on fresh test companies made here, because the 2.24 test company
and PostgreSQL are not available on this computer. R8 (all earlier kits) needs those kits and is not run here.

    python tests/kits/kit_2_38.py
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="bco238_")
os.environ["BCO_DATA_DIR"] = TMP
sys.path.insert(0, os.path.join(ROOT, "engine"))
os.chdir(os.path.join(ROOT, "engine"))

import core  # noqa: E402
import server  # noqa: E402,F401  (loads the engine modules as the desktop does)
import api_inventory as inv  # noqa: E402
from core import q, q1, val  # noqa: E402

RESULTS = []
MONTHS = ("2026-07", "2026-08", "2026-09", "2026-10")
_FUNCS = {}


def init_db():
    """Start-up for another company in the same process, as the web does it (engine/web/webpatch.py
    _patch_reinit): the data is prepared again, the function table is kept as the first start-up left it."""
    core.init_db()
    if _FUNCS:
        inv.FUNCS.clear()
        inv.FUNCS.update(_FUNCS)
    else:
        _FUNCS.update(inv.FUNCS)


def company(name):
    """A fresh company in its own data file, with an administrator, a second approver and the test machines."""
    d = os.path.join(TMP, name, "data")
    os.makedirs(d, exist_ok=True)
    core.DB_PATH = os.path.join(d, "buildcore.db")
    init_db()
    call("auth.setup", {"username": "admin", "password": "secret1", "name": "Admin"}, u=None, check=False)
    c = core.connect()
    c.execute("INSERT INTO users(username, name, role, active) VALUES('acc', 'Accountant', 'admin', 1)")
    for code, name_ in (("ROAD", "Road project"), ("BLDG", "Building project")):
        c.execute("INSERT INTO projects(code, name, status) VALUES(?,?, 'active')", (code, name_))
    road = val(c, "SELECT id FROM projects WHERE code='ROAD'")
    for code, nm, pv, life in (("EX-01", "Excavator", 9000000, 120), ("RL-01", "Roller", 3000000, 60)):
        c.execute("INSERT INTO equipment(code, name, category, ownership, purchase_date, purchase_value, residual_value, "
                  "life_months, dep_method, project_id, internal_rate, active, status) VALUES(?,?,?,'owned','2024-01-15',?,0,?,"
                  "'sl',?,3000,1,'working')", (code, nm, "Excavator" if code == "EX-01" else "Roller", pv, life, road))
    c.commit()
    c.close()
    return road


def call(fn, a=None, u="admin", check=True):
    f, module, action, public = inv.FUNCS[fn]
    c = core.connect()
    us = q1(c, "SELECT * FROM users WHERE username=?", (u,)) if u else None
    try:
        if module and check:
            core.require(us, module, action)
        c.execute("BEGIN IMMEDIATE")
        r = f(c, us, dict(a or {}))
        c.commit()
        return r
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def sw(key, on):
    c = core.connect()
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", ("agree_" + key, "1" if on else "0"))
    c.commit()
    c.close()


def one(sql, p=()):
    c = core.connect()
    try:
        return val(c, sql, p)
    finally:
        c.close()


def eq_id(code):
    return one("SELECT id FROM equipment WHERE code=?", (code,))


def figures(code):
    import api_agree as A
    c = core.connect()
    try:
        eid = eq_id(code)
        fa = A.fa_of_eq(c, eid)
        return (round(val(c, "SELECT accumulated_dep FROM equipment WHERE id=?", (eid,)), 2),
                round(fa["accumulated"], 2) if fa else None, A.ledger_accum(c, eid))
    finally:
        c.close()


def check(name, ok, detail):
    RESULTS.append((name, bool(ok), detail))
    print("%s  %s  %s" % ("PASS" if ok else "FAIL", name, detail))


def raises(fn, *a, **k):
    try:
        fn(*a, **k)
    except Exception as e:  # noqa: BLE001
        return str(e)
    return None


# ───────────── R1, R2: one depreciation route ─────────────
company("r1")
check("new company: switches on", one("SELECT value FROM settings WHERE key='agree_one_dep_route'") == "1",
      "agree_one_dep_route = %s" % one("SELECT value FROM settings WHERE key='agree_one_dep_route'"))
sw("one_dep_route", False)
for m in MONTHS[:2]:
    call("dep.run", {"month": m})                                # history on the Equipment route
sw("one_dep_route", True)
call("fa.sync", {})
eqa, faa, led = figures("EX-01")
check("R2 fa.sync carries the history", eqa == faa == led and eqa > 0,
      "EX-01 equipment %s, fixed assets %s, ledger 1502 share %s" % (eqa, faa, led))
sw("one_dep_route", False)
call("dep.run", {"month": "2026-09"})
before = one("SELECT COUNT(*) FROM fa_dep WHERE month='2026-09'")
err = raises(call, "fa.dep_run", {"month": "2026-09"})
after = one("SELECT COUNT(*) FROM fa_dep WHERE month='2026-09'")
check("R1 dep.run then fa.dep_run: nothing posted twice", before == after == 0,
      "fa_dep rows for September %s -> %s (%s)" % (before, after, err or "ran"))
call("fa.dep_run", {"month": "2026-10"})
r = call("dep.run", {"month": "2026-10"})
check("R1 reverse order refused too", r["count"] == 0 and set(r["skipped_fa"]) == {"EX-01", "RL-01"},
      "dep.run October after fa.dep_run: %s posted, skipped %s" % (r["count"], r["skipped_fa"]))
sw("one_dep_route", True)
err = raises(call, "dep.run", {"month": "2026-10"})
check("R1 dep.run refused when Fixed assets is official", err == "Depreciation is posted from Fixed assets › Depreciation.",
      err or "not refused")

# ───────────── R3: duplicates found and reversed after approval ─────────────
company("r3")
import api_agree as A  # noqa: E402
import api_fa as FA  # noqa: E402
sw("one_dep_route", False)
for m in MONTHS[:2]:
    call("dep.run", {"month": m})
sw("one_dep_route", True)
call("fa.sync", {})
sw("one_dep_route", False)
# force both runs through the old code for September
guarded, FA._dep_rows = FA._dep_rows, A._ORIG["_dep_rows"]
A._ORIG["dep.run"] and call("dep.run", {"month": "2026-09"})
call_old = A._ORIG["fa.dep_run"]
c = core.connect()
c.execute("BEGIN IMMEDIATE")
call_old(c, q1(c, "SELECT * FROM users WHERE username='admin'"), {"month": "2026-09"})
c.commit()
c.close()
FA._dep_rows = guarded
sw("one_dep_route", True)
d = call("agree.dup_dep", {})
listed = sorted((r["code"], r["month"]) for r in d["rows"])
check("R3 Check lists September for EX-01 and RL-01", listed == [("EX-01", "2026-09"), ("RL-01", "2026-09")], listed)
chk = call("fc.checks", {})
twice = next(x for x in chk["checks"] if x["check"] == "No machine and month depreciated twice")
check("R3 data check flags it", not twice["ok"] and twice["count"] == 2, twice["detail"])
for r in d["rows"]:
    call("agree.dup_propose", {"dep_run_id": r["dep_run_id"]}, u="acc")
mid = figures("EX-01")
check("R3 proposal changes nothing before approval", mid[2] > mid[1],
      "EX-01 equipment %s, fixed assets %s, ledger %s" % mid)
ids = [x["voucher_id"] for x in call("pq.list", {"stage": "open"}) if x["source"] == "agree_fix"]
call("pq.approve", {"ids": ids})
call("pq.post", {"ids": ids})
eqa, faa, led = figures("EX-01")
check("R3 after approval all three agree", eqa == faa == led, "EX-01 equipment %s, fixed assets %s, ledger %s" % (eqa, faa, led))
twice = next(x for x in call("fc.checks", {})["checks"] if x["check"] == "No machine and month depreciated twice")
check("R3 data check clear after posting", twice["ok"], twice["detail"])

# ───────────── R4: machine hours charged once ─────────────
road = company("r4")
ex = eq_id("EX-01")
c = core.connect()
c.execute("INSERT INTO dpr(no, project_id, date, status) VALUES('DPR-1', ?, '2026-09-10', 'approved')", (road,))
dpr = val(c, "SELECT id FROM dpr WHERE no='DPR-1'")
c.execute("INSERT INTO logsheets(equipment_id, project_id, date, hours, status, dpr_id) VALUES(?,?,'2026-09-10',8,'approved',?)",
          (ex, road, dpr))
c.execute("INSERT INTO logsheets(equipment_id, project_id, date, hours, status) VALUES(?,?,'2026-09-11',5,'approved')", (ex, road))
adm = q1(c, "SELECT * FROM users WHERE username='admin'")
core.post_voucher(c, adm, "journal", "2026-09-10", "Site resources DPR-1",
                  [{"role": "equipment_cost", "debit": 24000, "equipment_id": ex, "project_id": road},
                   {"role": "equipment_recovery", "credit": 24000, "equipment_id": ex, "project_id": road}],
                  project_id=road, source="dpr", source_id=dpr)
c.commit()
c.close()
call("internal.run", {"month": "2026-09"})
err = raises(call, "fa.alloc_run", {"month": "2026-09"})
charged = one("SELECT SUM(l.debit) FROM voucher_lines l JOIN accounts a ON a.id=l.account_id WHERE a.role IN "
              "('equipment_cost','equip_job_cost','internal_hire_cost') AND l.project_id=?", (road,))
ib_h = one("SELECT SUM(hours) FROM internal_bills WHERE equipment_id=?", (ex,))
check("R4 DPR + internal hire + allocation charge ROAD once", ib_h == 5 and err is not None,
      "DPR 8 h, internal hire %s h (the 5 h without a DPR), allocation refused: %s; ROAD charged %s" % (ib_h, bool(err), charged))

# ───────────── R5: posting queue explains store against books ─────────────
road = company("r5")
c = core.connect()
adm = q1(c, "SELECT * FROM users WHERE username='admin'")
c.execute("INSERT INTO stores(project_id, code, name, type, active) VALUES(?, 'S1', 'Main store', 'site', 1)", (road,))
st = val(c, "SELECT id FROM stores WHERE code='S1'")
c.execute("INSERT INTO materials(code, name, unit, category, active) VALUES('DSL', 'Diesel', 'ltr', 'Fuel', 1)")
mat = val(c, "SELECT id FROM materials WHERE code='DSL'")
c.execute("INSERT INTO stock_balances(project_id, store_id, material_id, qty, value) VALUES(?,?,?,1000,165000)", (road, st, mat))
core.post_voucher(c, adm, "journal", "2026-09-01", "Opening diesel", [
    {"role": "inventory_fuel", "debit": 165000, "project_id": road}, {"role": "ap_control", "credit": 165000, "project_id": road}],
    project_id=road)
# a 200-litre issue to EX-01 with the gate on: the store moves now, the voucher waits in the posting queue
c.execute("UPDATE stock_balances SET qty=800, value=132000 WHERE material_id=?", (mat,))
import api_exec as X  # noqa: E402
vid = X._ORIG.get("post", core.post_voucher)(c, adm, "journal", "2026-09-20", "Issue MIN/2083/0011 diesel to EX-01", [
    {"role": "fuel_cost", "debit": 33000, "project_id": road, "equipment_id": eq_id("EX-01")},
    {"role": "inventory_fuel", "credit": 33000, "project_id": road}], project_id=road, source="issue", status="submitted")
c.execute("INSERT INTO post_queue(voucher_id, source, gate, module, stage, label, project_id, amount, vtype, created_by, created_at) "
          "VALUES(?, 'issue', 'issue', 'inventory', 'review', 'MIN/2083/0011', ?, 33000, 'journal', ?, '2026-09-20')",
          (vid, road, val(c, "SELECT id FROM users WHERE username='acc'")))
c.commit()
c.close()
stk = next(x for x in call("fc.checks", {})["checks"] if x["check"] == "Stock value = inventory accounts, project by project")
check("R5 difference explained by 1 queued voucher", stk["ok"] and "1 voucher(s) waiting" in stk["detail"], stk["detail"])
call("pq.approve", {"id": vid})
call("pq.post", {"id": vid})
import api_agree as A  # noqa: E402,F811
c = core.connect()
sv = A.stock_vs_books(c)
c.close()
check("R5 after pq.post the difference is 0", sv[0]["difference"] == 0 and not sv[0]["queued"],
      "store %s, books %s" % (sv[0]["stock"], sv[0]["books"]))

# ───────────── R6: disposal through Lifecycle always posts ─────────────
road = company("r6")
rl = eq_id("RL-01")
c = core.connect()
adm = q1(c, "SELECT * FROM users WHERE username='admin'")
core.post_voucher(c, adm, "journal", "2024-01-15", "RL-01 bought", [
    {"role": "fixed_asset", "debit": 3000000, "equipment_id": rl}, {"role": "ap_control", "credit": 3000000}])
c.commit()
c.close()
sw("one_dep_route", False)
for m in MONTHS[:3]:
    call("dep.run", {"month": m})
sw("one_dep_route", True)
no_fa = one("SELECT COUNT(*) FROM fa_register WHERE kind='equipment' AND ref_id=?", (rl,))
dsp = call("life.disp_save", {"row": {"equipment_id": rl, "trigger": "end of life"}})["id"]
call("life.disp_save", {"row": {"id": dsp, "assessment": "worn out", "application": "scrap", "evaluation_value": 900000}})
for _ in range(4):
    call("life.disp_advance", {"id": dsp}, u="acc")
call("life.disp_advance", {"id": dsp, "proceeds": 900000, "date": "2026-10-30"}, u="acc")
v = one("SELECT voucher_id FROM asset_disposals WHERE id=?", (dsp,))
c = core.connect()
cost_left, acc_left = A.ledger_cost(c, rl), A.ledger_accum(c, rl)
c.close()
check("R6 disposal posts a voucher with no Fixed asset row before", no_fa == 0 and bool(v) and cost_left == 0 and acc_left == 0,
      "voucher %s; RL-01 Plant & Machinery %s, accumulated depreciation %s" % (v, cost_left, acc_left))

# ───────────── R7: hire bills count approved hours only ─────────────
road = company("r7")
c = core.connect()
c.execute("INSERT INTO parties(code, name, kind) VALUES('HV', 'Hire vendor', 'supplier')")
pv = val(c, "SELECT id FROM parties WHERE code='HV'")
c.execute("INSERT INTO equipment(code, name, ownership, project_id, active) VALUES('HX-9', 'Hired excavator', 'rented', ?, 1)", (road,))
hx = val(c, "SELECT id FROM equipment WHERE code='HX-9'")
c.execute("INSERT INTO hire_agreements(equipment_id, vendor_id, project_id, rate, unit) VALUES(?,?,?,2500,'hour')", (hx, pv, road))
ag = val(c, "SELECT id FROM hire_agreements")
for d_, h_, s_ in (("2026-09-02", 8, "approved"), ("2026-09-03", 7, "approved"), ("2026-09-04", 6, "draft")):
    c.execute("INSERT INTO logsheets(equipment_id, project_id, date, hours, status) VALUES(?,?,?,?,?)", (hx, road, d_, h_, s_))
c.commit()
c.close()
r = call("hire.bill", {"agreement_id": ag, "month": "2026-09"})
check("R7 hire bill counts approved hours only", r["billed"] == 15 and r["draft_hours"] == 6,
      "billed %s h, %s h in draft listed as not yet approved" % (r["billed"], r["draft_hours"]))

# ───────────── G1: histogram labour in man-days ─────────────
c = core.connect()
c.execute("INSERT INTO act_resources(project_id, kind, ref, name, unit, qty_total, source) VALUES(?, 'L', 'LAB', 'Labour', 'hr', 40, 'rate_analysis')", (road,))
n = A._fix_res_units(c)
u_ = val(c, "SELECT unit FROM act_resources WHERE ref='LAB'")
c.commit()
c.close()
import api_res as RES  # noqa: E402
check("G1 rate-analysis labour read as man-days", u_ == "day" and RES._per_day_units(u_, 40, 8) == 40,
      "unit %s; 40 man-days a day = %s workers (was %s)" % (u_, RES._per_day_units(u_, 40, 8), RES._per_day_units("hr", 40, 8)))

print("\n%d of %d passed" % (sum(1 for x in RESULTS if x[1]), len(RESULTS)))
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if all(x[1] for x in RESULTS) else 1)
