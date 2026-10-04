# Licence texts conveyed with a WIMI build

These are **verbatim** licence texts. They are copied from a canonical source,
never written from memory, never paraphrased, and never reflowed — a licence
that has been "tidied" is no longer the licence it claims to be.

`scripts/stage_license_files.py` copies them into `dist/<name>/` at build time,
and `scripts/check_bundled_licenses.py` is the CI gate that stops them drifting.

| file | what it is | where it came from |
|---|---|---|
| `../LICENSE` | GNU GPL v3 — **WIMI's own licence** | the FSF text, added by `58e5964` (#195 (d)) |
| `LGPL-3.0.txt` | GNU LGPL v3 — Qt 6 and QtWebEngine | the `PyQt6-Qt6` wheel's own `LICENSE` |

## Why the LGPL text is taken from the wheel rather than fetched

`PyQt6-Qt6` and `PyQt6-WebEngine-Qt6` carry the Qt binaries that actually get
bundled (CLAUDE.md records this under the build gate: they were unpinned until a
drifted Windows machine shipped Chromium 134 while every test ran 130). Both
wheels ship the **same** LGPL-3.0 text — byte-identical, sha256
`6c671e29…58edd4e` — so taking it from there means the text WIMI conveys is the
one the shipped binaries themselves declare, and the gate can prove that rather
than trusting a download.

## GPL-3.0 is not optional even though WIMI is not LGPL

LGPL-3.0 is **not a standalone licence**. Its own first operative sentence:

> This version of the GNU Lesser General Public License incorporates the terms
> and conditions of version 3 of the GNU General Public License, supplemented by
> the additional permissions listed below.

So a build conveying LGPL components must convey the GPL-3.0 text too. Here that
costs nothing extra — WIMI is GPL-3.0, so the root `LICENSE` serves both roles —
but it is the reason `LGPL-3.0.txt` must never be shipped *alone*, and the gate
checks for both.

## What is deliberately not here

- **whisper.cpp's MIT licence.** It already rides along in
  `vendor/whisper/<platform>/LICENSE`, put there by `scripts/fetch_whisper.py`.
  Copying it here would create a second copy to drift.
- **TinyMCE, KaTeX, D3, Fuse.js, Pillow and the rest.** Their licences are named
  in Settings → About, which is WIMI's Appropriate Legal Notices under GPL-3.0
  §5(d) (#195, owner's decision (a)); TinyMCE additionally ships its own
  `notices.txt` beside its licence. Only the two texts a *copyleft* obligation
  requires in full are conveyed as files.
