"""
BuildCore norms library - starter set.

IMPORTANT: these are NOT the Department of Roads (DoR) or DUDBC published coefficients. They are
a working starter set so the rate-analysis screens can be used from day one:

  * material quantities are DERIVED from first principles and shown with their derivation
    (dry-volume factor 1.54 for concrete and 1.30 for mortar, cement 1,440 kg/m3, 50 kg bag,
    brick 240x115x57 with 10 mm joints, stated wastage);
  * labour and equipment coefficients are INDICATIVE, typical of Nepali practice.

Every starter norm carries source "BuildCore starter" and verified = 0. Importing the DoR
"Norms for Rate Analysis of Road and Bridge Works" (and DUDBC building norms) adds those items
with their official codes and verified = 1; the starter items can then be retired.

Line kinds: L labour, M material, E equipment, N sub-norm (another norm's rate, e.g. mortar),
X fixed amount (e.g. sundries %) - qty is a percentage of labour for X lines.
"""

# cement 1440 kg/m3 -> bags per m3 of cement = 28.8
def _conc(c, s, a, factor=1.54):
    t = c + s + a
    cem = factor / t * c
    return round(cem * 28.8, 2), round(factor / t * s, 3), round(factor / t * a, 3)


def _mortar(c, s, factor=1.30):
    t = c + s
    return round(factor / t * c * 28.8, 2), round(factor / t * s, 3)


NORMS = []


def norm(code, section, title, unit, per, lines, remarks="", derivation=""):
    NORMS.append({"code": code, "source": "BuildCore starter", "section": section, "title": title, "unit": unit,
                  "per_qty": per, "lines": lines, "remarks": remarks, "derivation": derivation, "verified": 0})


# ── mortars and concrete mixes (used as sub-norms) ─────────────────────────────
for code, (c, s) in (("BC-MOR-13", (1, 3)), ("BC-MOR-14", (1, 4)), ("BC-MOR-15", (1, 5)), ("BC-MOR-16", (1, 6))):
    bags, sand = _mortar(c, s)
    norm(code, "Mortar", "Cement-sand mortar 1:%d" % s, "m3", 1,
         [("M", "M-CEM-01", bags, "cement"), ("M", "M-SND-01", sand, "sand"), ("M", "M-CON-01", 0.25, "water"),
          ("L", "L-001", 1.0, "mixing"), ],
         derivation="Dry volume 1.30 m3 per m3 wet; 1:%d -> cement %.3f m3 x 1440 kg = %.2f bags; sand %.3f m3"
                    % (s, 1.30 / (c + s), bags, sand))

for code, mix, grade in (("BC-PCC-01", (1, 4, 8), "M7.5"), ("BC-PCC-02", (1, 3, 6), "M10"), ("BC-PCC-03", (1, 2, 4), "M15"),
                         ("BC-PCC-04", (1, 1.5, 3), "M20")):
    bags, sand, agg = _conc(*mix)
    norm(code, "Concrete", "Nominal mix concrete %s (%s:%s:%s), machine-mixed, placed & vibrated" % ((grade,) + mix), "m3", 1,
         [("M", "M-CEM-01", bags, "cement"), ("M", "M-SND-01", sand, "coarse sand"), ("M", "M-AGG-04", agg, "20 mm aggregate"),
          ("M", "M-CON-01", 0.20, "water incl. curing"),
          ("L", "L-010", 0.17, "mason"), ("L", "L-001", 2.0, "labour: mixing, carrying, placing"), ("L", "L-015", 0.1, "finisher"),
          ("E", "E-CON-02", 0.40, "mixer 10/7 at about 2.5 m3/h"), ("E", "E-CON-13", 0.40, "needle vibrator")],
         derivation="Dry volume 1.54; cement 1440 kg/m3; %s -> %.2f bags cement, %.3f m3 sand, %.3f m3 aggregate"
                    % (":".join(str(x) for x in mix), bags, sand, agg))

