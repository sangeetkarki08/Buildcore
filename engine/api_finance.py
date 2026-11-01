"""Procurement (PR, comparative statement, PO), invoices, payments and accounting vouchers."""
import json
from datetime import date, timedelta

from core import (ApiError, EPS, audit, can, fsetting, get, ins, need, next_no, now, num, post_voucher, q, q1,
                  r2, r4, require, reverse_voucher, setting, today, upd, val, check_store, period_for, VOUCHER_PREFIX)
from api_inventory import (api, draft_doc, invoice_paid, load_doc, po_refresh_status, recalc_po, check_boq)


# ───────────────────────── purchase requests ─────────────────────────
def pr_refresh(c, pr_id):
    if not pr_id:
        return
    pr = get(c, "pr", pr_id)
    if pr["status"] not in ("approved", "partially_ordered", "ordered"):
        return
    lines = q(c, "SELECT * FROM pr_lines WHERE pr_id=?", (pr_id,))
    for l in lines:
        o = val(c, "SELECT SUM(CASE WHEN p.status='closed' THEN pl.received_qty ELSE pl.qty END) FROM po_lines pl "
                   "JOIN po p ON p.id=pl.po_id WHERE pl.pr_line_id=? AND p.status IN "
                   "('approved','partially_received','received','closed')", (l["id"],))
        upd(c, "pr_lines", l["id"], {"ordered_qty": r4(o)})
        l["ordered_qty"] = o
    tot = sum(l["qty"] for l in lines)
    done = sum(min(l["ordered_qty"] or 0, l["qty"]) for l in lines)
    st = "approved" if done <= EPS else ("ordered" if done + EPS >= tot else "partially_ordered")
    upd(c, "pr", pr_id, {"status": st})


@api("pr.submit", "procurement", "edit")
def pr_submit(c, u, a):
    draft_doc(c, "pr", a["id"])
    upd(c, "pr", a["id"], {"status": "submitted"})
    return True


@api("pr.approve", "procurement", "approve")
def pr_approve(c, u, a):
    pr = get(c, "pr", a["id"])
    if pr["status"] != "submitted":
        raise ApiError("Only submitted requests can be approved.")
    upd(c, "pr", pr["id"], {"status": "approved", "approved_by": u["id"]})
    audit(c, u, "approve", "pr", pr["id"])
    return True


@api("pr.reject", "procurement", "approve")
def pr_reject(c, u, a):
    pr = get(c, "pr", a["id"])
    if pr["status"] != "submitted":
        raise ApiError("Only submitted requests can be rejected.")
    upd(c, "pr", pr["id"], {"status": "draft", "remarks": ((pr["remarks"] or "") + " | Returned: " +
                                                          (a.get("reason") or "")).strip(" |")})
    return True


@api("pr.cancel", "procurement", "approve")
def pr_cancel(c, u, a):
    pr = get(c, "pr", a["id"])
    if val(c, "SELECT SUM(ordered_qty) FROM pr_lines WHERE pr_id=?", (pr["id"],)) > EPS:
        upd(c, "pr", pr["id"], {"status": "closed"})
    else:
        upd(c, "pr", pr["id"], {"status": "cancelled"})
    return True


def budget_check(c, project_id):
    """Budget, commitment and actual for material cost for a project."""
    acc = val(c, "SELECT id FROM accounts WHERE role='material_cost'")
    budget = val(c, "SELECT SUM(amount) FROM budgets WHERE project_id=? AND account_id=?", (project_id, acc))
    committed = val(c, "SELECT SUM((pl.qty-MIN(pl.received_qty,pl.qty))*pl.rate) FROM po_lines pl JOIN po p "
                       "ON p.id=pl.po_id WHERE p.project_id=? AND p.status IN ('approved','partially_received')",
                    (project_id,))
    actual = val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id WHERE "
                    "v.status IN ('posted','reversed') AND l.account_id=? AND l.project_id=?", (acc, project_id))
    stock = val(c, "SELECT SUM(value) FROM stock_balances WHERE project_id=?", (project_id,))
    return {"budget": r2(budget), "committed": r2(committed), "actual": r2(actual), "stock": r2(stock),
            "available": r2(budget - committed - actual - stock) if budget else None}


# ───────────────────────── comparative statements ─────────────────────────
@api("cs.get", "procurement", "view")
def cs_get(c, u, a):
    cs = get(c, "cs", a["id"], "Comparative statement")
    pr = load_doc(c, "pr", cs["pr_id"])
    quotes = q(c, "SELECT * FROM cs_quotes WHERE cs_id=? ORDER BY id", (cs["id"],))
    lines = [l for l in pr["lines"] if l["qty"] - (l["ordered_qty"] or 0) > EPS]
    best = None
    for qt in quotes:
        rates = json.loads(qt["rates"] or "{}")
        qt["rates"] = rates
        sub, missing = 0.0, 0
        for l in lines:
            rt = num(rates.get(str(l["id"])))
            if rt <= 0:
                missing += 1
            sub += (l["qty"] - (l["ordered_qty"] or 0)) * rt
        qt["subtotal"] = r2(sub)
        qt["missing"] = missing
        qt["total"] = r2(sub + (qt["freight"] or 0))
        if not missing and (best is None or qt["total"] < best["total"]):
            best = qt
    cs["pr"] = pr
    cs["lines"] = lines
    cs["quotes"] = quotes
    cs["l1_vendor_id"] = best["vendor_id"] if best else None
    return cs


