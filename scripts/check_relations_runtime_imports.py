#!/usr/bin/env python3
"""CI gate: nothing WIMI starts up through may import the relations runtime.

Run with no arguments. Exits non-zero and says what is wrong.

Why this exists (#60)
---------------------
WIMI ships **two artifacts per platform** (owner's decision, 2026-10-04): the
default one, and a larger one carrying the relation-extraction runtime --
``torch``, ``transformers``, ``gliner2``. The default artifact does not have
torch and never will; that is the whole point of splitting the download, since
bundling for everyone roughly doubles the installer for a feature many users
will not enable.

The cost of that choice is a build-level invariant:

    **A bare module-scope ``import torch`` anywhere WIMI starts up through
    breaks the DEFAULT artifact, at startup, for every user.**

Not a degraded feature -- an ``ImportError`` before the window appears, on the
artifact almost everyone downloads, from a line that looks perfectly ordinary
and that works on the developer's machine and in every test, because the
development venv for the relations build has torch installed. It is #135's
shape: the thing that ships is not the thing that was exercised. Nothing in
the code says the import is forbidden, so this script says it.

The two rules
-------------
Reachability is deliberately **not** computed by walking the import graph from
the entry point, and that is worth stating because it is the obvious design and
it does not work here. ``src/app/main.py`` defers almost every import into
``main()`` -- ``from app.main_window import run_application`` and friends are
function-local on purpose -- so a graph walk that followed module-scope edges
only would reach a handful of modules and pass while the violation sat in
``main_window.py``. Following function-level edges instead makes the walk reach
*everything*, including the feature's own runtime wrapper, which must be
allowed to import torch. Either way the graph answers the wrong question.

So the invariant is enforced as a **pair of rules about where imports may
appear**, which needs no graph and has no false negatives:

1. **No module under ``src/`` may import a relations-runtime package at module
   scope** -- except modules inside the quarantine package (below).
2. **No module outside the quarantine may import the quarantine package at
   module scope.** Reaching it must be a function-level import, which is what
   makes it run only after an availability check rather than at startup.

Rule 1 alone would let a quarantined module be dragged in at import time by a
shared one. Rule 2 alone would let any module import torch directly. Together
they say: at startup, nothing imports the relations runtime.

This is the same shape as ``check_instrumented_slots.py`` -- a pairing
invariant checked by parsing, not a behaviour checked by running.

The quarantine
--------------
``RELATIONS_PACKAGE`` names the one package that may import the runtime at its
own top level. It does not exist yet: #60's extraction feature is not built,
and this gate ships with the packaging so the contract is in place on the day
it starts. The path is a constant here precisely so the feature can move it in
one line; what must not change is that there is exactly one such place.

Module scope, and why ``try``/``if`` do not excuse it
-----------------------------------------------------
Only module-scope imports are violations; a function-level ``import torch`` is
the required pattern and is ignored. But a module-scope import is still a
violation when it is wrapped in ``try: ... except ImportError:`` or sat behind
an ``if``, and that is not pedantry -- two separate reasons:

* **PyInstaller's analysis is static and does not care about scope or
  guards.** A module-scope ``import torch`` in a shared module makes
  ``Analysis`` try to collect torch into the **default** artifact as well, on
  any build machine that has it installed. The ``excludes`` list in both spec
  files blocks that, so the bundle stays small -- and then the guarded import
  takes its ``except ImportError`` branch at runtime and the feature is
  silently absent from the artifact that was supposed to have it.
* **A ``try``-guarded import still costs the startup.** torch's import is
  seconds and ~1.25 GB of RSS. Paying that before the window appears, on every
  launch, for a feature that may never be used, is not what "degrade cleanly"
  means.

There is no allowlist and no exemption sentinel, deliberately -- the same
choice ``check_css_empty_selector.py`` makes. The quarantine package is the
exemption, and one is enough.

Usage
-----
::

    python scripts/check_relations_runtime_imports.py

Exit codes:

* ``0`` -- the default artifact's startup path is free of the runtime.
* ``1`` -- at least one violation; each is printed with ``file:line``.
* ``2`` -- the script could not do its job (a file it must parse is broken).

``--self-test`` runs the gate against synthetic fixtures instead of the repo:
one that must be rejected under each rule, and one clean module that must be
accepted. A guard with nothing to catch passes whether or not it works, and on
a clean tree this one has nothing to catch -- so the negative control is part
of the script rather than a thing somebody is trusted to have done once.
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# What gets scanned: the application source, plus the dev launcher. `scripts/`
# is deliberately NOT here -- `check_build_env.py` imports torch on purpose to
# verify it is the CPU build, and a build-time script is not in any artifact.
SCAN_ROOTS = [Path("src"), Path("run_wimi.py")]

# The top-level distributions the relations artifact adds and the default one
# does not have. Matched on the first dotted component, so `torch.nn` and
# `transformers.pipelines` are covered.
#
# `tokenizers`, `safetensors`, `huggingface_hub`, `accelerate` and
# `sentencepiece` arrive only as dependencies of the three real ones, so an
# import of any of them is equally absent from the default artifact. Listing
# them costs nothing and closes the side door.
RELATIONS_RUNTIME_PACKAGES = frozenset({
    "torch",
    "torchvision",
    "torchaudio",
    "transformers",
    "gliner2",
    "gliner",
    "tokenizers",
    "safetensors",
    "huggingface_hub",
    "accelerate",
    "sentencepiece",
})

# The ONE package permitted to import the runtime at its own module scope, and
# which therefore nothing may import at module scope (rule 2).
#
# It does not exist yet -- #60 is not built. Written as the import path the
# application would use (`src/` is on sys.path; see src/app/main.py:56), with
# the directory derived from it rather than stated twice.
RELATIONS_PACKAGE = "app.relation_extraction"


def _relations_package_dir() -> Path:
    return REPO_ROOT / "src" / Path(*RELATIONS_PACKAGE.split("."))


def _python_files() -> list[Path]:
    """Every file the gate parses, as absolute paths."""
    files: list[Path] = []
    for rel in SCAN_ROOTS:
        target = REPO_ROOT / rel
        if target.is_file():
            files.append(target)
        elif target.is_dir():
            files.extend(sorted(target.rglob("*.py")))
    return files


def _module_scope_imports(tree: ast.Module) -> list[tuple[str, int]]:
    """Return ``(top_level_package, lineno)`` for every module-scope import.

    "Module scope" means *executed when the module is imported*, so it includes
    imports nested in ``try``, ``if``, ``with`` and ``for`` at the top level. It
    excludes anything inside a ``def``, ``async def`` or ``class`` body, which
    is the deferred form this gate exists to require.

    ``if TYPE_CHECKING:`` is **not** exempted. It is never executed at runtime,
    so it cannot break startup -- but PyInstaller's modulegraph is static and
    follows it anyway, which would pull torch toward the default artifact and
    make it depend on the ``excludes`` list to stay out. A string annotation
    (this codebase already uses ``from __future__ import annotations``
    throughout) needs no import at all, so nothing is lost by refusing.
    """
    found: list[tuple[str, int]] = []

    def walk(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.append((alias.name.split(".", 1)[0], node.lineno))
            elif isinstance(node, ast.ImportFrom):
                # A relative import (level > 0) names no top-level package.
                if node.level == 0 and node.module:
                    found.append((node.module.split(".", 1)[0], node.lineno))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                # Deferred, or an attribute of a class body that is itself only
                # reached through the class -- neither runs torch at startup.
                continue
            else:
                # Any other compound statement still executes at import time.
                for field in ("body", "orelse", "finalbody"):
                    walk(getattr(node, field, []) or [])
                for handler in getattr(node, "handlers", []) or []:
                    walk(handler.body)

    walk(tree.body)
    return found


def _full_module_scope_targets(tree: ast.Module) -> list[tuple[str, int]]:
    """Module-scope imports with their full dotted path, for rule 2.

    Rule 2 matches on a package *prefix* (``app.relation_extraction`` and
    anything under it), so unlike rule 1 it needs more than the first
    component.
    """
    found: list[tuple[str, int]] = []

    def walk(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.append((alias.name, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    found.append((node.module, node.lineno))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            else:
                for field in ("body", "orelse", "finalbody"):
                    walk(getattr(node, field, []) or [])
                for handler in getattr(node, "handlers", []) or []:
                    walk(handler.body)

    walk(tree.body)
    return found


def _is_quarantined(path: Path) -> bool:
    quarantine = _relations_package_dir()
    try:
        path.relative_to(quarantine)
    except ValueError:
        return False
    return True


def _in_package(dotted: str, package: str) -> bool:
    return dotted == package or dotted.startswith(package + ".")


def check_file(path: Path, source: str, display: str) -> list[str]:
    """Return a list of violation messages for one module."""
    problems: list[str] = []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [
            f"{display}:{exc.lineno}: could not be parsed ({exc.msg}). The gate "
            f"cannot vouch for a file it cannot read."
        ]

    quarantined = _is_quarantined(path)

    # Rule 1 -- the runtime itself, at module scope, outside the quarantine.
    if not quarantined:
        for package, lineno in _module_scope_imports(tree):
            if package in RELATIONS_RUNTIME_PACKAGES:
                problems.append(
                    f"{display}:{lineno}: module-scope import of {package!r}.\n"
                    f"      The default artifact has no {package}, so this raises "
                    f"ImportError at startup\n"
                    f"      for every user of it. Move the import inside the "
                    f"function that needs it, or\n"
                    f"      put the code in {RELATIONS_PACKAGE} and reach it "
                    f"lazily (#60)."
                )

    # Rule 2 -- the quarantine package, at module scope, from outside it.
    if not quarantined:
        for dotted, lineno in _full_module_scope_targets(tree):
            if _in_package(dotted, RELATIONS_PACKAGE):
                problems.append(
                    f"{display}:{lineno}: module-scope import of {dotted!r}.\n"
                    f"      That package imports the relations runtime, so "
                    f"importing it at module scope\n"
                    f"      pulls torch into startup just as directly as "
                    f"importing torch here would.\n"
                    f"      Import it inside the function that needs it, after "
                    f"the availability check (#60)."
                )

    return problems


def run_repo_check() -> tuple[list[str], int, bool]:
    """Check the real tree. Returns (problems, files_scanned, quarantine_exists)."""
    problems: list[str] = []
    files = _python_files()
    for path in files:
        display = path.relative_to(REPO_ROOT).as_posix()
        problems.extend(check_file(path, path.read_text(encoding="utf-8"), display))
    return problems, len(files), _relations_package_dir().is_dir()


# --------------------------------------------------------------------- self-test

# Fixtures. Each is (label, synthetic path relative to repo root, source,
# must_be_rejected). The paths are not written to disk -- `check_file` takes the
# source directly, so the control cannot leave anything behind or depend on the
# tree's state.
_FIXTURES = [
    (
        "rule 1: bare module-scope import",
        "src/app/main_window.py",
        "import sys\nimport torch\n",
        True,
    ),
    (
        "rule 1: from-import",
        "src/app/bridge_domains/relations.py",
        "from transformers import AutoTokenizer\n",
        True,
    ),
    (
        "rule 1: try/except ImportError does not excuse it",
        "src/app/main_window.py",
        "try:\n    import torch\nexcept ImportError:\n    torch = None\n",
        True,
    ),
    (
        "rule 1: if TYPE_CHECKING does not excuse it",
        "src/app/main_window.py",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import torch\n",
        True,
    ),
    (
        "rule 1: a dependency counts too",
        "src/app/main_window.py",
        "import huggingface_hub\n",
        True,
    ),
    (
        "rule 2: module-scope import of the quarantine package",
        "src/app/bridge_domains/relations.py",
        f"from {RELATIONS_PACKAGE} import propose\n",
        True,
    ),
    (
        "rule 2: a submodule of it counts too",
        "src/app/main_window.py",
        f"import {RELATIONS_PACKAGE}.runtime\n",
        True,
    ),
    (
        "accepted: deferred import inside a function",
        "src/app/main_window.py",
        "def extract(text):\n    import torch\n    return torch\n",
        False,
    ),
    (
        "accepted: deferred import of the quarantine package",
        "src/app/bridge_domains/relations.py",
        f"def propose(text):\n"
        f"    from {RELATIONS_PACKAGE} import propose as _p\n"
        f"    return _p(text)\n",
        False,
    ),
    (
        "accepted: the quarantine package may import the runtime itself",
        f"src/{RELATIONS_PACKAGE.replace('.', '/')}/runtime.py",
        "import torch\nfrom transformers import AutoModel\n",
        False,
    ),
    (
        "accepted: an unrelated module-scope import",
        "src/app/main_window.py",
        "import sys\nfrom pathlib import Path\n",
        False,
    ),
]


def run_self_test() -> int:
    print("Self-test: the gate against synthetic fixtures\n")
    failures = 0
    for label, rel, source, must_reject in _FIXTURES:
        path = REPO_ROOT / rel
        problems = check_file(path, source, rel)
        rejected = bool(problems)
        ok = rejected == must_reject
        verdict = "ok" if ok else "BROKEN"
        want = "reject" if must_reject else "accept"
        got = "rejected" if rejected else "accepted"
        print(f"  [{verdict:>6}] want {want:<6} got {got:<8}  {label}")
        if not ok:
            failures += 1
            for problem in problems:
                print(f"            {problem.splitlines()[0]}")
    print()
    if failures:
        print(f"SELF-TEST FAILED: {failures} fixture(s) behaved wrongly.")
        print("The gate does not do what it claims; do not trust a green repo run.")
        return 1
    print(f"OK: all {len(_FIXTURES)} fixtures behaved as specified.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check that nothing WIMI starts up through imports the "
                    "relation-extraction runtime at module scope (#60).",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run the gate against synthetic fixtures instead of the repo, "
             "including the negative controls that prove it can fail",
    )
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    print("Relations-runtime import check (#60)\n")
    problems, scanned, quarantine_exists = run_repo_check()

    print(f"  scanned          {scanned} file(s) under "
          f"{', '.join(p.as_posix() for p in SCAN_ROOTS)}")
    print(f"  runtime packages {len(RELATIONS_RUNTIME_PACKAGES)} forbidden at "
          f"module scope")
    print(f"  quarantine       {RELATIONS_PACKAGE}  "
          f"({'present' if quarantine_exists else 'does not exist yet'})")
    print()

    if problems:
        print(f"FAIL: {len(problems)} violation(s).\n")
        for problem in problems:
            print(f"  - {problem}\n")
        print(
            "The default artifact does not contain the relation-extraction "
            "runtime and never\nwill (#60, owner's decision 2026-10-04: two "
            "artifacts per platform). An import of\nit on the startup path is "
            "an ImportError before the window appears, on the build\nalmost "
            "everyone downloads -- and it will not reproduce in a development "
            "venv that\nhas torch installed."
        )
        return 1

    if not quarantine_exists:
        print(
            f"OK: no module-scope import of the relations runtime.\n"
            f"     ({RELATIONS_PACKAGE} does not exist yet -- #60's feature is "
            f"not built. The gate\n"
            f"      is in place so the contract holds from its first commit.)"
        )
    else:
        print("OK: no module-scope import of the relations runtime, and the "
              "quarantine is only reached lazily.")
    print("     Run with --self-test to see the negative controls.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # the gate failing open is worse than failing loud
        print(f"ERROR: the check itself failed: {exc!r}", file=sys.stderr)
        sys.exit(2)
