"""Database-side assertion helpers for the WIMI test infrastructure.

Pure leaf module of small, composable assertion functions that operate
directly on a :class:`database.user_db.UserDatabase` instance. Each
helper raises :class:`wimi_test.errors.AssertionFailureWithCapture` on
mismatch with a clear ``expected vs actual`` diagnostic in the message.

These helpers are deliberately shared between two callers:

* pytest scenarios in ``tests/wimi_test/`` (and downstream Phase 4/5
  tests), which call them inside test bodies after a UI action has
  driven a database write.
* The MCP ``inspection`` tools in ``src/wimi_test_mcp/tools/inspection.py``
  (Phase 5), which call the same helpers to validate state during
  Claude-driven exploratory testing.

Module responsibility per
``docs/planning/TEST_INFRASTRUCTURE.md`` Section 3 (Module
responsibility matrix): a pure leaf — no imports from
``wimi_test.session``, no module-level state, no side effects beyond
raising. The capture-attachment design from Section 4 is honoured
here by the explicit choice to pass ``captures=None`` from this layer:
the pytest hook in ``wimi_test/fixtures/capture.py`` (T3.9) is
responsible for attaching a real :class:`CaptureBundle` when it
re-raises the failure during the failure report.

Initial helper set (per task T2.6 of
``docs/planning/TEST_INFRASTRUCTURE_TASKS.md``):

* :func:`assert_entry_count` — asserts the total entry count under
  optional ``exam_context_id`` / ``session_id`` filters.
* :func:`assert_subject_exists` — asserts a subject with the given
  exact name exists, optionally restricted to one exam context.
* :func:`assert_session_completed` — asserts a review session is in
  ``session_status='completed'``.

Bonus helpers (``assert_subject_count``, ``assert_entry_has_subject``)
are intentionally omitted here. Task T2.6 directs us to skip them
when their underlying ``UserDatabase`` calls are not obvious; both
tangle with the polyhierarchy migration in
``docs/planning/POLYHIERARCHY_MIGRATION.md``, so a follow-up task can
land them once the data shape is settled.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from wimi_test.errors import AssertionFailureWithCapture

if TYPE_CHECKING:  # pragma: no cover - import-time only
    from database.user_db import UserDatabase

__all__ = [
    "assert_entry_count",
    "assert_subject_exists",
    "assert_session_completed",
]


def _format_filters(**filters: object) -> str:
    """Render an ordered ``key=value`` list for diagnostic messages.

    Filters whose value is ``None`` are rendered as ``key=any`` so the
    failure message is unambiguous about what was (and was not)
    constrained.
    """
    parts = []
    for key, value in filters.items():
        parts.append(f"{key}={value if value is not None else 'any'}")
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Entry assertions
# ---------------------------------------------------------------------------


def assert_entry_count(
    db: "UserDatabase",
    expected: int,
    *,
    exam_context_id: Optional[int] = None,
    session_id: Optional[int] = None,
) -> None:
    """Assert that the total number of entries equals ``expected``.

    Uses :meth:`UserDatabase.get_entries_paginated`, which returns the
    full ``(entries, total)`` tuple — the ``total`` is the unpaginated
    row count and is the cheapest way to ask "how many?" against the
    same filter surface the bridge uses (mirrors the pattern in
    ``src/mcp_server.py`` ``list_entries``). We request a one-row page
    so the entry rows are not materialised.

    Parameters
    ----------
    db:
        The :class:`UserDatabase` to query. Always the first positional
        argument so this helper composes with any session that exposes
        a per-user db (pytest fixtures, MCP tools, ad-hoc scripts).
    expected:
        The expected total count.
    exam_context_id:
        Optional filter — only count entries belonging to this exam
        context.
    session_id:
        Optional filter — only count entries attached to this review
        session.

    Raises
    ------
    AssertionFailureWithCapture
        If the actual count differs from ``expected``. The bundled
        ``captures`` reference is ``None`` at this layer; it is filled
        in by the pytest hook in ``wimi_test/fixtures/capture.py``
        (T3.9) when re-raising during the failure report.
    """
    _, actual = db.get_entries_paginated(
        exam_context_id=exam_context_id,
        session_id=session_id,
        page=1,
        per_page=1,
    )

    if actual != expected:
        filters = _format_filters(
            exam_context_id=exam_context_id,
            session_id=session_id,
        )
        raise AssertionFailureWithCapture(
            f"Expected {expected} entries ({filters}); got {actual}",
            captures=None,
        )


# ---------------------------------------------------------------------------
# Subject assertions
# ---------------------------------------------------------------------------


def assert_subject_exists(
    db: "UserDatabase",
    name: str,
    *,
    exam_context_id: Optional[int] = None,
) -> None:
    """Assert that a subject with exact name ``name`` exists.

    Resolution path:

    * When ``exam_context_id`` is supplied, the function calls
      :meth:`UserDatabase.search_subjects` (which scopes by exam and
      returns a list of subject rows) and filters for an exact
      case-sensitive name match. ``search_subjects`` performs a
      ``LIKE %query%`` match, so we filter the results client-side
      rather than rely on the underlying SQL for exact-match
      semantics.
    * When ``exam_context_id`` is omitted, we drop to a direct SQL
      lookup on the ``subject_nodes`` table. Going through
      :meth:`UserDatabase.fetchone` keeps the helper a pure leaf — no
      cross-mixin choreography, no transaction management.

    Parameters
    ----------
    db:
        The :class:`UserDatabase` to query.
    name:
        Exact subject name to look for. Compared case-sensitively to
        match the way the application stores subject names (see
        ``src/database/domains/hierarchy.py``).
    exam_context_id:
        Optional restriction to a single exam context. ``None`` means
        "any exam context".

    Raises
    ------
    AssertionFailureWithCapture
        If no subject with that exact name is found in the requested
        scope.
    """
    if exam_context_id is not None:
        # Use the public bridge-facing API. ``search_subjects`` returns
        # dicts shaped ``{id, name, path, level_type, weight}``; we
        # filter for exact-match because the underlying query is a
        # substring LIKE.
        candidates = db.search_subjects(exam_context_id, name, limit=50)
        for row in candidates:
            if row.get("name") == name:
                return
    else:
        # Direct lookup against ``subject_nodes``. Status filter
        # mirrors the rest of the codebase (soft-deleted rows are
        # invisible to every other query).
        row = db.fetchone(
            "SELECT id FROM subject_nodes WHERE name = ? AND status = 'active' LIMIT 1",
            (name,),
        )
        if row is not None:
            return

    filters = _format_filters(exam_context_id=exam_context_id)
    raise AssertionFailureWithCapture(
        f"Expected subject named {name!r} ({filters}); not found",
        captures=None,
    )


# ---------------------------------------------------------------------------
# Session assertions
# ---------------------------------------------------------------------------


def assert_session_completed(db: "UserDatabase", session_id: int) -> None:
    """Assert that review session ``session_id`` is marked completed.

    The ``session_status`` column on ``review_sessions`` is the source
    of truth (see :class:`database.models.ReviewSession`); allowed
    values are ``'in_progress'``, ``'completed'``, ``'abandoned'``.
    This helper looks the row up via
    :meth:`UserDatabase.get_review_session` and compares the status
    field exactly.

    Parameters
    ----------
    db:
        The :class:`UserDatabase` to query.
    session_id:
        Primary key of the review session to inspect.

    Raises
    ------
    AssertionFailureWithCapture
        If the session does not exist or its ``session_status`` is
        anything other than ``'completed'``.
    """
    session = db.get_review_session(session_id)
    if session is None:
        raise AssertionFailureWithCapture(
            f"Expected session {session_id} status='completed'; "
            f"session not found",
            captures=None,
        )

    actual = session.session_status
    if actual != "completed":
        raise AssertionFailureWithCapture(
            f"Expected session {session_id} status='completed'; got {actual!r}",
            captures=None,
        )
