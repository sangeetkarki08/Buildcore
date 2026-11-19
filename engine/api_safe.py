"""BuildCore 2.49 "Safe and correct".

* Backups keep the attached files.  The daily backup copied only the database; scans, photos and drawings in
  data/files were in no backup.  Every backup now also brings data/files into backups/files (new and changed files
  only, nothing there is ever deleted), and a second copy can go to another place (USB drive, second computer,
  network folder): the latest database backup plus all files, checked every hour, with a warning after 7 days.
  "Bring missing files back" copies files that are missing from data/files back from either copy (never overwrites).
* Trust the numbers (switch tn_on, off on companies that already had data, on for new ones): CPI and tender margin
  are worked out on the same BOQ items, the items that have a cost estimate.  Before, CPI divided the earned value of
  costed items by the cost of every item (CPI 0.42 when half the items had no estimate) and the tender margin set the
  revenue of every item against the cost of the costed ones (77.8 % instead of about 13 %).
* A screen could be served a project position or CVR worked out before the latest entries (a kept result was found
  by the connection's number, which a new connection can reuse).  Fixed, no switch: it is a fault.
* Resource levelling no longer moves activities that have already started.
* Periods: the 12 accounting periods were made as "17th to 16th" of English months, so Ashwin ended on 16 October
  while the Nepali month (and the monthly close) runs to 17 October.  New years are made from the real Nepali
  calendar; existing years can be corrected from Setup & switches (accounts approve; refused where a voucher would
  change from a locked month to an open one).
* Staff import takes a Project column (code, number or name, matched like the GRN import).
* Tally Gateway features that are not built are labelled "planned" instead of "comes in 2.47 ... 2.57".
* Administration > Setup & switches: every setup step and switch on one page, in the order to turn them on.
* Administration > Usage report: records and last use of every register, to decide what to hide.
Nothing is posted, no account, voucher or balance changes.
"""
import json
import os
import shutil
import sqlite3
import sys
import threading
import time
from datetime import date, datetime, timedelta

import core
from core import ApiError, audit, q, q1, setting, today, val
import api_inventory as inv
from api_inventory import api

VERSION = "2.49.0"
FLAG = "_bco249"
EPS = 1e-6


def _set(c, key, value):
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", (key, str(value)))


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


def _is_admin(u):
    return bool(u) and u.get("role") == "admin"


# ═════════════════════════════ 1. backups with the attached files ═════════════════════════════
_BK_LOCK = threading.Lock()
STATUS_FILE = "bco_backup_status.json"


def _files_dir():
    return os.path.join(core.DATA_DIR, "files")


def _status_path():
    return os.path.join(core.BACKUP_DIR, STATUS_FILE)


