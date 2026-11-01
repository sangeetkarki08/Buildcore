"""Plant and asset management.

PLANT is the fixed production plant on a site - the batching plant, the crusher, the quarry.
It is not the same thing as EQUIPMENT (excavators, tippers): plant turns raw material into
another material. A production run takes cement, sand and aggregate out of the store and puts
concrete into it, at a cost the software works out: material + power + fuel + labour + the
machine's own hourly rate. That cost then follows the concrete wherever it is used.

ASSETS is everything the company owns that is not construction equipment and not stock:
land, buildings, camp, furniture, computers, instruments, light vehicles. It keeps custody,
location, insurance and warranty, runs depreciation into the accounts, and records transfers,
verification and disposal.
"""
from datetime import date

from core import (ApiError, EPS, assert_open, audit, get, ins, month_end, need, next_no, now, num, post_voucher,
                  q, q1, r2, r4, reverse_voucher, setting, stock_in, stock_out, today, upd, val)
from api_inventory import api, material

import api_inventory as inv

inv.MASTERS["plants"] = ("plant", ["code", "name", "kind", "project_id", "location", "capacity", "capacity_unit",
                                   "output_material_id", "equipment_id", "power_kw", "operator", "commissioned",
                                   "notes", "active"], ["code", "name"],
                         [("plant_runs", "plant_id"), ("mix_designs", "plant_id")])
inv.NUMERIC |= {"capacity", "power_kw"}
inv.ID_FIELDS |= {"output_material_id", "plant_id", "mix_id"}

POSTED = "v.status IN ('posted','reversed')"
PLANT_KINDS = ("batching", "crusher", "quarry", "block", "bending", "workshop", "other")
ASSET_CLASSES = ("land", "building", "camp", "vehicle", "furniture", "computer", "instrument", "tool", "other")


# ═══════════════════════════ plant masters ═══════════════════════════
def plant_of(c, pid):
    return get(c, "plants", pid, "Plant")


@api("plant.list", "plant", "view")
def plant_list(c, u, a):
    rows = q(c, "SELECT * FROM plants%s ORDER BY code" % (" WHERE project_id=?" if a.get("project_id") else ""),
             (a["project_id"],) if a.get("project_id") else ())
    for r in rows:
        r["runs"] = val(c, "SELECT COUNT(*) FROM plant_runs WHERE plant_id=? AND status='posted'", (r["id"],))
        r["output"] = r2(val(c, "SELECT SUM(output_qty) FROM plant_runs WHERE plant_id=? AND status='posted'",
                             (r["id"],)))
        r["cost"] = r2(val(c, "SELECT SUM(total_cost) FROM plant_runs WHERE plant_id=? AND status='posted'",
                           (r["id"],)))
        r["unit_cost"] = r2(r["cost"] / r["output"]) if r["output"] > EPS else None
        r["down_hours"] = r2(val(c, "SELECT SUM(down_hours) FROM plant_runs WHERE plant_id=? AND status='posted'",
                                 (r["id"],)))
        r["run_hours"] = r2(val(c, "SELECT SUM(run_hours) FROM plant_runs WHERE plant_id=? AND status='posted'",
                                (r["id"],)))
    return rows


@api("mix.list", "plant", "view")
def mix_list(c, u, a):
    cond = " WHERE plant_id=?" if a.get("plant_id") else ""
    rows = q(c, "SELECT * FROM mix_designs%s ORDER BY code" % cond,
             (a["plant_id"],) if a.get("plant_id") else ())
    for r in rows:
        r["lines"] = q(c, "SELECT * FROM mix_lines WHERE mix_id=? ORDER BY id", (r["id"],))
        r["material_cost"] = r2(sum(num(l["qty_per_unit"]) * (1 + num(l["wastage_pct"]) / 100.0)
                                    * (material(c, l["material_id"])["standard_rate"] or 0) for l in r["lines"]))
    return rows


