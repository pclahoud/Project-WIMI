"""Regression: a subject's weight band renders as text, never markup (#548).

``renderNode`` drew ``${node.exam_weight_low}–${node.exam_weight_high}%`` raw.
On the dimensioned load path -- the common case -- those are raw row values
from ``get_hierarchy_nodes_by_dimension``, and both columns are REAL. Affinity
is not enforcement: SQLite stores text that will not convert *as text*. A
profile arriving by ``.wimi`` import, restore or folder-sync install is copied
byte for byte, and #593's schema check compares structure, not values, so
such a row reaches the tree editor unchanged.

The value is written with plain SQL, past the domain layer, because WIMI's own
writers never produce one: the subject importer runs every weight through
``float()``. The plain load path builds ``SubjectNode``, which also calls
``float()``, so only the dimensioned path can carry the text to the page.
That is why this file drives that path alone.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.tree_details import open_tree_editor
from _helpers.tree_expand import expand_whole_tree

PAYLOAD = '<img src=x data-testid="tw-injected" onerror="window.__tw=1">'

CHIP = """
((id) => {
    const el = document.querySelector(`[data-testid="tree-node-weight-${id}"]`);
    if (!el) return null;
    return {imgs: el.querySelectorAll('img').length, text: el.textContent.trim()};
})(%s)
"""


@pytest.mark.slow
@pytest.mark.regression
def test_a_weight_band_carrying_markup_renders_as_its_own_text(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    name = "V548 band"
    exam = db.create_exam_context(exam_name=name, exam_description="")
    dim = db.create_dimension(exam_id=exam.id, name="System",
                              display_order=1, is_required=True)
    hostile = db.create_subject_node(
        exam_context=name, name="V548 Hostile", level_type="System",
        exam_weight_low=5.0, exam_weight_high=10.0, dimension_id=dim).id
    honest = db.create_subject_node(
        exam_context=name, name="V548 Honest", level_type="System",
        exam_weight_low=5.0, exam_weight_high=9.0, dimension_id=dim).id
    db.conn.execute("UPDATE subject_nodes SET exam_weight_high = ? WHERE id = ?",
                    (PAYLOAD, hostile))
    db.conn.commit()
    # The premise, checked rather than assumed: SQLite kept text in a REAL column.
    kind = db.conn.execute("SELECT typeof(exam_weight_high) FROM subject_nodes"
                           " WHERE id = ?", (hostile,)).fetchone()[0]
    assert kind == "text", kind
    assert db.exam_uses_dimensions(exam.id), "seed drifted: not the dimensioned path"

    open_tree_editor(wimi_page, exam.id)
    expand_whole_tree(wimi_page)
    wimi_page.wait_for_timeout(500)   # a broken <img>'s onerror fires async

    # Positive control: the honest row drew its band.
    good = wimi_page.eval_js(CHIP % json.dumps(honest))
    assert good is not None and good["text"].startswith("5–9%"), good

    chip = wimi_page.eval_js(CHIP % json.dumps(hostile))
    assert chip is not None, "the row with a text weight never drew"
    assert chip["imgs"] == 0, f"the weight band became an element: {chip}"
    assert not wimi_page.eval_js("window.__tw === 1"), "the injected handler ran"
    assert chip["text"].startswith(f"5–{PAYLOAD}%"), (
        f"the band should read back as its own text: {chip}")
