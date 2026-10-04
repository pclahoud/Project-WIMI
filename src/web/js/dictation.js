/**
 * WIMI dictation — the microphone beside a writing field (#59).
 *
 * One component, instantiated twice: once beside "Why did you get this
 * wrong?" and once beside "Why is the correct answer correct?". The student
 * presses it, explains out loud, presses stop, and what they said arrives
 * where their cursor was. The audio never leaves the machine.
 *
 * Plan: `docs/planning/FEYNMAN_CAPTURE_IMPLEMENTATION_PLAN.md` §3.5 (the two
 * fields), §3.8 (the first-run download) and §7 (the four failure paths).
 *
 * A named speech failure RESOLVES; it does not reject
 * ---------------------------------------------------
 *
 * `api._callBridge` throws on `success=false` and **drops `data`**, so a
 * failure returned that way would arrive here as a sentence with no `kind` —
 * and every branch below is on the kind, because "no microphone", "another
 * app has it", "you denied permission" and "the Windows privacy toggle is
 * eating your audio" have four different remediations and a retry button is a
 * lie for two of them. So every call can resolve with an `error` object and
 * **every call site checks `result.error` before it checks anything else**.
 * A bare `try/catch` would read "your microphone is muted" as success.
 *
 * `error.retryable` is the taxonomy's own answer to whether offering a retry
 * is honest (`src/app/stt/errors.py`'s RETRYABLE). It is never re-derived
 * here. A rejection still means what it always meant: the bridge could not do
 * its job at all — no profile open, no app data directory.
 *
 * Three things that are cheap to skip and expensive to miss (§3.5)
 * ---------------------------------------------------------------
 *
 * 1. **`onInserted` is called after every insertion, always.** The host page
 *    points it at `markDirty()` + `validateForm()`. TinyMCE's change event
 *    may or may not reach the editor's own `onChange` for a scripted insert,
 *    depending on undo-level batching — and if it does not, `isDirty` stays
 *    false, the 30-second autosave skips the entry, and the student loses a
 *    transcript with no error anywhere. Calling them twice is harmless;
 *    calling them zero times is silent data loss.
 * 2. **A stale transcript is discarded and the student is told.**
 *    Transcription takes seconds. In that window `resetFormForNewEntry()`,
 *    `populateFormWithEntry()` or `applyAutofillData()` can overwrite the
 *    form, and both targets are *required* fields, so a stale transcript can
 *    corrupt a required field on a different entry. See `_isStale`.
 * 3. **One recording at a time.** There is one microphone, one worker and one
 *    model. `_lock` is module-level; while one field holds it the other
 *    field's button is disabled with the reason on screen. Stopping the first
 *    recording to start the second was considered and rejected — it finalises
 *    a recording the student did not finish.
 *
 * The lock is held until the transcript lands, not merely until the
 * microphone closes. That is deliberate and it is the backend's shape:
 * `stopRecording` forgets the previous job (`_stt_last_job_id` is singular),
 * so a second stop while the first job is still running would throw the first
 * transcript away and answer the poll with `unknown_job`.
 *
 * The four resting states (§3.8, §7)
 * ----------------------------------
 *
 * Driven from `getSttStatus()`'s three *independent* flags, never one
 * boolean: `ready`, `no_model` (not a failure — the first press offers the
 * download), `mic_problem` and `engine_problem`. A missing engine is a broken
 * build, a missing model is a 190 MB download, and a missing microphone is a
 * cable: three sentences, three fixes.
 *
 * Neither writing field is ever disabled by any of this. The microphone is an
 * affordance on top of two required fields; if it is broken the student types
 * exactly as they did before this feature existed.
 */
