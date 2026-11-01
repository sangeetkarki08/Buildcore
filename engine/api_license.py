"""
BuildCore licence keys (2.13).

Every computer that runs the BuildCore engine needs a licence key made for THAT computer:

  1. The computer shows its request code (from Windows' machine id - it survives reinstalling BuildCore,
     not reinstalling Windows).
  2. The administrator, on the admin computer - the only one holding the master key - makes a key for
     that request code: licensee name, valid until (or no end), how many users.
  3. The key is pasted (or its .lic file loaded) on the computer, and BuildCore opens.

Keys are signed with Ed25519. BuildCore carries only the PUBLIC key, so no copy of BuildCore can make a
key; the master (private) key lives on the admin computer, locked with a password. A key made for one
computer does not open another. Browsers on other computers that use this computer's BuildCore over
the office network need no key of their own - only computers that run BuildCore themselves do.

Installations that already had data before this update get 15 days to enter their key.
"""
import base64
import csv
import hashlib
import hmac
import io
import json
import os
import platform
import sys
import time
import uuid
from datetime import date, timedelta

import core
from core import ApiError, audit, q1, setting
from api_inventory import FUNCS, api

VERSION = "2.13.0"
PUBLIC_KEY = bytes.fromhex("186f431848d69079bf5348f43a94b0bd026f086aa9b2343189a9b120689f0606")
EPOCH = date(2024, 1, 1)
GRACE_DAYS = 15
ALLOW = {"auth.status", "license.status", "license.activate", "license.master_load"}


# ───────────────────────── Ed25519 (RFC 8032), pure Python ─────────────────────────
_P = 2 ** 255 - 19
_D = -121665 * pow(121666, _P - 2, _P) % _P
_Q = 2 ** 252 + 27742317777372353535851937790883648493
_I = pow(2, (_P - 1) // 4, _P)


def _hq(s):
    return int.from_bytes(hashlib.sha512(s).digest(), "little") % _Q


def _add(P, Q):
    A, B = (P[1] - P[0]) * (Q[1] - Q[0]) % _P, (P[1] + P[0]) * (Q[1] + Q[0]) % _P
    C, D = 2 * P[3] * Q[3] * _D % _P, 2 * P[2] * Q[2] % _P
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % _P, G * H % _P, F * G % _P, E * H % _P)


def _mul(s, P):
    R = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            R = _add(R, P)
        P = _add(P, P)
        s >>= 1
    return R


def _same(P, Q):
    return (P[0] * Q[2] - Q[0] * P[2]) % _P == 0 and (P[1] * Q[2] - Q[1] * P[2]) % _P == 0


def _xr(y, sign):
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _I % _P
    if (x * x - x2) % _P:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_GY = 4 * pow(5, _P - 2, _P) % _P
_GX = _xr(_GY, 0)
_G = (_GX, _GY, 1, _GX * _GY % _P)


def _enc(P):
    zi = pow(P[2], _P - 2, _P)
    x, y = P[0] * zi % _P, P[1] * zi % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _dec(s):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _xr(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


def _expand(seed):
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def ed_public(seed):
    return _enc(_mul(_expand(seed)[0], _G))


def ed_sign(seed, msg):
    a, prefix = _expand(seed)
    A = _enc(_mul(a, _G))
    r = _hq(prefix + msg)
    R = _enc(_mul(r, _G))
    return R + ((r + _hq(R + A + msg) * a) % _Q).to_bytes(32, "little")


def ed_verify(pub, msg, sig):
    if len(pub) != 32 or len(sig) != 64:
        return False
    A, R = _dec(pub), _dec(sig[:32])
    if not A or not R:
        return False
    s = int.from_bytes(sig[32:], "little")
    if s >= _Q:
        return False
    return _same(_mul(s, _G), _add(R, _mul(_hq(sig[:32] + pub + msg), A)))


# ───────────────────────── this computer ─────────────────────────
def _machine_guid():
    if sys.platform.startswith("win"):
        try:
            import winreg
            for flag in (getattr(winreg, "KEY_WOW64_64KEY", 0), 0):
                try:
                    k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                                       winreg.KEY_READ | flag)
                    v, _t = winreg.QueryValueEx(k, "MachineGuid")
                    if v:
                        return "win:" + str(v).lower()
                except OSError:
                    continue
        except ImportError:
            pass
    for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            v = open(p).read().strip()
            if v:
                return "unix:" + v
        except OSError:
            pass
    return "mac:%012x" % uuid.getnode()


