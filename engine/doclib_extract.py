"""
Text extraction for the BuildCore document library (2.34), ported from the Document Manager tool.

Every format is optional. If a reader is missing, or a file has no text layer (for example a scanned PDF), the
document is still in the library and is found by its title, number, revision, tags, project, category and file name.
BuildCore ships pypdf in backend/vendor; Excel .xlsx is read straight from its XML (no openpyxl needed); old binary
Office / Outlook files (.doc .xls .ppt .msg) give their readable text runs.
"""
from __future__ import annotations

import email
import html
import logging
import re
import zipfile
from email import policy
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

logging.getLogger("pypdf").setLevel(logging.ERROR)

MAX_CHARS = 500_000                   # text kept per document (keeps the data file small)
MAX_PDF_PAGES = 600
MAX_BINARY_SCAN = 40 * 1024 * 1024    # bytes scanned in old .doc / .ppt / .msg files
MAX_DXF_BYTES = 300 * 1024 * 1024
MAX_EMPTY_ROWS = 2000                 # stop reading a sheet after this many blank rows

PLAIN_TEXT = {".txt", ".csv", ".tsv", ".md", ".log", ".json", ".xml", ".ini", ".cfg",
              ".yaml", ".yml", ".sql", ".bat", ".py", ".kml", ".gpx"}


# ------------------------------------------------------------------ helpers
def _clean(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t\r\f\v\u00a0]+", " ", text)
    text = re.sub(r" ?\n[\s]*", "\n", text)
    return text.strip()[:MAX_CHARS]


def _read_text_file(path: Path) -> str:
    raw = path.read_bytes()[:MAX_CHARS * 2]
    for enc in ("utf-8-sig", "utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig",):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("cp1252", errors="ignore")


def _natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


# ---------------------------------------------------------------------- PDF
def _pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path), strict=False)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            return ""
    out, total = [], 0
    for i, page in enumerate(reader.pages):
        if i >= MAX_PDF_PAGES or total > MAX_CHARS:
            break
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        out.append(t)
        total += len(t)
    return "\n".join(out)


# --------------------------------------------- Office Open XML / OpenDocument
_DROP = re.compile(r"<w:(instrText|delText)\b[^>]*>.*?</w:\1>", re.S)
_BREAKS = re.compile(r"</w:p>|</a:p>|</text:p>|</text:h>|<w:br\b[^>]*/>|<w:cr\b[^>]*/>|<a:br\b[^>]*/>")
_TABS = re.compile(r"<w:tab\b[^>]*/>|<text:tab\b[^>]*/>|</table:table-cell>")
_TAGS = re.compile(r"<[^>]+>")


def _xml_to_text(xml: str) -> str:
    xml = _DROP.sub("", xml)
    xml = _BREAKS.sub("\n", xml)
    xml = _TABS.sub("\t", xml)
    return html.unescape(_TAGS.sub("", xml))


def _zip_xml(path: Path, patterns) -> str:
    parts, total = [], 0
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if any(re.fullmatch(p, n) for p in patterns)]
        for n in sorted(names, key=_natural_key):
            t = _xml_to_text(z.read(n).decode("utf-8", "ignore"))
            parts.append(t)
            total += len(t)
            if total > MAX_CHARS:
                break
    return "\n".join(parts)


def _docx(path):
    return _zip_xml(path, [r"word/document\.xml", r"word/header\d*\.xml", r"word/footer\d*\.xml",
                           r"word/footnotes\.xml", r"word/endnotes\.xml"])


def _pptx(path):
    return _zip_xml(path, [r"ppt/slides/slide\d+\.xml", r"ppt/notesSlides/notesSlide\d+\.xml"])


def _odf(path):
    return _zip_xml(path, [r"content\.xml"])


_XL_SST = re.compile(r"<si>(.*?)</si>", re.S)
_XL_T = re.compile(r"<t[^>]*>(.*?)</t>", re.S)
_XL_INLINE = re.compile(r"<is>(.*?)</is>", re.S)
_XL_NUM = re.compile(r"<c [^>]*?(?<!t=\"s\")>\s*<v>([^<]*)</v>", re.S)


