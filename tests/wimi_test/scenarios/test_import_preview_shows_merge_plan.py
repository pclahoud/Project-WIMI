"""Regression: the import modal says what a re-import will do, first.

Issue #67 — "Re-import duplicates the tree; needs subject ids, a merge
preview, and a reassign path".

    ``import_node`` calls ``create_subject_node`` for every node in the
    file, unconditionally. No id, no lookup, no merge. The tree editor's
    confirm dialog says it plainly: *"This will add to your existing
    hierarchy."*

The backend half is pinned by ``tests/database/test_subject_import_merge.py``
and ``tests/app/test_bridge_import_preview.py``. What only a rendered
assertion can prove is that the student is *shown* the plan before the
destructive part runs — the counts, and the sentence naming the subject
that is being kept because entries are tagged to it, with a link to
those entries (issue #67 decision 3, built as the link rather than a
bulk reassign tool).

The trap this scenario exists for: the preview is fetched over the
bridge *after* the modal opens, so a preview that silently fails leaves
a modal that looks complete and promises nothing — which is exactly the
silence the issue is about. Asserting on the modal's own markup is the
only way to catch that.
"""

from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


_FIRST_IMPORT = {
    "root_nodes": [
        {
            "id": "1",
            "name": "Cardiovascular",
            "level_type": "System",
            "children": [
                {"id": "1.1", "name": "Arrhythmia", "level_type": "Topic"},
                {"id": "1.2", "name": "Valvular disease", "level_type": "Topic"},
            ],
        }
    ]
}

# The corrected file: "Arrhythmia" renamed but carrying the same id (a
# rename, not a replacement), "Valvular disease" dropped entirely — and
# it is the one the seeded entry is tagged to, so it must be kept.
_CORRECTED = {
    "root_nodes": [
        {
            "id": "1",
            "name": "Cardiovascular",
            "level_type": "System",
            "children": [
                {
                    "id": "1.1",
                    "name": "Arrhythmias and conduction",
                    "level_type": "Topic",
                },
                {"id": "1.3", "name": "Heart failure", "level_type": "Topic"},
            ],
        }
    ]
}

# Feeds the real file-input handler a synthetic change event, the way
# `test_import_accepts_subjects_key.py` does. The handler is the
# overridden `handleImportFileEnhanced`, which is what the page's file
# input actually reaches.
_RUNNER = """
window.__i67 = async function (payload) {
    const file = new File([JSON.stringify(payload)], 'corrected.json',
                          { type: 'application/json' });
    await window.handleImportFileEnhanced(
        { target: { files: [file], value: 'corrected.json' } }
    );
    const modal = document.getElementById('import-preview-modal');
    return !!modal && modal.classList.contains('active');
};
true
"""


def _wait_for(page: WimiPage, expression: str, *, what: str, tries: int = 60) -> None:
    for _ in range(tries):
        if page.eval_js(expression):
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"timed out waiting for {what}: {expression}")


def _tag_entry(db, exam_id: int, subject_id: int) -> int:
    session_id = db.execute(
        "INSERT INTO review_sessions "
        "(user_id, session_name, date_encountered, exam_context_id, "
        " total_questions, total_incorrect) "
        "VALUES (?, 'Scenario', '2026-09-16', ?, 1, 1)",
        (db.user_id, exam_id),
    ).lastrowid
    entry_id = db.execute(
        "INSERT INTO question_entries "
        "(review_session_id, entry_order, user_answer, correct_answer) "
        "VALUES (?, 1, 'A', 'B')",
        (session_id,),
    ).lastrowid
    db.execute(
        "INSERT INTO entry_subject_mappings "
        "(question_entry_id, subject_node_id, mapping_type) "
        "VALUES (?, ?, 'primary')",
        (entry_id, subject_id),
    )
    db.conn.commit()
    return entry_id


