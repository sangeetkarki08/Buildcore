"""BuildCore 2.47.0 - BOQ by location: overall summary and short codes.

Asked by SULAV: a BOQ can be priced per location (hydropower: M25 concrete at Headworks 45 m3, M25 at the Settling
basin 15 m3) and overall. Once the BOQ is entered or imported BuildCore must sum the same item over its locations
(M25 = 60 m3) and give every line an automatic short code that ties the BOQ item to its location (HW-M25, SB-M25), so
the code can be used to pick the BOQ line in procurement, DPR, billing, cost to complete and every other screen. For
every kind of project (hydropower, roads, buildings, bridges, irrigation and water, transmission lines ...).

The model (see 2.47/CHANGELOG_2.47.0.md for the audit behind it):
  * The BOQ line stays what it is today: one boq_items row per item and location, with its own id, quantity and rate.
    Every screen already links to that id (DPR work, requisitions, PR/PO, issues, measurements, IPC, cost codes,
    variations, subcontract orders, Tally cost centres), so all of them are location-specific without a change.
  * Location = the project's existing BOQ component / bill (boq_components, 2.x "By component"), or the text in the
    BOQ line's location column. Each location gets a short abbreviation (HW, SB, HRT, PH, CH0-1.5, GF, P1 ...).
  * Item = new side record bx_item: the same work in several locations (same description without the location words,
    same unit). Its key is generated from the description (M25, PCC-M10, RBAR-FE500, EXC-SOIL, GSB, HDPE-110 ...).
  * Short code = location abbreviation + item key ({LOC}-{ITEM} by default: HW-M25). Unique in the project; can be
    typed by hand (then kept). Lines with no location get the item key alone.
  * Summary = items with their total quantity and amount, the split by location (matrix) and the commercial
    figures of 'BOQ control' added up (executed, measured, billed, certified, actual cost, forecast).
  * An overall line that only repeats the sum of its location lines can be marked 'overall' so it is shown as the
    stated total and not counted twice; the import leaves such lines out by itself.

Nothing in boq_items changes except what a person asks for (the import adds lines; 'Build codes' may file a line
under a location component created from its own location text). Only new bx_* tables are added. Switch bx_on: off on
existing companies until commercial (approve) turns it on, on for new companies.
"""
import re

import core
from core import ApiError, q, q1, val, r2, r4, setting
import api_inventory as inv
from api_inventory import api

VERSION = "2.47.0"
FLAG = "_bco247"
EPS = 0.0005

SCHEMA = """
CREATE TABLE IF NOT EXISTS bx_loc(id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, component_id INTEGER, text TEXT,
  abbr TEXT, manual INTEGER DEFAULT 0, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_bx_loc_p ON bx_loc(project_id);
CREATE TABLE IF NOT EXISTS bx_item(id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, key TEXT, gkey TEXT, title TEXT,
  unit TEXT, manual INTEGER DEFAULT 0, stated_qty REAL, stated_note TEXT, ts TEXT);
CREATE INDEX IF NOT EXISTS ix_bx_item_p ON bx_item(project_id);
CREATE TABLE IF NOT EXISTS bx_line(boq_item_id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, item_id INTEGER,
  loc_id INTEGER, short_code TEXT, manual INTEGER DEFAULT 0, item_manual INTEGER DEFAULT 0, role TEXT DEFAULT 'line', ts TEXT);
CREATE INDEX IF NOT EXISTS ix_bx_line_p ON bx_line(project_id);
CREATE INDEX IF NOT EXISTS ix_bx_line_sc ON bx_line(project_id, short_code);
CREATE TABLE IF NOT EXISTS bx_log(id INTEGER PRIMARY KEY, ts TEXT, user_id INTEGER, project_id INTEGER, what TEXT, detail TEXT);
"""

FORMATS = {"{LOC}-{ITEM}": "HW-M25", "{ITEM}-{LOC}": "M25-HW", "{LOC}/{ITEM}": "HW/M25", "{LOC}.{ITEM}": "HW.M25"}
CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_./+]{0,23}$")


def _f(x, d=0.0):
    try:
        return float(x) if x not in (None, "") else d
    except (TypeError, ValueError):
        return d