def _read_status():
    try:
        with open(_status_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _write_status(st):
    try:
        os.makedirs(core.BACKUP_DIR, exist_ok=True)
        tmp = _status_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(st, fh, indent=1)
        os.replace(tmp, _status_path())
    except Exception:
        pass


def mirror(src, dst):
    """Copy every file under src that is missing or different (size or newer) in dst. Never deletes."""
    copied = same = 0
    size = 0
    if not os.path.isdir(src):
        return {"copied": 0, "same": 0, "bytes": 0}
    for root, dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        tdir = dst if rel == "." else os.path.join(dst, rel)
        for f in files:
            s = os.path.join(root, f)
            t = os.path.join(tdir, f)
            try:
                st = os.stat(s)
                size += st.st_size
                if os.path.exists(t):
                    tt = os.stat(t)
                    if tt.st_size == st.st_size and tt.st_mtime >= st.st_mtime - 2:
                        same += 1
                        continue
                os.makedirs(tdir, exist_ok=True)
                tmp = t + ".part"
                shutil.copyfile(s, tmp)
                os.replace(tmp, t)
                try:
                    os.utime(t, (st.st_atime, st.st_mtime))
                except OSError:
                    pass
                copied += 1
            except OSError:
                continue
    return {"copied": copied, "same": same, "bytes": size}


def _count_files(d):
    n = size = 0
    if os.path.isdir(d):
        for root, dirs, files in os.walk(d):
            for f in files:
                if f.endswith(".part"):
                    continue
                n += 1
                try:
                    size += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    return n, size


def _latest_db_backup():
    try:
        fs = [f for f in os.listdir(core.BACKUP_DIR) if f.startswith("buildcore_") and f.endswith(".db")]
    except OSError:
        return None
    if not fs:
        return None
    fs.sort(key=lambda f: os.path.getmtime(os.path.join(core.BACKUP_DIR, f)))
    return os.path.join(core.BACKUP_DIR, fs[-1])


def _company_code():
    try:
        import api_corp
        return api_corp.CUR.get("code") or "main"
    except Exception:
        return "main"


def files_to_backup():
    """data/files -> backups/files."""
    r = mirror(_files_dir(), os.path.join(core.BACKUP_DIR, "files"))
    st = _read_status()
    st["files_at"] = datetime.now().isoformat(timespec="seconds")
    st["files_copied_last"] = r["copied"]
    _write_status(st)
    return r


def second_copy(target, force=False):
    """The latest database backup and every attached file into <target>/BuildCore_backup/<company>/."""
    if not target:
        return {"ok": False, "reason": "No place for the second copy is set."}
    if not os.path.isdir(target):
        return {"ok": False, "reason": "The place %s cannot be reached now (drive not plugged in or folder missing)." % target}
    st = _read_status()
    last = st.get("copy_at")
    if not force and last and last[:10] == date.today().isoformat() and st.get("copy_to") == target:
        return {"ok": True, "skipped": True, "at": last}
    base = os.path.join(target, "BuildCore_backup", _company_code())
    os.makedirs(base, exist_ok=True)
    db = _latest_db_backup()
    if db:
        t = os.path.join(base, os.path.basename(db))
        if not os.path.exists(t):
            shutil.copyfile(db, t + ".part")
            os.replace(t + ".part", t)
        keep = sorted((f for f in os.listdir(base) if f.startswith("buildcore_") and f.endswith(".db")),
                      key=lambda f: os.path.getmtime(os.path.join(base, f)))
        for f in keep[:-14]:
            try:
                os.remove(os.path.join(base, f))
            except OSError:
                pass
    r = mirror(_files_dir(), os.path.join(base, "files"))
    st = _read_status()
    st.update({"copy_at": datetime.now().isoformat(timespec="seconds"), "copy_to": target, "copy_db": os.path.basename(db) if db else None,
               "copy_files_copied": r["copied"], "copy_error": None})
    _write_status(st)
    return {"ok": True, "at": st["copy_at"], "db": st["copy_db"], "files_copied": r["copied"]}


def _wrap_backup_now():
    orig = core.backup_now
    if getattr(orig, FLAG, False):
        return

    def backup_now(tag="auto"):
        path = orig(tag)
        with _BK_LOCK:
            try:
                files_to_backup()
            except Exception as e:  # a file problem must never stop the database backup
                st = _read_status()
                st["files_error"] = str(e)
                _write_status(st)
            try:
                tgt = _read_target()
                if tgt:
                    second_copy(tgt)
            except Exception as e:
                st = _read_status()
                st["copy_error"] = str(e)
                _write_status(st)
        return path
    setattr(backup_now, FLAG, True)
    backup_now._orig = orig
    core.backup_now = backup_now
    for name in ("__main__", "server"):
        m = sys.modules.get(name)
        if m is not None and getattr(m, "backup_now", None) is orig:
            m.backup_now = backup_now


def _read_target():
    """The second-copy place, read without a user session (stored in the settings table)."""
    try:
        k = sqlite3.connect("file:%s?mode=ro" % core.DB_PATH, uri=True, timeout=5)
        try:
            r = k.execute("SELECT value FROM settings WHERE key='sf_copy_dir'").fetchone()
            return (r[0] or "").strip() if r else ""
        finally:
            k.close()
    except Exception:
        return ""


_LOOP = {"started": False}


def _loop():
    """Every hour: today's files into backups/files, and the second copy when its place can be reached."""
    time.sleep(90)
    while True:
        try:
            got = core.LOCK.acquire(timeout=10)
            if got:
                try:
                    with _BK_LOCK:
                        st = _read_status()
                        if (st.get("files_at") or "")[:10] != date.today().isoformat():
                            files_to_backup()
                        tgt = _read_target()
                        if tgt and os.path.isdir(tgt):
                            if not _latest_db_backup():
                                core.backup_now._orig("auto") if hasattr(core.backup_now, "_orig") else core.backup_now("auto")
                            second_copy(tgt)
                finally:
                    core.LOCK.release()
        except Exception:
            pass
        time.sleep(3600)


def backup_health(c):
    st = _read_status()
    tgt = setting(c, "sf_copy_dir") or ""
    days = int(float(setting(c, "sf_copy_days") or 7))
    n_data, s_data = _count_files(_files_dir())
    n_bk, s_bk = _count_files(os.path.join(core.BACKUP_DIR, "files"))
    db = _latest_db_backup()
    db_at = datetime.fromtimestamp(os.path.getmtime(db)).isoformat(timespec="seconds") if db else None
    copy_age = None
    if st.get("copy_at"):
        copy_age = (datetime.now() - datetime.fromisoformat(st["copy_at"])).days
    warn = []
    if not db:
        warn.append("No database backup yet.")
    if n_bk < n_data:
        warn.append("%d attached file(s) are not in the backup yet." % (n_data - n_bk))
    if not tgt:
        warn.append("No second copy: every backup is on the same disk as the data.")
    elif copy_age is None:
        warn.append("The second copy has not been made yet (is the drive plugged in?).")
    elif copy_age > days:
        warn.append("The last second copy is %d days old." % copy_age)
    return {"db_backup": os.path.basename(db) if db else None, "db_backup_at": db_at, "backup_dir": core.BACKUP_DIR,
            "files_dir": _files_dir(), "files_in_data": n_data, "files_bytes": s_data, "files_in_backup": n_bk,
            "files_backup_at": st.get("files_at"), "copy_dir": tgt, "copy_days": days, "copy_at": st.get("copy_at"),
            "copy_age_days": copy_age, "copy_error": st.get("copy_error") or st.get("files_error"),
            "test": st.get("test"), "ok": not warn, "warnings": warn}


@api("sf.backup_status", "admin", "view")
def sf_backup_status(c, u, a):
    return backup_health(c)


@api("sf.backup_set", "admin", "edit")
def sf_backup_set(c, u, a):
    tgt = (a.get("copy_dir") or "").strip().strip('"')
    if tgt:
        if not os.path.isdir(tgt):
            raise ApiError("BuildCore cannot reach %s. Plug in the drive or create the folder first, then save again." % tgt)
        real = os.path.normcase(os.path.abspath(tgt))
        for d in (core.DATA_DIR, core.BACKUP_DIR):
            dd = os.path.normcase(os.path.abspath(d))
            if real == dd or real.startswith(dd + os.sep):
                raise ApiError("Choose a place outside BuildCore's own data and backup folders (another drive is best).")
        try:
            probe = os.path.join(tgt, "_bco_write_test.tmp")
            with open(probe, "wb") as fh:
                fh.write(b"x")
            os.remove(probe)
        except OSError:
            raise ApiError("BuildCore cannot write to %s." % tgt)
    _set(c, "sf_copy_dir", tgt)
    if a.get("copy_days"):
        _set(c, "sf_copy_days", max(1, int(float(a["copy_days"]))))
    audit(c, u, "backup_copy_place", "settings", None, {"copy_dir": tgt})
    return backup_health(c)


@api("sf.backup_run", "admin", "edit")
def sf_backup_run(c, u, a):
    """A backup now: database, attached files, and the second copy if its place can be reached."""
    c.commit()
    with _BK_LOCK:
        path = core.backup_now._orig("manual") if hasattr(core.backup_now, "_orig") else core.backup_now("manual")
        r = files_to_backup()
        tgt = setting(c, "sf_copy_dir") or ""
        cp = second_copy(tgt, force=True) if tgt else {"ok": False, "reason": "No place for the second copy is set."}
    audit(c, u, "backup_run", "settings", None, {"db": os.path.basename(path), "files_copied": r["copied"], "second_copy": cp.get("ok")})
    out = backup_health(c)
    out["ran"] = {"db": os.path.basename(path), "files_copied": r["copied"], "second_copy": cp}
    return out


@api("sf.backup_test", "admin", "view")
def sf_backup_test(c, u, a):
    """Open the latest backup in a scratch copy and check it."""
    db = _latest_db_backup()
    if not db:
        raise ApiError("There is no backup to test yet.")
    import tempfile
    tmpd = tempfile.mkdtemp(prefix="bco_bktest_")
    try:
        t = os.path.join(tmpd, "test.db")
        shutil.copyfile(db, t)
        k = sqlite3.connect(t)
        try:
            ok = k.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            nv = k.execute("SELECT COUNT(*) FROM vouchers").fetchone()[0]
            nf = k.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            stored = [r[0] for r in k.execute("SELECT stored FROM files WHERE stored IS NOT NULL")]
        finally:
            k.close()
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)
    bkf = os.path.join(core.BACKUP_DIR, "files")
    missing = [s for s in stored if not os.path.exists(os.path.join(bkf, s))]
    res = {"at": datetime.now().isoformat(timespec="seconds"), "backup": os.path.basename(db), "ok": ok and not missing,
           "database_ok": ok, "vouchers": nv, "files_listed": nf, "files_missing_in_backup": len(missing)}
    st = _read_status()
    st["test"] = res
    _write_status(st)
    return res


