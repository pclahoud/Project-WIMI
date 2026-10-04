"""``exam_names`` reaches the page, and a failure to fetch it says so (#200).

``_serialize_entry_media`` ran this, once per media item, every call::

    SELECT DISTINCT ec.name FROM entry_media_mapping emm
    JOIN question_entries qe ON emm.question_entry_id = qe.id
    JOIN review_sessions rs ON qe.review_session_id = rs.id
    JOIN exam_contexts ec ON rs.exam_context_id = ec.id
    WHERE emm.media_id = ?

``exam_contexts`` has no ``name`` column -- it is ``exam_name``
(``user_db_schema_v1_phase2.sql:18``) and no migration adds one -- so the
statement raised on every call, ``except Exception: pass`` swallowed it, and
``exam_names`` was **always** ``[]``. Measured on this tree: ``ec.name`` ->
``no such column: ec.name``, ``ec.exam_name`` -> OK.

**This is a feature that never worked, not a dead query.** Two surfaces
consume the key and both have real stylesheets behind them:
``entry_detail.js`` draws a ``.thumbnail-exam-badge`` on each attachment
(``detail.css:411``) and ``image_browser.js`` an ``.image-browser-exam``
label on each card (``media.css:637``). Nothing was ever shown. The payload
key being *present and empty* is what made it read as "this media belongs
to no exam" rather than as a failure.

#200 says "the fix is one character: ``ec.name`` -> ``ec.exam_name``". **It
is not, and that matters more than the column.**
``sqlite3.Row.__getitem__`` raises ``IndexError`` for a key the row does not
carry, so renaming only the column moves the failure from the SQL into the
``[r['name'] for r in rows]`` comprehension two lines below, where the same
bare ``except`` swallows it and ``exam_names`` is ``[]`` again --
indistinguishable from the original bug and with the one-character diff
looking obviously correct. Measured: a row whose only key is ``exam_name``
answers ``r['name']`` with ``IndexError: No item with that key``. The query
therefore aliases (``ec.exam_name AS name``) so the SQL and the read agree
in one place.

``test_the_one_character_fix_is_not_enough`` is the guard for exactly that,
and it is why these tests go through the real slot rather than asserting on
the SQL text: both broken versions return ``[]`` with ``success=True``, so
only the value can tell them apart.

The silence is the third defect and the one that would let this recur. A
query that is genuinely optional still has to say so once, so the handler
logs instead of passing. It is a WARNING rather than an ERROR -- the payload
is still useful without the badge, and WARNING-and-above deduplicates within
300 s by ``category:message``, which turns "once per media item per call"
into "once", which is what is wanted. Assertions are against the log file on
disk, per CLAUDE.md, never ``error_buffer``.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from app.bridge import DatabaseBridge
from app_logging import ErrorLogger
from database.master_db import MasterDatabase
from database.user_db import UserDatabase

EXAM = "Surgery Shelf Exam"
OTHER_EXAM = "Step 2 CK"


# ==================== Fixtures ====================

@pytest.fixture
def log_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def error_logger(log_dir: Path) -> Generator[ErrorLogger, None, None]:
    logger = ErrorLogger(
        app_name="Issue200",
        log_dir=log_dir,
        mode='development',
        flush_interval=3600.0,
    )
    yield logger
    logger.cleanup()


@pytest.fixture
def user_db() -> Generator[UserDatabase, None, None]:
    with tempfile.TemporaryDirectory() as tmpdir:
        db = UserDatabase(
            db_path=Path(tmpdir) / 'u.db', user_id=1, username="issue200_user",
        )
        yield db
        db.close()


@pytest.fixture
def master_db() -> Generator[MasterDatabase, None, None]:
    with tempfile.TemporaryDirectory() as tmpdir:
        db = MasterDatabase(data_dir=Path(tmpdir), error_logger=None)
        yield db
        db.close()


@pytest.fixture
def bridge(user_db, master_db, error_logger) -> DatabaseBridge:
    master_db.bootstrap_first_user(username="issue200", display_name="I200")
    return DatabaseBridge(
        master_db=master_db, user_db=user_db, error_logger=error_logger,
    )


def _seed_entry_with_media(db: UserDatabase, exam_name: str, uuid: str):
    """One exam -> session -> entry -> media, through the domain API.

    ``add_entry_media`` writes the ``entry_media_mapping`` row the query
    joins on, which is the whole reason it is used here instead of raw
    inserts: a test that inserted only ``entry_media`` would pass against a
    query that never looked at the junction table.
    """
    exam = db.create_exam_context(exam_name=exam_name)
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=10, total_incorrect=3,
    )
    entry = db.create_question_entry(
        review_session_id=session.id, user_answer='A', correct_answer='B',
    )
    media = db.add_entry_media(
        entry_id=entry.id, file_uuid=uuid,
        original_filename=f'{uuid}.png', mime_type='image/png',
    )
    return exam, entry, media


def _media_payload(bridge: DatabaseBridge, entry_id: int) -> list:
    response = json.loads(bridge.getQuestionMedia(entry_id))
    assert response['success'] is True, response
    return response['data']


def _log_text(log_dir: Path) -> str:
    return "\n".join(
        path.read_text(encoding='utf-8', errors='replace')
        for path in sorted(log_dir.glob('*.log'))
    )


# ==================== The value reaches the page ====================


def test_exam_names_carries_the_exam_name(bridge, user_db):
    """The issue's own repro: open an entry with an attachment and look."""
    _exam, entry, _media = _seed_entry_with_media(user_db, EXAM, 'uuid-one')

    items = _media_payload(bridge, entry.id)

    assert len(items) == 1
    assert items[0]['exam_names'] == [EXAM], (
        'exam_names has been [] for the whole life of this code -- the two '
        'surfaces that render it have never shown anything'
    )


