"""
BuildCore 2.3 - stores analysis and the remaining NFRS items, built into existing screens:

  Inventory > Stock on hand        ABC + VED + HML and a multi-criteria score (5.4), slow-moving and ageing
                                   stock with transfer suggestions (5.9), EOQ sensitivity (5.8), item and
                                   bin QR labels (5.11)
  Inventory > Stock count          cycle-count plan by class and inventory record accuracy (5.6)
  Inventory > Material forecast    joint replenishment by supplier and delivery pacing (5.7)
  Inventory > Material recon.      material cost S-curve and material CPI (5.3)
  Accounts > Integrity checks      NFRS compliance: entity tier with the two-year rules (1), checklist status,
                                   cash payments above the limit that are not tax-deductible (8)
  Accounts > Ageing                expected credit loss provision matrix (15)
  Accounts > Balance sheet         provisions register with movement table (16), deferred-tax schedule (17),
                                   NFRS 18-ready statement of profit or loss (23)
  Accounts > TDS rates             TDS rates by fiscal year (18)
  Accounts > Profit & loss         JV partner-share statement (19)
  Accounts > Client invoices       CBMS e-invoice export (22)
"""
import json
import math
from datetime import date, timedelta

from core import ApiError, EPS, audit, get, ins, need, next_no, now, num, q, q1, r2, r4, setting, today, upd, val
import api_inventory as inv
from api_inventory import api as _register
import api_project as P
import sched_calc as SC

POSTED = "v.status IN ('posted','reversed')"
_READY = set()


def api(name, module=None, action=None):
    def wrap(f):
        def run(c, u, a):
            ensure(c)
            return f(c, u, a)
        run.__name__, run.__doc__ = f.__name__, f.__doc__
        _register(name, module, action)(run)
        return f
    return wrap


def ensure(c):
    try:
        key = c.execute("PRAGMA database_list").fetchone()[2] or id(c)
    except Exception:
        key = id(c)
    if key not in _READY:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='entity_tier'").fetchone():
            init_books(c)
        _READY.add(key)


SCHEMA = """
CREATE TABLE IF NOT EXISTS entity_tier(fy INTEGER PRIMARY KEY, turnover REAL, borrowings REAL, total_assets REAL, employees REAL,
  fiduciary REAL DEFAULT 0, listed INTEGER DEFAULT 0, fi INTEGER DEFAULT 0, gbe INTEGER DEFAULT 0, remarks TEXT);
CREATE TABLE IF NOT EXISTS provisions(id INTEGER PRIMARY KEY, no TEXT, project_id INTEGER, kind TEXT, title TEXT,
  date TEXT, amount REAL DEFAULT 0, probability TEXT, basis TEXT, status TEXT DEFAULT 'open', voucher_id INTEGER,
  reversed_voucher_id INTEGER, remarks TEXT, created_by INTEGER);
CREATE TABLE IF NOT EXISTS prov_moves(id INTEGER PRIMARY KEY, provision_id INTEGER, date TEXT, kind TEXT, amount REAL,
  voucher_id INTEGER, note TEXT, user_id INTEGER);
CREATE TABLE IF NOT EXISTS tds_rates_fy(id INTEGER PRIMARY KEY, fy INTEGER, section TEXT, description TEXT, rate REAL,
  threshold REAL DEFAULT 0, final INTEGER DEFAULT 0, notes TEXT);
CREATE TABLE IF NOT EXISTS nfrs18_map(account_id INTEGER PRIMARY KEY, category TEXT);
"""
ECL_BUCKETS = [("current", 0, 30, 0.5), ("31-90", 31, 90, 2.0), ("91-180", 91, 180, 5.0), ("181-365", 181, 365, 15.0),
               ("over 1 year", 366, 99999, 50.0)]
PROV_KINDS = [["defects", "Defects liability"], ["restoration", "Site restoration / decommissioning"], ["legal", "Legal claims and disputes"],
              ["onerous", "Onerous contract"], ["warranty", "Warranty"], ["ld", "Liquidated damages likely to be deducted"], ["other", "Other"]]
TDS_2083 = [("89", "Contract / construction payment (resident)", 1.5, 50000, 0, "Sec. 89(1): 1.5% on contract payments; consumer committees exempt [confirm]"),
            ("88(1)", "Service fee - VAT registered", 1.5, 0, 0, "Invoice under VAT [confirm]"),
            ("88(1)", "Service fee / commission - others", 15, 0, 0, "[confirm]"),
            ("88(1)", "House rent (natural person)", 10, 0, 1, "Final withholding [confirm]"),
            ("87", "Salary and wages", 0, 0, 0, "Slab rates, see payroll [confirm]"),
            ("88(1)", "Transport of goods by VAT-registered carrier", 2.5, 0, 0, "[confirm]"),
            ("88(1)", "Rent of vehicles / equipment", 10, 0, 0, "[confirm]"),
            ("88(1)", "Interest paid to others", 15, 0, 0, "[confirm]")]


def _cols(c, t):
    try:
        return {r[1] for r in c.execute("PRAGMA table_info(%s)" % t)}
    except Exception:
        return set()


def _has(c, t):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone())


def init_books(c):
    c.executescript(SCHEMA)
    for k, v in (("ecl_rates", json.dumps({b[0]: b[3] for b in ECL_BUCKETS})), ("tax_rate", "0.25"),
                 ("cycle_days", json.dumps({"A": 30, "B": 90, "C": 365})), ("count_tolerance_pct", "2")):
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
    if not val(c, "SELECT COUNT(*) FROM tds_rates_fy"):
        for sec, d, r, th, fin, note in TDS_2083:
            ins(c, "tds_rates_fy", {"fy": 2083, "section": sec, "description": d, "rate": r, "threshold": th, "final": fin, "notes": note})


def _f(x, d=0.0):
    try:
        return float(x) if x not in (None, "") else d
    except (TypeError, ValueError):
        return d


def _set(c, k, v):
    c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))


def fy_bounds(fy):
    s = SC.bs_to_ad(fy, 4, 1)
    e = SC.bs_to_ad(fy + 1, 4, 1) - timedelta(days=1)
    return s.isoformat(), e.isoformat()


def current_fy():
    y, m, _ = SC.ad_to_bs(date.today())
    return y if m >= 4 else y - 1


def _role_account(c, role, name, typ, code0):
    a = val(c, "SELECT id FROM accounts WHERE role=?", (role,), None)
    if a:
        return a
    gid = val(c, "SELECT id FROM account_groups WHERE type=? ORDER BY id DESC", (typ,), None)
    code = code0
    while val(c, "SELECT id FROM accounts WHERE code=?", (code,), None):
        code = str(int(code) + 1)
    return ins(c, "accounts", {"code": code, "name": name, "type": typ, "group_id": gid, "role": role, "active": 1})


def _post(c, u, d, narration, lines, source, source_id=None, project_id=None):
    from core import post_voucher
    return post_voucher(c, u, "journal", d, narration, lines, project_id=project_id, source=source, source_id=source_id)


# ═════════════════════════ STORES ═════════════════════════
def _annual(c, pid=None):
    since = (date.today() - timedelta(days=365)).isoformat()
    w = "i.status='posted' AND i.date>=?"
    p = [since]
    if pid:
        w += " AND i.project_id=?"
        p.append(pid)
    return {r["material_id"]: r for r in q(c, "SELECT l.material_id, SUM(l.qty-l.returned_qty) qq, SUM(l.amount) v, MAX(i.date) last FROM "
                                             "issue_lines l JOIN issues i ON i.id=l.issue_id WHERE " + w + " GROUP BY l.material_id", p)}


@api("books.classify", "inventory", "view")
def classify(c, u, a):
    """ABC by annual consumption value, VED by criticality, HML by unit price, and a weighted score over
    annual value, lead time, criticality, ageing and unit price (the review found single-criterion ABC and
    multi-criteria ranking agree on few items)."""
    pid = a.get("project_id")
    w = {"value": 0.35, "lead": 0.20, "critical": 0.25, "ageing": 0.10, "price": 0.10}
    w.update({k: _f(v) for k, v in (a.get("weights") or {}).items()})
    ann = _annual(c, pid)
    mats = q(c, "SELECT * FROM materials WHERE active=1")
    pol = {r["material_id"]: r for r in q(c, "SELECT * FROM inv_policy")} if _has(c, "inv_policy") else {}
    rows = []
    for m in mats:
        stock = val(c, "SELECT SUM(qty) FROM stock_balances WHERE material_id=?" + (" AND project_id=?" if pid else ""),
                    (m["id"], int(pid)) if pid else (m["id"],))
        x = ann.get(m["id"])
        if not x and stock <= EPS:
            continue
        value = (x or {}).get("v") or 0
        qty = (x or {}).get("qq") or 0
        price = value / qty if qty > EPS else (m["standard_rate"] or 0)
        last = (x or {}).get("last") or val(c, "SELECT MAX(i.date) FROM issue_lines l JOIN issues i ON i.id=l.issue_id WHERE l.material_id=? AND "
                                              "i.status='posted'", (m["id"],), None)
        age = (date.today() - date.fromisoformat(last)).days if last else 999
        ved = (pol.get(m["id"]) or {}).get("ved") or "E"
        rows.append({"material_id": m["id"], "code": m["code"], "name": m["name"], "unit": m["unit"], "annual_qty": r4(qty), "annual_value": r2(value),
                     "unit_price": r2(price), "lead_days": m["lead_days"] or 7, "ved": ved, "days_since_issue": age, "stock": r4(stock)})
    if not rows:
        return {"rows": [], "weights": w}
    tot = sum(r["annual_value"] for r in rows) or 1
    acc = 0.0
    for r in sorted(rows, key=lambda r: -r["annual_value"]):
        acc += r["annual_value"]
        r["abc"] = "A" if acc / tot <= 0.70 or acc == r["annual_value"] else ("B" if acc / tot <= 0.90 else "C")
    prices = sorted(r["unit_price"] for r in rows)
    p90 = prices[int(0.9 * (len(prices) - 1))]
    p70 = prices[int(0.7 * (len(prices) - 1))]
    for r in rows:
        r["hml"] = "H" if r["unit_price"] >= p90 and r["unit_price"] > 0 else ("M" if r["unit_price"] >= p70 else "L")
    mx = {k: max([r[k] for r in rows] + [1e-9]) for k in ("annual_value", "lead_days", "unit_price")}
    for r in rows:
        crit = {"V": 1.0, "E": 0.5, "D": 0.0}.get(r["ved"], 0.5)
        ageing = min(1.0, r["days_since_issue"] / 365.0)
        r["score"] = round(100 * (w["value"] * r["annual_value"] / mx["annual_value"] + w["lead"] * r["lead_days"] / mx["lead_days"] +
                                  w["critical"] * crit + w["ageing"] * ageing + w["price"] * r["unit_price"] / mx["unit_price"]) /
                           sum(w.values()), 1)
    srt = sorted(rows, key=lambda r: -r["score"])
    for i, r in enumerate(srt):
        r["mc_class"] = "A" if i < max(1, round(0.2 * len(srt))) else ("B" if i < round(0.5 * len(srt)) else "C")
        r["agree"] = r["mc_class"] == r["abc"]
    agree = sum(1 for r in rows if r["agree"])
    return {"rows": srt, "weights": w, "agreement_pct": round(100 * agree / len(rows), 1),
            "summary": {k: sum(1 for r in rows if r["abc"] == k) for k in "ABC"}}


