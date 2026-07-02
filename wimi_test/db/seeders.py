"""Named seeder registry for the WIMI test infrastructure.

Implements the seeder layer described in
``docs/planning/TEST_INFRASTRUCTURE.md`` Section 3 (``db.seeders``
responsibility) and consumed by :meth:`wimi_test.db.test_user.TestUser.seed`
per Section 4.

A *seeder* is a small, deterministic function that takes a freshly
created :class:`UserDatabase` and populates it with whatever fixture
data a scenario needs (an exam context, a subject hierarchy, sample
entries, etc.). Seeders are registered by name so test code can ask for
them symbolically (``user.seed("usmle_step1_outline")``) without
importing private helpers.

Two seeders ship in this module:

* ``seed_minimal`` — one empty exam context, nothing else. Intended
  for smoke tests that just want a non-empty database.
* ``seed_usmle_step1_outline`` — full hierarchy parse of
  ``tests/fixtures/usmle_step1_outline.txt`` (the 2025 USMLE Step 1
  content outline). Produces ~2,500 subject nodes with the parent
  chain System → Section → Subsection → Topic, plus multi-parent
  edges (via ``EdgesMixin.add_edge``) for the ~120 topics that the
  outline lists under more than one section — hypertension under
  seven systems, deep venous thrombosis under both Cardiovascular
  and Pregnancy, etc.

Public API:

* :func:`seeder` — decorator that registers a function under a name.
* :func:`get_seeder` — look up a seeder by name (raises
  :class:`KeyError` listing valid names if missing).
* :func:`seed_minimal` — direct callable, also registered as
  ``"minimal"``.
* :func:`seed_usmle_step1_outline` — direct callable, also registered
  as ``"usmle_step1_outline"``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # pragma: no cover — import-time only
    from database.user_db import UserDatabase


__all__ = [
    "seeder",
    "get_seeder",
    "seed_minimal",
    "seed_usmle_step1_outline",
]


_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

# Maps seeder name → callable. Populated by the ``@seeder`` decorator.
# The signature is loosely typed because individual seeders may accept
# additional keyword-only kwargs (e.g. ``seed_polyhierarchy_fixture``
# is expected to take ``dvt_in_pregnancy=True``).
_SEEDERS: dict[str, Callable[..., None]] = {}


def seeder(name: str) -> Callable[[Callable[..., None]], Callable[..., None]]:
    """Decorator that registers a seeder function under ``name``.

    Example
    -------
    >>> @seeder("minimal")
    ... def seed_minimal(db):  # doctest: +SKIP
    ...     ...

    The decorated function is returned unchanged so it remains
    independently importable and callable.
    """

    def decorator(func: Callable[..., None]) -> Callable[..., None]:
        if name in _SEEDERS:
            # Re-registering the same name is almost always a bug —
            # warn loudly but allow override (test reload scenarios may
            # legitimately re-import this module).
            _logger.warning(
                "Seeder %r already registered; overwriting with %s",
                name,
                func.__qualname__,
            )
        _SEEDERS[name] = func
        return func

    return decorator


def get_seeder(name: str) -> Callable[..., None]:
    """Look up a seeder by name.

    Raises
    ------
    KeyError
        If ``name`` is not registered. The error message lists all
        currently-known seeder names so the caller can correct typos
        without having to grep the codebase.
    """
    if name not in _SEEDERS:
        valid = ", ".join(sorted(_SEEDERS)) or "<none registered>"
        raise KeyError(f"Unknown seeder {name!r}. Valid: {valid}")
    return _SEEDERS[name]


# ---------------------------------------------------------------------------
# Seeders
# ---------------------------------------------------------------------------


@seeder("minimal")
def seed_minimal(db: "UserDatabase") -> None:
    """Seed the bare minimum: one exam context, no subjects, no entries.

    Intended for smoke tests that need a non-empty database but do not
    care about hierarchy or content. Calls
    :meth:`UserDatabase._ensure_phase2_schema` to make sure the
    ``exam_contexts`` table is present, then creates a single context
    named ``"Test Minimal Exam"``.

    Returns
    -------
    None
        Per the registry contract, seeders mutate ``db`` in place and
        do not return values.
    """
    db._ensure_phase2_schema()

    db.create_exam_context(
        exam_name="Test Minimal Exam",
        exam_description="Minimal seed for smoke tests",
    )

    _logger.debug("seed_minimal: created 'Test Minimal Exam' context")


# ---------------------------------------------------------------------------
# USMLE outline seeder
# ---------------------------------------------------------------------------


# Path to the bundled outline fixture. Resolved relative to *this* module
# (``wimi_test/db/seeders.py``) so the seeder works whether tests are
# launched from the project root or from a sibling directory.
_OUTLINE_PATH: Path = (
    Path(__file__).parent.parent.parent / "tests" / "fixtures" / "usmle_step1_outline.txt"
)


def _level_type_for_depth(depth: int) -> str:
    """Map outline depth (0=root) to a UserDatabase level_type string.

    The outline is shallow enough that anything below depth 1 gets the
    catch-all ``"Topic"`` label — the existing tree editor renders
    these the same regardless of how deep they live.
    """
    if depth == 0:
        return "System"
    if depth == 1:
        return "Subsystem"
    return "Topic"


@seeder("usmle_step1_outline")
def seed_usmle_step1_outline(db: "UserDatabase") -> None:
    """Seed the full USMLE Step 1 content outline as a polyhierarchy.

    Walks ``tests/fixtures/usmle_step1_outline.txt`` via
    :func:`tests.fixtures.load_usmle_outline.load_usmle_outline` and
    materialises every named topic as a ``subject_nodes`` row under
    a fresh ``"USMLE Step 1 (Test Fixture)"`` exam context. Topics that
    the outline lists under multiple parent sections (~120 of the
    ~2,500 total — hypertension, deep venous thrombosis, sepsis,
    diabetes mellitus, etc.) get a single canonical node with one
    ``is_primary=TRUE`` edge to their first-seen parent and additional
    ``is_primary=FALSE`` edges to each subsequent parent. This is the
    canonical multi-parent demonstration described in
    ``docs/planning/POLYHIERARCHY_MIGRATION.md`` Section 1.

    Performance note: ~2,500 ``create_subject_node`` calls plus a few
    hundred ``add_edge`` calls take roughly 10–15 seconds in dev mode.
    Tests that don't need the full hierarchy should use ``seed_minimal``
    instead.

    Raises
    ------
    FileNotFoundError
        If the outline fixture is missing. Message includes the
        absolute path so callers can diagnose CI / packaging mistakes.
    """
    if not _OUTLINE_PATH.exists():
        raise FileNotFoundError(
            f"USMLE outline fixture not found at {_OUTLINE_PATH!s}. "
            "This file is required by seed_usmle_step1_outline; ensure "
            "tests/fixtures/usmle_step1_outline.txt is checked in."
        )

    # The parser lives with the test fixtures rather than under
    # wimi_test/, so this is the import boundary we cross. Import lazily
    # so the seeder module stays usable even if tests/fixtures/ isn't on
    # sys.path at collection time (the project conftest puts the repo
    # root on the path before any seeders run).
    from tests.fixtures.load_usmle_outline import load_usmle_outline

    outline = load_usmle_outline(_OUTLINE_PATH)
    if len(outline.topics) < 50:
        # Defensive: parser shape changed and recovered almost nothing.
        # Fail loud rather than seed a half-baked DB.
        raise RuntimeError(
            f"USMLE outline parser recovered only {len(outline.topics)} "
            f"topics from {_OUTLINE_PATH!s}. Expected several hundred. "
            "The fixture or the parser regressed; refusing to seed."
        )

    db._ensure_phase2_schema()
    db._ensure_phase4_schema()

    exam_name = "USMLE Step 1 (Test Fixture)"
    db.create_exam_context(
        exam_name=exam_name,
        exam_description=(
            f"Full polyhierarchy parse of the 2025 USMLE Step 1 content "
            f"outline. {len(outline.topics)} topics; "
            f"{len(outline.multi_parent_topics)} appear under multiple "
            f"parents (e.g. hypertension under 7 systems, DVT under "
            f"both Cardiovascular and Pregnancy)."
        ),
    )

    # Lookup tables.
    #   path_to_node_id keys are *normalized* tuples (lowercased) so the
    #   parser's case-inconsistencies between section-as-state and
    #   section-as-topic don't double-create nodes.
    #   name_to_node_id is what makes a topic multi-parent: when we
    #   re-encounter a name we already created, we add an edge instead
    #   of creating a second node.
    path_to_node_id: dict[tuple[str, ...], int] = {}
    name_to_node_id: dict[str, int] = {}
    sort_counter: dict[int | None, int] = {}
    # Dedupe (parent_id, child_id) pairs we've already attempted. The
    # parser sometimes emits the same (parent_path, leaf_name) tuple
    # more than once when a topic blob splits on comma into the same
    # canonical name twice; without this set we'd hit the
    # ``subject_edges.UNIQUE(parent_id, child_id)`` constraint and
    # surface noisy rollback warnings.
    edges_attempted: set[tuple[int, int]] = set()

    # Lazy imports so the seeder doesn't pull these into module scope
    # during normal collection.
    from database.exceptions import ValidationError
    from database.base_db import BaseDatabaseError
    try:
        from database.exceptions import CircularReferenceError
    except ImportError:  # pragma: no cover — defensive
        CircularReferenceError = None  # type: ignore

    def _norm_path(path: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(p.strip().lower() for p in path)

    def _ensure_path(
        path: tuple[str, ...], display_path: tuple[str, ...]
    ) -> int | None:
        """Materialise the chain of parents for ``path``; return immediate parent id."""
        if not path:
            return None
        norm = _norm_path(path)
        if norm in path_to_node_id:
            return path_to_node_id[norm]
        # Recurse for parent first.
        parent_id = _ensure_path(path[:-1], display_path[:-1])
        depth = len(path) - 1
        sort_counter[parent_id] = sort_counter.get(parent_id, 0) + 1
        node = db.create_subject_node(
            exam_context=exam_name,
            name=display_path[-1],
            level_type=_level_type_for_depth(depth),
            parent_id=parent_id,
            sort_order=sort_counter[parent_id],
        )
        path_to_node_id[norm] = node.id
        return node.id

    edge_added = 0
    edge_skipped = 0

    for topic in outline.topics:
        # Both the parser's parent_path tuple and topic.name come in
        # different cases (parent_path preserves original case; name is
        # already normalized lowercase). Build a display_path that uses
        # original-case ancestors plus the lowercase topic name.
        parent_id = _ensure_path(topic.parent_path, topic.parent_path)

        norm_name = topic.name  # already normalized by the parser
        if norm_name in name_to_node_id:
            # Multi-parent re-encounter — add a non-primary edge.
            if parent_id is None:
                # Root-level same-name (shouldn't happen with real data
                # but the parser is best-effort).
                continue
            existing_id = name_to_node_id[norm_name]
            edge_key = (parent_id, existing_id)
            if edge_key in edges_attempted:
                # Already added (or already attempted and skipped) — the
                # parser emits some (parent_path, name) tuples more than
                # once due to comma-splitting in topic blobs.
                continue
            edges_attempted.add(edge_key)
            try:
                db.add_edge(
                    parent_id=parent_id,
                    child_id=existing_id,
                    is_primary=False,
                )
                edge_added += 1
            except (ValidationError, BaseDatabaseError) as e:
                # Self-loop, duplicate edge, or integrity violation —
                # not fatal for a seeder.
                edge_skipped += 1
                _logger.debug(
                    "seed_usmle_step1_outline: skipped edge %s -> %s: %s",
                    parent_id, existing_id, e,
                )
            except Exception as e:
                # CircularReferenceError lives in the exceptions module
                # but we caught the import defensively above.
                if (
                    CircularReferenceError is not None
                    and isinstance(e, CircularReferenceError)
                ):
                    edge_skipped += 1
                    _logger.debug(
                        "seed_usmle_step1_outline: cycle skipped %s -> %s",
                        parent_id, existing_id,
                    )
                else:
                    raise
            continue

        # First encounter — create the node.
        depth = len(topic.parent_path)
        sort_counter[parent_id] = sort_counter.get(parent_id, 0) + 1
        node = db.create_subject_node(
            exam_context=exam_name,
            name=norm_name,
            level_type=_level_type_for_depth(depth),
            parent_id=parent_id,
            sort_order=sort_counter[parent_id],
        )
        name_to_node_id[norm_name] = node.id
        path_to_node_id[_norm_path(topic.parent_path + (norm_name,))] = node.id
        # ``create_subject_node`` auto-creates a primary edge from
        # ``parent_id`` to the new node. Record it so a later iteration
        # that normalises to the same parent_id doesn't trip the
        # ``UNIQUE(parent_id, child_id)`` constraint via ``add_edge``.
        if parent_id is not None:
            edges_attempted.add((parent_id, node.id))

    _logger.info(
        "seed_usmle_step1_outline: %d nodes, %d multi-parent edges added, "
        "%d edges skipped under %r",
        len(name_to_node_id) + len(path_to_node_id) - len(name_to_node_id),
        edge_added,
        edge_skipped,
        exam_name,
    )
