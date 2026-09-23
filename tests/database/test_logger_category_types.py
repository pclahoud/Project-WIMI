"""Every error_logger category must be an ErrorCategory, not a string.

Regression. ``ErrorLogger`` does ``category.value`` internally
(``error_logger.py:424``), so passing the string ``'DATABASE'`` raises
``AttributeError: 'str' object has no attribute 'value'`` -- but only
when a logger is actually attached.

That conditional is what let it live: the guard is
``if hasattr(self, 'error_logger') and self.error_logger``, and most
tests construct a database without one. So the call sites were silently
skipped under test and blew up in the running app.

The damage was worse than a failed log line. ``create_dimension`` does
its INSERT and ``conn.commit()`` *before* logging, so the row was written
and then the method raised -- the bridge reported "Failed to create
dimension" for a dimension that existed. Found when seeding a
multi-dimensional exam through the real bridge, which no test did.

Grepping is the right shape of check here: the failure is per call site,
not per behaviour, so exercising one path proves nothing about the other
six.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


SRC = Path(__file__).resolve().parents[2] / "src"

# ``category='FOO'`` as a keyword argument: no spaces around ``=`` (PEP 8
# for kwargs) and not preceded by a word character, so SQL like
# ``t.tag_category = 'mistake_type'`` does not match. That exact string
# was the first thing this caught, which is the trade: the check is
# textual, so it is worth keeping narrow rather than clever.
_STRING_CATEGORY = re.compile(r"""(?<![\w.])category=['"][A-Za-z_]+['"]""")


def _offenders():
    hits = []
    for path in SRC.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if _STRING_CATEGORY.search(line):
                rel = path.relative_to(SRC.parent)
                hits.append(f"{rel}:{lineno}: {line.strip()}")
    return hits


def test_no_string_error_categories():
    hits = _offenders()
    assert hits == [], (
        "error_logger category must be an ErrorCategory member, not a "
        "string -- the logger reads category.value and will raise:\n  "
        + "\n  ".join(hits)
    )