(function (window, document) {
    'use strict';

    /** How often to re-read status while parked on "no microphone". */
    var STATUS_RECHECK_MS = 5000;

    /** Below this the meter is a flat line: nothing is reaching WIMI. */
    var SILENCE_FLOOR = 0.01;

    /** How long a flat line is tolerated before saying so out loud. */
    var FLAT_LINE_MS = 3000;

    /** Waiting for TinyMCE, in the shape markEntryFormReady() uses. */
    var EDITOR_POLL_MS = 25;
    var EDITOR_TIMEOUT_MS = 15000;

    // ------------------------------------------------------------------
    // Module state: one microphone, one worker, one model
    // ------------------------------------------------------------------

    /** The controller currently recording or transcribing, or null. */
    var _lock = null;

    /** Every controller on the page, so the lock can update the others. */
    var _controllers = [];

    /**
     * Monotonically increasing, page-wide. Stamped onto a job at record-stop
     * and echoed back by `pollTranscription`; a result whose token is not the
     * one its field is still waiting for is from a recording that has been
     * superseded, and is dropped.
     */
    var _token = 0;

    /**
     * One status call shared by both buttons.
     *
     * `getSttStatus()` hashes the model file to decide whether it is the one
     * the pin table names, so two controllers asking separately at page load
     * is two hashes of 190 MB. They would also be free to disagree, which is
     * worse than slow: one button offering a download beside another
     * reporting it is ready.
     */
    var _statusPromise = null;
    var _statusAt = 0;
    var STATUS_SHARE_MS = 1000;

    function sharedStatus(force) {
        var now = Date.now();
        if (!force && _statusPromise && now - _statusAt < STATUS_SHARE_MS) {
            return _statusPromise;
        }
        _statusAt = now;
        _statusPromise = api().getSttStatus();
        // A rejection must not be cached as the answer for a whole second.
        _statusPromise.catch(function () { _statusPromise = null; });
        return _statusPromise;
    }

    // ------------------------------------------------------------------
    // Platform, for the two messages that genuinely differ by platform
    // ------------------------------------------------------------------

    var _ua = (window.navigator && window.navigator.userAgent) || '';
    var IS_WINDOWS = /Windows/i.test(_ua);
    var IS_MAC = /Mac OS X|Macintosh/i.test(_ua);

    /**
     * The Windows privacy toggle does not deny anything: it delivers a stream
     * of zeros while every API reports success. Qt has no Windows permission
     * backend, so nothing else in this feature can name it — which is why it
     * is named in both messages it could possibly explain.
     */
    var WINDOWS_PRIVACY = IS_WINDOWS
        ? ' On Windows, check Settings → Privacy & security → Microphone'
          + ' and that "Let desktop apps access your microphone" is on.'
        : '';

    // ------------------------------------------------------------------
    // Copy. `errors.py` deliberately does not carry it: what to say about a
    // kind differs by platform and by where in the flow the student is, and
    // neither is knowable there.
    // ------------------------------------------------------------------

    /**
     * A student-facing sentence and a remediation for one error kind.
     *
     * @param {object} error `{kind, detail, retryable}` from the bridge.
     * @returns {{title: string, hint: string, offersDownload: boolean}}
     */
    function describeError(error) {
        var kind = (error && error.kind) || 'capture_failed';
        var detail = (error && error.detail) || '';
        switch (kind) {
            case 'no_input_device':
                return {
                    title: 'No microphone found',
                    hint: 'Plug one in or connect a headset — WIMI will '
                        + 'notice it without a reload. You can type into this '
                        + 'field as usual in the meantime.',
                    offersDownload: false
                };
            /**
             * The non-macOS sentence used to end "then press the button
             * again", and at that moment there is no pressable button (#174).
             * `restIdle`'s `mic_problem` branch calls `setView` without
             * `buttonDisabled`, which defaults it to true, and the action
             * button is empty because `PERMISSION_DENIED` is deliberately
             * absent from `errors.py`'s `RETRYABLE`. Both of those are
             * correct; §7's third rule is what was broken -- "every message
             * names the remediation", and a remediation the student cannot
             * carry out is the shrug that rule forbids, with more words.
             *
             * So the sentence names the recovery that actually works and
             * needs no press at all: `onWindowFocus` calls `refreshStatus(true)`
             * whenever the state is `mic_problem`, so coming back to WIMI
             * re-reads the three states and enables the button by itself.
             * Granting access happens in another application by definition,
             * which is what makes returning to the window the moment that
             * matters -- the same reasoning as the browser pane's button.
             *
             * Leaving the button enabled off-macOS so a press could re-check
             * was the alternative, and it is the more expensive one: it means
             * a per-platform disabled state and reopens what §7 settled with
             * `RETRYABLE`. Do not reach for it without reopening #174.
             */
            case 'permission_denied':
                return {
                    title: 'WIMI does not have microphone access',
                    hint: IS_MAC
                        ? 'Open System Settings → Privacy & Security '
                          + '→ Microphone and switch WIMI on. macOS will '
                          + 'not ask again, so this has to be done there.'
                        : 'Grant WIMI access to the microphone in your system '
                          + 'settings, then switch back to WIMI. It re-checks '
                          + 'whenever the window comes back to the front, so '
                          + 'there is nothing to press here.',
                    offersDownload: false
                };
            case 'device_in_use':
                return {
                    title: 'Your microphone is in use by another app',
                    hint: 'Close it — a video call is the usual one — '
                        + 'and try again.' + WINDOWS_PRIVACY,
                    offersDownload: false
                };
            case 'no_audio_captured':
                return {
                    title: 'WIMI heard nothing',
                    hint: 'Nothing above silence reached the microphone, so '
                        + 'there was nothing to transcribe. Check that the '
                        + 'right microphone is selected in Settings and that '
                        + 'it is not muted.' + WINDOWS_PRIVACY,
                    offersDownload: false
                };
            case 'binary_missing':
                return {
                    title: 'This build has no speech engine',
                    hint: 'The speech program did not ship with this copy of '
                        + 'WIMI, so recording cannot work here. Typing is '
                        + 'unaffected.',
                    offersDownload: false
                };
            case 'model_missing':
                return {
                    title: 'The speech model is not on this computer yet',
                    hint: 'It is about 190 MB and downloads once.',
                    offersDownload: true
                };
            case 'model_corrupt':
                return {
                    title: 'The speech model on this computer is damaged',
                    hint: 'The file does not match what it should be. '
                        + 'Downloading it again replaces it.',
                    offersDownload: true
                };
            case 'transcription_failed':
                return {
                    title: 'The transcription failed',
                    hint: 'Nothing was written to the field. ' + (detail
                        ? 'The engine said: ' + detail : ''),
                    offersDownload: false
                };
            case 'transcription_timeout':
                return {
                    title: 'The transcription took too long and was stopped',
                    hint: 'A shorter recording usually goes through. The audio '
                        + 'has been discarded.',
                    offersDownload: false
                };
            case 'download_failed':
                return {
                    title: 'The speech model did not download',
                    hint: 'Check the connection and try again. ' + (detail || ''),
                    offersDownload: true
                };
            case 'download_cancelled':
                return {
                    title: 'Download cancelled',
                    hint: 'Nothing was kept. You can start it again whenever '
                        + 'you like.',
                    offersDownload: true
                };
            case 'unknown_job':
                return {
                    title: 'WIMI lost track of that recording',
                    hint: 'Nothing was written to the field. Recording again '
                        + 'is the only way back from this one.',
                    offersDownload: false
                };
            case 'capture_failed':
            default:
                return {
                    title: 'The microphone stopped working',
                    hint: (detail ? detail + ' ' : '')
                        + 'Typing into this field still works.'
                        + WINDOWS_PRIVACY,
                    offersDownload: false
                };
        }
    }

    // ------------------------------------------------------------------
    // Small helpers
    // ------------------------------------------------------------------

    function api() {
        // Resolved at call time: `_loader.js` moves the object to
        // `window.api` with a document.write, and a page script captured at
        // load time would hold the wrong thing.
        return window.api;
    }

    function el(tag, className, attrs) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (attrs) {
            Object.keys(attrs).forEach(function (key) {
                node.setAttribute(key, attrs[key]);
            });
        }
        return node;
    }

    /** Percentage for the meter. Square root because speech RMS is small. */
    function meterWidth(rms) {
        var value = Math.max(0, Number(rms) || 0);
        return Math.min(100, Math.round(Math.sqrt(value) * 140));
    }

    function formatBytes(bytes) {
        if (!bytes && bytes !== 0) return '';
        var mb = bytes / (1024 * 1024);
        return (mb >= 100 ? Math.round(mb) : mb.toFixed(1)) + ' MB';
    }

    /**
     * The staleness fields, wherever the payload happens to carry them.
     *
     * `pollTranscription` puts them at the top level *and* inside `context`;
     * a `stopRecording` failure carries only `context`. Reading both means a
     * failed capture can still be reported beside the field that asked for
     * it — a failure the page cannot place is a failure it cannot report.
     */
    function contextOf(payload) {
        var ctx = (payload && payload.context) || {};
        return {
            entry_id: payload && payload.entry_id !== undefined
                ? payload.entry_id : ctx.entry_id,
            field_key: payload && payload.field_key !== undefined
                ? payload.field_key : ctx.field_key,
            token: payload && payload.token !== undefined
                ? payload.token : ctx.token
        };
    }

    // ------------------------------------------------------------------
    // The controller
    // ------------------------------------------------------------------

    /**
     * Put a microphone beside one writing field.
     *
     * @param {object} options
     * @param {RichEditor} options.editor the field's editor.
     * @param {HTMLElement} options.mountEl where the control is rendered.
     * @param {string} options.fieldKey `'reflection'` or `'explanation'`;
     *     carried through the job so a transcript can only ever be delivered
     *     back to the field that asked for it.
     * @param {string} [options.label] what the field is called, for the
     *     other button's "why am I disabled" line.
     * @param {function} [options.getContext] returns
     *     `{entry_id, entry_index, subject_ids, exam_context_id}` for the
     *     entry the form is showing **right now**. Called at record-stop and
     *     again when the transcript lands; the two are compared.
     * @param {function} [options.onInserted] called after every successful
     *     insertion. Point it at `markDirty()` + `validateForm()` — see the
     *     module docstring for what happens if nothing does.
     * @param {function} [options.notify] `(level, title, message)` for a
     *     toast. Optional; the status line always says it too.
     * @returns {object} the controller.
     */
    function attachDictation(options) {
        var editor = options.editor;
        var mountEl = options.mountEl;
        var fieldKey = options.fieldKey;
        var label = options.label || fieldKey;
        var getContext = options.getContext || function () { return {}; };
        var onInserted = options.onInserted || function () {};
        var notify = options.notify || function () {};

        var state = 'starting';
        var status = null;          // the last getSttStatus() payload
        var pending = null;         // the job this field is waiting for
        var bookmark = null;        // where the caret was at record-start
        var stopLevelWatch = null;
        var recheckTimer = null;
        var flatSince = null;
        var destroyed = false;
        var everFocused = false;
        var downloadJobId = null;

        // -- markup ----------------------------------------------------

        var root = el('div', 'dictation', {
            'data-field-key': fieldKey,
            'data-testid': 'dictation-' + fieldKey
        });
        var row = el('div', 'dictation-row');
        var button = el('button', 'dictation-btn', {
            type: 'button',
            'data-testid': 'dictation-' + fieldKey + '-button'
        });
        var icon = el('span', 'dictation-icon', { 'aria-hidden': 'true' });
        icon.textContent = '●';   // a dot; it turns red while recording
        var btnLabel = el('span', 'dictation-btn-label');
        button.appendChild(icon);
        button.appendChild(btnLabel);

        // The meter always owns its fill element, so it never renders as a
        // container with no children -- which is exactly the shape the
        // Qt 6.10 `:empty` regression bites (#134, #136, #141).
        var meter = el('div', 'dictation-meter', {
            'data-testid': 'dictation-' + fieldKey + '-meter',
            'aria-hidden': 'true'
        });
        var meterFill = el('span', 'dictation-meter-fill');
        meter.appendChild(meterFill);

        var action = el('button', 'dictation-action', {
            type: 'button',
            'data-testid': 'dictation-' + fieldKey + '-action'
        });

        row.appendChild(button);
        row.appendChild(meter);
        row.appendChild(action);

        var statusLine = el('p', 'dictation-status', {
            role: 'status',
            'aria-live': 'polite',
            'data-testid': 'dictation-' + fieldKey + '-status'
        });

        root.appendChild(row);
        root.appendChild(statusLine);
        mountEl.appendChild(root);

        // -- rendering -------------------------------------------------

        var view = {
            buttonLabel: 'Speak',
            buttonDisabled: true,
            title: '',
            hint: '',
            tone: '',            // '', 'error', 'warn', 'busy'
            actionLabel: '',
            actionHandler: null,
            meterVisible: false
        };

        function render() {
            root.setAttribute('data-state', state);
            btnLabel.textContent = view.buttonLabel;
            button.disabled = Boolean(view.buttonDisabled);
            button.setAttribute('aria-pressed', state === 'recording'
                ? 'true' : 'false');
            button.classList.toggle('is-recording', state === 'recording');

            var text = view.title;
            if (view.hint) text = text ? text + ' ' + view.hint : view.hint;
            statusLine.textContent = text;
            statusLine.className = 'dictation-status'
                + (view.tone ? ' dictation-status--' + view.tone : '');

            if (view.actionLabel && view.actionHandler) {
                action.textContent = view.actionLabel;
                action.hidden = false;
                action.disabled = false;
            } else {
                action.textContent = '';
                action.hidden = true;
            }

            meter.hidden = !view.meterVisible;
            if (!view.meterVisible) meterFill.style.width = '0%';
        }

        function setView(next) {
            view = {
                buttonLabel: next.buttonLabel || 'Speak',
                buttonDisabled: next.buttonDisabled !== false,
                title: next.title || '',
                hint: next.hint || '',
                tone: next.tone || '',
                actionLabel: next.actionLabel || '',
                actionHandler: next.actionHandler || null,
                meterVisible: Boolean(next.meterVisible)
            };
            render();
        }

        action.addEventListener('click', function () {
            if (view.actionHandler) view.actionHandler();
        });

        // -- status ----------------------------------------------------

        function clearRecheck() {
            if (recheckTimer !== null) {
                clearTimeout(recheckTimer);
                recheckTimer = null;
            }
        }

        /**
         * Re-read the three independent states and park on the matching
         * resting state. Never throws into a caller: a status call that
         * fails is reported on the line, not up the stack, because the
         * writing field must keep working whatever speech is doing.
         */
        async function refreshStatus(force) {
            clearRecheck();
            try {
                status = await sharedStatus(force === true);
            } catch (e) {
                status = null;
                state = 'engine_problem';
                setView({
                    title: 'Speech is unavailable on this page.',
                    hint: (e && e.message) || '',
                    tone: 'error'
                });
                return;
            }
            if (destroyed) return;
            restIdle();
        }

        /** Park on whichever of the four resting states the status names. */
        function restIdle() {
            if (_lock && _lock !== controller) {
                restBlocked();
                return;
            }
            if (!status) {
                state = 'starting';
                setView({ title: 'Checking the microphone…', tone: 'busy' });
                return;
            }

            if (!status.engine_ready) {
                state = 'engine_problem';
                var engineError = (status.engine && status.engine.error)
                    || { kind: 'binary_missing' };
                var engineCopy = describeError(engineError);
                setView({
                    title: engineCopy.title + '.',
                    hint: engineCopy.hint,
                    tone: 'error'
                });
                return;
            }

            var micError = status.mic && status.mic.error;
            if (micError) {
                state = 'mic_problem';
                var micCopy = describeError(micError);
                setView({
                    title: micCopy.title + '.',
                    hint: micCopy.hint,
                    tone: 'error',
                    // `retryable` is the taxonomy's own answer to whether a
                    // retry button is honest here. It is never re-derived.
                    actionLabel: micError.retryable ? 'Try again' : '',
                    actionHandler: micError.retryable ? refreshStatus : null
                });
                if (micError.kind === 'no_input_device') {
                    // Qt signals a device list change, but nothing exposes
                    // that signal to the page, so plugging in a headset is
                    // noticed by asking again. Only while parked here.
                    recheckTimer = setTimeout(refreshStatus, STATUS_RECHECK_MS);
                }
                return;
            }

            if (!status.model_ready) {
                // Not a failure. It is the first-run resting state, and the
                // button offers the download rather than reporting that
                // something is broken (§3.8).
                state = 'no_model';
                setView({
                    // The button says what pressing it will do, and the line
                    // beneath says what it costs. THAT is the confirmation
                    // §3.8 asks for -- a student who presses a button reading
                    // "Download and speak" under a sentence naming 190 MB has
                    // agreed to a download. A modal here would be one more
                    // thing between an 11pm student and the recording they
                    // came to make, which is the friction this whole feature
                    // exists to remove.
                    buttonLabel: 'Download and speak',
                    buttonDisabled: false,
                    title: 'Speaking needs a one-time download.',
                    hint: 'About 190 MB, once. After that it works offline and '
                        + 'your audio never leaves this computer.',
                    actionLabel: 'Download only',
                    actionHandler: function () { startDownload(false); }
                });
                return;
            }

            state = 'ready';
            setView({
                buttonLabel: 'Speak',
                buttonDisabled: false,
                title: 'Explain it out loud, as if you were teaching it.',
                hint: ''
            });
        }

        /** The other field holds the microphone. Say so, do not just grey. */
        function restBlocked() {
            state = 'blocked';
            var holder = _lock ? _lock.label : 'another field';
            setView({
                buttonLabel: 'Speak',
                buttonDisabled: true,
                title: 'One recording at a time.',
                hint: 'WIMI is still working on “' + holder + '”. '
                    + 'This button comes back when that transcript arrives.',
                tone: 'warn'
            });
        }

        // -- the lock --------------------------------------------------

        function takeLock() {
            _lock = controller;
            _controllers.forEach(function (other) {
                if (other !== controller) other.refreshIdle();
            });
        }

        function releaseLock() {
            if (_lock === controller) _lock = null;
            _controllers.forEach(function (other) {
                if (other !== controller) other.refreshIdle();
            });
        }

        // -- the model download ----------------------------------------

        /**
         * Fetch the weights, in place on the button.
         *
         * @param {boolean} thenRecord start the recording the student came
         *     to make once it lands — but only if they are still here and
         *     still on the same field, because a download runs for minutes
         *     and opening a microphone into an empty room is not a kindness.
         */
        async function startDownload(thenRecord) {
            if (state === 'downloading') return;
            state = 'downloading';
            downloadJobId = null;
            setView({
                buttonLabel: 'Downloading…',
                buttonDisabled: true,
                title: 'Downloading the speech model…',
                tone: 'busy',
                actionLabel: 'Cancel',
                actionHandler: cancelDownload
            });

            // `downloadSttModel` would hide this loop, and since #171 it
            // *can* be cancelled -- `pollModelDownload` returns `job_id`
            // and the composite passes the poll payload to `onProgress`.
            // Two things still keep the loop here, and neither is the job
            // id: the composite polls until the job is terminal, so a
            // controller destroyed mid-download would go on calling the
            // bridge for the minutes the download has left; and
            // `downloadJobId` is wanted *before* the first poll, so Cancel
            // is live the moment the button says "Cancel" rather than one
            // round trip later.
            var report;
            try {
                var started = await api().startModelDownload('');
                downloadJobId = started.job_id;
                for (;;) {
                    report = await api().pollModelDownload(downloadJobId);
                    if (destroyed) return;
                    if (report.state !== 'running') break;
                    var done = formatBytes(report.bytes);
                    // `total` may legitimately be null: a response without a
                    // Content-Length is legal, so the progress line has to
                    // survive not knowing how big the file is.
                    var total = report.total
                        ? ' of ' + formatBytes(report.total) : '';
                    view.title = 'Downloading the speech model… '
                        + done + total;
                    render();
                    await new Promise(function (resolve) {
                        setTimeout(resolve, 400);
                    });
                    if (destroyed) return;
                }
            } catch (e) {
                if (destroyed) return;
                state = 'no_model';
                setView({
                    buttonLabel: 'Download and speak',
                    buttonDisabled: false,
                    title: 'The download could not start.',
                    hint: (e && e.message) || '',
                    tone: 'error',
                    actionLabel: 'Try again',
                    actionHandler: function () { startDownload(false); }
                });
                return;
            }
            if (destroyed) return;

            if (report.state !== 'done') {
                var copy = describeError(report.error || {});
                state = 'no_model';
                setView({
                    buttonLabel: 'Download and speak',
                    buttonDisabled: false,
                    title: copy.title + '.',
                    hint: copy.hint,
                    tone: report.error && report.error.kind === 'download_cancelled'
                        ? '' : 'error',
                    actionLabel: 'Download only',
                    actionHandler: function () { startDownload(false); }
                });
                return;
            }

            await refreshStatus(true);
            if (destroyed) return;
            if (thenRecord && state === 'ready'
                && document.visibilityState === 'visible') {
                startRecording();
            } else if (state === 'ready') {
                view.title = 'The speech model is ready.';
                view.hint = 'Press the button whenever you want to speak.';
                render();
            }
        }

        function cancelDownload() {
            action.disabled = true;
            if (!downloadJobId) return;
            api().cancelModelDownload(downloadJobId).catch(function () {
                // The poll loop reports download_cancelled a moment later;
                // a failure to cancel is not worth a second message.
            });
        }

        // -- recording -------------------------------------------------

        async function startRecording() {
            if (_lock && _lock !== controller) { restBlocked(); return; }
            if (state === 'recording' || state === 'transcribing') return;

            if (!status || !status.model_ready) {
                // The first press is the download offer, not a failure.
                await refreshStatus();
                if (destroyed) return;
                if (state === 'no_model') { startDownload(true); return; }
                if (state !== 'ready') return;
            }

            takeLock();
            state = 'recording';
            flatSince = null;
            setView({
                buttonLabel: 'Starting…',
                buttonDisabled: true,
                title: 'Opening the microphone…',
                tone: 'busy'
            });

            // Where the caret is NOW. The student's model is "I put the
            // cursor here and started talking"; eight seconds later they may
            // have clicked elsewhere entirely.
            bookmark = editor.captureInsertionPoint({ atEnd: !everFocused });

            var started;
            try {
                started = await api().startRecording();
            } catch (e) {
                releaseLock();
                state = 'error';
                setView({
                    buttonLabel: 'Speak',
                    buttonDisabled: false,
                    title: 'The microphone could not be opened.',
                    hint: (e && e.message) || '',
                    tone: 'error'
                });
                return;
            }
            if (destroyed) return;

            // A named capture failure arrives HERE, on the resolve path,
            // with a kind to branch on -- not as a rejection.
            if (started.error) {
                releaseLock();
                reportError(started.error, startRecording);
                return;
            }

            state = 'recording';
            setView({
                buttonLabel: 'Stop',
                buttonDisabled: false,
                title: 'Listening…',
                hint: 'Say it as you would explain it to someone else.',
                tone: 'busy',
                meterVisible: true,
                actionLabel: 'Cancel',
                actionHandler: cancelRecording
            });

            if (started.device_choice_honoured === false) {
                view.hint = 'The microphone you chose in Settings is not here, '
                    + 'so WIMI is using the default one.';
                render();
            }

            stopLevelWatch = api().watchRecordingLevel(onLevel);
        }

        /**
         * The meter, which is not decoration.
         *
         * It is the only thing that tells a student their microphone is
         * muted *while they are still speaking* rather than ninety seconds
         * later, and on Windows it is one of only two detectors this feature
         * has for the privacy toggle (§7).
         */
        function onLevel(level) {
            if (destroyed || state !== 'recording') return;
            meterFill.style.width = meterWidth(level && level.rms) + '%';

            if (level && level.stream_error) {
                var streamCopy = describeError(level.stream_error);
                view.title = streamCopy.title + '.';
                view.hint = 'What was recorded up to that point is kept.';
                view.tone = 'error';
                render();
                return;
            }

            var peak = (level && Number(level.peak)) || 0;
            if (peak > SILENCE_FLOOR) {
                flatSince = null;
                if (view.tone === 'warn') {
                    view.title = 'Listening…';
                    view.hint = 'Say it as you would explain it to someone else.';
                    view.tone = 'busy';
                    render();
                }
                return;
            }
            if (flatSince === null) { flatSince = Date.now(); return; }
            if (Date.now() - flatSince > FLAT_LINE_MS && view.tone !== 'warn') {
                view.title = 'WIMI is not hearing anything.';
                view.hint = 'The meter has been flat while you have been '
                    + 'speaking, which usually means the microphone is muted '
                    + 'or the wrong one is selected.' + WINDOWS_PRIVACY;
                view.tone = 'warn';
                render();
            }
        }

        async function cancelRecording() {
            if (state !== 'recording') return;
            stopWatching();
            state = 'cancelling';
            setView({
                buttonLabel: 'Speak',
                buttonDisabled: true,
                title: 'Discarding the recording…',
                tone: 'busy'
            });
            try {
                await api().cancelRecording();
            } catch (e) {
                // Idempotent on the bridge side, and there is nothing the
                // student can do about a failed cancel.
            }
            releaseLock();
            if (destroyed) return;
            await refreshStatus();
            if (!destroyed && state === 'ready') {
                view.title = 'Recording discarded. Nothing was written.';
                render();
            }
        }

        function stopWatching() {
            if (stopLevelWatch) {
                try { stopLevelWatch(); } catch (e) { /* already stopped */ }
                stopLevelWatch = null;
            }
        }

        /**
         * Stop the microphone, queue the transcription, and wait.
         *
         * The job is stamped with the entry id, the field key and a
         * monotonically increasing token at THIS moment, and the same three
         * come back with the result. Everything after that is the staleness
         * check in `_isStale`.
         */
        async function stopRecording() {
            if (state !== 'recording') return;
            stopWatching();

            var here = getContext() || {};
            _token += 1;
            pending = {
                token: _token,
                entryId: here.entry_id === undefined ? null : here.entry_id,
                entryIndex: here.entry_index === undefined ? null : here.entry_index,
                replaced: false
            };

            state = 'transcribing';
            setView({
                buttonLabel: 'Transcribing…',
                buttonDisabled: true,
                title: 'Writing down what you said…',
                hint: 'This takes a few seconds and runs entirely on this '
                    + 'computer.',
                tone: 'busy'
            });

            var context = {
                entry_id: pending.entryId,
                field_key: fieldKey,
                token: pending.token,
                subject_ids: here.subject_ids || [],
                exam_context_id: here.exam_context_id === undefined
                    ? null : here.exam_context_id
            };

            var report;
            try {
                report = await api().transcribeRecording(context);
            } catch (e) {
                releaseLock();
                pending = null;
                if (destroyed) return;
                state = 'error';
                setView({
                    buttonLabel: 'Speak',
                    buttonDisabled: false,
                    title: 'The transcription could not be run.',
                    hint: (e && e.message) || '',
                    tone: 'error'
                });
                return;
            }
            releaseLock();
            if (destroyed) return;

            // `stopRecording` itself can fail with a kind (no_audio_captured
            // is the common one), in which case there is no job and the
            // payload carries `job_id: null`.
            if (report.error) {
                pending = null;
                reportError(report.error, startRecording, report);
                return;
            }
            if (report.state === 'failed') {
                pending = null;
                reportError(report.error || { kind: 'transcription_failed' },
                    startRecording, report);
                return;
            }

            deliver(report);
        }

        // -- staleness -------------------------------------------------

        /**
         * Is this result still for the form on screen?
         *
         * Four ways it can be stale, and each of them has happened to
         * somebody's required field:
         *
         * - a **token** that is not the one this field is waiting for: the
         *   student recorded again, or cancelled, and this is the earlier
         *   recording arriving late;
         * - a **field key** that is not ours: a transcript may only ever be
         *   delivered to the field that asked for it;
         * - a different **entry**: `populateFormWithEntry()` or
         *   `navigateToEntry()` swapped the form under the job. `null ->
         *   a number` is NOT a swap — that is the same entry being saved for
         *   the first time by the autosave, which must not cost the student
         *   their transcript;
         * - the editor's whole content was **replaced** while the job ran
         *   (`resetFormForNewEntry()`, `populateFormWithEntry()`, or
         *   `applyAutofillData()`, which writes into `#explanation-editor`).
         *   The entry id alone does not see autofill, which changes the
         *   content without changing which entry it is.
         *
         * @returns {string|null} why it is stale, or null if it is good.
         */
        function stalenessReason(report) {
            if (!pending) return 'this field is no longer waiting for it';
            var echoed = contextOf(report);
            if (echoed.field_key !== fieldKey) {
                return 'it was recorded for a different field';
            }
            if (Number(echoed.token) !== Number(pending.token)) {
                return 'a newer recording replaced it';
            }
            if (pending.replaced) {
                return 'the field was rewritten while it was being transcribed';
            }
            var here = getContext() || {};
            var nowId = here.entry_id === undefined ? null : here.entry_id;
            if (pending.entryIndex !== null && here.entry_index !== undefined
                && here.entry_index !== pending.entryIndex) {
                return 'you moved to a different entry';
            }
            if (pending.entryId !== null && nowId !== pending.entryId) {
                return 'you moved to a different entry';
            }
            return null;
        }

        /** Insert, or say why not. Never silently drop anything. */
        function deliver(report) {
            var stale = stalenessReason(report);
            var text = (report.text || '').trim();
            pending = null;

            if (stale) {
                state = 'ready';
                setView({
                    buttonLabel: 'Speak',
                    buttonDisabled: false,
                    title: 'That transcript was discarded.',
                    hint: 'It arrived after ' + stale + ', so putting it in '
                        + 'now would have written it over something else.',
                    tone: 'warn'
                });
                notify('warning', 'Transcript discarded',
                    'A recording finished after ' + stale + '.');
                console.warn('[dictation] discarded a stale transcript for '
                    + fieldKey + ': ' + stale);
                return;
            }

            if (!text) {
                // Silence transcribes to the word " you", not to nothing, so
                // the backend's peak check is what usually catches this --
                // but an empty string still has to mean something here.
                reportError({
                    kind: 'no_audio_captured',
                    detail: 'the transcript was empty',
                    retryable: true
                }, startRecording, report);
                return;
            }

            try {
                editor.insertTranscript(text, bookmark);
            } catch (e) {
                state = 'error';
                setView({
                    buttonLabel: 'Speak',
                    buttonDisabled: false,
                    title: 'The transcript could not be inserted.',
                    hint: (e && e.message) || '',
                    tone: 'error'
                });
                console.error('[dictation] insertTranscript failed', e);
                notify('error', 'Transcript not inserted',
                    'What you said could not be written into the field.');
                return;
            }
            bookmark = null;

            // Explicitly, always, whatever TinyMCE's change event did or did
            // not do. See the module docstring: without this the autosave
            // skips the entry and the transcript is lost with no error.
            try {
                onInserted();
            } catch (e) {
                console.error('[dictation] onInserted failed', e);
            }

            state = 'ready';
            setView({
                buttonLabel: 'Speak',
                buttonDisabled: false,
                title: 'Added what you said.',
                hint: 'Edit it like any other text — Ctrl+Z removes it.'
            });
        }

        function reportError(error, retryHandler, payload) {
            var copy = describeError(error);
            state = 'error';
            var actionLabel = '';
            var handler = null;
            if (copy.offersDownload) {
                actionLabel = 'Download now';
                handler = function () { startDownload(false); };
            } else if (error && error.retryable) {
                actionLabel = 'Try again';
                handler = retryHandler;
            }
            var hint = copy.hint;
            var capture = payload && payload.capture;
            if (capture && capture.seconds) {
                hint += ' (' + capture.seconds + ' s were recorded.)';
            }
            setView({
                buttonLabel: 'Speak',
                buttonDisabled: false,
                title: copy.title + '.',
                hint: hint,
                tone: 'error',
                actionLabel: actionLabel,
                actionHandler: handler
            });
            notify('error', copy.title, copy.hint);
        }

        // -- wiring ----------------------------------------------------

        button.addEventListener('click', function () {
            if (state === 'recording') { stopRecording(); return; }
            if (state === 'ready' || state === 'no_model'
                || state === 'error') {
                startRecording();
            }
        });

        /**
         * Bind to the TinyMCE instance once it exists.
         *
         * Two listeners, both read-only:
         *
         * - `focus`, so an editor the student has never put the cursor in
         *   gets its transcript at the END of the document rather than
         *   prepended, which is where TinyMCE's default selection sits;
         * - `SetContent` without `selection`, which is a whole-document
         *   replacement — `clear()` from `resetFormForNewEntry()`, and
         *   `setContent()` from `populateFormWithEntry()` and
         *   `applyAutofillData()`. An insert-at-caret carries
         *   `selection: true` and is not this.
         */
        function bindEditorEvents(deadline) {
            if (destroyed) return;
            var tiny = editor && editor.getEditor && editor.getEditor();
            if (!tiny || !editor.isInitialized) {
                if (Date.now() < deadline) {
                    setTimeout(function () { bindEditorEvents(deadline); },
                        EDITOR_POLL_MS);
                } else {
                    console.warn('[dictation] the ' + fieldKey + ' editor never '
                        + 'reported ready; dictation will still record, but the '
                        + 'insertion point cannot be tracked');
                }
                return;
            }
            tiny.on('focus', function () { everFocused = true; });
            tiny.on('SetContent', function (e) {
                if (e && e.selection) return;      // an insert, not a replace
                if (pending) pending.replaced = true;
            });
        }

        var controller = {
            fieldKey: fieldKey,
            label: label,
            root: root,
            /** Re-read status and park on a resting state. */
            refresh: refreshStatus,
            /** Re-render the resting state without a bridge call. */
            refreshIdle: function () {
                if (state === 'recording' || state === 'transcribing'
                    || state === 'downloading' || state === 'cancelling') {
                    return;
                }
                restIdle();
            },
            /** For tests and for the host page. */
            getState: function () { return state; },
            destroy: function () {
                destroyed = true;
                clearRecheck();
                stopWatching();
                releaseLock();
                window.removeEventListener('focus', onWindowFocus);
                if (root.parentNode) root.parentNode.removeChild(root);
                var at = _controllers.indexOf(controller);
                if (at !== -1) _controllers.splice(at, 1);
            }
        };

        // The browser-pane button's precedent: a control must never claim a
        // state it cannot see. Coming back to the window is exactly when a
        // headset has been plugged in or a video call has ended.
        function onWindowFocus() {
            if (destroyed) return;
            controller.refreshIdle();
            if (state === 'mic_problem' || state === 'engine_problem') {
                refreshStatus(true);
            }
        }

        _controllers.push(controller);
        render();
        bindEditorEvents(Date.now() + EDITOR_TIMEOUT_MS);
        // Deliberately no status call here. Attaching is DOM work; reading
        // the three states is a bridge call, and the host page makes it from
        // inside its own init `try` where a failure has somewhere to land.
        // Until then the button reads "Checking the microphone" and is
        // disabled -- and the first press would fetch the status anyway.

        window.addEventListener('focus', onWindowFocus);

        return controller;
    }

    window.attachDictation = attachDictation;
    window.Dictation = {
        attach: attachDictation,
        describeError: describeError,
        /** Whoever holds the microphone, or null. For tests. */
        holder: function () { return _lock ? _lock.fieldKey : null; }
    };

})(window, document);
