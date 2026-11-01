"""
Decision centre (BuildCore 2.14): figures for decisions, from the company's own records.

Built around what goes wrong most in Nepal's construction industry:
  * contracts that turn "sick" (late, abandoned) - a portfolio radar that warns early, project by project;
  * payments held up by clients - each client's real days to certify and to pay, learnt from the IPCs and
    receipts, put into the cash forecast, with the interest a late payment costs;
  * low bidding and over-commitment - bid capacity (A x N x M - B), licence class limit, and a bid price
    simulator for the "closest to the average of the bids" award rule (Public Procurement Act, 2083
    amendment), from the competitors' own past bids;
  * price escalation - price adjustment by index, per IPC;
  * poor control of sub-contractors - a scorecard from DPR labour, bills, payments and safety;
  * no learning between projects - benchmarks of delay causes, productivity against norm and cost per sq ft;
  * small builders - a house estimate in minutes from area, storeys and quality, priced from the rate book.

Every figure says where it came from. Rules of thumb and legal parameters that need checking are marked
so; all of them can be changed in the screens.
"""
import json
import math
import random
from datetime import date, timedelta

from core import ApiError, audit, fy_of, ins, need, next_no, now, num, q, q1, r2, setting, today, upd, val
from api_inventory import FUNCS, api

VERSION = "2.14.0"

SCHEMA = """
CREATE TABLE IF NOT EXISTS pa_indices(id INTEGER PRIMARY KEY, code TEXT, name TEXT, period TEXT, value REAL,
  source TEXT, updated TEXT, UNIQUE(code, period));
CREATE TABLE IF NOT EXISTS pa_formula(project_id INTEGER PRIMARY KEY, base_period TEXT, fixed_a REAL DEFAULT 0.15,
  coeffs TEXT, start_after_months INTEGER DEFAULT 0, remarks TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS house_estimates(id INTEGER PRIMARY KEY, no TEXT, client TEXT, location TEXT, inputs TEXT,
  result TEXT, total REAL, per_sqft REAL, project_id INTEGER, created_by INTEGER, ts TEXT);
"""

PROFILES = {
    "home": {"label": "Home builder / small building contractor (houses, small buildings)",
             "hide_groups": ["Plant", "Fixed assets", "Assets"],
             "hide_items": ["p/evm", "c/bids", "c/docs", "acc/budget", "acc/cash", "acc/tdsrates", "acc/integrity",
                            "eq/rates", "eq/dep", "eq/kpi", "eq/hire", "rp/pool", "inv/risk", "inv/recon",
                            "proc/cs", "proc/vendors", "p/control", "p/kpi", "command"]},
    "small": {"label": "Small contractor (licence class D / C)",
              "hide_groups": ["Fixed assets"],
              "hide_items": ["acc/tdsrates", "fa/leases", "fa/impair", "c/docs"]},
    "medium": {"label": "Medium contractor (licence class B)", "hide_groups": [], "hide_items": []},
    "large": {"label": "Large contractor (class A) / JV on large projects", "hide_groups": [], "hide_items": []},
    "owner": {"label": "Client / consultant side (monitoring contracts)",
              "hide_groups": ["Plant", "Fixed assets", "Assets", "Equipment"],
              "hide_items": ["c/bids", "inv/risk", "proc/cs"]},
}
# Licence class limits (NPR). Sources disagree on the exact bands - edit them in the profile.  [confirm]
CLASS_LIMITS = {"D": 3e6, "C": 1e7, "B": 2e7, "A": None}

# House rule-of-thumb quantities per sq ft of built-up area (civilconcept.com Nepal estimator: cement 0.45 bag,
# steel 5.5 kg, bricks 22; bricknbolt.com 1000 sq ft guide: sand 1.2-1.6 cft, aggregate 1.5-2 cft). Editable.
HOUSE_RULES = {"cement_bag": 0.45, "steel_kg": 5.5, "brick_no": 22, "sand_cft": 1.6, "agg_cft": 1.8}
# cost shares that are not materials priced above - BuildCore defaults, change them to your own figures
HOUSE_SHARES = {"basic": {"labour_pct": 25, "finish_pct": 22, "services_pct": 10},
                "standard": {"labour_pct": 25, "finish_pct": 30, "services_pct": 12},
                "premium": {"labour_pct": 24, "finish_pct": 40, "services_pct": 15}}
HOUSE_STAGES = [("Foundation up to plinth", 20), ("Ground floor structure (columns, slab)", 15),
                ("Upper floor structure (each slab)", 25), ("Brick walls and plaster", 15),
                ("Plumbing, electrical, flooring", 15), ("Painting, doors, handover", 10)]
CFT = 0.0283168


def init_decide(c):
    for st in SCHEMA.strip().split(";"):
        if st.strip():
            c.execute(st)
    cols = {r[1] for r in c.execute("PRAGMA table_info(projects)").fetchall()}
    for col, typ in (("built_area_sqft", "REAL"), ("licence_class", "TEXT")):
        if col not in cols:
            c.execute("ALTER TABLE projects ADD COLUMN %s %s" % (col, typ))


def _has(c, t):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone())


def _cols(c, t):
    return {r[1] for r in c.execute("PRAGMA table_info(%s)" % t).fetchall()}


def _d(s):
    try:
        return date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def _json_setting(c, key, default):
    try:
        v = setting(c, key)
        return json.loads(v) if v else default
    except (ValueError, TypeError):
        return default


def _set(c, key, value):
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", (key, value))


# ───────────────────────── company profile (scale) ─────────────────────────
def _profile(c):
    p = _json_setting(c, "dc_profile", {})
    p.setdefault("kind", "")
    p.setdefault("licence_class", "")
    p.setdefault("class_limits", CLASS_LIMITS)
    p.setdefault("bid_m", 1.5)
    p.setdefault("bid_years_back", 5)
    p.setdefault("turnover_escalation_pct", 5.0)
    p.setdefault("turnover_manual", {})
    p.setdefault("other_commitments", 0)
    p.setdefault("late_interest_pct", 10.0)
    p.setdefault("house_rules", HOUSE_RULES)
    p.setdefault("house_shares", HOUSE_SHARES)
    p.setdefault("house_stages", HOUSE_STAGES)
    return p


@api("dc.profile_get")
def profile_get(c, u, a):
    p = _profile(c)
    return {"profile": p, "profiles": [{"key": k, "label": v["label"], "hide_groups": v["hide_groups"],
                                        "hide_items": v["hide_items"]} for k, v in PROFILES.items()]}


@api("dc.profile_save", "admin", "edit")
def profile_save(c, u, a):
    p = _profile(c)
    for k, v in (a.get("profile") or {}).items():
        if k in p:
            p[k] = v
    if p["kind"] and p["kind"] not in PROFILES:
        raise ApiError("Unknown kind of company.")
    _set(c, "dc_profile", json.dumps(p))
    audit(c, u, "profile", "settings", None, {"kind": p["kind"], "class": p["licence_class"]})
    return profile_get(c, u, {})