@api("books.slow", "inventory", "view")
def slow_moving(c, u, a):
    """Stock with no issue for 90, 180 or 365 days, by value, with projects whose schedules need it."""
    rows = q(c, "SELECT b.project_id, b.store_id, b.material_id, b.qty, b.value, m.code, m.name, m.unit, s.name store FROM stock_balances b "
                "JOIN materials m ON m.id=b.material_id LEFT JOIN stores s ON s.id=b.store_id WHERE b.qty>0.0001")
    out = []
    demand_cache = {}
    try:
        import api_res as RES
    except Exception:
        RES = None
    for r in rows:
        last = val(c, "SELECT MAX(i.date) FROM issue_lines l JOIN issues i ON i.id=l.issue_id WHERE i.status='posted' AND i.project_id=? AND "
                      "l.material_id=?", (r["project_id"], r["material_id"]), None)
        recv = val(c, "SELECT MAX(date) FROM stock_ledger WHERE project_id=? AND material_id=? AND qty_in>0", (r["project_id"], r["material_id"]), None)
        ref = last or recv
        days = (date.today() - date.fromisoformat(ref)).days if ref else 999
        if days < 90:
            continue
        band = "over 365 days" if days > 365 else ("181-365 days" if days > 180 else "91-180 days")
        need_at = []
        if RES:
            for p in q(c, "SELECT id, code FROM projects WHERE status='active' AND id<>?", (r["project_id"],)):
                if p["id"] not in demand_cache:
                    try:
                        demand_cache[p["id"]] = RES.schedule_demand(c, p["id"], 90)
                    except Exception:
                        demand_cache[p["id"]] = {}
                d = sum(demand_cache[p["id"]].get(r["material_id"], {}).values())
                if d > EPS:
                    need_at.append("%s needs %s" % (p["code"], r2(d)))
        out.append({"project_id": r["project_id"], "store": r["store"], "material_id": r["material_id"], "code": r["code"], "name": r["name"],
                    "unit": r["unit"], "qty": r4(r["qty"]), "value": r2(r["value"]), "last_movement": ref, "days": days, "band": band,
                    "transfer_to": "; ".join(need_at)})
    out.sort(key=lambda r: -r["value"])
    bands = {}
    for r in out:
        bands[r["band"]] = bands.get(r["band"], 0) + r["value"]
    return {"rows": out, "bands": {k: r2(v) for k, v in bands.items()}, "total": r2(sum(r["value"] for r in out)),
            "note": "Review these for NAS 2 net realisable value (Fixed assets › Inventory analysis) or transfer them to a site that needs them."}


@api("books.eoq", "inventory", "view")
def eoq_sensitivity(c, u, a):
    """EOQ with demand ±10% and holding cost ±25%, and the cost penalty of ordering a round truckload instead."""
    ann = _annual(c, a.get("project_id"))
    pol = {r["material_id"]: r for r in q(c, "SELECT * FROM inv_policy")} if _has(c, "inv_policy") else {}
    default_order = _f(a.get("order_cost"), 2500)
    out = []
    for mid, x in ann.items():
        m = q1(c, "SELECT * FROM materials WHERE id=?", (mid,))
        if not m or not x["qq"] or x["qq"] <= 0:
            continue
        p = pol.get(mid) or {}
        S_ = _f(p.get("order_cost")) or default_order
        h = _f(p.get("carrying_pct"), 0.2) or 0.2
        price = (x["v"] or 0) / x["qq"]
        D = x["qq"]
        if price <= 0:
            continue

        def eoq(D_, h_):
            return math.sqrt(2 * D_ * S_ / (price * h_))

        def tc(Q, D_=D, h_=h):
            return D_ / Q * S_ + Q / 2 * price * h_
        q0 = eoq(D, h)
        truck = _f((a.get("truck") or {}).get(str(mid)), 0) or (m["reorder_qty"] or 0)
        pen = round(100 * (tc(truck) / tc(q0) - 1), 2) if truck and truck > 0 else None
        out.append({"material_id": mid, "code": m["code"], "name": m["name"], "unit": m["unit"], "annual_demand": r2(D), "unit_price": r2(price),
                    "order_cost": S_, "holding_pct": h * 100, "eoq": r2(q0), "eoq_demand_minus10": r2(eoq(D * 0.9, h)), "eoq_demand_plus10": r2(eoq(D * 1.1, h)),
                    "eoq_holding_minus25": r2(eoq(D, h * 0.75)), "eoq_holding_plus25": r2(eoq(D, h * 1.25)), "total_cost_at_eoq": r2(tc(q0)),
                    "truck_qty": truck or None, "truck_penalty_pct": pen})
    out.sort(key=lambda r: -(r["annual_demand"] * r["unit_price"]))
    return {"rows": out, "note": "EOQ moves with the square root of demand and holding cost, so a ±10% error in demand changes it by only about "
                                 "±5%. Rounding to a truckload usually costs little — the penalty column shows how much."}


@api("books.cycle", "inventory", "view")
def cycle_count(c, u, a):
    """Cycle-count plan: class A every 30 days, B every 90, C every 365 (editable); items due now; and
    inventory record accuracy per store from the counts of the last 12 months."""
    pid = int(a["project_id"])
    try:
        freq = json.loads(setting(c, "cycle_days") or "{}")
    except ValueError:
        freq = {}
    freq = {"A": _f(freq.get("A"), 30), "B": _f(freq.get("B"), 90), "C": _f(freq.get("C"), 365)}
    tol = _f(setting(c, "count_tolerance_pct"), 2)
    cls = {r["material_id"]: r["abc"] for r in classify(c, u, {"project_id": pid})["rows"]}
    rows = []
    for b in q(c, "SELECT b.*, m.code, m.name, m.unit, s.name store FROM stock_balances b JOIN materials m ON m.id=b.material_id JOIN stores s "
                  "ON s.id=b.store_id WHERE b.project_id=? AND s.type<>'transit' AND b.qty>0.0001", (pid,)):
        last = val(c, "SELECT MAX(sc.date) FROM count_lines cl JOIN stock_counts sc ON sc.id=cl.count_id WHERE sc.status='posted' AND "
                      "sc.store_id=? AND cl.material_id=?", (b["store_id"], b["material_id"]), None)
        k = cls.get(b["material_id"], "C")
        due = (date.fromisoformat(last) + timedelta(days=int(freq[k]))).isoformat() if last else today()
        rows.append({"store_id": b["store_id"], "store": b["store"], "material_id": b["material_id"], "code": b["code"], "name": b["name"],
                     "unit": b["unit"], "class": k, "qty": r4(b["qty"]), "value": r2(b["value"]), "last_counted": last, "due": due,
                     "overdue": due <= today()})
    rows.sort(key=lambda r: (r["due"], r["class"]))
    since = (date.today() - timedelta(days=365)).isoformat()
    acc = []
    for s in q(c, "SELECT id, name FROM stores WHERE project_id=? AND type<>'transit'", (pid,)):
        lines = q(c, "SELECT cl.system_qty, cl.counted_qty FROM count_lines cl JOIN stock_counts sc ON sc.id=cl.count_id WHERE sc.status='posted' AND "
                     "sc.store_id=? AND sc.date>=?", (s["id"], since))
        ok = sum(1 for l in lines if abs((l["counted_qty"] or 0) - (l["system_qty"] or 0)) <= max(0.5, abs(l["system_qty"] or 0) * tol / 100))
        acc.append({"store": s["name"], "lines_counted": len(lines), "accurate": ok, "accuracy_pct": round(100 * ok / len(lines), 1) if lines else None})
    return {"rows": rows, "due": sum(1 for r in rows if r["overdue"]), "frequency": freq, "tolerance_pct": tol, "accuracy": acc}


@api("books.cycle_sheet", "inventory", "edit")
def cycle_sheet(c, u, a):
    """Draft count sheet for the items due in one store (counts post through the normal stock count)."""
    pid = int(a["project_id"])
    sid = int(a["store_id"])
    d = cycle_count(c, u, {"project_id": pid})
    due = [r for r in d["rows"] if r["store_id"] == sid and r["overdue"]]
    if not due:
        raise ApiError("Nothing is due in this store.")
    lines = [{"material_id": r["material_id"], "system_qty": r["qty"], "counted_qty": r["qty"], "reason": "Cycle count (class %s)" % r["class"]} for r in due]
    return inv.FUNCS["doc.save"][0](c, u, {"type": "count", "header": {"project_id": pid, "store_id": sid, "date": today(),
                                                                        "remarks": "Cycle count - %d items due" % len(lines)}, "lines": lines})


@api("books.cycle_settings", "inventory", "approve")
def cycle_settings(c, u, a):
    _set(c, "cycle_days", json.dumps({k: _f(v) for k, v in (a.get("frequency") or {}).items()}))
    if a.get("tolerance_pct") not in (None, ""):
        _set(c, "count_tolerance_pct", _f(a["tolerance_pct"]))
    return True


@api("books.joint", "procurement", "view")
def joint_replenishment(c, u, a):
    """Group the material plan's suggestions by the usual supplier into one order each, and pace the
    deliveries so each load covers N days of demand (small hill-site yards)."""
    import api_res as RES
    pid = int(a["project_id"])
    horizon = int(_f(a.get("horizon_days"), 21))
    pace = int(_f(a.get("cover_days"), 14))
    m = RES.res_mrp(c, u, {"project_id": pid, "weeks": 16})
    lim = (date.today() + timedelta(days=horizon)).isoformat()
    groups = {}
    for r in m["rows"]:
        if r["suggested_qty"] <= 0 or not r["order_by"] or r["order_by"] > lim:
            continue
        v = q1(c, "SELECT po.vendor_id FROM po_lines pl JOIN po ON po.id=pl.po_id WHERE pl.material_id=? AND po.status<>'cancelled' ORDER BY po.date "
                  "DESC LIMIT 1", (r["material_id"],))
        vid = (v or {}).get("vendor_id")
        g = groups.setdefault(vid, {"vendor_id": vid, "vendor": (q1(c, "SELECT name FROM parties WHERE id=?", (vid,)) or {}).get("name") if vid else "No usual supplier",
                                    "lines": [], "value": 0.0, "first_need": None})
        daily = (r["demand_horizon"] / (16 * 6.0)) if r["demand_horizon"] else 0
        loads = []
        if daily > 0 and r["suggested_qty"] > 0:
            per = daily * pace
            nloads = max(1, int(math.ceil(r["suggested_qty"] / per)))
            start = date.fromisoformat(r["need_date"]) - timedelta(days=3)
            for k in range(nloads):
                loads.append({"date": (start + timedelta(days=pace * k)).isoformat(), "qty": r2(min(per, r["suggested_qty"] - per * k))})
        g["lines"].append({"material_id": r["material_id"], "code": r["code"], "name": r["name"], "unit": r["unit"], "qty": r["suggested_qty"],
                           "need_date": r["need_date"], "order_by": r["order_by"], "value": r2(r["suggested_qty"] * (r["rate"] or 0)), "deliveries": loads})
        g["value"] += r["suggested_qty"] * (r["rate"] or 0)
        g["first_need"] = min(filter(None, [g["first_need"], r["need_date"]]))
    out = sorted(groups.values(), key=lambda g: g["first_need"] or "9999")
    for g in out:
        g["value"] = r2(g["value"])
        g["orders_saved"] = max(0, len(g["lines"]) - 1)
    return {"groups": out, "horizon_days": horizon, "cover_days": pace,
            "note": "One order per supplier saves the ordering cost of the others; delivery pacing keeps the yard small."}