@api("sf.files_restore", "admin", "edit")
def sf_files_restore(c, u, a):
    """Copy attached files that are missing from data/files back from backups/files or the second copy."""
    stored = [r["stored"] for r in q(c, "SELECT stored FROM files WHERE stored IS NOT NULL")]
    dst = _files_dir()
    os.makedirs(dst, exist_ok=True)
    srcs = [os.path.join(core.BACKUP_DIR, "files")]
    tgt = setting(c, "sf_copy_dir") or ""
    if tgt:
        srcs.append(os.path.join(tgt, "BuildCore_backup", _company_code(), "files"))
    back = still = 0
    for s in stored:
        t = os.path.join(dst, s)
        if os.path.exists(t):
            continue
        for d in srcs:
            f = os.path.join(d, s)
            if os.path.exists(f):
                shutil.copyfile(f, t)
                back += 1
                break
        else:
            still += 1
    audit(c, u, "files_restore", "files", None, {"brought_back": back, "still_missing": still})
    return {"brought_back": back, "still_missing": still}


# ═════════════════════════════ 2. trust the numbers (CPI and tender margin on one basis) ═════════════════════════════
def tn_on(c):
    return setting(c, "tn_on") == "1"


def _fix_evm(ev):
    rows = ev.get("rows") or []
    costed = [r for r in rows if r.get("bac") is not None]
    if not costed:
        return ev
    evs = sum(r.get("ev") or 0 for r in costed)
    acs = sum(r.get("ac") or 0 for r in costed)
    rev_c = sum(r.get("contract_amount") or 0 for r in costed)
    rev_all = sum(r.get("contract_amount") or 0 for r in rows)
    cost_c = sum((r.get("contract_qty") or 0) * (r.get("unit_budget") or 0) for r in costed)
    old = {k: ev.get(k) for k in ("cpi", "tender_margin", "forecast_margin", "margin_fade")}
    ev["cpi"] = round(evs / acs, 2) if acs > EPS else None
    ev["cv"] = round(evs - acs, 2)
    if rev_c > EPS:
        ev["tender_margin"] = round(100 * (rev_c - cost_c) / rev_c, 1)
    fr_c = sum(r.get("forecast_revenue") or 0 for r in costed)
    fr_all = sum(r.get("forecast_revenue") or 0 for r in rows)
    eac_c = sum(r.get("eac") or 0 for r in costed)
    eac_other = max(0.0, (ev.get("eac") or 0) - sum(r.get("eac") or 0 for r in rows))
    if fr_c > EPS:
        share = fr_c / fr_all if fr_all > EPS else 1.0
        ev["forecast_margin"] = round(100 * (fr_c - eac_c - eac_other * share) / fr_c, 1)
    fm = ev.get("forecast_margin")
    ev["margin_fade"] = round(ev["tender_margin"] - fm, 1) if ev.get("tender_margin") is not None and fm is not None else None
    ev["basis"] = {"items": len(rows), "costed": len(costed), "revenue_costed_pct": round(100 * rev_c / rev_all, 1) if rev_all else None,
                   "note": "CPI, tender margin and forecast margin are worked out on the %d of %d BOQ items that have a cost estimate (indirect cost shared by revenue)." % (len(costed), len(rows)),
                   "before": old}
    return ev


