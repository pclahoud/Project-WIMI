"""Bridge tests for the import merge preview — issue #67.

The slot pair is the contract the modal is written against:
``previewSubjectHierarchyImport`` must be read-only, and its counts must
be the ones ``importSubjectHierarchy`` then produces. Both call the same
planner, so what is asserted here is that the bridge does not undo that —
by trimming the payload differently, by forgetting a field the modal
renders, or by writing something on the preview path.
"""
import json
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from app.bridge import DatabaseBridge
from database.master_db import MasterDatabase
from database.user_db import UserDatabase


# ==================== Fixtures ====================

@pytest.fixture
def temp_db_path() -> Generator[Path, None, None]:
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        yield Path(f.name)
    try:
        Path(f.name).unlink()
    except Exception:
        pass


@pytest.fixture
def temp_master_db_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def user_db(temp_db_path: Path) -> Generator[UserDatabase, None, None]:
    db = UserDatabase(db_path=temp_db_path, user_id=1, username="test_user")
    yield db
    db.close()


@pytest.fixture
def master_db(temp_master_db_dir: Path) -> Generator[MasterDatabase, None, None]:
    db = MasterDatabase(data_dir=temp_master_db_dir, error_logger=None)
    yield db
    db.close()


@pytest.fixture
def bridge(user_db: UserDatabase, master_db: MasterDatabase) -> DatabaseBridge:
    master_db.bootstrap_first_user(username="test_admin", display_name="Test Admin")
    return DatabaseBridge(master_db=master_db, user_db=user_db)


@pytest.fixture
def exam(user_db: UserDatabase):
    created = user_db.create_exam_context(
        exam_name="Preview Exam",
        exam_description="issue #67",
    )
    return user_db.get_exam_context_by_name(created.exam_name)


# ==================== Helpers ====================

def _payload(nodes, **extra) -> str:
    return json.dumps(dict({'root_nodes': nodes}, **extra))


def _preview(bridge, exam_id, nodes, **extra) -> dict:
    response = json.loads(
        bridge.previewSubjectHierarchyImport(exam_id, _payload(nodes, **extra))
    )
    assert response['success'], response
    return response['data']


def _import(bridge, exam_id, nodes, **extra) -> dict:
    response = json.loads(
        bridge.importSubjectHierarchy(exam_id, _payload(nodes, **extra))
    )
    assert response['success'], response
    return response['data']


def _node_count(user_db, exam_name) -> int:
    return user_db.fetchone(
        "SELECT COUNT(*) AS c FROM subject_nodes WHERE exam_context = ?",
        (exam_name,),
    )['c']


# ==================== The preview writes nothing ====================

def test_preview_does_not_touch_the_database(bridge, user_db, exam):
    before = _node_count(user_db, exam.exam_name)

    data = _preview(bridge, exam.id, [
        {'name': 'Root', 'children': [{'name': 'Child'}]}
    ])

    assert data['counts']['added'] == 2  # Root + Child
    assert _node_count(user_db, exam.exam_name) == before, (
        "the preview created rows"
    )


def test_preview_counts_are_the_counts_the_import_produces(bridge, user_db, exam):
    """Acceptance 6, at the slot boundary."""
    _import(bridge, exam.id, [
        {'id': 'r', 'name': 'Root', 'children': [
            {'id': 'a', 'name': 'Stays'},
            {'id': 'b', 'name': 'Renamed'},
            {'id': 'c', 'name': 'Dropped'},
        ]},
    ])

    incoming = [
        {'id': 'r', 'name': 'Root', 'children': [
            {'id': 'a', 'name': 'Stays'},
            {'id': 'b', 'name': 'Renamed Well'},
            {'id': 'd', 'name': 'New'},
        ]},
    ]

    preview = _preview(bridge, exam.id, incoming)
    result = _import(bridge, exam.id, incoming)

    assert preview['counts'] == result['counts']
    assert preview['counts'] == {
        'added': 1, 'updated': 1, 'unchanged': 2, 'renamed': 1, 'moved': 0,
        'removed': 1, 'kept_in_use': 0, 'kept_as_ancestor': 0,
        'entries_affected': 0,
    }


def test_preview_flags_a_file_written_for_another_exam(bridge, exam):
    """Decision 2 in the direction that can still go wrong.

    A file naming an exam that already exists is a re-import of it — and
    the only import path targets the exam already open, so the merge is
    automatic. The case worth saying out loud is the other one: a file
    for a *different* exam being merged into this tree.
    """
    same = _preview(bridge, exam.id, [{'name': 'X'}],
                    exam_context=exam.exam_name)
    assert same['file_exam_matches'] is True

    other = _preview(bridge, exam.id, [{'name': 'X'}],
                     exam_context='Some Other Exam')
    assert other['file_exam_matches'] is False
    assert other['file_exam_name'] == 'Some Other Exam'


