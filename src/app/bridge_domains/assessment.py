"""WIMI psychometric assessment bridge operations (#766, Wave 1).

Thin slots over ``AssessmentsMixin`` (``database/domains/assessments.py``),
plus the one piece of logic the plan's Stage 2 puts here: shaping the
fixture into the ordered flow the assessment page renders.

Passive-recording only (owner, decision 3): every slot reads or writes the
student's own administration; nothing here changes any other surface.

Why ``startAssessment`` returns the whole item flow inline
--------------------------------------------------------
The alternative is a second round trip for the items. One call means the
page cannot render a flow for an administration other than the one it was
just handed, and the resume case (decision 6: skip now, come back later)
needs both the record and the answered-so-far set together anyway.

Why the flow is shaped here and not in the database mixin
--------------------------------------------------------
The mixin owns rows. The flow -- sections in order, attention checks spliced
in after the item each one names, a 1-indexed position across everything --
is a presentation of the fixture, and the fixture is read-only data the
mixin never needs to walk. ``_shape_flow`` is a pure function so Wave 2's
page tests and Wave 4's scenarios can call it without a database.

What is deliberately NOT in the payload
---------------------------------------
``reverse_scored`` and ``expected_response``. The first is scoring metadata
the page has no use for; the second is the attention check's answer, which
the prompt already states in words, but the page should not be able to
*compute* a pass without the student reading the prompt.
"""
from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot
from database.domains._assessment_scoring import (
    AssessmentFixture,
    ItemSpec,
    ScaleSpec,
    load_fixture,
)
from database.exceptions import AssessmentError

from ..bridge_helpers import serialize_response

_NO_DB = 'No user database connected'
_DEFAULT_VERSION = 'v1'

# Fixtures are read-only files; load each version once per process.
_FIXTURE_CACHE: dict[str, AssessmentFixture] = {}


def _fixture(version: str) -> AssessmentFixture:
    fx = _FIXTURE_CACHE.get(version)
    if fx is None:
        fx = load_fixture(version)
        _FIXTURE_CACHE[version] = fx
    return fx


def _scale_dict(scale: ScaleSpec) -> dict[str, Any]:
    return {
        'name': scale.name,
        'min': scale.min,
        'max': scale.max,
        'anchors': list(scale.anchors),
    }


def _item_dict(item: ItemSpec, kind: str) -> dict[str, Any]:
    return {
        'item_code': item.item_code,
        'prompt': item.prompt,
        'kind': kind,                # 'item' | 'attention'
        'subscale': item.subscale,   # None for NFC and attention checks
        'scale': item.scale.name,
    }


def _shape_flow(fixture: AssessmentFixture) -> list[dict[str, Any]]:
    """The ordered flow the page renders: sections, with attention checks
    spliced in directly after the item each one names, and a 1-indexed
    ``position`` on every entry so the page can say "Question N of M".

    An attention check whose anchor item is in no section is appended to the
    last section rather than dropped: a check that silently vanished would
    make ``attention_check_pass`` unreachable with nothing saying why.
    """
    after: dict[str, list[ItemSpec]] = {}
    orphans: list[ItemSpec] = []
    known = {it.item_code for sec in fixture.sections for it in sec.items}
    for ac in fixture.attention_checks:
        anchor = getattr(ac, 'insert_after_item_code', None)
        if anchor in known:
            after.setdefault(anchor, []).append(ac)
        else:
            orphans.append(ac)

    sections: list[dict[str, Any]] = []
    position = 0
    for sec in fixture.sections:
        items: list[dict[str, Any]] = []
        for it in sec.items:
            position += 1
            d = _item_dict(it, 'item'); d['position'] = position; items.append(d)
            for ac in after.get(it.item_code, ()):
                position += 1
                d = _item_dict(ac, 'attention'); d['position'] = position; items.append(d)
        sections.append({
            'name': sec.name,
            'title': sec.title,
            'scale': _scale_dict(sec.scale),
            'scoring_method': sec.scoring_method,
            'subscales': list(sec.subscales),
            'items': items,
        })
    if orphans and sections:
        for ac in orphans:
            position += 1
            d = _item_dict(ac, 'attention'); d['position'] = position
            sections[-1]['items'].append(d)
    return sections


