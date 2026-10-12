"""Regression: the tree editor shows a student's values as text (#548).

#324, #525 and #546 were one defect found three times: a value a student
typed or imported reached ``innerHTML`` unescaped and an
``<img src=x onerror=...>`` ran. The #548 sweep of the hierarchy pages found
the same shape in five places stage 2 had not reached:

* ``renderNode``'s level chip and ``showExamOverview``'s "Subjects by Level"
  row printed ``level_type`` raw -- a free-text column the subject importer
  writes from the file;
* the weight chip's ``title`` printed ``getWeightTooltip``, which carries
  ``exam_source`` (the source a file names), into a double-quoted attribute;
* the weight editor printed ``source_name`` (an official subject's
  ``exam_source``) and ``balancing_algorithm`` raw;
* ``Toast.show`` wrote its title and message as HTML, and the messages carry
  subject names -- "Renamed to ...", and the importer's own warnings, which
  quote the file's subject names back.

Both of the tree editor's load paths are exercised: ``loadHierarchy`` for a
plain exam and ``loadDimensionHierarchy`` for a dimensioned one, because the
dimensioned path is the common case (CLAUDE.md, *Dimension code path
symmetry*).

Each check is three-sided: the handler did not run, no ``<img>`` reached the
container, and the student's text reads back **exactly** -- escaping that
mangles the text fails as surely as escaping that is missing.
"""

from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.tree_details import open_tree_editor, select_subject, wait_for
from _helpers.tree_expand import expand_whole_tree

#: Breaks out of a double-quoted attribute AND runs in text content.
PAYLOAD = 'X "><img src=x onerror="window.__d=1">'

_PROBE = """
((sel) => {
    const els = Array.from(document.querySelectorAll(sel));
    return {
        fired: window.__d === 1,
        found: els.length,
        imgs: els.reduce((n, el) => n + el.querySelectorAll('img').length, 0),
        texts: els.map(el => el.textContent.trim()),
        titles: els.map(el => el.getAttribute('title')),
    };
})(%s)
"""


def _probe(page: WimiPage, selector: str) -> dict:
    return page.eval_js(_PROBE % json.dumps(selector))


def _assert_text(got: dict, expected: str, where: str) -> None:
    # `<img>` per container, not the global flag: an onerror fires
    # asynchronously, so the flag would blame whichever check ran first.
    assert got["found"], f"{where}: nothing rendered, so this proves nothing"
    assert got["imgs"] == 0, f"{where}: an <img> reached the DOM ({got!r})"
    assert expected in got["texts"], (
        f"{where}: expected the student's text exactly, got {got['texts']!r}")


def _assert_never_fired(page: WimiPage) -> None:
    page.wait_for_timeout(300)  # let any pending image error dispatch
    assert not page.eval_js("window.__d === 1"), (
        "an onerror handler RAN on this page; the per-site checks above say "
        "where only if the <img> is still in its container")


def _seed(db, *, dimensioned: bool):
    name = f"V548 {'dim' if dimensioned else 'plain'}"
    exam = db.create_exam_context(exam_name=name, exam_description="")
    dim = (db.create_dimension(exam_id=exam.id, name="System",
                               display_order=1, is_required=True)
           if dimensioned else None)
    root = db.create_subject_node(
        exam_context=name, name="V548 Root", level_type=PAYLOAD,
        exam_weight_low=10.0, exam_weight_high=20.0, exam_source=PAYLOAD,
        dimension_id=dim)
    db.create_subject_node(
        exam_context=name, name="V548 Sibling", level_type="System",
        exam_weight_low=5.0, exam_weight_high=9.0, dimension_id=dim)
    # An official subject is where getWeightConfig reads `source_name`.
    db.conn.execute("UPDATE subject_nodes SET weight_source = 'official' "
               "WHERE id = ?", (root.id,))
    db.conn.execute("UPDATE exam_contexts SET weight_validation_rules = json_set("
               "weight_validation_rules, '$.balancing_algorithm', ?) "
               "WHERE id = ?", (PAYLOAD, exam.id))
    db.conn.commit()
    return exam, root.id


