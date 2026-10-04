"""Tests for ``scripts/check_build_env.py`` — the #135 build environment guard.

These test the *pure* parts: pin parsing and name normalisation, plus the
invariant that the real ``requirements-prod.txt`` still declares the pins the
guard exists to protect. The runtime Qt checks are deliberately not tested —
they read the loaded library, so a test could only assert that this machine is
what it is, which is what the guard already reports.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PROJECT_ROOT / "scripts" / "check_build_env.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_build_env", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_build_env"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def guard():
    return _load()


@pytest.mark.unit
def test_script_exists():
    assert SCRIPT.exists(), "the build scripts call this; it must be present"


@pytest.mark.unit
def test_normalise_follows_pep503(guard):
    assert guard._normalise("PyQt6_sip") == "pyqt6-sip"
    assert guard._normalise("PyQt6-WebEngine-Qt6") == "pyqt6-webengine-qt6"
    assert guard._normalise("python.json.logger") == "python-json-logger"


@pytest.mark.unit
def test_parses_exact_pins_only(guard, tmp_path):
    """`>=` is not a claim about an exact version, so there is nothing to check."""
    req = tmp_path / "r.txt"
    req.write_text(
        "# a comment\n"
        "\n"
        "PyQt6==6.9.1\n"
        "python-json-logger>=2.0.0\n"
        "Pillow==11.3.0  # trailing comment\n"
        "pyinstaller>6.0\n",
        encoding="utf-8",
    )
    pins = guard.parse_pins(req)
    assert pins == {"pyqt6": "6.9.1", "pillow": "11.3.0"}


@pytest.mark.unit
def test_real_requirements_pin_the_qt_binaries(guard):
    """The hole #135 went through: bindings pinned, binaries floating.

    ``PyQt6`` and ``PyQt6-WebEngine`` are thin wrappers. ``PyQt6-Qt6`` and
    ``PyQt6-WebEngine-Qt6`` carry the Qt and Chromium binaries that actually
    get bundled, and they are transitive dependencies — pinning only the
    bindings lets the shipped Chromium float inside the binding's range.
    Do not remove these pins.
    """
    pins = guard.parse_pins(PROJECT_ROOT / "requirements-prod.txt")
    for required in (
        "pyqt6",
        "pyqt6-webengine",
        "pyqt6-qt6",
        "pyqt6-webengine-qt6",
    ):
        assert required in pins, (
            f"{required} is not pinned in requirements-prod.txt. See #135: the "
            f"Qt binary wheels decide which Chromium ships, and an unpinned one "
            f"shipped Chromium 134 while every test ran 130."
        )


@pytest.mark.unit
def test_expected_chromium_is_declared(guard):
    """The one fact no package pin states, so it has to be asserted somewhere."""
    assert isinstance(guard.EXPECTED_CHROMIUM_MAJOR, int)
    assert guard.EXPECTED_CHROMIUM_MAJOR > 0


@pytest.mark.unit
def test_python_range_is_coherent(guard):
    assert guard.MIN_PYTHON <= guard.MAX_TESTED_PYTHON


@pytest.mark.unit
@pytest.mark.parametrize("script", ["build_windows.bat", "build_macos.sh"])
def test_build_scripts_call_the_guard(script):
    """A guard the build does not run is the comment it replaced."""
    text = (PROJECT_ROOT / script).read_text(encoding="utf-8")
    assert "check_build_env.py" in text, (
        f"{script} does not invoke the build environment guard"
    )
    assert "--warn-only" not in text, (
        f"{script} runs the guard with --warn-only, which cannot stop a build"
    )


# --------------------------------------------------------- the relations variant


@pytest.mark.unit
def test_every_prod_pin_compares_exactly_as_before(guard):
    """``_satisfies`` must not have loosened the prod check (#60).

    It was added so one portable torch pin works on all three platforms: the
    CPU-index wheel is ``2.14.1+cpu`` on Linux and Windows, while macOS has a
    single torch build reporting a bare ``2.14.1``, so ``==2.14.1+cpu`` is
    unsatisfiable there. PEP 440 says a specifier with no local version label
    ignores the candidate's label.

    The risk in implementing that is weakening the #135 guard by accident. No
    pin in ``requirements-prod.txt`` carries a local label, so for all of them
    the new comparison must agree with plain string equality -- measured here
    against what is actually installed rather than asserted in a comment.
    """
    pins = guard.parse_pins(guard.REQUIREMENTS)
    assert pins, "no pins parsed; this test would be vacuous"
    for name, expected in sorted(pins.items()):
        actual = guard.installed_version(name)
        if actual is None:
            continue
        assert guard._satisfies(actual, expected) is (actual == expected), (
            f"{name}: _satisfies disagrees with equality "
            f"(installed {actual}, pinned {expected})"
        )


@pytest.mark.unit
@pytest.mark.parametrize("actual,expected,accept", [
    # The two cases the rule exists for.
    ("2.14.1+cpu", "2.14.1", True),      # Linux/Windows CPU wheel
    ("2.14.1", "2.14.1", True),          # macOS, no label at all
    # A pin that names a label is still compared in full, so the rule cannot be
    # used to wave through a different build.
    ("2.14.1+cu124", "2.14.1+cpu", False),
    ("2.14.1+cpu", "2.14.1+cpu", True),
    # The public version still has to match.
    ("2.14.2+cpu", "2.14.1", False),
    ("2.14.1", "2.14.2", False),
])
def test_local_version_labels_follow_pep_440(guard, actual, expected, accept):
    assert guard._satisfies(actual, expected) is accept


@pytest.mark.unit
def test_a_cuda_wheel_satisfies_the_version_pin_which_is_why_cpu_is_checked_separately(guard):
    """This looks like a hole and is the reason the CPU assertion exists.

    ``torch==2.14.1`` is satisfied by ``2.14.1+cu124`` -- correctly, per PEP
    440. So the pin states the *version* and says nothing about the *build*,
    and a maintainer who installed from the default index would pass this half
    of the gate while shipping gigabytes of CUDA libraries that can never
    execute (#135's shape; the #60 spike measured 5.6 GB with 3.2 GB of CUDA).

    ``check_relations_runtime`` is the other half: ``torch.version.cuda`` must
    be ``None`` and no ``nvidia-*``/``triton`` distribution may be installed.
    Anyone tempted to "tighten" the pin to ``==2.14.1+cpu`` instead should note
    that doing so breaks macOS, where no such label exists.
    """
    assert guard._satisfies("2.14.1+cu124", "2.14.1") is True
    assert guard.GPU_DIST_PREFIXES, "the compensating check must exist"
    assert guard.RELATIONS_REQUIREMENTS.name == "requirements-relations.txt"


@pytest.mark.unit
def test_the_relations_requirements_file_exists_and_is_separate(guard):
    """Its separateness is the decision, not a filing preference (#60).

    In ``requirements-prod.txt`` these pins would make this guard demand torch
    for the DEFAULT build on every machine, and both build scripts refuse to
    build on a mismatch.
    """
    assert guard.RELATIONS_REQUIREMENTS.is_file()
    relations = guard.parse_pins(guard.RELATIONS_REQUIREMENTS)
    prod = guard.parse_pins(guard.REQUIREMENTS)
    assert "torch" in relations
    assert not set(relations) & set(prod), (
        "a pin appears in both files; they would drift against each other"
    )


@pytest.mark.unit
@pytest.mark.parametrize("script", ["build_windows.bat", "build_macos.sh"])
def test_build_scripts_export_the_relations_flag_before_running_the_guard(script):
    """Order matters: the guard reads the variable to pick its mode (#60).

    Both scripts set ``WIMI_BUILD_RELATIONS`` and then call the guard with no
    extra argument. Setting it afterwards would silently check the default
    artifact while building the relations one.

    Both patterns match the real statements, not any mention of the names. The
    first draft of this test compared ``text.index("check_build_env.py")``
    against ``text.index("WIMI_BUILD_RELATIONS")`` and failed on
    ``build_macos.sh`` -- because the earliest occurrence of the guard's name
    is a *comment* saying the variable is exported before it runs. A
    text-level ordering test that can match prose reports an order that is not
    the execution order.
    """
    import re

    text = (PROJECT_ROOT / script).read_text(encoding="utf-8")

    # `export WIMI_BUILD_RELATIONS=` (bash) or `set "WIMI_BUILD_RELATIONS=` (batch)
    assignment = re.search(
        r'^\s*(?:export\s+|set\s+")WIMI_BUILD_RELATIONS=', text, re.MULTILINE
    )
    # The invocation, not a reference to it.
    invocation = re.search(
        r'python\s+scripts[/\\]check_build_env\.py', text
    )

    assert assignment, f"{script} never assigns WIMI_BUILD_RELATIONS"
    assert invocation, f"{script} never invokes check_build_env.py"
    assert assignment.start() < invocation.start(), (
        f"{script} runs check_build_env.py before setting WIMI_BUILD_RELATIONS, "
        f"so a relations build would be checked as a default one"
    )
