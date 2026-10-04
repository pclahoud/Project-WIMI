"""Issue #119 - settings changed while the page is still loading.

    "`settings.html` ships every control enabled [...] `loadSettings()`
    calls `populateForm(prefs)`, which unconditionally writes `el.value` /
    `el.checked` for **every** `[data-field]` element on the page, and
    follows it with `clearDirty()`. So a student who changes the theme, the
    font size, the primary colour or a hotkey in that window gets all of it
    overwritten by the stored preferences - and because `clearDirty()` runs
    immediately afterwards, the unsaved-changes guard does not fire either."

The fix is #114's gate, applied as ``docs/guides/PAGE_GATE.md`` describes:
``.app-container`` ships ``inert`` and ``markSettingsPageReady()`` removes it.
The *other* half of the issue's title - ``clearDirty()`` hiding a revert - has
its own file, ``test_settings_save_does_not_hide_an_edit.py``, because the gate
closes the load window and the save window is a different one.

Two things about the placement are worth a test rather than a comment
--------------------------------------------------------------------
**The release is at the end of ``init()``, not after ``loadSettings()``.** The
issue's own "what should have happened" says the controls should not be ready
until ``loadSettings()`` has populated them, and that would leave the defect
in place on a narrower window: ``renderPaneOpenMode()``,
``renderSttDevices()`` and ``renderSttModels()`` all run *after*
``loadSettings()`` returns and all assign ``select.value`` for controls that
carry ``data-field``. A microphone chosen in that tail would be reverted
exactly as a colour chosen earlier was.

**It is in a ``finally``.** ``init()``'s first statement is ``await
api.ready()`` and none of the eight sections after it is individually
guaranteed to catch, so a release reached only from the happy path would leave
a permanently dead page - a far worse bug than the one being fixed.

Why these tests are built the way they are
------------------------------------------
``inert`` blocks hit-tested input and focus but **not** ``el.value = 'x'``,
``el.click()`` or ``body.innerHTML = ...``. A test written with those passes
against a completely ungated page. Every gesture here goes through
``Input.dispatchMouseEvent`` / ``Input.insertText``, and the window is widened
by holding the page's bridge calls from a document-start hook rather than
raced. See ``_helpers/w114_form_ready.py``.

All probed controls are in the **Appearance** panel, which is the one the
sidebar opens on. The other panels are ``display: none``, so an element in one
has no box and no click can be aimed at it - which would read as a refusal
whatever the gate did.
"""
from __future__ import annotations

import pytest

from _helpers.page_gate import (
    assert_gate_can_be_heard,
    assert_still_gated,
    ax_mentions,
    ax_snapshot,
    ax_summary,
    enable_accessibility,
    gate_state,
    is_gated,
    wait_for_release,
)
from _helpers.w114_form_ready import (
    assert_slow_bridge_took,
    centre_of,
    install_slow_bridge,
    poll,
    real_click,
    real_type,
)
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

# A stored colour nobody would type and that is no default anywhere in the
# tree, so "the field shows the stored value" is an assertion rather than a
# coincidence with the markup's own `value="#2563eb"`.
STORED_COLOUR = "#0b7a6e"
DURING = "#ff00ff"