def _wrap_evm():
    import api_project as P
    orig = P.project_evm
    if getattr(orig, FLAG, False):
        return

    def project_evm(c, pid, asof):
        ev = orig(c, pid, asof)
        try:
            if tn_on(c):
                ev = _fix_evm(ev)
        except Exception:
            pass
        return ev
    for k in [k for k in getattr(orig, "__dict__", {}) if k.startswith("_bco")]:
        setattr(project_evm, k, getattr(orig, k))
    setattr(project_evm, FLAG, True)
    project_evm._orig = orig
    P.project_evm = project_evm


@api("sf.tn_preview", "accounts", "view")
def sf_tn_preview(c, u, a):
    import api_project as P
    out = []
    for p in q(c, "SELECT id, code, name FROM projects WHERE status='active' AND COALESCE(kind,'') NOT IN ('trading','general') ORDER BY code"):
        try:
            raw = P.project_evm._orig(c, p["id"], today()) if hasattr(P.project_evm, "_orig") else P.project_evm(c, p["id"], today())
            before = {k: raw.get(k) for k in ("cpi", "tender_margin", "forecast_margin", "margin_fade")}
            fixed = _fix_evm(dict(raw))
            after = {k: fixed.get(k) for k in ("cpi", "tender_margin", "forecast_margin", "margin_fade")}
            out.append({"project": p["code"], "name": p["name"], "before": before, "after": after, "basis": (fixed.get("basis") or {}).get("note")})
        except Exception as e:
            out.append({"project": p["code"], "name": p["name"], "error": str(e)})
    return {"on": tn_on(c), "projects": out}


# ═════════════════════════════ 3. kept results never outlive their connection ═════════════════════════════
def _fix_memo():
    try:
        import api_pfp as F
    except Exception:
        return
    if getattr(F, "_bco249memo", False):
        return
    import copy as _copy
    MEMO = F._MEMO

    def _memo_get(c, key):
        tc = getattr(c, "total_changes", None)
        if tc is None:
            return None
        hit = MEMO.get((id(c), tc) + key)
        if not (isinstance(hit, tuple) and len(hit) == 2 and hit[0] is c):
            return None
        return _copy.deepcopy(hit[1])

    def _memo_put(c, key, value):
        tc = getattr(c, "total_changes", None)
        if tc is None:
            return
        if len(MEMO) > 400:
            MEMO.clear()
        # the connection itself is kept with the result, so its number cannot be reused while the result is kept
        MEMO[(id(c), tc) + key] = (c, _copy.deepcopy(value))
    MEMO.clear()
    F._memo_get, F._memo_put = _memo_get, _memo_put
    F._bco249memo = True


# ═════════════════════════════ 4. levelling leaves started work alone ═════════════════════════════
def _w_level(orig):
    def res_level(c, u, a):
        apply = a.get("apply")
        b = dict(a)
        b["apply"] = False
        r = orig(c, u, b)
        started = {x["id"] for x in q(c, "SELECT id FROM activities WHERE project_id=? AND (actual_start IS NOT NULL AND actual_start<>'' "
                                          "OR COALESCE(actual_qty,0)>0 OR COALESCE(pct_complete,0)>0)", (int(a["project_id"]),))}
        kept = [m for m in r.get("moves") or [] if m["id"] not in started]
        skipped = [m for m in r.get("moves") or [] if m["id"] in started]
        if apply and kept:
            for m in kept:
                core.upd(c, "activities", m["id"], {"constraint_type": "SNET", "constraint_date": m["to"]})
            audit(c, u, "level", "schedule", int(a["project_id"]), {"moved": len(kept), "started_left_alone": len(skipped)})
        r["moves"] = kept
        r["started_not_moved"] = [{"code": m["code"], "name": m["name"]} for m in skipped]
        r["applied"] = bool(apply and kept)
        return r
    return res_level


# ═════════════════════════════ 5. periods on the real Nepali calendar ═════════════════════════════
def _fy_year(fy):
    try:
        return int(str(fy)[:4])
    except ValueError:
        return None


def true_months(fy):
    """The 12 real Nepali months of a fiscal year 'YYYY-YY' (Shrawan YYYY .. Asar YYYY+1) as (start, end)."""
    import sched_calc as SC
    y = _fy_year(fy)
    if not y or y < 2000 or y > 2200:
        return None
    out = []
    for i in range(12):
        m, yy = (4 + i, y) if i < 9 else (i - 8, y + 1)
        s = SC.bs_to_ad(yy, m, 1)
        nm, ny = (m + 1, yy) if m < 12 else (1, yy + 1)
        e = SC.bs_to_ad(ny, nm, 1) - timedelta(days=1)
        out.append((s.isoformat(), e.isoformat()))
    return out