@api("books.mat_curve", "commercial", "view")
def mat_curve(c, u, a):
    """Planned (baseline) against earned and actual material cost by month, and the material CPI."""
    pid = int(a["project_id"])
    acts = q(c, "SELECT * FROM activities WHERE project_id=? AND boq_item_id IS NOT NULL", (pid,))
    mat_ub = {}
    for x in acts:
        if x["boq_item_id"] not in mat_ub:
            ub, parts = P.unit_budget(c, x["boq_item_id"])
            mat_ub[x["boq_item_id"]] = parts.get("material") if parts else None
    starts = [x.get("baseline_start") or x.get("planned_start") for x in acts if x.get("baseline_start") or x.get("planned_start")]
    if not starts:
        return {"points": []}
    k = min(starts)[:7]
    last = max(today()[:7], k)
    pts = []
    y, mth = int(k[:4]), int(k[5:7])
    while True:
        key = "%04d-%02d" % (y, mth)
        me = (date(y + (mth // 12), mth % 12 + 1, 1) - timedelta(days=1)).isoformat()
        d = min(me, today())
        pv = ev = 0.0
        for x in acts:
            per = mat_ub.get(x["boq_item_id"])
            if not per:
                continue
            pv += (x["planned_qty"] or 0) * P.planned_fraction(x, d) * per
            done = val(c, "SELECT SUM(w.actual_qty) FROM dpr_work w JOIN dpr dd ON dd.id=w.dpr_id WHERE dd.status='approved' AND w.activity_id=? "
                          "AND dd.date<=?", (x["id"], d))
            ev += min(done, x["planned_qty"] or done) * per
        ac = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON x.id=l.account_id "
                    "WHERE x.role='material_cost' AND l.project_id=? AND v.date<=? AND " + POSTED, (pid, d))
        pts.append({"month": key, "planned": r2(pv), "earned": r2(ev), "actual": r2(ac), "cpi": round(ev / ac, 3) if ac > EPS else None})
        if key >= last:
            break
        mth += 1
        if mth > 12:
            mth, y = 1, y + 1
    return {"points": pts, "note": "Material part of each BOQ item's rate analysis, spread on the baseline dates (planned) and on the approved DPR "
                                   "quantities (earned); actual = material cost posted to the project."}


@api("books.item_tags", "inventory", "view")
def item_tags(c, u, a):
    pid = a.get("project_id")
    stores = q(c, "SELECT id, code, name FROM stores WHERE project_id=? AND type<>'transit' ORDER BY code", (int(pid),)) if pid else []
    items = q(c, "SELECT DISTINCT m.id, m.code, m.name, m.unit FROM materials m JOIN stock_balances b ON b.material_id=m.id WHERE b.qty>0.0001" +
              (" AND b.project_id=%d" % int(pid) if pid else "") + " ORDER BY m.code")
    return {"stores": stores, "items": items}


# ═════════════════════════ NFRS ═════════════════════════
LIMITS = {"borrowings": 500e6, "total_assets": 1000e6, "employees": 300, "turnover": 1000e6, "fiduciary": 500e6}
MICRO = {"turnover": 200e6, "borrowings": 100e6, "total_assets": 200e6, "fiduciary": 100e6}


def _tier_facts(c, fy):
    import api_equipment_reports as ER
    s, e = fy_bounds(fy)
    e2 = min(e, today())
    pl = ER.rep_pl(c, None, {"from": s, "to": e2})
    turnover = pl["total_income"] - sum(r["amount"] for r in pl["income"] if (q1(c, "SELECT role FROM accounts WHERE id=?", (r["id"],)) or {}).get("role")
                                         == "equipment_recovery")
    bs = ER.rep_bs(c, None, {"as_of": e2})
    gross_assets = sum(r["amount"] for r in bs["assets"] if r["amount"] > 0)
    loans = val(c, "SELECT SUM(balance) FROM loans WHERE active=1") if _has(c, "loans") else 0
    staff = val(c, "SELECT COUNT(*) FROM staff WHERE active=1") if _has(c, "staff") else 0
    workers = val(c, "SELECT AVG(n) FROM (SELECT d.date, SUM(l.count) n FROM dpr_labour l JOIN dpr d ON d.id=l.dpr_id WHERE d.date BETWEEN ? AND ? "
                     "GROUP BY d.date)", (s, e2))
    return {"turnover": r2(turnover), "total_assets": r2(gross_assets), "borrowings": r2(loans), "employees": round((staff or 0) + (workers or 0))}


def _significant(r):
    return bool(r.get("listed") or r.get("fi") or r.get("gbe") or any(_f(r.get(k)) >= v for k, v in LIMITS.items()))


def _micro(r):
    return not r.get("listed") and not r.get("fi") and all(_f(r.get(k)) <= v for k, v in MICRO.items())


@api("books.tier", "accounts", "view")
def tier(c, u, a):
    """ICAN tiers with the two-year rules: economically significant (NFRS 2024) after hitting any one limit in
    two consecutive years, and out only after being below all limits for two consecutive years; micro
    (NAS for MEs) after meeting all micro limits for two consecutive years."""
    fy = int(a.get("fy") or current_fy())
    years = [fy - 2, fy - 1, fy]
    rows = []
    for y in years:
        r = q1(c, "SELECT * FROM entity_tier WHERE fy=?", (y,))
        auto = None
        if not r:
            try:
                auto = _tier_facts(c, y)
            except Exception:
                auto = {}
            r = dict(auto, fy=y, fiduciary=0, listed=0, fi=0, gbe=0, auto=True)
        r["significant"] = _significant(r)
        r["micro"] = _micro(r)
        r["hits"] = [k for k, v in LIMITS.items() if _f(r.get(k)) >= v]
        rows.append(r)
    prev_tier = a.get("previous_tier") or setting(c, "entity_tier_prev") or "SME"
    t = prev_tier
    y1, y2 = rows[1], rows[2]
    if y1["significant"] and y2["significant"]:
        t = "NFRS"
    elif prev_tier == "NFRS" and not y1["significant"] and not y2["significant"]:
        t = "SME"
    if t != "NFRS":
        if y1["micro"] and y2["micro"]:
            t = "MICRO"
        elif prev_tier == "MICRO" and not y1["micro"] and not y2["micro"]:
            t = "SME"
    warn = None
    if t != "NFRS" and y2["significant"]:
        warn = "This year crosses %s. If next year does too, the company moves to full NFRS 2024." % ", ".join(y2["hits"]) if y2["hits"] else \
            "This year the company is in the public-accountability group."
    label = {"NFRS": "NFRS 2024 (full)", "SME": "NFRS for SMEs 2017", "MICRO": "NAS for Micro Entities 2018"}[t]
    return {"fy": fy, "years": rows, "tier": t, "label": label, "warning": warn, "limits": LIMITS, "micro_limits": MICRO,
            "note": "Limits from ICAN (Dec 2025). Employees include site workers on average. [confirm with the auditor]"}


@api("books.tier_save", "accounts", "edit")
def tier_save(c, u, a):
    r = a.get("row") or {}
    need(r, "fy")
    data = {k: _f(r.get(k)) for k in ("turnover", "borrowings", "total_assets", "employees", "fiduciary")}
    data.update({k: 1 if str(r.get(k)) in ("1", "true") else 0 for k in ("listed", "fi", "gbe")})
    data["remarks"] = r.get("remarks")
    if q1(c, "SELECT fy FROM entity_tier WHERE fy=?", (int(r["fy"]),)):
        sets = ", ".join("%s=?" % k for k in data)
        c.execute("UPDATE entity_tier SET %s WHERE fy=?" % sets, list(data.values()) + [int(r["fy"])])
    else:
        data["fy"] = int(r["fy"])
        ins(c, "entity_tier", data)
    if r.get("previous_tier"):
        _set(c, "entity_tier_prev", r["previous_tier"])
    return True


@api("books.nfrs_status", "accounts", "view")
def nfrs_status(c, u, a):
    """Where each item of the NFRS build checklist lives in BuildCore now."""
    items = [(1, "Entity tier with two-year rules", "Accounts › Integrity checks › NFRS compliance"),
             (2, "Contract register, performance obligations, s.26 flag", "Commercial › IPC billing › Contract accounting"),
             (3, "NFRS 15 contract asset / liability", "Commercial › IPC billing › Contract accounting"),
             (4, "Uninstalled materials and abnormal waste out of progress", "IPC billing › Contract accounting; Material reconciliation"),
             (5, "Variations, claims, escalation, LD with highly-probable flag", "Variations; Events & claims; Contract accounting"),
             (6, "Onerous contract provision", "Commercial › IPC billing › Contract accounting"),
             (7, "Retention and mobilisation-advance sub-ledgers", "Commercial › IPC billing › Retention & advance ledgers"),
             (8, "NPR 25,000 cash-payment limit", "Accounts › Payments (blocked with override); list below"),
             (9, "Immutable vouchers, reversal only", "Built into the database (1.9)"),
             (10, "PPE components and depreciation", "Fixed assets (1.7)"), (11, "Tax depreciation pools", "Fixed assets › Tax depreciation (1.7)"),
             (12, "NFRS 16 leases", "Fixed assets › Leases (1.7)"), (13, "NAS 36 impairment", "Fixed assets › Impairment watch (1.7)"),
             (14, "NAS 2 inventory, NRV, abnormal waste", "Fixed assets › Inventory analysis; Material reconciliation"),
             (15, "ECL provision matrix", "Accounts › Ageing › Expected credit loss"),
             (16, "Provisions register with movement", "Accounts › Balance sheet › Provisions"),
             (17, "Deferred-tax schedule", "Accounts › Balance sheet › Deferred tax"),
             (18, "TDS table by fiscal year", "Accounts › TDS rates › By fiscal year"),
             (19, "JV partner-share statement", "Accounts › Profit & loss › JV partner shares"),
             (20, "Backlog / remaining performance obligations", "Accounts › Cash forecast & ratios; Contract accounting"),
             (21, "Equipment costing and hour-meter depreciation", "Fixed assets (1.7)"),
             (22, "CBMS e-invoice export", "Accounts › Client invoices › CBMS export"),
             (23, "NFRS 18-ready statements", "Accounts › Balance sheet › NFRS 18 view")]
    since, to = fy_bounds(current_fy())
    cash = q(c, "SELECT p.no, p.date, p.gross, pa.name party FROM payments p JOIN accounts a ON a.id=p.bank_account_id LEFT JOIN parties pa ON "
                "pa.id=p.party_id WHERE a.role='cash' AND p.kind='pay' AND p.status='posted' AND p.gross>? AND p.date BETWEEN ? AND ? ORDER BY p.date",
             (_f(setting(c, "cash_limit_npr"), 25000), since, to))
    return {"items": [{"no": n, "item": t, "where": w} for n, t, w in items], "cash_over_limit": cash,
            "cash_over_limit_total": r2(sum(x["gross"] for x in cash)),
            "note": "Cash payments above the limit are not deductible for income tax (Income Tax Act s.21(2)); add the total back in the tax computation."}


# ───────────────────────── ECL ─────────────────────────
@api("books.ecl", "accounts", "view")
def ecl(c, u, a):
    """Simplified approach (lifetime ECL) with a provision matrix by age for receivables and certified IPCs,
    and retention held by clients (aged from the invoice that retained it)."""
    asof = a.get("as_of") or today()
    try:
        rates = json.loads(setting(c, "ecl_rates") or "{}")
    except ValueError:
        rates = {}
    rates = {b[0]: _f(rates.get(b[0]), b[3]) for b in ECL_BUCKETS}
    rows = []
    for inv_ in q(c, "SELECT id, no, party_id, project_id, date, due_date, payable, retention FROM invoices WHERE kind='sales' AND status='posted' "
                     "AND date<=?", (asof,)):
        bal = (inv_["payable"] or 0) - inv.invoice_paid(c, inv_["id"])
        age = (date.fromisoformat(asof) - date.fromisoformat(inv_["due_date"] or inv_["date"])).days
        for kind, amt, ag in (("Receivable", bal, age), ("Retention", inv_["retention"] or 0,
                                                          (date.fromisoformat(asof) - date.fromisoformat(inv_["date"])).days)):
            if amt <= 0.5:
                continue
            b = next(x for x in ECL_BUCKETS if x[1] <= max(ag, 0) <= x[2]) if ag >= 0 else ECL_BUCKETS[0]
            rows.append({"kind": kind, "no": inv_["no"], "party_id": inv_["party_id"], "project_id": inv_["project_id"], "age": ag, "bucket": b[0],
                         "amount": r2(amt), "rate": rates[b[0]], "ecl": r2(amt * rates[b[0]] / 100)})
    matrix = []
    for b in ECL_BUCKETS:
        for kind in ("Receivable", "Retention"):
            xs = [r for r in rows if r["bucket"] == b[0] and r["kind"] == kind]
            if xs:
                matrix.append({"bucket": b[0], "kind": kind, "amount": r2(sum(x["amount"] for x in xs)), "rate": rates[b[0]],
                               "ecl": r2(sum(x["ecl"] for x in xs))})
    need_ = r2(sum(r["ecl"] for r in rows))
    booked = -val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON x.id=l.account_id "
                     "WHERE x.role='ecl_allowance' AND " + POSTED, ())
    return {"as_of": asof, "rows": rows, "matrix": matrix, "rates": rates, "required": need_, "booked": r2(booked),
            "adjustment": r2(need_ - booked), "buckets": [b[0] for b in ECL_BUCKETS],
            "note": "Rates are yours to set from your own loss history (government clients usually pay; the matrix is mainly for private clients). "
                    "Retention is aged from the invoice date."}


@api("books.ecl_rates", "accounts", "edit")
def ecl_rates(c, u, a):
    _set(c, "ecl_rates", json.dumps({k: _f(v) for k, v in (a.get("rates") or {}).items()}))
    return True


@api("books.ecl_post", "accounts", "approve")
def ecl_post(c, u, a):
    d = ecl(c, u, a)
    adj = d["adjustment"]
    if abs(adj) < 0.5:
        raise ApiError("The allowance already matches.")
    _role_account(c, "ecl_allowance", "Allowance for expected credit losses (NFRS 9)", "asset", "1290")
    _role_account(c, "ecl_expense", "Impairment loss on receivables (ECL)", "expense", "5920")
    lines = [{"role": "ecl_expense", "debit": adj}, {"role": "ecl_allowance", "credit": adj}] if adj > 0 else \
        [{"role": "ecl_allowance", "debit": -adj}, {"role": "ecl_expense", "credit": -adj}]
    vid = _post(c, u, a.get("date") or today(), "Expected credit loss allowance adjustment", lines, "ecl")
    audit(c, u, "post", "ecl", None, {"adjustment": adj})
    return {"voucher_id": vid, "adjustment": adj}


# ───────────────────────── provisions register ─────────────────────────
@api("books.prov_list", "accounts", "view")
def prov_list(c, u, a):
    fy = int(a.get("fy") or current_fy())
    s, e = fy_bounds(fy)
    rows = q(c, "SELECT * FROM provisions ORDER BY id DESC")
    moves = {}
    for m in q(c, "SELECT * FROM prov_moves ORDER BY date, id"):
        moves.setdefault(m["provision_id"], []).append(m)
    table = {}
    for r in rows:
        mv = moves.get(r["id"], [])
        opening = sum(m["amount"] * (1 if m["kind"] in ("add", "unwind") else -1) for m in mv if m["date"] < s)
        per = lambda k: sum(m["amount"] for m in mv if m["kind"] == k and s <= m["date"] <= e)
        r.update({"opening": r2(opening), "additions": r2(per("add")), "used": r2(per("use")), "reversed": r2(per("reverse")),
                  "unwinding": r2(per("unwind"))})
        r["closing"] = r2(r["opening"] + r["additions"] + r["unwinding"] - r["used"] - r["reversed"])
        r["moves"] = mv
        t = table.setdefault(r["kind"], {"kind": r["kind"], "opening": 0.0, "additions": 0.0, "used": 0.0, "reversed": 0.0, "unwinding": 0.0, "closing": 0.0})
        for k in ("opening", "additions", "used", "reversed", "unwinding", "closing"):
            t[k] += r[k]
    lab = dict(PROV_KINDS)
    mv_table = [dict(v, label=lab.get(k, k), **{kk: r2(v[kk]) for kk in ("opening", "additions", "used", "reversed", "unwinding", "closing")})
                for k, v in table.items()]
    return {"fy": fy, "rows": rows, "movement": mv_table, "kinds": PROV_KINDS}


@api("books.prov_save", "accounts", "edit")
def prov_save(c, u, a):
    r = a.get("row") or {}
    need(r, "title", "kind")
    data = {"project_id": int(r["project_id"]) if r.get("project_id") else None, "kind": r["kind"], "title": r["title"], "probability": r.get("probability"),
            "basis": r.get("basis"), "remarks": r.get("remarks")}
    if r.get("id"):
        upd(c, "provisions", int(r["id"]), data)
        return {"id": int(r["id"])}
    data.update({"no": next_no(c, "PRV", today()), "date": r.get("date") or today(), "status": "open", "created_by": u["id"]})
    return {"id": ins(c, "provisions", data)}


@api("books.prov_move", "accounts", "approve")
def prov_move(c, u, a):
    """add: Dr expense / Cr provision; use: Dr provision / Cr the account paid from; reverse: Dr provision / Cr expense;
    unwind: Dr finance cost / Cr provision."""
    p = get(c, "provisions", int(a["id"]), "Provision")
    kind = a.get("kind")
    amt = r2(_f(a.get("amount")))
    if kind not in ("add", "use", "reverse", "unwind") or amt <= 0:
        raise ApiError("Choose a movement and an amount.")
    _role_account(c, "provisions", "Provisions (NAS 37)", "liability", "2320")
    _role_account(c, "provision_expense", "Provision expense", "expense", "5930")
    _role_account(c, "finance_cost", "Finance cost - unwinding of discount", "expense", "5940")
    d = a.get("date") or today()
    pj = p["project_id"]
    if kind == "add":
        lines = [{"role": "provision_expense", "debit": amt, "project_id": pj}, {"role": "provisions", "credit": amt, "project_id": pj}]
    elif kind == "reverse":
        lines = [{"role": "provisions", "debit": amt, "project_id": pj}, {"role": "provision_expense", "credit": amt, "project_id": pj}]
    elif kind == "unwind":
        lines = [{"role": "finance_cost", "debit": amt, "project_id": pj}, {"role": "provisions", "credit": amt, "project_id": pj}]
    else:
        acc = int(a["account_id"]) if a.get("account_id") else val(c, "SELECT id FROM accounts WHERE role='bank'", (), None)
        lines = [{"role": "provisions", "debit": amt, "project_id": pj}, {"account_id": acc, "credit": amt, "project_id": pj}]
    vid = _post(c, u, d, "Provision %s: %s %s" % (p["no"], kind, p["title"]), lines, "provision", p["id"], pj)
    ins(c, "prov_moves", {"provision_id": p["id"], "date": d, "kind": kind, "amount": amt, "voucher_id": vid, "note": a.get("note"), "user_id": u["id"]})
    return {"voucher_id": vid}


# ───────────────────────── deferred tax ─────────────────────────
@api("books.deferred", "accounts", "view")
def deferred(c, u, a):
    """NAS 12 schedule: PPE (from Fixed assets 1.7), provisions and the ECL allowance (tax allowed only when paid or
    written off), onerous provisions and lease liabilities less right-of-use assets."""
    rate = _f(setting(c, "tax_rate"), 0.25)
    if rate > 1:
        rate = rate / 100
    items = []
    if "fa.deferred_tax" in inv.FUNCS:
        try:
            d = inv.FUNCS["fa.deferred_tax"][0](c, u, {})
            items.append({"item": "Property, plant and equipment", "carrying": d.get("carrying"), "tax_base": d.get("tax_base"),
                          "difference": r2((d.get("carrying") or 0) - (d.get("tax_base") or 0)), "kind": "taxable"})
        except Exception as e:
            items.append({"item": "Property, plant and equipment", "error": str(e)})

    def bal(role):
        return val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x ON x.id=l.account_id "
                      "WHERE x.role=? AND " + POSTED, (role,))
    for role, label in (("provisions", "Provisions (allowed when paid)"), ("onerous_provision", "Onerous contract provision"),
                        ("ecl_allowance", "Expected credit loss allowance")):
        b = -bal(role)
        if abs(b) > 0.5:
            items.append({"item": label, "carrying": r2(b), "tax_base": 0.0, "difference": r2(-b), "kind": "deductible"})
    lease = -bal("lease_liability")
    rou = bal("rou_asset") + bal("rou_accum")
    if abs(lease) > 0.5 or abs(rou) > 0.5:
        items.append({"item": "Leases (right-of-use asset less lease liability)", "carrying": r2(rou - lease), "tax_base": 0.0,
                      "difference": r2(rou - lease), "kind": "taxable" if rou > lease else "deductible"})
    for x in items:
        if "difference" in x:
            x["deferred_tax"] = r2(x["difference"] * rate)
    net = r2(sum(x.get("deferred_tax") or 0 for x in items))
    return {"rate": rate * 100, "items": items, "net": net, "position": "liability" if net > 0 else "asset",
            "note": "Positive = taxable temporary difference (deferred tax liability). Post the PPE part in Fixed assets › Tax depreciation; "
                    "the rest is shown for the note."}


