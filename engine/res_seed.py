"""
BuildCore resource pool - the shipped catalogue of construction materials, labour, equipment and
transport. Users pick from it instead of creating masters one by one, edit it freely, and add
their own lines. Codes are stable: M- material, L- labour, E- equipment, T- transport.

"weight" is kg per unit, used to work out cartage by tonne-km.
"rate" is a SAMPLE rate (NPR, Kathmandu valley, FY 2082/83 order of magnitude) so that analyses
can be tried out; it is flagged as a sample everywhere and must be replaced with the District
Rate Committee (DRC) rate or a quotation before any estimate is issued.
"""

POOL = []


def add(code, typ, cat, name, unit, weight=0, rate=None, spec="", sub=""):
    POOL.append({"code": code, "type": typ, "category": cat, "subcategory": sub, "name": name, "spec": spec,
                 "unit": unit, "weight": weight, "rate": rate})


def series(prefix, typ, cat, fmt, sizes, unit, weight_fn=lambda s: 0, rate_fn=lambda s: None, spec="", sub=""):
    for i, s in enumerate(sizes, 1):
        add("%s-%02d" % (prefix, i) if len(sizes) < 100 else "%s-%03d" % (prefix, i), typ, cat, fmt.format(s=s), unit,
            weight_fn(s), rate_fn(s), spec, sub)


M, L, E, T = "material", "labour", "equipment", "transport"   # plus "tool" (res_seed_ext)

# ════════════════════════════ MATERIALS ════════════════════════════
# cement and binders
C = "Cement & binders"
add("M-CEM-01", M, C, "Ordinary Portland Cement 43 grade", "bag", 50, 800, "NS 049 / IS 269, 50 kg bag")
add("M-CEM-02", M, C, "Ordinary Portland Cement 53 grade", "bag", 50, 850, "IS 269, 50 kg bag")
add("M-CEM-03", M, C, "Portland Pozzolana Cement (PPC)", "bag", 50, 760, "NS 385 / IS 1489, 50 kg bag")
add("M-CEM-04", M, C, "Portland Slag Cement (PSC)", "bag", 50, 760, "IS 455, 50 kg bag")
add("M-CEM-05", M, C, "OPC in bulk", "t", 1000, 15500, "Bulk tanker delivery")
add("M-CEM-06", M, C, "Sulphate resisting cement", "bag", 50, 1000, "IS 12330")
add("M-CEM-07", M, C, "White cement", "kg", 1, 60, "IS 8042")
add("M-CEM-08", M, C, "Hydrated lime", "kg", 1, 25, "IS 712")
add("M-CEM-09", M, C, "Fly ash (pozzolana)", "t", 1000, 6000, "IS 3812")
add("M-CEM-10", M, C, "Micro silica / silica fume", "kg", 1, 95, "IS 15388")
add("M-CEM-11", M, C, "Ground granulated blast furnace slag", "t", 1000, 9000, "IS 16714")
add("M-CEM-12", M, C, "Rapid hardening cement", "bag", 50, 950, "IS 8041")
add("M-CEM-13", M, C, "Micro-fine cement for grouting", "kg", 1, 120, "Blaine > 6000")

# aggregates, sand, stone, earth
A = "Aggregates, sand & stone"
add("M-SND-01", M, A, "Coarse sand (river)", "m3", 1600, 3200, "Zone II, FM 2.6-3.2", "Sand")
add("M-SND-02", M, A, "Fine sand (plaster)", "m3", 1550, 3000, "Zone III-IV", "Sand")
add("M-SND-03", M, A, "Crushed / manufactured sand", "m3", 1650, 3400, "From crusher, washed", "Sand")
add("M-SND-04", M, A, "Filling sand", "m3", 1550, 1800, "", "Sand")
add("M-SND-05", M, A, "Bedding sand for pipes / paving", "m3", 1550, 2500, "", "Sand")
add("M-SND-06", M, A, "Filter sand", "m3", 1600, 3500, "Graded to specification", "Sand")
for i, s in enumerate(["6 mm", "10 mm", "12.5 mm", "20 mm", "25 mm", "40 mm", "63 mm"], 1):
    add("M-AGG-%02d" % i, M, A, "Crushed aggregate %s nominal" % s, "m3", 1550, [3800, 3700, 3600, 3500, 3400, 3300, 3200][i - 1],
        "IS 383 graded", "Aggregate")
add("M-AGG-08", M, A, "Natural gravel (rounded)", "m3", 1650, 2600, "", "Aggregate")
add("M-AGG-09", M, A, "Stone chips 6-10 mm (surface dressing)", "m3", 1450, 4200, "DoR Spec 1300", "Road aggregate")
add("M-AGG-10", M, A, "Stone chips 10-14 mm (surface dressing)", "m3", 1450, 4100, "DoR Spec 1300", "Road aggregate")
add("M-AGG-11", M, A, "Stone chips 14-20 mm (surface dressing)", "m3", 1450, 4000, "DoR Spec 1300", "Road aggregate")
add("M-AGG-12", M, A, "Granular sub-base material", "m3", 1900, 2200, "DoR Spec 1201, grading I-III", "Road aggregate")
add("M-AGG-13", M, A, "Crushed stone base course (crusher run)", "m3", 2000, 3000, "DoR Spec 1202", "Road aggregate")
add("M-AGG-14", M, A, "Stone dust / filler", "m3", 1600, 2500, "", "Road aggregate")
add("M-AGG-15", M, A, "Aggregate for bituminous macadam", "m3", 1550, 3900, "", "Road aggregate")
add("M-AGG-16", M, A, "Aggregate for asphalt concrete (graded)", "m3", 1550, 4200, "", "Road aggregate")
add("M-STN-01", M, A, "Boulders 150-300 mm", "m3", 1700, 2200, "", "Stone")
add("M-STN-02", M, A, "Boulders for gabion filling", "m3", 1700, 2000, "", "Stone")
add("M-STN-03", M, A, "Stone for masonry (undressed)", "m3", 1700, 2400, "", "Stone")
add("M-STN-04", M, A, "Dressed stone for ashlar masonry", "m3", 2400, 9000, "", "Stone")
add("M-STN-05", M, A, "Stone spalls / quarry spall", "m3", 1600, 1800, "", "Stone")
add("M-STN-06", M, A, "Rip-rap stone 300-600 mm", "m3", 1750, 2600, "", "Stone")
add("M-STN-07", M, A, "Rip-rap stone > 600 mm", "m3", 1800, 3000, "", "Stone")
add("M-STN-08", M, A, "Flag stone / slate", "m2", 60, 900, "", "Stone")
add("M-STN-09", M, A, "Kerb stone (dressed)", "m", 60, 700, "", "Stone")
add("M-ERT-01", M, A, "Borrow earth for embankment", "m3", 1800, 600, "Approved borrow", "Earth")
add("M-ERT-02", M, A, "Selected subgrade material", "m3", 1850, 900, "CBR as specified", "Earth")
add("M-ERT-03", M, A, "Top soil", "m3", 1400, 800, "", "Earth")
add("M-ERT-04", M, A, "Clay for puddle / core", "m3", 1800, 900, "", "Earth")
add("M-ERT-05", M, A, "Graded filter material", "m3", 1800, 3500, "", "Earth")

# bricks and blocks
B = "Bricks & blocks"
add("M-BRK-01", M, B, "Machine-made brick class A", "no", 3.2, 18, "240x115x57 mm, NS 1/2035", "Brick")
add("M-BRK-02", M, B, "Machine-made brick class B", "no", 3.1, 15, "240x115x57 mm", "Brick")
add("M-BRK-03", M, B, "Local / chimney brick", "no", 3.0, 13, "", "Brick")
add("M-BRK-04", M, B, "Fly-ash brick", "no", 3.0, 12, "IS 12894", "Brick")
add("M-BRK-05", M, B, "Compressed stabilised earth block", "no", 7, 30, "", "Brick")
add("M-BLK-01", M, B, "Hollow concrete block 100 mm", "no", 10, 45, "400x200x100", "Block")
add("M-BLK-02", M, B, "Hollow concrete block 150 mm", "no", 13, 60, "400x200x150", "Block")
add("M-BLK-03", M, B, "Hollow concrete block 200 mm", "no", 16, 75, "400x200x200", "Block")
add("M-BLK-04", M, B, "Solid concrete block 200 mm", "no", 24, 90, "400x200x200", "Block")
add("M-BLK-05", M, B, "AAC block 600x200x100", "no", 8, 120, "IS 2185-3", "Block")
add("M-BLK-06", M, B, "AAC block 600x200x200", "no", 16, 230, "IS 2185-3", "Block")
add("M-BLK-07", M, B, "Interlocking paver block 60 mm", "m2", 130, 950, "M30", "Paving")
add("M-BLK-08", M, B, "Interlocking paver block 80 mm", "m2", 175, 1150, "M35", "Paving")
add("M-BLK-09", M, B, "Precast concrete kerb 300x150", "m", 90, 650, "", "Paving")
add("M-BLK-10", M, B, "Grass paver block", "m2", 110, 1100, "", "Paving")

