"""JS-backed auto-waiting locator for the WIMI test infrastructure.

This module implements ``WimiLocator``, a thin wrapper around a
pychrome ``Tab`` (or duck-type with ``.Runtime.evaluate(...)`` and
``.Input.dispatchMouseEvent(...)``). It replaces the previous
Playwright ``Locator`` wrapper as part of the migration tracked in
:doc:`docs/planning/PYCHROME_MIGRATION.md` Section 5.3 (locator
engine sketch).

Each ``WimiLocator`` holds:

- a pychrome ``Tab`` reference,
- a :class:`LocatorStrategy` describing how the element was looked up
  (role+name vs. testid vs. CSS), and
- a **JS expression** (``selector_js``) that evaluates to the target
  element or ``null``.

Public methods (``click``, ``fill``, ``expect_visible``, ``text``,
``attribute``) build a JS scriptlet that combines the element-selection
JS with the action and the readiness check. Auto-waiting is implemented
in Python via a polling loop over ``Runtime.evaluate``.

**Auto-waiting policy.** ``click``/``fill``/``expect_visible`` poll
until the element is found, has non-zero area, and is enabled. The
default timeout is 5000ms. On timeout we raise
:class:`~wimi_test.errors.AssertionFailureWithCapture` with the last
observed reason (``"not_found"``, ``"not_visible"``, ``"disabled"``).

**Role+name resolution is intentionally simpler than Playwright's.**
We support: ``aria-label``, ``<label for=...>`` association for inputs,
``textContent`` for buttons/links, and ``el.value`` for inputs. Complex
ARIA structures (``aria-labelledby`` chains, nested live regions, etc.)
are **not** supported -- tests that need them should fall back to
``data-testid``. Phase 4's testid migration ensures this is workable.

pychrome is intentionally **not** imported at module load time -- this
module is exercised in unit tests with ``MagicMock`` Tab fakes, and the
runtime ``pychrome`` dependency is required only when a real session is
spawned. Type hints use string annotations / ``TYPE_CHECKING``.
"""

from __future__ import annotations

import enum
import json
import time
from typing import TYPE_CHECKING, Any

from wimi_test.errors import AssertionFailureWithCapture

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pychrome  # noqa: F401  (string-typed below)

__all__ = ["LocatorStrategy", "WimiLocator", "build_locator"]


# Default action timeout for ``click``/``fill``/``expect_visible`` when the
# caller does not supply one. Mirrors ``TestConfig.timeout_default_ms`` so the
# whole library converges on the same number; we keep a literal here rather
# than importing ``TestConfig`` to keep this module a leaf with respect to the
# rest of ``wimi_test`` (besides ``errors``).
_DEFAULT_TIMEOUT_MS: int = 5000

# Polling interval inside the auto-wait loop. 50ms keeps the loop responsive
# without hammering CPU; matches the value in PYCHROME_MIGRATION.md §5.3.
_POLL_INTERVAL_S: float = 0.05


# ---------------------------------------------------------------------- helpers


def _escape_attr_value(s: str) -> str:
    """Escape ``s`` for safe insertion inside a CSS attribute selector value.

    The result is intended to be placed between double quotes in a CSS
    attribute selector such as ``[data-testid="..."]``. We escape:

    - backslash -> ``\\\\``
    - double-quote -> ``\\"``
    - newline -> ``\\n`` (so a multi-line testid does not break the JS literal)
    """
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _escape_template_literal(s: str) -> str:
    """Escape ``s`` for safe insertion inside a JS template literal (backticks).

    Escapes the two characters that have meaning inside a template literal:

    - backtick (closes the literal early) -> ``\\` ``
    - ``${`` (begins an interpolation) -> ``\\${``

    Backslashes are escaped first so we don't double-escape the sequences we
    introduce.
    """
    return s.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")