def _xlsx(path):
    """Shared strings (all the words), inline strings and sheet names, read from the workbook XML."""
    out, total = [], 0
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if "xl/workbook.xml" in names:
            out += re.findall(r'<sheet [^>]*name="([^"]*)"', z.read("xl/workbook.xml").decode("utf-8", "ignore"))
        if "xl/sharedStrings.xml" in names:
            for si in _XL_SST.findall(z.read("xl/sharedStrings.xml").decode("utf-8", "ignore")):
                t = html.unescape("".join(_XL_T.findall(si))).strip()
                if t:
                    out.append(t)
                    total += len(t)
                if total > MAX_CHARS:
                    break
        for n in sorted((x for x in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", x)), key=_natural_key):
            if total > MAX_CHARS:
                break
            for si in _XL_INLINE.findall(z.read(n).decode("utf-8", "ignore")):
                t = html.unescape("".join(_XL_T.findall(si))).strip()
                if t:
                    out.append(t)
                    total += len(t)
    return "\n".join(out)


def _xls(path):
    return _binary_strings(path)


# ------------------------------------------------ old binary Office / Outlook
_ASCII_RUN = re.compile(rb"[\x20-\x7e\t]{5,}")
# UTF-16LE text: Latin characters (xx 00) and Devanagari for Nepali (xx 09)
_U16_RUN = re.compile(rb"(?:[\x20-\x7e\t]\x00|[\x00-\x7f]\x09){5,}")


def _wordy(s: str) -> bool:
    """Looks like real words: mostly letters/digits/spaces, with at least one run of 3 letters."""
    if not re.search(r"[A-Za-zऀ-ॿ]{3}", s):
        return False
    good = sum(ch.isalnum() or ch in " .,-/()&:;'\"%+" or "ऀ" <= ch <= "ॿ" for ch in s)
    return good >= 0.85 * len(s)


# Style, font and storage names Office writes into every old binary file
_OFFICE_NOISE = re.compile(
    r"^(heading( \d)?|.* char|list( \w+)*( \d)?|body text.*|normal.*|default paragraph font|table (normal|grid)|"
    r"no (list|spacing)|title|subtitle|caption|header|footer|header and footer|index.*|toc.*|"
    r"root entry|compobj|\d?table|(document)?summaryinformation|worddocument|powerpoint document|"
    r"current user|pictures|word\.document\.\d+|msworddoc|microsoft .*|times new roman|arial.*|calibri.*|"
    r"cambria.*|symbol|courier.*|wingdings.*|liberation .*|noto .*|freesans|tahoma|verdana|georgia|"
    r"strong|emphasis|intense .*|subtle .*|book title|quote.*|listlabel \d+|wwnum\d+|macro.*|hyperlink|"
    r"followedhyperlink|balloon text.*|caolan\d+|appversion|_pid_.*|compatibility.*|"
    r"(generated by )?python-docx|ole|ole10native|\x01?comp ?obj|workbook|book|sheet\d*|"
    r"__substg.*|__properties.*|__nameid.*|__recip.*|__attach.*|ipm\..*)$", re.I)


def _binary_strings(path) -> str:
    """Pull readable text runs out of old .doc/.ppt/.xls/.msg files (8-bit and UTF-16)."""
    data = Path(path).read_bytes()[:MAX_BINARY_SCAN]
    runs = [m.group().decode("cp1252", "ignore") for m in _ASCII_RUN.finditer(data)]
    for m in _U16_RUN.finditer(data):
        chunk = m.group()
        if len(chunk) % 2:
            chunk = chunk[:-1]
        runs.append(chunk.decode("utf-16-le", "ignore"))
    keep, seen = [], set()
    for r in runs:
        r = r.strip()
        if _wordy(r) and r not in seen and not _OFFICE_NOISE.match(r):
            seen.add(r)
            keep.append(r)
    return "\n".join(keep)


# ---------------------------------------------------------------------- RTF
_RTF_SKIP = ("fonttbl", "colortbl", "stylesheet", "info", "pict", "themedata", "colorschememapping",
             "latentstyles", "datastore", "listtable", "listoverridetable", "rsidtbl", "generator")


def _rtf(path):
    s = _read_text_file(path)
    # drop destination groups that hold no document text
    out, i, n = [], 0, len(s)
    while i < n:
        if s[i] == "{":
            m = re.match(r"\{\\(\*\\)?([a-zA-Z]+)", s[i:i + 40])
            if m and (m.group(1) or m.group(2) in _RTF_SKIP):
                depth = 0
                while i < n:
                    if s[i] == "\\":
                        i += 2
                        continue
                    if s[i] == "{":
                        depth += 1
                    elif s[i] == "}":
                        depth -= 1
                        if depth == 0:
                            i += 1
                            break
                    i += 1
                continue
        out.append(s[i])
        i += 1
    s = "".join(out)
    s = re.sub(r"\\u(-?\d+)\??(\\'[0-9a-fA-F]{2}|.)?", lambda m: chr(int(m.group(1)) % 65536), s)
    s = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes([int(m.group(1), 16)]).decode("cp1252", "ignore"), s)
    s = re.sub(r"\\(par|line|row)\b ?", "\n", s)
    s = re.sub(r"\\(tab|cell)\b ?", "\t", s)
    s = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", s)
    s = s.replace("\\{", "{").replace("\\}", "}").replace("\\\\", "\\")
    return re.sub(r"[{}]", "", s)


# ---------------------------------------------------------------- DXF (CAD)
_MTEXT_CODES = re.compile(r"\\[ACcFfHhQqTtWw][^;]*;|\\[LlOoKk]")


def _dxf(path: Path) -> str:
    if path.stat().st_size > MAX_DXF_BYTES:
        return ""
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="ignore")
    lines = text.splitlines()
    out = []
    section = ""
    for i in range(0, len(lines) - 1, 2):
        code, val = lines[i].strip(), lines[i + 1].strip()
        if code == "0" and val == "SECTION" and i + 3 < len(lines) and lines[i + 2].strip() == "2":
            section = lines[i + 3].strip()
            continue
        if section not in ("ENTITIES", "BLOCKS"):
            continue
        if code in ("1", "3"):     # TEXT / MTEXT / ATTRIB / ATTDEF values
            v = lines[i + 1].strip()
            if not v:
                continue
            v = v.replace("\\P", "\n").replace("%%c", "Ø").replace("%%C", "Ø")
            v = v.replace("%%d", "°").replace("%%D", "°").replace("%%p", "±").replace("%%P", "±")
            v = _MTEXT_CODES.sub("", v).replace("{", "").replace("}", "")
            if v.strip():
                out.append(v)
    return "\n".join(out)


