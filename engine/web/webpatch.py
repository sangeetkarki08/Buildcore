"""What the web edition does differently from the desktop engine, applied around it at start-up.

The desktop files are not edited. Each change here replaces one desktop behaviour that needs a computer's
own disk or a program that keeps running:

  * the server is reached over the internet (Vercel), so the office-network check is off; sign-in protects it
  * companies list, licence files, background jobs -> kept in the database (table web_kv)
  * attachments and backups -> Supabase Storage (private bucket), opened through short-lived signed links
  * backup = the company's data written as a desktop data file; restore = a desktop data file imported
  * the first administrator can only be created with the setup key from the Vercel settings (BCO_SETUP_KEY)
  * role templates are read again on every request, because several server copies may be running
"""
import hashlib
import hmac
import json
import mimetypes
import os
import re
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime
from urllib.parse import parse_qs, quote, urlparse

from web import pgsqlite, storage

_LOCAL = threading.local()
_GATE = threading.BoundedSemaphore(max(1, int(os.environ.get("BCO_MAX_PARALLEL") or 3)))


def main_path():
    return os.path.join(os.environ["BCO_DATA_DIR"], "data", "buildcore.db")


def current_schema():
    import core
    return pgsqlite.schema_for_path(core.DB_PATH)


# ───────────────────────── small key-value store in the database ─────────────────────────
_KV_READY = []


def _kv_conn():
    c = pgsqlite.connect(main_path())
    # the licence state is written from inside a request that already holds the company lock (the main
    # company shares this schema); one upsert needs no lock, and taking it here would wait on itself
    c.no_lock = True
    if not _KV_READY:
        c.execute("CREATE TABLE IF NOT EXISTS web_kv(name TEXT PRIMARY KEY, value TEXT, ts TEXT)")
        _KV_READY.append(1)
    return c


def kv_get(name, default=None):
    c = _kv_conn()
    try:
        r = c.execute("SELECT value FROM web_kv WHERE name=?", (name,)).fetchone()
        return r[0] if r else default
    finally:
        c.close()


def kv_set(name, value):
    c = _kv_conn()
    try:
        c.execute("INSERT OR REPLACE INTO web_kv(name, value, ts) VALUES(?,?,?)",
                  (name, value, datetime.now().isoformat(timespec="seconds")))
        c.commit()
    finally:
        c.close()


def kv_del(name):
    c = _kv_conn()
    try:
        c.execute("DELETE FROM web_kv WHERE name=?", (name,))
        c.commit()
    finally:
        c.close()


def project_ref():
    """Which Supabase project this is: the 'computer' a web licence key is made for."""
    u = os.environ.get("SUPABASE_URL") or ""
    m = re.match(r"https?://([a-z0-9]+)\.supabase\.(co|in|net)", u)
    if m:
        return m.group(1)
    d = os.environ.get("DATABASE_URL") or ""
    m = re.search(r"postgres(?:ql)?://postgres\.([a-z0-9]+)[:@]", d) or re.search(r"@db\.([a-z0-9]+)\.supabase\.co", d)
    if m:
        return m.group(1)
    m = re.search(r"@([^/:?]+)", d)
    return (m.group(1) if m else "local") + "/" + (urlparse(d).path.strip("/") or "postgres")


# ───────────────────────── companies list ─────────────────────────
def _patch_companies():
    import api_corp
    api_corp._backup_loop = lambda: None      # Supabase keeps the database; backups are downloaded on request
    api_corp._watchdog = lambda: None
    cache = _REG_CACHE

    def registry():
        if cache["v"] is not None and time.time() - cache["t"] < 10:
            return json.loads(json.dumps(cache["v"]))
        try:
            reg = json.loads(kv_get("companies.json") or "{}")
            if not reg.get("companies"):
                raise ValueError("empty")
        except Exception:
            reg = {"companies": [{"code": "main", "name": None, "dir": ""}], "default": "main"}
        if not any(x["code"] == "main" for x in reg["companies"]):
            reg["companies"].insert(0, {"code": "main", "name": None, "dir": ""})
        cache.update(t=time.time(), v=reg)
        return json.loads(json.dumps(reg))

    def save_registry(reg):
        kv_set("companies.json", json.dumps(reg, ensure_ascii=False))
        cache.update(t=time.time(), v=reg)
    api_corp.registry = registry
    api_corp.save_registry = save_registry

    # Several server copies run at once, each with its own copy of the list. A company made a moment ago in another
    # copy is not in this copy's list yet: read the list again rather than quietly opening the first company.
    orig_find = api_corp._find

    def _find(code):
        if code and cache["v"] is not None and not any(x["code"] == code for x in cache["v"]["companies"]):
            cache["t"] = 0
        return orig_find(code)
    api_corp._find = _find

    f = inv_funcs().get("co.list")
    if f and not getattr(f[0], "_web_fresh", False):
        orig_list = f[0]

        def co_list(c, u, a):
            cache["t"] = 0                         # always the current list
            out = orig_list(c, u, a)
            cur = api_corp.CUR["code"] or "main"
            # companies do not see each other: only the main company's administrator sees the whole list
            if not (u and u.get("role") == "admin" and cur == "main"):
                out = dict(out, companies=[x for x in out["companies"] if x["code"] == cur])
            return out
        co_list._web_fresh = True
        inv_funcs()["co.list"] = (co_list,) + tuple(f[1:])


_REG_CACHE = {"t": 0, "v": None}


def inv_funcs():
    from api_inventory import FUNCS
    return FUNCS