def _set(c, k, v):
    c.execute("INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))


def on(c):
    return setting(c, "bx_on") == "1"


def fmt_of(c):
    f = setting(c, "bx_format") or "{LOC}-{ITEM}"
    return f if f in FORMATS else "{LOC}-{ITEM}"


def _log(c, u, pid, what, detail):
    import json
    c.execute("INSERT INTO bx_log(ts, user_id, project_id, what, detail) VALUES(?,?,?,?,?)",
              (core.now() if hasattr(core, "now") else core.today(), (u or {}).get("id"), pid, what,
               json.dumps(detail, default=str)[:4000]))


# ───────────────────────────── words: units, locations, items ─────────────────────────────
UNITS = [(r"^(m3|m\^3|cum|cu\.?\s?m\.?|cubic\s?met(er|re)s?|m³)$", "m3"), (r"^(m2|m\^2|sqm|sq\.?\s?m\.?|square\s?met(er|re)s?|m²)$", "m2"),
         (r"^(m|rm|rmt|r\.?m\.?|lm|met(er|re)s?|running\s?met(er|re)s?)$", "m"), (r"^(t|mt|ton|tons|tonne|tonnes|m\.?t\.?)$", "t"),
         (r"^(kg|kgs|kilogram|kilograms)$", "kg"), (r"^(no|nos|no\.|nos\.|number|numbers|each|ea|pcs|pc)$", "nos"),
         (r"^(ls|l\.s\.?|lump\s?sum|lumpsum|item|job|lot)$", "ls"), (r"^(km|kilomet(er|re)s?)$", "km"), (r"^(l|ltr|litre|liter|litres|liters)$", "l")]


def norm_unit(u):
    s = re.sub(r"\s+", " ", str(u or "").strip().lower())
    for rx, out in UNITS:
        if re.match(rx, s):
            return out
    return s


# location words -> abbreviation (first match in this order wins; a number after the word is kept: Pier 3 -> P3)
LOC_WORDS = [
    (r"general|preliminar", "GEN"), (r"settling\s*basin|desilting|sediment(ation)?\s*basin", "SB"), (r"desander", "DS"),
    (r"head\s*works?", "HW"), (r"gravel\s*trap", "GT"), (r"under\s*sluice", "US"), (r"diversion", "DIV"), (r"\bweir\b|\bdam\b|barrage", "WR"),
    (r"\bintake\b", "INT"), (r"head\s*race\s*tunnel|\bhrt\b", "HRT"), (r"head\s*race\s*canal", "HRC"), (r"head\s*race\s*pipe", "HRP"),
    (r"head\s*race", "HR"), (r"\badit\b", "ADT"), (r"surge", "ST"), (r"fore\s*bay", "FB"), (r"penstock", "PS"), (r"anchor\s*block", "AB"),
    (r"power\s*house", "PH"), (r"tail\s*race", "TR"), (r"hydro[\s-]*mechanical|\bh\s*&\s*m\b|\bhm\b", "HM"),
    (r"electro[\s-]*mechanical|\be\s*&\s*m\b|\bem\b", "EM"), (r"switch\s*yard", "SY"), (r"sub\s*station", "SS"),
    (r"transmission\s*line", "TL"), (r"transmission\s*main", "TM"), (r"access\s*road", "AR"), (r"\bcamp\b", "CMP"),
    (r"environment|social|resettlement", "ENV"), (r"river\s*training", "RT"), (r"approach", "APR"),
    (r"abutment", "A"), (r"\bpier\b", "P"), (r"super\s*structure", "SUP"), (r"sub\s*structure", "SUB"), (r"\btowers?\b", "TWR"), (r"foundation", "FDN"),
    (r"basement", "B"), (r"ground\s*floor", "GF"), (r"\broof\b|terrace", "RF"), (r"\bblock\b", "BLK"), (r"\bwing\b", "WNG"),
    (r"\btowers?\b", "TWR"), (r"external\s*works?|site\s*works?", "EXT"), (r"\bmep\b|plumbing|sanitary|electrical\s*works", "MEP"),
    (r"main\s*canal", "MC"), (r"branch\s*canal", "BC"), (r"secondary\s*canal", "SC"), (r"distributary|tertiary", "DY"),
    (r"aqueduct", "AQ"), (r"syphon|siphon", "SYP"), (r"cross[\s-]*drainage", "CD"), (r"reservoir", "RES"), (r"\btank\b", "TNK"),
    (r"treatment\s*plant|\bwtp\b", "WTP"), (r"distribution", "DIST"), (r"\breach\b", "R"), (r"stringing", "STR"),
    (r"culvert", "CUL"), (r"retaining\s*wall", "RW"), (r"breast\s*wall", "BW"), (r"\bdrains?\b", "DRN"), (r"pavement", "PVT"),
    (r"earth\s*works?", "EW"), (r"carriage\s*way", "CW"), (r"bridge", "BR"), (r"\btunnel\b", "TUN"), (r"\bshaft\b", "SHF"),
    (r"\bstation\b", "STN"), (r"\byard\b", "YD"), (r"\bdepot\b", "DPT"), (r"\bapron\b", "APN"), (r"runway", "RWY"), (r"taxiway", "TWY"),
]
FLOORS = [(r"\bfirst\s*floor|\b1st\s*floor", "F1"), (r"\bsecond\s*floor|\b2nd\s*floor", "F2"), (r"\bthird\s*floor|\b3rd\s*floor", "F3"),
          (r"\bfourth\s*floor|\b4th\s*floor", "F4"), (r"\bfifth\s*floor|\b5th\s*floor", "F5"), (r"\b(\d{1,2})(th|st|nd|rd)?\s*floor", None)]
STOP = {"and", "the", "of", "for", "in", "at", "to", "on", "with", "by", "a", "an", "&", "-", "/", "including", "incl", "incl.", "all",
        "complete", "providing", "provide", "laying", "lay", "supplying", "supply", "fixing", "fix", "placing", "place", "works", "work",
        "construction", "constructing", "as", "per", "specification", "specifications", "drawing", "drawings", "approved", "engineer",
        "instructed", "directed", "etc", "item", "items", "no", "nos", "type", "using", "use", "from", "into", "up", "upto", "within"}


def _clean(s):
    return re.sub(r"[^A-Z0-9.+\-]", "", str(s or "").upper())


def _km(chain):
    km, m = chain
    v = int(km) + int(m) / 1000.0
    return ("%.3f" % v).rstrip("0").rstrip(".")


def loc_abbr(name):
    """Short code for a location name: Headworks -> HW, Settling basin -> SB, Pier 3 -> P3, Ch 0+000 - 1+500 -> CH0-1.5."""
    s = str(name or "").strip()
    if not s:
        return ""
    low = s.lower()
    ch = re.findall(r"(\d{1,3})\s*\+\s*(\d{3})", low)
    if ch:
        return "CH" + _km(ch[0]) + ("-" + _km(ch[1]) if len(ch) > 1 else "")
    for rx, ab in FLOORS:
        m = re.search(rx, low)
        if m:
            return ab or "F" + m.group(1)
    head = re.split(r"[(\[,;]", low)[0] or low
    for rx, ab in LOC_WORDS:
        m = re.search(rx, head) or re.search(rx, low)
        if m:
            tail = low[m.end():]
            n = re.match(r"\s*(?:no\.?\s*)?([a-z]?[0-9]+|[a-z](?![a-z]))", tail)
            if n and (ab in ("A", "P", "B", "BLK", "R", "TWR", "WNG", "CUL", "BR", "SHF", "ADT", "STN", "TNK") or n.group(1)[-1].isdigit()):
                g = n.group(1).upper()
                if len(ab) == 1 and len(g) > 1 and g[0] == ab:
                    return g                      # Abutment A1 -> A1, Pier P2 -> P2
                return ab + (g[1:] if len(g) > 1 and g[0].isalpha() and g[1:].isdigit() and len(ab) == 1 else g)
            if ab in ("A", "P", "R", "B"):
                return {"A": "ABT", "P": "PIER", "R": "RCH", "B": "BSMT"}[ab]
            return ab
    words = [w for w in re.findall(r"[a-z0-9]+", head) if w not in STOP]
    if not words:
        words = re.findall(r"[a-z0-9]+", low)
    if len(words) >= 2:
        return "".join(w[0] for w in words[:4]).upper() + "".join(w for w in words[1:] if w.isdigit())[:3]
    return words[0][:4].upper() if words else "LOC"


# item key rules: (regex on the lower-case description, key or function(match, text) -> key); first match wins
def _grade(t):
    m = re.search(r"\b([mc])\s?-?\s?(\d{2,3})(?:\s*/\s*\d{2,3})?\b", t)
    return (m.group(1).upper() + m.group(2)) if m else ""


def _num_mm(t):
    m = re.search(r"(\d{2,4})\s*(?:mm|mm\.|millimet)", t) or re.search(r"(?:dia\.?|diameter|ø|Ø)\s*(\d{2,4})", t)
    return m.group(1) if m else ""


def _thick(t):
    m = re.search(r"(\d{1,3})\s*mm", t)
    return m.group(1) + "MM" if m else ""


def _key_concrete(t):
    g = _grade(t)
    if re.search(r"shotcrete|sprayed\s*concrete", t):
        return "SHOT" + ("-" + g if g else "")
    if re.search(r"\bpcc\b|plain\s*(cement\s*)?concrete|lean\s*concrete|blinding", t):
        return "PCC" + ("-" + g if g else "")
    if g:
        return g
    mix = re.search(r"1\s*:\s*(\d(?:\.\d)?)\s*:\s*(\d)", t)
    if mix:
        return "CON-" + mix.group(1).replace(".", "") + mix.group(2)
    return "CON"


def _key_excavation(t):
    if re.search(r"tunnel|underground|adit|shaft|cavern", t):
        return "TEX" + ("-ROCK" if "rock" in t else "")
    if re.search(r"hard\s*rock", t):
        return "EXC-HROCK"
    if re.search(r"soft\s*rock|weathered\s*rock", t):
        return "EXC-SROCK"
    if "rock" in t:
        return "EXC-ROCK"
    if re.search(r"boulder", t):
        return "EXC-BLDR"
    if re.search(r"under\s*water|wet\s*soil|below\s*water", t):
        return "EXC-WET"
    if re.search(r"trench|foundation", t):
        return "EXC-FDN"
    if re.search(r"soil|earth|ordinary|common|all\s*kinds", t):
        return "EXC-SOIL"
    return "EXC"


def _key_pipe(t):
    kind = next((k for k, rx in (("HDPE", r"hdpe"), ("DI", r"\bdi\b|ductile"), ("GI", r"\bgi\b|galvani[sz]ed"), ("MS", r"\bms\b|mild\s*steel"),
                                  ("PVC", r"u?pvc"), ("RCC", r"rcc|hume|concrete\s*pipe"), ("CI", r"\bci\b|cast\s*iron"), ("PPR", r"\bppr\b")) if re.search(rx, t)), "PIPE")
    d = _num_mm(t)
    return kind + ("-" + d if d else "") if kind != "PIPE" else "PIPE" + ("-" + d if d else "")


ITEM_RULES = [
    (r"reinforc|rebar|\btmt\b|\bfe\s?-?\s?(415|500|550)|steel\s*bars?|deformed\s*bar|hysd", lambda t: "RBAR" + ("-FE" + re.search(r"fe\s?-?\s?(\d{3})", t).group(1) if re.search(r"fe\s?-?\s?(\d{3})", t) else "")),
    (r"form\s*work|shuttering|centering", lambda t: "FORM" + ("-SLIP" if "slip" in t else "")),
    (r"shotcrete|sprayed\s*concrete", _key_concrete),
    (r"rock\s*bolt|anchor\s*bar|soil\s*nail", lambda t: ("NAIL" if "nail" in t else "RBOLT") + ("-" + re.search(r"(\d{1,2})\s*m\b", t).group(1) + "M" if re.search(r"(\d{1,2})\s*m\b", t) else "")),
    (r"steel\s*rib|lattice\s*girder", lambda t: "RIB"),
    (r"wire\s*mesh|weld(ed)?\s*mesh", lambda t: "MESH"),
    (r"grout", lambda t: "GROUT" + ("-CON" if "consolidation" in t else "-CUR" if "curtain" in t else "-CON" if "contact" in t else "")),
    (r"excavat|cutting\s+in|earth\s*cutting", _key_excavation),
    (r"back\s*fill|filling|embankment|fill\s*material", lambda t: "EMB" if "embankment" in t else "FILL"),
    (r"sub[\s-]*base|\bgsb\b", lambda t: "GSB"),
    (r"wet\s*mix|\bwmm\b", lambda t: "WMM"),
    (r"base\s*course|crushed\s*stone\s*base|\bcbc\b|\bwbm\b", lambda t: "CBC" if "wbm" not in t else "WBM"),
    (r"prime\s*coat", lambda t: "PRIME"), (r"tack\s*coat", lambda t: "TACK"),
    (r"dense\s*bituminous|\bdbm\b", lambda t: "DBM"),
    (r"asphalt|bituminous\s*concrete|\bac\b\s*\d|\bsdbc\b", lambda t: "AC" + ("-" + _thick(t) if _thick(t) else "")),
    (r"surface\s*dressing|\bdbst\b|\bsbst\b|seal\s*coat|otta", lambda t: "SD"),
    (r"\bpcc\b|plain\s*(cement\s*)?concrete|lean\s*concrete|blinding|\brcc\b|reinforced\s*(cement\s*)?concrete|concrete|\bm\s?-?\s?\d{2}\b", _key_concrete),
    (r"brick", lambda t: "BRICK" + ("-" + _thick(t) if _thick(t) and "wall" in t else "")),
    (r"stone\s*masonry|rubble\s*masonry|\brrm\b|\bucr\b", lambda t: "SM" + ("-DRY" if "dry" in t else "")),
    (r"block\s*(masonry|work)|concrete\s*block|aac", lambda t: "BLOCK"),
    (r"gabion", lambda t: "GAB" + ("-MAT" if "mattress" in t else "")),
    (r"pitching|rip\s*rap|riprap", lambda t: "PITCH"),
    (r"plaster", lambda t: "PLAS" + ("-" + _thick(t) if _thick(t) else "")),
    (r"paint|distemper|emulsion|enamel|primer", lambda t: "PAINT"),
    (r"tile|tiling", lambda t: "TILE"), (r"marble|granite", lambda t: "STONE-FLR"),
    (r"water\s*proof|waterproof|membrane|bitumen\s*coat", lambda t: "WPROOF"),
    (r"water\s*stop", lambda t: "WSTOP"), (r"expansion\s*joint|\bej\b", lambda t: "EJ"), (r"bearing", lambda t: "BRG"),
    (r"pre[\s-]*stress|post[\s-]*tension|strand|cable\s*duct", lambda t: "PSC"),
    (r"\bpil(e|es|ing)\b", lambda t: "PILE" + ("-" + _num_mm(t) if _num_mm(t) else "")),
    (r"structural\s*steel|steel\s*structure|truss", lambda t: "SSTEEL"),
    (r"penstock\s*(pipe|steel)|steel\s*liner", lambda t: "PSTEEL"),
    (r"\bgate|stop\s*log|trash\s*rack|hoist", lambda t: "HM-" + ("GATE" if "gate" in t else "STOPLOG" if "stop" in t else "RACK" if "rack" in t else "HOIST")),
    (r"turbine|generator|transformer", lambda t: "EM-" + ("TURB" if "turbine" in t else "GEN" if "generator" in t else "TRF")),
    (r"pipe", _key_pipe),
    (r"dewater", lambda t: "DEWAT"), (r"clearing|grubbing|jungle", lambda t: "CLR"),
    (r"geo\s*textile|geotextile|geo\s*grid", lambda t: "GEOTX"), (r"drain(age)?\s*pipe|weep\s*hole", lambda t: "WEEP"),
    (r"kerb|curb", lambda t: "KERB"), (r"guard\s*rail|crash\s*barrier", lambda t: "GRAIL"), (r"road\s*mark|thermoplastic", lambda t: "MARK"),
    (r"sign\s*board|signage|road\s*sign", lambda t: "SIGN"), (r"fence|fencing", lambda t: "FENCE"),
    (r"door", lambda t: "DOOR"), (r"window", lambda t: "WIN"), (r"railing|hand\s*rail", lambda t: "RAIL"),
    (r"cable|conductor", lambda t: "CABLE"), (r"earthing|grounding", lambda t: "EARTH"), (r"\btower\b", lambda t: "TWR"),
    (r"survey|setting\s*out", lambda t: "SURV"), (r"mobili[sz]ation", lambda t: "MOB"), (r"insurance", lambda t: "INS"),
    (r"testing|test\b", lambda t: "TEST"), (r"curing", lambda t: "CURE"), (r"scaffold", lambda t: "SCAF"),
]


def item_key(desc):
    t = " " + re.sub(r"\s+", " ", str(desc or "").lower()) + " "
    for rx, fn in ITEM_RULES:
        if re.search(rx, t):
            try:
                k = fn(t)
            except Exception:  # noqa: BLE001
                k = ""
            if k:
                return _clean(k)[:16]
    words = [w for w in re.findall(r"[a-z][a-z0-9]*|\d+(?:\.\d+)?", t) if w not in STOP]
    letters = [w for w in words if not w[0].isdigit()]
    nums = [w for w in words if w[0].isdigit()]
    k = "".join(w[0] for w in letters[:3]).upper() or "ITEM"
    if nums:
        k += "-" + nums[0].replace(".", "")
    return _clean(k)[:16]


def _strip_loc(text, loc_names):
    t = " " + re.sub(r"[^a-z0-9+./ ]", " ", str(text or "").lower()) + " "
    for n in loc_names:
        if not n:
            continue
        for w in sorted({w for w in re.findall(r"[a-z0-9+.]+", str(n).lower()) if len(w) > 1 and w not in STOP}, key=len, reverse=True):
            t = re.sub(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", " ", t)
    t = re.sub(r"\b(at|in|for|of|on)\s*(the\s*)?(location|site|area|portion|section|component)?\s*$", " ", t.strip())
    return re.sub(r"\s+", " ", t).strip(" .,-")


def group_key(desc, unit, loc_names=()):
    return _strip_loc(desc, loc_names) + "|" + norm_unit(unit)


# ───────────────────────────── locations ─────────────────────────────
def _components(c, pid):
    try:
        import api_adv
        api_adv.ensure(c)
        comps = {x["id"]: x for x in q(c, "SELECT * FROM boq_components WHERE project_id=? AND active=1", (pid,))}
        eff = api_adv._comp_of_items(c, pid)
    except Exception:  # noqa: BLE001
        comps, eff = {}, {}
    return comps, eff


def _comp_name(x):
    return re.split(r"\s*\(", str(x.get("name") or ""))[0].strip() or str(x.get("code") or "")


def _unique(want, taken):
    base = want or "LOC"
    k, n = base, 2
    while k.upper() in taken:
        k = "%s%d" % (base, n)
        n += 1
    taken.add(k.upper())
    return k


class Ctx:
    """One project's BOQ lines, locations, items and codes, loaded once. sync() changes these dicts in memory and records
    the writes in self.ops; apply() writes them. A dry run (preview) simply never calls apply(). New rows get negative
    temporary ids until they are written."""

    def __init__(self, c, pid):
        self.c, self.pid = c, pid
        self.items = q(c, "SELECT * FROM boq_items WHERE project_id=? ORDER BY code, id", (pid,))
        self.comps, self.eff = _components(c, pid)
        self.locs = {r["id"]: r for r in q(c, "SELECT * FROM bx_loc WHERE project_id=?", (pid,))}
        self.bxi = {r["id"]: r for r in q(c, "SELECT * FROM bx_item WHERE project_id=?", (pid,))}
        self.lines = {r["boq_item_id"]: r for r in q(c, "SELECT * FROM bx_line WHERE project_id=?", (pid,))}
        self.fmt = fmt_of(c)
        self.ops = []
        self._tmp = 0
        self.reindex()

    def reindex(self):
        self.loc_by_comp = {r["component_id"]: r for r in self.locs.values() if r["component_id"]}
        self.loc_by_text = {str(r["text"]).strip().lower(): r for r in self.locs.values() if r["text"] and not r["component_id"]}

    def tmp(self):
        self._tmp -= 1
        return self._tmp

    def add_comp(self, name):
        """A location component that does not exist yet (import preview)."""
        cid = self.tmp()
        self.comps[cid] = {"id": cid, "project_id": self.pid, "code": "", "name": name, "sort": 999, "active": 1}
        return cid

    def loc_for(self, b):
        cid = b.get("component_id") or self.eff.get(b["id"])
        taken = {str(x["abbr"]).upper() for x in self.locs.values() if x["abbr"]}
        if cid and cid in self.comps:
            r = self.loc_by_comp.get(cid)
            if r:
                return r
            x = self.comps[cid]
            ab = _unique(loc_abbr(_comp_name(x)) or _clean(x.get("code")), taken)
            r = {"id": self.tmp(), "project_id": self.pid, "component_id": cid, "text": None, "abbr": ab, "manual": 0}
        else:
            t = str(b.get("location") or "").strip()
            if not t:
                return None
            r = self.loc_by_text.get(t.lower())
            if r:
                return r
            r = {"id": self.tmp(), "project_id": self.pid, "component_id": None, "text": t, "abbr": _unique(loc_abbr(t), taken), "manual": 0}
        self.locs[r["id"]] = r
        self.ops.append(("ins", "bx_loc", r["id"], r))
        self.reindex()
        return r

    def loc_names(self, loc):
        if not loc:
            return []
        if loc["component_id"] and loc["component_id"] in self.comps:
            x = self.comps[loc["component_id"]]
            return [x.get("name"), _comp_name(x), loc["abbr"]]
        return [loc["text"], loc["abbr"]]

    def loc_label(self, loc):
        if not loc:
            return ""
        if loc["component_id"] and loc["component_id"] in self.comps:
            return _comp_name(self.comps[loc["component_id"]])
        return loc["text"] or ""

    def apply(self):
        c, idmap = self.c, {}
        fix = lambda v: idmap.get(v, v) if isinstance(v, int) and v < 0 else v  # noqa: E731
        for op, table, rid, row in self.ops:
            if op == "ins":
                cols = [k for k in row if k != "id"]
                vals = [fix(row[k]) if k in ("item_id", "loc_id", "component_id") else row[k] for k in cols]
                if table == "bx_line":
                    c.execute("INSERT OR REPLACE INTO bx_line(%s) VALUES(%s)" % (",".join(cols), ",".join("?" * len(cols))), vals)
                else:
                    cur = c.execute("INSERT INTO %s(%s) VALUES(%s)" % (table, ",".join(cols), ",".join("?" * len(cols))), vals)
                    idmap[rid] = cur.lastrowid
            elif op == "upd":
                keycol = "boq_item_id" if table == "bx_line" else "id"
                cols = list(row)
                c.execute("UPDATE %s SET %s WHERE %s=?" % (table, ",".join(k + "=?" for k in cols), keycol),
                          [fix(row[k]) if k in ("item_id", "loc_id") else row[k] for k in cols] + [fix(rid)])
            elif op == "del":
                keycol = "boq_item_id" if table == "bx_line" else "id"
                c.execute("DELETE FROM %s WHERE %s=?" % (table, keycol), (rid,))
        self.ops = []
        return idmap


def compose(fmt, loc_ab, key):
    if not loc_ab:
        return key
    return fmt.replace("{LOC}", loc_ab).replace("{ITEM}", key)


def plan(X, regen=False):
    """Give every BOQ line of the project its item, location and short code (in memory, writes recorded in X.ops).
    Lines whose code or item was set by hand keep them. regen=True also recomputes automatic item keys and location
    abbreviations."""
    pid = X.pid
    alive = {b["id"] for b in X.items}
    for bid in [k for k in X.lines if k not in alive]:
        X.ops.append(("del", "bx_line", bid, None))
        X.lines.pop(bid, None)
    if regen:
        taken = {str(x["abbr"]).upper() for x in X.locs.values() if x["manual"]}
        for r in sorted(X.locs.values(), key=lambda z: z["id"]):
            if r["manual"]:
                continue
            nm = _comp_name(X.comps[r["component_id"]]) if r["component_id"] in X.comps else r["text"]
            ab = _unique(loc_abbr(nm), taken)
            if ab != r["abbr"]:
                X.ops.append(("upd", "bx_loc", r["id"], {"abbr": ab}))
                r["abbr"] = ab
    by_gkey = {r["gkey"]: r for r in X.bxi.values() if r["gkey"]}
    keys_taken = {str(r["key"]).upper(): r["id"] for r in X.bxi.values() if r["key"]}
    changed = {"lines_new": 0, "codes_changed": 0, "items_new": 0}
    want = {}
    for b in X.items:
        loc = X.loc_for(b)
        ln = X.lines.get(b["id"])
        gk = group_key(b["description"], b["unit"], X.loc_names(loc))
        item_id = ln["item_id"] if ln and ln["item_manual"] and ln["item_id"] in X.bxi else None
        if not item_id:
            it = by_gkey.get(gk)
            if not it:
                k = item_key(_strip_loc(b["description"], X.loc_names(loc)) or b["description"])
                kk, n = k, 2
                while kk.upper() in keys_taken:
                    kk = "%s-%d" % (k, n)
                    n += 1
                it = {"id": X.tmp(), "project_id": pid, "key": kk, "gkey": gk, "title": b["description"], "unit": b["unit"], "manual": 0,
                      "stated_qty": None, "stated_note": None, "ts": core.today()}
                X.bxi[it["id"]] = it
                X.ops.append(("ins", "bx_item", it["id"], it))
                by_gkey[gk] = it
                keys_taken[kk.upper()] = it["id"]
                changed["items_new"] += 1
            item_id = it["id"]
        want[b["id"]] = (item_id, loc["id"] if loc else None)
    if regen:
        taken = {k: v for k, v in keys_taken.items() if X.bxi.get(v, {}).get("manual")}
        used_items = {v[0] for v in want.values()}
        for it in sorted(X.bxi.values(), key=lambda z: (z["id"] < 0, abs(z["id"]))):
            if it["manual"] or it["id"] not in used_items:
                continue
            k = item_key(it["gkey"].split("|")[0] if it["gkey"] else it["title"])
            kk, n = k, 2
            while kk.upper() in taken:
                kk = "%s-%d" % (k, n)
                n += 1
            taken[kk.upper()] = it["id"]
            if kk != it["key"]:
                X.ops.append(("upd", "bx_item", it["id"], {"key": kk}))
                it["key"] = kk
    codes = {}
    for b in X.items:
        ln = X.lines.get(b["id"])
        if ln and ln["manual"] and ln["short_code"]:
            codes[str(ln["short_code"]).upper()] = b["id"]
    for b in X.items:
        item_id, loc_id = want[b["id"]]
        ln = X.lines.get(b["id"])
        if ln and ln["manual"] and ln["short_code"]:
            sc = ln["short_code"]
        else:
            base = compose(X.fmt, X.locs[loc_id]["abbr"] if loc_id else "", X.bxi[item_id]["key"])
            sc, n = base, 2
            while sc.upper() in codes and codes[sc.upper()] != b["id"]:
                sc = "%s/%d" % (base, n)
                n += 1
            codes[sc.upper()] = b["id"]
        if not ln:
            row = {"boq_item_id": b["id"], "project_id": pid, "item_id": item_id, "loc_id": loc_id, "short_code": sc, "manual": 0,
                   "item_manual": 0, "role": "line", "ts": core.today()}
            X.lines[b["id"]] = row
            X.ops.append(("ins", "bx_line", b["id"], row))
            changed["lines_new"] += 1
        elif (ln["item_id"], ln["loc_id"], ln["short_code"]) != (item_id, loc_id, sc):
            if ln["short_code"] != sc:
                changed["codes_changed"] += 1
            ch = {"item_id": item_id, "loc_id": loc_id, "short_code": sc, "ts": core.today()}
            ln.update(ch)
            X.ops.append(("upd", "bx_line", b["id"], ch))
    used = {v[0] for v in want.values()}
    for it in list(X.bxi.values()):
        if it["id"] not in used and not it["manual"] and it.get("stated_qty") is None:
            X.ops.append(("del", "bx_item", it["id"], None))
            X.bxi.pop(it["id"])
    return changed


def sync(c, pid, regen=False):
    X = Ctx(c, int(pid))
    r = plan(X, regen)
    X.apply()
    return r


def _projects(c):
    return [r["id"] for r in q(c, "SELECT id FROM projects WHERE COALESCE(kind,'') NOT IN ('trading','general') ORDER BY id")]


def _pid(a):
    if not a.get("project_id"):
        raise ApiError("Choose a project first.")
    return int(a["project_id"])


# ───────────────────────────── settings ─────────────────────────────
@api("bx.settings", "commercial", "view")
def bx_settings(c, u, a):
    return {"on": on(c), "format": fmt_of(c), "formats": [{"value": k, "example": v} for k, v in FORMATS.items()],
            "can_change": core.can(u, "commercial", "approve"), "can_edit": core.can(u, "commercial", "edit"), "version": VERSION}


@api("bx.settings_save", "commercial", "approve")
def bx_settings_save(c, u, a):
    was, was_fmt = on(c), fmt_of(c)
    want = (a.get("on") in (1, True, "1", "true")) if "on" in a else was
    f = a.get("format") or was_fmt
    if f not in FORMATS:
        raise ApiError("Unknown short code format.")
    _set(c, "bx_on", "1" if want else "0")
    _set(c, "bx_format", f)
    res = {"projects": 0, "lines_new": 0, "codes_changed": 0}
    if want and (not was or f != was_fmt):
        for pid in _projects(c):
            r = sync(c, pid)
            res["projects"] += 1
            res["lines_new"] += r["lines_new"]
            res["codes_changed"] += r["codes_changed"]
    core.audit(c, u, "settings", "bx_on", 0, {"on": want, "format": f})
    _log(c, u, None, "settings", {"on": want, "format": f})
    out = bx_settings(c, u, {})
    out["built"] = res
    return out


# ───────────────────────────── reading ─────────────────────────────
def _need_on(c):
    if not on(c):
        raise ApiError("BOQ short codes are off for this company. Turn them on in BOQ > Short codes (needs Commercial approve).")


def _lines(c, pid, X=None):
    X = X or Ctx(c, pid)
    out = []
    for b in X.items:
        ln = X.lines.get(b["id"]) or {}
        loc = X.locs.get(ln.get("loc_id")) if ln else None
        it = X.bxi.get(ln.get("item_id")) if ln else None
        out.append({"boq_item_id": b["id"], "code": b["code"], "description": b["description"], "unit": b["unit"],
                    "qty": r4(_f(b["revised_qty"] if b.get("revised_qty") is not None else b["qty"])),
                    "rate": _f(b["revised_rate"] if b.get("revised_rate") is not None else b["rate"]),
                    "contract_qty": r4(_f(b["qty"])), "contract_rate": _f(b["rate"]),
                    "location": X.loc_label(loc) if loc else "", "loc_id": loc["id"] if loc else None, "loc_abbr": loc["abbr"] if loc else "",
                    "item_id": it["id"] if it else None, "item_key": it["key"] if it else "", "short_code": ln.get("short_code") or "",
                    "manual": bool(ln.get("manual")), "item_manual": bool(ln.get("item_manual")), "role": ln.get("role") or "line",
                    "executed_qty": r4(_f(b.get("executed_qty"))), "new": b["id"] < 0})
    for r in out:
        r["amount"] = r2(r["qty"] * r["rate"])
    return out, X


@api("bx.lines", "commercial", "view")
def bx_lines(c, u, a):
    pid = _pid(a)
    if on(c):
        sync(c, pid)
    rows, X = _lines(c, pid)
    locs = sorted(X.locs.values(), key=lambda r: ((X.comps.get(r["component_id"]) or {}).get("sort") or 0, r["id"]))
    return {"on": on(c), "rows": rows, "format": X.fmt,
            "locations": [{"id": r["id"], "abbr": r["abbr"], "name": X.loc_label(r), "component_id": r["component_id"], "manual": bool(r["manual"]),
                           "lines": sum(1 for x in rows if x["loc_id"] == r["id"])} for r in locs],
            "items": [{"id": i["id"], "key": i["key"], "title": i["title"], "unit": i["unit"], "manual": bool(i["manual"])} for i in X.bxi.values()]}


SUMS = ["qty", "contract_qty", "amount", "executed_qty", "measured_qty", "billed_qty", "certified_qty", "balance_qty", "earned_revenue", "ac", "eac",
        "forecast_revenue", "forecast_profit"]


def summary(c, u, pid, X=None):
    rows, X = _lines(c, pid, X)
    fig = {}
    try:
        for r in inv.FUNCS["boq.control"][0](c, u, {"project_id": pid}):
            fig[r["id"]] = r
    except Exception:  # noqa: BLE001
        fig = {}
    items = {}
    loc_order = []
    for r in rows:
        f = fig.get(r["boq_item_id"], {})
        for k in ("measured_qty", "billed_qty", "certified_qty", "balance_qty", "earned_revenue", "ac", "eac", "forecast_revenue", "forecast_profit"):
            r[k] = f.get(k) if f.get(k) is not None else (r4(r["qty"] - r["executed_qty"]) if k == "balance_qty" else 0)
        key = r["item_id"] or ("b%d" % r["boq_item_id"])
        it = X.bxi.get(r["item_id"]) or {}
        g = items.setdefault(key, {"item_id": r["item_id"], "key": it.get("key") or r["code"], "title": it.get("title") or r["description"],
                                   "unit": norm_unit(r["unit"]) or r["unit"], "lines": [], "by_loc": {}, "rates": set(), "overall_lines": [],
                                   "stated_qty": it.get("stated_qty"), "stated_note": it.get("stated_note")})
        if r["role"] == "overall":
            g["overall_lines"].append(r)
            continue
        g["lines"].append(r)
        g["rates"].add(round(r["rate"], 2))
        lk = r["loc_abbr"] or "—"
        if lk not in loc_order:
            loc_order.append(lk)
        g["by_loc"][lk] = r4(g["by_loc"].get(lk, 0) + r["qty"])
        g.setdefault("amt_loc", {})[lk] = r2(g.get("amt_loc", {}).get(lk, 0) + r["amount"])
    out = []
    for g in items.values():
        s = {k: r4(sum(_f(x.get(k)) for x in g["lines"])) for k in SUMS}
        for k in ("amount", "earned_revenue", "ac", "eac", "forecast_revenue", "forecast_profit"):
            s[k] = r2(s[k])
        stated = g["stated_qty"]
        if stated is None and g["overall_lines"]:
            stated = r4(sum(x["qty"] for x in g["overall_lines"]))
        rates = sorted(g["rates"])
        row = {"item_id": g["item_id"], "key": g["key"], "title": g["title"], "unit": g["unit"], "locations": len([k for k in g["by_loc"] if k != "—"]),
               "lines": len(g["lines"]), "by_loc": g["by_loc"], "amt_loc": g.get("amt_loc", {}), "codes": [x["short_code"] for x in g["lines"]],
               "boq_item_ids": [x["boq_item_id"] for x in g["lines"]], "rate": rates[0] if len(rates) == 1 else None,
               "avg_rate": r2(s["amount"] / s["qty"]) if s["qty"] else None, "rates_differ": len(rates) > 1, "rate_min": rates[0] if rates else None,
               "rate_max": rates[-1] if rates else None, "stated_qty": stated, "overall_codes": [x["short_code"] for x in g["overall_lines"]],
               "progress_pct": round(100 * s["executed_qty"] / s["qty"], 1) if s["qty"] else 0}
        row.update(s)
        row["stated_diff"] = r4(stated - s["qty"]) if stated is not None else None
        out.append(row)
    out.sort(key=lambda r: (r["key"] or ""))
    tot = {k: r2(sum(_f(r[k]) for r in out)) for k in ("amount", "earned_revenue", "ac", "eac", "forecast_revenue", "forecast_profit")}
    loc_names = {}
    for r in rows:
        if r["loc_abbr"]:
            loc_names[r["loc_abbr"]] = r["location"]
    loc_amt = {}
    for r in rows:
        if r["role"] != "overall":
            lk = r["loc_abbr"] or "—"
            loc_amt[lk] = r2(loc_amt.get(lk, 0) + r["amount"])
    return {"rows": out, "totals": tot, "locations": [{"abbr": k, "name": loc_names.get(k, "No location"), "amount": loc_amt.get(k, 0)} for k in loc_order],
            "lines": len(rows), "items": len(out)}


@api("bx.summary", "commercial", "view")
def bx_summary(c, u, a):
    pid = _pid(a)
    if on(c):
        sync(c, pid)
    d = summary(c, u, pid)
    d["on"] = on(c)
    d["checks"] = checks(c, u, pid, d)
    return d


def checks(c, u, pid, d=None):
    d = d or summary(c, u, pid)
    rows, X = _lines(c, pid)
    out = []
    by_item = {}
    for r in rows:
        by_item.setdefault(r["item_id"], []).append(r)
    for g in d["rows"]:
        lines = by_item.get(g["item_id"], [])
        located = [x for x in lines if x["loc_id"] and x["role"] != "overall"]
        bare = [x for x in lines if not x["loc_id"] and x["role"] != "overall"]
        if located and bare:
            loc_sum = r4(sum(x["qty"] for x in located))
            for x in bare:
                same = abs(x["qty"] - loc_sum) <= max(0.005 * loc_sum, EPS)
                out.append({"kind": "double" if same else "overall_and_locations", "severity": "red" if same else "amber", "item": g["key"],
                            "boq_item_id": x["boq_item_id"], "short_code": x["short_code"],
                            "text": ("%s %s has an overall line of %s %s and location lines adding up to the same %s: the quantity is counted twice. "
                                     "Mark the overall line 'overall' (summary only) or delete it." if same else
                                     "%s %s has a line with no location (%s %s) beside location lines adding up to %s. Check whether it is an extra "
                                     "quantity or the overall figure.") % (g["key"], x["code"] or "", fmt_q(x["qty"]), x["unit"] or "", fmt_q(loc_sum))})
        if g["stated_diff"] is not None and abs(g["stated_diff"]) > max(0.005 * abs(g["stated_qty"] or 0), EPS):
            out.append({"kind": "stated", "severity": "amber", "item": g["key"], "item_id": g["item_id"], "boq_item_id": None, "short_code": "",
                        "text": "%s: the overall quantity stated in the BOQ is %s but the location lines add up to %s (difference %s %s)."
                                % (g["key"], fmt_q(g["stated_qty"]), fmt_q(g["qty"]), fmt_q(g["stated_diff"]), g["unit"])})
        if g["rates_differ"]:
            out.append({"kind": "rates", "severity": "info", "item": g["key"], "boq_item_id": None, "short_code": "",
                        "text": "%s is priced differently by location (%s to %s); the summary shows the weighted average %s."
                                % (g["key"], fmt_q(g["rate_min"]), fmt_q(g["rate_max"]), fmt_q(g["avg_rate"]))})
    for r in rows:
        if r["role"] == "overall":
            refs = _refs(c, r["boq_item_id"])
            if refs:
                out.append({"kind": "overall_used", "severity": "amber", "item": r["item_key"], "boq_item_id": r["boq_item_id"], "short_code": r["short_code"],
                            "text": "Overall line %s is used in %s. Record new work against the location lines." % (r["short_code"], ", ".join(refs))})
    if any(not r["short_code"] for r in rows) and on(c):
        out.append({"kind": "missing", "severity": "amber", "item": "", "boq_item_id": None, "short_code": "", "text": "Some lines have no short code yet."})
    return out


def fmt_q(x):
    x = _f(x)
    return ("{:,.3f}".format(x)).rstrip("0").rstrip(".")


REF_TABLES = [("dpr_work", "DPRs"), ("mrq_lines", "requisitions"), ("pr_lines", "purchase requests"), ("issue_lines", "material issues"),
              ("measurement_lines", "measurements"), ("ipc_lines", "IPCs"), ("voucher_lines", "postings"), ("activities", "activities"),
              ("variations", "variations"), ("invoice_lines", "invoices")]


def _refs(c, bid):
    out = []
    for t, label in REF_TABLES:
        try:
            if val(c, "SELECT COUNT(*) FROM %s WHERE boq_item_id=?" % t, (bid,)):
                out.append(label)
        except Exception:  # noqa: BLE001
            pass
    return out


@api("bx.checks", "commercial", "view")
def bx_checks(c, u, a):
    pid = _pid(a)
    if on(c):
        sync(c, pid)
    return {"rows": checks(c, u, pid)}


@api("bx.resolve", "commercial", "view")
def bx_resolve(c, u, a):
    """Short code or BOQ code -> the BOQ line of the project."""
    pid = _pid(a)
    code = str(a.get("code") or "").strip()
    if not code:
        raise ApiError("Type a short code or BOQ code.")
    r = q1(c, "SELECT b.id, b.code, b.description, b.unit, l.short_code FROM bx_line l JOIN boq_items b ON b.id=l.boq_item_id "
              "WHERE l.project_id=? AND upper(l.short_code)=upper(?)", (pid, code))
    if not r:
        r = q1(c, "SELECT b.id, b.code, b.description, b.unit, l.short_code FROM boq_items b LEFT JOIN bx_line l ON l.boq_item_id=b.id "
                  "WHERE b.project_id=? AND upper(b.code)=upper(?)", (pid, code))
    if not r:
        raise ApiError("No BOQ line %s in this project." % code)
    return r


def resolve_id(c, pid, code):
    try:
        return bx_resolve(c, None, {"project_id": pid, "code": code})["id"]
    except ApiError:
        return None


# ───────────────────────────── editing ─────────────────────────────
def _line(c, bid):
    b = q1(c, "SELECT * FROM boq_items WHERE id=?", (int(bid),))
    if not b:
        raise ApiError("BOQ line not found.")
    return b


@api("bx.line_save", "commercial", "edit")
def bx_line_save(c, u, a):
    """short_code (typed -> kept), auto=1 (back to the automatic code), item_id / new_item_key (file under another item),
    role 'line' | 'overall'."""
    _need_on(c)
    b = _line(c, a.get("boq_item_id"))
    pid = b["project_id"]
    sync(c, pid)
    ln = q1(c, "SELECT * FROM bx_line WHERE boq_item_id=?", (b["id"],))
    ch = {}
    if a.get("short_code") not in (None, ""):
        sc = str(a["short_code"]).strip()
        if not CODE_RE.match(sc):
            raise ApiError("A short code is 1 to 24 letters, digits or - _ . / + and starts with a letter or digit.")
        dup = q1(c, "SELECT boq_item_id FROM bx_line WHERE project_id=? AND upper(short_code)=upper(?) AND boq_item_id<>?", (pid, sc, b["id"]))
        if dup:
            raise ApiError("Short code %s is already used in this project." % sc)
        dupc = q1(c, "SELECT id FROM boq_items WHERE project_id=? AND upper(code)=upper(?) AND id<>?", (pid, sc, b["id"]))
        if dupc:
            raise ApiError("%s is the BOQ code of another line; choose another short code." % sc)
        ch.update({"short_code": sc, "manual": 1})
    if a.get("auto") in (1, True, "1", "true"):
        ch.update({"manual": 0})
    if a.get("new_item_key"):
        key = _clean(a["new_item_key"])
        if not key:
            raise ApiError("Type an item key.")
        if val(c, "SELECT COUNT(*) FROM bx_item WHERE project_id=? AND upper(key)=upper(?)", (pid, key)):
            raise ApiError("Item %s already exists; choose it from the list." % key)
        iid = core.ins(c, "bx_item", {"project_id": pid, "key": key, "gkey": None, "title": b["description"], "unit": b["unit"], "manual": 1, "ts": core.today()})
        ch.update({"item_id": iid, "item_manual": 1})
    elif a.get("item_id") not in (None, ""):
        it = q1(c, "SELECT * FROM bx_item WHERE id=? AND project_id=?", (int(a["item_id"]), pid))
        if not it:
            raise ApiError("Unknown item.")
        if norm_unit(it["unit"]) != norm_unit(b["unit"]):
            raise ApiError("Item %s is measured in %s; this line is in %s. Only lines with the same unit can be summed." % (it["key"], it["unit"], b["unit"]))
        ch.update({"item_id": it["id"], "item_manual": 1})
    elif a.get("item_auto") in (1, True, "1", "true"):
        ch.update({"item_manual": 0})
    if a.get("role") in ("line", "overall"):
        ch["role"] = a["role"]
    if not ch:
        raise ApiError("Nothing to change.")
    sets = ", ".join("%s=?" % k for k in ch)
    c.execute("UPDATE bx_line SET %s, ts=? WHERE boq_item_id=?" % sets, list(ch.values()) + [core.today(), b["id"]])
    sync(c, pid)
    _log(c, u, pid, "line", {"boq_item_id": b["id"], "before": dict(ln or {}), "change": ch})
    core.audit(c, u, "bx_line", "boq_items", b["id"], ch)
    return q1(c, "SELECT * FROM bx_line WHERE boq_item_id=?", (b["id"],))


@api("bx.item_save", "commercial", "edit")
def bx_item_save(c, u, a):
    _need_on(c)
    it = q1(c, "SELECT * FROM bx_item WHERE id=?", (int(a.get("id") or 0),))
    if not it:
        raise ApiError("Unknown item.")
    ch = {}
    if a.get("key") not in (None, ""):
        key = _clean(a["key"])
        if not key or len(key) > 16:
            raise ApiError("An item key is 1 to 16 letters or digits (e.g. M25, PCC-M10, RBAR).")
        if val(c, "SELECT COUNT(*) FROM bx_item WHERE project_id=? AND upper(key)=upper(?) AND id<>?", (it["project_id"], key, it["id"])):
            raise ApiError("Item key %s is already used in this project." % key)
        ch.update({"key": key, "manual": 1})
    if "title" in a and a.get("title"):
        ch["title"] = str(a["title"])[:500]
    if "stated_qty" in a:
        ch["stated_qty"] = None if a.get("stated_qty") in (None, "") else _f(a["stated_qty"])
    if a.get("auto") in (1, True, "1", "true"):
        ch["manual"] = 0
    if not ch:
        raise ApiError("Nothing to change.")
    c.execute("UPDATE bx_item SET %s WHERE id=?" % ", ".join("%s=?" % k for k in ch), list(ch.values()) + [it["id"]])
    sync(c, it["project_id"], regen=bool(ch.get("manual") == 0))
    _log(c, u, it["project_id"], "item", {"id": it["id"], "before": dict(it), "change": ch})
    return q1(c, "SELECT * FROM bx_item WHERE id=?", (it["id"],))


@api("bx.loc_save", "commercial", "edit")
def bx_loc_save(c, u, a):
    _need_on(c)
    r = q1(c, "SELECT * FROM bx_loc WHERE id=?", (int(a.get("id") or 0),))
    if not r:
        raise ApiError("Unknown location.")
    ch = {}
    if a.get("abbr") not in (None, ""):
        ab = _clean(a["abbr"])
        if not ab or len(ab) > 12:
            raise ApiError("A location abbreviation is 1 to 12 letters or digits (e.g. HW, SB, PH, CH0-1.5).")
        if val(c, "SELECT COUNT(*) FROM bx_loc WHERE project_id=? AND upper(abbr)=upper(?) AND id<>?", (r["project_id"], ab, r["id"])):
            raise ApiError("Abbreviation %s is already used in this project." % ab)
        ch.update({"abbr": ab, "manual": 1})
    if a.get("auto") in (1, True, "1", "true"):
        ch["manual"] = 0
    if not ch:
        raise ApiError("Nothing to change.")
    c.execute("UPDATE bx_loc SET %s WHERE id=?" % ", ".join("%s=?" % k for k in ch), list(ch.values()) + [r["id"]])
    sync(c, r["project_id"], regen=bool(ch.get("manual") == 0))
    _log(c, u, r["project_id"], "location", {"id": r["id"], "before": dict(r), "change": ch})
    return q1(c, "SELECT * FROM bx_loc WHERE id=?", (r["id"],))


@api("bx.build", "commercial", "edit")
def bx_build(c, u, a):
    """Build codes for a project. mode 'missing' (default) only fills gaps; 'auto' recomputes every automatic item key,
    abbreviation and code (typed ones stay). files=1 also files lines whose location column names a location under a
    location component (a new component is made for a name not yet known) - the same as BOQ > Components does by hand."""
    _need_on(c)
    pid = _pid(a)
    made = filed = 0
    if a.get("files") in (1, True, "1", "true"):
        made, filed = file_locations(c, pid)
    r = sync(c, pid, regen=a.get("mode") == "auto")
    r.update({"components_made": made, "lines_filed": filed})
    _log(c, u, pid, "build", r)
    return r


def file_locations(c, pid):
    import api_adv
    api_adv.ensure(c)
    comps = q(c, "SELECT * FROM boq_components WHERE project_id=? AND active=1", (pid,))
    by = {}
    for x in comps:
        for k in (x["name"], _comp_name(x), x["code"]):
            if k:
                by.setdefault(str(k).strip().lower(), x["id"])
    made = filed = 0
    eff = api_adv._comp_of_items(c, pid)
    for b in q(c, "SELECT id, location, component_id FROM boq_items WHERE project_id=? AND COALESCE(location,'')<>''", (pid,)):
        if b["component_id"] or eff.get(b["id"]):
            continue
        t = str(b["location"]).strip()
        cid = by.get(t.lower())
        if not cid:
            cid = core.ins(c, "boq_components", {"project_id": pid, "code": "", "name": t, "sort": 100 + len(by), "active": 1})
            by[t.lower()] = cid
            made += 1
        c.execute("UPDATE boq_items SET component_id=? WHERE id=? AND component_id IS NULL", (cid, b["id"]))
        filed += 1
    return made, filed


@api("bx.preview", "commercial", "view")
def bx_preview(c, u, a):
    """What 'Turn on' / 'Build codes' would give a project, without writing anything."""
    pid = _pid(a)
    X = Ctx(c, pid)
    plan(X, regen=a.get("mode") == "auto")
    rows, X = _lines(c, pid, X)
    return {"rows": rows, "summary": summary(c, u, pid, X)}


# ───────────────────────────── import with locations ─────────────────────────────
def _parse(rows, headings):
    out, cur = [], ""
    for i, r in enumerate(rows):
        g = lambda k: str(r.get(k) if r.get(k) is not None else "").strip()  # noqa: E731
        desc, unit, qty, rate, loc = g("description"), g("unit"), g("qty"), g("rate"), g("location")
        code = g("code")
        if not (desc or code):
            continue
        if headings and desc and not unit and _f(qty.replace(",", "")) == 0 and _f(rate.replace(",", "")) == 0 and not loc:
            cur = desc.rstrip(":").strip()
            if cur.isupper() and len(cur) > 3:
                cur = " ".join(w if (len(w) <= 3 and w.isalpha() and w not in ("AND", "THE", "FOR")) or any(ch.isdigit() for ch in w) else w.capitalize() for w in cur.split())
            out.append({"row": i + 1, "heading": True, "location": cur})
            continue
        if not loc:
            loc = cur
        out.append({"row": i + 1, "heading": False, "code": code, "description": desc, "unit": unit, "qty": _f(qty.replace(",", "")),
                    "rate": _f(rate.replace(",", "")), "location": loc, "short_code": g("short_code")})
    return out


def _known_locations(c, pid):
    import api_adv
    api_adv.ensure(c)
    comps = q(c, "SELECT * FROM boq_components WHERE project_id=? AND active=1", (pid,))
    known = {}
    for x in comps:
        for k in (x["name"], _comp_name(x), x["code"]):
            if k:
                known.setdefault(str(k).strip().lower(), x)
    for l in q(c, "SELECT * FROM bx_loc WHERE project_id=? AND component_id IS NOT NULL", (pid,)):
        x = next((y for y in comps if y["id"] == l["component_id"]), None)
        if x and l["abbr"]:
            known.setdefault(l["abbr"].lower(), x)
    return known


@api("bx.import", "commercial", "edit")
def bx_import(c, u, a):
    """rows: [{code, description, unit, qty, rate, location, short_code}]. headings=1: a row with a description only (no unit,
    quantity, rate or location) is a location heading for the rows under it. skip_overall=1 (default): a row with no location
    whose item also has location rows in the same paste is the overall figure - it is not added as a BOQ line; its quantity
    is kept as the item's stated total and checked against the locations. apply=0 previews without writing."""
    _need_on(c)
    pid = _pid(a)
    headings = a.get("headings", 1) in (1, True, "1", "true")
    skip_overall = a.get("skip_overall", 1) in (1, True, "1", "true")
    parsed = _parse(a.get("rows") or [], headings)
    lines = [x for x in parsed if not x["heading"]]
    if not lines:
        raise ApiError("No BOQ rows found. Paste rows with at least a description, unit and quantity.")
    errors = []
    known = _known_locations(c, pid)
    groups = {}
    for x in lines:
        if not x["description"]:
            errors.append("Row %d: description is missing." % x["row"])
        if x["qty"] < 0:
            errors.append("Row %d: quantity cannot be negative." % x["row"])
        if x["short_code"] and not CODE_RE.match(x["short_code"]):
            errors.append("Row %d: short code %s is not valid." % (x["row"], x["short_code"]))
        x["gkey"] = group_key(x["description"], x["unit"], [x["location"]] if x["location"] else [])
        groups.setdefault(x["gkey"], []).append(x)
    existing_codes = {str(r["code"]).upper() for r in q(c, "SELECT code FROM boq_items WHERE project_id=? AND code IS NOT NULL", (pid,))}
    seen, seen_sc = set(), set()
    for x in lines:
        if x["code"]:
            if x["code"].upper() in existing_codes:
                errors.append("Row %d: BOQ code %s already exists in this project." % (x["row"], x["code"]))
            if x["code"].upper() in seen:
                errors.append("Row %d: BOQ code %s appears twice." % (x["row"], x["code"]))
            seen.add(x["code"].upper())
        if x["short_code"]:
            if x["short_code"].upper() in seen_sc or val(c, "SELECT COUNT(*) FROM bx_line WHERE project_id=? AND upper(short_code)=upper(?)", (pid, x["short_code"])):
                errors.append("Row %d: short code %s is already used." % (x["row"], x["short_code"]))
            seen_sc.add(x["short_code"].upper())
    stated = {}
    for gk, xs in groups.items():
        located = [x for x in xs if x["location"]]
        bare = [x for x in xs if not x["location"]]
        for x in xs:
            x["action"] = "add"
        if skip_overall and located and bare:
            tot = r4(sum(x["qty"] for x in located))
            for x in bare:
                x["action"] = "overall"
                same = abs(x["qty"] - tot) <= max(0.005 * tot, EPS)
                x["note"] = "overall figure %s; the locations add up to %s%s" % (fmt_q(x["qty"]), fmt_q(tot), "" if same else " - CHECK")
            stated[gk] = r4(sum(x["qty"] for x in bare))
    adds = [x for x in lines if x["action"] == "add"]
    new_locs = []
    for x in adds:
        if x["location"] and x["location"].strip().lower() not in known and x["location"] not in new_locs:
            new_locs.append(x["location"])
    out = {"errors": errors, "new_locations": new_locs, "adds": len(adds), "overall": len(lines) - len(adds)}
    if not a.get("apply"):
        X = Ctx(c, pid)
        fake = {}
        nb = val(c, "SELECT COUNT(*) FROM boq_items WHERE project_id=?", (pid,))
        for x in adds:
            comp = known.get(x["location"].strip().lower()) if x["location"] else None
            cid = comp["id"] if comp else None
            if x["location"] and not comp:
                cid = fake.get(x["location"].strip().lower()) or X.add_comp(x["location"].strip())
                fake[x["location"].strip().lower()] = cid
            nb += 1
            x["_id"] = X.tmp()
            X.items.append({"id": x["_id"], "project_id": pid, "code": x["code"] or "BX-%03d" % nb, "description": x["description"], "unit": x["unit"],
                            "qty": x["qty"], "rate": x["rate"], "revised_qty": None, "revised_rate": None, "executed_qty": 0,
                            "component_id": cid, "location": x["location"]})
            if x["short_code"]:
                X.lines[x["_id"]] = {"boq_item_id": x["_id"], "project_id": pid, "item_id": None, "loc_id": None, "short_code": x["short_code"],
                                     "manual": 1, "item_manual": 0, "role": "line"}
        X.items.sort(key=lambda b: (str(b["code"] or ""), b["id"] if b["id"] > 0 else 10 ** 12 - b["id"]))
        plan(X)
        for gk, qty in stated.items():
            xs = [y for y in adds if y["gkey"] == gk]
            if xs:
                it = X.bxi.get(X.lines[xs[0]["_id"]]["item_id"])
                if it:
                    it["stated_qty"] = qty
        rows, X = _lines(c, pid, X)
        sc = {r["boq_item_id"]: r for r in rows}
        for x in adds:
            r = sc.get(x["_id"]) or {}
            x["proposed_code"] = r.get("short_code", "")
            x["item_key"] = r.get("item_key", "")
            x["loc_abbr"] = r.get("loc_abbr", "")
        out["rows"] = [{k: v for k, v in x.items() if k not in ("gkey", "_id")} for x in parsed]
        out["summary"] = summary(c, u, pid, X)
        return out
    if errors:
        raise ApiError("Nothing imported: " + "; ".join(errors[:5]) + (" ..." if len(errors) > 5 else ""))
    res = _do_import(c, u, pid, adds, known, stated)
    _log(c, u, pid, "import", {"added": len(res["ids"]), "components": res["components"], "overall": out["overall"]})
    return {"added": len(res["ids"]), "components_made": res["components"], "overall": out["overall"], "ids": res["ids"]}


def _do_import(c, u, pid, adds, known, stated):
    save = inv.FUNCS["master.save"][0]
    if getattr(save, FLAG, False):
        save = save._orig          # one sync at the end instead of one per line
    made = 0
    ids = []
    n = val(c, "SELECT COUNT(*) FROM boq_items WHERE project_id=?", (pid,))
    for x in adds:
        comp = None
        if x["location"]:
            comp = known.get(x["location"].strip().lower())
            if not comp:
                srt = val(c, "SELECT COALESCE(MAX(sort),0) FROM boq_components WHERE project_id=?", (pid,)) or 0
                cid = core.ins(c, "boq_components", {"project_id": pid, "code": "", "name": x["location"].strip(), "sort": int(srt) + 1, "active": 1})
                comp = {"id": cid, "name": x["location"].strip(), "code": ""}
                known[x["location"].strip().lower()] = comp
                made += 1
        n += 1
        row = {"project_id": pid, "code": x["code"] or "BX-%03d" % n, "description": x["description"], "unit": x["unit"], "qty": x["qty"], "rate": x["rate"]}
        if comp:
            row["component_id"] = comp["id"]
            row["location"] = _comp_name(comp)
        b = save(c, u, {"table": "boq_items", "row": row})
        ids.append(b["id"])
        if x["short_code"]:
            c.execute("INSERT OR REPLACE INTO bx_line(boq_item_id, project_id, short_code, manual, item_manual, role, ts) VALUES(?,?,?,1,0,'line',?)",
                      (b["id"], pid, x["short_code"], core.today()))
    sync(c, pid)
    for gk, qty in stated.items():
        xs = [i for i, y in zip(ids, adds) if y["gkey"] == gk]
        if xs:
            iid = val(c, "SELECT item_id FROM bx_line WHERE boq_item_id=?", (xs[0],), None)
            if iid:
                c.execute("UPDATE bx_item SET stated_qty=?, stated_note='from import' WHERE id=?", (qty, iid))
    return {"ids": ids, "components": made}


# ───────────────────────────── standard locations per kind of project ─────────────────────────────
PRESETS = {
    "hydro": ("Hydropower", [("HW", "Headworks"), ("SB", "Settling basin"), ("HRT", "Headrace tunnel"), ("ST", "Surge tank"), ("PS", "Penstock"),
                             ("PH", "Powerhouse"), ("TR", "Tailrace"), ("SY", "Switchyard"), ("HM", "Hydro-mechanical works"), ("EM", "Electro-mechanical works"),
                             ("TL", "Transmission line"), ("AR", "Access road & camp")]),
    "road": ("Road", [("CH0-5", "Ch 0+000 - 5+000"), ("CH5-10", "Ch 5+000 - 10+000"), ("STR", "Structures (bridges, culverts, walls)"), ("DRN", "Drainage"),
                      ("RF", "Road furniture & safety")]),
    "building": ("Building", [("SUB", "Substructure"), ("B1", "Basement 1"), ("GF", "Ground floor"), ("F1", "First floor"), ("F2", "Second floor"),
                              ("RF", "Roof"), ("MEP", "Services (MEP)"), ("EXT", "External works")]),
    "bridge": ("Bridge", [("A1", "Abutment A1"), ("P1", "Pier P1"), ("P2", "Pier P2"), ("A2", "Abutment A2"), ("SUP", "Superstructure"),
                          ("APR", "Approach roads"), ("RT", "River training")]),
    "irrigation": ("Irrigation / water", [("HW", "Headworks"), ("MC", "Main canal"), ("BC", "Branch canals"), ("CD", "Cross-drainage structures"),
                                         ("DY", "Distributaries"), ("RES", "Reservoir / tanks")]),
    "line": ("Transmission line / substation", [("TWR", "Tower foundations"), ("ERC", "Tower erection"), ("STR", "Stringing"), ("SS", "Substation")]),
}


@api("bx.presets", "commercial", "view")
def bx_presets(c, u, a):
    return {"presets": [{"key": k, "label": v[0], "locations": [{"abbr": x, "name": n} for x, n in v[1]]} for k, v in PRESETS.items()]}


@api("bx.loc_setup", "commercial", "edit")
def bx_loc_setup(c, u, a):
    """Add a set of standard locations (as BOQ components) with their abbreviations. Existing names are kept."""
    _need_on(c)
    pid = _pid(a)
    p = PRESETS.get(a.get("preset"))
    if not p:
        raise ApiError("Unknown kind of project.")
    import api_adv
    api_adv.ensure(c)
    have = {str(x["name"]).strip().lower() for x in q(c, "SELECT name FROM boq_components WHERE project_id=? AND active=1", (pid,))}
    abbrs = {str(x["abbr"]).upper() for x in q(c, "SELECT abbr FROM bx_loc WHERE project_id=?", (pid,)) if x["abbr"]}
    made = 0
    base = val(c, "SELECT COALESCE(MAX(sort),0) FROM boq_components WHERE project_id=?", (pid,)) or 0
    for i, (ab, name) in enumerate(p[1]):
        if name.lower() in have:
            continue
        cid = core.ins(c, "boq_components", {"project_id": pid, "code": "", "name": name, "sort": int(base) + i + 1, "active": 1})
        core.ins(c, "bx_loc", {"project_id": pid, "component_id": cid, "abbr": _unique(ab, abbrs), "manual": 1, "ts": core.today()})
        made += 1
    _log(c, u, pid, "presets", {"preset": a.get("preset"), "made": made})
    return {"created": made}


# ───────────────────────────── wrappers: pickers, lists, search, upkeep ─────────────────────────────
def _w_lookups(orig):
    def lookups(c, u, a):
        res = orig(c, u, a)
        try:
            if on(c) and isinstance(res, dict) and res.get("boq"):
                m = {r["boq_item_id"]: r for r in q(c, "SELECT l.boq_item_id, l.short_code, l.role, i.key, x.abbr FROM bx_line l "
                                                        "LEFT JOIN bx_item i ON i.id=l.item_id LEFT JOIN bx_loc x ON x.id=l.loc_id")}
                for b in res["boq"]:
                    r = m.get(b.get("id"))
                    if r:
                        b["sc"] = r["short_code"]
                        b["loc"] = r["abbr"] or ""
                        b["item"] = r["key"] or ""
                        if r["role"] == "overall":
                            b["overall"] = 1
        except Exception:  # noqa: BLE001
            pass
        return res
    return lookups


def _w_master_list(orig):
    def master_list(c, u, a):
        res = orig(c, u, a)
        try:
            if a.get("table") == "boq_items" and on(c) and isinstance(res, list):
                m = {r["boq_item_id"]: r["short_code"] for r in q(c, "SELECT boq_item_id, short_code FROM bx_line")}
                for r in res:
                    r["short_code"] = m.get(r.get("id"), "")
        except Exception:  # noqa: BLE001
            pass
        return res
    return master_list


def _w_master_save(orig):
    def master_save(c, u, a):
        res = orig(c, u, a)
        if a.get("table") in ("boq_items",) and on(c) and isinstance(res, dict) and res.get("project_id"):
            sync(c, res["project_id"])
        return res
    return master_save


def _w_master_delete(orig):
    def master_delete(c, u, a):
        pid = None
        if a.get("table") == "boq_items" and a.get("id"):
            pid = val(c, "SELECT project_id FROM boq_items WHERE id=?", (int(a["id"]),), None)
        res = orig(c, u, a)
        if pid:
            c.execute("DELETE FROM bx_line WHERE boq_item_id=?", (int(a["id"]),))
            if on(c):
                sync(c, pid)
        return res
    return master_delete


def _w_project_sync(id_table=None):
    def factory(orig):
        def fn(c, u, a):
            res = orig(c, u, a)
            try:
                if on(c):
                    pid = a.get("project_id") or ((a.get("row") or {}).get("project_id"))
                    if not pid and id_table and a.get("id"):
                        pid = val(c, "SELECT project_id FROM %s WHERE id=?" % id_table, (int(a["id"]),), None)
                    if pid:
                        sync(c, int(pid))
            except ApiError:
                raise
            except Exception:  # noqa: BLE001
                pass
            return res
        return fn
    return factory


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


def _search_entry():
    try:
        import api_project as P
        for e in P.SEARCH:
            if e.get("table") == "boq_items" and not e.get("_bx"):
                e["where"] = list(e["where"]) + ["@id IN (SELECT boq_item_id FROM bx_line WHERE COALESCE(short_code,'') LIKE ?)"]
                e["label"] = "COALESCE((SELECT short_code||' · ' FROM bx_line WHERE boq_item_id=boq_items.id),'')||" + e["label"]
                e["_bx"] = True
    except Exception:  # noqa: BLE001
        pass


def init_boqloc(c):
    c.executescript(SCHEMA)
    if not val(c, "SELECT COUNT(*) FROM settings WHERE key='bx_on'"):
        used = val(c, "SELECT COUNT(*) FROM boq_items") or val(c, "SELECT COUNT(*) FROM vouchers")
        c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES('bx_on', ?)", ("0" if used else "1",))
    c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES('bx_format', '{LOC}-{ITEM}')")
    c.commit()
    _wrap("lookups", _w_lookups)
    _wrap("master.list", _w_master_list)
    _wrap("master.save", _w_master_save)
    _wrap("master.delete", _w_master_delete)
    for fn, t in (("comp.save", None), ("comp.delete", "boq_components"), ("comp.assign", None), ("comp.setup", None), ("var.decide", "variations")):
        _wrap(fn, _w_project_sync(t))
    _search_entry()