class AssessmentBridgeMixin:
    """Bridge mixin for the psychometric assessment battery. Composed into
    DatabaseBridge; reaches the database through ``self.user_db``."""

    # ------------------------------------------------------------------ flow

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def startAssessment(self, instrument_version: str) -> str:
        """Start an administration, or resume the in-flight one.

        Returns the record plus the full item flow and the codes already
        answered, so one call is enough to render a fresh start or a resume.
        An empty version means the default.
        """
        if not self.user_db:
            return serialize_response(False, error=_NO_DB)
        version = instrument_version or _DEFAULT_VERSION
        try:
            in_flight = self.user_db.get_in_flight_assessment()
            record = self.user_db.start_assessment(version)
            fixture = _fixture(record.instrument_version)
            answered = [
                r.item_code
                for r in self.user_db.get_assessment_responses(record.id)
            ]
            sections = _shape_flow(fixture)
            total = sum(len(s['items']) for s in sections)
            data = record.to_dict()
            data.update({
                'assessment_id': record.id,
                'is_resumed': in_flight is not None,
                'answered_item_codes': answered,
                'total_items': total,
                'sections': sections,
            })
            return serialize_response(True, data=data)
        except AssessmentError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(f'Error starting assessment: {e}',
                            {'instrument_version': version})
            return serialize_response(False, error=str(e))

    @pyqtSlot(result=str)
    @instrumented_slot
    def getInFlightAssessment(self) -> str:
        """The unfinished administration, or null. Lets the dashboard banner
        say "resume" rather than "start" without starting anything."""
        if not self.user_db:
            return serialize_response(False, error=_NO_DB)
        try:
            rec = self.user_db.get_in_flight_assessment()
            return serialize_response(True, data=rec.to_dict() if rec else None)
        except Exception as e:
            self._log_error(f'Error reading in-flight assessment: {e}', {})
            return serialize_response(False, error=str(e))

    @pyqtSlot(int, str, int, int, result=str)
    @instrumented_slot
    def submitResponse(self, assessment_id: int, item_code: str,
                       raw_response: int, response_time_ms: int) -> str:
        """Record one answer. Validation failures come back as
        ``success=false`` with the mixin's sentence, never as a raw exception."""
        if not self.user_db:
            return serialize_response(False, error=_NO_DB)
        try:
            self.user_db.submit_response(
                assessment_id, item_code, raw_response, response_time_ms or 0)
            return serialize_response(True, data={'ok': True})
        except (AssessmentError, ValueError, KeyError) as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(f'Error submitting response: {e}',
                            {'assessment_id': assessment_id,
                             'item_code': item_code})
            return serialize_response(False, error=str(e))

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def finishAssessment(self, assessment_id: int) -> str:
        """Score and close the administration. Returns the completed record,
        scores and ``attention_check_pass`` included."""
        if not self.user_db:
            return serialize_response(False, error=_NO_DB)
        try:
            rec = self.user_db.finish_assessment(assessment_id)
            return serialize_response(True, data=rec.to_dict())
        except AssessmentError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(f'Error finishing assessment: {e}',
                            {'assessment_id': assessment_id})
            return serialize_response(False, error=str(e))

    # ----------------------------------------------------------------- reads

    @pyqtSlot(result=str)
    @instrumented_slot
    def getLatestScores(self) -> str:
        """The most recent completed administration, or null."""
        if not self.user_db:
            return serialize_response(False, error=_NO_DB)
        try:
            rec = self.user_db.get_latest_scores()
            return serialize_response(True, data=rec.to_dict() if rec else None)
        except Exception as e:
            self._log_error(f'Error reading latest scores: {e}', {})
            return serialize_response(False, error=str(e))

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getAssessmentHistory(self, limit: int) -> str:
        """Completed administrations, newest first. ``limit <= 0`` means the
        mixin's default."""
        if not self.user_db:
            return serialize_response(False, error=_NO_DB)
        try:
            kwargs = {'limit': limit} if limit and limit > 0 else {}
            recs = self.user_db.get_assessment_history(**kwargs)
            return serialize_response(True, data=[r.to_dict() for r in recs])
        except Exception as e:
            self._log_error(f'Error reading assessment history: {e}', {})
            return serialize_response(False, error=str(e))

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getAssessmentResponses(self, assessment_id: int) -> str:
        """Every recorded answer for one administration."""
        if not self.user_db:
            return serialize_response(False, error=_NO_DB)
        try:
            rows = self.user_db.get_assessment_responses(assessment_id)
            return serialize_response(True, data=[r.to_dict() for r in rows])
        except AssessmentError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(f'Error reading assessment responses: {e}',
                            {'assessment_id': assessment_id})
            return serialize_response(False, error=str(e))

    # ------------------------------------------------------------- cadence

    @pyqtSlot(result=str)
    @instrumented_slot
    def getReassessmentStatus(self) -> str:
        if not self.user_db:
            return serialize_response(False, error=_NO_DB)
        try:
            return serialize_response(
                True, data=self.user_db.get_reassessment_status())
        except Exception as e:
            self._log_error(f'Error reading reassessment status: {e}', {})
            return serialize_response(False, error=str(e))

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def snoozeReassessment(self, days: int) -> str:
        if not self.user_db:
            return serialize_response(False, error=_NO_DB)
        try:
            prefs = self.user_db.snooze_reassessment(days)
            return serialize_response(True, data=prefs.to_dict())
        except (AssessmentError, ValueError) as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(f'Error snoozing reassessment: {e}', {'days': days})
            return serialize_response(False, error=str(e))

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def setReassessmentCadence(self, cadence_days: int) -> str:
        if not self.user_db:
            return serialize_response(False, error=_NO_DB)
        try:
            prefs = self.user_db.set_reassessment_cadence(cadence_days)
            return serialize_response(True, data=prefs.to_dict())
        except (AssessmentError, ValueError) as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(f'Error setting reassessment cadence: {e}',
                            {'cadence_days': cadence_days})
            return serialize_response(False, error=str(e))

    @pyqtSlot(result=str)
    @instrumented_slot
    def getReassessmentCadence(self) -> str:
        if not self.user_db:
            return serialize_response(False, error=_NO_DB)
        try:
            prefs = self.user_db.get_assessment_preferences()
            return serialize_response(
                True, data={'cadence_days': prefs.cadence_days})
        except Exception as e:
            self._log_error(f'Error reading reassessment cadence: {e}', {})
            return serialize_response(False, error=str(e))
