"""
Scheduling arithmetic for BuildCore (pure functions, no database).

Hinze, Construction Planning and Scheduling (4th ed.):
  * ch. 2-3  precedence network, FS / SS / FF / SF links with lags, forward and backward pass,
             total, free, independent and interfering float, loop detection
  * ch. 4-5  working-day calendars, holidays, weather allowance
  * ch. 6    resource leveling (fixed finish) and Brooks' allocation (limited resources)
  * ch. 7    cost-loaded early / late curves, time-cost trade-off (crashing)
  * ch. 11   overtime, crowding and extra work faces, learning curves
  * ch. 14   linear (time-location) schedules
  * ch. 15   PERT and Monte Carlo

Time is kept as day boundaries (date ordinals): an activity that starts on day s occupies the
start of s, and one whose last working day is e finishes at boundary e + 1. A milestone starts and
finishes on the same boundary. Durations and lags are in WORKING days of the activity's calendar.
"""
import math
import random
from datetime import date, timedelta

# ───────────────────────── Bikram Sambat calendar ─────────────────────────
# year: (AD date of 1 Baishakh, lengths of the 12 months)
BS = {
    2070: ("2013-04-14", "313131323131293030293030"), 2071: ("2014-04-14", "313132313131302930293030"),
    2072: ("2015-04-14", "313231323130302930293030"), 2073: ("2016-04-13", "313231323130303029293031"),
    2074: ("2017-04-14", "313131323131302930293030"), 2075: ("2018-04-14", "313132313131302930293030"),
    2076: ("2019-04-14", "313231323130303029293030"), 2077: ("2020-04-13", "313231323130303029302931"),
    2078: ("2021-04-14", "313131323131302930293030"), 2079: ("2022-04-14", "313132313131302930293030"),
    2080: ("2023-04-14", "313231323130303029293030"), 2081: ("2024-04-13", "313231323130303029302931"),
    2082: ("2025-04-14", "313132313131302930293030"), 2083: ("2026-04-14", "313132313131302930293030"),
    2084: ("2027-04-14", "313231323130303029293031"), 2085: ("2028-04-14", "303231323130303029302931"),
    2086: ("2029-04-14", "313132313131302930293030"), 2087: ("2030-04-14", "313132313131303029303030"),
    2088: ("2031-04-15", "303132323031303029303030"), 2089: ("2032-04-14", "303231323130303029303030"),
    2090: ("2033-04-14", "303231323130303029303030"),
}
BS_MONTHS = ["Baishakh", "Jestha", "Asar", "Shrawan", "Bhadra", "Ashoj", "Kartik", "Mangsir", "Poush", "Magh",
             "Falgun", "Chaitra"]


def _lens(y):
    s = BS[y][1]
    return [int(s[i:i + 2]) for i in range(0, 24, 2)]


def bs_to_ad(y, m, d):
    """Bikram Sambat (year, month 1-12, day) to a Python date."""
    if y not in BS:
        raise ValueError("BS year %s is outside the calendar table (2070-2090)" % y)
    lens = _lens(y)
    if not 1 <= m <= 12 or not 1 <= d <= lens[m - 1]:
        raise ValueError("%s %s has only %s days" % (BS_MONTHS[m - 1] if 1 <= m <= 12 else m, y,
                                                     lens[m - 1] if 1 <= m <= 12 else "?"))
    return date.fromisoformat(BS[y][0]) + timedelta(days=sum(lens[:m - 1]) + d - 1)


def ad_to_bs(dt):
    """Python date (or ISO text) to (year, month, day) in Bikram Sambat."""
    if isinstance(dt, str):
        dt = date.fromisoformat(dt[:10])
    for y in sorted(BS, reverse=True):
        start = date.fromisoformat(BS[y][0])
        if dt >= start:
            off = (dt - start).days
            for m, n in enumerate(_lens(y)):
                if off < n:
                    return y, m + 1, off + 1
                off -= n
            break
    raise ValueError("%s is outside the calendar table" % dt)


def bs_text(dt):
    y, m, d = ad_to_bs(dt)
    return "%d-%02d-%02d" % (y, m, d)


def parse_any_date(s):
    """'2026-10-17' (AD) or '2083-06-31' / '2083/06/31' (BS, year above 2060) -> ISO AD text."""
    s = str(s).strip().replace("/", "-").replace(".", "-")
    y, m, d = [int(x) for x in s.split("-")[:3]]
    if y > 2060:
        return bs_to_ad(y, m, d).isoformat()
    return date(y, m, d).isoformat()


# ───────────────────────── calendars ─────────────────────────
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
NEPAL_WEEK = "1111101"      # Sunday to Friday work, Saturday off (Monday..Sunday order)


