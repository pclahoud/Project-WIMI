"""Regression: Settings -> Appearance, the Font Family select renders blank.

Forgejo issue #9 -- "[bug] Settings: Font Family select renders blank":

    Under Appearance, the **Font Family** dropdown renders with no visible
    value -- an empty control with just the chevron. Every other select on
    the same panel shows its current value: Theme ``Default (Light)``,
    Font Size ``16 px -- Default``, UI Density ``Comfortable``. [...] Not
    yet read back from the DOM, so I do not know whether the select has
    zero options or has options with no selection -- that is the first
    thing to check.

This scenario answers that question in the assertions rather than leaving
it to a screenshot: it reads the option list *and* the selection, so a
failure says which of the two candidate causes is live.

Why it failed: the select is not populated from a font enumeration -- it
carries exactly one static option, and that option's value was
``system_default`` while every other layer of the stack stores the same
preference as ``system`` (``m001_baseline`` defaults the column to
``'system'``, ``UserPreferences.font_family`` defaults to ``'system'``,
and ``SettingsPage.DEFAULTS`` repeats it). ``populateForm`` ends with a
bare ``el.value = value``; assigning a value that matches no
``option[value]`` drives a ``<select>`` to ``selectedIndex === -1``, which
paints an empty control. So the options existed and the *value* was the
outlier -- cause two of the two named in the issue.

What the fix changes: ``settings.html`` spells the option's value
``system``, the value the rest of the stack already agrees on, and marks
it ``selected`` the way the Font Size and UI Density defaults are marked.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

# populateForm fills the primary-colour text input, which has no value
# attribute in the markup -- a DOM-only signal that preferences landed.
PREFS_LOADED = "document.getElementById('primary_color_hex').value !== ''"
FRESH_DOC = "typeof window.__wimiPrevDoc === 'undefined' && typeof window.api === 'object'"

PROBE = """
(() => { const s = document.getElementById('font_family');
  if (!s) return JSON.stringify({ missing: true });
  return JSON.stringify({
    missing: false,
    optionValues: Array.from(s.options).map(o => o.value),
    optionCount: s.options.length,
    selectedIndex: s.selectedIndex,
    value: s.value,
    shown: s.selectedIndex >= 0
      ? s.options[s.selectedIndex].textContent.trim() : ''
  }); })()
"""


def _poll(wimi_page: WimiPage, js: str, want, *, timeout_ms: int = 10000):
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = wimi_page.eval_js(js)
        except Exception:  # context torn down mid-navigation
            last = None
        if last == want:
            return last
        wimi_page.wait_for_timeout(100)
        elapsed += 100
    return last


def _open_appearance(wimi_page: WimiPage, *, revisit: bool = False) -> dict:
    """Load Settings (Appearance is the panel that starts active) and probe."""
    if revisit:
        # Page.navigate returns before the new document commits, so mark the
        # old one and wait for it to go.
        wimi_page.eval_js("window.__wimiPrevDoc = true")
    wimi_page.goto('settings')
    if revisit:
        assert _poll(wimi_page, FRESH_DOC, True) is True, 'Settings page did not reload'
    assert _poll(wimi_page, PREFS_LOADED, True) is True, 'Preferences never populated the form'
    return json.loads(wimi_page.eval_js(PROBE))


@pytest.mark.slow
@pytest.mark.regression
def test_font_family_shows_its_current_value(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    # A fresh profile: no appearance preferences written, so the select
    # must fall back to the stored default.
    db = wimi_session.user.db
    stored = db.get_preferences().font_family

    # ---- Act ---------------------------------------------------------
    probe = _open_appearance(wimi_page)

    # ---- Assert: which of the two candidate causes is live -----------
    assert probe['missing'] is False, 'No #font_family select on the Appearance panel'
    assert probe['optionCount'] > 0, (
        'Font Family has zero options -- the list is populated from something '
        f'empty: {probe!r}'
    )
    # The reporter's symptom: an empty control with just the chevron.
    assert probe['selectedIndex'] != -1 and probe['value'] != '', (
        f'Font Family renders blank: {probe!r}. The options exist, so the stored '
        f'value {stored!r} matches no option[value]; assigning it in populateForm '
        'drives the select to selectedIndex -1.'
    )
    assert probe['shown'] != '', f'Font Family has a selection but no label: {probe!r}'

    # ---- Assert: it shows the *current* font family ------------------
    assert stored in probe['optionValues'], (
        f'The stored font_family {stored!r} is not offered by the select '
        f'{probe["optionValues"]!r}; the option list and the preference '
        'vocabulary disagree.'
    )
    assert probe['value'] == stored, (
        f'Font Family shows {probe["value"]!r} but the stored preference is {stored!r}'
    )


@pytest.mark.slow
@pytest.mark.regression
def test_every_offered_font_round_trips(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """Each option the select offers must come back selected after a save.

    Guards the mismatch in both directions: renaming an option value (or
    adding a typeface the store does not accept) breaks this before it
    reaches a screenshot.
    """
    db = wimi_session.user.db
    offered = _open_appearance(wimi_page)['optionValues']
    assert offered, 'No font options to round-trip'

    for value in offered:
        db.update_preferences(font_family=value)
        probe = _open_appearance(wimi_page, revisit=True)
        assert probe['value'] == value, (
            f'Stored font_family {value!r} came back as {probe["value"]!r} '
            f'(selectedIndex {probe["selectedIndex"]}): {probe!r}'
        )


@pytest.mark.slow
@pytest.mark.regression
def test_unrecognised_stored_font_falls_back_to_the_declared_default(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """A stored value no option carries must not paint an empty control.

    ``system_default`` is the value the pre-fix markup offered, so a profile
    that picked the lone option in the broken control has it saved. Any
    unknown value should land on the option the markup marks ``selected``
    rather than on selectedIndex -1.
    """
    wimi_session.user.db.update_preferences(font_family='system_default')

    probe = _open_appearance(wimi_page)

    assert probe['selectedIndex'] != -1 and probe['shown'] != '', (
        f'An unrecognised stored font_family still renders blank: {probe!r}'
    )
    assert probe['value'] in probe['optionValues'], probe