# reinforcement
S = "Steel & metals"
for i, d in enumerate([8, 10, 12, 16, 20, 25, 28, 32], 1):
    add("M-RBR-%02d" % i, M, S, "TMT bar Fe500 %d mm" % d, "kg", 1, 104, "NS 191 / IS 1786 Fe500", "Reinforcement")
for i, d in enumerate([8, 10, 12, 16, 20, 25, 32], 1):
    add("M-RBD-%02d" % i, M, S, "TMT bar Fe500D %d mm" % d, "kg", 1, 108, "IS 1786 Fe500D (seismic)", "Reinforcement")
for i, d in enumerate([6, 8, 10, 12], 1):
    add("M-MSB-%02d" % i, M, S, "Mild steel round bar %d mm" % d, "kg", 1, 102, "IS 432 / IS 2062", "Reinforcement")
add("M-RBR-20", M, S, "Binding wire 18 SWG (black annealed)", "kg", 1, 150, "", "Reinforcement")
add("M-RBR-21", M, S, "Welded steel wire fabric (mesh) 150x150x6", "m2", 3, 350, "IS 1566", "Reinforcement")
add("M-RBR-22", M, S, "Welded mesh 100x100x4", "m2", 2, 260, "", "Reinforcement")
add("M-RBR-23", M, S, "Steel fibre for shotcrete (hooked end)", "kg", 1, 220, "EN 14889-1", "Reinforcement")
add("M-RBR-24", M, S, "Macro synthetic fibre", "kg", 1, 650, "EN 14889-2", "Reinforcement")
add("M-RBR-25", M, S, "Rebar coupler (mechanical) 25-32 mm", "no", 1, 450, "", "Reinforcement")
add("M-RBR-26", M, S, "Cover blocks (concrete)", "no", 0.1, 5, "", "Reinforcement")
add("M-RBR-27", M, S, "Prestressing strand 12.7 mm", "kg", 1, 180, "IS 14268", "Reinforcement")
# structural sections
for i, s in enumerate([100, 125, 150, 175, 200, 225, 250, 300, 350, 400, 450, 500, 600], 1):
    add("M-ISB-%02d" % i, M, S, "Joist ISMB %d" % s, "kg", 1, 118, "IS 808 / IS 2062 E250", "Structural sections")
for i, s in enumerate([75, 100, 125, 150, 175, 200, 250, 300], 1):
    add("M-ISC-%02d" % i, M, S, "Channel ISMC %d" % s, "kg", 1, 118, "IS 808", "Structural sections")
for i, s in enumerate(["25x25x3", "40x40x5", "50x50x6", "65x65x6", "75x75x8", "90x90x8", "100x100x10", "150x150x12"], 1):
    add("M-ISA-%02d" % i, M, S, "Equal angle ISA %s" % s, "kg", 1, 116, "IS 808", "Structural sections")
for i, s in enumerate(["25x5", "40x6", "50x6", "75x8", "100x10"], 1):
    add("M-FLT-%02d" % i, M, S, "Flat bar %s" % s, "kg", 1, 116, "IS 2062", "Structural sections")
for i, s in enumerate([5, 6, 8, 10, 12, 16, 20, 25, 32, 40], 1):
    add("M-PLT-%02d" % i, M, S, "MS plate %d mm (E250)" % s, "kg", 1, 120, "IS 2062 E250", "Plates")
for i, s in enumerate([10, 12, 16, 20, 25, 32, 40], 1):
    add("M-PLH-%02d" % i, M, S, "High-strength plate %d mm for penstock" % s, "kg", 1, 165, "ASTM A537 Cl.1 / S355", "Plates")
add("M-PLT-20", M, S, "Chequered plate 6 mm", "kg", 1, 125, "IS 3502", "Plates")
for i, s in enumerate(["20x20x2", "40x40x2.5", "50x50x3", "72x72x3.2", "100x100x4"], 1):
    add("M-SHS-%02d" % i, M, S, "Square hollow section %s" % s, "kg", 1, 125, "IS 4923", "Hollow sections")
for i, s in enumerate(["15 mm (1/2\")", "20 mm", "25 mm", "32 mm", "40 mm", "50 mm", "65 mm", "80 mm", "100 mm", "150 mm"], 1):
    add("M-GIP-%02d" % i, M, S, "GI pipe medium class %s" % s, "m", [1.2, 1.6, 2.4, 3.1, 3.6, 5, 6.4, 7.4, 10.6, 18][i - 1],
        [320, 400, 560, 720, 850, 1150, 1500, 1750, 2500, 4500][i - 1], "IS 1239", "Pipes (steel)")
for i, s in enumerate([150, 200, 300, 400, 500, 600, 800, 1000, 1200], 1):
    add("M-MSP-%02d" % i, M, S, "MS pipe ERW/spiral %d mm dia" % s, "m", 0, None, "IS 3589", "Pipes (steel)")
add("M-STL-01", M, S, "Penstock pipe fabricated & delivered", "t", 1000, 260000, "Shop fabrication incl. rolling, welding, NDT", "Hydro-mechanical")
add("M-STL-02", M, S, "Steel for gates & stoplogs (fabricated)", "t", 1000, 320000, "", "Hydro-mechanical")
add("M-STL-03", M, S, "Trash rack (fabricated)", "t", 1000, 280000, "", "Hydro-mechanical")
add("M-STL-04", M, S, "Embedded parts / guides", "t", 1000, 300000, "", "Hydro-mechanical")
add("M-STL-05", M, S, "Steel sheet pile", "t", 1000, 170000, "", "Structural sections")
add("M-STL-06", M, S, "Rail 60 lb", "m", 30, 3500, "", "Structural sections")
add("M-FIX-01", M, S, "Nails assorted", "kg", 1, 150, "", "Fixings")
add("M-FIX-02", M, S, "Bolts & nuts (MS, assorted)", "kg", 1, 220, "", "Fixings")
add("M-FIX-03", M, S, "HSFG bolt M20 with nut & washer", "no", 0.3, 120, "IS 3757", "Fixings")
add("M-FIX-04", M, S, "Anchor / foundation bolt M20-M24", "no", 2, 450, "", "Fixings")
add("M-FIX-05", M, S, "Chemical anchor with stud M16", "no", 0.3, 650, "", "Fixings")
add("M-FIX-06", M, S, "Welding electrode E6013 / E7018", "kg", 1, 320, "", "Fixings")
add("M-FIX-07", M, S, "Oxygen cylinder (refill)", "no", 70, 1200, "", "Fixings")
add("M-FIX-08", M, S, "Acetylene / DA cylinder (refill)", "no", 60, 4500, "", "Fixings")
add("M-FIX-09", M, S, "Steel wire rope 12 mm", "m", 0.6, 180, "", "Fixings")
add("M-FIX-10", M, S, "Steel wire rope 20 mm", "m", 1.6, 420, "", "Fixings")
add("M-FIX-11", M, S, "Wire rope clamps / thimbles", "no", 0.2, 80, "", "Fixings")
add("M-FIX-12", M, S, "Turnbuckle", "no", 0.5, 250, "", "Fixings")
# gabion, fencing, roofing
G = "Gabions, fencing & roofing"
add("M-GAB-01", M, G, "GI gabion wire 4 mm (mesh wire)", "kg", 1, 150, "NS 546, heavily galvanised", "Gabion")
add("M-GAB-02", M, G, "GI wire 3.15 mm", "kg", 1, 152, "", "Gabion")
add("M-GAB-03", M, G, "GI wire 2.7 mm", "kg", 1, 155, "", "Gabion")
add("M-GAB-04", M, G, "GI binding / lacing wire 2.2 mm", "kg", 1, 160, "", "Gabion")
for i, s in enumerate(["2x1x1 m", "1.5x1x1 m", "3x1x1 m", "2x1x0.5 m", "1x1x1 m"], 1):
    add("M-GBX-%02d" % i, M, G, "Machine-woven gabion box %s" % s, "no", 0, None, "Mesh 100x120, 2.7 mm", "Gabion")