class Calendar:
    """week: 7 characters Mon..Sun, '1' = working day. holidays: ISO dates.
    windows: [(work_type, from_iso, to_iso)] - no work for that work type (e.g. river works in monsoon).
    weather: {AD month 1-12: expected working days lost} for weather-sensitive work."""

    def __init__(self, week=NEPAL_WEEK, holidays=(), windows=(), weather=None, name="", cid=None):
        self.week = (week or NEPAL_WEEK).ljust(7, "1")[:7]
        self.hol = {date.fromisoformat(h[:10]).toordinal() for h in holidays if h}
        self.win = [(wt or "", date.fromisoformat(a).toordinal(), date.fromisoformat(b).toordinal())
                    for wt, a, b in windows if a and b]
        self.weather = {int(k): float(v or 0) for k, v in (weather or {}).items()}
        self.name, self.id = name, cid
        self._cache = {}

    def work(self, o, wt=""):
        k = (o, wt)
        r = self._cache.get(k)
        if r is None:
            d = date.fromordinal(o)
            r = self.week[d.weekday()] == "1" and o not in self.hol
            if r and wt:
                for w, a, b in self.win:
                    if w == wt and a <= o <= b:
                        r = False
                        break
            self._cache[k] = r
        return r

    # boundary arithmetic (o = ordinal of a day boundary: start of that day)
    def start_up(self, b, wt=""):
        n = 0
        while not self.work(b, wt):
            b += 1
            n += 1
            if n > 3700:
                raise ValueError("Calendar %s has no working days" % self.name)
        return b

    def start_down(self, b, wt=""):
        n = 0
        while not self.work(b, wt):
            b -= 1
            n += 1
            if n > 3700:
                raise ValueError("Calendar %s has no working days" % self.name)
        return b

    def finish_up(self, b, wt=""):
        return self.start_up(b - 1, wt) + 1

    def finish_down(self, b, wt=""):
        return self.start_down(b - 1, wt) + 1

    def advance(self, b, n, wt=""):
        """Boundary after n working days counted from boundary b (n may be negative)."""
        if n < 0:
            return self.retreat(b, -n, wt)
        n = int(math.ceil(n - 1e-9))
        while n > 0:
            if self.work(b, wt):
                n -= 1
            b += 1
        return b

    def retreat(self, b, n, wt=""):
        if n < 0:
            return self.advance(b, -n, wt)
        n = int(math.ceil(n - 1e-9))
        while n > 0:
            b -= 1
            if self.work(b, wt):
                n -= 1
        return b

    def wd(self, a, b, wt=""):
        """Signed number of working days in [a, b)."""
        if b == a:
            return 0
        sgn = 1
        if b < a:
            a, b, sgn = b, a, -1
        return sgn * sum(1 for o in range(a, b) if self.work(o, wt))

    def workdays(self, a, b, wt=""):
        """Ordinals of the working days in [a, b)."""
        return [o for o in range(a, b) if self.work(o, wt)]


def weather_extra(cal, s, n, wt=""):
    """Expected working days lost to weather while an activity of n working days runs from s."""
    if not cal.weather or n <= 0:
        return 0
    lost = 0.0
    f = cal.advance(s, n, wt)
    per_month = {}
    for o in cal.workdays(s, f, wt):
        m = date.fromordinal(o).month
        per_month[m] = per_month.get(m, 0) + 1
    for m, k in per_month.items():
        a = cal.weather.get(m, 0)
        if a:
            # working days available in that month on this calendar (about 25 on a 6-day week)
            avail = 26 if cal.week.count("1") == 6 else round(cal.week.count("1") * 30 / 7)
            lost += a * k / max(avail, 1)
    return int(round(lost))


# ───────────────────────── CPM ─────────────────────────
LINK_TYPES = ("FS", "SS", "FF", "SF")


class ScheduleError(Exception):
    pass


def parse_pred_text(txt):
    """'A10, A20SS+3, 4.03.1FF-2' -> [(code, type, lag)]. Accepts spaces and ';'."""
    out = []
    for part in str(txt or "").replace(";", ",").split(","):
        p = part.strip().replace(" ", "")
        if not p:
            continue
        lag = 0.0
        typ = "FS"
        for sign in ("+", "-"):
            i = p.rfind(sign)
            if i > 0:
                try:
                    lag = float(p[i:])
                    p = p[:i]
                except ValueError:
                    pass
                break
        up = p.upper()
        for t in LINK_TYPES:
            if up.endswith(t) and len(p) > 2:
                typ, p = t, p[:-2]
                break
        out.append((p, typ, lag))
    return out


def find_cycle(ids, succ):
    """Return one loop as a list of ids, or None."""
    color = {i: 0 for i in ids}
    stack = []

    def dfs(v):
        color[v] = 1
        stack.append(v)
        for w in succ.get(v, ()):
            if w not in color:
                continue
            if color[w] == 1:
                return stack[stack.index(w):] + [w]
            if color[w] == 0:
                r = dfs(w)
                if r:
                    return r
        stack.pop()
        color[v] = 2
        return None

    import sys
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old, 10000))
    try:
        for i in ids:
            if color[i] == 0:
                r = dfs(i)
                if r:
                    return r
    finally:
        sys.setrecursionlimit(old)
    return None


def topo_order(ids, links):
    succ, indeg = {i: [] for i in ids}, {i: 0 for i in ids}
    for l in links:
        succ[l["pred"]].append(l["succ"])
        indeg[l["succ"]] += 1
    order = [i for i in ids if indeg[i] == 0]
    k = 0
    while k < len(order):
        v = order[k]
        k += 1
        for w in succ[v]:
            indeg[w] -= 1
            if indeg[w] == 0:
                order.append(w)
    if len(order) < len(ids):
        left = [i for i in ids if indeg[i] > 0]
        cyc = find_cycle(left, succ)
        raise ScheduleError(("The logic has a loop: %s" % " -> ".join(str(x) for x in cyc)) if cyc
                            else "The logic has a loop.", cyc)
    return order