# ───────────────────────── project facts used everywhere ─────────────────────────
def _project_facts(c, p):
    """Progress, time, money and warning signs of one project, from whatever records it has."""
    pid = p["id"]
    td = date.today()
    f = {"id": pid, "code": p["code"], "name": p["name"], "client": p.get("client"),
         "contract_value": p.get("contract_value") or 0}
    start = _d(p.get("ntp_date")) or _d(p.get("start_date"))
    end = _d(p.get("completion_date")) or _d(p.get("end_date"))
    if start and p.get("tfc_days") and not _d(p.get("completion_date")):
        end = start + timedelta(days=int(p["tfc_days"]))
    f["start"], f["end"] = (start.isoformat() if start else None), (end.isoformat() if end else None)
    f["time_pct"] = round(min(150.0, max(0.0, 100.0 * (td - start).days / max(1, (end - start).days))), 1) if start and end else None
    f["days_left"] = (end - td).days if end else None
    boq = q1(c, "SELECT SUM(COALESCE(revised_qty, qty) * COALESCE(revised_rate, rate)) v, "
                "SUM(COALESCE(executed_qty,0) * COALESCE(revised_rate, rate)) e FROM boq_items WHERE project_id=?", (pid,)) or {}
    base = boq.get("v") or f["contract_value"] or 0
    f["work_done"] = r2(boq.get("e") or 0)
    f["progress_pct"] = round(100.0 * (boq.get("e") or 0) / base, 1) if base else None
    f["spi"] = round(f["progress_pct"] / f["time_pct"], 2) if f["progress_pct"] is not None and f["time_pct"] else None
    ipcs = q(c, "SELECT * FROM ipc WHERE project_id=? AND status<>'draft' ORDER BY date", (pid,)) if _has(c, "ipc") else []
    f["certified"] = r2(sum(x["gross"] or 0 for x in ipcs if x["status"] in ("certified", "paid", "invoiced")))
    f["last_ipc"] = ipcs[-1]["date"] if ipcs else None
    f["days_since_ipc"] = (td - _d(ipcs[-1]["date"])).days if ipcs and _d(ipcs[-1]["date"]) else None
    unpaid = 0.0
    oldest = None
    for x in ipcs:
        if not x.get("invoice_id"):
            continue
        inv = q1(c, "SELECT total, date FROM invoices WHERE id=?", (x["invoice_id"],))
        paid = val(c, "SELECT COALESCE(SUM(amount),0) FROM allocations WHERE invoice_id=? AND COALESCE(active,1)=1",
                   (x["invoice_id"],), 0) or 0
        due = (inv["total"] if inv else 0) - paid
        if due > 1:
            unpaid += due
            dd = _d(inv["date"]) if inv else None
            if dd and (oldest is None or dd < oldest):
                oldest = dd
    f["unpaid_certified"] = r2(unpaid)
    f["oldest_unpaid_days"] = (td - oldest).days if oldest else None
    adv = (p.get("advance_pct") or 0) * (p.get("contract_value") or 0) / 100.0
    rec = sum(x["advance_recovery"] or 0 for x in ipcs)
    f["advance_outstanding"] = r2(max(0.0, adv - rec)) if adv else 0
    f["advance_vs_work_left"] = round(100.0 * f["advance_outstanding"] / max(1.0, base - (boq.get("e") or 0)), 1) if adv and base else None
    last_dpr = val(c, "SELECT MAX(date) FROM dpr WHERE project_id=?", (pid,), None)
    f["days_since_dpr"] = (td - _d(last_dpr)).days if _d(last_dpr) else None
    f["open_ncr"] = val(c, "SELECT COUNT(*) FROM ncrs WHERE project_id=? AND status='open'", (pid,), 0) if _has(c, "ncrs") else 0
    f["open_events"] = val(c, "SELECT COUNT(*) FROM events WHERE project_id=? AND status NOT IN ('closed','settled','rejected')",
                           (pid,), 0) if _has(c, "events") else 0
    f["expiring"] = []
    if _has(c, "contracts"):
        for k in q(c, "SELECT title, bond_expiry, insurance_expiry FROM contracts WHERE project_id=? AND COALESCE(status,'') "
                      "NOT IN ('closed','cancelled')", (pid,)):
            for col, lab in (("bond_expiry", "bond / guarantee"), ("insurance_expiry", "insurance")):
                dd = _d(k.get(col))
                if dd and (dd - td).days <= 30:
                    f["expiring"].append("%s %s %s" % (k["title"] or "contract", lab, "expired" if dd < td else "expires " + dd.isoformat()))
    f["lti_90"] = val(c, "SELECT COUNT(*) FROM hs_incidents WHERE project_id=? AND kind IN ('lti','fatality') AND date>=?",
                      (pid, (td - timedelta(days=90)).isoformat()), 0) if _has(c, "hs_incidents") else 0
    f["delay_hours_30"] = val(c, "SELECT COALESCE(SUM(x.hours),0) FROM dpr_delays x JOIN dpr d ON d.id=x.dpr_id WHERE d.project_id=? AND d.date>=?",
                              (pid, (td - timedelta(days=30)).isoformat()), 0) if _has(c, "dpr_delays") else 0
    return f


def _score(f):
    """0-100 health score with the reasons, from the signs that most often come before a contract is
    called 'sick': slow progress against time, no work recorded, money tied up, open quality and
    safety problems, guarantees running out."""
    s, why = 100.0, []

    def hit(pts, txt):
        nonlocal s
        s -= pts
        why.append(txt)
    if f.get("spi") is not None and f["time_pct"] and f["time_pct"] > 10:
        if f["spi"] < 0.6:
            hit(30, "progress %.0f%% against %.0f%% of the time gone (SPI %.2f)" % (f["progress_pct"], f["time_pct"], f["spi"]))
        elif f["spi"] < 0.85:
            hit(15, "progress behind time (SPI %.2f)" % f["spi"])
    if f.get("time_pct") is not None and f["time_pct"] >= 100 and (f.get("progress_pct") or 0) < 100:
        hit(20, "completion date passed with %.0f%% done" % (f.get("progress_pct") or 0))
    if f.get("days_since_dpr") is None:
        hit(10, "no daily progress report recorded")
    elif f["days_since_dpr"] > 30:
        hit(20, "no DPR for %d days - site may be idle" % f["days_since_dpr"])
    elif f["days_since_dpr"] > 7:
        hit(7, "no DPR for %d days" % f["days_since_dpr"])
    if f.get("days_since_ipc") is not None and f["days_since_ipc"] > 90:
        hit(10, "no IPC for %d days" % f["days_since_ipc"])
    if f.get("oldest_unpaid_days") and f["oldest_unpaid_days"] > 60:
        hit(10, "certified bills unpaid for %d days (Rs %s)" % (f["oldest_unpaid_days"], "{:,.0f}".format(f["unpaid_certified"])))
    if f.get("advance_vs_work_left") and f["advance_vs_work_left"] > 25:
        hit(10, "mobilisation advance not recovered: %.0f%% of the work left" % f["advance_vs_work_left"])
    if f.get("open_ncr"):
        hit(min(10, 3 * f["open_ncr"]), "%d open NCR" % f["open_ncr"])
    if f.get("lti_90"):
        hit(min(15, 8 * f["lti_90"]), "%d lost-time injury / fatality in 90 days" % f["lti_90"])
    if f.get("expiring"):
        hit(min(10, 5 * len(f["expiring"])), "; ".join(f["expiring"][:3]))
    s = max(0.0, s)
    band = "Healthy" if s >= 75 else "Watch" if s >= 55 else "At risk" if s >= 35 else "Critical"
    return round(s), band, why