_MID = []


def machine_hash():
    if not _MID:
        _MID.append(hashlib.sha256(("BuildCore-machine:" + _machine_guid()).encode()).digest()[:10])
    return _MID[0]


def _b32(b):
    return base64.b32encode(b).decode().rstrip("=")


def _unb32(s):
    s = "".join(ch for ch in str(s).upper() if ch.isalnum())
    s = s.replace("0", "O").replace("1", "I").replace("8", "B")
    return base64.b32decode(s + "=" * (-len(s) % 8))


def _group(s, n=5):
    return "-".join(s[i:i + n] for i in range(0, len(s), n))


def request_code(h=None):
    h = h or machine_hash()
    return _group(_b32(h + hashlib.sha256(h).digest()[:2]))


def parse_request(code):
    try:
        raw = _unb32(code)
    except Exception:
        raise ApiError("That request code is not readable - check it letter by letter.")
    clean = "".join(ch for ch in str(code).upper() if ch.isalnum())
    if len(raw) != 12 or hashlib.sha256(raw[:10]).digest()[:2] != raw[10:] or _b32(raw) != clean.replace("0", "O").replace("1", "I").replace("8", "B"):
        raise ApiError("That request code has a typing mistake - check it letter by letter (20 letters and digits).")
    return raw[:10]


# ───────────────────────── keys ─────────────────────────
def _day(d):
    return (d - EPOCH).days if d else 0


def _date(n):
    return EPOCH + timedelta(days=n) if n else None


def make_key(seed, mhash, licensee, expires=None, max_users=0, flags=0):
    name = (licensee or "").strip().encode("utf-8")[:60]
    payload = bytes([1]) + mhash + _day(expires).to_bytes(2, "big") + _day(date.today()).to_bytes(2, "big") \
        + bytes([max(0, min(255, int(max_users or 0))), flags & 255]) + name
    sig = ed_sign(seed, b"BCLIC1" + payload)
    return "BCK1-" + _group(_b32(payload + sig))


def read_key(text):
    t = "".join(str(text or "").split())
    if t.upper().startswith("BCK1-"):
        t = t[5:]
    try:
        raw = _unb32(t)
    except Exception:
        raise ApiError("That is not a BuildCore licence key.")
    if len(raw) < 17 + 64 or raw[0] != 1:
        raise ApiError("That is not a BuildCore licence key (or it is incomplete - copy all of it).")
    payload, sig = raw[:-64], raw[-64:]
    if not ed_verify(PUBLIC_KEY, b"BCLIC1" + payload, sig):
        raise ApiError("This licence key is not genuine or was changed while copying. Copy all of it again.")
    return {"machine": payload[1:11], "expires": _date(int.from_bytes(payload[11:13], "big")),
            "issued": _date(int.from_bytes(payload[13:15], "big")), "max_users": payload[15], "flags": payload[16],
            "licensee": payload[17:].decode("utf-8", "replace")}


# ───────────────────────── files on this computer ─────────────────────────
def _dir():
    d = os.path.join(core._ROOT, "licence")
    os.makedirs(d, exist_ok=True)
    return d


def _path(name):
    return os.path.join(_dir(), name)


def _read(name, default=None):
    try:
        with open(_path(name), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return default


def _write(name, text):
    p = _path(name)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(p + ".tmp", p)


def _state():
    try:
        return json.loads(_read("state.json", "{}") or "{}")
    except ValueError:
        return {}


def _save_state(st):
    _write("state.json", json.dumps(st))


# ───────────────────────── master key (admin computer only) ─────────────────────────
def _kdf(password, salt):
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=64)


def master_present():
    return os.path.exists(_path("master.bin"))


def master_seed(password):
    raw = _read("master.bin")
    if not raw:
        raise ApiError("This is not the admin computer - the master key is not here.")
    try:
        m = json.loads(raw)
        salt, ct, chk = (base64.b64decode(m[k]) for k in ("salt", "ct", "chk"))
    except Exception:
        raise ApiError("The master key file on this computer is damaged. Load it again from your backup.")
    k = _kdf(password or "", salt)
    seed = bytes(a ^ b for a, b in zip(ct, k[:32]))
    if not hmac.compare_digest(hmac.new(k[32:], seed, "sha256").digest()[:12], chk) or ed_public(seed) != PUBLIC_KEY:
        raise ApiError("Wrong master password.")
    return seed