def cpm(acts, links, cals, opts=None):
    """
    acts: [{id, code, name, dur (working days, 0 = milestone), cal (key into cals), wt (work type),
            weather (bool), snet, fnlt, mso (ISO dates), actual_start, actual_finish, remaining}]
    links: [{pred, succ, type, lag}]
    cals: {key: Calendar}; key None = project default
    opts: start (ISO project start), data_date (ISO), finish_target (ISO contract completion),
          near_days (float threshold for near-critical), keep_dates (treat planned start of an
          activity without predecessors as start-no-earlier-than; set by caller via snet)
    Returns {acts: {id: result}, finish, start, warnings, critical_ids}
    """
    opts = opts or {}
    ids = [a["id"] for a in acts]
    A = {a["id"]: a for a in acts}
    L = [dict(l, type=(l.get("type") or "FS").upper(), lag=float(l.get("lag") or 0)) for l in links
         if l["pred"] in A and l["succ"] in A and l["pred"] != l["succ"]]
    order = topo_order(ids, L)
    preds = {i: [] for i in ids}
    succs = {i: [] for i in ids}
    for l in L:
        preds[l["succ"]].append(l)
        succs[l["pred"]].append(l)
    default = cals.get(None) or Calendar()

    def C(i):
        return cals.get(A[i].get("cal")) or default

    def W(i):
        return A[i].get("wt") or ""

    def o(iso):
        return date.fromisoformat(iso[:10]).toordinal() if iso else None

    starts = [o(a["snet"]) for a in acts if a.get("snet")] + [o(a["actual_start"]) for a in acts
                                                               if a.get("actual_start")]
    p_start = o(opts["start"]) if opts.get("start") else (min(starts) if starts else date.today().toordinal())
    dd = o(opts["data_date"]) if opts.get("data_date") else None
    warn = []
    R = {}
    # forward pass
    for i in order:
        a, c, wt = A[i], C(i), W(i)
        n = max(0.0, float(a.get("dur") or 0))
        r = R[i] = {"dur": n, "weather_days": 0, "status": "not_started", "driver": None}
        if a.get("actual_start") and a.get("actual_finish"):
            es = o(a["actual_start"])
            ef = o(a["actual_finish"]) + 1 if n > 0 else es
            r.update(es=es, ef=ef, status="complete", rem=0)
            continue
        if a.get("actual_start"):
            es = o(a["actual_start"])
            rem = a.get("remaining")
            if rem is None:
                rem = n
            base = c.start_up(max(dd or es, es), wt)
            ef = c.advance(base, max(rem, 0), wt) if rem > 0 else max(base, es + 1 if n > 0 else es)
            r.update(es=es, ef=ef, status="in_progress", rem=rem)
            continue
        lo = p_start
        if dd:
            lo = max(lo, dd)
        cand = lo
        drv = None
        fin_req = None
        for l in preds[i]:
            p = R[l["pred"]]
            if l["type"] == "FS":
                v = c.advance(p["ef"], l["lag"], wt)
            elif l["type"] == "SS":
                v = c.advance(p["es"], l["lag"], wt)
            else:
                f = c.advance(p["ef"] if l["type"] == "FF" else p["es"], l["lag"], wt)
                if fin_req is None or f > fin_req:
                    fin_req = f
                v = c.retreat(c.finish_up(f, wt), n, wt) if n > 0 else f
            if v > cand or (v == cand and drv is None and v > lo):
                cand, drv = v, l["pred"]
        if a.get("snet") and o(a["snet"]) > cand:
            cand, drv = o(a["snet"]), None
        if a.get("mso"):
            cand = o(a["mso"])
        es = c.start_up(cand, wt) if n > 0 else cand
        if n > 0 and a.get("weather"):
            extra = weather_extra(c, es, n, wt)
            r["weather_days"] = extra
            n2 = n + extra
        else:
            n2 = n
        ef = c.advance(es, n2, wt) if n2 > 0 else es
        r.update(es=es, ef=ef, rem=n2, driver=drv, dur_eff=n2)
    finish = max([R[i]["ef"] for i in ids] or [p_start])
    target = o(opts["finish_target"]) + 1 if opts.get("finish_target") else None
    pf = target if target else finish
    # backward pass
    for i in reversed(order):
        a, c, wt, r = A[i], C(i), W(i), R[i]
        n = r.get("dur_eff", r["dur"])
        if r["status"] == "complete":
            r.update(ls=r["es"], lf=r["ef"])
            continue
        lf = c.finish_down(pf, wt) if n > 0 else pf
        if a.get("fnlt"):
            lf = min(lf, o(a["fnlt"]) + 1)
        for l in succs[i]:
            s = R[l["succ"]]
            cs, wts = C(l["succ"]), W(l["succ"])
            if l["type"] == "FS":
                v = cs.retreat(s["ls"], l["lag"], wts)
            elif l["type"] == "FF":
                v = cs.retreat(s["lf"], l["lag"], wts)
            else:
                x = cs.retreat(s["ls"] if l["type"] == "SS" else s["lf"], l["lag"], wts)
                v = c.advance(c.start_down(x, wt), n, wt) if n > 0 else x
            lf = min(lf, v)
        if n > 0:
            lf = c.finish_down(lf, wt)
        if r["status"] == "in_progress":
            rem = r.get("rem") or 0
            ls = c.retreat(lf, rem, wt) if rem > 0 else lf
            r.update(ls=ls, lf=lf)
        else:
            ls = c.retreat(lf, n, wt) if n > 0 else lf
            if a.get("mso"):
                ls = min(ls, o(a["mso"]))
            r.update(ls=ls, lf=lf)
    # floats
    for i in ids:
        a, c, wt, r = A[i], C(i), W(i), R[i]
        if r["status"] == "complete":
            r.update(tf=None, ff=None, if_=None, intf=None)
            continue
        if r["status"] == "in_progress":
            tf = c.wd(r["ef"], r["lf"], wt)
        else:
            tf = min(c.wd(r["es"], r["ls"], wt), c.wd(r["ef"], r["lf"], wt))
        slacks = []
        for l in succs[i]:
            s = R[l["succ"]]
            cs, wts = C(l["succ"]), W(l["succ"])
            if l["type"] in ("FS", "SS"):
                bound = cs.retreat(s["es"], l["lag"], wts)
            else:
                bound = cs.retreat(s["ef"], l["lag"], wts)
            mine = r["ef"] if l["type"] in ("FS", "FF") else r["es"]
            slacks.append(c.wd(mine, bound, wt))
        ff = min(slacks) if slacks else tf
        ff = max(0, min(ff, tf)) if tf >= 0 else 0
        # independent float: free float left when every predecessor finishes as late as it may
        late = None
        for l in preds[i]:
            p = R[l["pred"]]
            if p["status"] == "complete":
                continue
            if l["type"] == "FS":
                v = c.advance(p["lf"], l["lag"], wt)
            elif l["type"] == "SS":
                v = c.advance(p["ls"], l["lag"], wt)
            else:
                f = c.advance(p["lf"] if l["type"] == "FF" else p["ls"], l["lag"], wt)
                n = r.get("dur_eff", r["dur"])
                v = c.retreat(c.finish_up(f, wt), n, wt) if n > 0 else f
            late = v if late is None else max(late, v)
        push = max(0, c.wd(r["es"], late, wt)) if late is not None and r["status"] == "not_started" else 0
        r.update(tf=tf, ff=ff, if_=max(0, ff - push), intf=tf - ff)
    live = [R[i]["tf"] for i in ids if R[i]["tf"] is not None and not A[i].get("loe")]
    min_tf = min(live) if live else 0
    crit_limit = 0 if min_tf <= 0 else min_tf
    near = float(opts.get("near_days") or 0)
    crit = []
    for i in ids:
        r = R[i]
        tf = r["tf"]
        loe = bool(A[i].get("loe"))
        r["critical"] = tf is not None and tf <= crit_limit and not loe
        r["near"] = bool(tf is not None and not r["critical"] and not loe and near and tf <= crit_limit + near)
        if r["critical"]:
            crit.append(i)
    # open ends and dangling activities
    if len(ids) > 1 and L:
        no_pred = [A[i] for i in ids if not preds[i] and not A[i].get("actual_start")]
        no_succ = [A[i] for i in ids if not succs[i]]
        if len(no_pred) > 1:
            warn.append("%d activities have no predecessor (open start): %s" % (
                len(no_pred), ", ".join((x.get("code") or x.get("name") or str(x["id"])) for x in no_pred[:8])))
        if len(no_succ) > 1:
            warn.append("%d activities have no successor (open end): %s" % (
                len(no_succ), ", ".join((x.get("code") or x.get("name") or str(x["id"])) for x in no_succ[:8])))
    for i in ids:
        if not A[i].get("dur") and not A[i].get("milestone") and R[i]["status"] == "not_started":
            warn.append("%s has no duration (treated as a milestone)" % (A[i].get("code") or A[i].get("name")))
    return {"acts": R, "finish": finish, "start": p_start, "target": target, "warnings": warn,
            "critical_ids": crit, "min_tf": min_tf, "order": order}