def period_check(c):
    out = []
    for fy in [r["fy"] for r in q(c, "SELECT DISTINCT fy FROM fiscal_periods ORDER BY fy")]:
        tm = true_months(fy)
        rows = q(c, "SELECT * FROM fiscal_periods WHERE fy=? ORDER BY start_date", (fy,))
        if not tm or len(rows) != 12:
            continue
        for i, p in enumerate(rows):
            s, e = tm[i]
            if p["start_date"] != s or p["end_date"] != e:
                out.append({"id": p["id"], "fy": fy, "code": p["code"], "status": p["status"], "start": p["start_date"], "end": p["end_date"],
                            "true_start": s, "true_end": e})
    return out


def _period_of(c, d, changes):
    for x in changes:
        if x["true_start"] <= d <= x["true_end"]:
            return x["id"]
    r = q1(c, "SELECT id FROM fiscal_periods WHERE start_date<=? AND end_date>=?", (d, d))
    return r["id"] if r else None


@api("sf.periods_check", "accounts", "view")
def sf_periods_check(c, u, a):
    ch = period_check(c)
    return {"changes": ch, "problems": _period_problems(c, ch)}


def _period_problems(c, ch):
    """A voucher must not move from a closed / locked month into another month, nor into one."""
    if not ch:
        return []
    status = {r["id"]: r["status"] for r in q(c, "SELECT id, status FROM fiscal_periods")}
    probs = []
    lo = min(x["start"] for x in ch + [{"start": x["true_start"]} for x in ch])
    hi = max(x["end"] for x in ch + [{"end": x["true_end"]} for x in ch])
    for v in q(c, "SELECT id, no, date FROM vouchers WHERE date BETWEEN ? AND ? AND COALESCE(status,'')<>'cancelled'", (lo, hi)):
        now_p = q1(c, "SELECT id FROM fiscal_periods WHERE start_date<=? AND end_date>=?", (v["date"], v["date"]))
        now_id = now_p["id"] if now_p else None
        new_id = _period_of(c, v["date"], ch)
        if now_id != new_id and (status.get(now_id) not in (None, "open") or status.get(new_id) not in (None, "open")):
            probs.append({"voucher": v["no"], "date": v["date"]})
    return probs[:50]


@api("sf.periods_fix", "accounts", "approve")
def sf_periods_fix(c, u, a):
    ch = period_check(c)
    if not ch:
        return {"fixed": 0}
    probs = _period_problems(c, ch)
    if probs:
        raise ApiError("Not changed: %d voucher(s) would move between a closed and an open month (first: %s of %s). "
                       "Open those months first, correct the dates, then close them again." % (len(probs), probs[0]["voucher"], probs[0]["date"]))
    # two passes so that a moved boundary never overlaps for a moment
    for x in ch:
        c.execute("UPDATE fiscal_periods SET start_date=?, end_date=? WHERE id=?", ("~" + x["true_start"], "~" + x["true_end"], x["id"]))
    for x in ch:
        c.execute("UPDATE fiscal_periods SET start_date=?, end_date=? WHERE id=?", (x["true_start"], x["true_end"], x["id"]))
    audit(c, u, "periods_corrected", "fiscal_periods", None, {"changed": [{"code": x["code"], "from": [x["start"], x["end"]], "to": [x["true_start"], x["true_end"]]} for x in ch]})
    return {"fixed": len(ch)}


def _w_period_generate(orig):
    def period_generate(c, u, a):
        tm = true_months(a.get("fy"))
        if not tm or a.get("start_date") != tm[0][0]:
            return orig(c, u, a)
        import api_finance as F
        if val(c, "SELECT COUNT(*) FROM fiscal_periods WHERE fy=?", (a["fy"],)):
            raise ApiError("Periods for %s already exist." % a["fy"])
        for s_, e_ in tm:
            if F.period_for(c, s_) or F.period_for(c, e_):
                raise ApiError("New periods overlap existing ones.")
        for i, (s_, e_) in enumerate(tm):
            core.ins(c, "fiscal_periods", {"fy": a["fy"], "code": "%s-%02d %s" % (a["fy"], i + 1, F.BS_MONTHS[i]),
                                           "start_date": s_, "end_date": e_, "status": "open"})
        return True
    return period_generate


# ═════════════════════════════ 6. staff import with a project column ═════════════════════════════
def _staff_import_spec():
    try:
        import api_books as B
    except Exception:
        return
    spec = B.IMPORTS.get("staff")
    if not spec or any(f[0] == "project" for f in spec[3]):
        return
    fields = list(spec[3]) + [("project", False, ["project code", "site", "project name", "posted at"])]
    B.IMPORTS["staff"] = (spec[0], spec[1], spec[2], fields, spec[4])


def _w_master_save(orig):
    def master_save(c, u, a):
        if a.get("table") == "staff" and isinstance(a.get("row"), dict) and "project" in a["row"]:
            row = dict(a["row"])
            pv = row.pop("project")
            if pv not in (None, ""):
                import api_grnimp
                try:
                    row["project_id"] = api_grnimp.find_project(c, pv)["id"]
                except ValueError as e:
                    raise ApiError(str(e))
            a = dict(a)
            a["row"] = row
        return orig(c, u, a)
    return master_save


# ═════════════════════════════ 7. Tally features that are not built ═════════════════════════════
def _tally_labels():
    try:
        import api_tally as T
    except Exception:
        return
    for k in list(T.LATER):
        T.LATER[k] = "a later version (planned, not built yet)"


# ═════════════════════════════ 8. setup and switches ═════════════════════════════
def _projects(c):
    return q(c, "SELECT id, code, name, contract_value FROM projects WHERE status='active' AND COALESCE(kind,'') NOT IN ('trading','general') ORDER BY code")