def parse_master_file(text):
    lines = [x.strip() for x in str(text or "").splitlines() if x.strip() and not x.strip().startswith("#")]
    for ln in lines:
        try:
            raw = base64.b64decode(ln, validate=True)
        except Exception:
            continue
        if len(raw) == 32 and ed_public(raw) == PUBLIC_KEY:
            return raw
    raise ApiError("This is not the BuildCore master key file (or it belongs to another BuildCore).")


# ───────────────────────── status ─────────────────────────
_CACHE = {"t": 0, "v": None}


def status(force=False):
    if not force and _CACHE["v"] and time.time() - _CACHE["t"] < 30:
        return _CACHE["v"]
    st = _state()
    today_ = date.today()
    seen = max(today_, date.fromisoformat(st["last_seen"])) if st.get("last_seen") else today_
    if st.get("last_seen") != seen.isoformat():
        st["last_seen"] = seen.isoformat()
        try:
            _save_state(st)
        except OSError:
            pass
    out = {"active": False, "request_code": request_code(), "computer": platform.node(), "admin_pc": master_present(),
           "licensee": None, "expires": None, "max_users": 0, "days_left": None, "grace": False, "reason": "",
           "version": VERSION}
    key = _read("licence.key")
    if key:
        try:
            k = read_key(key)
            if k["machine"] != machine_hash():
                out["reason"] = "The licence key here was made for another computer."
            elif k["expires"] and seen > k["expires"]:
                out["reason"] = "The licence expired on %s." % k["expires"].isoformat()
                out["licensee"] = k["licensee"]
            else:
                out.update({"active": True, "licensee": k["licensee"], "max_users": k["max_users"],
                            "expires": k["expires"].isoformat() if k["expires"] else None,
                            "issued": k["issued"].isoformat() if k["issued"] else None,
                            "days_left": (k["expires"] - seen).days if k["expires"] else None})
        except ApiError as e:
            out["reason"] = str(e)
    if not out["active"] and out["admin_pc"]:
        out.update({"active": True, "licensee": "Admin computer (holds the master key)", "reason": ""})
    if not out["active"] and st.get("grace_until"):
        g = date.fromisoformat(st["grace_until"])
        if seen <= g:
            out.update({"active": True, "grace": True, "days_left": (g - seen).days,
                        "expires": g.isoformat(),
                        "reason": "No licence key yet - BuildCore works until %s. Enter the key before then." % g.isoformat()})
        elif not out["reason"]:
            out["reason"] = "The %d days to enter a licence key ended on %s." % (GRACE_DAYS, g.isoformat())
    if not out["active"] and not out["reason"]:
        out["reason"] = "BuildCore is not activated on this computer yet."
    _CACHE.update({"t": time.time(), "v": out})
    return out


def init_license(c):
    """Runs when a data file opens. Sets the 15-day period for installations that already had data,
    and puts the licence check in front of every request."""
    try:
        st = _state()
        db_g = setting(c, "licence_grace_until")
        if not st.get("first_run"):
            st["first_run"] = date.today().isoformat()
            users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            if db_g:
                st["grace_until"] = db_g          # the state file was removed: keep the period already given
            elif users:
                st["grace_until"] = (date.today() + timedelta(days=GRACE_DAYS)).isoformat()
            _save_state(st)
        if st.get("grace_until") and not db_g:
            c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('licence_grace_until', ?)", (st["grace_until"],))
        elif db_g and st.get("grace_until") and db_g < st["grace_until"]:
            st["grace_until"] = db_g
            _save_state(st)
        c.commit()
    except Exception as e:  # never stop BuildCore from starting
        print("BuildCore: licence set-up: %s" % e)
    _guard()


def _guard():
    for name in ("__main__", "server"):
        mod = sys.modules.get(name)
        if not mod or not hasattr(mod, "call") or not hasattr(mod, "Handler"):
            continue
        cur = mod.call
        if getattr(cur, "_bco_lic", False):
            continue

        def call(fn, args, token, ip=None, device=None, _orig=cur):
            if fn not in ALLOW and not status()["active"]:
                raise ApiError("Licence required: " + status()["reason"] + " Enter the licence key for this computer.")
            return _orig(fn, args, token, ip, device)
        call._bco_lic = True
        mod.call = call
    us = FUNCS.get("admin.user_save")
    if us and not getattr(us[0], "_bco_lic", False):
        orig = us[0]

        def user_save(c, u, a, _orig=orig):
            r = _orig(c, u, a)
            mx = status()["max_users"]
            if mx and c.execute("SELECT COUNT(*) FROM users WHERE active=1").fetchone()[0] > mx:
                raise ApiError("This licence allows %d active users. Switch someone off first, or ask for a key "
                               "with more users." % mx)
            return r
        user_save._bco_lic = True
        FUNCS["admin.user_save"] = (user_save,) + tuple(us[1:])


