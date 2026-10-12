"""Regression: the alias manager renders stored values as text (#597, #548).

`_renderAliases` built each row from a template literal interpolating **five**
database values: `alias.id` into `data-id` and into two inline `onclick`
handlers, and `alias_type` into a class attribute and into `_getTypeLabel`,
whose fallback returns the raw value. The tree editor's alias chip
(`renderAliasPreview`) interpolated `alias_type` into a class attribute as
well.

Measured on master before the fix, by the #548 sweep's page probe against a
crafted `subject_aliases`: **opening the modal ran the payload** (two `<img>`,
one from the class attribute and one from the label's fallback) and **one click
on the star ran the stored id as JavaScript**. `tree_editor.html` loads
`api/_bridge.js`, so injected script on that page holds the whole bridge --
every `@pyqtSlot`, including `deleteSubjectNode` and profile export.

**Why a test can seed this at all.** Normal use cannot: `alias_type` carries
`CHECK (alias_type IN (...))` and `id` is `INTEGER PRIMARY KEY AUTOINCREMENT`.
Both live in the DDL, and an installed profile brings its own DDL --
`install_profile_as_new` / `replace_profile` copy the incoming database byte for
byte and `preflight_schema` never looks at the tables. So the Arrange here
rebuilds the table the way an imported one could already be shaped. **Nothing
attack-shaped is committed**: the mutation is three lines of SQL in this file,
not a crafted archive, because `master` is published to a public mirror.

Whether the importer should validate an incoming schema is #593, and is the
owner's. This file is about the sink, which needs no decision: it is the same
escaping the rest of #548 applied everywhere else.

The fourth assertion is the one that keeps the fix honest. The per-type class
is emitted only for a *known* type, so a payload type is dropped rather than
escaped -- and `alias_manager.js` loads **after** `tree_editor.js` on that
page, so the chip reads `AliasManager.ALIAS_TYPES` across a load-order
dependency. Asserting that a known type still gets its class is what would
catch that dependency breaking; without it, "no payload class" would pass
against a version that emits no classes at all.
"""

from __future__ import annotations

import json

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

EXAM = "Alias Payload Exam"

#: Records into a window global rather than fetching: `main_window.py` sets
#: `LocalContentCanAccessRemoteUrls=False`, so a beacon proves nothing here.
HANDLER = 'onerror="(window.__x=window.__x||[]).push(1)"'
PAYLOAD_TYPE = f'eponym"><img src=x {HANDLER}>'
PAYLOAD_ID = "1);window.__hit=1;(1"

_READ = """
(() => {
  const list = document.getElementById('alias-list');
  const chip = document.querySelector('#alias-preview .alias-chip, .alias-chip');
  return JSON.stringify({
    fired: (window.__x || []).length,
    hit: window.__hit || null,
    imgs: list ? list.querySelectorAll('img').length : null,
    texts: list ? [...list.querySelectorAll('.alias-name')].map(e => e.textContent) : null,
    badges: list ? [...list.querySelectorAll('.alias-type-badge')]
        .map(e => ({cls: e.className, text: e.textContent.trim()})) : null,
    rows: list ? list.querySelectorAll('.alias-item').length : null,
  });
})()
"""