# ───────────────────────── licence ─────────────────────────
def _patch_licence():
    import api_license as L
    from api_inventory import FUNCS
    L._MID.clear()
    L.ALLOW = set(L.ALLOW) | {"web.info", "co.gate_login", "co.signup"}
    L._machine_guid = lambda: "web:" + project_ref()
    L._read = lambda name, default=None: kv_get("licence/" + name, default)
    L._write = lambda name, text: kv_set("licence/" + name, text)
    L.master_present = lambda: kv_get("licence/master.bin") is not None
    orig_status = L.status

    def status(force=False):
        s = orig_status(force)
        s["computer"] = "BuildCore web (%s)" % project_ref()
        return s
    L.status = status
    f = FUNCS.get("license.master_forget")
    if f:
        orig = f[0]

        def master_forget(c, u, a):
            orig(c, u, a)
            kv_del("licence/master.bin")
            L._CACHE.update(t=0, v=None)
            return L.status(force=True)
        FUNCS["license.master_forget"] = (master_forget,) + tuple(f[1:])
    f = FUNCS.get("license.make")
    if f:
        orig_make = f[0]

        def make(c, u, a):
            # the list of keys made is a file next to the master key on the desktop: keep it in the store
            p = L._path("issued.csv")
            old = kv_get("licence/issued.csv")
            if old:
                with open(p, "w", encoding="utf-8", newline="") as fh:
                    fh.write(old)
            elif os.path.exists(p):
                os.remove(p)
            out = orig_make(c, u, a)
            with open(p, encoding="utf-8") as fh:
                kv_set("licence/issued.csv", fh.read())
            return out
        FUNCS["license.make"] = (make,) + tuple(f[1:])


# ───────────────────────── attachments in Supabase Storage ─────────────────────────
def file_key(schema, stored):
    return "%s/files/%s" % (schema, os.path.basename(stored))