@api("mix.save", "plant", "edit")
def mix_save(c, u, a):
    h = a.get("header") or {}
    need(h, "plant_id", "name")
    data = {"plant_id": int(h["plant_id"]), "code": h.get("code"), "name": h["name"],
            "output_material_id": int(h["output_material_id"]) if h.get("output_material_id") else None,
            "output_qty": num(h.get("output_qty")) or 1, "unit": h.get("unit"), "grade": h.get("grade"),
            "approved_by": h.get("approved_by"), "approved_date": h.get("approved_date"),
            "remarks": h.get("remarks"), "active": int(num(h.get("active", 1)))}
    if h.get("id"):
        mid = int(h["id"])
        upd(c, "mix_designs", mid, data)
    else:
        mid = ins(c, "mix_designs", data)
    c.execute("DELETE FROM mix_lines WHERE mix_id=?", (mid,))
    for l in a.get("lines") or []:
        if not l.get("material_id") or num(l.get("qty_per_unit")) <= 0:
            continue
        ins(c, "mix_lines", {"mix_id": mid, "material_id": int(l["material_id"]),
                             "qty_per_unit": num(l["qty_per_unit"]), "wastage_pct": num(l.get("wastage_pct")),
                             "remarks": l.get("remarks")})
    audit(c, u, "save", "mix_designs", mid, data)
    return {"id": mid}


@api("mix.delete", "plant", "edit")
def mix_delete(c, u, a):
    mid = int(a["id"])
    if val(c, "SELECT COUNT(*) FROM plant_runs WHERE mix_id=?", (mid,)):
        raise ApiError("This mix has been used in a production run and cannot be deleted.")
    c.execute("DELETE FROM mix_lines WHERE mix_id=?", (mid,))
    c.execute("DELETE FROM mix_designs WHERE id=?", (mid,))
    return True


# ═══════════════════════════ production runs ═══════════════════════════
@api("run.prefill", "plant", "view")
def run_prefill(c, u, a):
    """What a run would consume, from the mix design and the quantity to be produced."""
    need(a, "mix_id")
    mix = get(c, "mix_designs", a["mix_id"], "Mix design")
    qty = num(a.get("output_qty")) or 1
    per = num(mix["output_qty"]) or 1
    lines = []
    for l in q(c, "SELECT * FROM mix_lines WHERE mix_id=? ORDER BY id", (mix["id"],)):
        m = material(c, l["material_id"])
        need_qty = r4(qty / per * num(l["qty_per_unit"]) * (1 + num(l["wastage_pct"]) / 100.0))
        lines.append({"material_id": m["id"], "name": m["code"] + " " + m["name"], "unit": m["unit"],
                      "planned_qty": need_qty, "qty": need_qty})
    return {"mix": mix, "lines": lines, "output_material_id": mix["output_material_id"], "unit": mix["unit"]}


@api("run.list", "plant", "view")
def run_list(c, u, a):
    cond, p = [], []
    for k in ("plant_id", "project_id", "status"):
        if a.get(k):
            cond.append("%s=?" % k)
            p.append(a[k])
    if a.get("from"):
        cond.append("date>=?")
        p.append(a["from"])
    if a.get("to"):
        cond.append("date<=?")
        p.append(a["to"])
    return q(c, "SELECT * FROM plant_runs%s ORDER BY date DESC, id DESC LIMIT 500" %
             (" WHERE " + " AND ".join(cond) if cond else ""), p)


@api("run.get", "plant", "view")
def run_get(c, u, a):
    r = get(c, "plant_runs", a["id"], "Production run")
    r["lines"] = q(c, "SELECT * FROM plant_run_lines WHERE run_id=? ORDER BY id", (r["id"],))
    r["tests"] = q(c, "SELECT * FROM plant_tests WHERE run_id=? ORDER BY id", (r["id"],))
    r["plant"] = q1(c, "SELECT * FROM plants WHERE id=?", (r["plant_id"],))
    return r


