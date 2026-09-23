"""Bridge tests for the subject sunburst's centre number (Forgejo issue #6).

From the issue:

    The "By Subject" sunburst shows ``14`` above the word ``TOTAL`` in
    its centre, while the OVERVIEW card at the top of the same screen
    reads ``TOTAL ENTRIES 11``. Both are visible without scrolling.

``14`` is the sum of the per-parent rollups: a subject with several
parents contributes to each of them, and an entry with a NULL
``primary_parent_id`` is counted under every parent it could route
through (``POLYHIERARCHY_MIGRATION`` §5.4). That arithmetic is correct
and the owner's decision (2026-09-14) keeps it:

    The centre shows the distinct entry count (11). The arcs keep their
    overlapping per-parent values. [...] The arcs will therefore visibly
    sum to more than the centre. That is intended, not a rounding bug.

So ``getSubjectHierarchyWithMistakes`` now carries **two** totals:
``value`` (the sum of the arcs, unchanged) and ``distinct_entries``
(the number the centre renders). These tests pin both on the issue's
own repro, and pin that ``distinct_entries`` is the same number the
"Total Entries" card shows — the two sit inches apart on screen and
must not drift.
"""
import json
import tempfile
from datetime import date
from pathlib import Path
from typing import Generator

import pytest

from app.bridge import DatabaseBridge
from database.master_db import MasterDatabase
from database.user_db import UserDatabase


EXAM = "Issue 6 Sunburst Centre"


# ==================== Fixtures ====================

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
    db = UserDatabase(db_path=temp_db_path, user_id=1, username="issue6_user")
    yield db
    db.close()


@pytest.fixture
def master_db(temp_master_db_dir: Path) -> Generator[MasterDatabase, None, None]:
    db = MasterDatabase(data_dir=temp_master_db_dir, error_logger=None)
    yield db
    db.close()


@pytest.fixture
def bridge(user_db: UserDatabase, master_db: MasterDatabase) -> DatabaseBridge:
    master_db.bootstrap_first_user(username="issue6_admin", display_name="Issue 6")
    return DatabaseBridge(master_db=master_db, user_db=user_db)


@pytest.fixture
def world(user_db: UserDatabase) -> dict:
    """The issue's "How to reproduce" seed, verbatim.

    ``hypertension`` under Cardiovascular (canonical) + Pregnancy,
    ``venous thromboembolism`` under all three systems, ``asthma``
    under Respiratory; 11 entries, 3 of them left undisambiguated.
    """
    exam = user_db.create_exam_context(exam_name=EXAM, exam_description="Issue #6")

    def node(name, parent=None, level="System"):
        return user_db.create_subject_node(
            exam_context=EXAM, name=name, level_type=level,
            parent_id=parent, sort_order=1,
        )

    cardio = node("Cardiovascular")
    preg = node("Pregnancy")
    resp = node("Respiratory")
    # First parent passed is the canonical one; the rest are extra edges.
    htn = node("hypertension", parent=cardio.id, level="Topic")
    user_db.add_edge(preg.id, htn.id, is_primary=False)
    vte = node("venous thromboembolism", parent=cardio.id, level="Topic")
    user_db.add_edge(preg.id, vte.id, is_primary=False)
    user_db.add_edge(resp.id, vte.id, is_primary=False)
    asthma = node("asthma", parent=resp.id, level="Topic")

    session = user_db.create_review_session(
        exam_context_id=exam.id, total_questions=11, total_incorrect=11,
        session_name="issue 6", date_encountered=date.today(),
    )

    order = iter(range(1, 100))

    def entries(subject_id, primary_parent_id, count):
        for _ in range(count):
            cur = user_db.execute(
                "INSERT INTO question_entries "
                "(review_session_id, entry_order, user_answer, correct_answer, is_draft) "
                "VALUES (?, ?, 'a', 'b', 0)",
                (session.id, next(order)),
            )
            user_db.execute(
                "INSERT INTO entry_subject_mappings "
                "(question_entry_id, subject_node_id, mapping_type, primary_parent_id) "
                "VALUES (?, ?, 'primary', ?)",
                (cur.lastrowid, subject_id, primary_parent_id),
            )

    entries(htn.id, cardio.id, 3)
    entries(htn.id, preg.id, 2)
    entries(htn.id, None, 1)
    entries(vte.id, preg.id, 2)
    entries(vte.id, None, 1)
    entries(asthma.id, None, 2)
    user_db.conn.commit()

    return {
        "exam_id": exam.id, "cardio": cardio.id, "preg": preg.id,
        "resp": resp.id, "htn": htn.id, "vte": vte.id, "asthma": asthma.id,
    }