add("M-GBX-10", M, G, "Gabion mattress 3x2x0.3 m", "no", 0, None, "", "Gabion")
add("M-GBX-11", M, G, "PVC-coated gabion box 2x1x1 m", "no", 0, None, "", "Gabion")
add("M-FNC-01", M, G, "Barbed wire (GI) 12x14 SWG", "kg", 1, 170, "IS 278", "Fencing")
add("M-FNC-02", M, G, "Chain-link mesh 50x50, 10 SWG", "m2", 2.2, 380, "IS 2721", "Fencing")
add("M-FNC-03", M, G, "Welded wire fencing panel", "m2", 3, 450, "", "Fencing")
add("M-FNC-04", M, G, "Angle iron fence post", "no", 10, 1300, "", "Fencing")
add("M-FNC-05", M, G, "RCC fence post (precast)", "no", 45, 900, "", "Fencing")
add("M-ROF-01", M, G, "CGI sheet 26 gauge", "m2", 4.2, 850, "IS 277", "Roofing")
add("M-ROF-02", M, G, "CGI sheet 28 gauge", "m2", 3.5, 700, "", "Roofing")
add("M-ROF-03", M, G, "Colour coated profile sheet 0.47 mm", "m2", 4.5, 1100, "", "Roofing")
add("M-ROF-04", M, G, "Ridge cover (GI)", "m", 2, 450, "", "Roofing")
add("M-ROF-05", M, G, "J-hook / roofing screw with washer", "no", 0.05, 12, "", "Roofing")
add("M-ROF-06", M, G, "Polycarbonate sheet 6 mm", "m2", 1.5, 1800, "", "Roofing")
add("M-ROF-07", M, G, "Z/C purlin cold-formed", "kg", 1, 130, "", "Roofing")

# timber and formwork
W = "Timber & formwork"
for i, (n, r) in enumerate([("Sal (Shorea robusta)", 350000), ("Salla (pine)", 120000), ("Sisau", 250000), ("Asna", 180000),
                            ("Saaj", 160000), ("Katus", 170000), ("Champ", 220000), ("Utis (alder)", 90000)], 1):
    add("M-TIM-%02d" % i, M, W, "Sawn timber — %s" % n, "m3", 800, r, "Seasoned, graded", "Timber")
add("M-TIM-20", M, W, "Timber ballies / props (round)", "m", 5, 180, "", "Timber")
add("M-TIM-21", M, W, "Bamboo (full size)", "no", 8, 250, "", "Timber")
add("M-TIM-22", M, W, "Bamboo stakes / splits", "no", 0.5, 20, "", "Timber")
for i, s in enumerate([4, 6, 9, 12, 18, 25], 1):
    add("M-PLY-%02d" % i, M, W, "Commercial plywood %d mm" % s, "m2", round(s * 0.6, 2), [450, 600, 800, 1000, 1400, 1900][i - 1], "IS 303", "Board")
add("M-PLY-10", M, W, "Film-faced shuttering plywood 12 mm", "m2", 7.5, 1200, "IS 4990", "Formwork")
add("M-PLY-11", M, W, "Film-faced shuttering plywood 18 mm", "m2", 11, 1600, "IS 4990", "Formwork")
add("M-PLY-12", M, W, "Block board 19 mm", "m2", 11, 1500, "", "Board")
add("M-PLY-13", M, W, "MDF board 18 mm", "m2", 13, 1300, "", "Board")
add("M-FRM-01", M, W, "Steel shuttering plate 600x900", "no", 22, 3500, "", "Formwork")
add("M-FRM-02", M, W, "Adjustable steel prop 2-3.5 m", "no", 14, 2800, "", "Formwork")
add("M-FRM-03", M, W, "Scaffolding tube 48.3 mm", "m", 4.4, 600, "BS EN 39", "Formwork")
add("M-FRM-04", M, W, "Scaffold coupler / clamp", "no", 1.2, 350, "", "Formwork")
add("M-FRM-05", M, W, "Cup-lock vertical 3 m", "no", 15, 3200, "", "Formwork")
add("M-FRM-06", M, W, "Form tie rod with wing nut", "no", 1.5, 250, "", "Formwork")
add("M-FRM-07", M, W, "Shutter release agent (oil)", "l", 0.9, 250, "", "Formwork")
add("M-FRM-08", M, W, "Slip-form / gantry hire (lining)", "month", 0, None, "Tunnel lining gantry", "Formwork")

# road materials
R = "Road & bituminous"
add("M-BIT-01", M, R, "Bitumen 60/70 penetration grade", "kg", 1, 105, "IS 73 / NS", "Bitumen")
add("M-BIT-02", M, R, "Bitumen 80/100 penetration grade", "kg", 1, 103, "", "Bitumen")
add("M-BIT-03", M, R, "Bitumen VG-30", "kg", 1, 105, "IS 73", "Bitumen")
add("M-BIT-04", M, R, "Bitumen VG-10", "kg", 1, 103, "IS 73", "Bitumen")
add("M-BIT-05", M, R, "Cationic emulsion RS-1", "kg", 1, 95, "IS 8887", "Bitumen")
add("M-BIT-06", M, R, "Cationic emulsion SS-1 (tack/prime)", "kg", 1, 92, "IS 8887", "Bitumen")
add("M-BIT-07", M, R, "Cutback bitumen MC-30 (prime)", "kg", 1, 115, "IS 217", "Bitumen")
add("M-BIT-08", M, R, "Modified bitumen PMB-40", "kg", 1, 130, "IS 15462", "Bitumen")
add("M-BIT-09", M, R, "Kerosene (for cutback)", "l", 0.8, 165, "", "Bitumen")
add("M-BIT-10", M, R, "Firewood (bitumen heating)", "kg", 1, 18, "", "Bitumen")
add("M-RDF-01", M, R, "Road marking paint (thermoplastic)", "kg", 1, 180, "BS 3262", "Road furniture")
add("M-RDF-02", M, R, "Road marking paint (cold, solvent)", "l", 1.4, 650, "", "Road furniture")
add("M-RDF-03", M, R, "Glass beads (drop-on)", "kg", 1, 150, "", "Road furniture")
add("M-RDF-04", M, R, "Road stud / cat's eye", "no", 0.3, 450, "", "Road furniture")
add("M-RDF-05", M, R, "W-beam crash barrier (metal beam) incl. post", "m", 35, 6500, "AASHTO M180", "Road furniture")
add("M-RDF-06", M, R, "Road sign board (retro-reflective) 900 mm", "no", 15, 9000, "", "Road furniture")
add("M-RDF-07", M, R, "Delineator post", "no", 20, 1500, "", "Road furniture")
add("M-RDF-08", M, R, "Kilometre post (RCC)", "no", 80, 3000, "", "Road furniture")
add("M-RDF-09", M, R, "Hectometre stone", "no", 25, 700, "", "Road furniture")

# admixtures and chemicals
X = "Admixtures & chemicals"
add("M-ADM-01", M, X, "Plasticiser (lignosulphonate)", "l", 1.2, 110, "IS 9103", "Admixture")
add("M-ADM-02", M, X, "Superplasticiser (PCE)", "kg", 1, 230, "IS 9103 / EN 934-2", "Admixture")
add("M-ADM-03", M, X, "Retarder", "l", 1.1, 160, "", "Admixture")
add("M-ADM-04", M, X, "Alkali-free shotcrete accelerator", "kg", 1, 140, "EN 934-5", "Admixture")
add("M-ADM-05", M, X, "Integral waterproofing compound", "kg", 1, 120, "IS 2645", "Admixture")
add("M-ADM-06", M, X, "Air-entraining agent", "l", 1, 200, "", "Admixture")
add("M-ADM-07", M, X, "Curing compound (wax/resin)", "l", 1, 180, "ASTM C309", "Admixture")
add("M-ADM-08", M, X, "Bonding agent (SBR latex)", "l", 1, 450, "", "Admixture")
add("M-ADM-09", M, X, "Non-shrink cementitious grout", "kg", 1, 70, "ASTM C1107", "Grout")
add("M-ADM-10", M, X, "Epoxy grout / mortar", "kg", 1, 900, "", "Grout")
add("M-ADM-11", M, X, "Polyurethane injection resin", "kg", 1, 1400, "", "Grout")
add("M-ADM-12", M, X, "Bentonite (drilling / grout)", "kg", 1, 35, "API 13A", "Grout")
add("M-ADM-13", M, X, "Sodium silicate", "kg", 1, 60, "", "Grout")
add("M-ADM-14", M, X, "Anti-washout admixture", "kg", 1, 500, "", "Admixture")
add("M-ADM-15", M, X, "Crystalline waterproofing slurry", "kg", 1, 600, "", "Waterproofing")
add("M-ADM-16", M, X, "Epoxy bonding agent", "kg", 1, 1100, "", "Admixture")

