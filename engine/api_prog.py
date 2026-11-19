"""BuildCore 2.50 "Programme in fast".

* Import a programme from Microsoft Project (XML, "Save as > XML") or Primavera P6 (XER): WBS, activities,
  durations, links with lags, constraints, baseline dates and the working week and holidays (MS Project).
  Always shown first as a preview.  Activities are matched to BuildCore's by code (then by name), so importing an
  updated file again updates the same activities and keeps their DPR history; nothing in BuildCore is deleted.
  Activities are tied to BOQ items by the BOQ code (activity code, Text1 / a code in the name, or BOQ short code).
* Export to Microsoft Project XML with BuildCore's actual progress (actual dates, % complete from DPRs), so the
  planner can update the official programme.  P6 opens the same XML (File > Import > Microsoft Project).
* First programme from the BOQ: one activity per BOQ item that has none yet; duration = quantity / output per day,
  the output coming from the item's rate analysis norm (machine hours or labour days), links suggested inside each
  WBS group.  Preview first; the planner corrects it.
* Programme check: twelve checks (open ends, hard constraints, long durations and lags, negative float, activities
  without BOQ item, BOQ value without activity, out-of-sequence progress, old calculation, ...).
Only the schedule tables change (activities, wbs, act_links, sched_calendars, sched_holidays) and only when the
user presses Apply.  No money, stock or accounting is touched.
"""
import base64
import json
import math
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

import core
from core import ApiError, audit, ins, now, q, q1, today, upd, val
from api_inventory import api

VERSION = "2.50.0"
NS = "{http://schemas.microsoft.com/project}"
MSP_CT = {"0": "", "1": "", "2": "MSO", "3": "FNLT", "4": "SNET", "5": "", "6": "", "7": "FNLT"}
MSP_LT = {"0": "FF", "1": "FS", "2": "SF", "3": "SS"}
P6_CT = {"CS_MSO": "MSO", "CS_MANDSTART": "MSO", "CS_MSOA": "SNET", "CS_MEOB": "FNLT", "CS_MANDFIN": "FNLT",
         "CS_MEO": "FNLT"}
