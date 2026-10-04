"""Bridge surface for the Archived panel (issue #37 Wave 3).

Three slots, all thin: every decision lives in
``database/domains/subject_restore.py`` and this layer only marshals.

Two things about the shape are worth stating here, because both are easy
to get wrong from the JS side.

**`kind` is passed, not inferred.** A batch id identifies either a subject
delete or a whole dimension archive, and the two have different journals,
different planners and different consequences. The panel already knows
which it is -- ``getArchivedBatches`` labels every entry -- so the slot
takes the label rather than probing both tables and guessing. Guessing
would also be ambiguous in the one case that matters: a subject batch
*owned* by a dimension archive exists in both relations, and answering
"subject" for it is exactly the refusal #37's hazard 4 exists to produce.

**A refused restore is ``success=false``, never a success carrying a
quiet complaint.** ``SubjectRestoreError`` is caught and returned as the
error string, so the panel shows the sentence the planner wrote. That
distinction is #240's lesson: a call reporting ``0 restored`` alongside
``success`` is indistinguishable from one that worked, and this is a
surface where the difference is a student's subject tree.

The preview slot exists so the panel can show what a restore *would* do
before the student commits -- the same preview/apply pairing
``getSubjectDeletePreview`` / ``deleteSubjectNode`` has for the delete
direction. Both consume one planner, so they cannot disagree (#67).
"""
from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot
from database.exceptions import SubjectRestoreError

from ..bridge_helpers import serialize_response


class SubjectRestoreBridgeMixin:
    """Bridge mixin for the delete journal's read side. Composed into DatabaseBridge."""

    # ``kind`` values the two slots below accept. A typo from JS should be
    # a sentence, not a silent fall-through to the subject path.
    _KINDS = ('subject', 'dimension')

    @pyqtSlot(result=str)
    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getArchivedBatches(self, exam_context_id: int = 0) -> str:
        """Archive events that still have something to restore, newest first.

        Two arities: the tree editor scopes to the exam it is showing, and
        a caller with no exam in hand (a future global Archived view) may
        omit it. ``0`` means unscoped, because QWebChannel has no natural
        ``None`` for an ``int`` parameter -- an exam id is always positive,
        so zero is unambiguous.

        Each entry carries ``kind`` (``'subject'`` or ``'dimension'``),
        which the restore slots then take back. Subject batches owned by a
        dimension archive are **absent**: one archive event is one entry,
        and restoring an owned batch alone is refused anyway.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            scope = exam_context_id if exam_context_id else None
            return serialize_response(
                True,
                data={
                    'batches': self.user_db.list_archived_batches(
                        exam_context_id=scope),
                },
            )
        except Exception as e:
            self._log_error(
                f'Error listing archived batches: {e}',
                {'exam_context_id': exam_context_id},
            )
            return serialize_response(
                False, error=f'Failed to list archived deletions: {e}')

    @pyqtSlot(str, str, result=str)
    @instrumented_slot
    def previewRestoreBatch(self, batch_id: str, kind: str) -> str:
        """What restoring ``batch_id`` would do. Read-only; mutates nothing.

        Safe to call when the panel expands or a row is selected. Returns
        the planner's output including ``blocked`` (why it cannot run),
        ``notes`` (things worth saying that do not stop it, such as a
        subject coming back at the top level because its parent is still
        archived -- #260) and the per-item ``skip_reason`` values the
        owner's "report what it skipped" decision requires.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        if kind not in self._KINDS:
            return serialize_response(
                False, error=f"Unknown archive kind {kind!r}")

        try:
            if kind == 'dimension':
                plan = self.user_db.plan_dimension_batch_restore(batch_id)
            else:
                plan = self.user_db.plan_batch_restore(batch_id)
            return serialize_response(True, data=plan)
        except Exception as e:
            self._log_error(
                f'Error building restore preview: {e}',
                {'batch_id': batch_id, 'kind': kind},
            )
            return serialize_response(False, error=f'Failed to preview restore: {e}')

    @pyqtSlot(str, str, result=str)
    @instrumented_slot
    def restoreBatch(self, batch_id: str, kind: str) -> str:
        """Undo the archive ``batch_id`` recorded.

        ``SubjectRestoreError`` is caught on purpose and returned as
        ``success=false`` with its message: every one of those is a
        sentence the student can act on (the name is taken, the parent
        must come back first, there is nothing left to restore), not a
        crash. Anything else is logged and reported generically, because
        an unexpected exception here is a defect rather than a state.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        if kind not in self._KINDS:
            return serialize_response(
                False, error=f"Unknown archive kind {kind!r}")

        try:
            if kind == 'dimension':
                result = self.user_db.restore_dimension_delete_batch(batch_id)
            else:
                result = self.user_db.restore_subject_delete_batch(batch_id)
            return serialize_response(True, data=result)
        except SubjectRestoreError as e:
            # A refusal, not a failure of the code. The planner wrote the
            # sentence; pass it through untouched.
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(
                f'Error restoring archive batch: {e}',
                {'batch_id': batch_id, 'kind': kind},
            )
            return serialize_response(False, error=f'Failed to restore: {e}')
