"""BuildCore 2.55 "Management pack and fewer screens" (U6, A10, P2, optional hide list).

Nothing here posts, deletes or changes a figure.  It reads the screens that already exist and puts them together:
* Commercial > Monthly review pack: one page per project (position, margin trend, time, top alerts, cost
  completeness, cash for the next months, checks, decisions) and a company page that ranks the projects by risk.
  Decisions agreed at the review are kept (table pk_decisions) and come back on next month's page until closed.
* Accounts > Data health: one traffic light per area, from the checks that already exist (Integrity checks,
  financial data checks, the twelve project checks, programme check, cost completeness, backup, periods, alerts).
* Project control room: a "Time and site" panel (last DPR, DPRs waiting, forecast finish against completion,
  delays by responsibility, milestones and look-ahead).
* Simpler menu (Administration > Setup & switches): an optional list of duplicate or unused screens to take out of
  the menus.  OFF by default; the menu stays exactly as it is until an administrator turns it on.  A hidden screen
  is still there: its links and its address keep working, and it comes back when unticked.
"""
import json
from datetime import date, timedelta

import core
from core import ApiError, audit, ins, now, q, q1, setting, today, upd, val
import api_inventory as inv
from api_inventory import api

VERSION = "2.55.0"
FLAG = "_bco255"

SCHEMA = """
CREATE TABLE IF NOT EXISTS pk_decisions(id INTEGER PRIMARY KEY, project_id INTEGER, month TEXT NOT NULL, text TEXT NOT NULL,
  owner TEXT, due_date TEXT, status TEXT NOT NULL DEFAULT 'open', note TEXT, created_by INTEGER, created_at TEXT,
  closed_at TEXT, closed_by INTEGER);
CREATE INDEX IF NOT EXISTS ix_pk_dec ON pk_decisions(project_id, status);
"""

# route, label, group, why, "default" rule
HIDE_CANDIDATES = [
    ("dashboard/classic", "Classic dashboard", "Overview", "The dashboard of 2.48 shows the same figures, better grouped.", "yes"),
    ("approvals", "Approvals list", "Overview", "Action centre › Approvals lists the same items with owners and dates.", "yes"),
    ("inv/store", "Store by kind", "Store", "Stock on hand filters by store and kind.", "yes"),
    ("mg/stores", "Stock by segment", "Store", "Stock on hand and the segment reports show the same balances.", "yes"),
    ("ws/central", "Central store", "Store", "Stock on hand with the central store chosen.", "yes"),
    ("ws/inventory", "Stock by location", "Store", "Stock on hand by store.", "yes"),
    ("help", "Ask BuildCore (AI)", "Overview", "Needs an AI key; off on this company.", "ai_off"),
    ("copilot", "Copilot", "Overview", "Needs an AI key; off on this company.", "ai_off"),
    ("c/docs", "Contract documents (AI)", "Commercial", "Needs an AI key; the Document library keeps the papers.", "ai_off"),
    ("pl/register", "Plants (crusher, batching)", "Plant", "Side business: no records on this company.", "unused:plants"),
    ("pl/runs", "Production runs", "Plant", "Side business: no records on this company.", "unused:plant_runs"),
    ("pl/mix", "Mix designs", "Plant", "Side business: no records on this company.", "unused:mix_designs"),
    ("dc/house", "House & small job estimate", "Commercial", "Side business: no records on this company.", "unused:house_estimates"),
    ("proc/trade", "Trading sales", "Procurement", "Side business: no records on this company.", "unused:trade_moves"),
    ("fa/leases", "Leases (NFRS 16)", "Assets", "No leases on this company.", "unused:fa_leases"),
    ("x/pools", "Small asset pools", "Assets", "No pools on this company.", "unused:sa_pools"),
    ("admin/sync", "Site packs", "Administration", "Offline site packs: never used on this company.", "unused:site_packs"),
]


def _ai_on(c):
    try:
        r = q1(c, "SELECT value FROM ai_config WHERE key='provider'")
        p = r["value"] if r else ""
        if p == "local":
            return True
        k = q1(c, "SELECT value FROM ai_config WHERE key='key'")
        return p == "claude" and bool(k and k["value"])
    except Exception:
        return False


def _count(c, table):
    try:
        return val(c, "SELECT COUNT(*) FROM %s" % table) or 0
    except Exception:
        return 0