# JS fragment that defines ``implicitRole(tagName)`` -- a small, intentionally
# limited mapping from common HTML tag names to ARIA role strings. Embedded
# inside the role+name selector_js so the role check works on elements without
# an explicit ``role`` attribute (which is most of them).
_implicit_role_js: str = r"""
function implicitRole(tagName, type) {
    const t = (tagName || '').toLowerCase();
    const ty = (type || '').toLowerCase();
    if (t === 'button') return 'button';
    if (t === 'a') return 'link';
    if (t === 'nav') return 'navigation';
    if (t === 'main') return 'main';
    if (t === 'header') return 'banner';
    if (t === 'footer') return 'contentinfo';
    if (t === 'aside') return 'complementary';
    if (t === 'section') return 'region';
    if (t === 'h1' || t === 'h2' || t === 'h3' || t === 'h4' || t === 'h5' || t === 'h6') return 'heading';
    if (t === 'img') return 'img';
    if (t === 'ul' || t === 'ol') return 'list';
    if (t === 'li') return 'listitem';
    if (t === 'table') return 'table';
    if (t === 'tr') return 'row';
    if (t === 'td') return 'cell';
    if (t === 'th') return 'columnheader';
    if (t === 'select') return 'combobox';
    if (t === 'textarea') return 'textbox';
    if (t === 'option') return 'option';
    if (t === 'dialog') return 'dialog';
    if (t === 'input') {
        if (ty === 'checkbox') return 'checkbox';
        if (ty === 'radio') return 'radio';
        if (ty === 'button' || ty === 'submit' || ty === 'reset') return 'button';
        if (ty === 'range') return 'slider';
        if (ty === 'search') return 'searchbox';
        if (ty === 'email' || ty === 'tel' || ty === 'url' || ty === 'text' || ty === '' || ty == null) return 'textbox';
        return 'textbox';
    }
    return null;
}
"""

# JS fragment that defines ``accessibleName(el)``. Resolution order matches the
# module docstring -- ``aria-label``, then label-for, then textContent, then
# input value. Kept simple by design.
_accessible_name_js: str = r"""
function accessibleName(el) {
    if (!el) return '';
    const aria = el.getAttribute && el.getAttribute('aria-label');
    if (aria) return aria.trim();
    const tag = (el.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') {
        if (el.id) {
            const lab = document.querySelector('label[for="' + el.id.replace(/"/g, '\\"') + '"]');
            if (lab && lab.textContent) return lab.textContent.trim();
        }
        const parentLabel = el.closest && el.closest('label');
        if (parentLabel && parentLabel.textContent) return parentLabel.textContent.trim();
        if (el.value != null && String(el.value) !== '') return String(el.value).trim();
        return '';
    }
    if (el.textContent) return el.textContent.trim();
    return '';
}
"""


# ---------------------------------------------------------------------- enums


class LocatorStrategy(enum.Enum):
    """Identifies which strategy resolved a locator.

    Stored on every ``WimiLocator`` so failure diagnostics can report
    *how* the element was looked up (role+name vs. testid vs. CSS).
    """

    ROLE_AND_NAME = "role+name"
    TESTID = "testid"
    CSS = "css"


# ---------------------------------------------------------------------- core


