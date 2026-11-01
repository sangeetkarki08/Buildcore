"""A stand-in for Supabase Storage, for testing on one computer without a Supabase project.

    python tools/dev_storage.py 8761          then  set SUPABASE_URL=http://127.0.0.1:8761  SUPABASE_SERVICE_ROLE_KEY=dev

Implements only the calls BuildCore web makes (bucket, upload, download, info, list, move, delete,
signed links). Files are kept in a folder next to this script (dev_storage_data). Not for real use.
"""
import json
import os
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dev_storage_data")
TOKENS = {}


def _path(bucket, key):
    p = os.path.normpath(os.path.join(DATA, bucket, key))
    if not p.startswith(DATA):
        raise ValueError("bad key")
    return p


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _j(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def _auth(self):
        return (self.headers.get("Authorization") or "").startswith("Bearer ")

    def do_GET(self):
        u = urlparse(self.path)
        p = unquote(u.path)
        if p.startswith("/storage/v1/bucket/"):
            b = p.split("/")[4]
            return self._j(200, {"id": b}) if os.path.isdir(os.path.join(DATA, b)) else self._j(404, {"message": "not found"})
        if p.startswith("/storage/v1/object/info/"):
            rest = p[len("/storage/v1/object/info/"):]
            b, key = rest.split("/", 1)
            f = _path(b, key)
            return self._j(200, {"size": os.path.getsize(f)}) if os.path.isfile(f) else self._j(404, {"message": "not found"})
        if p.startswith("/storage/v1/object/sign/"):
            rest = p[len("/storage/v1/object/sign/"):]
            tok = parse_qs(u.query).get("token", [""])[0]
            if TOKENS.get(tok) != ("get", rest):
                return self._j(400, {"message": "bad token"})
            b, key = rest.split("/", 1)
            with open(_path(b, key), "rb") as fh:
                data = fh.read()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
            return
        if p.startswith("/storage/v1/object/"):
            if not self._auth():
                return self._j(401, {"message": "no key"})
            rest = p[len("/storage/v1/object/"):]
            b, key = rest.split("/", 1)
            f = _path(b, key)
            if not os.path.isfile(f):
                return self._j(404, {"message": "not found"})
            data = open(f, "rb").read()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._j(404, {"message": "?"})

    def do_PUT(self):
        u = urlparse(self.path)
        p = unquote(u.path)
        if p.startswith("/storage/v1/object/upload/sign/"):
            rest = p[len("/storage/v1/object/upload/sign/"):]
            tok = parse_qs(u.query).get("token", [""])[0]
            if TOKENS.get(tok) != ("put", rest):
                return self._j(400, {"message": "bad token"})
            b, key = rest.split("/", 1)
            f = _path(b, key)
            os.makedirs(os.path.dirname(f), exist_ok=True)
            with open(f, "wb") as fh:
                fh.write(self._body())
            return self._j(200, {"Key": rest})
        self._j(404, {"message": "?"})

    def do_POST(self):
        u = urlparse(self.path)
        p = unquote(u.path)
        body = self._body()
        if not self._auth():
            return self._j(401, {"message": "no key"})
        if p == "/storage/v1/bucket":
            os.makedirs(os.path.join(DATA, json.loads(body)["id"]), exist_ok=True)
            return self._j(200, {"name": "ok"})
        if p == "/storage/v1/object/move":
            j = json.loads(body)
            a, z = _path(j["bucketId"], j["sourceKey"]), _path(j["bucketId"], j["destinationKey"])
            os.makedirs(os.path.dirname(z), exist_ok=True)
            os.replace(a, z)
            return self._j(200, {"message": "moved"})
        if p.startswith("/storage/v1/object/list/"):
            b = p.split("/")[5]
            j = json.loads(body)
            d = _path(b, j.get("prefix", ""))
            out = []
            if os.path.isdir(d):
                for n in sorted(os.listdir(d), reverse=True):
                    f = os.path.join(d, n)
                    if os.path.isfile(f):
                        out.append({"name": n, "id": n, "metadata": {"size": os.path.getsize(f)}})
            return self._j(200, out)
        if p.startswith("/storage/v1/object/upload/sign/"):
            rest = p[len("/storage/v1/object/upload/sign/"):]
            tok = uuid.uuid4().hex
            TOKENS[tok] = ("put", rest)
            return self._j(200, {"url": "/object/upload/sign/%s?token=%s" % (rest, tok)})
        if p.startswith("/storage/v1/object/sign/"):
            rest = p[len("/storage/v1/object/sign/"):]
            tok = uuid.uuid4().hex
            TOKENS[tok] = ("get", rest)
            return self._j(200, {"signedURL": "/object/sign/%s?token=%s" % (rest, tok)})
        if p.startswith("/storage/v1/object/"):
            rest = p[len("/storage/v1/object/"):]
            b, key = rest.split("/", 1)
            f = _path(b, key)
            os.makedirs(os.path.dirname(f), exist_ok=True)
            with open(f, "wb") as fh:
                fh.write(body)
            return self._j(200, {"Key": rest})
        self._j(404, {"message": "?"})

    def do_DELETE(self):
        p = unquote(urlparse(self.path).path)
        if not self._auth():
            return self._j(401, {"message": "no key"})
        b = p.split("/")[4]
        for k in json.loads(self._body()).get("prefixes", []):
            try:
                os.remove(_path(b, k))
            except OSError:
                pass
        self._j(200, [])


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8761
    os.makedirs(DATA, exist_ok=True)
    print("dev storage on http://127.0.0.1:%d (files in %s)" % (port, DATA))
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
