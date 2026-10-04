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


# ------------------------------------------------- click: stability (#117)
#
# A click is measured in one ``Runtime.evaluate`` and dispatched in three
# further CDP commands. An element still moving between them receives
# ``mousePressed`` and ``mouseReleased`` at different elements, and the
# browser then produces **no ``click`` event at all** -- silently. #117
# was that: WIMI's Add Subject modal animates its Save button 41.8 px
# over ~200 ms, and 4 of 20 clicks into that window never reached the
# bridge.


def _moving_sample(y: float) -> dict:
    """A ready readiness reply whose rect tracks ``y``."""
    return _eval_value(
        {"ready": True, "x": 10.0, "y": y, "rect": [0.0, y - 5.0, 20.0, 10.0]}
    )


def test_click_waits_for_a_moving_target_to_come_to_rest() -> None:
    """A target whose rect is still changing is not clicked yet."""
    tab = _make_tab()
    tab.Runtime.evaluate.side_effect = [
        _moving_sample(20.0), _moving_sample(40.0),
        _moving_sample(90.0), _moving_sample(90.0),
    ]
    wl = WimiLocator(tab, LocatorStrategy.TESTID, "document.querySelector('#x')")

    wl.click()

    # The dispatched point must be the SETTLED one. Dispatching at the
    # first reading is the bug: by the time the events arrive the target
    # has moved 70 px and the press lands on whatever is there instead.
    for call in tab.Input.dispatchMouseEvent.call_args_list:
        assert call.kwargs["y"] == 90.0, (
            "click dispatched at a coordinate read while the target was "
            "still moving -- that is #117 exactly"
        )


def test_the_rect_must_match_the_previous_sample_not_merely_exist() -> None:
    """One reading cannot establish stability; two matching ones can.

    A single sample is what the pre-#117 code had, and it was always
    self-consistent -- the rect and the hit test came from the same
    evaluate. The information is only in the comparison.
    """
    tab = _make_tab()
    tab.Runtime.evaluate.side_effect = [
        _moving_sample(20.0), _moving_sample(30.0), _moving_sample(40.0),
        _moving_sample(50.0), _moving_sample(50.0),
    ]
    wl = WimiLocator(tab, LocatorStrategy.TESTID, "document.querySelector('#x')")

    wl.click()

    assert tab.Runtime.evaluate.call_count == 5
    assert tab.Input.dispatchMouseEvent.call_args_list[0].kwargs["y"] == 50.0


def test_a_stationary_target_is_clicked_without_extra_polling() -> None:
    """Negative control: the wait must not fire on a target that is still.

    Without this, "wait until it stops moving" could be satisfied by any
    delay at all, and the fix would be a sleep wearing a predicate's
    clothes. Two readings is the minimum that can establish a rect has
    not changed, so two is what a stationary target costs.
    """
    tab = _make_tab()
    tab.Runtime.evaluate.return_value = _eval_value(
        {"ready": True, "x": 42.0, "y": 84.0, "rect": [32.0, 79.0, 20.0, 10.0]}
    )
    wl = WimiLocator(tab, LocatorStrategy.TESTID, "document.querySelector('#x')")

    wl.click()

    assert tab.Runtime.evaluate.call_count == 2
    assert tab.Input.dispatchMouseEvent.call_count == 3


def test_a_target_that_never_settles_is_still_clicked() -> None:
    """Failing to settle delays a click; it must never refuse one.

    An element inside a container with a perpetual animation would never
    satisfy the predicate. Raising there would turn passing scenarios red
    in order to fix a flake, so the budget expiring falls back to the
    pre-#117 behaviour: dispatch at the last measured point.
    """
    tab = _make_tab()
    counter = {"n": 0}

    def forever(**_kwargs: object) -> dict:
        counter["n"] += 1
        return _eval_value(
            {"ready": True, "x": 1.0, "y": float(counter["n"]),
             "rect": [0.0, float(counter["n"]), 5.0, 5.0]}
        )

    tab.Runtime.evaluate.side_effect = forever
    wl = WimiLocator(tab, LocatorStrategy.TESTID, "document.querySelector('#x')")

    wl.click(timeout_ms=200)

    assert tab.Input.dispatchMouseEvent.call_count == 3


def test_a_readiness_reply_without_a_rect_still_clicks() -> None:
    """Backward compatibility with a reply that predates the #117 field.

    Every other test in this file answers ``{ready, x, y}`` and nothing
    else. Treating a missing rect as "stationary" is what keeps those --
    and any fake elsewhere in the suite -- from hanging until the budget.
    """
    tab = _make_tab()
    tab.Runtime.evaluate.return_value = _eval_value(
        {"ready": True, "x": 7.0, "y": 9.0}
    )
    wl = WimiLocator(tab, LocatorStrategy.TESTID, "document.querySelector('#x')")

    wl.click()

    assert tab.Runtime.evaluate.call_count == 1
    assert tab.Input.dispatchMouseEvent.call_count == 3


def test_the_readiness_scriptlet_sends_the_rect_back() -> None:
    """The JS half must actually return the rect.

    The Python loop can only compare what the page sends it, so a
    refactor that dropped the field would leave every stability test
    above passing (missing rect means "stationary") against a locator
    that no longer waits for anything.
    """
    tab = _make_tab()
    tab.Runtime.evaluate.return_value = _eval_value(
        {"ready": True, "x": 1.0, "y": 1.0}
    )
    wl = WimiLocator(tab, LocatorStrategy.TESTID, "document.querySelector('#x')")

    wl.click()

    expression = tab.Runtime.evaluate.call_args.kwargs["expression"]
    assert "rect: [rect.left, rect.top, rect.width, rect.height]" in expression


def test_the_stability_wait_does_not_use_getanimations() -> None:
    """``document.getAnimations()`` was measured and rejected (#117).

    It blocked 150 ms on every ``.dictation-btn`` press for three colour
    transitions that cannot move the button, which pushed
    ``test_a_dictated_answer_survives_the_autosave`` across its own
    1200 ms autosave boundary -- 8 failures in 8 runs. Re-adding it would
    be a silent retiming of every scenario that clicks a button with a
    ``transition`` on it, which is most of them.
    """
    tab = _make_tab()
    tab.Runtime.evaluate.return_value = _eval_value(
        {"ready": True, "x": 1.0, "y": 1.0}
    )
    wl = WimiLocator(tab, LocatorStrategy.TESTID, "document.querySelector('#x')")

    wl.click()

    expression = tab.Runtime.evaluate.call_args.kwargs["expression"]
    assert "getAnimations" not in expression


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