def _hierarchy(bridge: DatabaseBridge, exam_id: int) -> dict:
    response = json.loads(bridge.getSubjectHierarchyWithMistakes(
        json.dumps({"exam_context_id": exam_id})
    ))
    assert response["success"], response.get("error")
    return response["data"]


# ==================== Tests ====================

def test_fixture_has_eleven_entries(user_db: UserDatabase, world: dict) -> None:
    """Guard the seed itself, so a later failure is never the setup."""
    total = user_db.fetchone("SELECT COUNT(*) AS n FROM question_entries")["n"]
    assert total == 11


def test_arcs_keep_their_overlapping_per_parent_rollups(bridge, world) -> None:
    """The decision explicitly keeps the arcs as they are.

    Cardiovascular 5 = htn (3 pinned + 1 NULL) + VTE (1 NULL);
    Pregnancy 6 = htn (2 + 1 NULL) + VTE (2 + 1 NULL);
    Respiratory 3 = VTE (1 NULL) + asthma 2.
    """
    data = _hierarchy(bridge, world["exam_id"])
    rollups = {c["name"]: c["value"] for c in data["children"]}

    assert rollups["Cardiovascular"] == 5
    assert rollups["Pregnancy"] == 6
    assert rollups["Respiratory"] == 3
    # Non-additive on purpose: 3 entries are counted under more than one
    # parent. Do NOT "fix" this to 11 — see the issue's decision.
    assert data["value"] == 14


def test_payload_carries_the_distinct_entry_count(bridge, world) -> None:
    """The centre's number is its own count, not a re-sum of the arcs."""
    data = _hierarchy(bridge, world["exam_id"])

    # Failed before the fix: the key did not exist, so the chart had
    # nothing to render but ``value`` and the centre read 14.
    assert data["distinct_entries"] == 11
    assert data["value"] == 14, "the two totals are different numbers by design"


def test_distinct_count_matches_the_total_entries_card(bridge, user_db, world) -> None:
    """The pair the issue is about: both numbers are on screen together."""
    data = _hierarchy(bridge, world["exam_id"])
    card = json.loads(bridge.getAnalyticsOverview(
        json.dumps({"exam_context_id": world["exam_id"]})
    ))
    assert card["success"], card.get("error")

    assert data["distinct_entries"] == card["data"]["total_entries"] == 11


def test_distinct_count_counts_entries_with_no_subject_tag(bridge, user_db, world) -> None:
    """An untagged entry is on the card, so it is in the centre too.

    The centre answers "how many entries are behind this chart", which
    is the card's question. Deriving it from the tagged buckets instead
    would reintroduce a second, differently-computed total — the exact
    complaint in issue #6.
    """
    session = user_db.fetchone("SELECT id FROM review_sessions LIMIT 1")["id"]
    user_db.execute(
        "INSERT INTO question_entries "
        "(review_session_id, entry_order, user_answer, correct_answer, is_draft) "
        "VALUES (?, 99, 'a', 'b', 0)",
        (session,),
    )
    user_db.conn.commit()

    data = _hierarchy(bridge, world["exam_id"])
    card = json.loads(bridge.getAnalyticsOverview(
        json.dumps({"exam_context_id": world["exam_id"]})
    ))["data"]

    assert data["distinct_entries"] == card["total_entries"] == 12
    assert data["value"] == 14, "an untagged entry is in no arc"