# ───────────────────────── endpoints ─────────────────────────
@api("license.status", public=True)
def lic_status(c, u, a):
    _guard()
    s = dict(status(force=True))
    if u:
        s["users_active"] = c.execute("SELECT COUNT(*) FROM users WHERE active=1").fetchone()[0]
    return s


@api("license.activate", public=True)
def lic_activate(c, u, a):
    k = read_key(a.get("key"))
    if k["machine"] != machine_hash():
        raise ApiError("This key was made for another computer. This computer's request code is %s - "
                       "ask for a key made for this code." % request_code())
    if k["expires"] and date.today() > k["expires"]:
        raise ApiError("This key expired on %s. Ask for a new one." % k["expires"].isoformat())
    old = _read("licence.key")
    if old:
        _write("licence.key.old", old)
    _write("licence.key", "".join(str(a.get("key")).split()) + "\n")
    s = status(force=True)
    try:
        audit(c, u, "activate", "licence", None, {"licensee": k["licensee"], "expires": s["expires"]})
    except Exception:
        pass
    return s


def _need_admin(u):
    if not u or u.get("role") != "admin":
        raise ApiError("Only an administrator can do this.")


@api("license.master_load", public=True)
def lic_master_load(c, u, a):
    """Make this the admin computer: load the master key file once and lock it with a password.
    Possession of the master key file is the authority, so this works before anyone signs in."""
    seed = parse_master_file(a.get("text"))
    pw = a.get("password") or ""
    if len(pw) < 8:
        raise ApiError("Choose a master password of at least 8 characters.")
    if master_present() and not a.get("replace"):
        raise ApiError("The master key is already on this computer.")
    salt = os.urandom(16)
    k = _kdf(pw, salt)
    _write("master.bin", json.dumps({"v": 1, "salt": base64.b64encode(salt).decode(),
                                     "ct": base64.b64encode(bytes(x ^ y for x, y in zip(seed, k[:32]))).decode(),
                                     "chk": base64.b64encode(hmac.new(k[32:], seed, "sha256").digest()[:12]).decode()}))
    return status(force=True)


@api("license.master_forget")
def lic_master_forget(c, u, a):
    _need_admin(u)
    master_seed(a.get("password"))
    try:
        os.remove(_path("master.bin"))
    except OSError:
        pass
    audit(c, u, "master_forget", "licence", None, {})
    return status(force=True)


@api("license.make")
def lic_make(c, u, a):
    _need_admin(u)
    seed = master_seed(a.get("password"))
    mh = parse_request(a.get("request_code"))
    name = (a.get("licensee") or "").strip()
    if not name:
        raise ApiError("Write who the licence is for (company / site).")
    exp = None
    if a.get("expires"):
        try:
            exp = date.fromisoformat(str(a["expires"])[:10])
        except ValueError:
            raise ApiError("Valid until must be a date.")
        if exp < date.today():
            raise ApiError("Valid until is in the past.")
    mu = int(a.get("max_users") or 0)
    key = make_key(seed, mh, name, exp, mu)
    rec = {"ts": core.now(), "request_code": request_code(mh), "licensee": name,
           "expires": exp.isoformat() if exp else "", "max_users": mu, "computer": (a.get("computer") or "").strip(),
           "note": (a.get("note") or "").strip(), "made_by": u.get("name") or u.get("username"), "key": key}
    new = not os.path.exists(_path("issued.csv"))
    with open(_path("issued.csv"), "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rec.keys()))
        if new:
            w.writeheader()
        w.writerow(rec)
    audit(c, u, "make_key", "licence", None, {k: v for k, v in rec.items() if k != "key"})
    return {"key": key, "filename": "BuildCore_%s.lic" % "".join(ch for ch in name if ch.isalnum())[:30], "record": rec}


@api("license.issued")
def lic_issued(c, u, a):
    _need_admin(u)
    if not master_present():
        return []
    txt = _read("issued.csv", "")
    return list(reversed(list(csv.DictReader(io.StringIO(txt))))) if txt else []
