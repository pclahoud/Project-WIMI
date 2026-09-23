"""Tests for ``scripts/check_import_guide_sync.py`` and the guide it guards.

The subject-tree import guide is published three times from one source
(issue #69):

* ``docs/examples/subject_tree_import_format.md`` — the source;
* the ``import-help-source`` block in ``src/web/html/tree_editor.html`` —
  what the ❓ *Import Format Help* button renders, embedded rather than
  fetched because ``docs/`` does not exist in a PyInstaller build;
* ``docs/examples/subject_tree_import.schema.json`` — the JSON Schema,
  lifted out of the guide's own ``## JSON Schema`` section.

Hand synchronisation had already failed: #61 (``root_nodes`` / ``subjects``)
and #62 (sibling order) both landed in the HTML embed and never reached
``docs/``. These tests cover the two halves that have to be right for the
generator to be worth trusting — that it **notices** a desync, and that
``--write`` repairs one — plus the standing guard that the real tree is
clean, and that the shipped schema actually describes the shipped examples.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import jsonschema
import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "check_import_guide_sync.py"
GUIDE_PATH = PROJECT_ROOT / "docs" / "examples" / "subject_tree_import_format.md"
SCHEMA_PATH = PROJECT_ROOT / "docs" / "examples" / "subject_tree_import.schema.json"
HTML_PATH = PROJECT_ROOT / "src" / "web" / "html" / "tree_editor.html"


def _load_script():
    """Import the gate by path — ``scripts/`` is not a package.

    The same arrangement ``tests/test_check_css_tokens.py`` uses, for the
    same reason: an ``__init__.py`` added only to make a test importable
    would change how the gates are run in CI.
    """
    spec = importlib.util.spec_from_file_location("check_import_guide_sync", SCRIPT_PATH)
    assert spec and spec.loader, f"could not load {SCRIPT_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sync = _load_script()


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """A miniature repo with the three files the gate knows about, in sync."""
    guide = "# Guide\n\nBody text.\n\n## JSON Schema\n\n```json\n{\n  \"type\": \"object\"\n}\n```\n"
    (tmp_path / "docs" / "examples").mkdir(parents=True)
    (tmp_path / "src" / "web" / "html").mkdir(parents=True)
    (tmp_path / sync.SOURCE).write_text(guide, encoding="utf-8")
    (tmp_path / sync.EMBED_HOST).write_text(
        "<body>\n"
        f"    {sync.EMBED_OPEN}\n"
        "PLACEHOLDER\n"
        "    </script>\n"
        "</body>\n",
        encoding="utf-8",
    )
    sync.write(tmp_path)
    return tmp_path


# --------------------------------------------------------------------------- #
# The gate notices, and --write repairs
# --------------------------------------------------------------------------- #

@pytest.mark.unit
def test_write_makes_a_fresh_repo_clean(fake_repo: Path):
    """``--write`` is what produces a clean tree in the first place."""
    assert sync.audit(fake_repo) == {}


@pytest.mark.unit
def test_gate_fails_on_a_desynced_embed(fake_repo: Path):
    """Editing the embed by hand is exactly the failure mode #69 is about.

    This is the deliberate-desync check: without it the gate could be
    comparing a string to itself and nobody would know.
    """
    html_path = fake_repo / sync.EMBED_HOST
    html_path.write_text(
        html_path.read_text(encoding="utf-8").replace("Body text.", "Drifted text."),
        encoding="utf-8",
    )

    problems = sync.audit(fake_repo)
    assert str(sync.EMBED_HOST) in problems
    assert "Drifted text." in problems[str(sync.EMBED_HOST)]

    sync.write(fake_repo)
    assert sync.audit(fake_repo) == {}
    assert "Body text." in html_path.read_text(encoding="utf-8")


@pytest.mark.unit
def test_gate_fails_on_a_desynced_schema(fake_repo: Path):
    """The published schema is generated too, so it can drift the same way."""
    schema_path = fake_repo / sync.SCHEMA_FILE
    schema_path.write_text('{\n  "type": "array"\n}\n', encoding="utf-8")

    problems = sync.audit(fake_repo)
    assert str(sync.SCHEMA_FILE) in problems

    sync.write(fake_repo)
    assert json.loads(schema_path.read_text(encoding="utf-8")) == {"type": "object"}


@pytest.mark.unit
def test_gate_fails_when_the_embed_block_is_gone(fake_repo: Path):
    """A renamed or deleted block must fail loudly, not silently stop syncing."""
    html_path = fake_repo / sync.EMBED_HOST
    html_path.write_text("<body>nothing here</body>\n", encoding="utf-8")

    with pytest.raises(sync.GuideError):
        sync.audit(fake_repo)


@pytest.mark.unit
def test_source_containing_a_script_close_tag_is_refused(fake_repo: Path):
    """``</script>`` in the guide would close the block and spill markup."""
    guide = fake_repo / sync.SOURCE
    guide.write_text(
        guide.read_text(encoding="utf-8") + "\nliteral </script> here\n",
        encoding="utf-8",
    )
    with pytest.raises(sync.GuideError):
        sync.audit(fake_repo)


@pytest.mark.unit
def test_main_exit_codes(fake_repo: Path, monkeypatch):
    """0 clean, 1 drifted — the contract CI reads."""
    monkeypatch.setattr(
        sync, "audit", lambda _root: {}, raising=True
    )
    assert sync.main([]) == 0

    monkeypatch.setattr(
        sync, "audit", lambda _root: {"x": "diff"}, raising=True
    )
    assert sync.main([]) == 1


# --------------------------------------------------------------------------- #
# The real tree
# --------------------------------------------------------------------------- #

@pytest.mark.unit
def test_real_tree_is_in_sync():
    """Standing guard: the shipped modal is the shipped guide."""
    assert sync.audit(PROJECT_ROOT) == {}


@pytest.mark.unit
def test_published_schema_is_valid_json_schema():
    """A schema nobody can load settles nothing."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)