@api("cs.save", "procurement", "edit")
def cs_save(c, u, a):
    h = a.get("header") or {}
    if h.get("id"):
        cs = get(c, "cs", h["id"])
        if cs["status"] != "draft":
            raise ApiError("Only draft statements can be edited.")
        upd(c, "cs", cs["id"], {"remarks": h.get("remarks"), "date": h.get("date") or cs["date"]})
        cid = cs["id"]
    else:
        pr = get(c, "pr", h.get("pr_id"), "Purchase request")
        if pr["status"] not in ("approved", "partially_ordered"):
            raise ApiError("Comparative statements need an approved purchase request.")
        d = h.get("date") or today()
        cid = ins(c, "cs", {"no": next_no(c, "CS", d), "pr_id": pr["id"], "project_id": pr["project_id"],
                            "date": d, "status": "draft", "remarks": h.get("remarks"), "created_by": u["id"]})
    c.execute("DELETE FROM cs_quotes WHERE cs_id=?", (cid,))
    seen = set()
    for qt in a.get("quotes") or []:
        if not qt.get("vendor_id"):
            continue
        vid = int(qt["vendor_id"])
        if vid in seen:
            raise ApiError("Each vendor can appear only once.")
        seen.add(vid)
        ins(c, "cs_quotes", {"cs_id": cid, "vendor_id": vid, "quote_no": qt.get("quote_no"),
                             "freight": num(qt.get("freight")), "vat_rate": num(qt.get("vat_rate")),
                             "delivery_days": int(num(qt.get("delivery_days"))),
                             "payment_terms": qt.get("payment_terms"),
                             "rates": json.dumps({str(k): num(v) for k, v in (qt.get("rates") or {}).items()})})
    return cs_get(c, u, {"id": cid})


@api("cs.submit", "procurement", "edit")
def cs_submit(c, u, a):
    cs = cs_get(c, u, {"id": a["id"]})
    if cs["status"] != "draft":
        raise ApiError("Already submitted.")
    vid = int(a.get("vendor_id") or 0)
    qt = next((x for x in cs["quotes"] if x["vendor_id"] == vid), None)
    if not qt:
        raise ApiError("Choose the recommended vendor from the quotes.")
    if qt["missing"]:
        raise ApiError("The recommended quote has lines without a rate.")
    minq = int(num(setting(c, "min_quotes") or 3))
    if len(cs["quotes"]) < minq and not (a.get("reason") or "").strip():
        raise ApiError("Fewer than %d quotes: give a reason." % minq)
    if vid != cs["l1_vendor_id"] and not (a.get("reason") or "").strip():
        raise ApiError("The recommended vendor is not the lowest (L1). Give a reason.")
    upd(c, "cs", cs["id"], {"status": "submitted", "recommended_vendor_id": vid, "reason": a.get("reason")})
    return True


@api("cs.approve", "procurement", "approve")
def cs_approve(c, u, a):
    cs = cs_get(c, u, {"id": a["id"]})
    if cs["status"] != "submitted":
        raise ApiError("Only submitted statements can be approved.")
    qt = next(x for x in cs["quotes"] if x["vendor_id"] == cs["recommended_vendor_id"])
    pr = cs["pr"]
    d = today()
    store = val(c, "SELECT id FROM stores WHERE project_id=? AND type='main'", (pr["project_id"],))
    po_id = ins(c, "po", {"no": next_no(c, "PO", d), "project_id": pr["project_id"], "vendor_id": qt["vendor_id"],
                          "date": d, "store_id": store, "pr_id": pr["id"], "cs_id": cs["id"],
                          "payment_terms": qt["payment_terms"], "freight": qt["freight"] or 0,
                          "status": "draft", "created_by": u["id"],
                          "delivery_date": (date.today() + timedelta(days=qt["delivery_days"] or 7)).isoformat(),
                          "terms": setting(c, "po_terms")})
    for l in cs["lines"]:
        ins(c, "po_lines", {"po_id": po_id, "pr_line_id": l["id"], "material_id": l["material_id"],
                            "description": l["description"], "qty": r4(l["qty"] - (l["ordered_qty"] or 0)),
                            "unit": l["unit"], "rate": num(qt["rates"].get(str(l["id"]))),
                            "vat_rate": qt["vat_rate"] or 0, "boq_item_id": l["boq_item_id"]})
    recalc_po(c, po_id)
    upd(c, "cs", cs["id"], {"status": "approved", "approved_by": u["id"], "po_id": po_id})
    audit(c, u, "approve", "cs", cs["id"], {"po_id": po_id})
    return {"po_id": po_id}


@api("cs.reject", "procurement", "approve")
def cs_reject(c, u, a):
    upd(c, "cs", a["id"], {"status": "draft"})
    return True


# ───────────────────────── purchase orders ─────────────────────────
@api("po.submit", "procurement", "edit")
def po_submit(c, u, a):
    po = draft_doc(c, "po", a["id"])
    need(po, "vendor_id", "project_id", "store_id")
    if not po["lines"]:
        raise ApiError("Add at least one line.")
    for l in po["lines"]:
        if not l["material_id"]:
            raise ApiError("Every PO line needs a material so it can be received into stock.")
        if (l["rate"] or 0) <= 0:
            raise ApiError("Every PO line needs a rate.")
        if l["qty"] < (l["received_qty"] or 0) - EPS:
            raise ApiError("A line quantity is below what was already received.")
        if l["pr_line_id"]:
            pl = get(c, "pr_lines", l["pr_line_id"])
            other = val(c, "SELECT SUM(pl.qty) FROM po_lines pl JOIN po p ON p.id=pl.po_id WHERE pl.pr_line_id=? "
                           "AND p.id<>? AND p.status IN ('approved','partially_received','received','closed')",
                        (pl["id"], po["id"]))
            if other + l["qty"] > pl["qty"] + EPS:
                raise ApiError("Line %s orders more than the purchase request quantity." % (l["description"] or ""))
    vendor = get(c, "parties", po["vendor_id"])
    if vendor["blacklisted"]:
        raise ApiError("Vendor %s is blacklisted." % vendor["name"])
    recalc_po(c, po["id"])
    upd(c, "po", po["id"], {"status": "pending_approval"})
    return True


