"""The machine logsheet, the way sites keep it on paper.

Five companies' sheets were put side by side: a hoist daily check-list, a vehicle
sheet with kilometres, an excavator sheet with an hour meter, a generator sheet
with an energy meter, a jumbo with two booms, a dewatering pump, a rented machine
with the owner's name and payable days, and machines lent to another company.
They are all the same document underneath:

    one machine, one month, one signed sheet

with a header (whose machine, which operator, which site), a line a day (what it
did, when it started and stopped, every meter it carries, fuel taken, and three
signatures), a daily tick-list, what was serviced, what oil went in, and the
month's totals at the foot.

So BuildCore keeps one logbook and switches the columns on and off. A sheet type
sets the starting meters; anything can be changed per machine.
"""
from datetime import date, timedelta

from core import (ApiError, EPS, audit, get, ins, month_end, need, next_no, now, num, q, q1, r2, today, upd, val)
from api_inventory import api
import api_equipment_reports as eqr

# Every meter a machine can carry. "hour" and "km" live on the logsheet row itself
# because hours drive utilisation, cost and the earned-value figures; the rest are
# kept beside the row so a new kind of meter never needs a new column.
METERS = {
    "hour": ("Hour meter", "h"),
    "km": ("Kilometre", "km"),
    "kwh": ("Energy meter", "kWh"),
    "boom1": ("Boom 1", "h"),
    "boom2": ("Boom 2", "h"),
    "drum": ("Drum / batch counter", "no"),
    "strokes": ("Strokes", "no"),
    "load": ("Load counter", "no"),
    "pump": ("Pump running", "h"),
}


def primary(eq):
    """The machine's own meter - the one on its passport, the one the workshop services by."""
    return "km" if (eq["meter_type"] or "hours") == "km" else "hour"


def slot(eq, code):
    """Where a meter's readings live: the machine's own meter uses the logsheet's own columns."""
    if code == primary(eq):
        return ("meter_start", "meter_end", "km_run" if code == "km" else "hours")
    return None


# What each kind of sheet starts with. The operator can add or drop meters afterwards.
SHEETS = {
    "owned": ("Company machine", "hour"),
    "rental": ("Rented machine", "hour"),
    "hired_out": ("Working for another company", "hour"),
    "vehicle": ("Vehicle, tipper or transit mixer", "km,hour"),
    "genset": ("Generator", "kwh,hour"),
    "drilling": ("Drilling jumbo", "boom1,boom2,hour"),
    "dewatering": ("Dewatering pump", "hour"),
    "hoist": ("Hoist or lift", "hour"),
}
RESULTS = ("ok", "low", "topped_up", "repair", "na")


def meter_list(s):
    out = []
    for code in (s or "").replace(" ", "").split(","):
        if code in METERS and code not in out:
            out.append(code)
    return out


def default_meters(eq):
    have = meter_list(eq["meters"] if "meters" in eq.keys() else None)
    if have:
        return have
    return ["km", "hour"] if (eq["meter_type"] or "") == "km" else ["hour"]


def month_days(period):
    first = date(int(period[:4]), int(period[5:7]), 1)
    last = date.fromisoformat(month_end(period))
    return [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]


def book_or_die(c, bid):
    return get(c, "logbooks", int(bid), "Logsheet")


def editable(b):
    if b["status"] == "approved":
        raise ApiError("This sheet is approved. Reopen it first if it has to change.")