def _hide_list(c):
    try:
        return [x for x in json.loads(setting(c, "pk_hide") or "[]") if isinstance(x, str)]
    except ValueError:
        return []


def _is_admin(u):
    try:
        return core.can(u, "admin", "edit")
    except Exception:
        return False


def _set(c, key, value):
    c.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


@api("pk.menu")
def pk_menu(c, u, a):
    """What the menus leave out for everyone (empty while the simpler menu is off)."""
    on = setting(c, "pk_simple") == "1"
    return {"on": on, "hidden": _hide_list(c) if on else []}


@api("pk.menu_options", "admin", "view")
def pk_menu_options(c, u, a):
    ai = _ai_on(c)
    saved = _hide_list(c)
    first = setting(c, "pk_hide") is None
    rows = []
    for route, label, grp, why, rule in HIDE_CANDIDATES:
        n = None
        if rule == "yes":
            sugg = True
        elif rule == "ai_off":
            sugg = not ai
            if ai:
                why = "AI is set up on this company: keep it."
        else:
            n = _count(c, rule.split(":", 1)[1])
            sugg = n == 0
            if n:
                why = "%d record(s) on this company: keep it." % n
        rows.append({"route": route, "label": label, "group": grp, "why": why, "suggested": sugg, "records": n,
                     "hidden": (route in saved) if not first else sugg})
    return {"on": setting(c, "pk_simple") == "1", "rows": rows, "first": first,
            "note": "Nothing is deleted. A hidden screen keeps its data and its address, links to it keep working, and it comes back as soon as it is unticked or the simpler menu is turned off."}


@api("pk.menu_save", "admin", "edit")
def pk_menu_save(c, u, a):
    known = {r[0] for r in HIDE_CANDIDATES}
    if "hidden" in a:
        lst = [x for x in (a.get("hidden") or []) if x in known]
        _set(c, "pk_hide", json.dumps(lst))
    if "on" in a:
        _set(c, "pk_simple", "1" if a.get("on") in (1, "1", True) else "0")
    audit(c, u, "save", "settings", None, {"pk_simple": setting(c, "pk_simple"), "pk_hide": setting(c, "pk_hide")})
    return pk_menu(c, u, {})


# ───────────────────────── helpers ─────────────────────────
def _call(c, u, name, args):
    """Run an existing action as this user; a missing right comes back as None (the area says so)."""
    f, module, action, _public = inv.FUNCS[name]
    if module:
        try:
            core.require(u, module, action)
        except Exception:
            return None
    try:
        return f(c, u, dict(args))
    except ApiError:
        return None


def _active(c, u):
    rows = q(c, "SELECT id, code, name FROM projects WHERE status='active' AND COALESCE(kind,'project') NOT IN ('trading','general') ORDER BY code")
    try:
        import api_workspace
        allow = api_workspace.allowed_projects(c, u) if hasattr(api_workspace, "allowed_projects") else None
    except Exception:
        allow = None
    if allow is not None:
        rows = [r for r in rows if r["id"] in allow]
    return rows


def _check_project(c, u, pid):
    p = q1(c, "SELECT * FROM projects WHERE id=?", (pid,))
    if not p:
        raise ApiError("Project not found.")
    if pid not in {r["id"] for r in _active(c, u)} and not _is_admin(u):
        try:
            import api_workspace
            if hasattr(api_workspace, "allowed_projects"):
                al = api_workspace.allowed_projects(c, u)
                if al is not None and pid not in al:
                    raise ApiError("You are not on the team of this project.")
        except ApiError:
            raise
        except Exception:
            pass
    return p


def _light(worst):
    return {0: "green", 1: "amber", 2: "red"}.get(worst, "grey")


def _month_end(m):
    y, mo = int(m[:4]), int(m[5:7])
    nxt = date(y + (mo == 12), 1 if mo == 12 else mo + 1, 1)
    return (nxt - timedelta(days=1)).isoformat()


def _prev_month(m):
    y, mo = int(m[:4]), int(m[5:7])
    return "%04d-%02d" % (y - (mo == 1), 12 if mo == 1 else mo - 1)


def _snap(c, pid, upto):
    try:
        return q1(c, "SELECT * FROM wn_snapshots WHERE project_id=? AND day<=? ORDER BY day DESC LIMIT 1", (pid, upto))
    except Exception:
        return None