def _prev_bs_month():
    import sched_calc as SC
    y, m, _d = SC.ad_to_bs(date.today())
    m -= 1
    if m < 1:
        y, m = y - 1, 12
    return "%04d-%02d" % (y, m), "%s %d" % (SC.BS_MONTHS[m - 1], y)


SWITCHES = [
    # key, label, what it changes, on-value test, where, right needed, order
    ("tn_on", "Trust the numbers (CPI and tender margin on one basis)", "CPI and tender margin use only BOQ items with a cost estimate, the same items as the forecast.",
     lambda v: v == "1", "#/admin/setup", "accounts approve", 1),
    ("pfp_on", "One project position", "Every project screen shows the same cost, forecast and profit.", lambda v: v == "1",
     "#/cl/cvr", "accounts approve", 2),
    ("run_months", "Monthly runs by Nepali month", "Depreciation, hire and salary runs go by Nepali month, like the close and logsheets.",
     lambda v: v == "nepali", "#/cl/cvr", "accounts approve", 3),
    ("pp_con_register", "One contract register", "Contract value, retention, advance and bonds come from one register.", lambda v: v == "1",
     "#/c/contracts", "commercial approve", 4),
    ("bx_on", "BOQ short codes and summary", "Each BOQ line gets a location + item short code; summaries by item.", lambda v: v == "1",
     "#/p/boq", "commercial approve", 5),
    ("mt_on", "Match receipts, bills and payments", "Purchase bills are matched to goods received; gaps and over-billing are shown.", lambda v: v == "1",
     "#/proc/invoices", "accounts approve", 6),
    ("pp_need_bill", "Papers before posting: purchase bills", "A bill needs its scan or photo before it is posted.", lambda v: v == "1",
     "#/acc/payments", "accounts approve", 7),
    ("pp_need_payment", "Papers before posting: payments", "A payment needs its paper before it is posted.", lambda v: v == "1",
     "#/acc/payments", "accounts approve", 7),
    ("mn_payreq_required", "Payments need an approved payment request", "Supplier, subcontractor and hire payments are made from an approved request.",
     lambda v: v == "1", "#/acc/payments", "accounts approve", 8),
    ("tl_on", "Tally-style Gateway", "Accounts > Gateway with groups, voucher types and keyboard entry.", lambda v: v == "1",
     "#/acc/gw", "accounts approve", 9),
    ("po_budget_block", "Over-budget PO needs an administrator", "A purchase order above the budget left waits for an administrator.",
     lambda v: v == "1", "#/cl/cvr", "accounts approve", 10),
    ("eqcc_from", "Equipment cost centre (EQUIP)", "Own machines' cost is kept in one cost centre and charged out by the hour.",
     lambda v: bool(v), "#/cl/cvr", "accounts approve", 10),
    ("gl_on", "Informative dashboard", "Grouped alerts, This month panel.", lambda v: v == "1", "#/dashboard", "display only", 11),
    ("pr_price_fill", "Past prices on PR / PO", "Rates filled from the project's own past receipts.", lambda v: v == "1", "#/proc/pr", "setting", 11),
]


@api("sf.setup")
def sf_setup(c, u, a):
    steps = []
    hb = backup_health(c) if _is_admin(u) else None
    if hb is not None:
        steps.append({"key": "backup", "title": "Second backup copy away from this computer", "done": bool(hb["copy_dir"]) and hb["copy_age_days"] is not None and hb["copy_age_days"] <= hb["copy_days"],
                      "detail": "; ".join(hb["warnings"]) or "Backups and attached files are copied to %s." % hb["copy_dir"], "href": "#/admin/backup", "link": "Backup & restore"})
    cb = q(c, "SELECT a.id FROM accounts a WHERE a.role IN ('cash','bank') AND (COALESCE(a.opening_balance,0)<>0 OR EXISTS(SELECT 1 FROM voucher_lines l WHERE l.account_id=a.id))")
    steps.append({"key": "cash", "title": "Bank and cash opening balances", "done": bool(cb),
                  "detail": "Entered." if cb else "No bank or cash account has an opening balance or any entry, so cash today and the cash forecast start from 0.",
                  "href": "#/acc/coa", "link": "Chart of accounts"})
    mism = []
    nob = []
    for p in _projects(c):
        boq = val(c, "SELECT SUM(qty*rate) FROM boq_items WHERE project_id=?", (p["id"],)) or 0
        cv = p["contract_value"] or 0
        if boq and cv and abs(boq - cv) > 0.01 * max(boq, cv):
            mism.append("%s (BOQ %s, contract %s)" % (p["code"], "{:,.0f}".format(boq), "{:,.0f}".format(cv)))
        elif boq and not cv:
            mism.append("%s (no contract value)" % p["code"])
        if not val(c, "SELECT COUNT(*) FROM cl_budget_versions WHERE project_id=? AND kind='current' AND status='approved'", (p["id"],)):
            nob.append(p["code"])
    steps.append({"key": "value", "title": "Contract value agrees with the BOQ total", "done": not mism,
                  "detail": ("Differs on: " + ", ".join(mism)) if mism else "Agrees on every project.", "href": "#/m/projects", "link": "Projects"})
    steps.append({"key": "budget", "title": "Approved control budget on every project", "done": not nob,
                  "detail": ("Missing on: " + ", ".join(nob) + ". Control budget > From rate analysis, then approve.") if nob else "Every project has one.",
                  "href": "#/cl/budget", "link": "Control budget"})
    per = period_check(c)
    steps.append({"key": "periods", "title": "Accounting periods follow the Nepali calendar", "done": not per,
                  "detail": ("%d period(s) end on the wrong day (for example %s ends %s, the Nepali month ends %s)." % (len(per), per[0]["code"], per[0]["end"], per[0]["true_end"])) if per else "All periods match.",
                  "href": "#/admin/setup?fix=periods", "link": "Correct the dates", "action": "periods" if per else None})
    pm, pl = _prev_bs_month()
    notclosed = [p["code"] for p in _projects(c) if not val(c, "SELECT COUNT(*) FROM cl_closes WHERE project_id=? AND status='locked' AND period>=?", (p["id"], pm))]
    steps.append({"key": "close", "title": "Last Nepali month (%s) closed and locked" % pl, "done": not notclosed,
                  "detail": ("Not locked on: " + ", ".join(notclosed) + ". The margin trend and 'margin deteriorating' alert need it.") if notclosed else "Locked.",
                  "href": "#/cl/close", "link": "Project close"})
    sw = []
    for key, label, what, test, href, right, order in SWITCHES:
        v = setting(c, key) or ""
        sw.append({"key": key, "label": label, "what": what, "on": bool(test(v)), "value": v, "href": href, "right": right, "order": order})
    sw.sort(key=lambda x: x["order"])
    return {"steps": steps, "switches": sw, "can_switch_tn": core.can(u, "accounts", "approve"), "version": VERSION}