# ───────────────────────── TDS by fiscal year ─────────────────────────
@api("books.tds_fy", "accounts", "view")
def tds_fy(c, u, a):
    fy = int(a.get("fy") or current_fy())
    rows = q(c, "SELECT * FROM tds_rates_fy WHERE fy=? ORDER BY section, description", (fy,))
    master = q(c, "SELECT * FROM tds_rates WHERE active=1")
    diffs = []
    for m in master:
        hit = next((r for r in rows if r["description"].lower()[:18] == (m["description"] or "").lower()[:18]), None)
        if hit and abs((hit["rate"] or 0) - (m["rate"] or 0)) > 1e-6:
            diffs.append({"master": m["description"], "master_rate": m["rate"], "fy_rate": hit["rate"]})
    years = [r["fy"] for r in q(c, "SELECT DISTINCT fy FROM tds_rates_fy ORDER BY fy")]
    return {"fy": fy, "rows": rows, "years": years, "differences": diffs,
            "note": "Keep one table per fiscal year so an old year's TDS is checked at that year's rates. Verify each rate against the Finance Act."}


@api("books.tds_fy_save", "accounts", "edit")
def tds_fy_save(c, u, a):
    fy = int(a["fy"])
    if a.get("copy_from"):
        if val(c, "SELECT COUNT(*) FROM tds_rates_fy WHERE fy=?", (fy,)):
            raise ApiError("%d already has rates." % fy)
        for r in q(c, "SELECT * FROM tds_rates_fy WHERE fy=?", (int(a["copy_from"]),)):
            r.pop("id")
            r["fy"] = fy
            ins(c, "tds_rates_fy", r)
        return True
    c.execute("DELETE FROM tds_rates_fy WHERE fy=?", (fy,))
    for r in a.get("rows") or []:
        if not r.get("description"):
            continue
        ins(c, "tds_rates_fy", {"fy": fy, "section": r.get("section"), "description": r["description"], "rate": _f(r.get("rate")),
                                "threshold": _f(r.get("threshold")), "final": 1 if str(r.get("final")) in ("1", "true") else 0, "notes": r.get("notes")})
    return True


