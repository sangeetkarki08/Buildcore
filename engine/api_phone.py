"""BuildCore 2.57 "Site on the phone" (M1, K1, B4, K3).

* Phone page (#/phone): big buttons for the site entries - today's DPR (copied from yesterday), goods received with
  challan / vehicle / weighbridge numbers and a photo of the challan, material issue, machine hours, petty cash slip,
  site issue with a photo and the phone's location, attendance.  Every entry goes through the same actions as the
  desktop screens (same rights, same checks, same numbering); photos are made smaller on the phone before sending.
  Works on the server edition (and on the office network); the desktop screens are unchanged.
* DPR copy yesterday (K1): the DPR prefill now also brings yesterday's work lines (activity and location, quantity
  left blank) when the schedule has nothing planned for the day, and when it has, the lines of yesterday not planned.
* GRN at the gate (B4): weighbridge ticket number on the GRN (new column), challan photo attached to the GRN.
* Quick add (K3): petty cash slip, attendance, site issue and the phone page added to "+ New".
Nothing posted changes; no switch is needed (only new screens and one new optional column).
"""
from datetime import date, timedelta

import core
from core import ApiError, audit, ins, now, q, q1, setting, today, upd, val
import api_inventory as inv
from api_inventory import api

VERSION = "2.57.0"
FLAG = "_bco257"


def _f(x, d=0.0):
    try:
        return float(x) if x not in (None, "") else d
    except (TypeError, ValueError):
        return d