@api("run.save", "plant", "edit")
def run_save(c, u, a):
    h = a.get("header") or {}
    need(h, "plant_id", "project_id", "date")
    assert_open(c, u, h["date"])
    pl = plant_of(c, int(h["plant_id"]))
    if h.get("id"):
        old = get(c, "plant_runs", int(h["id"]), "Production run")
        if old["status"] != "draft":
            raise ApiError("Only a draft run can be changed. Reverse it instead.")
    data = {"plant_id": pl["id"], "project_id": int(h["project_id"]), "date": h["date"],
            "shift": h.get("shift") or "day",
            "mix_id": int(h["mix_id"]) if h.get("mix_id") else None,
            "store_id": int(h["store_id"]) if h.get("store_id") else None,
            "output_material_id": int(h["output_material_id"]) if h.get("output_material_id")
            else pl["output_material_id"],
            "output_qty": num(h.get("output_qty")), "rejected_qty": num(h.get("rejected_qty")),
            "run_hours": num(h.get("run_hours")), "down_hours": num(h.get("down_hours")),
            "down_reason": h.get("down_reason"), "power_units": num(h.get("power_units")),
            "diesel_qty": num(h.get("diesel_qty")), "labour_cost": num(h.get("labour_cost")),
            "other_cost": num(h.get("other_cost")),
            "boq_item_id": int(h["boq_item_id"]) if h.get("boq_item_id") else None,
            "activity_id": int(h["activity_id"]) if h.get("activity_id") else None,
            "operator": h.get("operator"), "remarks": h.get("remarks")}
    if data["output_qty"] <= 0:
        raise ApiError("Enter what the plant produced.")
    if not data["output_material_id"]:
        raise ApiError("Say which material this plant produces.")
    if not data["store_id"]:
        raise ApiError("Choose the store the production goes into.")
    if h.get("id"):
        rid = int(h["id"])
        upd(c, "plant_runs", rid, data)
    else:
        data.update({"no": next_no(c, "PRD", h["date"]), "status": "draft", "created_by": u["id"]})
        rid = ins(c, "plant_runs", data)
    c.execute("DELETE FROM plant_run_lines WHERE run_id=?", (rid,))
    for l in a.get("lines") or []:
        if not l.get("material_id") or num(l.get("qty")) <= 0:
            continue
        ins(c, "plant_run_lines", {"run_id": rid, "material_id": int(l["material_id"]),
                                   "planned_qty": num(l.get("planned_qty")), "qty": num(l["qty"])})
    return {"id": rid}