def _time(c, pid):
    pr = q1(c, "SELECT * FROM projects WHERE id=?", (pid,))
    out = {"completion": None, "finish": None, "late_days": None, "ld": None, "data_date": None}
    try:
        import api_sched
        cd = api_sched.contract_dates(c, pr)
        out["completion"] = cd.get("revised") or cd.get("original")
        run = q1(c, "SELECT * FROM sched_runs WHERE project_id=? ORDER BY id DESC LIMIT 1", (pid,))
        if run:
            out["finish"], out["data_date"] = run["finish"], run["data_date"]
        if out["finish"] and out["completion"]:
            out["late_days"] = (date.fromisoformat(out["finish"][:10]) - date.fromisoformat(out["completion"][:10])).days
            if out["late_days"] > 0:
                out["ld"] = (api_sched.ld_exposure(c, pr, out["finish"], cd) or {}).get("amount")
    except Exception:
        pass
    return out


def _alerts(c, pid, n=8):
    try:
        return q(c, "SELECT id, kind, title, severity, amount, status, target_date, first_seen FROM fcc_alerts WHERE project_id=? "
                    "AND status NOT IN ('closed','resolved','dismissed') AND present=1 "
                    "ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, COALESCE(amount,0) DESC LIMIT ?",
                 (pid, n))
    except Exception:
        return []


def _score(c, pid):
    try:
        import api_allcost
        s = api_allcost.score(c, pid)
        return {"score": s["score"], "missing_total": s["missing_total"],
                "weakest": [x["label"] for x in sorted(s["parts"], key=lambda x: x["points"] - x["weight"]) if not x["ok"]][:3]}
    except Exception:
        return {"score": None, "missing_total": None, "weakest": []}


def _complete(c, pid, pos):
    try:
        import api_fcast
        d = api_fcast.additions(c, pid, None, pos)
        return {"add_cost": d.get("add_cost"), "eac": d["after"]["eac"], "profit": d["after"]["profit"], "margin_pct": d["after"]["margin_pct"]}
    except Exception:
        return None


def _risk(r):
    pts, why = 0, []
    m, bid = r.get("margin_pct"), r.get("bid_margin_pct")
    if m is not None and m < 0:
        pts += 30; why.append("loss forecast")
    elif m is not None and bid is not None and m < bid:
        pts += 15; why.append("margin below bid")
    if r.get("margin_change") is not None and r["margin_change"] <= -3:
        pts += 15; why.append("margin fell %.1f pts" % -r["margin_change"])
    ld = r.get("late_days")
    if ld is not None and ld > 0:
        pts += 25 if ld > 60 else 20; why.append("%d days late" % ld)
    if r.get("high_alerts"):
        pts += min(20, 5 * r["high_alerts"]); why.append("%d high alerts" % r["high_alerts"])
    s = r.get("score")
    if s is not None and s < 60:
        pts += 15; why.append("cost incomplete (%d)" % s)
    elif s is not None and s < 80:
        pts += 8; why.append("cost partly incomplete (%d)" % s)
    return min(100, pts), why


def _project_row(c, pid, month):
    import api_pfp
    p = q1(c, "SELECT id, code, name, contract_value FROM projects WHERE id=?", (pid,))
    end = _month_end(month)
    t = today()
    asof = min(end, t)
    pos = api_pfp.position(c, pid, asof)
    f = pos["forecast"]
    prev = _snap(c, pid, _month_end(_prev_month(month)))
    tm = _time(c, pid)
    al = _alerts(c, pid, 50)
    sc = _score(c, pid)
    row = {"project_id": pid, "code": p["code"], "name": p["name"], "contract_value": pos["project"].get("contract_value"),
           "as_of": asof, "cost": pos["cost"]["total"], "certified": pos["value"]["certified"], "earned": pos["value"]["earned"],
           "eac": f["eac"], "value": f["value"], "profit": f["profit"], "margin_pct": f["margin_pct"], "bid_margin_pct": f.get("bid_margin_pct"),
           "margin_to_date": pos["margin"]["certified_pct"], "prev_margin": prev["margin"] if prev else None, "prev_day": prev["day"] if prev else None,
           "margin_change": round(f["margin_pct"] - prev["margin"], 1) if prev and prev["margin"] is not None and f["margin_pct"] is not None else None,
           "late_days": tm["late_days"], "finish": tm["finish"], "completion": tm["completion"], "ld": tm["ld"],
           "high_alerts": sum(1 for x in al if x["severity"] in ("high", "critical")), "alerts": len(al),
           "score": sc["score"], "missing_total": sc["missing_total"]}
    row["risk"], row["risk_why"] = _risk(row)
    return row, pos, tm, al, sc