P6_LT = {"PR_FS": "FS", "PR_SS": "SS", "PR_FF": "FF", "PR_SF": "SF"}
TIME_UNITS = {"ls", "l.s.", "lump sum", "item", "job", "sum", "month", "months", "p.s.", "ps"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS prog_imports(id INTEGER PRIMARY KEY, project_id INTEGER, kind TEXT, filename TEXT,
  source TEXT, summary TEXT, ts TEXT, user_id INTEGER);
"""


def init_prog(c):
    c.executescript(SCHEMA)
    c.commit()


# ───────────────────────── reading files ─────────────────────────
def _d(s):
    """'2027-01-05T08:00:00' or '2027-01-05 08:00' -> '2027-01-05'."""
    if not s:
        return None
    s = str(s).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    return "%s-%s-%s" % m.groups() if m else None


def _pt_hours(s):
    """MS Project duration 'PT16H0M0S' (or 'P2DT4H...') -> hours."""
    if not s:
        return 0.0
    m = re.match(r"P(?:(\d+(?:\.\d+)?)D)?T?(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?", s)
    if not m:
        return 0.0
    dd, hh, mm, ss = (float(x or 0) for x in m.groups())
    return dd * 24 + hh + mm / 60 + ss / 3600


def _t(el, tag):
    x = el.find(NS + tag)
    return x.text if x is not None and x.text is not None else None


def parse_msp(data):
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise ApiError("This is not a readable MS Project XML file (%s). In MS Project use File > Save As > XML." % e)
    if not root.tag.endswith("Project"):
        raise ApiError("This XML is not an MS Project file (it starts with <%s>)." % root.tag.split("}")[-1])
    mpd = float(_t(root, "MinutesPerDay") or 480) / 60.0 or 8.0
    out = {"source": "MS Project XML", "project_name": _t(root, "Name") or _t(root, "Title") or "", "wbs": [],
           "tasks": [], "links": [], "calendar": None, "warnings": [], "hours_day": mpd}
    cal_uid = _t(root, "CalendarUID")
    for cal in root.iter(NS + "Calendar"):
        if cal_uid and _t(cal, "UID") != cal_uid:
            continue
        week = list("1111101")
        found = False
        holidays = []
        for wd in cal.iter(NS + "WeekDay"):
            dt = _t(wd, "DayType")
            working = (_t(wd, "DayWorking") or "0") == "1"
            if dt and dt != "0" and dt.isdigit():
                k = (int(dt) + 5) % 7          # MSP 1=Sunday ... 7=Saturday -> Mon=0
                week[k] = "1" if working else "0"
                found = True
            elif dt == "0" and not working:  # an old-style exception
                tp = wd.find(NS + "TimePeriod")
                if tp is not None:
                    holidays += _range(_d(_t(tp, "FromDate")), _d(_t(tp, "ToDate")), _t(wd, "Name"))
        for ex in cal.iter(NS + "Exception"):
            if (_t(ex, "DayWorking") or "0") == "1":
                continue
            tp = ex.find(NS + "TimePeriod")
            if tp is not None:
                holidays += _range(_d(_t(tp, "FromDate")), _d(_t(tp, "ToDate")), _t(ex, "Name"))
        out["calendar"] = {"name": _t(cal, "Name") or "Imported", "week": "".join(week) if found else None,
                           "holidays": holidays[:400]}
        break
    stack = {}
    for t in root.iter(NS + "Task"):
        uid = _t(t, "UID")
        name = (_t(t, "Name") or "").strip()
        if uid is None or uid == "0" or not name:
            continue
        lvl = int(_t(t, "OutlineLevel") or 1)
        summary = (_t(t, "Summary") or "0") == "1"
        parent = None
        for k in sorted(stack, reverse=True):
            if k < lvl:
                parent = stack[k]
                break
        if summary:
            code = _t(t, "WBS") or _t(t, "OutlineNumber") or uid
            out["wbs"].append({"key": "W" + uid, "parent": parent, "code": code, "name": name})
            stack = {k: v for k, v in stack.items() if k < lvl}
            stack[lvl] = "W" + uid
            continue
        text1 = None
        for ea in t.iter(NS + "ExtendedAttribute"):
            if _t(ea, "FieldID") == "188743731":
                text1 = _t(ea, "Value")
        hrs = _pt_hours(_t(t, "Duration"))
        bl = None
        for b in t.iter(NS + "Baseline"):
            if (_t(b, "Number") or "0") == "0":
                bl = b
        ct = MSP_CT.get(_t(t, "ConstraintType") or "0", "")
        task = {"key": uid, "code": (_t(t, "WBS") or "").strip(),
                "msp_id": _t(t, "ID"), "name": name, "wbs": parent, "dur": round(hrs / mpd, 2) if mpd else 0,
                "start": _d(_t(t, "Start")), "finish": _d(_t(t, "Finish")),
                "act_start": _d(_t(t, "ActualStart")), "act_finish": _d(_t(t, "ActualFinish")),
                "pct": float(_t(t, "PercentComplete") or 0), "milestone": (_t(t, "Milestone") or "0") == "1",
                "loe": False, "ct": ct, "cd": _d(_t(t, "ConstraintDate")) if ct else None,
                "bl_start": _d(_t(bl, "Start")) if bl is not None else None,
                "bl_finish": _d(_t(bl, "Finish")) if bl is not None else None, "boq_code": text1}
        out["tasks"].append(task)
        for pl in t.iter(NS + "PredecessorLink"):
            pu = _t(pl, "PredecessorUID")
            raw = float(_t(pl, "LinkLag") or 0)
            fmt = _t(pl, "LagFormat") or "7"
            if fmt in ("19", "20"):                            # percent lags: tenths of %, of the predecessor
                lag_days, pct = None, raw / 10.0
            else:                                              # tenths of a minute
                pct, lag_days = None, raw / 10.0 / 60.0 / mpd
            out["links"].append({"pred": pu, "succ": uid, "type": MSP_LT.get(_t(pl, "Type") or "1", "FS"),
                                 "lag": round(lag_days, 2) if lag_days is not None else None, "lag_pct": pct})
    # MS Project ids differ from WBS codes; use WBS for code, or the task ID when WBS repeats
    seen = {}
    for x in out["tasks"]:
        if not x["code"]:
            x["code"] = "T" + (x["msp_id"] or x["key"])
        seen[x["code"]] = seen.get(x["code"], 0) + 1
    for x in out["tasks"]:
        if seen[x["code"]] > 1:
            x["code"] = "%s-%s" % (x["code"], x["msp_id"] or x["key"])
    byk = {x["key"]: x for x in out["tasks"]}
    for l in out["links"]:
        if l["lag"] is None:
            p = byk.get(l["pred"])
            l["lag"] = round((p["dur"] if p else 0) * (l["lag_pct"] or 0) / 100.0, 2)
    out["links"] = [l for l in out["links"] if l["pred"] in byk and l["succ"] in byk]
    return out


def _range(a, b, name):
    if not a:
        return []
    b = b or a
    d0, d1 = date.fromisoformat(a), date.fromisoformat(b)
    if (d1 - d0).days > 60:
        return []
    return [((d0 + timedelta(days=i)).isoformat(), name or "Holiday") for i in range((d1 - d0).days + 1)]


def _xer_tables(text):
    tables, cur, fields = {}, None, None
    for line in text.splitlines():
        if not line:
            continue
        parts = line.rstrip("\r").split("\t")
        tag = parts[0]
        if tag == "%T":
            cur = parts[1].strip()
            tables[cur] = []
            fields = None
        elif tag == "%F":
            fields = parts[1:]
        elif tag == "%R" and cur and fields:
            tables[cur].append(dict(zip(fields, parts[1:])))
    return tables


def parse_xer(data):
    text = None
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not text or not text.lstrip().startswith("ERMHDR"):
        raise ApiError("This is not a Primavera P6 XER file (it must start with ERMHDR). In P6 use File > Export > XER.")
    T = _xer_tables(text)
    if not T.get("TASK"):
        raise ApiError("The XER file has no activities (TASK table).")
    projs = T.get("PROJECT") or [{}]
    pid = projs[0].get("proj_id")
    out = {"source": "Primavera P6 XER", "project_name": projs[0].get("proj_short_name", ""), "wbs": [], "tasks": [],
           "links": [], "calendar": None, "warnings": []}
    if len(projs) > 1:
        out["warnings"].append("The file holds %d projects; only %s is read." % (len(projs), out["project_name"]))
    hrs_cal = {}
    for cl in T.get("CALENDAR", []):
        try:
            hrs_cal[cl.get("clndr_id")] = float(cl.get("day_hr_cnt") or 8) or 8.0
        except ValueError:
            hrs_cal[cl.get("clndr_id")] = 8.0
    wbs_ids = set()
    for w in T.get("PROJWBS", []):
        if pid and w.get("proj_id") != pid:
            continue
        if w.get("proj_node_flag") == "Y":
            continue
        wbs_ids.add(w["wbs_id"])
    for w in T.get("PROJWBS", []):
        if w.get("wbs_id") in wbs_ids:
            par = w.get("parent_wbs_id")
            out["wbs"].append({"key": "W" + w["wbs_id"], "parent": "W" + par if par in wbs_ids else None,
                               "code": w.get("wbs_short_name") or w["wbs_id"], "name": w.get("wbs_name") or ""})
    keys = set()
    for t in T["TASK"]:
        if pid and t.get("proj_id") != pid:
            continue
        tt = t.get("task_type", "TT_Task")
        if tt == "TT_WBS":
            continue
        hd = hrs_cal.get(t.get("clndr_id"), 8.0)
        try:
            dur = float(t.get("target_drtn_hr_cnt") or 0) / hd
        except ValueError:
            dur = 0.0
        ct = P6_CT.get(t.get("cstr_type") or "", "")
        try:
            pct = float(t.get("phys_complete_pct") or 0)
        except ValueError:
            pct = 0.0
        x = {"key": t["task_id"], "code": (t.get("task_code") or t["task_id"]).strip(), "name": (t.get("task_name") or "").strip(),
             "wbs": "W" + t["wbs_id"] if t.get("wbs_id") in wbs_ids else None, "dur": round(dur, 2),
             "start": _d(t.get("target_start_date") or t.get("early_start_date")),
             "finish": _d(t.get("target_end_date") or t.get("early_end_date")),
             "act_start": _d(t.get("act_start_date")), "act_finish": _d(t.get("act_end_date")), "pct": pct,
             "milestone": tt in ("TT_Mile", "TT_FinMile"), "loe": tt == "TT_LOE", "ct": ct,
             "cd": _d(t.get("cstr_date")) if ct else None, "bl_start": None, "bl_finish": None, "boq_code": None}
        out["tasks"].append(x)
        keys.add(x["key"])
    cal_of = {t["task_id"]: t.get("clndr_id") for t in T["TASK"]}
    for p in T.get("TASKPRED", []):
        if p.get("task_id") in keys and p.get("pred_task_id") in keys:
            try:
                lag = float(p.get("lag_hr_cnt") or 0) / hrs_cal.get(cal_of.get(p["task_id"]), 8.0)
            except ValueError:
                lag = 0.0
            out["links"].append({"pred": p["pred_task_id"], "succ": p["task_id"], "type": P6_LT.get(p.get("pred_type"), "FS"),
                                 "lag": round(lag, 2)})
    out["warnings"].append("P6 calendars are not read: the project calendar in BuildCore is used.")
    return out


def read_file(a):
    fn = (a.get("filename") or "").lower()
    if not a.get("b64"):
        raise ApiError("Choose the programme file (MS Project .xml or Primavera .xer).")
    data = base64.b64decode(a["b64"].split(",")[-1])
    if fn.endswith(".mpp"):
        raise ApiError("BuildCore cannot read .mpp. In MS Project use File > Save As > XML (*.xml) and import that.")
    if fn.endswith(".xer") or data[:6] == b"ERMHDR":
        return parse_xer(data)
    if fn.endswith(".xml") or data.lstrip()[:1] == b"<":
        return parse_msp(data)
    raise ApiError("Use an MS Project .xml or a Primavera .xer file.")


# ───────────────────────── matching and applying ─────────────────────────
def _norm(s):
    return re.sub(r"[\s\-_./]", "", (s or "").upper())


def _boq_index(c, pid):
    rows = q(c, "SELECT id, code, description, unit, COALESCE(revised_qty, qty) qty FROM boq_items WHERE project_id=?", (pid,))
    idx = {}
    for b in rows:
        if b["code"]:
            idx.setdefault(_norm(b["code"]), b)
    try:   # 2.47 short codes (location + item)
        for r in q(c, "SELECT boq_item_id id, short_code FROM bx_line WHERE project_id=? AND short_code IS NOT NULL", (pid,)):
            b = next((x for x in rows if x["id"] == r["id"]), None)
            if b:
                idx.setdefault(_norm(r["short_code"]), b)
    except Exception:
        pass
    return idx


def _find_boq(idx, task):
    for cand in (task.get("boq_code"), task.get("code")):
        if cand and _norm(cand) in idx:
            return idx[_norm(cand)]
    m = re.match(r"\s*\[?([A-Za-z0-9][A-Za-z0-9.\-/]{0,15})\]?[\s:\-]+", task.get("name") or "")
    if m and _norm(m.group(1)) in idx:
        return idx[_norm(m.group(1))]
    return None


def plan_import(c, pid, P):
    acts = q(c, "SELECT * FROM activities WHERE project_id=?", (pid,))
    by_code = {}
    by_name = {}
    for x in acts:
        if x["code"]:
            by_code.setdefault(_norm(x["code"]), x)
        by_name.setdefault((x["name"] or "").strip().lower(), x)
    wbs_by_code = {_norm(w["code"]): w for w in q(c, "SELECT * FROM wbs WHERE project_id=?", (pid,)) if w["code"]}
    idx = _boq_index(c, pid)
    rows, used = [], set()
    for t in P["tasks"]:
        ex = by_code.get(_norm(t["code"])) or by_name.get(t["name"].lower())
        if ex and ex["id"] in used:
            ex = None
        if ex:
            used.add(ex["id"])
        b = _find_boq(idx, t)
        rows.append({"key": t["key"], "code": t["code"], "name": t["name"], "action": "update" if ex else "add",
                     "activity_id": ex["id"] if ex else None, "dur": t["dur"], "start": t["start"], "finish": t["finish"],
                     "boq": b["code"] if b else None, "boq_item_id": b["id"] if b else None,
                     "has_progress": bool(ex and ((ex["actual_qty"] or 0) > 0 or ex["actual_start"])),
                     "milestone": t["milestone"], "constraint": (t["ct"] + " " + (t["cd"] or "")).strip()})
    only_here = [{"code": x["code"], "name": x["name"]} for x in acts if x["id"] not in used]
    wb_new = [w for w in P["wbs"] if _norm(w["code"]) not in wbs_by_code]
    return rows, only_here, wb_new, wbs_by_code


@api("prog.import", "project", "edit")
def prog_import(c, u, a):
    """Preview (apply=0) or apply (apply=1) an MS Project XML / P6 XER programme on the project."""
    pid = int(a["project_id"])
    if not q1(c, "SELECT id FROM projects WHERE id=?", (pid,)):
        raise ApiError("Choose the project first.")
    P = read_file(a)
    if not P["tasks"]:
        raise ApiError("No activities found in the file.")
    rows, only_here, wb_new, wbs_by_code = plan_import(c, pid, P)
    summary = {"source": P["source"], "file_project": P["project_name"], "activities": len(rows),
               "add": sum(1 for r in rows if r["action"] == "add"), "update": sum(1 for r in rows if r["action"] == "update"),
               "links": len(P["links"]), "wbs": len(P["wbs"]), "wbs_new": len(wb_new),
               "boq_matched": sum(1 for r in rows if r["boq_item_id"]),
               "with_progress": sum(1 for r in rows if r["has_progress"]),
               "only_in_buildcore": len(only_here),
               "calendar": P["calendar"]["name"] if P.get("calendar") and P["calendar"].get("week") else None,
               "holidays": len(P["calendar"]["holidays"]) if P.get("calendar") else 0}
    out = {"summary": summary, "rows": rows, "only_in_buildcore": only_here[:200], "warnings": P["warnings"]}
    if not a.get("apply"):
        return out
    take_baseline = bool(a.get("baseline", 1))
    take_actuals = bool(a.get("actuals", 0))
    use_cal = bool(a.get("calendar", 1))
    # WBS
    wmap = {}
    for w in P["wbs"]:
        ex = wbs_by_code.get(_norm(w["code"]))
        if ex:
            wmap[w["key"]] = ex["id"]
    order = 0
    for w in P["wbs"]:
        order += 1
        if w["key"] in wmap:
            continue
        wid = ins(c, "wbs", {"project_id": pid, "code": w["code"], "name": w["name"] or w["code"], "parent_id": None,
                             "sort": order})
        wmap[w["key"]] = wid
    for w in P["wbs"]:
        if w["parent"] and w["parent"] in wmap:
            cur = q1(c, "SELECT parent_id FROM wbs WHERE id=?", (wmap[w["key"]],))
            if cur and not cur["parent_id"]:
                upd(c, "wbs", wmap[w["key"]], {"parent_id": wmap[w["parent"]]})
    # calendar
    cal_id = None
    if use_cal and P.get("calendar") and P["calendar"].get("week"):
        name = ("Imported: " + (P["calendar"]["name"] or ""))[:60]
        ex = q1(c, "SELECT id FROM sched_calendars WHERE project_id=? AND name=?", (pid, name))
        if ex:
            cal_id = ex["id"]
            upd(c, "sched_calendars", cal_id, {"week": P["calendar"]["week"], "hours_day": P.get("hours_day") or 8})
        else:
            cal_id = ins(c, "sched_calendars", {"project_id": pid, "name": name, "week": P["calendar"]["week"],
                                                "hours_day": P.get("hours_day") or 8, "is_default": 0,
                                                "notes": "From " + (a.get("filename") or "the imported file")})
        have = {r["date"] for r in q(c, "SELECT date FROM sched_holidays WHERE calendar_id=?", (cal_id,))}
        for d, nm in P["calendar"]["holidays"]:
            if d not in have:
                ins(c, "sched_holidays", {"calendar_id": cal_id, "date": d, "name": nm, "kind": "public"})
                have.add(d)
    # activities
    tmap = {}
    byk = {t["key"]: t for t in P["tasks"]}
    boq_rows = {b["id"]: b for b in q(c, "SELECT id, unit, COALESCE(revised_qty, qty) qty FROM boq_items WHERE project_id=?", (pid,))}
    for r in rows:
        t = byk[r["key"]]
        d = {"name": t["name"], "wbs_id": wmap.get(t["wbs"]) if t["wbs"] else None,
             "duration": 0 if t["milestone"] else t["dur"], "is_milestone": 1 if t["milestone"] else 0,
             "constraint_type": t["ct"] or None, "constraint_date": t["cd"] if t["ct"] else None}
        if t["loe"]:
            d["work_type"] = "loe"
        if cal_id:
            d["calendar_id"] = cal_id
        if r["action"] == "add" or not r["has_progress"]:
            d["planned_start"], d["planned_finish"] = t["start"], t["finish"]
        if r["action"] == "add":
            d.update({"project_id": pid, "code": t["code"]})
            if r["boq_item_id"]:
                b = boq_rows.get(r["boq_item_id"])
                d.update({"boq_item_id": r["boq_item_id"], "unit": b["unit"] if b else None, "planned_qty": b["qty"] if b else 0})
            if take_baseline:
                d["baseline_start"] = t["bl_start"] or t["start"]
                d["baseline_finish"] = t["bl_finish"] or t["finish"]
            if take_actuals:
                d["act_start_override"], d["act_finish_override"] = t["act_start"], t["act_finish"]
            tmap[t["key"]] = ins(c, "activities", d)
        else:
            ex = q1(c, "SELECT * FROM activities WHERE id=?", (r["activity_id"],))
            if r["boq_item_id"] and not ex["boq_item_id"]:
                b = boq_rows.get(r["boq_item_id"])
                d["boq_item_id"] = r["boq_item_id"]
                if not ex["unit"] and b:
                    d["unit"] = b["unit"]
                if not ex["planned_qty"] and b:
                    d["planned_qty"] = b["qty"]
            if take_baseline and not ex["baseline_start"] and (t["bl_start"] or t["start"]):
                d["baseline_start"] = t["bl_start"] or t["start"]
                d["baseline_finish"] = t["bl_finish"] or t["finish"]
            if take_actuals and not r["has_progress"]:
                d["act_start_override"], d["act_finish_override"] = t["act_start"], t["act_finish"]
            upd(c, "activities", ex["id"], d)
            tmap[t["key"]] = ex["id"]
    # links among the imported activities are replaced by the file's; links to other activities stay
    ids = list(tmap.values())
    if ids:
        marks = ",".join("?" * len(ids))
        c.execute("DELETE FROM act_links WHERE project_id=? AND pred_id IN (%s) AND succ_id IN (%s)" % (marks, marks),
                  [pid] + ids + ids)
    n_links = 0
    for l in P["links"]:
        if l["pred"] in tmap and l["succ"] in tmap and tmap[l["pred"]] != tmap[l["succ"]]:
            ins(c, "act_links", {"project_id": pid, "pred_id": tmap[l["pred"]], "succ_id": tmap[l["succ"]],
                                 "type": l["type"], "lag": l["lag"] or 0})
            n_links += 1
    summary["links_written"] = n_links
    summary["calendar_id"] = cal_id
    ins(c, "prog_imports", {"project_id": pid, "kind": "import", "filename": a.get("filename"), "source": P["source"],
                            "summary": json.dumps(summary), "ts": now(), "user_id": u["id"]})
    audit(c, u, "import", "programme", pid, {k: summary[k] for k in ("source", "add", "update", "links_written")})
    out["applied"] = True
    return out


# ───────────────────────── export to MS Project ─────────────────────────
def _esc(s):
    return (str(s if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _dt(d, end=False):
    return (d + ("T17:00:00" if end else "T08:00:00")) if d else ""


@api("prog.export", "project", "view")
def prog_export(c, u, a):
    """MS Project XML of the project's programme with actual progress (P6 imports the same file)."""
    pid = int(a["project_id"])
    p = q1(c, "SELECT * FROM projects WHERE id=?", (pid,))
    if not p:
        raise ApiError("Choose the project first.")
    hd = 8
    wbs = q(c, "SELECT * FROM wbs WHERE project_id=? ORDER BY COALESCE(sort,0), code, id", (pid,))
    acts = q(c, "SELECT a.*, b.code boq_code FROM activities a LEFT JOIN boq_items b ON b.id=a.boq_item_id "
                "WHERE a.project_id=? ORDER BY a.code, a.id", (pid,))
    links = q(c, "SELECT * FROM act_links WHERE project_id=?", (pid,))
    kids = {}
    for w in wbs:
        kids.setdefault(w["parent_id"], []).append(w)
    wids = {w["id"] for w in wbs}
    acts_by_w = {}
    for x in acts:
        acts_by_w.setdefault(x["wbs_id"] if x["wbs_id"] in wids else None, []).append(x)
    tasks = []
    uid = [0]
    act_uid = {}

    def add_act(x, lvl, outline):
        uid[0] += 1
        act_uid[x["id"]] = uid[0]
        s = x["es"] or x["planned_start"]
        f = x["ef"] or x["planned_finish"]
        ast = x["act_start_override"] or x["actual_start"]
        afn = x["act_finish_override"] or x["actual_finish"]
        dur = 0 if x["is_milestone"] else (x["duration"] if x["duration"] is not None else
                                            (max(1, (date.fromisoformat(f) - date.fromisoformat(s)).days + 1) if s and f else 1))
        tasks.append({"uid": uid[0], "name": x["name"], "lvl": lvl, "outline": outline, "summary": 0, "wbs": x["code"] or "",
                      "start": s, "finish": f, "dur": dur, "ms": x["is_milestone"], "ast": ast, "afn": afn,
                      "pct": int(round(x["pct_complete"] or 0)), "ct": x["constraint_type"], "cd": x["constraint_date"],
                      "bs": x["baseline_start"], "bf": x["baseline_finish"], "aid": x["id"], "text1": x["boq_code"] or ""})

    def add_wbs(w, lvl, outline):
        uid[0] += 1
        tasks.append({"uid": uid[0], "name": w["name"] or w["code"], "lvl": lvl, "outline": outline, "summary": 1,
                      "wbs": w["code"] or ""})
        n = 0
        for x in acts_by_w.get(w["id"], []):
            n += 1
            add_act(x, lvl + 1, "%s.%d" % (outline, n))
        for k in kids.get(w["id"], []):
            n += 1
            add_wbs(k, lvl + 1, "%s.%d" % (outline, n))
    n = 0
    for w in kids.get(None, []) + [w for w in wbs if w["parent_id"] and w["parent_id"] not in wids]:
        n += 1
        add_wbs(w, 1, str(n))
    for x in acts_by_w.get(None, []):
        n += 1
        add_act(x, 1, str(n))
    preds = {}
    for l in links:
        if l["pred_id"] in act_uid and l["succ_id"] in act_uid:
            preds.setdefault(l["succ_id"], []).append(l)
    rev_ct = {"MSO": 2, "FNLT": 7, "SNET": 4}
    rev_lt = {"FF": 0, "FS": 1, "SF": 2, "SS": 3}
    start = p.get("ntp_date") or p.get("start_date") or today()
    X = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
         '<Project xmlns="http://schemas.microsoft.com/project">',
         "<SaveVersion>14</SaveVersion>", "<Name>%s</Name>" % _esc((p["code"] or "") + " " + (p["name"] or "")),
         "<Title>%s</Title>" % _esc(p["name"]), "<StartDate>%s</StartDate>" % _dt(start),
         "<MinutesPerDay>%d</MinutesPerDay>" % (hd * 60), "<MinutesPerWeek>%d</MinutesPerWeek>" % (hd * 60 * 6),
         "<DaysPerMonth>26</DaysPerMonth>", "<StatusDate>%s</StatusDate>" % _dt(p.get("data_date") or today(), True),
         "<CalendarUID>1</CalendarUID>",
         "<ExtendedAttributes><ExtendedAttribute><FieldID>188743731</FieldID><FieldName>Text1</FieldName>"
         "<Alias>BOQ item</Alias></ExtendedAttribute></ExtendedAttributes>",
         "<Calendars><Calendar><UID>1</UID><Name>BuildCore 6-day week</Name><IsBaseCalendar>1</IsBaseCalendar><WeekDays>"]
    week = (q1(c, "SELECT week FROM sched_calendars WHERE is_default=1 AND (project_id IS NULL OR project_id=?) ORDER BY project_id DESC", (pid,)) or {"week": "1111101"})["week"] or "1111101"
    for k in range(7):
        dt = (k + 1) % 7 + 1          # Mon=0 -> 2 ... Sun=6 -> 1
        working = week[k] == "1"
        X.append("<WeekDay><DayType>%d</DayType><DayWorking>%d</DayWorking>%s</WeekDay>" % (
            dt, 1 if working else 0,
            "<WorkingTimes><WorkingTime><FromTime>08:00:00</FromTime><ToTime>12:00:00</ToTime></WorkingTime>"
            "<WorkingTime><FromTime>13:00:00</FromTime><ToTime>17:00:00</ToTime></WorkingTime></WorkingTimes>" if working else ""))
    X.append("</WeekDays></Calendar></Calendars><Tasks>")
    X.append("<Task><UID>0</UID><ID>0</ID><Name>%s</Name><OutlineLevel>0</OutlineLevel><Summary>1</Summary></Task>" % _esc(p["name"]))
    for i, t in enumerate(tasks, 1):
        e = ["<Task><UID>%d</UID><ID>%d</ID><Name>%s</Name><WBS>%s</WBS><OutlineNumber>%s</OutlineNumber>"
             "<OutlineLevel>%d</OutlineLevel><Summary>%d</Summary>" % (t["uid"], i, _esc(t["name"]), _esc(t["wbs"]),
                                                                       t["outline"], t["lvl"], t["summary"])]
        if not t["summary"]:
            e.append("<Milestone>%d</Milestone>" % (1 if t["ms"] else 0))
            e.append("<Duration>PT%dH0M0S</Duration><DurationFormat>7</DurationFormat>" % int(round((t["dur"] or 0) * hd)))
            if t["start"]:
                e.append("<Start>%s</Start>" % _dt(t["start"]))
            if t["finish"]:
                e.append("<Finish>%s</Finish>" % _dt(t["finish"], True))
            if t["ast"]:
                e.append("<ActualStart>%s</ActualStart>" % _dt(t["ast"]))
            if t["afn"]:
                e.append("<ActualFinish>%s</ActualFinish>" % _dt(t["afn"], True))
            e.append("<PercentComplete>%d</PercentComplete>" % (100 if t["afn"] else min(99, t["pct"]) if t["ast"] else 0))
            ct = rev_ct.get((t["ct"] or "").upper())
            if ct and t["cd"]:
                e.append("<ConstraintType>%d</ConstraintType><ConstraintDate>%s</ConstraintDate>" % (ct, _dt(t["cd"])))
            for l in preds.get(t["aid"], []):
                e.append("<PredecessorLink><PredecessorUID>%d</PredecessorUID><Type>%d</Type><LinkLag>%d</LinkLag>"
                         "<LagFormat>7</LagFormat></PredecessorLink>" % (act_uid[l["pred_id"]], rev_lt.get(l["type"], 1),
                                                                          int(round((l["lag"] or 0) * hd * 600))))
            if t["text1"]:
                e.append("<ExtendedAttribute><FieldID>188743731</FieldID><Value>%s</Value></ExtendedAttribute>" % _esc(t["text1"]))
            if t["bs"] and t["bf"]:
                e.append("<Baseline><Number>0</Number><Start>%s</Start><Finish>%s</Finish></Baseline>" % (_dt(t["bs"]), _dt(t["bf"], True)))
        e.append("</Task>")
        X.append("".join(e))
    X.append("</Tasks></Project>")
    xml = "\n".join(X)
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", (p["code"] or "project")) + "_programme_" + today() + ".xml"
    ins(c, "prog_imports", {"project_id": pid, "kind": "export", "filename": name, "source": "MS Project XML",
                            "summary": json.dumps({"tasks": len(tasks), "links": sum(len(v) for v in preds.values())}),
                            "ts": now(), "user_id": u["id"]})
    return {"filename": name, "b64": base64.b64encode(xml.encode("utf-8")).decode("ascii"), "tasks": len(tasks),
            "links": sum(len(v) for v in preds.values())}


