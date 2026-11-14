"""Bring a BuildCore desktop version into this web project.

    python tools/sync_desktop.py "C:\\Program Files\\BuildCore\\resources\\backend"

Copies the engine (*.py and its data files) into engine/ and the screens (static/) into public/, then makes
the few web text changes listed in WEB_TEXT below. Run it after updating the desktop app to a new version,
then commit and push: Vercel deploys the new version and the engine upgrades the database on its next start,
exactly as the desktop does with its data file.

The files in engine/web/ (the web layer) are not touched.
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(HERE, "engine")
PUBLIC = os.path.join(HERE, "public")
SKIP = {"__pycache__", "static", "tools", "data", "backups", "licence", "web"}
SKIP_FILES = {"README.md"}

# (file, desktop text, web text)
WEB_TEXT = [
    ("index.html", "<title>BuildCore Offline</title>", "<title>BuildCore</title>"),
    ("index.html", '<script src="/lib.js"></script>', '<script src="/web.js"></script>\n<script src="/lib.js"></script>'),
    ("lib.js", '"BuildCore server is not running. Keep the black BuildCore window open (start it with START_BuildCore_Windows.bat)."',
     '"Cannot reach BuildCore. Check the internet connection and try again."'),
    ("lib.js", 'throw new Error("The server sent an unexpected reply (HTTP " + r.status + "). See data/error.log.");',
     'throw new Error("The server sent an unexpected reply (HTTP " + r.status + "). The details are in the Vercel logs.");'),
    ("app.js", "Create the first administrator. Everything is stored on this computer.",
     "Create the first administrator. Everything is stored in your own Supabase database."),
    ("pages_corp.js", "Your data stays on your own computer or office server.", "Your data stays in your own Supabase database."),
    ("pages_license.js", '"Activate BuildCore on this computer"', '"Activate BuildCore"'),
]


def main(src):
    src = os.path.abspath(src)
    if not os.path.isfile(os.path.join(src, "core.py")) or not os.path.isdir(os.path.join(src, "static")):
        sys.exit("Not a BuildCore backend folder (core.py and static\\ expected): %s" % src)
    n = 0
    for name in os.listdir(src):
        p = os.path.join(src, name)
        if name in SKIP or name in SKIP_FILES or name.startswith("_backup"):
            continue
        dst = os.path.join(ENGINE, name)
        if os.path.isdir(p):
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.copytree(p, dst, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(p, dst)
        n += 1
    keep = os.path.join(PUBLIC, "web.js")
    webjs = open(keep, encoding="utf-8").read() if os.path.exists(keep) else None
    if os.path.exists(PUBLIC):
        shutil.rmtree(PUBLIC)
    shutil.copytree(os.path.join(src, "static"), PUBLIC, ignore=shutil.ignore_patterns("__pycache__"))
    # the engine itself reads one file from static/ (the formatted GRN import sample)
    os.makedirs(os.path.join(ENGINE, "static"), exist_ok=True)
    for name in ("GRN_import_sample.xlsx",):
        if os.path.exists(os.path.join(src, "static", name)):
            shutil.copy2(os.path.join(src, "static", name), os.path.join(ENGINE, "static", name))
    if webjs is not None:
        with open(keep, "w", encoding="utf-8") as fh:
            fh.write(webjs)
    missing = []
    for fname, a, b in WEB_TEXT:
        p = os.path.join(PUBLIC, fname)
        s = open(p, encoding="utf-8").read()
        if a not in s:
            missing.append("%s: %s" % (fname, a[:60]))
            continue
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(s.replace(a, b, 1))
    print("Engine: %d items copied to %s" % (n, ENGINE))
    print("Screens copied to %s" % PUBLIC)
    for m in missing:
        print("  note - text not found (check by hand): " + m)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
