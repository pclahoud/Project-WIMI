"""Force one named microphone failure into a running entry form (#59, §7).

The four failure paths in
``docs/planning/FEYNMAN_CAPTURE_IMPLEMENTATION_PLAN.md`` §7 need hardware
states no test machine can be asked for and CI does not have at all: a box
with **no** input device, an OS that has **denied** access, a device another
application holds **exclusively**, and a microphone delivering digital
silence. T15's own task entry settles how to test them: *"Do not try to deny
a real microphone."*

So the page is fed each error at the one seam it reads them through, and
everything after that seam is the shipped code — ``describeError``,
``restIdle``, ``reportError``, ``setView``, ``render``.

Why the injected payloads can be believed
-----------------------------------------

A stub is only worth as much as its fidelity to the thing it stands in for,
so three things are tied back to the real implementation rather than typed
out here:

1. **The payloads come from the taxonomy itself.** :func:`error_payload`
   calls ``SttError(kind, detail).to_dict()`` — the same constructor
   ``bridge_domains/stt.py`` calls — so ``kind``, ``detail`` and above all
   ``retryable`` are computed by ``errors.py``'s ``RETRYABLE`` set. Nothing
   here re-derives whether a retry button is honest; if that set changes,
   these scenarios change with it instead of asserting a stale literal.
2. **The envelope is checked against the live bridge, every run.**
   :func:`assert_error_envelope_matches_bridge` calls a real, unstubbed slot
   that produces a named failure with no hardware and no app data
   (``pollModelDownload`` with an unknown job id) and compares what comes
   back, field for field, with a locally built payload. If the bridge ever
   stops shipping ``{kind, detail, retryable}``, these scenarios fail loudly
   rather than testing a shape the application no longer sends.
3. **The stubbed seam is the one the page really uses.**
   :func:`open_entry_form` waits for the page's own ``getSttStatus`` call to
   be recorded in WIMI's ``@instrumented_slot`` buffer before anything is
   replaced, so the function being wrapped is demonstrably the one
   ``dictation.js`` calls.

The stub wraps ``window.api``'s own methods and keeps the originals, so an
unplanned call still reaches the bridge. ``_loader.js`` publishes one object
under both ``window.api`` and (briefly) ``window._wimiApi``, so a property
replaced here is seen by ``stt.js``'s own composites — ``transcribeRecording``
and ``watchRecordingLevel`` keep running for real on top of the injected
answer.

**Not a different JavaScript world.** ``CLAUDE.md``'s hazard is about globals
written by Qt's ``page().runJavaScript()``; CDP ``Runtime.evaluate`` shares
the page's main world, which is why ``window.api`` — built by the page's own
scripts — is reachable from ``eval_js`` at all (``test_stt_live_probe.py``
depends on the same fact).
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from _helpers.foldersync_fork import await_js
from _helpers.w114_form_ready import poll, seed_empty_session, wait_for_form_ready
from app.stt.errors import SttError, SttErrorKind
from wimi_test.page import WimiPage

FIELDS = ("reflection", "explanation")

#: Stubbed because §7's four paths surface at exactly these three moments:
#: status (before a press), start (the device refuses) and stop (the peak
#: never rose). ``getRecordingLevel`` joins them because the live meter is
#: §7's *first* detector for the silent path.
_WRAPPED = ("getSttStatus", "startRecording", "getRecordingLevel", "stopRecording")

_INSTALL_JS = """
(() => {
  const api = window.api;
  if (!api) return 'no window.api';
  const S = window.__t15 || (window.__t15 = { real: {}, plan: {}, calls: [] });
  %s.forEach(name => {
    if (typeof api[name] !== 'function') return;
    if (!S.real[name]) S.real[name] = api[name].bind(api);
    api[name] = function () {
      S.calls.push(name);
      if (Object.prototype.hasOwnProperty.call(S.plan, name)) {
        return Promise.resolve(JSON.parse(S.plan[name]));
      }
      return S.real[name].apply(api, arguments);
    };
  });
  return 'ok';
})()
""" % json.dumps(list(_WRAPPED))


# ---------------------------------------------------------------------------
# Payloads, built by the real taxonomy
# ---------------------------------------------------------------------------


def error_payload(kind: SttErrorKind, detail: str = "") -> Dict[str, Any]:
    """``{kind, detail, retryable}`` exactly as the bridge would send it."""
    return SttError(kind, detail).to_dict()


# ---------------------------------------------------------------------------
# Getting to a ready entry form
# ---------------------------------------------------------------------------


def open_entry_form(session: Any, page: WimiPage, *, name: str) -> int:
    """Seed a session, open the form, and wait until it is genuinely ready.

    A ``session_id`` is not optional: ``question_entry.js`` redirects to
    ``index.html`` about two seconds after load without one, which destroys
    the execution context mid-call and surfaces as *"Execution context was
    destroyed"* — a message that says nothing about speech.
    """
    session_id = seed_empty_session(session.user.db, name=name)
    mark = page.mark_bridge_calls()
    page.goto("entry-form", query={"session_id": session_id})
    wait_for_form_ready(page)

    # Proof that the seam about to be wrapped is the one the page reads its
    # speech states through: WIMI recorded the slot returning.
    page.wait_for_bridge_call("getSttStatus", since_ts=mark, timeout_ms=30000)

    assert poll(page, "(EntryState.dictation || []).length === 2"), (
        "the entry form did not attach two dictation controllers, so there "
        "is nothing to drive — check initDictation() in question_entry.js")
    installed = page.eval_js(_INSTALL_JS)
    assert installed == "ok", f"could not wrap window.api: {installed!r}"
    return session_id


# ---------------------------------------------------------------------------
# Injection
# ---------------------------------------------------------------------------


def set_response(page: WimiPage, method: str, payload: Any) -> None:
    """Make ``window.api.<method>`` resolve with ``payload`` from now on."""
    assert method in _WRAPPED, f"{method} is not wrapped by this helper"
    page.eval_js(
        f"(() => {{ window.__t15.plan[{json.dumps(method)}] = "
        f"{json.dumps(json.dumps(payload))}; return true; }})()")


def force_status(page: WimiPage, *, mic: Optional[Dict[str, Any]] = None,
                 model_ready: bool = True) -> Dict[str, Any]:
    """Pin ``getSttStatus`` to the real payload with the mic section replaced.

    Read from the live bridge and edited, rather than written from scratch:
    the shape a scenario asserts against should be the shape the application
    actually produces, including any key added after this was written.
    """
    real = await_js(page, "window.api.getSttStatus()")
    status = dict(real)
    status["engine_ready"] = True
    status["engine"] = dict(status.get("engine") or {})
    status["engine"].update({"ready": True, "error": None})
    status["model_ready"] = bool(model_ready)
    status["model"] = dict(status.get("model") or {})
    status["model"].update(
        {"ready": bool(model_ready), "installed": bool(model_ready),
         "error": None})
    status["mic"] = dict(mic if mic is not None else healthy_mic())
    status["microphone_ready"] = bool(status["mic"].get("ready"))
    status["recording"] = False
    set_response(page, "getSttStatus", status)
    return status


def healthy_mic() -> Dict[str, Any]:
    return {
        "permission": "granted",
        "devices": [{"id": "t15-default", "label": "Test input",
                     "is_default": True}],
        "ready": True,
        "error": None,
    }


def refresh_controls(page: WimiPage) -> None:
    """Re-read the (now pinned) status into both buttons and settle.

    ``refresh(true)`` forces past ``dictation.js``'s one-second shared-status
    cache, which exists so two buttons cannot hash a 190 MB model twice and
    would otherwise serve the pre-stub answer.
    """
    await_js(
        page,
        "Promise.all((EntryState.dictation || [])"
        ".map(c => c.refresh(true))).then(() => true)")


# ---------------------------------------------------------------------------
# Reading what the student sees
# ---------------------------------------------------------------------------

_CONTROL_JS = """
(() => {
  const root = document.querySelector('[data-testid="dictation-%(f)s"]');
  if (!root) return null;
  const pick = s => root.querySelector('[data-testid="dictation-%(f)s-' + s + '"]');
  const btn = pick('button'), act = pick('action'), line = pick('status'),
        meter = pick('meter');
  const lbl = btn ? btn.querySelector('.dictation-btn-label') : null;
  return {
    state: root.getAttribute('data-state'),
    button_label: lbl ? lbl.textContent.trim() : null,
    button_disabled: btn ? btn.disabled === true : null,
    action_label: act ? act.textContent.trim() : null,
    action_hidden: act ? act.hidden === true : null,
    status_text: line ? line.textContent.trim() : null,
    status_class: line ? line.className : null,
    meter_hidden: meter ? meter.hidden === true : null
  };
})()
"""


def control(page: WimiPage, field: str) -> Dict[str, Any]:
    """Everything one microphone control is currently showing."""
    got = page.eval_js(_CONTROL_JS % {"f": field})
    assert got, f"no dictation control rendered for {field!r}"
    return got


def wait_for_state(page: WimiPage, field: str, state: str,
                   *, timeout_ms: int = 20000) -> Dict[str, Any]:
    """Poll until the control reports ``state``. Polls for *rendered*, not
    for the message — a poll that waits for the expected text cannot report
    a wrong one."""
    expression = (
        f"(() => {{ const r = document.querySelector("
        f"'[data-testid=\"dictation-{field}\"]');"
        f" return !!r && r.getAttribute('data-state') === {json.dumps(state)}; }})()")
    assert poll(page, expression, timeout_ms=timeout_ms), (
        f"the {field} control never reached {state!r}; it is showing "
        f"{control(page, field)!r}")
    return control(page, field)


def wait_for_status_containing(page: WimiPage, field: str, fragment: str,
                               *, timeout_ms: int = 20000) -> Dict[str, Any]:
    """Poll the status line for ``fragment``.

    Used only where the thing being waited for *is* a message — the flat-line
    warning changes the line and its tone without changing ``data-state``, so
    there is no rendered flag to poll instead.
    """
    expression = (
        f"(() => {{ const l = document.querySelector("
        f"'[data-testid=\"dictation-{field}-status\"]');"
        f" return !!l && l.textContent.indexOf({json.dumps(fragment)}) !== -1; }})()")
    assert poll(page, expression, timeout_ms=timeout_ms), (
        f"the {field} status line never said {fragment!r}; it is showing "
        f"{control(page, field)!r}")
    return control(page, field)


def assert_remediation(shown: Dict[str, Any], *fragments: str) -> None:
    """§7: *"Every message names the remediation."*"""
    text = (shown.get("status_text") or "").lower()
    for fragment in fragments:
        assert fragment.lower() in text, (
            f"the student is not told {fragment!r}. The whole line reads: "
            f"{shown.get('status_text')!r}")


def assert_writing_fields_usable(page: WimiPage, when: str) -> None:
    """§7's first rule for all four paths, and the most consequential one.

    *"Neither writing field is ever disabled by a microphone failure."* Both
    are required, and greying one would turn a convenience failure into a
    data-entry failure on the two things a WIMI entry is for.
    """
    fields = page.eval_js("""
    (() => {
      const out = {};
      ['reflection', 'explanation'].forEach(k => {
        const box = document.getElementById(k + '-editor');
        const ed = (typeof EntryState !== 'undefined')
          ? EntryState[k + 'Editor'] : null;
        let mode = null;
        try {
          const tiny = ed && ed.getEditor ? ed.getEditor() : null;
          mode = tiny ? tiny.mode.get() : null;
        } catch (e) { mode = 'threw:' + e.message; }
        out[k] = {
          greyed: box ? box.classList.contains('rich-editor-disabled') : null,
          mode: mode
        };
      });
      const page_el = document.querySelector('.entry-page');
      out.inert = page_el ? page_el.hasAttribute('inert') : null;
      return out;
    })()
    """)
    assert fields.get("inert") is False, (
        f"{when}: the whole entry page is inert, so nothing can be typed "
        f"anywhere: {fields!r}")
    for field in FIELDS:
        got = fields.get(field) or {}
        assert got.get("greyed") is False, (
            f"{when}: the {field} field carries rich-editor-disabled — a "
            f"microphone failure disabled a required writing field (§7)")
        assert got.get("mode") == "design", (
            f"{when}: the {field} editor is in {got.get('mode')!r} mode "
            f"rather than 'design', i.e. it is read-only (§7)")


# ---------------------------------------------------------------------------
# The trust check
# ---------------------------------------------------------------------------

_UNKNOWN_JOB_ID = "t15-no-such-download-job"


def assert_error_envelope_matches_bridge(page: WimiPage) -> None:
    """The injected payloads have the shape the live bridge really sends.

    ``pollModelDownload`` with an unknown id is the one named failure the
    bridge produces with no hardware, no model and no app data — so it runs
    identically here and on a CI box with no audio stack at all. What comes
    back is compared field for field with a payload built the same way every
    injection in these scenarios is built.
    """
    real = await_js(
        page, f"window.api.pollModelDownload({json.dumps(_UNKNOWN_JOB_ID)})")
    assert real.get("state") == "failed", (
        f"the bridge no longer reports an unknown download job as a failure: "
        f"{real!r}")
    expected = error_payload(
        SttErrorKind.UNKNOWN_JOB, f"no such download job: {_UNKNOWN_JOB_ID}")
    assert real.get("error") == expected, (
        f"the bridge's named-failure envelope has changed. It sent "
        f"{real.get('error')!r}; SttError.to_dict() builds {expected!r}. "
        f"Every injected error in this scenario claims that shape, so this "
        f"mismatch invalidates the test rather than merely failing it.")
