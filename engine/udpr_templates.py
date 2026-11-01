"""Built-in Universal DPR templates (BuildCore 2.25).

Each template is data: sections of header fields ("fields"), repeating tables ("table") and extra columns on the
activity rows ("line"). Administrators edit them in Daily progress (DPR) > Templates & fields; editing publishes a
new version and every DPR keeps the versions it was filled with. Nothing here is code that runs per project.
"""


def F(key, label, type="text", **kw):
    d = {"key": key, "label": label, "type": type}
    d.update(kw)
    return d


def S(key, label, kind, fields, **kw):
    d = {"key": key, "label": label, "kind": kind, "fields": fields}
    d.update(kw)
    return d


YN = ["Yes", "No"]
STATUS_IR = ["Requested", "Inspected - passed", "Inspected - failed", "Re-inspection", "Cancelled"]
TEST_RESULT = ["Pending", "Pass", "Fail", "Retest"]

BASIC = [
    S("toolbox", "Toolbox talks and safety inspections", "table", [
        F("topic", "Topic / inspection", required=True), F("kind", "Type", "select", options=["Toolbox talk", "Safety inspection", "PPE check", "Permit to work"]),
        F("attendees", "Persons", "int", min=0), F("by", "Conducted by", "person"), F("findings", "Findings / actions", "longtext")],
      group="hse", advanced=True),
    S("hse_events", "Incidents, near misses and environment", "table", [
        F("kind", "Type", "select", required=True, options=["Near miss", "First aid", "Lost-time injury", "Property damage", "Environmental (dust, noise, waste, water)", "Community complaint"]),
        F("time", "Time", "time"), F("location", "Location", "location"), F("description", "What happened", "longtext", required=True),
        F("persons", "Persons involved", "text"), F("action", "Corrective action", "longtext"), F("owner", "Responsible", "person"),
        F("status", "Status", "select", options=["Open", "Action taken", "Closed"], default="Open")],
      group="hse", advanced=True, sensitive=True),
    S("inspections", "Inspection requests and tests", "table", [
        F("ir_no", "IR / sample no."), F("activity", "Work inspected"), F("location", "Location", "location"),
        F("test", "Test type"), F("date", "Inspection date", "date"),
        F("status", "Status", "select", options=STATUS_IR, default="Requested"), F("result", "Result"),
        F("ncr", "NCR reference"), F("by", "Inspected by", "person")],
      group="quality", advanced=True,
      note="Recording an inspection here does not accept the work; acceptance is the QS / engineer's step on the quantities."),
    S("visitors", "Visitors and instructions received", "table", [
        F("who", "Visitor / issued by", required=True), F("org", "Organisation"), F("instruction", "Instruction or purpose", "longtext"),
        F("ref", "Reference (letter, site instruction no.)"), F("action", "Action required", "longtext")],
      advanced=True),
]

BUILDING = [
    S("bld_line", "Building location on each work row", "line", [
        F("block", "Block"), F("floor", "Floor", "select", options=["Foundation", "Basement", "Ground", "1st", "2nd", "3rd", "4th", "5th", "6th", "7th", "8th", "9th", "10th", "Roof"]),
        F("grid", "Grid"), F("level", "Level / elevation")]),
    S("bld_concrete", "Concrete casting", "table", [
        F("element", "Element", "select", required=True, options=["Footing", "Column", "Beam", "Slab", "Wall", "Staircase", "Lift core", "Water tank"]),
        F("floor", "Floor"), F("grid", "Grid"), F("grade", "Grade", "select", options=["M15", "M20", "M25", "M30", "M35", "M40"]),
        F("qty", "Quantity", "measure", unit="m3", min=0), F("slump", "Slump (mm)", "int", min=0, max=250),
        F("cubes", "Cubes sampled", "int", min=0), F("start", "Start", "time"), F("end", "End", "time")]),
    S("bld_rebar", "Reinforcement and formwork", "table", [
        F("element", "Element"), F("floor", "Floor"), F("rebar_t", "Reinforcement fixed", "measure", unit="t", min=0),
        F("form_m2", "Formwork", "measure", unit="m2", min=0), F("status", "Status", "select", options=["In progress", "Ready for inspection", "Approved for casting"])]),
    S("bld_finish", "Masonry, plaster, finishing and services", "table", [
        F("trade", "Work", "select", required=True, options=["Masonry", "Plaster", "Waterproofing", "Flooring", "Painting", "Doors & windows", "Plumbing", "Electrical", "Fire fighting", "HVAC", "Lift"]),
        F("floor", "Floor"), F("area", "Area / room"), F("qty", "Quantity", "decimal", min=0), F("unit", "Unit"),
        F("test", "Test (pressure, insulation...)", "select", options=["", "Not required", "Pending", "Passed", "Failed"])], advanced=True),
]