def _files_row(c, u, meta, name, stored, size):
    from core import audit, ins, now, today
    ext = os.path.splitext(name)[1].lower()[:10]
    row = {"kind": meta.get("kind") or ("photo" if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif") else "document"),
           "filename": name, "stored": stored, "mime": meta.get("mime") or mimetypes.guess_type(name)[0],
           "size": size, "user_id": u["id"], "ts": now(), "date": meta.get("date") or today()}
    for k in ("entity", "caption", "stage", "location"):
        if meta.get(k):
            row[k] = meta[k]
    for k in ("entity_id", "project_id", "wbs_id", "activity_id", "boq_item_id", "dpr_id"):
        if meta.get(k):
            row[k] = int(meta[k])
    fid = ins(c, "files", row)
    audit(c, u, "upload", "files", fid, {"filename": name, "entity": row.get("entity"), "entity_id": row.get("entity_id")})
    return fid


def _patch_files(server):
    import api_ai
    import api_project
    from api_inventory import FUNCS, api
    from core import ApiError

    def store_file(c, u, meta, body):
        if not body:
            raise ApiError("The file is empty.")
        name = os.path.basename(meta.get("filename") or "file")
        stored = uuid.uuid4().hex + os.path.splitext(name)[1].lower()[:10]
        storage.put(file_key(current_schema(), stored), body, meta.get("mime") or mimetypes.guess_type(name)[0])
        return _files_row(c, u, meta, name, stored, len(body))
    api_project.store_file = store_file

    f = FUNCS["files.delete"]
    orig_delete = f[0]

    def files_delete(c, u, a):
        row = c.execute("SELECT stored FROM files WHERE id=?", (a.get("id"),)).fetchone()
        r = orig_delete(c, u, a)
        if row and row[0]:
            try:
                storage.delete([file_key(current_schema(), row[0])])
            except storage.StorageError:
                pass
        return r
    FUNCS["files.delete"] = (files_delete,) + tuple(f[1:])

    orig_path = api_ai._file_path

    def _file_path(c, file_id):
        """documents the AI reads: fetched from Storage into a temporary folder first"""
        frow, path = orig_path(c, file_id)
        if not os.path.isfile(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            data = storage.get(file_key(current_schema(), frow["stored"]))
            with open(path, "wb") as fh:
                fh.write(data)
        return frow, path
    api_ai._file_path = _file_path

    # files larger than a Vercel request can carry go straight from the browser to Storage
    @api("web.upload_url")
    def web_upload_url(c, u, a):
        name = os.path.basename(str(a.get("filename") or "file"))
        key = "%s/incoming/%s%s" % (current_schema(), uuid.uuid4().hex, os.path.splitext(name)[1].lower()[:10])
        return {"url": storage.signed_upload(key), "key": key}

    @api("web.upload_done")
    def web_upload_done(c, u, a):
        key = str(a.get("key") or "")
        if not key.startswith(current_schema() + "/incoming/") or ".." in key:
            raise ApiError("That upload does not belong to this company.")
        meta = {k: v for k, v in (a.get("meta") or {}).items() if v not in (None, "")}
        size = storage.info(key)
        if not size:
            raise ApiError("The upload did not arrive. Try again.")
        name = os.path.basename(meta.get("filename") or "file")
        stored = os.path.basename(key)
        storage.move(key, file_key(current_schema(), stored))
        return {"id": _files_row(c, u, meta, name, stored, size)}

    @api("web.attachment_slot", "admin", "edit")
    def web_attachment_slot(c, u, a):
        """bringing the desktop's data\\files folder across: one signed link per file, under its own name"""
        name = os.path.basename(str(a.get("name") or ""))
        if not re.fullmatch(r"[0-9a-f]{32}(\.[A-Za-z0-9]{1,9})?", name):
            return {"skip": True}
        known = c.execute("SELECT 1 FROM files WHERE stored=?", (name,)).fetchone()
        if not known:
            return {"skip": True}
        return {"url": storage.signed_upload(file_key(current_schema(), name))}

    @api("web.info", public=True)
    def web_info(c, u, a):
        return {"web": True, "storage": storage.configured(), "setup_key_needed": bool(os.environ.get("BCO_SETUP_KEY")),
                "project": project_ref() if u else None}


# ───────────────────────── document library (2.34) ─────────────────────────
def local_copy(stored):
    """The engine reads a stored file from its files folder: on the web it is fetched from Storage into that
    (temporary) folder first. Stored names are unique and never reused, so a copy already there is current.
    Returns the path; it does not exist when the file is not in Storage either."""
    import api_project
    name = os.path.basename(stored or "")
    path = os.path.join(api_project.FILES_DIR, name)
    if name and not os.path.isfile(path) and storage.configured():
        try:
            data = storage.get(file_key(current_schema(), name))
        except storage.StorageError:
            return path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".part"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    return path


def _patch_doclib():
    try:
        import api_doclib as D
    except ImportError:
        return
    from api_inventory import FUNCS
    from core import q, upd
    D._file_path = lambda f: local_copy(f.get("stored"))

    def dl_check(c, u, a):
        """Library cards whose file is no longer in Storage (the desktop looks in its data folder)."""
        D._ensure(c)
        have = storage.names(current_schema() + "/files") if storage.configured() else set()
        n_missing = 0
        for r in q(c, "SELECT d.id, d.text_status, f.stored FROM dl_docs d LEFT JOIN files f ON f.id=d.file_id"):
            gone = not r.get("stored") or os.path.basename(r["stored"]) not in have
            if gone and r["text_status"] != "missing":
                upd(c, "dl_docs", r["id"], {"text_status": "missing"})
            if gone:
                n_missing += 1
            elif r["text_status"] == "missing":
                upd(c, "dl_docs", r["id"], {"text_status": "pending"})
        return {"missing": n_missing, "catalogued": D.sync(c)}
    f = FUNCS["dl.check"]
    FUNCS["dl.check"] = (dl_check,) + tuple(f[1:])

    # Search. The desktop uses SQLite's full-text index (FTS5), which PostgreSQL does not have, and its fallback
    # for that case only knows plain words. Here the same search syntax is kept: all words, "exact phrase",
    # word starts, OR, -left out. Results come newest first.
    orig_search = D.search
    lock = threading.Lock()
    fields = ["d.title", "d.doc_number", "d.tags", "d.file_name", "d.description", "IFNULL(p.name,'')",
              "IFNULL(p.code,'')", "IFNULL(k.name,'')",
              "REPLACE(IFNULL((SELECT x.body FROM dl_fts x WHERE x.doc_id=d.id),''), char(10), ' ')"]

    def parse(text):
        groups, neg, join_next = [], [], False
        for m in D._TERM_RE.finditer(text or ""):
            neg_flag, phrase, word = m.groups()
            if phrase is None:
                if word.upper() == "OR":
                    join_next = bool(groups)
                    continue
                if word.startswith("-") and len(word) > 1:
                    neg_flag, word = "-", word[1:]
                t = word
            else:
                t = " ".join(phrase.split())
            if not any(ch.isalnum() for ch in t):
                continue
            if neg_flag:
                neg.append(t)
            elif join_next:
                groups[-1].append(t)
            else:
                groups.append([t])
            join_next = False
        return groups, neg

    def cond(t):
        like = "%" + t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        return "(" + " OR ".join("%s LIKE ? ESCAPE '\\'" % f for f in fields) + ")", [like] * len(fields)

    def search(c, u, a, page=1, per_page=50):
        text = (a.get("q") or "").strip()
        if not text or D._ensure(c):
            return orig_search(c, u, a, page=page, per_page=per_page)
        groups, neg = parse(text)
        extra_w, extra_a = [], []
        for g in groups:
            parts = [cond(t) for t in g]
            extra_w.append("(" + " OR ".join(x for x, _ in parts) + ")")
            for _, ag in parts:
                extra_a.extend(ag)
        for t in neg:
            x, ag = cond(t)
            extra_w.append("NOT " + x)
            extra_a.extend(ag)
        b = dict(a)
        b["q"] = ""
        orig_filters = D._filters

        def filters(c2, u2, a2):
            w, ag = orig_filters(c2, u2, a2)
            return w + extra_w, ag + extra_a
        with lock:
            D._filters = filters
            try:
                out = orig_search(c, u, b, page=page, per_page=per_page)
            finally:
                D._filters = orig_filters
        terms = D.query_terms(text)
        out["terms"] = terms
        ids = [r["id"] for r in out["rows"]]
        bodies = {}
        if ids:
            for r in q(c, "SELECT doc_id, body FROM dl_fts WHERE doc_id IN (%s)" % ",".join(str(int(i)) for i in ids)):
                bodies[r["doc_id"]] = r["body"]
        for r in out["rows"]:
            r["snippet"] = D._mark(D._py_snippet(bodies.get(r["id"]) or "", terms), terms) if terms else []
            r["title_marked"] = D._mark(r["title"], terms)
        return out
    D.search = search


# ───────────────────────── engine start-up run again ─────────────────────────
def _patch_reinit(server):
    """The engine's start-up (core.init_db) also connects some screens to others (My work, search...). The web
    runs it again in the same server copy after a restore and for each further company; those connections must
    not be made twice (My work would list each claim deadline or letter more than once). Each later start-up
    still prepares the data exactly as before; only the function table is put back as it was."""
    import core
    from api_inventory import FUNCS
    orig = core.init_db
    state = {"done": False}

    def init_db(*a, **k):
        before = dict(FUNCS)
        try:
            result = orig(*a, **k)
            _add_indexes(core)
            return result
        finally:
            if state["done"]:
                for name, entry in before.items():
                    FUNCS[name] = entry
            state["done"] = True
    core.init_db = init_db
    server.init_db = init_db


_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_vl_project ON voucher_lines(project_id)",
    "CREATE INDEX IF NOT EXISTS ix_v_project ON vouchers(project_id)",
    "CREATE INDEX IF NOT EXISTS ix_vl_boq ON voucher_lines(boq_item_id)",
    "CREATE INDEX IF NOT EXISTS ix_vl_act ON voucher_lines(activity_id)",
)


def _add_indexes(core):
    """Speed: look-up indexes on voucher lines and vouchers in the current company. No data changes."""
    try:
        c = core.connect()
    except Exception:
        return
    try:
        for sql in _INDEXES:
            try:
                c.execute(sql)
                c.commit()
            except Exception:
                try:
                    c.rollback()
                except Exception:
                    pass
    finally:
        c.close()


# ───────────────────────── backups and restore ─────────────────────────
def backup_key(schema, name):
    return "%s/backups/%s" % (schema, os.path.basename(name))


def _patch_backups(server):
    import core
    from api_inventory import FUNCS
    from web import transfer

    def backup_now(tag="auto"):
        schema = current_schema()
        name = "buildcore_%s_%s.db" % (tag, datetime.now().strftime("%Y%m%d_%H%M%S"))
        d = tempfile.mkdtemp(prefix="bco_bk_")
        path = os.path.join(d, name)
        transfer.export_sqlite(schema, path)
        if storage.configured():
            with open(path, "rb") as fh:
                storage.put(backup_key(schema, name), fh.read())
        return path
    core.backup_now = backup_now
    server.backup_now = backup_now

    f = FUNCS["admin.backups"]

    def admin_backups(c, u, a):
        if not storage.configured():
            return []
        return [{"file": x["name"], "size": (x.get("metadata") or {}).get("size") or 0}
                for x in storage.listing(current_schema() + "/backups/") if x["name"].endswith(".db")]
    FUNCS["admin.backups"] = (admin_backups,) + tuple(f[1:])


# ───────────────────────── background jobs (AI) ─────────────────────────
def _patch_jobs():
    import api_ai
    from api_inventory import FUNCS
    from core import ApiError

    def _start(u, kind, work, info=None):
        jid = uuid.uuid4().hex[:16]
        job = {"id": jid, "user_id": u["id"], "kind": kind, "status": "running", "started": time.time(), "result": None,
               "error": None, "step": "Working…", "info": info or {}}
        with api_ai._JL:
            api_ai.JOBS[jid] = job
        pend = getattr(_LOCAL, "pending", None)
        if pend is None:
            _run_job(job, work)
        else:
            pend.append((job, work))      # runs as soon as this request's transaction is committed
        return {"job": jid}
    api_ai._start = _start

    f = FUNCS["ai.job"]

    def ai_job(c, u, a):
        j = api_ai.JOBS.get(a.get("id") or "")
        if not j:
            raw = kv_get("job/" + str(a.get("id") or ""))
            j = json.loads(raw) if raw else None
        if not j or j["user_id"] != u["id"]:
            raise ApiError("This request is no longer available. Ask again.")
        return {k: j.get(k) for k in ("id", "kind", "status", "result", "error", "step")}
    FUNCS["ai.job"] = (ai_job,) + tuple(f[1:])


def _run_job(job, work):
    import api_ai
    from core import ApiError
    try:
        job["result"] = work(job)
        job["status"] = "done"
    except ApiError as e:
        job["status"], job["error"] = "failed", str(e)
    except Exception as e:  # pragma: no cover
        job["status"], job["error"] = "failed", "The AI request failed: %s" % e
    try:
        kv_set("job/" + job["id"], json.dumps({k: job.get(k) for k in ("id", "user_id", "kind", "status", "result",
                                                                         "error", "step")}, default=str))
    except Exception:
        pass


# ───────────────────────── first administrator ─────────────────────────
def _patch_setup():
    from api_inventory import FUNCS
    from core import ApiError
    f = FUNCS["auth.setup"]
    orig = f[0]

    def auth_setup(c, u, a):
        n = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if not n:
            want = os.environ.get("BCO_SETUP_KEY") or ""
            if not want:
                raise ApiError("This BuildCore web is not set up yet: add BCO_SETUP_KEY in Vercel (Settings > "
                               "Environment Variables), redeploy, and enter that key here.")
            if not hmac.compare_digest(str(a.get("setup_key") or "").strip(), want.strip()):
                raise ApiError("The setup key is not right. It is the value of BCO_SETUP_KEY in your Vercel settings.")
        return orig(c, u, a)
    FUNCS["auth.setup"] = (auth_setup,) + tuple(f[1:])


# ───────────────────────── forgotten passwords ─────────────────────────
_PW_REQ = ("CREATE TABLE IF NOT EXISTS web_pw_requests(id INTEGER PRIMARY KEY, ts TEXT, username TEXT, name TEXT, "
           "note TEXT, ip TEXT)")
_KEY_TRIES = "~setup_key"      # wrong setup keys are counted in login_attempts under this name


_CO_TRIES = "~company_key"      # wrong company keys are counted in login_attempts under this name


def _patch_signup():
    """A new company from the sign-in page, for an office that has no company here yet. It needs the company key
    (BCO_COMPANY_KEY, or BCO_SETUP_KEY when that is not set), so nobody who merely finds the address can make one.
    The new company starts empty, with the person who made it as its administrator; nothing is shared with the
    other companies."""
    from datetime import timedelta
    import api_corp
    from api_inventory import FUNCS, api
    from core import ApiError, hash_pw, ins, now, q, setting

    @api("co.signup", public=True)
    def co_signup(c, u, a):
        want = (os.environ.get("BCO_COMPANY_KEY") or os.environ.get("BCO_SETUP_KEY") or "").strip()
        if not want:
            raise ApiError("New companies cannot be made here yet: add BCO_SETUP_KEY in Vercel (Settings > Environment "
                           "Variables) and redeploy.")
        try:
            mins = int(float(setting(c, "lock_minutes") or 10))
        except ValueError:
            mins = 10
        since = (datetime.now() - timedelta(minutes=mins)).isoformat(timespec="seconds")
        recent = q(c, "SELECT ok FROM login_attempts WHERE username=? AND ts>=? ORDER BY id DESC LIMIT 5", (_CO_TRIES, since))
        if len(recent) == 5 and not any(r["ok"] for r in recent):
            raise ApiError("Too many wrong company keys. Wait %d minutes and try again." % mins)
        if not hmac.compare_digest(str(a.get("company_key") or "").strip(), want):
            ins(c, "login_attempts", {"ts": now(), "username": _CO_TRIES, "ip": a.get("_ip"), "ok": 0})
            c.commit()
            raise ApiError("The company key is not right. Ask the person who runs this BuildCore for it.")
        name = str(a.get("name") or "").strip()
        admin_name = str(a.get("admin_name") or "").strip()
        username = str(a.get("username") or "").strip().lower()
        pw = str(a.get("password") or "")
        if not name or not admin_name or not username:
            raise ApiError("Fill in the company name, your full name and a username.")
        if len(pw) < 6:
            raise ApiError("The password needs at least 6 characters.")
        login_id = _clean_company_id(a.get("company_id"))
        co_pw = str(a.get("company_password") or "")
        if len(co_pw) < 6:
            raise ApiError("The company password needs at least 6 characters.")
        reg = api_corp.registry()
        _company_id_free(reg, login_id)
        if any((x.get("name") or "").strip().lower() == name.lower() for x in reg["companies"]):
            raise ApiError("A company called %s is already here. Choose it on the sign-in page instead." % name)
        code = base = api_corp._slug(name)
        n = 2
        while any(x["code"] == code for x in reg["companies"]):
            code = "%s%d" % (base, n)
            n += 1
        reg["companies"].append({"code": code, "name": name, "dir": "companies/" + code, "created": now(), "login_id": login_id})
        api_corp.save_registry(reg)
        src = api_corp.CUR["code"] or "main"
        ok = False
        try:
            api_corp.switch(code)
            k = core_connect()
            try:
                for key, v in (("company_name", name), ("company_pan", a.get("pan")), ("company_address", a.get("address"))):
                    if v is not None:
                        k.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                  (key, str(v).strip()))
                if q(k, "SELECT id FROM users"):
                    raise ApiError("This company already has users.")
                h, s = hash_pw(pw)
                uid = ins(k, "users", {"username": username, "name": admin_name, "pw_hash": h, "salt": s, "role": "admin",
                                       "active": 1})
                if "access" in {r[1] for r in k.execute("PRAGMA table_info(users)")}:
                    k.execute("UPDATE users SET access='all' WHERE id=?", (uid,))
                if a.get("fy") and a.get("fy_start") and "period.generate" in FUNCS:
                    FUNCS["period.generate"][0](k, {"id": uid, "role": "admin", "name": admin_name}, {"fy": a["fy"], "start_date": a["fy_start"]})
                k.commit()
            finally:
                k.close()
            ok = True
        finally:
            api_corp.switch(src)
            if not ok:
                try:
                    reg = api_corp.registry()
                    reg["companies"] = [x for x in reg["companies"] if x["code"] != code]
                    api_corp.save_registry(reg)
                except Exception:
                    pass
        ins(c, "login_attempts", {"ts": now(), "username": _CO_TRIES, "ip": a.get("_ip"), "ok": 1})
        _set_company_password(code, co_pw)
        return {"code": code, "name": name, "username": username, "company_id": login_id, "ticket": company_ticket(code)}

    f = FUNCS.get("web.info")
    if f:
        orig = f[0]

        def web_info(c, u, a):
            out = orig(c, u, a)
            out["company_signup"] = bool(os.environ.get("BCO_COMPANY_KEY") or os.environ.get("BCO_SETUP_KEY"))
            return out
        FUNCS["web.info"] = (web_info,) + tuple(f[1:])


