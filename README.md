# WIMI — Why I Missed It

**A metacognitive exam preparation tool.** WIMI helps students analyze *why* they miss questions — not just track that they missed them. Log every wrong answer with a structured reflection, tag it against your exam's real content outline, and let the analytics show you where your preparation is actually weak.

Built for high-stakes standardized exams (USMLE, NBME shelf exams, MCAT, SAT, GRE, LSAT, CPA and more), but works for any exam you can describe as a subject hierarchy.

![Entry browser](assets/screenshots/entry-browser.png)

![Analytics dashboard](assets/screenshots/analytics-dashboard.png)

## Why

Reviewing a practice test usually stops at "I got 12 wrong." WIMI pushes one step further: for each miss, you record what you picked, what was right, why you got it wrong, and what the mistake reveals (knowledge gap, misread stem, time pressure, second-guessing). Over hundreds of entries, patterns emerge that a raw score never shows — and the dashboard weighs them against how heavily each topic actually counts on your exam.

## Features

- **Structured mistake entry** — session-based workflow with rich text (tables, math via KaTeX), media attachments, fuzzy subject search, and auto-save
- **Multi-dimensional exam models** — categorize a single question along several axes at once (e.g. organ system × physician task × discipline for USMLE-style exams)
- **Real content-outline weighting** — subject hierarchies are true DAGs with per-edge weights, a Hamilton largest-remainder question allocator, feasibility checking, and support for computer-adaptive (variable-length) exams
- **Analytics dashboard** — D3.js sunburst, cross-dimension heatmaps, activity trends, streak tracking, weakness-vs-weight quadrant analysis, and pattern detection with study recommendations
- **10 built-in exam templates** — USMLE Step 1/2 CK, NBME shelf exams, MCAT, SAT, ACT, GRE, LSAT, CPA — fully customizable after selection
- **Assignable notes** — multiple notes per entry, each linkable to specific subjects, aggregated in per-subject deep-dive views
- **Session timer** — multi-round timing with break tracking, plus import of externally-timed sessions
- **Question bank beside the form** — an embedded browser pane keeps your question bank open next to the entry form, with logins that persist between sessions
- **Speech-to-text** — dictate an answer instead of typing it; transcription runs locally through [whisper.cpp](https://github.com/ggerganov/whisper.cpp), and the speech model downloads on first use
- **Related topics** — link subjects to each other with a written reason, shown on each subject's deep-dive page
- **Import, export, archive and restore** — bring in a whole exam outline from a JSON file behind a preview, export it back out, and restore subjects or whole dimensions you archived
- **Profiles** — several study profiles on one machine, each portable as a single `.wimi` file
- **Folder sync** — keep a profile in step across your own computers through a folder in whatever cloud client you already run (tested with Box Drive); WIMI writes files into that folder and never talks to a cloud service itself
- **Plugin system** — backend (Python) and frontend (JS/CSS) plugins with a permission-scoped API
- **Local-first** — everything lives in SQLite on your machine; no account, no server, no telemetry

## Getting started

Requires **Python 3.11+** on Windows or macOS.

```bash
git clone https://github.com/pclahoud/Project-WIMI.git
cd Project-WIMI
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS: source .venv/bin/activate
pip install -r requirements-prod.txt
python run_wimi.py
```

Use a virtual environment: the Qt and Chromium versions are pinned exactly, and a mismatch changes how pages render. Development mode gives you F5 reload and F12 dev tools. On first launch WIMI creates a local demo user and walks you through the exam setup wizard.

Speech-to-text needs the whisper.cpp binary, which is not committed. When running from source, fetch it once with `python scripts/fetch_whisper.py`; the build scripts below do this for you.

### Building a standalone executable

```bash
# Windows → dist/WIMI/WIMI.exe
build_windows.bat

# macOS (Apple Silicon) → dist/WIMI/WIMI.app
chmod +x build_macos.sh && ./build_macos.sh
```

Both scripts first check that the active environment matches `requirements-prod.txt` and refuse to build on a mismatch.

## Architecture

Three layers, all local:

1. **Backend** — Python + SQLite (WAL mode), composed from domain mixins (`src/database/`), with a versioned migration runner
2. **Bridge** — PyQt6 WebChannel exposing `@pyqtSlot` methods to the frontend (`src/app/`)
3. **Frontend** — HTML/CSS/JS rendered in QWebEngineView, with D3.js visualizations and Fuse.js search (`src/web/`)

The UI test stack (`wimi_test/`) drives the real app over the Chrome DevTools Protocol.

## Testing

```bash
pip install -r requirements-test.txt

# Fast suite (skips end-to-end UI scenarios)
pytest -m "not regression and not slow"

# Everything, including the UI regression scenarios
pytest
```

The UI regression scenarios start the real app, open its window and drive it, so they need a desktop session and take several minutes. Coverage is enforced at 80% on the database layer; add `--no-cov` when running a single file, or the partial run fails that gate.

## Status

Production-ready for personal use, under active development.

## About this repository

This is a **read-only snapshot**. Development happens on a private tracker, and
each release is published here as a single squashed commit rather than as
upstream history — so there are no branches to follow, and the commit log will
not match the work.

Issues and pull requests are not monitored. The code is
[GPL-3.0](LICENSE)-licensed: fork it, use it, take pieces of it — and if you
distribute what you build from it, that has to be GPL-3.0 too, with source.
If you have found a bug and want to say so, a fork with a note in its README
is the most reliable way to be seen.

## License

Copyright © 2026 pclahoud.

WIMI is free software: you can redistribute it and/or modify it under the
terms of the [GNU General Public License version 3](LICENSE) as published by
the Free Software Foundation.

WIMI is distributed in the hope that it will be useful, but **without any
warranty**; without even the implied warranty of merchantability or fitness
for a particular purpose. See the [GNU General Public License](LICENSE) for
more details.

The licence is GPL-3.0 rather than something permissive because WIMI is built
on **PyQt6**, whose bindings are `GPL-3.0-only`, and ships **TinyMCE** under
GPL v2 or later. A binary combining those cannot be distributed under a
permissive licence. WIMI bundles other components under their own terms —
Qt and QtWebEngine (LGPL v3), Chromium, Pillow, D3, Fuse.js, KaTeX,
whisper.cpp and the Microsoft C++ runtime; the full list, with versions and
licences, is in the app under **Settings → About**.