def test_the_one_character_fix_is_not_enough(bridge, user_db):
    """A column rename alone leaves the comprehension reading ``r['name']``.

    This test cannot be written as "the SQL says exam_name"; it has to read
    the value, because the one-character version returns ``[]`` with
    ``success=True`` exactly like the original. Stated as its own test so
    the reason survives a later tidy-up that "simplifies" the alias away.
    """
    _exam, entry, _media = _seed_entry_with_media(user_db, EXAM, 'uuid-two')

    items = _media_payload(bridge, entry.id)

    assert items[0]['exam_names'], (
        "empty here means the SQL column and the key the comprehension "
        "reads have drifted apart again -- sqlite3.Row raises IndexError "
        "for a missing key and the handler swallows it"
    )


def test_media_shared_across_two_exams_reports_both(bridge, user_db):
    """``DISTINCT`` over the junction table is the point of the query.

    One media row can attach to many entries (CLAUDE.md, Media Handling),
    which is why the key is plural and why both consumers ``join(', ')`` it.
    A fix that reached for the owning entry's exam instead would pass the
    test above and fail here.
    """
    _exam_a, entry_a, media = _seed_entry_with_media(
        user_db, EXAM, 'uuid-shared',
    )
    exam_b = user_db.create_exam_context(exam_name=OTHER_EXAM)
    session_b = user_db.create_review_session(
        exam_context_id=exam_b.id, total_questions=5, total_incorrect=1,
    )
    entry_b = user_db.create_question_entry(
        review_session_id=session_b.id, user_answer='C', correct_answer='D',
    )
    user_db.attach_existing_media_to_entry(media.id, entry_b.id)

    items = _media_payload(bridge, entry_a.id)

    assert sorted(items[0]['exam_names']) == sorted([EXAM, OTHER_EXAM])


def test_an_unmapped_media_row_reports_no_exams(bridge, user_db):
    """Empty is still a legitimate answer, and must stay distinguishable
    from a failure -- which is the whole reason the failure now logs."""
    _exam, entry, media = _seed_entry_with_media(user_db, EXAM, 'uuid-bare')
    user_db.execute(
        "DELETE FROM entry_media_mapping WHERE media_id = ?", (media.id,),
    )
    user_db.conn.commit()

    items = json.loads(bridge.getQuestionMedia(entry.id))['data']

    # The mapping is also how getQuestionMedia finds the media at all, so
    # the list is empty rather than carrying an item with no exams. What
    # matters is that nothing raised and nothing was logged.
    assert items == []


# ==================== A failure says so, once ====================


def test_the_payload_survives_a_failing_lookup(bridge, user_db,
                                               error_logger, log_dir):
    """The defect that made this invisible, and the one that must stay.

    ``except Exception: pass`` is why a wrong column name survived in a
    query that runs on every entry open; renaming the table out from under
    it reproduces any future breakage of the same shape. And optional stays
    optional.

    The badge is a nicety; the image is not. A lookup failure must leave
    ``exam_names`` empty and every other field intact, which is why the
    handler still catches broadly instead of narrowing what escapes (#139's
    reasoning, same shape).
    """
    _exam, entry, _media = _seed_entry_with_media(user_db, EXAM, 'uuid-fail')
    user_db.execute("ALTER TABLE exam_contexts RENAME TO exam_contexts_moved")
    user_db.conn.commit()

    items = _media_payload(bridge, entry.id)

    assert len(items) == 1
    assert items[0]['exam_names'] == []
    assert items[0]['original_filename'] == 'uuid-fail.png'
    assert items[0]['mime_type'] == 'image/png'

    error_logger.flush(drain_all=True)
    text = _log_text(log_dir)
    assert 'exam names' in text.lower(), (
        'a swallowed failure is how #200 survived; the handler must log'
    )
    assert '"level": "WARNING"' in text, (
        'an optional display field is a WARNING -- an ERROR here would '
        'pollute the bucket that carries real failures'
    )


def test_one_warning_for_many_items(bridge, user_db, error_logger, log_dir):
    """Once, not once per attachment.

    The serializer runs per media item, so a broken lookup on an entry with
    several attachments would otherwise write one identical line each.
    WARNING-and-above deduplicates within 300 s by ``category:message``
    (CLAUDE.md, Logging), and this test is what makes that reliance
    deliberate rather than incidental.
    """
    _exam, entry, _media = _seed_entry_with_media(user_db, EXAM, 'uuid-m0')
    for i in range(1, 6):
        user_db.add_entry_media(
            entry_id=entry.id, file_uuid=f'uuid-m{i}',
            original_filename=f'uuid-m{i}.png', mime_type='image/png',
        )
    user_db.execute("ALTER TABLE exam_contexts RENAME TO exam_contexts_moved")
    user_db.conn.commit()

    items = _media_payload(bridge, entry.id)
    assert len(items) == 6, 'arrange failed: six attachments, six lookups'

    error_logger.flush(drain_all=True)
    hits = sum(
        1 for line in _log_text(log_dir).splitlines()
        if 'exam names' in line.lower()
    )
    assert hits == 1, f'expected one deduplicated warning, got {hits}'


if __name__ == '__main__':  # pragma: no cover
    pytest.main([__file__, '-v'])
