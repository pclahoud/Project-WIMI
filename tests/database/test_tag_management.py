"""Tests for Error Type Management domain work (TagsMixin).

Covers the Step 2 additions from the Error Type Management plan:

- ``delete_tag`` — hard delete with cascade through BOTH junction
  tables (``entry_tags`` and legacy ``question_tags``), guarded for
  missing ids and non-empty groups, returning ``affected_entries``
- ``update_tag_description`` — set / update / clear-to-NULL
- ``get_tag_usage_count`` + the ``get_tag_hierarchy`` live-count fix
  (correlated COUNT over ``entry_tags``; the stale ``tags.usage_count``
  column must be ignored)
- ``seed_default_tags`` definitions — every seeded group and type
  carries a non-NULL description, and the frozen definition map matches
  the m010 migration's copy exactly
"""
import pytest
from datetime import date

from database.user_db import UserDatabase
from database.exceptions import TagError
from database.domains.tags import _DEFAULT_TAG_DEFINITIONS
from database.migrations.user.m010_default_tag_definitions import DEFAULT_DEFINITIONS

pytestmark = pytest.mark.database

EXAM = "Tag Test Exam"


@pytest.fixture
def db(tmp_path):
    """UserDatabase with an exam context, one subject, and a session."""
    db_path = tmp_path / "test_user.db"
    db = UserDatabase(str(db_path), user_id=1, username="testuser")

    exam = db.create_exam_context(
        exam_name=EXAM,
        exam_description="For tag management testing",
        hierarchy_levels=["System", "Topic"]
    )
    subj = db.create_subject_node(
        exam_context=EXAM,
        name="Cardiology",
        level_type="System"
    )
    source = db.create_question_source(
        source_name="Test Source",
        source_type="textbook"
    )
    session = db.create_review_session(
        exam_context_id=exam.id,
        session_name="Test Session",
        date_encountered=date.today(),
        total_questions=10,
        total_incorrect=5,
        question_source_id=source.id
    )

    yield {
        'db': db,
        'exam': exam,
        'subj': subj,
        'session': session,
    }

    db.close()


def _make_group_and_tag(db, group_name="Group A", tag_name="Type A"):
    group = db.create_tag_group(exam_context=EXAM, group_name=group_name)
    tag = db.create_hierarchical_tag(
        exam_context=EXAM, tag_name=tag_name, group_id=group.id
    )
    return group, tag


def _make_entry(db, session, subj, tag_ids=None):
    return db.create_question_entry(
        review_session_id=session.id,
        user_answer="A",
        correct_answer="B",
        primary_subject_ids=[subj.id],
        tag_ids=tag_ids or []
    )


def _find_node(nodes, tag_id):
    """Depth-first search for a tag id in a get_tag_hierarchy payload."""
    for node in nodes:
        if node['id'] == tag_id:
            return node
        found = _find_node(node['children'], tag_id)
        if found:
            return found
    return None


# ==================================================================
# delete_tag
# ==================================================================

