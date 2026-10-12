"""A release names one version, and `APP_VERSION` is where it comes from (#425).

`v0.1.0-beta` shipped `WIMI_mac` and `WIMI_win` **under the MIT declaration**;
WIMI relicensed to GPL-3.0 on 2026-09-30 (#195). So two artifacts could call
themselves one version while being offered under different licences, and a
recipient holding `WIMI_win_v0.1.0-beta.zip` had no way to tell which they
had. That is the inverse of what #272's conveyance work is for.

Nothing connected a tag to the version: `publish_release.py` contained no
reference to a version at all, so `--tag v0.2.0` would have published a
snapshot whose binaries report `0.1.1-beta` with no gate objecting. The build
scripts printed `v<version>` for a human to fill in, which is a third place
the same release could disagree with itself.

What this file pins:

* **one build-time reader.** `stage_license_files._app_version()` parses
  `src/app/__init__.py`, and `publish_release.py` and both build scripts go
  through it. `app.profile_archive._app_version()` is a *different mechanism*
  (it imports the constant, in-process, with Qt available) and is not in
  scope here -- the duplication worth preventing is two parsers of one file,
  which is #588's class;
* **the `--print-version` contract** the build scripts depend on: exactly
  `APP_VERSION`, on one line, with nothing round it. They capture it into a
  shell variable and put it in a filename;
* **no `<version>` placeholder** survives in either build script.

The tag-agreement logic itself is checked by calling `resolve_tag` directly
rather than by running a publish: a publish pushes to GitHub, and a test that
could do that by accident is not a test anybody should write. `publish()` is
not reached.

**The batch file cannot be executed here.** What is asserted about it is its
source: that it reads the version through the one reader and carries no
placeholder. That its `for /f` capture actually works is a Windows
measurement, requested from the machine B session rather than assumed.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
MACOS = ROOT / "build_macos.sh"
WINDOWS = ROOT / "build_windows.bat"


def _load(name: str):
    """Import a `scripts/` module by path, as the gates' own tests do.

    A plain class, not a dataclass, anywhere in these modules: `dataclass`
    reads `sys.modules[cls.__module__].__dict__` and a module loaded this way
    is never registered, which surfaces as an AttributeError at import and
    reads like a broken test file.
    """
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module          # so the module can import its siblings
    spec.loader.exec_module(module)
    return module


def _declared_version() -> str:
    """APP_VERSION read here, independently of the readers under test."""
    init = ROOT / "src" / "app" / "__init__.py"
    for line in init.read_text(encoding="utf-8").splitlines():
        if line.startswith("APP_VERSION"):
            return line.split("=", 1)[1].strip().strip("'\"")
    pytest.fail("APP_VERSION not found in src/app/__init__.py")


# ----------------------------------------------------------------- the reader

def test_print_version_emits_exactly_app_version():
    """The contract both build scripts capture into a filename."""
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / "stage_license_files.py"),
         "--print-version"],
        capture_output=True, text=True, check=True, cwd=ROOT,
    )
    assert out.stdout.strip() == _declared_version()
    assert out.stdout.count("\n") == 1, (
        f"one line, nothing else: {out.stdout!r}")


def test_bundle_dir_is_still_required_without_the_flag():
    """The control for the flag: it must not have made the argument optional."""
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / "stage_license_files.py")],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert out.returncode != 0, "staging with no bundle_dir should be refused"
    assert "bundle_dir is required" in out.stderr


# ------------------------------------------------------- tag against version

def test_a_tag_that_disagrees_with_app_version_is_refused():
    """The headline. A tag naming any other version must not publish.

    Deliberately says no version number. This docstring named `v0.2.0` on
    "a 0.1.1-beta tree" and was stale within three days of being written,
    twice over: the assertion below has always used `v99.0.0`, and
    `APP_VERSION` became `0.2.0-beta` on 2026-10-09 (#425), which would have
    made the example tag the *agreeing* one. The test reads `APP_VERSION`
    rather than hardcoding it, so only the prose could rot -- and prose that
    quotes a number the code does not use is the kind that does.
    """
    publish = _load("publish_release")
    with pytest.raises(SystemExit) as exc:
        publish.resolve_tag("v99.0.0")
    message = str(exc.value)
    assert "disagree" in message
    # The refusal has to name both values and the way out, or it is a dead
    # end rather than a refusal (#174 applies to a message as much as a
    # button).
    assert "v99.0.0" in message
    assert _declared_version() in message
    assert "APP_VERSION" in message


def test_a_tag_that_agrees_is_accepted():
    """The other direction, so the test above is not just "refuse always"."""
    publish = _load("publish_release")
    expected = f"v{_declared_version()}"
    assert publish.resolve_tag(expected) == expected


def test_no_tag_requested_stays_no_tag():
    """Publishing without `--tag` must behave exactly as it did before."""
    publish = _load("publish_release")
    assert publish.resolve_tag(None) is None


def test_the_bare_flag_derives_the_tag_from_app_version():
    publish = _load("publish_release")
    assert publish.resolve_tag(publish.DERIVE_TAG) == f"v{_declared_version()}"


def test_there_is_no_override_for_a_disagreeing_tag():
    """Stated as a test because the absence is the decision (#425).

    An override flag would let the tag and the version diverge exactly when
    somebody is in a hurry, which is when this matters most. The escape hatch
    is bumping APP_VERSION -- the thing you wanted if the tag is ahead. Same
    reasoning as the denylist having no allowlist.
    """
    source = (SCRIPTS / "publish_release.py").read_text(encoding="utf-8")
    for flag in ("--force", "--no-verify", "--allow-mismatch",
                 "--skip-version-check"):
        assert flag not in source, (
            f"{flag} would defeat the agreement check; see this test's "
            f"docstring before adding one")


# ------------------------------------------------- one reader, no placeholder

def test_publish_release_does_not_parse_app_version_itself():
    """Two parsers of one file is #588's class, and a first draft had them."""
    source = (SCRIPTS / "publish_release.py").read_text(encoding="utf-8")
    assert "stage_license_files" in source, (
        "publish_release should reach APP_VERSION through the one build-time "
        "reader")
    assert 'startswith("APP_VERSION")' not in source, (
        "publish_release is parsing src/app/__init__.py itself again -- use "
        "stage_license_files._app_version()")


@pytest.mark.parametrize("script", [MACOS, WINDOWS], ids=lambda p: p.name)
def test_a_build_script_reads_the_version_and_carries_no_placeholder(script):
    """Both scripts, so neither can be fixed while the other is forgotten."""
    source = script.read_text(encoding="utf-8")

    assert "--print-version" in source, (
        f"{script.name} should read APP_VERSION through "
        f"stage_license_files.py --print-version")

    # Comment lines are skipped, and the first run of this test is why: the
    # comment explaining that there is no `<version>` placeholder contains the
    # literal `<version>`, so it failed on its own explanation. A source
    # sweep's reader needs its own control, and this is the cheap version of
    # one -- what matters is a placeholder on a line a human is SHOWN.
    shown = [
        line for line in source.splitlines()
        if not line.strip().startswith(("#", "REM", "rem"))
    ]
    offenders = [line.strip() for line in shown if "<version>" in line]
    assert not offenders, (
        f"{script.name} still asks a human to type a version, which is the "
        f"third place a release can disagree with itself (#425): {offenders}")


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="build_macos.sh cannot run on Windows, and neither can this probe "
           "of it (#639): a bare 'bash' resolves to WSL's launcher in System32 "
           "ahead of PATH, and the POSIX PATH and 'cd C:\\...' below mean "
           "nothing to it. The .bat's half is checked by the next test.",
)
def test_the_shell_capture_falls_back_to_a_word_not_an_empty_string():
    """Executed, not grepped, because this is where the first draft was wrong.

    A command substitution yields an EMPTY string when the command is absent
    -- not the reader's "unknown" -- so `build_macos.sh` printed
    `WIMI_mac_v.zip` while its own comment claimed a word. Measured by running
    the two lines with python off PATH; the Windows half had an explicit
    default and the shell half did not.

    `WIMI_mac_v.zip` is the bad outcome precisely because it looks deliberate.
    `vunknown` cannot be mistaken for a version.

    Only reachable in a real build if python vanished mid-build (it is called
    several times earlier, and WHISPER_TAG exits on an empty read), so this
    guards the claim in the comment rather than a likely path.
    """
    lines = [
        ln for ln in MACOS.read_text(encoding="utf-8").splitlines()
        if "APP_VERSION=" in ln and not ln.strip().startswith("#")
    ]
    assert lines, "build_macos.sh no longer assigns APP_VERSION"

    script = "cd %s\n%s\necho \"[${APP_VERSION}]\"\n" % (ROOT, "\n".join(lines))
    out = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin"},          # no python anywhere
    )
    assert "[unknown]" in out.stdout, (
        f"with no python on PATH the shell capture must yield 'unknown', not "
        f"an empty string that renders WIMI_mac_v.zip: {out.stdout!r}")