# waterproofing, joints, geosynthetics
J = "Joints, waterproofing & geosynthetics"
add("M-JNT-01", M, J, "PVC waterstop 150 mm (centre bulb)", "m", 1.2, 450, "", "Joints")
add("M-JNT-02", M, J, "PVC waterstop 230 mm", "m", 1.8, 650, "", "Joints")
add("M-JNT-03", M, J, "Hydrophilic swelling strip 20x10", "m", 0.3, 550, "", "Joints")
add("M-JNT-04", M, J, "Bitumen-impregnated joint filler board 20 mm", "m2", 5, 900, "IS 1838", "Joints")
add("M-JNT-05", M, J, "Polysulphide sealant", "l", 1.6, 1500, "IS 12118", "Joints")
add("M-JNT-06", M, J, "Elastomeric bearing pad", "dm3", 1.5, 1600, "IRC 83-II", "Bearings")
add("M-JNT-07", M, J, "Expansion joint (strip seal) for bridge", "m", 60, 35000, "", "Bearings")
add("M-WPF-01", M, J, "Bitumen felt (APP membrane) 3 mm", "m2", 3.5, 550, "", "Waterproofing")
add("M-WPF-02", M, J, "HDPE geomembrane 1.5 mm", "m2", 1.4, 450, "GRI GM13", "Waterproofing")
add("M-WPF-03", M, J, "PVC tunnel waterproofing membrane 2 mm", "m2", 2.6, 900, "", "Waterproofing")
add("M-WPF-04", M, J, "Bitumen primer / paint", "l", 1, 250, "IS 3384", "Waterproofing")
add("M-GEO-01", M, J, "Non-woven geotextile 200 gsm", "m2", 0.2, 90, "", "Geosynthetics")
add("M-GEO-02", M, J, "Non-woven geotextile 300 gsm", "m2", 0.3, 120, "", "Geosynthetics")
add("M-GEO-03", M, J, "Non-woven geotextile 400 gsm", "m2", 0.4, 150, "", "Geosynthetics")
add("M-GEO-04", M, J, "Woven geotextile (PP)", "m2", 0.25, 110, "", "Geosynthetics")
add("M-GEO-05", M, J, "Biaxial geogrid 30 kN/m", "m2", 0.3, 220, "", "Geosynthetics")
add("M-GEO-06", M, J, "Uniaxial geogrid 80 kN/m", "m2", 0.5, 380, "", "Geosynthetics")
add("M-GEO-07", M, J, "Geocell 100 mm", "m2", 1.5, 650, "", "Geosynthetics")
add("M-GEO-08", M, J, "Geocomposite drain", "m2", 0.8, 550, "", "Geosynthetics")
add("M-GEO-09", M, J, "Jute netting (geo-jute)", "m2", 0.5, 70, "", "Bio-engineering")
add("M-GEO-10", M, J, "Coir netting", "m2", 0.7, 110, "", "Bio-engineering")

# pipes (non-steel)
P = "Pipes & drainage"
for i, d in enumerate([63, 75, 90, 110, 160, 200, 250, 315, 400, 500, 630], 1):
    add("M-HDP-%02d" % i, M, P, "HDPE pipe PE100 PN6 %d mm" % d, "m", round(d * d * 0.00006, 2), None, "NS 40 / IS 4984", "HDPE")
for i, d in enumerate([63, 90, 110, 160, 200, 250, 315], 1):
    add("M-HDQ-%02d" % i, M, P, "HDPE pipe PE100 PN10 %d mm" % d, "m", round(d * d * 0.0001, 2), None, "", "HDPE")
for i, d in enumerate([50, 75, 110, 160], 1):
    add("M-PVC-%02d" % i, M, P, "uPVC pipe 6 kgf %d mm" % d, "m", round(d * 0.012, 2), None, "IS 4985", "uPVC")
for i, d in enumerate([300, 450, 600, 750, 900, 1000, 1200], 1):
    add("M-HUM-%02d" % i, M, P, "RCC hume pipe NP3 %d mm" % d, "m", [170, 300, 420, 600, 800, 900, 1250][i - 1],
        [3500, 5500, 7800, 11000, 15000, 17500, 24000][i - 1], "IS 458", "RCC pipe")
for i, d in enumerate([100, 150, 200, 300, 400, 600], 1):
    add("M-DIP-%02d" % i, M, P, "Ductile iron pipe K9 %d mm" % d, "m", [20, 30, 40, 65, 95, 160][i - 1], None, "IS 8329", "DI")
add("M-DRN-01", M, P, "Perforated PVC drain pipe 100 mm", "m", 1, 350, "", "Drainage")
add("M-DRN-02", M, P, "Perforated HDPE drain pipe 150 mm", "m", 1.5, 550, "", "Drainage")
add("M-DRN-03", M, P, "Weep hole pipe PVC 75 mm", "m", 0.7, 180, "", "Drainage")
add("M-DRN-04", M, P, "Corrugated steel pipe culvert 900 mm", "m", 90, 20000, "AASHTO M36", "Drainage")
add("M-DRN-05", M, P, "Manhole cover & frame (CI/DI) heavy duty", "no", 120, 18000, "", "Drainage")
add("M-DRN-06", M, P, "Pipe fittings allowance (bends, tees)", "LS", 0, None, "", "Drainage")

# tunnelling & underground
U = "Tunnelling & rock support"
add("M-EXP-01", M, U, "Emulsion explosive cartridge 25 mm", "kg", 1, 450, "Licensed; NA/ Home Ministry permit", "Explosives")
add("M-EXP-02", M, U, "Emulsion explosive cartridge 32 mm", "kg", 1, 440, "", "Explosives")
add("M-EXP-03", M, U, "Emulsion explosive cartridge 40 mm", "kg", 1, 430, "", "Explosives")
add("M-EXP-04", M, U, "Water gel / slurry explosive", "kg", 1, 460, "", "Explosives")
add("M-EXP-05", M, U, "ANFO", "kg", 1, 180, "", "Explosives")
add("M-EXP-06", M, U, "Electric detonator (delay)", "no", 0.02, 120, "", "Explosives")
add("M-EXP-07", M, U, "Non-electric detonator LP/MS (Nonel) 4.8 m", "no", 0.05, 260, "", "Explosives")
add("M-EXP-08", M, U, "Detonating cord 10 g/m", "m", 0.02, 45, "", "Explosives")
add("M-EXP-09", M, U, "Safety fuse", "m", 0.01, 25, "", "Explosives")
add("M-EXP-10", M, U, "Stemming cartridge (clay)", "no", 0.3, 8, "", "Explosives")
add("M-EXP-11", M, U, "Smooth-blasting (perimeter) explosive 17 mm", "kg", 1, 700, "", "Explosives")
for i, (n, r) in enumerate([("25 mm fully grouted rock bolt 3 m", 2600), ("25 mm fully grouted rock bolt 4 m", 3400),
                            ("25 mm fully grouted rock bolt 6 m", 5000), ("32 mm fully grouted rock bolt 6 m", 7000),
                            ("Swellex / friction bolt 2.4 m", 3800), ("Self-drilling anchor R32 per m", 2400),
                            ("Split set SS39 1.8 m", 1500), ("Cable anchor 15.2 mm strand per m", 900)], 1):
    add("M-RBT-%02d" % i, M, U, n, "no" if "per m" not in n else "m", 0, r, "", "Rock support")
add("M-RBT-20", M, U, "Bearing plate 150x150x8 with nut", "no", 1.5, 350, "", "Rock support")
add("M-RBT-21", M, U, "Resin cartridge (fast/slow)", "no", 0.5, 180, "", "Rock support")
add("M-RBT-22", M, U, "Cement grout cartridge", "no", 0.5, 70, "", "Rock support")
add("M-RBT-23", M, U, "Lattice girder 3-bar (fabricated)", "kg", 1, 160, "", "Rock support")
add("M-RBT-24", M, U, "Steel rib ISMB 150 (fabricated, bent)", "kg", 1, 150, "", "Rock support")
add("M-RBT-25", M, U, "Tie rods & collar pipes for ribs", "kg", 1, 140, "", "Rock support")
add("M-RBT-26", M, U, "Forepoling / spiling bar 25 mm 4 m", "no", 16, 1800, "", "Rock support")
add("M-RBT-27", M, U, "Pipe umbrella / pipe roof 114 mm per m", "m", 17, 3500, "", "Rock support")
add("M-RBT-28", M, U, "Wire mesh 150x150x6 (tunnel)", "m2", 3, 350, "", "Rock support")
add("M-DRL-01", M, U, "Button bit 45 mm", "no", 0.8, 6500, "", "Drilling consumables")
add("M-DRL-02", M, U, "Button bit 51 mm", "no", 1, 7500, "", "Drilling consumables")
add("M-DRL-03", M, U, "Reamer bit 102 mm", "no", 4, 25000, "", "Drilling consumables")
add("M-DRL-04", M, U, "Drill rod / MF rod 4.3 m", "no", 25, 38000, "", "Drilling consumables")
add("M-DRL-05", M, U, "Shank adaptor", "no", 5, 22000, "", "Drilling consumables")
add("M-DRL-06", M, U, "Coupling sleeve", "no", 1.5, 5000, "", "Drilling consumables")
add("M-DRL-07", M, U, "Drill steel (hand-held) 1.6 m integral", "no", 6, 9000, "", "Drilling consumables")
add("M-DRL-08", M, U, "Core bit NX (diamond)", "no", 1, 45000, "", "Drilling consumables")
add("M-DRL-09", M, U, "Core box", "no", 6, 1200, "", "Drilling consumables")
add("M-DRL-10", M, U, "Drill water hose / air hose 25 mm", "m", 0.6, 450, "", "Drilling consumables")
add("M-VNT-01", M, U, "Ventilation duct 800 mm", "m", 1.5, 1300, "Flexible PVC", "Ventilation")
add("M-VNT-02", M, U, "Ventilation duct 1000 mm", "m", 1.8, 1600, "", "Ventilation")
add("M-VNT-03", M, U, "Ventilation duct 1200 mm", "m", 2.2, 2000, "", "Ventilation")
add("M-VNT-04", M, U, "Ventilation duct 1400 mm", "m", 2.6, 2500, "", "Ventilation")

