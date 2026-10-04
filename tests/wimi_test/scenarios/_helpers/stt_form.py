"""Shared machinery for the four T16 form-integration scenarios (#59).

What is faked, and what is emphatically not
-------------------------------------------
These four scenarios are about the *page*: the ``inert`` gate, the
staleness check, the dirty flag and insert-at-caret. Every one of those
lives in ``dictation.js``, ``question_entry.js``'s wiring and
``RichEditor.insertTranscript`` — none of them in whisper.cpp. So the
seam is the **bridge**: ``startRecording`` / ``stopRecording`` /
``pollTranscription`` / ``getSttStatus`` are replaced on ``window.api``
and everything above them is the code that ships.

``api.transcribeRecording`` is deliberately left real. It is the
composite that calls ``stopRecording`` and then polls until the state
stops being ``running``, and the whole staleness hazard only exists
because that poll takes seconds — a stub that resolved it in one step
would delete the window the tests are here to open.

The alternative was a live recording through ``dev_virtual_mic.sh``.
That is what ``test_stt_live_probe.py`` and ``test_stt_mic_button_live.py``
already do, and on a box with no 190 MB model they **skip** — which
reads exactly like a pass. These four must run everywhere, because the
bugs they guard against (a transcript accepted by the page and then
silently dropped) are the ones that are invisible when they happen.

The stub is a real state machine, not a constant
------------------------------------------------
``window.__stt.release`` holds the transcription open for as long as the
test wants; ``__stt.override`` lets a test hand back a payload echoing a
*different* ``field_key``, ``token`` or ``entry_id``, which is the only
way to reach three of ``stalenessReason``'s four branches from outside.
Every call is logged to ``__stt.calls``, so "the click was refused" and
"the click landed and did nothing" are distinguishable.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

from _helpers.w114_form_ready import BRIDGE_DELAY_MS
from wimi_test.page import WimiPage

# Names the stub owns. Held out of the slow-bridge wrap as well: the page's
# own init calls are what needs slowing, and a delayed status call would
# narrow the window instead of widening it.
STT_METHODS = (
    "getSttStatus", "startRecording", "getRecordingLevel", "stopRecording",
    "pollTranscription", "cancelRecording",
)

# A function expression, applied to the api object. Used twice: from a
# document-start hook (the inert scenario, which needs the button live
# before the form is handed over) and after load (the other three).
STT_STUB_FN = r"""
(function (api) {
  var S = window.__stt = window.__stt || {};
  S.calls = [];
  S.jobs = 0;
  S.recording = false;
  S.release = false;             // the poll says 'running' until this flips
  S.text = 'STUB TRANSCRIPT';
  S.override = {};               // echo a different entry_id/field_key/token
  S.lastContext = null;
  S.status = {
    engine_ready: true, model_ready: true, model_size: 'small.en-q5_1',
    engine: {ready: true, error: null}, model: {ready: true, error: null},
    mic: {permission: 'granted', ready: true, error: null,
          devices: [{id: 'stub', label: 'Stub microphone'}]},
    priming_enabled: false, show_first_use_notice: false, recording: false
  };
  function log(name, arg) { S.calls.push({name: name, arg: arg, at: Date.now()}); }
  function pick(key, fallback) {
    return Object.prototype.hasOwnProperty.call(S.override, key)
      ? S.override[key] : fallback;
  }

  api.getSttStatus = function () {
    log('getSttStatus');
    return Promise.resolve(JSON.parse(JSON.stringify(S.status)));
  };
  api.startRecording = function () {
    log('startRecording');
    S.recording = true;
    return Promise.resolve({recording: true, format: {},
      device: {id: 'stub', label: 'Stub microphone'},
      device_choice_honoured: true});
  };
  api.getRecordingLevel = function () {
    return Promise.resolve({recording: S.recording, rms: 0.25, peak: 0.4,
      stream_error: null});
  };
  api.stopRecording = function (context) {
    log('stopRecording', context);
    S.recording = false;
    S.lastContext = context || {};
    return Promise.resolve({job_id: 'stub-job-' + (++S.jobs),
      context: S.lastContext, primed: {tier: 'none'}, capture: {seconds: 3}});
  };
  api.pollTranscription = function (jobId) {
    log('pollTranscription', jobId);
    if (!S.release) return Promise.resolve({state: 'running'});
    var ctx = S.lastContext || {};
    var echoed = {
      entry_id: pick('entry_id', ctx.entry_id),
      field_key: pick('field_key', ctx.field_key),
      token: pick('token', ctx.token)
    };
    return Promise.resolve(Object.assign({state: 'done', text: S.text, ms: 900,
      context: Object.assign({}, ctx, echoed)}, echoed));
  };
  api.cancelRecording = function () {
    log('cancelRecording');
    S.recording = false;
    return Promise.resolve({recording: false, cancelled: true});
  };
  S.installed = true;
  return api;
})
"""

# The same trick as ``w114_form_ready.install_slow_bridge``, plus the stub.
# One ``defineProperty`` on ``window.api``, because two would fight.
SLOW_BRIDGE_WITH_STT = """
(() => {
  const DELAY = %(delay)d;
  const SKIP = new Set(%(skip)s);
  const stub = %(stub)s;
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
      stub(obj);
      window.__sttSlow = Object.keys(obj).length;
    } catch (err) { window.__sttSlowError = String(err); }
    return obj;
  };
  Object.defineProperty(window, 'api', {
    configurable: true,
    get() { return real; },
    set(value) { real = (value && typeof value === 'object') ? wrap(value) : value; }
  });
})();
"""

SKIP_NAMES = list(STT_METHODS) + [
    "ready", "getTestModeBridgeCalls", "transcribeRecording",
    "watchRecordingLevel",
]


def install_slow_bridge_with_stt(page: WimiPage,
                                 delay_ms: int = BRIDGE_DELAY_MS) -> None:
    """Hold the page's own bridge calls; run speech at full speed.

    Call before ``goto``. The delay is what keeps ``.entry-page`` inert
    long enough to aim a real click at a live microphone button.
    """
    page.tab.Page.enable()
    page.tab.Page.addScriptToEvaluateOnNewDocument(
        source=SLOW_BRIDGE_WITH_STT % {
            "delay": delay_ms,
            "skip": json.dumps(SKIP_NAMES),
            "stub": STT_STUB_FN.strip(),
        })


def assert_hook_took(page: WimiPage) -> None:
    wrapped = page.eval_js("window.__sttSlow || null")
    error = page.eval_js("window.__sttSlowError || null")
    assert wrapped, (
        f"the document-start hook never wrapped window.api (error={error!r}); "
        f"without it neither the delay nor the speech stub is in place and "
        f"every assertion below is measuring the wrong page")


def install_stt_stub(page: WimiPage) -> None:
    """Install the stub on an already-loaded page, then re-park both buttons."""
    installed = page.eval_js(f"(() => {{ {STT_STUB_FN.strip()}(window.api);"
                             " return window.__stt.installed === true; })()")
    assert installed is True, "the speech stub did not attach to window.api"
    refresh_controllers(page)


def refresh_controllers(page: WimiPage) -> None:
    """Make both controllers re-read status through the stub.

    ``refresh`` is the same call ``refreshDictation()`` makes; ``true``
    forces past ``sharedStatus``'s one-second cache.
    """
    page.eval_js(
        "(() => { (EntryState.dictation || []).forEach(c => c.refresh(true));"
        " return true; })()")


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def seed_entry_session(db: Any, *, name: str = "STT", slots: int = 1) -> int:
    """An exam context and a review session with ``slots`` entry slots.

    ``total_incorrect`` is what ``getEntrySlotCount()`` reads, so it is
    what decides whether "next entry" is reachable.
    """
    exam = db.create_exam_context(exam_name=f"{name} Exam", exam_description="")
    session = db.create_review_session(
        exam_context_id=exam.id,
        total_questions=max(slots, 1) * 5,
        total_incorrect=slots,
        session_name=f"{name} session",
        date_encountered=date.today(),
    )
    db.conn.commit()
    return session.id


# ---------------------------------------------------------------------------
# Reading the control
# ---------------------------------------------------------------------------


def poll(page: WimiPage, expression: str, *, timeout_ms: int = 30000,
         step_ms: int = 25) -> bool:
    """Poll ``expression`` until it is true. Never ``time.sleep``."""
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


def _root(field: str) -> str:
    return f"document.querySelector('[data-testid=\"dictation-{field}\"]')"


def control_state(page: WimiPage, field: str) -> str | None:
    """``data-state`` on the control's root: the controller's own state."""
    return page.eval_js(
        f"(() => {{ const r = {_root(field)};"
        " return r ? r.getAttribute('data-state') : null; })()")


def button_disabled(page: WimiPage, field: str) -> bool | None:
    return page.eval_js(
        f"(() => {{ const b = document.querySelector("
        f"'[data-testid=\"dictation-{field}-button\"]');"
        " return b ? b.disabled : null; })()")


def status_text(page: WimiPage, field: str) -> str:
    return page.eval_js(
        f"(() => {{ const s = document.querySelector("
        f"'[data-testid=\"dictation-{field}-status\"]');"
        " return s ? s.textContent : ''; })()") or ""


def wait_for_state(page: WimiPage, field: str, want: str, *,
                   timeout_ms: int = 30000) -> None:
    ok = poll(page,
              f"(() => {{ const r = {_root(field)};"
              f" return !!r && r.getAttribute('data-state') === {json.dumps(want)};"
              " })()",
              timeout_ms=timeout_ms)
    assert ok, (
        f"the {field} control never reached {want!r} "
        f"(state={control_state(page, field)!r}, "
        f"status={status_text(page, field)!r})")


def editor_text(page: WimiPage, field: str) -> str:
    """Plain text of the field's editor, via the RichEditor the page owns."""
    prop = "reflectionEditor" if field == "reflection" else "explanationEditor"
    return page.eval_js(
        f"(() => {{ const e = EntryState.{prop};"
        " if (!e || !e.getEditor || !e.getEditor()) return '';"
        " return e.getEditor().getBody().textContent || ''; })()") or ""


def stub_calls(page: WimiPage, name: str | None = None) -> list:
    raw = page.eval_js(
        "(() => JSON.stringify((window.__stt && window.__stt.calls) || []))()")
    calls = json.loads(raw or "[]")
    return [c for c in calls if name is None or c.get("name") == name]


# ---------------------------------------------------------------------------
# Driving one recording
# ---------------------------------------------------------------------------


def press_mic(page: WimiPage, field: str) -> None:
    """A hit-tested click on the field's microphone button."""
    page.locator(testid=f"dictation-{field}-button").click()


def start_recording(page: WimiPage, field: str) -> None:
    press_mic(page, field)
    wait_for_state(page, field, "recording")


def stop_and_hold(page: WimiPage, field: str) -> None:
    """Stop the microphone and leave the transcription running."""
    press_mic(page, field)
    wait_for_state(page, field, "transcribing")


def release_transcript(page: WimiPage, text: str, **override: Any) -> None:
    """Let the held poll return ``done``, optionally echoing other fields."""
    page.eval_js(
        "(() => { window.__stt.text = %s;"
        " window.__stt.override = %s;"
        " window.__stt.release = true; return true; })()"
        % (json.dumps(text), json.dumps(override)))