@pytest.mark.slow
@pytest.mark.regression
def test_import_preview_shows_the_merge_plan_and_keeps_used_subjects(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    exam = db.create_exam_context(
        exam_name="Issue 67 Import Merge",
        exam_description="Regression — re-import merges behind a preview",
    )
    exam_id = db.get_exam_context_by_name(exam.exam_name).id

    wimi_page.goto("tree-editor", query={"exam_id": exam_id})
    _wait_for(
        wimi_page,
        "!!(window.api && window.api.importSubjectHierarchy "
        "&& window.handleImportFileEnhanced)",
        what="the tree editor's import layer to come up",
    )

    first = wimi_page.eval_js(
        f"window.api.importSubjectHierarchy({exam_id}, "
        f"{json.dumps(json.dumps(_FIRST_IMPORT))})",
        await_promise=True,
    )
    assert first["counts"]["added"] == 3, first

    valvular_id = db.fetchone(
        "SELECT id FROM subject_nodes WHERE name = 'Valvular disease'"
    )["id"]
    _tag_entry(db, exam_id, valvular_id)

    wimi_page.eval_js("window.loadHierarchy()", await_promise=True)
    wimi_page.eval_js(_RUNNER)

    # ---- Act: hand the corrected file to the real handler -------------
    opened = wimi_page.eval_js(
        f"window.__i67({json.dumps(_CORRECTED)})", await_promise=True
    )
    assert opened is True, "the import preview modal did not open"

    _wait_for(
        wimi_page,
        "!!document.querySelector('#import-merge-plan .import-plan-stats')",
        what="the merge plan to render in the modal",
    )

    # ---- Assert: the modal states the plan before anything runs -------
    plan_text = wimi_page.eval_js(
        "document.getElementById('import-merge-plan').innerText"
    )
    stats = wimi_page.eval_js(
        """(() => {
            const out = {};
            document.querySelectorAll(
                '#import-merge-plan .import-plan-stat'
            ).forEach(el => {
                out[el.querySelector('.import-plan-label').textContent.trim()] =
                    el.querySelector('.import-plan-number').textContent.trim();
            });
            return out;
        })()"""
    )
    assert stats == {
        "added": "1", "updated": "1", "removed": "0", "unchanged": "1"
    }, f"merge plan showed {stats} — plan text was: {plan_text!r}"

    kept_href = wimi_page.eval_js(
        "document.querySelector('#import-merge-plan .import-plan-link')"
        "?.getAttribute('href') || ''"
    )
    assert f"subject={valvular_id}" in kept_href, (
        f"the kept-in-use subject has no link to its entries: {kept_href!r}"
    )
    assert "Valvular disease" in plan_text
    assert "kept" in plan_text.lower()

    # Nothing has been written yet — the preview is read-only.
    assert db.fetchone(
        "SELECT status FROM subject_nodes WHERE id = ?", (valvular_id,)
    )["status"] == "active"
    assert db.fetchone(
        "SELECT COUNT(*) AS c FROM subject_nodes WHERE name = 'Heart failure'"
    )["c"] == 0

    # ---- Act: confirm, and check the plan was the truth ---------------
    wimi_page.eval_js("window.executeImport()", await_promise=True)
    _wait_for(
        wimi_page,
        "!document.getElementById('import-preview-modal')"
        ".classList.contains('active')",
        what="the modal to close after the import",
    )

    rows = {
        row["name"]: row["status"]
        for row in db.fetchall(
            "SELECT name, status FROM subject_nodes WHERE exam_context = ?",
            (exam.exam_name,),
        )
    }
    # The rename landed in place: one row, new name, no duplicate.
    assert "Arrhythmia" not in rows
    assert rows["Arrhythmias and conduction"] == "active"
    # Decision 3: the file dropped it, the student's entry keeps it.
    assert rows["Valvular disease"] == "active"
    assert rows["Heart failure"] == "active"
    assert db.fetchone(
        "SELECT COUNT(*) AS c FROM subject_nodes WHERE exam_context = ?",
        (exam.exam_name,),
    )["c"] == 4, (
        "the tree gained a duplicate — the merge appended instead of matching"
    )