class WimiLocator:
    """Auto-waiting locator built on a pychrome ``Tab``.

    Instead of wrapping a Playwright ``Locator`` (one round-trip per
    method), this class holds a JS expression (``selector_js``) and
    composes per-action JS scriptlets that resolve the element fresh on
    every poll. That keeps the design honest about the fact that the
    DOM may change between polls.
    """

    def __init__(
        self,
        tab: "pychrome.Tab",
        strategy: LocatorStrategy,
        selector_js: str,
    ) -> None:
        self._tab: "pychrome.Tab" = tab
        self._strategy: LocatorStrategy = strategy
        self._js: str = selector_js

    @property
    def strategy(self) -> LocatorStrategy:
        """The strategy used by ``build_locator`` to construct this locator."""
        return self._strategy

    @property
    def selector_js(self) -> str:
        """The raw JS expression that resolves to the target element (or null)."""
        return self._js

    # ------------------------------------------------------------------ actions

    def click(self, *, timeout_ms: int | None = None) -> None:
        """Wait for the element to be clickable, then dispatch a click.

        Polls every 50ms until the element is found, has a non-zero
        bounding rect, and is not disabled. On success, dispatches a
        ``mousePressed`` + ``mouseReleased`` pair via
        ``Input.dispatchMouseEvent`` at the element's center.

        Raises :class:`~wimi_test.errors.AssertionFailureWithCapture`
        on timeout, including the last observed readiness reason.
        """
        effective_timeout = _DEFAULT_TIMEOUT_MS if timeout_ms is None else timeout_ms
        x, y, _reason = self._wait_clickable(effective_timeout)
        # Use Input.dispatchMouseEvent for a real synthetic click rather than
        # ``el.click()`` -- exercises the same code path users do, including
        # focus changes and event bubbling.
        #
        # We dispatch a ``mouseMoved`` to the target coordinates BEFORE the
        # press. Without this, QtWebEngine's CDP implementation has been
        # observed to drop ``mouseup``/``click`` on the very first press
        # against a focusable element (e.g. ``tabindex="0"``): the press
        # fires, focus shifts, and the subsequent release is treated as
        # belonging to a different stream because the synthetic cursor was
        # never positioned over the element. Moving first matches the
        # production-faithful pattern Playwright uses and ensures the full
        # ``mousedown`` -> ``mouseup`` -> ``click`` sequence fires reliably,
        # even on the first interaction with a previously-unfocused element.
        self._tab.Input.dispatchMouseEvent(
            type="mouseMoved", x=x, y=y, button="none"
        )
        self._tab.Input.dispatchMouseEvent(
            type="mousePressed", x=x, y=y, button="left", clickCount=1
        )
        self._tab.Input.dispatchMouseEvent(
            type="mouseReleased", x=x, y=y, button="left", clickCount=1
        )

    def fill(self, value: str, *, timeout_ms: int | None = None) -> None:
        """Wait for the element to be ready, then set its value.

        For ``<input>``/``<textarea>``: focuses the element, sets
        ``.value``, and dispatches ``input`` and ``change`` events so
        any framework listeners pick up the change.

        For contenteditable elements: focuses and sets ``.textContent``.

        Same auto-wait semantics as :meth:`click`.
        """
        effective_timeout = _DEFAULT_TIMEOUT_MS if timeout_ms is None else timeout_ms
        self._wait_clickable(effective_timeout)

        encoded_value = json.dumps(value)
        # The scriptlet handles three element shapes:
        #   (a) input/textarea with ``.value`` -- set value, fire input+change
        #   (b) contenteditable -- set textContent, fire input
        #   (c) anything else -- best-effort fallback (textContent), still
        #       fires input so framework hooks can react
        fill_js = f"""
            (() => {{
                const el = {self._js};
                if (!el) return false;
                el.focus();
                if (el.select && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) {{
                    el.select();
                }}
                const v = {encoded_value};
                if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {{
                    el.value = v;
                }} else if (el.isContentEditable) {{
                    el.textContent = v;
                }} else {{
                    el.textContent = v;
                }}
                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                return true;
            }})()
        """
        result = self._tab.Runtime.evaluate(expression=fill_js, returnByValue=True)
        self._raise_if_eval_error(result, "fill")

    # ------------------------------------------------------------------ assertions

    def expect_visible(self, *, timeout_ms: int | None = None) -> None:
        """Assert that the element becomes visible within ``timeout_ms``.

        Polls visibility (presence + non-zero bounding rect) without
        clicking. On timeout, raises
        :class:`~wimi_test.errors.AssertionFailureWithCapture` with the
        last observed reason. No captures are attached at this layer --
        higher-level helpers do that.
        """
        effective_timeout = _DEFAULT_TIMEOUT_MS if timeout_ms is None else timeout_ms
        deadline = time.time() + effective_timeout / 1000.0
        last_reason: str = "not_found"

        visibility_js = f"""
            (() => {{
                const el = {self._js};
                if (!el) return {{ visible: false, reason: "not_found" }};
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0)
                    return {{ visible: false, reason: "not_visible" }};
                return {{ visible: true }};
            }})()
        """

        while True:
            r = self._tab.Runtime.evaluate(
                expression=visibility_js, returnByValue=True
            )
            self._raise_if_eval_error(r, "expect_visible")
            v = self._unwrap_value(r) or {}
            if v.get("visible"):
                return
            last_reason = v.get("reason", last_reason)
            if time.time() >= deadline:
                break
            time.sleep(_POLL_INTERVAL_S)

        raise AssertionFailureWithCapture(
            f"Locator {self._strategy.value} did not become visible within "
            f"{effective_timeout}ms; last reason: {last_reason!r}",
            captures=None,
        )

    # ------------------------------------------------------------------ reads

    def text(self) -> str:
        """Return the element's text content (or ``""`` if missing/empty).

        Does **not** wait beyond a single round-trip. Returning ``""``
        for an absent element matches the read-side contract from the
        Playwright version: tests that want a stricter check should use
        :meth:`expect_visible` first.
        """
        js = f"({self._js})?.textContent || ''"
        r = self._tab.Runtime.evaluate(expression=js, returnByValue=True)
        self._raise_if_eval_error(r, "text")
        value = self._unwrap_value(r)
        if value is None:
            return ""
        return str(value)

    def attribute(self, name: str) -> str | None:
        """Return the value of attribute ``name`` (or ``None`` if missing).

        Same single-round-trip semantics as :meth:`text`. Returns
        ``None`` when the element is missing or the attribute is absent.
        """
        encoded_name = json.dumps(name)
        js = f"({self._js})?.getAttribute({encoded_name}) ?? null"
        r = self._tab.Runtime.evaluate(expression=js, returnByValue=True)
        self._raise_if_eval_error(r, "attribute")
        value = self._unwrap_value(r)
        if value is None:
            return None
        return str(value)

    # ------------------------------------------------------------------ helpers

    def _wait_clickable(self, timeout_ms: int) -> tuple[float, float, str]:
        """Poll until the element is clickable, returning the click point.

        Returns ``(x, y, reason)`` where ``reason`` is the **last**
        observed reason (always ``""`` on success, useful only for the
        timeout path). Raises
        :class:`~wimi_test.errors.AssertionFailureWithCapture` on
        timeout.
        """
        deadline = time.time() + timeout_ms / 1000.0
        last_reason: str = "not_found"

        readiness_js = f"""
            (() => {{
                const el = {self._js};
                if (!el) return {{ ready: false, reason: "not_found" }};
                const rect0 = el.getBoundingClientRect();
                if (rect0.width === 0 || rect0.height === 0)
                    return {{ ready: false, reason: "not_visible" }};
                const style = window.getComputedStyle(el);
                if (style && style.display === 'none')
                    return {{ ready: false, reason: "not_visible" }};
                if (el.disabled)
                    return {{ ready: false, reason: "disabled" }};

                // Scroll into view BEFORE computing click coords. Without
                // this, off-viewport elements have rects pointing at coords
                // outside the visible area; CDP's Input.dispatchMouseEvent
                // still fires at those coords, which lands on whatever is
                // actually painted at that viewport position (e.g. a fixed
                // footer or whitespace). Re-read the rect after scrolling.
                el.scrollIntoView({{ block: "center", inline: "center" }});
                const rect = el.getBoundingClientRect();
                const cx = rect.left + rect.width / 2;
                const cy = rect.top + rect.height / 2;

                // Final hit-test: confirm the element actually receives a
                // click at (cx, cy). If a fixed-position overlay covers it,
                // bail with a discriminating reason rather than dispatching
                // a click into the wrong element.
                const hit = document.elementFromPoint(cx, cy);
                if (hit !== el && (!hit || !el.contains(hit) && !hit.contains(el))) {{
                    return {{
                        ready: false,
                        reason: "occluded:" + (hit ? hit.tagName.toLowerCase() : "null")
                    }};
                }}
                return {{ ready: true, x: cx, y: cy }};
            }})()
        """

        while True:
            r = self._tab.Runtime.evaluate(
                expression=readiness_js, returnByValue=True
            )
            self._raise_if_eval_error(r, "click")
            v = self._unwrap_value(r) or {}
            if v.get("ready"):
                return float(v["x"]), float(v["y"]), ""
            last_reason = v.get("reason", last_reason)
            if time.time() >= deadline:
                break
            time.sleep(_POLL_INTERVAL_S)

        raise AssertionFailureWithCapture(
            f"Locator {self._strategy.value} did not become clickable within "
            f"{timeout_ms}ms; last reason: {last_reason!r}",
            captures=None,
        )

    @staticmethod
    def _unwrap_value(eval_response: Any) -> Any:
        """Pull ``result.value`` out of a ``Runtime.evaluate`` response.

        pychrome returns the standard CDP shape:
        ``{"result": {"type": ..., "value": ...}}``. We tolerate
        missing keys so a misshapen mock doesn't crash with KeyError.
        """
        if not isinstance(eval_response, dict):
            return None
        result = eval_response.get("result")
        if not isinstance(result, dict):
            return None
        return result.get("value")

    @staticmethod
    def _raise_if_eval_error(eval_response: Any, op: str) -> None:
        """Raise if a CDP ``Runtime.evaluate`` returned an exception.

        The CDP shape includes ``exceptionDetails`` when the JS threw.
        We surface that as a clear error rather than silently treating
        a thrown JS exception as ``ready: false``.
        """
        if isinstance(eval_response, dict) and eval_response.get("exceptionDetails"):
            details = eval_response["exceptionDetails"]
            text = (
                details.get("text")
                if isinstance(details, dict)
                else str(details)
            )
            raise AssertionFailureWithCapture(
                f"Locator {op} JS evaluation raised: {text}",
                captures=None,
            )


