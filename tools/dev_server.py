"""Run BuildCore web on your own computer, the way Vercel runs it (for trying changes before you push).

    set DATABASE_URL=postgresql://...        (your Supabase connection string, or a local PostgreSQL)
    set SUPABASE_URL=https://xxxx.supabase.co
    set SUPABASE_SERVICE_ROLE_KEY=...
    set BCO_SETUP_KEY=any-secret-words
    python tools/dev_server.py               then open http://127.0.0.1:8760

Needs Python 3.10+ and:  pip install -r requirements.txt
"""
import mimetypes
import os
import sys
from http.server import ThreadingHTTPServer
from urllib.parse import quote, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))
sys.path.insert(0, os.path.join(ROOT, "engine"))
PUBLIC = os.path.join(ROOT, "public")

import index  # noqa: E402  (api/index.py: starts the engine, gives the request handler)


class Dev(index.handler):
    """Static screens from public/, everything else through the function, with Vercel's rewrites."""

    def _static(self):
        p = urlparse(self.path).path
        if p.startswith("/api") or p.startswith("/files/"):
            u = urlparse(self.path)
            self.path = "/api/index?__p=" + quote(u.path, safe="/") + ("&" + u.query if u.query else "")
            return False
        f = os.path.normpath(os.path.join(PUBLIC, p.lstrip("/") or "index.html"))
        if not f.startswith(PUBLIC) or not os.path.isfile(f):
            f = os.path.join(PUBLIC, "index.html")
        with open(f, "rb") as fh:
            self._send(200, fh.read(), mimetypes.guess_type(f)[0] or "application/octet-stream")
        return True

    def do_GET(self):
        if not self._static():
            return super().do_GET()

    def do_POST(self):
        if not self._static():
            return super().do_POST()


def main():
    port = int(os.environ.get("PORT") or 8760)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Dev)
    srv.daemon_threads = True
    print("BuildCore web running on http://127.0.0.1:%d  (Ctrl+C stops it)" % port)
    srv.serve_forever()


if __name__ == "__main__":
    main()
