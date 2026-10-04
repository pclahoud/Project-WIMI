"""Dimension validation reads mechanism A, reports, and never refuses (#209).

`validate_entry_dimensions_complete` used to read `question_hierarchy_tags` --
mechanism B, a complete, wired, **unreachable** feature. No page in
`src/web/` ever called any of its five slots, and nothing ever wrote a row to
the table. So the method answered *"every required dimension is missing"* for
every entry in the application, and the only reason that was survivable is
that it had no callers either.

The owner's decision (2', 2026-09-26) keeps the validation layer and drops the
table's code: the validation re-homes onto **A**, the live path, where an
entry reaches a dimension because the *subject* it is tagged with carries
`dimension_id`.

Three properties, one test each, because each one is the sort of thing a later
change would find reasonable to "fix":

* **Primary-only counting (#13).** A secondary "also tested" tag is not a
  second classification. Counting it would let a shared subject over-tag a
  dimension it was only mentioned in.
* **Report, never refuse (#64 decision 2).** Multi-tagging has been
  unconditionally permitted for the whole life of the feature, so existing
  profiles already hold data a hard rule would make unsaveable.
* **`allow_multiple` finally means something.** It gated nothing before -- the
  flag was stored, settable and displayed, while `create_question_entry` took
  a *list* of subjects and `entries.py` had no dimension awareness at all.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))

from database import MasterDatabase, UserDatabase  # noqa: E402


@pytest.fixture
def user_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        master = MasterDatabase(data_dir=Path(tmpdir))
        user = master.create_user(username='dim_probe', display_name='Probe',
                                  user_types=['student'])
        db = UserDatabase(db_path=master.ensure_user_database(user.id),
                          user_id=user.id, username='dim_probe')
        db._ensure_phase2_schema()
        db._ensure_phase4_schema()
        db._ensure_phase7_schema()
        yield db
        db.close()
        master.close()


@pytest.fixture
def exam(user_db):
    return user_db.create_exam_context(exam_name='Issue 209 Validation')


def _dimension(user_db, exam, name, order, *, required=True, multiple=False):
    return user_db.create_dimension(
        exam_id=exam.id, name=name, display_order=order,
        is_required=required, allow_multiple=multiple,
    )


def _subject(user_db, exam, name, dimension_id):
    return user_db.create_subject_node(
        exam_context=exam.exam_name, name=name,
        level_type='System', dimension_id=dimension_id,
    )


def _entry(user_db, exam, subject_ids):
    session = user_db.create_review_session(
        exam_context_id=exam.id, total_questions=5, total_incorrect=1)
    return user_db.create_question_entry(
        review_session_id=session.id, user_answer='A', correct_answer='B',
        reflection='r', explanation='e', primary_subject_ids=subject_ids,
    )


@pytest.mark.database
def test_a_required_dimension_with_a_subject_is_complete(user_db, exam):
    """The happy path, which the old implementation could never reach.

    Reading `question_hierarchy_tags` meant this returned `is_complete=False`
    for every entry ever created, because nothing wrote to that table.
    """
    site = _dimension(user_db, exam, 'Site', 1)
    entry = _entry(user_db, exam, [_subject(user_db, exam, 'Emergency', site).id])

    result = user_db.validate_entry_dimensions_complete(entry.id, exam.id)

    assert result['is_complete'] is True
    assert result['missing_dimensions'] == []
    assert result['tagged_dimensions'] == [site]


@pytest.mark.database
def test_a_required_dimension_with_no_subject_is_missing(user_db, exam):
    """Negative control. Without it, a method that always reported complete
    would pass the test above."""
    site = _dimension(user_db, exam, 'Site', 1)
    task = _dimension(user_db, exam, 'Task', 2)
    entry = _entry(user_db, exam, [_subject(user_db, exam, 'Emergency', site).id])

    result = user_db.validate_entry_dimensions_complete(entry.id, exam.id)

    assert result['is_complete'] is False
    assert result['missing_dimensions'] == [task]


@pytest.mark.database
def test_an_optional_dimension_is_never_missing(user_db, exam):
    """`is_required` is the only thing that makes a dimension mandatory."""
    _dimension(user_db, exam, 'Site', 1, required=True)
    _dimension(user_db, exam, 'Optional Axis', 2, required=False)
    site = user_db.get_exam_dimensions(exam.id)[0]['id']
    entry = _entry(user_db, exam, [_subject(user_db, exam, 'Emergency', site).id])

    result = user_db.validate_entry_dimensions_complete(entry.id, exam.id)

    assert result['is_complete'] is True


@pytest.mark.database
def test_two_subjects_in_one_dimension_are_reported_not_refused(user_db, exam):
    """The `allow_multiple = False` case: a warning, and the entry still saved.

    This is #64 decision 2 applied to dimensions -- a checkable thing that
    real data can already violate is a warning, never a hard failure. The
    entry is created before the check and is unaffected by it.
    """
    site = _dimension(user_db, exam, 'Site', 1, multiple=False)
    entry = _entry(user_db, exam, [
        _subject(user_db, exam, 'Emergency', site).id,
        _subject(user_db, exam, 'Inpatient', site).id,
    ])

    result = user_db.validate_entry_dimensions_complete(entry.id, exam.id)

    assert result['is_complete'] is True, 'over-tagging must not make it incomplete'
    assert len(result['over_tagged_dimensions']) == 1
    reported = result['over_tagged_dimensions'][0]
    assert reported['dimension_id'] == site
    assert reported['dimension_name'] == 'Site'
    assert reported['count'] == 2


@pytest.mark.database
def test_allow_multiple_suppresses_the_over_tag_report(user_db, exam):
    """The flag finally gates something.

    Before #209 `allow_multiple` was stored, settable and displayed while
    reading nothing -- `create_hierarchy_tag` inserted unconditionally and
    this method checked `is_required` only. If this test passes with the flag
    ignored, the flag is inert again.
    """
    site = _dimension(user_db, exam, 'Site', 1, multiple=True)
    entry = _entry(user_db, exam, [
        _subject(user_db, exam, 'Emergency', site).id,
        _subject(user_db, exam, 'Inpatient', site).id,
    ])

    result = user_db.validate_entry_dimensions_complete(entry.id, exam.id)

    assert result['over_tagged_dimensions'] == []


@pytest.mark.database
def test_a_secondary_mapping_neither_completes_nor_over_tags(user_db, exam):
    """Counting is primary-only (#13).

    A secondary "also tested" tag is not a second classification. If secondary
    mappings counted, a shared subject would over-tag a dimension it was only
    mentioned in -- and would also satisfy a required dimension the student
    never actually classified the entry under.
    """
    site = _dimension(user_db, exam, 'Site', 1, multiple=False)
    task = _dimension(user_db, exam, 'Task', 2, multiple=False)

    emergency = _subject(user_db, exam, 'Emergency', site)
    inpatient = _subject(user_db, exam, 'Inpatient', site)
    diagnosis = _subject(user_db, exam, 'Diagnosis', task)

    entry = _entry(user_db, exam, [emergency.id])
    with user_db.transaction():
        for node_id in (inpatient.id, diagnosis.id):
            user_db.execute(
                "INSERT INTO entry_subject_mappings "
                "(question_entry_id, subject_node_id, mapping_type) "
                "VALUES (?, ?, 'secondary')",
                (entry.id, node_id))

    result = user_db.validate_entry_dimensions_complete(entry.id, exam.id)

    assert result['over_tagged_dimensions'] == [], (
        'a secondary mapping counted towards over-tagging'
    )
    assert result['missing_dimensions'] == [task], (
        'a secondary mapping satisfied a required dimension'
    )


@pytest.mark.database
def test_a_dimensionless_subject_is_ignored(user_db, exam):
    """`dimension_id IS NULL` is the part-converted exam's leftovers.

    Those subjects belong to no axis, so they cannot complete one. `IS NULL`
    never equals a dimension id, but the count would still pick them up under
    a `GROUP BY` without the predicate -- as a NULL key.
    """
    site = _dimension(user_db, exam, 'Site', 1)
    legacy = user_db.create_subject_node(
        exam_context=exam.exam_name, name='Legacy', level_type='System')
    entry = _entry(user_db, exam, [legacy.id])

    result = user_db.validate_entry_dimensions_complete(entry.id, exam.id)

    assert result['tagged_dimensions'] == []
    assert result['missing_dimensions'] == [site]


@pytest.mark.database
def test_an_archived_subject_does_not_satisfy_a_dimension(user_db, exam):
    """Archived is not tagged.

    A subject archived by #15's soft delete keeps its `entry_subject_mappings`
    rows -- that is deliberate, so a restore can replay them. Without the
    `status = 'active'` predicate an entry would stay "complete" on the
    strength of a subject the student deleted.
    """
    site = _dimension(user_db, exam, 'Site', 1)
    emergency = _subject(user_db, exam, 'Emergency', site)
    entry = _entry(user_db, exam, [emergency.id])
    assert user_db.validate_entry_dimensions_complete(
        entry.id, exam.id)['is_complete'] is True

    user_db.delete_subject_subtree(emergency.id)

    result = user_db.validate_entry_dimensions_complete(entry.id, exam.id)
    assert result['is_complete'] is False
    assert result['missing_dimensions'] == [site]


@pytest.mark.database
def test_mechanism_b_is_gone_from_the_database_layer():
    """Enforced by absence.

    B was a complete, wired, unreachable feature -- table, five database
    methods, a bridge mixin composed into `DatabaseBridge`, and JS wrappers.
    Its shape made it look alive. The **table stays** (dropping it needs a
    migration for no functional gain, and it is provably empty), but nothing
    may read or write it from the dimensions domain again.
    """
    import inspect

    import database.domains.dimensions as module

    source = inspect.getsource(module)
    gone = ['create_hierarchy_tag', 'get_entry_tags', 'delete_hierarchy_tag',
            'delete_entry_tags_by_dimension', 'get_tags_by_dimension']
    still_defined = [name for name in gone if f'def {name}' in source]
    assert still_defined == [], f'mechanism B is back: {still_defined}'

    executable = '\n'.join(
        line for line in source.splitlines() if not line.strip().startswith('#'))
    # The remaining mentions are prose -- a docstring explaining what was
    # removed and why. A query is not.
    assert 'FROM question_hierarchy_tags' not in executable
    assert 'INTO question_hierarchy_tags' not in executable


def test_the_bridge_no_longer_exposes_mechanism_b():
    """The five slots are gone from the composed bridge.

    A mixin can be deleted from the package and left composed, or removed
    from the import list and left on disk. This asks the assembled class,
    which is what QWebChannel publishes.
    """
    from app.bridge import DatabaseBridge

    for slot in ('createHierarchyTag', 'getEntryHierarchyTags',
                 'deleteHierarchyTag', 'deleteEntryTagsByDimension',
                 'validateEntryDimensions'):
        assert not hasattr(DatabaseBridge, slot), (
            f'{slot} is still published to JavaScript'
        )
