"""Regression: press, propose, confirm and reject, against the real model (#60).

The inverse of ``test_relations_are_silent_when_unavailable.py``. That file
needs a machine that *cannot* extract; this one needs a machine that can --
a venv carrying the relations runtime (torch, transformers, gliner2, peft)
and the pinned GLiNER2 weights. Where either is missing it **skips, naming
which**, rather than failing: the absence of the runtime is the other
scenario's fixture, not a defect.

What this is and is not evidence of
-----------------------------------
:data:`EXPLANATION` is a fixed own-words paragraph chosen so the model's
output is deterministic, and the assertions are on the **specific pairs it
produces**. That makes this a test of the mechanism -- the press, the cards,
what each answer writes, and what the next press does with it. **It is not
precision evidence.** Which corpus counts for that is #60's acceptance
criterion and the owner's call; three sentences written to be readable are
not that corpus. The two rejections below are applied to whichever card the
test needs to exercise a kind on, not as a judgement of the model.

Measured on the MacBook Air (M-series, macOS 26, torch 2.14.1, 2026-10-05):
the three proposals came back identically on every pass; the first pass of a
process loads the model in ~7.5 s and later passes take ~0.13 s.

Where the model comes from
--------------------------
``<app_data_dir>/models/gliner2/`` is where WIMI looks, under ``--test-mode``
as anywhere else, and ``app_data_test/`` is created fresh for a run. So the
fixture **links** the eight pinned files into it from a local copy instead of
downloading 845 MB per run, and removes the links afterwards -- the silence
scenario shares ``app_data_test/`` within a session and must not find a model
there. **It removes only what it created.** That directory is also where
Settings' download button installs under ``--test-mode``, so a real model may
already be there; any file already present is used as-is and never touched,
and teardown unlinks the fixture's own symlinks rather than ``rmtree``-ing the
directory (an 845 MB deletion caught in #389's review). The source is ``WIMI_RELATIONS_MODEL_DIR`` if set, else the Hugging Face
cache snapshot **at the pinned revision**. A different revision would pass the
size check Settings uses and fail the hash check at first press, so only the
pinned snapshot directory is ever looked at.

The positive control comes first
--------------------------------
As in the silence scenario: the module is loaded, its attach ran, and the
controller exists -- read through the bare ``EntryState`` name, because it is
a script-scope ``const`` and ``window.EntryState`` is ``undefined`` without an
error. Then the bridge is asked for its state; a ``ready`` page with no button
is a failure here, not a skip.
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import date
from pathlib import Path

import pytest

from _helpers.page_gate import wait_for_release
from _helpers.w114_form_ready import centre_of, poll, real_click
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from app.relation_extraction import model_spec

#: Own words, one relation per sentence. The model returns exactly
#: :data:`EXPECTED` for it (see the module docstring).
EXPLANATION = (
    '<p>I picked the wrong answer. Hypertension is a risk factor for stroke. '
    'Metformin treats diabetes mellitus. Lactic acidosis is a complication '
    'of metformin.</p>'
)

SUBJECTS = (
    'Hypertension', 'Stroke', 'Diabetes mellitus', 'Metformin',
    'Lactic acidosis',
)

CONFIRM = ('Hypertension', 'risk factor for', 'Stroke')
MISREAD = ('Metformin', 'treats', 'Diabetes mellitus')
UNRELATED = ('Lactic acidosis', 'complication of', 'Metformin')
EXPECTED = {CONFIRM, MISREAD, UNRELATED}

#: The first press of a process loads 845 MB of weights.
FIRST_PASS_MS = 120_000

FIND = '[data-testid="entry-form-relations-find"]'

#: Runtime-absent states. Anything else that is not ``ready`` once the model is
#: linked is a failure: ``runtime_broken`` is exactly the #364 class of bug
#: this scenario exists to catch, and must not be skipped past.
RUNTIME_ABSENT = {'dev_runtime_missing', 'not_in_this_build'}

POSITIVE_CONTROL = """
(() => JSON.stringify({
  module_loaded: typeof window.attachRelationProposals === 'function',
  controller_attached: typeof EntryState !== 'undefined'
    && !!EntryState.relationProposals,
  entry_id: (typeof EntryState !== 'undefined' && EntryState.currentEntry)
    ? EntryState.currentEntry.id : null,
}))()
"""

ASK_STATUS = """
(() => {
  window.__relStatus = null;
  window.api.getRelationExtractionStatus()
    .then(s => { window.__relStatus = JSON.stringify(s); })
    .catch(e => { window.__relStatus = JSON.stringify({error: String(e)}); });
  return 'asked';
})()
"""

CARDS = """
(() => JSON.stringify(Array.from(document.querySelectorAll(
    '[data-testid="entry-form-relation-proposal"]')).map(card => {
  const select = card.querySelector('[data-testid="entry-form-relation-type"]');
  return {
    relation_id: Number(card.getAttribute('data-relation-id')),
    pair: card.querySelector('.relprop-pair').textContent,
    has_select: !!select,
    reason: card.querySelector('[data-testid="entry-form-relation-reason"]').value,
  };
})))()
"""

PENDING_NOTES = """
(() => JSON.stringify(Array.from(document.querySelectorAll(
    '[data-testid="entry-form-relations-pending"]')).map(note => ({
  entry_id: Number(note.getAttribute('data-entry-id')),
  text: note.textContent,
  controls: note.querySelectorAll('button, select, textarea').length,
}))))()
"""

#: Settled: not running, and either cards, a note or a failure is drawn.
SETTLED = """
(() => {
  const find = document.querySelector('%s');
  if (!find || find.textContent !== 'Find related topics') return false;
  return !!document.querySelector(
    '[data-testid="entry-form-relation-proposal"],'
    + '[data-testid="entry-form-relations-note"],'
    + '[data-testid="entry-form-relations-failure"]');
})()
""" % FIND


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------


def _model_source() -> Path | None:
    """A local directory holding the pinned files, or ``None``."""
    explicit = os.environ.get('WIMI_RELATIONS_MODEL_DIR')
    if explicit:
        return Path(explicit)
    hub = Path(os.environ.get('HF_HUB_CACHE') or (
        Path(os.environ.get('HF_HOME', Path.home() / '.cache' / 'huggingface'))
        / 'hub'))
    snapshot = (hub / ('models--' + model_spec.MODEL_REPO.replace('/', '--'))
                / 'snapshots' / model_spec.MODEL_REVISION)
    return snapshot if snapshot.is_dir() else None


def _app_data_dir(session: WimiTestSession) -> Path:
    """Absolute, the way ``process.py`` hands it to WIMI."""
    path = Path(session.config.app_data_dir)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[3] / path
    return path


def _place(src: Path, dst: Path) -> str:
    """Make ``src`` readable at ``dst`` without copying 845 MB if avoidable.

    **A symlink is not available to an ordinary Windows account**, and that is
    measured rather than anticipated: on `Windows machine B` every test in this
    file ERRORed at setup with

        OSError: [WinError 1314] A required privilege is not held by the client

    because `SeCreateSymbolicLinkPrivilege` needs an elevated account or
    Developer Mode. So the whole file was unreachable on Windows -- not failing
    on a product defect, simply never reaching its body.

    Three mechanisms, cheapest first:

    * **symlink** -- costs nothing, and is what POSIX gets;
    * **hard link** -- needs no privilege, so it is the Windows answer, but
      only works within one volume. Safe against the HF cache: unlinking one
      name leaves the file alive while any other name remains, which is what
      a hard link *is*;
    * **copy** -- the cross-volume fallback, and the only one that spends
      845 MB and the time to write it.

    Each result is an ordinary directory entry the teardown can `unlink()`,
    so "remove only what we created" holds whichever branch ran.

    Returns:
        ``'symlink'``, ``'hardlink'`` or ``'copy'``, so a run says which
        mechanism it used instead of leaving it to be guessed from timing.
    """
    try:
        dst.symlink_to(src)
        return 'symlink'
    except (OSError, NotImplementedError):
        pass
    try:
        os.link(src, dst)
        return 'hardlink'
    except OSError:
        pass
    shutil.copyfile(src, dst)
    return 'copy'


@pytest.fixture
def relations_ready(wimi_session: WimiTestSession):
    """Make the pinned weights present in this run's app data, then undo ONLY that.

    **This fixture must never delete a model it did not put there.**
    ``<app_data_dir>/models/gliner2`` is a real install location under
    ``--test-mode`` too -- Settings' download button writes there -- so a
    student-shaped model may already be sitting in it. A file that is already
    present is left exactly as it is, and the teardown removes only the entries
    this fixture created, in reverse order, never with ``rmtree``. A run that
    stops part-way through therefore removes what it made and nothing else.

    How each file gets there is :func:`_place`'s business, and it is **not
    always a symlink** -- Windows refuses those without privilege. The teardown
    does not care, because all three mechanisms produce something `unlink()`
    removes.
    """
    app_data = _app_data_dir(wimi_session)
    target = model_spec.model_dir(app_data, create=False)
    created_files: list[Path] = []
    created_dirs: list[Path] = []
    mechanisms: set[str] = set()
    try:
        if model_spec.missing_files(app_data):
            source = _model_source()
            if source is None:
                pytest.skip('no local copy of the GLiNER2 weights at revision '
                            f'{model_spec.MODEL_REVISION[:12]}; set '
                            'WIMI_RELATIONS_MODEL_DIR to a directory holding '
                            'them')
            for name in model_spec.MODEL_FILES:
                dst = target / name
                if dst.exists() or dst.is_symlink():
                    continue  # not ours: never replaced, never removed
                src = (source / name).resolve()
                if not src.is_file():
                    pytest.skip(f'{source} has no {name}')
                missing_parents = [d for d in reversed(dst.parents)
                                   if not d.exists()]
                for directory in missing_parents:
                    directory.mkdir()
                    created_dirs.append(directory)
                mechanisms.add(_place(src, dst))
                created_files.append(dst)
            if mechanisms:
                print(f'[relations_ready] placed {len(created_files)} file(s) '
                      f'by {"/".join(sorted(mechanisms))}')
        # The cheap check Settings uses. The hash check runs in WIMI before
        # the model is built, and a wrong file fails the first press loudly.
        assert not model_spec.missing_files(app_data), (
            f'the model directory holds files of the wrong size for the pin: '
            f'{model_spec.missing_files(app_data)}')
        yield app_data
    finally:
        for placed in reversed(created_files):
            placed.unlink(missing_ok=True)
        for directory in reversed(created_dirs):
            try:
                directory.rmdir()  # only if empty: anything else is not ours
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Seeding and driving
# ---------------------------------------------------------------------------


def _seed(db, *, entries: int = 1) -> dict:
    exam = db.create_exam_context(
        exam_name='Proposals Exam',
        exam_description='#60 -- press, propose, confirm, reject',
    )
    subjects = {}
    for name in SUBJECTS:
        node = db.create_subject_node(
            exam_context=exam.exam_name, name=name, level_type='Topic')
        subjects[name] = node.id
    session = db.create_review_session(
        exam_context_id=exam.id,
        total_questions=entries,
        total_incorrect=entries,
        session_name='Proposals session',
        date_encountered=date.today(),
    )
    entry_ids = [
        db.create_question_entry(
            session.id, 'A', 'B', explanation=EXPLANATION).id
        for _ in range(entries)
    ]
    db.conn.commit()
    types = {t['label']: t['id'] for t in db.get_relation_types(exam.id)}
    return {'exam_id': exam.id, 'session_id': session.id,
            'entry_ids': entry_ids, 'subjects': subjects, 'types': types}


def _open_entry(page: WimiPage, world: dict, entry_id: int) -> None:
    page.goto('entry-form', query={'session_id': world['session_id'],
                                   'entry': entry_id})
    wait_for_release(page)

    control = json.loads(page.eval_js(POSITIVE_CONTROL))
    assert control['module_loaded'], 'relation_proposals.js did not load'
    assert control['controller_attached'], 'attachRelationProposals never ran'
    assert control['entry_id'] == entry_id, (
        f'the form opened entry {control["entry_id"]}, not {entry_id}')

    page.eval_js(ASK_STATUS)
    assert poll(page, 'window.__relStatus !== null'), (
        'getRelationExtractionStatus never answered')
    status = json.loads(page.eval_js('window.__relStatus'))
    state = status.get('state')
    if state in RUNTIME_ABSENT:
        pytest.skip(f'the relations runtime is not in this interpreter '
                    f'({state}); test_relations_are_silent_when_unavailable '
                    f'covers this machine')
    assert state == 'ready', (
        f'the model is linked but WIMI reports {state!r}: {status}')

    assert poll(page, "(() => { const b = document.querySelector('%s');"
                      " return !!b && !b.disabled; })()" % FIND), (
        'the bridge says ready, but the entry form drew no usable Find button')


def _press(page: WimiPage) -> list[dict]:
    real_click(page, centre_of(page, FIND))
    assert poll(page, SETTLED, timeout_ms=FIRST_PASS_MS, step_ms=200), (
        'the extraction never settled into cards, a note or a failure')
    failure = page.eval_js(
        "(() => { const f = document.querySelector("
        "'[data-testid=\"entry-form-relations-failure\"]');"
        " return f ? f.textContent : null; })()")
    assert failure is None, f'the extraction failed: {failure}'
    return json.loads(page.eval_js(CARDS))


def _triple(card: dict) -> tuple[str, str, str]:
    for label in ('risk factor for', 'complication of', 'treats', 'causes',
                  'presents with', 'confused with'):
        head, sep, tail = card['pair'].partition(f' {label} ')
        if sep:
            return (head, label, tail)
    raise AssertionError(f'no known label in {card["pair"]!r}')


def _by_triple(cards: list[dict]) -> dict:
    return {_triple(card): card for card in cards}


def _answer(page: WimiPage, card: dict, button: str) -> None:
    selector = ('[data-testid="entry-form-relation-proposal"]'
                f'[data-relation-id="{card["relation_id"]}"] '
                f'[data-testid="entry-form-relation-{button}"]')
    real_click(page, centre_of(page, selector))
    assert poll(page, "!document.querySelector("
                      "'[data-relation-id=\"%d\"]')" % card['relation_id']), (
        f'the card for {card["pair"]!r} was still there after {button}')


def _rows(db, sql: str, params=()) -> list[dict]:
    db.conn.commit()  # end any read snapshot so WIMI's writes are visible
    return [dict(row) for row in db.conn.execute(sql, params).fetchall()]


# ---------------------------------------------------------------------------
# The scenarios
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.regression
def test_each_answer_writes_what_the_student_chose(
    wimi_session: WimiTestSession, wimi_page: WimiPage, relations_ready,
) -> None:
    db = wimi_session.user.db
    world = _seed(db)
    entry_id = world['entry_ids'][0]
    subjects = world['subjects']
    _open_entry(wimi_page, world, entry_id)

    cards = _by_triple(_press(wimi_page))
    assert set(cards) == EXPECTED, (
        f'the fixed explanation produced {sorted(cards)}; the assertions below '
        f'are written against {sorted(EXPECTED)}')
    assert all(card['has_select'] for card in cards.values())

    # The reason is prefilled with the passage and editable (#5494).
    assert cards[CONFIRM]['reason'] == 'Hypertension is a risk factor for stroke.'
    edited = 'High blood pressure damages cerebral vessels.'
    wimi_page.eval_js(
        "(() => { const t = document.querySelector('[data-relation-id=\"%d\"] "
        "[data-testid=\"entry-form-relation-reason\"]'); t.value = %s; })()"
        % (cards[CONFIRM]['relation_id'], json.dumps(edited)))

    _answer(wimi_page, cards[CONFIRM], 'confirm')
    _answer(wimi_page, cards[MISREAD], 'misread')
    _answer(wimi_page, cards[UNRELATED], 'not-related')

    # --- confirm: the student's reason, endorsed, provenance kept (#382).
    confirmed = _rows(db, 'SELECT * FROM subject_relations WHERE id = ?',
                      (cards[CONFIRM]['relation_id'],))
    assert len(confirmed) == 1, 'the confirmed relation is gone'
    row = confirmed[0]
    assert row['reason'] == edited, 'the edited reason was not the one stored'
    assert row['confirmed_at'], 'confirming did not stamp confirmed_at'
    assert row['origin'] == 'extracted', (
        'confirming rewrote origin; the entry is where the pair was noticed')
    assert row['source_entry_id'] == entry_id, (
        'confirming dropped source_entry_id (#382 keeps it)')
    assert row['relation_type_id'] == world['types']['risk factor for'], (
        'the type changed although the student did not change it')
    assert (row['from_subject_id'], row['to_subject_id']) == (
        subjects['Hypertension'], subjects['Stroke'])

    # --- the two rejections: rows gone, kinds recorded, nothing else left.
    for triple in (MISREAD, UNRELATED):
        assert not _rows(db, 'SELECT id FROM subject_relations WHERE id = ?',
                         (cards[triple]['relation_id'],)), (
            f'{triple} was rejected but its unconfirmed row survived, so it '
            f'still occupies m026 UNIQUE')
    rejections = {
        (r['from_subject_id'], r['to_subject_id']): r for r in _rows(
            db, 'SELECT * FROM subject_relation_rejections')}
    misread = rejections.get((subjects['Metformin'], subjects['Diabetes mellitus']))
    unrelated = rejections.get((subjects['Lactic acidosis'], subjects['Metformin']))
    assert misread and misread['kind'] == 'misread', rejections
    assert misread['source_entry_id'] == entry_id, (
        'a misread is scoped to its entry and must carry it')
    assert unrelated and unrelated['kind'] == 'not_related', rejections
    assert len(rejections) == 2, rejections
    assert _rows(db, 'SELECT id FROM subject_relations WHERE confirmed_at IS NULL'
                     ' AND source_entry_id = ?', (entry_id,)) == []

    # --- and the confirmed relation is on the deep dive.
    wimi_page.goto('subject-deep-dive', query={
        'subject': subjects['Hypertension'], 'exam': world['exam_id']})
    item = '[data-testid="deep-dive-relation-%d"]' % row['id']
    assert poll(wimi_page, "!!document.querySelector('%s')" % item), (
        'the confirmed relation is not on the Hypertension deep dive')
    text = wimi_page.eval_js("document.querySelector('%s').textContent" % item)
    assert 'Stroke' in text, text
    others = _rows(db, 'SELECT id FROM subject_relations WHERE id <> ?', (row['id'],))
    assert others == [], f'rows other than the confirmed one exist: {others}'


@pytest.mark.slow
@pytest.mark.regression
def test_a_second_press_replaces_the_unanswered_proposals(
    wimi_session: WimiTestSession, wimi_page: WimiPage, relations_ready,
) -> None:
    """The catch for reading the suppression set BEFORE the discard.

    Read first, the entry's own unconfirmed rows are in it, so the second pass
    suppresses every pair it proposed the first time and writes nothing. The
    right answer is the two unanswered pairs again, as new rows, and the
    confirmed one not at all.
    """
    db = wimi_session.user.db
    world = _seed(db)
    entry_id = world['entry_ids'][0]
    _open_entry(wimi_page, world, entry_id)

    first = _by_triple(_press(wimi_page))
    assert set(first) == EXPECTED, sorted(first)
    _answer(wimi_page, first[CONFIRM], 'confirm')

    second = _by_triple(_press(wimi_page))
    assert set(second) == {MISREAD, UNRELATED}, (
        f'the second press offered {sorted(second)}. Empty means the '
        f'suppression set was read before the discard; {CONFIRM} means a '
        f'confirmed relation was proposed again')
    for triple in (MISREAD, UNRELATED):
        assert second[triple]['relation_id'] != first[triple]['relation_id'], (
            f'{triple} kept its row id, so the earlier proposal was not discarded')

    unconfirmed = _rows(db, 'SELECT id FROM subject_relations '
                            'WHERE confirmed_at IS NULL AND source_entry_id = ?',
                        (entry_id,))
    assert sorted(r['id'] for r in unconfirmed) == sorted(
        card['relation_id'] for card in second.values()), (
        f'the entry holds {unconfirmed} unconfirmed rows, not just this press')
    still = _rows(db, 'SELECT confirmed_at FROM subject_relations WHERE id = ?',
                  (first[CONFIRM]['relation_id'],))
    assert still and still[0]['confirmed_at'], (
        'the second press discarded a relation the student had confirmed')


@pytest.mark.slow
@pytest.mark.regression
def test_misread_is_scoped_to_its_entry_and_not_related_is_not(
    wimi_session: WimiTestSession, wimi_page: WimiPage, relations_ready,
) -> None:
    """m027: the kind decides the scope.

    Two entries with the same explanation. On the first, one pair is rejected
    as a misread and another as not related. On the second, the misread pair
    is offered again -- it was a statement about one piece of text -- and the
    not-related pair is not, because that was a claim about the two subjects.
    """
    db = wimi_session.user.db
    world = _seed(db, entries=2)
    first_entry, second_entry = world['entry_ids']

    _open_entry(wimi_page, world, first_entry)
    cards = _by_triple(_press(wimi_page))
    assert set(cards) == EXPECTED, sorted(cards)
    _answer(wimi_page, cards[MISREAD], 'misread')
    _answer(wimi_page, cards[UNRELATED], 'not-related')

    # Same entry again: both suppressed here.
    again = _by_triple(_press(wimi_page))
    assert set(again) == {CONFIRM}, (
        f'on the entry where both were rejected the press offered '
        f'{sorted(again)}')

    _open_entry(wimi_page, world, second_entry)
    other = _by_triple(_press(wimi_page))
    assert MISREAD in other, (
        'a misread on another entry suppressed the pair here too; misread is '
        'scoped to the entry it was said about')
    assert UNRELATED not in other, (
        'a pair rejected as not related was offered again on another entry')
    # CONFIRM was left unanswered on the first entry. Its invisible row holds
    # m026's UNIQUE, so it cannot be proposed here -- and since #390 the card
    # says where it is waiting instead of saying nothing. The rejected pair
    # gets no note: the student's own decision is not re-surfaced.
    assert CONFIRM not in other
    notes = json.loads(wimi_page.eval_js(PENDING_NOTES))
    assert len(notes) == 1, notes
    assert notes[0]['entry_id'] == first_entry, notes
    assert notes[0]['controls'] == 0, 'nothing on this entry to answer'
    assert notes[0]['text'] == (
        'Hypertension risk factor for Stroke is already suggested on '
        'Proposals session — Question 1, waiting for you there.'), notes


@pytest.mark.slow
@pytest.mark.regression
def test_without_a_type_list_confirming_keeps_the_proposed_type(
    wimi_session: WimiTestSession, wimi_page: WimiPage, relations_ready,
) -> None:
    """No list, no select -- and confirming must not untype the relation.

    The page's type list comes from a separate read that can fail while the
    bridge still has labels to extract with. Forced empty here by replacing
    that one read before reloading the list. An empty select would yield
    ``'' -> null``, which differs from the proposal's type, so confirming
    would silently make the relation untyped.
    """
    db = wimi_session.user.db
    world = _seed(db)
    _open_entry(wimi_page, world, world['entry_ids'][0])

    wimi_page.eval_js(
        "(() => { window.api.getRelationTypes = () => Promise.resolve([]);"
        " window.__typesLoaded = false;"
        " EntryState.relationProposals.loadTypes(%d)"
        "   .then(() => { window.__typesLoaded = true; }); })()"
        % world['exam_id'])
    assert poll(wimi_page, 'window.__typesLoaded === true')

    cards = _by_triple(_press(wimi_page))
    assert set(cards) == EXPECTED, sorted(cards)
    assert not any(card['has_select'] for card in cards.values()), (
        'a type select was drawn with no types to put in it')

    _answer(wimi_page, cards[CONFIRM], 'confirm')
    row = _rows(db, 'SELECT * FROM subject_relations WHERE id = ?',
                (cards[CONFIRM]['relation_id'],))[0]
    assert row['confirmed_at']
    assert row['relation_type_id'] == world['types']['risk factor for'], (
        f'confirming with no type list changed the type to '
        f'{row["relation_type_id"]!r}; it must keep the proposed one')
