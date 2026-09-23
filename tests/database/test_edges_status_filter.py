"""``get_edges_for_child`` must not offer an archived parent — issue #57.

``EdgesMixin.get_edges_for_child`` joined ``subject_nodes`` with no
``status`` predicate, so an edge pointing at a soft-deleted parent came
back like any other. That is the same defect issue #15 fixed on the
sibling method :meth:`EdgesMixin.get_parents` (casualty 2); this one was
deliberately left out of PR #56 and is the substance of #57.

Why it is worse than a stale name in a pill: the query orders
``is_primary DESC, parent_id ASC``, and ``mountTagContextPill`` in
``src/web/js/question_entry.js`` takes ``cached[0].parent_id`` as the
**default** parent context. CLAUDE.md's standing rule is that every
multi-parent subject gets a non-NULL ``primary_parent_id`` on save,
defaulting to exactly that first edge. So an archived parent at the head
of the list silently pins a **new** entry to a deleted parent, and per
§5.4 that entry then rolls up through a chain that is in no scope set —
it counts nowhere on every analytics surface while still showing up in
the entry browser.

The fixture shape throughout:

::

        Barch     Ckeep   Ekeep      Barch is archived, and holds the
            \\       |     /          ``is_primary`` edge, so under the
             \\      |    /           old query it led the list and
              \\     |   /            became the pill's default.
                 Dleaf

The end-to-end consequence — the ``primary_parent_id`` the entry form
actually writes — is pinned by
``tests/wimi_test/scenarios/test_tag_context_pill_skips_archived_parent.py``.
A status filter alone could pass the queries below while the pill still
defaulted wrong, so both halves are needed.
"""
from __future__ import annotations

import tempfile
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
def test_user(master_db):
    return master_db.create_user(
        username="edges_status_user",
        display_name="Edges Status Filter User",
        user_types=["student"],
    )


@pytest.fixture
def user_db(master_db, test_user):
    db_path = master_db.ensure_user_database(test_user.id)
    db = UserDatabase(
        db_path=db_path,
        user_id=test_user.id,
        username=test_user.username,
    )
    yield db
    db.close()


# ---------------------------------------------------------------- helpers


def _node(user_db, name: str) -> int:
    """Insert a bare subject_node. No legacy ``parent_id``, no edge."""
    cursor = user_db.execute(
        "INSERT INTO subject_nodes "
        "(exam_context, name, level_type, parent_id, sort_order, status) "
        "VALUES ('USMLE', ?, 'Topic', NULL, 0, 'active')",
        (name,),
    )
    user_db.conn.commit()
    return cursor.lastrowid


def _archive(user_db, node_id: int) -> None:
    """Archive a node *without* going through ``delete_subject_subtree``.

    Deliberately raw. Since #15 a real delete also **removes** the
    archived-parent→surviving-child edge, so the dangling row this issue
    is about can no longer be created by the delete path — it only exists
    on databases that had subject deletes before #15. Flipping ``status``
    by hand is how that legacy state is reconstructed.
    """
    user_db.execute(
        "UPDATE subject_nodes SET status = 'archived' WHERE id = ?",
        (node_id,),
    )
    user_db.conn.commit()


def _archived_parent_leads(user_db):
    """Build the fixture shape; returns (barch, ckeep, ekeep, dleaf).

    ``Barch`` is archived and holds the ``is_primary`` edge, which under
    ``ORDER BY is_primary DESC, parent_id ASC`` puts it at the head of the
    list regardless of the ids SQLite hands out.
    """
    barch = _node(user_db, "Barch")
    ckeep = _node(user_db, "Ckeep")
    ekeep = _node(user_db, "Ekeep")
    dleaf = _node(user_db, "Dleaf")
    user_db.add_edge(barch, dleaf, is_primary=True)
    user_db.add_edge(ckeep, dleaf, is_primary=False)
    user_db.add_edge(ekeep, dleaf, is_primary=False)
    _archive(user_db, barch)
    return barch, ckeep, ekeep, dleaf


# ------------------------------------------------------------------- tests


def test_archived_parent_is_omitted_and_survivor_leads(user_db):
    """#57's acceptance 1: the deleted parent is gone and Ckeep leads.

    Both halves matter. Omitting ``Barch`` is the filter; *who leads the
    remainder* is the behaviour change — the pill's default moves from the
    archived parent to the first surviving one, which is the intended
    correction, not a side effect.
    """
    barch, ckeep, ekeep, dleaf = _archived_parent_leads(user_db)

    edges = user_db.get_edges_for_child(dleaf)

    assert [e['parent_id'] for e in edges] == [ckeep, ekeep]
    assert barch not in {e['parent_id'] for e in edges}
    assert edges[0]['parent_id'] == ckeep
    assert edges[0]['parent_name'] == "Ckeep"


def test_all_parents_archived_returns_an_empty_list(user_db):
    """#57's acceptance 3: no rows, no crash, no half-built edge dicts.

    ``mountTagContextPill`` gates on ``cached.length < 2`` and clears the
    slot, so an empty list is the safe shape. A ``None`` or a raise here
    would surface as a broken entry form.
    """
    barch, ckeep, ekeep, dleaf = _archived_parent_leads(user_db)
    _archive(user_db, ckeep)
    _archive(user_db, ekeep)

    edges = user_db.get_edges_for_child(dleaf)

    assert edges == []


def test_get_edges_for_child_agrees_with_get_parents(user_db):
    """The two methods answer the same question and must not diverge.

    #15 fixed ``get_parents`` and left this one; the point of #57 is that
    the pair now tells one story. They order their tails differently
    (``display_order`` vs ``parent_id``), so only the membership is
    compared.
    """
    _barch, ckeep, ekeep, dleaf = _archived_parent_leads(user_db)

    edge_parents = {e['parent_id'] for e in user_db.get_edges_for_child(dleaf)}
    parent_ids = {p.parent_id for p in user_db.get_parents(dleaf)}

    assert edge_parents == parent_ids == {ckeep, ekeep}


def test_an_all_active_child_is_unaffected(user_db):
    """The filter must not narrow the normal case.

    Every existing consumer — the weight editor, the deep dive's "Show as
    part of" selector, the tag-context pill — reads this method for live
    subjects, and they must see exactly what they saw before.
    """
    parent_a = _node(user_db, "Active A")
    parent_b = _node(user_db, "Active B")
    child = _node(user_db, "Active child")
    user_db.add_edge(parent_a, child, is_primary=True)
    user_db.add_edge(parent_b, child, is_primary=False)

    edges = user_db.get_edges_for_child(child)

    assert [e['parent_id'] for e in edges] == [parent_a, parent_b]
    assert edges[0]['is_primary'] is True


def test_a_subject_with_only_an_archived_parent_reads_as_an_orphan(user_db):
    """A single dangling edge leaves the child parentless, not mis-parented.

    This is the shape a pre-#15 delete of an exclusive parent left behind
    (casualty 1). It is not this issue's job to re-wire it; it is this
    issue's job to stop naming the deleted parent as its context.
    """
    dead_parent = _node(user_db, "Dead parent")
    child = _node(user_db, "Stranded child")
    user_db.add_edge(dead_parent, child, is_primary=True)
    _archive(user_db, dead_parent)

    assert user_db.get_edges_for_child(child) == []
