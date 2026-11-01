"""
Logsheet, Nepali month and DPR fixes (BuildCore 2.30).

Corrections reported from site on 2.25, all still present in 2.29:
  1. Monthly logsheets did not take in machine days that an approved DPR made after the sheet was opened: the sheet
     itself listed them, but its totals, the register and the equipment reports counted only the days it had taken in
     when it was opened. Such days now join the sheet they fall in (a link only; nothing posts), unless that sheet is
     already approved: then the register says how many days wait for the sheet to be reopened.
  2. The register can be read for any date range, so a Nepali month (Bhadra 2083 = 17 Aug - 16 Sep 2026) shows the
     days of that month across the English-month sheets. Its total row now has the days as well.
  3. Split by output read only the attachment lines that a DPR with an attachment wrote. A DPR machine line without an
     attachment (the 2.25 smart form has no attachment box) lost its output there. The output, the attachment (or the
     machine's default) and the work the DPR reported on the same activity are now read from the DPR itself. Read only.
  4. Contract events made from DPR delay lines: saving a DPR again (after a return or a reopen) dropped the link from
     the delay line to its event, so the next approval made a second event and an event stayed after its delay line
     was removed. The link is now kept; an event whose line is gone is removed when nobody has worked on it, and
     listed for review when someone has. Older leftovers are listed on Events & claims with a button to tidy them.
  5. In a Project Workspace, lists of tables that have no project (maintenance plans) failed with "no such column:
     project_id"; they now ignore the project.
Nothing here posts, changes a balance or alters an existing table.
"""
import json

import core
from core import ApiError, audit, now, q, q1, r2, today, val
import api_inventory as inv
from api_inventory import api

VERSION = "2.30.0"
FLAG = "_bco230"
EPS = 1e-6

SCHEMA = """
CREATE TABLE IF NOT EXISTS lf_event_log(id INTEGER PRIMARY KEY, ts TEXT, user_id INTEGER, action TEXT, event_id INTEGER,
  event_no TEXT, dpr_id INTEGER, project_id INTEGER, detail TEXT);
"""


def init_logfix(c):
    c.executescript(SCHEMA)
    _install()


