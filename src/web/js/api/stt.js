/**
 * WIMI API — Speech to Text (#59)
 *
 * A record button beside each of the entry form's two existing writing
 * fields. The student speaks; WIMI records through Qt, runs a vendored
 * whisper.cpp against the WAV on a worker thread with a prompt primed from
 * their own subject tree, and hands the transcript back. The audio never
 * leaves the machine, at any tier, including as a fallback.
 *
 * **A named speech failure resolves; it does not reject.** `_callBridge`
 * throws on `success=false` and drops `data` on the floor, so a failure
 * returned that way arrives as a sentence with no `kind`. The kind is the
 * whole point — "no microphone", "another app has it", "you denied
 * permission" and "the Windows privacy toggle is eating your audio" have
 * four different remediations, and a retry button is a lie for two of them.
 * So every call below can resolve with an `error` object:
 *
 *     const started = await api.startRecording();
 *     if (started.error) { show(started.error.kind, started.error.retryable); }
 *
 * `error.kind` is one of `no_input_device`, `permission_denied`,
 * `device_in_use`, `no_audio_captured`, `capture_failed`, `binary_missing`,
 * `model_missing`, `model_corrupt`, `transcription_failed`,
 * `transcription_timeout`, `download_failed`, `download_cancelled`,
 * `unknown_job`. `error.retryable` is the taxonomy's own answer to whether
 * offering a retry is honest, so no page has to re-derive it.
 *
 * A rejection still means what it always meant: the bridge could not do its
 * job — no profile open, no app data directory, malformed arguments.
 *
 * **"No model yet" is not a failure.** It is the first-run resting state:
 * `getSttStatus().model_ready` is false with `model.error.kind ===
 * 'model_missing'`, and the button offers `downloadSttModel` rather than
 * reporting that something is broken.
 *
 * **The staleness contract is yours to enforce.** `stopRecording` takes the
 * entry id, the field key, a monotonically increasing token and the subject
 * ids; `pollTranscription` gives all four back. Compare them against what
 * the page is still looking at before inserting anything. The form can be
 * overwritten by `resetFormForNewEntry`, `populateFormWithEntry` or
 * `applyAutofillData` while a transcription runs, and both dictation
 * targets are *required* fields.
 */