# ───────────────────────── first programme from the BOQ ─────────────────────────
def _output_per_day(c, boq_id, hours_day, crew):
    """Output per working day of one crew/machine set, from the item's rate analysis norm."""
    ra = q1(c, "SELECT norm_id, result FROM ra_analyses WHERE boq_item_id=? ORDER BY (status='approved') DESC, id DESC LIMIT 1", (boq_id,))
    rows, per = [], 1.0
    if ra and ra["result"]:
        try:
            r = json.loads(ra["result"])
            rows, per = r.get("rows") or [], float(r.get("per_qty") or 1)
        except Exception:
            rows = []
    if not rows and ra and ra["norm_id"]:
        n = q1(c, "SELECT per_qty FROM ra_norms WHERE id=?", (ra["norm_id"],))
        per = float((n or {}).get("per_qty") or 1)
        rows = [dict(r) for r in q(c, "SELECT kind, qty FROM ra_norm_lines WHERE norm_id=?", (ra["norm_id"],))]
    if not rows:
        return None, "no rate analysis"
    eq = [float(r.get("qty") or 0) for r in rows if (r.get("kind") or "").upper() == "E" and (r.get("unit") in (None, "hour", "hr", "hrs"))]
    eq = [x for x in eq if x > 0]
    if eq:
        return per / max(eq) * hours_day, "machines: %g h per %g (busiest machine)" % (max(eq), per)
    lab = sum(float(r.get("qty") or 0) for r in rows if (r.get("kind") or "").upper() == "L")
    if lab > 0:
        return per / lab * crew, "labour: %g days per %g, crew of %d" % (lab, per, crew)
    return None, "norm has no labour or machine lines"