# ───────────────────────── monthly review pack ─────────────────────────
@api("pk.review", "project", "view")
def pk_review(c, u, a):
    pid = int(a.get("project_id") or 0)
    if not pid:
        raise ApiError("Choose a project.")
    _check_project(c, u, pid)
    month = (a.get("month") or today()[:7])[:7]
    row, pos, tm, al, sc = _project_row(c, pid, month)
    start = month + "-01"
    end = _month_end(month)
    trend = []
    try:
        trend = q(c, "SELECT substr(day,1,7) month, MAX(day) day FROM wn_snapshots WHERE project_id=? GROUP BY substr(day,1,7) ORDER BY 1 DESC LIMIT 12", (pid,))
        trend = [dict(q1(c, "SELECT day, cost, eac, value, profit, margin, margin_to_date, finish FROM wn_snapshots WHERE project_id=? AND day=?", (pid, r["day"])))
                 for r in reversed(trend)]
    except Exception:
        trend = []
    dprs = val(c, "SELECT COUNT(*) FROM dpr WHERE project_id=? AND date BETWEEN ? AND ?", (pid, start, end)) or 0
    dprs_ok = val(c, "SELECT COUNT(*) FROM dpr WHERE project_id=? AND date BETWEEN ? AND ? AND status='approved'", (pid, start, end)) or 0
    delays = q(c, "SELECT COALESCE(NULLIF(d.responsibility,''),'not given') who, ROUND(SUM(d.hours),1) hours, COUNT(*) n FROM dpr_delays d JOIN dpr r ON r.id=d.dpr_id "
                  "WHERE r.project_id=? AND r.date BETWEEN ? AND ? GROUP BY 1 ORDER BY 2 DESC", (pid, start, end))
    cash = None
    cp = _call(c, u, "cash.project", {"project_id": pid})
    if cp:
        rows = [r for r in cp.get("rows", []) if r["month"] >= month][:6]
        cash = {"rows": [{k: r.get(k) for k in ("month", "in", "out", "net", "cumulative")} for r in rows],
                "peak_cash": cp.get("peak_cash"), "peak_month": cp.get("peak_month"),
                "retention_held": cp.get("retention_held"), "advance_outstanding": cp.get("advance_outstanding")}
    checks = None
    ck = _call(c, u, "cl.checks", {"project_id": pid})
    if ck:
        fails = [x for x in ck["checks"] if x.get("result") not in ("pass", "na", "n/a", "skip")]
        checks = {"total": len(ck["checks"]), "fails": [{"name": x["name"], "blocking": x.get("blocking"), "detail": x.get("detail")} for x in fails]}
    flags = {}
    for fl in pos.get("flags") or []:
        flags[fl["key"]] = flags.get(fl["key"], 0) + 1
    worst = []
    for it in (pos["forecast"].get("items") or []):
        try:
            v = it.get("forecast_margin")
            if v is not None and v < 0:
                worst.append({"code": it.get("code"), "name": it.get("name"), "basis": it.get("basis"), "eac": it.get("eac"),
                              "value": it.get("forecast_value"), "loss": round(v, 2)})
        except Exception:
            pass
    worst = sorted(worst, key=lambda x: x["loss"])[:6]
    decisions = q(c, "SELECT * FROM pk_decisions WHERE project_id=? AND (month=? OR (status='open' AND month<?)) ORDER BY status DESC, due_date, id",
                  (pid, month, month))
    return {"month": month, "row": row, "position": {k: pos[k] for k in ("cost", "value", "margin")},
            "forecast": {k: pos["forecast"].get(k) for k in ("cost_to_complete", "eac", "value", "profit", "margin_pct", "bid_margin_pct")},
            "complete": _complete(c, pid, pos), "trend": trend, "time": tm, "dprs": dprs, "dprs_approved": dprs_ok, "delays": delays,
            "alerts": al[:8], "score": sc, "cash": cash, "checks": checks, "flags": flags, "worst_items": worst, "decisions": decisions,
            "can_edit": core.can(u, "project", "edit")}