def core_connect():
    import core
    return core.connect()


# ───────────────────────── company sign-in ─────────────────────────
# The address is shared with other companies, so it opens on a company sign-in and shows no company's name. A person
# gives the company ID and password and gets a ticket for that company; only then does the server say anything about
# it (name, licence holder, user sign-in). Signed-in sessions work as before. Until a company has its own password,
# the setup key (BCO_SETUP_KEY) opens it, so the first company can get in after this update.
_GATE_FREE = {"co.gate_login", "co.signup", "license.status", "license.activate", "license.master_load", "web.info"}
_SETUP_DONE = []


def _gate_secret():
    seed = (os.environ.get("BCO_SETUP_KEY") or "") + "|" + (os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or "")
    return hashlib.sha256(("bco-company|" + seed).encode()).digest()


def company_ticket(code):
    """Good for this company until its password changes."""
    msg = "%s|%s" % (code, kv_get("gatepw/" + code) or "")
    return hmac.new(_gate_secret(), msg.encode(), hashlib.sha256).hexdigest()


def _set_company_password(code, pw):
    from core import hash_pw
    h, s = hash_pw(pw)
    kv_set("gatepw/" + code, "%s:%s" % (s, h))


def _clean_company_id(v):
    from core import ApiError
    cid = str(v or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,29}", cid):
        raise ApiError("The company ID needs 3 to 30 letters, numbers or dashes, with no spaces.")
    return cid


