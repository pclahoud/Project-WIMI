"""A build conveys its licence texts, and says where its source is (#272).

These are deliberately fast and static -- no Qt, no WIMI process, no CDP. The
whole obligation is about files existing with exact bytes, which is checkable
by reading the repository and running the stager into a temp directory.

What went wrong, and what each test defends
-------------------------------------------
WIMI became GPL-3.0 on 2026-09-30 and the bundle carried **no copyleft licence
text at all**. The only ``LICENSE`` reaching ``dist/`` was whisper.cpp's MIT,
and only because ``scripts/fetch_whisper.py`` drops it in
``vendor/whisper/<platform>/``. ``wimi.spec`` contains no reference to the root
``LICENSE`` -- measured, not inferred.

The sharper half: Settings -> About *is* WIMI's Appropriate Legal Notices under
GPL-3.0 s5(d), and it told the reader the GPL text was "in the LICENSE file
distributed with WIMI". It was not. A notices document that misstates where its
own licence lives is the one error it cannot afford, so
``test_the_about_panel_names_files_that_are_actually_staged`` ties the panel's
claims to the stager's real output rather than to a hand-maintained list.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
GATE = SCRIPTS / "check_bundled_licenses.py"
STAGER = SCRIPTS / "stage_license_files.py"
SETTINGS_HTML = REPO_ROOT / "src" / "web" / "html" / "settings.html"

# Kept in step with scripts/stage_license_files.py:LICENSE_FILES. Written out
# here rather than imported so that a change there has to be made twice on
# purpose -- these are the paths a recipient is promised, in the About panel.
STAGED_LICENCES = ["LICENSE", "licenses/LGPL-3.0.txt"]
SOURCE_NOTICE = "CORRESPONDING-SOURCE.txt"


def _run(script: Path, *args: str):
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )


@pytest.fixture(scope="module")
def staged(tmp_path_factory) -> Path:
    """Run the real stager into a temp directory, once."""
    bundle = tmp_path_factory.mktemp("bundle")
    result = _run(STAGER, str(bundle))
    assert result.returncode == 0, (
        f"the stager failed, so no build can convey its licences:\n"
        f"{result.stdout}\n{result.stderr}")
    return bundle


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------

def test_the_gate_passes_on_the_real_tree():
    result = _run(GATE)
    assert result.returncode == 0, (
        f"check_bundled_licenses.py failed on the committed tree:\n"
        f"{result.stdout}\n{result.stderr}")


def test_the_gate_catches_an_edited_licence(tmp_path):
    """Negative control. Without this the gate above proves nothing.

    A licence is conveyed verbatim; reflowing it, or "fixing" a URL in it,
    means conveying something that is not the licence. One changed character
    must fail.
    """
    target = REPO_ROOT / "licenses" / "LGPL-3.0.txt"
    original = target.read_bytes()
    backup = tmp_path / "LGPL-3.0.txt"
    backup.write_bytes(original)
    try:
        target.write_bytes(original.replace(b"LESSER", b"Lesser", 1))
        result = _run(GATE)
        assert result.returncode != 0, (
            "the gate passed on a licence text with a changed character, so it "
            "would not notice a reflowed or paraphrased licence")
        assert "content changed" in result.stdout
    finally:
        target.write_bytes(backup.read_bytes())

    # And the tree is genuinely restored -- a control that leaves damage behind
    # would make every later test in the session meaningless.
    assert _run(GATE).returncode == 0


def test_the_gate_catches_a_build_script_that_stopped_staging(tmp_path):
    """The failure mode that would hit exactly one platform, silently.

    CLAUDE.md records this shape for wimi.spec / wimi_macos.spec: "clones with
    no shared helper and a change made in one of them is a bug that only shows
    on the other platform". The build scripts are worse, being batch and bash.
    """
    target = REPO_ROOT / "build_windows.bat"
    original = target.read_text(encoding="utf-8")
    try:
        target.write_text(
            original.replace("stage_license_files.py", "nothing_at_all.py"),
            encoding="utf-8")
        result = _run(GATE)
        assert result.returncode != 0, (
            "the gate passed with the Windows build no longer staging licences")
        assert "build_windows.bat" in result.stdout
    finally:
        target.write_text(original, encoding="utf-8")
    assert _run(GATE).returncode == 0


# --------------------------------------------------------------------------
# What a build actually ends up with
# --------------------------------------------------------------------------

@pytest.mark.parametrize("rel", STAGED_LICENCES)
def test_each_licence_reaches_the_bundle_byte_for_byte(staged: Path, rel: str):
    shipped = staged / rel
    assert shipped.is_file(), f"{rel} is not in the bundle"
    assert shipped.read_bytes() == (REPO_ROOT / rel).read_bytes(), (
        f"{rel} was altered on its way into the bundle")


def test_lgpl_is_the_text_the_shipped_qt_binaries_declare():
    """The LGPL copy comes from the wheel carrying the bundled Qt binaries.

    Skips rather than fails when Qt is not installed: CI need not install it,
    and the digest pin in the gate still covers the file. When it *is*
    installed this is the stronger check -- it proves the pin matches reality
    rather than matching itself.
    """
    candidates = [
        p
        for base in (REPO_ROOT / ".venv" / "lib", REPO_ROOT / ".venv" / "Lib")
        if base.is_dir()
        for sp in list(base.glob("*/site-packages")) + [base / "site-packages"]
        if sp.is_dir()
        for pattern in ("pyqt6_qt6-*.dist-info/LICENSE",
                        "pyqt6_webengine_qt6-*.dist-info/LICENSE")
        for p in sp.glob(pattern)
    ]
    if not candidates:
        pytest.skip("PyQt6-Qt6 / PyQt6-WebEngine-Qt6 not installed")

    ours = (REPO_ROOT / "licenses" / "LGPL-3.0.txt").read_bytes()
    for wheel_license in candidates:
        assert wheel_license.read_bytes() == ours, (
            f"licenses/LGPL-3.0.txt differs from {wheel_license}, whose binaries "
            f"this build bundles")


def test_lgpl_incorporates_gpl_so_both_must_ship(staged: Path):
    """LGPL-3.0 is not standalone, which is why GPL-3.0 is not optional here.

    Its own first operative sentence incorporates GPL-3.0 by reference. If a
    future change ever ships the LGPL text alone, the result is a licence the
    recipient cannot read.
    """
    lgpl = (staged / "licenses" / "LGPL-3.0.txt").read_text(encoding="utf-8")
    flattened = " ".join(lgpl.split())
    assert (
        "incorporates the terms and conditions of version 3 of the "
        "GNU General Public License"
    ) in flattened, "this does not look like LGPL-3.0"
    assert (staged / "LICENSE").is_file(), (
        "LGPL-3.0 incorporates GPL-3.0 by reference, so a bundle carrying the "
        "LGPL text without the GPL text conveys an unreadable licence")


# --------------------------------------------------------------------------
# The source notice (GPL-3.0 s6)
# --------------------------------------------------------------------------

def test_the_source_notice_states_a_place_to_get_the_source(staged: Path):
    notice = (staged / SOURCE_NOTICE).read_text(encoding="utf-8")
    assert "https://github.com/pclahoud/Project-WIMI" in notice
    assert "no charge" in notice, (
        "s6(d) is about access at no charge; saying where without saying that "
        "is not the same offer")


def test_the_source_notice_identifies_the_build(staged: Path):
    """A notice that cannot be tied to a binary does not answer s6."""
    notice = (staged / SOURCE_NOTICE).read_text(encoding="utf-8")
    version = re.search(r"^APP_VERSION\s*=\s*['\"]([^'\"]+)", (
        REPO_ROOT / "src" / "app" / "__init__.py").read_text(encoding="utf-8"),
        re.M)
    assert version, "could not read APP_VERSION"
    assert version.group(1) in notice
    assert "Built" in notice


def test_the_notice_does_not_claim_a_private_commit_is_fetchable(staged: Path):
    """`master` is never pushed to the public mirror -- only squashed snapshots.

    So the build commit is real and useful to the maintainer, and resolves to
    nothing on GitHub. Stating it without that caveat would send a recipient
    exercising their s6 rights to a hash that does not exist.
    """
    notice = (staged / SOURCE_NOTICE).read_text(encoding="utf-8")
    if "Internal build commit:" in notice:
        assert "will not" in notice and "resolve there" in notice, (
            "the notice gives a build commit without saying it is not findable "
            "in the public repository")


# --------------------------------------------------------------------------
# The About panel is the s5(d) notices document, so it must not lie
# --------------------------------------------------------------------------

def test_the_about_panel_names_files_that_are_actually_staged(staged: Path):
    """Every licence path the panel promises is really in the bundle.

    This is the test that would have caught the original defect: the panel said
    the GPL text was "in the LICENSE file distributed with WIMI" while nothing
    put it there.
    """
    html = SETTINGS_HTML.read_text(encoding="utf-8")
    for rel in STAGED_LICENCES:
        assert rel in html, (
            f"the About panel does not mention {rel}, which the build stages")
        assert (staged / rel).is_file(), (
            f"the About panel promises {rel} but the stager does not produce it")
    assert SOURCE_NOTICE in html, (
        f"the About panel does not point at {SOURCE_NOTICE}")


def test_the_about_panel_still_carries_the_three_section_5d_notices():
    """Copyright, warranty disclaimer, source location -- s5(d)'s minimum.

    Also asserted end-to-end by
    tests/wimi_test/scenarios/test_about_panel_shows_notices.py; repeated here
    because that one needs a running WIMI and this one does not, and a notices
    regression should not wait for a scenario slot.
    """
    html = SETTINGS_HTML.read_text(encoding="utf-8")
    assert "Copyright" in html
    assert "WITHOUT ANY WARRANTY" in html
    assert "https://github.com/pclahoud/Project-WIMI" in html
