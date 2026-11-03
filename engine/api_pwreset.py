"""
BuildCore 2.36 - forgotten passwords, offline.

Nothing here needs the internet. A person who forgot the sign-in password chooses a new one with:

  1. their own RECOVERY CODE - made once from the user menu (needs the current password), shown once,
     kept only as a hash; it is used up when it is used, and a new one can be made after signing in;
  2. a one-time RESET CODE from an administrator - Administration > Users, valid 24 hours by default
     (setting reset_code_hours), so the administrator never needs to know the new password;
  3. when every administrator is locked out:
       a. the BuildCore MASTER KEY FILE (.bckey) - whoever holds it is the authority (as for licence keys);
       b. a RESET KEY from the BuildCore supplier - the sign-in screen shows a reset request code; the
          supplier makes a key for it on the admin computer (Administration > Licence keys, master password);
          the key opens only that request, for that user, on that data file, once.

Also: "Forgot master password?" on the admin computer - load the master key file again and choose a new
master password (licence keys already issued keep working; the list of keys made is kept).

Wrong codes count as wrong passwords: 5 in a row lock the username for the usual minutes.
New table pw_codes only; nothing posts, no account, voucher, id or balance changes.
"""
import base64
import csv
import hashlib
import json
import os
import secrets
from datetime import date, datetime, timedelta

import core
from core import ApiError, audit, can, get, hash_pw, ins, now, q, q1, setting, val
import api_inventory as inv
from api_inventory import FUNCS, api

VERSION = "2.36.0"
ALPHA = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"      # no 0/O, no 1/I - nothing to misread
REQUEST_DAYS = 7

SCHEMA = """
CREATE TABLE IF NOT EXISTS pw_codes(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, kind TEXT NOT NULL,
  code_hash TEXT NOT NULL, salt TEXT NOT NULL, created TEXT, created_by INTEGER, expires TEXT,
  used_at TEXT, revoked_at TEXT);
CREATE INDEX IF NOT EXISTS ix_pw_codes_user ON pw_codes(user_id, kind);
"""


def init_pwreset(c):
    c.executescript(SCHEMA)
    c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES('reset_code_hours', '24')")
    c.commit()
    _wrap_users2()


# ───────────────────────── helpers ─────────────────────────
def _norm(code):
    return "".join(ch for ch in str(code or "").upper() if ch.isalnum())


def _new_code():
    raw = "".join(secrets.choice(ALPHA) for _ in range(20))
    return "-".join(raw[i:i + 5] for i in range(0, 20, 5))


def _lock_minutes(c):
    try:
        return int(float(setting(c, "lock_minutes") or 10))
    except ValueError:
        return 10


def _locked(c, name):
    since = (datetime.now() - timedelta(minutes=_lock_minutes(c))).isoformat(timespec="seconds")
    rec = q(c, "SELECT ok FROM login_attempts WHERE username=? AND ts>=? ORDER BY id DESC LIMIT 5", (name, since))
    return len(rec) == 5 and not any(r["ok"] for r in rec)


def _fail(c, name, ip, msg):
    """Count it like a wrong password, keep that record, then refuse."""
    ins(c, "login_attempts", {"ts": now(), "username": name, "ip": ip, "ok": 0})
    c.commit()
    raise ApiError(msg)


def _user(c, a):
    """The person named on the sign-in screen (username, or full name like the sign-in box accepts)."""
    name = (a.get("username") or "").strip().lower()
    if not name:
        raise ApiError("Type your username.")
    usr = q1(c, "SELECT * FROM users WHERE username=?", (name,))
    if not usr:
        byname = q(c, "SELECT * FROM users WHERE lower(trim(name))=? AND active=1", (name,))
        if len(byname) == 1:
            usr = byname[0]
    if not usr:
        coname = (setting(c, "company_name") or "this company").rstrip(".")
        raise ApiError("There is no user '%s' in %s. Check the company chosen above and the username." % (name, coname))
    if not usr["active"]:
        raise ApiError("User '%s' is switched off. Ask the administrator to tick Active in Administration > Users." % usr["username"])
    return usr