@api("sf.switch", "accounts", "approve")
def sf_switch(c, u, a):
    key = a.get("key")
    if key != "tn_on":
        raise ApiError("This switch is turned on from its own screen (see the link).")
    v = "1" if a.get("on") in (True, 1, "1", "true") else "0"
    old = setting(c, key)
    _set(c, key, v)
    audit(c, u, "switch", "settings", None, {"key": key, "from": old, "to": v})
    return {"key": key, "on": v == "1"}


# ═════════════════════════════ 9. usage report ═════════════════════════════
USAGE = [
    # menu group, screen, path, table, date column
    ("Site work", "Daily progress (DPR)", "p/dpr", "dpr", "date"), ("Site work", "Schedule & WBS (activities)", "p/schedule", "activities", None),
    ("Site work", "Quality tests", "p/quality", "qa_tests", "sampled_date"), ("Site work", "NCRs", "p/quality", "ncrs", "date"),
    ("Site work", "Documents & photos", "p/docs", "files", "date"), ("Site work", "Drawings (field)", "f/drawings", "fld_drawings", None),
    ("Site work", "Issues & punch list", "f/issues", "fld_issues", "ts"), ("Site work", "RFIs", "f/rfis", "fld_rfis", None),
    ("Site work", "Inspections", "f/inspections", "fld_inspections", "date"), ("Site work", "Meetings", "f/meetings", "fld_meetings", None),
    ("Site work", "Document control", "dm", "dm_docs", "ts"), ("Site work", "Transmittals", "dm/transmittals", "dm_transmittals", None),
    ("Site work", "Document library", "dl", "dl_docs", "added_at"), ("Site work", "Discussions", "cm", "cm_posts", "ts"),
    ("Site work", "Tasks", "p/tasks", "tasks", "ts"), ("Site work", "Events & claims", "p/events", "events", None),
    ("Site work", "Workers & safety (workers)", "hs", "hs_workers", None), ("Site work", "Safety incidents", "hs", "hs_incidents", None),
    ("Commercial", "BOQ items", "p/boq", "boq_items", None), ("Commercial", "Measurements", "p/measure", "measurements", "date"),
    ("Commercial", "IPC billing", "p/ipc", "ipc", "date"), ("Commercial", "Variations", "p/variations", "variations", "date"),
    ("Commercial", "Contracts & letters", "c/contracts", "contracts", "ts"), ("Commercial", "Subcontract work orders", "x/sub", "sc_orders", "date"),
    ("Commercial", "Subcontract bills", "x/sub", "sc_bills", "date"), ("Commercial", "Correspondence register", "ca/letters", "ca_letters", None),
    ("Commercial", "Notices & time bars", "ca/timebars", "ca_timebars", None), ("Commercial", "Claims register", "cr", "cr_claims", None),
    ("Commercial", "Bonds, guarantees & insurance", "ca/securities", "ca_securities", None), ("Commercial", "Contract documents (AI)", "c/docs", "ai_docs", None),
    ("Commercial", "Control budget lines", "cl/budget", "cl_budget_lines", None), ("Commercial", "Project close", "cl/close", "cl_closes", "ts"),
    ("Commercial", "Bids & markup", "c/bids", "bids", None), ("Commercial", "House & small job estimate", "dc/house", "house_estimates", None),
    ("Store", "Requisitions", "inv/mrq", "mrq", "date"), ("Store", "Goods received", "inv/grn", "grn", "date"), ("Store", "Issues", "inv/issue", "issues", "date"),
    ("Store", "Returns", "inv/return", "returns", "date"), ("Store", "Transfers", "inv/transfer", "transfers", "date"),
    ("Store", "Stock count", "inv/count", "stock_counts", "date"),
    ("Procurement", "Purchase requests", "proc/pr", "pr", "date"), ("Procurement", "Quotation comparison", "proc/cs", "cs", "date"),
    ("Procurement", "Purchase orders", "proc/po", "po", "date"), ("Procurement", "Purchase bills", "proc/invoices", "invoices", "date"),
    ("Procurement", "Trading sales", "proc/trade", "trade_moves", None), ("Procurement", "Vendor ratings", "proc/vendors", "vendor_ratings", None),
    ("Accounts", "Vouchers", "acc/vouchers", "vouchers", "date"), ("Accounts", "Payments & receipts", "acc/payments", "payments", "date"),
    ("Accounts", "Payment requests", "acc/payments", "fc_payreq", None), ("Accounts", "Ledger budgets (Budget vs actual)", "acc/budget", "budgets", None),
    ("Accounts", "Loans", "acc/cash", "loans", None), ("Accounts", "Salary runs", "acc/payments", "mn_salary_run", "date"),
    ("Accounts", "Wage sheets", "acc/payments", "mn_wage_sheet", None), ("Accounts", "Petty cash slips", "acc/payments", "mn_slips", None),
    ("Accounts", "Bank statement lines", "acc/bank", "mn_stmt", None),
    ("Equipment", "Machines", "eq/register", "equipment", None), ("Equipment", "Day-by-day log (logsheets)", "eq/logs", "logsheets", "date"),
    ("Equipment", "Monthly logsheets", "eq/books", "logbooks", None), ("Equipment", "Work orders", "eq/wo", "work_orders", None),
    ("Equipment", "Maintenance plans", "eq/maint", "maint_plans", None), ("Equipment", "Hire agreements", "eq/hire", "hire_agreements", None),
    ("Equipment", "Rental deductions", "x/rent", "rent_deductions", None),
    ("Assets", "Asset register (small and office assets)", "as/register", "assets", None), ("Assets", "Small asset pools", "x/pools", "sa_pools", None),
    ("Assets", "Capital register (fixed assets)", "fa/register", "fa_register", None), ("Assets", "Leases (NFRS 16)", "fa/leases", "fa_leases", None),
    ("Plant", "Plants (crusher, batching)", "pl/register", "plants", None), ("Plant", "Production runs", "pl/runs", "plant_runs", None),
    ("Plant", "Mix designs", "pl/mix", "mix_designs", None),
    ("Overview", "Risk register", "risks", "risks", None), ("Overview", "Saved reports (report generator)", "rg", "fcc_reports", None),
    ("Overview", "Copilot drafts", "copilot", "cop_drafts", None), ("Overview", "AI questions", "help", "ai_log", "ts"),
    ("Masters", "Staff", "m/staff", "staff", None), ("Masters", "Extra fields", "m/fields", "custom_fields", None),
    ("Masters", "Daily check lists", "m/checklists", "check_lists", None),
    ("Administration", "Site packs", "admin/sync", "site_packs", None),
]