# ───────────────────────── the monthly sheet ─────────────────────────
@api("book.open", "equipment", "edit")
def book_open(c, u, a):
    """Open the sheet for one machine and one month, making it if it is not there yet."""
    need(a, "equipment_id", "period")
    eq = get(c, "equipment", int(a["equipment_id"]), "Equipment")
    period = a["period"][:7]
    kind = a.get("sheet_type") or ("rental" if (eq["ownership"] or "") in ("rented", "hired") else "owned")
    if kind not in SHEETS:
        raise ApiError("Unknown kind of sheet.")
    pid = int(a["project_id"]) if a.get("project_id") else eq["project_id"]
    if not pid:
        raise ApiError("Deploy the machine to a project, or choose the project for this sheet.")
    b = q1(c, "SELECT * FROM logbooks WHERE equipment_id=? AND period=? AND sheet_type=?",
           (eq["id"], period, kind))
    if b:
        return {"id": b["id"], "new": False}
    first = period + "-01"
    # what the machine itself says it carries wins; otherwise the kind of sheet decides
    own_meters = meter_list(eq["meters"] if "meters" in eq.keys() else None)
    ms = a.get("meters") or ",".join(own_meters or meter_list(SHEETS[kind][1]) or default_meters(eq))
    cl = a.get("checklist_id") or (eq["checklist_id"] if "checklist_id" in eq.keys() else None)
    if not cl:
        cl = val(c, "SELECT id FROM check_lists WHERE active=1 AND category=? ",
                 ((eq["category"] or "").lower(),), None) or val(c, "SELECT id FROM check_lists WHERE active=1", (),
                                                                 None)
    bid = ins(c, "logbooks", {
        "no": next_no(c, "LOG", first), "equipment_id": eq["id"], "project_id": pid, "period": period,
        "period_label": a.get("period_label") or date(int(period[:4]), int(period[5:7]), 1).strftime("%B %Y"),
        "from_date": first, "to_date": month_end(period), "sheet_type": kind,
        "owner_party_id": eq["vendor_id"] if kind == "rental" else None,
        "owner_name": (eq["owner_name"] if "owner_name" in eq.keys() else None) or None,
        "hirer_party_id": int(a["hirer_party_id"]) if a.get("hirer_party_id") else None,
        "operator": a.get("operator") or eq["operator"], "site": a.get("site"), "location": a.get("location"),
        "meters": ms, "checklist_id": cl, "status": "draft", "prepared_by": u["id"], "created_by": u["id"]})
    # days already entered on the day-by-day screen belong to this sheet
    took = c.execute("UPDATE logsheets SET book_id=? WHERE equipment_id=? AND book_id IS NULL AND date BETWEEN ? AND ?",
                     (bid, eq["id"], first, month_end(period))).rowcount
    audit(c, u, "open", "logbook", bid, {"equipment": eq["code"], "period": period})
    return {"id": bid, "new": True, "adopted": took}


def row_meters(c, log_id):
    return {r["code"]: {"s": r["r_start"], "e": r["r_stop"], "t": r["total"]}
            for r in q(c, "SELECT * FROM log_meters WHERE log_id=?", (log_id,))}


def flatten(c, eq, row, codes):
    d = dict(row)
    extra = row_meters(c, row["id"])
    for code in codes:
        sl = slot(eq, code)
        if sl:
            d["ms_" + code], d["me_" + code], d["mt_" + code] = row[sl[0]] or 0, row[sl[1]] or 0, row[sl[2]] or 0
        else:
            m = extra.get(code) or {}
            d["ms_" + code], d["me_" + code], d["mt_" + code] = m.get("s") or 0, m.get("e") or 0, m.get("t") or 0
    return d


@api("book.get", "equipment", "view")
def book_get(c, u, a):
    b = book_or_die(c, a["id"])
    eq = get(c, "equipment", b["equipment_id"], "Equipment")
    codes = meter_list(b["meters"]) or default_meters(eq)
    rows = q(c, "SELECT * FROM logsheets WHERE book_id=? OR (equipment_id=? AND date BETWEEN ? AND ?) "
                "ORDER BY date, shift", (b["id"], b["equipment_id"], b["from_date"], b["to_date"]))
    seen, days = set(), []
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        days.append(flatten(c, eq, r, codes))
    cl = q1(c, "SELECT * FROM check_lists WHERE id=?", (b["checklist_id"],)) if b["checklist_id"] else None
    items = [x.strip() for x in ((cl["items"] if cl else "") or "").split("\n") if x.strip()]
    checks = {}
    for r in q(c, "SELECT * FROM log_checks WHERE book_id=?", (b["id"],)):
        checks.setdefault(r["date"], {})[r["item"]] = {"result": r["result"], "remarks": r["remarks"]}
    return {"book": dict(b), "equipment": dict(eq), "meters": codes,
            "meter_names": {k: {"label": METERS[k][0], "unit": METERS[k][1]} for k in codes},
            "dates": month_days(b["period"]), "rows": days,
            "checklist": {"id": cl["id"], "name": cl["name"], "items": items} if cl else None,
            "checks": checks,
            "service": [dict(x) for x in q(c, "SELECT * FROM log_service WHERE book_id=? ORDER BY date, sn, id",
                                           (b["id"],))],
            "fluids": [dict(x) for x in q(c, "SELECT * FROM log_fluids WHERE book_id=? ORDER BY date, id",
                                          (b["id"],))],
            "summary": summarise(c, b, codes)}