@api("po.approve", "procurement", "approve")
def po_approve(c, u, a):
    po = get(c, "po", a["id"])
    if po["status"] != "pending_approval":
        raise ApiError("Only POs pending approval can be approved.")
    if po["total"] > fsetting(c, "high_value_po") and u["role"] != "admin":
        raise ApiError("POs above %s need approval by an administrator." % setting(c, "high_value_po"))
    upd(c, "po", po["id"], {"status": "approved", "approved_by": u["id"], "approved_at": now()})
    po_refresh_status(c, po["id"])
    pr_refresh(c, po["pr_id"])
    audit(c, u, "approve", "po", po["id"], {"total": po["total"]})
    return True


@api("po.reject", "procurement", "approve")
def po_reject(c, u, a):
    po = get(c, "po", a["id"])
    if po["status"] != "pending_approval":
        raise ApiError("Only POs pending approval can be returned.")
    upd(c, "po", po["id"], {"status": "draft", "remarks": ((po["remarks"] or "") + " | Returned: " +
                                                          (a.get("reason") or "")).strip(" |")})
    return True


@api("po.revise", "procurement", "edit")
def po_revise(c, u, a):
    po = load_doc(c, "po", a["id"])
    if po["status"] not in ("approved", "partially_received"):
        raise ApiError("Only approved or partly received POs can be revised.")
    if not (a.get("reason") or "").strip():
        raise ApiError("Give a reason for the revision.")
    ins(c, "po_revisions", {"po_id": po["id"], "revision": po["revision"], "snapshot": json.dumps(po, default=str),
                            "reason": a["reason"], "ts": now(), "user_id": u["id"]})
    upd(c, "po", po["id"], {"status": "draft", "revision": (po["revision"] or 0) + 1})
    pr_refresh(c, po["pr_id"])
    audit(c, u, "revise", "po", po["id"], a["reason"])
    return True


@api("po.revisions", "procurement", "view")
def po_revisions(c, u, a):
    return q(c, "SELECT id, revision, reason, ts, user_id FROM po_revisions WHERE po_id=? ORDER BY revision",
             (a["id"],))


@api("po.close", "procurement", "approve")
def po_close(c, u, a):
    po = get(c, "po", a["id"])
    if po["status"] not in ("approved", "partially_received", "received"):
        raise ApiError("This PO cannot be closed.")
    if not (a.get("reason") or "").strip() and po["status"] != "received":
        raise ApiError("Give a reason for short-closing.")
    upd(c, "po", po["id"], {"status": "closed", "close_reason": a.get("reason")})
    pr_refresh(c, po["pr_id"])
    return True


@api("po.cancel", "procurement", "approve")
def po_cancel(c, u, a):
    po = get(c, "po", a["id"])
    if val(c, "SELECT SUM(received_qty) FROM po_lines WHERE po_id=?", (po["id"],)) > EPS:
        raise ApiError("Goods were received on this PO. Short-close it instead.")
    if po["status"] in ("cancelled", "closed"):
        raise ApiError("Already %s." % po["status"])
    upd(c, "po", po["id"], {"status": "cancelled", "close_reason": a.get("reason")})
    pr_refresh(c, po["pr_id"])
    return True


@api("po.pending", "procurement", "view")
def po_pending(c, u, a):
    p, cond = [], ""
    if a.get("project_id"):
        cond = " AND p.project_id=?"
        p.append(a["project_id"])
    rows = q(c, "SELECT p.no, p.id po_id, p.date, p.delivery_date, p.vendor_id, p.project_id, pl.material_id, "
                "pl.description, pl.qty, pl.received_qty, pl.rate, pl.unit FROM po_lines pl JOIN po p ON "
                "p.id=pl.po_id WHERE p.status IN ('approved','partially_received') AND pl.qty-pl.received_qty>0.0001"
             + cond + " ORDER BY p.delivery_date", p)
    t = today()
    for r in rows:
        r["pending"] = r4(r["qty"] - r["received_qty"])
        r["pending_value"] = r2(r["pending"] * r["rate"])
        r["overdue_days"] = (date.fromisoformat(t) - date.fromisoformat(r["delivery_date"])).days \
            if r["delivery_date"] and r["delivery_date"] < t else 0
    return rows


@api("po.budget", "procurement", "view")
def po_budget(c, u, a):
    return budget_check(c, a["project_id"])


@api("price.history", "procurement", "view")
def price_history(c, u, a):
    return q(c, "SELECT g.date, g.no, g.vendor_id, g.project_id, l.accepted_qty qty, l.rate, l.landed_rate "
                "FROM grn_lines l JOIN grn g ON g.id=l.grn_id WHERE g.status='posted' AND l.material_id=? "
                "ORDER BY g.date DESC LIMIT ?", (a["material_id"], int(a.get("limit") or 20)))


