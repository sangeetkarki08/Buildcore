"""BuildCore Offline - local web server.

Run:  python server.py            (this computer only)
      python server.py --lan      (other computers on the office network can connect)
      python server.py --port 8750 --no-browser
"""
import argparse
import json
import mimetypes
import os
import shutil
import sqlite3
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

if sys.version_info < (3, 8):
    print("BuildCore needs Python 3.8 or newer. This computer has Python %d.%d." % sys.version_info[:2])
    sys.exit(1)
for _stream in (sys.stdout, sys.stderr):
    try:  # never crash because the console cannot print a character (Nepali folder names, etc.)
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core  # noqa: E402
from core import ApiError, LOCK, BACKUP_DIR, DB_PATH, connect, init_db, require, user_from_token, backup_now  # noqa
import api_inventory  # noqa: E402
import api_finance  # noqa: E402,F401
import api_equipment_reports  # noqa: E402,F401
import api_project  # noqa: E402,F401
import api_team  # noqa: E402,F401
import api_plant  # noqa: E402,F401
import api_logsheet  # noqa: E402,F401

MIME = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".png": "image/png", ".svg": "image/svg+xml", ".ico": "image/x-icon",
        ".json": "application/json", ".ttf": "font/ttf", ".txt": "text/plain; charset=utf-8"}
ERROR_LOG = os.path.join(core.DATA_DIR, "error.log")


def log_error(where):
    """Write the full error to data/error.log (and the console if it can)."""
    text = "[%s] %s\n%s\n" % (core.now(), where, traceback.format_exc())
    try:
        os.makedirs(os.path.dirname(ERROR_LOG), exist_ok=True)
        with open(ERROR_LOG, "a", encoding="utf-8") as fh:
            fh.write(text)
    except Exception:
        pass
    try:
        sys.stderr.write(text)
    except Exception:
        pass


STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MAX_BODY = 60 * 1024 * 1024
ALLOW_PUBLIC = [False]      # set from settings at start-up; a list so the handler sees changes
SERVER_NAME = ["BuildCore"]


def call(fn, args, token, ip=None, device=None):
    entry = api_inventory.FUNCS.get(fn)
    if not entry:
        raise ApiError("Unknown action: %s" % fn)
    f, module, action, public = entry
    with LOCK:
        c = connect()
        try:
            user = user_from_token(c, token)
            if not public and not user:
                raise ApiError("SESSION_EXPIRED")
            if module:
                require(user, module, action)
            args = dict(args or {})
            args["_token"], args["_ip"], args["_device"] = token, ip, device
            c.execute("BEGIN IMMEDIATE")
            result = f(c, user, args)
            if user:
                core.touch_session(c, token, ip, device)
                try:
                    api_team.log_call(c, user, fn, args, result)
                except Exception:      # the feed must never break real work
                    log_error("activity feed " + fn)
            c.commit()
            return result
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()


