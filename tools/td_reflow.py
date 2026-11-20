#!/usr/bin/env python3
"""Paragraph reconstitution for TD transcripts from page layout (2026-11-20).

Why: printed line breaks were kept in the transcripts, so every printed line showed as its own line, and the old
bulletins ran their paragraphs together. This module rebuilds paragraphs from the page geometry and moves page
furniture out of the text. It only ever changes whitespace and line-end hyphens; `guard()` proves that on
every build.

Inputs:
  - a PDF: ``pdftotext -bbox-layout`` (each line's x/y extent and each word's width);
  - a plain .txt (the IRS T.D. 8734 file): monospace, with columns counted in characters.

The rule, per pair of consecutive lines on a page:
  - the previous line was *wrapped* when its first word would not have fitted on it (prev right edge + space +
    the next line's first word > the local right margin);
  - a wrapped line JOINS the next one unless the next line is indented (a new paragraph) or is a structural start
    (ART. / PAR. / (a) / § ...) right after a sentence end;
  - a line that was not wrapped ends its block.
Consecutive one-line short blocks (letterhead, signature, list items, headings) are grouped and keep their line
breaks (rendered with <br>); every other block is one paragraph on one Markdown line.

Furniture: a printed page number at the top or bottom of a page is kept (it goes into the page marker,
`<!-- page: N printed: X -->`). Running heads, the HathiTrust "Google" watermark, GPO printer's signatures
and lines of stray marks are dropped, and each drop is listed.
"""
import html
import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class Line:
    x0: float
    x1: float
    y0: float
    text: str
    fw: float            # width of the first word
    space: float         # typical width of one space at this line's size
    trailing: bool = False   # .txt only: the line ended with spaces (the source's paragraph-end mark)
    y1: float = 0.0
    words: list = field(default_factory=list)   # PDF only: (x0, x1, text)
    col: int = 0             # two-column pages: 0 left, 1 right, 2 full width
    base: float = 0.0        # baseline: median bottom of the line's alphanumeric words (tall marks like * skew a box)


@dataclass
class Page:
    lines: list
    width: float
    height: float
    printed: str = ""                 # printed page number, if found
    dropped: list = field(default_factory=list)


# ----------------------------------------------------------------------------- input

_LINE_RE = re.compile(r'<line xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</line>', re.S)
_WORD_RE = re.compile(r'<word xMin="([\d.]+)" yMin="[\d.]+" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>', re.S)
_PAGE_RE = re.compile(r'<page width="([\d.]+)" height="([\d.]+)">(.*?)</page>', re.S)