def test_the_windows_capture_sets_a_default_before_reading():
    """The same property for the .bat, SOURCE-CHECKED because cmd is absent.

    Verified by execution on Windows machine B rather than here -- both arms,
    `CAPTURED=[0.1.1-beta]` with the venv on PATH and `CAPTURED=[unknown]`
    without. That figure is the APP_VERSION of the tree it was taken on
    (2026-10-09, before the bump to 0.2.0-beta) and is deliberately NOT
    renumbered: it records a measurement somebody took, and rewriting it to
    today's version would assert a run nobody has made. The capture
    construct is what this asserts, and that is version-independent.

    What this asserts is the construct that makes that true, so it cannot be
    removed quietly from a machine that cannot run it.
    """
    source = WINDOWS.read_text(encoding="utf-8")
    body = [ln for ln in source.splitlines()
            if not ln.strip().upper().startswith("REM")]
    defaulted = [ln for ln in body if 'APP_VERSION=unknown' in ln.replace('"', '')]
    assert defaulted, (
        "build_windows.bat must set APP_VERSION=unknown before the for /f "
        "capture: an unset variable renders a literal %APP_VERSION% in a "
        "filename, and an empty one renders WIMI_win_v.zip")

    capture = [i for i, ln in enumerate(body) if "--print-version" in ln]
    default_at = [i for i, ln in enumerate(body)
                  if 'APP_VERSION=unknown' in ln.replace('"', '')]
    assert default_at[0] < capture[0], (
        "the default must come BEFORE the capture, or a failed read leaves "
        "the variable unset rather than 'unknown'")


@pytest.mark.parametrize("script", [MACOS, WINDOWS], ids=lambda p: p.name)
def test_both_scripts_still_stage_the_licences(script):
    """A control on the edit above, not a new rule.

    `check_bundled_licenses.py` already fails if a build script stops calling
    the stager -- which is now also the version reader, so an edit here could
    plausibly disturb it. Asserted alongside rather than relied upon, because
    the two calls are one line apart.
    """
    source = script.read_text(encoding="utf-8")
    assert "stage_license_files.py" in source
    staging = [ln for ln in source.splitlines()
               if "stage_license_files.py" in ln and "--print-version" not in ln
               and not ln.strip().startswith(("#", "REM"))]
    assert staging, (
        f"{script.name} no longer stages the licence files -- GPL-3.0 s4 "
        f"requires them in the bundle (#272)")