@api("book.list", "equipment", "view")
def book_list(c, u, a):
    cond, p = [], []
    for k in ("equipment_id", "project_id", "status", "sheet_type", "period"):
        if a.get(k):
            cond.append("b.%s=?" % k)
            p.append(a[k])
    if a.get("from"):
        cond.append("b.period>=?")
        p.append(a["from"][:7])
    if a.get("to"):
        cond.append("b.period<=?")
        p.append(a["to"][:7])
    rows = q(c, "SELECT b.*, e.code eq_code, e.name eq_name, e.reg_no, e.category "
                "FROM logbooks b JOIN equipment e ON e.id=b.equipment_id%s "
                "ORDER BY b.period DESC, e.code LIMIT 500" % (" WHERE " + " AND ".join(cond) if cond else ""), p)
    out = []
    for b in rows:
        d = dict(b)
        t = q1(c, "SELECT COUNT(*) n, SUM(hours) h, SUM(idle_hours) i, SUM(breakdown_hours) bd, "
                  "SUM(standby_hours) sb, SUM(fuel_qty) f, SUM(km_run) km FROM logsheets WHERE book_id=?",
               (b["id"],))
        d.update({"days": t["n"] or 0, "hours": r2(t["h"] or 0), "idle": r2(t["i"] or 0),
                  "breakdown": r2(t["bd"] or 0), "standby": r2(t["sb"] or 0), "fuel": r2(t["f"] or 0),
                  "km": r2(t["km"] or 0)})
        out.append(d)
    return out


@api("book.save", "equipment", "edit")
def book_save(c, u, a):
    r = a.get("row") or {}
    b = book_or_die(c, r["id"])
    editable(b)
    # only what was sent is changed: a screen that shows half the header must not wipe the other half
    data = {k: r[k] for k in ("period_label", "operator", "operator2", "site", "location", "cost_code",
                              "remarks", "issues", "rate_basis", "owner_name", "hirer_name") if k in r}
    for k in ("owner_party_id", "hirer_party_id", "checklist_id"):
        if k in r:
            data[k] = int(r[k]) if r[k] else None
    for k in ("rate", "payable_days", "payable_hours"):
        if k in r:
            data[k] = num(r[k])
    if r.get("meters"):
        codes = meter_list(r["meters"])
        if not codes:
            raise ApiError("Choose at least one meter for this sheet.")
        data["meters"] = ",".join(codes)
    upd(c, "logbooks", b["id"], data)
    return {"id": b["id"]}


# A day whose hours came from an approved daily progress report is signed off: the working hours
# and the machine's own meter are settled and nothing here may move them. The monthly sheet can
# still fill in what the paper carries beside them - the fuel taken and its requisition number,
# the times, the three signatures, and the readings of any second meter the machine carries,
# because those are a record of the day, not a claim for it.
PAPER = ("time_start", "time_stop", "fuel_qty", "fuel_req_no", "cost_code", "down_reason",
         "sign_store", "sign_operator", "sign_incharge", "sign_hirer")


def put_meter(c, book_id, log_id, code, s, e):
    t = r2(e - s) if (s or e) else 0
    ex = q1(c, "SELECT id FROM log_meters WHERE log_id=? AND code=?", (log_id, code))
    d = {"log_id": log_id, "book_id": book_id, "code": code, "r_start": s, "r_stop": e, "total": t}
    if ex:
        upd(c, "log_meters", ex["id"], d)
    elif s or e:
        ins(c, "log_meters", d)