@api("dc.radar", "commercial", "view")
def radar(c, u, a):
    rows = []
    for p in q(c, "SELECT * FROM projects WHERE COALESCE(status,'active') IN ('active','ongoing','running') ORDER BY code"):
        f = _project_facts(c, p)
        f["score"], f["band"], f["reasons"] = _score(f)
        rows.append(f)
    rows.sort(key=lambda r: r["score"])
    return {"rows": rows, "counts": {b: sum(1 for r in rows if r["band"] == b) for b in ("Critical", "At risk", "Watch", "Healthy")},
            "note": "Score 0-100 from progress against time, days without DPR or IPC, unpaid bills, unrecovered advance, "
                    "open NCRs, lost-time injuries and expiring guarantees. Critical below 35, at risk below 55."}


# ───────────────────────── client payment behaviour ─────────────────────────
def _ipc_timeline(c):
    out = []
    if not _has(c, "ipc"):
        return out
    for x in q(c, "SELECT i.*, p.code pcode, p.cert_days, p.pay_days, pa.name client_name FROM ipc i "
                  "JOIN projects p ON p.id=i.project_id LEFT JOIN parties pa ON pa.id=i.client_id "
                  "WHERE i.status<>'draft' ORDER BY i.date"):
        sub = _d(x["date"])
        inv = q1(c, "SELECT date, total FROM invoices WHERE id=?", (x["invoice_id"],)) if x.get("invoice_id") else None
        cert = _d(inv["date"]) if inv else None
        al = q(c, "SELECT date, amount FROM allocations WHERE invoice_id=? AND COALESCE(active,1)=1 ORDER BY date",
               (x["invoice_id"],)) if x.get("invoice_id") else []
        paid_amt = sum(r["amount"] or 0 for r in al)
        total = (inv or {}).get("total") or 0
        paid_full = total and paid_amt >= total - 1
        paid_on = _d(al[-1]["date"]) if al and paid_full else None
        rec = {"ipc": x["no"], "project": x["pcode"], "client": x.get("client_name") or "—", "submitted": x["date"],
               "certified": cert.isoformat() if cert else None, "paid": paid_on.isoformat() if paid_on else None,
               "amount": r2(total or x.get("net") or 0), "paid_amount": r2(paid_amt),
               "days_to_certify": max(0, (cert - sub).days) if cert and sub else None,
               "days_to_pay": max(0, (paid_on - cert).days) if paid_on and cert else None,
               "contract_pay_days": x.get("pay_days") or 28, "contract_cert_days": x.get("cert_days") or 21}
        if cert and not paid_on:
            rec["waiting_days"] = (date.today() - cert).days
        elif sub and not cert:
            rec["waiting_days"] = (date.today() - sub).days
        out.append(rec)
    return out


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


@api("dc.payments", "commercial", "view")
def payments(c, u, a):
    rate = num(a.get("interest_pct")) or _profile(c)["late_interest_pct"]
    rows = _ipc_timeline(c)
    clients = {}
    for r in rows:
        g = clients.setdefault(r["client"], {"client": r["client"], "ipcs": 0, "cert": [], "pay": [], "late": 0, "done": 0,
                                             "outstanding": 0.0, "oldest": 0, "interest": 0.0})
        g["ipcs"] += 1
        g["cert"].append(r["days_to_certify"])
        g["pay"].append(r["days_to_pay"])
        if r["days_to_pay"] is not None:
            g["done"] += 1
            if r["days_to_pay"] > r["contract_pay_days"]:
                g["late"] += 1
        if not r["paid"] and r["certified"]:
            due = r["amount"] - r["paid_amount"]
            g["outstanding"] += due
            g["oldest"] = max(g["oldest"], r.get("waiting_days") or 0)
            over = (r.get("waiting_days") or 0) - r["contract_pay_days"]
            if over > 0:
                r["interest"] = r2(due * rate / 100 * over / 365)
                g["interest"] += r["interest"]
    out = []
    for g in clients.values():
        ac, ap = _avg(g["cert"]), _avg(g["pay"])
        total_days = (ac or 0) + (ap or 0)
        grade = "A" if total_days <= 45 else "B" if total_days <= 75 else "C" if total_days <= 120 else "D"
        if g["oldest"] > 180:
            grade = "E"
        out.append({"client": g["client"], "ipcs": g["ipcs"], "avg_days_to_certify": ac, "avg_days_to_pay": ap,
                    "late_pct": round(100.0 * g["late"] / g["done"], 0) if g["done"] else None,
                    "outstanding": r2(g["outstanding"]), "oldest_waiting_days": g["oldest"],
                    "interest_claimable": r2(g["interest"]), "grade": grade})
    out.sort(key=lambda x: -x["outstanding"])
    return {"clients": out, "ipcs": rows[::-1], "interest_pct": rate,
            "note": "Days are counted from the IPC date to the client's invoice (certification) and to the last receipt "
                    "that clears it. Grade A: certified and paid within 45 days on average; E: a bill waiting more than "
                    "180 days. Interest on late payment uses the rate given - check the contract's clause."}


@api("dc.payments_apply", "commercial", "edit")
def payments_apply(c, u, a):
    """Put the client's real days to certify and pay into this project's cash-flow terms."""
    need(a, "project_id")
    p = q1(c, "SELECT * FROM projects WHERE id=?", (int(a["project_id"]),))
    if not p:
        raise ApiError("Project not found.")
    rows = [r for r in _ipc_timeline(c) if r["project"] == p["code"]]
    client = rows[0]["client"] if rows else None
    if client:
        rows = [r for r in _ipc_timeline(c) if r["client"] == client]
    ac, ap = _avg([r["days_to_certify"] for r in rows]), _avg([r["days_to_pay"] for r in rows])
    if ac is None and ap is None:
        raise ApiError("No certified or paid IPC yet for this client - nothing to learn from.")
    ch = {}
    if ac is not None:
        ch["cert_days"] = round(ac)
    if ap is not None:
        ch["pay_days"] = round(ap)
    upd(c, "projects", p["id"], ch)
    audit(c, u, "learn_terms", "projects", p["id"], ch)
    return dict(ch, client=client)