def _json_fences(markdown: str) -> list[str]:
    """Every ```json fence in the guide, in order."""
    return re.findall(r"```json\n(.*?)\n```", markdown, re.S)


@pytest.mark.unit
def test_every_json_example_in_the_guide_parses():
    """A guide whose examples do not parse teaches a format nobody can use."""
    fences = _json_fences(GUIDE_PATH.read_text(encoding="utf-8"))
    assert fences, "the guide has no JSON examples at all"
    for index, fence in enumerate(fences):
        try:
            json.loads(fence)
        except json.JSONDecodeError as exc:  # pragma: no cover - failure path
            pytest.fail(f"JSON example {index} does not parse: {exc}\n{fence}")


@pytest.mark.unit
def test_schema_validates_every_document_example_in_the_guide():
    """The shipped schema must accept the guide's own example files.

    A fence is treated as a whole import *file* when it carries
    ``root_nodes`` or ``subjects``, and as a single *subject* when it
    carries a ``name`` — the guide shows both, and validating a bare
    subject against the file schema would be a test bug rather than a
    guide bug.
    """
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    file_validator = jsonschema.Draft202012Validator(schema)
    subject_validator = jsonschema.Draft202012Validator(
        {**schema, "$ref": "#/$defs/subject", "anyOf": [{}], "properties": {}}
    )

    documents = 0
    subjects = 0
    for index, fence in enumerate(_json_fences(GUIDE_PATH.read_text(encoding="utf-8"))):
        payload = json.loads(fence)
        if not isinstance(payload, dict):
            continue
        if "$schema" in payload:
            continue  # the schema fence itself
        if "root_nodes" in payload or "subjects" in payload:
            documents += 1
            errors = sorted(file_validator.iter_errors(payload), key=str)
            assert not errors, f"example {index} fails the schema: {errors[0].message}"
        elif "name" in payload:
            subjects += 1
            errors = sorted(subject_validator.iter_errors(payload), key=str)
            assert not errors, f"subject {index} fails the schema: {errors[0].message}"

    assert documents >= 5, f"expected the guide's five worked examples, saw {documents}"
    assert subjects >= 1, "the guide should show at least one single-subject snippet"

    # Neither validator may be vacuous: a schema that accepts everything
    # would make every assertion above pass while settling nothing.
    assert list(file_validator.iter_errors({"root_nodes": [{"name": " "}]}))
    assert list(subject_validator.iter_errors({"name": "ok", "weight": "heavy"}))
    assert list(
        subject_validator.iter_errors(
            {"name": "ok", "aliases": [{"name": "x", "type": "nickname"}]}
        )
    )