for code, grade, cem, sand, agg, pce in (("BC-RCC-25", "M25", 380, 0.45, 0.85, 3.8), ("BC-RCC-30", "M30", 420, 0.43, 0.84, 4.2),
                                         ("BC-RCC-35", "M35", 450, 0.42, 0.82, 4.5)):
    norm(code, "Concrete", "Design mix concrete %s by batching plant, transit mixer and pump" % grade, "m3", 1,
         [("M", "M-CEM-01", round(cem / 50 * 1.02, 2), "cement incl. 2% handling loss"), ("M", "M-SND-03", sand, "sand"),
          ("M", "M-AGG-04", round(agg * 0.6, 3), "20 mm"), ("M", "M-AGG-02", round(agg * 0.4, 3), "10 mm"),
          ("M", "M-ADM-02", pce, "PCE superplasticiser ~1% of cement"), ("M", "M-CON-01", 0.25, "water incl. curing"),
          ("L", "L-047", 0.02, "plant operator"), ("L", "L-010", 0.08, "mason"), ("L", "L-001", 0.6, "placing & curing"),
          ("E", "E-CON-06", 0.02, "batching plant 60 m3/h at 50 m3/h"), ("E", "E-CON-08", 0.08, "transit mixer, 2 km lead"),
          ("E", "E-CON-11", 0.03, "pump"), ("E", "E-CON-13", 0.15, "vibrators")],
         remarks="Replace cement/aggregate with the approved mix design (IS 10262).",
         derivation="Typical %s design: cement %d kg, sand %.2f m3, aggregate %.2f m3 (60/40 split 20/10 mm)" % (grade, cem, sand, agg))

# ── earthwork ───────────────────────────────────────────────────────────────
norm("BC-EW-01", "Earthwork", "Excavation in ordinary soil by excavator 0.9 m3, loading into tipper", "m3", 100,
     [("E", "E-EXC-04", 1.5, "about 65 m3/h"), ("L", "L-001", 3.0, "trimming & helpers"), ("L", "L-060", 0.1, "")])
norm("BC-EW-02", "Earthwork", "Excavation in hard soil / soft rock by excavator with ripper", "m3", 100,
     [("E", "E-EXC-10", 3.0, ""), ("L", "L-001", 4.0, ""), ("L", "L-060", 0.2, "")])
norm("BC-EW-03", "Earthwork", "Excavation in hard rock by hydraulic breaker (no blasting)", "m3", 10,
     [("E", "E-EXC-09", 2.5, "about 4 m3/h"), ("E", "E-EXC-04", 0.3, "loading"), ("L", "L-001", 3.0, "")])
norm("BC-EW-04", "Earthwork", "Excavation in hard rock by drilling & blasting (open cut)", "m3", 10,
     [("E", "E-CMP-02", 1.2, "compressor"), ("E", "E-CMP-05", 2.4, "2 jack hammers"), ("M", "M-EXP-03", 4.0, "0.4 kg/m3"),
      ("M", "M-EXP-06", 8.0, "detonators"), ("M", "M-EXP-08", 20.0, ""), ("M", "M-DRL-07", 0.05, "drill steel wear"),
      ("L", "L-050", 2.0, ""), ("L", "L-052", 0.5, ""), ("L", "L-001", 6.0, "")])
norm("BC-EW-05", "Earthwork", "Manual excavation in ordinary soil up to 1.5 m depth, lead 10 m", "m3", 1,
     [("L", "L-001", 0.75, "")])
norm("BC-EW-06", "Earthwork", "Embankment with borrow material, spread & compacted in 200 mm layers to 95% MDD", "m3", 100,
     [("M", "M-ERT-01", 120.0, "20% bulking allowance"), ("E", "E-GRD-01", 0.8, ""), ("E", "E-RLR-05", 1.2, ""),
      ("E", "E-TRK-10", 0.8, "watering"), ("M", "M-CON-01", 10.0, "water"), ("L", "L-001", 4.0, "")])
norm("BC-EW-07", "Earthwork", "Backfilling with excavated material, compacted by plate compactor", "m3", 10,
     [("L", "L-001", 3.0, ""), ("E", "E-RLR-01", 2.0, ""), ("M", "M-CON-01", 1.0, "")])
norm("BC-EW-08", "Earthwork", "Haulage of excavated material by tipper, 1 km lead", "m3", 100,
     [("E", "E-TRK-02", 2.5, "10 m3 tipper, 20 min cycle"), ("L", "L-001", 1.0, "")])

# ── masonry ─────────────────────────────────────────────────────────────────
norm("BC-MAS-01", "Masonry", "Brick masonry in cement mortar 1:4 (machine-made brick)", "m3", 1,
     [("M", "M-BRK-01", 500, "478 bricks/m3 + ~5% wastage"), ("N", "BC-MOR-14", 0.25, "mortar incl. frog filling"),
      ("L", "L-010", 1.2, ""), ("L", "L-001", 2.0, ""), ("M", "M-CON-01", 0.05, "wetting & curing")],
     derivation="Brick with joint 0.25 x 0.125 x 0.067 = 0.002094 m3 -> 478 no/m3; mortar = 1 - 478 x 0.00157 = 0.25 m3")