ROAD = [
    S("road_line", "Road position on each work row", "line", [
        F("side", "Side", "select", options=["LHS", "RHS", "Both", "Median"]),
        F("layer", "Layer", "select", options=["Clearing", "Cut", "Fill / embankment", "Subgrade", "Sub-base", "Base course", "Prime / tack", "DBM", "AC / wearing", "Shoulder", "Drain"]),
        F("cut_fill", "Cut / fill", "select", options=["", "Cut", "Fill"])]),
    S("road_earth", "Earthwork", "table", [
        F("ch_from", "Ch. from", "chainage"), F("ch_to", "Ch. to", "chainage"), F("kind", "Cut / fill", "select", options=["Cut", "Fill"]),
        F("class", "Classification", "select", options=["Soil", "Ordinary rock", "Hard rock", "Boulder", "Unsuitable"]),
        F("qty", "Quantity", "measure", unit="m3", min=0), F("haul", "Lead (km)", "decimal", min=0)]),
    S("road_pave", "Pavement layers", "table", [
        F("layer", "Layer", "select", required=True, options=["Subgrade", "Sub-base", "Base course", "Prime", "Tack", "DBM", "AC", "Shoulder"]),
        F("ch_from", "Ch. from", "chainage"), F("ch_to", "Ch. to", "chainage"), F("side", "Side", "select", options=["LHS", "RHS", "Both"]),
        F("thick", "Thickness (mm)", "int", min=0), F("qty", "Quantity", "decimal", min=0), F("unit", "Unit", default="m2"),
        F("compaction", "Field density", "percent", min=0, max=110)]),
    S("road_agg", "Aggregate production", "table", [
        F("plant", "Crusher / plant"), F("product", "Product", "select", options=["40 mm", "20 mm", "10 mm", "Dust", "GSB", "WMM"]),
        F("qty", "Produced", "measure", unit="m3", min=0), F("hours", "Running hours", "decimal", min=0, max=24)], advanced=True),
    S("road_struct", "Culverts, drains, gabions and slope protection", "table", [
        F("kind", "Structure", "select", required=True, options=["Pipe culvert", "Box / slab culvert", "Side drain", "Catch drain", "Gabion", "Retaining wall", "Breast wall", "Bio-engineering"]),
        F("chainage", "Chainage", "chainage"), F("element", "Element / activity"), F("qty", "Quantity", "decimal", min=0), F("unit", "Unit")]),
    S("road_slide", "Landslides and slope events", "table", [
        F("chainage", "Chainage", "chainage"), F("event", "Event", "select", options=["Landslide", "Rock fall", "Washout", "Settlement"]),
        F("volume", "Volume", "measure", unit="m3", min=0), F("blocked", "Road blocked", "yesno"), F("action", "Action taken", "longtext")], advanced=True),
    S("road_lab", "Laboratory tests", "table", [
        F("test", "Test", "select", options=["Field density", "CBR", "Gradation", "Atterberg limits", "Marshall", "Core", "Bitumen extraction", "Cube strength"]),
        F("chainage", "Chainage", "chainage"), F("result", "Result"), F("spec", "Specified"), F("status", "Status", "select", options=TEST_RESULT)],
      group="quality", advanced=True),
]

