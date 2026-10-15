"""AnkiBridgeMixin against a real database and a fake AnkiConnect (#784 Wave 2).

The guard the plan promised and Wave 1 deferred (#792 review note 1): every
job kind runs here against a ``user_db`` that **raises when touched from any
thread but the one that built it**. A worker closure that captured the
database -- the mistake a static import check cannot see -- fails its job,
and ``test_the_guard_catches_a_worker_that_touches_the_database`` proves the
guard is live rather than assuming it.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

import pytest

from app.bridge import DatabaseBridge
from app.media_manager import MediaManager
from database.user_db import UserDatabase
from tests._fake_ankiconnect import FakeAnkiConnect

TPL = 'tag:Bank::{{qid}}'
PNG = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06'
       b'\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01'
       b'\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82')


#: Every slot that refuses without a profile, with minimal arguments.
GUARDED_SLOTS = {
    'getAnkiStatus': (), 'getAnkiTemplates': (0,), 'addAnkiTemplate': (1, 1, TPL),
    'updateAnkiTemplate': (1, TPL), 'removeAnkiTemplate': (1,),
    'getAnkiFieldSettings': (), 'setAnkiFieldVisibility': ('Basic', 'Front', False),
    'getAnkiEntryStats': (1,), 'startAnkiJob': ('refresh_entry', '{"entry_id": 1}'),
    'setAnkiCardVerdict': (1, 101, 'confirmed'), 'rejectAnkiCardForSubjects': (1, 101),
}


class ThreadGuardedDB:
    """Forwards to the real database on its own thread; raises on any other."""

    def __init__(self, db):
        object.__setattr__(self, '_db', db)
        object.__setattr__(self, '_home', threading.get_ident())
        object.__setattr__(self, 'violations', [])

    def __getattr__(self, name):
        if threading.get_ident() != self._home:
            self.violations.append(name)
            raise AssertionError(
                f'the Anki worker touched the database: user_db.{name}. Database work '
                f'belongs in the prepare or finish phase, on the main thread.')
        return getattr(self._db, name)


@pytest.fixture
def anki():
    with FakeAnkiConnect() as fake:
        yield fake


@pytest.fixture
def real_db(tmp_path):
    db = UserDatabase(tmp_path / 'anki.db', user_id=1, username='anki_user')
    yield db
    db.close()


@pytest.fixture
def world(real_db, anki, tmp_path):
    """An exam, a bank with a template, an entry, Anki on and pointed at the fake."""
    exam = real_db.create_exam_context(exam_name='Step X')
    bank = real_db.create_question_source(source_name='Bank', exam_context='Step X')
    real_db.anki_add_template(exam.id, bank.id, TPL)
    session = real_db.create_review_session(exam_context_id=exam.id, total_questions=5,
                                            total_incorrect=2, question_source_id=bank.id)
    entry = real_db.create_question_entry(session.id, 'A', 'B', question_id='7')
    real_db.update_device_settings(anki_integration_enabled=True, ankiconnect_port=anki.port)
    anki.searches['tag:Bank::7'] = [101, 102]
    anki.add_card(101, note_id=10, interval=12, queue=2,
                  fields={'Front': {'value': '<b>Front</b> <img src="pic.png">', 'order': 0},
                          'Back': {'value': 'Back', 'order': 1}})
    anki.add_card(102, note_id=10, interval=3, queue=0)
    anki.reviews[101] = [{'id': 1_700_000_000_000, 'ivl': 12, 'factor': 2500,
                          'time': 4000, 'ease': 3, 'lastIvl': 4, 'type': 1}]
    anki.media['pic.png'] = PNG
    return {'db': real_db, 'exam': exam, 'bank': bank, 'entry': entry, 'tmp': tmp_path}


@pytest.fixture
def bridge(world):
    guarded = ThreadGuardedDB(world['db'])
    b = DatabaseBridge(master_db=None, user_db=guarded)
    b.media_manager = MediaManager(base_path=world['tmp'] / 'app_data', user_id=1,
                                   username='anki_user')
    yield b
    b.teardownAnki()
    assert guarded.violations == [], f'worker touched the database: {guarded.violations}'


def _ok(raw):
    payload = json.loads(raw)
    assert payload['success'], payload.get('error')
    return payload.get('data')


def _err(raw):
    payload = json.loads(raw)
    assert not payload['success'], payload
    return payload['error']


def _run(bridge, kind, params, deadline_s=10.0):
    job_id = _ok(bridge.startAnkiJob(kind, json.dumps(params)))['job_id']
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        report = _ok(bridge.pollAnkiJob(job_id))
        if report['state'] != 'running':
            return report
        time.sleep(0.01)
    raise AssertionError(f'{kind} still running after {deadline_s} s')


# --------------------------------------------------------------- the guard

def test_the_guard_catches_a_worker_that_touches_the_database(bridge, anki):
    """Control: without it, a passing job kind proves nothing."""
    jobs = bridge._anki_jobs()
    job_id = jobs.start(lambda client: bridge.user_db.user_id,
                        client_factory=bridge._anki_client_factory(anki.port))
    end = time.monotonic() + 5
    while (report := jobs.poll(job_id))['state'] == 'running' and time.monotonic() < end:
        time.sleep(0.01)
    assert report['state'] == 'failed'
    assert 'touched the database' in report['error']['detail']
    bridge.user_db.violations.clear()   # expected here; the fixture checks the rest


# -------------------------------------------------------------- inline slots

class TestInline:
    @pytest.mark.parametrize('slot', sorted(GUARDED_SLOTS))
    def test_no_database_is_a_sentence(self, slot):
        b = DatabaseBridge(master_db=None, user_db=None)
        assert _err(getattr(b, slot)(*GUARDED_SLOTS[slot])) == 'No user database connected'

    def test_the_sweep_covers_every_slot_and_the_js_calls_only_those(self):
        """pollAnkiJob is the one slot without a user_db guard: the job layer's
        profile check covers it. Both directions, so neither list can drift."""
        root = Path(__file__).resolve().parents[2]
        src = (root / 'src/app/bridge_domains/anki.py').read_text(encoding='utf-8')
        slots = set(re.findall(r'@pyqtSlot\([^)]*\)\s*@instrumented_slot\s*def (\w+)', src))
        assert slots == set(GUARDED_SLOTS) | {'pollAnkiJob'}
        js = (root / 'src/web/js/api/anki.js').read_text(encoding='utf-8')
        assert set(re.findall(r"_callBridge\('(\w+)'", js)) == slots

    def test_a_failing_saved_port_read_is_a_sentence(self):
        """#800 review note 2: ping with no port reads the device settings, and
        a database error there must not escape the slot."""
        class Broken:
            user_id = 1

            def get_device_settings(self):
                raise RuntimeError('disk I/O error')

        b = DatabaseBridge(master_db=None, user_db=Broken())
        assert 'disk I/O error' in _err(b.startAnkiJob('ping', '{}'))

    def test_status(self, bridge, anki):
        assert _ok(bridge.getAnkiStatus()) == {'enabled': True, 'port': anki.port}

    def test_template_slots(self, bridge, world):
        exam, bank = world['exam'], world['bank']
        added = _ok(bridge.addAnkiTemplate(exam.id, bank.id, 'deck:D {{qid}}'))
        assert len(_ok(bridge.getAnkiTemplates(exam.id))) == 2
        assert _ok(bridge.updateAnkiTemplate(added['id'], 'deck:E {{qid}}'))['template'] \
            == 'deck:E {{qid}}'
        assert 'already' in _err(bridge.addAnkiTemplate(exam.id, bank.id, TPL))
        _ok(bridge.removeAnkiTemplate(added['id']))
        assert '{{qid}}' in _err(bridge.addAnkiTemplate(exam.id, bank.id, 'deck:D'))

    def test_stats_before_any_sync_are_stale_and_empty(self, bridge, world):
        stats = _ok(bridge.getAnkiEntryStats(world['entry'].id))
        assert stats['matchable'] and stats['has_templates']
        assert stats['synced'] is False and stats['stale'] is True and stats['cards'] == []

    def test_an_unmatchable_entry_says_why(self, bridge, world):
        db = world['db']
        session = db.create_review_session(exam_context_id=world['exam'].id,
                                           total_questions=1, total_incorrect=1)
        bare = db.create_question_entry(session.id, 'A', 'B', question_id='9')
        stats = _ok(bridge.getAnkiEntryStats(bare.id))
        assert stats['matchable'] is False and 'question bank' in stats['reason']


# ----------------------------------------------------------------------- jobs

class TestJobs:
    def test_unknown_kind_and_bad_params_are_refused_before_a_worker(self, bridge):
        assert 'Unknown Anki job' in _err(bridge.startAnkiJob('deleteDecks', '{}'))
        assert 'Invalid' in _err(bridge.startAnkiJob('ping', '[1]'))

    def test_ping_on_the_saved_port_and_on_an_explicit_one(self, bridge, anki):
        assert _run(bridge, 'ping', {})['result'] == {'version': 6}
        assert _run(bridge, 'ping', {'port': anki.port})['result'] == {'version': 6}
        assert '1000 to 65535' in _err(bridge.startAnkiJob('ping', '{"port": 80}'))

    def test_jobs_need_the_feature_switched_on(self, bridge, world):
        world['db'].update_device_settings(anki_integration_enabled=False)
        assert 'switched off' in _err(bridge.startAnkiJob(
            'refresh_entry', json.dumps({'entry_id': world['entry'].id})))

    def test_refresh_entry_records_and_returns_the_payload(self, bridge, world, anki):
        report = _run(bridge, 'refresh_entry', {'entry_id': world['entry'].id})
        assert report['state'] == 'done'
        payload = report['result']
        assert [c['card_id'] for c in payload['cards']] == [101, 102]
        first = payload['cards'][0]
        assert first['fields'][0] == {'name': 'Front', 'text': 'Front',
                                      'images': ['pic.png'], 'visible': True}
        assert first['estimate']['stability_days'] == 12.0
        assert first['estimate']['ease_percent'] == 250.0
        assert payload['stale'] is False and payload['last_synced_at'].endswith('Z')
        assert anki.requests[0]['params'] == {'query': 'tag:Bank::7'}

    def test_finding_1_a_closed_anki_records_nothing(self, bridge, world, anki):
        _run(bridge, 'refresh_entry', {'entry_id': world['entry'].id})
        before = _ok(bridge.getAnkiEntryStats(world['entry'].id))
        anki.stop()                                          # Anki closed
        report = _run(bridge, 'refresh_entry', {'entry_id': world['entry'].id})
        assert report['state'] == 'failed'
        assert report['error']['kind'] == 'unavailable' and report['error']['retryable']
        after = _ok(bridge.getAnkiEntryStats(world['entry'].id))
        # Retrievability moves with the clock, so compare what was stored.
        assert [c['card_id'] for c in after['cards']] == [101, 102]
        assert [c['fields'] for c in after['cards']] == [c['fields'] for c in before['cards']]
        assert after['last_synced_at'] == before['last_synced_at']

    def test_a_bank_with_no_template_is_refused_with_a_sentence(self, bridge, world):
        db = world['db']
        other = db.create_question_source(source_name='Other', exam_context='Step X')
        session = db.create_review_session(exam_context_id=world['exam'].id, total_questions=1,
                                           total_incorrect=1, question_source_id=other.id)
        entry = db.create_question_entry(session.id, 'A', 'B', question_id='3')
        assert 'no Anki search template' in _err(bridge.startAnkiJob(
            'refresh_entry', json.dumps({'entry_id': entry.id})))

    def test_sync_exam_includes_drafts_and_reports_counts(self, bridge, world, anki):
        db = world['db']
        session = db.create_review_session(exam_context_id=world['exam'].id, total_questions=1,
                                           total_incorrect=1, question_source_id=world['bank'].id)
        db.create_question_entry(session.id, 'A', 'B', question_id='8')   # a draft
        db.create_question_entry(session.id, 'A', 'B', question_id='has space')
        anki.searches['tag:Bank::8'] = [103]
        anki.add_card(103, note_id=11)
        result = _run(bridge, 'sync_exam', {'exam_context_id': world['exam'].id})['result']
        assert result['questions'] == 3 and result['synced'] == 2
        assert [s['question_id'] for s in result['skipped']] == ['has space']
        assert result['stopped'] is None

    def test_sync_exam_keeps_what_completed_when_anki_goes_away(self, bridge, world, anki):
        db = world['db']
        session = db.create_review_session(exam_context_id=world['exam'].id, total_questions=1,
                                           total_incorrect=1, question_source_id=world['bank'].id)
        db.create_question_entry(session.id, 'A', 'B', question_id='8')
        anki.fail_actions['findCards'] = 'boom'   # an action failure is per question
        result = _run(bridge, 'sync_exam', {'exam_context_id': world['exam'].id})['result']
        assert result['synced'] == 0 and len(result['skipped']) == 2

    def test_a_collected_job_is_forgotten(self, bridge, world, anki):
        """#800 review note 1: a report is released once its terminal state
        has been read, so a refresh's payload does not live for the session."""
        job_id = json.loads(bridge.startAnkiJob('ping', '{}'))['data']['job_id']
        end = time.monotonic() + 10
        while (report := json.loads(bridge.pollAnkiJob(job_id))['data'])['state'] == 'running':
            assert time.monotonic() < end
            time.sleep(0.02)
        assert report['state'] == 'done'
        again = json.loads(bridge.pollAnkiJob(job_id))['data']
        assert again['error']['kind'] == 'unknown_job'
        assert bridge._anki_jobs()._jobs == {}

    def test_unsuspend_records_the_queue_anki_restored(self, bridge, world, anki):
        """#800 review note 3: a review card comes back as review (2), not new (0)."""
        anki.cards[102]['type'] = 2
        anki.cards[102]['queue'] = 2
        entry_id = world['entry'].id
        _run(bridge, 'refresh_entry', {'entry_id': entry_id})
        _run(bridge, 'suspend', {'entry_id': entry_id, 'card_ids': [102]})
        payload = _run(bridge, 'unsuspend', {'entry_id': entry_id, 'card_ids': [102]})['result']
        assert {c['card_id']: c['queue'] for c in payload['cards']}[102] == 2
        assert anki.actions()[-2:] == ['unsuspend', 'cardsInfo']

    def test_unsuspend_falls_back_to_the_card_type_when_the_read_back_fails(
            self, bridge, world, anki):
        anki.cards[102]['type'] = 3          # relearning: Anki restores learning
        entry_id = world['entry'].id
        _run(bridge, 'refresh_entry', {'entry_id': entry_id})
        _run(bridge, 'suspend', {'entry_id': entry_id, 'card_ids': [102]})
        anki.fail_actions['cardsInfo'] = 'collection is busy'
        payload = _run(bridge, 'unsuspend', {'entry_id': entry_id, 'card_ids': [102]})['result']
        assert {c['card_id']: c['queue'] for c in payload['cards']}[102] == 1

    def test_suspend_then_unsuspend_once_each(self, bridge, world, anki):
        entry_id = world['entry'].id
        _run(bridge, 'refresh_entry', {'entry_id': entry_id})
        anki.requests.clear()
        payload = _run(bridge, 'suspend', {'entry_id': entry_id, 'card_ids': [102]})['result']
        assert [c['suspended'] for c in payload['cards']] == [False, True]
        assert anki.cards[102]['queue'] == -1
        payload = _run(bridge, 'unsuspend', {'entry_id': entry_id, 'card_ids': [102]})['result']
        assert [c['suspended'] for c in payload['cards']] == [False, False]
        # One request per press: the plugin's re-bound handler fired twice.
        assert anki.actions() == ['suspend', 'unsuspend', 'cardsInfo']

    @pytest.mark.parametrize('card_ids, fragment', [
        ([], 'at least one'), ([999], "not this entry's"), (['101'], 'at least one'),
    ])
    def test_suspension_ids_come_from_the_entrys_match(self, bridge, world, card_ids, fragment):
        _run(bridge, 'refresh_entry', {'entry_id': world['entry'].id})
        assert fragment in _err(bridge.startAnkiJob(
            'suspend', json.dumps({'entry_id': world['entry'].id, 'card_ids': card_ids})))

    def test_save_image_attaches_it_once(self, bridge, world):
        entry_id = world['entry'].id
        _run(bridge, 'refresh_entry', {'entry_id': entry_id})
        report = _run(bridge, 'save_image', {'entry_id': entry_id, 'filename': 'pic.png'})
        assert report['state'] == 'done', report
        assert report['result']['original_filename'] == 'pic.png'
        names = [m.original_filename for m in world['db'].get_entry_media_list(entry_id)]
        assert names == ['pic.png']
        assert 'already attached' in _err(bridge.startAnkiJob(
            'save_image', json.dumps({'entry_id': entry_id, 'filename': 'pic.png'})))

    @pytest.mark.parametrize('filename, fragment', [
        ('other.png', "not on any of this entry's cards"),
        ('../x.png', 'not an Anki image'),
    ])
    def test_save_image_only_fetches_what_the_cards_show(self, bridge, world, filename,
                                                         fragment):
        _run(bridge, 'refresh_entry', {'entry_id': world['entry'].id})
        assert fragment in _err(bridge.startAnkiJob(
            'save_image', json.dumps({'entry_id': world['entry'].id, 'filename': filename})))

    def test_an_image_anki_no_longer_has_fails_rather_than_saving(self, bridge, world, anki):
        _run(bridge, 'refresh_entry', {'entry_id': world['entry'].id})
        del anki.media['pic.png']
        report = _run(bridge, 'save_image', {'entry_id': world['entry'].id,
                                              'filename': 'pic.png'})
        assert report['state'] == 'failed'
        assert world['db'].get_entry_media_list(world['entry'].id) == []

    def test_view_image_returns_the_image_and_writes_nothing(self, bridge, world, anki):
        """#784 Wave 4: the entry page shows a card image in its lightbox."""
        import base64
        entry_id = world['entry'].id
        _run(bridge, 'refresh_entry', {'entry_id': entry_id})
        report = _run(bridge, 'view_image', {'entry_id': entry_id, 'filename': 'pic.png'})
        assert report['state'] == 'done', report
        assert report['result']['filename'] == 'pic.png'
        assert report['result']['data_url'] == (
            'data:image/png;base64,' + base64.b64encode(PNG).decode('ascii'))
        assert world['db'].get_entry_media_list(entry_id) == []

    @pytest.mark.parametrize('filename, fragment', [
        ('other.png', "not on any of this entry's cards"),
        ('../x.png', 'not an Anki image'),
    ])
    def test_view_image_only_fetches_what_the_cards_show(self, bridge, world, anki,
                                                         filename, fragment):
        _run(bridge, 'refresh_entry', {'entry_id': world['entry'].id})
        anki.requests.clear()
        assert fragment in _err(bridge.startAnkiJob(
            'view_image', json.dumps({'entry_id': world['entry'].id, 'filename': filename})))
        assert anki.actions() == [], 'a refused name must never reach Anki'

    def test_view_image_refuses_bytes_that_are_not_an_image(self, bridge, world, anki):
        """The type comes from the bytes, never from the name a deck chose."""
        _run(bridge, 'refresh_entry', {'entry_id': world['entry'].id})
        anki.media['pic.png'] = b'<svg onload="alert(1)"></svg>'
        report = _run(bridge, 'view_image', {'entry_id': world['entry'].id,
                                              'filename': 'pic.png'})
        assert report['state'] == 'failed'
        assert 'not an image WIMI can show' in report['error']['detail']

    def test_a_job_that_cannot_start_is_a_sentence(self, bridge, world, monkeypatch):
        """#802 review 2: the non-ping start was the one call outside the try."""
        def refuse(*args, **kwargs):
            raise RuntimeError('cannot schedule new futures after shutdown')
        monkeypatch.setattr(bridge._anki_jobs(), 'start', refuse)
        assert 'after shutdown' in _err(bridge.startAnkiJob(
            'refresh_entry', json.dumps({'entry_id': world['entry'].id})))

    def test_proposals_confirm_and_both_rejections(self, bridge, world, anki):
        """#784 Wave 5 end to end through the bridge, against the fake's cards.

        Card 101's Front names the entry's subject; card 102 has no fields. A
        confirmation moves 101 first and ends its proposal; *not for this
        entry* is entry-scoped; *never* follows the subject to another entry.
        """
        db = world['db']
        subject = db.create_subject_node('Step X', 'Front', 'System')
        with db.transaction():
            db.execute("INSERT INTO entry_subject_mappings (question_entry_id, subject_node_id, "
                       "mapping_type) VALUES (?, ?, 'primary')", (world['entry'].id, subject.id))
        # The fixture's two cards share note 10 and so its fields; give 102 a
        # note of its own with nothing in it, so only 101 names the subject.
        anki.cards[102]['note'] = 11
        entry_id = world['entry'].id
        _run(bridge, 'refresh_entry', {'entry_id': entry_id})
        payload = _ok(bridge.getAnkiEntryStats(entry_id))
        assert [p['card_id'] for p in payload['proposals']] == [101]
        assert payload['proposals'][0]['subject_ids'] == [subject.id]
        assert [c['card_id'] for c in payload['cards']] == [101, 102]

        payload = _ok(bridge.setAnkiCardVerdict(entry_id, 102, 'confirmed'))
        assert [c['card_id'] for c in payload['cards']] == [102, 101], 'confirmed comes first'
        assert payload['cards'][0]['confirmed'] is True

        payload = _ok(bridge.setAnkiCardVerdict(entry_id, 101, 'not_for_entry'))
        assert payload['proposals'] == []
        payload = _ok(bridge.setAnkiCardVerdict(entry_id, 101, 'clear'))
        assert [p['card_id'] for p in payload['proposals']] == [101]

        payload = _ok(bridge.rejectAnkiCardForSubjects(entry_id, 101))
        assert payload['proposals'] == []
        assert db.anki_subject_rejections([subject.id]) == {(subject.id, 101)}
        assert 'not being proposed' in _err(bridge.rejectAnkiCardForSubjects(entry_id, 101))
        assert len(payload['cards']) == 2, 'a rejection never hides a card'

    def test_an_unknown_verdict_is_a_sentence(self, bridge, world):
        _run(bridge, 'refresh_entry', {'entry_id': world['entry'].id})
        assert 'shown first' in _err(bridge.setAnkiCardVerdict(world['entry'].id, 101, 'maybe'))

    def test_a_profile_switch_mid_job_writes_nothing(self, bridge, world, anki):
        anki.delay_s = 0.5
        job_id = _ok(bridge.startAnkiJob('refresh_entry',
                                         json.dumps({'entry_id': world['entry'].id})))['job_id']
        real = bridge.user_db
        bridge.user_db = None            # the profile closed while Anki answered
        try:
            end = time.monotonic() + 5
            while (report := _ok(bridge.pollAnkiJob(job_id)))['state'] == 'running':
                assert time.monotonic() < end
                time.sleep(0.02)
        finally:
            bridge.user_db = real
        assert report['error']['kind'] == 'profile_changed'
        assert world['db'].anki_get_match({'exam_context_id': world['exam'].id,
                                           'question_source_id': world['bank'].id,
                                           'question_id': '7'}) is None


def test_main_window_tears_the_anki_worker_down_before_the_databases_close():
    """#800 review note 5: behaviour and order, not a source string. Uses the
    browser-pane test's recording stand-ins with a bridge that has the slot."""
    from app.main_window import MainWindow
    from tests.app.test_main_window_closes_the_browser_pane import (
        _FakeWindow, _RecordingBridge, _RecordingEvent)

    class AnkiBridge(_RecordingBridge):
        def teardownAnki(self):  # noqa: N802 (mirrors the bridge method)
            self._log.append('anki')

    window = _FakeWindow()
    window.db_bridge = AnkiBridge(window.log)
    event = _RecordingEvent(window.log)
    MainWindow.closeEvent(window, event)
    assert window.log == ['foldersync', 'anki', 'close:user', 'close:master', 'accept']