# ───────────────────────── JV partner shares ─────────────────────────
def _partners(txt, own):
    out = []
    for part in (txt or "").replace(";", ",").split(","):
        if ":" in part:
            n, s = part.split(":", 1)
            try:
                out.append((n.strip(), float(s.strip().rstrip("%"))))
            except ValueError:
                pass
    if not out and own:
        out = [("Us", own), ("Other partners", 100 - own)]
    return out


@api("books.jv", "accounts", "view")
def jv(c, u, a):
    """Each profit-or-loss and balance line of a JV project split by partner share (joint operation: each partner
    books its share). Export and send each partner its column."""
    pid = int(a["project_id"])
    p = get(c, "projects", pid, "Project")
    partners = _partners(p.get("jv_partners"), p.get("jv_share_pct"))
    if not partners:
        raise ApiError("Enter the JV partners and shares in the contract register (IPC billing › Contract accounting), e.g. 'Us: 51, ABC: 49'.")
    tot = sum(s for _n, s in partners)
    frm, to = a.get("from") or "0000-01-01", a.get("to") or today()
    rows = q(c, "SELECT x.code, x.name, x.type, SUM(l.debit-l.credit) amt FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts x "
                "ON x.id=l.account_id WHERE l.project_id=? AND v.date BETWEEN ? AND ? AND " + POSTED + " GROUP BY x.id ORDER BY x.code", (pid, frm, to))
    out = []
    for r in rows:
        if abs(r["amt"] or 0) < 0.5:
            continue
        line = {"code": r["code"], "name": r["name"], "type": r["type"], "total": r2(r["amt"])}
        for n, s in partners:
            line[n] = r2(r["amt"] * s / tot)
        out.append(line)
    return {"project": {"code": p["code"], "name": p["name"]}, "partners": [{"name": n, "share": s} for n, s in partners], "rows": out,
            "from": frm, "to": to, "note": "Debit positive, credit negative. [confirm joint operation vs joint venture per the JV agreement]"}


# ───────────────────────── CBMS e-invoice export ─────────────────────────
@api("books.cbms", "accounts", "view")
def cbms(c, u, a):
    """Sales invoices in the CBMS field layout (seller PAN, buyer PAN and name, invoice number, BS and AD dates,
    taxable amount, VAT, total). Check the exact file format with the IRD before uploading. [confirm]"""
    frm = a.get("from") or fy_bounds(current_fy())[0]
    to = a.get("to") or today()
    pan = setting(c, "company_pan") or ""
    rows = []
    for x in q(c, "SELECT i.*, p.name buyer, p.pan buyer_pan FROM invoices i LEFT JOIN parties p ON p.id=i.party_id WHERE i.kind='sales' AND "
                  "i.status IN ('posted','cancelled') AND i.date BETWEEN ? AND ? ORDER BY i.date, i.id", (frm, to)):
        y, m, d = SC.ad_to_bs(x["date"])
        rows.append({"seller_pan": pan, "buyer_pan": x["buyer_pan"] or "", "buyer_name": x["buyer"] or "", "fiscal_year": "%d.%02d" % (y if m >= 4 else y - 1, (y + 1 if m >= 4 else y) % 100),
                     "invoice_number": x["no"], "invoice_date": "%04d.%02d.%02d" % (y, m, d), "invoice_date_ad": x["date"],
                     "taxable_sales_vat": r2(x["subtotal"]), "vat": r2(x["vat"]), "total_sales": r2(x["total"]), "excisable_amount": 0,
                     "excise": 0, "export_sales": 0, "tax_exempted_sales": 0, "is_realtime": False,
                     "status": "cancelled" if x["status"] == "cancelled" else "active"})
    year_total = val(c, "SELECT SUM(total) FROM invoices WHERE kind='sales' AND status='posted' AND date BETWEEN ? AND ?", fy_bounds(current_fy()))
    return {"rows": rows, "count": len(rows), "total": r2(sum(r["total_sales"] for r in rows if r["status"] == "active")),
            "year_total": r2(year_total), "threshold": 100e6, "linked_required": year_total > 100e6,
            "note": "VAT Act s.14ka: businesses with yearly transactions above NPR 100 million issuing e-invoices are to be linked to CBMS. "
                    "Field names follow the IRD CBMS bill API as commonly published; confirm against the current specification."}


# ───────────────────────── NFRS 18-ready statement ─────────────────────────
N18 = [["operating", "Operating"], ["investing", "Investing"], ["financing", "Financing"], ["tax", "Income tax"], ["discontinued", "Discontinued"]]


def _n18_guess(acc):
    n = (acc["name"] or "").lower()
    role = acc.get("role") or ""
    if role in ("lease_interest", "finance_cost") or "interest expense" in n or "bank charge" in n or ("interest" in n and acc["type"] == "expense"):
        return "financing"
    if role in ("disposal_gain", "disposal_loss") or "dividend" in n or ("interest" in n and acc["type"] == "income") or "investment" in n:
        return "investing"
    if role in ("deferred_tax_exp",) or "income tax" in n or "tax expense" in n:
        return "tax"
    return "operating"


@api("books.nfrs18", "accounts", "view")
def nfrs18(c, u, a):
    """Statement of profit or loss by the NFRS 18 categories (operating, investing, financing, income tax) with the
    required subtotals, and a management-defined performance measure reconciled to the nearest subtotal.
    NFRS 18 is an exposure draft in Nepal; the ledger does not change, only the grouping. [watch]"""
    import api_equipment_reports as ER
    frm = a.get("from") or fy_bounds(current_fy())[0]
    to = a.get("to") or today()
    pl = ER.rep_pl(c, None, {"from": frm, "to": to})
    mp = {r["account_id"]: r["category"] for r in q(c, "SELECT * FROM nfrs18_map")}
    accs = {x["id"]: x for x in q(c, "SELECT * FROM accounts")}
    lines = []
    for r in pl["income"]:
        acc = accs.get(r["id"]) or {}
        lines.append({"id": r["id"], "code": r["code"], "name": r["name"], "amount": r["amount"], "category": mp.get(r["id"]) or _n18_guess(acc)})
    for r in pl["expense"]:
        acc = accs.get(r["id"]) or {}
        lines.append({"id": r["id"], "code": r["code"], "name": r["name"], "amount": -r["amount"], "category": mp.get(r["id"]) or _n18_guess(acc)})
    tot = {k: r2(sum(x["amount"] for x in lines if x["category"] == k)) for k, _l in N18}
    op = tot["operating"]
    before_fin = r2(op + tot["investing"])
    before_tax = r2(before_fin + tot["financing"])
    dep = sum(-x["amount"] for x in lines if (accs.get(x["id"]) or {}).get("role") in ("depreciation",) and x["category"] == "operating")
    return {"from": frm, "to": to, "lines": lines, "totals": tot, "operating_profit": op, "profit_before_financing_and_tax": before_fin,
            "profit_before_tax": before_tax, "profit": r2(before_tax + tot["tax"] + tot["discontinued"]), "categories": N18,
            "mpm": [{"name": "EBITDA (management-defined)", "value": r2(op + dep), "reconciliation": "Operating profit %s + depreciation %s" % (fmt(op), fmt(dep))}]}


def fmt(v):
    return "{:,.2f}".format(v or 0)


@api("books.nfrs18_map", "accounts", "edit")
def nfrs18_map(c, u, a):
    for k, v in (a.get("map") or {}).items():
        if v:
            c.execute("INSERT INTO nfrs18_map(account_id, category) VALUES(?,?) ON CONFLICT(account_id) DO UPDATE SET category=excluded.category",
                      (int(k), v))
        else:
            c.execute("DELETE FROM nfrs18_map WHERE account_id=?", (int(k),))
    return True


# ═════════════════════════ FILE IMPORT (CSV / XLSX) ═════════════════════════
# Replaces "Paste from Excel": the user picks the .csv (or .xlsx) saved from Excel. The whole file is checked first
# (preview), then valid rows are saved; a bad row never stops the others. Existing codes are updated, not duplicated.
import base64
import csv
import io
import re as _re

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DATE_FIELDS = {"planned_start", "planned_finish", "baseline_start", "baseline_finish", "purchase_date", "date", "start_date", "end_date",
               "insurance_expiry", "registration_expiry"}
NUM_FIELDS = {"reorder_level", "reorder_qty", "standard_rate", "lead_days", "min_level", "credit_days", "daily_rate", "monthly_rate",
              "purchase_value", "life_months", "residual_value", "qty", "rate", "planned_qty", "duration", "lag", "weight",
              "chainage_from", "chainage_to", "vat_registered"}