@api("run.post", "plant", "approve")
def run_post(c, u, a):
    """Raw material leaves the store, the produced material comes in at what it really cost."""
    r = run_get(c, u, {"id": a["id"]})
    if r["status"] != "draft":
        raise ApiError("This run is already posted.")
    if not r["lines"]:
        raise ApiError("Add the materials the run consumed.")
    assert_open(c, u, r["date"])
    pl = plant_of(c, r["plant_id"])
    out_mat = material(c, r["output_material_id"])
    net = r2(num(r["output_qty"]) - num(r["rejected_qty"]))
    if net <= 0:
        raise ApiError("Rejected quantity cannot be the whole production.")

    # 1. consume the raw material at the store's weighted average rate
    material_cost = 0.0
    for l in r["lines"]:
        m = material(c, l["material_id"])
        rate, value = stock_out(c, u, r["project_id"], r["store_id"], m["id"], num(l["qty"]), r["date"],
                                "PRD", r["id"], r["no"])
        material_cost += value
        upd(c, "plant_run_lines", l["id"], {"rate": r2(rate), "amount": r2(value)})

    # 2. the running cost of the plant itself: power, fuel, labour, and the machine's own rate
    power_rate = num(setting(c, "power_rate") or 0) or 16.0
    dsl = q1(c, "SELECT * FROM materials WHERE code LIKE 'DSL%' OR name LIKE '%diesel%'")
    diesel_rate = 0.0
    if dsl:
        bal = q1(c, "SELECT qty, value FROM stock_balances WHERE project_id=? AND material_id=? AND qty>0 LIMIT 1",
                 (r["project_id"], dsl["id"]))
        diesel_rate = r2(bal["value"] / bal["qty"]) if bal and bal["qty"] else num(dsl["standard_rate"])
    power_cost = r2(num(r["power_units"]) * power_rate)
    fuel_cost = r2(num(r["diesel_qty"]) * diesel_rate)
    machine_cost = 0.0
    if pl["equipment_id"] and num(r["run_hours"]) > 0:
        import api_project
        eq = get(c, "equipment", pl["equipment_id"], "Plant machine")
        rate, _src = api_project.equipment_rate(c, eq, r["date"])
        machine_cost = r2(num(r["run_hours"]) * rate)
    other = r2(num(r["labour_cost"]) + num(r["other_cost"]) + power_cost + fuel_cost + machine_cost)
    total = r2(material_cost + other)
    unit_cost = r2(total / net)

    # 3. the produced material goes into the store at that cost
    stock_in(c, u, r["project_id"], r["store_id"], out_mat["id"], net, unit_cost, r["date"], "PRD", r["id"], r["no"])

    # 4. the accounts: the running cost is capitalised into the produced stock
    lines = [{"role": "inventory", "debit": r2(other), "project_id": r["project_id"],
              "narration": "%s production, running cost" % pl["name"]}]
    if power_cost:
        lines.append({"role": "overhead", "credit": power_cost, "project_id": r["project_id"],
                      "narration": "Power used by %s" % pl["code"]})
    if fuel_cost:
        lines.append({"role": "fuel_cost", "credit": fuel_cost, "project_id": r["project_id"],
                      "narration": "Fuel used by %s" % pl["code"]})
    if machine_cost:
        lines.append({"role": "equipment_recovery", "credit": machine_cost, "project_id": r["project_id"],
                      "equipment_id": pl["equipment_id"], "narration": "Plant hours %s" % pl["code"]})
    if num(r["labour_cost"]) or num(r["other_cost"]):
        lines.append({"role": "payroll_payable", "credit": r2(num(r["labour_cost"]) + num(r["other_cost"])),
                      "project_id": r["project_id"], "narration": "Plant crew, %s" % pl["code"]})
    vid = None
    if other > EPS:
        vid = post_voucher(c, u, "journal", r["date"], "Production %s at %s" % (r["no"], pl["name"]), lines,
                           project_id=r["project_id"], source="plant_run", source_id=r["id"])
    upd(c, "plant_runs", r["id"], {"status": "posted", "material_cost": r2(material_cost), "other_cost": r2(other),
                                   "total_cost": total, "unit_cost": unit_cost, "voucher_id": vid,
                                   "approved_by": u["id"]})
    audit(c, u, "post", "plant_runs", r["id"], {"total": total, "unit_cost": unit_cost})
    return {"id": r["id"], "no": r["no"], "total_cost": total, "unit_cost": unit_cost, "produced": net,
            "material_cost": r2(material_cost), "running_cost": r2(other)}


@api("run.reverse", "plant", "approve")
def run_reverse(c, u, a):
    r = run_get(c, u, {"id": a["id"]})
    if r["status"] != "posted":
        raise ApiError("Only a posted run can be reversed.")
    assert_open(c, u, today())
    net = r2(num(r["output_qty"]) - num(r["rejected_qty"]))
    # take the produced material back out, put the raw material back in
    stock_out(c, u, r["project_id"], r["store_id"], r["output_material_id"], net, today(), "PRD-REV", r["id"],
              r["no"] + "-REV")
    for l in r["lines"]:
        stock_in(c, u, r["project_id"], r["store_id"], l["material_id"], num(l["qty"]), num(l["rate"]), today(),
                 "PRD-REV", r["id"], r["no"] + "-REV")
    if r["voucher_id"]:
        reverse_voucher(c, u, r["voucher_id"], today(), "Production run %s reversed" % r["no"])
    upd(c, "plant_runs", r["id"], {"status": "reversed"})
    audit(c, u, "reverse", "plant_runs", r["id"], {"reason": a.get("reason")})
    return True