def _company_login_id(co):
    return (co.get("login_id") or co["code"]).lower()


def _company_id_free(reg, cid, code=None):
    from core import ApiError
    if any(x["code"] != code and cid in (_company_login_id(x), x["code"].lower()) for x in reg["companies"]):
        raise ApiError("That company ID is taken. Choose another one.")


def _first_run():
    """A new BuildCore with no first administrator yet shows its usual first set-up."""
    if _SETUP_DONE:
        return False
    c = _kv_conn()
    try:
        n = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        c.close()
    if n:
        _SETUP_DONE.append(1)
    return not n


def company_pass(token):
    """May this request hear about the company it names?"""
    import core
    code = getattr(_LOCAL, "company", None) or "main"
    ticket = getattr(_LOCAL, "ticket", None)
    if ticket and hmac.compare_digest(str(ticket), company_ticket(code)):
        return True
    if code == "main" and _first_run():
        return True
    if token:
        c = core.connect()
        try:
            return bool(core.user_from_token(c, token))
        finally:
            c.close()
    return False


def _owner(u):
    import api_corp
    return bool(u and u.get("role") == "admin" and (api_corp.CUR["code"] or "main") == "main")


def _patch_gate():
    import api_corp
    from api_inventory import FUNCS, api
    from core import ApiError, hash_pw

    @api("co.gate_login", public=True)
    def gate_login(c, u, a):
        cid = str(a.get("company_id") or "").strip().lower()
        pw = str(a.get("password") or "")
        if not cid or not pw:
            raise ApiError("Type the company ID and the company password.")
        key = "gatetry/" + hashlib.sha256(cid.encode()).hexdigest()[:20]
        try:
            n, t = json.loads(kv_get(key) or "[0, 0]")
        except ValueError:
            n, t = 0, 0
        if time.time() - t > 600:
            n = 0
        if n >= 5:
            raise ApiError("Too many wrong tries. Wait 10 minutes and try again.")
        co = next((x for x in api_corp.registry()["companies"] if not x.get("broken") and
                   cid in (_company_login_id(x), x["code"].lower())), None)
        good = False
        if co:
            stored = kv_get("gatepw/" + co["code"])
            if stored:
                salt, h = stored.split(":", 1)
                good = hmac.compare_digest(hash_pw(pw, salt)[0], h)
            else:
                want = (os.environ.get("BCO_SETUP_KEY") or "").strip()
                good = bool(want) and hmac.compare_digest(pw.strip(), want)
        if not good:          # the same words whether or not the company exists
            kv_set(key, json.dumps([n + 1, time.time()]))
            raise ApiError("The company ID or password is not right.")
        kv_del(key)
        return {"code": co["code"], "ticket": company_ticket(co["code"])}

    def gate_info(code):
        co = api_corp._find(code)
        return {"code": code, "ticket": company_ticket(code), "company_id": _company_login_id(co),
                "has_password": kv_get("gatepw/" + code) is not None}

    @api("co.gate_ticket")
    def gate_ticket(c, u, a):
        return gate_info(api_corp.CUR["code"] or "main")

    @api("co.gate_set", "admin", "edit")
    def gate_set(c, u, a):
        code = api_corp.CUR["code"] or "main"
        reg = api_corp.registry()
        co = next(x for x in reg["companies"] if x["code"] == code)
        cid = _clean_company_id(a.get("company_id"))
        _company_id_free(reg, cid, code)
        pw = str(a.get("password") or "")
        if pw and len(pw) < 6:
            raise ApiError("The company password needs at least 6 characters.")
        if not pw and kv_get("gatepw/" + code) is None:
            raise ApiError("Choose a company password.")
        co["login_id"] = cid
        api_corp.save_registry(reg)
        if pw:
            _set_company_password(code, pw)
        return gate_info(code)

    f = FUNCS.get("license.status")
    if f:
        orig_status = f[0]

        def license_status(c, u, a):
            s = orig_status(c, u, a)
            if getattr(_LOCAL, "http", False) and not company_pass(a.get("_token")) and isinstance(s, dict):
                s = dict(s, licensee="")          # the licence holder's name is a company's name
            return s
        FUNCS["license.status"] = (license_status,) + tuple(f[1:])

    f = FUNCS.get("co.create")
    if f:
        orig_create = f[0]

        def co_create(c, u, a):
            if not _owner(u):
                raise ApiError("New companies are made from the sign-in page (Set up a new company).")
            return orig_create(c, u, a)
        FUNCS["co.create"] = (co_create,) + tuple(f[1:])

    f = FUNCS.get("co.update")
    if f:
        orig_update = f[0]

        def co_update(c, u, a):
            if not _owner(u) and a.get("code") not in (None, api_corp.CUR["code"] or "main"):
                raise ApiError("You can change only your own company.")
            return orig_update(c, u, a)
        FUNCS["co.update"] = (co_update,) + tuple(f[1:])


