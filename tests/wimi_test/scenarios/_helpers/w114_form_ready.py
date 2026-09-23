"""Shared helpers for the #114 scenarios: real input, and a widened window.

Two problems these solve, both of which a naive test gets wrong.

**Real input, not DOM writes.** ``inert`` blocks hit-tested pointer events
and focus. It does *not* block ``el.value = 'x'``, ``el.click()`` or
``body.innerHTML = '<p>x</p>'`` — those all still work on an inert
subtree. A probe built from them reports a fix that isn't one, which is
why everything here goes through ``Input.dispatchMouseEvent`` and
``Input.insertText``.

**Acting inside the window.** Unthrottled, the entry form finishes
initialising ~850 ms after ``Page.navigate`` on this box, and the part
that matters most — the gap between the TinyMCE iframe becoming editable
and its queued content being flushed — is a few hundred milliseconds
inside that. A test that races it is a flake generator.

``install_slow_bridge`` widens the window by holding the page's *bridge
calls*, from a ``Page.addScriptToEvaluateOnNewDocument`` hook installed
before any of the page's own scripts run. Nothing is added to the
shipped page; the code under test is the code that ships. Everything
except the bridge keeps running at full speed, which is the whole point:
the probe's own ``eval_js`` round trips stay ~1 ms, so it can fit a
dozen of them inside the window.

``Emulation.setCPUThrottlingRate`` was tried first and rejected. It does
widen the window (20x turns 0.85 s into ~20 s), but it throttles the
renderer the probe is talking to just as hard: individual ``eval_js``
calls were measured at 300 ms to 6.6 s, so the probe consumed its own
window and reported the form as "handed over part-way through". A knob
that slows the observer as much as the observed buys nothing.

Lifting these into ``wimi_test/`` is the obvious move when #119–#122
(the same defect on settings, session setup, the tree editor and the
entry browser) get their own scenarios.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

from wimi_test.page import WimiPage

# Per bridge call. The entry form's init chain makes roughly ten, so this
# turns a ~0.85 s window into ~4.5 s — and, more importantly, leaves ~2.5 s
# between the reflection iframe becoming editable and the form being handed
# over, which is where the rich-text probe has to act. Measured, not guessed.
BRIDGE_DELAY_MS = 600

# Installed before the page's first script. `_loader.js` builds the API on
# `window._wimiApi` and then assigns it to `window.api`; this intercepts that
# assignment and wraps every method in a `setTimeout`, so the chain of awaits
# in initializeEntryPage() takes longer while nothing else slows down.
#
# `ready` is skipped because it is a latch rather than a call, and
# `getTestModeBridgeCalls` because the harness's own bridge-call helpers go
# through it and must not be slowed or reordered.
SLOW_BRIDGE_TEMPLATE = """
(() => {
  const DELAY = %d;
  const SKIP = new Set(['ready', 'getTestModeBridgeCalls']);
  let real;
  const wrap = (obj) => {
    try {
      for (const key of Object.keys(obj)) {
        const fn = obj[key];
        if (typeof fn !== 'function' || SKIP.has(key) || key[0] === '_') continue;
        obj[key] = function (...args) {
          return new Promise((resolve, reject) => setTimeout(() => {
            try { Promise.resolve(fn.apply(obj, args)).then(resolve, reject); }
            catch (err) { reject(err); }
          }, DELAY));
        };
      }
      window.__w114slow = Object.keys(obj).length;
    } catch (err) { window.__w114slowError = String(err); }
    return obj;
  };
  Object.defineProperty(window, 'api', {
    configurable: true,
    get() { return real; },
    set(value) { real = (value && typeof value === 'object') ? wrap(value) : value; }
  });
})();
"""


def install_slow_bridge(page: WimiPage, delay_ms: int = BRIDGE_DELAY_MS) -> None:
    """Hold every bridge call by ``delay_ms``. Call before ``goto``."""
    page.tab.Page.enable()
    page.tab.Page.addScriptToEvaluateOnNewDocument(
        source=SLOW_BRIDGE_TEMPLATE % delay_ms)


def assert_slow_bridge_took(page: WimiPage) -> None:
    """Fail if the hook did not wrap the API — otherwise the window is ~0.85 s."""
    wrapped = page.eval_js("window.__w114slow || null")
    error = page.eval_js("window.__w114slowError || null")
    assert wrapped, (
        f"the slow-bridge hook never wrapped window.api (error={error!r}); "
        f"without it the init window is ~0.85 s and every 'during init' "
        f"assertion below is racing rather than measuring")


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def seed_empty_session(db: Any, *, name: str = "W114") -> int:
    """A session with no entries — init takes the resetFormForNewEntry() path."""
    exam = db.create_exam_context(exam_name=f"{name} Exam", exam_description="")
    session = db.create_review_session(
        exam_context_id=exam.id,
        total_questions=20,
        total_incorrect=3,
        session_name=name,
        date_encountered=date.today(),
    )
    db.conn.commit()
    return session.id


def seed_session_with_draft(db: Any, *, name: str = "W114 draft") -> tuple[int, int]:
    """A session holding one unfinished draft.

    Init then takes ``loadExistingEntry`` → ``populateFormWithEntry``,
    the path the issue body never mentions and which overwrites the same
    fields as the reset does. An entry with no explanation and no primary
    subject is a draft by ``create_question_entry``'s own rule.
    """
    exam = db.create_exam_context(exam_name=f"{name} Exam", exam_description="")
    session = db.create_review_session(
        exam_context_id=exam.id,
        total_questions=20,
        total_incorrect=3,
        session_name=name,
        date_encountered=date.today(),
    )
    entry = db.create_question_entry(
        review_session_id=session.id,
        user_answer="STORED-ANSWER",
        correct_answer="STORED-CORRECT",
        question_id="Q-STORED",
        reflection="<p>STORED-REFLECTION</p>",
    )
    assert entry.is_draft, "seed is meant to be a draft; the populate path depends on it"
    db.conn.commit()
    return session.id, entry.id


# ---------------------------------------------------------------------------
# Waiting
# ---------------------------------------------------------------------------


def poll(page: WimiPage, expression: str, *, timeout_ms: int = 40000,
         step_ms: int = 20) -> bool:
    """Poll ``expression`` until it evaluates true. Never ``time.sleep``."""
    waited = 0
    while waited < timeout_ms:
        try:
            if page.eval_js(expression) is True:
                return True
        except Exception:  # noqa: BLE001 — the page may be mid-navigation
            pass
        page.wait_for_timeout(step_ms)
        waited += step_ms
    return False


FORM_READY = (
    "(() => { try { return typeof EntryState !== 'undefined'"
    " && EntryState.isFormReady === true; } catch (e) { return false; } })()"
)


def wait_for_form_ready(page: WimiPage, *, timeout_ms: int = 60000) -> None:
    assert poll(page, FORM_READY, timeout_ms=timeout_ms), (
        "the entry form never reported ready — markEntryFormReady() either "
        "never ran or is still waiting on the rich text editors"
    )


def is_inert(page: WimiPage) -> bool:
    return page.eval_js(
        "(() => { const p = document.querySelector('.entry-page');"
        " return p ? p.hasAttribute('inert') : null; })()"
    ) is True


def assert_still_in_window(page: WimiPage, what: str) -> None:
    """Fail loudly if the init window closed under the probe's feet.

    Every "input was refused" assertion is only meaningful while the page
    is still inert. Checked on both sides of each gesture so a race
    produces this message instead of a confident, wrong one.
    """
    if is_inert(page):
        return
    handed_over = page.eval_js(
        "(() => { try { return EntryState.isFormReady === true; }"
        " catch (e) { return null; } })()")
    if handed_over is True:
        raise AssertionError(
            f"{what}: the form was handed over part-way through the probe, so "
            f"what follows would be measuring the wrong state. Raise "
            f"BRIDGE_DELAY_MS rather than weakening the assertion — an "
            f"assertion made outside the window is worse than no assertion "
            f"at all."
        )
    raise AssertionError(
        f"{what}: .entry-page is not inert and the form has not been handed "
        f"over (EntryState.isFormReady={handed_over!r}), i.e. the page never "
        f"gated itself at all — #114 unfixed, or the `inert` attribute was "
        f"dropped from question_entry.html."
    )


# ---------------------------------------------------------------------------
# Real, hit-tested input
# ---------------------------------------------------------------------------


def centre_of(page: WimiPage, selector: str) -> dict:
    """Viewport centre of ``selector``, scrolled into view first.

    ``scrollIntoView`` is a programmatic call and works on an inert
    subtree — that is fine and deliberate: scrolling is not the thing
    under test, the click that follows is.
    """
    raw = page.eval_js(
        "(() => { const el = document.querySelector(%s);"
        " if (!el) return null;"
        " el.scrollIntoView({block: 'center'});"
        " const r = el.getBoundingClientRect();"
        " if (r.width === 0 || r.height === 0) return null;"
        " return JSON.stringify({x: Math.round(r.left + r.width / 2),"
        " y: Math.round(r.top + Math.min(r.height / 2, 20))}); })()"
        % json.dumps(selector)
    )
    assert raw, f"{selector} is not laid out, so no click can be aimed at it"
    return json.loads(raw)


def real_click(page: WimiPage, point: dict) -> None:
    """A hit-tested left click. Goes through hit testing, so ``inert`` sees it."""
    tab = page.tab
    tab.Input.dispatchMouseEvent(type="mouseMoved", x=point["x"], y=point["y"],
                                 button="none")
    tab.Input.dispatchMouseEvent(type="mousePressed", x=point["x"], y=point["y"],
                                 button="left", clickCount=1)
    tab.Input.dispatchMouseEvent(type="mouseReleased", x=point["x"], y=point["y"],
                                 button="left", clickCount=1)
    page.wait_for_timeout(100)


def real_type(page: WimiPage, text: str) -> None:
    """Type into whatever currently has focus. Lands nowhere when nothing does."""
    page.tab.Input.insertText(text=text)
    page.wait_for_timeout(120)


ARM_CLICK_PROBE = """
(() => {
  const btn = document.getElementById('btn-save-draft');
  if (!btn) return false;
  window.__w114clicked = false;
  if (!btn.__w114armed) {
    btn.__w114armed = true;
    btn.addEventListener('click', () => { window.__w114clicked = true; });
  }
  return true;
})()
"""


def arm_save_draft_probe(page: WimiPage) -> None:
    """Attach a marker listener to Save as Draft.

    Adding the listener is a DOM write, but what is under test is whether
    a *real* click reaches the button at all — the page's own handler is
    bound at the very end of init, so without this marker "nothing
    happened" and "the handler is not attached yet" are indistinguishable.
    """
    assert page.eval_js(ARM_CLICK_PROBE) is True, "#btn-save-draft is not in the DOM"


def click_reached_save_draft(page: WimiPage) -> bool:
    return page.eval_js("window.__w114clicked === true") is True


REFLECTION_BODY = """
(() => {
  const f = document.querySelector('#reflection-editor iframe');
  try {
    const b = f && f.contentDocument && f.contentDocument.body;
    return b ? b.innerHTML : null;
  } catch (e) { return null; }
})()
"""

REFLECTION_EDITABLE_AND_INERT = """
(() => {
  const p = document.querySelector('.entry-page');
  const f = document.querySelector('#reflection-editor iframe');
  try {
    const b = f && f.contentDocument && f.contentDocument.body;
    return !!(b && b.isContentEditable && p && p.hasAttribute('inert'));
  } catch (e) { return false; }
})()
"""

RICH_STATE = """
(() => {
  const p = document.querySelector('.entry-page');
  const f = document.querySelector('#reflection-editor iframe');
  let editable = null, html = null;
  try {
    const b = f && f.contentDocument && f.contentDocument.body;
    editable = b ? b.isContentEditable : null;
    html = b ? b.innerHTML : null;
  } catch (e) {}
  const ed = (typeof EntryState !== 'undefined') ? EntryState.reflectionEditor : null;
  return JSON.stringify({
    inert: p ? p.hasAttribute('inert') : null,
    editable: editable,
    html: html,
    editorInitialised: ed ? ed.isInitialized === true : null,
    isLoading: (typeof EntryState !== 'undefined') ? EntryState.isLoading : null
  });
})()
"""


def rich_state(page: WimiPage) -> dict:
    return json.loads(page.eval_js(RICH_STATE))
