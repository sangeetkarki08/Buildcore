"""BuildCore 2.58 "Subcontracts and billing" (E1, E2, E3, F1, F2, F3, F4, B3, D7).

* Subcontract bills (E1, E2): the running-bill prefill now suggests this period's quantity per item from the DPR work
  done on that subcontractor's packages / work fronts (accepted quantity where accepted), or, when no front is tied
  to the subcontractor, from the verified joint measurements; and shows, per BOQ item, what the client has certified
  to us.  Switch sb_on (off on existing data) puts the suggestion in the quantity box; until then it is shown only.
  "Billed to the subcontractor more than the client certified" is warned on the bill check and, when accounts turns
  on sb_block, stops approval unless a reason is given.
* Final account (E3): per work order - work billed, retention held, advances and materials still with the
  subcontractor, defects period end - and a release checklist (defects period over, materials and advances
  recovered, no claims open, NOC received).  It is a statement and checklist; the release itself is paid as before.
* Labour contractors (D7): DPR gang hours of each labour contractor not yet billed; "Make the bill" makes a draft
  running bill on the contractor's labour-supply work order (or a draft order "Labour supply as per DPR" for
  approval when there is none), so the normal submit / approve / post steps follow.
* Prepare IPC (F1): one screen - verified measurement quantities this period, retention, VAT, TDS from the project
  terms, advance recovery at the agreed % (capped at the open advance), price adjustment from the formula (shown,
  claimed as before) - and "Make the draft IPC".
* IPC chase (F2): days each client takes to pay and days late against the contract's payment days.
* Retention and advance ledger (F3): per contract (client and subcontractors): retention held / released / open,
  advances given / recovered / open.
* Variation tracker (F4): instruction, priced, submitted, approved, billed, with ageing and time claimed.
* Rate contracts (B3): agreed rate per supplier and material for a period (one project or all); a PO or GRN line
  for that supplier with no rate takes it, and GRNs above the agreed rate are listed.
"""
import json
from datetime import date, timedelta

import core
from core import ApiError, audit, ins, now, q, q1, setting, today, upd, val
import api_inventory as inv
from api_inventory import api

VERSION = "2.58.0"
FLAG = "_bco258"
EPS = 0.0005

SCHEMA = """
CREATE TABLE IF NOT EXISTS sb_final(order_id INTEGER PRIMARY KEY, checks TEXT, note TEXT, status TEXT DEFAULT 'open', user_id INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS sb_override(id INTEGER PRIMARY KEY, bill_id INTEGER, reason TEXT, user_id INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS rc_contracts(id INTEGER PRIMARY KEY, party_id INTEGER NOT NULL, material_id INTEGER NOT NULL, project_id INTEGER,
  rate REAL NOT NULL, valid_from TEXT, valid_to TEXT, max_qty REAL, ref TEXT, note TEXT, active INTEGER DEFAULT 1, created_by INTEGER, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_rc ON rc_contracts(party_id, material_id);
"""
CHECKS = [("defects", "Defects liability period is over"), ("materials", "All materials issued to the subcontractor are recovered or returned"),
          ("advances", "All advances are recovered"), ("claims", "No claims or disputes open"), ("noc", "No-objection letter (NOC) received"),
          ("measure", "Final joint measurement signed")]


def _f(x, d=0.0):
    try:
        return float(x) if x not in (None, "") else d
    except (TypeError, ValueError):
        return d


def r2(x):
    return round(_f(x) + 0.0, 2)


def r4(x):
    return round(_f(x) + 0.0, 4)


def _set(c, k, v):
    c.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))


def on(c):
    return setting(c, "sb_on") == "1"


