"""The build gate must read the loaded Qt, and must compare what it reads (#188).

`check_runtime_qt`'s own docstring states the intent: *"Ask the loaded
libraries, not the package metadata. A wheel version is a claim about what was
installed. These are the versions that will be copied into the frozen bundle."*

It then printed `QT_VERSION_STR`, which is **not** the loaded library's version
— it is a constant compiled into the PyQt6 bindings, recording the Qt they were
built against. On this machine, one interpreter, one process:

    qVersion()      (loaded runtime)        6.9.2   <- what ships
    QT_VERSION_STR  (bindings constant)     6.9.0   <- what was printed

Two patch versions apart on a **correctly pinned** machine, under a line
labelled "Qt runtime", while the gate said *"Safe to build."*

There was a second half to it. Even the wrong value was only ever *printed* —
`check_runtime_qt` compared Chromium alone, so core Qt was checked by nobody.
Reading the wrong source and not comparing it are independent defects and both
are guarded here.

Why this gate specifically: #135 is the recorded case of a drifted machine
shipping Chromium 134 while every test ran 130, and CLAUDE.md describes this
script as the thing that catches it, because *"PyQt6-Qt6 and
PyQt6-WebEngine-Qt6 carry the binaries that actually get bundled"*. For
Chromium that was true. For core Qt it was not.

The behavioural tests below drive the real function with a falsified pin,
rather than asserting on source text, because "does it compare?" is a question
about behaviour. The one source-level test covers the part no behavioural test
can see: *which API* the value came from, when both APIs return a plausible
version string.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / 'scripts' / 'check_build_env.py'


@pytest.fixture(scope='module')
def gate():
    """Load the gate script by path; `scripts/` is not an importable package."""
    spec = importlib.util.spec_from_file_location('check_build_env', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def script_text() -> str:
    return SCRIPT.read_text(encoding='utf-8')


# ----------------------------------------------- which API the value comes from

def test_the_runtime_line_asks_the_loaded_library_not_the_bindings(script_text):
    """`qVersion()` is the loaded Qt. `QT_VERSION_STR` is a bindings constant.

    No behavioural test can tell these apart — both return a well-formed
    version string, and on a machine where they happen to agree the wrong one
    looks right. Only the source says which was asked.
    """
    assert 'qVersion' in script_text, (
        "check_build_env.py never calls qVersion(). It is the only API that "
        "reports the Qt actually loaded; QT_VERSION_STR is compiled into the "
        "PyQt6 bindings and reports what they were built against (#188)."
    )

    runtime_lines = [
        ln for ln in script_text.splitlines()
        if 'Qt runtime' in ln and 'print' in ln
    ]
    assert runtime_lines, 'no line prints a "Qt runtime" value'
    for line in runtime_lines:
        assert 'QT_VERSION_STR' not in line, (
            f"the line labelled 'Qt runtime' prints QT_VERSION_STR: {line.strip()!r}. "
            f"That is the bindings' compile-time constant, not the runtime — the "
            f"exact substitution this function's docstring warns against (#188)."
        )


# ------------------------------------------------------- does it compare at all

def _qt_problems(gate, monkeypatch, pins: dict[str, str]) -> list[str]:
    """Run the real check with `pins` substituted, return Qt-related problems."""
    monkeypatch.setattr(gate, 'parse_pins', lambda _path: pins)
    problems: list[str] = []
    gate.check_runtime_qt(problems)
    # Chromium is compared separately and was never the defect; ignore it so a
    # drifted Chromium on the running machine cannot mask or fake a result.
    return [p for p in problems if not p.startswith('Chromium is')]


def test_a_drifted_qt_runtime_is_a_problem_not_a_printout(gate, monkeypatch):
    """Before #188 this returned nothing: core Qt was displayed and never checked."""
    problems = _qt_problems(gate, monkeypatch, {'pyqt6-qt6': '0.0.0'})
    assert any('Qt runtime is' in p for p in problems), (
        f"a Qt runtime that disagrees with its pin produced no problem: "
        f"{problems}. Reading the right value is only half the job — before "
        f"#188 the value was printed and nothing compared it (#188)."
    )


def test_qtwebengine_runtime_is_compared_too(gate, monkeypatch):
    """Same defect, same wheel class — `pyqt6-webengine-qt6` also ships binaries."""
    problems = _qt_problems(gate, monkeypatch, {'pyqt6-webengine-qt6': '0.0.0'})
    assert any('QtWebEngine runtime is' in p for p in problems), (
        f"a QtWebEngine runtime that disagrees with its pin produced no "
        f"problem: {problems}."
    )


def test_a_matching_runtime_raises_no_problem(gate, monkeypatch):
    """The negative control.

    Without this, a check that appended a problem unconditionally would pass
    both tests above and block every build on a correct machine.
    """
    from PyQt6.QtCore import qVersion
    from PyQt6.QtWebEngineCore import qWebEngineVersion

    problems = _qt_problems(gate, monkeypatch, {
        'pyqt6-qt6': qVersion(),
        'pyqt6-webengine-qt6': qWebEngineVersion(),
    })
    assert problems == [], (
        f"a correctly pinned environment was reported as a problem: {problems}. "
        f"A gate that fails on a good machine gets switched off."
    )


def test_an_absent_pin_is_not_invented(gate, monkeypatch):
    """`requirements-prod.txt` is the authority; silence there means no check.

    Guards against the comparison inventing an expectation when the pin is
    missing, which would make the gate fail for a reason the file never stated.
    """
    assert _qt_problems(gate, monkeypatch, {}) == []