def test_preview_reads_the_name_out_of_an_exam_context_object(bridge, exam):
    """Issue #103: the published format spells ``exam_context`` as an object.

    Every file written to the guide — the guide's own worked examples
    included — carries ``{"name": ..., "description": ..., "source": ...}``
    rather than a bare string. Handing that dict on as ``file_exam_name``
    failed the comparison above for *every* such file and rendered in the
    modal as ``[object Object]``, so the one case the note exists to
    catch was indistinguishable from the normal one.
    """
    same = _preview(bridge, exam.id, [{'name': 'X'}], exam_context={
        'name': exam.exam_name,
        'description': 'Written to the guide',
        'source': {'title': 'Content Outline', 'year': 2025},
    })
    assert same['file_exam_name'] == exam.exam_name
    assert same['file_exam_matches'] is True, (
        "a guide-shaped file naming this very exam still claimed to be "
        "written for another one"
    )

    other = _preview(bridge, exam.id, [{'name': 'X'}],
                     exam_context={'name': 'Some Other Exam'})
    assert other['file_exam_name'] == 'Some Other Exam'
    assert other['file_exam_matches'] is False


@pytest.mark.parametrize('exam_context', [
    {},                       # object, no name
    {'name': None},
    {'name': '   '},
    [],                       # not an object at all
    17,
    '',
])
def test_preview_treats_an_unusable_exam_context_as_unstated(
    bridge, exam, exam_context
):
    """Anything that is not a usable name degrades to "the file does not say".

    ``file_exam_name is None`` is the case the payload already treats as
    a match, and the modal renders no note for it — which is the right
    outcome for a file whose ``exam_context`` carries no name: there is
    nothing to warn about and nothing to print.
    """
    data = _preview(bridge, exam.id, [{'name': 'X'}], exam_context=exam_context)
    assert data['file_exam_name'] is None
    assert data['file_exam_matches'] is True


def test_preview_reports_kept_in_use_subjects_with_their_entries(
    bridge, user_db, exam
):
    """Decision 3's "reachable from there": the payload carries the ids.

    The modal turns each of these into a link to the entry browser
    filtered by that subject, which is the cheap version of "the student
    can reassign" the issue asks to start with.
    """
    _import(bridge, exam.id, [
        {'name': 'Root', 'children': [{'name': 'Used'}]}
    ])
    used_id = user_db.fetchone(
        "SELECT id FROM subject_nodes WHERE name = 'Used'"
    )['id']
    session_id = user_db.execute(
        "INSERT INTO review_sessions "
        "(user_id, session_name, date_encountered, exam_context_id, "
        " total_questions, total_incorrect) VALUES (1, 'S', '2026-09-16', ?, 1, 1)",
        (exam.id,),
    ).lastrowid
    entry_id = user_db.execute(
        "INSERT INTO question_entries "
        "(review_session_id, entry_order, user_answer, correct_answer) "
        "VALUES (?, 1, 'A', 'B')",
        (session_id,),
    ).lastrowid
    user_db.execute(
        "INSERT INTO entry_subject_mappings "
        "(question_entry_id, subject_node_id, mapping_type) "
        "VALUES (?, ?, 'primary')",
        (entry_id, used_id),
    )
    user_db.conn.commit()

    data = _preview(bridge, exam.id, [{'name': 'Root'}])

    assert data['counts']['kept_in_use'] == 1
    kept = data['kept_in_use'][0]
    assert kept['id'] == used_id
    assert kept['name'] == 'Used'
    assert kept['entry_count'] == 1
    assert entry_id in kept['entry_ids']
    assert data['entries_affected'] == 1
    assert data['counts']['removed'] == 0


def test_preview_payload_omits_the_execution_script(bridge, exam):
    """The plan carries one record per file node; the modal must not.

    2,211 of them crossing the bridge for a modal that renders four
    numbers is the kind of payload that makes a preview feel broken.
    """
    data = _preview(bridge, exam.id, [
        {'name': f'S{i}'} for i in range(60)
    ])

    assert 'nodes' not in data
    assert data['added_total'] == 60
    assert len(data['added']) == 50, "sample lists are capped"


def test_preview_guards_on_no_user_database(master_db):
    lone = DatabaseBridge(master_db=master_db, user_db=None)
    response = json.loads(lone.previewSubjectHierarchyImport(1, '{}'))
    assert response['success'] is False
    assert 'No user database' in response['error']


def test_preview_rejects_an_unknown_exam(bridge):
    response = json.loads(bridge.previewSubjectHierarchyImport(9999, '{}'))
    assert response['success'] is False
    assert response['error'] == 'Exam context not found'


def test_preview_reads_the_spec_spelling_too(bridge, exam):
    """Issue #61's reconciliation still holds on the new slot."""
    response = json.loads(bridge.previewSubjectHierarchyImport(
        exam.id, json.dumps({'subjects': [{'name': 'From subjects'}]})
    ))
    assert response['success'], response
    assert response['data']['counts']['added'] == 1


def test_import_reports_duplicate_ids_as_a_failure(bridge, user_db, exam):
    """A file defect fails loudly and writes nothing."""
    before = _node_count(user_db, exam.exam_name)
    response = json.loads(bridge.importSubjectHierarchy(exam.id, _payload([
        {'id': 'same', 'name': 'One'},
        {'id': 'same', 'name': 'Two'},
    ])))

    assert response['success'] is False
    assert 'same' in response['error']
    assert _node_count(user_db, exam.exam_name) == before


def test_export_round_trips_the_stable_id(bridge, exam):
    """``getSubjectHierarchy`` has to carry ``import_id`` or the export
    cannot write the file's ``id`` back out, and the next re-import is
    rename-blind again."""
    _import(bridge, exam.id, [{'id': 'topic-1', 'name': 'Root'}])

    data = json.loads(bridge.exportSubjectHierarchy(exam.id))['data']
    assert data['root_nodes'][0]['import_id'] == 'topic-1'