@api("vendor.performance", "procurement", "view")
def vendor_performance(c, u, a):
    rows = q(c, "SELECT p.id, p.code, p.name FROM parties p WHERE p.kind IN ('vendor','subcontractor')")
    out = []
    for p in rows:
        pos = q(c, "SELECT id, total, delivery_date, status FROM po WHERE vendor_id=? AND status NOT IN "
                   "('draft','pending_approval','cancelled')", (p["id"],))
        if not pos:
            continue
        late = 0
        for po in pos:
            first = val(c, "SELECT MAX(date) FROM grn WHERE po_id=? AND status='posted'", (po["id"],), None)
            if first and po["delivery_date"] and first > po["delivery_date"]:
                late += 1
        rej = q1(c, "SELECT SUM(l.received_qty) r, SUM(l.rejected_qty) x FROM grn_lines l JOIN grn g ON "
                    "g.id=l.grn_id WHERE g.vendor_id=? AND g.status='posted'", (p["id"],))
        rt = q1(c, "SELECT AVG(quality) q, AVG(delivery) d, AVG(price) pr, AVG(service) s, COUNT(*) n FROM "
                   "vendor_ratings WHERE vendor_id=?", (p["id"],))
        scores = [x for x in (rt["q"], rt["d"], rt["pr"], rt["s"]) if x is not None]
        out.append(dict(p, po_count=len(pos), po_value=r2(sum(x["total"] for x in pos)), late_pos=late,
                        rejection_pct=round(100 * (rej["x"] or 0) / rej["r"], 2) if rej["r"] else 0,
                        rating=round(sum(scores) / len(scores), 2) if scores else None, ratings=rt["n"]))
    return sorted(out, key=lambda x: -x["po_value"])


# ───────────────────────── invoices ─────────────────────────
@api("invoice.uninvoiced", "procurement", "view")
def invoice_uninvoiced(c, u, a):
    rows = q(c, "SELECT l.id grn_line_id, l.material_id, l.accepted_qty-l.invoiced_qty qty, l.rate, g.no grn_no, "
                "g.date, g.project_id, l.po_line_id, pl.vat_rate FROM grn_lines l JOIN grn g ON g.id=l.grn_id "
                "LEFT JOIN po_lines pl ON pl.id=l.po_line_id WHERE g.status='posted' AND g.vendor_id=? AND "
                "l.accepted_qty-l.invoiced_qty>0.0001 ORDER BY g.date", (a["party_id"],))
    for r in rows:
        r["qty"] = r4(r["qty"])
        r["vat_rate"] = r["vat_rate"] or 0
    return rows


def party_advance_balance(c, party_id, kind):
    pay_kind = "pay" if kind == "purchase" else "receive"
    adv = val(c, "SELECT SUM(advance) FROM payments WHERE party_id=? AND kind=? AND status='posted'",
              (party_id, pay_kind))
    adj = val(c, "SELECT SUM(a.amount) FROM allocations a JOIN invoices i ON i.id=a.invoice_id WHERE a.active=1 AND "
                 "a.payment_id IS NULL AND i.party_id=? AND i.kind=?", (party_id, kind))
    rec = val(c, "SELECT SUM(advance_recovery) FROM invoices WHERE party_id=? AND kind=? AND status='posted'",
              (party_id, kind))
    return r2(adv - adj - rec)


@api("invoice.advance_balance", "procurement", "view")
def invoice_advance_balance(c, u, a):
    return party_advance_balance(c, a["party_id"], a.get("kind") or "purchase")


def advance_role(c, party):
    return "subcon_advance" if party["kind"] == "subcontractor" else "supplier_advance"


