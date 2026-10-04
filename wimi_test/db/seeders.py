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

Three seeders ship in this module:

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
* ``seed_multi_dimensional`` — one exam carrying two dimensions, with
  entries in both, an archived subject that still carries an entry, a
  subject with no dimension at all, and a subject under two parents.
  Added for #208; the dimensional code paths had **no** seeder before
  it — ``grep -c dimension`` over this file returned 0 — so every test
  of one was written against a database that could not express the
  failure mode.

Public API:

* :func:`seeder` — decorator that registers a function under a name.
* :func:`get_seeder` — look up a seeder by name (raises
  :class:`KeyError` listing valid names if missing).
* :func:`seed_minimal` — direct callable, also registered as
  ``"minimal"``.
* :func:`seed_usmle_step1_outline` — direct callable, also registered
  as ``"usmle_step1_outline"``.
* :func:`seed_multi_dimensional` — direct callable, also registered
  as ``"multi_dimensional"``.

One asymmetry to know about: ``seed_multi_dimensional`` returns a
:class:`MultiDimensionalFixture` of ids, where the other two return
``None``. :meth:`TestUser.seed` discards the return value either way;
a direct caller in ``tests/database/`` needs it. See that class for
why.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # pragma: no cover — import-time only
    from database.user_db import UserDatabase


