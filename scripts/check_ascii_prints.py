#!/usr/bin/env python3
"""CI gate: no non-ASCII literal may appear inside a ``print()`` in shipped code.

Why
---
``print()`` encodes through ``sys.stdout``, and on Windows that encoder is
the console codepage (cp1252 on most installs) whenever the stream is not
a real console - a pipe, or ``WIMI.exe > log.txt``. A character outside
that codepage raises ``UnicodeEncodeError`` *from inside print*, and at
startup that kills the process before the window appears. That is #137:
six calls in four files, of which the first one reached during scheme
registration took the whole frozen build down.

``console_encoding.configure_stdio`` now runs at the top of every entry
point and makes the streams UTF-8 with ``errors='replace'``, so the crash
is fixed at runtime. This gate is the second half: it stops the class
coming back through a path that guard does not cover - a new entry point
that forgets to call it, a subprocess that inherits a different stream, a
tool that imports one of these modules directly. #137 called for it in
the issue body and again in comment #1689.

**Emoji are not the rule.** Two of #137's six call sites were an em dash
(``\\u2014``), which cp1252 cannot encode either. The check is "ASCII or
not", not "emoji or not".

What is checked
---------------
Every ``print(...)`` call in :data:`SCANNED_ROOTS`, for string literals
containing a codepoint above U+007F. f-strings are covered: their literal
segments are ordinary ``ast.Constant`` nodes. A non-ASCII value arriving
through a *variable* is not detectable here and is not the point - the
guard covers it at runtime; this gate covers what a reviewer can see.

``scripts/`` is deliberately out of scope. Those are developer tools run
from a UTF-8 terminal on this project's machines, they never ship, and
several already print an em dash on purpose.

Usage
-----
    python scripts/check_ascii_prints.py

Exit code 0 when clean, 1 with a per-site report otherwise.
``tests/test_ascii_prints_gate.py`` runs this against the real tree.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Iterator, NamedTuple

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories and files whose ``print()`` output can reach a redirected
# stream on an end user's machine. ``src/`` is the whole shipped app;
# ``run_wimi.py`` is the dev launcher, which the test harness pipes.
SCANNED_ROOTS: tuple[str, ...] = ("src", "run_wimi.py")


class Offence(NamedTuple):
    """One non-ASCII literal inside one ``print()`` call."""

    path: Path
    line: int
    chars: str
    snippet: str


def _iter_python_files(root: Path) -> Iterator[Path]:
    """Yield every ``.py`` file under ``root`` (or ``root`` itself)."""
    if root.is_file():
        if root.suffix == ".py":
            yield root
        return
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def _is_print_call(node: ast.AST) -> bool:
    """``True`` for a bare ``print(...)`` call (not ``obj.print(...)``)."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
    )


def _non_ascii(text: str) -> str:
    """Return the distinct non-ASCII characters in ``text``, in order."""
    seen: list[str] = []
    for char in text:
        if ord(char) > 0x7F and char not in seen:
            seen.append(char)
    return "".join(seen)


def scan_file(path: Path) -> list[Offence]:
    """Return every non-ASCII ``print()`` literal in ``path``."""
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:  # pragma: no cover - a broken file is a build error
        raise SystemExit(f"error: could not parse {path}: {exc}") from exc

    lines = source.splitlines()
    offences: list[Offence] = []

    for call in ast.walk(tree):
        if not _is_print_call(call):
            continue
        # ``ast.walk`` over the call reaches f-string segments too: a
        # JoinedStr's literal parts are plain Constant nodes.
        for node in ast.walk(call):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            chars = _non_ascii(node.value)
            if not chars:
                continue
            line = getattr(node, "lineno", call.lineno)
            snippet = lines[line - 1].strip() if 0 < line <= len(lines) else ""
            offences.append(
                Offence(path=path, line=line, chars=chars, snippet=snippet)
            )

    return offences


def main() -> int:
    offences: list[Offence] = []
    for root_name in SCANNED_ROOTS:
        root = REPO_ROOT / root_name
        if not root.exists():
            print(f"error: {root} does not exist", file=sys.stderr)
            return 1
        for path in _iter_python_files(root):
            offences.extend(scan_file(path))

    if not offences:
        print("check_ascii_prints: OK - no non-ASCII print() literals.")
        return 0

    print(
        f"check_ascii_prints: FAIL - {len(offences)} non-ASCII literal(s) "
        "inside print():",
        file=sys.stderr,
    )
    for offence in offences:
        rel = offence.path.relative_to(REPO_ROOT)
        escaped = " ".join(f"{c!r} (U+{ord(c):04X})" for c in offence.chars)
        print(f"  {rel}:{offence.line}: {escaped}", file=sys.stderr)
        if offence.snippet:
            print(f"      {offence.snippet}", file=sys.stderr)
    print(
        "\nWindows encodes print() with the console codepage when stdout is\n"
        "redirected; cp1252 cannot represent these and print() raises\n"
        "UnicodeEncodeError. Use ASCII in print(), or make it a log record.\n"
        "See #137 and src/console_encoding.py.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