class Handler(BaseHTTPRequestHandler):
    server_version = "BuildCoreOffline/1.0"

    def log_message(self, fmt, *args):
        if os.environ.get("BCO_VERBOSE"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, default=str))

    def _token(self):
        return self.headers.get("X-Token") or parse_qs(urlparse(self.path).query).get("token", [None])[0]

    def _device(self):
        ua = self.headers.get("User-Agent") or ""
        if "Electron" in ua:
            return "BuildCore desktop app"
        for name, label in (("Edg/", "Edge"), ("Chrome/", "Chrome"), ("Firefox/", "Firefox"), ("Safari/", "Safari")):
            if name in ua:
                return ("phone " if "Mobile" in ua else "") + label
        return ua[:40] or "unknown"

    def allowed(self):
        """Who may reach this server. Public internet is refused unless it is switched on."""
        cls = core.client_class(self.client_address[0] if self.client_address else "")
        if cls != "public" or ALLOW_PUBLIC[0]:
            return True
        self._json(403, {"ok": False, "error":
                         "BuildCore refused a connection from outside the office network or VPN (%s). "
                         "This protects your data. To use BuildCore between two cities, join both computers to "
                         "a VPN such as Tailscale, or switch on 'Allow computers outside the office network' in "
                         "Administration - Remote access." % (self.client_address[0] if self.client_address else "?")})
        return False

    def do_GET(self):
        try:
            self._get()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            log_error("GET " + self.path)
            try:
                self._json(500, {"ok": False, "error": "Server error: %s (details in data/error.log)" % e})
            except Exception:
                pass

    def _get(self):
        path = urlparse(self.path).path
        if path == "/api/ping":
            return self._json(200, {"ok": True, "data": "pong", "version": api_team.VERSION,
                                    "name": SERVER_NAME[0]})
        if not self.allowed():
            return
        if path == "/api/backup/download":
            return self.download_backup()
        if path.startswith("/files/"):
            return self.send_stored_file(path)
        if path in ("/", ""):
            path = "/index.html"
        full = os.path.normpath(os.path.join(STATIC, path.lstrip("/")))
        if not full.startswith(STATIC) or not os.path.isfile(full):
            full = os.path.join(STATIC, "index.html")
        ctype = MIME.get(os.path.splitext(full)[1].lower()) or mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as fh:
            self._send(200, fh.read(), ctype)

    def send_stored_file(self, path):
        with LOCK:
            c = connect()
            try:
                user = user_from_token(c, self._token())
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
        full = os.path.join(api_project.FILES_DIR, os.path.basename(row["stored"]))
        if not os.path.isfile(full):
            return self._json(404, {"error": "File is missing from the data folder."})
        with open(full, "rb") as fh:
            data = fh.read()
        ctype = row["mime"] or mimetypes.guess_type(row["filename"])[0] or "application/octet-stream"
        disp = "inline" if ctype.startswith("image/") or ctype == "application/pdf" else "attachment"
        from urllib.parse import quote
        self._send(200, data, ctype, {"Content-Disposition": "%s; filename*=UTF-8''%s" % (disp,
                                                                                          quote(row["filename"]))})

    def download_backup(self):
        token = self._token()
        with LOCK:
            c = connect()
            try:
                user = user_from_token(c, token)
                if not user or user["role"] != "admin":
                    return self._json(403, {"error": "Only administrators can download backups."})
            finally:
                c.close()
        name = parse_qs(urlparse(self.path).query).get("file", [""])[0]
        if name:
            full = os.path.normpath(os.path.join(BACKUP_DIR, os.path.basename(name)))
        else:
            full = backup_now("download")
        if not os.path.isfile(full):
            return self._json(404, {"error": "Backup not found."})
        with open(full, "rb") as fh:
            data = fh.read()
        self._send(200, data, "application/octet-stream",
                   {"Content-Disposition": 'attachment; filename="%s"' % os.path.basename(full)})

    def do_POST(self):
        try:
            self._post()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            log_error("POST " + self.path)
            try:
                self._json(200, {"ok": False, "error": "Server error: %s (details in data/error.log)" % e})
            except Exception:
                pass

    def _post(self):
        if not self.allowed():
            return
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._json(413, {"error": "Upload is too large."})
        body = self.rfile.read(length) if length else b""
        if path == "/api/restore":
            return self.restore(body)
        if path == "/api/upload":
            meta = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            try:
                with LOCK:
                    c = connect()
                    try:
                        user = user_from_token(c, self._token())
                        if not user:
                            raise ApiError("SESSION_EXPIRED")
                        c.execute("BEGIN IMMEDIATE")
                        fid = api_project.store_file(c, user, meta, body)
                        c.commit()
                    except Exception:
                        c.rollback()
                        raise
                    finally:
                        c.close()
                return self._json(200, {"ok": True, "data": {"id": fid}})
            except ApiError as e:
                return self._json(200, {"ok": False, "error": str(e)})
        if path != "/api":
            return self._json(404, {"error": "Not found"})
        try:
            req = json.loads(body.decode("utf-8") or "{}")
            result = call(req.get("fn"), req.get("args"), self._token(),
                          self.client_address[0] if self.client_address else None, self._device())
            self._json(200, {"ok": True, "data": result})
        except ApiError as e:
            self._json(200, {"ok": False, "error": str(e)})
        except sqlite3.IntegrityError as e:
            self._json(200, {"ok": False, "error": "Duplicate or invalid data: %s" % e})
        except Exception as e:  # pragma: no cover
            log_error("API " + str(body[:200]))
            self._json(200, {"ok": False, "error": "Unexpected error: %s (details in data/error.log)" % e})

    def restore(self, body):
        token = self._token()
        with LOCK:
            c = connect()
            try:
                user = user_from_token(c, token)
            finally:
                c.close()
            if not user or user["role"] != "admin":
                return self._json(403, {"ok": False, "error": "Only administrators can restore."})
            if not body.startswith(b"SQLite format 3\x00"):
                return self._json(200, {"ok": False, "error": "This is not a BuildCore backup file."})
            tmp = DB_PATH + ".restore"
            with open(tmp, "wb") as fh:
                fh.write(body)
            try:
                t = sqlite3.connect(tmp)
                names = {r[0] for r in t.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                ok = t.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                t.close()
                if not ok or not {"vouchers", "stock_ledger", "users"} <= names:
                    raise ValueError("backup is damaged or incomplete")
            except Exception as e:
                os.remove(tmp)
                return self._json(200, {"ok": False, "error": "Restore failed: %s" % e})
            backup_now("before_restore")
            for ext in ("-wal", "-shm"):
                if os.path.exists(DB_PATH + ext):
                    os.remove(DB_PATH + ext)
            shutil.move(tmp, DB_PATH)
            init_db()
        return self._json(200, {"ok": True, "data": True})


def daily_backup_loop():
    import time
    while True:
        try:
            backup_now("auto")
        except Exception:
            log_error("daily backup")
        time.sleep(24 * 3600)


def read_server_settings():
    """Read the few settings the network layer needs, without a user session."""
    with LOCK:
        c = connect()
        try:
            ALLOW_PUBLIC[0] = core.setting(c, "allow_public") == "1"
            SERVER_NAME[0] = core.setting(c, "site_name") or core.setting(c, "company_name") or "BuildCore"
        finally:
            c.close()


def lan_ips():
    """Every address other computers could use to reach this one."""
    import socket
    out = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ip = info[4][0]
            if core.client_class(ip) in ("private", "vpn") and ip not in out:
                out.append(ip)
    except OSError:
        pass
    try:  # the address used to reach the outside world - finds the real one behind several adapters
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip not in out:
            out.insert(0, ip)
    except OSError:
        pass
    return out


def already_running(port):
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/ping" % port, timeout=2) as r:
            return b"pong" in r.read()
    except Exception:
        return False


def self_check(port):
    """Checks the usual reasons BuildCore cannot start. Returns a list of problems."""
    import socket
    problems = []
    print(" Python %s   SQLite %s" % (sys.version.split()[0], sqlite3.sqlite_version))
    if tuple(int(x) for x in sqlite3.sqlite_version.split(".")[:2]) < (3, 24):
        problems.append("SQLite %s is too old; install a newer Python from python.org." % sqlite3.sqlite_version)
    if not os.path.isfile(os.path.join(STATIC, "app.js")):
        problems.append("The 'static' folder is missing. Unzip the WHOLE BuildCore_Offline folder first; "
                        "do not run the file from inside the zip.")
    try:
        os.makedirs(core.DATA_DIR, exist_ok=True)
        test = os.path.join(core.DATA_DIR, "write_test.tmp")
        with open(test, "w") as fh:
            fh.write("ok")
        os.remove(test)
    except OSError as e:
        problems.append("Cannot write to %s (%s). Move the folder to e.g. D:\\BuildCore_Offline." % (core.DATA_DIR, e))
    if already_running(port):
        problems.append("BuildCore is already running on port %d (another black window is open). "
                        "Use that window, or close it first." % port)
    return problems


def main():
    ap = argparse.ArgumentParser(description="BuildCore Offline")
    ap.add_argument("--port", type=int, default=8750)
    ap.add_argument("--lan", action="store_true", help="allow other computers on the network")
    ap.add_argument("--host", help="address to listen on (default 127.0.0.1, or 0.0.0.0 with --lan)")
    ap.add_argument("--cert", help="TLS certificate file, to serve https instead of http")
    ap.add_argument("--key", help="TLS private key file")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--check", action="store_true", help="only run the start-up checks")
    ap.add_argument("--desktop", action="store_true", help="started by the BuildCore desktop app")
    args = ap.parse_args()
    print("=" * 64)
    print(" BuildCore Offline - starting")
    problems = self_check(args.port)
    if args.check:
        print(" Problems found:" if problems else " All checks passed.")
        for p in problems:
            print("  - " + p)
        return
    url = "http://127.0.0.1:%d" % args.port
    if problems:
        for p in problems:
            print(" PROBLEM: " + p)
        if any("already running" in p for p in problems):
            print(" Opening the existing BuildCore instead: " + url)
            if not args.no_browser and not args.desktop:
                webbrowser.open(url)
        return
    try:
        init_db()
    except Exception:
        log_error("database start-up")
        print(" PROBLEM: the database could not be opened. See data\\error.log")
        return
    threading.Thread(target=daily_backup_loop, daemon=True).start()
    read_server_settings()
    host = args.host or ("0.0.0.0" if args.lan else "127.0.0.1")
    try:
        srv = ThreadingHTTPServer((host, args.port), Handler)
    except OSError as e:
        print(" PROBLEM: port %d cannot be used (%s)." % (args.port, e))
        print(" Another program is using it. Start BuildCore on another port:  python server.py --port 8751")
        return
    srv.daemon_threads = True
    scheme = "http"
    if args.cert:
        import ssl
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(args.cert, args.key or args.cert)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
        scheme = "https"
    api_team.SERVER.update({"mode": "network" if host != "127.0.0.1" else "local", "port": args.port,
                            "tls": scheme == "https", "started": core.now(),
                            "addresses": ["%s://%s:%d" % (scheme, a, args.port) for a in lan_ips()]})
    url = "%s://127.0.0.1:%d" % (scheme, args.port)
    if args.desktop:
        # The desktop app keeps our stdin open; when the app closes (or crashes) stdin ends and we stop.
        def watch_parent():
            try:
                while sys.stdin.read(1024):
                    pass
            except Exception:
                pass
            os._exit(0)
        threading.Thread(target=watch_parent, daemon=True).start()
        print("BUILDCORE_READY %d" % args.port, flush=True)
    print(" Running. Open this address in Chrome or Edge:  %s" % url)
    if host != "127.0.0.1":
        for a in api_team.SERVER["addresses"]:
            print(" Other computers (office network or VPN):  %s" % a)
        if not api_team.SERVER["addresses"]:
            print(" No network address found - this computer is not on a network.")
        print(" Computers outside the office network or VPN are %s." %
              ("ALLOWED (setting 'allow_public')" if ALLOW_PUBLIC[0] else "refused"))
    print(" Data file: %s" % DB_PATH)
    if not args.desktop:
        print(" KEEP THIS WINDOW OPEN while using BuildCore. Closing it stops the app.")
        print(" Tip: do not click inside this window; Windows may pause the app (press Esc to resume).")
    print("=" * 64)
    if not args.no_browser and not args.desktop:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("Stopping...")
        srv.shutdown()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_error("start-up")
        print("BuildCore could not start. The error is saved in data\\error.log")