__all__ = [
    "seeder",
    "get_seeder",
    "seed_minimal",
    "seed_usmle_step1_outline",
    "seed_multi_dimensional",
    "MultiDimensionalFixture",
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


# ---------------------------------------------------------------------------
# Multi-dimensional seeder
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MultiDimensionalFixture:
    """Handle onto everything :func:`seed_multi_dimensional` created.

    The two seeders above return ``None`` because their callers only ever
    needed "a database with stuff in it". A multi-dimensional fixture is
    not usable that way: every assertion about it has to name a dimension
    or a subject, and looking those back up by name in each test is how
    a test ends up asserting against the wrong row. So this one returns
    its ids.

    :meth:`wimi_test.db.test_user.TestUser.seed` discards the return
    value, which is fine — a UI scenario navigates by name. Direct
    callers (``tests/database/``) use the handle.
    """

    exam_name: str
    exam_context_id: int
    #: dimension name -> ``exam_dimensions.id``
    dimensions: dict
    #: subject name -> ``subject_nodes.id``, active and archived alike
    nodes: dict
    #: ids of the subjects left ``status='archived'``
    archived_node_ids: tuple
    #: the subject sitting under two parents inside one dimension
    shared_node_id: int
    #: the subject carrying ``dimension_id IS NULL``
    undimensioned_node_id: int
    review_session_id: int
    #: subject name -> the entry ids mapped to it as ``mapping_type='primary'``
    entries_by_subject: dict


@seeder("multi_dimensional")
def seed_multi_dimensional(
    db: "UserDatabase",
    *,
    exam_name: str = "Multi-Dimensional Exam (Test Fixture)",
    filler_topics_per_dimension: int = 0,
    filler_entries: int = 0,
) -> MultiDimensionalFixture:
    """Seed one exam carrying **two** dimensions, with entries in both.

    There was no multi-dimensional seeder in this module at all before
    #208 — ``grep -c dimension wimi_test/db/seeders.py`` returned 0 —
    which meant every test of a dimensional code path was written
    against a single-dimension or dimensionless database and passed for
    the wrong reason. This project has been bitten by that shape three
    times in two days: a tree seeded without entries hid a deep-dive N+1
    at 0.17 ms/child against its real 4.5 (#201), a seed with one review
    session hid DOM growth at 412 elements against 4,463 (#202), and a
    400-entry seed hid a 2.8 s page (#199).

    So the four things here are chosen to be the ones a dimensional
    query can get wrong, not to look realistic:

    * **Two dimensions**, each with its own subjects and its own
      entries. A query that forgets ``dimension_id`` counts the other
      dimension's mistakes, and with one dimension nothing notices.
    * **An archived subject inside a dimension that still carries an
      entry.** Archived-but-empty proves nothing: the row has to be able
      to *arrive* in a result for a missing ``status = 'active'`` to be
      visible. Archived through :meth:`delete_subject_subtree`, the real
      path (#15), rather than an ``UPDATE`` that skips its journal.
    * **A subject with ``dimension_id IS NULL``** carrying an entry —
      the dimensionless leftovers a part-converted exam really has.
      ``IS NULL`` never equals a dimension id, so this one is caught by
      the same predicate as the point above, from the other side.
    * **A shared subject under two parents inside one dimension**, with
      one entry pinned to each parent and one left unpinned, so §5.4's
      three-way bucket split (#13) is exercised rather than assumed.

    Parameters
    ----------
    exam_name
        Lets a test seed two of these into one database without
        colliding on ``exam_contexts.exam_name``.
    filler_topics_per_dimension
        Extra leaf topics under each dimension's first root. Zero by
        default: the named fixture above is what tests assert on, and
        every filler node costs a ``create_subject_node`` round trip.
        Raise it to make a dimension large enough to measure a query
        plan against (#208's A/B used 200/800/2,000).
    filler_entries
        Entries spread round-robin over the **first** dimension's filler
        topics. Zero by default. Ignored when there are no filler
        topics.

    Returns
    -------
    MultiDimensionalFixture
        Ids for everything created. See that class for why this seeder
        returns a value when the others do not.
    """
    if filler_entries and not filler_topics_per_dimension:
        raise ValueError(
            "filler_entries=%d with filler_topics_per_dimension=0 has "
            "nowhere to put them. Ask for filler topics too." % filler_entries
        )

    db._ensure_phase2_schema()
    db._ensure_phase4_schema()

    exam = db.create_exam_context(
        exam_name=exam_name,
        exam_description=(
            "Two dimensions, entries in both, one archived subject that "
            "still carries an entry, one subject with no dimension at "
            "all, and one subject under two parents (#208)."
        ),
        hierarchy_levels=["System", "Topic"],
    )

    dimensions = {
        "System": db.create_dimension(
            exam_id=exam.id, name="System", display_order=1,
            description="Organ system the item is coded to",
        ),
        "Physician Task": db.create_dimension(
            exam_id=exam.id, name="Physician Task", display_order=2,
            description="What the item asks the candidate to do",
        ),
    }
    sys_dim = dimensions["System"]
    task_dim = dimensions["Physician Task"]

    nodes: dict = {}

    def _node(name, level_type, parent_id=None, dimension_id=None, sort_order=1):
        node = db.create_subject_node(
            exam_context=exam.exam_name,
            name=name,
            level_type=level_type,
            parent_id=parent_id,
            dimension_id=dimension_id,
            sort_order=sort_order,
        )
        nodes[name] = node.id
        return node.id

    # --- dimension 1: System -------------------------------------------
    cardio = _node("Cardiovascular System", "System", dimension_id=sys_dim, sort_order=1)
    renal = _node("Renal System", "System", dimension_id=sys_dim, sort_order=2)
    # The shared subject: created under Cardiovascular, then given Renal
    # as a second parent. Both parents are inside this dimension, which
    # is what makes the §5.4 split observable here rather than a
    # cross-dimension question.
    hypertension = _node("Hypertension", "Topic", parent_id=cardio,
                         dimension_id=sys_dim, sort_order=1)
    db.add_edge(parent_id=renal, child_id=hypertension, is_primary=False)
    heart_failure = _node("Heart Failure", "Topic", parent_id=cardio,
                          dimension_id=sys_dim, sort_order=2)
    aki = _node("Acute Kidney Injury", "Topic", parent_id=renal,
                dimension_id=sys_dim, sort_order=1)
    retired = _node("Retired Cardiology Topic", "Topic", parent_id=cardio,
                    dimension_id=sys_dim, sort_order=3)

    # --- dimension 2: Physician Task ------------------------------------
    diagnosis = _node("Diagnosis", "System", dimension_id=task_dim, sort_order=1)
    management = _node("Management", "System", dimension_id=task_dim, sort_order=2)
    labs = _node("Interpreting Laboratory Data", "Topic", parent_id=diagnosis,
                 dimension_id=task_dim, sort_order=1)
    pharm = _node("Pharmacotherapy", "Topic", parent_id=management,
                  dimension_id=task_dim, sort_order=1)

    # --- no dimension at all --------------------------------------------
    undimensioned = _node("Unsorted Leftovers", "System", dimension_id=None,
                          sort_order=99)

    # --- filler ----------------------------------------------------------
    filler_by_dimension: dict = {"System": [], "Physician Task": []}
    for dim_name, dim_id, root in (
        ("System", sys_dim, cardio),
        ("Physician Task", task_dim, diagnosis),
    ):
        for i in range(filler_topics_per_dimension):
            filler_by_dimension[dim_name].append(
                _node(f"{dim_name} Filler {i}", "Topic", parent_id=root,
                      dimension_id=dim_id, sort_order=100 + i)
            )

    # --- entries ----------------------------------------------------------
    named_targets = [
        ("Hypertension", hypertension, cardio),
        ("Hypertension", hypertension, renal),
        ("Hypertension", hypertension, None),   # never disambiguated
        ("Heart Failure", heart_failure, None),
        ("Acute Kidney Injury", aki, None),
        ("Retired Cardiology Topic", retired, None),
        ("Interpreting Laboratory Data", labs, None),
        ("Pharmacotherapy", pharm, None),
        ("Diagnosis", diagnosis, None),
        ("Unsorted Leftovers", undimensioned, None),
    ]
    filler_targets = []
    first_dim_filler = filler_by_dimension["System"]
    if first_dim_filler and filler_entries:
        for i in range(filler_entries):
            target = first_dim_filler[i % len(first_dim_filler)]
            filler_targets.append((f"System Filler {i % len(first_dim_filler)}",
                                   target, None))

    all_targets = named_targets + filler_targets
    session = db.create_review_session(
        exam_context_id=exam.id,
        total_questions=len(all_targets),
        total_incorrect=len(all_targets),
        session_name="Multi-dimensional fixture session",
        date_encountered=date.today(),
    )

    entries_by_subject: dict = {}
    for subject_name, node_id, pinned_parent in all_targets:
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="a",
            correct_answer="b",
            primary_subject_ids=[node_id],
        )
        entries_by_subject.setdefault(subject_name, []).append(entry.id)
        if pinned_parent is not None:
            # No database-layer setter exists for this column — the
            # bridge's setPrimaryParentForEntry writes it directly, so
            # the fixture issues the same statement rather than
            # inventing an API. Same choice as #199's guard test.
            with db.transaction():
                db.execute(
                    "UPDATE entry_subject_mappings SET primary_parent_id = ? "
                    "WHERE question_entry_id = ? AND subject_node_id = ?",
                    (pinned_parent, entry.id, node_id),
                )

    # Archive last, so the entry above is already attached to it. The
    # real delete path, not an UPDATE: it also removes the edge from the
    # surviving parent and nulls the orphaned primary_parent_id, which
    # is the state a genuinely archived subject is in (#15).
    db.delete_subject_subtree(retired)

    _logger.info(
        "seed_multi_dimensional: exam %r, dimensions %s, %d subjects "
        "(%d filler/dimension), %d entries",
        exam.exam_name, sorted(dimensions), len(nodes),
        filler_topics_per_dimension, len(all_targets),
    )

    return MultiDimensionalFixture(
        exam_name=exam.exam_name,
        exam_context_id=exam.id,
        dimensions=dimensions,
        nodes=nodes,
        archived_node_ids=(retired,),
        shared_node_id=hypertension,
        undimensioned_node_id=undimensioned,
        review_session_id=session.id,
        entries_by_subject=entries_by_subject,
    )