def _check_new(a):
    pw = a.get("password") or ""
    if len(pw) < 6:
        raise ApiError("The new password needs at least 6 characters.")
    if "password2" in a and a.get("password2") != pw:
        raise ApiError("The two new passwords are not the same.")
    return pw


def _set_password(c, usr, pw, how, ip, device):
    """Same storage as Administration > Users: new hash and salt, other sign-ins closed, lock cleared."""
    h, s = hash_pw(pw)
    c.execute("UPDATE users SET pw_hash=?, salt=? WHERE id=?", (h, s, usr["id"]))
    c.execute("DELETE FROM sessions WHERE user_id=?", (usr["id"],))
    c.execute("DELETE FROM login_attempts WHERE username=?", (usr["username"],))
    ins(c, "login_attempts", {"ts": now(), "username": usr["username"], "ip": ip, "ok": 1})
    audit(c, usr, "password_reset", "users", usr["id"], {"how": how, "ip": ip})
    out = inv.login_user(c, usr["id"], ip, device)
    out["username"] = usr["username"]
    return out


def _is_admin(usr):
    try:
        return usr["role"] == "admin" or can(usr, "admin", "edit")
    except Exception:
        return usr["role"] == "admin"


def _active_codes(c, uid, kind=None):
    sql = "SELECT * FROM pw_codes WHERE user_id=? AND used_at IS NULL AND revoked_at IS NULL AND (expires IS NULL OR expires>=?)"
    args = [uid, now()]
    if kind:
        sql += " AND kind=?"
        args.append(kind)
    return q(c, sql + " ORDER BY id DESC", tuple(args))


def _store_code(c, uid, kind, by, hours=None):
    c.execute("UPDATE pw_codes SET revoked_at=? WHERE user_id=? AND kind=? AND used_at IS NULL AND revoked_at IS NULL",
              (now(), uid, kind))
    code = _new_code()
    h, s = hash_pw(_norm(code))
    exp = (datetime.now() + timedelta(hours=hours)).isoformat(timespec="seconds") if hours else None
    ins(c, "pw_codes", {"user_id": uid, "kind": kind, "code_hash": h, "salt": s, "created": now(),
                        "created_by": by, "expires": exp})
    return code, exp


# ───────────────────────── recovery code (the person's own) ─────────────────────────
@api("auth.recovery_status")
def recovery_status(c, u, a):
    r = _active_codes(c, u["id"], "recovery")
    return {"has_code": bool(r), "created": r[0]["created"] if r else None}


@api("auth.recovery_make")
def recovery_make(c, u, a):
    if hash_pw(a.get("password") or "", u["salt"])[0] != u["pw_hash"]:
        raise ApiError("Your current password is wrong.")
    code, _exp = _store_code(c, u["id"], "recovery", u["id"])
    audit(c, u, "recovery_code", "users", u["id"], {})
    return {"code": code, "username": u["username"], "company": setting(c, "company_name")}


# ───────────────────────── reset code (made by an administrator) ─────────────────────────
@api("adm.reset_code", "admin", "edit")
def adm_reset_code(c, u, a):
    usr = get(c, "users", int(a["id"]), "User")
    if not usr["active"]:
        raise ApiError("User '%s' is switched off. Tick Active first." % usr["username"])
    try:
        hours = max(1, min(24 * 14, int(float(setting(c, "reset_code_hours") or 24))))
    except ValueError:
        hours = 24
    code, exp = _store_code(c, usr["id"], "reset", u["id"], hours)
    audit(c, u, "reset_code", "users", usr["id"], {"expires": exp})
    return {"code": code, "username": usr["username"], "name": usr["name"], "expires": exp, "hours": hours}