PAGE_RENDERED = "(() => !!document.getElementById('primary_color_hex'))()"
COLOUR_VALUE = "document.getElementById('primary_color_hex').value"
ANIMATIONS_CHECKED = "document.getElementById('show_animations').checked"
ACTIVE_ID = (
    "(() => document.activeElement ? document.activeElement.id"
    " || document.activeElement.tagName : null)()"
)
# `#pane_default_source_id` ships with ZERO options; renderPaneOpenMode()
# replaces its whole list, and is reached from initQuestionBanks() -- in the
# tail of init(), after loadSettings() has returned.
PANE_PICKER_FILLED = (
    "(() => { const el ="
    " document.getElementById('pane_default_source_id');"
    " return !!el && el.options.length > 0; })()"
)
# The sighted half of the gate: `[data-page-gated][inert]` in styles.css fades
# the page to 0.55 after a 250 ms delay. This is the only check anywhere that
# the dim still works -- it was `.entry-page[inert]` in entry.css until #119
# and #120 needed it on two more pages, and a selector that stopped matching
# would produce no error, just a page that silently stops saying it is busy.
PAGE_IS_DIMMED = (
    "(() => { const p = document.querySelector('[data-page-gated]');"
    " return !!p && parseFloat(getComputedStyle(p).opacity) < 1; })()"
)
PAGE_IS_FULL_STRENGTH = (
    "(() => { const p = document.querySelector('[data-page-gated]');"
    " return !!p && parseFloat(getComputedStyle(p).opacity) === 1; })()"
)
# `settingsPage` is a top-level `const` in a classic script, so it is a global
# binding rather than a property of `window` -- `window.settingsPage` is
# undefined and the bare name is what resolves.
IS_DIRTY = (
    "(() => { try { return typeof settingsPage !== 'undefined'"
    " ? settingsPage.isDirty : null; } catch (e) { return null; } })()"
)

# Strings the shipped page owns. Quoted rather than read from the page so a fix
# that empties the message cannot make the test agree with it.
HOLDING = "Preparing the settings page"
READY = "Settings ready"

# A control: a label only the gated container has. If this is in the
# accessibility tree the page is not gated, whatever the attribute says.
PAGE_ONLY = "Reset to Defaults"

# Make `api.ready()` reject, from before the page's first script. `init()`'s
# very first statement awaits it, so this is the failure that reaches the
# `finally` without any of the eight init sections having run -- the one a
# release written at the end of the happy path would miss.
BREAK_API_READY = """
(() => {
  let real;
  Object.defineProperty(window, 'api', {
    configurable: true,
    get() { return real; },
    set(value) {
      real = value;
      if (value && typeof value === 'object') {
        value.ready = () => Promise.reject(new Error('W119 forced failure'));
      }
    }
  });
})();
"""


def _seed(db) -> None:
    db.update_preferences(primary_color_hex=STORED_COLOUR, show_animations=True)
    db.conn.commit()