@api("prog.from_boq", "project", "edit")
def prog_from_boq(c, u, a):
    """First programme from the BOQ: preview (apply=0) or create (apply=1) one activity per BOQ item without one."""
    pid = int(a["project_id"])
    p = q1(c, "SELECT * FROM projects WHERE id=?", (pid,))
    if not p:
        raise ApiError("Choose the project first.")
    hours_day = float(a.get("hours_day") or 8)
    crew = int(a.get("crew") or 15)
    default_days = float(a.get("default_days") or 5)
    link_mode = a.get("links") or "ss"
    start = p.get("ntp_date") or p.get("start_date") or today()
    try:
        import api_sched
        cd = api_sched.contract_dates(c, p)
        finish = cd.get("revised")
    except Exception:
        finish = p.get("completion_date") or p.get("end_date")
    span = max(30, int(((date.fromisoformat(finish) - date.fromisoformat(start)).days if finish else 365) * 6 / 7))
    have = {r["boq_item_id"] for r in q(c, "SELECT boq_item_id FROM activities WHERE project_id=? AND boq_item_id IS NOT NULL", (pid,))}
    items = q(c, "SELECT b.*, w.code wbs_code, w.name wbs_name FROM boq_items b LEFT JOIN wbs w ON w.id=b.wbs_id "
                 "WHERE b.project_id=? ORDER BY COALESCE(w.sort,0), w.code, b.id", (pid,))
    share_base = sum(((b["revised_qty"] if b["revised_qty"] is not None else b["qty"]) or 0) *
                     ((b["revised_rate"] if b["revised_rate"] is not None else b["rate"]) or 0) for b in items
                     if (b["unit"] or "").strip().lower() not in TIME_UNITS)
    rows = []
    for b in items:
        if b["id"] in have:
            continue
        qty = b["revised_qty"] if b["revised_qty"] is not None else (b["qty"] or 0)
        unit = (b["unit"] or "").strip().lower()
        if unit in TIME_UNITS:
            dur, basis, loe = span, "time-related item: runs for the contract period", True
        else:
            out, basis = _output_per_day(c, b["id"], hours_day, crew)
            loe = False
            if out and qty:
                dur = max(1, math.ceil(qty / out))
                basis = "%s → %s %s/day" % (basis, round(out, 1), b["unit"] or "")
                if dur > span:
                    basis += " (more than the contract period: plan more crews)"
            elif share_base and qty:
                v = qty * ((b["revised_rate"] if b["revised_rate"] is not None else b["rate"]) or 0)
                dur = int(max(default_days, min(span * 0.6, round(span * 4 * v / share_base))))
                basis = "guessed (%s): %d days from its share of the BOQ value" % (basis, dur)
            else:
                dur = default_days
                basis = "guessed (%s): %g days" % (basis, default_days)
        rows.append({"boq_item_id": b["id"], "boq": b["code"], "name": (b["description"] or "")[:120], "unit": b["unit"],
                     "qty": qty, "value": round(qty * ((b["revised_rate"] if b["revised_rate"] is not None else b["rate"]) or 0), 2),
                     "dur": dur, "basis": basis, "loe": loe, "wbs_id": b["wbs_id"], "wbs": b["wbs_code"] or "",
                     "guessed": basis.startswith("guessed")})
    out = {"rows": rows, "start": start, "contract_finish": finish, "span_days": span, "existing": len(have),
           "guessed": sum(1 for r in rows if r["guessed"])}
    if not a.get("apply"):
        return out
    if not rows:
        raise ApiError("Every BOQ item already has an activity.")
    wid0 = None
    if any(r["wbs_id"] is None for r in rows):
        ex = q1(c, "SELECT id FROM wbs WHERE project_id=? AND code='BOQ'", (pid,))
        wid0 = ex["id"] if ex else ins(c, "wbs", {"project_id": pid, "code": "BOQ", "name": "Work from the BOQ", "sort": 999})
    codes = {(r["code"] or "").upper() for r in q(c, "SELECT code FROM activities WHERE project_id=?", (pid,))}
    groups = {}
    for r in rows:
        code = "A-" + (r["boq"] or str(r["boq_item_id"]))
        k = 2
        while code.upper() in codes:
            code = "A-%s-%d" % (r["boq"] or r["boq_item_id"], k)
            k += 1
        codes.add(code.upper())
        aid = ins(c, "activities", {"project_id": pid, "wbs_id": r["wbs_id"] or wid0, "code": code, "name": r["name"],
                                    "boq_item_id": r["boq_item_id"], "unit": r["unit"], "planned_qty": r["qty"],
                                    "duration": r["dur"], "planned_start": start, "work_type": "loe" if r["loe"] else None,
                                    "weight": r["value"]})
        r["activity_id"] = aid
        if not r["loe"]:
            groups.setdefault(r["wbs_id"] or wid0, []).append(r)
    n_links = 0
    if link_mode in ("ss", "fs"):
        for g in groups.values():
            for a1, a2 in zip(g, g[1:]):
                lag = 0 if link_mode == "fs" else max(1, round(a1["dur"] * 0.3))
                ins(c, "act_links", {"project_id": pid, "pred_id": a1["activity_id"], "succ_id": a2["activity_id"],
                                     "type": "FS" if link_mode == "fs" else "SS", "lag": lag})
                n_links += 1
    out.update({"applied": True, "created": len(rows), "links": n_links})
    ins(c, "prog_imports", {"project_id": pid, "kind": "from_boq", "filename": None, "source": "BOQ",
                            "summary": json.dumps({"created": len(rows), "links": n_links}), "ts": now(), "user_id": u["id"]})
    audit(c, u, "create", "programme from BOQ", pid, {"activities": len(rows), "links": n_links})
    return out