def _table_cols(c, t):
    try:
        return [r[1] for r in c.execute("PRAGMA table_info(%s)" % t)]
    except sqlite3.Error:
        return []


@api("sf.usage", "admin", "view")
def sf_usage(c, u, a):
    rows = []
    tables = {r["name"] for r in q(c, "SELECT name FROM sqlite_master WHERE type='table'")}
    since = (date.today() - timedelta(days=90)).isoformat()
    for grp, label, path, table, dcol in USAGE:
        if table not in tables:
            rows.append({"group": grp, "screen": label, "path": path, "records": 0, "last": None, "recent": 0})
            continue
        cols = _table_cols(c, table)
        n = val(c, "SELECT COUNT(*) FROM %s" % table) or 0
        last = recent = None
        dc = dcol if dcol in cols else next((x for x in ("date", "ts", "created_at", "updated", "created") if x in cols), None)
        if dc and n:
            last = val(c, "SELECT MAX(substr(%s,1,10)) FROM %s" % (dc, table))
            recent = val(c, "SELECT COUNT(*) FROM %s WHERE substr(%s,1,10)>=?" % (table, dc), (since,))
        rows.append({"group": grp, "screen": label, "path": path, "records": n, "last": last, "recent": recent})
    feed = q(c, "SELECT kind, COUNT(*) n, MAX(substr(ts,1,10)) last FROM activity GROUP BY kind ORDER BY n DESC") if "activity" in tables else []
    unused = [r for r in rows if not r["records"]]
    return {"rows": rows, "feed": feed, "unused": len(unused), "since": since,
            "note": "Records each register holds on this company and the last date entered. A screen with no records has never been used here."}


# ═════════════════════════════ start-up ═════════════════════════════
@api("sf.flags")
def sf_flags(c, u, a):
    out = {"pfp_on": setting(c, "pfp_on") == "1", "tn_on": tn_on(c), "version": VERSION}
    if _is_admin(u):
        try:
            h = backup_health(c)
            out["backup_ok"] = h["ok"]
            out["backup_warnings"] = h["warnings"]
        except Exception:
            pass
    return out


def init_safe(c):
    if not val(c, "SELECT COUNT(*) FROM settings WHERE key='tn_on'"):
        used = val(c, "SELECT COUNT(*) FROM vouchers") or val(c, "SELECT COUNT(*) FROM boq_items")
        _set(c, "tn_on", "0" if used else "1")
    c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES('sf_copy_days', '7')")
    c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES('sf_copy_dir', '')")
    c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES('sf_installed', ?)", (today(),))
    c.commit()
    _wrap_backup_now()
    _wrap_evm()
    _fix_memo()
    _wrap("res.level", _w_level)
    _wrap("period.generate", _w_period_generate)
    _wrap("master.save", _w_master_save)
    _staff_import_spec()
    _tally_labels()
    if not _LOOP["started"]:
        _LOOP["started"] = True
        threading.Thread(target=_loop, daemon=True).start()