norm("BC-MAS-02", "Masonry", "Brick masonry in cement mortar 1:6", "m3", 1,
     [("M", "M-BRK-01", 500, ""), ("N", "BC-MOR-16", 0.25, ""), ("L", "L-010", 1.2, ""), ("L", "L-001", 2.0, "")])
norm("BC-MAS-03", "Masonry", "Random rubble stone masonry in cement mortar 1:6", "m3", 1,
     [("M", "M-STN-03", 1.10, "stone"), ("N", "BC-MOR-16", 0.40, "mortar"), ("L", "L-010", 1.5, ""), ("L", "L-001", 3.0, "")])
norm("BC-MAS-04", "Masonry", "Random rubble stone masonry in cement mortar 1:4", "m3", 1,
     [("M", "M-STN-03", 1.10, ""), ("N", "BC-MOR-14", 0.40, ""), ("L", "L-010", 1.5, ""), ("L", "L-001", 3.0, "")])
norm("BC-MAS-05", "Masonry", "Dry stone masonry / pitching", "m3", 1,
     [("M", "M-STN-03", 1.25, ""), ("L", "L-010", 1.0, ""), ("L", "L-001", 2.0, "")])
norm("BC-MAS-06", "Masonry", "Hollow concrete block masonry 200 mm in 1:6", "m2", 1,
     [("M", "M-BLK-03", 12.8, "12.5/m2 + wastage"), ("N", "BC-MOR-16", 0.012, ""), ("L", "L-010", 0.15, ""), ("L", "L-001", 0.25, "")])
norm("BC-GAB-01", "Gabion", "Gabion works: supply, weave (4 mm mesh wire) & fill boulders", "m3", 1,
     [("M", "M-GAB-01", 11.0, "mesh 100x120 box incl. lacing"), ("M", "M-GAB-04", 0.8, "lacing wire"),
      ("M", "M-STN-02", 1.20, "boulders incl. voids packing"), ("L", "L-016", 0.5, ""), ("L", "L-001", 1.5, "")],
     remarks="Wire kg per m3 depends on box size; set from DoR/NS gabion schedule.")

# ── plaster, reinforcement, formwork ────────────────────────────────────────
norm("BC-PLS-01", "Finishes", "12 mm cement plaster 1:4 on walls", "m2", 10,
     [("N", "BC-MOR-14", 0.16, "12 mm + 33% for joints & wastage"), ("L", "L-013", 0.8, ""), ("L", "L-001", 0.8, "")])
norm("BC-PLS-02", "Finishes", "20 mm cement plaster 1:6 on rough stone", "m2", 10,
     [("N", "BC-MOR-16", 0.26, ""), ("L", "L-013", 1.0, ""), ("L", "L-001", 1.0, "")])
norm("BC-PNT-01", "Finishes", "Two coats of exterior acrylic emulsion over primer", "m2", 10,
     [("M", "M-PNT-06", 1.0, "primer"), ("M", "M-PNT-03", 1.6, "2 coats"), ("L", "L-030", 0.6, ""), ("L", "L-001", 0.2, "")])
norm("BC-RFT-01", "Reinforcement", "Reinforcement Fe500: cut, bend, place & tie", "t", 1,
     [("M", "M-RBR-04", 1025, "2.5% cutting wastage"), ("M", "M-RBR-20", 10, "binding wire"), ("M", "M-RBR-26", 40, "cover blocks"),
      ("L", "L-022", 6.0, ""), ("L", "L-001", 6.0, ""), ("E", "E-CON-17", 2.0, ""), ("E", "E-CON-18", 2.0, "")])
norm("BC-FRM-01", "Formwork", "Plywood formwork to walls & foundations incl. staging, removal", "m2", 10,
     [("M", "M-PLY-10", 2.2, "5 uses"), ("M", "M-TIM-02", 0.08, "salla battens, 8 uses"), ("M", "M-FIX-01", 1.5, ""),
      ("M", "M-FRM-07", 0.5, ""), ("M", "M-FRM-06", 3.0, ""), ("L", "L-020", 2.0, ""), ("L", "L-001", 2.0, "")])
norm("BC-FRM-02", "Formwork", "Formwork to slab soffit with steel props up to 3.5 m", "m2", 10,
     [("M", "M-PLY-10", 2.2, ""), ("M", "M-TIM-02", 0.1, ""), ("M", "M-FRM-02", 0.1, "prop wear (props hired)"),
      ("M", "M-FIX-01", 1.2, ""), ("M", "M-FRM-07", 0.5, ""), ("L", "L-020", 2.5, ""), ("L", "L-001", 2.5, "")])

