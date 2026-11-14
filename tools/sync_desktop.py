"""Bring a BuildCore desktop version into this web project.

    python tools/sync_desktop.py "C:\\Program Files\\BuildCore\\resources\\backend"

Copies the engine (*.py and its data files) into engine/ and the screens (static/) into public/, then makes
the few web text changes listed in WEB_TEXT below. Run it after updating the desktop app to a new version,
then commit and push: Vercel deploys the new version and the engine upgrades the database on its next start,
exactly as the desktop does with its data file.

The files in engine/web/ (the web layer) are not touched.
"""
import os
import re
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
    # Speed (docs/performance): the whole page's text was read every 2 seconds on every screen, for Copilot's "use what
    # is on my last screen". It is now read once, as Copilot opens (before the router clears the page).
    ("pages_copilot.js", '''  setInterval(() => {
    try {
      if (!/^#\\/copilot/.test(location.hash)) {
        const pg = document.querySelector("#page");
        if (pg) window.__bcoLastScreenText = ((document.querySelector("#page h1") || {}).textContent || "") + "\\n" + pg.innerText.slice(0, 15000);
      }
    } catch (e) { /* ignore */ }
  }, 2000);''', '''  window.addEventListener("hashchange", (ev) => {      // web: read once as Copilot opens, not every 2 seconds
    try {
      if (/^#\\/copilot/.test(location.hash) && !/#\\/copilot/.test(String(ev.oldURL || ""))) {
        const pg = document.querySelector("#page");
        if (pg) window.__bcoLastScreenText = ((document.querySelector("#page h1") || {}).textContent || "") + "\\n" + pg.innerText.slice(0, 15000);
      }
    } catch (e) { /* ignore */ }
  });'''),
    # Speed: money and quantity figures were formatted with Number.toLocaleString(locale, options), which builds a new
    # number formatter for every figure (a 5,000-row table: several thousand formatters per draw). The same formatter is
    # now made once and reused; the text it gives is the same by definition (ECMA-402: toLocaleString = new
    # Intl.NumberFormat(locale, options).format).
    ("lib.js", '''const fmtMoney = (n) => n == null || n === "" ? "" : Number(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtQty = (n) => n == null || n === "" ? "" : Number(n).toLocaleString("en-IN", { maximumFractionDigits: 3 });''',
     '''const NF_MONEY = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const NF_QTY = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 3 });
const fmtMoney = (n) => n == null || n === "" ? "" : NF_MONEY.format(Number(n));
const fmtQty = (n) => n == null || n === "" ? "" : NF_QTY.format(Number(n));'''),
    # Speed: a list's "Filter these rows" box drew every row again on each key press; it now draws once typing pauses
    # (150 ms), and at once when the box is left, so keys and buttons used next always act on the filtered rows.
    ("pages_keys.js", '''      K.search = h("input", { type: "search", placeholder: "Filter these rows", oninput: () => { K.q = K.search.value; K.render(); } });''',
     '''      const runQ = () => { clearTimeout(K.qWait); K.qWait = 0; K.q = K.search.value; K.render(); };
      K.search = h("input", { type: "search", placeholder: "Filter these rows", oninput: () => { clearTimeout(K.qWait); K.qWait = setTimeout(runQ, 150); },
        onblur: () => { if (K.qWait) runQ(); } });'''),
]


def apply_web_text():
    """Make the WEB_TEXT changes in public/ (files are read with any line endings and written with LF). A change already
    made is left alone. Returns the ones whose desktop text was not found."""
    missing = []
    for fname, a, b in WEB_TEXT:
        p = os.path.join(PUBLIC, fname)
        s = open(p, encoding="utf-8").read()
        if b in re.sub(r"\?v=[0-9a-f]{6,64}", "", s):      # already made (web_build.py may have versioned the addresses)
            continue
        if a not in s:
            missing.append("%s: %s" % (fname, a[:60]))
            continue
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(s.replace(a, b, 1))
    return missing


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
    missing = apply_web_text()
    print("Engine: %d items copied to %s" % (n, ENGINE))
    print("Screens copied to %s" % PUBLIC)
    for m in missing:
        print("  note - text not found (check by hand): " + m)
    # fonts as WOFF2 and versioned addresses, so browsers keep the files (tools/web_build.py)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import web_build
    web_build.main()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