def iso(o):
    return date.fromordinal(o).isoformat() if o is not None else None


def dates_out(r, dur):
    """Display dates: start day and last working day (finish boundary - 1); milestones one date."""
    s = iso(r["es"])
    f = iso(r["ef"] - 1) if r["ef"] > r["es"] else s
    ls = iso(r["ls"]) if r.get("ls") is not None else None
    lf = iso(r["lf"] - 1) if r.get("lf") is not None and r["lf"] > r.get("ls", r["lf"]) else ls
    return s, f, ls, lf


# ───────────────────────── loading & curves ─────────────────────────
def spread(cal, s, f, value, wt=""):
    """{ordinal: amount}: value spread evenly over the working days in [s, f)."""
    days = cal.workdays(s, f, wt) if f > s else []
    if not days:
        return {s: value}
    per = value / len(days)
    return {o: per for o in days}


def cumulative(daily, points):
    """daily {ordinal: amount}, points [ordinal] ascending -> cumulative at end of each point day."""
    items = sorted(daily.items())
    out, acc, k = [], 0.0, 0
    for p in points:
        while k < len(items) and items[k][0] <= p:
            acc += items[k][1]
            k += 1
        out.append(acc)
    return out


def histogram(loads, cal_of, start, end):
    """loads: [(cal, s, f, per_day_units, wt)] -> {ordinal: units}."""
    h = {}
    for cal, s, f, u, wt in loads:
        for o in (cal.workdays(s, f, wt) if f > s else []):
            if start <= o < end:
                h[o] = h.get(o, 0) + u
    return h


# ───────────────────────── leveling and allocation (integer working-day model) ─────────────────────────
def _simple_net(acts, links):
    """acts [{id, dur, res: {key: units per day}}], links [{pred, succ, type, lag}] in working days.
    Returns order, preds, succs."""
    ids = [a["id"] for a in acts]
    L = [l for l in links if l["pred"] in set(ids) and l["succ"] in set(ids)]
    order = topo_order(ids, L)
    preds = {i: [] for i in ids}
    succs = {i: [] for i in ids}
    for l in L:
        preds[l["succ"]].append(l)
        succs[l["pred"]].append(l)
    return order, preds, succs