@api("run.test", "plant", "edit")
def run_test(c, u, a):
    need(a, "run_id")
    r = get(c, "plant_runs", a["run_id"], "Production run")
    tid = ins(c, "plant_tests", {"run_id": r["id"], "plant_id": r["plant_id"], "date": a.get("date") or today(),
                                 "test_type": a.get("test_type") or "Cube test", "sample_ref": a.get("sample_ref"),
                                 "criteria": a.get("criteria"), "result_value": a.get("result_value"),
                                 "status": a.get("status") or "pending", "remarks": a.get("remarks")})
    return {"id": tid}


@api("plant.report", "plant", "view")
def plant_report(c, u, a):
    """How each plant performed: output, cost per unit, utilisation and downtime."""
    frm = a.get("from") or "0000-01-01"
    to = a.get("to") or today()
    out = []
    for pl in q(c, "SELECT * FROM plants WHERE active=1%s ORDER BY code" %
                (" AND project_id=?" if a.get("project_id") else ""),
                (a["project_id"],) if a.get("project_id") else ()):
        runs = q(c, "SELECT * FROM plant_runs WHERE plant_id=? AND status='posted' AND date BETWEEN ? AND ?",
                 (pl["id"], frm, to))
        prod = r2(sum(num(x["output_qty"]) - num(x["rejected_qty"]) for x in runs))
        rej = r2(sum(num(x["rejected_qty"]) for x in runs))
        cost = r2(sum(num(x["total_cost"]) for x in runs))
        mat = r2(sum(num(x["material_cost"]) for x in runs))
        rh = r2(sum(num(x["run_hours"]) for x in runs))
        dh = r2(sum(num(x["down_hours"]) for x in runs))
        mm = material(c, pl["output_material_id"]) if pl["output_material_id"] else None
        out.append({"id": pl["id"], "code": pl["code"], "name": pl["name"], "kind": pl["kind"],
                    "project_id": pl["project_id"], "runs": len(runs), "produced": prod, "rejected": rej,
                    "reject_pct": r2(100 * rej / (prod + rej)) if (prod + rej) > EPS else 0,
                    "cost": cost, "material_cost": mat, "running_cost": r2(cost - mat),
                    "unit_cost": r2(cost / prod) if prod > EPS else None,
                    "output_unit": mm["unit"] if mm else "", "output_name": mm["name"] if mm else "",
                    "run_hours": rh, "down_hours": dh,
                    "availability": r2(100 * rh / (rh + dh)) if (rh + dh) > EPS else None,
                    "output_per_hour": r2(prod / rh) if rh > EPS else None,
                    "capacity_pct": r2(100 * (prod / rh) / pl["capacity"]) if rh > EPS and pl["capacity"] else None})
    return out


# ═══════════════════════════ assets ═══════════════════════════
def asset_book_value(c, asset):
    return r2(num(asset["purchase_value"]) - num(asset["accumulated_dep"]))


@api("asset.list", "assets", "view")
def asset_list(c, u, a):
    cond, p = [], []
    for k in ("project_id", "class", "status"):
        if a.get(k):
            cond.append("%s=?" % ("class" if k == "class" else k))
            p.append(a[k])
    if a.get("q"):
        cond.append("(code LIKE ? OR name LIKE ? OR custodian LIKE ? OR serial LIKE ?)")
        p += ["%%%s%%" % a["q"]] * 4
    rows = q(c, "SELECT * FROM assets%s ORDER BY code" % (" WHERE " + " AND ".join(cond) if cond else ""), p)
    for r in rows:
        r["book_value"] = asset_book_value(c, r)
        r["age_months"] = months_between(r["purchase_date"], today()) if r["purchase_date"] else None
        r["insurance_due"] = bool(r["insurance_expiry"] and r["insurance_expiry"] <= add_days(today(), 45))
        r["warranty_live"] = bool(r["warranty_expiry"] and r["warranty_expiry"] >= today())
    return rows


