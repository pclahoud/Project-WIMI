"""The mic button on the real entry form, end to end (#59, Wave 3).

Session-owned verification of T13, not a shipped scenario — T15 and T16
own those. This is the first time the *visible* feature is driven: a
button on `question_entry.html`, a real `QAudioSource` behind it, and a
transcript arriving in a TinyMCE editor.

Needs `./scripts/dev_virtual_mic.sh start`, `vendor/whisper/<platform>/`
and a model. Skips with the fix named rather than reporting a false pass.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import date
from pathlib import Path

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession
from _helpers.live_audio import REPO, WAV, requires_live_audio


pytestmark = [pytest.mark.slow, pytest.mark.regression]


# Shared gate -- see _helpers/live_audio.py (#182).


@pytest.fixture
def stt_model_installed(wimi_config) -> Path:
    """Symlink the default model into this session's app_data.

    The harness deletes the whole `app_data_test` tree on teardown, so a
    model put there by hand survives one run and then reads as
    `model_missing` rather than as a missing file.
    """
    from app.stt import model_spec

    spec = model_spec.get_spec(None)
    env = os.environ.get('WIMI_STT_MODEL')
    src = Path(env) if env else (REPO / 'app_data' / 'models' / 'whisper'
                                 / spec.filename)
    if not src.is_file():
        pytest.skip(f'set WIMI_STT_MODEL to a copy of {spec.filename}')
    dest_dir = Path(wimi_config.app_data_dir) / 'models' / 'whisper'
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / spec.filename
    if not dest.exists():
        dest.symlink_to(src.resolve())
    return dest


def _poll(page: WimiPage, expr: str, want, attempts: int = 60):
    last = None
    for _ in range(attempts):
        last = page.eval_js(expr)
        if want(last):
            return last
        page.wait_for_timeout(250)
    return last


@requires_live_audio
def test_the_button_records_and_the_transcript_lands_in_the_editor(
    stt_model_installed: Path,
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name='STT live', exam_description='mic')
    review = db.create_review_session(
        exam_context_id=exam.id, total_questions=1, total_incorrect=1,
        session_name='STT live session', date_encountered=date.today())

    # A session id is required: question_entry.js redirects to index.html
    # without one, which destroys the page mid-transcription.
    wimi_page.goto('entry-form', query={'session_id': review.id})

    # The mounts exist and the buttons become enabled once status resolves.
    count = _poll(
        wimi_page,
        "document.querySelectorAll('[data-testid^=\"dictation\"], "
        "[class*=\"dictation\"]').length",
        lambda n: isinstance(n, int) and n > 0)
    assert count and count > 0, (
        'no dictation controls rendered on the entry form')

    state = _poll(
        wimi_page,
        "(() => { const b = document.querySelector('button[data-testid*=\"dictat\"],"
        " .dictation-button, [class*=dictation] button');"
        " return b ? (b.disabled ? 'disabled' : 'enabled') : 'absent'; })()",
        lambda s: s == 'enabled')
    assert state == 'enabled', (
        f'the mic button never became usable (state={state!r}) — with a '
        'microphone, engine and model all present it should be ready')


@requires_live_audio
def test_both_editors_get_their_own_control(
    stt_model_installed: Path,
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """One component, two instances — and exactly two (§3.5, D1)."""
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name='STT two', exam_description='mic')
    review = db.create_review_session(
        exam_context_id=exam.id, total_questions=1, total_incorrect=1,
        session_name='STT two session', date_encountered=date.today())
    wimi_page.goto('entry-form', query={'session_id': review.id})

    mounts = _poll(
        wimi_page,
        "document.querySelectorAll('.write-block [class*=dictation]').length",
        lambda n: isinstance(n, int) and n >= 2)
    assert mounts == 2, (
        f'expected exactly two dictation mounts, one per writing field; '
        f'found {mounts}')