# -------------------------------------------------------------- email / html
def _html_to_text(s: str) -> str:
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>|</h\d>", "\n", s)
    return html.unescape(_TAGS.sub(" ", s))


def _html(path):
    return _html_to_text(_read_text_file(path))


def _eml(path):
    with open(path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=policy.default)
    head = [f"{k}: {msg.get(k, '')}" for k in ("Subject", "From", "To", "Cc", "Date") if msg.get(k)]
    body_text = ""
    body = msg.get_body(preferencelist=("plain", "html"))
    if body is not None:
        try:
            body_text = body.get_content()
        except Exception:
            body_text = ""
        if body.get_content_type() == "text/html":
            body_text = _html_to_text(body_text)
    attachments = [p.get_filename() for p in msg.iter_attachments() if p.get_filename()]
    if attachments:
        head.append("Attachments: " + ", ".join(attachments))
    return "\n".join(head) + "\n" + body_text


# ----------------------------------------------------------------- dispatch
HANDLERS = {
    ".pdf": _pdf,
    ".docx": _docx, ".docm": _docx, ".dotx": _docx,
    ".pptx": _pptx, ".pptm": _pptx,
    ".xlsx": _xlsx, ".xlsm": _xlsx,
    ".xls": _xls,
    ".odt": _odf, ".ods": _odf, ".odp": _odf,
    ".doc": _binary_strings, ".ppt": _binary_strings, ".msg": _binary_strings,
    ".rtf": _rtf,
    ".dxf": _dxf,
    ".eml": _eml,
    ".htm": _html, ".html": _html,
}
for _e in PLAIN_TEXT:
    HANDLERS[_e] = _read_text_file


def readable_types():
    return sorted(HANDLERS)


def capabilities():
    try:
        import pypdf  # noqa: F401
        pdf = True
    except Exception:
        pdf = False
    return {"PDF (pypdf)": pdf, "Excel .xlsx": True, "Old Excel .xls (text runs)": True}


def extract_text(path):
    """Return (text, status). status: 'ok', 'empty' (no text found), 'unsupported' or 'error'."""
    path = Path(path)
    fn = HANDLERS.get(path.suffix.lower())
    if fn is None:
        return "", "unsupported"
    try:
        text = _clean(fn(path))
    except ImportError:
        return "", "unsupported"
    except Exception:
        return "", "error"
    return text, ("ok" if text else "empty")
