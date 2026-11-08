"""Regression: the Archived subjects panel is there on a dimensioned exam's first load (#745).

``refreshArchivedPanel()`` was called only from inside ``loadHierarchy()``.
On a dimensioned exam the initial load is ``loadDimensions() ->
selectDimension() -> loadDimensionHierarchy()``, and ``loadHierarchy`` never
runs. So the panel stayed at its markup default, hidden with a count of 0,
until a write (archive, restore, add a child) happened to call
``loadHierarchy``. A student who archived something last week opened the
tree today and found no way back to it.

The test is on a DIMENSIONED exam reached by a FRESH navigation, with the
archiving done beforehand in the database. Both conditions matter:

- the existing archived-panel scenario passes on master because it reaches
  the panel through a write, which has already called ``loadHierarchy``;
- a plain exam cannot fail this, because its initial load IS
  ``loadHierarchy``.

The plain exam is driven as the control. It always worked, and it has to
keep working once the refresh is also called from the dimensioned path.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.tree_details import open_tree_editor

PANEL = """
(() => {
    const el = document.querySelector('[data-testid="tree-archived-panel"]');
    const count = document.getElementById('archived-panel-count');
    return {
        shown: !!el && !el.classList.contains('hidden'),
        count: count ? count.textContent.trim() : null,
    };
})()
"""


def _seed(db, *, dimensioned: bool) -> int:
    exam = db.create_exam_context(exam_name="W745 Archive", exam_description="")
    dim = None
    if dimensioned:
        dim = db.create_dimension(exam_id=exam.id, name="System", display_order=1)
    root = db.create_subject_node(exam_context=exam.exam_name, name="Cardiology",
                                  level_type="System", dimension_id=dim)
    gone = db.create_subject_node(exam_context=exam.exam_name, name="Valvular",
                                  level_type="Topic", parent_id=root.id,
                                  dimension_id=dim)
    db.conn.commit()
    batch = db.delete_subject_subtree(gone.id)["batch_id"]
    assert batch, "premise: the delete must journal a batch"
    assert db.exam_uses_dimensions(exam.id) == dimensioned, "seed drifted"
    return exam.id


@pytest.mark.slow
@pytest.mark.regression
@pytest.mark.parametrize("dimensioned", [True, False],
                         ids=["loadDimensionHierarchy", "loadHierarchy"])
def test_the_archived_panel_shows_on_a_fresh_load(
    wimi_session: WimiTestSession, wimi_page: WimiPage, dimensioned: bool,
) -> None:
    exam_id = _seed(wimi_session.user.db, dimensioned=dimensioned)

    open_tree_editor(wimi_page, exam_id)
    assert wimi_page.eval_js("TreeState.usesDimensions") == dimensioned
    # Poll rather than wait_for: on master the panel never fills, and the
    # assertion below should be what reports that, with the #745 sentence.
    panel = None
    for _ in range(60):
        panel = wimi_page.eval_js(PANEL)
        if panel["shown"]:
            break
        wimi_page.wait_for_timeout(100)
    assert panel == {"shown": True, "count": "1"}, (
        f"#745: on a fresh load the Archived subjects panel reads {panel}. A"
        f" deletion made before this visit is journalled and has no way back"
        f" unless the panel shows it.")