# ---------------------------------------------------------------------- factory


def build_locator(
    tab: "pychrome.Tab",
    *,
    role: str | None = None,
    name: str | None = None,
    testid: str | None = None,
    css: str | None = None,
) -> WimiLocator:
    """Construct a :class:`WimiLocator` from exactly one strategy.

    The caller must supply *exactly one* of:

    - ``role`` and ``name`` together (strategy
      :attr:`LocatorStrategy.ROLE_AND_NAME`),
    - ``testid`` alone (strategy :attr:`LocatorStrategy.TESTID`),
    - ``css`` alone (strategy :attr:`LocatorStrategy.CSS`).

    Mixing strategies, supplying ``role`` without ``name`` (or vice
    versa), or supplying nothing all raise ``ValueError`` with a
    message that lists the offending combination.

    **Accessible-name resolution for role+name** is intentionally
    simpler than Playwright's: it covers ``aria-label``, ``<label
    for=...>`` for form controls, ``textContent`` for buttons/links,
    and ``el.value`` for inputs. Anything more complex (``aria-labelledby``
    chains, nested live regions) should fall back to ``data-testid``.
    """
    has_role = role is not None
    has_name = name is not None
    has_testid = testid is not None
    has_css = css is not None

    role_name_pair = has_role and has_name
    role_or_name_only = has_role ^ has_name  # XOR: exactly one set

    # ``role`` without ``name`` (or vice versa) is always invalid.
    if role_or_name_only:
        raise ValueError(
            f"role and name must both be provided; got role={role!r}, name={name!r}"
        )

    # Count active strategies so we can enforce "exactly one".
    strategies_set = sum([role_name_pair, has_testid, has_css])
    if strategies_set == 0:
        raise ValueError(
            "build_locator requires exactly one strategy. "
            "Valid combinations: (role+name), testid alone, or css alone."
        )
    if strategies_set > 1:
        active: list[str] = []
        if role_name_pair:
            active.append("role+name")
        if has_testid:
            active.append("testid")
        if has_css:
            active.append("css")
        raise ValueError(
            "build_locator requires exactly one strategy; got multiple: "
            f"{', '.join(active)}. Valid combinations: (role+name), testid "
            "alone, or css alone."
        )

    if has_testid:
        # CSS attribute selector with a JSON-safe escaped value. We can't just
        # use ``json.dumps`` here because the surrounding context is a CSS
        # attribute selector, not a JS string literal -- the rules differ
        # (notably: no \uXXXX escapes inside CSS attribute values).
        escaped = _escape_attr_value(testid)
        selector_js = (
            f'document.querySelector(\'[data-testid="{escaped}"]\')'
        )
        return WimiLocator(tab, LocatorStrategy.TESTID, selector_js)

    if has_css:
        # Use a JS template literal so any single/double quotes in the CSS
        # selector pass through unchanged. We only need to escape backticks
        # and ``${`` interpolation triggers.
        escaped_css = _escape_template_literal(css)
        selector_js = f"document.querySelector(`{escaped_css}`)"
        return WimiLocator(tab, LocatorStrategy.CSS, selector_js)

    # role+name (the only remaining branch).
    encoded_role = json.dumps(role)
    encoded_name = json.dumps(name)
    selector_js = f"""
        (() => {{
            {_implicit_role_js}
            {_accessible_name_js}
            const wantedRole = {encoded_role};
            const wantedName = {encoded_name};
            const all = document.querySelectorAll('*');
            for (const el of all) {{
                const explicit = el.getAttribute && el.getAttribute('role');
                const implicit = implicitRole(el.tagName, el.getAttribute && el.getAttribute('type'));
                const r = explicit || implicit;
                if (r !== wantedRole) continue;
                if (accessibleName(el) === wantedName) return el;
            }}
            return null;
        }})()
    """
    return WimiLocator(tab, LocatorStrategy.ROLE_AND_NAME, selector_js)