def _has(c, t):
    return bool(val(c, "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (t,)))


def _cols(c, t):
    return {r[1] for r in c.execute("PRAGMA table_info(%s)" % t)}


def _wrap(name, factory):
    cur = inv.FUNCS.get(name)
    if not cur or getattr(cur[0], FLAG, False):
        return
    w = factory(cur[0])
    for k in dir(cur[0]):
        if k.startswith("_bco") and getattr(cur[0], k, False):
            setattr(w, k, True)
    setattr(w, FLAG, True)
    w.__name__ = getattr(cur[0], "__name__", name)
    inv.FUNCS[name] = (w, cur[1], cur[2], cur[3])


# ═════════════════════════ 1. DPR days join the monthly sheet they fall in ═════════════════════════
def _book_for(c, eid, d):
    return q1(c, "SELECT id, status FROM logbooks WHERE equipment_id=? AND ? BETWEEN from_date AND to_date "
                 "ORDER BY CASE status WHEN 'approved' THEN 1 ELSE 0 END, id LIMIT 1", (eid, d))


def adopt(c, eid=None):
    """Link machine days that have no sheet to the open (not approved) sheet of their machine and date. Returns the
    number linked. Days of an approved sheet's dates stay unlinked until the sheet is reopened."""
    if not (_has(c, "logbooks") and "book_id" in _cols(c, "logsheets")):
        return 0
    sql = ("SELECT l.id, l.equipment_id, l.date FROM logsheets l WHERE l.book_id IS NULL AND EXISTS (SELECT 1 FROM logbooks b "
           "WHERE b.equipment_id=l.equipment_id AND l.date BETWEEN b.from_date AND b.to_date AND COALESCE(b.status,'draft')<>'approved')")
    p = []
    if eid:
        sql += " AND l.equipment_id=?"
        p.append(int(eid))
    n = 0
    for l in q(c, sql, p):
        b = _book_for(c, l["equipment_id"], l["date"])
        if b and b["status"] != "approved":
            c.execute("UPDATE logsheets SET book_id=? WHERE id=? AND book_id IS NULL", (b["id"], l["id"]))
            n += 1
    return n


def waiting(c, b):
    """Machine days in an approved sheet's dates that are not on it (they came after it was approved)."""
    return q(c, "SELECT id, date, shift, hours, dpr_id FROM logsheets WHERE equipment_id=? AND book_id IS NULL AND date BETWEEN ? AND ? "
                "ORDER BY date, shift", (b["equipment_id"], b["from_date"], b["to_date"]))


def _book_eq(c, a):
    try:
        return val(c, "SELECT equipment_id FROM logbooks WHERE id=?", (int(a.get("id") or 0),), None)
    except (TypeError, ValueError):
        return None


def _adopt_first(scope):
    def factory(orig):
        def run(c, u, a):
            try:
                adopt(c, _book_eq(c, a) if scope == "book" else (a.get("equipment_id") if scope == "eq" else None))
            except Exception as e:  # never stop the screen because of the link
                print("BuildCore 2.30: logsheet link skipped: %s" % e)
            r = orig(c, u, a)
            if scope == "book" and isinstance(r, dict) and isinstance(r.get("book"), dict) and r["book"].get("status") == "approved":
                r["waiting_days"] = waiting(c, r["book"])
            return r
        return run
    return factory


# ═════════════════════════ 2. the register for any month, English or Nepali ═════════════════════════
def _figs(c, b, rows, whole):
    days, nights, sb_d, bd_d = set(), set(), set(), set()
    hours = idle = bd = sb = fuel = km = 0.0
    for r in rows:
        d = r["date"]
        if (r["hours"] or 0) > 0:
            (nights if r["shift"] == "night" else days).add(d)
        if (r["breakdown_hours"] or 0) > 0:
            bd_d.add(d)
        if (r["standby_hours"] or 0) > 0 and not (r["hours"] or 0):
            sb_d.add(d)
        hours += r["hours"] or 0
        idle += r["idle_hours"] or 0
        bd += r["breakdown_hours"] or 0
        sb += r["standby_hours"] or 0
        fuel += r["fuel_qty"] or 0
        km += r["km_run"] or 0
    worked = days | nights
    payable = b["payable_days"] if (whole and b["payable_days"]) else len(worked | sb_d)
    amount = 0.0
    if b["rate"]:
        basis = (b["rate_basis"] or "hour").lower()
        qty = hours if basis.startswith("hour") else (km if basis.startswith("km") else payable)
        amount = r2(b["rate"] * qty)
    return {"days": len(worked), "hours": r2(hours), "idle": r2(idle), "breakdown": r2(bd), "standby": r2(sb),
            "payable_days": r2(payable), "fuel": r2(fuel), "km": r2(km), "ratio": r2(fuel / hours) if hours else 0,
            "availability": r2(100.0 * (hours + idle + sb) / (hours + idle + sb + bd)) if (hours + idle + sb + bd) else 0,
            "amount": amount, "lines": len(rows)}


def register_range(c, u, a):
    frm, to = a["from"][:10], a["to"][:10]
    if to < frm:
        raise ApiError("The month ends before it starts.")
    pid = a.get("project_id")
    import api_logsheet as LS
    cond, p = ["b.from_date<=?", "b.to_date>=?"], [to, frm]
    if pid:
        cond.append("b.project_id=?")
        p.append(int(pid))
    books = q(c, "SELECT b.*, e.code eq_code, e.name eq_name, e.reg_no FROM logbooks b JOIN equipment e ON e.id=b.equipment_id WHERE "
                 + " AND ".join(cond) + " ORDER BY e.code, b.from_date", p)
    out, tot = [], {"days": 0, "hours": 0.0, "fuel": 0.0, "km": 0.0, "bd": 0.0, "amount": 0.0}
    for b in books:
        rows = q(c, "SELECT * FROM logsheets WHERE book_id=? AND date BETWEEN ? AND ?", (b["id"], frm, to))
        whole = b["from_date"] >= frm and b["to_date"] <= to
        s = _figs(c, b, rows, whole)
        flagged = val(c, "SELECT COUNT(*) FROM log_checks WHERE book_id=? AND date BETWEEN ? AND ? AND result IN ('low','repair')",
                      (b["id"], frm, to)) if _has(c, "log_checks") else 0
        wait = len([x for x in waiting(c, b) if frm <= x["date"] <= to]) if b["status"] == "approved" else 0
        out.append(dict(s, id=b["id"], no=b["no"], equipment_id=b["equipment_id"], eq_code=b["eq_code"], eq_name=b["eq_name"],
                        reg_no=b["reg_no"], sheet_type=b["sheet_type"], kind=LS.SHEETS.get(b["sheet_type"], (b["sheet_type"],))[0],
                        status=b["status"], operator=b["operator"], owner=b["owner_name"], flagged=flagged, waiting=wait,
                        sheet_from=b["from_date"], sheet_to=b["to_date"], part=not whole))
        tot["days"] += s["days"]
        tot["hours"] += s["hours"]
        tot["fuel"] += s["fuel"]
        tot["km"] += s["km"]
        tot["bd"] += s["breakdown"]
        tot["amount"] += s["amount"]
    have = {b["equipment_id"] for b in books}
    missing = [dict(x) for x in q(c, "SELECT e.id, e.code, e.name FROM equipment e WHERE e.active=1 AND e.status<>'disposed' "
                                    "AND (? IS NULL OR e.project_id=?) ORDER BY e.code", (pid, pid)) if x["id"] not in have]
    loose = q(c, "SELECT e.code, e.name, COUNT(*) n, SUM(l.hours) h FROM logsheets l JOIN equipment e ON e.id=l.equipment_id "
                 "WHERE l.book_id IS NULL AND l.date BETWEEN ? AND ?%s GROUP BY e.id ORDER BY e.code"
              % (" AND l.project_id=?" if pid else ""), [frm, to] + ([int(pid)] if pid else []))
    return {"from": frm, "to": to, "period": a.get("period") or frm[:7], "label": a.get("label") or "",
            "rows": sorted(out, key=lambda r: (-r["hours"], r["eq_code"])),
            "totals": {k: r2(v) for k, v in tot.items()}, "no_sheet": missing,
            "loose": [dict(x, h=r2(x["h"] or 0)) for x in loose],
            "note": "Sheets are kept per English month (hire bills follow them). This view counts only each sheet's days "
                    "from %s to %s." % (frm, to)}


def _rep_w(orig):
    def run(c, u, a):
        try:
            adopt(c)
        except Exception as e:
            print("BuildCore 2.30: logsheet link skipped: %s" % e)
        if a.get("from") and a.get("to"):
            return register_range(c, u, a)
        r = orig(c, u, a)
        tot_days = 0
        for row in r.get("rows") or []:
            tot_days += row.get("days") or 0
            if row.get("status") == "approved":
                b = q1(c, "SELECT * FROM logbooks WHERE id=?", (row["id"],))
                row["waiting"] = len(waiting(c, b)) if b else 0
        if isinstance(r.get("totals"), dict):
            r["totals"]["days"] = tot_days
        return r
    return run


# ═════════════════════════ 3. split by output read from the DPR ═════════════════════════
def _default_tool(c, eid):
    return q1(c, "SELECT * FROM eq_tools WHERE equipment_id=? AND active=1 AND is_default=1 ORDER BY id LIMIT 1", (eid,))


def _dpr_lines(c, log):
    """The DPR machine lines behind one logsheet day that wrote no attachment line of their own."""
    if not log.get("dpr_id"):
        return []
    lines = q(c, "SELECT * FROM dpr_equipment WHERE logsheet_id=? ORDER BY id", (log["id"],))
    if not lines:
        lines = q(c, "SELECT * FROM dpr_equipment WHERE dpr_id=? AND equipment_id=? ORDER BY id", (log["dpr_id"], log["equipment_id"]))
    done = {r["dpr_equipment_id"] for r in q(c, "SELECT dpr_equipment_id FROM log_tools WHERE log_id=? AND dpr_equipment_id IS NOT NULL", (log["id"],))}
    return [e for e in lines if e["id"] not in done]


def _out(x):
    return x if (x is not None and abs(x) > EPS) else None


def tool_hours(c, log):
    """[(tool or None, hours, output)] for one logsheet day; DPR lines without an attachment line count at their own
    attachment (or the machine's default) with the output written on the DPR; hours left go to the default."""
    import api_life as L
    rows = q(c, "SELECT tool_id, SUM(hours) h, SUM(output_qty) o FROM log_tools WHERE log_id=? GROUP BY tool_id", (log["id"],))
    out = [(L._tool(c, r["tool_id"]), r["h"] or 0, _out(r["o"])) for r in rows]
    extra = _dpr_lines(c, log) if not rows else []
    if extra:
        line_h = sum(e["hours"] or 0 for e in extra)
        total = log.get("hours") or 0
        for e in extra:
            t = L._tool(c, e.get("tool_id")) or _default_tool(c, log["equipment_id"])
            hrs = (e["hours"] or 0) * total / line_h if line_h > EPS else (total if e is extra[0] else 0)
            out.append((t, r2(hrs), _out(e.get("output_qty"))))
    rest = (log.get("hours") or 0) - sum(x[1] for x in out)
    if rest > 0.01:
        out.append((_default_tool(c, log["equipment_id"]), rest, None))
    # one attachment, one entry
    merged = {}
    for t, h_, o in out:
        k = t["id"] if t else 0
        m = merged.setdefault(k, [t, 0.0, None])
        m[1] += h_
        if o is not None:
            m[2] = (m[2] or 0) + o
    return [tuple(v) for v in merged.values()]


def _dpr_work(c, log):
    """The work the DPR reported on the activities this machine worked on that day (for reference)."""
    if not log.get("dpr_id"):
        return []
    acts = [e["activity_id"] for e in q(c, "SELECT DISTINCT activity_id FROM dpr_equipment WHERE dpr_id=? AND equipment_id=? AND activity_id IS NOT NULL",
                                       (log["dpr_id"], log["equipment_id"]))]
    res = []
    for aid in acts:
        w = q1(c, "SELECT SUM(w.actual_qty) qty, a.name, COALESCE(a.unit, b.unit) unit FROM dpr_work w JOIN activities a ON a.id=w.activity_id "
                  "LEFT JOIN boq_items b ON b.id=a.boq_item_id WHERE w.dpr_id=? AND w.activity_id=?", (log["dpr_id"], aid))
        if w and w["qty"]:
            n = val(c, "SELECT COUNT(DISTINCT equipment_id) FROM dpr_equipment WHERE dpr_id=? AND activity_id=?", (log["dpr_id"], aid))
            res.append({"activity": w["name"], "qty": r2(w["qty"]), "unit": w["unit"] or "", "machines": n})
    return res


def _log_get_w(orig):
    def run(c, u, a):
        import api_life as L
        eid = int(a["equipment_id"])
        m = (a.get("month") or today())[:7]
        frm = (a.get("from") or "")[:10]
        to = (a.get("to") or "")[:10]
        if not (frm and to):
            import api_equipment_reports as ER
            frm, to = m + "-01", ER.month_end(m) if hasattr(ER, "month_end") else m + "-31"
        tools = L.tool_list(c, u, {"equipment_id": eid})["rows"]
        logs = q(c, "SELECT id, equipment_id, date, shift, hours, dpr_id, work FROM logsheets WHERE equipment_id=? AND date BETWEEN ? AND ? "
                    "ORDER BY date, shift", (eid, frm, to))
        for l in logs:
            own = {str(x["tool_id"]): {"hours": x["hours"], "output_qty": _out(x["output_qty"])}
                   for x in q(c, "SELECT tool_id, SUM(hours) hours, SUM(output_qty) output_qty FROM log_tools WHERE log_id=? GROUP BY tool_id", (l["id"],))}
            l["from_dpr"] = bool(l["dpr_id"])
            l["dpr_no"] = val(c, "SELECT no FROM dpr WHERE id=?", (l["dpr_id"],), None) if l["dpr_id"] else None
            l["read_from_dpr"] = False
            if not own and l["dpr_id"]:
                for t, h_, o in tool_hours(c, l):
                    if t:
                        own[str(t["id"])] = {"hours": r2(h_), "output_qty": o}
                l["read_from_dpr"] = bool(own)
            l["tools"] = own
            l["dpr_work"] = _dpr_work(c, l)
            l["output_missing"] = bool(l["dpr_id"]) and not any(v.get("output_qty") for v in own.values())
        return {"tools": tools, "logs": logs, "month": m, "from": frm, "to": to}
    return run


# ═════════════════════════ 4. contract events made from DPR delay lines ═════════════════════════
def _touched(c, e):
    """True when someone has worked on an event BuildCore made from a DPR delay line."""
    if (e.get("status") or "open") != "open":
        return True
    for k in ("notice_sent", "fragnet", "responsibility", "activity_ids"):
        if e.get(k) not in (None, "", "[]"):
            return True
    for k in ("eot_claimed", "eot_granted", "cost_impact", "claim_value", "prolongation_cost", "highly_probable",
              "compensable", "concurrent"):
        if (e.get(k) or 0) not in (0, 0.0):
            return True
    if e.get("excusable") is not None:
        return True
    if val(c, "SELECT COUNT(*) FROM audit WHERE entity='events' AND entity_id=? AND action<>'save'", (e["id"],)):
        return True
    if (val(c, "SELECT COUNT(*) FROM audit WHERE entity='events' AND entity_id=? AND action='save'", (e["id"],)) or 0) > 1:
        return True
    for t, col in (("files", "entity"), ("comments", "entity")):
        if _has(c, t) and val(c, "SELECT COUNT(*) FROM %s WHERE %s='events' AND entity_id=?" % (t, col), (e["id"],)):
            return True
    if _has(c, "udpr_issue_x") and val(c, "SELECT COUNT(*) FROM udpr_issue_x WHERE event_id=?", (e["id"],)):
        return True
    return False


def orphans(c, pid=None, dpr_id=None):
    """Events made from a DPR delay line that no delay line points to any more."""
    if not _has(c, "dpr_delays"):
        return []
    cond, p = ["e.dpr_id IS NOT NULL", "e.id NOT IN (SELECT event_id FROM dpr_delays WHERE event_id IS NOT NULL)"], []
    if pid:
        cond.append("e.project_id=?")
        p.append(int(pid))
    if dpr_id:
        cond.append("e.dpr_id=?")
        p.append(int(dpr_id))
    rows = q(c, "SELECT e.*, d.no dpr_no, d.status dpr_status FROM events e LEFT JOIN dpr d ON d.id=e.dpr_id WHERE "
                + " AND ".join(cond) + " ORDER BY e.date, e.id", p)
    for r in rows:
        r["worked_on"] = _touched(c, r)
        same = q1(c, "SELECT x.event_id, e2.no FROM dpr_delays x JOIN events e2 ON e2.id=x.event_id WHERE x.dpr_id=? AND "
                     "LOWER(REPLACE(x.category,'_',' '))||' delay'=LOWER(SUBSTR(?,1,INSTR(?,' (')-1))", (r["dpr_id"], r["title"] or "", r["title"] or "")) \
            if r["dpr_id"] and " (" in (r["title"] or "") else None
        r["why"] = ("a second copy of %s, made when the DPR was approved again" % same["no"]) if same else \
            ("the DPR is gone" if not r["dpr_no"] else "the delay line is no longer on %s" % r["dpr_no"])
    return rows


def _log(c, u, action, e, detail):
    c.execute("INSERT INTO lf_event_log(ts, user_id, action, event_id, event_no, dpr_id, project_id, detail) VALUES(?,?,?,?,?,?,?,?)",
              (now(), u["id"] if u else None, action, e["id"], e.get("no"), e.get("dpr_id"), e.get("project_id"),
               json.dumps(detail, default=str)[:4000]))


def remove_event(c, u, e, why):
    """Remove an event BuildCore made from a DPR delay line that nobody worked on; its review task is closed."""
    row = q1(c, "SELECT * FROM events WHERE id=?", (e["id"],))
    if not row:
        return False
    c.execute("DELETE FROM events WHERE id=?", (row["id"],))
    if _has(c, "tasks"):
        c.execute("UPDATE tasks SET status='done', done_at=?, description=COALESCE(description,'')||? WHERE source_type='events' "
                  "AND source_id=? AND status<>'done'", (now(), " (closed: the event was withdrawn, %s)" % why, row["id"]))
    audit(c, u, "withdraw", "events", row["id"], dict(row, reason=why))
    _log(c, u, "removed", row, {"reason": why, "event": row})
    return True


def _dpr_save_w(orig):
    def run(c, u, a):
        h = a.get("header") or {}
        rid = h.get("id")
        before = []
        if rid:
            try:
                before = q(c, "SELECT category, activity_id, event_id FROM dpr_delays WHERE dpr_id=? AND event_id IS NOT NULL ORDER BY id", (int(rid),))
            except Exception:
                before = []
        r = orig(c, u, a)
        did = (r or {}).get("id") or rid
        if not did:
            return r
        did = int(did)
        # give each delay line back the event it had (same reason and activity, in order); a line now marked
        # "not a contract event" lets its event go
        pool = list(before)
        for ln in q(c, "SELECT id, category, activity_id, create_event FROM dpr_delays WHERE dpr_id=? ORDER BY id", (did,)):
            if not ln["create_event"]:
                continue
            for i, b in enumerate(pool):
                if b["category"] == ln["category"] and (b["activity_id"] or 0) == (ln["activity_id"] or 0):
                    if q1(c, "SELECT id FROM events WHERE id=?", (b["event_id"],)):
                        c.execute("UPDATE dpr_delays SET event_id=? WHERE id=?", (b["event_id"], ln["id"]))
                    pool.pop(i)
                    break
        relink(c, did)
        for e in orphans(c, dpr_id=did):
            if e["id"] not in {b["event_id"] for b in before}:
                continue                      # older leftovers are for the user to tidy on Events & claims
            if e["worked_on"]:
                _log(c, u, "kept", e, {"reason": "delay line removed from the DPR; the event has been worked on"})
            else:
                remove_event(c, u, e, "its delay line was removed when %s was revised" % (e.get("dpr_no") or "the DPR"))
        return r
    return run


def relink(c, did):
    """A delay line that lost its event before 2.30 (the DPR was saved again) gets it back, so approving the DPR
    again does not make a second one."""
    for ln in q(c, "SELECT id, category, activity_id FROM dpr_delays WHERE dpr_id=? AND create_event=1 AND event_id IS NULL ORDER BY id", (did,)):
        for e in orphans(c, dpr_id=did):
            want = ((ln["category"] or "").replace("_", " ").capitalize() + " delay (").lower()
            if (e["title"] or "").lower().startswith(want) and (e["activity_id"] or 0) == (ln["activity_id"] or 0):
                c.execute("UPDATE dpr_delays SET event_id=? WHERE id=?", (e["id"], ln["id"]))
                break


def _approve_w(orig):
    def run(c, u, a):
        try:
            relink(c, int(a["id"]))
        except Exception as e:
            print("BuildCore 2.30: event link skipped: %s" % e)
        r = orig(c, u, a)
        try:
            for e in q(c, "SELECT DISTINCT equipment_id FROM dpr_equipment WHERE dpr_id=?", (int(a["id"]),)):
                adopt(c, e["equipment_id"])
        except Exception as e:
            print("BuildCore 2.30: logsheet link skipped: %s" % e)
        return r
    return run


@api("lf.event_check", "project", "view")
def event_check(c, u, a):
    """Events made from DPR delay lines that no DPR line points to any more, with whether anyone worked on them."""
    pid = a.get("project_id")
    rows = orphans(c, pid=pid)
    return {"rows": [{k: r.get(k) for k in ("id", "no", "date", "title", "status", "dpr_id", "dpr_no", "dpr_status", "worked_on", "why", "project_id")}
                     for r in rows],
            "removable": len([r for r in rows if not r["worked_on"]]), "kept": len([r for r in rows if r["worked_on"]]),
            "log": q(c, "SELECT * FROM lf_event_log WHERE (? IS NULL OR project_id=?) ORDER BY id DESC LIMIT 50", (pid, pid))}


@api("lf.event_tidy", "project", "view")
def event_tidy(c, u, a):
    """Remove the leftover events nobody worked on (the ones listed by lf.event_check). Worked-on events stay."""
    if not (core.can(u, "commercial", "edit") or core.can(u, "project", "edit")):
        raise ApiError("You need edit rights on Events & claims to tidy them.")
    pid = a.get("project_id")
    ids = {int(x) for x in (a.get("ids") or [])}
    n = 0
    for e in orphans(c, pid=pid):
        if e["worked_on"] or (ids and e["id"] not in ids):
            continue
        if remove_event(c, u, e, e["why"]):
            n += 1
    return {"removed": n}


# ═════════════════════════ 5. lists without a project in a Project Workspace ═════════════════════════
def _master_list_w(orig):
    """In a Project Workspace the active project is added to every call; a list whose table has no project column
    (maintenance plans, for one) then failed with "no such column: project_id". Such a list ignores the project."""
    def run(c, u, a):
        t = a.get("table")
        if a.get("project_id") and t and _has(c, t) and "project_id" not in _cols(c, t):
            a = dict(a)
            a.pop("project_id", None)
        return orig(c, u, a)
    return run


# ═════════════════════════ install ═════════════════════════
def _install():
    import api_life as L
    if not getattr(L._tool_hours, FLAG, False):
        setattr(tool_hours, FLAG, True)
        L._tool_hours = tool_hours
    for name in ("book.get", "book.summary", "book.submit", "book.approve"):
        _wrap(name, _adopt_first("book"))
    _wrap("book.list", _adopt_first("eq"))
    _wrap("rep.logbooks", _rep_w)
    _wrap("tool.log_get", _log_get_w)
    _wrap("dpr.save", _dpr_save_w)
    _wrap("dpr.approve", _approve_w)
    _wrap("master.list", _master_list_w)