# electrical materials
EL = "Electrical"
for i, s in enumerate(["2.5", "4", "6", "10", "16", "25", "35", "50", "70", "95", "120", "185", "240"], 1):
    add("M-CBL-%02d" % i, M, EL, "Cu armoured cable 4 core %s mm²" % s, "m", 0, None, "IS 1554", "Cable")
for i, s in enumerate(["1.5", "2.5", "4", "6"], 1):
    add("M-WIR-%02d" % i, M, EL, "PVC insulated Cu wire %s mm²" % s, "m", 0.03, [30, 45, 70, 100][i - 1], "IS 694", "Wiring")
add("M-ELC-01", M, EL, "PVC conduit 20/25 mm", "m", 0.2, 60, "", "Wiring")
add("M-ELC-02", M, EL, "GI earthing plate 600x600x6 with pit", "no", 20, 9000, "IS 3043", "Earthing")
add("M-ELC-03", M, EL, "Earth rod copper-bonded 3 m", "no", 5, 4500, "", "Earthing")
add("M-ELC-04", M, EL, "LED flood light 100 W", "no", 3, 5500, "", "Lighting")
add("M-ELC-05", M, EL, "Tunnel light LED 40 W IP65", "no", 2, 3500, "", "Lighting")
add("M-ELC-06", M, EL, "MCB / distribution board (8-way)", "no", 5, 6500, "", "Switchgear")
add("M-ELC-07", M, EL, "Street light pole 8 m with fitting", "no", 180, 45000, "", "Lighting")
add("M-ELC-08", M, EL, "Electricity (grid)", "kWh", 0, 13, "NEA commercial tariff", "Energy")

# finishing, sanitary, doors/windows
FN = "Finishing & building services"
for i, (n, u, r) in enumerate([("Red oxide zinc chromate primer", "l", 450), ("Synthetic enamel paint", "l", 600),
                               ("Acrylic exterior emulsion", "l", 650), ("Interior emulsion", "l", 450),
                               ("Oil-bound distemper", "kg", 180), ("Cement primer", "l", 280), ("Wall putty", "kg", 40),
                               ("Epoxy paint (2-pack)", "l", 1500), ("Zinc-rich epoxy primer", "l", 1800),
                               ("Coal-tar epoxy (penstock inside)", "l", 1400), ("Bituminous black paint", "l", 280),
                               ("Wood primer", "l", 400), ("Varnish / polish", "l", 650), ("Thinner", "l", 300),
                               ("Snowcem / cement paint", "kg", 90)], 1):
    add("M-PNT-%02d" % i, M, FN, n, u, 1.2, r, "", "Paint")
for i, (n, r) in enumerate([("Ceramic floor tile 300x300", 800), ("Ceramic wall tile 300x450", 850),
                            ("Vitrified tile 600x600", 1400), ("Anti-skid tile 300x300", 950), ("Granite slab 18 mm", 3500),
                            ("Marble slab 18 mm", 3000), ("Terrazzo tile", 900)], 1):
    add("M-TIL-%02d" % i, M, FN, n, "m2", 22, r, "", "Tiles & stone")
add("M-TIL-20", M, FN, "Tile adhesive (polymer)", "kg", 1, 35, "", "Tiles & stone")
add("M-TIL-21", M, FN, "Tile grout / joint filler", "kg", 1, 90, "", "Tiles & stone")
for i, (n, u, r) in enumerate([("Float glass 5 mm", "m2", 1100), ("Toughened glass 10 mm", "m2", 3800),
                               ("Aluminium section (anodised)", "kg", 700), ("UPVC window (sliding)", "m2", 9000),
                               ("Flush door shutter 35 mm", "m2", 4500), ("Panel door shutter (sal)", "m2", 12000),
                               ("Steel door (fire-rated)", "m2", 18000), ("Rolling shutter (MS)", "m2", 5500),
                               ("Door frame sal 100x75", "m", 1500), ("Door hardware set", "set", 3500),
                               ("MS grill work", "kg", 180)], 1):
    add("M-DWN-%02d" % i, M, FN, n, u, 1, r, "", "Doors & windows")
for i, (n, u, r) in enumerate([("Water closet (Asian) with cistern", "set", 9000), ("Water closet (European) with cistern", "set", 16000),
                               ("Wash basin with pillar tap", "set", 7500), ("Urinal", "set", 6500), ("Kitchen sink SS", "set", 7000),
                               ("PPR pipe 20 mm", "m", 180), ("PPR pipe 25 mm", "m", 260), ("PVC water tank 1000 l", "no", 12000),
                               ("Septic tank (precast) 10 users", "no", 60000), ("Gate valve 50 mm", "no", 3500),
                               ("Floor trap", "no", 600), ("Bib cock", "no", 700)], 1):
    add("M-SAN-%02d" % i, M, FN, n, u, 1, r, "", "Sanitary & plumbing")

# fuel, lubricants, consumables, water
FU = "Fuel, lubricants & consumables"
add("M-FUL-01", M, FU, "Diesel (HSD)", "l", 0.84, 160, "NOC retail price", "Fuel")
add("M-FUL-02", M, FU, "Petrol", "l", 0.74, 170, "NOC retail price", "Fuel")
add("M-FUL-03", M, FU, "Engine oil 15W-40", "l", 0.9, 600, "", "Lubricants")
add("M-FUL-04", M, FU, "Hydraulic oil 68", "l", 0.9, 520, "", "Lubricants")
add("M-FUL-05", M, FU, "Gear oil 90", "l", 0.9, 550, "", "Lubricants")
add("M-FUL-06", M, FU, "Grease (MP3)", "kg", 1, 550, "", "Lubricants")
add("M-FUL-07", M, FU, "Rock-drill oil", "l", 0.9, 480, "", "Lubricants")
add("M-FUL-08", M, FU, "LPG cylinder 14.2 kg", "no", 30, 1910, "", "Fuel")
add("M-CON-01", M, FU, "Water for construction", "kl", 0, 150, "Tanker or pumped at site (no cartage)", "Water")
add("M-CON-02", M, FU, "Gunny / polypropylene bags", "no", 0.1, 20, "", "Consumables")
add("M-CON-03", M, FU, "Polythene sheet 250 micron", "m2", 0.25, 45, "", "Consumables")
add("M-CON-04", M, FU, "Hessian cloth (curing)", "m2", 0.3, 60, "", "Consumables")
add("M-CON-05", M, FU, "Manila / nylon rope", "m", 0.1, 35, "", "Consumables")
add("M-CON-06", M, FU, "PPE set (helmet, boots, vest, gloves)", "set", 3, 4500, "", "Safety")
add("M-CON-07", M, FU, "Safety net", "m2", 0.3, 150, "", "Safety")
add("M-CON-08", M, FU, "Warning tape / barricade", "m", 0.02, 10, "", "Safety")
add("M-CON-09", M, FU, "Traffic cone 750 mm", "no", 3, 1200, "", "Safety")
add("M-CON-10", M, FU, "Cutting disc 14\"", "no", 1, 450, "", "Consumables")
add("M-CON-11", M, FU, "Grinding disc 4\"", "no", 0.2, 90, "", "Consumables")
add("M-CON-12", M, FU, "Marking paint / spray", "no", 0.4, 350, "", "Consumables")