HYDRO = [
    S("hp_line", "Hydropower component on each work row", "line", [
        F("component", "Component", "select", options=["Headworks", "Intake", "Desander", "Headrace tunnel", "Adit", "Surge shaft", "Pressure shaft", "Penstock", "Powerhouse", "Tailrace", "Access road", "Ropeway", "Batching plant", "Electro-mechanical", "Hydro-mechanical", "Switchyard"]),
        F("face", "Face / heading")]),
    S("hp_faces", "Tunnel faces", "table", [
        F("face", "Face", required=True), F("ch_from", "Ch. from", "chainage"), F("ch_to", "Ch. to", "chainage"),
        F("advance", "Advance", "measure", unit="m", min=0, max=30), F("rock_class", "Rock class", "select", options=["I", "II", "III", "IV", "V"]),
        F("q_value", "Q value", "decimal", min=0), F("water", "Groundwater inflow", "measure", unit="l/min", min=0),
        F("bolts", "Rock bolts", "int", min=0), F("bolt_len", "Bolt length", "measure", unit="m", min=0),
        F("shotcrete", "Shotcrete", "measure", unit="m3", min=0), F("mesh", "Wire mesh", "measure", unit="m2", min=0),
        F("ribs", "Steel ribs", "int", min=0), F("grout", "Grouting", "measure", unit="m", min=0),
        F("cycles", "Cycles", "int", min=0), F("remarks", "Geology / remarks", "longtext")]),
    S("hp_shafts", "Surge shaft, pressure shaft and penstock", "table", [
        F("structure", "Structure", "select", options=["Surge shaft", "Pressure shaft", "Penstock", "Valve chamber"]),
        F("from", "From (EL / ch.)"), F("to", "To (EL / ch.)"), F("advance", "Advance / length", "measure", unit="m", min=0),
        F("activity", "Activity", "select", options=["Excavation", "Support", "Lining", "Erection", "Welding", "NDT", "Backfill concrete"])]),
    S("hp_conc", "Concrete and lining", "table", [
        F("structure", "Structure"), F("element", "Element"), F("grade", "Grade"), F("qty", "Quantity", "measure", unit="m3", min=0)]),
    S("hp_em", "Electro-mechanical and hydro-mechanical", "table", [
        F("package", "Package", "select", options=["Turbine", "Generator", "Transformer", "Control & protection", "Gates", "Stoplogs", "Trash rack", "Penstock steel"]),
        F("item", "Item / tag"), F("activity", "Activity"), F("progress", "Progress", "percent", min=0, max=100)], advanced=True),
    S("hp_ug_safety", "Underground safety", "table", [
        F("face", "Face"), F("gas", "Gas test (ppm CO)", "decimal", min=0), F("o2", "Oxygen", "percent", min=0, max=30),
        F("vent", "Ventilation working", "yesno"), F("persons", "Persons underground", "int", min=0),
        F("tag", "Tag board checked", "yesno")], group="hse", advanced=True),
    S("hp_access", "Access roads, ropeways and batching plants", "table", [
        F("facility", "Facility", "select", options=["Access road", "Ropeway", "Batching plant", "Crusher", "Camp"]),
        F("status", "Status", "select", options=["Working", "Partly working", "Stopped"]), F("output", "Output today"), F("note", "Note", "longtext")], advanced=True),
]

RAIL = [
    S("rl_line", "Railway position on each work row", "line", [
        F("section", "Section / station"), F("track", "Track", "select", options=["UP", "DN", "Both", "Siding"])]),
    S("rl_track", "Track works", "table", [
        F("activity", "Activity", "select", required=True, options=["Formation", "Blanketing", "Ballast", "Sleepers", "Rails", "Flash-butt welding", "Thermit welding", "Tamping", "Turnouts"]),
        F("ch_from", "Ch. from", "chainage"), F("ch_to", "Ch. to", "chainage"), F("qty", "Quantity", "decimal", min=0), F("unit", "Unit")]),
    S("rl_struct", "Tunnels, bridges and stations", "table", [
        F("structure", "Structure"), F("element", "Element"), F("activity", "Activity"), F("qty", "Quantity", "decimal", min=0), F("unit", "Unit")]),
    S("rl_sys", "Systems", "table", [
        F("system", "System", "select", options=["Signalling", "Traction (OHE)", "Telecom", "Power supply", "Utilities", "Fare collection"]),
        F("location", "Location", "location"), F("activity", "Activity"), F("progress", "Progress", "percent", min=0, max=100)]),
    S("rl_window", "Work windows and possessions", "table", [
        F("start", "Window start", "datetime"), F("end", "Window end", "datetime"), F("granted", "Possession granted", "yesno"),
        F("hours_used", "Hours used", "decimal", min=0), F("constraint", "Constraint", "longtext")]),
    S("rl_test", "Testing and commissioning", "table", [
        F("system", "System"), F("test", "Test"), F("result", "Result", "select", options=TEST_RESULT)], group="quality", advanced=True),
]