# ── road pavement ───────────────────────────────────────────────────────────
norm("BC-RD-01", "Pavement", "Granular sub-base, spread, watered & compacted", "m3", 100,
     [("M", "M-AGG-12", 125.0, "25% compaction allowance"), ("E", "E-GRD-01", 1.2, ""), ("E", "E-RLR-05", 1.6, ""),
      ("E", "E-TRK-10", 1.0, ""), ("M", "M-CON-01", 12.0, ""), ("L", "L-001", 5.0, "")])
norm("BC-RD-02", "Pavement", "Crushed stone base course, spread & compacted", "m3", 100,
     [("M", "M-AGG-13", 128.0, ""), ("E", "E-GRD-02", 1.4, ""), ("E", "E-RLR-06", 1.8, ""), ("E", "E-TRK-10", 1.2, ""),
      ("M", "M-CON-01", 14.0, ""), ("L", "L-001", 6.0, "")])
norm("BC-RD-03", "Pavement", "Prime coat with MC-30 at 1.0 kg/m2", "m2", 100,
     [("M", "M-BIT-07", 100.0, "application rate per design (0.6-1.2)"), ("E", "E-RD-09", 0.2, "broom"),
      ("E", "E-RD-02", 0.15, "distributor"), ("L", "L-001", 1.0, "")])
norm("BC-RD-04", "Pavement", "Tack coat with SS-1 emulsion at 0.25 kg/m2", "m2", 100,
     [("M", "M-BIT-06", 25.0, ""), ("E", "E-RD-09", 0.2, ""), ("E", "E-RD-02", 0.1, ""), ("L", "L-001", 0.5, "")])
norm("BC-RD-05", "Pavement", "Double bituminous surface treatment (DBST) with 60/70 bitumen", "m2", 100,
     [("M", "M-BIT-01", 320.0, "1st spray 1.9 + 2nd 1.3 kg/m2"), ("M", "M-AGG-11", 1.4, "14-20 chips"),
      ("M", "M-AGG-09", 0.8, "6-10 chips"), ("M", "M-BIT-10", 30.0, "heating fuel"),
      ("E", "E-RD-02", 0.3, ""), ("E", "E-RD-04", 0.4, ""), ("E", "E-RLR-09", 0.4, ""), ("E", "E-RD-09", 0.2, ""),
      ("L", "L-001", 4.0, ""), ("L", "L-041", 0.3, "")], remarks="Spray & chip rates from design (DoR Spec 1300 ranges).")
norm("BC-RD-06", "Pavement", "Asphalt concrete 50 mm with VG-30, hot-mix, paver laid & rolled", "m3", 10,
     [("M", "M-BIT-03", 1290.0, "5.5% of 23.5 t mix"), ("M", "M-AGG-16", 10.6, "graded aggregate incl. dust"),
      ("M", "M-AGG-14", 0.6, "filler"), ("E", "E-RD-06", 0.5, ""), ("E", "E-LDR-02", 0.5, "feeding"),
      ("E", "E-TRK-02", 1.5, "haul"), ("E", "E-RD-08", 0.5, ""), ("E", "E-RLR-08", 0.5, ""), ("E", "E-RLR-09", 0.5, ""),
      ("E", "E-GEN-05", 0.5, ""), ("M", "M-FUL-01", 150.0, "drying fuel"), ("L", "L-001", 6.0, ""), ("L", "L-060", 0.5, "")],
     remarks="Bitumen content from the approved job-mix formula.")

# ── tunnelling (hydropower headrace) ────────────────────────────────────────
norm("BC-TUN-01", "Tunnel", "Drill & blast excavation, 20 m2 face, rock class II-III, jumbo & LHD, 3 m pull", "m3", 60,
     [("E", "E-TUN-02", 2.5, "2-boom jumbo, 45 holes x 3.4 m"), ("M", "M-EXP-02", 84.0, "specific charge 1.4 kg/m3"),
      ("M", "M-EXP-07", 45.0, "Nonel per hole"), ("M", "M-EXP-08", 30.0, ""), ("M", "M-DRL-01", 0.6, "bit wear"),
      ("M", "M-DRL-04", 0.06, "rod wear"), ("M", "M-DRL-05", 0.03, ""), ("E", "E-TUN-05", 2.0, "mucking"),
      ("E", "E-TUN-07", 3.0, "haul to portal/adit"), ("E", "E-TUN-10", 0.8, "scaling"), ("E", "E-TUN-12", 8.0, "ventilation per cycle"),
      ("E", "E-GEN-06", 8.0, ""), ("L", "L-051", 2.0, ""), ("L", "L-052", 1.0, ""), ("L", "L-054", 6.0, ""),
      ("L", "L-058", 1.0, ""), ("L", "L-060", 1.0, "")], remarks="One round = 60 m3 in place. Tune per rock class and face area.")