@api("pk.company", "project", "view")
def pk_company(c, u, a):
    month = (a.get("month") or today()[:7])[:7]
    rows, errors = [], []
    for p in _active(c, u)[:80]:
        try:
            rows.append(_project_row(c, p["id"], month)[0])
        except Exception as e:
            errors.append("%s: %s" % (p["code"], str(e)[:120]))
    rows.sort(key=lambda r: (-r["risk"], r["code"]))
    tot = {k: round(sum((r.get(k) or 0) for r in rows), 2) for k in ("contract_value", "cost", "certified", "eac", "value", "profit", "missing_total")}
    tot["margin_pct"] = round(tot["profit"] / tot["value"] * 100, 1) if tot["value"] else None
    cash = None
    cf = _call(c, u, "cfw.forecast", {})
    if cf:
        cash = {k: cf.get(k) for k in ("opening", "lowest", "first_gap", "max_gap", "prudent_first_gap", "prudent_lowest")}
        cash["weeks"] = [{k: w.get(k) for k in ("week", "start", "in", "out", "closing", "gap")} for w in cf.get("weeks", [])[:13]]
    open_dec = q(c, "SELECT d.*, p.code FROM pk_decisions d LEFT JOIN projects p ON p.id=d.project_id WHERE d.status='open' ORDER BY d.due_date, d.id LIMIT 100")
    return {"month": month, "rows": rows, "total": tot, "cash": cash, "decisions": open_dec, "errors": errors}


@api("pk.decision_save", "project", "edit")
def pk_decision_save(c, u, a):
    text = (a.get("text") or "").strip()
    if a.get("id"):
        d = q1(c, "SELECT * FROM pk_decisions WHERE id=?", (int(a["id"]),))
        if not d:
            raise ApiError("Decision not found.")
        ch = {}
        for k in ("text", "owner", "due_date", "note"):
            if k in a:
                ch[k] = (a.get(k) or "").strip() or None
        if a.get("status") in ("open", "done", "dropped") and a["status"] != d["status"]:
            ch["status"] = a["status"]
            ch["closed_at"] = now() if a["status"] != "open" else None
            ch["closed_by"] = u["id"] if a["status"] != "open" else None
        if "text" in ch and not ch["text"]:
            raise ApiError("Write the decision.")
        if ch:
            upd(c, "pk_decisions", d["id"], ch)
            audit(c, u, "edit", "pk_decisions", d["id"], ch)
        return {"id": d["id"]}
    if not text:
        raise ApiError("Write the decision.")
    pid = int(a.get("project_id") or 0) or None
    if pid:
        _check_project(c, u, pid)
    i = ins(c, "pk_decisions", {"project_id": pid, "month": (a.get("month") or today()[:7])[:7], "text": text,
                                "owner": (a.get("owner") or "").strip() or None, "due_date": a.get("due_date") or None, "status": "open",
                                "created_by": u["id"], "created_at": now()})
    audit(c, u, "create", "pk_decisions", i, {"text": text, "project_id": pid})
    return {"id": i}