def _patch_forgot():
    """Passwords are kept only as hashes, so a forgotten one cannot be shown: the person sets a new one.
    Anyone who has the setup key from the Vercel settings (BCO_SETUP_KEY) can do that for any user, so even
    the only administrator can get back in. Everyone else asks: the request waits in Administration > Users."""
    from datetime import timedelta
    from api_inventory import api
    from core import ApiError, audit, hash_pw, ins, now, q, q1, setting

    def find_user(c, name):
        name = (name or "").strip().lower()
        usr = q1(c, "SELECT * FROM users WHERE username=?", (name,))
        if not usr and name:
            byname = q(c, "SELECT * FROM users WHERE lower(trim(name))=?", (name,))
            usr = byname[0] if len(byname) == 1 else None
        return usr

    def lock_minutes(c):
        try:
            return int(float(setting(c, "lock_minutes") or 10))
        except ValueError:
            return 10

    @api("auth.reset_with_key", public=True)
    def reset_with_key(c, u, a):
        want = (os.environ.get("BCO_SETUP_KEY") or "").strip()
        if not want:
            raise ApiError("Resetting with the setup key is not available: BCO_SETUP_KEY is not set in Vercel. "
                           "Ask an administrator instead.")
        mins = lock_minutes(c)
        since = (datetime.now() - timedelta(minutes=mins)).isoformat(timespec="seconds")
        recent = q(c, "SELECT ok FROM login_attempts WHERE username=? AND ts>=? ORDER BY id DESC LIMIT 5",
                   (_KEY_TRIES, since))
        if len(recent) == 5 and not any(r["ok"] for r in recent):
            raise ApiError("Too many wrong setup keys. Wait %d minutes and try again." % mins)
        if not hmac.compare_digest(str(a.get("setup_key") or "").strip(), want):
            ins(c, "login_attempts", {"ts": now(), "username": _KEY_TRIES, "ip": a.get("_ip"), "ok": 0})
            c.commit()      # keep the record of the wrong key
            raise ApiError("The setup key is not right. It is the value of BCO_SETUP_KEY in your Vercel settings.")
        usr = find_user(c, a.get("username"))
        if not usr:
            raise ApiError("There is no user '%s' in this company. Check the company and the username."
                           % (a.get("username") or "").strip())
        pw = a.get("password") or ""
        if len(pw) < 6:
            raise ApiError("The new password needs at least 6 characters.")
        h, s = hash_pw(pw)
        c.execute("UPDATE users SET pw_hash=?, salt=? WHERE id=?", (h, s, usr["id"]))
        c.execute("DELETE FROM sessions WHERE user_id=?", (usr["id"],))       # signed out everywhere
        c.execute("DELETE FROM login_attempts WHERE username=?", (usr["username"],))
        ins(c, "login_attempts", {"ts": now(), "username": _KEY_TRIES, "ip": a.get("_ip"), "ok": 1})
        c.execute(_PW_REQ)
        c.execute("DELETE FROM web_pw_requests WHERE username=?", (usr["username"],))
        audit(c, usr, "password_reset", "users", usr["id"], {"how": "setup key", "ip": a.get("_ip")})
        return {"username": usr["username"]}

    @api("auth.reset_request", public=True)
    def reset_request(c, u, a):
        # the same answer whether or not the user exists, so nobody can find usernames this way
        answer = {"sent": True}
        usr = find_user(c, a.get("username"))
        if not usr or not usr["active"]:
            return answer
        c.execute(_PW_REQ)
        if q1(c, "SELECT id FROM web_pw_requests WHERE username=?", (usr["username"],)):
            return answer
        if (q1(c, "SELECT COUNT(*) n FROM web_pw_requests") or {}).get("n", 0) >= 50:
            return answer
        ins(c, "web_pw_requests", {"ts": now(), "username": usr["username"], "name": usr["name"],
                                   "note": str(a.get("note") or "").strip()[:300], "ip": a.get("_ip")})
        return answer

    @api("web.pw_requests", "admin", "view")
    def pw_requests(c, u, a):
        c.execute(_PW_REQ)
        return q(c, "SELECT r.id, r.ts, r.username, r.name, r.note, u.id user_id FROM web_pw_requests r "
                    "LEFT JOIN users u ON u.username=r.username ORDER BY r.id")

    @api("web.pw_request_done", "admin", "edit")
    def pw_request_done(c, u, a):
        """Set the new password the administrator chose (and unlock), or with no password just dismiss."""
        c.execute(_PW_REQ)
        req = q1(c, "SELECT * FROM web_pw_requests WHERE id=?", (int(a["id"]),))
        if not req:
            return True
        pw = a.get("password")
        if pw is not None:
            usr = q1(c, "SELECT * FROM users WHERE username=?", (req["username"],))
            if not usr:
                raise ApiError("User '%s' no longer exists." % req["username"])
            if len(pw) < 6:
                raise ApiError("The new password needs at least 6 characters.")
            h, s = hash_pw(pw)
            c.execute("UPDATE users SET pw_hash=?, salt=? WHERE id=?", (h, s, usr["id"]))
            c.execute("DELETE FROM sessions WHERE user_id=?", (usr["id"],))
            c.execute("DELETE FROM login_attempts WHERE username=?", (usr["username"],))
            audit(c, u, "password_reset", "users", usr["id"], {"how": "reset request"})
        c.execute("DELETE FROM web_pw_requests WHERE id=?", (req["id"],))
        return True


