"""Both build specs bundle the self-assessment's instrument files where the
frozen resolver looks for them (#794).

Every frozen build between #766 landing and this test offered the assessment
on the dashboard and could not load one item: ``_resolve_fixture_dir`` reads
``<exe dir>/_internal/fixtures/assessments/<version>`` when frozen, and
neither spec bundled ``src/database/fixtures/`` at all. The scenarios run
from a checkout, where the dev path resolves, so nothing saw it (#760's
class: a frozen-build run exercises the bundle's Python against the
checkout's assets).

This test ties the three together by reading them: the directory on disk,
the destination the resolver expects, and the ``datas`` entry in each spec.
It does not build anything.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from database.domains import _assessment_scoring as scoring

REPO = Path(__file__).resolve().parents[1]
SPECS = [REPO / "wimi.spec", REPO / "wimi_macos.spec"]
FIXTURE_ROOT = REPO / "src" / "database" / "fixtures"


def _datas_entries(spec: Path) -> list[tuple[str, str]]:
    """Every ``(str(src_dir / 'a' / 'b'), 'dest')`` tuple in the spec's
    hand-written data lists, as (source relative to src, destination)."""
    text = spec.read_text(encoding="utf-8")
    out = []
    for m in re.finditer(r"\(str\(src_dir((?: / '[^']+')+)\),\s*'([^']+)'\)", text):
        parts = re.findall(r"'([^']+)'", m.group(1))
        out.append(("/".join(parts), m.group(2)))
    return out


def test_the_fixture_directory_exists_and_holds_the_v1_instrument():
    assert (FIXTURE_ROOT / "assessments" / "v1" / "manifest.json").is_file()


def test_the_frozen_resolver_reads_internal_fixtures(monkeypatch, tmp_path):
    """The destination the specs must use is whatever the resolver expects
    under ``_internal``; read it rather than assuming 'fixtures'."""
    monkeypatch.setattr(scoring.sys, "frozen", True, raising=False)
    monkeypatch.setattr(scoring.sys, "executable", str(tmp_path / "WIMI.exe"))
    resolved = scoring._resolve_fixture_dir("v1")
    assert resolved == tmp_path / "_internal" / "fixtures" / "assessments" / "v1"


@pytest.mark.parametrize("spec", SPECS, ids=lambda p: p.name)
def test_each_spec_bundles_the_fixtures_at_the_resolvers_destination(spec, monkeypatch, tmp_path):
    monkeypatch.setattr(scoring.sys, "frozen", True, raising=False)
    monkeypatch.setattr(scoring.sys, "executable", str(tmp_path / "WIMI.exe"))
    frozen_dir = scoring._resolve_fixture_dir("v1")
    # The first path component under _internal is the destination the spec
    # must write the fixtures directory to.
    expected_dest = frozen_dir.relative_to(tmp_path / "_internal").parts[0]
    entries = _datas_entries(spec)
    assert entries, f"{spec.name}: no datas entries parsed; the reader is broken"
    matching = [dest for src, dest in entries if src == "database/fixtures"]
    assert matching == [expected_dest], (
        f"{spec.name} must bundle src/database/fixtures as {expected_dest!r}; "
        f"found {matching!r}. A frozen build without it offers an assessment "
        f"it cannot load (#794).")


def test_the_reader_sees_the_entries_that_have_always_been_there():
    """Control for the regex: the schema and migrations lines predate #794
    and must be parsed, or an empty parse could pass the test above."""
    for spec in SPECS:
        srcs = {src for src, _ in _datas_entries(spec)}
        assert {"database/schema", "database/migrations", "web/html"} <= srcs, spec.name
