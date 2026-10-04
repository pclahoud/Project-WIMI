"""The Archived panel's three slots (#37 Wave 3).

Bridge tests construct ``DatabaseBridge`` directly and call slots as plain
methods, per the convention in CLAUDE.md -- no ``QApplication`` needed.

Two contracts carry the weight here, and both are about *how a refusal
arrives* rather than about the restore itself (that is covered by
`tests/database/test_subject_restore_core.py` and
`test_dimension_restore.py`):

* **A refused restore is `success=false` with the planner's sentence.**
  #240's lesson: a call reporting `0 restored` alongside `success` is
  indistinguishable from one that worked, and here the difference is a
  student's subject tree. `SubjectRestoreError` is caught and passed
  through; anything else is a defect and reports generically.
* **`kind` is passed, not inferred.** A batch id identifies either a
  subject delete or a dimension archive. The panel knows which, so the
  slot takes the label rather than probing both tables -- and an unknown
  label is a sentence rather than a silent fall-through to the subject
  path, which would answer "subject" for a dimension-owned batch and
  produce exactly the refusal hazard 4 exists for.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile

import pytest

ROOT = pathlib.Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / 'src'))

from app.bridge import DatabaseBridge  # noqa: E402
from database import MasterDatabase, UserDatabase  # noqa: E402


@pytest.fixture
def bridge():
    with tempfile.TemporaryDirectory() as tmpdir:
        master = MasterDatabase(data_dir=pathlib.Path(tmpdir))
        user = master.create_user(username='restorebridge', display_name='P',
                                  user_types=['student'])
        db = UserDatabase(db_path=master.ensure_user_database(user.id),
                          user_id=user.id, username='restorebridge')
        db._ensure_phase2_schema()
        db._ensure_phase4_schema()
        db._ensure_phase7_schema()
        yield DatabaseBridge(master_db=master, user_db=db)
        db.close()
        master.close()


@pytest.fixture
def exam(bridge):
    return bridge.user_db.create_exam_context(exam_name='Wave 3')


def _node(bridge, exam, name, parent_id=None, dimension_id=None):
    n = bridge.user_db.create_subject_node(
        exam_context=exam.exam_name, name=name, parent_id=parent_id,
        level_type='System', dimension_id=dimension_id)
    return n.id if hasattr(n, 'id') else n


def _payload(raw):
    parsed = json.loads(raw)
    return parsed


# ---------------------------------------------------------------------------
# getArchivedBatches
# ---------------------------------------------------------------------------


def test_the_listing_reaches_the_panel_with_its_kind(bridge, exam):
    """Every entry is labelled, because the restore slots take the label back."""
    root = _node(bridge, exam, 'Cardiovascular')
    bridge.user_db.delete_subject_subtree(root)

    body = _payload(bridge.getArchivedBatches(exam.id))
    assert body['success'] is True
    batches = body['data']['batches']
    assert len(batches) == 1
    assert batches[0]['kind'] == 'subject'
    assert batches[0]['root_node_name'] == 'Cardiovascular'


def test_the_listing_can_be_called_unscoped(bridge, exam):
    """Zero means "every exam".

    QWebChannel has no natural ``None`` for an ``int`` parameter and an exam
    id is always positive, so zero is the unambiguous spelling. Both arities
    are registered; this asserts the no-argument one resolves.
    """
    root = _node(bridge, exam, 'Anywhere')
    bridge.user_db.delete_subject_subtree(root)

    scoped = _payload(bridge.getArchivedBatches(exam.id))['data']['batches']
    unscoped = _payload(bridge.getArchivedBatches())['data']['batches']
    assert [b['batch_id'] for b in scoped] == [b['batch_id'] for b in unscoped]


def test_the_listing_guards_a_missing_user_database(bridge, exam):
    """Every slot works with ``user_db=None`` -- the profile picker runs first."""
    root = _node(bridge, exam, 'Gone')
    bridge.user_db.delete_subject_subtree(root)
    bridge.user_db = None

    body = _payload(bridge.getArchivedBatches(exam.id))
    assert body['success'] is False
    assert 'No user database' in body['error']


# ---------------------------------------------------------------------------
# previewRestoreBatch
# ---------------------------------------------------------------------------


def test_the_preview_mutates_nothing(bridge, exam):
    """Safe to call when the panel expands, which is the point of having it."""
    root = _node(bridge, exam, 'Preview me')
    batch = bridge.user_db.delete_subject_subtree(root)['batch_id']

    body = _payload(bridge.previewRestoreBatch(batch, 'subject'))
    assert body['success'] is True
    assert body['data']['restorable'] is True

    status = bridge.user_db.fetchone(
        'SELECT status FROM subject_nodes WHERE id = ?', (root,))['status']
    assert status == 'archived', 'previewing must not restore anything'


def test_the_preview_carries_notes_as_well_as_blocks(bridge, exam):
    """#260's note has to reach the panel, or the student is not told.

    A subject whose parent is still archived comes back at the top level.
    That is not a refusal and not an error, so it travels in ``notes`` --
    and a payload that dropped the key would leave the student wondering
    where their subject went.
    """
    parent = _node(bridge, exam, 'Parent')
    child = _node(bridge, exam, 'Child', parent_id=parent)
    child_batch = bridge.user_db.delete_subject_subtree(child)['batch_id']
    bridge.user_db.delete_subject_subtree(parent)

    body = _payload(bridge.previewRestoreBatch(child_batch, 'subject'))
    assert body['success'] is True
    assert body['data']['restorable'] is True
    codes = [n['code'] for n in body['data']['notes']]
    assert 'will_appear_at_top_level' in codes


def test_an_unknown_kind_is_a_sentence_not_a_fall_through(bridge, exam):
    """A typo from JS must not silently take the subject path.

    That path would answer "subject" for a dimension-owned batch, which is
    the one case where guessing is actively wrong.
    """
    body = _payload(bridge.previewRestoreBatch('whatever', 'subjcet'))
    assert body['success'] is False
    assert 'Unknown archive kind' in body['error']


# ---------------------------------------------------------------------------
# restoreBatch
# ---------------------------------------------------------------------------


def test_restoring_reports_success_and_a_summary(bridge, exam):
    root = _node(bridge, exam, 'Back again')
    child = _node(bridge, exam, 'Beneath', parent_id=root)
    batch = bridge.user_db.delete_subject_subtree(root)['batch_id']

    body = _payload(bridge.restoreBatch(batch, 'subject'))
    assert body['success'] is True
    assert body['data']['restored'] is True
    assert body['data']['summary'] == 'Restored 2 subjects.'

    for node_id in (root, child):
        assert bridge.user_db.fetchone(
            'SELECT status FROM subject_nodes WHERE id = ?',
            (node_id,))['status'] == 'active'


def test_a_refused_restore_is_success_false_with_the_planners_sentence(
    bridge, exam,
):
    """The #240 contract, at the surface where it matters most.

    Restoring twice has nothing to do. Reporting ``success=true`` with zero
    restored would be indistinguishable from a restore that worked, so the
    slot turns ``SubjectRestoreError`` into ``success=false`` carrying the
    sentence the planner wrote -- not a stack-flavoured string.
    """
    root = _node(bridge, exam, 'Once')
    batch = bridge.user_db.delete_subject_subtree(root)['batch_id']
    assert _payload(bridge.restoreBatch(batch, 'subject'))['success'] is True

    body = _payload(bridge.restoreBatch(batch, 'subject'))
    assert body['success'] is False
    assert 'Nothing in this deletion can be restored' in body['error']
    assert 'Traceback' not in body['error']
    assert 'Failed to restore' not in body['error'], (
        'a refusal must not be dressed up as an internal failure'
    )


def test_a_dimension_archive_restores_through_the_same_slot(bridge, exam):
    """One pair of slots, dispatching on the label the listing supplied."""
    dimension = bridge.user_db.create_dimension(
        exam_id=exam.id, name='System', display_order=1, is_required=True)
    dim_id = dimension.id if hasattr(dimension, 'id') else dimension
    root = _node(bridge, exam, 'Cardio', dimension_id=dim_id)
    batch = bridge.user_db.archive_dimension(dim_id)['batch_id']

    listed = _payload(bridge.getArchivedBatches(exam.id))['data']['batches']
    assert len(listed) == 1 and listed[0]['kind'] == 'dimension'

    body = _payload(bridge.restoreBatch(listed[0]['batch_id'], 'dimension'))
    assert body['success'] is True
    assert 'System' in body['data']['summary']
    assert bridge.user_db.fetchone(
        'SELECT status FROM subject_nodes WHERE id = ?',
        (root,))['status'] == 'active'
    assert batch == listed[0]['batch_id']


def test_a_dimension_owned_batch_refused_through_the_subject_kind(bridge, exam):
    """Hazard 4 survives the trip through the bridge.

    The listing does not offer this batch, but a caller holding the id from
    somewhere else must still be refused rather than allowed to strand its
    subjects inside an archived dimension.
    """
    dimension = bridge.user_db.create_dimension(
        exam_id=exam.id, name='Task', display_order=1, is_required=True)
    dim_id = dimension.id if hasattr(dimension, 'id') else dimension
    _node(bridge, exam, 'Diagnosis', dimension_id=dim_id)
    result = bridge.user_db.archive_dimension(dim_id)
    sub = result['subject_batch_ids'][0]
    sub_batch = sub[0] if isinstance(sub, (tuple, list)) else sub

    body = _payload(bridge.restoreBatch(sub_batch, 'subject'))
    assert body['success'] is False
    assert 'Task' in body['error']