# ───────────────────────── request handling ─────────────────────────
def _wrap_call(server):
    import api_workspace
    import core
    orig = server.call

    def call(fn, args, token, ip=None, device=None):
        from api_inventory import FUNCS
        entry = FUNCS.get(fn)
        if entry and entry[3] and fn not in _GATE_FREE and getattr(_LOCAL, "http", False) and not company_pass(token):
            raise core.ApiError("COMPANY_LOGIN")
        # role templates may have been changed by another copy of the server: read them for this request
        try:
            c = core.connect()
            try:
                api_workspace.load_roles(c)
            finally:
                c.close()
        except Exception:
            pass
        _LOCAL.pending = []
        try:
            return orig(fn, args, token, ip, device)
        finally:
            pend, _LOCAL.pending = _LOCAL.pending, None
            for job, work in pend:
                _run_job(job, work)
    server.call = call


def make_handler(server):
    import core
    from web import transfer

    class WebHandler(server.Handler):
        server_version = "BuildCoreWeb/1.0"

        def _fix_path(self):
            # Vercel hands requests to /api/index; the address the browser used comes along in __p
            u = urlparse(self.path)
            if u.path.rstrip("/") in ("/api/index", "/api/index.py"):
                qs = parse_qs(u.query, keep_blank_values=True)
                p = (qs.pop("__p", [None])[0]) or "/api"
                rest = "&".join("%s=%s" % (k, quote(v, safe="")) for k, vs in qs.items() for v in vs)
                self.path = p + ("?" + rest if rest else "")

        # Requests of one company run one after the other anyway (the company lock), so running many at once in
        # one server copy only uses up database connections (Supabase free plan: 15 in all). A few at a time.
        def _company_of_request(self):
            import api_corp
            _LOCAL.http = True
            _LOCAL.company = api_corp._req_company(self)
            _LOCAL.ticket = self.headers.get("X-Company-Ticket")

        def do_GET(self):
            self._fix_path()
            self._company_of_request()
            with _GATE:
                return super().do_GET()

        def do_POST(self):
            self._fix_path()
            self._company_of_request()
            with _GATE:
                return super().do_POST()

        def allowed(self):
            return True

        def _redirect(self, url):
            self.send_response(302)
            self.send_header("Location", url)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _admin(self):
            c = core.connect()
            try:
                u = core.user_from_token(c, self._token())
            finally:
                c.close()
            return u if (u and u["role"] == "admin") else None

        def send_stored_file(self, path):
            c = core.connect()
            try:
                user = core.user_from_token(c, self._token())
                row = None
                if user:
                    try:
                        row = core.q1(c, "SELECT * FROM files WHERE id=?", (int(path.rsplit("/", 1)[1]),))
                    except ValueError:
                        row = None
            finally:
                c.close()
            if not user:
                return self._json(403, {"error": "Sign in first."})
            if not row:
                return self._json(404, {"error": "File not found."})
            try:
                url = storage.signed_download(file_key(current_schema(), row["stored"]), 300)
            except storage.StorageError as e:
                return self._json(404, {"error": str(e)})
            ctype = row["mime"] or mimetypes.guess_type(row["filename"])[0] or ""
            if not (ctype.startswith("image/") or ctype == "application/pdf"):
                url += "&download=" + quote(row["filename"])
            return self._redirect(url)

        def download_backup(self):
            if not self._admin():
                return self._json(403, {"error": "Only administrators can download backups."})
            name = parse_qs(urlparse(self.path).query).get("file", [""])[0]
            try:
                if not name:
                    path = core.backup_now("download")
                    name = os.path.basename(path)
                    if not storage.configured():
                        with open(path, "rb") as fh:
                            data = fh.read()
                        return self._send(200, data, "application/octet-stream",
                                          {"Content-Disposition": 'attachment; filename="%s"' % name})
                return self._redirect(storage.signed_download(backup_key(current_schema(), name), 300, name))
            except Exception as e:
                server.log_error("backup download")
                return self._json(500, {"error": "Backup failed: %s" % e})

        def restore(self, body):
            if not self._admin():
                return self._json(403, {"ok": False, "error": "Only administrators can restore."})
            key = parse_qs(urlparse(self.path).query).get("key", [""])[0]
            schema = current_schema()
            d = tempfile.mkdtemp(prefix="bco_in_")
            path = os.path.join(d, "buildcore.db")
            try:
                if key:
                    if not key.startswith(schema + "/incoming/") or ".." in key:
                        raise ValueError("That upload does not belong to this company.")
                    body = storage.get(key)
                with open(path, "wb") as fh:
                    fh.write(body or b"")
                transfer.check_sqlite(path)
                rep = transfer.import_sqlite(path, schema)
                del _KV_READY[:]
                if key:
                    try:
                        storage.delete([key])
                    except storage.StorageError:
                        pass
            except Exception as e:
                server.log_error("restore")
                return self._json(200, {"ok": False, "error": "Restore failed: %s" % e})
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass
            try:
                import api_workspace
                c = core.connect()
                try:
                    api_workspace.load_roles(c)
                finally:
                    c.close()
            except Exception:
                pass
            return self._json(200, {"ok": True, "data": True, "report": {
                "rows": rep["rows"], "tables": len(rep["tables"]), "notes": rep["notes"],
                "note_samples": rep.get("note_samples"), "seconds": rep["seconds"]}})

    return WebHandler


def before_init(server):
    _patch_companies()
    _patch_licence()
    _patch_files(server)
    _patch_backups(server)
    _patch_jobs()
    _patch_setup()
    _patch_forgot()
    _patch_signup()
    _patch_gate()
    _patch_doclib()
    _patch_reinit(server)
    server.Handler.allowed = lambda self: True


def after_init(server):
    import api_corp
    if hasattr(api_corp, "_patch_server"):
        api_corp._patch_server()          # company switching and the engine lock around each request
    _wrap_call(server)
    server.read_server_settings()