norm("BC-TUN-02", "Tunnel", "Shotcrete wet-mix M25 with alkali-free accelerator, 20% rebound", "m3", 1,
     [("M", "M-CEM-01", 10.8, "450 kg x 1.2 rebound"), ("M", "M-SND-03", 0.72, ""), ("M", "M-AGG-01", 0.54, "6-10 mm"),
      ("M", "M-ADM-04", 27.0, "5% of cement"), ("M", "M-ADM-02", 5.4, ""), ("E", "E-CON-23", 0.3, "sprayer"),
      ("E", "E-CON-06", 0.03, ""), ("E", "E-CON-08", 0.25, ""), ("L", "L-053", 0.3, ""), ("L", "L-054", 1.0, "")])
norm("BC-TUN-03", "Tunnel", "Steel-fibre reinforced shotcrete (SFRS) — fibre extra over shotcrete", "m3", 1,
     [("M", "M-RBR-23", 48.0, "40 kg/m3 x 1.2 rebound"), ("L", "L-054", 0.2, "")])
norm("BC-TUN-04", "Tunnel", "Fully grouted rock bolt 25 mm x 3 m, drilled, grouted & plated", "no", 1,
     [("M", "M-RBT-01", 1, ""), ("M", "M-RBT-20", 1, ""), ("M", "M-CEM-01", 0.35, "grout"), ("M", "M-ADM-09", 2.0, ""),
      ("E", "E-TUN-04", 0.15, "bolting rig"), ("E", "E-TUN-16", 0.1, ""), ("M", "M-DRL-01", 0.01, ""),
      ("L", "L-054", 0.15, ""), ("L", "L-056", 0.05, "")])
norm("BC-TUN-05", "Tunnel", "Lattice girder support, erected incl. bolts & ties", "t", 1,
     [("M", "M-RBT-23", 1000, ""), ("M", "M-RBT-25", 40, ""), ("M", "M-FIX-02", 15, ""), ("E", "E-TUN-20", 6, ""),
      ("L", "L-025", 4, ""), ("L", "L-054", 8, "")])
norm("BC-TUN-06", "Tunnel", "Contact / consolidation grouting, cement", "t", 1,
     [("M", "M-CEM-01", 21.0, "cement 1 t + 5%"), ("M", "M-ADM-12", 20.0, "bentonite 2%"), ("E", "E-TUN-16", 6, ""),
      ("E", "E-CMP-13", 3, "drilling holes"), ("L", "L-056", 3, ""), ("L", "L-001", 6, "")])

# ── hydromechanical & misc ──────────────────────────────────────────────────
norm("BC-HM-01", "Hydro-mechanical", "Penstock pipe: transport on site, erection, field welding & NDT", "t", 1,
     [("M", "M-STL-01", 1.0, "shop-fabricated"), ("M", "M-FIX-06", 12, "electrodes"), ("M", "M-FIX-07", 1.5, ""),
      ("M", "M-FIX-08", 0.5, ""), ("E", "E-CRN-02", 2.5, ""), ("E", "E-WLD-01", 12, ""), ("E", "E-WLD-07", 2, ""),
      ("E", "E-WLD-08", 1, ""), ("E", "E-CRN-16", 3, ""), ("L", "L-024", 4, ""), ("L", "L-025", 3, ""), ("L", "L-026", 3, ""),
      ("L", "L-001", 6, "")])
norm("BC-HM-02", "Hydro-mechanical", "Painting of penstock: blast SA 2.5, zinc primer + 2 coats epoxy", "m2", 10,
     [("M", "M-PNT-09", 1.0, ""), ("M", "M-PNT-10", 3.0, ""), ("M", "M-PNT-14", 0.5, ""), ("E", "E-WLD-09", 1.0, ""),
      ("E", "E-WLD-10", 0.5, ""), ("L", "L-030", 1.5, ""), ("L", "L-001", 1.0, "")])
norm("BC-BIO-01", "Bio-engineering", "Grass slip planting on slopes at 10 cm spacing in rows", "m2", 100,
     [("M", "M-BIO-01", 2000, ""), ("M", "M-BIO-06", 0.5, ""), ("L", "L-070", 4.0, "")])
norm("BC-SC-01", "Site clearance", "Clearing & grubbing of light jungle including disposal", "m2", 1000,
     [("L", "L-001", 15.0, ""), ("E", "E-DOZ-02", 1.0, ""), ("E", "E-SML-02", 2.0, "")])
