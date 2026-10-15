"""Regression: a search template typed in Settings -> Anki is still there after
the page is reloaded, under the bank it was added to and no other.

Templates are per (exam, bank) -- owner decision 7 on #784 -- so the scenario
seeds two banks and asserts the template lands in one block, is written to the
database against that bank, and is drawn back into the same block on a fresh
document. It also adds a template with no ``{{qid}}`` and expects the
database's refusal to reach the student as a sentence, with nothing written.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json

import pytest

from _helpers.anki_settings import open_panel, poll, poll_true
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

TPL = 'tag:Bank::{{qid}}'


def _block(source_id: int) -> str:
    return f"document.querySelector('.anki-bank[data-source-id=\"{source_id}\"]')"


def _templates_in(wimi_page: WimiPage, source_id: int) -> list[str]:
    return json.loads(wimi_page.eval_js(
        f"JSON.stringify(Array.from({_block(source_id)}"
        ".querySelectorAll('input[data-template-id]')).map(i => i.value))"))


def _type_and_add(wimi_page: WimiPage, source_id: int, text: str) -> None:
    wimi_page.eval_js(
        f"(() => {{ const i = {_block(source_id)}.querySelector('input:not([data-template-id])');"
        f" i.value = {json.dumps(text)}; }})()")
    wimi_page.locator(
        css=f'.anki-bank[data-source-id="{source_id}"] .btn-primary').click()


@pytest.mark.slow
@pytest.mark.regression
def test_a_template_survives_a_reload_under_its_own_bank(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name='Step X')
    bank = db.create_question_source(source_name='Bank', exam_context='Step X')
    other = db.create_question_source(source_name='Other', exam_context='Step X')
    open_panel(wimi_page, banks=2)

    # ---- Act: add a template to the first bank
    _type_and_add(wimi_page, bank.id, TPL)
    assert poll(wimi_page, f"JSON.stringify(Array.from({_block(bank.id)}"
                           ".querySelectorAll('input[data-template-id]')).map(i => i.value))",
                json.dumps([TPL])) == json.dumps([TPL]), 'Template row never appeared'
    stored = db.anki_get_templates(exam.id)
    assert [(t['question_source_id'], t['template']) for t in stored] == [(bank.id, TPL)]

    # ---- Act: a template with no {{qid}} is refused with a sentence, nothing written
    _type_and_add(wimi_page, other.id, 'tag:Other')
    status = f"{_block(other.id)}.querySelector('[role=status]')"
    assert poll_true(wimi_page, f"{status}.classList.contains('is-error')"
                                f" && {status}.textContent.length > 0")
    assert len(db.anki_get_templates(exam.id)) == 1

    # ---- Assert: a fresh document draws it back in the same block only
    open_panel(wimi_page, banks=2)
    assert _templates_in(wimi_page, bank.id) == [TPL]
    assert _templates_in(wimi_page, other.id) == []
    assert not wimi_page.eval_js("document.getElementById('anki-sync-exam').disabled"), \
        'Fetch stayed disabled although the exam now has a template'
