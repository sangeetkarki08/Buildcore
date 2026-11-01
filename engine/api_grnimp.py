"""
Bulk goods received notes from Excel / CSV (BuildCore 2.16.1).

The store keeps one sheet - one row per material received - for any number of days, vendors and challans, and
imports it at once:

  * every column is required (the sample sheet shows them);
  * rows with the same date, project, store, vendor and challan / bill number become one GRN with several lines;
  * a vendor that is not in BuildCore yet is created from the sheet (name, PAN / VAT no., phone, address) -
    found first by PAN, then by name;
  * a material code that is not in BuildCore yet is created from the sheet (code, name, unit);
  * dates may be AD (2026-09-27, 27/09/2026, Excel dates) or BS (2083-06-11); only rows between the chosen
    from / to dates are taken;
  * "Check" runs the whole import, posting included, and then undoes it - nothing is saved until "Import";
  * a challan already imported (same project, vendor, challan no. and date) is skipped, so the same sheet can be
    imported again after adding rows;
  * one GRN that fails (closed period, blacklisted vendor, bad row) does not stop the others.
"""
import base64
import re

from core import ApiError, audit, can, ins, now, num, q, q1, today, val
from api_inventory import FUNCS, api

VERSION = "2.16.1"

# field, heading in the sample, other headings recognised
COLUMNS = [
    ("date", "GRN Date", ["date", "grn date", "received date", "receipt date", "date received", "miti"]),
    ("project_code", "Project Code", ["project", "project code", "site", "site code"]),
    ("store", "Store", ["store", "store code", "store name", "godown", "warehouse"]),
    ("vendor_name", "Vendor Name", ["vendor", "supplier", "supplier name", "party", "party name"]),
    ("vendor_pan", "Vendor PAN/VAT No", ["pan", "vat no", "pan no", "pan/vat", "pan / vat no", "vendor pan", "vendor vat no", "pan vat no"]),
    ("vendor_phone", "Vendor Phone", ["phone", "mobile", "contact", "vendor mobile", "vendor contact"]),
    ("vendor_address", "Vendor Address", ["address", "vendor location", "location"]),
    ("challan_no", "Challan/Bill No", ["challan", "challan no", "bill no", "invoice no", "challan / bill no", "challan bill no", "dn no", "delivery note"]),
    ("vehicle_no", "Vehicle No", ["vehicle", "vehicle number", "truck no", "tipper no"]),
    ("material_code", "Material Code", ["material code", "item code", "code"]),
    ("material_name", "Material Name", ["material", "item", "description", "item name", "material description"]),
    ("unit", "Unit", ["uom", "unit of measure"]),
    ("received_qty", "Received Qty", ["received", "qty received", "received quantity", "quantity", "qty"]),
    ("accepted_qty", "Accepted Qty", ["accepted", "qty accepted", "accepted quantity", "ok qty"]),
    ("rate", "Rate (excl. VAT)", ["rate", "unit rate", "rate excl vat", "rate excl. vat", "price", "rate (npr)"]),
]
SAMPLE = [
    ["2026-09-27", "RD-12", "MS", "Himal Cement Suppliers", "301234567", "9851012345", "Butwal-11, Rupandehi", "CH-1021", "LU 1 KHA 2233",
     "CEM-OPC", "Cement OPC 43 grade", "bag", 500, 500, 920],
    ["2026-09-27", "RD-12", "MS", "Himal Cement Suppliers", "301234567", "9851012345", "Butwal-11, Rupandehi", "CH-1021", "LU 1 KHA 2233",
     "CEM-PPC", "Cement PPC", "bag", 200, 195, 860],
    ["2026-09-29", "RD-12", "MS", "Gandaki Steel Traders", "609876543", "9846054321", "Pokhara-8, Kaski", "INV-552", "GA 2 KHA 7788",
     "STL-TMT-16", "TMT bar Fe500 16 mm", "kg", 4200, 4200, 108.5],
    ["2083-06-14", "RD-12", "MS", "Kali Gandaki Aggregates", "612345678", "9857011122", "Beni-4, Myagdi", "D-0098", "DHA 3 KHA 4455",
     "AGG-20", "Aggregate 20 mm", "m3", 18, 18, 3200],
]
NUMS = ("received_qty", "accepted_qty", "rate")


def init_grnimp(c):
    pass


def _clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _spec():
    return [(f, True, [h] + al) for f, h, al in COLUMNS]