class TestDeleteTag:

    def test_delete_cascades_entry_tags(self, db):
        """Deleting a tag removes its entry_tags rows (assert rows, not schema)."""
        udb = db['db']
        _, tag = _make_group_and_tag(udb)
        e1 = _make_entry(udb, db['session'], db['subj'], tag_ids=[tag.id])
        e2 = _make_entry(udb, db['session'], db['subj'], tag_ids=[tag.id])

        rows = udb.fetchall(
            "SELECT * FROM entry_tags WHERE tag_id = ?", (tag.id,)
        )
        assert len(rows) == 2

        udb.delete_tag(tag.id)

        rows = udb.fetchall(
            "SELECT * FROM entry_tags WHERE tag_id = ?", (tag.id,)
        )
        assert rows == []
        # The entries themselves survive.
        assert udb.get_question_entry(e1.id) is not None
        assert udb.get_question_entry(e2.id) is not None

    def test_delete_cascades_legacy_question_tags(self, db):
        """Deleting a tag removes legacy question_tags rows too."""
        udb = db['db']
        _, tag = _make_group_and_tag(udb)

        qa = udb.create_question_analysis(
            exam_context=EXAM,
            question_source="Test Source",
            question_source_id="Q-001",
            answered_incorrectly_date=date.today()
        )
        udb.tag_question(qa.id, [tag.id])

        rows = udb.fetchall(
            "SELECT * FROM question_tags WHERE tag_id = ?", (tag.id,)
        )
        assert len(rows) == 1

        udb.delete_tag(tag.id)

        rows = udb.fetchall(
            "SELECT * FROM question_tags WHERE tag_id = ?", (tag.id,)
        )
        assert rows == []
        # The tag row itself is hard-deleted, not soft-deactivated.
        raw = udb.fetchone("SELECT * FROM tags WHERE id = ?", (tag.id,))
        assert raw is None

    def test_delete_reports_affected_entries(self, db):
        udb = db['db']
        _, tag = _make_group_and_tag(udb)
        for _ in range(3):
            _make_entry(udb, db['session'], db['subj'], tag_ids=[tag.id])

        result = udb.delete_tag(tag.id)

        assert result == {
            'id': tag.id,
            'name': 'Type A',
            'affected_entries': 3
        }

    def test_delete_unused_tag_reports_zero_affected(self, db):
        udb = db['db']
        _, tag = _make_group_and_tag(udb)

        result = udb.delete_tag(tag.id)

        assert result['affected_entries'] == 0

    def test_delete_nonempty_group_raises(self, db):
        udb = db['db']
        group = udb.create_tag_group(exam_context=EXAM, group_name="Busy Group")
        udb.create_hierarchical_tag(
            exam_context=EXAM, tag_name="T1", group_id=group.id
        )
        udb.create_hierarchical_tag(
            exam_context=EXAM, tag_name="T2", group_id=group.id
        )

        with pytest.raises(TagError) as exc_info:
            udb.delete_tag(group.id)
        assert "Group 'Busy Group' contains 2 types" in str(exc_info.value)
        assert "delete or move them first" in str(exc_info.value)

        # Group survives the refused delete.
        assert udb.get_tag(group.id) is not None

    def test_delete_empty_group_succeeds(self, db):
        udb = db['db']
        group = udb.create_tag_group(exam_context=EXAM, group_name="Empty Group")

        result = udb.delete_tag(group.id)

        assert result['name'] == "Empty Group"
        assert udb.fetchone("SELECT * FROM tags WHERE id = ?", (group.id,)) is None

    def test_delete_group_after_children_deleted(self, db):
        """A group becomes deletable once its types are removed."""
        udb = db['db']
        group, tag = _make_group_and_tag(udb, "Drainable", "Only Child")
        udb.delete_tag(tag.id)

        result = udb.delete_tag(group.id)
        assert result['name'] == "Drainable"

    def test_delete_missing_tag_raises(self, db):
        with pytest.raises(TagError, match="not found"):
            db['db'].delete_tag(999999)

    def test_delete_frees_name_for_recreation(self, db):
        """Hard delete frees the UNIQUE(exam_context, tag_name) slot."""
        udb = db['db']
        group, tag = _make_group_and_tag(udb)
        udb.delete_tag(tag.id)

        recreated = udb.create_hierarchical_tag(
            exam_context=EXAM, tag_name="Type A", group_id=group.id
        )
        assert recreated.tag_name == "Type A"
        assert recreated.id != tag.id


# ==================================================================
# update_tag_description
# ==================================================================

class TestUpdateTagDescription:

    def test_set_description(self, db):
        udb = db['db']
        _, tag = _make_group_and_tag(udb)
        assert tag.description is None

        updated = udb.update_tag_description(tag.id, "A first definition.")
        assert updated.description == "A first definition."

    def test_update_existing_description(self, db):
        udb = db['db']
        _, tag = _make_group_and_tag(udb)
        udb.update_tag_description(tag.id, "First.")

        updated = udb.update_tag_description(tag.id, "Second, better.")
        assert updated.description == "Second, better."
        # Persisted, not just returned.
        assert udb.get_tag(tag.id).description == "Second, better."

    def test_empty_string_clears_to_null(self, db):
        udb = db['db']
        _, tag = _make_group_and_tag(udb)
        udb.update_tag_description(tag.id, "Something.")

        updated = udb.update_tag_description(tag.id, "")
        assert updated.description is None
        raw = udb.fetchone("SELECT description FROM tags WHERE id = ?", (tag.id,))
        assert raw['description'] is None

    def test_whitespace_only_clears_to_null(self, db):
        udb = db['db']
        _, tag = _make_group_and_tag(udb)
        udb.update_tag_description(tag.id, "Something.")

        updated = udb.update_tag_description(tag.id, "   \n\t  ")
        assert updated.description is None

    def test_none_clears_to_null(self, db):
        udb = db['db']
        _, tag = _make_group_and_tag(udb)
        udb.update_tag_description(tag.id, "Something.")

        updated = udb.update_tag_description(tag.id, None)
        assert updated.description is None

    def test_description_is_stripped(self, db):
        udb = db['db']
        _, tag = _make_group_and_tag(udb)

        updated = udb.update_tag_description(tag.id, "  padded text  ")
        assert updated.description == "padded text"

    def test_missing_tag_raises(self, db):
        with pytest.raises(TagError, match="not found"):
            db['db'].update_tag_description(999999, "text")

    def test_group_description_updatable(self, db):
        udb = db['db']
        group = udb.create_tag_group(exam_context=EXAM, group_name="Some Group")

        updated = udb.update_tag_description(group.id, "Group definition.")
        assert updated.description == "Group definition."


# ==================================================================
# Live usage counts (get_tag_usage_count + get_tag_hierarchy fix)
# ==================================================================