def _es_from(l, p_es, p_ef, dur):
    t, lag = (l.get("type") or "FS").upper(), float(l.get("lag") or 0)
    if t == "FS":
        return p_ef + lag
    if t == "SS":
        return p_es + lag
    if t == "FF":
        return p_ef + lag - dur
    return p_es + lag - dur


def int_cpm(acts, links, fixed=None):
    """Integer CPM in working days from 0. fixed {id: es} pins starts (used by the heuristics)."""
    order, preds, succs = _simple_net(acts, links)
    A = {a["id"]: a for a in acts}
    es, ef = {}, {}
    for i in order:
        d = A[i]["dur"]
        v = max([_es_from(l, es[l["pred"]], ef[l["pred"]], d) for l in preds[i]] + [A[i].get("min_start", 0), 0])
        if fixed and i in fixed:
            v = max(v, fixed[i])
        es[i], ef[i] = v, v + d
    T = max(ef.values() or [0])
    ls, lf = {}, {}
    for i in reversed(order):
        d = A[i]["dur"]
        v = T
        for l in succs[i]:
            s = l["succ"]
            t, lag = (l.get("type") or "FS").upper(), float(l.get("lag") or 0)
            if t == "FS":
                v = min(v, ls[s] - lag)
            elif t == "SS":
                v = min(v, ls[s] - lag + d)
            elif t == "FF":
                v = min(v, lf[s] - lag)
            else:
                v = min(v, lf[s] - lag + d)
        lf[i], ls[i] = v, v - d
    return {"es": es, "ef": ef, "ls": ls, "lf": lf, "T": T, "order": order, "preds": preds, "succs": succs}


def profile(acts, start):
    """{resource: [units per working day]} for activity starts `start`."""
    T = int(max([start[a["id"]] + a["dur"] for a in acts] or [0]))
    prof = {}
    for a in acts:
        for k, u in (a.get("res") or {}).items():
            p = prof.setdefault(k, [0.0] * (T + 1))
            for t in range(int(start[a["id"]]), int(start[a["id"]] + a["dur"])):
                if t < len(p):
                    p[t] += u
    return prof


def level(acts, links, passes=3):
    """Minimum-moment leveling (Harris / Burgess): keep the finish date, shift non-critical
    activities within their float to minimise the sum of squared daily demand.
    Returns {id: new_es}, stats."""
    base = int_cpm(acts, links)
    A = {a["id"]: a for a in acts}
    start = dict(base["es"])
    T = base["T"]

    def ssq(st):
        return sum(sum(x * x for x in p) for p in profile(acts, st).values())

    before = ssq(start)
    for _ in range(passes):
        moved = False
        for i in sorted(base["order"], key=lambda x: -base["es"][x]):
            a = A[i]
            if not a.get("res") or a["dur"] <= 0:
                continue
            # window allowed by current positions of neighbours
            lo = max([_es_from(l, start[l["pred"]], start[l["pred"]] + A[l["pred"]]["dur"], a["dur"])
                      for l in base["preds"][i]] + [a.get("min_start", 0), 0])
            hi = T - a["dur"]
            for l in base["succs"][i]:
                s = l["succ"]
                t, lag = (l.get("type") or "FS").upper(), float(l.get("lag") or 0)
                ss, sf = start[s], start[s] + A[s]["dur"]
                if t == "FS":
                    hi = min(hi, ss - lag - a["dur"])
                elif t == "SS":
                    hi = min(hi, ss - lag)
                elif t == "FF":
                    hi = min(hi, sf - lag - a["dur"])
                else:
                    hi = min(hi, sf - lag)
            if hi <= lo:
                continue
            best, best_v = start[i], None
            for s0 in range(int(lo), int(hi) + 1):
                trial = dict(start)
                trial[i] = s0
                v = ssq(trial)
                if best_v is None or v < best_v - 1e-9 or (abs(v - best_v) < 1e-9 and s0 < best):
                    best, best_v = s0, v
            if best != start[i]:
                start[i] = best
                moved = True
        if not moved:
            break
    after = ssq(start)
    peaks_b = {k: max(p) if p else 0 for k, p in profile(acts, base["es"]).items()}
    peaks_a = {k: max(p) if p else 0 for k, p in profile(acts, start).items()}
    return start, {"finish": T, "ssq_before": before, "ssq_after": after, "peaks_before": peaks_b,
                   "peaks_after": peaks_a}


