"""Regression: ``subject_edges`` is authoritative for hierarchy walks.

``_get_descendant_node_ids`` and ``_build_subject_path``
(``src/database/domains/_base.py``) used to consult the LadybugDB graph
first and return its answer whenever the node existed there. The graph's
``HAS_CHILD`` edges are built by ``GraphMixin._etl_subjects`` exclusively
from ``subject_nodes.parent_id`` — the legacy single-parent column the
polyhierarchy migration deprecated — and ``EdgesMixin`` performs no graph
dual-write at all. A second parent added via ``add_edge`` therefore never
reached the graph.

The failure mode was not "slightly stale", it was *silent and total*:
``create_subject_node`` dual-writes the **node**, so the graph knew the
edge-only parent and the shortcut fired; the node simply had no outgoing
``HAS_CHILD``, so the walk returned an EMPTY descendant set. Every caller
that derives query scope from the helper (``get_entries_paginated``'s
subject filter, the analytics rollups) then computed a correct query over
a wrong id set, quietly reverting polyhierarchy behaviour.

The DAG these tests build — ``Shared Child`` has two parents, and the
second one exists ONLY in ``subject_edges``::

       LegacyParent      EdgeOnlyParent
            |             :
            | (parent_id  : (subject_edges only —
            |  + edge)    :  never dual-written to the graph)
            +---> SharedChild <---+
"""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import pytest

from database import MasterDatabase, UserDatabase


# ---------------------------------------------------------------- fixtures


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def master_db(temp_dir):
    db = MasterDatabase(data_dir=temp_dir)
    yield db
    db.close()


@pytest.fixture
def user_db(master_db):
    user = master_db.create_user(
        username="dws_user",
        display_name="Descendant Walk Sources User",
        user_types=["student"],
    )
    db_path = master_db.ensure_user_database(user.id)
    db = UserDatabase(
        db_path=db_path,
        user_id=user.id,
        username=user.username,
    )
    yield db
    db.close()


def _node(user_db, name, parent_id=None):
    """Create a node through the public writer.

    Deliberately NOT a raw INSERT: ``create_subject_node`` is what
    dual-writes the node into the graph, and the node being present in
    the graph is exactly the precondition that made the old graph-first
    shortcut fire.
    """
    return user_db.create_subject_node(
        exam_context="USMLE",
        name=name,
        level_type="Topic",
        parent_id=parent_id,
    ).id


@pytest.fixture
def edge_only_dag(user_db):
    """``SharedChild`` under a legacy parent plus an edge-only parent."""
    legacy_parent = _node(user_db, "LegacyParent")
    edge_only_parent = _node(user_db, "EdgeOnlyParent")
    # parent_id is set here, so this relationship reaches the graph.
    shared_child = _node(user_db, "SharedChild", parent_id=legacy_parent)
    # This one does not: add_edge writes subject_edges and nothing else.
    user_db.add_edge(edge_only_parent, shared_child, is_primary=False)
    return legacy_parent, edge_only_parent, shared_child


def _exam_context_id(user_db):
    """The ``USMLE`` exam context the nodes above were created under."""
    row = user_db.fetchone(
        "SELECT id FROM exam_contexts WHERE exam_name = 'USMLE'"
    )
    if row is not None:
        return row['id']
    cursor = user_db.execute(
        "INSERT INTO exam_contexts (user_id, exam_name, exam_description) "
        "VALUES (?, 'USMLE', 'Test')",
        (user_db.user_id,),
    )
    user_db.conn.commit()
    return cursor.lastrowid


def _graph_is_live(user_db):
    """Whether the graph read path is actually available in this env.

    ``real_ladybug`` is an optional dependency. When it is absent the
    defect could not have triggered, so the divergence tests below have
    no teeth and say so rather than passing vacuously.
    """
    return bool(getattr(user_db, '_graph_read_ready', False))


# ------------------------------------------------- the defect, head-on


def test_descendant_walk_finds_child_via_edge_only_parent(edge_only_dag, user_db):
    """A parent whose relationship exists only in ``subject_edges`` must
    still find its descendant.

    This is the whole bug in one assertion. Pre-fix this returned ``[]``:
    the graph knew ``EdgeOnlyParent`` as a node but had no ``HAS_CHILD``
    out of it, and the helper trusted that empty answer over SQLite.
    """
    legacy_parent, edge_only_parent, shared_child = edge_only_dag

    assert user_db._get_descendant_node_ids(edge_only_parent) == [shared_child], (
        "Descendant walk from the edge-only parent lost its child. "
        "subject_edges is the source of truth for the hierarchy — if a "
        "graph-first read was re-added to _get_descendant_node_ids, it is "
        "answering from subject_nodes.parent_id, which the polyhierarchy "
        "migration deprecated."
    )