@pytest.fixture
def aliases(wimi_session: WimiTestSession, wimi_page: WimiPage):
    """A subject whose aliases came from a database WIMI did not write."""
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name=EXAM, exam_description="#597")
    root = db.create_subject_node(EXAM, "Cardiomyopathy", "System")

    # Reshape `subject_aliases` the way an imported database could already be:
    # no CHECK on alias_type, and a TEXT id. This is the state #593's variants
    # A and D installed with `schema_verdict=ok`.
    # Mirrors user_db_schema_v1_subject_aliases.sql column for column, with
    # exactly two deliberate differences: no CHECK on `alias_type`, and `id`
    # declared TEXT. Every other column is kept because the reader selects
    # them -- an invented column here makes the panel fail to load, which reads
    # like the fix being broken rather than the fixture.
    db.conn.executescript(
        """
        DROP TABLE IF EXISTS subject_aliases;
        CREATE TABLE subject_aliases (
            id TEXT PRIMARY KEY,
            subject_node_id INTEGER NOT NULL,
            exam_context VARCHAR(50) NOT NULL,
            alias_name VARCHAR(255) NOT NULL,
            alias_type VARCHAR(50) NOT NULL DEFAULT 'alternate_name',
            is_primary BOOLEAN DEFAULT FALSE,
            usage_count INTEGER DEFAULT 0,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    db.conn.executemany(
        "INSERT INTO subject_aliases "
        "(id, subject_node_id, exam_context, alias_name, alias_type, is_primary) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            # The control: a legitimate row, so the positive assertions below
            # are about a working panel rather than an empty one.
            ("7", root.id, EXAM, "Broken heart syndrome", "eponym", 1),
            (PAYLOAD_ID, root.id, EXAM, "Takotsubo", PAYLOAD_TYPE, 0),
        ],
    )
    db.conn.commit()

    wimi_page.goto("tree-editor")
    assert poll(
        wimi_page,
        "typeof AliasManager !== 'undefined' && typeof WimiEscape !== 'undefined'",
        timeout_ms=20000,
    ), "the page never finished loading its scripts"

    wimi_page.eval_js(
        f"AliasManager.open({root.id}, '{EXAM}', 'Cardiomyopathy'); true")
    assert poll(
        wimi_page,
        "document.querySelectorAll('#alias-list .alias-item').length === 2",
        timeout_ms=20000,
    ), "the alias list never rendered both rows"
    return wimi_page


@pytest.mark.slow
@pytest.mark.regression
def test_opening_the_panel_runs_nothing(aliases):
    """The headline. On master this fired twice and parsed two images."""
    state = json.loads(aliases.eval_js(_READ))

    assert state["rows"] == 2, state
    assert state["fired"] == 0, f"a stored alias_type ran as markup: {state}"
    assert state["imgs"] == 0, f"a stored alias_type was parsed as HTML: {state}"


@pytest.mark.slow
@pytest.mark.regression
def test_the_stored_values_are_shown_as_text(aliases):
    """An escape that mangles or drops the student's text fails too."""
    state = json.loads(aliases.eval_js(_READ))

    assert "Takotsubo" in state["texts"], state["texts"]
    assert "Broken heart syndrome" in state["texts"], state["texts"]

    # `_getTypeLabel` falls back to the raw value for an unknown type, which is
    # reasonable to display and safe through textContent.
    labels = [b["text"] for b in state["badges"]]
    assert PAYLOAD_TYPE in labels, labels


@pytest.mark.slow
@pytest.mark.regression
def test_a_known_type_still_gets_its_class_and_an_unknown_one_does_not(aliases):
    """The control for the allowlist, and for a load-order dependency.

    Without the first assertion, "the payload is not in a class" would pass
    against a version that stopped emitting per-type classes altogether --
    including one broken by `alias_manager.js` loading after `tree_editor.js`.
    """
    state = json.loads(aliases.eval_js(_READ))
    classes = [b["cls"] for b in state["badges"]]

    assert any("alias-type-eponym" in c for c in classes), (
        f"the known type lost its class, so this file's other assertions "
        f"would pass for the wrong reason: {classes}")
    assert not any("img" in c or "<" in c for c in classes), classes


@pytest.mark.slow
@pytest.mark.regression
def test_pressing_the_star_does_not_run_the_stored_id(aliases):
    """The second half of the defect: one click executed the id as JavaScript.

    The handler closes over the alias rather than reading an id back out of an
    attribute, so there is no string round trip to inject into.
    """
    aliases.eval_js(
        "document.querySelectorAll('#alias-list .alias-primary-toggle')[1]"
        ".click(); true")
    aliases.wait_for_timeout(300)
    state = json.loads(aliases.eval_js(_READ))

    assert state["hit"] is None, (
        f"the stored id ran as JavaScript on click: {state}")