@api("grn.import_template", "inventory", "view")
def grn_import_template(c, u, a):
    """The sample sheet (.xlsx, or .csv with format=csv) with every column and four example rows."""
    heads = [h for _f, h, _a in COLUMNS]
    if a.get("format") == "csv":
        import csv
        import io
        out = io.StringIO()
        csv.writer(out, lineterminator="\r\n").writerows([heads] + SAMPLE)
        return {"filename": "GRN_import_sample.csv", "csv": out.getvalue(), "columns": heads}
    import os
    ready = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "GRN_import_sample.xlsx")
    if os.path.exists(ready):      # the formatted sample with a "How to fill" sheet
        with open(ready, "rb") as fh:
            return {"filename": "GRN_import_sample.xlsx", "b64": base64.b64encode(fh.read()).decode("ascii"), "columns": heads}
    from api_copilot import make_xlsx
    data = make_xlsx("Goods received - import sheet (every column is required; one row per material; delete the example rows)", heads, SAMPLE)
    return {"filename": "GRN_import_sample.xlsx", "b64": base64.b64encode(data).decode("ascii"), "columns": heads}


def _pan(s):
    return re.sub(r"\D", "", str(s or ""))


def _next_code(c, table, prefix):
    n = 0
    for r in q(c, "SELECT code FROM %s WHERE code LIKE ?" % table, (prefix + "%",)):
        m = re.match(re.escape(prefix) + r"(\d+)$", r["code"] or "")
        if m:
            n = max(n, int(m.group(1)))
    return "%s%04d" % (prefix, n + 1)