@api("invoice.post")
def invoice_post(c, u, a):
    d = draft_doc(c, "invoice", a["id"])
    kind = d["kind"]
    require(u, "accounts" if kind == "sales" else "procurement", "edit")
    need(d, "party_id", "project_id", "date")
    party = get(c, "parties", d["party_id"], "Party")
    if kind == "sales" and party["kind"] != "client":
        raise ApiError("Sales invoices must be for a client.")
    if kind == "purchase" and party["kind"] == "client":
        raise ApiError("Purchase invoices must be for a vendor or subcontractor.")
    if not d["lines"]:
        raise ApiError("Add at least one line.")
    tol = fsetting(c, "price_tol_pct")
    mismatch = []
    vl = []
    sub = vat = 0.0
    for l in d["lines"]:
        amount = r2(num(l["qty"]) * num(l["rate"]))
        lv = r2(amount * num(l["vat_rate"]) / 100)
        sub += amount
        vat += lv
        upd(c, "invoice_lines", l["id"], {"amount": amount})
        dims = {"equipment_id": l["equipment_id"], "boq_item_id": l["boq_item_id"]}
        if l["boq_item_id"]:
            check_boq(c, l["boq_item_id"], d["project_id"])
        if kind == "purchase" and l["grn_line_id"]:
            gl = get(c, "grn_lines", l["grn_line_id"], "GRN line")
            g = get(c, "grn", gl["grn_id"])
            if g["vendor_id"] != d["party_id"] or g["status"] != "posted":
                raise ApiError("GRN %s is not a posted receipt from this vendor." % g["no"])
            if l["qty"] > gl["accepted_qty"] - gl["invoiced_qty"] + EPS:
                raise ApiError("GRN %s: invoiced quantity %s exceeds uninvoiced quantity %s." %
                               (g["no"], l["qty"], r4(gl["accepted_qty"] - gl["invoiced_qty"])))
            if gl["po_line_id"]:
                pr_ = val(c, "SELECT rate FROM po_lines WHERE id=?", (gl["po_line_id"],))
                if pr_ and abs(l["rate"] - pr_) / pr_ * 100 > tol:
                    mismatch.append("%s: invoice rate %s vs PO rate %s" % (g["no"], l["rate"], pr_))
            base = r2(l["qty"] * gl["rate"])
            vl.append({"role": "grni", "debit": base, "party_id": d["party_id"], "narration": g["no"],
                       "project_id": g["project_id"]})
            if abs(amount - base) > 0.004:
                vl.append(dict(role="price_variance", debit=r2(amount - base), narration="Rate difference " + g["no"],
                               **dims))
            c.execute("UPDATE grn_lines SET invoiced_qty=invoiced_qty+? WHERE id=?", (l["qty"], gl["id"]))
            upd(c, "invoice_lines", l["id"], {"material_id": gl["material_id"]})
        else:
            if not l["account_id"]:
                if kind == "sales":
                    acc = val(c, "SELECT id FROM accounts WHERE role='contract_revenue'")
                    upd(c, "invoice_lines", l["id"], {"account_id": acc})
                    l["account_id"] = acc
                else:
                    raise ApiError("Line '%s' needs an expense account or a GRN line." % (l["description"] or ""))
            side = "credit" if kind == "sales" else "debit"
            vl.append(dict({"account_id": l["account_id"], side: amount, "narration": l["description"]}, **dims))
    if mismatch:
        if not a.get("override"):
            raise ApiError("Rate differs from PO beyond %s%%: %s. Tick 'Accept rate difference' to continue." %
                           (tol, "; ".join(mismatch)))
        require(u, "procurement", "approve")
    sub, vat = r2(sub), r2(vat)
    ret, adv, tds = r2(d["retention"]), r2(d["advance_recovery"]), r2(d["tds"])
    if adv > 0 and adv > party_advance_balance(c, party["id"], kind) + 0.01:
        raise ApiError("Advance recovery %s is more than the open advance %s." %
                       (adv, party_advance_balance(c, party["id"], kind)))
    if kind == "purchase":
        payable = r2(sub + vat - ret - adv)
        tds = 0
        vl += [{"role": "vat_input", "debit": vat},
               {"role": "retention_payable", "credit": ret, "party_id": party["id"]},
               {"role": advance_role(c, party), "credit": adv, "party_id": party["id"]},
               {"role": "ap_control", "credit": payable, "party_id": party["id"]}]
        vtype, prefix = "purchase", "PI"
    else:
        payable = r2(sub + vat - tds - ret - adv)
        vl += [{"role": "vat_output", "credit": vat},
               {"role": "tds_receivable", "debit": tds},
               {"role": "retention_receivable", "debit": ret, "party_id": party["id"]},
               {"role": "client_advance", "debit": adv, "party_id": party["id"]},
               {"role": "ar_control", "debit": payable, "party_id": party["id"]}]
        vtype, prefix = "sales", "SI"
    if payable < -0.005:
        raise ApiError("Deductions are larger than the invoice amount.")
    no = next_no(c, prefix, d["date"])
    due = d["due_date"] or (date.fromisoformat(d["date"]) + timedelta(days=party["credit_days"] or 0)).isoformat()
    vid = post_voucher(c, u, vtype, d["date"], "%s %s %s" % ("Bill from" if kind == "purchase" else "Invoice to",
                                                           party["name"], d["party_inv_no"] or no),
                       vl, project_id=d["project_id"], source="invoice", source_id=d["id"], party_id=party["id"],
                       ref_no=d["party_inv_no"])
    upd(c, "invoices", d["id"], {"status": "posted", "no": no, "voucher_id": vid, "subtotal": sub, "vat": vat,
                                 "tds": tds, "total": r2(sub + vat), "payable": payable, "due_date": due,
                                 "match_status": "override" if mismatch else "matched"})
    audit(c, u, "post", "invoices", d["id"], {"no": no, "payable": payable, "mismatch": mismatch})
    return {"no": no}


@api("invoice.cancel")
def invoice_cancel(c, u, a):
    d = load_doc(c, "invoice", a["id"])
    require(u, "accounts", "approve")
    if d["status"] != "posted":
        raise ApiError("Only posted invoices can be cancelled.")
    if invoice_paid(c, d["id"]) > 0.004:
        raise ApiError("Payments are allocated to this invoice. Cancel them first.")
    for l in d["lines"]:
        if l["grn_line_id"]:
            c.execute("UPDATE grn_lines SET invoiced_qty=invoiced_qty-? WHERE id=?", (l["qty"], l["grn_line_id"]))
    reverse_voucher(c, u, d["voucher_id"], today(), a.get("reason") or "Invoice cancelled")
    upd(c, "invoices", d["id"], {"status": "cancelled"})
    audit(c, u, "cancel", "invoices", d["id"], a.get("reason"))
    return True


@api("invoice.open", "procurement", "view")
def invoice_open(c, u, a):
    rows = q(c, "SELECT * FROM invoices WHERE party_id=? AND kind=? AND status='posted' ORDER BY date",
             (a["party_id"], a.get("kind") or "purchase"))
    out = []
    for r in rows:
        r["paid"] = invoice_paid(c, r["id"])
        r["balance"] = r2(r["payable"] - r["paid"])
        if r["balance"] > 0.004:
            out.append(r)
    return out


# ───────────────────────── payments ─────────────────────────
def is_money_account(c, acc_id):
    a = q1(c, "SELECT role, active FROM accounts WHERE id=?", (acc_id,))
    if not a or a["role"] not in ("cash", "bank") or not a["active"]:
        raise ApiError("Choose an active cash or bank account (role 'cash' or 'bank').")


