"""BuildCore 2.43.0 — Past prices on purchase requests and purchase orders.

Asked by SULAV: when a purchase request or PO is made for an item already bought for the project, link the price: if it
was always bought at one price, use that price; if prices differ, show the latest three and value the request from them.
  * price.recent: per material, the project's posted GRN prices (latest first), with the company's other projects as a
    fall-back when the project never bought it.
  * Suggested price: one price when every purchase was at the same rate; otherwise the average of the latest three.
  * doc.save for a purchase request (est_rate) or PO (rate) fills a blank rate on a material line with the suggested
    price. A rate that was typed is never changed. Setting pr_price_fill (default on).
  * A purchase request raised from a requisition (mrq.to_pr) was valued at the material's standard rate; it now takes the
    suggested price where the material was bought before.
Nothing posted is changed; no table is changed.
"""
import core
from core import ApiError, q, r2, setting
import api_inventory as inv
from api_inventory import api

VERSION = "2.43.0"
FLAG = "_bco243"
EPS = 0.005


def _f(x, d=0.0):
    try:
        return float(x) if x not in (None, "") else d
    except (TypeError, ValueError):
        return d


def fill_on(c):
    return (setting(c, "pr_price_fill") or "1") == "1"


def _history(c, project_id, material_ids=None, limit=200):
    cond, p = ["g.status='posted'", "l.material_id IS NOT NULL", "COALESCE(l.accepted_qty, l.received_qty, 0) > 0"], []
    if project_id is not None:
        cond.append("g.project_id=?")
        p.append(int(project_id))
    if material_ids:
        cond.append("l.material_id IN (%s)" % ",".join("?" * len(material_ids)))
        p += [int(m) for m in material_ids]
    return q(c, "SELECT l.material_id, l.rate, g.date, g.no, g.project_id, pr.code project, pa.name vendor, "
                "COALESCE(l.accepted_qty, l.received_qty) qty FROM grn_lines l JOIN grn g ON g.id=l.grn_id "
                "LEFT JOIN parties pa ON pa.id=g.vendor_id LEFT JOIN projects pr ON pr.id=g.project_id WHERE " + " AND ".join(cond) +
             " ORDER BY g.date DESC, g.id DESC, l.id DESC LIMIT %d" % int(limit), p)


def summarise(rows, scope):
    """rows: one material's purchases, latest first."""
    if not rows:
        return None
    rates = [r2(_f(r["rate"])) for r in rows]
    distinct = sorted(set(rates))
    last3 = rows[:3]
    if len(distinct) == 1:
        sug, basis = distinct[0], "bought %d time%s, always at %s" % (len(rows), "" if len(rows) == 1 else "s", "{:,.2f}".format(distinct[0]))
    else:
        sug = r2(sum(_f(r["rate"]) for r in last3) / len(last3))
        basis = "prices differ: average of the latest %d (%s)" % (len(last3), ", ".join("{:,.2f}".format(_f(r["rate"])) for r in last3))
    return {"suggested": sug, "single": len(distinct) == 1, "basis": basis, "scope": scope, "count": len(rows),
            "latest": [{"date": r["date"], "rate": r2(_f(r["rate"])), "grn": r["no"], "vendor": r["vendor"], "project": r["project"],
                        "qty": r["qty"]} for r in last3]}


def recent(c, project_id, material_ids=None):
    out = {}
    by = {}
    for r in _history(c, project_id, material_ids, 2000):
        by.setdefault(r["material_id"], []).append(r)
    for m, rows in by.items():
        out[m] = summarise(rows, "project")
    want = [int(m) for m in material_ids] if material_ids else None
    missing = [m for m in want if m not in out] if want else None
    if missing is None or missing:
        other = {}
        for r in _history(c, None, missing, 4000):
            if r["material_id"] in out:
                continue
            other.setdefault(r["material_id"], []).append(r)
        for m, rows in other.items():
            out[m] = summarise(rows, "company")
    return out


@api("price.recent", "procurement", "view")
def price_recent(c, u, a):
    pid = a.get("project_id")
    mids = a.get("material_ids")
    res = recent(c, int(pid) if pid else None, mids)
    return {"materials": {str(k): v for k, v in res.items()}, "fill": fill_on(c)}


def _w_doc_save(orig):
    def doc_save(c, u, a):
        t = a.get("type")
        if t in ("pr", "po") and fill_on(c):
            fld = "est_rate" if t == "pr" else "rate"
            h = a.get("header") or {}
            pid = h.get("project_id")
            if not pid and h.get("id"):
                pid = core.val(c, "SELECT project_id FROM %s WHERE id=?" % ("pr" if t == "pr" else "po"), (int(h["id"]),))
            lines = [dict(l) for l in (a.get("lines") or [])]
            mids = [int(l["material_id"]) for l in lines if l.get("material_id") and _f(l.get(fld)) <= EPS]
            if pid and mids:
                rec = recent(c, int(pid), mids)
                for l in lines:
                    if l.get("material_id") and _f(l.get(fld)) <= EPS:
                        s = rec.get(int(l["material_id"]))
                        if s:
                            l[fld] = s["suggested"]
                a = dict(a, lines=lines)
        return orig(c, u, a)
    return doc_save


def _w_mrq_to_pr(orig):
    def mrq_to_pr(c, u, a):
        res = orig(c, u, a)
        try:
            if fill_on(c) and res and res.get("id"):
                prid = int(res["id"])
                pid = core.val(c, "SELECT project_id FROM pr WHERE id=?", (prid,))
                lines = q(c, "SELECT l.id, l.material_id, l.est_rate, m.standard_rate FROM pr_lines l LEFT JOIN materials m ON m.id=l.material_id "
                             "WHERE l.pr_id=? AND l.material_id IS NOT NULL", (prid,))
                rec = recent(c, int(pid), [l["material_id"] for l in lines]) if pid and lines else {}
                for l in lines:
                    s = rec.get(l["material_id"])
                    if s and (_f(l["est_rate"]) <= EPS or abs(_f(l["est_rate"]) - _f(l["standard_rate"])) <= EPS):
                        c.execute("UPDATE pr_lines SET est_rate=? WHERE id=?", (s["suggested"], l["id"]))
        except Exception:
            pass
        return res
    return mrq_to_pr


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


@api("price.settings_save", "procurement", "approve")
def price_settings_save(c, u, a):
    v = "1" if a.get("fill") in (1, True, "1", "true") else "0"
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('pr_price_fill', ?)", (v,))
    core.audit(c, u, "settings", "pr_price_fill", 0, {"value": v})
    return {"fill": v == "1"}


def init_prices(c):
    c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES('pr_price_fill', '1')")
    c.commit()
    _wrap("doc.save", _w_doc_save)
    _wrap("mrq.to_pr", _w_mrq_to_pr)