@api("book.rows", "equipment", "edit")
def book_rows(c, u, a):
    """Save the month's day lines in one go. Empty lines that used to have something are removed."""
    b = book_or_die(c, a["id"])
    editable(b)
    eq = get(c, "equipment", b["equipment_id"], "Equipment")
    codes = meter_list(b["meters"])
    saved, removed, warn, signed = 0, 0, [], 0
    for r in a.get("rows") or []:
        if r.get("id"):
            old = q1(c, "SELECT * FROM logsheets WHERE id=?", (int(r["id"]),))
            if old and old["status"] != "draft":
                d = {k: r.get(k) for k in PAPER if r.get(k) not in (None, "")}
                d["book_id"] = b["id"]
                if "fuel_qty" in d:
                    d["fuel_qty"] = num(d["fuel_qty"])
                upd(c, "logsheets", old["id"], d)
                for code in codes:
                    if slot(eq, code) or code == "hour":
                        continue          # these two decide the hours, and the hours are settled
                    s, e = num(r.get("ms_" + code)), num(r.get("me_" + code))
                    if e + EPS < s:
                        raise ApiError("%s on %s: closing reading is below the opening reading."
                                       % (METERS[code][0], r.get("date")))
                    put_meter(c, b["id"], old["id"], code, s, e)
                signed += 1
                continue
        filled = any(num(r.get(k)) for k in ("hours", "idle_hours", "breakdown_hours", "standby_hours",
                                             "trips", "fuel_qty")) \
            or any(num(r.get("ms_" + m)) or num(r.get("me_" + m)) for m in codes) \
            or any((r.get(k) or "").strip() for k in ("work", "time_start", "time_stop", "down_reason",
                                                      "cost_code", "fuel_req_no", "sign_store", "sign_operator",
                                                      "sign_incharge", "sign_hirer"))
        if not filled:
            if r.get("id"):
                old = q1(c, "SELECT * FROM logsheets WHERE id=?", (r["id"],))
                if old and old["status"] == "draft":
                    c.execute("DELETE FROM log_meters WHERE log_id=?", (old["id"],))
                    c.execute("DELETE FROM logsheets WHERE id=?", (old["id"],))
                    removed += 1
            continue
        row = dict(r)
        row.update({"equipment_id": b["equipment_id"], "project_id": b["project_id"], "book_id": b["id"]})
        row.setdefault("operator", b["operator"])
        extra = {}
        for code in codes:
            s, e = num(r.get("ms_" + code)), num(r.get("me_" + code))
            if e + EPS < s:
                raise ApiError("%s on %s: closing reading is below the opening reading."
                               % (METERS[code][0], r.get("date")))
            sl = slot(eq, code)
            if sl:
                row["meter_start"], row["meter_end"] = s, e
                if code == "km":
                    row["km_start"], row["km_end"] = s, e
            else:
                extra[code] = (s, e, r2(e - s) if (s or e) else 0)
                # hours on a machine whose own meter counts kilometres still drive costing
                if code == "hour" and (s or e):
                    row["hours"] = extra[code][2]
        res = eqr.save_log(c, u, row)
        if res.get("warning"):
            warn.append("%s: %s" % (r.get("date"), res["warning"]))
        for code, (s, e, _t) in extra.items():
            put_meter(c, b["id"], res["id"], code, s, e)
        saved += 1
    return {"saved": saved, "removed": removed, "signed": signed, "warnings": warn[:5]}


@api("book.checks", "equipment", "edit")
def book_checks(c, u, a):
    """The daily tick-list: one date, every item on the list."""
    b = book_or_die(c, a["id"])
    editable(b)
    n = 0
    for r in a.get("checks") or []:
        d, item = r.get("date"), (r.get("item") or "").strip()
        if not d or not item:
            continue
        res = r.get("result") or "ok"
        if res not in RESULTS:
            raise ApiError("Unknown check result '%s'." % res)
        ex = q1(c, "SELECT id FROM log_checks WHERE book_id=? AND date=? AND item=?", (b["id"], d, item))
        data = {"book_id": b["id"], "equipment_id": b["equipment_id"], "date": d, "item": item, "result": res,
                "remarks": r.get("remarks"), "checked_by": r.get("checked_by") or u["name"]}
        if r.get("clear"):
            if ex:
                c.execute("DELETE FROM log_checks WHERE id=?", (ex["id"],))
            continue
        if ex:
            upd(c, "log_checks", ex["id"], data)
        else:
            ins(c, "log_checks", data)
        n += 1
    return {"saved": n}