def allocate(acts, links, limits):
    """Brooks' method (serial scheduling): resources capped at `limits` {res: units per day}.
    Activities ready to start are ranked by late start (then longest duration) and started as
    soon as the resources allow, so the finish date may move. Returns {id: es}, finish."""
    base = int_cpm(acts, links)
    A = {a["id"]: a for a in acts}
    for a in acts:
        for k, u in (a.get("res") or {}).items():
            if k in limits and u > limits[k] + 1e-9:
                raise ScheduleError("%s needs %s %s a day but only %s are available." % (
                    a.get("code") or a["id"], u, k, limits[k]))
    use = {}
    start = {}
    done = set()
    preds = base["preds"]
    remaining = list(base["order"])
    guard = 0
    while remaining:
        guard += 1
        if guard > 100000:
            raise ScheduleError("Allocation did not converge.")
        ready = [i for i in remaining if all(l["pred"] in done for l in preds[i])]
        ready.sort(key=lambda i: (base["ls"][i], -A[i]["dur"], str(A[i].get("code") or i)))
        i = ready[0]
        a = A[i]
        t = max([_es_from(l, start[l["pred"]], start[l["pred"]] + A[l["pred"]]["dur"], a["dur"])
                 for l in preds[i]] + [a.get("min_start", 0), 0])
        t = int(math.ceil(t))
        while True:
            ok = True
            for k, u in (a.get("res") or {}).items():
                if k not in limits:
                    continue
                for d in range(t, t + int(a["dur"])):
                    if use.get((k, d), 0) + u > limits[k] + 1e-9:
                        ok = False
                        break
                if not ok:
                    break
            if ok:
                break
            t += 1
        start[i] = t
        for k, u in (a.get("res") or {}).items():
            for d in range(t, t + int(a["dur"])):
                use[(k, d)] = use.get((k, d), 0) + u
        done.add(i)
        remaining.remove(i)
    finish = max([start[i] + A[i]["dur"] for i in start] or [0])
    return start, {"finish": finish, "base_finish": base["T"], "delay": finish - base["T"]}


# ───────────────────────── crashing (time-cost trade-off) ─────────────────────────
def crash(acts, links, indirect_per_day=0.0, ld_per_day=0.0, target=None, max_steps=500):
    """acts [{id, dur, crash_dur, cost, crash_cost}] in working days.
    Repeatedly shortens by one day the cheapest critical activity (or cheapest combination
    covering all critical paths, approximated by one per parallel critical chain), recording
    direct + indirect + LD cost at every duration. Returns steps and the least-cost point."""
    A = {a["id"]: dict(a) for a in acts}
    for a in A.values():
        a["crash_dur"] = min(a.get("crash_dur") if a.get("crash_dur") not in (None, "") else a["dur"], a["dur"])
        span = a["dur"] - a["crash_dur"]
        extra = (a.get("crash_cost") or a.get("cost") or 0) - (a.get("cost") or 0)
        a["slope"] = extra / span if span > 0 else None
        a["cur"] = a["dur"]
    direct = sum(a.get("cost") or 0 for a in A.values())

    def run():
        return int_cpm([{"id": i, "dur": a["cur"], "min_start": a.get("min_start", 0)} for i, a in A.items()], links)

    net = run()
    base_T = net["T"]
    tgt = target if target is not None else base_T

    def total(T, d):
        late = max(0, T - tgt)
        return d + indirect_per_day * T + ld_per_day * late

    steps = [{"duration": net["T"], "direct": round(direct, 2), "indirect": round(indirect_per_day * net["T"], 2),
              "ld": round(ld_per_day * max(0, net["T"] - tgt), 2), "total": round(total(net["T"], direct), 2),
              "crashed": None}]
    for _ in range(max_steps):
        crit = [i for i in A if abs(net["ls"][i] - net["es"][i]) < 1e-9 and A[i]["dur"] > 0]
        # group critical activities by start time: parallel critical chains must each shorten
        cands = [i for i in crit if A[i]["slope"] is not None and A[i]["cur"] > A[i]["crash_dur"]]
        if not cands:
            break
        # try the cheapest single activity; if the project does not shorten, add the cheapest
        # activity on the other critical path(s) as well
        cands.sort(key=lambda i: A[i]["slope"])
        chosen = []
        T0 = net["T"]
        cost = 0.0
        for i in cands:
            A[i]["cur"] -= 1
            chosen.append(i)
            cost += A[i]["slope"]
            trial = run()
            if trial["T"] < T0:
                net = trial
                break
        else:
            for i in chosen:
                A[i]["cur"] += 1
            break
        direct += cost
        steps.append({"duration": net["T"], "direct": round(direct, 2), "indirect": round(indirect_per_day * net["T"], 2),
                      "ld": round(ld_per_day * max(0, net["T"] - tgt), 2), "total": round(total(net["T"], direct), 2),
                      "crashed": [A[i].get("code") or i for i in chosen], "slope": round(cost, 2)})
    best = min(steps, key=lambda s: (s["total"], s["duration"]))
    return {"steps": steps, "best": best, "normal_duration": base_T}


# ───────────────────────── PERT and Monte Carlo ─────────────────────────
def pert(to, tm, tp):
    te = (to + 4 * tm + tp) / 6.0
    sd = (tp - to) / 6.0
    return te, sd


