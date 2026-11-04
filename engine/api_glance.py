"""BuildCore 2.48.0 - A dashboard that informs.

Found on SULAV's home screen (2.47.0): "Decisions this week" was six near-identical lines
"ACT NOW  Send notice: Equipment breakdown delay (DPR/2026-27/000x) - Notice due ... after that the claim may be
time-barred", and the tiles said "Not available" / "BOQ != contract" without saying what to do.

Why the lines came:
  * Every DPR delay line with "make an event" ticked becomes a delay event (2.21), and every new delay event gets a
    contract notice deadline = DPR date + notice days (28) (2.3 roadmap rule in api_sched.reg_save), whatever the cause.
  * The 2.18 dashboard listed every open event whose notice deadline is within 7 days - including deadlines long
    passed - one line each, as "critical" = "Act now".
  * An equipment breakdown, a material or labour shortage is the contractor's own risk (2.21 CAT_RESP): there is
    nobody to send a contract notice to. Those lines were noise, and a passed deadline is not "act now" either.

What 2.48 does (display only; nothing is posted, no row is changed or deleted):
  * Contract notices: only events that are the employer's, neutral or concurrent (by the responsibility set on the
    event or its DPR delay line, else by the delay category) and whose notice is not marked sent. Due in the next
    7 days -> "This week: send the notice"; deadline already passed -> one "Review" line per project with the count.
    Own delays (equipment breakdown, shortages) are never notice lines; the dashboard counts them under the site.
  * Repeated lines of the same kind are grouped into one line with a count (notices, material orders, overdue
    suppliers, risks, collections); the line opens to show each one.
  * Project health (commercial) and the Action centre use the same notice rule.
  * glance.month: this month (Nepali or English) at a glance - DPRs and days reported, workers, work reported in
    money, machine hours worked / idle / breakdown, delay hours by who is responsible, cash and bank, billed,
    received, paid, receivable and payable with what is overdue, stock, deliveries awaited, approvals waiting,
    and one row per project.
Switch gl_on (default on, every company: it changes what the dashboard shows, not any figure); gl_on = 0 gives the
2.47 dashboard and notice lines back. Setting gl_month = bs | ad picks the default month.
"""
from datetime import date, timedelta

import core
from core import ApiError, q, q1, r2, setting, today, val
import api_inventory as inv
from api_inventory import api

VERSION = "2.48.0"
FLAG = "_bco248"
EPS = 0.005

CAT_LABEL = {"weather": "Weather", "geology": "Ground / geology", "access": "Site access", "drawing": "Drawings late",
             "consultant_instruction": "Consultant instruction", "employer_instruction": "Employer instruction",
             "equipment_breakdown": "Equipment breakdown", "material_shortage": "Material shortage",
             "labour_shortage": "Labour shortage", "other": "Other"}
RESP_LABEL = {"employer": "Employer's", "contractor": "Own", "neutral": "Neutral", "concurrent": "Concurrent"}


def _f(x, d=0.0):
    try:
        return float(x) if x not in (None, "") else d
    except (TypeError, ValueError):
        return d


