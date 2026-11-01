"""
DPR machine lines fill themselves (BuildCore 2.35).

Asked from site on 2.34: while writing a DPR the machine lines should
  1. list the project's machines on their own;
  2. open each machine at its previous closing reading (the last DPR before this date and shift);
  3. take the operator from the equipment list;
  4. work out the working hours as closing minus opening;
  5. when closing equals opening, ask Idle or Breakdown and put a standard day in that column.

Before 2.35 a new DPR copied yesterday's machine lines, but the opening meter came from equipment.meter, which DPRs
never update (usually 0), and the operator came from yesterday's line. Hours were only worked out on save.

This module only reads. It answers `dpr.meter_open` and widens `dpr.prefill`; the rest (hours as you type, the Idle /
Breakdown question) is on the DPR screens (pages_dprmeter.js). The standard day is the existing setting
`shift_hours` ("Scheduled hours per day (equipment)", 10 by default), already used for equipment elsewhere.
No table is added or changed, dpr.save is not touched, and nothing posts.
"""
from core import fsetting, q, q1, r2, today
import api_inventory as inv
from api_inventory import api

VERSION = "2.35.0"
FLAG = "_bco235"


def init_dprmeter(c):
    return None


def day_hours(c):
    return fsetting(c, "shift_hours") or 10


def _later(a, b):
    """(date, shift) a after b? Night follows day on the same date."""
    return (a[0], 1 if a[1] == "night" else 0) > (b[0], 1 if b[1] == "night" else 0)


def last_closing(c, eid, d, shift="day", dpr_id=0):
    """The machine's closing reading before this date and shift: the last DPR line with a closing reading above 0 (any project,
    any status but rejected; the highest reading when the machine has several lines that day), or a logsheet day typed
    by hand that is later still. None when the machine has no reading yet."""
    night = 1 if (shift or "day") == "night" else 0
    r = q1(c, "SELECT e.meter_end AS reading, d.date, d.shift, d.no, d.id AS dpr_id FROM dpr_equipment e JOIN dpr d ON d.id=e.dpr_id "
              "WHERE e.equipment_id=? AND e.meter_end>0 AND d.id<>? AND COALESCE(d.status,'')<>'rejected' "
              "AND (d.date<? OR (d.date=? AND ?=1 AND COALESCE(d.shift,'day')<>'night')) "
              "ORDER BY d.date DESC, CASE WHEN d.shift='night' THEN 1 ELSE 0 END DESC, e.meter_end DESC LIMIT 1",
           (eid, int(dpr_id or 0), d, d, night))
    found = None
    if r:
        found = {"reading": r2(r["reading"]), "date": r["date"], "shift": r["shift"] or "day",
                 "from": "DPR %s" % (r["no"] or r["dpr_id"]), "dpr_id": r["dpr_id"]}
    ls = q1(c, "SELECT l.meter_end AS reading, l.date, l.shift FROM logsheets l WHERE l.equipment_id=? AND l.meter_end>0 AND l.dpr_id IS NULL "
               "AND COALESCE(l.status,'')<>'rejected' AND NOT EXISTS (SELECT 1 FROM dpr_equipment x WHERE x.logsheet_id=l.id) "
               "AND (l.date<? OR (l.date=? AND ?=1 AND COALESCE(l.shift,'day')<>'night')) "
               "ORDER BY l.date DESC, CASE WHEN l.shift='night' THEN 1 ELSE 0 END DESC, l.meter_end DESC LIMIT 1",
            (eid, d, d, night))
    if ls and (not found or _later((ls["date"], ls["shift"] or "day"), (found["date"], found["shift"]))):
        found = {"reading": r2(ls["reading"]), "date": ls["date"], "shift": ls["shift"] or "day", "from": "logsheet", "dpr_id": None}
    return found


def _machine(c, e, d, shift, dpr_id):
    last = last_closing(c, e["id"], d, shift, dpr_id)
    opening = last["reading"] if last else (r2(e["meter"]) if e.get("meter") else None)
    return {"equipment_id": e["id"], "code": e["code"], "name": e["name"], "operator": (e.get("operator") or "").strip(),
            "meter_type": e.get("meter_type") or "hours", "status": e.get("status") or "",
            "opening": opening, "opening_from": ("%s · %s %s" % (last["from"], last["date"], last["shift"])) if last else
            ("machine register" if opening is not None else ""), "opening_date": last["date"] if last else None}


@api("dpr.meter_open", "project", "view")
def meter_open(c, u, a):
    """Opening reading and operator of machines for a DPR date and shift. Without equipment_ids: every machine that is
    not disposed (the screen keeps the list and fills lines as machines are picked)."""
    d = a.get("date") or today()
    shift = a.get("shift") or "day"
    dpr_id = int(a.get("dpr_id") or 0)
    ids = [int(x) for x in (a.get("equipment_ids") or []) if str(x).strip()]
    sql = "SELECT * FROM equipment WHERE COALESCE(status,'')<>'disposed'"
    if ids:
        sql += " AND id IN (%s)" % ",".join("?" * len(ids))
    rows = q(c, sql + " ORDER BY code", ids)
    out = {}
    for e in rows:
        out[str(e["id"])] = _machine(c, e, d, shift, dpr_id)
    return {"date": d, "shift": shift, "day_hours": r2(day_hours(c)), "machines": out}


def _project_machines(c, pid):
    return q(c, "SELECT * FROM equipment WHERE project_id=? AND COALESCE(active,1)=1 AND COALESCE(status,'')<>'disposed' ORDER BY code", (pid,))


def _prefill_w(orig):
    def w(c, u, a):
        r = orig(c, u, a)
        pid = a.get("project_id")
        if not pid:
            return r
        d = a.get("date") or today()
        shift = a.get("shift") or "day"
        lines = r.get("equipment") or []
        seen = set()
        for ln in lines:
            e = q1(c, "SELECT * FROM equipment WHERE id=?", (ln.get("equipment_id"),))
            if not e:
                continue
            seen.add(e["id"])
            m = _machine(c, e, d, shift, 0)
            ln["meter_start"] = m["opening"]
            ln["operator"] = m["operator"] or ln.get("operator") or ""
            ln["_opening_from"] = m["opening_from"]
        for e in _project_machines(c, int(pid)):
            if e["id"] in seen:
                continue
            seen.add(e["id"])
            m = _machine(c, e, d, shift, 0)
            lines.append({"activity_id": None, "equipment_id": e["id"], "operator": m["operator"], "meter_start": m["opening"],
                          "_opening_from": m["opening_from"], "_listed": 1})
        r["equipment"] = lines
        r["day_hours"] = r2(day_hours(c))
        return r
    return w


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


_wrap("dpr.prefill", _prefill_w)
setattr(meter_open, FLAG, True)