# bio-engineering
BI = "Bio-engineering & landscape"
add("M-BIO-01", M, BI, "Grass slips (Amliso / Napier)", "no", 0.05, 3, "", "Vegetation")
add("M-BIO-02", M, BI, "Grass seed", "kg", 1, 900, "", "Vegetation")
add("M-BIO-03", M, BI, "Hardwood cuttings", "no", 0.2, 8, "", "Vegetation")
add("M-BIO-04", M, BI, "Seedlings (polybag)", "no", 0.5, 30, "", "Vegetation")
add("M-BIO-05", M, BI, "Bamboo rhizome", "no", 2, 80, "", "Vegetation")
add("M-BIO-06", M, BI, "Compost / farmyard manure", "m3", 600, 2500, "", "Vegetation")
add("M-BIO-07", M, BI, "Brush layering / fascine material", "m", 2, 60, "", "Vegetation")

# ════════════════════════════ LABOUR ════════════════════════════
LB = [
    ("L-001", "General", "Unskilled labour (mazdoor)", 1100),
    ("L-002", "General", "Semi-skilled labour", 1300),
    ("L-003", "General", "Skilled labour (general)", 1500),
    ("L-004", "General", "Helper / khalasi", 1150),
    ("L-005", "General", "Porter (load carrier)", 1200),
    ("L-006", "General", "Watchman / chowkidar", 1100),
    ("L-010", "Masonry & concrete", "Mason (1st class)", 1600),
    ("L-011", "Masonry & concrete", "Mason (2nd class)", 1450),
    ("L-012", "Masonry & concrete", "Stone dresser / cutter", 1550),
    ("L-013", "Masonry & concrete", "Plasterer", 1500),
    ("L-014", "Masonry & concrete", "Tile / marble fixer", 1600),
    ("L-015", "Masonry & concrete", "Concrete finisher", 1450),
    ("L-016", "Masonry & concrete", "Gabion weaver / filler", 1350),
    ("L-020", "Steel & formwork", "Carpenter (formwork)", 1550),
    ("L-021", "Steel & formwork", "Carpenter (joinery)", 1650),
    ("L-022", "Steel & formwork", "Bar bender / steel fixer", 1550),
    ("L-023", "Steel & formwork", "Welder (structural)", 1800),
    ("L-024", "Steel & formwork", "Welder (coded, pressure pipe)", 2800),
    ("L-025", "Steel & formwork", "Fitter / fabricator", 1700),
    ("L-026", "Steel & formwork", "Rigger", 1600),
    ("L-027", "Steel & formwork", "Blacksmith", 1550),
    ("L-028", "Steel & formwork", "Scaffolder", 1450),
    ("L-030", "Services & finishes", "Painter", 1450),
    ("L-031", "Services & finishes", "Plumber", 1600),
    ("L-032", "Services & finishes", "Electrician", 1700),
    ("L-033", "Services & finishes", "Glazier / aluminium fabricator", 1600),
    ("L-034", "Services & finishes", "Waterproofing applicator", 1500),
    ("L-040", "Plant & transport", "Heavy equipment operator", 2000),
    ("L-041", "Plant & transport", "Light equipment operator", 1600),
    ("L-042", "Plant & transport", "Heavy vehicle driver", 1800),
    ("L-043", "Plant & transport", "Light vehicle driver", 1500),
    ("L-044", "Plant & transport", "Mechanic (heavy)", 1900),
    ("L-045", "Plant & transport", "Auto electrician", 1800),
    ("L-046", "Plant & transport", "Crane operator (licensed)", 2300),
    ("L-047", "Plant & transport", "Plant operator (batching/crusher)", 1800),
    ("L-050", "Tunnel & drilling", "Driller (hand-held)", 1800),
    ("L-051", "Tunnel & drilling", "Drill jumbo operator", 2800),
    ("L-052", "Tunnel & drilling", "Blaster / shot-firer (licensed)", 2500),
    ("L-053", "Tunnel & drilling", "Shotcrete nozzleman", 2400),
    ("L-054", "Tunnel & drilling", "Miner / tunnel worker", 1700),
    ("L-055", "Tunnel & drilling", "Mucking (LHD) operator", 2200),
    ("L-056", "Tunnel & drilling", "Grouting operator", 1900),
    ("L-057", "Tunnel & drilling", "Core drilling operator", 2000),
    ("L-058", "Tunnel & drilling", "Scaler", 1700),
    ("L-060", "Supervision & technical", "Foreman / supervisor", 2200),
    ("L-061", "Supervision & technical", "Site engineer (per day)", 4000),
    ("L-062", "Supervision & technical", "Surveyor", 2500),
    ("L-063", "Supervision & technical", "Survey helper / chainman", 1200),
    ("L-064", "Supervision & technical", "Lab technician", 2000),
    ("L-065", "Supervision & technical", "Lab assistant", 1400),
    ("L-066", "Supervision & technical", "Safety officer (per day)", 3000),
    ("L-067", "Supervision & technical", "Store keeper", 1600),
    ("L-070", "Bio-engineering", "Gardener / bio-engineering worker", 1150),
    ("L-071", "Bio-engineering", "Diver (underwater works)", 6000),
]
for code, cat, name, rate in LB:
    add(code, L, "Labour — " + cat, name, "day", 0, rate, "8-hour day; DRC wage rate", cat)