# ───────────────────────── sign-in screen: use a code ─────────────────────────
@api("auth.forgot_code", public=True)
def forgot_code(c, u, a):
    usr = _user(c, a)
    ip = a.get("_ip")
    if _locked(c, usr["username"]):
        raise ApiError("Too many wrong tries for '%s'. Wait %d minutes, or ask your administrator." %
                       (usr["username"], _lock_minutes(c)))
    code = _norm(a.get("code"))
    if not code:
        raise ApiError("Type the code.")
    pw = _check_new(a)
    hit = None
    for r in _active_codes(c, usr["id"]):
        if hash_pw(code, r["salt"])[0] == r["code_hash"]:
            hit = r
            break
    if not hit:
        _fail(c, usr["username"], ip, "That code is not right for '%s' (or it was used, replaced or has expired). "
              "A recovery code works once; a reset code from the administrator works once and only for a day." % usr["username"])
    c.execute("UPDATE pw_codes SET used_at=? WHERE id=?", (now(), hit["id"]))
    out = _set_password(c, usr, pw, hit["kind"] + " code", ip, a.get("_device"))
    out["kind"] = hit["kind"]
    return out


# ───────────────────────── every administrator locked out: master key file ─────────────────────────
def _lic():
    import api_license
    return api_license


@api("auth.forgot_bckey", public=True)
def forgot_bckey(c, u, a):
    usr = _user(c, a)
    pw = _check_new(a)
    try:
        _lic().parse_master_file(a.get("text"))
    except ApiError:
        _fail(c, usr["username"], a.get("_ip"), "This is not the BuildCore master key file (.bckey).")
    return _set_password(c, usr, pw, "master key file", a.get("_ip"), a.get("_device"))


# ───────────────────────── every administrator locked out: reset key from the supplier ─────────────────────────
def _req_check(body):
    return hashlib.sha256(b"BCPWR-request:" + body).digest()[:2]


def _pending(c):
    try:
        p = json.loads(setting(c, "pw_reset_request") or "{}")
    except ValueError:
        return {}
    if not p.get("created") or p["created"] < (datetime.now() - timedelta(days=REQUEST_DAYS)).isoformat(timespec="seconds"):
        return {}
    return p


def _request_code(nonce, uid):
    L = _lic()
    body = nonce + int(uid).to_bytes(2, "big")
    return L._group(L._b32(body + _req_check(body)))


def parse_reset_request(code):
    L = _lic()
    try:
        raw = L._unb32(code)
    except Exception:
        raise ApiError("That reset request code is not readable - check it letter by letter.")
    if len(raw) != 12 or _req_check(raw[:10]) != raw[10:]:
        raise ApiError("That is not a password reset request code (20 letters and digits from the sign-in screen's "
                       "Forgot password). A licence request code goes in 'Make a licence key' above.")
    return raw[:10]


def make_reset_key(seed, body):
    L = _lic()
    payload = bytes([1]) + body + L._day(date.today()).to_bytes(2, "big")
    return "BCR1-" + L._group(L._b32(payload + L.ed_sign(seed, b"BCPWR1" + payload)))


def read_reset_key(text):
    L = _lic()
    t = "".join(str(text or "").split())
    if t.upper().startswith("BCR1-"):
        t = t[5:]
    try:
        raw = L._unb32(t)
    except Exception:
        raise ApiError("That is not a BuildCore password reset key.")
    if len(raw) != 13 + 64 or raw[0] != 1:
        raise ApiError("That is not a BuildCore password reset key (or it is incomplete - copy all of it).")
    payload, sig = raw[:-64], raw[-64:]
    if not L.ed_verify(L.PUBLIC_KEY, b"BCPWR1" + payload, sig):
        raise ApiError("This reset key is not genuine or was changed while copying. Copy all of it again.")
    return {"body": payload[1:11], "issued": L._date(int.from_bytes(payload[11:13], "big"))}