# kind: (title, table, by_project, [(field, required, [aliases])], key field)
IMPORTS = {
    "materials": ("Materials", "materials", False, [
        ("code", True, ["material code", "item code"]), ("name", True, ["material", "item", "description", "material name"]),
        ("category", False, ["group", "type"]), ("unit", True, ["uom", "unit of measure"]),
        ("reorder_level", False, ["reorder at", "reorder point"]), ("reorder_qty", False, ["reorder quantity", "order qty"]),
        ("standard_rate", False, ["rate", "std rate", "price", "unit rate"]), ("lead_days", False, ["lead time", "lead time (days)"]),
        ("min_level", False, ["minimum level", "min stock"]), ("local_name", False, ["nepali name"]), ("spec", False, ["specification"])], "code"),
    "parties": ("Vendors, subcontractors & clients", "parties", False, [
        ("code", True, ["party code", "vendor code"]), ("name", True, ["party", "vendor", "supplier", "party name"]),
        ("kind", False, ["type", "party type"]), ("pan", False, ["pan no", "vat no", "pan / vat no.", "pan/vat"]),
        ("phone", False, ["mobile", "contact"]), ("email", False, ["e-mail"]), ("address", False, ["location"]),
        ("credit_days", False, ["credit period"]), ("vat_registered", False, ["vat registered", "vat"])], "code"),
    "staff": ("Staff", "staff", False, [
        ("code", False, ["staff code", "employee code", "emp code"]), ("name", True, ["staff", "employee", "full name"]),
        ("designation", False, ["post", "position"]), ("phone", False, ["mobile"]),
        ("daily_rate", False, ["daily wage", "wage"]), ("monthly_rate", False, ["salary", "monthly salary"])], "code"),
    "equipment": ("Equipment", "equipment", False, [
        ("code", True, ["equipment code", "machine code"]), ("name", True, ["equipment", "machine", "description"]),
        ("category", False, ["type", "class"]), ("make", False, ["brand", "manufacturer"]), ("model", False, []),
        ("reg_no", False, ["registration", "reg no.", "registration no"]), ("ownership", False, ["owned/hired", "owner"]),
        ("purchase_value", False, ["price", "cost", "purchase price"]), ("life_months", False, ["life (months)", "life"]),
        ("purchase_date", False, ["purchased", "date of purchase"])], "code"),
    "boq_items": ("BOQ items", "boq_items", True, [
        ("code", True, ["item no", "item no.", "s.n.", "sn", "item code", "boq code"]), ("description", True, ["item", "description of work", "particulars"]),
        ("unit", False, ["uom"]), ("qty", False, ["quantity", "boq qty"]), ("rate", False, ["unit rate", "rate (npr)"]),
        ("component", False, ["bill", "bill no", "bill no.", "component name", "structure", "part"])], "code"),
    "activities": ("Schedule activities", "activities", True, [
        ("wbs_code", True, ["wbs", "wbs no"]), ("wbs_name", False, ["wbs description", "wbs title"]),
        ("code", True, ["activity code", "activity id", "id"]), ("name", True, ["activity", "activity name", "description", "task", "task name"]),
        ("unit", False, ["uom"]), ("planned_qty", False, ["qty", "quantity"]), ("planned_start", False, ["start", "start date", "planned start"]),
        ("planned_finish", False, ["finish", "end", "finish date", "end date", "planned finish"]), ("duration", False, ["duration (days)", "days", "working days"]),
        ("predecessors", False, ["predecessor", "pred", "preds"]), ("boq_code", False, ["boq", "boq item", "boq no"]),
        ("location", False, ["area", "chainage"]), ("work_type", False, ["work type"])], "code"),
    "links": ("Schedule links", None, True, [
        ("successor", True, ["succ", "activity", "activity code"]), ("predecessor", True, ["pred"]), ("type", False, ["link type", "relation"]),
        ("lag", False, ["lag (days)"])], None),
    "holidays": ("Holidays", None, False, [
        ("date", True, ["holiday date", "from"]), ("name", False, ["holiday", "description"]), ("kind", False, ["type"])], None),
    "opening": ("Opening stock", None, True, [
        ("material_code", True, ["code", "material", "item code"]), ("qty", True, ["quantity"]), ("rate", False, ["unit rate", "price"])], None),
}


def _decode(data):
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def _grid(a):
    fn = (a.get("filename") or "").lower()
    if a.get("text") is not None:
        text = a["text"]
    else:
        if not a.get("b64"):
            raise ApiError("Choose the file to import.")
        data = base64.b64decode(a["b64"].split(",")[-1])
        if fn.endswith((".xlsx", ".xlsm")) or data[:2] == b"PK":
            import api_ra
            return [[("" if x is None else str(x)) for x in r] for r in api_ra._xlsx_rows(data)], True
        if fn.endswith(".xls"):
            raise ApiError("Old .xls files cannot be read. In Excel use File › Save As › 'CSV UTF-8 (Comma delimited)' or .xlsx.")
        text = _decode(data)
    first = next((l for l in text.splitlines() if l.strip()), "")
    delim = max([",", ";", "\t"], key=lambda d: first.count(d))
    if not first.count(delim):
        delim = ","
    return [r for r in csv.reader(io.StringIO(text), delimiter=delim)], False


def _norm(s):
    return _re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def _map_header(grid, spec):
    """Find the header row (first row in the top 15 that names at least one expected column) and map columns.
    Without a header, the columns are taken in the template order."""
    names = {}
    for f, _req, al in spec:
        for n in [f, f.replace("_", " ")] + al:
            names.setdefault(_norm(n), f)
    for i, r in enumerate(grid[:15]):
        cols = {}
        unknown = []
        for j, x in enumerate(r):
            k = names.get(_norm(x))
            if k and k not in cols.values():
                cols[j] = k
            elif str(x).strip():
                unknown.append(str(x).strip())
        if len(cols) >= max(1, min(2, len(spec))):
            return i + 1, cols, unknown
    return 0, {j: f for j, (f, _r, _a) in enumerate(spec)}, []


def norm_date(v, order="auto"):
    """Excel / CSV date text -> ISO AD. Accepts 2026-09-27, 27/09/2026, 9/27/2026, 27-Sep-2026, Sep 27 2026,
    Excel serial numbers and BS dates (year 2060+)."""
    s = str(v or "").strip()
    if not s:
        return None
    s = s.split(" ")[0] if _re.match(r"^\d{4}-\d\d-\d\d[ T]\d", s) else s
    if _re.fullmatch(r"\d{4,5}(\.\d+)?", s) and 20000 < float(s) < 80000:
        return (date(1899, 12, 30) + timedelta(days=int(float(s)))).isoformat()
    m = _re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        return SC.parse_any_date("%s-%s-%s" % m.groups())
    m = _re.fullmatch(r"(\d{1,2})[-/. ]([A-Za-z]{3,})[-/. ,]*(\d{2,4})", s)
    if m:
        d, mon, y = m.groups()
        y = int(y) + (2000 if len(y) == 2 else 0)
        return date(y, MONTHS[mon[:3].lower()], int(d)).isoformat()
    m = _re.fullmatch(r"([A-Za-z]{3,})[-/. ]+(\d{1,2})[, ]+(\d{2,4})", s)
    if m:
        mon, d, y = m.groups()
        y = int(y) + (2000 if len(y) == 2 else 0)
        return date(y, MONTHS[mon[:3].lower()], int(d)).isoformat()
    m = _re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", s)
    if m:
        a1, a2, y = int(m.group(1)), int(m.group(2)), m.group(3)
        y = int(y) + (2000 if len(y) == 2 else 0)
        if order == "dmy" or (order == "auto" and a1 > 12):
            d, mo = a1, a2
        elif order == "mdy" or (order == "auto" and a2 > 12):
            mo, d = a1, a2
        else:
            d, mo = a1, a2   # auto and ambiguous: day first (Nepal / UK style); the preview shows the result
        if y > 2060:
            return SC.bs_to_ad(y, mo, d).isoformat()
        return date(y, mo, d).isoformat()
    raise ValueError("date '%s' not understood" % s)


def norm_num(v):
    s = str(v or "").strip()
    if not s:
        return ""
    neg = s.startswith("(") and s.endswith(")")
    s = _re.sub(r"(?i)npr|rs\.?|%|\s|,", "", s.strip("()"))
    if s in ("-", ""):
        return ""
    x = float(s)
    return -x if neg else x


def _date_order(values):
    for v in values:
        m = _re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.]\d{2,4}", str(v).strip())
        if m:
            if int(m.group(1)) > 12:
                return "dmy"
            if int(m.group(2)) > 12:
                return "mdy"
    return "dmy"


KIND_WORDS = {"vendor": "vendor", "supplier": "vendor", "seller": "vendor", "subcontractor": "subcontractor", "sub contractor": "subcontractor",
              "sub-contractor": "subcontractor", "petty contractor": "subcontractor", "client": "client", "employer": "client", "customer": "client"}


def _savepoint(c, name, fn):
    c.execute("SAVEPOINT " + name)
    try:
        r = fn()
    except Exception:
        c.execute("ROLLBACK TO " + name)
        c.execute("RELEASE " + name)
        raise
    c.execute("RELEASE " + name)
    return r


@api("imp.template", "masters", "view")
def imp_template(c, u, a):
    spec = IMPORTS[a["kind"]]
    ex = {"materials": ["CEM-OPC", "Cement OPC 43 grade", "Cement", "bag", "500", "1000", "900", "14"],
          "parties": ["V-001", "Himal Suppliers", "vendor", "301234567", "9851000000", "", "Kathmandu", "30"],
          "staff": ["S-001", "Ram Thapa", "Site engineer", "9851000001", "", "60000"],
          "equipment": ["EX-01", "Excavator 20 t", "Excavator", "CAT", "320D", "BA 1 KHA 1234", "owned", "14000000", "120", "2024-05-12"],
          "boq_items": ["2.01", "Common excavation in soil", "m3", "1250", "450", "Headworks"],
          "activities": ["1.1", "Headworks", "1.1.01", "Excavation of weir foundation", "m3", "1250", "2026-10-01", "2026-11-15", "", "", "2.01", "Weir", "river"],
          "links": ["1.1.02", "1.1.01", "FS", "0"], "holidays": ["2083-07-22", "Tihar", "festival"], "opening": ["CEM-OPC", "250", "895"]}
    rows = [[f for f, _r, _a in spec[3]], ex.get(a["kind"], [])]
    out = io.StringIO()
    csv.writer(out, lineterminator="\r\n").writerows(rows)
    return {"filename": "%s_import_template.csv" % a["kind"], "csv": out.getvalue(),
            "columns": [{"field": f, "required": r} for f, r, _a in spec[3]]}


