"""Regression: clearing the details panel's Name field keeps the old name (#737).

The tree row's inline rename has always refused an empty name, and chapter 10
says so: "Clearing the box keeps the old name: an empty name is never saved."
The details panel's **Name** field (``#edit-name``) did not. Its ``onchange``
sent the field's value as it stood, the bridge wrote ``name = ''`` (SQLite
accepts it on a ``NOT NULL`` column), and the panel toasted "Name saved" over
a subject with no name.

The field is driven the way a student drives it: the value is cleared and a
real ``change`` event is fired. The database row, the field and the tree row
must all still carry the old name, and no rename may reach the bridge. A
second edit with a padded name is the control: it saves, trimmed, so the fix
is "refuse empty", not "refuse every edit".

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.tree_details import open_tree_editor, select_subject

SPY = """
(() => {
    window.__renames = [];
    const real = api.updateSubjectNode;
    api.updateSubjectNode = (...args) => {
        window.__renames.push(args);
        return real.apply(api, args);
    };
})()
"""


def _set_name(page: WimiPage, value: str) -> None:
    page.eval_js(f"""(() => {{
        const f = document.getElementById('edit-name');
        f.value = {json.dumps(value)};
        f.dispatchEvent(new Event('change'));
    }})()""")
    page.wait_for_timeout(800)


def _stored(db, node_id: int) -> str:
    return db.fetchone("SELECT name FROM subject_nodes WHERE id = ?", (node_id,))["name"]


@pytest.mark.slow
@pytest.mark.regression
def test_clearing_the_name_field_keeps_the_old_name(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="W737 Names", exam_description="")
    node = db.create_subject_node(exam_context=exam.exam_name, name="Cardiology",
                                  level_type="System")
    db.conn.commit()

    open_tree_editor(wimi_page, exam.id)
    select_subject(wimi_page, node.id)
    wimi_page.eval_js(SPY)

    _set_name(wimi_page, "   ")

    assert _stored(db, node.id) == "Cardiology", (
        f"#737: clearing the Name field saved {_stored(db, node.id)!r}. Chapter 10"
        f" says an empty name is never saved, and the inline rename refuses one.")
    assert wimi_page.eval_js("window.__renames.length") == 0, (
        "#737: an empty name was sent to updateSubjectNode")
    assert wimi_page.eval_js("document.getElementById('edit-name').value") == "Cardiology", (
        "#737: the field must show the name that was kept, not the cleared box")
    row = wimi_page.eval_js(
        f"(document.getElementById('name-{node.id}') || {{}}).textContent")
    assert row == "Cardiology", f"#737: the tree row reads {row!r}"

    # The control: a real edit still saves, trimmed.
    _set_name(wimi_page, "  Electrophysiology  ")
    assert _stored(db, node.id) == "Electrophysiology", (
        "a real rename through the Name field no longer saves, so the empty-name"
        " half above proves nothing")