@pytest.mark.slow
@pytest.mark.regression
@pytest.mark.parametrize("dimensioned", [False, True],
                         ids=["loadHierarchy", "loadDimensionHierarchy"])
def test_tree_rows_overview_and_weight_editor_show_text(
    wimi_session: WimiTestSession, wimi_page: WimiPage, dimensioned: bool,
) -> None:
    db = wimi_session.user.db
    exam, root = _seed(db, dimensioned=dimensioned)
    assert db.exam_uses_dimensions(exam.id) == dimensioned, "seed drifted"

    open_tree_editor(wimi_page, exam.id)
    expand_whole_tree(wimi_page)

    _assert_text(_probe(wimi_page, ".level-count-name"), PAYLOAD,
                 "overview 'Subjects by Level'")
    _assert_text(_probe(wimi_page, f'.tree-node[data-id="{root}"] '
                                   '.tree-node-level'),
                 PAYLOAD, "row level chip")
    chip = _probe(wimi_page, f'[data-testid="tree-node-weight-{root}"]')
    assert chip["found"] and chip["imgs"] == 0, f"weight chip: {chip!r}"
    # Only the dimensioned payload carries `exam_source` to the row, so the
    # tooltip's "Source:" clause exists on that path alone.
    if dimensioned:
        assert chip["titles"][0].endswith(f"Source: {PAYLOAD}"), (
            f"the weight tooltip must carry the source verbatim: {chip!r}")

    select_subject(wimi_page, root)
    _assert_text(_probe(wimi_page, "#weight-editor-container"
                                   " .weight-mode-source"),
                 f"📋 {PAYLOAD}", "weight editor source name")
    src = _probe(wimi_page, "#weight-editor-container .weight-mode-source")
    assert src["titles"] == [PAYLOAD], src
    _assert_text(_probe(wimi_page, "#weight-editor-container"
                                   " .weight-algorithm-name"),
                 PAYLOAD, "weight editor balancing algorithm")
    _assert_never_fired(wimi_page)


def _open_plain_exam(db, page: WimiPage, name: str) -> int:
    exam = db.create_exam_context(exam_name=name, exam_description="")
    node = db.create_subject_node(exam_context=name, name="V548 Before",
                                  level_type="System").id
    open_tree_editor(page, exam.id)
    return node


def _toast(page: WimiPage, title: str) -> dict:
    """The one toast whose title is ``title``: its <img>s and its message."""
    wait_for(page, "Array.from(document.querySelectorAll('.toast-container"
                   f" > div')).some(t => t.textContent.includes({json.dumps(title)}))",
             what=f"the {title!r} toast")
    return page.eval_js(f"""
        (() => {{
            const t = Array.from(document.querySelectorAll(
                '.toast-container > div')).find(
                el => el.textContent.includes({json.dumps(title)}));
            const lines = Array.from(t.querySelectorAll(':scope > div > div'))
                .map(el => el.textContent);
            return {{found: 1, imgs: t.querySelectorAll('img').length,
                     texts: lines}};
        }})()
    """)


