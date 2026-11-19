# Treasury Decisions

The one home for the Treasury Decisions (T.D.s) cited in the transcript summaries: a transcript page and the
scan for each, served at **https://dogthathunts.github.io/treasury-decisions/**.

- `td/<N>/index.html` is the transcript page, so its URL is `…/td/<N>/`. It is a faithful text-layer extraction
  of the scan; spelling and OCR quirks are kept.
- `td/<N>/TD-<N>.pdf` is the scan. T.D. 2402 is printed in the same scan as T.D. 2401, so its page links
  `td/2401/TD-2401.pdf`.
- `td/<N>/td_<N>.md` is the same text as Markdown.
- `td/<N>/meta.json` holds the TD's details: the external sources, a note, its amend and supersede relations,
  and the Queue rows that cite it.
- `tds.json` (generated) is the **source of truth** for other projects. The transcription-agent publisher
  reads it to link "T.D. N". The dave_champion book builds and `TREASURY_DECISIONS.md` read it too.

## Adding a TD

1. Find the scan. HathiTrust blocks scripts, so use a real browser. Check that the page really is T.D. N,
   not a neighbouring decision or a later correction notice.
2. Create `td/<N>/` with `TD-<N>.pdf`, `index.html`, `td_<N>.md` and `meta.json`. Copy an existing folder
   as the template.
3. Run `python3 tools/build_index.py`, then commit and push. That gives one Pages build.

Never rename or move a `td/<N>/` folder, because published posts link to it.

## History

These files were imported on 2026-11-19 from `DogThatHunts/dave_champion` (`citations/treasury_decisions/`).
The old pages there now forward here.
