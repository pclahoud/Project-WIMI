"""#790: the wimi-db tool's mixin map is derived from the composed class.

The hand-kept ``checks`` dict in ``verify_mixin_decomposition`` drifted to
eight mixins short (18 named of 26) without anything noticing. The map is
now built from ``UserDatabase.__bases__`` at call time, with the old sample
methods kept as a second assertion for the mixins they named. This test
holds both halves: every base is in the map, and no sample names a mixin
that is not a base.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from database.user_db import UserDatabase

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "mcp_server.py"


def _bases():
    return {b.__name__ for b in UserDatabase.__bases__} - {"BaseDatabase"}


@pytest.mark.unit
def test_the_map_is_built_from_the_composed_class_not_a_literal():
    text = SRC.read_text(encoding="utf-8")
    body = text[text.index("def verify_mixin_decomposition"):]
    body = body[:body.index("\ndef ", 10)]
    assert "UserDatabase.__bases__" in body
    assert "checks[base.__name__] = public" in body


@pytest.mark.unit
def test_every_sample_names_a_real_mixin():
    """The sample dict is the one thing that can still go stale; it may only
    shrink to a subset of the real bases, never name a mixin that is gone."""
    text = SRC.read_text(encoding="utf-8")
    body = text[text.index("    samples = {"):]
    body = body[:body.index("    }\n")]
    named = set(re.findall(r'"([A-Za-z]+Mixin)"', body))
    assert named, "no samples found"
    assert named <= _bases(), sorted(named - _bases())


@pytest.mark.unit
def test_the_derived_map_covers_every_mixin_with_its_public_methods():
    """Reproduce the tool's derivation here and check it against the class,
    so a refactor of the tool that quietly drops a mixin fails."""
    derived = {}
    for base in UserDatabase.__bases__:
        if base.__name__ == "BaseDatabase":
            continue
        derived[base.__name__] = sorted(
            n for n, m in vars(base).items() if callable(m) and not n.startswith("_"))
    assert set(derived) == _bases()
    assert "create_planned_session" in derived["CalendarMixin"]
    assert "start_assessment" in derived["AssessmentsMixin"]
    assert len(derived) >= 27, "UserDatabase composes at least 27 mixins as of #778 Wave 0"