def test_descendant_walk_still_finds_child_via_legacy_parent(edge_only_dag, user_db):
    """The legacy parent keeps working — this is a correctness fix, not a
    swap of which parent is visible. Both parents must see the child."""
    legacy_parent, edge_only_parent, shared_child = edge_only_dag

    assert user_db._get_descendant_node_ids(legacy_parent) == [shared_child]


@pytest.mark.skipif(
    "not __import__('importlib').util.find_spec('real_ladybug')",
    reason="real_ladybug not installed — the graph read path cannot fire, "
           "so there is no divergence to observe",
)
def test_graph_and_sqlite_disagree_and_sqlite_wins(edge_only_dag, user_db):
    """Pin the divergence itself, so the test cannot quietly lose teeth.

    If someone rebuilds the ETL on ``subject_edges`` (or adds graph
    dual-writes to ``EdgesMixin``) the two sources will agree and this
    test stops being meaningful — at which point restoring the
    graph-first shortcut becomes a legitimate option. Until then, the
    disagreement is the reason the shortcut is gone, and asserting on it
    documents the precondition that the removal depends on.
    """
    legacy_parent, edge_only_parent, shared_child = edge_only_dag

    if not _graph_is_live(user_db):
        pytest.skip("graph present but not read-ready in this environment")

    # Precondition: the graph knows the node (this is what let the old
    # shortcut fire) but does not know the edge.
    assert user_db._graph_get_subject_node(edge_only_parent), (
        "Precondition broken: the graph no longer knows EdgeOnlyParent, so "
        "the graph-first shortcut could not have fired. Re-derive this test."
    )
    graph_answer = user_db._graph_get_descendant_ids(edge_only_parent)
    assert shared_child not in graph_answer, (
        "The graph now knows the edge-only relationship. If _etl_subjects "
        "was rebuilt on subject_edges, or EdgesMixin gained a graph "
        "dual-write, update _base.py's comments and this test together."
    )

    # And the helper ignores it.
    assert shared_child in user_db._get_descendant_node_ids(edge_only_parent)


# ------------------------------------------- the same defect in the path builder


def test_subject_path_uses_primary_edge_not_graph(user_db):
    """``_build_subject_path`` had the identical graph-first shape.

    Built here as the divergence case the descendant DAG does not
    produce: a node created as a root (so the graph records it via
    ``ROOT_OF``, with no incoming ``HAS_CHILD``) and only afterwards
    attached to a parent via ``add_edge``. SQLite's primary-edge walk
    yields ``Adopter > Orphan``; the graph, having never seen the edge,
    yields the bare node name.
    """
    adopter = _node(user_db, "Adopter")
    orphan = _node(user_db, "Orphan")            # created parentless
    user_db.add_edge(adopter, orphan, is_primary=True)  # edges only

    assert user_db._build_subject_path(orphan) == "Adopter > Orphan", (
        "Path builder fell back to the graph's parent_id-derived "
        "hierarchy and lost the edge-only parent."
    )


@pytest.mark.skipif(
    "not __import__('importlib').util.find_spec('real_ladybug')",
    reason="real_ladybug not installed — the graph read path cannot fire",
)
def test_graph_path_would_have_been_wrong(user_db):
    """Companion to the above: show the graph's answer is the wrong one,
    so the path assertion is not passing by coincidence."""
    adopter = _node(user_db, "Adopter")
    orphan = _node(user_db, "Orphan")
    user_db.add_edge(adopter, orphan, is_primary=True)

    if not _graph_is_live(user_db):
        pytest.skip("graph present but not read-ready in this environment")

    assert user_db._graph_get_subject_node(orphan), "precondition: node in graph"
    assert user_db._graph_build_subject_path(orphan) != "Adopter > Orphan", (
        "The graph now agrees with the primary-edge walk — see the note in "
        "test_graph_and_sqlite_disagree_and_sqlite_wins."
    )


# ------------------------------------------- downstream: scope actually changes


def test_entry_filter_sees_entry_through_edge_only_parent(edge_only_dag, user_db):
    """The reason the helper matters: a caller's scope comes from it.

    ``get_entries_paginated``'s subject filter builds its id set from the
    descendant walk. With the walk returning nothing for an edge-only
    parent, filtering the entry browser by that parent found no entries
    at all — the SQL was right and the inputs were empty.
    """
    legacy_parent, edge_only_parent, shared_child = edge_only_dag

    session = user_db.create_review_session(
        exam_context_id=_exam_context_id(user_db),
        total_questions=1,
        total_incorrect=1,
        session_name="Edge-only scope session",
        date_encountered=date.today(),
    )
    entry = user_db.create_question_entry(
        review_session_id=session.id,
        user_answer="A",
        correct_answer="B",
        primary_subject_ids=[shared_child],
    )

    entries, _total = user_db.get_entries_paginated(
        subject_ids=[edge_only_parent], include_child_subjects=True
    )
    assert {e.id for e in entries} == {entry.id}, (
        "Filtering by the edge-only parent lost the entry on its child. "
        "The descendant walk fed this query an empty id set."
    )