def _has(c, t):
    return bool(q1(c, "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)))


def _call(c, u, name, args):
    f, module, action, _p = inv.FUNCS[name]
    if module:
        core.require(u, module, action)
    return f(c, u, dict(args))


def certified_qty(c, boq_id):
    return _f(val(c, "SELECT SUM(l.qty) FROM ipc_lines l JOIN ipc i ON i.id=l.ipc_id WHERE i.status='certified' AND l.boq_item_id=?", (boq_id,)))


SAME_UNIT = "LOWER(TRIM(COALESCE(oi.unit,'')))=LOWER(TRIM(COALESCE((SELECT unit FROM boq_items WHERE id=oi.boq_item_id),'')))"


def same_unit(c, oi):
    """A work-order line measured in the BOQ item's own unit (amount lines such as labour in Rs are not compared)."""
    if not oi or not oi["boq_item_id"]:
        return False
    bu = val(c, "SELECT unit FROM boq_items WHERE id=?", (oi["boq_item_id"],)) or ""
    return (oi["unit"] or "").strip().lower() == bu.strip().lower()


def sub_billed_all(c, boq_id, exclude_bill=0):
    return _f(val(c, "SELECT SUM(bi.qty) FROM sc_bill_items bi JOIN sc_bills b ON b.id=bi.bill_id JOIN sc_order_items oi ON oi.id=bi.order_item_id "
                     "WHERE oi.boq_item_id=? AND b.status<>'cancelled' AND b.id<>? AND " + SAME_UNIT, (boq_id, exclude_bill or 0)))


# ───────────────────────── E1 / E2: bill suggestion and check ─────────────────────────
def done_by_party(c, o, boq_id, upto):
    """DPR quantity on the subcontractor's packages / fronts (accepted where accepted)."""
    if not _has(c, "udpr_fronts"):
        return None
    fronts = [r["id"] for r in q(c, "SELECT id FROM udpr_fronts WHERE project_id=? AND party_id=?", (o["project_id"], o["party_id"]))]
    if not fronts:
        return None
    ph = ",".join("?" * len(fronts))
    v = val(c, "SELECT SUM(COALESCE(x.accepted_qty, w.actual_qty)) FROM dpr_work w JOIN dpr d ON d.id=w.dpr_id JOIN udpr_work x ON x.work_id=w.id "
               "WHERE d.project_id=? AND d.status='approved' AND d.date<=? AND w.boq_item_id=? AND (x.package_id IN (%s) OR x.front_id IN (%s))" % (ph, ph),
            [o["project_id"], upto, boq_id] + fronts + fronts)
    return _f(v)


def measured_qty(c, boq_id, upto):
    return _f(val(c, "SELECT SUM(l.qty) FROM measurement_lines l JOIN measurements m ON m.id=l.measurement_id WHERE m.status='verified' AND "
                     "l.boq_item_id=? AND m.date<=?", (boq_id, upto)))


def suggest(c, o, items, upto, bill_id=0):
    out = []
    for it in items:
        oi = q1(c, "SELECT * FROM sc_order_items WHERE id=?", (it["order_item_id"],))
        bid = oi and oi["boq_item_id"]
        prev = _f(it.get("prev_qty"))
        row = dict(it, boq_item_id=bid, suggested=0.0, basis="no BOQ item on this line", certified=None, sub_billed_all=None)
        if bid and not same_unit(c, oi):
            row["basis"] = "amount line (unit differs from the BOQ item); enter the amount"
        elif bid:
            dp = done_by_party(c, o, bid, upto)
            if dp is not None and dp > EPS:
                done, basis = dp, "DPR on this subcontractor's fronts"
            else:
                done, basis = measured_qty(c, bid, upto), "verified joint measurement (all work on the item)"
            others = sub_billed_all(c, bid, bill_id) - prev          # billed on other work orders for the same item
            if basis.startswith("verified"):
                done = max(0.0, done - max(0.0, others))
            sug = max(0.0, min(_f(oi["qty"]) - prev, done - prev))
            row.update(suggested=r4(sug), done=r4(done), basis=basis, certified=r4(certified_qty(c, bid)), sub_billed_all=r4(sub_billed_all(c, bid, bill_id)))
        out.append(row)
    return out


def _w_prefill(orig):
    def sco_bill_prefill(c, u, a):
        d = orig(c, u, a)
        try:
            d["items"] = suggest(c, d["order"], d["items"], a.get("date") or today())
            if on(c):
                for it in d["items"]:
                    it["qty"] = it["suggested"]
            d["suggest_on"] = on(c)
        except Exception as e:
            d["suggest_error"] = str(e)[:200]
        return d
    return sco_bill_prefill


def bill_check(c, bill_id):
    b = q1(c, "SELECT * FROM sc_bills WHERE id=?", (bill_id,))
    if not b:
        raise ApiError("Bill not found.")
    out = []
    for it in q(c, "SELECT bi.*, oi.boq_item_id, oi.description, oi.unit FROM sc_bill_items bi JOIN sc_order_items oi ON oi.id=bi.order_item_id WHERE bi.bill_id=?", (bill_id,)):
        if not same_unit(c, it):
            continue
        cum_all = sub_billed_all(c, it["boq_item_id"], bill_id) + _f(it["qty"])
        cert = certified_qty(c, it["boq_item_id"])
        meas = measured_qty(c, it["boq_item_id"], b["date"])
        if cum_all > cert + EPS:
            out.append({"item": it["description"], "unit": it["unit"], "subs_cumulative": r4(cum_all), "client_certified": r4(cert), "measured": r4(meas),
                        "over": r4(cum_all - cert), "amount": r2((cum_all - cert) * _f(it["rate"])),
                        "level": "high" if cum_all > meas + EPS else "medium"})
    return out


def _w_approve(orig):
    def sco_bill_approve(c, u, a):
        if setting(c, "sb_block") == "1":
            over = bill_check(c, int(a["id"]))
            if over:
                reason = (a.get("override_reason") or "").strip()
                if not reason:
                    raise ApiError("Subcontractors would be paid for more than the client has certified on %d item(s) (%s). Give a reason to approve anyway."
                                   % (len(over), "; ".join("%s +%s" % (x["item"], x["over"]) for x in over[:3])))
                ins(c, "sb_override", {"bill_id": int(a["id"]), "reason": reason, "user_id": u["id"], "ts": now()})
        return orig(c, u, a)
    return sco_bill_approve


@api("sb.bill_check", "commercial", "view")
def sb_bill_check(c, u, a):
    return {"rows": bill_check(c, int(a["id"])), "block": setting(c, "sb_block") == "1"}


@api("sb.overview", "commercial", "view")
def sb_overview(c, u, a):
    """Per work-order item: billed to the subcontractor against certified by the client (E2), for one project."""
    pid = int(a.get("project_id") or 0)
    rows = []
    for it in q(c, "SELECT oi.*, o.no, o.party_id, pa.name party, b.code bcode FROM sc_order_items oi JOIN sc_orders o ON o.id=oi.order_id "
                   "LEFT JOIN parties pa ON pa.id=o.party_id LEFT JOIN boq_items b ON b.id=oi.boq_item_id WHERE o.project_id=? AND o.status NOT IN ('draft','cancelled') ORDER BY o.no, oi.id", (pid,)):
        billed = _f(val(c, "SELECT SUM(bi.qty) FROM sc_bill_items bi JOIN sc_bills b ON b.id=bi.bill_id WHERE bi.order_item_id=? AND b.status<>'cancelled'", (it["id"],)))
        cmp_ = same_unit(c, it)
        cert = certified_qty(c, it["boq_item_id"]) if cmp_ else None
        allb = sub_billed_all(c, it["boq_item_id"]) if cmp_ else None
        rows.append({"order": it["no"], "party": it["party"], "item": it["description"], "boq": it["bcode"], "unit": it["unit"], "order_qty": it["qty"],
                     "billed": r4(billed), "all_subs": r4(allb) if allb is not None else None, "certified": r4(cert) if cert is not None else None,
                     "over": r4(allb - cert) if allb is not None and cert is not None and allb > cert + EPS else 0})
    return {"rows": rows, "block": setting(c, "sb_block") == "1", "on": on(c)}


# ───────────────────────── E3: final account ─────────────────────────
@api("sb.final", "commercial", "view")
def sb_final(c, u, a):
    o = q1(c, "SELECT o.*, pa.name party, p.code pcode, p.dlp_months, p.completion_date FROM sc_orders o LEFT JOIN parties pa ON pa.id=o.party_id "
              "LEFT JOIN projects p ON p.id=o.project_id WHERE o.id=?", (int(a["order_id"]),))
    if not o:
        raise ApiError("Work order not found.")
    bills = q(c, "SELECT no, date, status, gross, retention, advance_recovery, material_recovery, net FROM sc_bills WHERE order_id=? AND status<>'cancelled' ORDER BY date", (o["id"],))
    posted = [b for b in bills if b["status"] == "posted"]
    ret_held = r2(sum(_f(b["retention"]) for b in posted))
    ret_rel = r2(_f(val(c, "SELECT SUM(l.debit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id JOIN accounts ac ON ac.id=l.account_id "
                           "WHERE ac.role='retention_payable' AND l.party_id=? AND v.status='posted' AND l.debit>0", (o["party_id"],))))
    try:
        import api_finance as F
        adv = F.party_advance_balance(c, o["party_id"], "purchase")
    except Exception:
        adv = None
    custody = []
    try:
        import api_exec as X
        for mid, r in X._custody(c, o["id"], today()).items():
            if r["balance"] > EPS:
                m = q1(c, "SELECT name, unit FROM materials WHERE id=?", (mid,))
                custody.append({"material": m["name"], "unit": m["unit"], "qty": r4(r["balance"]), "value": r2(r["balance_value"])})
    except Exception:
        pass
    end = o["end_date"] or o["completion_date"]
    dlp_end = None
    if end:
        d0 = date.fromisoformat(end[:10])
        mm = int(_f(o["dlp_months"], 12))
        y, m = d0.year + (d0.month - 1 + mm) // 12, (d0.month - 1 + mm) % 12 + 1
        dlp_end = date(y, m, min(d0.day, 28)).isoformat()
    st = q1(c, "SELECT * FROM sb_final WHERE order_id=?", (o["id"],)) or {}
    ticks = json.loads(st.get("checks") or "{}")
    auto = {"defects": bool(dlp_end and dlp_end <= today()), "materials": not custody, "advances": adv is not None and adv <= 0.5}
    items = [{"key": k, "label": l, "auto": auto.get(k), "ticked": bool(ticks.get(k)) or bool(auto.get(k))} for k, l in CHECKS]
    return {"order": {k: o[k] for k in ("id", "no", "party", "pcode", "type", "title", "retention_pct", "end_date", "status")}, "bills": bills,
            "work_billed": r2(sum(_f(b["gross"]) for b in posted)), "retention_held": ret_held, "retention_released": ret_rel,
            "retention_open": r2(ret_held - ret_rel), "advance_open": r2(adv) if adv is not None else None, "custody": custody, "dlp_end": dlp_end,
            "checks": items, "ready": all(x["ticked"] for x in items), "status": st.get("status") or "open", "note": st.get("note")}


@api("sb.final_save", "commercial", "edit")
def sb_final_save(c, u, a):
    oid = int(a["order_id"])
    ticks = {k: 1 for k, _l in CHECKS if (a.get("checks") or {}).get(k)}
    status = a.get("status") if a.get("status") in ("open", "ready", "closed") else "open"
    c.execute("INSERT INTO sb_final(order_id, checks, note, status, user_id, ts) VALUES(?,?,?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET "
              "checks=excluded.checks, note=excluded.note, status=excluded.status, user_id=excluded.user_id, ts=excluded.ts",
              (oid, json.dumps(ticks), a.get("note"), status, u["id"], now()))
    audit(c, u, "final_account", "sc_orders", oid, {"status": status, "checks": list(ticks)})
    return sb_final(c, u, {"order_id": oid})


# ───────────────────────── D7: labour contractors from the DPR ─────────────────────────
def _amount_line(i):
    return (i["unit"] or "").lower() in ("rs", "amount", "npr") and abs(_f(i["rate"]) - 1) < EPS


def _lab_by_boq(c, pid, party, upto):
    """DPR gang amounts of one contractor by BOQ item (through the DPR line's activity); None = no BOQ item."""
    out = {}
    for r in q(c, "SELECT a.boq_item_id, SUM(l.amount) amount FROM dpr_labour l JOIN dpr d ON d.id=l.dpr_id LEFT JOIN activities a ON a.id=l.activity_id "
                  "WHERE d.project_id=? AND d.status='approved' AND d.date<=? AND l.party_id=? GROUP BY a.boq_item_id", (pid, upto, party)):
        out[r["boq_item_id"]] = out.get(r["boq_item_id"], 0) + _f(r["amount"])
    return out


@api("sb.labour", "commercial", "view")
def sb_labour(c, u, a):
    pid = int(a.get("project_id") or 0)
    upto = a.get("to") or today()
    rows = []
    for r in q(c, "SELECT l.party_id, pa.name party, SUM(l.count) heads, SUM(l.count*l.hours) hours, SUM(l.amount) amount, MIN(d.date) first, MAX(d.date) last "
                  "FROM dpr_labour l JOIN dpr d ON d.id=l.dpr_id LEFT JOIN parties pa ON pa.id=l.party_id WHERE d.project_id=? AND d.status='approved' "
                  "AND d.date<=? AND l.party_id IS NOT NULL GROUP BY l.party_id ORDER BY party", (pid, upto)):
        billed = _f(val(c, "SELECT SUM(b.gross) FROM sc_bills b JOIN sc_orders o ON o.id=b.order_id WHERE o.project_id=? AND o.party_id=? AND o.type='labour' "
                           "AND b.status<>'cancelled'", (pid, r["party_id"])))
        order = q1(c, "SELECT id, no, status FROM sc_orders WHERE project_id=? AND party_id=? AND type='labour' AND status NOT IN ('cancelled','closed') ORDER BY id DESC LIMIT 1",
                   (pid, r["party_id"]))
        rows.append(dict(r, amount=r2(r["amount"]), billed=r2(billed), not_billed=r2(_f(r["amount"]) - billed), order=order))
    return {"rows": rows, "to": upto}


@api("sb.labour_bill", "commercial", "edit")
def sb_labour_bill(c, u, a):
    """Draft running bill on the contractor's labour work order, one amount line per BOQ item, for the DPR amount not yet billed."""
    pid, party = int(a["project_id"]), int(a["party_id"])
    upto = a.get("to") or today()
    d = {r["party_id"]: r for r in sb_labour(c, u, {"project_id": pid, "to": upto})["rows"]}.get(party)
    if not d or d["not_billed"] <= 0.5:
        raise ApiError("Nothing on the DPR to bill for this contractor.")
    by = _lab_by_boq(c, pid, party, upto)
    o = q1(c, "SELECT * FROM sc_orders WHERE project_id=? AND party_id=? AND type='labour' AND status NOT IN ('cancelled','closed') ORDER BY id DESC LIMIT 1", (pid, party))
    if not o:
        mult = _f(a.get("ceiling_times"), 1.5)
        names = {b["id"]: b for b in q(c, "SELECT id, code, description FROM boq_items WHERE project_id=?", (pid,))}
        items = [{"boq_item_id": k, "description": "Labour as per DPR - " + ((names.get(k) or {}).get("code") or "") + " " + ((names.get(k) or {}).get("description") or "")
                  if k else "Labour as per DPR - not tied to a BOQ item", "unit": "Rs", "qty": r2(max(v, 1) * mult), "rate": 1} for k, v in by.items() if v > 0.5]
        r = _call(c, u, "sco.save", {"header": {"project_id": pid, "party_id": party, "type": "labour", "title": "Labour supply as per DPR",
                                                "date": today(), "retention_pct": _f(a.get("retention_pct"), 0), "remarks": "Made from the DPR gang hours (2.58); amounts are ceilings"},
                                     "items": items})
        oid = r.get("id") if isinstance(r, dict) else r
        return {"order_created": oid, "message": "Draft work order made with %d amount line(s) for approval. Check the ceilings, approve it, then make the bill." % len(items)}
    if o["status"] != "approved":
        raise ApiError("Work order %s is %s; approve it first." % (o["no"] or o["id"], o["status"]))
    lines = [i for i in q(c, "SELECT * FROM sc_order_items WHERE order_id=? ORDER BY id", (o["id"],)) if _amount_line(i)]
    if not lines:
        raise ApiError("Work order %s has no amount line (unit Rs, rate 1). Bill it on the Subcontract screen by its items." % (o["no"] or o["id"]))
    bill, missing = [], 0.0
    for k, v in by.items():
        ln = next((i for i in lines if i["boq_item_id"] == k), None) or (next((i for i in lines if not i["boq_item_id"]), None) if not k else None)
        if not ln:
            missing += v
            continue
        done = _f(val(c, "SELECT SUM(bi.qty) FROM sc_bill_items bi JOIN sc_bills b ON b.id=bi.bill_id WHERE bi.order_item_id=? AND b.status<>'cancelled'", (ln["id"],)))
        q_ = r2(min(v - done, _f(ln["qty"]) - done))
        if q_ > 0.5:
            bill.append({"order_item_id": ln["id"], "qty": q_})
    if not bill:
        raise ApiError("Nothing to bill on work order %s (the DPR amount is on BOQ items it has no line for, or the ceilings are used up)." % o["no"])
    r = _call(c, u, "sco.bill_save", {"header": {"order_id": o["id"], "date": today(), "period_to": upto, "party_bill_no": a.get("party_bill_no")}, "items": bill})
    amt = r2(sum(x["qty"] for x in bill))
    msg = "Draft running bill made on %s for %s." % (o["no"], amt)
    if missing > 0.5:
        msg += " %s of DPR labour is on BOQ items the work order has no line for; add those lines to bill it." % r2(missing)
    return {"bill_id": r.get("id") if isinstance(r, dict) else r, "amount": amt, "message": msg}



# ───────────────────────── F1: prepare IPC ─────────────────────────
@api("sb.ipc_prepare", "commercial", "view")
def sb_ipc_prepare(c, u, a):
    pid = int(a["project_id"])
    p = q1(c, "SELECT * FROM projects WHERE id=?", (pid,))
    import api_cash as CA
    t = CA.terms(c, p)
    lines = _call(c, u, "ipc.prefill", {"project_id": pid})
    boq = {b["id"]: b for b in q(c, "SELECT id, code, description, unit FROM boq_items WHERE project_id=?", (pid,))}
    for l in lines:
        b = boq.get(l["boq_item_id"]) or {}
        l.update(code=b.get("code"), description=b.get("description"), unit=b.get("unit"), amount=r2(_f(l["qty"]) * _f(l["rate"])))
    gross = r2(sum(l["amount"] for l in lines))
    last = q1(c, "SELECT * FROM ipc WHERE project_id=? ORDER BY date DESC, id DESC LIMIT 1", (pid,))
    client = last["client_id"] if last else val(c, "SELECT id FROM parties WHERE kind='client' ORDER BY id LIMIT 1")
    adv_open = 0.0
    try:
        import api_finance as F
        adv_open = F.party_advance_balance(c, client, "sales") if client else 0.0
    except Exception:
        pass
    adv = r2(min(max(0.0, adv_open), gross * _f(t["advance_recovery_pct"]) / 100))
    ret = r2(gross * _f(t["retention_pct"]) / 100)
    vat = r2(gross * _f(t["vat_pct"]) / 100)
    tds = r2(gross * _f(t["tds_pct"]) / 100)
    pa = None
    try:
        pa = _call(c, u, "dc.pa_calc", {"project_id": pid})
        pa = {"total": pa.get("total"), "rows": len(pa.get("rows") or [])}
    except Exception as e:
        pa = {"total": None, "note": str(e)[:160]}
    waiting = q(c, "SELECT no, status, date FROM ipc WHERE project_id=? AND status IN ('draft','submitted') ORDER BY date", (pid,))
    return {"lines": lines, "gross": gross, "terms": t, "client_id": client, "client": val(c, "SELECT name FROM parties WHERE id=?", (client,)) if client else None,
            "retention": ret, "vat": vat, "tds": tds, "advance_open": r2(adv_open), "advance_recovery": adv, "net": r2(gross + vat - ret - tds - adv),
            "price_adjustment": pa, "waiting": waiting, "last": {k: last[k] for k in ("no", "date", "status")} if last else None}


@api("sb.ipc_make", "commercial", "edit")
def sb_ipc_make(c, u, a):
    pid = int(a["project_id"])
    d = sb_ipc_prepare(c, u, {"project_id": pid})
    if not d["lines"]:
        raise ApiError("No verified measurement quantity to bill.")
    if not d["client_id"]:
        raise ApiError("No client found. Add the client (Parties, kind client) first.")
    t = d["terms"]
    r = _call(c, u, "ipc.save", {"header": {"project_id": pid, "client_id": d["client_id"], "date": a.get("date") or today(), "period_to": a.get("period_to") or today(),
                                            "retention_pct": t["retention_pct"], "tds_pct": t["tds_pct"], "vat_rate": t["vat_pct"],
                                            "advance_recovery": a.get("advance_recovery", d["advance_recovery"]), "remarks": "Prepared from verified measurements (2.58)"},
                                 "lines": [{"boq_item_id": l["boq_item_id"], "qty": l["qty"]} for l in d["lines"]]})
    return {"id": r["id"]}


# ───────────────────────── F2: IPC chase, days to pay ─────────────────────────
@api("sb.pay_days", "commercial", "view")
def sb_pay_days(c, u, a):
    rows = q(c, "SELECT i.party_id, pa.name client, i.id, i.no, i.date, i.payable, i.project_id, p.pay_days, "
                "(SELECT MAX(al.date) FROM allocations al WHERE al.invoice_id=i.id AND al.active=1) paid_on, "
                "(SELECT SUM(al.amount) FROM allocations al WHERE al.invoice_id=i.id AND al.active=1) paid "
                "FROM invoices i LEFT JOIN parties pa ON pa.id=i.party_id LEFT JOIN projects p ON p.id=i.project_id WHERE i.kind='sales' AND i.status='posted'")
    by = {}
    t = today()
    for r in rows:
        x = by.setdefault(r["party_id"], {"client": r["client"], "invoices": 0, "paid": 0, "days": 0.0, "weight": 0.0, "late": 0, "open": 0.0, "oldest_open": None})
        x["invoices"] += 1
        terms = int(_f(r["pay_days"], 28))
        if r["paid_on"] and _f(r["paid"]) >= _f(r["payable"]) - 0.5:
            dd = (date.fromisoformat(r["paid_on"][:10]) - date.fromisoformat(r["date"][:10])).days
            x["paid"] += 1
            x["days"] += dd * _f(r["payable"])
            x["weight"] += _f(r["payable"])
            if dd > terms:
                x["late"] += 1
        else:
            x["open"] += _f(r["payable"]) - _f(r["paid"])
            age = (date.fromisoformat(t) - date.fromisoformat(r["date"][:10])).days
            x["oldest_open"] = max(x["oldest_open"] or 0, age)
    out = []
    for pid_, x in by.items():
        out.append({"client": x["client"], "invoices": x["invoices"], "paid_invoices": x["paid"], "avg_days": round(x["days"] / x["weight"], 1) if x["weight"] else None,
                    "paid_late": x["late"], "open": r2(x["open"]), "oldest_open_days": x["oldest_open"]})
    return {"rows": sorted(out, key=lambda r: -(r["avg_days"] or 0))}


# ───────────────────────── F3: retention and advance ledger ─────────────────────────
@api("sb.ledger", "accounts", "view")
def sb_ledger(c, u, a):
    pid = a.get("project_id")
    cond, p = "", []
    if pid:
        cond, p = " AND COALESCE(l.project_id, v.project_id)=?", [int(pid)]
    out = []
    for role, side, label in (("retention_receivable", 1, "Retention held by the client"), ("retention_payable", -1, "Retention we hold"),
                              ("client_advance", -1, "Advance from the client"), ("supplier_advance", 1, "Advance to suppliers"),
                              ("subcon_advance", 1, "Advance to subcontractors")):
        for r in q(c, "SELECT l.party_id, pa.name party, pa.kind, SUM(l.debit) dr, SUM(l.credit) cr, MIN(v.date) first, MAX(v.date) last FROM voucher_lines l "
                      "JOIN vouchers v ON v.id=l.voucher_id JOIN accounts ac ON ac.id=l.account_id LEFT JOIN parties pa ON pa.id=l.party_id "
                      "WHERE ac.role=? AND v.status='posted'" + cond + " GROUP BY l.party_id ORDER BY party", [role] + p):
            held = r2(r["dr"] if side == 1 else r["cr"])
            back = r2(r["cr"] if side == 1 else r["dr"])
            if abs(held) < 0.5 and abs(back) < 0.5:
                continue
            out.append({"kind": label, "party": r["party"] or "(no party)", "held": held, "released": back, "open": r2(held - back), "first": r["first"], "last": r["last"]})
    pr = q1(c, "SELECT completion_date, dlp_months, retention_release_pct FROM projects WHERE id=?", (int(pid),)) if pid else None
    return {"rows": out, "project": pr}


# ───────────────────────── F4: variation tracker ─────────────────────────
@api("sb.variations", "commercial", "view")
def sb_variations(c, u, a):
    pid = int(a["project_id"])
    t = today()
    out = []
    for v in q(c, "SELECT v.*, b.code bcode, b.description bdesc, b.rate brate FROM variations v LEFT JOIN boq_items b ON b.id=v.boq_item_id WHERE v.project_id=? ORDER BY v.date, v.id", (pid,)):
        value = _f(v["est_value"]) or _f(v["var_qty"]) * _f(v["new_rate"] or v["brate"])
        billed = _f(val(c, "SELECT SUM(l.amount) FROM ipc_lines l JOIN ipc i ON i.id=l.ipc_id WHERE l.boq_item_id=? AND i.status IN ('submitted','certified') AND i.date>=?",
                        (v["boq_item_id"], v["approved_date"] or v["date"]))) if v["boq_item_id"] and v["status"] == "approved" else 0
        stage = "billed" if billed > 0.5 else v["status"] if v["status"] in ("approved", "rejected", "submitted") else ("priced" if value else "instructed")
        since = v["approved_date"] if stage == "approved" else v["date"]
        out.append({"no": v["no"], "title": v["title"] or v["new_description"] or v["bdesc"], "instruction": v["instruction_ref"], "date": v["date"], "stage": stage,
                    "value": r2(value), "time_days": v["time_impact_days"], "approved_date": v["approved_date"], "billed": r2(billed),
                    "age_days": (date.fromisoformat(t) - date.fromisoformat((since or t)[:10])).days, "event_id": v["event_id"]})
    stages = ["instructed", "priced", "submitted", "approved", "billed", "rejected"]
    return {"rows": out, "summary": [{"stage": s, "count": sum(1 for r in out if r["stage"] == s), "value": r2(sum(r["value"] for r in out if r["stage"] == s))} for s in stages]}


# ───────────────────────── B3: rate contracts ─────────────────────────
def contract_rate(c, party, material, d, project=None):
    r = q1(c, "SELECT * FROM rc_contracts WHERE active=1 AND party_id=? AND material_id=? AND (project_id IS NULL OR project_id=?) AND "
              "(valid_from IS NULL OR valid_from<=?) AND (valid_to IS NULL OR valid_to>=?) ORDER BY project_id IS NULL, id DESC LIMIT 1",
           (party, material, project or 0, d, d))
    return r


@api("rc.list", "procurement", "view")
def rc_list(c, u, a):
    rows = q(c, "SELECT r.*, pa.name party, m.name material, m.unit, p.code project FROM rc_contracts r LEFT JOIN parties pa ON pa.id=r.party_id "
                "LEFT JOIN materials m ON m.id=r.material_id LEFT JOIN projects p ON p.id=r.project_id ORDER BY r.active DESC, pa.name, m.name")
    t = today()
    for r in rows:
        r["used_qty"] = r4(val(c, "SELECT SUM(COALESCE(l.accepted_qty, l.received_qty)) FROM grn_lines l JOIN grn g ON g.id=l.grn_id WHERE g.status='posted' AND g.vendor_id=? "
                                  "AND l.material_id=? AND (? IS NULL OR g.project_id=?) AND g.date>=COALESCE(?, '0000') AND g.date<=COALESCE(?, '9999')",
                               (r["party_id"], r["material_id"], r["project_id"], r["project_id"], r["valid_from"], r["valid_to"])))
        r["current"] = bool(r["active"]) and (not r["valid_from"] or r["valid_from"] <= t) and (not r["valid_to"] or r["valid_to"] >= t)
    above = q(c, "SELECT g.no, g.date, pa.name party, m.name material, l.rate, r.rate agreed, COALESCE(l.accepted_qty, l.received_qty) qty FROM grn_lines l JOIN grn g ON g.id=l.grn_id "
                 "JOIN rc_contracts r ON r.active=1 AND r.party_id=g.vendor_id AND r.material_id=l.material_id AND (r.project_id IS NULL OR r.project_id=g.project_id) "
                 "AND (r.valid_from IS NULL OR r.valid_from<=g.date) AND (r.valid_to IS NULL OR r.valid_to>=g.date) LEFT JOIN parties pa ON pa.id=g.vendor_id "
                 "LEFT JOIN materials m ON m.id=l.material_id WHERE g.status<>'cancelled' AND l.rate>r.rate+0.005 ORDER BY g.date DESC LIMIT 200")
    for x in above:
        x["extra"] = r2((_f(x["rate"]) - _f(x["agreed"])) * _f(x["qty"]))
    return {"rows": rows, "above": above}


@api("rc.save", "procurement", "approve")
def rc_save(c, u, a):
    for k in ("party_id", "material_id", "rate"):
        if not a.get(k):
            raise ApiError("Supplier, material and rate are needed.")
    row = {"party_id": int(a["party_id"]), "material_id": int(a["material_id"]), "project_id": int(a["project_id"]) if a.get("project_id") else None,
           "rate": _f(a["rate"]), "valid_from": a.get("valid_from") or None, "valid_to": a.get("valid_to") or None, "max_qty": _f(a.get("max_qty")) or None,
           "ref": a.get("ref") or None, "note": a.get("note") or None, "active": 0 if a.get("active") in (0, "0", False) else 1}
    if row["rate"] <= 0:
        raise ApiError("The rate must be more than zero.")
    if row["valid_from"] and row["valid_to"] and row["valid_to"] < row["valid_from"]:
        raise ApiError("Valid to is before valid from.")
    if a.get("id"):
        upd(c, "rc_contracts", int(a["id"]), row)
        rid = int(a["id"])
    else:
        row.update(created_by=u["id"], ts=now())
        rid = ins(c, "rc_contracts", row)
    audit(c, u, "save", "rc_contracts", rid, row)
    return {"id": rid}


@api("rc.rates", "procurement", "view")
def rc_rates(c, u, a):
    d = a.get("date") or today()
    out = {}
    for m in a.get("material_ids") or []:
        r = contract_rate(c, int(a["party_id"]), int(m), d, a.get("project_id"))
        if r:
            out[str(m)] = {"rate": r["rate"], "ref": r["ref"], "valid_to": r["valid_to"]}
    return {"rates": out}


def _w_doc_save(orig):
    def doc_save(c, u, a):
        t = a.get("type")
        if t in ("po", "grn"):
            h = a.get("header") or {}
            tbl = "po" if t == "po" else "grn"
            old = q1(c, "SELECT * FROM %s WHERE id=?" % tbl, (int(h["id"]),)) if h.get("id") else {}
            party = h.get("vendor_id") or (old or {}).get("vendor_id")
            pid = h.get("project_id") or (old or {}).get("project_id")
            d = h.get("date") or (old or {}).get("date") or today()
            if party and not h.get("po_id"):
                lines = []
                for l in a.get("lines") or []:
                    l = dict(l)
                    if l.get("material_id") and _f(l.get("rate")) <= 0.005:
                        r = contract_rate(c, int(party), int(l["material_id"]), d, int(pid) if pid else None)
                        if r:
                            l["rate"] = r["rate"]
                    lines.append(l)
                a = dict(a, lines=lines)
        return orig(c, u, a)
    return doc_save


# ───────────────────────── settings, start-up ─────────────────────────
@api("sb.settings", "commercial", "view")
def sb_settings(c, u, a):
    return {"on": on(c), "block": setting(c, "sb_block") == "1"}


@api("sb.settings_save", "accounts", "approve")
def sb_settings_save(c, u, a):
    for k, key in (("on", "sb_on"), ("block", "sb_block")):
        if k in a:
            _set(c, key, "1" if a[k] in (1, "1", True) else "0")
    audit(c, u, "save", "settings", None, {"sb_on": setting(c, "sb_on"), "sb_block": setting(c, "sb_block")})
    return sb_settings(c, u, {})


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


def init_subbill(c):
    c.executescript(SCHEMA)
    used = val(c, "SELECT COUNT(*) FROM vouchers") or val(c, "SELECT COUNT(*) FROM sc_bills")
    if not q1(c, "SELECT 1 FROM settings WHERE key='sb_on'"):
        _set(c, "sb_on", "0" if used else "1")
    if not q1(c, "SELECT 1 FROM settings WHERE key='sb_block'"):
        _set(c, "sb_block", "0")
    c.commit()
    _wrap("sco.bill_prefill", _w_prefill)
    _wrap("sco.bill_approve", _w_approve)
    _wrap("doc.save", _w_doc_save)
    try:
        import api_safe
        have = {s[0] for s in getattr(api_safe, "SWITCHES", [])}
        if "sb_on" not in have:
            api_safe.SWITCHES.append(("sb_on", "Subcontract bill quantities from the DPR (2.58)", "The running bill fills this period's quantity from the DPR or joint measurement.",
                                      lambda v: v == "1", "#/x/sub", "accounts approve", 11))
        if "sb_block" not in have:
            api_safe.SWITCHES.append(("sb_block", "Stop sub bills above client certification (2.58)", "Approval of a subcontract bill paying more than the client certified needs a reason.",
                                      lambda v: v == "1", "#/x/sub", "accounts approve", 12))
    except Exception:
        pass