@api("book.service", "equipment", "edit")
def book_service(c, u, a):
    b = book_or_die(c, a["id"])
    editable(b)
    keep = []
    for i, r in enumerate(a.get("service") or [], 1):
        if not (r.get("description") or "").strip():
            continue
        d = {"book_id": b["id"], "equipment_id": b["equipment_id"], "date": r.get("date") or b["from_date"],
             "sn": i, "description": r["description"], "part_no": r.get("part_no"), "qty": num(r.get("qty")),
             "unit": r.get("unit"), "brand": r.get("brand"), "remarks": r.get("remarks"),
             "material_id": int(r["material_id"]) if r.get("material_id") else None,
             "at_hour": num(r.get("at_hour")), "at_km": num(r.get("at_km"))}
        if r.get("id"):
            upd(c, "log_service", int(r["id"]), d)
            keep.append(int(r["id"]))
        else:
            keep.append(ins(c, "log_service", d))
    old = [x["id"] for x in q(c, "SELECT id FROM log_service WHERE book_id=?", (b["id"],))]
    for i in old:
        if i not in keep:
            c.execute("DELETE FROM log_service WHERE id=?", (i,))
    return {"saved": len(keep)}


FLUIDS = ("engine_oil", "gear_oil", "brake_oil", "hydraulic_oil", "transmission_oil", "crown_oil",
          "grease", "coolant", "other_qty")


@api("book.fluids", "equipment", "edit")
def book_fluids(c, u, a):
    b = book_or_die(c, a["id"])
    editable(b)
    keep = []
    for r in a.get("fluids") or []:
        if not r.get("date") or not any(num(r.get(k)) for k in FLUIDS):
            if r.get("id"):
                c.execute("DELETE FROM log_fluids WHERE id=?", (int(r["id"]),))
            continue
        d = {"book_id": b["id"], "equipment_id": b["equipment_id"], "date": r["date"],
             "other_name": r.get("other_name"), "remarks": r.get("remarks")}
        for k in FLUIDS:
            d[k] = num(r.get(k))
        if r.get("id"):
            upd(c, "log_fluids", int(r["id"]), d)
            keep.append(int(r["id"]))
        else:
            keep.append(ins(c, "log_fluids", d))
    return {"saved": len(keep)}


# ───────────────────────── the month's totals ─────────────────────────
def summarise(c, b, codes=None):
    codes = codes or meter_list(b["meters"])
    rows = q(c, "SELECT * FROM logsheets WHERE book_id=? ORDER BY date, shift", (b["id"],))
    days, nights, both = set(), set(), set()
    idle_d, bd_d, sb_d = set(), set(), set()
    hours = idle = bd = sb = fuel = km = trips = 0.0
    for r in rows:
        d = r["date"]
        if (r["hours"] or 0) > 0:
            (nights if r["shift"] == "night" else days).add(d)
        if (r["idle_hours"] or 0) > 0 and not (r["hours"] or 0):
            idle_d.add(d)
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
        trips += r["trips"] or 0
    both = days & nights
    worked = days | nights
    payable = b["payable_days"] if b["payable_days"] else len(worked | sb_d)
    out = {"working_days": len(worked), "day_and_night": len(both), "idle_days": len(idle_d),
           "breakdown_days": len(bd_d), "standby_days": len(sb_d), "payable_days": r2(payable),
           "hours": r2(hours), "idle_hours": r2(idle), "breakdown_hours": r2(bd), "standby_hours": r2(sb),
           "fuel": r2(fuel), "km": r2(km), "trips": r2(trips), "lines": len(rows),
           "fuel_per_hour": r2(fuel / hours) if hours else 0,
           "fuel_per_km": r2(fuel / km) if km else 0,
           "availability": r2(100.0 * (hours + idle + sb) / (hours + idle + sb + bd)) if (hours + idle + sb + bd) else 0,
           "amount": 0.0}
    if b["rate"]:
        basis = (b["rate_basis"] or "hour").lower()
        qty = out["hours"] if basis.startswith("hour") else (out["km"] if basis.startswith("km") else out["payable_days"])
        out["amount"] = r2(b["rate"] * qty)
        out["billed_qty"] = qty
        out["billed_basis"] = basis
    eq = q1(c, "SELECT * FROM equipment WHERE id=?", (b["equipment_id"],))
    for code in codes:
        sl = slot(eq, code) if eq else None
        if sl:
            out["meter_" + code] = r2(val(c, "SELECT SUM(%s) FROM logsheets WHERE book_id=?" % sl[2],
                                          (b["id"],)) or 0)
            out["close_" + code] = val(c, "SELECT MAX(%s) FROM logsheets WHERE book_id=?" % sl[1],
                                       (b["id"],)) or 0
        else:
            out["meter_" + code] = r2(val(c, "SELECT SUM(total) FROM log_meters WHERE book_id=? AND code=?",
                                          (b["id"], code)) or 0)
            out["close_" + code] = val(c, "SELECT MAX(r_stop) FROM log_meters WHERE book_id=? AND code=?",
                                       (b["id"], code)) or 0
    if not out["km"] and out.get("meter_km"):
        out["km"] = out["meter_km"]                 # kilometres kept beside the machine's own hour meter
        out["fuel_per_km"] = r2(out["fuel"] / out["km"]) if out["km"] else 0
    out["service_items"] = val(c, "SELECT COUNT(*) FROM log_service WHERE book_id=?", (b["id"],))
    out["checks_done"] = val(c, "SELECT COUNT(DISTINCT date) FROM log_checks WHERE book_id=?", (b["id"],))
    out["checks_flagged"] = val(c, "SELECT COUNT(*) FROM log_checks WHERE book_id=? AND result IN "
                                   "('low','repair')", (b["id"],))
    return out


