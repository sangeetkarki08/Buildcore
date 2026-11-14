"""Prepare public/ for fast delivery. Safe to run any number of times; sync_desktop.py runs it after each sync.

    python tools/web_build.py

  1. Fonts: a WOFF2 copy of each TTF in public/fonts (the same font, compressed: about half the bytes), listed first
     in app.css with font-display: swap so text shows at once in a fallback font while the font arrives.
     Needs `pip install fonttools brotli` on the computer that runs this; without it the TTF fonts are used as before.
  2. Versions: every script, stylesheet and font address gets ?v=<first 10 characters of the file's SHA-256>. Vercel
     (vercel.json) lets browsers keep versioned files for a year without asking again; a changed file gets a new
     address, so nobody is left with an old copy. Addresses without ?v= are still checked on every visit.

Nothing else in the screens changes.
"""
import hashlib
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, "public")
VER = re.compile(r"\?v=[0-9a-f]{6,64}")


def digest(path):
    """The file's version. Text files are read with LF line endings (as Git stores them), so every computer gives the
    same version for the same content whatever its checkout does with line endings."""
    with open(path, "rb") as fh:
        data = fh.read()
    if path.endswith((".js", ".css", ".html")):
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()[:10]


def read(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def make_woff2(fonts):
    """WOFF2 next to each TTF. Returns the names that have a WOFF2 copy."""
    try:
        from fontTools.ttLib import TTFont
        import brotli  # noqa: F401  (fontTools needs it for WOFF2)
    except ImportError:
        print("  note - fonttools/brotli not installed: WOFF2 fonts not made (pip install fonttools brotli)")
        TTFont = None
    have = set()
    for name in sorted(os.listdir(fonts)):
        if not name.lower().endswith(".ttf"):
            continue
        src = os.path.join(fonts, name)
        dst = src[:-4] + ".woff2"
        if TTFont is not None and (not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src)):
            f = TTFont(src, recalcTimestamp=False)      # same bytes every time, so the version only changes with the font
            f.flavor = "woff2"
            f.save(dst)
            print("  font %s: %d KB -> %s %d KB" % (name, os.path.getsize(src) // 1024, os.path.basename(dst),
                                                    os.path.getsize(dst) // 1024))
        if os.path.exists(dst):
            have.add(name)
    return have


def fix_css(css, have_woff2):
    """@font-face: WOFF2 first (when made), TTF as the fallback, font-display: swap, versioned addresses."""
    def face(m):
        block = m.group(0)
        url = re.search(r'url\("(/fonts/[^"?]+\.ttf)(?:\?v=[0-9a-f]+)?"\)\s*format\("truetype"\)', block)
        if not url:
            return block
        ttf = url.group(1)
        ttf_path = os.path.join(PUBLIC, ttf.lstrip("/"))
        if not os.path.exists(ttf_path):
            return block
        srcs = []
        if os.path.basename(ttf) in have_woff2:
            w = ttf[:-4] + ".woff2"
            srcs.append('url("%s?v=%s") format("woff2")' % (w, digest(os.path.join(PUBLIC, w.lstrip("/")))))
        srcs.append('url("%s?v=%s") format("truetype")' % (ttf, digest(ttf_path)))
        block = re.sub(r"src:[^;]*;", "src: " + ", ".join(srcs) + ";", block, count=1)
        if "font-display" not in block:
            block = block.rstrip("}").rstrip() + " font-display: swap; }"
        return block
    return re.sub(r"@font-face\s*\{[^}]*\}", face, css)


def stamp_html(html):
    """?v=<hash> on each local script and stylesheet."""
    def one(m):
        attr, path = m.group(1), m.group(2)
        f = os.path.join(PUBLIC, path.lstrip("/"))
        if not os.path.isfile(f):
            return m.group(0)
        return '%s="%s?v=%s"' % (attr, path, digest(f))
    return re.sub(r'(src|href)="(/[^"?#]+\.(?:js|css))(?:\?v=[0-9a-f]+)?"', one, html)


def main():
    if not os.path.isfile(os.path.join(PUBLIC, "index.html")):
        sys.exit("public/index.html not found")
    fonts = os.path.join(PUBLIC, "fonts")
    have = make_woff2(fonts) if os.path.isdir(fonts) else set()
    css_path = os.path.join(PUBLIC, "app.css")
    if os.path.exists(css_path):
        css = read(css_path)
        new = fix_css(css, have)
        if new != css:
            write(css_path, new)
            print("  app.css: fonts updated")
    html_path = os.path.join(PUBLIC, "index.html")
    html = read(html_path)
    new = stamp_html(html)
    if new != html:
        write(html_path, new)
    n = len(re.findall(r'\?v=[0-9a-f]{10}"', new))
    print("  index.html: %d files versioned" % n)


if __name__ == "__main__":
    main()