def _has(c, t):
    return bool(val(c, "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (t,)))


def _cols(c, t):
    return {r[1] for r in c.execute("PRAGMA table_info(%s)" % t)}


def on(c):
    return (setting(c, "gl_on") or "1") != "0"


def _cat_resp():
    try:
        import api_exec
        return dict(api_exec.CAT_RESP)
    except Exception:
        return {"weather": "neutral", "geology": "neutral", "access": "employer", "drawing": "employer",
                "consultant_instruction": "employer", "employer_instruction": "employer",
                "equipment_breakdown": "contractor", "material_shortage": "contractor",
                "labour_shortage": "contractor", "other": "contractor"}


# ───────────────────────── who is responsible for an event ─────────────────────────
def responsibility(c, e, _dd=None):
    """employer / contractor / neutral / concurrent, or None when nobody said and nothing tells."""
    r = (e.get("responsibility") or "").strip().lower()
    if r:
        return r
    if e.get("compensable") == 1:
        return "employer"
    if e.get("concurrent") == 1:
        return "concurrent"
    if e.get("excusable") == 1:
        return "neutral"
    dd = _dd.get(e["id"]) if _dd is not None else (
        q1(c, "SELECT * FROM dpr_delays WHERE event_id=? ORDER BY id LIMIT 1", (e["id"],)) if _has(c, "dpr_delays") else None)
    if dd:
        rr = (dd.get("responsibility") or "").strip().lower() if "responsibility" in dd else ""
        return rr or _cat_resp().get(dd.get("category") or "", "contractor")
    # an event typed from a DPR delay whose line is gone: read the category back from its title
    if e.get("dpr_id") and " delay (" in (e.get("title") or ""):
        cat = (e["title"].split(" delay (")[0] or "").strip().lower().replace(" ", "_")
        if cat in _cat_resp():
            return _cat_resp()[cat]
    return None


def open_notices(c, pid=None):
    """Open events that carry a notice deadline and no 'notice sent' date, each with its responsibility and whether a
    contract notice is needed (not for the contractor's own delays)."""
    cols = _cols(c, "events")
    cond = ["status='open'", "notice_deadline IS NOT NULL", "notice_deadline<>''"]
    if "notice_sent" in cols:
        cond.append("(notice_sent IS NULL OR notice_sent='')")
    sql = "SELECT * FROM events WHERE " + " AND ".join(cond) + (" AND project_id=%d" % int(pid) if pid else "") + " ORDER BY notice_deadline"
    rows = q(c, sql)
    dd = {}
    if rows and _has(c, "dpr_delays"):
        for x in q(c, "SELECT * FROM dpr_delays WHERE event_id IN (%s) ORDER BY id DESC" % ",".join(str(int(r["id"])) for r in rows)):
            dd[x["event_id"]] = x
    for r in rows:
        r["resp"] = responsibility(c, r, dd)
        r["notice_needed"] = r["resp"] != "contractor"
    return rows


# ───────────────────────── Decisions: notices by the rule, repeats grouped ─────────────────────────
SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "info": 3}


def _fmt(x):
    try:
        import api_insight
        return api_insight.fmt(x)
    except Exception:
        return "{:,.0f}".format(_f(x))


def notice_lines(c, u, pid=None):
    """The contract-notice lines of the dashboard, one per project and state."""
    if not core.can(u, "project", "view"):
        return []
    t = today()
    soon = (date.today() + timedelta(days=7)).isoformat()
    codes = {r["id"]: r["code"] for r in q(c, "SELECT id, code FROM projects")}
    groups = {}
    for e in open_notices(c, pid):
        if not e["notice_needed"]:
            continue
        d = e["notice_deadline"]
        if d > soon:
            continue
        state = "passed" if d < t else "due"
        groups.setdefault((e["project_id"], state), []).append(e)
    out = []
    for (p, state), evs in sorted(groups.items(), key=lambda x: (x[0][1] != "due", x[1][0]["notice_deadline"])):
        code = codes.get(p, "")
        subs = [{"severity": "high" if state == "due" else "medium", "kind": "contract", "title": "%s %s" % (e["no"] or "", e["title"] or ""),
                 "why": "Notice %s %s%s - %s event." % ("due" if state == "due" else "deadline was", e["notice_deadline"],
                                                        (" (clause %s)" % e["clause"]) if e.get("clause") else "",
                                                        RESP_LABEL.get(e["resp"], "Unclassified") if e["resp"] else "unclassified"),
                 "link": "#/p/events", "impact": r2(e["cost_impact"]) if _f(e.get("cost_impact")) else None,
                 "project_id": p, "action": "Open"} for e in evs]
        n = len(evs)
        imp = sum(_f(e.get("cost_impact")) for e in evs) or None
        if state == "due":
            title = ("Send the contract notice for %s" % evs[0]["title"]) if n == 1 else ("Send %d contract notices on %s" % (n, code))
            why = "Due %s%s. These events are the employer's or neutral, so a notice keeps the time and cost claim open." % (
                evs[0]["notice_deadline"], (" to %s" % evs[-1]["notice_deadline"]) if n > 1 and evs[-1]["notice_deadline"] != evs[0]["notice_deadline"] else "")
            sev, act = "high", "Write the notice"
        else:
            title = ("%s: notice deadline passed for %s" % (code, evs[0]["title"])) if n == 1 else \
                ("%s: %d notice deadlines passed" % (code, n))
            why = "Deadline%s %s%s. If the notice was sent, mark it sent; if no notice is needed, set the delay as own." % (
                "s" if n > 1 else "", evs[0]["notice_deadline"],
                (" to %s" % evs[-1]["notice_deadline"]) if n > 1 and evs[-1]["notice_deadline"] != evs[0]["notice_deadline"] else "")
            sev, act = "medium", "Check notices"
        line = {"severity": sev, "kind": "contract", "title": title, "why": why, "link": "#/p/events",
                "impact": r2(imp) if imp else None, "project_id": p, "action": act, "count": n}
        if n > 1:
            line["items"] = subs
        out.append(line)
    return out


def _group(items, key, make, min_n=2):
    """Replace items that share key(x) (when there are min_n or more) by one line from make(list)."""
    buckets, order = {}, []
    for x in items:
        k = key(x)
        if k is None:
            order.append(("one", x))
            continue
        if k not in buckets:
            buckets[k] = []
            order.append(("grp", k))
        buckets[k].append(x)
    out = []
    for kind, v in order:
        if kind == "one":
            out.append(v)
        elif len(buckets[v]) >= min_n:
            out.append(make(buckets[v]))
        else:
            out.extend(buckets[v])
    return out


def _worst(xs):
    return min((x["severity"] for x in xs), key=lambda s: SEV_ORDER.get(s, 9))


def group_lines(items, codes):
    def mk(title, why, xs, action, link=None, pid=None):
        imp = sum(_f(x.get("impact")) for x in xs) or None
        return {"severity": _worst(xs), "kind": xs[0]["kind"], "title": title, "why": why, "link": link or xs[0]["link"],
                "impact": r2(imp) if imp else None, "project_id": pid, "action": action, "count": len(xs), "items": xs}
    # material orders, per project
    items = _group(items, lambda x: ("order", x.get("project_id")) if x["kind"] == "supply" and x["title"].startswith("Order ") else None,
                   lambda xs: mk("Order %d materials for %s" % (len(xs), codes.get(xs[0].get("project_id"), "")),
                                 "Stock will not last until the next delivery: " + ", ".join(x["title"][6:].rsplit(" for ", 1)[0] for x in xs[:6]) + ".",
                                 xs, "Raise PRs", pid=xs[0].get("project_id")))
    items = _group(items, lambda x: "supp" if x["kind"] == "supply" and x["title"].startswith("Overdue to ") else None,
                   lambda xs: mk("%d suppliers are overdue: %s" % (len(xs), _fmt(sum(_f(x.get("impact")) for x in xs))),
                                 ", ".join(x["title"][11:].split(":")[0] for x in xs[:5]) + ". Deliveries may stop.", xs, "Plan payment"), min_n=3)
    items = _group(items, lambda x: "coll" if x["kind"] == "cash" and x["title"].startswith("Collect ") else None,
                   lambda xs: mk("Collect %s from %d clients" % (_fmt(sum(_f(x.get("impact")) for x in xs)), len(xs)),
                                 "Overdue client bills. Largest: " + xs[0]["title"][8:] + ".", xs, "Chase payment", "#/acc/ageing"), min_n=3)
    items = _group(items, lambda x: "risk" if x["kind"] == "risk" else None,
                   lambda xs: mk("%d risks need action" % len(xs), "High score or the action date has passed: " + "; ".join(x["title"][5:] for x in xs[:3]) + ".",
                                 xs, "Open the register", "#/risks"), min_n=3)
    return items


def _decisions_w(orig):
    def decisions(c, u, rows, cash, pid=None):
        out = orig(c, u, rows, cash, pid)
        try:
            if not on(c):
                return out
            out = [x for x in out if not (x.get("kind") == "contract" and (x.get("title") or "").startswith("Send notice: "))]
            out += notice_lines(c, u, pid)
            codes = {r["id"]: r["code"] for r in q(c, "SELECT id, code FROM projects")}
            out = group_lines(out, codes)
            out.sort(key=lambda x: (SEV_ORDER.get(x["severity"], 9), -(x.get("impact") or 0)))
        except Exception as e:  # the old list rather than no list
            print("BuildCore 2.48: decisions kept as before: %s" % e)
        return out
    setattr(decisions, FLAG, True)
    decisions._orig = orig
    return decisions


def _health_w(orig):
    """Commercial health: the same notice rule (own delays never; passed deadlines are 'attention', not 'critical')."""
    def health(c, pid, asof=None, *a, **k):
        res = orig(c, pid, asof, *a, **k)
        try:
            if not on(c):
                return res
            dims = res[0]
            com = dims.get("commercial")
            if not com:
                return res
            others = [r for r in com.get("reasons") or [] if not r.startswith("Notice for ") and r != "Nothing pending."]
            t = today()
            soon = (date.today() + timedelta(days=7)).isoformat()
            ns = [e for e in open_notices(c, pid) if e["notice_needed"] and e["notice_deadline"] <= soon]
            reasons = [("Notice for %s due %s." if e["notice_deadline"] >= t else "Notice deadline for %s passed on %s: check it was sent.")
                       % (e["title"], e["notice_deadline"]) for e in ns]
            reasons += others
            due = any(e["notice_deadline"] >= t for e in ns)
            com["level"] = "critical" if due else ("attention" if reasons else "ok")
            com["reasons"] = reasons or ["Nothing pending."]
        except Exception as e:
            print("BuildCore 2.48: health kept as before: %s" % e)
        return res
    setattr(health, FLAG, True)
    health._orig = orig
    return health


def _actions_w(orig):
    """Action centre: own-delay notices leave; a passed deadline is 'overdue' (check), not 'critical'."""
    def action_items(c, u, pid=None, *a, **k):
        items = orig(c, u, pid, *a, **k)
        try:
            if not on(c):
                return items
            ns = {(e["project_id"], e["title"]): e for e in open_notices(c, pid)}
            t = today()
            out = []
            for it in items:
                ti = it.get("title") or ""
                if ti.startswith("Notice deadline: "):
                    e = ns.get((it.get("project_id"), ti[17:]))
                    if e is None or not e["notice_needed"]:
                        continue
                    if (e["notice_deadline"] or "") < t:
                        it = dict(it, category="overdue", why="Notice deadline passed %s. If sent, mark it sent." % e["notice_deadline"])
                out.append(it)
            return out
        except Exception as e:
            print("BuildCore 2.48: action list kept as before: %s" % e)
            return items
    setattr(action_items, FLAG, True)
    action_items._orig = orig
    return action_items


def _w_overview(orig):
    def overview(c, u, a):
        res = orig(c, u, a)
        try:
            res["glance"] = {"on": on(c), "version": VERSION}
            if on(c):
                own = [e for e in open_notices(c, a.get("project_id")) if not e["notice_needed"]]
                res["glance"]["own_events"] = len(own)
        except Exception:
            pass
        return res
    return overview


def _wrap(name, factory):
    cur = inv.FUNCS.get(name)
    if not cur or getattr(cur[0], FLAG, False):
        return
    w = factory(cur[0])
    for k in [k for k in getattr(cur[0], "__dict__", {}) if k.startswith("_bco")]:
        setattr(w, k, getattr(cur[0], k))
    setattr(w, FLAG, True)
    w._orig = cur[0]
    inv.FUNCS[name] = (w, cur[1], cur[2], cur[3])


def _patch(mod, name, factory):
    f = getattr(mod, name, None)
    if f is None or getattr(f, FLAG, False):
        return
    w = factory(f)
    for k in [k for k in getattr(f, "__dict__", {}) if k.startswith("_bco")]:
        setattr(w, k, getattr(f, k))
    setattr(w, FLAG, True)
    setattr(mod, name, w)


# ───────────────────────── this month at a glance ─────────────────────────
def period(c, cal=None, ref=None):
    cal = cal if cal in ("bs", "ad") else ((setting(c, "gl_month") or "").lower() if (setting(c, "gl_month") or "").lower() in ("bs", "ad")
                                           else "bs")
    ref = ref or today()
    frm = to = label = None
    if cal == "bs":
        try:
            import api_logbs
            _k, frm, to, label = api_logbs.month_of("bs", ref)
        except Exception:
            cal = "ad"
    if cal == "ad":
        frm = ref[:7] + "-01"
        to = core.month_end(ref[:7])
        label = date.fromisoformat(frm).strftime("%B %Y")
    d0, d1, dt = date.fromisoformat(frm), date.fromisoformat(to), date.fromisoformat(min(ref, to))
    return {"cal": cal, "from": frm, "to": to, "label": label, "days_total": (d1 - d0).days + 1,
            "days_elapsed": max(0, (dt - d0).days + 1), "as_of": ref}


def _prev(c, cal, frm):
    return period(c, cal, (date.fromisoformat(frm) - timedelta(days=1)).isoformat())


def _site(c, pids, frm, to):
    """Per project: DPRs, workers, work reported, machine hours, delays."""
    out = {}
    if not pids:
        return out
    ids = ",".join(str(int(p)) for p in pids)
    base = "FROM dpr d WHERE d.project_id IN (%s) AND d.date BETWEEN ? AND ?" % ids
    for r in q(c, "SELECT d.project_id pid, COUNT(*) n, COUNT(DISTINCT d.date) days, SUM(d.status='approved') approved, "
                  "SUM(d.status IN ('draft','submitted','checked')) waiting, MAX(d.date) last " + base + " GROUP BY d.project_id", (frm, to)):
        out[r["pid"]] = {"dpr": r["n"], "dpr_days": r["days"], "approved": r["approved"] or 0, "waiting": r["waiting"] or 0, "last_dpr": r["last"]}
    for r in q(c, "SELECT project_id pid, MAX(date) last FROM dpr WHERE project_id IN (%s) GROUP BY project_id" % ids):
        out.setdefault(r["pid"], {"dpr": 0, "dpr_days": 0, "approved": 0, "waiting": 0})["last_dpr_ever"] = r["last"]
    for r in q(c, "SELECT d.project_id pid, SUM(l.count) md, SUM(l.count*(COALESCE(l.hours,0)+COALESCE(l.ot_hours,0))) mh, "
                  "COUNT(DISTINCT d.date) days FROM dpr_labour l JOIN dpr d ON d.id=l.dpr_id WHERE d.project_id IN (%s) AND d.date BETWEEN ? AND ? "
                  "GROUP BY d.project_id" % ids, (frm, to)):
        x = out.setdefault(r["pid"], {})
        x["man_days"] = r2(r["md"] or 0)
        x["labour_hours"] = r2(r["mh"] or 0)
        x["workers_avg"] = round((r["md"] or 0) / r["days"], 1) if r["days"] else 0
    for r in q(c, "SELECT d.project_id pid, SUM(COALESCE(e.hours,0)) h, SUM(COALESCE(e.idle_hours,0)) idle, SUM(COALESCE(e.breakdown_hours,0)) bd, "
                  "COUNT(DISTINCT e.equipment_id) machines FROM dpr_equipment e JOIN dpr d ON d.id=e.dpr_id WHERE d.project_id IN (%s) "
                  "AND d.date BETWEEN ? AND ? GROUP BY d.project_id" % ids, (frm, to)):
        x = out.setdefault(r["pid"], {})
        x.update({"machine_hours": r2(r["h"] or 0), "idle_hours": r2(r["idle"] or 0), "breakdown_hours": r2(r["bd"] or 0), "machines": r["machines"]})
        tot = _f(r["h"]) + _f(r["idle"]) + _f(r["bd"])
        x["utilisation"] = round(100 * _f(r["h"]) / tot, 1) if tot > EPS else None
    # work reported: quantity x BOQ rate (the line on the DPR, else the activity's BOQ line)
    acols = _cols(c, "activities")
    bexpr = "COALESCE(w.boq_item_id, a.boq_item_id)" if "boq_item_id" in acols else "w.boq_item_id"
    items = {}
    for r in q(c, "SELECT d.project_id pid, b.id bid, b.code, b.description, b.unit, SUM(w.actual_qty) qty, "
                  "COALESCE(b.revised_rate, b.rate, 0) rate FROM dpr_work w JOIN dpr d ON d.id=w.dpr_id "
                  "LEFT JOIN activities a ON a.id=w.activity_id JOIN boq_items b ON b.id=%s "
                  "WHERE d.project_id IN (%s) AND d.date BETWEEN ? AND ? AND w.actual_qty>0 GROUP BY d.project_id, b.id" % (bexpr, ids), (frm, to)):
        v = _f(r["qty"]) * _f(r["rate"])
        x = out.setdefault(r["pid"], {})
        x["work_value"] = r2(_f(x.get("work_value")) + v)
        items.setdefault(r["pid"], []).append({"code": r["code"], "description": r["description"], "unit": r["unit"],
                                               "qty": r2(r["qty"]), "value": r2(v)})
    for pid, lst in items.items():
        lst.sort(key=lambda z: -z["value"])
        out[pid]["top_items"] = lst[:5]
    # delays by who carries them
    if _has(c, "dpr_delays"):
        resp_sql = "COALESCE(x.responsibility, CASE x.category %s ELSE 'contractor' END)" % " ".join(
            "WHEN '%s' THEN '%s'" % kv for kv in _cat_resp().items()) if "responsibility" in _cols(c, "dpr_delays") else \
            "CASE x.category %s ELSE 'contractor' END" % " ".join("WHEN '%s' THEN '%s'" % kv for kv in _cat_resp().items())
        for r in q(c, "SELECT d.project_id pid, x.category cat, %s resp, COUNT(*) n, SUM(COALESCE(x.hours,0)) h FROM dpr_delays x "
                      "JOIN dpr d ON d.id=x.dpr_id WHERE d.project_id IN (%s) AND d.date BETWEEN ? AND ? GROUP BY d.project_id, x.category, resp"
                      % (resp_sql, ids), (frm, to)):
            x = out.setdefault(r["pid"], {})
            dl = x.setdefault("delays", {"hours": 0.0, "count": 0, "by_resp": {}, "by_cat": []})
            dl["hours"] = r2(dl["hours"] + _f(r["h"]))
            dl["count"] += r["n"]
            dl["by_resp"][r["resp"]] = r2(dl["by_resp"].get(r["resp"], 0) + _f(r["h"]))
            dl["by_cat"].append({"category": CAT_LABEL.get(r["cat"], (r["cat"] or "Other").replace("_", " ").capitalize()),
                                 "resp": r["resp"], "hours": r2(r["h"]), "count": r["n"]})
        for x in out.values():
            if x.get("delays"):
                x["delays"]["by_cat"].sort(key=lambda z: -z["hours"])
    return out


def _money(c, u, pids, frm, to, scoped):
    from api_inventory import invoice_paid
    t = today()
    pc = " AND project_id IN (%s)" % ",".join(str(int(p)) for p in pids) if scoped else ""
    out = {}
    for kind, key in (("sales", "receivable"), ("purchase", "payable")):
        tot = od = od60 = 0.0
        for r in q(c, "SELECT id, payable, due_date FROM invoices WHERE kind=? AND status='posted'" + pc, (kind,)):
            bal = _f(r["payable"]) - invoice_paid(c, r["id"])
            if bal <= 0.5:
                continue
            tot += bal
            if r["due_date"] and r["due_date"] < t:
                od += bal
                if r["due_date"] < (date.today() - timedelta(days=60)).isoformat():
                    od60 += bal
        out[key] = r2(tot)
        out[key + "_overdue"] = r2(od)
        out[key + "_overdue_60"] = r2(od60)
    out["billed"] = r2(val(c, "SELECT COALESCE(SUM(gross),0) FROM ipc WHERE status NOT IN ('draft','cancelled','rejected') AND date BETWEEN ? AND ?" + pc, (frm, to))) \
        if _has(c, "ipc") else 0
    out["ipcs"] = val(c, "SELECT COUNT(*) FROM ipc WHERE status NOT IN ('draft','cancelled','rejected') AND date BETWEEN ? AND ?" + pc, (frm, to)) if _has(c, "ipc") else 0
    pcol = "gross" if "gross" in _cols(c, "payments") else "net"
    out["received"] = r2(val(c, "SELECT COALESCE(SUM(%s),0) FROM payments WHERE kind='receive' AND status='posted' AND date BETWEEN ? AND ?" % pcol + pc, (frm, to)))
    out["paid"] = r2(val(c, "SELECT COALESCE(SUM(%s),0) FROM payments WHERE kind='pay' AND status='posted' AND date BETWEEN ? AND ?" % pcol + pc, (frm, to)))
    lpc = " AND l.project_id IN (%s)" % ",".join(str(int(p)) for p in pids) if scoped else ""
    out["cost"] = r2(val(c, "SELECT COALESCE(SUM(l.debit-l.credit),0) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts a "
                            "ON a.id=l.account_id WHERE a.type='expense' AND v.status IN ('posted','reversed') AND v.date BETWEEN ? AND ?" + lpc, (frm, to)))
    by = {}
    for r in q(c, "SELECT l.project_id pid, SUM(l.debit-l.credit) x FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts a "
                  "ON a.id=l.account_id WHERE a.type='expense' AND v.status IN ('posted','reversed') AND v.date BETWEEN ? AND ? "
                  "AND l.project_id IS NOT NULL GROUP BY l.project_id", (frm, to)):
        by[r["pid"]] = r2(r["x"])
    out["cost_by_project"] = by
    if not scoped:
        try:
            import api_cash
            cb = q(c, "SELECT id, code, name, role FROM accounts WHERE role IN ('cash','bank') AND COALESCE(active,1)=1")
            for a_ in q(c, "SELECT id, code, name, 'bank' role FROM accounts WHERE role IS NULL AND type='asset' AND bank_name IS NOT NULL "
                           "AND bank_name<>'' AND COALESCE(active,1)=1"):
                cb.append(a_)
            for a_ in cb:
                a_["balance"] = r2(val(c, "SELECT COALESCE(SUM(l.debit-l.credit),0) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id "
                                          "WHERE l.account_id=? AND " + api_cash.POSTED, (a_["id"],)))
            out["cash_bank"] = cb
            out["cash_total"] = r2(sum(_f(x["balance"]) for x in cb))
            out["cash_entered"] = any(abs(_f(x["balance"])) > EPS for x in cb) or bool(
                val(c, "SELECT COUNT(*) FROM voucher_lines l JOIN accounts a ON a.id=l.account_id WHERE a.role IN ('cash','bank')"))
        except Exception as e:
            out["cash_error"] = str(e)
    return out


def _supply(c, u, pids, frm, to, scoped):
    out = {}
    ids = ",".join(str(int(p)) for p in pids)
    pc = (" AND project_id IN (%s)" % ids) if scoped else ""
    if core.can(u, "inventory", "view"):
        out["stock_value"] = r2(val(c, "SELECT COALESCE(SUM(value),0) FROM stock_balances WHERE 1=1" + pc))
        low = []
        for m in q(c, "SELECT m.id, m.code, m.name, m.unit, m.reorder_level, COALESCE(SUM(b.qty),0) qty FROM materials m LEFT JOIN stock_balances b "
                      "ON b.material_id=m.id" + ((" AND b.project_id IN (%s)" % ids) if scoped else "") +
                      " WHERE COALESCE(m.active,1)=1 AND COALESCE(m.reorder_level,0)>0 GROUP BY m.id"):
            if _f(m["qty"]) < _f(m["reorder_level"]):
                low.append({"code": m["code"], "name": m["name"], "unit": m["unit"], "qty": r2(m["qty"]), "reorder": m["reorder_level"]})
        out["low_stock"] = low[:10]
        out["low_stock_count"] = len(low)
    if core.can(u, "procurement", "view"):
        try:
            from api_finance import po_pending
            pend = po_pending(c, u, {})
            if scoped:
                pend = [p for p in pend if p.get("project_id") in pids]
            out["po_pending"] = len({p["po_id"] for p in pend})
            out["po_pending_value"] = r2(sum(_f(p.get("pending_value")) for p in pend))
            out["po_overdue"] = len({p["po_id"] for p in pend if _f(p.get("overdue_days")) > 0})
        except Exception:
            pass
        gp = (" AND g.project_id IN (%s)" % ids) if scoped else ""
        r = q1(c, "SELECT COUNT(DISTINCT g.id) n, COALESCE(SUM(COALESCE(gl.accepted_qty, gl.received_qty, 0)*COALESCE(gl.rate,0)),0) v FROM grn g "
                  "LEFT JOIN grn_lines gl ON gl.grn_id=g.id WHERE g.date BETWEEN ? AND ? AND COALESCE(g.status,'') NOT IN ('draft','cancelled')" + gp, (frm, to))
        out["grn_count"], out["grn_value"] = r["n"], r2(r["v"])
    return out


def _equipment(c, u, pids, scoped):
    ids = ",".join(str(int(p)) for p in pids)
    pc = (" AND project_id IN (%s)" % ids) if scoped else ""
    by = {}
    for r in q(c, "SELECT COALESCE(status,'working') st, COUNT(*) n FROM equipment WHERE COALESCE(active,1)=1" + pc + " GROUP BY st"):
        by[r["st"]] = r["n"]
    down = q(c, "SELECT code, name FROM equipment WHERE COALESCE(active,1)=1 AND status IN ('breakdown','under_maintenance')" + pc)
    return {"by_status": by, "total": sum(by.values()), "down": down[:8]}


def _approvals(c, u, pids, scoped):
    out = {}
    try:
        import api_project as P
        cnt = {}
        for it in P.action_items(c, u, pids[0] if scoped and len(pids) == 1 else None):
            if scoped and it.get("project_id") and it["project_id"] not in pids:
                continue
            cnt[it["category"]] = cnt.get(it["category"], 0) + 1
        out["approval"] = cnt.get("approval", 0)
        out["overdue"] = cnt.get("overdue", 0)
    except Exception:
        pass
    if _has(c, "post_queue") and core.can(u, "accounts", "view"):
        pc = (" AND pq.project_id IN (%s)" % ",".join(str(int(p)) for p in pids)) if scoped else ""
        r = q1(c, "SELECT COUNT(*) n, COALESCE(SUM(pq.amount),0) v FROM post_queue pq JOIN vouchers v ON v.id=pq.voucher_id "
                  "WHERE v.status='submitted' AND COALESCE(pq.stage,'') NOT IN ('posted','returned','rejected')" + pc)
        out["to_post"], out["to_post_value"] = r["n"], r2(r["v"])
    return out


@api("glance.month")
def glance_month(c, u, a):
    """This month at a glance, for the whole company or one project. Each part only for the rights the user has."""
    pid = int(a["project_id"]) if a.get("project_id") else None
    per = period(c, a.get("cal"), a.get("ref"))
    frm, to = per["from"], per["to"]
    projects = q(c, "SELECT id, code, name, contract_value FROM projects WHERE status='active' AND COALESCE(kind,'') NOT IN ('general','trading')" + (" AND id=%d" % pid if pid else "") + " ORDER BY code")
    try:
        import api_workspace as W  # project authorisation (2.20): only the projects this user may see
        allowed = getattr(W, "allowed_projects", None)
        if allowed:
            ok = allowed(c, u)
            if ok is not None:
                projects = [p for p in projects if p["id"] in ok]
    except Exception:
        pass
    pids = [p["id"] for p in projects]
    scoped = bool(pid)
    res = {"period": per, "version": VERSION, "projects": projects, "rights": {}}
    if core.can(u, "project", "view"):
        res["rights"]["site"] = True
        site = _site(c, pids, frm, to)
        prev = _prev(c, per["cal"], frm)
        site_prev = _site(c, pids, prev["from"], prev["to"])
        res["site"] = site
        tot = {"dpr": 0, "dpr_days": 0, "waiting": 0, "man_days": 0.0, "machine_hours": 0.0, "idle_hours": 0.0, "breakdown_hours": 0.0,
               "work_value": 0.0, "delay_hours": 0.0, "delay_by_resp": {}}
        for x in site.values():
            for k in ("dpr", "dpr_days", "waiting"):
                tot[k] += x.get(k) or 0
            for k in ("man_days", "machine_hours", "idle_hours", "breakdown_hours", "work_value"):
                tot[k] = r2(tot[k] + _f(x.get(k)))
            if x.get("delays"):
                tot["delay_hours"] = r2(tot["delay_hours"] + x["delays"]["hours"])
                for k, v in x["delays"]["by_resp"].items():
                    tot["delay_by_resp"][k] = r2(tot["delay_by_resp"].get(k, 0) + v)
        mt = tot["machine_hours"] + tot["idle_hours"] + tot["breakdown_hours"]
        tot["utilisation"] = round(100 * tot["machine_hours"] / mt, 1) if mt > EPS else None
        tot["work_value_prev"] = r2(sum(_f(x.get("work_value")) for x in site_prev.values()))
        tot["prev_label"] = prev["label"]
        cats = {}
        for x in site.values():
            for d in (x.get("delays") or {}).get("by_cat", []):
                k = (d["category"], d["resp"])
                cats[k] = r2(cats.get(k, 0) + d["hours"])
        tot["delay_top"] = [{"category": k[0], "resp": k[1], "hours": v} for k, v in sorted(cats.items(), key=lambda z: -z[1])[:4]]
        top = []
        for p in projects:
            for it in (site.get(p["id"]) or {}).get("top_items", []):
                top.append(dict(it, project=p["code"]))
        tot["top_items"] = sorted(top, key=lambda z: -z["value"])[:6]
        res["site_total"] = tot
        own = [e for e in open_notices(c, pid) if not e["notice_needed"]]
        res["own_events"] = {"count": len(own), "examples": [e["title"] for e in own[:3]]}
    if core.can(u, "accounts", "view"):
        res["rights"]["money"] = True
        res["money"] = _money(c, u, pids, frm, to, scoped)
    if core.can(u, "inventory", "view") or core.can(u, "procurement", "view"):
        res["rights"]["supply"] = True
        res["supply"] = _supply(c, u, pids, frm, to, scoped)
    if core.can(u, "equipment", "view"):
        res["rights"]["equipment"] = True
        res["equipment"] = _equipment(c, u, pids, scoped)
    res["approvals"] = _approvals(c, u, pids, scoped)
    return res


@api("glance.settings")
def glance_settings(c, u, a):
    return {"on": on(c), "month": (setting(c, "gl_month") or "").lower() or None, "version": VERSION,
            "can_change": core.can(u, "accounts", "approve") or core.can(u, "admin", "edit")}


@api("glance.settings_save")
def glance_settings_save(c, u, a):
    if not (core.can(u, "accounts", "approve") or core.can(u, "admin", "edit")):
        raise ApiError("Only accounts (approve) or an administrator can change the dashboard settings.")
    if "on" in a:
        c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('gl_on', ?)", ("1" if a["on"] in (1, True, "1", "true") else "0",))
    if a.get("month") in ("bs", "ad"):
        c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('gl_month', ?)", (a["month"],))
    core.audit(c, u, "settings", "glance", 0, {k: a.get(k) for k in ("on", "month")})
    return glance_settings(c, u, {})


def init_glance(c):
    c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES('gl_on', '1')")
    c.commit()
    import api_insight
    import api_project as P
    _patch(api_insight, "decisions", _decisions_w)
    _patch(P, "health", _health_w)
    _patch(P, "action_items", _actions_w)
    _wrap("insight.overview", _w_overview)