# ───────────────────────── data health ─────────────────────────
@api("pk.health")
def pk_health(c, u, a):
    areas = []

    def area(key, label, worst, summary, link, rows=None, cols=None):
        areas.append({"key": key, "label": label, "light": _light(worst), "summary": summary, "link": link, "rows": rows or [], "cols": cols or []})

    def noaccess(key, label, link, need):
        areas.append({"key": key, "label": label, "light": "grey", "summary": "You do not have the right to see this (%s)." % need, "link": link, "rows": [], "cols": []})

    r = _call(c, u, "rep.integrity", {})
    if r is None:
        noaccess("integrity", "Integrity checks", "acc/integrity", "accounts view")
    else:
        lst = r if isinstance(r, list) else r.get("checks", [])
        bad = [x for x in lst if not x["ok"]]
        area("integrity", "Integrity checks", 2 if bad else 0, "%d of %d checks pass" % (len(lst) - len(bad), len(lst)),
             "acc/integrity", [{"check": x["check"], "detail": x["detail"]} for x in bad], ["check", "detail"])
    r = _call(c, u, "fc.checks", {})
    if r is None:
        noaccess("fin", "Financial data checks", "acc/integrity", "accounts view")
    else:
        by = {}
        for x in r["checks"]:
            by.setdefault(x["area"], []).append(x)
        for ar, lst in by.items():
            bad = [x for x in lst if not x["ok"]]
            worst = 2 if any(x["severity"] == "error" for x in bad) else 1 if bad else 0
            area("fin:" + ar, ar, worst, "%d of %d checks pass" % (len(lst) - len(bad), len(lst)), "acc/integrity",
                 [{"check": x["check"], "detail": x["detail"], "count": x.get("count"), "fix": x.get("fix")} for x in bad], ["check", "detail", "count", "fix"])
    projects = _active(c, u)[:40]
    if core.can(u, "project", "view"):
        rows, worst = [], 0
        prow, pworst = [], 0
        srow, sworst = [], 0
        for p in projects:
            ck = _call(c, u, "cl.checks", {"project_id": p["id"]})
            if ck:
                fails = [x for x in ck["checks"] if x.get("result") == "fail"]
                blk = [x for x in fails if x.get("blocking")]
                w = 2 if blk else 1 if fails else 0
                worst = max(worst, w)
                rows.append({"project": p["code"], "light": _light(w), "detail": "; ".join(x["name"] for x in fails) or "All pass"})
            pc = _call(c, u, "prog.check", {"project_id": p["id"]}) if "prog.check" in inv.FUNCS else None
            if pc and pc.get("activities"):
                w = 0 if pc["passed"] == pc["total"] else 1
                pworst = max(pworst, w)
                prow.append({"project": p["code"], "light": _light(w), "detail": "%d of %d checks pass, %d activities" % (pc["passed"], pc["total"], pc["activities"])})
            elif pc is not None:
                prow.append({"project": p["code"], "light": "grey", "detail": "No programme"})
            s = _score(c, p["id"])["score"]
            if s is not None:
                w = 0 if s >= 80 else 1 if s >= 60 else 2
                sworst = max(sworst, w)
                srow.append({"project": p["code"], "light": _light(w), "detail": "Score %d of 100" % s})
        area("project", "Project checks (twelve per project)", worst if rows else -1,
             "%d project(s), %d with a failing check" % (len(rows), sum(1 for x in rows if x["light"] != "green")), "cl/close", rows, ["project", "light", "detail"])
        area("prog", "Programme", pworst if any(x["light"] != "grey" for x in prow) else -1,
             "%d project(s) with a programme" % sum(1 for x in prow if x["light"] != "grey"), "p/schedule", prow, ["project", "light", "detail"])
        area("cost", "Cost completeness", sworst if srow else -1, "%d project(s) scored" % len(srow), "cl/cvr", srow, ["project", "light", "detail"])
    try:
        import api_safe
        if _is_admin(u):
            b = api_safe.backup_health(c)
            area("backup", "Backup and attached files", 0 if b["ok"] else 2, "All good" if b["ok"] else "; ".join(b["warnings"][:3]), "admin/backup",
                 [{"detail": w} for w in b["warnings"]], ["detail"])
        pc = api_safe.period_check(c)
        area("periods", "Accounting periods", 1 if pc else 0, "%d period(s) with dates that differ from the calendar" % len(pc) if pc else "Dates agree with the calendar",
             "admin/setup", [{"check": "%s %s" % (x["fy"], x["code"]), "detail": "%s – %s, should be %s – %s" % (x["start"], x["end"], x["true_start"], x["true_end"])} for x in pc], ["check", "detail"])
    except Exception:
        pass
    try:
        ids = [p["id"] for p in projects]
        hi = val(c, "SELECT COUNT(*) FROM fcc_alerts WHERE status NOT IN ('closed','resolved','dismissed') AND present=1 AND severity IN ('high','critical')") or 0
        od = val(c, "SELECT COUNT(*) FROM fcc_alerts WHERE status NOT IN ('closed','resolved','dismissed') AND present=1 AND target_date IS NOT NULL AND target_date<?", (today(),)) or 0
        area("alerts", "Alerts", 2 if od else 1 if hi else 0, "%d high alert(s) open, %d past their target date" % (hi, od), "action?tab=1")
    except Exception:
        pass
    order = {"red": 0, "amber": 1, "grey": 3, "green": 2}
    return {"areas": areas, "red": sum(1 for x in areas if x["light"] == "red"), "amber": sum(1 for x in areas if x["light"] == "amber"),
            "green": sum(1 for x in areas if x["light"] == "green"), "as_of": now()}


