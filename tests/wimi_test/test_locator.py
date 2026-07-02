"""Unit tests for ``wimi_test.locator`` (pychrome edition).

pychrome is not a hard dependency for these tests: the ``Tab`` is a
``unittest.mock.MagicMock`` exposing ``.Runtime.evaluate(expression=...)``
and ``.Input.dispatchMouseEvent(...)``. The tests exercise the three
resolution strategies of :func:`build_locator`, the input-validation
guards, and the auto-wait / read behaviour of :class:`WimiLocator`.

See ``docs/planning/PYCHROME_MIGRATION.md`` Section 5.3 for the design
this file mirrors.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from wimi_test.errors import AssertionFailureWithCapture
from wimi_test.locator import (
    LocatorStrategy,
    WimiLocator,
    build_locator,
)


# ---------------------------------------------------------------------- helpers


def _make_tab() -> MagicMock:
    """Build a MagicMock standing in for a pychrome ``Tab``.

    We expose two attributes the locator uses: ``Runtime.evaluate`` and
    ``Input.dispatchMouseEvent``. ``Runtime.evaluate`` defaults to a
    benign empty result so accidental calls don't blow up; tests that
    care override ``side_effect`` or ``return_value`` directly.
    """
    tab = MagicMock(name="pychrome_tab")
    tab.Runtime.evaluate.return_value = {"result": {"type": "object", "value": None}}
    return tab


def _eval_value(value: object) -> dict:
    """Build a CDP-shaped ``Runtime.evaluate`` response carrying ``value``."""
    return {"result": {"type": "object", "value": value}}


# ---------------------------------------------------------------- build_locator


def test_build_locator_role_and_name_returns_role_and_name_strategy() -> None:
    """role+name produces a ROLE_AND_NAME locator with role-walking JS."""
    tab = _make_tab()

    wl = build_locator(tab, role="button", name="Save")

    assert isinstance(wl, WimiLocator)
    assert wl.strategy is LocatorStrategy.ROLE_AND_NAME
    # The JS should reference both the role and the accessible name and
    # contain the implicit-role helper signature.
    assert '"button"' in wl.selector_js
    assert '"Save"' in wl.selector_js
    assert "implicitRole" in wl.selector_js
    assert "accessibleName" in wl.selector_js


def test_build_locator_testid_returns_testid_strategy() -> None:
    """testid produces a TESTID locator using a CSS attribute selector."""
    tab = _make_tab()

    wl = build_locator(tab, testid="entry-form-save-button")

    assert wl.strategy is LocatorStrategy.TESTID
    assert '[data-testid="entry-form-save-button"]' in wl.selector_js
    assert "document.querySelector" in wl.selector_js


def test_build_locator_testid_escapes_quotes_and_backslashes() -> None:
    """A testid containing ``"`` and ``\\`` is safely escaped."""
    tab = _make_tab()

    wl = build_locator(tab, testid='weird"id\\with\\stuff')

    # The raw quotes/backslashes must be escaped so the embedded CSS
    # selector parses cleanly.
    assert '\\"' in wl.selector_js
    assert "\\\\" in wl.selector_js


def test_build_locator_css_returns_css_strategy() -> None:
    """css produces a CSS locator using a JS template literal."""
    tab = _make_tab()

    wl = build_locator(tab, css=".save-button")

    assert wl.strategy is LocatorStrategy.CSS
    # Template-literal form keeps the original selector intact (quotes etc.).
    assert ".save-button" in wl.selector_js
    assert "document.querySelector(`" in wl.selector_js


def test_build_locator_css_escapes_backticks() -> None:
    """A CSS selector containing a backtick is safely escaped."""
    tab = _make_tab()

    wl = build_locator(tab, css="[data-x=`value`]")

    # The backtick inside the selector is escaped to ``\``` so it does not
    # close the surrounding JS template literal early.
    assert "\\`" in wl.selector_js


# ------------------------------------------------------------- invalid inputs