@pytest.mark.slow
@pytest.mark.regression
def test_a_rename_toast_shows_the_name_as_text(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    node = _open_plain_exam(wimi_session.user.db, wimi_page, "V548 rename")
    wimi_page.eval_js(f"finishInlineEdit({node}, {json.dumps(PAYLOAD)})",
                      await_promise=True)
    _assert_text(_toast(wimi_page, "Updated"), f'Renamed to "{PAYLOAD}"',
                 "rename toast")
    _assert_never_fired(wimi_page)


@pytest.mark.slow
@pytest.mark.regression
def test_an_import_warning_toast_quotes_the_file_as_text(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The real file path: a File through handleImportFileEnhanced, then the
    import. A band whose low is above its high makes the importer quote the
    subject's name back in a warning, which is shown as a toast -- so this is
    a FILE's contents reaching the page."""
    _open_plain_exam(wimi_session.user.db, wimi_page, "V548 import")
    data = {"root_nodes": [{"name": PAYLOAD, "level_type": "System",
                            "weight": {"low": 20, "high": 5}}]}
    err = wimi_page.eval_js(
        "handleImportFileEnhanced({target: {value: '', files: [new File("
        f"[{json.dumps(json.dumps(data))}], 'v548.json')]}}}}).then(() => null,"
        " e => String(e && e.stack || e))", await_promise=True)
    assert err is None, err
    _assert_text(_probe(wimi_page, "#import-preview-tree .preview-name"),
                 PAYLOAD, "import preview of the file")
    wimi_page.eval_js("executeImport()", await_promise=True)
    got = _toast(wimi_page, "Import warning")
    assert got["imgs"] == 0, f"import-warning toast: {got!r}"
    assert any(t.startswith(f'"{PAYLOAD}" has a weight low of 20 above')
               for t in got["texts"]), got["texts"]
    _assert_never_fired(wimi_page)


@pytest.mark.slow
@pytest.mark.regression
def test_search_highlight_does_not_split_an_entity(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The match was found in the ESCAPED name, so 'p' hit '&amp;'."""
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="V548 search", exam_description="")
    node = db.create_subject_node(exam_context=exam.exam_name,
                                  name="Salt & Pepper", level_type="System").id
    open_tree_editor(wimi_page, exam.id)
    wimi_page.eval_js("applyTreeSearch('p')")
    got = _probe(wimi_page, f"#name-{node}")
    assert got["texts"] == ["Salt & Pepper"], got
    marks = wimi_page.eval_js(
        f"Array.from(document.querySelectorAll('#name-{node} mark'))"
        ".map(m => m.textContent)")
    assert marks == ["P"], f"the highlight must wrap the matched text: {marks!r}"



#: A JS-string breakout. HTML escaping does not stop it inside an inline
#: handler: the parser decodes `&#39;` back to `'` before the script runs.
BATCH_ID = "x');window.__d=1;('"


@pytest.mark.slow
@pytest.mark.regression
def test_an_archived_batch_id_reaches_restore_as_data(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The Restore button carried its batch id in an inline ``onclick`` JS
    string. Ids are uuid4 when WIMI writes them, but a ``.wimi`` profile
    import installs a whole database, so the id is whatever that file says."""
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="V548 archive",
                                  exam_description="")
    node = db.create_subject_node(exam_context=exam.exam_name,
                                  name="V548 Archived", level_type="System").id
    db.conn.execute(
        "INSERT INTO subject_delete_batches (id, root_node_id, root_node_name)"
        " VALUES (?, ?, ?)", (BATCH_ID, node, "V548 Archived"))
    db.conn.execute(
        "UPDATE subject_nodes SET status = 'archived', deleted_batch_id = ?"
        " WHERE id = ?", (BATCH_ID, node))
    db.create_subject_node(exam_context=exam.exam_name, name="V548 Kept",
                           level_type="System")
    db.conn.commit()

    open_tree_editor(wimi_page, exam.id)
    wait_for(wimi_page, "!!document.querySelector("
                        "'[data-testid=\"tree-archived-restore\"]')",
             what="the archived panel's Restore button")
    # Record what the button hands to restore, and stop there: the restore
    # itself is test_archived_panel_restores_a_subject.py's business.
    wimi_page.eval_js("window.__calls = []; restoreArchivedBatch ="
                      " (id, kind) => { window.__calls.push([id, kind]); }")
    wimi_page.eval_js("document.querySelector("
                      "'[data-testid=\"tree-archived-restore\"]').click()")
    calls = wimi_page.eval_js("window.__calls")
    assert calls == [[BATCH_ID, "subject"]], (
        f"Restore must receive the batch id exactly: {calls!r}")
    _assert_never_fired(wimi_page)