@api("imp.file", "masters", "view")
def imp_file(c, u, a):
    """Import a .csv / .xlsx saved from Excel. apply=0 checks every row and changes nothing; apply=1 saves the
    rows that pass. Codes that already exist are updated."""
    kind = a.get("kind")
    if kind not in IMPORTS:
        raise ApiError("Unknown import.")
    title, table, by_project, spec, key = IMPORTS[kind]
    pid = int(a["project_id"]) if a.get("project_id") else None
    if by_project and not pid:
        raise ApiError("Select a project first.")
    grid, is_xlsx = _grid(a)
    start, cols, unknown = _map_header(grid, spec)
    data = []
    for n, r in enumerate(grid[start:], start + 1):
        if not any(str(x).strip() for x in r):
            continue
        row = {f: str(r[j]).strip() if j < len(r) else "" for j, f in cols.items()}
        row["_line"] = n
        data.append(row)
    missing = [f for f, req, _a in spec if req and f not in cols.values()]
    if missing and start:
        raise ApiError("The file has no column for: %s. First row of your file: %s" % (", ".join(missing), ", ".join(str(x) for x in grid[start - 1][:10])))
    order = a.get("date_order") or "auto"
    if order == "auto":
        order = _date_order([r.get(f) for r in data for f in DATE_FIELDS if r.get(f)])
    apply = bool(a.get("apply"))
    results = []

    def clean(r):
        out = {}
        for f, v in r.items():
            if f == "_line":
                continue
            if f == "vat_registered":
                out[f] = 1 if str(v).strip().lower() in ("1", "yes", "y", "true", "registered") else 0
            elif f in DATE_FIELDS:
                out[f] = norm_date(v, order) if v else None
            elif f in NUM_FIELDS and kind not in ("links",):
                try:
                    out[f] = norm_num(v)
                except ValueError:
                    raise ValueError("%s: '%s' is not a number" % (f.replace("_", " "), v))
            else:
                out[f] = v
        return out

    if kind == "opening":
        lines = []
        for r in data:
            try:
                x = clean(r)
                m = q1(c, "SELECT id, name FROM materials WHERE lower(code)=lower(?)", (x["material_code"],))
                if not m:
                    raise ValueError("material %s not found" % x["material_code"])
                if not x.get("qty"):
                    raise ValueError("quantity missing")
                lines.append({"material_id": m["id"], "qty": x["qty"], "rate": x.get("rate") or ""})
                results.append({"line": r["_line"], "key": x["material_code"], "name": m["name"], "action": "add"})
            except Exception as e:
                results.append({"line": r["_line"], "key": r.get("material_code"), "error": str(e)})
        return _summary(results, cols, unknown, order, lines=lines)

    if kind in ("links", "holidays"):
        from core import require
        require(u, "project", "edit")
        for r in data:
            try:
                x = clean(r)
                if kind == "holidays":
                    x["date"] = norm_date(r["date"], order) if ".." not in r["date"] else r["date"]
                results.append({"line": r["_line"], "key": x.get("successor") or x.get("date"), "name": x.get("predecessor") or x.get("name"),
                                "action": "add", "_x": x})
            except Exception as e:
                results.append({"line": r["_line"], "key": r.get("successor") or r.get("date"), "error": str(e)})
        ok = [x.pop("_x") for x in results if "_x" in x]
        if kind == "links":
            text = "\n".join("\t".join(str(x.get(k) or "") for k in ("successor", "predecessor", "type", "lag")) for x in ok)
            fn = lambda: inv.FUNCS["sched.links_paste"][0](c, u, {"project_id": pid, "text": text})
        else:
            fn = lambda: inv.FUNCS["sched.hol_save"][0](c, u, {"rows": [{"date": x["date"], "name": x.get("name") or "Holiday",
                                                                          "kind": x.get("kind") or "public", "calendar_id": a.get("calendar_id")} for x in ok]})
        c.execute("SAVEPOINT imp_all")
        try:
            res = fn() if ok else {}
        except ApiError as e:
            c.execute("ROLLBACK TO imp_all")
            c.execute("RELEASE imp_all")
            raise
        errs = res.get("errors") or res.get("bad") or []
        passed = [x for x in results if "error" not in x]
        for e in errs:
            m = _re.match(r"line (\d+): (.*)", str(e))
            if m and int(m.group(1)) <= len(ok):
                hit = passed[int(m.group(1)) - 1]
                hit["error"], hit["action"] = m.group(2), None
            elif not m:
                results.append({"line": "", "key": str(e), "error": "could not read this date"})
        if not apply:
            c.execute("ROLLBACK TO imp_all")
        c.execute("RELEASE imp_all")
        return _summary(results, cols, unknown, order, applied=apply)

    save = inv.FUNCS["master.save"][0]
    c.execute("SAVEPOINT imp_all")
    try:
        preds = []
        for i, r in enumerate(data):
            try:
                x = clean(r)
                row = {k: v for k, v in x.items() if k not in ("wbs_code", "wbs_name", "boq_code", "predecessors")}
                if by_project:
                    row["project_id"] = pid
                kv = (x.get(key) or "").strip() if key else ""
                if kind == "parties":
                    row["kind"] = KIND_WORDS.get((x.get("kind") or "vendor").strip().lower(), (x.get("kind") or "vendor").strip().lower())
                    row.setdefault("credit_days", 30)
                    if row["kind"] not in ("vendor", "subcontractor", "client"):
                        raise ValueError("type must be vendor, subcontractor or client")
                if kind == "parties" and row.get("vat_registered") in ("", None):
                    row.pop("vat_registered", None)
                if kind == "boq_items":
                    row.pop("component", None)
                    if x.get("component"):
                        cv = x["component"].strip()
                        comp = q1(c, "SELECT id FROM boq_components WHERE project_id=? AND active=1 AND (lower(code)=lower(?) OR lower(name)=lower(?))", (pid, cv, cv))
                        if not comp:
                            import api_adv
                            api_adv.ensure(c)
                            comp = {"id": ins(c, "boq_components", {"project_id": pid, "code": cv if len(cv) <= 6 else "", "name": cv, "active": 1,
                                                                     "sort": val(c, "SELECT COUNT(*) FROM boq_components WHERE project_id=?", (pid,))})}
                        row["component_id"] = comp["id"]
                if kind == "activities":
                    w = q1(c, "SELECT id FROM wbs WHERE project_id=? AND code=?", (pid, x["wbs_code"]))
                    if not w:
                        if not x.get("wbs_code"):
                            raise ValueError("WBS code missing")
                        w = save(c, u, {"table": "wbs", "row": {"project_id": pid, "code": x["wbs_code"], "name": x.get("wbs_name") or x["wbs_code"]}})
                    row["wbs_id"] = w["id"]
                    if x.get("boq_code"):
                        b = q1(c, "SELECT id FROM boq_items WHERE project_id=? AND code=?", (pid, x["boq_code"]))
                        if not b:
                            raise ValueError("BOQ item %s not found in this project" % x["boq_code"])
                        row["boq_item_id"] = b["id"]
                    if x.get("planned_start") and x.get("planned_finish") and x["planned_finish"] < x["planned_start"]:
                        raise ValueError("finish %s is before start %s" % (x["planned_finish"], x["planned_start"]))
                for k in list(row):
                    if row[k] == "" and k in NUM_FIELDS:
                        row.pop(k)
                ex = None
                if kv:
                    if by_project:
                        ex = q1(c, "SELECT id FROM %s WHERE project_id=? AND lower(code)=lower(?)" % table, (pid, kv))
                    else:
                        ex = q1(c, "SELECT id FROM %s WHERE lower(code)=lower(?)" % table, (kv,))
                if ex:
                    row["id"] = ex["id"]
                    row["code"] = kv
                saved = _savepoint(c, "imp_row", lambda: save(c, u, {"table": table, "row": row}))
                results.append({"line": r["_line"], "key": kv or row.get("name"), "name": row.get("name") or row.get("description"),
                                "action": "update" if ex else "add", "start": row.get("planned_start"), "finish": row.get("planned_finish")})
                if kind == "activities" and x.get("predecessors"):
                    preds.append((len(results) - 1, saved["id"], x["predecessors"]))
            except Exception as e:
                results.append({"line": r["_line"], "key": (r.get(key) if key else "") or r.get("name"), "name": r.get("name") or r.get("description"),
                                "error": str(e)})
        for idx, aid, ptxt in preds:      # second pass, so predecessors further down the file are found
            try:
                res = _savepoint(c, "imp_row", lambda: save(c, u, {"table": "activities", "row": {"id": aid, "predecessors": ptxt}}))
                if res.get("warning"):
                    results[idx]["warning"] = res["warning"]
            except Exception as e:
                results[idx]["warning"] = "predecessors not set: %s" % e
    except Exception:
        c.execute("ROLLBACK TO imp_all")
        c.execute("RELEASE imp_all")
        raise
    if not apply:
        c.execute("ROLLBACK TO imp_all")
    c.execute("RELEASE imp_all")
    if apply:
        audit(c, u, "import", table, None, {"file": a.get("filename"), "rows": len(results)})
    return _summary(results, cols, unknown, order, applied=apply)


def _summary(results, cols, unknown, order, applied=False, lines=None):
    ok = [r for r in results if not r.get("error")]
    out = {"rows": results, "added": sum(1 for r in ok if r.get("action") == "add"), "updated": sum(1 for r in ok if r.get("action") == "update"),
           "failed": len(results) - len(ok), "columns": sorted(set(cols.values())), "ignored_columns": unknown,
           "date_order": {"dmy": "day/month/year", "mdy": "month/day/year"}.get(order, order), "applied": applied}
    if lines is not None:
        out["lines"] = lines
    return out


# ═════════════════════════ Nepali (BS) dates everywhere ═════════════════════════
@api("bs.table")
def bs_table(c, u, a):
    """The BS calendar (1 Baishakh in AD and the 12 month lengths for each year) for the browser to convert
    dates both ways without a round trip."""
    return {"years": {str(y): {"start": v[0], "months": [int(v[1][i:i + 2]) for i in range(0, 24, 2)]} for y, v in SC.BS.items()},
            "months": SC.BS_MONTHS}


# ═════════════════════════ 2.7  Admin delete (one or many) and voucher duplicate ═════════════════════════
# Creating is easy; deleting used to mean one record at a time and a message for each one.  An administrator
# can now tick any number of rows in a list and delete them together.  Nothing that has already moved money or
# stock is ever removed: posted and approved records, and masters used by them, are refused with the reason
# ("reverse / cancel it", "mark it inactive").  Setup-only rows that belong to a master (a machine's
# attachments, a material's coefficients, a zero stock balance…) go with it.