@api("book.summary", "equipment", "view")
def book_summary(c, u, a):
    return summarise(c, book_or_die(c, a["id"]))


# ───────────────────────── signing the sheet off ─────────────────────────
@api("book.submit", "equipment", "edit")
def book_submit(c, u, a):
    b = book_or_die(c, a["id"])
    editable(b)
    s = summarise(c, b)
    if not s["lines"]:
        raise ApiError("There is nothing on this sheet yet.")
    upd(c, "logbooks", b["id"], {"status": "submitted", "checked_by": u["id"]})
    audit(c, u, "submit", "logbook", b["id"], None)
    return {"id": b["id"], "summary": s}


@api("book.approve", "equipment", "approve")
def book_approve(c, u, a):
    b = book_or_die(c, a["id"])
    if b["status"] == "approved":
        raise ApiError("This sheet is already approved.")
    if b["status"] != "submitted" and not a.get("force"):
        raise ApiError("The sheet has to be checked and submitted before it is approved.")
    if b["checked_by"] == u["id"] and not a.get("force"):
        raise ApiError("The person who submits a sheet should not be the one who approves it.")
    c.execute("UPDATE logsheets SET status='approved', approved_by=? WHERE book_id=? AND status='draft'",
              (u["id"], b["id"]))
    s = summarise(c, b)
    upd(c, "logbooks", b["id"], {"status": "approved", "approved_by": u["id"], "approved_on": now(),
                                 "payable_days": b["payable_days"] or s["payable_days"],
                                 "payable_hours": b["payable_hours"] or s["hours"]})
    audit(c, u, "approve", "logbook", b["id"], {"hours": s["hours"], "days": s["payable_days"]})
    return {"id": b["id"], "summary": s}


@api("book.reopen", "equipment", "approve")
def book_reopen(c, u, a):
    b = book_or_die(c, a["id"])
    if b["status"] == "draft":
        raise ApiError("The sheet is already open.")
    c.execute("UPDATE logsheets SET status='draft', approved_by=NULL WHERE book_id=?", (b["id"],))
    upd(c, "logbooks", b["id"], {"status": "draft", "approved_by": None, "approved_on": None})
    audit(c, u, "reopen", "logbook", b["id"], {"reason": a.get("reason")})
    return True


