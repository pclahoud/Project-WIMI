"""``get_subject_deep_dive`` reports which axis a subject is on (#314).

The owner's decision, 2026-10-10. On a multi-dimensional exam the deep
dive's heading was the bare subject name -- **"18 to 65"** -- and
"Full path: 18 to 65" repeated it rather than disambiguating, because a
dimension root has nothing above it. Nothing on the page said this was a
**Patient Age** group rather than a topic or a Site of Care value.

The page cannot say it until the payload carries it, which is this file.

Three things are pinned, and the second is the one a later change is most
likely to break:

1. a subject in an axis reports that axis's id and name;
2. a subject in NO axis has **neither key present** -- absent, not null.
   That is this payload's existing convention (``path_omitted_ancestors``
   under #301) and it lets the page treat absence as "no axis" without
   comparing against ``None``. A null would render as the word "in"
   followed by nothing;
3. an **archived** axis reports nothing either, because the JOIN filters
   ``status = 'active'``. Every read of ``exam_dimensions`` filters on
   status and partial adoption is worse than none
   (``test_dimension_soft_delete.py`` sweeps for exactly this).

Test 3 is cover rather than a live path -- #210's cascade archives a
dimension's subjects with it, so an active subject in an archived axis
should not exist. It is asserted anyway because the cost is one predicate
and the symptom would be the word "in" beside a blank.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from database import MasterDatabase, UserDatabase


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
        username="axis_user",
        display_name="Axis User",
        user_types=["student"],
    )
    db = UserDatabase(
        db_path=master_db.ensure_user_database(user.id),
        user_id=user.id,
        username=user.username,
    )
    yield db
    db.close()


def _exam(user_db):
    return user_db.create_exam_context(
        exam_name="Axis Exam",
        exam_description="#314 - which axis is this subject on",
    )


def _subject_in(user_db, exam, name, dimension_id=None):
    cursor = user_db.execute(
        "INSERT INTO subject_nodes "
        "(exam_context, name, level_type, dimension_id, sort_order, status) "
        "VALUES (?, ?, 'System', ?, 0, 'active')",
        (exam.exam_name, name, dimension_id),
    )
    user_db.conn.commit()
    return cursor.lastrowid


def test_a_subject_in_an_axis_reports_that_axis(user_db):
    exam = _exam(user_db)
    axis = user_db.create_dimension(
        exam_id=exam.id, name="Patient Age", display_order=1)
    subject_id = _subject_in(user_db, exam, "18 to 65", dimension_id=axis)

    dive = user_db.get_subject_deep_dive(subject_id, exam_context_id=exam.id)

    assert dive is not None, "the deep dive returned nothing for a real subject"
    assert dive["dimension_name"] == "Patient Age", (
        "the payload must name the axis, or the page cannot: the heading is "
        f"just {dive['subject_name']!r}, which identifies nothing. Got "
        f"{dive.get('dimension_name')!r}")
    assert dive["dimension_id"] == axis


def test_a_subject_in_no_axis_reports_no_keys_at_all(user_db):
    """Absent, never null -- a null renders as "in" followed by nothing."""
    exam = _exam(user_db)
    subject_id = _subject_in(user_db, exam, "Cardiovascular System")

    dive = user_db.get_subject_deep_dive(subject_id, exam_context_id=exam.id)

    assert dive is not None
    assert "dimension_name" not in dive, (
        "a subject on an exam with no dimensions is in no axis, and the key "
        f"must be ABSENT rather than null: got {dive.get('dimension_name')!r}")
    assert "dimension_id" not in dive


def test_an_archived_axis_is_not_named(user_db):
    """The JOIN filters status='active', so an archived axis reports nothing.

    Cover rather than a live path: #210's cascade archives a dimension's
    subjects with it, so an active subject in an archived axis should not
    be reachable. Asserted because the symptom would be silent -- the word
    "in" beside a blank -- and because every read of ``exam_dimensions``
    is supposed to filter on status.
    """
    exam = _exam(user_db)
    axis = user_db.create_dimension(
        exam_id=exam.id, name="Retired Axis", display_order=1)
    subject_id = _subject_in(user_db, exam, "Orphan", dimension_id=axis)

    # Archive the DIMENSION ROW only, leaving the subject active -- the
    # state the cascade exists to prevent, reached directly so the status
    # predicate is what is under test rather than the cascade.
    user_db.execute(
        "UPDATE exam_dimensions SET status = 'archived' WHERE id = ?",
        (axis,),
    )
    user_db.conn.commit()

    dive = user_db.get_subject_deep_dive(subject_id, exam_context_id=exam.id)

    assert dive is not None
    assert "dimension_name" not in dive, (
        "an archived axis must not be named: the subject still carries its "
        f"dimension_id, so an unfiltered JOIN yields a null name. Got "
        f"{dive.get('dimension_name')!r}")