@api("grn.import", "inventory", "edit")
def grn_import(c, u, a):
    """apply=0: check every row and every GRN (posting included) and undo it all; apply=1: save.
    post=1 (default) posts each GRN - stock and accounts move; post=0 leaves them as drafts to check first."""
    import api_books as B
    grid, _x = B._grid(a)
    spec = _spec()
    start, cols, unknown = B._map_header(grid, spec)
    if not start:
        raise ApiError("No heading row found. The first row must have the column names of the sample sheet (GRN Date, Project Code, Store ...).")
    missing = [h for f, h, _a in COLUMNS if f not in cols.values()]
    if missing:
        raise ApiError("These columns are missing from the sheet: %s. Every column of the sample sheet is required." % ", ".join(missing))
    raw = []
    for n, r in enumerate(grid[start:], start + 1):
        if not any(str(x).strip() for x in r):
            continue
        raw.append(({f: _clean(r[j]) if j < len(r) else "" for j, f in cols.items()}, n))
    if not raw:
        raise ApiError("The sheet has no rows under the headings.")
    order = a.get("date_order") or "auto"
    if order == "auto":
        order = B._date_order([r["date"] for r, _n in raw if r.get("date")])
    dfrom, dto = (a.get("from") or None), (a.get("to") or None)
    apply_, post = bool(a.get("apply")), a.get("post", 1) not in (0, "0", False, "")
    rows_out, groups = [], {}
    vend_cache, mat_cache = {}, {}
    new_vendors, new_materials = [], []

    c.execute("SAVEPOINT grnimp_all")
    try:
        def vendor_for(r):
            pan = _pan(r["vendor_pan"])
            key = pan or r["vendor_name"].lower()
            if key in vend_cache:
                return vend_cache[key]
            v = None
            if pan:
                v = q1(c, "SELECT * FROM parties WHERE REPLACE(REPLACE(COALESCE(pan,''),' ',''),'-','')=? ORDER BY kind='vendor' DESC, id LIMIT 1", (pan,))
            if not v:
                v = q1(c, "SELECT * FROM parties WHERE LOWER(TRIM(name))=LOWER(?) ORDER BY kind='vendor' DESC, id LIMIT 1", (r["vendor_name"],))
            note = None
            if v:
                if pan and v.get("pan") and _pan(v["pan"]) != pan:
                    note = "vendor %s found by name but its PAN in BuildCore is %s" % (v["name"], v["pan"])
                elif r["vendor_name"].lower() not in v["name"].lower() and v["name"].lower() not in r["vendor_name"].lower():
                    note = "PAN %s belongs to %s in BuildCore - that vendor is used" % (pan, v["name"])
                res = (v["id"], v["name"], False, note, v.get("blacklisted"))
            else:
                code = _next_code(c, "parties", "V-")
                vid = ins(c, "parties", {"code": code, "name": r["vendor_name"], "kind": "vendor", "pan": r["vendor_pan"], "phone": r["vendor_phone"],
                                         "address": r["vendor_address"], "vat_registered": 0, "credit_days": 30, "active": 1,
                                         "notes": "Created by GRN import %s" % today()})
                audit(c, u, "create", "parties", vid, {"code": code, "name": r["vendor_name"], "by": "grn import"})
                new_vendors.append({"code": code, "name": r["vendor_name"], "pan": r["vendor_pan"]})
                res = (vid, r["vendor_name"], True, None, 0)
            vend_cache[key] = res
            return res

        def material_for(r):
            code = r["material_code"].upper()
            if code in mat_cache:
                return mat_cache[code]
            m = q1(c, "SELECT * FROM materials WHERE UPPER(code)=?", (code,))
            note = None
            if m:
                if (m["unit"] or "").strip().lower() != r["unit"].lower():
                    note = "unit in sheet is %s but %s is kept in %s - check the quantity" % (r["unit"], m["code"], m["unit"])
                if not m["active"]:
                    note = (note + "; " if note else "") + "material %s is inactive" % m["code"]
                res = (m["id"], m["name"], False, note)
            else:
                mid = ins(c, "materials", {"code": code, "name": r["material_name"], "unit": r["unit"], "category": "Imported with GRN",
                                           "active": 1, "standard_rate": num(r["rate"]) if r.get("rate") else 0})
                audit(c, u, "create", "materials", mid, {"code": code, "by": "grn import"})
                new_materials.append({"code": code, "name": r["material_name"], "unit": r["unit"]})
                res = (mid, r["material_name"], True, None)
            mat_cache[code] = res
            return res

        for r, line in raw:
            out = {"line": line, "date": r.get("date"), "vendor": r.get("vendor_name"), "challan": r.get("challan_no"),
                   "material": "%s %s" % (r.get("material_code"), r.get("material_name")), "qty": r.get("accepted_qty"), "rate": r.get("rate")}
            rows_out.append(out)
            try:
                empty = [h for f, h, _a in COLUMNS if not r.get(f)]
                if empty:
                    raise ValueError("empty: " + ", ".join(empty))
                try:
                    d = B.norm_date(r["date"], order)
                except Exception:
                    raise ValueError("date '%s' not understood" % r["date"])
                out["date"] = d
                if (dfrom and d < dfrom) or (dto and d > dto):
                    out["status"] = "outside the date range"
                    continue
                if d > today():
                    raise ValueError("date %s is in the future" % d)
                x = {}
                for f in NUMS:
                    try:
                        x[f] = float(B.norm_num(r[f]))
                    except Exception:
                        raise ValueError("%s '%s' is not a number" % (f.replace("_", " "), r[f]))
                if x["received_qty"] <= 0:
                    raise ValueError("received qty must be above zero")
                if x["accepted_qty"] < 0 or x["accepted_qty"] > x["received_qty"] + 1e-9:
                    raise ValueError("accepted qty must be between 0 and the received qty")
                if x["rate"] <= 0:
                    raise ValueError("rate must be above zero")
                p = q1(c, "SELECT id, code, status FROM projects WHERE UPPER(code)=UPPER(?)", (r["project_code"],))
                if not p:
                    raise ValueError("project %s not found" % r["project_code"])
                if p["status"] not in ("active", None, ""):
                    out["warn"] = "project %s is %s" % (p["code"], p["status"])
                s = q1(c, "SELECT id, name FROM stores WHERE project_id=? AND active=1 AND COALESCE(type,'')<>'transit' AND "
                          "(UPPER(COALESCE(code,''))=UPPER(?) OR UPPER(name)=UPPER(?)) ORDER BY id LIMIT 1", (p["id"], r["store"], r["store"]))
                if not s:
                    names = ", ".join((z["code"] or z["name"]) for z in q(c, "SELECT code, name FROM stores WHERE project_id=? AND active=1 AND COALESCE(type,'')<>'transit'", (p["id"],)))
                    raise ValueError("store '%s' not found in %s (stores: %s)" % (r["store"], p["code"], names or "none"))
                vid, vname, vnew, vnote, black = vendor_for(r)
                if black:
                    raise ValueError("vendor %s is blacklisted" % vname)
                mid, mname, mnew, mnote = material_for(r)
                notes = [z for z in (out.get("warn"), vnote, mnote, "new vendor" if vnew else None, "new material" if mnew else None) if z]
                out["note"] = "; ".join(notes)
                key = (d, p["id"], s["id"], vid, r["challan_no"].upper())
                g = groups.setdefault(key, {"date": d, "project_id": p["id"], "project": p["code"], "store_id": s["id"], "store": s["name"],
                                            "vendor_id": vid, "vendor": vname, "challan_no": r["challan_no"], "vehicle_no": r["vehicle_no"],
                                            "lines": [], "rows": [], "value": 0.0})
                g.setdefault("sheet_vendors", set()).add(r["vendor_name"].lower())
                g["lines"].append({"material_id": mid, "received_qty": x["received_qty"], "accepted_qty": x["accepted_qty"], "rate": x["rate"],
                                   "remarks": "Imported (sheet line %d)" % line})
                g["rows"].append(out)
                g["value"] += x["accepted_qty"] * x["rate"]
                out["status"] = "ok"
            except ValueError as e:
                out["status"] = "error"
                out["error"] = str(e)

        # bad rows stop their whole challan, so no GRN is half imported
        bad_keys = set()
        for out in rows_out:
            if out.get("status") == "error":
                for k, g in groups.items():
                    if g["challan_no"].upper() == (out.get("challan") or "").upper() and (out.get("vendor") or "").lower() in g.get("sheet_vendors", ()):
                        bad_keys.add(k)
        res_groups = []
        save, post_fn = FUNCS["doc.save"][0], FUNCS["grn.post"][0]
        for k, g in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[1]["vendor"], kv[1]["challan_no"])):
            info = {"date": g["date"], "project": g["project"], "store": g["store"], "vendor": g["vendor"], "challan_no": g["challan_no"],
                    "lines": len(g["lines"]), "value": round(g["value"], 2)}
            res_groups.append(info)
            if k in bad_keys:
                info.update({"status": "error", "message": "a row of this challan has an error - fix it and import again"})
                for o in g["rows"]:
                    if o["status"] == "ok":
                        o["status"] = "held"
                continue
            dup = q1(c, "SELECT no, status FROM grn WHERE project_id=? AND vendor_id=? AND UPPER(COALESCE(challan_no,''))=? AND date=? "
                        "AND status<>'cancelled' LIMIT 1", (g["project_id"], g["vendor_id"], g["challan_no"].upper(), g["date"]))
            if dup:
                info.update({"status": "already in BuildCore", "message": "%s (%s) - skipped" % (dup["no"] or "draft GRN", dup["status"])})
                for o in g["rows"]:
                    o["status"] = "skipped - already imported"
                continue
            c.execute("SAVEPOINT grnimp_one")
            try:
                doc = save(c, u, {"type": "grn", "header": {"project_id": g["project_id"], "store_id": g["store_id"], "vendor_id": g["vendor_id"],
                                                            "date": g["date"], "challan_no": g["challan_no"], "vehicle_no": g["vehicle_no"],
                                                            "freight": 0, "remarks": "Imported from %s" % (a.get("filename") or "sheet")},
                                  "lines": g["lines"]})
                gid = doc["id"]
                no = None
                if post:
                    no = post_fn(c, u, {"id": gid})["no"]
                c.execute("RELEASE grnimp_one")
                info.update({"status": "posted" if post else "draft", "grn_id": gid, "grn_no": no})
            except Exception as e:
                c.execute("ROLLBACK TO grnimp_one")
                c.execute("RELEASE grnimp_one")
                info.update({"status": "error", "message": str(e)})
                for o in g["rows"]:
                    if o["status"] == "ok":
                        o["status"] = "held"
        ok = [g for g in res_groups if g["status"] in ("posted", "draft")]
        summary = {"rows": len(rows_out), "row_errors": sum(1 for o in rows_out if o.get("status") == "error"),
                   "outside": sum(1 for o in rows_out if o.get("status") == "outside the date range"),
                   "grns": len(ok), "grn_errors": sum(1 for g in res_groups if g["status"] == "error"),
                   "skipped": sum(1 for g in res_groups if g["status"] == "already in BuildCore"),
                   "value": round(sum(g["value"] for g in ok), 2), "new_vendors": len(new_vendors), "new_materials": len(new_materials)}
        if apply_:
            c.execute("RELEASE grnimp_all")
            audit(c, u, "import", "grn", None, dict(summary, file=a.get("filename")))
        else:
            c.execute("ROLLBACK TO grnimp_all")
            c.execute("RELEASE grnimp_all")
    except Exception:
        c.execute("ROLLBACK TO grnimp_all")
        c.execute("RELEASE grnimp_all")
        raise
    return {"applied": apply_, "posted": post, "summary": summary, "groups": res_groups, "rows": rows_out, "new_vendors": new_vendors,
            "new_materials": new_materials, "ignored_columns": unknown,
            "date_order": {"dmy": "day/month/year", "mdy": "month/day/year"}.get(order, order)}