# ════════════════════════════ EQUIPMENT (hire rate per hour incl. operator & fuel unless noted) ════════════════════════════
EQ = "Equipment — "
eq = [
    # earthmoving
    ("E-EXC-01", "Earthmoving", "Mini excavator 0.1-0.2 m³", 2200), ("E-EXC-02", "Earthmoving", "Excavator 0.3 m³ (8 t)", 3000),
    ("E-EXC-03", "Earthmoving", "Excavator 0.6 m³ (14 t)", 4200), ("E-EXC-04", "Earthmoving", "Excavator 0.9 m³ (20 t)", 5200),
    ("E-EXC-05", "Earthmoving", "Excavator 1.2 m³ (22-25 t)", 6000), ("E-EXC-06", "Earthmoving", "Excavator 1.6 m³ (30 t)", 7500),
    ("E-EXC-07", "Earthmoving", "Excavator 2.0 m³ (35-40 t)", 9500), ("E-EXC-08", "Earthmoving", "Long-reach excavator 18 m", 7500),
    ("E-EXC-09", "Earthmoving", "Excavator with hydraulic rock breaker", 6500), ("E-EXC-10", "Earthmoving", "Excavator with vibro-ripper", 7000),
    ("E-EXC-11", "Earthmoving", "Amphibious excavator", 9000), ("E-BHL-01", "Earthmoving", "Backhoe loader (JCB 3DX)", 3200),
    ("E-DOZ-01", "Earthmoving", "Bulldozer D4 (80 hp)", 5000), ("E-DOZ-02", "Earthmoving", "Bulldozer D6 (150 hp)", 7500),
    ("E-DOZ-03", "Earthmoving", "Bulldozer D7 (240 hp)", 9500), ("E-DOZ-04", "Earthmoving", "Bulldozer D8 (310 hp) with ripper", 12500),
    ("E-DOZ-05", "Earthmoving", "Bulldozer D9 (410 hp) with ripper", 16000),
    ("E-LDR-01", "Earthmoving", "Skid-steer loader", 2500), ("E-LDR-02", "Earthmoving", "Wheel loader 1.5 m³", 4000),
    ("E-LDR-03", "Earthmoving", "Wheel loader 2.0 m³", 4800), ("E-LDR-04", "Earthmoving", "Wheel loader 3.0 m³", 6200),
    ("E-GRD-01", "Earthmoving", "Motor grader 120 hp", 6000), ("E-GRD-02", "Earthmoving", "Motor grader 140-160 hp", 7000),
    ("E-SCR-01", "Earthmoving", "Tractor with scraper / leveller", 2800),
    # compaction
    ("E-RLR-01", "Compaction", "Plate compactor 100 kg", 700), ("E-RLR-02", "Compaction", "Rammer (jumping jack)", 700),
    ("E-RLR-03", "Compaction", "Pedestrian vibratory roller 1 t", 1200), ("E-RLR-04", "Compaction", "Tandem vibratory roller 3 t", 2500),
    ("E-RLR-05", "Compaction", "Vibratory roller 8-10 t (single drum)", 4500), ("E-RLR-06", "Compaction", "Vibratory roller 12-14 t", 5500),
    ("E-RLR-07", "Compaction", "Padfoot / sheepsfoot roller 10 t", 5000), ("E-RLR-08", "Compaction", "Static tandem roller 8-10 t", 4000),
    ("E-RLR-09", "Compaction", "Pneumatic tyred roller 12-20 t", 5000), ("E-RLR-10", "Compaction", "Three-wheel static roller 8-10 t", 3500),
    # hauling
    ("E-TRK-01", "Hauling", "Tipper 5 m³ (mini)", 2200), ("E-TRK-02", "Hauling", "Tipper 10 m³ (10-wheel)", 3500),
    ("E-TRK-03", "Hauling", "Tipper 16 m³ (12-wheel)", 4500), ("E-TRK-04", "Hauling", "Articulated dump truck 25 t", 8000),
    ("E-TRK-05", "Hauling", "Rigid dump truck 35 t", 10000), ("E-TRK-06", "Hauling", "Truck 10 t flatbed", 3000),
    ("E-TRK-07", "Hauling", "Trailer / low-bed 40 t with prime mover", 9000), ("E-TRK-08", "Hauling", "Tractor with trailer", 1800),
    ("E-TRK-09", "Hauling", "Power tiller with trailer", 1200), ("E-TRK-10", "Hauling", "Water tanker 6,000 l", 2200),
    ("E-TRK-11", "Hauling", "Water tanker / bowser 10,000 l", 2800), ("E-TRK-12", "Hauling", "Fuel bowser 9,000 l", 2800),
    ("E-TRK-13", "Hauling", "Pickup 4x4 (light vehicle)", 1500), ("E-TRK-14", "Hauling", "Jeep / SUV", 1600),
    ("E-TRK-15", "Hauling", "Crew bus / van", 2200), ("E-TRK-16", "Hauling", "Motorcycle", 300), ("E-TRK-17", "Hauling", "Ambulance", 2000),
    ("E-TRK-18", "Hauling", "Dumper 1 t (site)", 900),
    # concrete
    ("E-CON-01", "Concrete", "Concrete mixer 0.2 m³ (7/5 cft)", 700), ("E-CON-02", "Concrete", "Concrete mixer 0.28 m³ (10/7 cft) diesel", 900),
    ("E-CON-03", "Concrete", "Concrete mixer 0.4 m³ (14/10 cft) with hopper", 1200), ("E-CON-04", "Concrete", "Reversible drum mixer 0.5 m³", 1500),
    ("E-CON-05", "Concrete", "Batching plant 30 m³/h", 9000), ("E-CON-06", "Concrete", "Batching plant 60 m³/h", 14000),
    ("E-CON-07", "Concrete", "Batching plant 90-120 m³/h", 20000), ("E-CON-08", "Concrete", "Transit mixer 6 m³", 4000),
    ("E-CON-09", "Concrete", "Transit mixer 8 m³", 4800), ("E-CON-10", "Concrete", "Self-loading concrete mixer 4 m³", 4500),
    ("E-CON-11", "Concrete", "Stationary concrete pump 30-60 m³/h", 6000), ("E-CON-12", "Concrete", "Boom pump 36 m", 12000),
    ("E-CON-13", "Concrete", "Needle vibrator 40/60 mm with engine", 300), ("E-CON-14", "Concrete", "Screed / surface vibrator", 400),
    ("E-CON-15", "Concrete", "Power trowel", 500), ("E-CON-16", "Concrete", "Concrete cutter (joint saw)", 900),
    ("E-CON-17", "Concrete", "Bar bending machine", 500), ("E-CON-18", "Concrete", "Bar cutting machine", 450),
    ("E-CON-19", "Concrete", "Rebar threading machine", 700), ("E-CON-20", "Concrete", "Concrete bucket 1 m³ with crane", 300),
    ("E-CON-21", "Concrete", "Tunnel lining gantry / shutter (hydraulic)", 9000), ("E-CON-22", "Concrete", "Shotcrete machine dry-mix 6 m³/h", 3000),
    ("E-CON-23", "Concrete", "Wet shotcrete robotic sprayer (e.g. Spraymec)", 11000), ("E-CON-24", "Concrete", "Curing water pump", 350),
    # road / asphalt
    ("E-RD-01", "Road & asphalt", "Bitumen boiler 1,000 l (manual)", 600), ("E-RD-02", "Road & asphalt", "Bitumen pressure distributor 6,000 l", 6500),
    ("E-RD-03", "Road & asphalt", "Hand sprayer for bitumen", 400), ("E-RD-04", "Road & asphalt", "Chip spreader (towed)", 2200),
    ("E-RD-05", "Road & asphalt", "Self-propelled chip spreader", 6000), ("E-RD-06", "Road & asphalt", "Hot-mix plant 40-60 tph", 30000),
    ("E-RD-07", "Road & asphalt", "Hot-mix plant 90-120 tph (drum)", 45000), ("E-RD-08", "Road & asphalt", "Asphalt paver finisher (sensor)", 12000),
    ("E-RD-09", "Road & asphalt", "Mechanical broom / power broom", 2000), ("E-RD-10", "Road & asphalt", "Air compressor for road cleaning", 2200),
    ("E-RD-11", "Road & asphalt", "Road marking machine (thermoplastic)", 4000), ("E-RD-12", "Road & asphalt", "Cold milling machine", 20000),
    ("E-RD-13", "Road & asphalt", "Soil stabiliser / recycler", 22000), ("E-RD-14", "Road & asphalt", "Wet mix macadam plant", 12000),
    # drilling, tunnel, compressors
    ("E-CMP-01", "Compressors & drilling", "Air compressor 250 cfm", 2200), ("E-CMP-02", "Compressors & drilling", "Air compressor 400 cfm", 3000),
    ("E-CMP-03", "Compressors & drilling", "Air compressor 600 cfm", 4000), ("E-CMP-04", "Compressors & drilling", "Air compressor 900 cfm (high pressure)", 6000),
    ("E-CMP-05", "Compressors & drilling", "Jack hammer / pneumatic rock drill", 400), ("E-CMP-06", "Compressors & drilling", "Pusher-leg rock drill", 450),
    ("E-CMP-07", "Compressors & drilling", "Pneumatic breaker / chipping hammer", 350), ("E-CMP-08", "Compressors & drilling", "Wagon drill / crawler drill (DTH)", 7000),
    ("E-CMP-09", "Compressors & drilling", "Hydraulic crawler drill (top hammer)", 9000), ("E-CMP-10", "Compressors & drilling", "Core drilling rig (NX/HQ)", 3500),
    ("E-CMP-11", "Compressors & drilling", "Rotary piling rig (bored piles up to 1.2 m)", 25000), ("E-CMP-12", "Compressors & drilling", "Tripod / bailer boring rig", 2500),
    ("E-CMP-13", "Compressors & drilling", "Micropile / anchor drilling rig", 8000),
    ("E-TUN-01", "Tunnel", "Drill jumbo 1-boom", 9000), ("E-TUN-02", "Tunnel", "Drill jumbo 2-boom", 15000),
    ("E-TUN-03", "Tunnel", "Drill jumbo 3-boom", 20000), ("E-TUN-04", "Tunnel", "Rock-bolting rig", 12000),
    ("E-TUN-05", "Tunnel", "LHD / mucking loader 3-4 m³", 9000), ("E-TUN-06", "Tunnel", "Side-tipping loader (tunnel)", 7000),
    ("E-TUN-07", "Tunnel", "Low-profile dump truck 20 t", 8000), ("E-TUN-08", "Tunnel", "Battery / diesel locomotive 8 t", 4500),
    ("E-TUN-09", "Tunnel", "Muck car / Granby car 4 m³", 600), ("E-TUN-10", "Tunnel", "Mechanical scaler", 8000),
    ("E-TUN-11", "Tunnel", "Ventilation fan 55 kW", 1800), ("E-TUN-12", "Tunnel", "Ventilation fan 2x75 kW (axial)", 3500),
    ("E-TUN-13", "Tunnel", "Charging platform / explosive charger", 3500), ("E-TUN-14", "Tunnel", "Raise climber (Alimak)", 9000),
    ("E-TUN-15", "Tunnel", "Raise boring machine", 40000), ("E-TUN-16", "Tunnel", "Grout mixer & pump (colloidal)", 2500),
    ("E-TUN-17", "Tunnel", "Grout pump high pressure", 2200), ("E-TUN-18", "Tunnel", "Dewatering pump for heading", 900),
    ("E-TUN-19", "Tunnel", "Road header", 45000), ("E-TUN-20", "Tunnel", "Scissor-lift / utility vehicle", 3500),
    # lifting
    ("E-CRN-01", "Lifting", "Mobile crane 12-14 t (pick & carry)", 4000), ("E-CRN-02", "Lifting", "Mobile crane 25 t", 6500),
    ("E-CRN-03", "Lifting", "Mobile crane 50 t", 11000), ("E-CRN-04", "Lifting", "Mobile crane 80-100 t", 18000),
    ("E-CRN-05", "Lifting", "Crawler crane 50-80 t", 16000), ("E-CRN-06", "Lifting", "Tower crane 6 t", 7000),
    ("E-CRN-07", "Lifting", "Derrick / gin pole", 1500), ("E-CRN-08", "Lifting", "Winch 5 t (motorised)", 1500),
    ("E-CRN-09", "Lifting", "Chain pulley block 5 t", 150), ("E-CRN-10", "Lifting", "Forklift 3 t", 2500),
    ("E-CRN-11", "Lifting", "Telehandler", 4500), ("E-CRN-12", "Lifting", "Material ropeway / cable crane", 5000),
    ("E-CRN-13", "Lifting", "Hydraulic jack 50-100 t", 300), ("E-CRN-14", "Lifting", "Prestressing jack with pump", 1500),
    ("E-CRN-15", "Lifting", "Boom lift / man lift 20 m", 4000), ("E-CRN-16", "Lifting", "Penstock pipe trolley / winch system", 3500),
    # power & pumps
    ("E-GEN-01", "Power & pumps", "Generator 5 kVA", 400), ("E-GEN-02", "Power & pumps", "Generator 15 kVA", 900),
    ("E-GEN-03", "Power & pumps", "Generator 30 kVA", 1500), ("E-GEN-04", "Power & pumps", "Generator 62.5 kVA", 2500),
    ("E-GEN-05", "Power & pumps", "Generator 125 kVA", 4200), ("E-GEN-06", "Power & pumps", "Generator 250 kVA", 7500),
    ("E-GEN-07", "Power & pumps", "Generator 500 kVA", 13500), ("E-GEN-08", "Power & pumps", "Generator 1000 kVA", 25000),
    ("E-PMP-01", "Power & pumps", "Dewatering pump 2\" petrol", 350), ("E-PMP-02", "Power & pumps", "Dewatering pump 3\" diesel", 500),
    ("E-PMP-03", "Power & pumps", "Dewatering pump 4\" diesel", 700), ("E-PMP-04", "Power & pumps", "Dewatering pump 6\" diesel", 1100),
    ("E-PMP-05", "Power & pumps", "Submersible pump 5-10 hp", 500), ("E-PMP-06", "Power & pumps", "Slurry / sludge pump", 900),
    ("E-PMP-07", "Power & pumps", "Well-point dewatering system", 3000), ("E-PMP-08", "Power & pumps", "Transformer & HT line (temporary)", 2000),
    # welding, workshop, small tools
    ("E-WLD-01", "Welding & workshop", "Welding generator 300-400 A", 900), ("E-WLD-02", "Welding & workshop", "Welding transformer / inverter", 400),
    ("E-WLD-03", "Welding & workshop", "SAW (submerged arc) welding tractor", 2500), ("E-WLD-04", "Welding & workshop", "Gas cutting set", 250),
    ("E-WLD-05", "Welding & workshop", "Plate bending / rolling machine", 5000), ("E-WLD-06", "Welding & workshop", "Pipe beveling machine", 1200),
    ("E-WLD-07", "Welding & workshop", "Ultrasonic flaw detector (NDT)", 2500), ("E-WLD-08", "Welding & workshop", "Radiography (X-ray) set", 5000),
    ("E-WLD-09", "Welding & workshop", "Sand blasting unit", 2500), ("E-WLD-10", "Welding & workshop", "Airless paint sprayer", 900),
    ("E-WLD-11", "Welding & workshop", "Angle grinder", 100), ("E-WLD-12", "Welding & workshop", "Magnetic drill", 250),
    ("E-WLD-13", "Welding & workshop", "Electrode drying oven", 150), ("E-WLD-14", "Welding & workshop", "Hydro-test pump", 800),
    ("E-SML-01", "Small plant", "Chain saw", 300), ("E-SML-02", "Small plant", "Brush cutter", 250),
    ("E-SML-03", "Small plant", "Stump cutter / grinder", 1200), ("E-SML-04", "Small plant", "Pressure washer", 400),
    ("E-SML-05", "Small plant", "Core cutter / diamond drill (hand)", 500), ("E-SML-06", "Small plant", "Hammer drill", 150),
    ("E-SML-07", "Small plant", "Tile cutter", 150), ("E-SML-08", "Small plant", "Mortar mixer", 400),
    ("E-SML-09", "Small plant", "Light tower 4x1000 W", 800), ("E-SML-10", "Small plant", "Hand cart / wheel barrow", 20),
    # aggregate production
    ("E-AGP-01", "Aggregate production", "Jaw crusher 50 tph", 8000), ("E-AGP-02", "Aggregate production", "Crushing & screening plant 100 tph", 18000),
    ("E-AGP-03", "Aggregate production", "Cone crusher (secondary)", 9000), ("E-AGP-04", "Aggregate production", "VSI sand maker", 9000),
    ("E-AGP-05", "Aggregate production", "Vibrating screen 3-deck", 3500), ("E-AGP-06", "Aggregate production", "Sand washing machine", 3000),
    ("E-AGP-07", "Aggregate production", "Mobile crusher (track)", 22000),
    # survey & lab
    ("E-SUR-01", "Survey & lab", "Total station with accessories", 600), ("E-SUR-02", "Survey & lab", "Auto level with staff", 150),
    ("E-SUR-03", "Survey & lab", "GNSS / RTK set", 1500), ("E-SUR-04", "Survey & lab", "Drone survey (with processing)", 4000),
    ("E-SUR-05", "Survey & lab", "Tunnel laser / guidance system", 1500), ("E-SUR-06", "Survey & lab", "Tunnel profile scanner", 2500),
    ("E-LAB-01", "Survey & lab", "Compression testing machine 2000 kN", 400), ("E-LAB-02", "Survey & lab", "Universal testing machine", 800),
    ("E-LAB-03", "Survey & lab", "Sand replacement density kit", 100), ("E-LAB-04", "Survey & lab", "Nuclear density gauge", 800),
    ("E-LAB-05", "Survey & lab", "Plate load test set", 1500), ("E-LAB-06", "Survey & lab", "Benkelman beam", 300),
    ("E-LAB-07", "Survey & lab", "Rebound hammer", 50), ("E-LAB-08", "Survey & lab", "Ultrasonic pulse velocity tester", 300),
    ("E-LAB-09", "Survey & lab", "Pull-out tester (rock bolt)", 300), ("E-LAB-10", "Survey & lab", "Marshall test apparatus", 400),
    ("E-LAB-11", "Survey & lab", "CBR apparatus", 200), ("E-LAB-12", "Survey & lab", "Los Angeles abrasion machine", 250),
    # marine / river
    ("E-RIV-01", "River & marine", "Dredger (cutter suction, small)", 15000), ("E-RIV-02", "River & marine", "Pontoon / barge", 3000),
    ("E-RIV-03", "River & marine", "Boat with outboard motor", 900), ("E-RIV-04", "River & marine", "Sheet pile vibro-hammer", 9000),
    ("E-RIV-05", "River & marine", "Diesel pile hammer", 7000),
]
for code, cat, name, rate in eq:
    add(code, E, EQ + cat, name, "hr", 0, rate, "Hire rate incl. operator, fuel & lubricants", cat)