def months_between(a, b):
    try:
        x, y = date.fromisoformat(a), date.fromisoformat(b)
    except (TypeError, ValueError):
        return None
    return (y.year - x.year) * 12 + (y.month - x.month)


def add_days(iso, n):
    from datetime import timedelta
    return (date.fromisoformat(iso) + timedelta(days=n)).isoformat()


@api("asset.get", "assets", "view")
def asset_get(c, u, a):
    r = get(c, "assets", a["id"], "Asset")
    r["book_value"] = asset_book_value(c, r)
    r["moves"] = q(c, "SELECT * FROM asset_moves WHERE asset_id=? ORDER BY date DESC, id DESC", (r["id"],))
    r["dep_schedule"] = asset_schedule(r)
    return r


def asset_schedule(r):
    """What the books will charge each year, so the register can be checked at a glance."""
    out = []
    if not r["purchase_date"] or num(r["purchase_value"]) <= 0:
        return out
    if (r["dep_method"] or "slm") == "slm":
        life = int(num(r["life_months"]) or 60)
        per_month = (num(r["purchase_value"]) - num(r["residual_value"])) / life if life else 0
        for yr in range(0, max(1, (life + 11) // 12)):
            out.append({"year": yr + 1, "charge": r2(per_month * min(12, life - yr * 12))})
    else:
        rate = num(r["wdv_rate"]) or 15
        wdv = num(r["purchase_value"])
        for yr in range(0, 8):
            ch = r2(wdv * rate / 100.0)
            out.append({"year": yr + 1, "charge": ch})
            wdv = r2(wdv - ch)
    return out


@api("asset.save", "assets", "edit")
def asset_save(c, u, a):
    r = a.get("row") or {}
    need(r, "name")
    fields = ["code", "name", "category", "class", "project_id", "location", "custodian", "custodian_staff_id",
              "supplier_id", "invoice_no", "purchase_date", "purchase_value", "residual_value", "life_months",
              "dep_method", "wdv_rate", "serial", "warranty_expiry", "insurance_policy", "insurance_expiry",
              "condition", "status", "remarks", "active"]
    data = {}
    for k in fields:
        if k in r:
            v = r[k]
            if k in ("project_id", "custodian_staff_id", "supplier_id", "life_months"):
                data[k] = int(num(v)) if v not in ("", None) else None
            elif k in ("purchase_value", "residual_value", "wdv_rate"):
                data[k] = num(v)
            elif k == "active":
                data[k] = int(num(v))
            else:
                data[k] = v
    if data.get("class") and data["class"] not in ASSET_CLASSES:
        raise ApiError("Unknown asset class.")
    if r.get("id"):
        aid = int(r["id"])
        upd(c, "assets", aid, data)
    else:
        if not data.get("code"):
            data["code"] = "AST-%04d" % (1 + int(val(c, "SELECT COUNT(*) FROM assets")))
        data.setdefault("status", "in_use")
        data["accumulated_dep"] = 0
        aid = ins(c, "assets", data)
        ins(c, "asset_moves", {"asset_id": aid, "date": data.get("purchase_date") or today(), "kind": "acquired",
                               "to_location": data.get("location"), "custodian": data.get("custodian"),
                               "amount": data.get("purchase_value") or 0, "user_id": u["id"], "ts": now(),
                               "remarks": "Added to the register"})
    upd(c, "assets", aid, {"book_value": asset_book_value(c, get(c, "assets", aid))})
    audit(c, u, "save", "assets", aid, data)
    return {"id": aid}


@api("asset.move", "assets", "edit")
def asset_move(c, u, a):
    """Hand an asset to another person, site or project, and keep the trail."""
    need(a, "id", "kind")
    r = get(c, "assets", a["id"], "Asset")
    kind = a["kind"]
    if kind not in ("transfer", "custody", "verified", "repair", "condition"):
        raise ApiError("Unknown movement.")
    data = {"asset_id": r["id"], "date": a.get("date") or today(), "kind": kind,
            "from_location": r["location"], "to_location": a.get("location") or r["location"],
            "from_project": r["project_id"],
            "to_project": int(a["project_id"]) if a.get("project_id") else r["project_id"],
            "custodian": a.get("custodian") or r["custodian"], "remarks": a.get("remarks"),
            "user_id": u["id"], "ts": now()}
    ins(c, "asset_moves", data)
    upd(c, "assets", r["id"], {"location": data["to_location"], "project_id": data["to_project"],
                               "custodian": data["custodian"],
                               "condition": a.get("condition") or r["condition"],
                               "last_verified": data["date"] if kind == "verified" else r["last_verified"],
                               "status": "under_repair" if kind == "repair" else r["status"]})
    audit(c, u, kind, "assets", r["id"], data)
    return True


@api("asset.dispose", "assets", "approve")
def asset_dispose(c, u, a):
    """Sell or scrap an asset: the books lose the asset and its depreciation, and take the gain or loss."""
    need(a, "id", "date")
    r = get(c, "assets", a["id"], "Asset")
    if r["status"] == "disposed":
        raise ApiError("This asset is already disposed.")
    assert_open(c, u, a["date"])
    proceeds = num(a.get("amount"))
    bv = asset_book_value(c, r)
    gain = r2(proceeds - bv)
    lines = [{"role": "accum_dep", "debit": r2(num(r["accumulated_dep"])), "narration": "Depreciation written back"},
             {"role": "fixed_asset", "credit": r2(num(r["purchase_value"])),
              "narration": "%s %s removed from the register" % (r["code"], r["name"])}]
    if proceeds:
        lines.append({"role": a.get("into") or "bank", "debit": proceeds, "narration": "Sale proceeds"})
    if abs(gain) > EPS:
        lines.append({"role": "stock_gain" if gain > 0 else "overhead",
                      "credit" if gain > 0 else "debit": abs(gain),
                      "narration": "%s on disposal of %s" % ("Gain" if gain > 0 else "Loss", r["code"])})
    vid = post_voucher(c, u, "journal", a["date"], "Disposal of %s %s" % (r["code"], r["name"]), lines,
                       project_id=r["project_id"], source="asset", source_id=r["id"])
    upd(c, "assets", r["id"], {"status": "disposed", "disposal_date": a["date"], "disposal_value": proceeds,
                               "active": 0, "book_value": 0})
    ins(c, "asset_moves", {"asset_id": r["id"], "date": a["date"], "kind": "disposed", "amount": proceeds,
                           "remarks": a.get("remarks") or ("Gain %s" % gain if gain >= 0 else "Loss %s" % -gain),
                           "voucher_id": vid, "user_id": u["id"], "ts": now()})
    audit(c, u, "dispose", "assets", r["id"], {"proceeds": proceeds, "book_value": bv, "gain": gain})
    return {"book_value": bv, "proceeds": proceeds, "gain": gain, "voucher_id": vid}


@api("asset.dep_preview", "assets", "view")
def asset_dep_preview(c, u, a):
    month = a.get("month") or today()[:7]
    return _asset_dep(c, u, month, False)


@api("asset.dep_run", "assets", "approve")
def asset_dep_run(c, u, a):
    month = a.get("month") or today()[:7]
    return _asset_dep(c, u, month, True)


def _asset_dep(c, u, month, post):
    """One month of depreciation for every asset that is still in use."""
    end = month_end(month + "-01")
    if post:
        assert_open(c, u, end)
    done = val(c, "SELECT COUNT(*) FROM vouchers WHERE source='asset_dep' AND date=? AND status='posted'", (end,))
    rows, total = [], 0.0
    for r in q(c, "SELECT * FROM assets WHERE status<>'disposed' AND active=1"):
        if not r["purchase_date"] or r["purchase_date"] > end or num(r["purchase_value"]) <= 0:
            continue
        if (r["class"] or "") == "land":
            continue                                   # land is never depreciated
        bv = asset_book_value(c, r)
        floor = num(r["residual_value"])
        if bv - floor <= 0.01:
            continue
        if (r["dep_method"] or "slm") == "slm":
            life = int(num(r["life_months"]) or 60)
            charge = (num(r["purchase_value"]) - floor) / life if life else 0
        else:
            charge = bv * (num(r["wdv_rate"]) or 15) / 100.0 / 12.0
        charge = r2(min(charge, bv - floor))
        if charge <= 0:
            continue
        rows.append({"id": r["id"], "code": r["code"], "name": r["name"], "class": r["class"],
                     "project_id": r["project_id"], "book_value": bv, "charge": charge,
                     "method": r["dep_method"] or "slm"})
        total += charge
    total = r2(total)
    if not post:
        return {"month": month, "rows": rows, "total": total, "already_posted": bool(done)}
    if done:
        raise ApiError("Depreciation for %s is already posted." % month)
    if not rows:
        return {"month": month, "rows": [], "total": 0}
    lines = [{"role": "depreciation", "debit": x["charge"], "project_id": x["project_id"],
              "narration": "%s %s" % (x["code"], x["name"])} for x in rows]
    lines.append({"role": "accum_dep", "credit": total, "narration": "Asset depreciation for %s" % month})
    vid = post_voucher(c, u, "journal", end, "Asset depreciation %s" % month, lines, source="asset_dep")
    for x in rows:
        r = get(c, "assets", x["id"])
        upd(c, "assets", x["id"], {"accumulated_dep": r2(num(r["accumulated_dep"]) + x["charge"]),
                                   "book_value": r2(asset_book_value(c, r) - x["charge"])})
    audit(c, u, "depreciation", "assets", None, {"month": month, "total": total})
    return {"month": month, "rows": rows, "total": total, "voucher_id": vid}


@api("asset.summary", "assets", "view")
def asset_summary(c, u, a):
    """The register at a glance: what we own, by class, and what needs attention."""
    rows = asset_list(c, u, a)
    by = {}
    for r in rows:
        k = r["class"] or "other"
        g = by.setdefault(k, {"class": k, "count": 0, "cost": 0.0, "dep": 0.0, "book": 0.0})
        g["count"] += 1
        g["cost"] += num(r["purchase_value"])
        g["dep"] += num(r["accumulated_dep"])
        g["book"] += num(r["book_value"])
    for g in by.values():
        for k in ("cost", "dep", "book"):
            g[k] = r2(g[k])
    alerts = []
    for r in rows:
        if r["status"] == "disposed":
            continue
        if r["insurance_due"]:
            alerts.append({"id": r["id"], "code": r["code"], "name": r["name"],
                           "why": "Insurance expires " + (r["insurance_expiry"] or "")})
        if r["last_verified"] and r["last_verified"] < add_days(today(), -365):
            alerts.append({"id": r["id"], "code": r["code"], "name": r["name"],
                           "why": "Not verified since " + r["last_verified"]})
        if not r["last_verified"]:
            alerts.append({"id": r["id"], "code": r["code"], "name": r["name"], "why": "Never verified"})
        if (r["condition"] or "") in ("poor", "damaged"):
            alerts.append({"id": r["id"], "code": r["code"], "name": r["name"],
                           "why": "Condition recorded as " + r["condition"]})
    live = [r for r in rows if r["status"] != "disposed"]
    return {"by_class": sorted(by.values(), key=lambda x: -x["cost"]), "alerts": alerts[:40],
            "count": len(live), "cost": r2(sum(num(r["purchase_value"]) for r in live)),
            "dep": r2(sum(num(r["accumulated_dep"]) for r in live)),
            "book": r2(sum(num(r["book_value"]) for r in live)),
            "disposed": len([r for r in rows if r["status"] == "disposed"])}
