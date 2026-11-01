"""Supabase Storage for BuildCore web: attachments, backups and desktop data files being imported.

Only the server talks to Storage with the service-role key. Browsers get short-lived signed links,
one file at a time, so the bucket stays private.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

BUCKET = os.environ.get("BCO_STORAGE_BUCKET") or "buildcore-files"
_READY = []


class StorageError(Exception):
    pass


def configured():
    return bool(_base() and _key())


def _base():
    return (os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or "").rstrip("/")


def _key():
    return os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SECRET_KEY") or ""


def _req(method, path, body=None, headers=None, raw=False, timeout=120):
    if not configured():
        raise StorageError("File storage is not set up: add SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in Vercel.")
    url = _base() + "/storage/v1" + path
    k = _key()
    # a legacy service_role key is a JWT and goes in both headers; a new secret key (sb_secret_...) is not a
    # JWT, so Supabase takes it in the apikey header only
    h = {"apikey": k} if k.startswith("sb_") else {"Authorization": "Bearer " + k, "apikey": k}
    data = None
    if body is not None:
        if isinstance(body, (bytes, bytearray)):
            data = bytes(body)
        else:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = r.read()
            return out if raw else (json.loads(out.decode() or "null") if out else None)
    except urllib.error.HTTPError as e:
        try:
            msg = e.read().decode()[:300]
        except Exception:
            msg = ""
        raise StorageError("Storage %s %s failed (%s): %s" % (method, path.split("?")[0], e.code, msg))
    except urllib.error.URLError as e:
        raise StorageError("Storage could not be reached: %s" % e)


def _q(key):
    return urllib.parse.quote(key, safe="/")


def ensure_bucket():
    if _READY:
        return
    try:
        _req("GET", "/bucket/" + BUCKET)
    except StorageError:
        try:
            _req("POST", "/bucket", {"id": BUCKET, "name": BUCKET, "public": False})
        except StorageError as e:
            if "already exists" not in str(e) and "409" not in str(e):
                raise
    _READY.append(1)


def put(key, data, content_type="application/octet-stream"):
    ensure_bucket()
    _req("POST", "/object/%s/%s" % (BUCKET, _q(key)), bytes(data),
         {"Content-Type": content_type or "application/octet-stream", "x-upsert": "true"})


def get(key):
    ensure_bucket()
    return _req("GET", "/object/%s/%s" % (BUCKET, _q(key)), raw=True, timeout=300)


def info(key):
    """size in bytes, or None when the object is missing"""
    ensure_bucket()
    try:
        r = _req("GET", "/object/info/%s/%s" % (BUCKET, _q(key)))
    except StorageError:
        return None
    if not isinstance(r, dict):
        return None
    size = r.get("size")
    if size is None:
        size = (r.get("metadata") or {}).get("size")
    return int(size or 0)


def delete(keys):
    ensure_bucket()
    keys = [k for k in (keys if isinstance(keys, (list, tuple)) else [keys]) if k]
    if keys:
        _req("DELETE", "/object/" + BUCKET, {"prefixes": keys})


def move(src, dst):
    ensure_bucket()
    _req("POST", "/object/move", {"bucketId": BUCKET, "sourceKey": src, "destinationKey": dst})


def listing(prefix, limit=200):
    ensure_bucket()
    r = _req("POST", "/object/list/" + BUCKET, {"prefix": prefix, "limit": limit, "offset": 0,
                                                 "sortBy": {"column": "name", "order": "desc"}})
    return [x for x in (r or []) if x.get("id")]


def signed_download(key, seconds=300, filename=None):
    ensure_bucket()
    body = {"expiresIn": int(seconds)}
    r = _req("POST", "/object/sign/%s/%s" % (BUCKET, _q(key)), body)
    url = _base() + "/storage/v1" + (r.get("signedURL") or r.get("signedUrl"))
    if filename:
        url += "&download=" + urllib.parse.quote(filename)
    return url


def signed_upload(key):
    """a link the browser can PUT one file to (valid for two hours)"""
    ensure_bucket()
    r = _req("POST", "/object/upload/sign/%s/%s" % (BUCKET, _q(key)), {}, {"x-upsert": "true"})
    return _base() + "/storage/v1" + r["url"]


def names(prefix):
    """every object name directly under prefix (a folder), page by page"""
    ensure_bucket()
    out, off = set(), 0
    while True:
        r = _req("POST", "/object/list/" + BUCKET, {"prefix": prefix, "limit": 1000, "offset": off,
                                                     "sortBy": {"column": "name", "order": "asc"}}) or []
        out.update(x["name"] for x in r if x.get("id"))
        if len(r) < 1000:
            return out
        off += 1000