# ════════════════════════════ TRANSPORT (cartage) ════════════════════════════
# rates per tonne-km by road class; porter and mule per tonne-km on trails; loading/unloading per tonne
for code, name, unit, rate, spec in [
    ("T-001", "Cartage on black-topped road", "t-km", 18, "Truck/tipper, first 50 km"),
    ("T-002", "Cartage on black-topped road beyond 50 km", "t-km", 14, ""),
    ("T-003", "Cartage on gravel road", "t-km", 28, ""),
    ("T-004", "Cartage on earthen / fair-weather road", "t-km", 40, ""),
    ("T-005", "Cartage by tractor (earthen track)", "t-km", 55, ""),
    ("T-006", "Cartage by mule", "t-km", 450, ""),
    ("T-007", "Cartage by porter (trail)", "t-km", 1200, "Hill trail, up to 30 kg per load"),
    ("T-008", "Loading on truck (manual)", "t", 150, ""),
    ("T-009", "Unloading from truck (manual)", "t", 100, ""),
    ("T-010", "Loading by loader", "t", 60, ""),
    ("T-011", "Ropeway / cable crane transport", "t", 900, "Per crossing"),
    ("T-012", "Air transport (helicopter)", "t-km", 25000, "Remote sites"),
]:
    add(code, T, "Transport & cartage", name, unit, 0, rate, spec)


# 1.8.2 extension: tools and every project type (never reorder - codes are positional)
import res_seed_ext  # noqa: E402
res_seed_ext.extend(add)


def by_code():
    return {x["code"]: x for x in POOL}


if __name__ == "__main__":
    import collections
    codes = [x["code"] for x in POOL]
    dup = [c for c, n in collections.Counter(codes).items() if n > 1]
    print(len(POOL), "resources;", collections.Counter(x["type"] for x in POOL), "duplicates:", dup)
