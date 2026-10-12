"""The five availability states, and the quarantine that makes them matter (#60).

Owner's decision, 2026-10-04: a copy of WIMI that cannot extract relations gets
a line in Settings and silence everywhere else. The states exist because "cannot
run it" turned out to be five situations wanting five different sentences, and
three of them are actionable -- so collapsing them fails #174 from the side
nobody expects (telling a student nothing can be done when something can).

The test that matters most here is the last one. Everything else checks a
branch; that one checks the property the whole delivery design rests on.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.relation_extraction import (
    Availability,
    AvailabilityState,
    get_availability,
    is_relations_build,
)
from app.relation_extraction.availability import ACTIONABLE, RUNTIME_PACKAGES

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# --------------------------------------------------------------------------
# The build flag
# --------------------------------------------------------------------------

def test_a_development_checkout_is_not_a_relations_build(monkeypatch):
    """Whatever is installed in the venv, a checkout built nothing.

    The flag answers "what did the build intend", and that is the only question
    that separates "absent by design" from "broken". A checkout with torch
    installed must not impersonate the relations artifact, or the dev case gets
    reported with the artifact's sentence.
    """
    monkeypatch.delattr(sys, '_wimi_relations_build', raising=False)
    assert is_relations_build() is False


def test_the_flag_is_what_makes_a_relations_build(monkeypatch):
    monkeypatch.setattr(sys, '_wimi_relations_build', True, raising=False)
    assert is_relations_build() is True


# --------------------------------------------------------------------------
# The five states
# --------------------------------------------------------------------------

def test_the_default_artifact_reports_absent_by_design(monkeypatch):
    """And does NOT consult whether torch happens to be importable.

    This is the state a probe cannot distinguish from a broken runtime, which
    is why `packaging/rthook_relations_build.py` exists. The assertion that it
    ignores the installed packages is the point: on a build machine that has
    torch, a probe would call this one READY and ship a feature the artifact
    cannot run.
    """
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.delattr(sys, '_wimi_relations_build', raising=False)

    result = get_availability()
    assert result.state is AvailabilityState.NOT_IN_THIS_BUILD
    assert not result.ready
    assert result.actionable, (
        "the other download exists, so #174 permits naming it -- this state "
        "must not be lumped in with the ones that have no next step")


def test_a_relations_artifact_with_no_runtime_is_a_packaging_bug(monkeypatch):
    """The state the default artifact must never be confused with.

    The student deliberately took the larger download and did not get what it
    promised. Reporting that as "not in this build" would describe a bug as a
    design decision and leave them with nothing to do about it.
    """
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_wimi_relations_build', True, raising=False)
    monkeypatch.setattr(
        'app.relation_extraction.availability._missing_runtime_packages',
        lambda: ('torch',))

    result = get_availability()
    assert result.state is AvailabilityState.RUNTIME_BROKEN
    assert result.missing == ('torch',)
    assert result.state not in ACTIONABLE, (
        "nothing in the application can fix a broken bundle, so #174 forbids "
        "offering an action for it")


def test_a_checkout_without_the_runtime_gets_its_own_state(monkeypatch):
    """Not an artifact state. The fix is a pip command, which is a third thing."""
    monkeypatch.delattr(sys, 'frozen', raising=False)
    monkeypatch.delattr(sys, '_wimi_relations_build', raising=False)
    monkeypatch.setattr(
        'app.relation_extraction.availability._missing_runtime_packages',
        lambda: ('torch', 'gliner2'))

    result = get_availability()
    assert result.state is AvailabilityState.DEV_RUNTIME_MISSING
    assert result.missing == ('torch', 'gliner2')
    assert result.actionable


def test_a_working_runtime_with_no_weights_asks_for_the_download(
        monkeypatch, tmp_path):
    monkeypatch.delattr(sys, 'frozen', raising=False)
    monkeypatch.setattr(
        'app.relation_extraction.availability._missing_runtime_packages',
        lambda: ())

    absent = tmp_path / "gliner2" / "model.safetensors"
    result = get_availability(model_path=absent)
    assert result.state is AvailabilityState.MODEL_NOT_DOWNLOADED
    assert result.model_path == absent
    assert result.actionable, "a download button belongs here (#59's D2 path)"


def test_everything_present_is_ready(monkeypatch, tmp_path):
    monkeypatch.delattr(sys, 'frozen', raising=False)
    monkeypatch.setattr(
        'app.relation_extraction.availability._missing_runtime_packages',
        lambda: ())

    present = tmp_path / "model.safetensors"
    present.write_bytes(b"weights")

    result = get_availability(model_path=present)
    assert result.state is AvailabilityState.READY
    assert result.ready
    assert result.state not in ACTIONABLE, (
        "READY needs no action; including it would make `actionable` mean "
        "nothing")


def test_the_model_is_only_checked_when_a_path_is_given(monkeypatch):
    """Availability can be asked before anything model-shaped exists.

    Settings asks this to decide whether to draw a line of text, and the model
    layer owns where weights live. If this module reached into that location it
    could not be imported before it.
    """
    monkeypatch.delattr(sys, 'frozen', raising=False)
    monkeypatch.setattr(
        'app.relation_extraction.availability._missing_runtime_packages',
        lambda: ())
    assert get_availability().state is AvailabilityState.READY


def test_a_directory_must_come_with_an_answer_about_completeness(
        monkeypatch, tmp_path):
    """The symptomless one, which is why it raises instead of guessing.

    This model is **eight files**, and ``model_spec.model_dir()`` creates the
    directory by default. So a caller passing that path would get ``READY``
    on a machine holding none of the weights -- permanently, with no error
    anywhere, and the entry form reads ``ready``. Raising names the fix.
    """
    monkeypatch.delattr(sys, 'frozen', raising=False)
    monkeypatch.setattr(
        'app.relation_extraction.availability._missing_runtime_packages',
        lambda: ())
    directory = tmp_path / "gliner2"
    directory.mkdir()

    with pytest.raises(ValueError) as exc:
        get_availability(model_path=directory)
    assert 'model_installed' in str(exc.value), (
        'the message has to name the way out, not just refuse')

    # With the answer supplied it resolves, and the path is still reported.
    assert get_availability(
        model_path=directory, model_installed=False
    ).state is AvailabilityState.MODEL_NOT_DOWNLOADED
    assert get_availability(
        model_path=directory, model_installed=True
    ).state is AvailabilityState.READY


def test_the_callers_answer_beats_the_paths_existence(monkeypatch, tmp_path):
    """``model_installed`` decides. ``model_path`` is then only reported.

    Both directions, because a flag that is read in one branch and ignored in
    the other is the shape that passes a one-sided test.
    """
    monkeypatch.delattr(sys, 'frozen', raising=False)
    monkeypatch.setattr(
        'app.relation_extraction.availability._missing_runtime_packages',
        lambda: ())
    present = tmp_path / "model.safetensors"
    present.write_bytes(b"weights")
    absent = tmp_path / "gone.safetensors"

    assert get_availability(
        model_path=present, model_installed=False
    ).state is AvailabilityState.MODEL_NOT_DOWNLOADED
    assert get_availability(
        model_path=absent, model_installed=True
    ).state is AvailabilityState.READY


def test_every_state_is_either_actionable_or_deliberately_not():
    """A state added later must be classified, not left to default.

    `actionable` drives whether the copy may direct a press (#174). A new state
    that nobody put on either side of this line would silently read as
    not-actionable, which is the failure that looks like caution.
    """
    classified = ACTIONABLE | {
        AvailabilityState.READY,
        AvailabilityState.RUNTIME_BROKEN,
    }
    unclassified = set(AvailabilityState) - classified
    assert not unclassified, (
        f"{unclassified} are neither in ACTIONABLE nor in this test's list of "
        f"deliberate exclusions. Decide which, and say why in ACTIONABLE's "
        f"comment -- #174 depends on it")


def test_peft_is_watched_because_findable_is_not_importable(monkeypatch):
    """#364: `gliner2` was findable and unimportable, and this reported READY.

    `gliner2==2.0.0` declares `peft` only under an extra, and the pin file
    asked for bare `gliner2`. `gliner2/training/trainer.py` then does an
    unconditional `from peft import PeftModel` on the INFERENCE path, so a venv
    built exactly as instructed could not construct a model.

    Measured on this tree with peft uninstalled:

        find_spec('gliner2') is not None  -> True
        get_availability().state          -> READY
        from gliner2 import GLiNER2       -> ModuleNotFoundError

    `find_spec` resolves a name and executes nothing, so it cannot see a
    missing transitive dependency. Watching `peft` closes this instance; the
    class stays open, which is why MODEL_LOAD_FAILED is the real backstop.
    """
    assert "peft" in RUNTIME_PACKAGES, (
        "peft was dropped from the watched set -- a runtime missing it has a "
        "findable gliner2 that cannot be imported, and this module would "
        "report READY (#364)")

    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_wimi_relations_build', True, raising=False)
    monkeypatch.setattr(
        'app.relation_extraction.availability._missing_runtime_packages',
        lambda: ('peft',))

    result = get_availability()
    assert result.state is AvailabilityState.RUNTIME_BROKEN, (
        "a relations artifact missing peft is a packaging bug and must say so")
    assert result.missing == ('peft',)


# --------------------------------------------------------------------------
# The quarantine. This is the one that protects the default artifact.
# --------------------------------------------------------------------------

def test_importing_the_package_does_not_import_the_runtime():
    """`import app.relation_extraction` must not pull torch in.

    The default artifact does not carry torch. If importing this package --
    which Settings does, to ask one question -- loaded the runtime, the feature
    would raise ImportError before the window appeared for almost every user,
    from a line that works perfectly on a developer's machine. That is #135's
    shape and the reason `check_relations_runtime_imports.py` exists.

    Run in a subprocess because the test session has already imported plenty;
    asking `sys.modules` in-process would answer a different question. Uses the
    RELATIONS venv if present, so the check is meaningful: a venv without torch
    passes this trivially, which would make it a tautology on CI.
    """
    relations_python = REPO_ROOT / ".venv-relations" / "bin" / "python"
    interpreter = (str(relations_python) if relations_python.exists()
                   else sys.executable)

    probe = (
        "import sys; sys.path[:0] = [%r, %r]\n"
        "import app.relation_extraction as m\n"
        "loaded = [n for n in (%r) if n in sys.modules]\n"
        "print('LOADED:' + ','.join(loaded))\n"
        % (str(REPO_ROOT), str(REPO_ROOT / "src"), RUNTIME_PACKAGES)
    )
    out = subprocess.run(
        [interpreter, "-c", probe], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, f"probe failed:\n{out.stdout}\n{out.stderr}"

    loaded = out.stdout.strip().removeprefix("LOADED:")
    assert loaded == "", (
        f"importing app.relation_extraction loaded {loaded} -- that import "
        f"reaches the default artifact's startup path, where those packages "
        f"do not exist")

    if interpreter == sys.executable:
        pytest.skip(
            "ran against the default venv, which has no runtime to load; "
            "the assertion above cannot fail here. Build .venv-relations for "
            "this to mean something.")