@api("payment.create", "accounts", "edit")
def payment_create(c, u, a):
    need(a, "kind", "party_id", "date", "bank_account_id")
    kind = a["kind"]
    if kind not in ("pay", "receive"):
        raise ApiError("Unknown payment type.")
    is_money_account(c, int(a["bank_account_id"]))
    party = get(c, "parties", int(a["party_id"]), "Party")
    inv_kind = "purchase" if kind == "pay" else "sales"
    allocs = [x for x in (a.get("allocations") or []) if num(x.get("amount")) > 0]
    advance = r2(num(a.get("advance")))
    alloc_total = 0.0
    lines = []
    for x in allocs:
        inv = get(c, "invoices", int(x["invoice_id"]), "Invoice")
        amt = r2(num(x["amount"]))
        if inv["party_id"] != party["id"] or inv["kind"] != inv_kind or inv["status"] != "posted":
            raise ApiError("Invoice %s does not belong to this party." % inv["no"])
        bal = r2(inv["payable"] - invoice_paid(c, inv["id"]))
        if amt > bal + 0.004:
            raise ApiError("Invoice %s: allocation %s exceeds balance %s." % (inv["no"], amt, bal))
        alloc_total += amt
        lines.append((inv, amt))
    gross = r2(alloc_total + advance)
    if gross <= 0:
        raise ApiError("Enter an amount against at least one invoice, or an advance.")
    tds = 0.0
    if kind == "pay" and a.get("tds_rate_id"):
        tr = get(c, "tds_rates", int(a["tds_rate_id"]), "TDS rate")
        if gross >= (tr["threshold"] or 0):
            tds = r2(gross * tr["rate"] / 100)
    net = r2(gross - tds)
    proj = int(a["project_id"]) if a.get("project_id") else (lines[0][0]["project_id"] if lines else None)
    if not proj:
        raise ApiError("Select a project for this advance.")
    bank = int(a["bank_account_id"])
    vl = []
    if kind == "pay":
        for inv, amt in lines:
            vl.append({"role": "ap_control", "debit": amt, "party_id": party["id"], "project_id": inv["project_id"],
                       "narration": inv["no"]})
        vl.append({"role": advance_role(c, party), "debit": advance, "party_id": party["id"]})
        vl.append({"account_id": bank, "credit": net})
        vl.append({"role": "tds_payable", "credit": tds, "party_id": party["id"]})
        vtype, prefix = "payment", "PAY"
    else:
        vl.append({"account_id": bank, "debit": gross})
        for inv, amt in lines:
            vl.append({"role": "ar_control", "credit": amt, "party_id": party["id"], "project_id": inv["project_id"],
                       "narration": inv["no"]})
        vl.append({"role": "client_advance", "credit": advance, "party_id": party["id"]})
        vtype, prefix = "receipt", "REC"
    no = next_no(c, prefix, a["date"])
    pid = ins(c, "payments", {"no": no, "kind": kind, "party_id": party["id"], "project_id": proj, "date": a["date"],
                              "bank_account_id": bank, "gross": gross, "tds": tds,
                              "tds_rate_id": a.get("tds_rate_id") or None, "net": net, "advance": advance,
                              "mode": a.get("mode"), "cheque_no": a.get("cheque_no"), "status": "posted",
                              "remarks": a.get("remarks"), "created_by": u["id"]})
    vid = post_voucher(c, u, vtype, a["date"], "%s %s %s" % ("Paid to" if kind == "pay" else "Received from",
                                                           party["name"], no), vl, project_id=proj,
                       source="payment", source_id=pid, party_id=party["id"], ref_no=a.get("cheque_no"))
    upd(c, "payments", pid, {"voucher_id": vid})
    for inv, amt in lines:
        ins(c, "allocations", {"payment_id": pid, "invoice_id": inv["id"], "amount": amt, "date": a["date"],
                               "active": 1})
    audit(c, u, "create", "payments", pid, {"no": no, "gross": gross})
    return {"id": pid, "no": no, "gross": gross, "tds": tds, "net": net}


@api("payment.cancel", "accounts", "approve")
def payment_cancel(c, u, a):
    p = get(c, "payments", a["id"], "Payment")
    if p["status"] != "posted":
        raise ApiError("Already cancelled.")
    if p["advance"] > 0:
        inv_kind = "purchase" if p["kind"] == "pay" else "sales"
        if party_advance_balance(c, p["party_id"], inv_kind) + 0.004 < p["advance"]:
            raise ApiError("This advance has already been adjusted against invoices.")
    reverse_voucher(c, u, p["voucher_id"], today(), a.get("reason") or "Payment cancelled")
    c.execute("UPDATE allocations SET active=0 WHERE payment_id=?", (p["id"],))
    upd(c, "payments", p["id"], {"status": "cancelled"})
    audit(c, u, "cancel", "payments", p["id"], a.get("reason"))
    return True


@api("payment.list", "accounts", "view")
def payment_list(c, u, a):
    cond, p = [], []
    for k in ("kind", "party_id", "project_id"):
        if a.get(k):
            cond.append("%s=?" % k)
            p.append(a[k])
    return q(c, "SELECT * FROM payments%s ORDER BY date DESC, id DESC LIMIT 500" %
             (" WHERE " + " AND ".join(cond) if cond else ""), p)


