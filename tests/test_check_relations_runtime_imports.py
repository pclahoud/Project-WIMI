"""The relations-runtime import gate works, and the tree it guards is clean (#60).

Two different claims, and the first is the one that needs saying. The default
WIMI artifact has no torch, so a module-scope ``import torch`` on the startup
path is an ``ImportError`` before the window appears for every user of it. On a
clean tree the gate has nothing to catch, which means a gate that had been
broken into a no-op would report exactly what a working one reports.

So the controls are first-class here rather than a thing somebody is trusted to
have run once: ``check_relations_runtime_imports.py`` carries its fixtures in
``_FIXTURES`` and this file asserts every one of them, in both directions.
``test_the_real_tree_is_clean`` is the second claim and is worth little without
them.

The gate also has a ``--self-test`` mode that runs the same fixtures from the
command line, for anyone reaching for it outside pytest. Both paths share the
one fixture list, so they cannot disagree.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GATE_PATH = REPO_ROOT / "scripts" / "check_relations_runtime_imports.py"


def _load_gate():
    """Import the gate by path -- scripts/ is not a package."""
    spec = importlib.util.spec_from_file_location(
        "check_relations_runtime_imports", GATE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_gate()


@pytest.mark.unit
@pytest.mark.parametrize(
    "label,rel_path,source,must_reject",
    gate._FIXTURES,
    ids=[f[0] for f in gate._FIXTURES],
)
def test_the_gate_behaves_as_specified(
    label: str, rel_path: str, source: str, must_reject: bool
) -> None:
    """Every fixture, in the direction it claims.

    The rejections are the negative controls -- a gate that cannot fail is not
    a gate. The acceptances matter just as much: a gate that rejected a
    deferred import, or rejected the quarantine package's own top-level
    ``import torch``, would forbid the pattern the feature is required to use
    and would be "fixed" by deleting it.
    """
    problems = gate.check_file(REPO_ROOT / rel_path, source, rel_path)
    assert bool(problems) is must_reject, (
        f"{label}: expected {'rejection' if must_reject else 'acceptance'}, "
        f"got {problems or 'no problems'}"
    )


@pytest.mark.unit
def test_both_rules_are_actually_exercised_by_the_fixtures() -> None:
    """The fixture list covers rule 1 and rule 2, not just one of them.

    Without this, dropping every rule-2 fixture would leave a green
    parametrised test and an unguarded half of the invariant. The two rules
    guard different things -- rule 1 the runtime itself, rule 2 the package
    that is allowed to import it -- and either alone leaves a way through.
    """
    labels = [f[0] for f in gate._FIXTURES]
    assert any(label.startswith("rule 1:") for label in labels)
    assert any(label.startswith("rule 2:") for label in labels)
    assert any(label.startswith("accepted:") for label in labels)


@pytest.mark.unit
def test_the_quarantine_is_the_only_exemption() -> None:
    """No allowlist and no docstring sentinel, deliberately.

    ``check_css_empty_selector.py`` makes the same choice and says "No
    allowlist by design". One exemption that is a *place* can be reasoned
    about; a list of exempted modules grows and is never pruned.
    """
    source = GATE_PATH.read_text(encoding="utf-8")
    assert "ALLOWLIST" not in source.upper().replace("NO ALLOWLIST", "")
    assert gate.RELATIONS_PACKAGE


@pytest.mark.unit
def test_torch_is_covered_along_with_what_arrives_with_it() -> None:
    """The three named packages, and the dependencies that come only with them.

    ``transformers`` pulls ``tokenizers``, ``safetensors`` and
    ``huggingface_hub``; none of them is in the default artifact either, so an
    import of any one breaks it exactly as ``torch`` would. Listing them closes
    the side door at no cost.
    """
    for package in ("torch", "transformers", "gliner2"):
        assert package in gate.RELATIONS_RUNTIME_PACKAGES
    for dependency in ("tokenizers", "safetensors", "huggingface_hub"):
        assert dependency in gate.RELATIONS_RUNTIME_PACKAGES


@pytest.mark.unit
def test_the_real_tree_is_clean() -> None:
    """src/ and run_wimi.py import none of it at module scope.

    Worth little on its own -- see this module's docstring -- which is why the
    fixtures above come first.
    """
    problems, scanned, _quarantine_exists = gate.run_repo_check()
    assert problems == []
    # A scan that found nothing because it looked at nothing would also pass
    # the line above. src/ holds well over a hundred modules.
    assert scanned > 100, f"only {scanned} file(s) scanned; the scan roots look wrong"


@pytest.mark.unit
def test_the_command_line_self_test_agrees_with_these_tests() -> None:
    """``--self-test`` exits 0, so the two entry points cannot drift."""
    assert gate.run_self_test() == 0