def _has(c, t):
    return bool(q1(c, "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)))


def _call(c, u, name, args):
    f, module, action, _p = inv.FUNCS[name]
    if module:
        core.require(u, module, action)
    return f(c, u, dict(args))


def _pid(a):
    pid = int(a.get("project_id") or 0)
    if not pid:
        raise ApiError("Choose a project.")
    return pid


@api("ph.home", "project", "view")
def ph_home(c, u, a):
    pid = _pid(a)
    t = today()
    p = q1(c, "SELECT id, code, name FROM projects WHERE id=?", (pid,))
    if not p:
        raise ApiError("Project not found.")
    dpr = q1(c, "SELECT id, no, status, shift FROM dpr WHERE project_id=? AND date=? ORDER BY id LIMIT 1", (pid, t))
    mine = {}
    for k, sql in (("grn", "SELECT COUNT(*) FROM grn WHERE project_id=? AND date=? AND created_by=?"),
                   ("issue", "SELECT COUNT(*) FROM issues WHERE project_id=? AND date=? AND created_by=?"),
                   ("log", "SELECT COUNT(*) FROM logsheets WHERE project_id=? AND date=? AND created_by=?"),
                   ("photo", "SELECT COUNT(*) FROM files WHERE project_id=? AND date=? AND user_id=?")):
        try:
            mine[k] = val(c, sql, (pid, t, u["id"])) or 0
        except Exception:
            mine[k] = 0
    stores = q(c, "SELECT id, code, name FROM stores WHERE project_id=? AND COALESCE(type,'main')<>'transit' ORDER BY type<>'main', name", (pid,))
    used = q(c, "SELECT m.id, m.code, m.name, m.unit FROM materials m WHERE m.id IN (SELECT l.material_id FROM grn_lines l JOIN grn g ON g.id=l.grn_id "
                "WHERE g.project_id=? UNION SELECT l.material_id FROM issue_lines l JOIN issues i ON i.id=l.issue_id WHERE i.project_id=?) ORDER BY m.name", (pid, pid))
    eq = q(c, "SELECT id, code, name, meter FROM equipment WHERE COALESCE(active,1)=1 AND project_id=? ORDER BY code", (pid,))
    imp = q(c, "SELECT id, holder FROM mn_imprest WHERE project_id=? AND active=1", (pid,)) if _has(c, "mn_imprest") else []
    trades = q(c, "SELECT id, name FROM trades ORDER BY name") if _has(c, "trades") else []
    return {"project": p, "today": t, "dpr": dpr, "trades": trades, "mine": mine, "stores": stores, "materials_used": used, "equipment": eq, "imprests": imp,
            "rights": {k: core.can(u, *k.split(".")) for k in ("project.edit", "inventory.edit", "equipment.edit", "accounts.edit")}}


@api("ph.vendors", "inventory", "view")
def ph_vendors(c, u, a):
    pid = int(a.get("project_id") or 0)
    recent = q(c, "SELECT DISTINCT p.id, p.name FROM grn g JOIN parties p ON p.id=g.vendor_id WHERE g.project_id=? ORDER BY g.id DESC LIMIT 15", (pid,)) if pid else []
    allv = q(c, "SELECT id, name FROM parties WHERE COALESCE(blacklisted,0)=0 AND COALESCE(active,1)=1 AND kind='vendor' ORDER BY name LIMIT 800")
    return {"recent": recent, "all": allv}


@api("ph.grn", "inventory", "edit")
def ph_grn(c, u, a):
    """One call from the gate: make the GRN (draft) and post it when asked and allowed."""
    pid = _pid(a)
    lines = [l for l in (a.get("lines") or []) if l.get("material_id") and _f(l.get("qty")) > 0]
    if not lines:
        raise ApiError("Add at least one material with a quantity.")
    if not a.get("vendor_id"):
        raise ApiError("Choose the supplier.")
    header = {"project_id": pid, "store_id": int(a.get("store_id") or 0) or None, "vendor_id": int(a["vendor_id"]), "date": a.get("date") or today(),
              "challan_no": (a.get("challan_no") or "").strip() or None, "vehicle_no": (a.get("vehicle_no") or "").strip() or None,
              "weighbridge_no": (a.get("weighbridge_no") or "").strip() or None, "remarks": (a.get("remarks") or "").strip() or "Entered on the phone"}
    if not header["store_id"]:
        st = q1(c, "SELECT id FROM stores WHERE project_id=? AND type='main' ORDER BY id LIMIT 1", (pid,))
        header["store_id"] = st["id"] if st else None
    ls = [{"material_id": int(l["material_id"]), "received_qty": _f(l["qty"]), "accepted_qty": _f(l.get("accepted"), _f(l["qty"])),
           "rate": _f(l.get("rate"))} for l in lines]
    r = _call(c, u, "doc.save", {"type": "grn", "header": header, "lines": ls})
    gid = r.get("id") if isinstance(r, dict) else r
    out = {"id": gid, "posted": False}
    if a.get("post"):
        p = _call(c, u, "grn.post", {"id": gid})
        out.update(posted=True, no=(p or {}).get("no"))
    return out


@api("ph.issue", "inventory", "edit")
def ph_issue(c, u, a):
    pid = _pid(a)
    lines = [l for l in (a.get("lines") or []) if l.get("material_id") and _f(l.get("qty")) > 0]
    if not lines:
        raise ApiError("Add at least one material with a quantity.")
    header = {"project_id": pid, "store_id": int(a.get("store_id") or 0) or None, "date": a.get("date") or today(),
              "issued_to": (a.get("issued_to") or "").strip() or None, "remarks": (a.get("remarks") or "").strip() or "Entered on the phone"}
    if not header["store_id"]:
        st = q1(c, "SELECT id FROM stores WHERE project_id=? AND type='main' ORDER BY id LIMIT 1", (pid,))
        header["store_id"] = st["id"] if st else None
    ls = [{"material_id": int(l["material_id"]), "qty": _f(l["qty"]), "target": "equipment" if l.get("equipment_id") else ("overhead" if l.get("target") == "overhead" else "boq"),
           "boq_item_id": int(l["boq_item_id"]) if l.get("boq_item_id") else None,
           "equipment_id": int(l["equipment_id"]) if l.get("equipment_id") else None} for l in lines]
    r = _call(c, u, "doc.save", {"type": "issue", "header": header, "lines": ls})
    iid = r.get("id") if isinstance(r, dict) else r
    out = {"id": iid, "posted": False}
    if a.get("post"):
        p = _call(c, u, "issue.post", {"id": iid})
        out.update(posted=True, no=(p or {}).get("no"))
    return out


@api("ph.stock", "inventory", "view")
def ph_stock(c, u, a):
    pid = _pid(a)
    return {"rows": q(c, "SELECT b.material_id, m.name, m.unit, SUM(b.qty) qty FROM stock_balances b JOIN materials m ON m.id=b.material_id "
                         "WHERE b.project_id=? GROUP BY b.material_id HAVING SUM(b.qty)>0 ORDER BY m.name", (pid,))}


@api("ph.boq", "project", "view")
def ph_boq(c, u, a):
    pid = _pid(a)
    return {"rows": q(c, "SELECT id, code, description name, unit FROM boq_items WHERE project_id=? ORDER BY code", (pid,)),
            "activities": q(c, "SELECT id, code, name, location, boq_item_id FROM activities WHERE project_id=? AND actual_finish IS NULL ORDER BY code", (pid,))}


# ───────────────────────── K1: DPR copy yesterday ─────────────────────────
def _w_prefill(orig):
    def dpr_prefill(c, u, a):
        d = orig(c, u, a)
        prev = d.get("previous_dpr")
        if prev:
            have = {(w.get("activity_id"), w.get("boq_item_id")) for w in d.get("work") or []}
            extra = [{"activity_id": w["activity_id"], "boq_item_id": w["boq_item_id"], "location": w["location"], "planned_qty": w["planned_qty"],
                      "actual_qty": "", "from_yesterday": True}
                     for w in q(c, "SELECT * FROM dpr_work WHERE dpr_id=?", (prev,)) if (w["activity_id"], w["boq_item_id"]) not in have]
            d["work"] = (d.get("work") or []) + extra
            pr = q1(c, "SELECT date, no FROM dpr WHERE id=?", (prev,))
            d["previous_label"] = (pr["no"] or "") + " of " + pr["date"] if pr else None
        return d
    return dpr_prefill


def _wrap(name, factory):
    cur = inv.FUNCS.get(name)
    if not cur or getattr(cur[0], FLAG, False):
        return
    w = factory(cur[0])
    for f in [x for x in dir(cur[0]) if x.startswith("_bco")]:
        setattr(w, f, getattr(cur[0], f))
    setattr(w, FLAG, True)
    w._orig = cur[0]
    inv.FUNCS[name] = (w, cur[1], cur[2], cur[3])


def init_phone(c):
    cols = [r[1] for r in c.execute("PRAGMA table_info(grn)")]
    if cols and "weighbridge_no" not in cols:
        c.execute("ALTER TABLE grn ADD COLUMN weighbridge_no TEXT")
    c.commit()
    hf = inv.DOCS["grn"][6]
    if isinstance(hf, list) and "weighbridge_no" not in hf:
        hf.append("weighbridge_no")
    _wrap("dpr.prefill", _w_prefill)