def test_build_locator_role_without_name_raises() -> None:
    tab = _make_tab()
    with pytest.raises(ValueError, match="role and name must both be provided"):
        build_locator(tab, role="button")


def test_build_locator_name_without_role_raises() -> None:
    tab = _make_tab()
    with pytest.raises(ValueError, match="role and name must both be provided"):
        build_locator(tab, name="Save")


def test_build_locator_testid_and_css_raises() -> None:
    tab = _make_tab()
    with pytest.raises(ValueError, match="exactly one strategy"):
        build_locator(tab, testid="x", css=".y")


def test_build_locator_role_name_and_testid_raises() -> None:
    tab = _make_tab()
    with pytest.raises(ValueError, match="exactly one strategy"):
        build_locator(tab, role="button", name="Save", testid="t")


def test_build_locator_role_name_and_css_raises() -> None:
    tab = _make_tab()
    with pytest.raises(ValueError, match="exactly one strategy"):
        build_locator(tab, role="button", name="Save", css=".y")


def test_build_locator_no_args_raises() -> None:
    tab = _make_tab()
    with pytest.raises(ValueError, match="exactly one strategy"):
        build_locator(tab)


# ---------------------------------------------------------------- click


def test_click_polls_until_ready_and_dispatches_mouse_events() -> None:
    """``click`` polls until ``ready=True`` then dispatches moved+pressed+released."""
    tab = _make_tab()
    # First two polls report not_found, third reports ready with coordinates.
    tab.Runtime.evaluate.side_effect = [
        _eval_value({"ready": False, "reason": "not_found"}),
        _eval_value({"ready": False, "reason": "not_found"}),
        _eval_value({"ready": True, "x": 100.0, "y": 50.0}),
    ]
    wl = WimiLocator(tab, LocatorStrategy.TESTID, "document.querySelector('#x')")

    wl.click()

    assert tab.Runtime.evaluate.call_count == 3
    # Three dispatchMouseEvent calls in order: moved (cursor positioning),
    # pressed, then released. The ``mouseMoved`` matches Playwright's
    # production-faithful sequence and works around a QtWebEngine + CDP
    # quirk where the first press on a focusable element silently drops
    # ``mouseup``/``click`` if the synthetic cursor was never positioned
    # over the target first.
    assert tab.Input.dispatchMouseEvent.call_count == 3
    moved_call, pressed_call, released_call = tab.Input.dispatchMouseEvent.call_args_list
    assert moved_call.kwargs == {
        "type": "mouseMoved",
        "x": 100.0,
        "y": 50.0,
        "button": "none",
    }
    assert pressed_call.kwargs == {
        "type": "mousePressed",
        "x": 100.0,
        "y": 50.0,
        "button": "left",
        "clickCount": 1,
    }
    assert released_call.kwargs == {
        "type": "mouseReleased",
        "x": 100.0,
        "y": 50.0,
        "button": "left",
        "clickCount": 1,
    }


def test_click_dispatches_mouse_moved_before_pressed() -> None:
    """The ``mouseMoved`` event MUST precede ``mousePressed``.

    This is the core invariant of the QtWebEngine + CDP fix: positioning
    the synthetic cursor at the target before the press is what makes
    the full ``mousedown`` -> ``mouseup`` -> ``click`` sequence fire
    reliably on the first interaction with a previously-unfocused
    focusable element. If a future refactor accidentally reorders the
    calls (e.g. moves AFTER pressing), the bug returns silently --
    success is still reported but the click handler never fires.
    """
    tab = _make_tab()
    tab.Runtime.evaluate.return_value = _eval_value(
        {"ready": True, "x": 42.0, "y": 84.0}
    )
    wl = WimiLocator(tab, LocatorStrategy.TESTID, "document.querySelector('#x')")

    wl.click()

    # Pull just the ``type`` of each dispatched event in call order.
    types_in_order = [
        call.kwargs["type"] for call in tab.Input.dispatchMouseEvent.call_args_list
    ]
    assert types_in_order == ["mouseMoved", "mousePressed", "mouseReleased"], (
        f"Expected moved->pressed->released, got {types_in_order!r}"
    )

    # The cursor must be moved to the same coordinates the press uses --
    # moving to a different point would not solve the focus-handoff
    # problem the fix targets.
    moved_call = tab.Input.dispatchMouseEvent.call_args_list[0]
    pressed_call = tab.Input.dispatchMouseEvent.call_args_list[1]
    assert moved_call.kwargs["x"] == pressed_call.kwargs["x"]
    assert moved_call.kwargs["y"] == pressed_call.kwargs["y"]


