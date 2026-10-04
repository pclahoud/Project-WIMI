#!/usr/bin/env python3
"""CI gate: the licence texts WIMI conveys are verbatim and actually shipped.

Run with no arguments. Exits non-zero and says what is wrong.

Why this exists (#272)
----------------------
WIMI became GPL-3.0 on 2026-09-30 and the mechanical obligations that follow
were not done. The bundle carried **no copyleft licence text at all** -- the
only `LICENSE` in `dist/` was whisper.cpp's MIT, there because
`scripts/fetch_whisper.py` drops it in `vendor/whisper/<platform>/`. Meanwhile
Settings -> About, which *is* WIMI's Appropriate Legal Notices under GPL-3.0
s5(d), told the reader the GPL text was "in the LICENSE file distributed with
WIMI". `wimi.spec` has no reference to the root `LICENSE`; the statement was
false.

A gate rather than a note, for the reason this repo already has five of them:
every one of those five exists because a thing that was merely written down
went wrong anyway. Three failure modes are checked, and the third is the one
that would be silent:

1. **A licence text was edited.** Reflowing, re-wrapping or "fixing" a URL in a
   licence means conveying something that is not the licence. Pinned by digest.
2. **A build script stopped staging them.** Then the obligation quietly stops
   being met on one platform only -- exactly the clone-drift CLAUDE.md records
   for `wimi.spec` / `wimi_macos.spec`.
3. **The LGPL text drifted from what the shipped Qt binaries declare.** When
   the wheels are installed this compares against them directly, so a PyQt6-Qt6
   bump that changed the licence text cannot pass unnoticed.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Digests of the verbatim texts. A licence is copied, never written from memory
# and never tidied, so any change to these bytes is a finding rather than a
# maintenance step. If one legitimately changes (a new upstream text), replace
# the digest in the same commit that replaces the file and say why.
EXPECTED = {
    Path("LICENSE"): (
        "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986",
        "GNU GPL v3 (WIMI's own licence)",
        "GNU GENERAL PUBLIC LICENSE",
    ),
    Path("licenses/LGPL-3.0.txt"): (
        "6c671e2912ec69c0832f32066c0313cee5fdc3bbcbce237822e89f3da58edd4e",
        "GNU LGPL v3 (Qt 6 and QtWebEngine)",
        "GNU LESSER GENERAL PUBLIC LICENSE",
    ),
}

# The wheels carrying the Qt binaries that actually get bundled. Both ship the
# same LGPL text; whichever is installed is a live check on the pin above.
QT_WHEEL_GLOBS = [
    "pyqt6_qt6-*.dist-info/LICENSE",
    "pyqt6_webengine_qt6-*.dist-info/LICENSE",
]

BUILD_SCRIPTS = [Path("build_windows.bat"), Path("build_macos.sh")]
STAGER = "stage_license_files.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _site_packages() -> list[Path]:
    roots: list[Path] = []
    for base in (REPO_ROOT / ".venv" / "lib", REPO_ROOT / ".venv" / "Lib"):
        if base.is_dir():
            roots.extend(p for p in base.glob("*/site-packages") if p.is_dir())
            if (base / "site-packages").is_dir():
                roots.append(base / "site-packages")
    return roots


def main() -> int:
    problems: list[str] = []

    # 1. The texts exist, are verbatim, and are the licence they claim to be.
    for rel, (digest, label, first_line) in EXPECTED.items():
        path = REPO_ROOT / rel
        if not path.is_file():
            problems.append(f"{rel}: missing. {label} must be conveyed with the build.")
            continue
        actual = _sha256(path)
        if actual != digest:
            raw = path.read_bytes()
            # The overwhelmingly likely cause on a Windows clone, and it is not
            # an edit: with no .gitattributes git converts LF to CRLF on
            # checkout, adding one byte per line to a file nobody touched.
            # Measured on 2026-10-03: LGPL-3.0.txt 7,687 bytes here, 7,849 on
            # Windows, exactly its 162 line count. Say so rather than making
            # somebody diff a licence.
            if b"\r\n" in raw and hashlib.sha256(
                    raw.replace(b"\r\n", b"\n")).hexdigest() == digest:
                problems.append(
                    f"{rel}: CRLF line endings -- this is git's end-of-line\n"
                    f"    conversion, NOT an edit. The content is byte-identical once\n"
                    f"    CRLF is normalised to LF.\n"
                    f"    Fix the working tree with:  git add --renormalize .\n"
                    f"    `.gitattributes` marks these files `-text` so a fresh checkout\n"
                    f"    is unaffected; a clone made before it existed still needs this."
                )
            else:
                problems.append(
                    f"{rel}: content changed.\n"
                    f"    expected sha256 {digest}\n"
                    f"    actual   sha256 {actual}\n"
                    f"    A licence text is copied verbatim, never edited or reflowed. If this\n"
                    f"    is a deliberate replacement, update the digest in the same commit."
                )
        head = path.read_text(encoding="utf-8").lstrip().splitlines()[0].strip()
        if first_line not in head:
            problems.append(
                f"{rel}: does not look like {label} -- first line is {head!r}"
            )

    # 2. Both build scripts stage them. One platform silently stopping is the
    #    failure this catches.
    for script in BUILD_SCRIPTS:
        path = REPO_ROOT / script
        if not path.is_file():
            problems.append(f"{script}: missing")
            continue
        if STAGER not in path.read_text(encoding="utf-8"):
            problems.append(
                f"{script}: does not call {STAGER}, so a build on that platform\n"
                f"    would ship without its licence texts or source notice (#272)."
            )

    # 3. The LGPL pin still matches what the installed Qt wheels declare.
    #    Informational when the wheels are absent -- CI need not install Qt.
    lgpl = REPO_ROOT / "licenses" / "LGPL-3.0.txt"
    checked_against = []
    if lgpl.is_file():
        for sp in _site_packages():
            for pattern in QT_WHEEL_GLOBS:
                for wheel_license in sp.glob(pattern):
                    checked_against.append(wheel_license)
                    if _sha256(wheel_license) != _sha256(lgpl):
                        problems.append(
                            f"licenses/LGPL-3.0.txt differs from {wheel_license}.\n"
                            f"    That wheel carries the Qt binaries this build bundles, so its\n"
                            f"    licence text is the one WIMI must convey. If Qt changed it,\n"
                            f"    replace the file and the digest together."
                        )

    if problems:
        print("FAIL: bundled licence check (#272)\n")
        for problem in problems:
            print(f"  - {problem}\n")
        return 1

    print("OK: licence texts are verbatim and both build scripts stage them.")
    for rel, (_, label, _) in EXPECTED.items():
        print(f"     {rel}  --  {label}")
    if checked_against:
        for wheel_license in checked_against:
            print(f"     verified against {wheel_license.parent.name}")
    else:
        print("     (Qt wheels not installed -- LGPL text checked by digest only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