# ───────────────────────── bid capacity ─────────────────────────
def _turnover_by_fy(c):
    out = {}
    for r in q(c, "SELECT date, subtotal, total FROM invoices WHERE kind='sales' AND status IN ('posted','paid')"):
        try:
            fy = fy_of(c, r["date"])
        except Exception:
            fy = str(r["date"])[:4]
        out[fy] = out.get(fy, 0) + (r["subtotal"] or r["total"] or 0)
    return out


def capacity_calc(c, years=None, m=None, bid_value=None):
    p = _profile(c)
    ty = _turnover_by_fy(c)
    for fy, v in (p.get("turnover_manual") or {}).items():
        if v not in (None, ""):
            ty[fy] = num(v)
    esc = num(p.get("turnover_escalation_pct")) / 100.0
    fys = sorted(ty.keys())[-int(p.get("bid_years_back") or 5):]
    updated = []
    for i, fy in enumerate(fys):
        age = len(fys) - 1 - i
        updated.append({"fy": fy, "turnover": r2(ty[fy]), "updated": r2(ty[fy] * (1 + esc) ** age)})
    A = max([x["updated"] for x in updated] or [0])
    N = num(years) if years not in (None, "") else 1.0
    M = num(m) if m not in (None, "") else num(p.get("bid_m") or 1.5)
    commit = []
    for pr in q(c, "SELECT * FROM projects WHERE COALESCE(status,'active') IN ('active','ongoing','running')"):
        f = _project_facts(c, pr)
        left = max(0.0, (pr.get("contract_value") or 0) - max(f["certified"], f["work_done"]))
        commit.append({"project": pr["code"], "contract_value": pr.get("contract_value") or 0, "remaining": r2(left)})
    for b in q(c, "SELECT no, title, our_bid FROM bids WHERE status='won' AND project_id IS NULL") if _has(c, "bids") else []:
        commit.append({"project": "%s %s (won, not started)" % (b["no"], b["title"] or ""), "contract_value": b["our_bid"] or 0,
                       "remaining": r2(b["our_bid"] or 0)})
    B = sum(x["remaining"] for x in commit) + num(p.get("other_commitments") or 0)
    cap = A * N * M - B
    lim = (p.get("class_limits") or CLASS_LIMITS).get(p.get("licence_class") or "")
    res = {"A": r2(A), "N": N, "M": M, "B": r2(B), "capacity": r2(cap), "turnover": updated, "commitments": commit,
           "other_commitments": num(p.get("other_commitments") or 0), "licence_class": p.get("licence_class"),
           "class_limit": lim,
           "formula": "Bid capacity = A x N x M - B. A = highest yearly turnover of the last %d years, brought to "
                      "today's prices at %.1f%% a year; N = years to complete the new work; M = %.2f; B = work still to do "
                      "on contracts in hand. Check A's period and M in the bid document." % (int(p.get("bid_years_back") or 5),
                                                                                             esc * 100, M)}
    if bid_value:
        res["bid_value"] = bid_value
        res["ok"] = cap >= bid_value
        res["class_ok"] = lim is None or bid_value <= lim
    return res


@api("dc.capacity", "commercial", "view")
def capacity(c, u, a):
    return capacity_calc(c, a.get("years"), a.get("m"), num(a.get("bid_value")) if a.get("bid_value") else None)