BRIDGE = [
    S("br_line", "Bridge position on each work row", "line", [
        F("bridge", "Bridge"), F("span", "Span / pier"),
        F("element", "Element", "select", options=["Pile", "Pile cap", "Well", "Pier", "Abutment", "Pier cap", "Bearing", "Girder", "Deck slab", "Crash barrier", "Approach slab"])]),
    S("br_pile", "Piling and foundations", "table", [
        F("pile", "Pile / well no.", required=True), F("location", "Location", "location"), F("depth", "Depth", "measure", unit="m", min=0),
        F("concrete", "Concrete", "measure", unit="m3", min=0), F("status", "Status", "select", options=["Boring", "Cage lowered", "Concreted", "Integrity tested"])]),
    S("br_elem", "Piers, abutments, girders and deck", "table", [
        F("span", "Span / pier"), F("element", "Element"), F("activity", "Activity"), F("qty", "Quantity", "decimal", min=0), F("unit", "Unit")]),
    S("br_ps", "Prestressing and grouting", "table", [
        F("girder", "Girder"), F("cable", "Cable"), F("pressure", "Jack pressure (bar)", "decimal", min=0),
        F("elong", "Elongation (mm)", "decimal", min=0), F("grout", "Grouted", "yesno")]),
    S("br_lift", "Lifting operations", "table", [
        F("item", "Item lifted"), F("crane", "Crane"), F("weight", "Weight", "measure", unit="t", min=0), F("permit", "Lift permit no."),
        F("outcome", "Outcome", "select", options=["Completed", "Aborted", "Postponed"])], group="hse", advanced=True),
    S("br_insp", "Structural inspection", "table", [
        F("element", "Element"), F("finding", "Finding", "longtext"), F("status", "Status", "select", options=TEST_RESULT)], group="quality", advanced=True),
]

WATER = [
    S("ws_line", "Network position on each work row", "line", [
        F("zone", "Zone / branch"), F("dia", "Pipe dia (mm)", "int", min=0)]),
    S("ws_pipe", "Pipe laying", "table", [
        F("zone", "Zone / branch"), F("ch_from", "Ch. from", "chainage"), F("ch_to", "Ch. to", "chainage"), F("dia", "Dia (mm)", "int", min=0),
        F("material", "Pipe", "select", options=["HDPE", "DI", "GI", "MS", "uPVC", "RCC"]), F("length", "Length laid", "measure", unit="m", min=0),
        F("depth", "Trench depth", "measure", unit="m", min=0), F("backfilled", "Backfilled", "yesno")]),
    S("ws_struct", "Intakes, reservoirs, canals and treatment", "table", [
        F("structure", "Structure", "select", options=["Intake", "Reservoir / tank", "Treatment plant", "Canal", "Aqueduct", "Manhole", "Pump house"]),
        F("element", "Element"), F("qty", "Quantity", "decimal", min=0), F("unit", "Unit")]),
    S("ws_test", "Pressure and leakage tests", "table", [
        F("section", "Section"), F("pressure", "Test pressure (bar)", "decimal", min=0), F("hours", "Duration (h)", "decimal", min=0),
        F("result", "Result", "select", options=TEST_RESULT)], group="quality"),
    S("ws_conn", "Connections", "table", [F("kind", "Type", "select", options=["House connection", "Public tap", "Valve", "Hydrant"]), F("count", "Number", "int", min=0)], advanced=True),
]

LINEAR_POWER = [
    S("tl_line", "Tower, bay or area on each work row", "line", [F("tower", "Tower / bay / area")]),
    S("tl_tower", "Tower foundations and erection", "table", [
        F("tower", "Tower no.", required=True), F("type", "Tower type"),
        F("activity", "Activity", "select", options=["Excavation", "Stub setting", "Foundation concrete", "Backfill", "Erection", "Tack welding", "Earthing"]),
        F("status", "Status", "select", options=["Started", "Completed"])]),
    S("tl_string", "Stringing", "table", [
        F("from", "From tower"), F("to", "To tower"), F("conductor", "Conductor strung", "measure", unit="km", min=0), F("opgw", "OPGW strung", "measure", unit="km", min=0)]),
    S("tl_ss", "Substation and switchyard", "table", [
        F("bay", "Bay"), F("equipment", "Equipment"), F("activity", "Activity"), F("progress", "Progress", "percent", min=0, max=100)]),
    S("tl_air", "Airside and terminal works", "table", [
        F("area", "Area", "select", options=["Runway", "Taxiway", "Apron", "Terminal", "Control tower", "Fencing", "Airfield lighting"]),
        F("layer", "Layer / activity"), F("qty", "Quantity", "decimal", min=0), F("unit", "Unit")], advanced=True),
    S("tl_test", "Testing and energisation", "table", [
        F("item", "Item"), F("test", "Test"), F("result", "Result", "select", options=TEST_RESULT)], group="quality", advanced=True),
]

