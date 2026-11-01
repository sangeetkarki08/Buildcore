"""
Logsheets by Nepali month, one set of figures everywhere, and DPR days before approval (BuildCore 2.32).

Reported from site on 2.30:
  1. With Nepali dates the register showed Bhadra 2083 as parts of the English-month sheets ("September 2026 (Bhadra 16 -
     Ashoj 14) (part)"). Monthly sheets can now be kept per Nepali month: an administrator chooses the calendar once
     (setting logbook_calendar = bs). A Nepali sheet carries the period key "BS2083-05", its own English dates
     (from_date / to_date) and the label "Bhadra 2083". Changing the calendar moves the days of draft sheets to sheets of
     the new calendar (a draft sheet is renamed in place where it can be, so its number stays); submitted and approved
     sheets are never touched. Changing back moves them back the same way.
  2. The opened sheet listed every day of its machine in its dates, the register counted only the days linked to it,
     and the register's fuel came from the day lines while the sheet's came from store issues. The sheet now lists its
     own days, shows other days apart (another sheet, or waiting), and the register, the sheet and its summary use
     the same figures.
  3. Each day on the sheet shows its output / attachment and quantity from the DPR, and the sheet totals each output.
  4. DPR machine lines not yet approved (draft, submitted, checked, returned) show on the sheet and in the register,
     marked and kept apart from the approved hours: costing, hire and payable days still count approved days only.
     When an approved DPR is reopened and approved again, its day goes back on the same sheet with what had been
     written beside it on the sheet (fuel, times, signatures, extra meters), carrying the revised hours.
  5. Depreciation by hours reads the logsheet days by date, so Nepali-month sheets count in English-month runs.
Nothing here posts or changes a balance. New tables: lb_keep (what a reopened DPR day carried), lb_log (changes).
"""
import json
from datetime import date, timedelta

from core import ApiError, audit, get, ins, month_end, need, next_no, now, q, q1, r2, today, upd, val
import api_inventory as inv
from api_inventory import api
from sched_calc import BS, BS_MONTHS, _lens, ad_to_bs, bs_to_ad

VERSION = "2.32.0"
FLAG = "_bco232"
EPS = 1e-6
DPR_OPEN = ("approved", "rejected")        # every other DPR state is "not approved yet"

SCHEMA = """
CREATE TABLE IF NOT EXISTS lb_keep(id INTEGER PRIMARY KEY, equipment_id INTEGER, date TEXT, shift TEXT, book_id INTEGER,
  log_id INTEGER, dpr_id INTEGER, data TEXT, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_lbkeep ON lb_keep(equipment_id, date, shift);
CREATE TABLE IF NOT EXISTS lb_log(id INTEGER PRIMARY KEY, ts TEXT, user_id INTEGER, action TEXT, book_id INTEGER, detail TEXT);
"""
PAPER = ("time_start", "time_stop", "fuel_qty", "fuel_req_no", "cost_code", "down_reason",
         "sign_store", "sign_operator", "sign_incharge", "sign_hirer")


def init_logbs(c):
    c.executescript(SCHEMA)
    _install()