def test_click_times_out_when_never_ready() -> None:
    """``click(timeout_ms=...)`` raises ``AssertionFailureWithCapture`` on timeout."""
    tab = _make_tab()
    tab.Runtime.evaluate.return_value = _eval_value(
        {"ready": False, "reason": "not_found"}
    )
    wl = WimiLocator(tab, LocatorStrategy.CSS, "document.querySelector('#x')")

    with pytest.raises(AssertionFailureWithCapture) as exc_info:
        wl.click(timeout_ms=200)

    msg = exc_info.value.message
    assert "css" in msg
    assert "200ms" in msg
    assert "not_found" in msg
    assert exc_info.value.captures is None
    # No mouse events should have been dispatched on a failed click.
    tab.Input.dispatchMouseEvent.assert_not_called()


def test_click_times_out_with_disabled_reason() -> None:
    """The last observed reason is surfaced in the timeout message."""
    tab = _make_tab()
    tab.Runtime.evaluate.return_value = _eval_value(
        {"ready": False, "reason": "disabled"}
    )
    wl = WimiLocator(tab, LocatorStrategy.TESTID, "document.querySelector('#x')")

    with pytest.raises(AssertionFailureWithCapture) as exc_info:
        wl.click(timeout_ms=150)

    assert "disabled" in exc_info.value.message


# ---------------------------------------------------------------- expect_visible


def test_expect_visible_succeeds_on_visible_response() -> None:
    """``expect_visible`` returns when the eval reports ``visible=True``."""
    tab = _make_tab()
    tab.Runtime.evaluate.return_value = _eval_value({"visible": True})
    wl = WimiLocator(tab, LocatorStrategy.TESTID, "document.querySelector('#x')")

    # Should not raise.
    wl.expect_visible()

    tab.Runtime.evaluate.assert_called_once()
    # The evaluated JS must reference the selector.
    expression = tab.Runtime.evaluate.call_args.kwargs["expression"]
    assert "document.querySelector('#x')" in expression


def test_expect_visible_times_out_when_never_visible() -> None:
    """``expect_visible`` raises ``AssertionFailureWithCapture`` on timeout."""
    tab = _make_tab()
    tab.Runtime.evaluate.return_value = _eval_value(
        {"visible": False, "reason": "not_visible"}
    )
    wl = WimiLocator(tab, LocatorStrategy.CSS, "document.querySelector('#x')")

    with pytest.raises(AssertionFailureWithCapture) as exc_info:
        wl.expect_visible(timeout_ms=200)

    assert "css" in exc_info.value.message
    assert "200ms" in exc_info.value.message
    assert "not_visible" in exc_info.value.message
    assert exc_info.value.captures is None


# ---------------------------------------------------------------- text


def test_text_returns_eval_value() -> None:
    """``text()`` returns the string the eval reports."""
    tab = _make_tab()
    tab.Runtime.evaluate.return_value = _eval_value("Hello, world")
    wl = WimiLocator(tab, LocatorStrategy.CSS, "document.querySelector('#x')")

    assert wl.text() == "Hello, world"

    expression = tab.Runtime.evaluate.call_args.kwargs["expression"]
    assert "textContent" in expression
    assert "document.querySelector('#x')" in expression