# ───────────────────────── bid price simulator ─────────────────────────
def _history_ratios(c, work_type=None, client=None):
    rows = q(c, "SELECT b.work_type, b.client, b.ee, p.price, p.is_us FROM bid_prices p JOIN bids b ON b.id=p.bid_id "
                "WHERE b.ee>0 AND p.price>0 AND p.is_us=0") if _has(c, "bids") else []
    allr = [x["price"] / x["ee"] for x in rows]
    pick, basis = allr, "all past bids"
    if work_type:
        t = [x["price"] / x["ee"] for x in rows if (x["work_type"] or "").lower() == work_type.lower()]
        if len(t) >= 8:
            pick, basis = t, "past bids for %s" % work_type
    if client and len(pick) >= 8:
        t = [x["price"] / x["ee"] for x in rows if (x["client"] or "").lower() == client.lower()]
        if len(t) >= 8:
            pick, basis = t, "past bids for %s" % client
    nb = [val(c, "SELECT COUNT(*) FROM bid_prices WHERE bid_id=?", (b["id"],), 0) for b in q(c, "SELECT id FROM bids")] if _has(c, "bids") else []
    nb = sorted(n for n in nb if n > 1)
    return pick, basis, (nb[len(nb) // 2] if nb else None)


def simulate(ratios, n_others, our_ratios, rule="average", floor=0.70, runs=2000, seed=7):
    rnd = random.Random(seed)
    fallback = not ratios or len(ratios) < 5
    mu, sd = 0.88, 0.07
    if not fallback:
        mu = sum(ratios) / len(ratios)
        sd = max(0.02, math.sqrt(sum((x - mu) ** 2 for x in ratios) / max(1, len(ratios) - 1)))

    def draw():
        if fallback:
            return rnd.gauss(mu, sd)
        return rnd.choice(ratios) + rnd.gauss(0, 0.01)
    wins = {r: 0 for r in our_ratios}
    for _ in range(runs):
        others = [draw() for _ in range(n_others)]
        for r in our_ratios:
            bids = others + [r]
            if rule == "lowest":
                valid = [b for b in bids if b <= 1.0]
                if valid and min(valid) == r:
                    wins[r] += 1
                continue
            valid = [b for b in bids if floor <= b <= 1.0]
            if r not in valid:
                continue
            avg = sum(valid) / len(valid)
            best = min(valid, key=lambda b: (abs(b - avg), b))
            if best == r:
                wins[r] += 1
    return {r: wins[r] / runs for r in our_ratios}, {"mean": round(mu, 4), "sd": round(sd, 4), "assumed": fallback,
                                                     "samples": len(ratios or [])}


@api("dc.bid_sim", "commercial", "view")
def bid_sim(c, u, a):
    b = q1(c, "SELECT * FROM bids WHERE id=?", (int(a["bid_id"]),)) if a.get("bid_id") and _has(c, "bids") else {}
    ee = num(a.get("ee")) or (b or {}).get("ee")
    cost = num(a.get("our_cost")) or (b or {}).get("our_cost")
    if not ee or not cost:
        raise ApiError("Enter the engineer's estimate and your cost.")
    wt = a.get("work_type") or (b or {}).get("work_type")
    cl = a.get("client") or (b or {}).get("client")
    ratios, basis, typical_n = _history_ratios(c, wt, cl)
    n = int(num(a.get("bidders")) or typical_n or 6)
    rule = a.get("rule") or "average"
    floor = num(a.get("floor_pct") or 70) / 100.0
    min_mk = num(a.get("min_markup_pct") if a.get("min_markup_pct") not in (None, "") else 3) / 100.0
    grid = [round(x / 1000.0, 3) for x in range(int(max(floor, 0.5) * 1000), 1001, 5)]
    pw, dist = simulate(ratios, max(1, n - 1), grid, rule, floor)
    rows = []
    for r in grid:
        price = ee * r
        profit = price - cost
        rows.append({"pct_ee": round(r * 100, 1), "price": r2(price), "win_prob": round(100 * pw[r], 1),
                     "markup_pct": round(100 * (price / cost - 1), 2), "expected_profit": r2(pw[r] * profit)})
    ok = [x for x in rows if x["markup_pct"] >= min_mk * 100]
    best = max(ok, key=lambda x: x["expected_profit"]) if ok else None
    likely = max(rows, key=lambda x: x["win_prob"]) if rows else None
    cap = capacity_calc(c, a.get("years") or 1, None, best["price"] if best else ee)
    return {"ee": ee, "cost": cost, "cost_pct_ee": round(100 * cost / ee, 1), "bidders": n, "rule": rule,
            "floor_pct": floor * 100, "history": dict(dist, basis=basis if not dist["assumed"] else "no bid history yet - assumed spread"),
            "rows": rows, "best": best, "most_likely_win": likely, "capacity": cap,
            "note": ("Award to the bid closest to the average of the bids between %.0f%% and 100%% of the estimate "
                     "(Public Procurement Act, 2083 amendment, as reported) - check the bid document. " % (floor * 100)
                     if rule == "average" else "Award to the lowest bid not above the estimate. ")
            + "Competitor bids are drawn from your bid register (%s); %d simulated tenders per price." % (basis, 2000)}


@api("dc.bid_check", "commercial", "view")
def bid_check(c, u, a):
    """Go / no-go: capacity, licence class, backlog, the client's payment record, the health of the jobs in
    hand, cash needed and your record with this client - each a pass, warning or stop with its figure."""
    bid_value = num(a.get("bid_value"))
    if not bid_value:
        raise ApiError("Enter the bid amount.")
    years = num(a.get("years")) or 1
    client = (a.get("client") or "").strip()
    items = []

    def add(name, status, detail):
        items.append({"check": name, "status": status, "detail": detail})
    cap = capacity_calc(c, years, None, bid_value)
    if not cap["A"]:
        add("Bid capacity", "warn", "No turnover recorded yet - enter past years' turnover in Company profile to work it out")
    else:
        add("Bid capacity", "pass" if cap["ok"] else "stop", "Capacity Rs {:,.0f} against this bid Rs {:,.0f}".format(cap["capacity"], bid_value))
    if cap["class_limit"]:
        add("Licence class", "pass" if cap["class_ok"] else "stop", "Class %s allows up to Rs {:,.0f}".format(cap["class_limit"]) % cap["licence_class"])
    else:
        add("Licence class", "pass" if cap.get("licence_class") else "warn",
            "Class %s - no upper limit" % cap["licence_class"] if cap.get("licence_class") else "Set your licence class in the profile")
    rev = max([x["turnover"] for x in cap["turnover"][-1:]] or [0])
    backlog_m = 12.0 * cap["B"] / rev if rev else None
    if backlog_m is not None:
        add("Work in hand", "warn" if backlog_m > 24 else "pass", "%.0f months of work in hand at last year's turnover" % backlog_m)
    rad = radar(c, u, {})
    bad = [r["code"] for r in rad["rows"] if r["band"] in ("Critical", "At risk")]
    add("Jobs in hand", "warn" if bad else "pass", ("At risk / critical: " + ", ".join(bad)) if bad else "All running jobs healthy or on watch")
    if client:
        pay = [x for x in payments(c, u, {})["clients"] if x["client"].lower() == client.lower()]
        if pay:
            g = pay[0]
            add("Client pays", "pass" if g["grade"] in ("A", "B") else "warn" if g["grade"] == "C" else "stop",
                "Grade %s: %s days to certify, %s days to pay on average; Rs {:,.0f} outstanding".format(g["outstanding"])
                % (g["grade"], g["avg_days_to_certify"], g["avg_days_to_pay"]))
        else:
            add("Client pays", "warn", "No payment record with this client yet")
        st = q(c, "SELECT status FROM bids WHERE LOWER(client)=LOWER(?) AND status IN ('won','lost')", (client,)) if _has(c, "bids") else []
        if st:
            w = sum(1 for x in st if x["status"] == "won")
            add("Record with client", "pass" if w else "warn", "%d won of %d bids" % (w, len(st)))
    perf = 0.05 * bid_value
    adv = num(a.get("advance_pct") if a.get("advance_pct") not in (None, "") else 10) / 100.0
    months = max(1.0, years * 12)
    need_cash = perf + 2 * bid_value / months * 0.85 - adv * bid_value
    cash = None
    try:
        cs = FUNCS["cash.summary"][0](c, u, {})
        cash = cs.get("cash") if isinstance(cs, dict) else None
    except Exception:
        cash = None
    if cash is not None:
        add("Cash", "pass" if cash >= need_cash else "warn",
            "Needs about Rs {:,.0f} (5% performance security + 2 months of cost - advance); cash and bank Rs {:,.0f}".format(max(0, need_cash), cash))
    else:
        add("Cash", "warn", "Needs about Rs {:,.0f} (5% performance security + 2 months of cost - advance)".format(max(0, need_cash)))
    stops = sum(1 for x in items if x["status"] == "stop")
    warns = sum(1 for x in items if x["status"] == "warn")
    verdict = "No-go" if stops else "Go with care" if warns >= 2 else "Go"
    return {"verdict": verdict, "items": items, "capacity": cap}


# ───────────────────────── price adjustment (escalation) ─────────────────────────
@api("dc.idx_list", "commercial", "view")
def idx_list(c, u, a):
    return q(c, "SELECT * FROM pa_indices ORDER BY code, period")


@api("dc.idx_save", "commercial", "edit")
def idx_save(c, u, a):
    n = 0
    for r in a.get("rows") or []:
        if not r.get("code") or not r.get("period") or r.get("value") in (None, ""):
            continue
        per = str(r["period"])[:7]
        c.execute("INSERT INTO pa_indices(code, name, period, value, source, updated) VALUES(?,?,?,?,?,?) "
                  "ON CONFLICT(code, period) DO UPDATE SET value=excluded.value, name=COALESCE(excluded.name, name), "
                  "source=excluded.source, updated=excluded.updated",
                  (r["code"].strip().upper(), r.get("name"), per, num(r["value"]), r.get("source"), now()))
        n += 1
    return {"saved": n}


@api("dc.idx_delete", "commercial", "edit")
def idx_delete(c, u, a):
    c.execute("DELETE FROM pa_indices WHERE id=?", (int(a["id"]),))
    return True


@api("dc.pa_get", "commercial", "view")
def pa_get(c, u, a):
    f = q1(c, "SELECT * FROM pa_formula WHERE project_id=?", (int(a["project_id"]),))
    if f:
        f["coeffs"] = json.loads(f["coeffs"] or "[]")
    return f or {"project_id": int(a["project_id"]), "base_period": "", "fixed_a": 0.15, "coeffs": [], "start_after_months": 0}


@api("dc.pa_save", "commercial", "edit")
def pa_save(c, u, a):
    r = a.get("row") or {}
    pid = int(r["project_id"])
    co = [{"code": x["code"].strip().upper(), "weight": num(x["weight"])} for x in r.get("coeffs") or [] if x.get("code")]
    tot = num(r.get("fixed_a")) + sum(x["weight"] for x in co)
    if abs(tot - 1) > 0.005:
        raise ApiError("The fixed part and the weights must add up to 1.00 (now %.3f)." % tot)
    c.execute("INSERT OR REPLACE INTO pa_formula(project_id, base_period, fixed_a, coeffs, start_after_months, remarks, updated) "
              "VALUES(?,?,?,?,?,?,?)", (pid, str(r.get("base_period") or "")[:7], num(r.get("fixed_a")), json.dumps(co),
                                        int(num(r.get("start_after_months"))), r.get("remarks"), now()))
    return pa_get(c, u, {"project_id": pid})


def _index(c, code, period):
    r = q1(c, "SELECT value, period FROM pa_indices WHERE code=? AND period<=? ORDER BY period DESC LIMIT 1", (code, period))
    return (r["value"], r["period"]) if r else (None, None)


@api("dc.pa_calc", "commercial", "view")
def pa_calc(c, u, a):
    pid = int(a["project_id"])
    f = pa_get(c, u, {"project_id": pid})
    if not f.get("coeffs") or not f.get("base_period"):
        raise ApiError("Set the price adjustment formula first (base month and the weights).")
    base = {x["code"]: _index(c, x["code"], f["base_period"]) for x in f["coeffs"]}
    rows, total = [], 0.0
    p = q1(c, "SELECT * FROM projects WHERE id=?", (pid,))
    start = _d((p or {}).get("ntp_date")) or _d((p or {}).get("start_date"))
    for i in q(c, "SELECT * FROM ipc WHERE project_id=? AND status<>'draft' ORDER BY date", (pid,)):
        per = str(i.get("period_to") or i["date"])[:7]
        miss, factor, parts = [], f["fixed_a"], []
        for x in f["coeffs"]:
            b0 = base[x["code"]][0]
            vn, pn = _index(c, x["code"], per)
            if not b0 or vn is None:
                miss.append(x["code"])
                continue
            factor += x["weight"] * vn / b0
            parts.append("%s %.4g/%.4g" % (x["code"], vn, b0))
        months = None
        if start and _d(i["date"]):
            months = (_d(i["date"]).year - start.year) * 12 + _d(i["date"]).month - start.month
        applies = not (f.get("start_after_months") and months is not None and months < f["start_after_months"])
        value = i["gross"] or 0
        adj = (factor - 1) * value if not miss and applies else 0.0
        total += adj
        rows.append({"ipc": i["no"], "month": per, "work_value": r2(value), "factor": round(factor, 5) if not miss else None,
                     "adjustment": r2(adj), "missing": miss, "applies": applies, "indices": ", ".join(parts)})
    return {"rows": rows, "total": r2(total), "formula": f,
            "note": "Pn = a + sum(w x In / Io). Adjustment = (Pn - 1) x value of work in the IPC. Use the indices and the "
                    "weights named in the contract (e.g. NRB / National Statistics Office price indices)."}


@api("dc.pa_claim", "commercial", "edit")
def pa_claim(c, u, a):
    pid = int(a["project_id"])
    r = pa_calc(c, u, {"project_id": pid})
    amt = r["total"]
    if abs(amt) < 1:
        raise ApiError("No price adjustment to claim.")
    no = next_no(c, "EVT", today())
    eid = ins(c, "events", {"no": no, "project_id": pid, "date": today(), "type": "escalation",
                            "title": "Price adjustment claim to %s" % (r["rows"][-1]["month"] if r["rows"] else today()),
                            "description": "Price adjustment by the contract formula: " + "; ".join(
                                "%s Rs %s" % (x["ipc"], "{:,.0f}".format(x["adjustment"])) for x in r["rows"] if x["adjustment"]),
                            "cost_impact": amt, "status": "open", "created_by": u["id"]})
    audit(c, u, "claim", "events", eid, {"amount": amt})
    return {"id": eid, "no": no, "amount": amt}


# ───────────────────────── sub-contractor scorecard ─────────────────────────
@api("dc.subcons", "commercial", "view")
def subcons(c, u, a):
    td = date.today()
    since = a.get("since") or (td - timedelta(days=365)).isoformat()
    parties = {r["id"]: r for r in q(c, "SELECT id, code, name, kind FROM parties")}
    ids = {r["party_id"] for r in q(c, "SELECT DISTINCT party_id FROM dpr_labour WHERE party_id IS NOT NULL")} if _has(c, "dpr_labour") else set()
    ids |= {k for k, v in parties.items() if (v["kind"] or "") == "subcontractor"}
    out = []
    for pid in ids:
        pa = parties.get(pid)
        if not pa:
            continue
        lab = q1(c, "SELECT COALESCE(SUM(l.count*COALESCE(l.hours,8)),0) mh, COALESCE(SUM(l.count),0) md, COALESCE(SUM(l.amount),0) amt, "
                    "COUNT(DISTINCT d.date) days, MAX(d.date) last FROM dpr_labour l JOIN dpr d ON d.id=l.dpr_id "
                    "WHERE l.party_id=? AND d.date>=?", (pid, since)) if _has(c, "dpr_labour") else {}
        bills = q1(c, "SELECT COALESCE(SUM(total),0) t, COUNT(*) n FROM invoices WHERE kind='purchase' AND party_id=? "
                      "AND status IN ('posted','paid') AND date>=?", (pid, since)) or {}
        paid = val(c, "SELECT COALESCE(SUM(a.amount),0) FROM allocations a JOIN invoices i ON i.id=a.invoice_id "
                      "WHERE i.party_id=? AND i.kind='purchase' AND COALESCE(a.active,1)=1 AND i.date>=?", (pid, since), 0) or 0
        inc = q(c, "SELECT kind FROM hs_incidents WHERE party_id=? AND date>=?", (pid, since)) if _has(c, "hs_incidents") else []
        w = q1(c, "SELECT COUNT(*) n, SUM(CASE WHEN COALESCE(ssf_no,'')<>'' THEN 1 ELSE 0 END) ssf, "
                  "SUM(CASE WHEN COALESCE(bank_acno,'')<>'' THEN 1 ELSE 0 END) bank, "
                  "SUM(CASE WHEN COALESCE(insurance_expiry,'')>=? THEN 1 ELSE 0 END) ins FROM hs_workers WHERE party_id=? AND active=1",
               (td.isoformat(), pid)) if _has(c, "hs_workers") else None
        mh = (lab or {}).get("mh") or 0
        lti = sum(1 for x in inc if x["kind"] in ("lti", "fatality"))
        rec = {"party_id": pid, "code": pa["code"], "name": pa["name"], "man_days": r2((lab or {}).get("md") or 0),
               "man_hours": r2(mh), "days_on_site": (lab or {}).get("days") or 0, "last_on_site": (lab or {}).get("last"),
               "labour_value": r2((lab or {}).get("amt") or 0), "billed": r2(bills.get("t") or 0), "bills": bills.get("n") or 0,
               "paid": r2(paid), "outstanding": r2((bills.get("t") or 0) - paid), "incidents": len(inc), "lti": lti,
               "ltifr": round(lti * 1e6 / mh, 2) if mh else None,
               "workers": (w or {}).get("n") or 0,
               "ssf_pct": round(100.0 * (w["ssf"] or 0) / w["n"]) if w and w["n"] else None,
               "bank_pct": round(100.0 * (w["bank"] or 0) / w["n"]) if w and w["n"] else None,
               "insured_pct": round(100.0 * (w["ins"] or 0) / w["n"]) if w and w["n"] else None}
        s = 100
        if lti:
            s -= min(30, 15 * lti)
        if rec["ssf_pct"] is not None and rec["ssf_pct"] < 80:
            s -= 15
        if rec["insured_pct"] is not None and rec["insured_pct"] < 100:
            s -= 10
        if rec["last_on_site"] and _d(rec["last_on_site"]) and (td - _d(rec["last_on_site"])).days > 14:
            s -= 10
        if rec["workers"] == 0:
            s -= 10
        rec["score"] = max(0, s)
        out.append(rec)
    out.sort(key=lambda x: x["score"])
    return {"rows": out, "since": since,
            "note": "From DPR labour booked to the sub-contractor (man-days and hours), their bills and what was paid, "
                    "safety incidents, and the workers registered with SSF number, bank account and accident insurance "
                    "(Labour Act 2074: Rs 7 lakh minimum accident insurance; the 2083 procurement amendment asks for SSF "
                    "and bank payment of workers)."}


# ───────────────────────── benchmarks across projects ─────────────────────────
@api("dc.bench", "commercial", "view")
def bench(c, u, a):
    since = a.get("since") or (date.today() - timedelta(days=730)).isoformat()
    delays = q(c, "SELECT x.category, p.code project, COUNT(*) n, COALESCE(SUM(x.hours),0) hours FROM dpr_delays x "
                  "JOIN dpr d ON d.id=x.dpr_id JOIN projects p ON p.id=d.project_id WHERE d.date>=? "
                  "GROUP BY x.category, p.code ORDER BY hours DESC", (since,)) if _has(c, "dpr_delays") else []
    by_cause = {}
    for r in delays:
        g = by_cause.setdefault(r["category"] or "other", {"cause": r["category"] or "other", "hours": 0, "events": 0, "projects": set()})
        g["hours"] += r["hours"]
        g["events"] += r["n"]
        g["projects"].add(r["project"])
    tot = sum(g["hours"] for g in by_cause.values()) or 1
    causes, cum = [], 0
    for g in sorted(by_cause.values(), key=lambda x: -x["hours"]):
        cum += g["hours"]
        causes.append({"cause": g["cause"], "hours": r2(g["hours"]), "events": g["events"], "projects": len(g["projects"]),
                       "share_pct": round(100 * g["hours"] / tot, 1), "cumulative_pct": round(100 * cum / tot, 1)})
    prod = []
    if _has(c, "dpr_work") and _has(c, "activities"):
        for r in q(c, "SELECT a.id, a.code, a.name, a.unit, a.std_labour_prod std, p.code project, "
                      "(SELECT COALESCE(SUM(w.actual_qty),0) FROM dpr_work w JOIN dpr d ON d.id=w.dpr_id WHERE w.activity_id=a.id AND d.date>=?) qty, "
                      "(SELECT COALESCE(SUM(l.count*COALESCE(l.hours,8)),0) FROM dpr_labour l JOIN dpr d ON d.id=l.dpr_id WHERE l.activity_id=a.id AND d.date>=?) mh "
                      "FROM activities a JOIN projects p ON p.id=a.project_id", (since, since)):
            if r["qty"] and r["mh"]:
                actual = r["qty"] / r["mh"]
                prod.append({"project": r["project"], "activity": (r["code"] or "") + " " + r["name"], "unit": r["unit"],
                             "qty": r2(r["qty"]), "man_hours": r2(r["mh"]), "output_per_mh": round(actual, 4),
                             "standard": r["std"], "vs_standard_pct": round(100 * (actual / r["std"] - 1), 1) if r["std"] else None})
        prod.sort(key=lambda x: (x["vs_standard_pct"] is None, x["vs_standard_pct"] or 0))
    sqft = []
    for p in q(c, "SELECT id, code, name, status, built_area_sqft FROM projects WHERE COALESCE(built_area_sqft,0)>0"):
        cost = val(c, "SELECT COALESCE(SUM(l.debit-l.credit),0) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id "
                      "JOIN accounts ac ON ac.id=l.account_id WHERE l.project_id=? AND ac.type='expense' AND v.status IN ('posted','reversed')",
                   (p["id"],), 0) or 0
        sqft.append({"project": p["code"], "name": p["name"], "status": p["status"], "area_sqft": p["built_area_sqft"],
                     "cost": r2(cost), "cost_per_sqft": r2(cost / p["built_area_sqft"]) if cost else None})
    weather = []
    if _has(c, "dpr_delays"):
        wl = "COALESCE(d.weather_lost_hours,0)" if "weather_lost_hours" in _cols(c, "dpr") else "0"
        ld = "COALESCE(d.lost_day,0)" if "lost_day" in _cols(c, "dpr") else "0"
        for r in q(c, "SELECT substr(d.date,6,2) month, COUNT(*) dprs, SUM(%s) wl, SUM(CASE WHEN %s=1 THEN 1 ELSE 0 END) lost_days, "
                      "SUM((SELECT COALESCE(SUM(x.hours),0) FROM dpr_delays x WHERE x.dpr_id=d.id AND x.category='weather')) dh "
                      "FROM dpr d WHERE d.date>=? GROUP BY month ORDER BY month" % (wl, ld), (since,)):
            weather.append({"month": r["month"], "days": r["dprs"], "lost_hours": r2(max(r["wl"] or 0, r["dh"] or 0)),
                            "lost_days": r["lost_days"] or 0})
    return {"since": since, "delay_causes": causes, "productivity": prod[:200], "cost_per_sqft": sqft, "weather": weather}


# ───────────────────────── house & small job estimate ─────────────────────────
def _rate(c, code, book_id=None):
    if not _has(c, "res_pool"):
        return None, None
    rp = q1(c, "SELECT id, rate, unit FROM res_pool WHERE code=?", (code,))
    if not rp:
        return None, None
    bid = book_id or val(c, "SELECT id FROM rate_books WHERE is_default=1 ORDER BY id LIMIT 1", (), None)
    r = q1(c, "SELECT rate, source FROM res_rates WHERE book_id=? AND res_id=?", (bid, rp["id"])) if bid else None
    return ((r or {}).get("rate") or rp["rate"]), ((r or {}).get("source") or "resource pool")


@api("dc.house_estimate", "commercial", "view")
def house_estimate(c, u, a):
    p = _profile(c)
    area = num(a.get("plinth_sqft"))
    floors = num(a.get("floors")) or 1
    if area <= 0:
        raise ApiError("Enter the plinth (floor) area in sq ft.")
    q_ = a.get("quality") or "standard"
    rules = dict(HOUSE_RULES, **(p.get("house_rules") or {}))
    for k in rules:
        if a.get(k) not in (None, ""):
            rules[k] = num(a[k])
    shares = dict(HOUSE_SHARES.get(q_, HOUSE_SHARES["standard"]), **((p.get("house_shares") or {}).get(q_) or {}))
    for k in ("labour_pct", "finish_pct", "services_pct"):
        if a.get(k) not in (None, ""):
            shares[k] = num(a[k])
    built = area * floors
    if a.get("built_sqft"):
        built = num(a["built_sqft"])
    book = int(a["book_id"]) if a.get("book_id") else None
    lines = []

    def mat(name, code, qty, unit, conv=1.0):
        rate, src = _rate(c, code, book)
        amt = qty * conv * rate if rate else 0
        lines.append({"item": name, "qty": r2(qty), "unit": unit, "rate": r2(rate * conv) if rate else None,
                      "amount": r2(amt), "source": src or "no rate in the book"})
        return amt
    m = 0.0
    m += mat("Cement", "M-NRM-CEM", rules["cement_bag"] * built, "bag", 0.05)
    m += mat("Reinforcement steel", "M-NRM-ROD", rules["steel_kg"] * built, "kg", 0.001)
    m += mat("Bricks", "M-NRM-BRICK", rules["brick_no"] * built, "no")
    m += mat("Sand", "M-NRM-SAND", rules["sand_cft"] * built * CFT, "m3")
    m += mat("Aggregate", "M-NRM-AGG", rules["agg_cft"] * built * CFT, "m3")
    rest = 100 - shares["labour_pct"] - shares["finish_pct"] - shares["services_pct"]
    if rest <= 5:
        raise ApiError("Labour, finishing and services shares leave nothing for the structure.")
    total = m * 100.0 / rest
    for name, k in (("Labour (all trades)", "labour_pct"), ("Finishing: flooring, doors and windows, paint, railing", "finish_pct"),
                    ("Services: plumbing, sanitary, electrical", "services_pct")):
        lines.append({"item": name, "qty": None, "unit": "%.0f%% of total" % shares[k], "rate": None,
                      "amount": r2(total * shares[k] / 100.0), "source": "share of the total - set your own figure"})
    contingency = num(a.get("contingency_pct") if a.get("contingency_pct") not in (None, "") else 5)
    total_c = total * (1 + contingency / 100.0)
    stages = []
    st_list = p.get("house_stages") or HOUSE_STAGES
    for name, pct in st_list:
        stages.append({"stage": name, "pct": pct, "amount": r2(total_c * pct / 100.0)})
    own = [x for x in bench(c, u, {}).get("cost_per_sqft") or [] if x.get("cost_per_sqft")]
    own_avg = r2(sum(x["cost_per_sqft"] for x in own) / len(own)) if own else None
    clean = {k: v for k, v in a.items() if not str(k).startswith("_") and k != "save"}
    res = {"inputs": dict(clean, quality=q_, built_sqft=built, rules=rules, shares=shares), "lines": lines,
           "materials": r2(m), "total": r2(total), "contingency_pct": contingency, "total_with_contingency": r2(total_c),
           "per_sqft": r2(total_c / built), "stages": stages, "own_benchmark_per_sqft": own_avg, "own_jobs": len(own),
           "note": "Quick estimate, not a BOQ. Structural materials use rules of thumb per sq ft of built-up area "
                   "(cement %.2f bag, steel %.1f kg, bricks %.0f, sand %.1f cft, aggregate %.1f cft) priced from the rate "
                   "book; labour, finishing and services are shares of the total. Calibrate them against your own finished "
                   "houses (benchmark shown when projects have a built-up area)." % (rules["cement_bag"], rules["steel_kg"],
                                                                                   rules["brick_no"], rules["sand_cft"], rules["agg_cft"])}
    if a.get("save"):
        from core import require
        require(u, "commercial", "edit")
        no = "HE-%04d" % ((val(c, "SELECT COUNT(*) FROM house_estimates", (), 0) or 0) + 1)
        hid = ins(c, "house_estimates", {"no": no, "client": a.get("client"), "location": a.get("location"),
                                         "inputs": json.dumps(res["inputs"]), "result": json.dumps(res), "total": res["total_with_contingency"],
                                         "per_sqft": res["per_sqft"], "created_by": u["id"], "ts": now()})
        res["id"], res["no"] = hid, no
    return res


@api("dc.set_area", "commercial", "edit")
def set_area(c, u, a):
    """Built-up area of a building project, so its cost per sq ft becomes a benchmark."""
    pid = int(a["project_id"])
    upd(c, "projects", pid, {"built_area_sqft": num(a.get("area_sqft")) or None})
    return True


@api("dc.house_list", "commercial", "view")
def house_list(c, u, a):
    return q(c, "SELECT id, no, client, location, total, per_sqft, project_id, ts FROM house_estimates ORDER BY id DESC")


@api("dc.house_get", "commercial", "view")
def house_get(c, u, a):
    r = q1(c, "SELECT * FROM house_estimates WHERE id=?", (int(a["id"]),))
    if not r:
        raise ApiError("Estimate not found.")
    r["result"] = json.loads(r["result"] or "{}")
    return r


@api("dc.house_to_project", "commercial", "edit")
def house_to_project(c, u, a):
    """Turn an estimate into a project with one BOQ line per stage, so the house is billed by stage and its
    actual cost per sq ft becomes the next benchmark."""
    h = house_get(c, u, a)
    if h.get("project_id"):
        raise ApiError("This estimate is already a project.")
    code = (a.get("code") or "").strip().upper()
    if not code:
        raise ApiError("Give the project a short code.")
    if q1(c, "SELECT id FROM projects WHERE code=?", (code,)):
        raise ApiError("Project code %s exists." % code)
    r = h["result"]
    pid = ins(c, "projects", {"code": code, "name": a.get("name") or ("House - %s" % (h.get("client") or code)),
                              "client": h.get("client"), "location": h.get("location"),
                              "contract_value": r["total_with_contingency"], "start_date": a.get("start_date") or today(),
                              "end_date": a.get("end_date"), "status": "active", "built_area_sqft": r["inputs"]["built_sqft"]})
    try:
        from core import ensure_project_stores
        ensure_project_stores(c, pid)
    except Exception:
        pass
    for i, s in enumerate(r["stages"], 1):
        ins(c, "boq_items", {"project_id": pid, "code": "S%02d" % i, "description": s["stage"], "unit": "LS", "qty": 1,
                             "rate": s["amount"], "executed_qty": 0})
    upd(c, "house_estimates", h["id"], {"project_id": pid})
    audit(c, u, "house_to_project", "projects", pid, {"estimate": h["no"]})
    return {"project_id": pid, "code": code}