@pytest.mark.slow
@pytest.mark.regression
def test_changes_made_during_load_are_refused_rather_than_reverted(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The defect and its release, asserted as explicitly as each other."""
    # ---- Arrange ----------------------------------------------------------
    _seed(wimi_session.user.db)
    install_slow_bridge(wimi_page)
    wimi_page.goto("settings", wait_for_bridge=False)
    assert poll(wimi_page, PAGE_RENDERED), "the settings markup never rendered"
    assert_slow_bridge_took(wimi_page)

    # ---- Act: inside the window -------------------------------------------
    assert_still_gated(wimi_page, "before the probe started")

    real_click(wimi_page, centre_of(wimi_page, "#primary_color_hex"))
    active_during = wimi_page.eval_js(ACTIVE_ID)
    real_type(wimi_page, DURING)
    colour_during = wimi_page.eval_js(COLOUR_VALUE)
    assert_still_gated(wimi_page, "after typing a colour during load")

    real_click(wimi_page, centre_of(wimi_page, "#show_animations"))
    animations_during = wimi_page.eval_js(ANIMATIONS_CHECKED)
    dirty_during = wimi_page.eval_js(IS_DIRTY)
    dimmed_during = poll(wimi_page, PAGE_IS_DIMMED, timeout_ms=5000)
    assert_still_gated(wimi_page, "after clicking the animations checkbox")

    # ---- Assert: refused --------------------------------------------------
    assert active_during != "primary_color_hex", (
        f"focus reached the primary-colour field during load (activeElement="
        f"{active_during!r}); anything typed there is overwritten by "
        f"populateForm() and then hidden by clearDirty() (#119)")
    assert DURING not in (colour_during or ""), (
        f"a colour typed during load landed in the field "
        f"(value={colour_during!r}). populateForm() writes every "
        f"[data-field] element unconditionally and clearDirty() runs on the "
        f"next line, so this is the state where the change is reverted with "
        f"the unsaved-changes guard still reading clean (#119)")
    assert animations_during is True, (
        "a real click toggled the 'Show animations' checkbox during load. "
        "populateForm() writes `el.checked` for every [data-field] element, "
        "so the student watches the box they ticked tick itself back (#119)")
    assert dirty_during is not True, (
        f"the page reported itself dirty from input it had not accepted "
        f"(isDirty={dirty_during!r})")
    assert dimmed_during is True, (
        "the page never dimmed during a load held open for seconds. That is "
        "the only thing a student who can see the screen is told, and it "
        "comes from `[data-page-gated][inert]` in styles.css -- a selector "
        "that stops matching produces no error anywhere (#114, #119)")

    # ---- Act: after the page is handed over -------------------------------
    wait_for_release(wimi_page)
    colour_after_load = wimi_page.eval_js(COLOUR_VALUE)
    real_click(wimi_page, centre_of(wimi_page, "#primary_color_hex"))
    active_after = wimi_page.eval_js(ACTIVE_ID)
    real_click(wimi_page, centre_of(wimi_page, "#show_animations"))
    animations_after = wimi_page.eval_js(ANIMATIONS_CHECKED)
    dirty_after = wimi_page.eval_js(IS_DIRTY)

    # ---- Assert: cleared, as explicitly as it was blocked -----------------
    assert is_gated(wimi_page) is False, (
        "the page stayed gated after init finished. A permanently gated page "
        "is a far worse bug than the one #119 describes, which is why the "
        "release is in a `finally` (#114's rule)")
    assert colour_after_load == STORED_COLOUR, (
        f"the field does not show the stored colour after load "
        f"(value={colour_after_load!r}, stored={STORED_COLOUR!r}), so this "
        f"test is not measuring a page that loaded its preferences at all")
    assert active_after == "primary_color_hex", (
        f"a real click did not focus the colour field after handover "
        f"(activeElement={active_after!r}) - the gate never lifted for input")
    assert animations_after is False, (
        "a real click did not toggle the animations checkbox after handover, "
        "so the page is still refusing input it is supposed to accept")
    assert dirty_after is True, (
        f"toggling a control after handover did not mark the page dirty "
        f"(isDirty={dirty_after!r}), so the unsaved-changes guard would not "
        f"fire for a real edit either")
    assert poll(wimi_page, PAGE_IS_FULL_STRENGTH, timeout_ms=3000), (
        "the page is still dimmed after handover. Removing `inert` drops the "
        "rule, so this means the attribute is gone and the dim is not -- a "
        "live page that looks permanently busy")


@pytest.mark.slow
@pytest.mark.regression
def test_the_gate_covers_the_whole_of_init_not_just_loadSettings(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The placement decision, measured rather than left to a comment.

    The issue's own "what should have happened" proposes that the controls be
    ready once ``loadSettings()`` has populated them. That would leave the
    defect in place on a narrower window, because ``init()``'s tail writes
    ``data-field`` controls too - ``renderPaneOpenMode()`` replaces
    ``#pane_default_source_id``'s whole option list, and ``renderSttModels()``
    does the same for ``#stt_model_size``. Both ship with **zero** options in
    the markup, so "this select has options" is an unambiguous marker that the
    tail has run.

    Asserting the *timing* rather than typing into them is deliberate: both
    live in sidebar panels that are ``display: none`` until their nav button is
    clicked, and those buttons are inside the gate, so no real gesture can
    reach either control during the window. What can be measured is that their
    writes land while the page is still refusing input - which is the property
    that makes the placement correct.
    """
    # ---- Arrange ----------------------------------------------------------
    _seed(wimi_session.user.db)
    install_slow_bridge(wimi_page)
    wimi_page.goto("settings", wait_for_bridge=False)
    assert poll(wimi_page, PAGE_RENDERED), "the settings markup never rendered"
    assert_slow_bridge_took(wimi_page)

    # ---- Act: wait for a write that happens AFTER loadSettings() ----------
    assert poll(wimi_page, PANE_PICKER_FILLED, timeout_ms=60000), (
        "#pane_default_source_id never gained an option, so this run cannot "
        "say anything about the tail of init(). renderPaneOpenMode() is "
        "reached from initQuestionBanks()")

    # ---- Assert: the page was still gated when it landed ------------------
    assert is_gated(wimi_page) is True, (
        "a `data-field` control was rewritten by the tail of init() after the "
        "page had already been handed over. #pane_default_source_id and "
        "#stt_model_size have their option lists replaced by "
        "renderPaneOpenMode() / renderSttModels(), both of which run after "
        "loadSettings() returns, so a release placed there leaves #119 in "
        "place on a narrower window: a question bank or a microphone chosen "
        "in the tail is reverted exactly as a colour chosen earlier was. The "
        "release belongs at the END of init(), in its `finally`")


@pytest.mark.slow
@pytest.mark.regression
def test_the_gate_is_in_the_accessibility_tree_while_the_page_is_not(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """#127 on this page, measured where it is observable at all.

    ``inert`` removes the gated subtree from the accessibility tree, so the
    gate is silence as well as refusal. The way to get the fix wrong is to put
    the status region *inside* ``.app-container``, where it keeps its role, its
    ``aria-live``, its text and a non-zero box, is removed from the tree with
    everything else, and passes every DOM-level check ever written about it.
    ``tests/test_page_gate_markup.py`` guards the markup; this measures the
    tree.

    No screen reader was run - this box has none and CDP cannot observe an
    announcement. What is measured is that the gate's text is in the tree
    while the page is not, and that the text changes at handover.
    """
    # ---- Arrange ----------------------------------------------------------
    install_slow_bridge(wimi_page)
    wimi_page.goto("settings", wait_for_bridge=False)
    assert poll(wimi_page, PAGE_RENDERED), "the settings markup never rendered"
    assert_slow_bridge_took(wimi_page)
    enable_accessibility(wimi_page)

    # ---- Act: inside the window -------------------------------------------
    gated_during = is_gated(wimi_page)
    during_gate = gate_state(wimi_page)
    during_ax = ax_snapshot(wimi_page)

    # ---- Assert: the gate is up, and audible ------------------------------
    assert gated_during is True, (
        "the page was not gated when the probe ran, so nothing below is "
        "measuring the window this test is about. Raise BRIDGE_DELAY_MS "
        "rather than weakening the assertion")
    assert_gate_can_be_heard(during_gate, where="while the gate was up")
    assert HOLDING.lower() in during_gate["text"].lower(), (
        f"the gate carries no holding message while it holds "
        f"(text={during_gate['text']!r}); a screen reader lands on a document "
        f"that is empty and silent (#127)")
    assert ax_mentions(during_ax, HOLDING), (
        f"'{HOLDING}' is NOT in the accessibility tree while the gate is up, "
        f"so a screen reader is still handed an empty document. This is the "
        f"failure mode of putting the status element inside the `inert` "
        f"container: present in the DOM, absent from the tree. "
        f"Tree: {ax_summary(during_ax)}")
    assert not ax_mentions(during_ax, PAGE_ONLY), (
        f"the settings page itself is already exposed to assistive technology "
        f"during the gate ({PAGE_ONLY!r} is in the tree), so the gate is not "
        f"doing what this test assumes and the measurement is of some other "
        f"state. Tree: {ax_summary(during_ax)}")

    # ---- Act: after handover ----------------------------------------------
    wait_for_release(wimi_page)
    after_gate = gate_state(wimi_page)
    after_ax = ax_snapshot(wimi_page)

    # ---- Assert: the handover is announced, and the page arrives ----------
    assert after_gate["state"] == "ready", (
        f"PageGate.release() never ran: the gate still reads "
        f"state={after_gate['state']!r} after the page was handed over. "
        f"markSettingsPageReady() is the one place that calls it (#127)")
    assert READY.lower() in after_gate["text"].lower(), (
        f"the gate's text did not change to the ready message "
        f"(text={after_gate['text']!r}). The text change IS the "
        f"announcement; without it a reader gets no event when the page "
        f"arrives (#127)")
    assert ax_mentions(after_ax, PAGE_ONLY), (
        f"the settings page is still not exposed to assistive technology "
        f"after the gate lifted - `inert` removed but something else is "
        f"hiding it. Tree: {ax_summary(after_ax)}")
    assert after_ax["exposed"] > during_ax["exposed"] * 10, (
        f"the accessibility tree barely grew when the gate lifted "
        f"({during_ax['exposed']} -> {after_ax['exposed']} exposed nodes); "
        f"measured on the entry form's fix, 1 -> 290")


@pytest.mark.slow
@pytest.mark.regression
def test_a_failed_init_still_releases_and_still_stops_holding(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The unhappy path, where "permanently gated and silent" would hide.

    ``init()``'s first statement is ``await api.ready()`` and this page does
    not redirect when its init fails - it stays put. So a release reached only
    from the end of the happy path leaves a dead page on screen for as long as
    the student looks at it, which is a far worse bug than the one #119
    describes (#114's own rule). The release lives in a ``finally`` for that
    reason, and this is the test that would notice if it moved.
    """
    # ---- Arrange / Act ----------------------------------------------------
    wimi_page.tab.Page.enable()
    wimi_page.tab.Page.addScriptToEvaluateOnNewDocument(source=BREAK_API_READY)
    wimi_page.goto("settings", wait_for_bridge=False)
    assert poll(wimi_page, PAGE_RENDERED), "the settings markup never rendered"
    released = poll(
        wimi_page,
        "(() => { const p = document.querySelector('[data-page-gated]');"
        " return !!p && !p.hasAttribute('inert'); })()",
        timeout_ms=20000)

    # ---- Assert -----------------------------------------------------------
    assert released, (
        "the page stayed gated after init() failed on its first statement. "
        "The `finally` in init() is not releasing it, which leaves a "
        "permanently dead page the student has no way out of (#114, #119)")
    state = gate_state(wimi_page)
    assert state["state"] == "ready", (
        f"the page was released but the gate was left holding "
        f"(state={state['state']!r}), so assistive technology is still being "
        f"told the page is being prepared while it has actually given up. "
        f"PageGate.release() must be reached from the same exits "
        f"markSettingsPageReady() is (#127)")
    assert HOLDING.lower() not in state["text"].lower(), (
        f"the gate still reads {state['text']!r} after the page was released")


# ---------------------------------------------------------------------------
# Why each assertion catches the regression
# ---------------------------------------------------------------------------
#
# * `active_during != "primary_color_hex"`, `DURING not in colour_during` and
#   `animations_during is True` all fail against master, where every control
#   ships enabled. They are the three halves of "the page refuses what it
#   cannot keep": focus, text, and a click on a checkbox.
# * `colour_after_load == STORED_COLOUR` is the control. Without it the three
#   assertions above would pass against a page that had simply failed to load
#   its preferences at all, which is a different bug wearing this fix's face.
# * `active_after`, `animations_after is False` and `is_gated(...) is False`
#   fail against a gate that never lifts - the worse bug, and the one a test
#   that only checked refusal could not distinguish.
# * `ax_mentions(during_ax, HOLDING)` fails against a bare `inert` copied from
#   #114 with no voice, and against the status element nested inside
#   `.app-container` - which is precisely what no DOM-level assertion can tell
#   apart from a correct one.
# * `not ax_mentions(during_ax, PAGE_ONLY)` is that assertion's control: it
#   fails against a page that had stopped gating itself, which would be #119
#   reopened and #127 "fixed".