@api("advance.adjust", "accounts", "edit")
def advance_adjust(c, u, a):
    need(a, "invoice_id", "amount", "date")
    inv = get(c, "invoices", int(a["invoice_id"]), "Invoice")
    party = get(c, "parties", inv["party_id"])
    amt = r2(num(a["amount"]))
    if inv["status"] != "posted":
        raise ApiError("Invoice is not posted.")
    if amt > r2(inv["payable"] - invoice_paid(c, inv["id"])) + 0.004:
        raise ApiError("Amount exceeds the invoice balance.")
    if amt > party_advance_balance(c, party["id"], inv["kind"]) + 0.004:
        raise ApiError("Amount exceeds the open advance.")
    if inv["kind"] == "purchase":
        vl = [{"role": "ap_control", "debit": amt, "party_id": party["id"]},
              {"role": advance_role(c, party), "credit": amt, "party_id": party["id"]}]
    else:
        vl = [{"role": "client_advance", "debit": amt, "party_id": party["id"]},
              {"role": "ar_control", "credit": amt, "party_id": party["id"]}]
    vid = post_voucher(c, u, "journal", a["date"], "Advance adjusted against %s" % inv["no"], vl,
                       project_id=inv["project_id"], source="advance_adjust", source_id=inv["id"],
                       party_id=party["id"])
    ins(c, "allocations", {"payment_id": None, "invoice_id": inv["id"], "amount": amt, "date": a["date"],
                           "voucher_id": vid, "active": 1})
    return True


# ───────────────────────── manual vouchers ─────────────────────────
@api("voucher.save", "accounts", "edit")
def voucher_save(c, u, a):
    h = a.get("header") or {}
    need(h, "date", "type", "narration")
    if h["type"] not in VOUCHER_PREFIX:
        raise ApiError("Unknown voucher type.")
    lines = []
    for l in a.get("lines") or []:
        if not l.get("account_id"):
            continue
        dr, cr = r2(num(l.get("debit"))), r2(num(l.get("credit")))
        if dr < 0 or cr < 0 or (dr > 0 and cr > 0) or (dr == 0 and cr == 0):
            raise ApiError("Each line needs either a debit or a credit (not both, not negative).")
        acc = get(c, "accounts", int(l["account_id"]), "Account")
        if not acc["active"]:
            raise ApiError("Account %s is inactive." % acc["name"])
        if acc["role"] in ("inventory", "inventory_fuel", "inventory_spares", "grni"):
            if not a.get("allow_control"):
                raise ApiError("%s is updated by store documents. Use a stock count or GRN instead." % acc["name"])
        lines.append({"account_id": acc["id"], "debit": dr, "credit": cr, "narration": l.get("narration"),
                      "project_id": int(l["project_id"]) if l.get("project_id") else (
                          int(h["project_id"]) if h.get("project_id") else None),
                      "equipment_id": int(l["equipment_id"]) if l.get("equipment_id") else None,
                      "boq_item_id": int(l["boq_item_id"]) if l.get("boq_item_id") else None,
                      "party_id": int(l["party_id"]) if l.get("party_id") else None})
    if len(lines) < 2:
        raise ApiError("A voucher needs at least two lines.")
    td, tc = r2(sum(l["debit"] for l in lines)), r2(sum(l["credit"] for l in lines))
    if abs(td - tc) > 0.004:
        raise ApiError("Debits (%.2f) and credits (%.2f) must be equal." % (td, tc))
    if h.get("id"):
        v = get(c, "vouchers", int(h["id"]), "Voucher")
        if v["status"] != "draft" or v["source"] != "manual":
            raise ApiError("Only manual draft vouchers can be edited.")
        c.execute("DELETE FROM voucher_lines WHERE voucher_id=?", (v["id"],))
        upd(c, "vouchers", v["id"], {"date": h["date"], "type": h["type"], "narration": h["narration"],
                                     "project_id": h.get("project_id") or None, "ref_no": h.get("ref_no"),
                                     "total": td})
        vid = v["id"]
    else:
        vid = ins(c, "vouchers", {"no": None, "type": h["type"], "date": h["date"], "narration": h["narration"],
                                  "project_id": h.get("project_id") or None, "status": "draft", "source": "manual",
                                  "ref_no": h.get("ref_no"), "total": td, "created_by": u["id"], "ts": now()})
    for l in lines:
        l["voucher_id"] = vid
        ins(c, "voucher_lines", l)
    audit(c, u, "save", "vouchers", vid, {"header": h, "lines": lines})
    return {"id": vid}


@api("voucher.post", "accounts", "edit")
def voucher_post(c, u, a):
    v = get(c, "vouchers", a["id"], "Voucher")
    if v["status"] != "draft":
        raise ApiError("Only drafts can be posted.")
    if setting(c, "voucher_approval") == "1":
        require(u, "accounts", "approve")
        if v["created_by"] == u["id"] and u["role"] != "admin":
            raise ApiError("Another person must approve vouchers you created.")
    lines = q(c, "SELECT * FROM voucher_lines WHERE voucher_id=?", (v["id"],))
    c.execute("DELETE FROM voucher_lines WHERE voucher_id=?", (v["id"],))
    c.execute("DELETE FROM vouchers WHERE id=?", (v["id"],))
    for l in lines:
        l.pop("id")
        l.pop("voucher_id")
        l.pop("cleared_date")
    nid = post_voucher(c, u, v["type"], v["date"], v["narration"], lines, project_id=v["project_id"],
                       source="manual", ref_no=v["ref_no"])
    upd(c, "vouchers", nid, {"created_by": v["created_by"]})
    audit(c, u, "post", "vouchers", nid, {"draft_id": v["id"]})
    return {"id": nid}


@api("voucher.reverse", "accounts", "approve")
def voucher_reverse(c, u, a):
    v = get(c, "vouchers", a["id"], "Voucher")
    if v["source"] != "manual":
        raise ApiError("This voucher came from %s. Cancel the source document instead." % v["source"])
    rid = reverse_voucher(c, u, v["id"], a.get("date") or today(), a.get("reason") or "")
    audit(c, u, "reverse", "vouchers", v["id"], a.get("reason"))
    return {"id": rid}