@api("book.delete", "equipment", "edit")
def book_delete(c, u, a):
    b = book_or_die(c, a["id"])
    if b["status"] == "approved":
        raise ApiError("An approved sheet cannot be deleted. Reopen it first.")
    if val(c, "SELECT COUNT(*) FROM logsheets WHERE book_id=?", (b["id"],)):
        raise ApiError("Clear the day lines before deleting the sheet.")
    for t in ("log_checks", "log_service", "log_fluids", "log_meters"):
        c.execute("DELETE FROM %s WHERE book_id=?" % t, (b["id"],))
    c.execute("DELETE FROM logbooks WHERE id=?", (b["id"],))
    return True


# ───────────────────────── the register ─────────────────────────
@api("rep.logbooks", "equipment", "view")
def rep_logbooks(c, u, a):
    """Every machine's month on one page: hours, fuel, breakdown, what is still unsigned."""
    period = (a.get("period") or today())[:7]
    pid = a.get("project_id")
    books = book_list(c, u, {"period": period, "project_id": pid})
    rows, tot = [], {"hours": 0.0, "fuel": 0.0, "km": 0.0, "bd": 0.0, "amount": 0.0}
    for b in books:
        s = summarise(c, q1(c, "SELECT * FROM logbooks WHERE id=?", (b["id"],)))
        rows.append({"id": b["id"], "no": b["no"], "equipment_id": b["equipment_id"], "eq_code": b["eq_code"],
                     "eq_name": b["eq_name"], "reg_no": b["reg_no"], "sheet_type": b["sheet_type"],
                     "kind": SHEETS.get(b["sheet_type"], (b["sheet_type"],))[0], "status": b["status"],
                     "operator": b["operator"], "owner": b["owner_name"], "days": s["working_days"],
                     "hours": s["hours"], "idle": s["idle_hours"], "breakdown": s["breakdown_hours"],
                     "standby": s["standby_hours"], "payable_days": s["payable_days"], "fuel": s["fuel"],
                     "km": s["km"], "ratio": s["fuel_per_hour"], "availability": s["availability"],
                     "flagged": s["checks_flagged"], "amount": s["amount"]})
        tot["hours"] += s["hours"]
        tot["fuel"] += s["fuel"]
        tot["km"] += s["km"]
        tot["bd"] += s["breakdown_hours"]
        tot["amount"] += s["amount"]
    missing = q(c, "SELECT e.id, e.code, e.name FROM equipment e WHERE e.active=1 AND e.status<>'disposed' "
                   "AND (? IS NULL OR e.project_id=?) AND e.id NOT IN "
                   "(SELECT equipment_id FROM logbooks WHERE period=?) ORDER BY e.code",
                (pid, pid, period))
    periods = [dict(x) for x in q(c, "SELECT period, COUNT(*) n FROM logbooks%s GROUP BY period "
                                     "ORDER BY period DESC LIMIT 36"
                                  % (" WHERE project_id=?" if pid else ""), (pid,) if pid else ())]
    return {"period": period, "rows": sorted(rows, key=lambda r: (-r["hours"], r["eq_code"])),
            "totals": {k: r2(v) for k, v in tot.items()},
            "periods": periods, "latest": periods[0]["period"] if periods else period,
            "no_sheet": [dict(x) for x in missing]}


@api("check.templates", "equipment", "view")
def check_templates(c, u, a):
    return [dict(x) for x in q(c, "SELECT * FROM check_lists WHERE active=1 ORDER BY name")]


@api("check.save", "masters", "edit")
def check_save(c, u, a):
    r = a.get("row") or {}
    need(r, "name")
    items = (r.get("items") or "").strip()
    if not items:
        raise ApiError("A check list needs at least one item, one to a line.")
    d = {"code": r.get("code") or ("CL-%03d" % (val(c, "SELECT COUNT(*) FROM check_lists") + 1)),
         "name": r["name"], "category": r.get("category"), "items": items,
         "active": 1 if str(r.get("active", 1)) in ("1", "True", "true") else 0}
    if r.get("id"):
        upd(c, "check_lists", int(r["id"]), d)
        return {"id": int(r["id"])}
    return {"id": ins(c, "check_lists", d)}


@api("book.meters", "equipment", "view")
def book_meters(c, u, a):
    return {"meters": {k: {"label": v[0], "unit": v[1]} for k, v in METERS.items()},
            "sheets": {k: {"label": v[0], "meters": v[1]} for k, v in SHEETS.items()},
            "results": list(RESULTS)}