EPC = [
    S("epc_line", "Discipline and area on each work row", "line", [
        F("discipline", "Discipline", "select", options=["Civil", "Structural", "Mechanical", "Piping", "Electrical", "Instrumentation", "HVAC", "Architectural"]),
        F("area", "Area / unit"), F("system", "System")]),
    S("epc_prog", "Discipline progress", "table", [
        F("discipline", "Discipline", "select", required=True, options=["Civil", "Structural", "Mechanical", "Piping", "Electrical", "Instrumentation", "HVAC"]),
        F("area", "Area / system"), F("activity", "Activity"), F("qty", "Quantity", "decimal", min=0), F("unit", "Unit"),
        F("progress", "Progress", "percent", min=0, max=100)]),
    S("epc_erect", "Equipment erection", "table", [
        F("tag", "Equipment tag", required=True), F("activity", "Activity"), F("weight", "Weight", "measure", unit="t", min=0),
        F("status", "Status", "select", options=["Received", "Set on foundation", "Aligned", "Grouted", "Ready for commissioning"])]),
    S("epc_pipe", "Piping", "table", [
        F("line", "Line no."), F("dia", "Dia (inch)", "decimal", min=0), F("inch_dia", "Inch-dia welded", "decimal", min=0),
        F("joints", "Joints", "int", min=0), F("ndt", "NDT", "select", options=["", "Pending", "Passed", "Repair"])]),
    S("epc_comm", "Pre-commissioning and handover", "table", [
        F("system", "System"), F("test", "Test / check"), F("status", "Status", "select", options=TEST_RESULT)], group="quality", advanced=True),
    S("epc_iface", "Interfaces with other contractors", "table", [
        F("with", "With contractor"), F("item", "Interface item"), F("need", "Needed by", "date"),
        F("status", "Status", "select", options=["Open", "Agreed", "Closed"])], advanced=True),
]

BUILTIN = [
    ("BASIC", "Basic (every project)", "basic", "Safety, inspections, incidents and visitors for any project.", BASIC),
    ("BLDG", "Residential and commercial buildings", "building", "Floor, grid and block on work rows; concrete casting, reinforcement, finishing and services.", BUILDING),
    ("ROAD", "Roads, highways and fast-track roads", "road", "Chainage and layer on work rows; earthwork, pavement, aggregates, structures, landslides and lab tests.", ROAD),
    ("HYDRO", "Hydropower projects", "hydro", "Component and face on work rows; tunnel faces with geology and support, shafts, concrete, E&M / HM, underground safety.", HYDRO),
    ("RAIL", "Railways, metro and high-speed rail", "rail", "Track works, structures, systems, work windows and commissioning.", RAIL),
    ("BRIDGE", "Bridges and elevated structures", "bridge", "Bridge, span and element on work rows; piling, prestressing, lifting and inspections.", BRIDGE),
    ("WATER", "Water supply, irrigation, drainage and sewerage", "water", "Pipe laying, structures, pressure tests and connections.", WATER),
    ("POWERLINE", "Airports, transmission lines and substations", "linear", "Towers, stringing, substations, airside works and energisation.", LINEAR_POWER),
    ("EPC", "Industrial and multidisciplinary EPC", "epc", "Discipline progress, erection, piping, commissioning and interfaces.", EPC),
]

# project_type words -> template code suggested when a project has no templates chosen yet
SUGGEST = [("hydro", "HYDRO"), ("tunnel", "HYDRO"), ("road", "ROAD"), ("highway", "ROAD"), ("rail", "RAIL"), ("metro", "RAIL"),
           ("bridge", "BRIDGE"), ("water", "WATER"), ("irrig", "WATER"), ("sewer", "WATER"), ("drain", "WATER"),
           ("transmission", "POWERLINE"), ("substation", "POWERLINE"), ("airport", "POWERLINE"), ("industr", "EPC"), ("epc", "EPC"),
           ("build", "BLDG"), ("house", "BLDG"), ("residential", "BLDG"), ("commercial", "BLDG")]