(function(api) {
    'use strict';

    /** How often to ask a running job whether it has finished. */
    var POLL_MS = 400;

    /** How often to refresh the level meter while recording. */
    var LEVEL_MS = 100;

    /**
     * The three independent states: engine, model, microphone.
     *
     * Never collapse them into one boolean. A missing engine is a broken
     * build, a missing model is a 190 MB download, and a missing microphone
     * is a cable — three sentences, three fixes.
     *
     * @returns {Promise<object>} `{engine_ready, model_ready, model_size,
     *     engine, model, mic: {permission, devices, ready, error},
     *     priming_enabled, show_first_use_notice, recording}`.
     *     `mic.permission` is `granted` / `denied` / `undetermined`, and is
     *     **always `granted` on Windows** whatever the OS thinks — Qt has no
     *     Windows permission backend.
     */
    api.getSttStatus = async function() {
        return api._callBridge('getSttStatus');
    };

    /**
     * Ask the OS for microphone access.
     *
     * Meaningful on macOS, where the answer is remembered system-wide and a
     * second prompt never comes. `pending: true` means Qt has not resolved
     * yet and `permission` is the state as it stands, not the answer.
     *
     * @returns {Promise<object>} `{permission, pending}`.
     */
    api.requestMicrophonePermission = async function() {
        return api._callBridge('requestMicrophonePermission');
    };

    /**
     * Open the microphone and start writing a WAV.
     *
     * @param {string} [deviceId] a device id from `getSttStatus().mic.devices`,
     *     or omitted for this machine's stored choice and then the default.
     * @returns {Promise<object>} `{recording: true, device, format,
     *     device_choice_honoured}`, or `{recording: false, error}`.
     *     `device_choice_honoured: false` means the stored microphone is
     *     gone and the default was used instead — worth saying once.
     */
    api.startRecording = async function(deviceId) {
        return api._callBridge('startRecording', deviceId || '');
    };

    /**
     * The latest microphone level, for the meter.
     *
     * The meter is not decoration: it is the only signal that tells a
     * student their microphone is muted *while they are still speaking*,
     * rather than ninety seconds later.
     *
     * @returns {Promise<object>} `{recording, rms, peak, stream_error}`,
     *     both levels normalised 0.0–1.0.
     */
    api.getRecordingLevel = async function() {
        return api._callBridge('getRecordingLevel');
    };

    /**
     * Stop the microphone and queue the transcription.
     *
     * @param {object} context `{entry_id, field_key, token, subject_ids}`,
     *     plus an optional `exam_context_id` — without it, an entry with no
     *     subject tagged yet gets no vocabulary priming at all, because the
     *     fallback tier is the exam's most-mistaken subjects.
     * @returns {Promise<object>} `{job_id, context, primed, capture}`, or
     *     `{job_id: null, error, context}` — `no_audio_captured` is the
     *     common one and means the peak never rose above the floor.
     */
    api.stopRecording = async function(context) {
        return api._callBridge('stopRecording', JSON.stringify(context || {}));
    };

    /**
     * Throw away the recording in progress. The WAV is deleted; nothing was
     * queued. Safe to call when nothing is recording.
     *
     * @returns {Promise<object>} `{recording: false, cancelled}`.
     */
    api.cancelRecording = async function() {
        return api._callBridge('cancelRecording');
    };

    /**
     * Where a transcription has got to.
     *
     * @param {string} jobId
     * @returns {Promise<object>} `{state: 'running'}`, or `{state: 'done',
     *     text, ms, entry_id, field_key, token, context}`, or
     *     `{state: 'failed', error, code, message, entry_id, field_key,
     *     token, context}`. The four staleness fields come back on **both**
     *     terminal states.
     */
    api.pollTranscription = async function(jobId) {
        return api._callBridge('pollTranscription', String(jobId));
    };

    /**
     * Stop recording and resolve with the transcript.
     *
     * Polls for you. `onLevel` is not called here — recording has already
     * stopped — but `onProgress` fires once per poll while the worker runs,
     * which is all the progress that honestly exists: whisper.cpp reports
     * nothing until it is done.
     *
     * Resolves with the poll's own payload, so **check `state`**: a
     * transcription that failed for a named reason resolves with
     * `{state: 'failed', error}` rather than rejecting, for the same reason
     * everything else here does.
     *
     * @param {object} context as for `stopRecording`.
     * @param {function} [onProgress] called with no arguments per poll.
     * @returns {Promise<object>} the terminal poll payload, or
     *     `stopRecording`'s own `{job_id: null, error, context}` when the
     *     capture never produced anything to transcribe.
     */
    api.transcribeRecording = async function(context, onProgress) {
        const stopped = await api.stopRecording(context);
        if (!stopped.job_id) return stopped;
        for (;;) {
            const report = await api.pollTranscription(stopped.job_id);
            if (report.state !== 'running') return report;
            if (typeof onProgress === 'function') onProgress(report);
            await new Promise(resolve => setTimeout(resolve, POLL_MS));
        }
    };

    /**
     * Poll the microphone level until recording stops.
     *
     * Returns a function that stops the loop early. The loop ends by itself
     * when `recording` goes false, so a caller that forgets to stop it leaks
     * nothing — but call it anyway on teardown.
     *
     * @param {function} onLevel called with `{rms, peak, stream_error}`.
     * @returns {function} stop
     */
    api.watchRecordingLevel = function(onLevel) {
        let live = true;
        (async function() {
            while (live) {
                let level;
                try {
                    level = await api.getRecordingLevel();
                } catch (e) {
                    return;
                }
                if (!live) return;
                if (typeof onLevel === 'function') onLevel(level);
                if (!level.recording) return;
                await new Promise(resolve => setTimeout(resolve, LEVEL_MS));
            }
        })();
        return function() { live = false; };
    };

    /**
     * Fetch the pinned speech model. The first-run path, and a normal one.
     *
     * @param {string} [size] a size from `getSttSettings().available_models`,
     *     or omitted for this machine's choice and then the default.
     * @returns {Promise<object>} `{job_id, size, filename, total_bytes}`.
     */
    api.startModelDownload = async function(size) {
        return api._callBridge('startModelDownload', size || '');
    };

    /**
     * Where a download has got to.
     *
     * **`job_id` comes back on every state**, including `unknown_job`. That
     * is what makes `downloadSttModel` cancellable (#171): the composite
     * starts the job itself, so the poll payload is the only place a caller
     * using it can learn the id. It also means a poll line in a log says
     * which job it belongs to.
     *
     * @param {string} jobId
     * @returns {Promise<object>} `{job_id, state: 'running', bytes, total,
     *     size}`, `{job_id, state: 'done', path, size}`, or `{job_id,
     *     state: 'failed', error, code, message}`. **`total` may be `null`**
     *     — a response without a Content-Length is legal, so a progress bar
     *     must survive not knowing how big the file is.
     */
    api.pollModelDownload = async function(jobId) {
        return api._callBridge('pollModelDownload', String(jobId));
    };

    /**
     * Cancel a download and delete its partial file.
     *
     * @param {string} jobId
     * @returns {Promise<object>} `{cancelled}`. Keep polling: the job
     *     reaches `failed` with `download_cancelled` a moment later.
     */
    api.cancelModelDownload = async function(jobId) {
        return api._callBridge('cancelModelDownload', String(jobId));
    };

    /**
     * Delete one downloaded model from this machine.
     *
     * Changing size downloads the new model and **leaves the old one
     * alone**, so that switching back is free. The price is that models
     * accumulate ~190 MB at a time, and this is the explicit undo: nothing
     * removes a model behind a settings change.
     *
     * `removed: false` means there was nothing there, which is a success.
     *
     * @param {string} [size] a size from `getSttSettings().available_models`,
     *     or omitted for this machine's resolved size.
     * @returns {Promise<object>} `{size, removed, path}`.
     */
    api.removeSttModel = async function(size) {
        return api._callBridge('removeSttModel', size || '');
    };

    /**
     * Download the model and resolve when it is installed.
     *
     * `onProgress` is called with the poll payload — `{job_id, bytes,
     * total, size}` — per poll. Resolves with the terminal poll payload, so
     * check `state`: a cancelled or failed download resolves rather than
     * rejecting.
     *
     * **Cancel through `job_id` on the progress payload** (#171). §3.8
     * requires a download be stoppable mid-flight, and this composite
     * starts the job itself, so the progress report is where its id
     * arrives:
     *
     *     let jobId = null;
     *     const report = await api.downloadSttModel('', p => {
     *         jobId = p.job_id;            // same id on every poll
     *         drawProgress(p);
     *     });
     *     // meanwhile, from a Cancel button:
     *     if (jobId) api.cancelModelDownload(jobId);
     *     // …and `report` arrives as {state: 'failed', error:
     *     //   {kind: 'download_cancelled'}}.
     *
     * The id is deliberately **not** also passed as a second argument, and
     * this function deliberately does **not** return a `stop()` handle the
     * way `watchRecordingLevel` does. That one is fire-and-forget, so a
     * bare function is the whole of its contract; this one resolves with a
     * result the caller awaits, so a handle would have to be a second,
     * different shape for the same idea. One way in, and it is the payload.
     *
     * What this does not give you is a way to stop *polling* early — the
     * loop runs until the job is terminal. A caller that can be torn down
     * mid-download (`dictation.js`) still drives start/poll by hand for
     * that reason, not for want of a job id.
     *
     * @param {string} [size]
     * @param {function} [onProgress] called with each running poll payload.
     * @returns {Promise<object>} the terminal poll payload.
     */
    api.downloadSttModel = async function(size, onProgress) {
        const started = await api.startModelDownload(size);
        for (;;) {
            const report = await api.pollModelDownload(started.job_id);
            if (report.state !== 'running') return report;
            if (typeof onProgress === 'function') onProgress(report);
            await new Promise(resolve => setTimeout(resolve, POLL_MS));
        }
    };

    /**
     * The four stored settings, plus what can be chosen.
     *
     * Two are user-level and travel in a `.wimi`; two name this machine's
     * hardware and its `app_data/` and do not. The page sees one flat
     * object — the split is a storage and travel property, not something a
     * settings screen has any reason to model.
     *
     * @returns {Promise<object>} `{stt_priming_enabled,
     *     stt_show_first_use_notice, stt_model_size, stt_input_device_id,
     *     resolved_model_size, default_model_size, available_models}`.
     *     `available_models[].installed` is read from the filesystem, which
     *     is the only record that a model is there.
     */
    api.getSttSettings = async function() {
        return api._callBridge('getSttSettings');
    };

    /**
     * Write any of the four settings. An unknown key is refused by name.
     *
     * @param {object} settings any of `stt_priming_enabled`,
     *     `stt_show_first_use_notice`, `stt_model_size`,
     *     `stt_input_device_id`.
     * @returns {Promise<object>} the same shape as `getSttSettings`.
     */
    api.updateSttSettings = async function(settings) {
        return api._callBridge('updateSttSettings', JSON.stringify(settings || {}));
    };

})(window._wimiApi);
