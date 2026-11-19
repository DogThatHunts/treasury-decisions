#!/usr/bin/env python3
"""Rebuild tds.json and index.html from td/<N>/meta.json.

tds.json is the single source of truth other projects read (the transcription-agent publisher's
Treasury Decision linker, the dave_champion book builds). Run after adding or editing a TD:

    python3 tools/build_index.py
"""
import html
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = ("number", "page", "pdf", "text", "sources")


def load():
    tds = []
    for f in sorted(ROOT.glob("td/*/meta.json"), key=lambda p: int(p.parent.name)):
        m = json.loads(f.read_text())
        missing = [k for k in REQUIRED if not m.get(k)]
        if missing:
            raise SystemExit(f"{f}: missing {missing}")
        if m["number"] != f.parent.name:
            raise SystemExit(f"{f}: number {m['number']!r} does not match folder {f.parent.name!r}")
        if not (f.parent / "index.html").exists():
            raise SystemExit(f"{f.parent}: no index.html")
        tds.append(m)
    return tds


def rel_text(m):
    words = {"amends": "amends", "amended_by": "amended by", "supersedes": "supersedes",
             "superseded_by": "superseded by"}
    parts = [f"{words[k]} " + ", ".join(f'<a href="td/{o}/">T.D. {o}</a>' for o in v)
             for k, v in m.get("relations", {}).items()]
    return "; ".join(parts)


def build_html(tds):
    rows = []
    for m in tds:
        n = m["number"]
        src = " · ".join(f'<a href="{html.escape(s["url"])}">{html.escape(s["label"])}</a>' for s in m["sources"])
        extra = " — ".join(x for x in (rel_text(m), html.escape(m.get("note", ""))) if x)
        rows.append(
            f'<tr><td><a href="td/{n}/"><strong>T.D. {n}</strong></a></td>'
            f'<td><a href="td/{n}/">transcript</a> · <a href="{html.escape(m["pdf"])}">scan (PDF)</a> · {src}'
            + (f'<div class="note">{extra}</div>' if extra else "") + "</td></tr>")
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Treasury Decisions</title>
<link rel="canonical" href="https://dogthathunts.github.io/treasury-decisions/">
<style>
:root{{--ink:#1c1a17;--muted:#8a8072;--rule:#e6e0d6;--bg:#faf7f2;--paper:#fffdf9;--link:#7a1f1f}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:Georgia,'Times New Roman',serif;line-height:1.6;font-size:17px}}
main{{max-width:48rem;margin:0 auto;padding:2.5rem 16px 5rem}}
h1{{font-size:1.9rem;margin:0 0 .4rem}}
p.lede{{color:#5b5348;margin:0 0 1.6rem}}
table{{width:100%;border-collapse:collapse;background:var(--paper);border:1px solid var(--rule)}}
td{{padding:.6rem .8rem;border-top:1px solid var(--rule);vertical-align:top}}
td:first-child{{white-space:nowrap}}
a{{color:var(--link)}}
.note{{font-size:.85rem;color:var(--muted);margin-top:.25rem}}
footer{{font-size:.8rem;color:var(--muted);margin-top:2rem}}
</style></head><body><main>
<h1>Treasury Decisions</h1>
<p class="lede">Transcripts and scans of {len(tds)} Treasury Decisions cited in the transcript summaries.
Each transcript is a faithful text-layer extraction of the scan beside it. Machine-readable index:
<a href="tds.json">tds.json</a>.</p>
<table>
{chr(10).join(rows)}
</table>
<footer>Built {date.today().isoformat()} by tools/build_index.py. U.S. government works; public domain.</footer>
</main></body></html>
"""


def main():
    tds = load()
    out = {"version": 1, "generated": date.today().isoformat(), "count": len(tds),
           "tds": {m["number"]: m for m in tds}}
    (ROOT / "tds.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    (ROOT / "index.html").write_text(build_html(tds))
    print(f"{len(tds)} TDs -> tds.json, index.html")


if __name__ == "__main__":
    main()