@api("voucher.delete", "accounts", "edit")
def voucher_delete(c, u, a):
    v = get(c, "vouchers", a["id"], "Voucher")
    if v["status"] != "draft":
        raise ApiError("Posted vouchers cannot be deleted. Reverse them instead.")
    c.execute("DELETE FROM voucher_lines WHERE voucher_id=?", (v["id"],))
    c.execute("DELETE FROM vouchers WHERE id=?", (v["id"],))
    return True


@api("voucher.get", "accounts", "view")
def voucher_get(c, u, a):
    v = get(c, "vouchers", a["id"], "Voucher")
    v["lines"] = q(c, "SELECT l.*, a.code account_code, a.name account_name FROM voucher_lines l JOIN accounts a "
                      "ON a.id=l.account_id WHERE voucher_id=? ORDER BY l.id", (v["id"],))
    return v


@api("voucher.list", "accounts", "view")
def voucher_list(c, u, a):
    cond, p = [], []
    for k in ("status", "type", "source", "project_id"):
        if a.get(k):
            cond.append("%s=?" % k)
            p.append(a[k])
    if a.get("from"):
        cond.append("date>=?")
        p.append(a["from"])
    if a.get("to"):
        cond.append("date<=?")
        p.append(a["to"])
    if a.get("search"):
        cond.append("(narration LIKE ? OR no LIKE ? OR ref_no LIKE ?)")
        p += ["%" + a["search"] + "%"] * 3
    return q(c, "SELECT * FROM vouchers%s ORDER BY date DESC, id DESC LIMIT %d" %
             (" WHERE " + " AND ".join(cond) if cond else "", int(a.get("limit") or 500)), p)


# ───────────────────────── periods ─────────────────────────
BS_MONTHS = ["Shrawan", "Bhadra", "Ashwin", "Kartik", "Mangsir", "Poush", "Magh", "Falgun", "Chaitra",
             "Baisakh", "Jestha", "Asar"]


@api("period.generate", "accounts", "approve")
def period_generate(c, u, a):
    need(a, "fy", "start_date")
    start = date.fromisoformat(a["start_date"])
    if val(c, "SELECT COUNT(*) FROM fiscal_periods WHERE fy=?", (a["fy"],)):
        raise ApiError("Periods for %s already exist." % a["fy"])

    def add_month(d, n):
        y, m = d.year + (d.month - 1 + n) // 12, (d.month - 1 + n) % 12 + 1
        day = min(d.day, 28 if m == 2 else 30 if m in (4, 6, 9, 11) else 31)
        return date(y, m, day)
    for i in range(12):
        s, e = add_month(start, i), add_month(start, i + 1) - timedelta(days=1)
        if period_for(c, s.isoformat()) or period_for(c, e.isoformat()):
            raise ApiError("New periods overlap existing ones.")
        ins(c, "fiscal_periods", {"fy": a["fy"], "code": "%s-%02d %s" % (a["fy"], i + 1, BS_MONTHS[i]),
                                  "start_date": s.isoformat(), "end_date": e.isoformat(), "status": "open"})
    return True


@api("period.status", "accounts", "approve")
def period_status(c, u, a):
    p = get(c, "fiscal_periods", a["id"], "Period")
    st = a.get("status")
    if st not in ("open", "soft_closed", "locked"):
        raise ApiError("Unknown status.")
    if p["status"] == "locked" and u["role"] != "admin":
        raise ApiError("Only an administrator can reopen a locked period.")
    upd(c, "fiscal_periods", p["id"], {"status": st})
    audit(c, u, "period_status", "fiscal_periods", p["id"], {"from": p["status"], "to": st})
    return True


# ───────────────────────── bank reconciliation ─────────────────────────
@api("bank.lines", "accounts", "view")
def bank_lines(c, u, a):
    need(a, "account_id")
    to = a.get("to") or today()
    rows = q(c, "SELECT l.id, l.debit, l.credit, l.cleared_date, l.narration, v.no, v.date, v.narration vnar, "
                "v.ref_no FROM voucher_lines l JOIN vouchers v ON v.id=l.voucher_id WHERE l.account_id=? AND "
                "v.status IN ('posted','reversed') AND v.date<=? AND (l.cleared_date IS NULL OR l.cleared_date>=?) "
                "ORDER BY v.date, v.id", (a["account_id"], to, a.get("from") or "0000"))
    acc = get(c, "accounts", a["account_id"])
    book = acc["opening_balance"] + val(c, "SELECT SUM(l.debit-l.credit) FROM voucher_lines l JOIN vouchers v ON "
                                           "v.id=l.voucher_id WHERE l.account_id=? AND v.status IN "
                                           "('posted','reversed') AND v.date<=?", (a["account_id"], to))
    unc_dr = sum(r["debit"] for r in rows if not r["cleared_date"] or r["cleared_date"] > to)
    unc_cr = sum(r["credit"] for r in rows if not r["cleared_date"] or r["cleared_date"] > to)
    return {"rows": rows, "book_balance": r2(book), "uncleared_deposits": r2(unc_dr),
            "uncleared_payments": r2(unc_cr), "bank_balance": r2(book - unc_dr + unc_cr)}


@api("bank.clear", "accounts", "edit")
def bank_clear(c, u, a):
    for lid in a.get("ids") or []:
        c.execute("UPDATE voucher_lines SET cleared_date=? WHERE id=?", (a.get("date") or None, int(lid)))
    return True


@api("cs.list", "procurement", "view")
def cs_list(c, u, a):
    cond, p = "", []
    if a.get("project_id"):
        cond = " WHERE cs.project_id=?"
        p.append(a["project_id"])
    return q(c, "SELECT cs.*, pr.no pr_no FROM cs JOIN pr ON pr.id=cs.pr_id" + cond + " ORDER BY cs.id DESC", p)