def pdf_pages(pdf: str, columns: int = 1) -> list:
    out = subprocess.run(["pdftotext", "-bbox-layout", pdf, "-"], capture_output=True, text=True).stdout
    pages = []
    for pm in _PAGE_RE.finditer(out):
        w, h = float(pm.group(1)), float(pm.group(2))
        lines = []
        for lm in _LINE_RE.finditer(pm.group(3)):
            raw = _WORD_RE.findall(lm.group(5))
            words = [(float(a), float(b), html.unescape(t)) for a, b, _y, t in raw]
            y0l, y1l = float(lm.group(2)), float(lm.group(4))
            # marks only ("(", "*"): their boxes run from ascender to descender; take three quarters down
            bots = sorted(float(y) for _a, _b, y, t in raw if re.search(r"\w", t)) or [y0l + 0.75 * (y1l - y0l)]
            if not words:
                continue
            gaps = [words[i + 1][0] - words[i][1] for i in range(len(words) - 1)]
            gaps = [g for g in gaps if g > 0]
            space = sorted(gaps)[len(gaps) // 2] if gaps else (float(lm.group(4)) - float(lm.group(2))) * 0.3
            lines.append(Line(float(lm.group(1)), float(lm.group(3)), float(lm.group(2)),
                              _text(words, space), words[0][1] - words[0][0], space, words=words,
                              y1=float(lm.group(4)), base=bots[len(bots) // 2]))
        lines = _order(_rows(lines, w, columns), w, columns)
        pages.append(Page(lines, w, h))
    return pages


def _glue(a: str, b: str) -> bool:
    """Two touching OCR boxes are one printed word only around a hyphen or punctuation ("sixty", "-", "five";
    "charter", ","); two touching letter words stay apart (OCR boxes overlap: "of" "its")."""
    if len(a) == 1 and a.isupper() and b.isupper() and b.isalpha():
        return True                      # small capitals set as a capital + a smaller word: "R" "ETURNS"
    return a.endswith(("-", "(", "[", "\u201c")) or b.startswith(("-", ",", ".", ";", ":", ")", "]", "?", "!"))


def _text(words, space):
    text = words[0][2]
    for k in range(1, len(words)):
        tight = words[k][0] - words[k - 1][1] < 0.25 * space
        text += ("" if tight and _glue(words[k - 1][2], words[k][2]) else " ") + words[k][2]
    return text


def _text_seq(words, space):
    """Like _text, for words already in reading order (after a splice): a negative gap counts as a space."""
    text = words[0][2]
    for k in range(1, len(words)):
        gap = words[k][0] - words[k - 1][1]
        text += ("" if 0 <= gap < 0.25 * space and _glue(words[k - 1][2], words[k][2]) else " ") + words[k][2]
    return text


def _rows(lines, width, columns):
    """Rebuild printed lines from OCR fragments.

    OCR text layers split one printed line into pieces at slightly different heights, and set marks ("(", "*")
    in boxes of their own. Pass 1 merges word pieces whose baselines agree (within 0.45 of a line height) and
    whose words do not overlap. A short piece whose boxes collide with its line is spliced in by position.
    Pass 2 attaches each marks-only piece to the line holding the word it touches (within 1.5 spaces), else to
    the nearest line by baseline. On a two-column page pieces never cross the gutter."""
    mid = width / 2
    side = (lambda l: 0 if l.x1 <= mid + width * 0.02 else (1 if l.x0 >= mid - width * 0.02 else 2)) \
        if columns > 1 else (lambda l: 0)

    def apart(l, m):
        for a0, a1, _t in l.words:
            for b0, b1, _u in m.words:
                slop = min(2.0, 0.3 * min(a1 - a0, b1 - b0))
                if a1 > b0 + slop and a0 < b1 - slop:
                    return False
        return True

    marks = [l for l in lines if not re.search(r"\w", l.text)]
    rows = []                    # each row: dict(base, h, side, words, spliced)
    for l in sorted((l for l in lines if re.search(r"\w", l.text)), key=lambda l: l.base):
        h = max(1.0, l.y1 - l.y0)
        for r in reversed(rows[-4:]):
            if abs(l.base - r["base"]) >= 0.45 * min(h, r["h"]) or side(l) != r["side"]:
                continue
            host = Line(0, 0, 0, "", 0, l.space, words=r["words"])
            if apart(l, host):
                r["words"] = r["words"] + list(l.words)
                r["sorted"] = False
                break
            # the words collide (OCR boxes overlap): splice the new piece in as a block, placed by its centre
            # among the row's word centres
            fc = (l.x0 + l.x1) / 2
            ws = r["words"] if r["spliced"] else sorted(r["words"], key=lambda w: w[0])
            r["words"] = [w for w in ws if (w[0] + w[1]) / 2 < fc] + list(l.words) + \
                         [w for w in ws if (w[0] + w[1]) / 2 >= fc]
            r["spliced"] = True
            break
        else:
            rows.append({"base": l.base, "h": h, "side": side(l), "words": list(l.words), "spliced": False,
                         "sorted": False, "space": l.space, "y0": l.y0, "y1": l.y1})
            continue
        r["y0"], r["y1"] = min(r["y0"], l.y0), max(r["y1"], l.y1)
    for m in marks:
        h = max(1.0, m.y1 - m.y0)
        best = None
        for r in rows:
            mcy = (m.y0 + m.y1) / 2
            if not (r["y0"] <= mcy <= r["y1"]) or side(m) != r["side"]:
                continue                 # a mark joins only a line it sits inside vertically
            gaps = [w[0] - m.x1 for w in r["words"]] + [m.x0 - w[1] for w in r["words"]]
            touch = min((g for g in gaps if -1.0 <= g <= 1.5 * r["space"]), default=None)
            if touch is None and abs(m.base - r["base"]) >= 0.45 * min(h, r["h"]):
                continue                 # neither touching a word nor on the same baseline: not this line
            score = (0 if touch is not None else 1, abs(m.base - r["base"]))
            if best is None or score < best[0]:
                best = (score, r)
        if best is None:
            rows.append({"base": m.base, "h": h, "side": side(m), "words": list(m.words), "spliced": False,
                         "sorted": False, "space": m.space, "y0": m.y0, "y1": m.y1})
            continue
        r = best[1]
        if r["spliced"]:                 # keep the splice order: put the mark by position among the words
            mc = (m.x0 + m.x1) / 2
            r["words"] = [w for w in r["words"] if (w[0] + w[1]) / 2 < mc] + list(m.words) + \
                         [w for w in r["words"] if (w[0] + w[1]) / 2 >= mc]
        else:
            r["words"] = r["words"] + list(m.words)
    out = []
    for r in rows:
        ws = r["words"] if r["spliced"] else sorted(r["words"], key=lambda w: w[0])
        txt = _text_seq(ws, r["space"]) if r["spliced"] else _text(ws, r["space"])
        out.append(Line(min(w[0] for w in ws), max(w[1] for w in ws), r["y0"], txt, ws[0][1] - ws[0][0],
                        r["space"], words=ws, y1=r["y1"], base=r["base"]))
    return out


def _order(lines, width, columns):
    """Reading order. One column: top to bottom. Two columns: bands between full-width lines, and inside each
    band the left column, then the right."""
    lines = sorted(lines, key=lambda l: (l.base, l.x0))
    if columns == 1:
        return lines
    mid, g = width / 2, width * 0.02
    out, band = [], []

    def flush():
        for c, part in ((0, [l for l in band if l.x1 <= mid + g]), (1, [l for l in band if l.x1 > mid + g])):
            for l in sorted(part, key=lambda l: l.base):
                l.col = c
                out.append(l)
        band.clear()
    for l in lines:
        if l.x0 < mid - g and l.x1 > mid + g:        # spans the gutter: a full-width line
            flush()
            l.col = 2
            out.append(l)
        else:
            band.append(l)
    flush()
    return out


def txt_pages(text: str) -> list:
    pages = []
    for chunk in text.replace("\r", "").split("\f"):
        lines = []
        for i, raw in enumerate(chunk.split("\n")):
            if not raw.strip():
                continue
            ind = len(raw) - len(raw.lstrip(" "))
            body = raw.strip()
            lines.append(Line(float(ind), float(ind + len(body)), float(i), re.sub(r"\s+", " ", body),
                              float(len(body.split(" ")[0])), 1.0, trailing=raw != raw.rstrip()))
        pages.append(Page(lines, 0.0, 0.0))
    return pages


# ----------------------------------------------------------------------------- furniture

_PAGENO = re.compile(r"^[-–—\s]*(\d{1,4})[-–—\s]*$")
_RUNNING = [re.compile(p) for p in (
    r"^TREASURY DECISION \d+\s*\(\d{4}\)$",
    r"^Internal Revenue Service, Treasury\b",
    r"\b26 CFR Ch\. I\b",
    r"^§\s*[\d.]+[–-]\d+[A-Za-z]?$",                 # the section number half of a CFR running head
)]
_WATERMARK = re.compile(r"^(Digitized by\s+)?Google$", re.I)
_PRINTER = re.compile(r"^(\d{4,6}\s*°?\s*[-–]?\s*VOL\.?\s*\d+[-–\d\s]*|\d{4,6}\s*°[-–—\s\d]*)$", re.I)
_STRAY = re.compile(r"^[-–—:;.,'\"_~•·|\s]+$")


def strip_furniture(pages: list, pdf: bool) -> None:
    """In place: drop furniture lines, record each page's printed number."""
    for p in pages:
        if not p.lines:
            continue
        keep = []
        by_y = sorted(range(len(p.lines)), key=lambda k: p.lines[k].base if pdf else k)
        edges = set(by_y[:2] + by_y[-2:])         # the two top and two bottom lines by position
        for i, l in enumerate(p.lines):
            t = l.text.strip()
            edge = i in edges
            if pdf and edge and _PAGENO.match(t) and not p.printed:
                p.printed = _PAGENO.match(t).group(1)
                p.dropped.append(("printed page number", t))
                continue
            if pdf and edge and any(r.search(t) for r in _RUNNING):
                p.dropped.append(("running head", t))
                continue
            if _WATERMARK.match(t):
                p.dropped.append(("scan watermark", t))
                continue
            if _PRINTER.match(t):
                p.dropped.append(("printer's signature", t))
                continue
            if _STRAY.match(t) and "*" not in t:
                p.dropped.append(("stray marks", t))
                continue
            keep.append(l)
        p.lines = keep


# ----------------------------------------------------------------------------- reflow

_STRUCT = re.compile(r"^(ART\.|Art\.|PAR\.|Par\.|PARAGRAPH\b|SEC\.|Sec\.|SECTION\b|§|\(\w{1,4}\)\s|\d{1,2}\.\s|[A-Z]\.\s"
                     r"|Example \d|\* \*|[A-Z][A-Z ,.'&-]{3,}:|To [Cc]ollectors|Approved:)")
_LABEL = re.compile(r"^([A-Z][A-Z ,.'&-]{3,}:\s|\[)")      # "AGENCY: ", "SUMMARY: ", "[TD 8734]": always a new line
_SENT_END = re.compile(r"[.:;?!—]['\"”’)]*$")


def _margins(lines, txt=False):
    xs0 = sorted(l.x0 for l in lines)
    left = xs0[len(xs0) // 5] if xs0 else 0.0
    if txt:   # the typical full line of the file (its median length)
        xs1 = sorted(l.x1 - l.x0 for l in lines)
        return left, (xs1[len(xs1) // 2] if xs1 else 85.0)
    xs1 = sorted(l.x1 for l in lines)
    right = xs1[min(len(xs1) - 1, int(len(xs1) * 0.9))] if xs1 else 0.0
    return left, right


def _wrapped(prev: Line, cur: Line, right: float, txt: bool) -> bool:
    if txt:
        # the IRS file was wrapped by a word processor in a proportional font, so character counts cannot tell
        # a wrap; a line runs on unless it is short, or it ends a sentence with the file's trailing-space mark
        if prev.x1 - prev.x0 < 0.7 * right:
            return False
        return not (prev.trailing and _SENT_END.search(prev.text))
    return prev.x1 + prev.space + cur.fw > right - 0.5 * prev.space


def _indented(cur: Line, left: float, right: float, txt: bool) -> bool:
    tol = 2.5 if txt else max(3.5, (right - left) * 0.018)
    return cur.x0 > left + tol


def _local_right(lines, i, left, right):
    near = [l.x1 for l in lines[max(0, i - 3): i + 3]]
    r = max(near) if near else right
    return r if r > left + 0.85 * (right - left) else right


def _join(a: str, b: str, compounds: set) -> str:
    m = re.search(r"([A-Za-z]+)-$", a)
    if m and b[:1].islower():
        word = m.group(1) + "-" + re.match(r"[A-Za-z]*", b).group(0)
        if word.lower() in compounds:
            return a + b
        return a[:-1] + b
    if a.endswith("—"):
        return a + b
    return a + " " + b


@dataclass
class Logical:
    text: str
    nphys: int
    short: bool
    open_end: bool = False        # the last physical line was wrapped to the next page


def reflow_page(p: Page, txt: bool, compounds: set) -> list:
    lines = p.lines
    if not lines:
        return []
    cols = {}
    for c in {l.col for l in lines}:
        cols[c] = _margins([l for l in lines if l.col == c], txt)
    out = []
    for i, cur in enumerate(lines):
        left, right = cols[cur.col]
        if out:
            prev = lines[i - 1]
            pl, pr = cols[prev.col]
            same = [l for l in lines if l.col == prev.col]
            r = pr if txt else _local_right(same, same.index(prev), pl, pr)
            # an indented line starts a paragraph only after a sentence end: after a wrapped line that ends
            # mid-sentence it is a centred or hanging-indent continuation (headnotes, centred titles)
            ends = bool(_SENT_END.search(prev.text))
            # a display line (indented well past the margin: letterhead, centred title) ends at a comma or a
            # sentence end; otherwise it runs on (a centred or indented headnote set over several lines)
            display = not txt and prev.x0 > pl + 0.08 * (pr - pl) and (
                bool(re.search(r"[.,:;]['\")]*$", prev.text)) or (prev.x1 - prev.x0) < 0.5 * (pr - pl))
            brk = (not _wrapped(prev, cur, r, txt) or display
                   or (_indented(cur, left, right, txt) and (ends or txt))
                   or (_STRUCT.match(cur.text) and ends)
                   or bool(_LABEL.match(cur.text)))
            if not brk:
                o = out[-1]
                o.text = _join(o.text, cur.text, compounds)
                o.nphys += 1
                o.short = False
                continue
        width = (right - left) or 1.0
        out.append(Logical(cur.text, 1, (cur.x1 - cur.x0) < 0.75 * width
                           or (not txt and cur.x0 > left + 0.08 * width)))   # short, or a centred display line
    # does the page end mid-paragraph?
    last = lines[-1]
    left, right = cols[last.col]
    sp = 1 if txt else last.space
    out[-1].open_end = last.x1 + 4 * sp > right and not (txt and last.trailing)
    return out


def _marker(n: int, printed: str) -> str:
    return f"<!-- page: {n}{' printed: ' + printed if printed else ''} -->"


def _md_escape(s: str) -> str:
    """A body line must not read as Markdown structure to build_td_html (a '#', '>' or '---' line)."""
    if s.startswith(("#", ">")) or s.strip() == "---":
        return "​" + s
    return s


def reflow_document(pages: list, txt: bool) -> str:
    joined = " ".join(l.text for p in pages for l in p.lines)
    compounds = {w.lower() for w in re.findall(r"\b[A-Za-z]+-[A-Za-z]+\b", joined)}
    parts = []
    carry = None          # an open paragraph from the previous page: (block list, text)
    for n, p in enumerate(pages, 1):
        logical = reflow_page(p, txt, compounds)
        marker = _marker(n, p.printed)
        if not logical:
            if carry is None:
                parts.append(marker)
            continue
        first = logical[0]
        first_line = p.lines[0]
        left, right = _margins(p.lines, txt)
        cont = carry is not None and not _indented(first_line, left, right, txt) and not _STRUCT.match(first.text)
        if carry is not None and cont:
            parts[-1] = _join(parts[-1], marker + " " + first.text, set()) if not parts[-1].endswith("-") \
                else parts[-1][:-1] + marker + first.text
            logical = logical[1:]
        else:
            parts.append(marker)
        carry = None
        # group consecutive one-line short blocks; every other block is its own paragraph
        group = []
        for j, lg in enumerate(logical):
            single = lg.nphys == 1 and lg.short
            if single:
                group.append(_md_escape(lg.text))
                continue
            if group:
                parts.append("\n".join(group))
                group = []
            parts.append(_md_escape(lg.text))
        if group:
            parts.append("\n".join(group))
        if logical and logical[-1].open_end and not (logical[-1].nphys == 1 and logical[-1].short):
            carry = True
    return "\n\n".join(parts)


# ----------------------------------------------------------------------------- guard

_MARK_RE = re.compile(r"<!--\s*page:[^>]*-->")


def _chars(s: str) -> str:
    s = _MARK_RE.sub(" ", s).replace("​", "")
    return re.sub(r"[\s\-]", "", s)


def guard(legacy: str, new: str, dropped: list, multiset: bool = False, allow=()):
    """(ok, message). Ignoring whitespace and hyphens, the new body must be the legacy body with only the dropped
    furniture taken out: every difference must be a deletion from the legacy text, and the deleted characters must
    be furniture characters. For a two-column source, whose legacy text is interleaved, the same holds for the
    character multisets."""
    a, b = _chars(legacy), _chars(new)
    furn = Counter(_chars(" ".join(t for _, t in dropped)))
    if multiset:
        ca, cb = Counter(a), Counter(b)
        extra, gone = cb - ca, ca - cb
        if not extra and not (gone - furn):
            return True, f"ok (multiset, {len(b):,} chars; {sum(gone.values())} furniture chars out)"
        return False, f"multiset differs: missing {dict((gone - furn).most_common(8))}, extra {dict(extra.most_common(8))}"
    if a == b:
        return True, f"ok ({len(b):,} chars, in order)"
    # deletions only: walk the new text over the legacy text; at a mismatch, the legacy text must pick the new
    # text up again a little further on (anchored on the next 24 new characters), and what was skipped is deleted
    deleted, i, j = Counter(), 0, 0
    allow = [_chars(x) for x in allow]
    inserted, reordered = [], []
    while j < len(b):
        if i < len(a) and a[i] == b[j]:
            i += 1
            j += 1
            continue
        hit = next((x for x in allow if x and b.startswith(x, j)), None)
        if hit:                          # a listed, reviewed addition (see the TD's guard_allow)
            inserted.append(hit)
            j += len(hit)
            continue
        # a local reordering: the same characters within a short window, both texts agreeing again after it
        w = next((w for w in range(2, 401) if Counter(a[i:i + w]) == Counter(b[j:j + w])
                  and a[i + w:i + w + 12] == b[j + w:j + w + 12]), None)
        if w:
            reordered.append((a[max(0, i - 25):i + w + 10], b[max(0, j - 25):j + w + 10]))
            i += w
            j += w
            continue
        k = a.find(b[j:j + 24], i)
        if k < 0 or k - i > 2000:
            return False, f"new text not found in legacy at new char {j}: legacy …{a[max(0, i - 50):i + 60]}… new …{b[max(0, j - 50):j + 60]}…"
        deleted.update(a[i:k])
        i = k
    deleted.update(a[i:])
    if deleted - furn:
        return False, f"deleted text that is not furniture: {dict((deleted - furn).most_common(8))}"
    msg = (f"ok ({len(b):,} chars, in order; {sum(deleted.values())} furniture chars out"
           f"{'; allowed additions: ' + ', '.join(inserted) if inserted else ''}"
           f"{'; ' + str(len(reordered)) + ' local reorder(s), listed below' if reordered else ''})")
    for x, y in reordered:
        msg += f"\n      reorder: legacy …{x}… -> new …{y}…"
    return True, msg