# ───────────────────────── programme check ─────────────────────────
@api("prog.check", "project", "view")
def prog_check(c, u, a):
    """About twelve checks on the project's programme, each with the activities it concerns."""
    pid = int(a["project_id"])
    p = q1(c, "SELECT * FROM projects WHERE id=?", (pid,))
    if not p:
        raise ApiError("Choose the project first.")
    acts = q(c, "SELECT * FROM activities WHERE project_id=?", (pid,))
    links = q(c, "SELECT * FROM act_links WHERE project_id=?", (pid,))
    has_pred = {l["succ_id"] for l in links}
    has_succ = {l["pred_id"] for l in links}
    by = {x["id"]: x for x in acts}
    loe = lambda x: (x["work_type"] or "") == "loe" or (x["unit"] or "").strip().lower() in TIME_UNITS
    real = [x for x in acts if not loe(x)]
    first = min((x["planned_start"] or "9999" for x in real), default=None)
    last = max((x["planned_finish"] or "" for x in real), default=None)
    lab = lambda x: {"id": x["id"], "code": x["code"], "name": x["name"]}
    checks = []

    def add(key, title, items, level, fix, help_):
        checks.append({"key": key, "title": title, "count": len(items), "items": items[:50], "level": level if items else "ok",
                       "fix": fix, "help": help_})
    add("no_pred", "Activities with no predecessor (open start)",
        [lab(x) for x in real if x["id"] not in has_pred and not (x["is_milestone"] and x["planned_start"] == first)
         and x["planned_start"] != first], "warn", "logic", "Every activity except the first needs a predecessor, or the dates hang on typed dates.")
    add("no_succ", "Activities with no successor (open end)",
        [lab(x) for x in real if x["id"] not in has_succ and x["planned_finish"] != last], "warn", "logic",
        "An open end hides delay: nothing after it moves when it slips.")
    add("hard", "Hard constraints (must start on / finish no later than)",
        [dict(lab(x), note=(x["constraint_type"] or "") + " " + (x["constraint_date"] or "")) for x in acts
         if (x["constraint_type"] or "").upper() in ("MSO", "FNLT")], "warn", "programme",
        "Hard constraints override the logic and can hide negative float. Keep them for contract milestones.")
    add("long", "Long activities (more than 60 working days)",
        [dict(lab(x), note="%g days" % x["duration"]) for x in real if (x["duration"] or 0) > 60], "info", "programme",
        "Split long activities by location or stage so progress and delay show early.")
    add("lags", "Long lags (over 20 days) or negative lags",
        [{"id": l["succ_id"], "code": (by.get(l["succ_id"]) or {}).get("code"), "name": (by.get(l["succ_id"]) or {}).get("name"),
          "note": "%s lag %g after %s" % (l["type"], l["lag"] or 0, (by.get(l["pred_id"]) or {}).get("code") or "")}
         for l in links if abs(l["lag"] or 0) > 20 or (l["lag"] or 0) < 0], "info", "logic",
        "A long lag is usually hidden work: make it an activity (curing, approval, mobilisation).")
    add("neg_float", "Negative total float (finish later than the contract allows)",
        [dict(lab(x), note="%g days" % x["tf"]) for x in acts if x["tf"] is not None and x["tf"] < 0], "bad", "cpm",
        "Recover time (more crews, overlap) or claim extension of time.")
    add("no_boq", "Activities with no BOQ item (progress cannot be valued)",
        [lab(x) for x in real if not x["boq_item_id"] and not x["is_milestone"]], "info", "programme",
        "Tie each work activity to its BOQ item so DPR quantities give earned value.")
    covered = {x["boq_item_id"] for x in acts if x["boq_item_id"]}
    miss = q(c, "SELECT id, code, description, COALESCE(revised_qty, qty) * COALESCE(revised_rate, rate) v FROM boq_items "
                "WHERE project_id=? ORDER BY v DESC", (pid,))
    miss = [m for m in miss if m["id"] not in covered and (m["v"] or 0) > 0]
    tot = val(c, "SELECT SUM(COALESCE(revised_qty, qty) * COALESCE(revised_rate, rate)) FROM boq_items WHERE project_id=?", (pid,)) or 0
    mv = sum(m["v"] for m in miss)
    add("boq_no_act", "BOQ value with no activity (%s%% of the BOQ)" % (round(100 * mv / tot, 1) if tot else 0),
        [{"id": None, "code": m["code"], "name": (m["description"] or "")[:80], "note": "%.0f" % m["v"]} for m in miss],
        "warn", "from_boq", "Use 'First programme from the BOQ' to add them, or link them to activities.")
    add("no_qty", "Activities with a BOQ item but no planned quantity",
        [lab(x) for x in real if x["boq_item_id"] and not (x["planned_qty"] or 0)], "warn", "programme",
        "Without the planned quantity, DPR progress cannot give % complete.")
    oos = []
    for l in links:
        s, pr = by.get(l["succ_id"]), by.get(l["pred_id"])
        if s and pr and l["type"] == "FS" and (s["actual_start"] or s["act_start_override"]) and not (pr["actual_finish"] or pr["act_finish_override"]) \
                and not (pr["actual_qty"] and pr["planned_qty"] and pr["actual_qty"] >= pr["planned_qty"]):
            oos.append(dict(lab(s), note="started before %s finished" % (pr["code"] or pr["name"])))
    add("oos", "Out-of-sequence progress", oos, "info", "logic",
        "Work started before its finish-to-start predecessor finished: change the link to SS with a lag, or check the DPR.")
    run = q1(c, "SELECT * FROM sched_runs WHERE project_id=? ORDER BY id DESC LIMIT 1", (pid,))
    stale = []
    if not run:
        stale = [{"id": None, "code": "", "name": "The schedule has never been calculated"}]
    elif (run["data_date"] or "") < (date.today() - timedelta(days=14)).isoformat():
        stale = [{"id": None, "code": "", "name": "Last calculated with data date %s" % run["data_date"]}]
    add("stale", "Schedule not updated in the last 14 days", stale, "warn", "calc",
        "Calculate the schedule at least every week, after the DPRs are approved.")
    ct = []
    try:
        import api_sched
        cd = api_sched.contract_dates(c, p)
        if not cd.get("revised"):
            ct = [{"id": None, "code": "", "name": "Contract completion date is not set"}]
        elif run and run["finish"] and run["finish"] > cd["revised"]:
            ct = [{"id": None, "code": "", "name": "Forecast finish %s is after contract completion %s" % (run["finish"], cd["revised"])}]
    except Exception:
        pass
    add("contract", "Contract time", ct, "bad" if ct and "after" in ct[0]["name"] else "warn", "contract",
        "Set NTP, time for completion and LD in Contract time; then the finish is checked every run.")
    score = sum(1 for x in checks if x["level"] == "ok")
    return {"checks": checks, "passed": score, "total": len(checks), "activities": len(acts), "links": len(links),
            "history": q(c, "SELECT kind, filename, source, ts FROM prog_imports WHERE project_id=? ORDER BY id DESC LIMIT 10", (pid,))}
