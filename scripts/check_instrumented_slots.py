#!/usr/bin/env python
"""Check that every @pyqtSlot in src/app/bridge_domains/ is paired with @instrumented_slot.

What this script does
---------------------
Walks every ``*.py`` file under ``src/app/bridge_domains/`` (excluding
``__init__.py``), parses each with the standard library ``ast`` module, and
verifies that every method decorated with ``@pyqtSlot`` is *also* decorated
with ``@instrumented_slot``.

Why
---
See ``docs/planning/TEST_INFRASTRUCTURE.md`` Section 6.3 for the rationale.

In short: the test instrumentation harness wraps each bridge slot so that
exceptions raised inside Qt-invoked slots (which Qt would otherwise swallow
silently and turn into a generic boolean ``False`` return) get recorded and
re-raised in tests. This only works when ``@instrumented_slot`` is applied to
every ``@pyqtSlot`` method. Forgetting the pair on a single new method leaves
a silent gap in the test safety net, so we enforce the convention in CI.

Convention (documented in TEST_INFRASTRUCTURE.md Section 6.3)
-------------------------------------------------------------
The decorators stack with ``@pyqtSlot`` *outermost* and ``@instrumented_slot``
*inner*::

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def some_method(self, payload: str) -> str:
        ...

This script does **not** enforce decorator order — only presence. PyQt's
runtime already enforces the functional ordering (the outermost decorator wins
for slot registration), so a pure-presence check is sufficient. The order
recommendation is purely stylistic.

Exemption mechanism (docstring sentinel)
----------------------------------------
A ``@pyqtSlot`` method may legitimately *need* to skip ``@instrumented_slot``
— the canonical example is ``UtilityBridgeMixin.getTestModeBridgeCalls``,
which returns the very buffer that ``@instrumented_slot`` writes into;
wrapping it would self-record on every poll and pollute the stream.

To exempt such a slot, include the literal phrase ``Intentionally not wrapped``
(case-sensitive) anywhere in the method's docstring. The script will skip the
violation and count the slot toward the "exempted" tally printed in the
success line, so a future maintainer can see at a glance whether the exempt
list has grown unexpectedly. New exemptions are self-documenting: the
docstring must already explain *why* the slot opts out, and the sentinel
phrase rides along with that explanation.

Usage
-----
Manual run from the project root::

    python scripts/check_instrumented_slots.py

CI integration: add a step that runs this script and fails the build on a
non-zero exit code. Exit codes:

* ``0`` — every ``@pyqtSlot`` method has a paired ``@instrumented_slot``.
* ``1`` — at least one violation; each is printed with ``file:line``.
* ``2`` — unexpected error (e.g., the script itself crashed).

Expected initial-failure state
------------------------------
Until tasks T3.5a-T3.5e land (which add ``@instrumented_slot`` to the existing
~190 bridge mixin methods), this script will report a violation for *every*
existing ``@pyqtSlot`` method. That's expected and is why the script is wired
into CI **after** T3.5* completes. The script's ongoing job is to catch any
*future* slot that forgets the pair.

Limitations
-----------
* Only the literal decorator names ``pyqtSlot`` and ``instrumented_slot`` are
  recognised. Aliased imports such as ``from PyQt6.QtCore import pyqtSlot as
  Slot`` would slip past this check. The bridge mixins do not use aliases; if
  that changes, extend ``DECORATOR_NAMES`` below.
* Both the bare-name (``@pyqtSlot``) and call (``@pyqtSlot(str)``) decorator
  forms are detected. Same for ``@instrumented_slot``.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


PYQTSLOT_NAME = "pyqtSlot"
INSTRUMENTED_NAME = "instrumented_slot"

# Case-sensitive substring that, when present in a slot's docstring,
# exempts the slot from the "must be paired with @instrumented_slot"
# rule. See the "Exemption mechanism" section in the module docstring.
EXEMPT_DOCSTRING_SENTINEL = "Intentionally not wrapped"


# --------------------------------------------------------------------------- #
# AST helpers
# --------------------------------------------------------------------------- #

def _decorator_name(decorator: ast.expr) -> str | None:
    """Return the bare name of a decorator expression, or None if not extractable.

    Handles both forms:

    * ``@foo`` -> ``ast.Name(id="foo")``
    * ``@foo(...)`` -> ``ast.Call(func=ast.Name(id="foo"))``

    Attribute decorators like ``@module.foo`` are intentionally not unwrapped;
    they return the attribute name (``foo``) so that fully-qualified usages
    still match. We extract via ``ast.Attribute.attr`` for that case.
    """
    if isinstance(decorator, ast.Name):
        return decorator.id
    if isinstance(decorator, ast.Call):
        return _decorator_name(decorator.func)
    if isinstance(decorator, ast.Attribute):
        return decorator.attr
    return None


def _has_decorator(func: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> bool:
    """Return True if `func` carries a decorator with the given bare name."""
    for dec in func.decorator_list:
        if _decorator_name(dec) == name:
            return True
    return False


def _iter_functions_in_class(cls: ast.ClassDef):
    """Yield every FunctionDef/AsyncFunctionDef inside a class, recursing into nested classes."""
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node
        elif isinstance(node, ast.ClassDef):
            yield from _iter_functions_in_class(node)


# --------------------------------------------------------------------------- #
# Public API (per the task spec)
# --------------------------------------------------------------------------- #

def find_pyqtslot_methods(tree: ast.AST) -> list[ast.FunctionDef]:
    """Return every function/method decorated with ``@pyqtSlot`` in `tree`.

    Walks every ``ClassDef`` (recursing into nested classes) plus module-level
    function definitions. Both ``ast.FunctionDef`` and ``ast.AsyncFunctionDef``
    are returned (the spec types this as ``list[ast.FunctionDef]`` for brevity,
    but async slots are accepted too).
    """
    matches: list[ast.FunctionDef] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for func in _iter_functions_in_class(node):
                if _has_decorator(func, PYQTSLOT_NAME):
                    matches.append(func)
    # Also handle module-level slots (rare but possible).
    if isinstance(tree, ast.Module):
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if _has_decorator(node, PYQTSLOT_NAME):
                    matches.append(node)
    return matches


def has_instrumented_slot(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return True if `func` is decorated with ``@instrumented_slot`` (bare or call form)."""
    return _has_decorator(func, INSTRUMENTED_NAME)