class TestLiveUsageCounts:

    def test_usage_count_counts_entry_tags(self, db):
        udb = db['db']
        _, tag = _make_group_and_tag(udb)
        assert udb.get_tag_usage_count(tag.id) == 0

        _make_entry(udb, db['session'], db['subj'], tag_ids=[tag.id])
        _make_entry(udb, db['session'], db['subj'], tag_ids=[tag.id])

        assert udb.get_tag_usage_count(tag.id) == 2

    def test_hierarchy_reports_live_counts_not_stale_column(self, db):
        """entry_tags rows inserted directly, tags.usage_count left at 0 —
        the hierarchy must report the live number anyway."""
        udb = db['db']
        _, tag = _make_group_and_tag(udb)
        e1 = _make_entry(udb, db['session'], db['subj'])
        e2 = _make_entry(udb, db['session'], db['subj'])
        e3 = _make_entry(udb, db['session'], db['subj'])

        with udb.transaction():
            for entry in (e1, e2, e3):
                udb.execute(
                    "INSERT INTO entry_tags (question_entry_id, tag_id) VALUES (?, ?)",
                    (entry.id, tag.id)
                )

        # Precondition: the legacy column really is stale.
        raw = udb.fetchone("SELECT usage_count FROM tags WHERE id = ?", (tag.id,))
        assert raw['usage_count'] == 0

        hierarchy = udb.get_tag_hierarchy(EXAM)
        node = _find_node(hierarchy, tag.id)
        assert node is not None
        assert node['usage_count'] == 3

    def test_group_usage_count_sums_children(self, db):
        udb = db['db']
        group = udb.create_tag_group(exam_context=EXAM, group_name="Summed Group")
        t1 = udb.create_hierarchical_tag(
            exam_context=EXAM, tag_name="Child 1", group_id=group.id
        )
        t2 = udb.create_hierarchical_tag(
            exam_context=EXAM, tag_name="Child 2", group_id=group.id
        )

        _make_entry(udb, db['session'], db['subj'], tag_ids=[t1.id])
        _make_entry(udb, db['session'], db['subj'], tag_ids=[t1.id])
        _make_entry(udb, db['session'], db['subj'], tag_ids=[t2.id])

        hierarchy = udb.get_tag_hierarchy(EXAM)
        group_node = _find_node(hierarchy, group.id)
        assert group_node is not None
        assert group_node['usage_count'] == 3
        assert _find_node(hierarchy, t1.id)['usage_count'] == 2
        assert _find_node(hierarchy, t2.id)['usage_count'] == 1

    def test_hierarchy_counts_drop_after_delete(self, db):
        udb = db['db']
        group = udb.create_tag_group(exam_context=EXAM, group_name="Shrinking")
        t1 = udb.create_hierarchical_tag(
            exam_context=EXAM, tag_name="Kept", group_id=group.id
        )
        t2 = udb.create_hierarchical_tag(
            exam_context=EXAM, tag_name="Doomed", group_id=group.id
        )
        _make_entry(udb, db['session'], db['subj'], tag_ids=[t1.id, t2.id])

        udb.delete_tag(t2.id)

        hierarchy = udb.get_tag_hierarchy(EXAM)
        assert _find_node(hierarchy, t2.id) is None
        assert _find_node(hierarchy, group.id)['usage_count'] == 1


# ==================================================================
# Seeded default definitions
# ==================================================================

class TestSeededDefinitions:

    def test_definition_maps_identical(self):
        """The domain copy and the m010 migration copy are frozen mirrors."""
        assert _DEFAULT_TAG_DEFINITIONS == DEFAULT_DEFINITIONS

    def test_all_seeded_tags_have_descriptions(self, db):
        udb = db['db']
        context = "Fresh Seed Exam"
        udb.seed_default_tags(context)

        rows = udb.fetchall(
            "SELECT tag_name, description, is_group FROM tags WHERE exam_context = ?",
            (context,)
        )
        assert len(rows) == len(DEFAULT_DEFINITIONS)  # 5 groups + 16 types
        for row in rows:
            assert row['description'] is not None, \
                f"Seeded tag {row['tag_name']!r} has no description"
            assert row['description'] == DEFAULT_DEFINITIONS[row['tag_name']]

    def test_seeded_hierarchy_exposes_descriptions(self, db):
        udb = db['db']
        context = "Fresh Seed Exam 2"
        udb.seed_default_tags(context)

        def walk(nodes):
            for node in nodes:
                yield node
                yield from walk(node['children'])

        hierarchy = udb.get_tag_hierarchy(context)
        seen = list(walk(hierarchy))
        assert len(seen) == len(DEFAULT_DEFINITIONS)
        for node in seen:
            assert node['description'] == DEFAULT_DEFINITIONS[node['name']]

    def test_seeded_defaults_are_deletable(self, db):
        """Defaults behave like user tags — deletable once selected."""
        udb = db['db']
        context = "Fresh Seed Exam 3"
        udb.seed_default_tags(context)

        row = udb.fetchone(
            "SELECT id FROM tags WHERE exam_context = ? AND tag_name = ?",
            (context, 'Knowledge Gap')
        )
        result = udb.delete_tag(row['id'])
        assert result['name'] == 'Knowledge Gap'
        assert result['affected_entries'] == 0