def test_text_returns_empty_string_when_eval_value_is_none() -> None:
    """A ``None`` eval value (missing element / null textContent) yields ``""``."""
    tab = _make_tab()
    tab.Runtime.evaluate.return_value = _eval_value(None)
    wl = WimiLocator(tab, LocatorStrategy.TESTID, "document.querySelector('#x')")

    assert wl.text() == ""


# ---------------------------------------------------------------- attribute


def test_attribute_returns_eval_value() -> None:
    """``attribute(name)`` returns the string the eval reports."""
    tab = _make_tab()
    tab.Runtime.evaluate.return_value = _eval_value("/foo/bar")
    wl = WimiLocator(tab, LocatorStrategy.ROLE_AND_NAME, "document.querySelector('#x')")

    assert wl.attribute("href") == "/foo/bar"

    expression = tab.Runtime.evaluate.call_args.kwargs["expression"]
    assert "getAttribute" in expression
    # The attribute name must be JSON-encoded inside the JS expression so
    # quotes / non-ASCII / etc. round-trip safely.
    assert '"href"' in expression


def test_attribute_returns_none_when_value_is_none() -> None:
    """A ``None`` eval value (missing attribute or element) yields ``None``."""
    tab = _make_tab()
    tab.Runtime.evaluate.return_value = _eval_value(None)
    wl = WimiLocator(tab, LocatorStrategy.TESTID, "document.querySelector('#x')")

    assert wl.attribute("data-missing") is None


# ---------------------------------------------------------------- fill


def test_fill_dispatches_focus_and_set_scriptlet_with_json_encoded_value() -> None:
    """``fill('hello')`` runs after the readiness poll and embeds JSON-encoded value."""
    tab = _make_tab()
    # First eval = readiness check (ready), second eval = fill scriptlet.
    tab.Runtime.evaluate.side_effect = [
        _eval_value({"ready": True, "x": 10.0, "y": 20.0}),
        _eval_value(True),
    ]
    wl = WimiLocator(tab, LocatorStrategy.TESTID, "document.querySelector('#x')")

    wl.fill("hello")

    # Two evaluates: readiness, then fill.
    assert tab.Runtime.evaluate.call_count == 2
    fill_expression = tab.Runtime.evaluate.call_args_list[1].kwargs["expression"]
    # The value must be JSON-encoded (quoted) in the embedded scriptlet.
    assert '"hello"' in fill_expression
    # The scriptlet must focus, set value, and dispatch input+change events.
    assert ".focus()" in fill_expression
    assert "el.value" in fill_expression
    assert "'input'" in fill_expression
    assert "'change'" in fill_expression


def test_fill_escapes_special_characters_via_json() -> None:
    """A value with quotes/newlines/backslashes is safely JSON-encoded."""
    tab = _make_tab()
    tab.Runtime.evaluate.side_effect = [
        _eval_value({"ready": True, "x": 10.0, "y": 20.0}),
        _eval_value(True),
    ]
    wl = WimiLocator(tab, LocatorStrategy.CSS, "document.querySelector('#x')")

    wl.fill('she said "hi"\nand left')

    fill_expression = tab.Runtime.evaluate.call_args_list[1].kwargs["expression"]
    # JSON encoding turns the raw newline into ``\n`` and the inner quotes
    # into ``\"`` -- verify both made it through unchanged.
    assert '\\"hi\\"' in fill_expression
    assert "\\n" in fill_expression


def test_fill_times_out_when_element_never_ready() -> None:
    """If readiness polling fails, ``fill`` raises and never dispatches the set scriptlet."""
    tab = _make_tab()
    tab.Runtime.evaluate.return_value = _eval_value(
        {"ready": False, "reason": "not_found"}
    )
    wl = WimiLocator(tab, LocatorStrategy.TESTID, "document.querySelector('#x')")

    with pytest.raises(AssertionFailureWithCapture) as exc_info:
        wl.fill("anything", timeout_ms=200)

    assert "not_found" in exc_info.value.message