def _prose_lines(markdown: str) -> list[tuple[int, str]]:
    """``(line number, text)`` for every line outside a fenced code block."""
    out: list[tuple[int, str]] = []
    in_fence = False
    for number, line in enumerate(markdown.split("\n"), start=1):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append((number, line))
    return out


@pytest.mark.unit
def test_guide_avoids_constructs_the_modal_renderer_mishandles():
    """The modal renders the guide with ``parseMarkdown`` in import_export.js.

    That is a ~100-line regex renderer, not a markdown library, and it
    has three limits the guide has to live within. None of them errors:
    each just renders the wrong thing, in the shipped app, where nobody
    is looking.

    * A table row with an empty cell loses that cell entirely
      (``.filter(cell => cell)``), silently shifting every later column
      left by one.
    * ``>`` at the start of a line is escaped to ``&gt;`` — blockquotes
      render as literal text.
    * An ordered list is re-numbered from 1 per consecutive run, so a
      list that resumes at 5 after a paragraph displays as 1.
    """
    lines = _prose_lines(GUIDE_PATH.read_text(encoding="utf-8"))
    separator = re.compile(r"\|[-|: ]+\|\s*")

    empty_cells: list[int] = []
    quotes: list[int] = []
    for number, line in lines:
        if line.startswith(">"):
            quotes.append(number)
        if line.startswith("|") and not separator.fullmatch(line):
            cells = line.strip().strip("|").split("|")
            if any(not cell.strip() for cell in cells):
                empty_cells.append(number)

    assert not empty_cells, f"empty table cell(s) at line(s) {empty_cells}"
    assert not quotes, f"blockquote(s) at line(s) {quotes}"

    # Every ordered-list run must start at 1, because that is what the
    # reader will see whatever the source says.
    run_start: int | None = None
    bad_starts: list[tuple[int, int]] = []
    for number, line in lines:
        match = re.match(r"^(\d+)\. ", line)
        if match:
            value = int(match.group(1))
            if run_start is None:
                run_start = value
                if value != 1:
                    bad_starts.append((number, value))
        elif line.strip() and not line.startswith("   "):
            run_start = None

    assert not bad_starts, (
        f"ordered list(s) resuming mid-count at {bad_starts}; the modal "
        f"renumbers each run from 1"
    )


@pytest.mark.unit
def test_guide_documents_the_fields_the_importer_reads():
    """Issue #63: the guide went years without the word ``aliases`` in it.

    The importer reads exactly these keys off a subject. A field added to
    the importer without a line in the guide is the #63 bug happening
    again, so this asserts the names appear rather than trusting review.
    """
    guide = GUIDE_PATH.read_text(encoding="utf-8")
    for field in (
        "`name`", "`id`", "`level_type`", "`weight`",
        "`aliases`", "`sort_order`", "`children`",
        "`root_nodes`", "`subjects`", "`dimension_id`",
    ):
        assert field in guide, f"the import guide never mentions {field}"

    # #63's specific complaint: the four alias types and the two extra
    # alias fields, which a user packed into subject names for want of a
    # paragraph saying they existed.
    for value in ("eponym", "acronym", "alternate_name", "colloquial",
                  "`is_primary`", "`notes`"):
        assert value in guide, f"the import guide never mentions {value}"