def norm_cdf(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def pert_network(acts, links, target_days=None):
    """acts [{id, to, tm, tp}] -> expected duration of the critical path, sigma, P(finish <= target)."""
    ex = []
    for a in acts:
        te, sd = pert(a["to"], a["tm"], a["tp"])
        ex.append({"id": a["id"], "dur": te, "sd": sd})
    net = int_cpm(ex, links)
    crit = [x for x in ex if abs(net["ls"][x["id"]] - net["es"][x["id"]]) < 1e-6]
    var = sum(x["sd"] ** 2 for x in crit)
    T = net["T"]
    sd = math.sqrt(var)
    p = None
    if target_days is not None:
        p = norm_cdf((target_days - T) / sd) if sd > 0 else (1.0 if target_days >= T else 0.0)
    return {"expected": T, "sigma": sd, "probability": p, "critical": [x["id"] for x in crit]}


def tri_sample(rng, a, m, b):
    if b <= a:
        return a
    return rng.triangular(a, b, m)


def monte_carlo(acts, links, n=1000, target_days=None, seed=1):
    """Triangular durations (to, tm, tp). Returns finish percentiles, P(target) and how often each
    activity was critical (the criticality index that PERT cannot give)."""
    rng = random.Random(seed)
    order, preds, succs = _simple_net([{"id": a["id"]} for a in acts], links)
    A = {a["id"]: a for a in acts}
    finishes = []
    crit_count = {a["id"]: 0 for a in acts}
    for _ in range(int(n)):
        d = {i: tri_sample(rng, A[i]["to"], A[i]["tm"], A[i]["tp"]) for i in A}
        es, ef = {}, {}
        for i in order:
            v = max([_es_from(l, es[l["pred"]], ef[l["pred"]], d[i]) for l in preds[i]] + [0])
            es[i], ef[i] = v, v + d[i]
        T = max(ef.values() or [0])
        ls, lf = {}, {}
        for i in reversed(order):
            v = T
            for l in succs[i]:
                s = l["succ"]
                t, lag = (l.get("type") or "FS").upper(), float(l.get("lag") or 0)
                if t == "FS":
                    v = min(v, ls[s] - lag)
                elif t == "SS":
                    v = min(v, ls[s] - lag + d[i])
                elif t == "FF":
                    v = min(v, lf[s] - lag)
                else:
                    v = min(v, lf[s] - lag + d[i])
            lf[i], ls[i] = v, v - d[i]
            if abs(ls[i] - es[i]) < 1e-6:
                crit_count[i] += 1
        finishes.append(T)
    finishes.sort()

    def pct(p):
        return finishes[min(len(finishes) - 1, int(p * len(finishes)))]
    prob = None
    if target_days is not None:
        prob = sum(1 for x in finishes if x <= target_days) / len(finishes)
    buckets = {}
    for x in finishes:
        b = int(math.floor(x))
        buckets[b] = buckets.get(b, 0) + 1
    return {"runs": len(finishes), "mean": sum(finishes) / len(finishes), "p10": pct(0.10), "p50": pct(0.50),
            "p80": pct(0.80), "p90": pct(0.90), "min": finishes[0], "max": finishes[-1], "probability": prob,
            "criticality": {k: v / len(finishes) for k, v in crit_count.items()},
            "histogram": sorted(buckets.items())}


# ───────────────────────── productivity (Hinze ch. 11) ─────────────────────────
def overtime_efficiency(days_week, hours_day, k=5.0):
    """Efficiency % = 100 - k[(days/week - 5) + (hours/day - 8)] (k = 5 by default, editable)."""
    return max(0.0, 100.0 - k * (max(0, days_week - 5) + max(0, hours_day - 8)))


def crowding_efficiency(ratio, a=115.0, b=15.0):
    """Efficiency % = 115 - 15 x (expanded crew / normal crew), never above 100."""
    return max(0.0, min(100.0, a - b * ratio))


def work_faces_duration(t_old, points_old, points_new, exp=2.0 / 3.0):
    """T_new = T_old / (points_new / points_old)^(2/3)."""
    return t_old / ((points_new / float(points_old)) ** exp)


def acceleration(p):
    """p: dur_days (remaining work in working days at the normal crew and week), crew (workers),
    wage_hour (burdened), hours_day and days_week of the normal week, ot_premium (1.5 = time and a
    half), ld_per_day, indirect_per_day, supervision_per_day, equipment_per_day; options:
    ot_days_week, ot_hours_day, crew_ratio, faces_old, faces_new, face_setup_cost.
    Productivity of a long week is taken relative to the normal week, so a 6-day site is not
    penalised twice. Returns one row per option: days gained, extra cost, LD and indirect saved."""
    D = float(p.get("dur_days") or 0)
    crew = float(p.get("crew") or 1)
    wage = float(p.get("wage_hour") or 0)
    hd = float(p.get("hours_day") or 8)
    dw = float(p.get("days_week") or 6)
    prem = float(p.get("ot_premium") or 1.5)
    ld = float(p.get("ld_per_day") or 0)
    ind = float(p.get("indirect_per_day") or 0)
    sup = float(p.get("supervision_per_day") or 0)
    eqd = float(p.get("equipment_per_day") or 0)
    k = float(p.get("ot_k") or 5)
    ca, cb = float(p.get("crowd_a") or 115), float(p.get("crowd_b") or 15)
    work = D * hd * crew                          # effective worker-hours at normal productivity
    wk_norm = work / (dw * hd * crew) if D else 0  # calendar weeks at the normal week
    base_cost = work * wage
    cal_norm = wk_norm * 7.0
    rows = []
    # 1 overtime
    odw = float(p.get("ot_days_week") or dw)
    ohd = float(p.get("ot_hours_day") or 10)
    e_norm = overtime_efficiency(dw, hd, k) or 1.0
    e_ot = overtime_efficiency(odw, ohd, k)
    rel = e_ot / e_norm
    wk_ot = work / (odw * ohd * crew * rel) if rel > 0 else wk_norm
    std_h = min(dw * hd, odw * ohd)
    pay = wk_ot * crew * wage * (std_h + (odw * ohd - std_h) * prem)
    rows.append(_accel_row("Overtime: %g h x %g days a week (productivity %.1f%% of normal)" % (ohd, odw, rel * 100),
                           cal_norm - wk_ot * 7.0, pay - base_cost, ld, ind, sup, 0, 0, rel))
    # 2 bigger crew (crowding)
    ratio = float(p.get("crew_ratio") or 1.5)
    e2 = crowding_efficiency(ratio, ca, cb) / 100.0
    dur2 = D / (ratio * e2) if ratio * e2 > 0 else D
    cal2 = dur2 * 7.0 / dw
    pay2 = dur2 * hd * crew * ratio * wage
    rows.append(_accel_row("Crew x %g (crowding efficiency %.1f%%)" % (ratio, e2 * 100), cal_norm - cal2,
                           pay2 - base_cost, ld, ind, sup, cal2, eqd, e2))
    # 3 more work faces (e.g. a second HRT heading through an adit)
    po, pn = float(p.get("faces_old") or 1), float(p.get("faces_new") or 2)
    dur3 = work_faces_duration(D, po, pn) if D else 0
    cal3 = dur3 * 7.0 / dw
    rows.append(_accel_row("Work faces %g -> %g (duration %.0f%%)" % (po, pn, 100 * dur3 / D if D else 0),
                           cal_norm - cal3, float(p.get("face_setup_cost") or 0), ld, ind, sup, cal3, eqd, None))
    return {"base_calendar_days": round(cal_norm, 1), "base_labour_cost": round(base_cost, 2),
            "normal_week_efficiency": e_norm, "options": rows}


def _accel_row(label, gained, extra_labour, ld, ind, sup, dur_cal, eqd, eff):
    gained = max(0.0, gained)
    extra = extra_labour + sup * dur_cal + eqd * dur_cal
    saved = (ld + ind) * gained
    per_day = extra / gained if gained > 0 else None
    return {"option": label, "days_gained": round(gained, 1), "extra_cost": round(extra, 2),
            "ld_indirect_saved": round(saved, 2), "net_benefit": round(saved - extra, 2),
            "cost_per_day_gained": round(per_day, 2) if per_day is not None else None,
            "worth_it": bool(per_day is not None and per_day < ld + ind), "efficiency": eff}


def learning(t1, rate, n_units):
    """Unit time for units 1..n: T_N = T1 x N^s, s = log(f)/log 2 (f = learning rate, e.g. 0.85)."""
    s = math.log(rate) / math.log(2)
    return [t1 * (k ** s) for k in range(1, int(n_units) + 1)]


def fit_learning(times):
    """Least squares fit of log T = log T1 + s log N. Returns (t1, rate)."""
    pts = [(math.log(i + 1), math.log(t)) for i, t in enumerate(times) if t and t > 0]
    if len(pts) < 2:
        return (times[0] if times else None), None
    n = len(pts)
    sx = sum(p[0] for p in pts)
    sy = sum(p[1] for p in pts)
    sxx = sum(p[0] ** 2 for p in pts)
    sxy = sum(p[0] * p[1] for p in pts)
    den = n * sxx - sx * sx
    if abs(den) < 1e-12:
        return math.exp(sy / n), 1.0
    s = (n * sxy - sx * sy) / den
    b = (sy - s * sx) / n
    return math.exp(b), 2 ** s


def lost_learning(t1, rate, done_before, gap_units_lost, remaining):
    """Extra time when a stoppage sends the crew back down the curve by `gap_units_lost` units."""
    s = math.log(rate) / math.log(2)
    normal = sum(t1 * ((done_before + k) ** s) for k in range(1, remaining + 1))
    restart = max(1, done_before - gap_units_lost)
    after = sum(t1 * ((restart + k) ** s) for k in range(1, remaining + 1))
    return {"normal": normal, "after_stoppage": after, "lost": after - normal}


# ───────────────────────── linear schedule ─────────────────────────
def linear_conflicts(lines, time_buffer=0.0, dist_buffer=0.0):
    """lines [{id, name, ch_from, ch_to, start (ordinal), finish (ordinal), order}] where order says
    which crew follows which (a later crew must stay behind the earlier one).
    For each pair of consecutive crews, sample the position of both along their common stretch and
    report the smallest time gap and distance gap, and where the follower catches the leader."""
    out = []
    ls = sorted(lines, key=lambda x: x.get("order", 0))
    for a, b in zip(ls, ls[1:]):
        lo = max(min(a["ch_from"], a["ch_to"]), min(b["ch_from"], b["ch_to"]))
        hi = min(max(a["ch_from"], a["ch_to"]), max(b["ch_from"], b["ch_to"]))
        if hi <= lo:
            continue

        def t_at(x, ch):
            span = (x["ch_to"] - x["ch_from"]) or 1e-9
            return x["start"] + (ch - x["ch_from"]) / span * (x["finish"] - x["start"])
        min_gap, where = None, None
        steps = 50
        for k in range(steps + 1):
            ch = lo + (hi - lo) * k / steps
            g = t_at(b, ch) - t_at(a, ch)
            if min_gap is None or g < min_gap:
                min_gap, where = g, ch
        # distance gap at the time the follower is at `where`
        va = (a["ch_to"] - a["ch_from"]) / max(a["finish"] - a["start"], 1e-9)
        dist_gap = abs(va) * min_gap if min_gap is not None else None
        out.append({"leader": a["name"], "follower": b["name"], "min_time_gap": round(min_gap, 1),
                    "at_chainage": round(where, 1), "distance_gap": round(dist_gap, 1) if dist_gap is not None else None,
                    "clash": min_gap < time_buffer or (dist_buffer and dist_gap is not None and dist_gap < dist_buffer),
                    "crosses": min_gap < 0})
    return out