# which columns in other tables point at each master
_REFCOLS = {
    "projects": ["project_id"],
    "parties": ["party_id", "vendor_id", "supplier_id", "hirer_party_id", "owner_party_id", "recommended_vendor_id",
                "client_id"],
    "materials": ["material_id", "output_material_id"],
    "accounts": ["account_id", "bank_account_id"],
    "account_groups": ["group_id"],
    "equipment": ["equipment_id"],
    "stores": ["store_id", "from_store", "to_store"],
    "boq_items": ["boq_item_id"],
    "staff": ["custodian_staff_id"],
    "tds_rates": ["tds_rate_id"],
    "maint_plans": ["plan_id"],
    "hire_agreements": ["agreement_id"],
}
# rows that are only set-up for the master and may be removed with it (table: extra condition)
_CASCADE = {
    "material_coefficients": "", "act_resources": "", "eq_tools": "", "equipment_rates": "", "equipment_spares": "",
    "inv_policy": "", "nfrs18_map": "", "stock_balances": "ABS(COALESCE(qty,0))<0.0001", "maint_plans": "",
    "equipment_status_log": "", "import_map": "",
}
# extra set-up rows a new project creates by itself
_PROJECT_CASCADE = {"stores": "", "sched_calendars": "", "wbs": "", "boq_components": "", "trades": "", "site_packs": "",
                    "sched_windows": "", "sched_holidays": ""}
_IGNORE = {"audit", "activity", "sessions", "comments"}
_NULLIFY = {("staff", "project_id"), ("equipment", "project_id")}   # a person or machine simply loses the link


def _is_admin(u):
    if not u or u.get("role") != "admin":
        raise ApiError("Only an administrator can delete records in bulk.")


def _tables_with(c, col):
    out = []
    for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        if t in _IGNORE or t.startswith("sqlite_"):
            continue
        if col in {r[1] for r in c.execute("PRAGMA table_info(%s)" % t).fetchall()}:
            out.append(t)
    return out


def _label(t):
    return t.replace("_", " ")


def _admin_master_delete(c, u, t, rid):
    row = q1(c, "SELECT * FROM %s WHERE id=?" % t, (rid,))
    if not row:
        raise ApiError("Already deleted.")
    if t == "accounts" and row.get("role"):
        raise ApiError("This is a system account used by automatic postings; it cannot be deleted.")
    if t == "stores" and row.get("type") == "transit":
        raise ApiError("The in-transit store is part of the project.")
    if t == "fiscal_periods" and row.get("status") not in (None, "open"):
        raise ApiError("Only open periods can be deleted.")
    cols = list(_REFCOLS.get(t, []))
    uses, cascade, nullify = [], [], []
    extra_casc = _PROJECT_CASCADE if t == "projects" else {}
    for col in cols:
        for rt in _tables_with(c, col):
            if rt == t:
                continue
            n = val(c, "SELECT COUNT(*) FROM %s WHERE %s=?" % (rt, col), (rid,))
            if not n:
                continue
            if (rt, col) in _NULLIFY:
                nullify.append((rt, col))
            elif rt in _CASCADE or rt in extra_casc:
                cond = _CASCADE.get(rt, extra_casc.get(rt, ""))
                if cond:
                    bad = val(c, "SELECT COUNT(*) FROM %s WHERE %s=? AND NOT (%s)" % (rt, col, cond), (rid,))
                    if bad:
                        uses.append("%s (%d)" % (_label(rt), bad))
                        continue
                cascade.append((rt, col, cond))
            else:
                uses.append("%s (%d)" % (_label(rt), n))
    # self references (a parent group or store)
    for col in ("parent_id",):
        if t in ("account_groups", "stores", "wbs") and val(c, "SELECT COUNT(*) FROM %s WHERE %s=?" % (t, col), (rid,)):
            uses.append("sub-%s" % _label(t))
    if t == "account_groups" and val(c, "SELECT COUNT(*) FROM accounts WHERE group_id=?", (rid,)):
        pass  # already counted through group_id
    if uses:
        raise ApiError("Used in " + ", ".join(sorted(set(uses))) + ". Mark it inactive instead.")
    # a project's own stores must be empty too
    if t == "projects":
        for s in q(c, "SELECT id FROM stores WHERE project_id=?", (rid,)):
            if val(c, "SELECT COUNT(*) FROM stock_ledger WHERE store_id=?", (s["id"],)):
                raise ApiError("A store of this project has stock movements.")
        cal = [x["id"] for x in q(c, "SELECT id FROM sched_calendars WHERE project_id=?", (rid,))] \
            if "sched_calendars" in {x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table'")} else []
        for cid in cal:
            for ct in ("sched_holidays", "sched_windows"):
                try:
                    c.execute("DELETE FROM %s WHERE calendar_id=?" % ct, (cid,))
                except Exception:
                    pass
    removed = {}
    for rt, col, cond in cascade:
        cur = c.execute("DELETE FROM %s WHERE %s=?%s" % (rt, col, (" AND " + cond) if cond else ""), (rid,))
        removed[rt] = removed.get(rt, 0) + (cur.rowcount or 0)
    for rt, col in nullify:
        c.execute("UPDATE %s SET %s=NULL WHERE %s=?" % (rt, col, col), (rid,))
    c.execute("DELETE FROM %s WHERE id=?" % t, (rid,))
    audit(c, u, "delete", t, rid, {"row": row, "with": removed})
    return removed


def _dpr_delete(c, u, a):
    d = get(c, "dpr", int(a["id"]), "Daily report")
    if d["status"] == "approved":
        raise ApiError("Approved — reopen the DPR first (it reverses what it posted), then delete it.")
    if val(c, "SELECT COUNT(*) FROM plant_runs WHERE dpr_id=?", (d["id"],)):
        raise ApiError("A plant production run is linked to this DPR.")
    if val(c, "SELECT COUNT(*) FROM logsheets WHERE dpr_id=? AND status<>'draft'", (d["id"],)):
        raise ApiError("Approved logsheet days came from this DPR.")
    eq = [x["id"] for x in q(c, "SELECT id FROM dpr_equipment WHERE dpr_id=?", (d["id"],))]
    if eq:
        try:
            c.execute("DELETE FROM log_tools WHERE dpr_equipment_id IN (%s)" % ",".join("?" * len(eq)), eq)
        except Exception:
            pass
    for lg in q(c, "SELECT id FROM logsheets WHERE dpr_id=?", (d["id"],)):
        c.execute("DELETE FROM log_meters WHERE log_id=?", (lg["id"],))
        try:
            c.execute("DELETE FROM log_tools WHERE log_id=?", (lg["id"],))
        except Exception:
            pass
        c.execute("DELETE FROM logsheets WHERE id=?", (lg["id"],))
    for t in ("dpr_work", "dpr_labour", "dpr_equipment", "dpr_delays", "dpr_survey"):
        c.execute("DELETE FROM %s WHERE dpr_id=?" % t, (d["id"],))
    for t in ("events", "qa_tests", "files"):
        try:
            c.execute("UPDATE %s SET dpr_id=NULL WHERE dpr_id=?" % t, (d["id"],))
        except Exception:
            pass
    c.execute("DELETE FROM dpr WHERE id=?", (d["id"],))
    audit(c, u, "delete", "dpr", d["id"], d)
    return True


def _via(name, build):
    def run(c, u, rid):
        fn = inv.FUNCS[name][0]
        return fn(c, u, build(rid))
    return run


def _kinds():
    k = {}
    for t in inv.MASTERS:
        if t in _REFCOLS or t == "fiscal_periods":
            k[t] = ("master", lambda c, u, rid, t=t: _admin_master_delete(c, u, t, rid))
        else:   # lists added by other screens keep their own checks
            k[t] = ("record", _via("master.delete", lambda rid, t=t: {"table": t, "id": rid}))
    for t in inv.DOCS:
        k.setdefault(t, ("draft document", _via("doc.delete", lambda rid, t=t: {"type": t, "id": rid})))
    for t in getattr(P, "REGISTERS", {}):
        k.setdefault(t, ("register", _via("reg.delete", lambda rid, t=t: {"table": t, "id": rid})))
    k["vouchers"] = ("draft voucher", _via("voucher.delete", lambda rid: {"id": rid}))
    k["dpr"] = ("daily report", lambda c, u, rid: _dpr_delete(c, u, {"id": rid}))
    k["measurements"] = ("measurement", _via("meas.delete", lambda rid: {"id": rid}))
    k["ipc"] = ("draft IPC", _via("ipc.delete", lambda rid: {"id": rid}))
    k["logsheets"] = ("logsheet day", _via("log.delete", lambda rid: {"id": rid}))
    if "life.viol_delete" in inv.FUNCS:
        k["violations"] = ("violation", _via("life.viol_delete", lambda rid: {"id": rid}))
    if "book.delete" in inv.FUNCS:
        k["logbooks"] = ("monthly logsheet", _via("book.delete", lambda rid: {"id": rid}))
    return k


@api("adm.kinds")
def adm_kinds(c, u, a):
    """The lists an administrator can delete from (the browser shows 'Delete selected' only on these)."""
    if not u or u.get("role") != "admin":
        return {"kinds": [], "admin": False}
    return {"kinds": sorted(_kinds().keys()), "admin": True}


@api("adm.delete")
def adm_delete(c, u, a):
    """Delete many records at once.  Each one is tried on its own: what can go is deleted, what cannot is
    listed with the reason, and nothing half-done is left behind."""
    _is_admin(u)
    kinds = _kinds()
    kind = a.get("kind")
    if kind not in kinds:
        raise ApiError("Records in this list cannot be deleted here.")
    ids = []
    for x in a.get("ids") or []:
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            pass
    if not ids:
        raise ApiError("Select at least one row.")
    label, fn = kinds[kind]
    deleted, refused = [], []
    for n, rid in enumerate(ids):
        sp = "admdel%d" % n
        try:
            _savepoint(c, sp, lambda: fn(c, u, rid))
            deleted.append(rid)
        except ApiError as e:
            refused.append({"id": rid, "reason": str(e)})
        except Exception as e:  # a database rule (e.g. posted records are locked)
            refused.append({"id": rid, "reason": "Locked: " + str(e)})
    audit(c, u, "bulk_delete", kind, None, {"deleted": deleted, "refused": len(refused)})
    return {"kind": kind, "label": label, "deleted": deleted, "refused": refused}


@api("voucher.dup", "accounts", "edit")
def voucher_dup(c, u, a):
    """Alt+2 — a new draft copied from any voucher, dated today (or the date given)."""
    v = get(c, "vouchers", int(a["id"]), "Voucher")
    if (v.get("source") or "manual") != "manual":
        raise ApiError("This voucher was made automatically from a %s; copy the %s instead." % (v["source"], v["source"]))
    lines = q(c, "SELECT account_id, debit, credit, narration, project_id, equipment_id, boq_item_id, party_id "
                 "FROM voucher_lines WHERE voucher_id=? ORDER BY id", (v["id"],))
    save = inv.FUNCS["voucher.save"][0]
    out = save(c, u, {"header": {"date": a.get("date") or today(), "type": v["type"],
        "narration": v["narration"] or ("Copy of " + (v["no"] or "voucher")), "project_id": v["project_id"],
        "ref_no": v.get("ref_no")}, "lines": lines, "allow_control": False})
    nid = out.get("id") if isinstance(out, dict) else out
    if not nid:
        nid = val(c, "SELECT MAX(id) FROM vouchers WHERE created_by=?", (u["id"],))
    audit(c, u, "duplicate", "vouchers", nid, {"from": v["id"]})
    return {"id": nid}