@api("auth.forgot_request", public=True)
def forgot_request(c, u, a):
    """Reset request code for the supplier. Only for administrators; others ask an administrator."""
    usr = _user(c, a)
    if not _is_admin(usr):
        raise ApiError("'%s' is not an administrator. Ask your administrator for a reset code "
                       "(Administration > Users > Reset code)." % usr["username"])
    p = _pending(c)
    if not p or p.get("user_id") != usr["id"]:
        p = {"user_id": usr["id"], "nonce": secrets.token_hex(8), "created": now()}
        c.execute("INSERT INTO settings(key, value) VALUES('pw_reset_request', ?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(p),))
        audit(c, usr, "reset_request", "users", usr["id"], {"ip": a.get("_ip")})
    until = (datetime.fromisoformat(p["created"]) + timedelta(days=REQUEST_DAYS)).date().isoformat()
    return {"request_code": _request_code(bytes.fromhex(p["nonce"]), usr["id"]), "username": usr["username"],
            "valid_until": until, "company": setting(c, "company_name")}


@api("auth.forgot_key", public=True)
def forgot_key(c, u, a):
    usr = _user(c, a)
    ip = a.get("_ip")
    if _locked(c, usr["username"]):
        raise ApiError("Too many wrong tries for '%s'. Wait %d minutes." % (usr["username"], _lock_minutes(c)))
    pw = _check_new(a)
    try:
        k = read_reset_key(a.get("key"))
    except ApiError as e:
        _fail(c, usr["username"], ip, str(e))
    p = _pending(c)
    if not p or p.get("user_id") != usr["id"]:
        raise ApiError("There is no open reset request for '%s' on this company (or it is older than %d days). "
                       "Press 'Get reset request code' and send the new code." % (usr["username"], REQUEST_DAYS))
    if k["body"] != bytes.fromhex(p["nonce"]) + int(usr["id"]).to_bytes(2, "big"):
        _fail(c, usr["username"], ip, "This reset key was made for another request code. The code to send is %s."
              % _request_code(bytes.fromhex(p["nonce"]), usr["id"]))
    c.execute("DELETE FROM settings WHERE key='pw_reset_request'")
    return _set_password(c, usr, pw, "supplier reset key", ip, a.get("_device"))


# ───────────────────────── admin computer: make a reset key; forgot master password ─────────────────────────
@api("license.pwreset_make")
def lic_pwreset_make(c, u, a):
    L = _lic()
    L._need_admin(u)
    seed = L.master_seed(a.get("password"))
    body = parse_reset_request(a.get("request_code"))
    key = make_reset_key(seed, body)
    rec = {"ts": core.now(), "request_code": _request_code(body[:8], int.from_bytes(body[8:], "big")),
           "for": (a.get("for") or "").strip(), "note": (a.get("note") or "").strip(),
           "made_by": u.get("name") or u.get("username"), "key": key}
    path = L._path("pwreset.csv")
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rec.keys()))
        if new:
            w.writeheader()
        w.writerow(rec)
    audit(c, u, "make_reset_key", "licence", None, {k: v for k, v in rec.items() if k != "key"})
    return {"key": key, "record": rec}


@api("license.master_reset")
def lic_master_reset(c, u, a):
    """Forgot the master password: the master key file itself is the authority. Load it again with a new password."""
    L = _lic()
    L._need_admin(u)
    if a.get("password") != a.get("password2"):
        raise ApiError("The two passwords are different.")
    L.parse_master_file(a.get("text"))
    s = FUNCS["license.master_load"][0](c, u, {"text": a.get("text"), "password": a.get("password"), "replace": True})
    audit(c, u, "master_reset", "licence", None, {})
    return s


# ───────────────────────── Administration > Users: who has a recovery code ─────────────────────────
def _wrap_users2():
    cur = FUNCS.get("adm.users2")
    if not cur or getattr(cur[0], "_bco236", False):
        return
    orig = cur[0]

    def users2(c, u, a):
        rows = orig(c, u, a)
        have = {r["user_id"]: r["kind"] for r in q(
            c, "SELECT user_id, GROUP_CONCAT(DISTINCT kind) kind FROM pw_codes WHERE used_at IS NULL AND revoked_at IS NULL "
               "AND (expires IS NULL OR expires>=?) GROUP BY user_id", (now(),))}
        for r in rows:
            k = have.get(r["id"]) or ""
            r["recovery"] = "recovery" in k
            r["reset_open"] = "reset" in k
        return rows
    users2._bco236 = True
    FUNCS["adm.users2"] = (users2,) + tuple(cur[1:])