# ───────────────────────── time and site panel (control room) ─────────────────────────
@api("pk.site", "project", "view")
def pk_site(c, u, a):
    pid = int(a.get("project_id") or 0)
    if not pid:
        raise ApiError("Choose a project.")
    _check_project(c, u, pid)
    t = today()
    d7 = (date.fromisoformat(t) - timedelta(days=7)).isoformat()
    d30 = (date.fromisoformat(t) - timedelta(days=30)).isoformat()
    last = q1(c, "SELECT date, status FROM dpr WHERE project_id=? ORDER BY date DESC LIMIT 1", (pid,))
    out = {"today": t, "last_dpr": last["date"] if last else None, "last_dpr_status": last["status"] if last else None,
           "dpr_7": val(c, "SELECT COUNT(DISTINCT date) FROM dpr WHERE project_id=? AND date>?", (pid, d7)) or 0,
           "dpr_30": val(c, "SELECT COUNT(DISTINCT date) FROM dpr WHERE project_id=? AND date>?", (pid, d30)) or 0,
           "dpr_waiting": val(c, "SELECT COUNT(*) FROM dpr WHERE project_id=? AND status NOT IN ('approved','void','rejected')", (pid,)) or 0,
           "time": _time(c, pid)}
    out["delays"] = q(c, "SELECT COALESCE(NULLIF(d.responsibility,''),'not given') who, ROUND(SUM(d.hours),1) hours, COUNT(*) n FROM dpr_delays d "
                         "JOIN dpr r ON r.id=d.dpr_id WHERE r.project_id=? AND r.date>? GROUP BY 1 ORDER BY 2 DESC", (pid, d30))
    try:
        out["issues"] = val(c, "SELECT COUNT(*) FROM fld_issues WHERE project_id=? AND status NOT IN ('closed','void')", (pid,)) or 0
    except Exception:
        out["issues"] = None
    try:
        out["milestones"] = q(c, "SELECT m.name, m.due_date, a.ef forecast, a.actual_finish FROM contract_milestones m LEFT JOIN activities a ON a.id=m.activity_id "
                                 "WHERE m.project_id=? AND m.due_date IS NOT NULL AND a.actual_finish IS NULL AND m.due_date<=? ORDER BY m.due_date LIMIT 8",
                              (pid, (date.fromisoformat(t) + timedelta(days=60)).isoformat()))
    except Exception:
        out["milestones"] = []
    try:
        ws = (date.fromisoformat(t) - timedelta(days=date.fromisoformat(t).weekday())).isoformat()
        la = q1(c, "SELECT COUNT(*) n, SUM(CASE WHEN done=1 THEN 1 ELSE 0 END) done FROM lookahead WHERE project_id=? AND week_start=?", (pid, ws))
        out["lookahead"] = {"week": ws, "planned": la["n"] or 0, "done": la["done"] or 0}
    except Exception:
        out["lookahead"] = None
    try:
        out["acts_due"] = val(c, "SELECT COUNT(*) FROM activities WHERE project_id=? AND actual_finish IS NULL AND ef IS NOT NULL AND ef<=?",
                              (pid, (date.fromisoformat(t) + timedelta(days=14)).isoformat())) or 0
        out["acts_late"] = val(c, "SELECT COUNT(*) FROM activities WHERE project_id=? AND actual_finish IS NULL AND ef IS NOT NULL AND ef<?", (pid, t)) or 0
    except Exception:
        out["acts_due"] = out["acts_late"] = None
    return out


# ───────────────────────── start-up ─────────────────────────
def init_pack(c):
    c.executescript(SCHEMA)
    if not q1(c, "SELECT 1 FROM settings WHERE key='pk_simple'"):
        c.execute("INSERT INTO settings(key, value) VALUES('pk_simple', '0')")   # off on every company until an admin turns it on
    c.commit()
    try:
        import api_safe
        if "pk_simple" not in {s[0] for s in getattr(api_safe, "SWITCHES", [])}:
            api_safe.SWITCHES.append(("pk_simple", "Simpler menu (2.55)", "Takes chosen duplicate or unused screens out of the menus. Nothing is deleted.",
                                      lambda v: v == "1", "#/admin/setup", "admin", 9))
    except Exception:
        pass