def _has(c, t):
    return bool(val(c, "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (t,)))


def _cols(c, t):
    return {r[1] for r in c.execute("PRAGMA table_info(%s)" % t)}


def _log(c, u, action, book_id, detail):
    c.execute("INSERT INTO lb_log(ts, user_id, action, book_id, detail) VALUES(?,?,?,?,?)",
              (now(), (u or {}).get("id"), action, book_id, json.dumps(detail, default=str)))


# ═════════════════════════ the two calendars ═════════════════════════
def calendar(c):
    v = (val(c, "SELECT value FROM settings WHERE key='logbook_calendar'", (), "") or "").strip().lower()
    return "bs" if v == "bs" else "ad"


def is_bs(period):
    return isinstance(period, str) and period.upper().startswith("BS")


def bs_parse(p):
    """'BS2083-05', '2083-05' or '2083-05-12' -> (2083, 5)"""
    s = str(p).strip().upper()
    if s.startswith("BS"):
        s = s[2:]
    y, m = int(s[:4]), int(s[5:7])
    if y not in BS or not 1 <= m <= 12:
        raise ApiError("%s is outside the Nepali calendar BuildCore knows (2070 to 2090)." % p)
    return y, m


def bs_key(y, m):
    return "BS%04d-%02d" % (y, m)


def bs_range(y, m):
    first = bs_to_ad(y, m, 1)
    return first.isoformat(), (first + timedelta(days=_lens(y)[m - 1] - 1)).isoformat()


def bs_label(y, m):
    return "%s %d" % (BS_MONTHS[m - 1], y)


def en_span(frm, to):
    """'17 Aug – 16 Sep 2026' (written so the Nepali date switch leaves it alone)"""
    a, b = date.fromisoformat(frm), date.fromisoformat(to)
    left = "%d %s" % (a.day, a.strftime("%b")) + ("" if a.year == b.year else " %d" % a.year)
    return "%s – %d %s %d" % (left, b.day, b.strftime("%b"), b.year)


def month_of(cal, iso):
    """(period key, from, to, label) of the sheet month holding a date"""
    if cal == "bs":
        y, m, _d = ad_to_bs(iso)
        f, t = bs_range(y, m)
        return bs_key(y, m), f, t, bs_label(y, m)
    p = iso[:7]
    return p, p + "-01", month_end(p), date(int(p[:4]), int(p[5:7]), 1).strftime("%B %Y")


def cal_of(b):
    return "bs" if is_bs(b["period"]) else "ad"


def book_label(b):
    if is_bs(b["period"]):
        y, m = bs_parse(b["period"])
        return bs_label(y, m)
    try:
        return date(int(b["period"][:4]), int(b["period"][5:7]), 1).strftime("%B %Y")
    except (TypeError, ValueError):
        return b.get("period_label") or b["period"]


def _month_days_factory(orig):
    def month_days(period):
        if is_bs(period):
            f, t = bs_range(*bs_parse(period))
            a, n = date.fromisoformat(f), (date.fromisoformat(t) - date.fromisoformat(f)).days + 1
            return [(a + timedelta(days=i)).isoformat() for i in range(n)]
        return orig(period)
    month_days._bco232 = True
    return month_days


# ═════════════════════════ opening a Nepali-month sheet ═════════════════════════
def _new_header(c, u, eq, kind, pid, a):
    import api_logsheet as LS
    own = LS.meter_list(eq["meters"] if "meters" in eq.keys() else None)
    ms = a.get("meters") or ",".join(own or LS.meter_list(LS.SHEETS[kind][1]) or LS.default_meters(eq))
    cl = a.get("checklist_id") or (eq["checklist_id"] if "checklist_id" in eq.keys() else None)
    if not cl:
        cl = val(c, "SELECT id FROM check_lists WHERE active=1 AND category=? ", ((eq["category"] or "").lower(),), None) \
            or val(c, "SELECT id FROM check_lists WHERE active=1", (), None)
    return {"equipment_id": eq["id"], "project_id": pid, "sheet_type": kind,
            "owner_party_id": eq["vendor_id"] if kind == "rental" else None,
            "owner_name": (eq["owner_name"] if "owner_name" in eq.keys() else None) or None,
            "hirer_party_id": int(a["hirer_party_id"]) if a.get("hirer_party_id") else None,
            "operator": a.get("operator") or eq["operator"], "site": a.get("site"), "location": a.get("location"),
            "meters": ms, "checklist_id": cl, "status": "draft", "prepared_by": u["id"], "created_by": u["id"]}


def open_bs(c, u, a, y, m):
    import api_logsheet as LS
    need(a, "equipment_id")
    eq = get(c, "equipment", int(a["equipment_id"]), "Equipment")
    kind = a.get("sheet_type") or ("rental" if (eq["ownership"] or "") in ("rented", "hired") else "owned")
    if kind not in LS.SHEETS:
        raise ApiError("Unknown kind of sheet.")
    pid = int(a["project_id"]) if a.get("project_id") else eq["project_id"]
    if not pid:
        raise ApiError("Deploy the machine to a project, or choose the project for this sheet.")
    key = bs_key(y, m)
    b = q1(c, "SELECT * FROM logbooks WHERE equipment_id=? AND period=? AND sheet_type=?", (eq["id"], key, kind))
    if b:
        return {"id": b["id"], "new": False}
    frm, to = bs_range(y, m)
    row = _new_header(c, u, eq, kind, pid, a)
    row.update({"no": next_no(c, "LOG", frm), "period": key, "period_label": a.get("period_label") or bs_label(y, m),
                "from_date": frm, "to_date": to})
    bid = ins(c, "logbooks", row)
    took = c.execute("UPDATE logsheets SET book_id=? WHERE equipment_id=? AND book_id IS NULL AND date BETWEEN ? AND ?",
                     (bid, eq["id"], frm, to)).rowcount
    audit(c, u, "open", "logbook", bid, {"equipment": eq["code"], "period": key})
    return {"id": bid, "new": True, "adopted": took}


def _open_w(orig):
    def run(c, u, a):
        p = a.get("bs_period") or (a.get("period") if is_bs(a.get("period")) else None)
        if p:
            return open_bs(c, u, a, *bs_parse(p))
        return orig(c, u, a)
    return run


def _book_for(c, eid, d):
    """The sheet a machine day belongs to: an open one first, then one of the chosen calendar."""
    bs = 0 if calendar(c) == "bs" else 1
    return q1(c, "SELECT id, status FROM logbooks WHERE equipment_id=? AND ? BETWEEN from_date AND to_date "
                 "ORDER BY CASE status WHEN 'approved' THEN 1 ELSE 0 END, "
                 "CASE WHEN upper(substr(period,1,2))='BS' THEN ? ELSE ? END, id LIMIT 1", (eid, d, bs, 1 - bs))


# ═════════════════════════ changing the calendar ═════════════════════════
def _dated(c, bid):
    """every dated thing on a sheet: day lines, checks, servicing, oil"""
    out = [("logsheets", r["id"], r["date"]) for r in q(c, "SELECT id, date FROM logsheets WHERE book_id=?", (bid,))]
    for t in ("log_checks", "log_service", "log_fluids"):
        if _has(c, t):
            out += [(t, r["id"], r["date"]) for r in q(c, "SELECT id, date FROM %s WHERE book_id=?" % t, (bid,)) if r["date"]]
    return out


def _empty(c, bid):
    if val(c, "SELECT COUNT(*) FROM logsheets WHERE book_id=?", (bid,)):
        return False
    return not any(_has(c, t) and val(c, "SELECT COUNT(*) FROM %s WHERE book_id=?" % t, (bid,))
                   for t in ("log_checks", "log_service", "log_fluids", "log_meters"))


COPY = ("project_id", "operator", "operator2", "site", "location", "cost_code", "meters", "checklist_id", "rate", "rate_basis",
        "owner_party_id", "owner_name", "hirer_party_id", "hirer_name", "remarks")


def convert(c, u, cal, dry=False):
    """Move the days of draft sheets kept in the other calendar onto sheets of `cal`."""
    other = [dict(b) for b in q(c, "SELECT * FROM logbooks WHERE COALESCE(status,'draft')='draft' ORDER BY equipment_id, sheet_type, from_date, id")
             if cal_of(b) != cal]
    left = q(c, "SELECT no, status, period, period_label FROM logbooks WHERE COALESCE(status,'draft')<>'draft'")
    left = [x for x in left if cal_of(x) != cal]
    res = {"calendar": cal, "drafts": len(other), "renamed": 0, "created": 0, "removed": 0, "moved": 0,
           "kept": len(left), "kept_sheets": [x["no"] for x in left][:30]}
    if dry or not other:
        return res
    groups = {}
    for b in other:
        groups.setdefault((b["equipment_id"], b["sheet_type"]), []).append(b)
    for (eid, kind), grp in groups.items():
        target = {b["period"]: dict(b) for b in q(c, "SELECT * FROM logbooks WHERE equipment_id=? AND sheet_type=?", (eid, kind))
                  if cal_of(b) == cal}
        renamed = set()
        # a draft becomes the sheet of the month that holds most of its days, so its number stays
        for b in grp:
            dates = [x[2] for x in _dated(c, b["id"])] or [b["from_date"]]
            tally = {}
            for d in dates:
                k = month_of(cal, d)
                tally.setdefault(k, 0)
                tally[k] += 1
            for k in sorted(tally, key=lambda x: (-tally[x], x[1])):
                if k[0] in target:
                    continue
                key, frm, to, label = k
                upd(c, "logbooks", b["id"], {"period": key, "period_label": label, "from_date": frm, "to_date": to,
                                             "payable_days": None, "payable_hours": None})
                _log(c, u, "calendar_rename", b["id"], {"no": b["no"], "from": b["period"], "to": key,
                                                        "payable_days_was": b["payable_days"], "payable_hours_was": b["payable_hours"]})
                target[key] = dict(b, period=key, period_label=label, from_date=frm, to_date=to, status="draft")
                renamed.add(b["id"])
                res["renamed"] += 1
                break
        # then every dated line goes to the sheet of its month
        for b in grp:
            for table, rid, d in _dated(c, b["id"]):
                key, frm, to, label = month_of(cal, d)
                tb = target.get(key)
                if tb is None:
                    row = {k: b[k] for k in COPY if k in b}
                    row.update({"no": next_no(c, "LOG", frm), "equipment_id": eid, "sheet_type": kind, "period": key,
                                "period_label": label, "from_date": frm, "to_date": to, "status": "draft",
                                "prepared_by": u["id"], "created_by": u["id"]})
                    nid = ins(c, "logbooks", row)
                    tb = target[key] = dict(row, id=nid)
                    _log(c, u, "calendar_new", nid, {"no": row["no"], "period": key, "from_sheet": b["no"]})
                    res["created"] += 1
                if tb["id"] == b["id"] or (tb.get("status") or "draft") != "draft":
                    continue
                if table == "log_checks":
                    c.execute("UPDATE OR IGNORE log_checks SET book_id=? WHERE id=?", (tb["id"], rid))
                else:
                    c.execute("UPDATE %s SET book_id=? WHERE id=?" % table, (tb["id"], rid))
                if table == "logsheets":
                    c.execute("UPDATE log_meters SET book_id=? WHERE log_id=?", (tb["id"], rid))
                    res["moved"] += 1
        for b in grp:
            if b["id"] not in renamed and _empty(c, b["id"]):
                c.execute("DELETE FROM logbooks WHERE id=?", (b["id"],))
                _log(c, u, "calendar_remove_empty", b["id"], {"no": b["no"], "period": b["period"]})
                audit(c, u, "delete", "logbook", b["id"], {"no": b["no"], "why": "its days moved to %s-calendar sheets" % cal})
                res["removed"] += 1
    return res


@api("lb.calendar", "equipment", "view")
def lb_calendar(c, u, a):
    cal = calendar(c)
    other = "ad" if cal == "bs" else "bs"
    return {"calendar": cal, "preview": convert(c, u, other, dry=True), "today": month_of(cal, today())[0]}


@api("lb.calendar_set", "equipment", "approve")
def lb_calendar_set(c, u, a):
    cal = (a.get("calendar") or "").lower()
    if cal not in ("ad", "bs"):
        raise ApiError("Choose English (ad) or Nepali (bs) months.")
    was = calendar(c)
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('logbook_calendar', ?)", (cal,))
    res = convert(c, u, cal) if a.get("move_drafts", True) else {"calendar": cal}
    try:
        import api_logfix
        res["linked"] = api_logfix.adopt(c)
    except Exception as e:
        print("BuildCore 2.32: logsheet link skipped: %s" % e)
    audit(c, u, "setting", "settings", None, {"logbook_calendar": [was, cal], "result": res})
    _log(c, u, "calendar", None, {"was": was, "now": cal, "result": res})
    return res


# ═════════════════════════ DPR days not approved yet ═════════════════════════
def _tool_name(c, tid, eid):
    t = q1(c, "SELECT * FROM eq_tools WHERE id=?", (int(tid),)) if tid else None
    if not t and _has(c, "eq_tools"):
        t = q1(c, "SELECT * FROM eq_tools WHERE equipment_id=? AND active=1 AND is_default=1 ORDER BY id LIMIT 1", (eid,))
    return t


def _out_text(parts):
    bits = []
    for name, h_, qty, unit in parts:
        s = (name or "Machine") + (" %s h" % _n(h_) if h_ else "")
        if qty:
            s += " · %s%s" % (_n(qty), (" " + unit) if unit else "")
        bits.append(s)
    return "; ".join(bits)


def _n(x):
    x = r2(x or 0)
    return str(int(x)) if abs(x - int(x)) < EPS else str(x)


def pending(c, eid, frm, to):
    """Machine lines on DPRs of these dates that are not approved yet (one line per DPR and shift)."""
    if not _has(c, "dpr_equipment"):
        return []
    rows = q(c, "SELECT e.*, d.no dpr_no, d.date, d.shift dshift, d.status dpr_status, d.project_id dpr_project "
                "FROM dpr_equipment e JOIN dpr d ON d.id=e.dpr_id WHERE e.equipment_id=? AND d.date BETWEEN ? AND ? "
                "AND COALESCE(d.status,'draft') NOT IN (%s) ORDER BY d.date, d.shift, e.id" % ",".join("?" * len(DPR_OPEN)),
             [eid, frm, to] + list(DPR_OPEN))
    grp = {}
    for e in rows:
        g = grp.setdefault(e["dpr_id"], {"dpr_id": e["dpr_id"], "dpr_no": e["dpr_no"], "date": e["date"], "shift": e["dshift"] or "day",
                                         "dpr_status": e["dpr_status"] or "draft", "project_id": e["dpr_project"], "operator": e["operator"],
                                         "hours": 0.0, "idle_hours": 0.0, "breakdown_hours": 0.0, "starts": [], "ends": [], "parts": [], "acts": []})
        g["hours"] += e["hours"] or 0
        g["idle_hours"] += e["idle_hours"] or 0
        g["breakdown_hours"] += e["breakdown_hours"] or 0
        if e["meter_start"] is not None:
            g["starts"].append(e["meter_start"])
        if e["meter_end"] is not None:
            g["ends"].append(e["meter_end"])
        t = _tool_name(c, e.get("tool_id"), eid)
        g["parts"].append(((t or {}).get("name"), e["hours"] or 0, e.get("output_qty") or 0, (t or {}).get("output_unit") or ""))
        if e["activity_id"]:
            nm = val(c, "SELECT name FROM activities WHERE id=?", (e["activity_id"],), None)
            if nm and nm not in g["acts"]:
                g["acts"].append(nm)
    out = []
    for g in grp.values():
        if q1(c, "SELECT id FROM logsheets WHERE equipment_id=? AND date=? AND shift=?", (eid, g["date"], g["shift"])):
            continue          # a day already on the logsheet is reused by the DPR when it is approved
        out.append({"date": g["date"], "shift": g["shift"], "dpr_id": g["dpr_id"], "dpr_no": g["dpr_no"], "dpr_status": g["dpr_status"],
                    "project_id": g["project_id"], "operator": g["operator"], "hours": r2(g["hours"]), "idle_hours": r2(g["idle_hours"]),
                    "breakdown_hours": r2(g["breakdown_hours"]),
                    "meter_start": min(g["starts"]) if g["starts"] else None, "meter_end": max(g["ends"]) if g["ends"] else None,
                    "work": ", ".join(g["acts"]), "out_text": _out_text(g["parts"]),
                    "output_qty": r2(sum(p[2] for p in g["parts"])) if len({p[3] for p in g["parts"] if p[2]}) <= 1 else None,
                    "output_unit": next((p[3] for p in g["parts"] if p[2]), ""), "pending": True})
    return out


def _pend_figs(rows):
    return {"pending_hours": r2(sum(x["hours"] or 0 for x in rows)), "pending_days": len({x["date"] for x in rows if (x["hours"] or 0) > 0})}


# ═════════════════════════ the output of each day ═════════════════════════
def outputs_of(c, log):
    import api_life as L
    try:
        parts = L._tool_hours(c, log)
    except Exception:
        return []
    return [((t or {}).get("name"), h_ or 0, o or 0, (t or {}).get("output_unit") or "") for t, h_, o in parts]


def enrich(c, rows):
    """DPR number, activity, output / attachment and quantity on each day line; the month's total per output."""
    per = {}
    for r in rows:
        parts = outputs_of(c, r)
        r["out_text"] = _out_text(parts) if any(p[0] or p[2] for p in parts) else ""
        units = {p[3] for p in parts if p[2]}
        r["output_qty"] = r2(sum(p[2] for p in parts)) if len(units) <= 1 and any(p[2] for p in parts) else None
        r["output_unit"] = next(iter(units)) if len(units) == 1 else ""
        r["dpr_no"] = val(c, "SELECT no FROM dpr WHERE id=?", (r["dpr_id"],), None) if r.get("dpr_id") else None
        if r.get("activity_id") and not r.get("activity"):
            r["activity"] = val(c, "SELECT name FROM activities WHERE id=?", (r["activity_id"],), None)
        for name, h_, qty, unit in parts:
            k = name or "Not split"
            o = per.setdefault(k, {"name": k, "hours": 0.0, "qty": 0.0, "unit": unit})
            o["hours"] += h_
            o["qty"] += qty
    return [dict(o, hours=r2(o["hours"]), qty=r2(o["qty"])) for o in sorted(per.values(), key=lambda x: -x["hours"])]


# ═════════════════════════ the sheet: its own days, the others apart ═════════════════════════
def _book_get_w(orig):
    def run(c, u, a):
        r = orig(c, u, a)
        if not isinstance(r, dict) or not isinstance(r.get("book"), dict):
            return r
        b = r["book"]
        mine, others = [], []
        for x in r.get("rows") or []:
            (mine if x.get("book_id") == b["id"] else others).append(x)
        r["rows"] = mine
        r["outputs"] = enrich(c, mine)
        nos = {}
        r["elsewhere"] = []
        for x in others:
            bid = x.get("book_id")
            if bid and bid not in nos:
                nos[bid] = q1(c, "SELECT id, no, status, period, period_label FROM logbooks WHERE id=?", (bid,))
            ob = nos.get(bid) if bid else None
            r["elsewhere"].append({"id": x["id"], "date": x["date"], "shift": x["shift"], "hours": x.get("hours"),
                                   "dpr_id": x.get("dpr_id"), "book_id": bid, "book_no": ob["no"] if ob else None,
                                   "book_status": ob["status"] if ob else None, "book_label": book_label(ob) if ob else None,
                                   "why": ("on sheet %s (%s, %s)" % (ob["no"], book_label(ob), ob["status"])) if ob
                                   else "on no sheet yet: this sheet was approved before the day came; reopen it to take the day in"})
        enrich(c, others)
        r["pending"] = pending(c, b["equipment_id"], b["from_date"], b["to_date"])
        b["calendar"] = cal_of(b)
        b["month_name"] = book_label(b)
        b["english_span"] = en_span(b["from_date"], b["to_date"])
        if isinstance(r.get("summary"), dict):
            r["summary"].update(_pend_figs(r["pending"]))
            r["summary"]["outputs"] = r["outputs"]
            r["summary"]["elsewhere_hours"] = r2(sum(x.get("hours") or 0 for x in others))
        return r
    return run


def _book_summary_w(orig):
    def run(c, u, a):
        r = orig(c, u, a)
        b = q1(c, "SELECT * FROM logbooks WHERE id=?", (int(a["id"]),))
        if b and isinstance(r, dict):
            s = r["summary"] if isinstance(r.get("summary"), dict) else r
            s.update(_pend_figs(pending(c, b["equipment_id"], b["from_date"], b["to_date"])))
            s["outputs"] = enrich(c, q(c, "SELECT * FROM logsheets WHERE book_id=? ORDER BY date, shift", (b["id"],)))
        return r
    return run


def _book_list_w(orig):
    """from / to are dates: a sheet is in when its dates meet them (English and Nepali sheets alike)"""
    def run(c, u, a):
        frm, to = a.get("from"), a.get("to")
        if not (frm or to):
            return orig(c, u, a)
        a2 = {k: v for k, v in a.items() if k not in ("from", "to")}
        f = (frm or "0000-01-01")[:10] if len(frm or "") >= 10 else (frm[:7] + "-01" if frm else "0000-01-01")
        t = (to or "9999-12-31")[:10] if len(to or "") >= 10 else (month_end(to[:7]) if to else "9999-12-31")
        return [x for x in orig(c, u, a2) if x["from_date"] <= t and x["to_date"] >= f]
    return run


# ═════════════════════════ the register: the same figures as the sheet ═════════════════════════
def sheet_figs(c, b, frm, to):
    """One sheet's figures inside frm..to: summarise() and the store's fuel, exactly as the sheet shows them."""
    import api_logsheet as LS
    import api_life as L
    whole = b["from_date"] >= frm and b["to_date"] <= to
    if whole:
        s = LS.summarise(c, b)
        try:
            L._store_fuel(c, b, s)
        except Exception:
            pass
        f = {"days": s["working_days"], "hours": s["hours"], "idle": s["idle_hours"], "breakdown": s["breakdown_hours"],
             "standby": s["standby_hours"], "payable_days": s["payable_days"], "fuel": s["fuel"], "km": s["km"],
             "ratio": s["fuel_per_hour"], "availability": s["availability"], "amount": s["amount"],
             "flagged": s["checks_flagged"]}
    else:
        import api_logfix as LF
        lo, hi = max(frm, b["from_date"]), min(to, b["to_date"])
        rows = q(c, "SELECT * FROM logsheets WHERE book_id=? AND date BETWEEN ? AND ?", (b["id"], lo, hi))
        f = LF._figs(c, b, rows, False)
        try:
            fuel = sum((x["qty"] or 0) for x in L.store_issues(c, b["equipment_id"], lo, hi) if L._mat_kind(x) == "fuel")
            if fuel or L.dpr_only(c):
                f["fuel"] = r2(fuel)
                f["ratio"] = r2(fuel / f["hours"]) if f["hours"] else 0
        except Exception:
            pass
        f["flagged"] = val(c, "SELECT COUNT(*) FROM log_checks WHERE book_id=? AND date BETWEEN ? AND ? AND result IN ('low','repair')",
                           (b["id"], lo, hi)) if _has(c, "log_checks") else 0
    p = pending(c, b["equipment_id"], max(frm, b["from_date"]), min(to, b["to_date"]))
    f.update(_pend_figs(p))
    f["whole"] = whole
    return f


def register(c, u, a):
    import api_logsheet as LS
    import api_logfix as LF
    per = a.get("period") or ""
    label = a.get("label") or ""
    if is_bs(per):
        y, m = bs_parse(per)
        frm, to = bs_range(y, m)
        label = label or bs_label(y, m)
    elif a.get("from") and a.get("to"):
        frm, to = a["from"][:10], a["to"][:10]
        try:
            date.fromisoformat(frm), date.fromisoformat(to)
        except ValueError:
            raise ApiError("Give the dates as YYYY-MM-DD.")
    else:
        per = (per or today())[:7]
        frm, to = per + "-01", month_end(per)
        label = label or date(int(per[:4]), int(per[5:7]), 1).strftime("%B %Y")
    if to < frm:
        raise ApiError("The month ends before it starts.")
    pid = a.get("project_id")
    cond, p = ["b.from_date<=?", "b.to_date>=?"], [to, frm]
    if pid:
        cond.append("b.project_id=?")
        p.append(int(pid))
    books = q(c, "SELECT b.*, e.code eq_code, e.name eq_name, e.reg_no FROM logbooks b JOIN equipment e ON e.id=b.equipment_id WHERE "
                 + " AND ".join(cond) + " ORDER BY e.code, b.from_date", p)
    out, tot = [], {"days": 0, "hours": 0.0, "fuel": 0.0, "km": 0.0, "bd": 0.0, "amount": 0.0, "pending_hours": 0.0, "pending_days": 0}
    for b in books:
        s = sheet_figs(c, b, frm, to)
        wait = len([x for x in LF.waiting(c, b) if frm <= x["date"] <= to]) if b["status"] == "approved" else 0
        out.append(dict(s, id=b["id"], no=b["no"], equipment_id=b["equipment_id"], eq_code=b["eq_code"], eq_name=b["eq_name"],
                        reg_no=b["reg_no"], sheet_type=b["sheet_type"], kind=LS.SHEETS.get(b["sheet_type"], (b["sheet_type"],))[0],
                        status=b["status"], operator=b["operator"], owner=b["owner_name"], waiting=wait,
                        sheet_from=b["from_date"], sheet_to=b["to_date"], part=not s["whole"], calendar=cal_of(b),
                        sheet_label=book_label(b), sheet_span=en_span(b["from_date"], b["to_date"])))
        tot["days"] += s["days"]
        tot["hours"] += s["hours"]
        tot["fuel"] += s["fuel"]
        tot["km"] += s["km"]
        tot["bd"] += s["breakdown"]
        tot["amount"] += s["amount"]
        tot["pending_hours"] += s["pending_hours"]
        tot["pending_days"] += s["pending_days"]
    have = {b["equipment_id"] for b in books}
    missing = [dict(x) for x in q(c, "SELECT e.id, e.code, e.name FROM equipment e WHERE e.active=1 AND e.status<>'disposed' "
                                    "AND (? IS NULL OR e.project_id=?) ORDER BY e.code", (pid, pid)) if x["id"] not in have]
    loose = q(c, "SELECT e.code, e.name, COUNT(*) n, SUM(l.hours) h FROM logsheets l JOIN equipment e ON e.id=l.equipment_id "
                 "WHERE l.book_id IS NULL AND l.date BETWEEN ? AND ?%s GROUP BY e.id ORDER BY e.code"
              % (" AND l.project_id=?" if pid else ""), [frm, to] + ([int(pid)] if pid else []))
    # machines with DPR lines not approved yet but no sheet for these dates
    pend_loose = []
    for e in q(c, "SELECT DISTINCT x.equipment_id id, eq.code, eq.name FROM dpr_equipment x JOIN dpr d ON d.id=x.dpr_id "
                  "JOIN equipment eq ON eq.id=x.equipment_id WHERE d.date BETWEEN ? AND ? AND COALESCE(d.status,'draft') NOT IN ('approved','rejected')%s"
               % (" AND d.project_id=?" if pid else ""), [frm, to] + ([int(pid)] if pid else [])) if _has(c, "dpr_equipment") else []:
        if e["id"] in have:
            continue
        pf = _pend_figs(pending(c, e["id"], frm, to))
        if pf["pending_hours"] or pf["pending_days"]:
            pend_loose.append(dict(e, **pf))
    cal = calendar(c)
    periods = [dict(x) for x in q(c, "SELECT period, MIN(period_label) label, COUNT(*) n FROM logbooks%s GROUP BY period "
                                     "ORDER BY from_date DESC LIMIT 36" % (" WHERE project_id=?" if pid else ""),
                                  (int(pid),) if pid else ())]
    parts = [r for r in out if r["part"]]
    note = ""
    if parts:
        note = ("%d sheet(s) here are kept for another month (%s); only their days of %s are counted on this page."
                % (len(parts), ", ".join(sorted({r["sheet_label"] for r in parts})), en_span(frm, to)))
    return {"period": per or frm[:7], "label": label, "from": frm, "to": to, "english_span": en_span(frm, to), "calendar": cal,
            "rows": sorted(out, key=lambda r: (-r["hours"], r["eq_code"])),
            "totals": {k: r2(v) for k, v in tot.items()}, "no_sheet": missing,
            "loose": [dict(x, h=r2(x["h"] or 0)) for x in loose], "pending_loose": pend_loose,
            "periods": periods, "latest": periods[0]["period"] if periods else (per or frm[:7]), "note": note}


def _rep_w(orig):
    def run(c, u, a):
        try:
            import api_logfix as LF
            LF.adopt(c)
        except Exception as e:
            print("BuildCore 2.32: logsheet link skipped: %s" % e)
        return register(c, u, a)
    return run


# ═════════════════════════ a reopened DPR keeps its day on the sheet ═════════════════════════
def _keep(c, d):
    lcols = _cols(c, "logsheets")
    for e in q(c, "SELECT * FROM dpr_equipment WHERE dpr_id=? AND created_log=1 AND logsheet_id IS NOT NULL", (d["id"],)):
        l = q1(c, "SELECT * FROM logsheets WHERE id=? AND dpr_id=?", (e["logsheet_id"], d["id"]))
        if not l:
            continue
        data = {k: l[k] for k in PAPER if k in lcols and l[k] not in (None, "", 0, 0.0)}
        data["_meters"] = [{"code": m["code"], "s": m["r_start"], "e": m["r_stop"], "t": m["total"]}
                           for m in q(c, "SELECT * FROM log_meters WHERE log_id=?", (l["id"],))]
        c.execute("INSERT INTO lb_keep(equipment_id, date, shift, book_id, log_id, dpr_id, data, ts) VALUES(?,?,?,?,?,?,?,?)",
                  (l["equipment_id"], l["date"], l["shift"], l.get("book_id"), l["id"], d["id"], json.dumps(data), now()))


def _restore(c, d):
    lcols = _cols(c, "logsheets")
    for l in q(c, "SELECT * FROM logsheets WHERE dpr_id=?", (d["id"],)):
        k = q1(c, "SELECT * FROM lb_keep WHERE equipment_id=? AND date=? AND shift=? ORDER BY id DESC LIMIT 1",
               (l["equipment_id"], l["date"], l["shift"]))
        if not k:
            continue
        data = json.loads(k["data"] or "{}")
        ch = {}
        if not l.get("book_id") and k["book_id"] and val(c, "SELECT COUNT(*) FROM logbooks WHERE id=?", (k["book_id"],)):
            ch["book_id"] = k["book_id"]
        for f, v in data.items():
            if f in PAPER and f in lcols and l.get(f) in (None, "", 0, 0.0):
                ch[f] = v
        if ch:
            upd(c, "logsheets", l["id"], ch)
        bid = ch.get("book_id") or l.get("book_id")
        for m in data.get("_meters") or []:
            if not q1(c, "SELECT id FROM log_meters WHERE log_id=? AND code=?", (l["id"], m["code"])):
                c.execute("INSERT INTO log_meters(log_id, book_id, code, r_start, r_stop, total) VALUES(?,?,?,?,?,?)",
                          (l["id"], bid, m["code"], m["s"], m["e"], m["t"]))
        c.execute("DELETE FROM lb_keep WHERE equipment_id=? AND date=? AND shift=?", (l["equipment_id"], l["date"], l["shift"]))
        _log(c, None, "dpr_day_back", bid, {"dpr": d.get("no"), "date": l["date"], "log_id": l["id"], "was_log_id": k["log_id"],
                                            "restored": sorted(x for x in ch if x != "book_id"), "sheet": bid})


def _wrap_posting():
    import api_project as P
    if not getattr(P.unpost_dpr, FLAG, False):
        o = P.unpost_dpr

        def unpost_dpr(c, u, d, reason, _o=o):
            try:
                _keep(c, d)
            except Exception as e:
                print("BuildCore 2.32: logsheet day not kept: %s" % e)
            return _o(c, u, d, reason)
        for k in dir(o):
            if k.startswith("_bco") and getattr(o, k, False):
                setattr(unpost_dpr, k, True)
        setattr(unpost_dpr, FLAG, True)
        P.unpost_dpr = unpost_dpr
    if not getattr(P.post_dpr, FLAG, False):
        o2 = P.post_dpr

        def post_dpr(c, u, d, _o=o2):
            r = _o(c, u, d)
            try:
                _restore(c, d)
            except Exception as e:
                print("BuildCore 2.32: logsheet day not restored: %s" % e)
            return r
        for k in dir(o2):
            if k.startswith("_bco") and getattr(o2, k, False):
                setattr(post_dpr, k, True)
        setattr(post_dpr, FLAG, True)
        P.post_dpr = post_dpr


# ═════════════════════════ depreciation by hours: days by date ═════════════════════════
def hours_used(c, fa_row, month):
    """Hours the machine ran in an English month, from the days on its monthly sheets (English or Nepali), per project."""
    import api_fa as FA
    if fa_row["kind"] != "equipment" or not fa_row["ref_id"] or not _has(c, "logsheets"):
        return {}
    lcols = _cols(c, "logsheets")
    hcol = next((x for x in ("hours", "work_hours", "hmr_total", "total_hours") if x in lcols), None)
    if not hcol or not _has(c, "logbooks"):
        return {}
    m = month[:7]
    rows = q(c, "SELECT b.project_id, SUM(l.%s) h FROM logsheets l JOIN logbooks b ON b.id=l.book_id "
                "WHERE b.equipment_id=? AND l.date BETWEEN ? AND ? AND b.sheet_type IN ('owned','hired_out','vehicle','genset',"
                "'drilling','dewatering','hoist') GROUP BY b.project_id" % hcol, (fa_row["ref_id"], m + "-01", month_end(m)))
    return {x["project_id"]: FA.num(x["h"]) for x in rows if FA.num(x["h"]) > 0}


hours_used._bco232 = True


# ═════════════════════════ wiring ═════════════════════════
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


def _install():
    import api_logsheet as LS
    if not getattr(LS.month_days, FLAG, False):
        LS.month_days = _month_days_factory(LS.month_days)
    try:
        import api_logfix as LF
        if not getattr(LF._book_for, FLAG, False):
            setattr(_book_for, FLAG, True)
            LF._book_for = _book_for
    except ImportError:
        pass
    try:
        import api_fa as FA
        if not getattr(FA.hours_used, FLAG, False):
            FA.hours_used = hours_used
    except ImportError:
        pass
    _wrap_posting()
    _wrap("book.open", _open_w)
    _wrap("book.get", _book_get_w)
    _wrap("book.summary", _book_summary_w)
    _wrap("book.list", _book_list_w)
    _wrap("rep.logbooks", _rep_w)