def is_exempt(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return True if `func` opts out of the @instrumented_slot pairing rule.

    Opt-out mechanism: the function's docstring contains the literal,
    case-sensitive phrase ``Intentionally not wrapped`` (see
    ``EXEMPT_DOCSTRING_SENTINEL``). This is intentionally narrow — the
    phrase rides along with the prose that *justifies* the exemption,
    so an exempt slot is self-documenting.
    """
    docstring = ast.get_docstring(func, clean=False)
    if not docstring:
        return False
    return EXEMPT_DOCSTRING_SENTINEL in docstring


def _enclosing_class_name(tree: ast.AST, target: ast.AST) -> str | None:
    """Find the name of the ClassDef that directly or transitively contains `target`."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for func in _iter_functions_in_class(node):
                if func is target:
                    return node.name
    return None


def check_file(path: Path) -> list[str]:
    """Parse `path` and return a list of human-readable violation strings.

    A violation is a ``@pyqtSlot`` method missing the paired ``@instrumented_slot``.
    An empty list means the file is clean. Slots that carry the docstring
    sentinel (see :func:`is_exempt`) are skipped silently here; callers that
    need the exempt-slot tally should use :func:`scan_file` instead.
    """
    violations, _exempt = scan_file(path)
    return violations


def scan_file(
    path: Path,
) -> tuple[list[str], list[str]]:
    """Parse `path` and return ``(violations, exempt_qualnames)``.

    ``violations`` mirrors :func:`check_file`'s return value. ``exempt_qualnames``
    lists the ``file::Class::method`` qualnames of slots that opted out via the
    docstring sentinel — used by :func:`main` to print the exemption tally.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{path}: could not read file ({exc})"], []

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [f"{path}:{exc.lineno or 0} — could not parse ({exc.msg})"], []

    violations: list[str] = []
    exempt: list[str] = []
    for func in find_pyqtslot_methods(tree):
        if has_instrumented_slot(func):
            continue
        cls_name = _enclosing_class_name(tree, func) or "<module>"
        # Docstring-sentinel exemption: skip without flagging.
        if is_exempt(func):
            exempt.append(f"{path.name}::{cls_name}::{func.name}")
            continue
        violations.append(
            f"{path}:{func.lineno} {path.name}::{cls_name}::{func.name} "
            f"— @pyqtSlot without paired @instrumented_slot"
        )
    return violations, exempt


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main() -> int:
    """Discover bridge mixin files, scan each, and print a summary.

    Returns ``0`` on success, ``1`` on violations, ``2`` on unexpected error.
    """
    try:
        project_root = Path(__file__).parent.parent
        bridge_domains = project_root / "src" / "app" / "bridge_domains"

        if not bridge_domains.is_dir():
            print(
                f"ERROR: bridge_domains directory not found at {bridge_domains}",
                file=sys.stderr,
            )
            return 2

        files = sorted(
            p for p in bridge_domains.glob("*.py") if p.name != "__init__.py"
        )

        violations: list[str] = []
        exempt_qualnames: list[str] = []
        slot_count = 0
        scanned = 0

        for path in files:
            scanned += 1
            try:
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(path))
            except (OSError, SyntaxError) as exc:
                # Per-file error — record and continue, do not abort.
                print(f"WARN: could not parse {path}: {exc}", file=sys.stderr)
                continue

            slot_methods = find_pyqtslot_methods(tree)
            slot_count += len(slot_methods)
            # Use scan_file so we can also tally docstring-exempt slots.
            file_violations, file_exempt = scan_file(path)
            violations.extend(file_violations)
            exempt_qualnames.extend(file_exempt)

        # Sort violations by file path then line number for stable output.
        def _sort_key(line: str) -> tuple[str, int]:
            head = line.split(" ", 1)[0]  # "path:lineno"
            file_part, _, line_part = head.rpartition(":")
            try:
                return (file_part, int(line_part))
            except ValueError:
                return (head, 0)

        violations.sort(key=_sort_key)
        exempt_qualnames.sort()

        print(f"Scanned {scanned} files, found {slot_count} @pyqtSlot methods.")

        # Build a stable, glanceable exemption summary so a future maintainer
        # can spot growth in the exempt list at a glance.
        exempt_count = len(exempt_qualnames)
        if exempt_count == 0:
            exempt_summary = "0 slots exempted"
        else:
            exempt_summary = (
                f"{exempt_count} slot{'s' if exempt_count != 1 else ''} exempted: "
                + ", ".join(qn.split("::", 1)[1] if "::" in qn else qn for qn in exempt_qualnames)
            )

        if not violations:
            paired = slot_count - exempt_count
            print(
                f"OK: {paired} of {slot_count} pyqtSlot methods paired with "
                f"@instrumented_slot ({exempt_summary})"
            )
            return 0

        for v in violations:
            print(v)
        files_with_violations = len({v.split(":", 1)[0] for v in violations})
        print(
            f"FAIL: {len(violations)} violations across {files_with_violations} "
            f"files ({exempt_summary})"
        )
        return 1

    except Exception as exc:  # pragma: no cover — defensive top-level catch
        print(f"ERROR: unexpected failure in check_instrumented_slots: {exc!r}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
