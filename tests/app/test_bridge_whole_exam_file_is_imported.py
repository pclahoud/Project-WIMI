"""A whole-exam file imports through both bridge slots (#241, #66 Wave 3).

**This file is #240's guard, inverted.** It was written to assert that a
whole-exam file is *refused*, because refusing was better than what it did
before: `_read_import_request` looked only at `root_nodes`/`subjects`, so a file
carrying a top-level `dimensions` list reached the planner as an **empty node
list** -- and "this file lists no subjects" is exactly the input #67 guarantees
will remove nothing. The import therefore did nothing and reported
`0 added, 0 updated, 0 removed`, which reads like success. A file carrying
*both* keys was worse: `root_nodes` won in the reader, so a multi-axis
blueprint imported as one tree with its other axes dropped, and the student was
told it worked.

#241 lands the planner, so every one of those files now imports. The tests kept
their shape on purpose -- the same fixtures, the same three files -- because
what they assert is the behaviour at the same inputs, and reading them beside
the git history shows exactly what changed.

The dispatch itself is still keyed on the **list type**, not the key's
presence: `dimensions: 3` is a malformed file rather than a whole-exam file and
belongs to the ordinary validation path. That test is unchanged from #240 and
is the one that fails if the dispatch is loosened.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from app.bridge import DatabaseBridge
from database.master_db import MasterDatabase
from database.user_db import UserDatabase


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
    db = UserDatabase(db_path=temp_db_path, user_id=1, username='whole_exam')
    yield db
    db.close()


@pytest.fixture
def master_db(temp_master_db_dir: Path) -> Generator[MasterDatabase, None, None]:
    db = MasterDatabase(data_dir=temp_master_db_dir, error_logger=None)
    yield db
    db.close()


@pytest.fixture
def bridge(user_db, master_db) -> DatabaseBridge:
    master_db.bootstrap_first_user(username='admin', display_name='Admin')
    return DatabaseBridge(master_db=master_db, user_db=user_db)


@pytest.fixture
def exam(user_db):
    user_db.create_exam_context(exam_name='Whole Exam', exam_description='#241')
    return user_db.get_exam_context_by_name('Whole Exam')


def _whole_exam_file(*, also_root_nodes=False):
    file = {
        'exam_context': {'name': 'Whole Exam'},
        'dimensions': [
            {'id': 'axis-system', 'name': 'System', 'display_order': 1,
             'root_nodes': [{'name': 'Cardiovascular'}]},
            {'id': 'axis-task', 'name': 'Task', 'display_order': 2,
             'root_nodes': [{'name': 'Diagnosis'}]},
        ],
    }
    if also_root_nodes:
        file['root_nodes'] = [{'name': 'Stray Top Level'}]
    return json.dumps(file)


def _active(user_db, exam_name):
    return {
        row['name'] for row in user_db.fetchall(
            "SELECT name FROM subject_nodes "
            "WHERE exam_context = ? AND status = 'active'", (exam_name,))
    }


def _axes(user_db, exam):
    return [d['name'] for d in user_db.get_exam_dimensions(exam.id)]


@pytest.mark.parametrize('slot', ['previewSubjectHierarchyImport',
                                  'importSubjectHierarchy'])
def test_a_whole_exam_file_is_accepted_by_both_slots(bridge, exam, slot):
    """Preview and import alike, and both report per axis.

    They have to agree: the preview is what the student acts on, and #67's
    guarantee is that one planner serves both.
    """
    response = json.loads(getattr(bridge, slot)(exam.id, _whole_exam_file()))

    assert response['success'] is True, response.get('error')
    data = response['data']
    assert data['whole_exam'] is True
    assert data['axis_count'] == 2
    assert [axis['name'] for axis in data['axes']] == ['System', 'Task']
    assert data['counts']['dimensions_added'] == 2


def test_it_imports_rather_than_reporting_zero_subjects(bridge, exam, user_db):
    """The old behaviour, stated as the thing that must not happen.

    Before #240 this returned `success=True` with every count at zero --
    indistinguishable from a no-op re-import of an unchanged file. #240 made
    it an explicit refusal; #241 makes it work.
    """
    response = json.loads(
        bridge.importSubjectHierarchy(exam.id, _whole_exam_file()))

    assert response['success'] is True, response.get('error')
    assert response['data']['counts']['added'] == 2, (
        'the file declared two subjects across two axes and none were added'
    )
    assert _axes(user_db, exam) == ['System', 'Task']
    assert _active(user_db, exam.exam_name) == {'Cardiovascular', 'Diagnosis'}


def test_a_file_carrying_both_keys_imports_its_axes(bridge, exam, user_db):
    """The case #240 cared most about: `root_nodes` wins in the reader.

    Without the dispatch this imported the stray top-level tree, dropped both
    axes, and reported success -- a whole-exam blueprint silently flattened.
    The axes are what the file is about, so they are what gets imported; the
    stray key is not a third axis and must not become one.
    """
    response = json.loads(bridge.importSubjectHierarchy(
        exam.id, _whole_exam_file(also_root_nodes=True)))

    assert response['success'] is True, response.get('error')
    assert _axes(user_db, exam) == ['System', 'Task']
    assert 'Stray Top Level' not in _active(user_db, exam.exam_name), (
        'the top-level tree was imported as though it were an axis'
    )
    assert _active(user_db, exam.exam_name) == {'Cardiovascular', 'Diagnosis'}


def test_an_ordinary_single_tree_file_still_imports(bridge, exam, user_db):
    """Negative control, and still the one that matters.

    Every file written today has no `dimensions` key at all, so a dispatch
    that fired more widely would break every existing import.
    """
    ordinary = json.dumps({
        'exam_context': {'name': 'Whole Exam'},
        'root_nodes': [{'name': 'Cardiovascular',
                        'children': [{'name': 'Heart Failure'}]}],
    })

    response = json.loads(bridge.importSubjectHierarchy(exam.id, ordinary))

    assert response['success'] is True, response.get('error')
    assert response['data'].get('whole_exam') is not True, (
        'a single-tree file was routed to the whole-exam planner'
    )
    assert 'Cardiovascular' in _active(user_db, exam.exam_name)
    assert _axes(user_db, exam) == []


def test_a_dimensions_key_that_is_not_a_list_takes_the_ordinary_path(
        bridge, exam, user_db):
    """`dimensions: 3` is a malformed file, not a whole-exam file.

    Unchanged from #240. Keyed on the type rather than the key's presence, so
    a file that happens to carry an unrelated scalar named `dimensions` is
    handled by the ordinary path and reported by the ordinary validation.
    """
    odd = json.dumps({
        'exam_context': {'name': 'Whole Exam'},
        'dimensions': 3,
        'root_nodes': [{'name': 'Cardiovascular'}],
    })

    response = json.loads(bridge.importSubjectHierarchy(exam.id, odd))

    assert response['success'] is True, response.get('error')
    assert response['data'].get('whole_exam') is not True
    assert 'Cardiovascular' in _active(user_db, exam.exam_name)


def test_an_empty_dimensions_list_removes_nothing(bridge, exam, user_db):
    """A misspelled `dimensions` key arrives as an empty list (#67, one level up).

    It reaches the whole-exam planner -- the key is a list -- and must remove
    no axis. Under #210 a mistaken axis removal archives whole trees, so this
    is the most expensive way to get the empty-file rule wrong.
    """
    dimension_id = user_db.create_dimension(
        exam_id=exam.id, name='System', display_order=1)
    user_db.create_subject_node(exam_context=exam.exam_name, name='Kept',
                               level_type='System', dimension_id=dimension_id)

    response = json.loads(bridge.importSubjectHierarchy(
        exam.id, json.dumps({'dimensions': []})))

    assert response['success'] is True, response.get('error')
    assert response['data']['declares_no_dimensions'] is True
    assert _axes(user_db, exam) == ['System']
    assert _active(user_db, exam.exam_name) == {'Kept'}


def test_the_preview_carries_coverage_per_axis_and_no_combined_figure(
        bridge, exam):
    """#241 acceptance, asserted at the payload rather than only at the plan.

    The modal is what the student reads, so the absence has to hold where the
    modal looks. A combined figure would be the rescaling #64 forbids: the
    axes are overlapping partitions of one item pool.
    """
    file = json.dumps({
        'dimensions': [
            {'name': 'System', 'display_order': 1,
             'root_nodes': [{'name': 'A', 'weight': 60}]},
            {'name': 'Task', 'display_order': 2,
             'root_nodes': [{'name': 'B', 'weight': 70}]},
        ],
    })

    data = json.loads(
        bridge.previewSubjectHierarchyImport(exam.id, file))['data']

    assert [axis['coverage']['low'] for axis in data['axes']] == [60.0, 70.0]
    assert 'coverage' not in data, (
        'the whole-exam preview payload grew a combined coverage figure'
    )


def test_a_file_error_is_reported_without_importing_anything(bridge, exam, user_db):
    """Two axes sharing a name is a file the schema cannot hold.

    Reported as a sentence from the planner rather than surfacing as an
    IntegrityError from three frames down, and the import must not half-apply
    on the way to finding out.
    """
    file = json.dumps({
        'dimensions': [
            {'name': 'System', 'display_order': 1, 'root_nodes': [{'name': 'A'}]},
            {'name': 'system', 'display_order': 2, 'root_nodes': [{'name': 'B'}]},
        ],
    })

    response = json.loads(bridge.importSubjectHierarchy(exam.id, file))

    assert response['success'] is False
    assert 'same name' in response['error']
    assert _axes(user_db, exam) == []
    assert _active(user_db, exam.exam_name) == set()
