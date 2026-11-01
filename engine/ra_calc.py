"""
Rate analysis engine (pure functions).

Build-up follows the DoR / DUDBC convention used in Nepal:

    labour + material (+ cartage to site) + equipment      for the norm quantity
    ÷ norm quantity                                         = cost per unit
    + contractor's overhead & profit (default 15%)         = rate excluding VAT
    + VAT (13%) where the estimate is shown VAT-inclusive

Sub-norms (a mortar inside masonry, a concrete mix inside a structure item) are analysed
recursively at cost - overhead is added once, on the parent.
"""

KINDS = {"L": "Labour", "M": "Material", "E": "Equipment", "N": "Sub-analysis", "X": "Sundries"}
X_BASES = {"L": "labour", "M": "material", "E": "equipment", "LM": "labour + material", "LE": "labour + equipment",
           "ME": "material + equipment", "LME": "labour + material + equipment"}


def r2(x):
    return round((x or 0) + 0.0, 2)


def cartage_per_unit(weight_kg, leads, trates):
    """weight_kg per unit; leads {transport_code: km or trips}; trates {code: (rate, unit)}.
    t-km rates multiply by tonnes x km; 't' rates (loading/unloading) by tonnes only."""
    if not weight_kg or not leads:
        return 0.0
    t = weight_kg / 1000.0
    tot = 0.0
    for code, km in leads.items():
        rate, unit = trates.get(code, (0, "t-km"))
        tot += t * rate * (km if unit == "t-km" else (km or 1))
    return tot


def analyse(norm, resources, norms, overhead_pct=15.0, vat_pct=13.0, leads=None, trates=None, _depth=0):
    """
    norm: {code, title, unit, per_qty, lines:[{kind, ref, qty, note}], verified}
    resources: {code: {name, unit, rate, weight, sample}}
    norms: {code: norm}  (for sub-norms)
    Returns the full build-up.
    """
    if _depth > 6:
        raise ValueError("Sub-analysis nesting too deep (circular reference?) at " + norm["code"])
    leads, trates = leads or {}, trates or {}
    warn = []
    tot = {"L": 0.0, "M": 0.0, "E": 0.0, "N": 0.0, "X": 0.0, "C": 0.0}
    per = float(norm.get("per_qty") or 1)
    lines = list(norm["lines"])
    # percentage lines ("3% of labour for tools", "1.5% of the total for water") are worked out after the other
    # lines, whatever their order in the norm, on the totals named by the letters in ref (L, M, E, LM, LME; blank = L)
    order = [i for i, x in enumerate(lines) if x["kind"] != "X"] + [i for i, x in enumerate(lines) if x["kind"] == "X"]
    out_rows = {}
    for i in order:
        ln = lines[i]
        k, ref, qty = ln["kind"], ln["ref"], float(ln.get("qty") or 0)
        row = {"kind": k, "ref": ref, "qty": qty, "note": ln.get("note") or ""}
        out_rows[i] = row
        if k == "X":
            letters = "".join(ch for ch in str(ref or "").upper() if ch in "LME") or "L"
            base = sum(tot[ch] + (tot["N"] + tot["C"] if ch == "M" else 0) for ch in dict.fromkeys(letters))
            row.update({"name": ln.get("note") or "Sundries", "unit": "%% of %s" % X_BASES.get(letters, letters),
                        "rate": r2(base), "amount": r2(base * qty / 100)})
        elif k == "N":
            sub = norms.get(ref)
            if not sub:
                warn.append("Sub-analysis %s not found" % ref)
                row.update({"name": ref, "unit": "", "rate": 0, "amount": 0})
            else:
                a = analyse(sub, resources, norms, 0, 0, leads, trates, _depth + 1)
                warn += ["%s: %s" % (ref, w) for w in a["warnings"]]
                row.update({"name": sub["title"], "unit": sub["unit"], "rate": a["cost_per_unit"],
                            "amount": r2(a["cost_per_unit"] * qty)})
        else:
            res = resources.get(ref)
            if not res:
                warn.append("Resource %s is not in the pool" % ref)
                row.update({"name": ref, "unit": "", "rate": 0, "amount": 0})
            else:
                rate = res.get("rate")
                if rate in (None, ""):
                    warn.append("No rate for %s %s" % (ref, res["name"]))
                    rate = 0
                elif res.get("sample"):
                    warn.append("Sample rate used for %s %s" % (ref, res["name"]))
                rate = float(rate)
                row.update({"name": res["name"], "unit": res["unit"], "rate": r2(rate), "amount": r2(rate * qty)})
                if k == "M":
                    c = cartage_per_unit(float(res.get("weight") or 0), leads, trates)
                    if c:
                        row["cartage_rate"] = r2(c)
                        row["cartage"] = r2(c * qty)
                        tot["C"] += c * qty
        tot[k] += row["amount"]
    rows = [out_rows[i] for i in range(len(lines))]
    direct = sum(tot.values())
    cpu = direct / per
    oh = cpu * overhead_pct / 100.0
    ex = cpu + oh
    vat = ex * vat_pct / 100.0
    if not norm.get("verified"):
        warn.insert(0, "Norm %s is not a verified DoR/DUDBC norm (%s)" % (norm["code"], norm.get("source") or "user"))
    return {"code": norm["code"], "title": norm["title"], "unit": norm["unit"], "per_qty": per, "rows": rows,
            "labour": r2(tot["L"]), "material": r2(tot["M"] + tot["N"]), "cartage": r2(tot["C"]),
            "equipment": r2(tot["E"]), "sundries": r2(tot["X"]), "sub": r2(tot["N"]), "direct": r2(direct),
            "cost_per_unit": r2(cpu), "overhead_pct": overhead_pct, "overhead": r2(oh), "rate_ex_vat": r2(ex),
            "vat_pct": vat_pct, "vat": r2(vat), "rate_incl_vat": r2(ex + vat),
            "warnings": list(dict.fromkeys(warn))}
