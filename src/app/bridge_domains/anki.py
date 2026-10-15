"""WIMI's Anki bridge (#784 Wave 2).

Slots over ``AnkiMixin`` (``database/domains/anki.py``) and the job layer in
``app.anki``. Plan: ``docs/planning/ANKI_INTEGRATION_IMPLEMENTATION_PLAN.md``.

Two kinds of slot, and the split is the whole design
----------------------------------------------------
**Reads and writes of WIMI's own rows answer inline** -- templates, field
visibility, the cached stats for an entry. None of them talks to Anki, so
none of them can block.

**Anything that talks to Anki is a job.** ``startAnkiJob`` does the database
reads on this thread (the Qt main thread), hands the worker a closure over
**plain data and a client**, and returns a job id; ``pollAnkiJob`` runs the
finish phase -- the database writes -- on this thread too. The plugin this
replaces made every AnkiConnect call inline, so a closed Anki froze the
window for up to ten seconds per request (#784 plan, finding 5). The worker
must never reach ``self.user_db``; ``tests/app/test_anki_bridge.py`` runs
every job kind against a database that raises when touched from another
thread, which is the guard a static import check cannot be.

There is **no generic pass-through slot**: the plugin's ``callPlugin`` let
the page send AnkiConnect any action at all (finding 6). The job kinds below
are the whole vocabulary.

Job kinds
---------
``ping``            ``{}``                       AnkiConnect's version, no profile needed
``refresh_entry``   ``{entry_id}``               re-fetch one question's cards and log
``sync_exam``       ``{exam_context_id}``        every question in an exam, drafts included
``suspend``         ``{entry_id, card_ids}``     suspend cards this entry's match found
``unsuspend``       ``{entry_id, card_ids}``     the reverse
``save_image``      ``{entry_id, filename}``     copy a card's image into the entry

Everything but ``ping`` needs the feature enabled on this device
(``anki_integration_enabled``, owner decision 5) and a profile open.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot
from database.exceptions import AnkiDataError, ValidationError

from ..bridge_helpers import serialize_response

logger = logging.getLogger(__name__)

_NO_DB = 'No user database connected'

#: The job vocabulary; anything else is refused before a worker is involved.
JOB_KINDS = ('ping', 'refresh_entry', 'sync_exam', 'suspend', 'unsuspend', 'save_image',
             'view_image')

#: Image types the entry page may draw from Anki's media folder, by their
#: leading bytes -- never by the file name, which a shared deck chooses.
_IMAGE_SIGNATURES = (
    (b'\x89PNG\r\n\x1a\n', 'image/png'),
    (b'\xff\xd8\xff', 'image/jpeg'),
    (b'GIF87a', 'image/gif'),
    (b'GIF89a', 'image/gif'),
)

#: What the page reads for a card's queue. AnkiConnect's -1 is "suspended".
_SUSPENDED_QUEUE = -1


class AnkiBridgeMixin:
    """Mixin for the Anki bridge. Composed into DatabaseBridge."""

    # ------------------------------------------------------------------
    # Plumbing
    # ------------------------------------------------------------------

    def _anki_jobs(self):
        """The single-worker job layer, built on first use.

        A plain attribute so a test can inspect or replace it. ``current_user_id``
        is read at poll time from whatever profile is open *then*, so a job
        started under one profile cannot finish into another.
        """
        jobs = getattr(self, '_anki_jobs_obj', None)
        if jobs is None:
            from app.anki.jobs import AnkiJobs
            jobs = AnkiJobs(current_user_id=lambda: getattr(self.user_db, 'user_id', None)
                            if self.user_db is not None else None)
            self._anki_jobs_obj = jobs
        return jobs

    def teardownAnki(self) -> None:  # noqa: N802 (named like the other teardowns)
        """Stop the worker and drop uncollected jobs. Called from ``closeEvent``.

        Not a slot: the shutdown path is Qt's, not the page's.
        """
        jobs = getattr(self, '_anki_jobs_obj', None)
        if jobs is not None:
            try:
                jobs.shutdown()
            except Exception as e:  # noqa: BLE001 - close must not raise
                self._log_error(f'teardownAnki failed: {e}')
            self._anki_jobs_obj = None

    def _anki_device(self) -> Dict[str, Any]:
        settings = self.user_db.get_device_settings()
        return {'enabled': bool(settings.anki_integration_enabled),
                'port': int(settings.ankiconnect_port or 8765)}

    def _anki_client_factory(self, port: int):
        """A factory the worker calls. Captures the port, never the database."""
        def factory():
            from app.anki.client import AnkiConnectClient
            return AnkiConnectClient(port)
        return factory

    # ------------------------------------------------------------------
    # Status and settings
    # ------------------------------------------------------------------

    @pyqtSlot(result=str)
    @instrumented_slot
    def getAnkiStatus(self) -> str:
        """``{enabled, port}`` for this device. Reads nothing from Anki."""
        if not self.user_db:
            return serialize_response(False, error=_NO_DB)
        try:
            return serialize_response(True, data=self._anki_device())
        except Exception as e:
            self._log_error(f'getAnkiStatus failed: {e}')
            return serialize_response(False, error=str(e))

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getAnkiTemplates(self, exam_context_id: int) -> str:
        """This profile's search templates; ``0`` means every exam."""
        if not self.user_db:
            return serialize_response(False, error=_NO_DB)
        try:
            return serialize_response(
                True, data=self.user_db.anki_get_templates(exam_context_id or None))
        except Exception as e:
            self._log_error(f'getAnkiTemplates failed: {e}')
            return serialize_response(False, error=str(e))

    @pyqtSlot(int, int, str, result=str)
    @instrumented_slot
    def addAnkiTemplate(self, exam_context_id: int, question_source_id: int,
                        template: str) -> str:
        if not self.user_db:
            return serialize_response(False, error=_NO_DB)
        try:
            return serialize_response(True, data=self.user_db.anki_add_template(
                exam_context_id, question_source_id, template))
        except AnkiDataError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(f'addAnkiTemplate failed: {e}')
            return serialize_response(False, error=str(e))

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def updateAnkiTemplate(self, template_id: int, template: str) -> str:
        if not self.user_db:
            return serialize_response(False, error=_NO_DB)
        try:
            return serialize_response(
                True, data=self.user_db.anki_update_template(template_id, template))
        except AnkiDataError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(f'updateAnkiTemplate failed: {e}')
            return serialize_response(False, error=str(e))

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def removeAnkiTemplate(self, template_id: int) -> str:
        if not self.user_db:
            return serialize_response(False, error=_NO_DB)
        try:
            self.user_db.anki_remove_template(template_id)
            return serialize_response(True, data={'removed': template_id})
        except AnkiDataError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(f'removeAnkiTemplate failed: {e}')
            return serialize_response(False, error=str(e))

    # ------------------------------------------------------------------
    # Field visibility
    # ------------------------------------------------------------------

    @pyqtSlot(result=str)
    @instrumented_slot
    def getAnkiFieldSettings(self) -> str:
        """Every cached note type with its fields in Anki's order, and which are shown.

        A field with no visibility row is shown: a student who has never
        touched the setting sees every field rather than none.
        """
        if not self.user_db:
            return serialize_response(False, error=_NO_DB)
        try:
            visibility = self.user_db.anki_get_field_visibility()
            types = [{'model_name': model,
                      'fields': [{'name': name,
                                  'visible': visibility.get(model, {}).get(name, True)}
                                 for name in names]}
                     for model, names in self.user_db.anki_get_note_types().items()]
            return serialize_response(True, data={'note_types': types})
        except Exception as e:
            self._log_error(f'getAnkiFieldSettings failed: {e}')
            return serialize_response(False, error=str(e))

    @pyqtSlot(str, str, bool, result=str)
    @instrumented_slot
    def setAnkiFieldVisibility(self, model_name: str, field_name: str, visible: bool) -> str:
        if not self.user_db:
            return serialize_response(False, error=_NO_DB)
        try:
            self.user_db.anki_set_field_visibility(model_name, field_name, bool(visible))
            return serialize_response(True, data={'model_name': model_name,
                                                  'field_name': field_name,
                                                  'visible': bool(visible)})
        except AnkiDataError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(f'setAnkiFieldVisibility failed: {e}')
            return serialize_response(False, error=str(e))

    # ------------------------------------------------------------------
    # Relevance verdicts (#784 Wave 5) -- the student's answers, no Anki
    # ------------------------------------------------------------------

    # ``card_id`` is declared ``qint64``, never ``int``: an Anki card id is a
    # millisecond timestamp (~1.7e12), and a Qt ``int`` is 32 bits, so
    # QWebChannel kept only the low 32 bits and every real card was refused
    # as "not this entry's" (#813). WIMI's own row ids stay ``int``.
    @pyqtSlot(int, 'qint64', str, result=str)
    @instrumented_slot
    def setAnkiCardVerdict(self, entry_id: int, card_id: int, verdict: str) -> str:
        """``confirmed`` (show it first), ``not_for_entry`` (stop proposing
        it here) or ``clear``. Returns the entry's refreshed payload."""
        if not self.user_db:
            return serialize_response(False, error=_NO_DB)
        try:
            self.user_db.anki_set_verdict(entry_id, card_id,
                                          None if verdict == 'clear' else verdict)
            return serialize_response(True, data=self._anki_entry_payload(entry_id))
        except AnkiDataError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(f'setAnkiCardVerdict failed: {e}', {'entry_id': entry_id})
            return serialize_response(False, error=str(e))

    # qint64, not int: see setAnkiCardVerdict (#813).
    @pyqtSlot(int, 'qint64', result=str)
    @instrumented_slot
    def rejectAnkiCardForSubjects(self, entry_id: int, card_id: int) -> str:
        """Never propose this card again for the subjects whose words
        proposed it on this entry. The subjects are worked out here from the
        live proposal, never taken from the page."""
        if not self.user_db:
            return serialize_response(False, error=_NO_DB)
        try:
            proposal = next((p for p in self._anki_entry_payload(entry_id).get('proposals', [])
                             if p['card_id'] == card_id), None)
            if proposal is None:
                raise AnkiDataError('That card is not being proposed on this entry any more')
            self.user_db.anki_reject_for_subjects(entry_id, card_id, proposal['subject_ids'])
            return serialize_response(True, data=self._anki_entry_payload(entry_id))
        except AnkiDataError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(f'rejectAnkiCardForSubjects failed: {e}', {'entry_id': entry_id})
            return serialize_response(False, error=str(e))

    # ------------------------------------------------------------------
    # The entry's cached stats -- no Anki involved
    # ------------------------------------------------------------------

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getAnkiEntryStats(self, entry_id: int) -> str:
        """What the cache holds for one entry, shaped for the page.

        Always answers from the cache, so it is safe to call on page load.
        ``stale`` tells the page whether to start a ``refresh_entry`` job;
        ``matchable`` false carries the sentence that says why this entry
        cannot be looked up (no bank, no question id).
        """
        if not self.user_db:
            return serialize_response(False, error=_NO_DB)
        try:
            return serialize_response(True, data=self._anki_entry_payload(entry_id))
        except Exception as e:
            self._log_error(f'getAnkiEntryStats failed: {e}', {'entry_id': entry_id})
            return serialize_response(False, error=str(e))

    def _anki_entry_payload(self, entry_id: int) -> Dict[str, Any]:
        from app.anki.fields import field_to_text
        from app.anki.fsrs import estimate

        device = self._anki_device()
        prefs = self.user_db.get_preferences()
        base = {'enabled': device['enabled'], 'display_mode': prefs.anki_display_mode}
        try:
            cache = self.user_db.anki_get_entry_cache(entry_id)
        except AnkiDataError as e:
            return dict(base, matchable=False, reason=str(e))

        visibility = self.user_db.anki_get_field_visibility()
        now_ms = int(time.time() * 1000)
        cards = []
        for card in cache['cards']:
            shown = visibility.get(card.get('model_name') or '', {})
            fields = []
            for f in card['fields']:
                rendered = field_to_text(f.get('field_value') or '')
                fields.append({'name': f['field_name'], 'text': rendered.text,
                               'images': rendered.images,
                               'visible': shown.get(f['field_name'], True)})
            log = [{'id': r['review_id_ms'], 'ivl': r['ivl'], 'factor': r['factor'],
                    'time': r['time_ms']} for r in card['reviews']]
            cards.append({
                'card_id': card['card_id'], 'note_id': card['note_id'],
                'deck_name': card['deck_name'], 'model_name': card['model_name'],
                'interval': card['interval'], 'due': card['due'], 'reps': card['reps'],
                'lapses': card['lapses'], 'queue': card['queue'],
                'suspended': card['queue'] == _SUSPENDED_QUEUE,
                'card_type': card['card_type'], 'ord': card['card_ord'],
                # Labelled "estimated" by the page; owner decision 11.
                'estimate': estimate(log, now_ms).to_dict(),
                'fields': fields,
            })
        match = cache['match']
        return dict(
            base, matchable=True,
            has_templates=bool(cache['templates']),
            synced=match is not None,
            last_synced_at=match['last_synced_at'] if match else None,
            stale=self.user_db.anki_match_is_stale(match),
            **self._anki_relevance(entry_id, cards),
        )

    def _anki_relevance(self, entry_id: int, cards: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Order the cards and propose the likely ones (#784 Wave 5).

        A card the student confirmed for this entry comes first; nothing else
        moves. Proposals come from ``app.anki.relevance``'s lexical scorer and
        never include a card already answered about on this entry.
        """
        from app.anki.relevance import proposals_for

        verdicts = self.user_db.anki_get_verdicts(entry_id)
        terms = self.user_db.anki_relevance_terms(entry_id)
        rejected = self.user_db.anki_subject_rejections(s['id'] for s in terms['subjects'])
        for card in cards:
            card['confirmed'] = verdicts.get(card['card_id']) == 'confirmed'
        ordered = sorted(cards, key=lambda c: 0 if c['confirmed'] else 1)  # stable
        return {'cards': ordered,
                'proposals': proposals_for(terms, cards, verdicts, rejected)}

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------

    @pyqtSlot(str, str, result=str)
    @instrumented_slot
    def startAnkiJob(self, kind: str, params_json: str) -> str:
        """Begin one conversation with Anki on the worker. Returns ``{job_id}``.

        The database is read here, inline, so a refusal (feature off, no
        template, a card id not from this entry) is a sentence now rather
        than a failed job later.
        """
        if kind not in JOB_KINDS:
            return serialize_response(
                False, error=f"Unknown Anki job {kind!r}; expected one of {', '.join(JOB_KINDS)}")
        try:
            params = json.loads(params_json) if params_json else {}
            if not isinstance(params, dict):
                raise ValueError('params must be a JSON object')
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            return serialize_response(False, error=f'Invalid Anki job params: {e}')

        if kind == 'ping':
            try:
                port = self._anki_ping_port(params)
                if isinstance(port, str):
                    return serialize_response(False, error=port)
                job_id = self._anki_jobs().start(
                    lambda client: {'version': client.version()},
                    client_factory=self._anki_client_factory(port),
                    context={'kind': kind})
            except Exception as e:
                # The saved port is a database read (#800 review).
                self._log_error(f'startAnkiJob(ping) failed: {e}')
                return serialize_response(False, error=str(e))
            return serialize_response(True, data={'job_id': job_id})

        if not self.user_db:
            return serialize_response(False, error=_NO_DB)
        try:
            device = self._anki_device()
            if not device['enabled']:
                return serialize_response(
                    False, error='Anki is switched off on this computer; turn it on in '
                                 'Settings, Anki')
            prepared = getattr(self, f'_anki_prepare_{kind}')(params)
        except (AnkiDataError, ValidationError, ValueError) as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(f'startAnkiJob({kind}) failed: {e}')
            return serialize_response(False, error=str(e))

        work, finish = prepared
        try:
            job_id = self._anki_jobs().start(
                work, finish=finish,
                client_factory=self._anki_client_factory(device['port']),
                context={'kind': kind, **{k: params[k] for k in ('entry_id', 'exam_context_id')
                                          if k in params}},
                user_id=self.user_db.user_id)
        except Exception as e:
            # A pool that has been shut down refuses new work (#802 review 2).
            self._log_error(f'startAnkiJob({kind}) could not start: {e}')
            return serialize_response(False, error=str(e))
        return serialize_response(True, data={'job_id': job_id})

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def pollAnkiJob(self, job_id: str) -> str:
        """Where a job has got to. The finish phase runs inside this call."""
        try:
            jobs = self._anki_jobs()
            report = jobs.poll(str(job_id))
            if report.get('state') in ('done', 'failed'):
                # Collected: the page has its answer and runAnkiJob stops
                # polling, so keeping the report would hold a refresh's whole
                # payload for the session (#800 review).
                jobs.forget(str(job_id))
        except Exception as e:
            self._log_error(f'pollAnkiJob failed: {e}', {'job_id': job_id})
            return serialize_response(False, error=str(e))
        return serialize_response(True, data=report)

    # -- ping -------------------------------------------------------------

    def _anki_ping_port(self, params):
        """The port to ping: an explicit one (Settings' Test connection, before
        saving) or this device's saved one. Returns a sentence on refusal."""
        port = params.get('port')
        if port is None:
            if not self.user_db:
                return 8765
            return self._anki_device()['port']
        if isinstance(port, bool) or not isinstance(port, int) or not 1000 <= port <= 65535:
            return 'The AnkiConnect port must be a number from 1000 to 65535'
        return port

    # -- refresh_entry ----------------------------------------------------

    def _anki_prepare_refresh_entry(self, params):
        key = self.user_db.anki_question_key_for_entry(_as_int(params, 'entry_id'))
        work = self._anki_fetch_work([self._anki_searches_for(key)])
        entry_id = key['entry_id']

        def finish(results):
            (fetched,) = results['fetched']
            self.user_db.anki_record_refresh(fetched['key'], cards=fetched['cards'],
                                             reviews=fetched['reviews'])
            return self._anki_entry_payload(entry_id)
        return work, finish

    # -- sync_exam --------------------------------------------------------

    def _anki_prepare_sync_exam(self, params):
        exam_id = _as_int(params, 'exam_context_id')
        keys = self.user_db.anki_question_keys_for_exam(exam_id)
        plans, skipped = [], []
        for key in keys:
            try:
                plans.append(self._anki_searches_for(key))
            except AnkiDataError as e:
                skipped.append({'question_id': key['question_id'], 'reason': str(e)})
        work = self._anki_fetch_work(plans, stop_on_unavailable=True)

        def finish(results):
            # Record every question that completed, even if Anki went away
            # part-way: those answers are real. Nothing is recorded for the
            # rest, so a closed Anki never reads as "no cards" (finding 1).
            for fetched in results['fetched']:
                self.user_db.anki_record_refresh(fetched['key'], cards=fetched['cards'],
                                                 reviews=fetched['reviews'])
            return {'questions': len(keys), 'synced': len(results['fetched']),
                    'skipped': skipped + results['skipped'],
                    'stopped': results['stopped']}
        return work, finish

    # -- the fetch both of the above share --------------------------------

    def _anki_searches_for(self, key: Dict[str, Any]) -> Dict[str, Any]:
        """One question's searches, built on this thread. Refuses with a
        sentence when the bank has no template or the id cannot be searched."""
        from app.anki.client import build_search
        from app.anki.errors import AnkiError

        templates = self.user_db.anki_templates_for(key['exam_context_id'],
                                                    key['question_source_id'])
        if not templates:
            raise AnkiDataError('This question bank has no Anki search template yet; add '
                                'one in Settings, Anki')
        try:
            searches = [build_search(t, key['question_id']) for t in templates]
        except AnkiError as e:
            raise AnkiDataError(e.detail or str(e)) from e
        return {'key': dict(key), 'searches': searches}

    @staticmethod
    def _anki_fetch_work(plans: List[Dict[str, Any]], *, stop_on_unavailable: bool = False):
        """The worker closure: plain data in, plain data out, a client only."""
        def work(client):
            from app.anki.errors import AnkiError, AnkiErrorKind

            fetched, skipped, stopped = [], [], None
            for plan in plans:
                try:
                    ids: List[int] = []
                    for search in plan['searches']:
                        for card_id in client.find_cards(search):
                            if card_id not in ids:
                                ids.append(card_id)
                    cards = client.cards_info(ids)
                    reviews = client.reviews_of_cards(ids)
                except AnkiError as e:
                    if not stop_on_unavailable:
                        raise
                    if e.kind is AnkiErrorKind.UNAVAILABLE:
                        stopped = e.to_dict()
                        break
                    skipped.append({'question_id': plan['key']['question_id'],
                                    'reason': e.detail or e.kind.value})
                    continue
                fetched.append({'key': plan['key'], 'cards': cards, 'reviews': reviews})
            if stopped is not None and not fetched:
                raise AnkiError(AnkiErrorKind.UNAVAILABLE, stopped.get('detail', ''))
            return {'fetched': fetched, 'skipped': skipped, 'stopped': stopped}
        return work

    # -- suspend / unsuspend ----------------------------------------------

    def _anki_prepare_suspend(self, params):
        return self._anki_prepare_suspension(params, suspend=True)

    def _anki_prepare_unsuspend(self, params):
        return self._anki_prepare_suspension(params, suspend=False)

    def _anki_prepare_suspension(self, params, *, suspend: bool):
        entry_id = _as_int(params, 'entry_id')
        card_ids = params.get('card_ids')
        if not isinstance(card_ids, list) or not card_ids or not all(
                isinstance(c, int) and not isinstance(c, bool) for c in card_ids):
            raise AnkiDataError('Choose at least one card')
        allowed = set(self.user_db.anki_entry_card_ids(entry_id))
        foreign = [c for c in card_ids if c not in allowed]
        if foreign:
            # The page may only name cards this entry's match found. The plugin
            # took ids from the page as given, so any card in the collection
            # could be suspended from any entry.
            raise AnkiDataError("Those cards are not this entry's; refresh the entry and "
                                'try again')
        ids = list(card_ids)

        def work(client):
            from app.anki.errors import AnkiError
            if suspend:
                client.suspend(ids)
                return {'ids': ids, 'queues': {}}
            client.unsuspend(ids)
            # Anki restores each card's own queue (learning, review, ...),
            # not 0, so read it back rather than guess (#800 review).
            try:
                queues = {c['cardId']: c['queue'] for c in client.cards_info(ids)
                          if isinstance(c.get('cardId'), int)
                          and isinstance(c.get('queue'), int)}
            except AnkiError:
                queues = {}
            return {'ids': ids, 'queues': queues}

        def finish(done):
            if suspend:
                self.user_db.anki_set_card_queue(done['ids'], _SUSPENDED_QUEUE)
            else:
                self.user_db.anki_restore_card_queues(done['ids'], done['queues'])
            return self._anki_entry_payload(entry_id)
        return work, finish

    # -- save_image -------------------------------------------------------

    def _anki_card_image(self, params):
        """``(entry_id, filename)`` once the name is one of this entry's
        cards' images; a sentence otherwise. Shared by save and view."""
        from app.anki.fields import field_to_text, is_media_filename

        entry_id = _as_int(params, 'entry_id')
        filename = params.get('filename')
        if not isinstance(filename, str) or not is_media_filename(filename):
            raise AnkiDataError('That is not an Anki image file name')
        cache = self.user_db.anki_get_entry_cache(entry_id)
        shown = {img for card in cache['cards'] for f in card['fields']
                 for img in field_to_text(f.get('field_value') or '').images}
        if filename not in shown:
            # Only an image one of this entry's cards actually shows may be
            # fetched, so the page cannot read arbitrary files out of Anki's
            # media folder.
            raise AnkiDataError("That image is not on any of this entry's cards")
        return entry_id, filename

    def _anki_prepare_view_image(self, params):
        """Fetch one card image for the entry page's lightbox. Nothing is
        written; the bytes go to the page as a data URL, like attachments."""
        _, filename = self._anki_card_image(params)

        def work(client):
            return client.retrieve_media_file(filename)

        def finish(data: Optional[bytes]):
            if data is None:
                raise AnkiDataError("Anki no longer has that image in its media folder")
            mime = _image_mime(data)
            if mime is None:
                raise AnkiDataError("That file is not an image WIMI can show")
            return {'filename': filename,
                    'data_url': f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"}
        return work, finish

    def _anki_prepare_save_image(self, params):
        entry_id, filename = self._anki_card_image(params)
        media_manager = getattr(self, 'media_manager', None)
        if media_manager is None:
            raise AnkiDataError('Images cannot be saved: the media store is not available')
        existing = {m.original_filename for m in self.user_db.get_entry_media_list(entry_id)}
        if filename in existing:
            raise AnkiDataError('That image is already attached to this entry')

        def work(client):
            return client.retrieve_media_file(filename)

        def finish(data: Optional[bytes]):
            if data is None:
                raise AnkiDataError("Anki no longer has that image in its media folder")
            # MIME from the bytes, not the name (the plugin guessed from the
            # extension); a type the media store refuses is a ValueError,
            # reported as a failure rather than as "saved".
            info = media_manager.save_media_from_base64(
                entry_id=entry_id, base64_data=base64.b64encode(data).decode('ascii'),
                original_filename=filename, mime_type=None)
            media = self.user_db.add_entry_media(
                entry_id=entry_id, file_uuid=info.file_uuid,
                original_filename=info.original_filename, mime_type=info.mime_type,
                file_size_bytes=info.file_size)
            return {'media_id': media.id, 'original_filename': info.original_filename}
        return work, finish


def _image_mime(data: bytes) -> Optional[str]:
    for signature, mime in _IMAGE_SIGNATURES:
        if data.startswith(signature):
            return mime
    if len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    return None


def _as_int(params: Dict[str, Any], name: str) -> int:
    value = params.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise AnkiDataError(f'{name} must be a number')
    return value
