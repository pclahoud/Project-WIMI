/**
 * WIMI API — Anki (#784)
 *
 * Mirrors AnkiBridgeMixin. Two kinds of call, as in the bridge:
 *
 * - Reads and writes of WIMI's own rows answer at once: templates, field
 *   visibility, and getAnkiEntryStats, which reads only the cache and is safe
 *   to call on page load.
 * - Anything that talks to Anki is a job: start it, then poll. runAnkiJob
 *   does the polling, so callers rarely poll by hand. A job that fails
 *   rejects with an Error whose `kind` is the bridge's AnkiErrorKind
 *   ('unavailable', 'action_failed', 'profile_changed', ...) and whose
 *   `retryable` says whether offering a retry is honest.
 *
 * There is deliberately no way to send Anki an arbitrary action.
 */
(function(api) {
    'use strict';

    /** How often to ask a running job whether it has finished. */
    var POLL_MS = 250;

    api.getAnkiStatus = async function() {
        return api._callBridge('getAnkiStatus');
    };

    /** @param {number} [examContextId] 0 or omitted for every exam. */
    api.getAnkiTemplates = async function(examContextId) {
        return api._callBridge('getAnkiTemplates', examContextId || 0);
    };

    api.addAnkiTemplate = async function(examContextId, questionSourceId, template) {
        return api._callBridge('addAnkiTemplate', examContextId, questionSourceId, template);
    };

    api.updateAnkiTemplate = async function(templateId, template) {
        return api._callBridge('updateAnkiTemplate', templateId, template);
    };

    api.removeAnkiTemplate = async function(templateId) {
        return api._callBridge('removeAnkiTemplate', templateId);
    };

    /** @returns {Promise<object>} `{note_types: [{model_name, fields: [{name, visible}]}]}` */
    api.getAnkiFieldSettings = async function() {
        return api._callBridge('getAnkiFieldSettings');
    };

    api.setAnkiFieldVisibility = async function(modelName, fieldName, visible) {
        return api._callBridge('setAnkiFieldVisibility', modelName, fieldName, !!visible);
    };

    /**
     * The cached stats for one entry. Never talks to Anki.
     *
     * @returns {Promise<object>} `{enabled, display_mode, matchable, reason?,
     *     has_templates, synced, last_synced_at, stale, cards: [...]}`.
     *     `last_synced_at` is a UTC instant ending in Z.
     */
    api.getAnkiEntryStats = async function(entryId) {
        return api._callBridge('getAnkiEntryStats', entryId);
    };

    api.startAnkiJob = async function(kind, params) {
        return api._callBridge('startAnkiJob', kind, JSON.stringify(params || {}));
    };

    api.pollAnkiJob = async function(jobId) {
        return api._callBridge('pollAnkiJob', jobId);
    };

    /**
     * Start a job and poll it to the end.
     *
     * @param {string} kind ping | refresh_entry | sync_exam | suspend |
     *     unsuspend | save_image | view_image
     * @param {object} [params]
     * @param {function} [onProgress] called once per poll while running.
     * @returns {Promise<*>} the job's result.
     */
    api.runAnkiJob = async function(kind, params, onProgress) {
        var started = await api.startAnkiJob(kind, params);
        for (;;) {
            var report = await api.pollAnkiJob(started.job_id);
            if (report.state === 'done') return report.result;
            if (report.state === 'failed') {
                var err = report.error || {};
                var e = new Error(err.detail || err.kind || 'Anki job failed');
                e.kind = err.kind;
                e.retryable = !!err.retryable;
                throw e;
            }
            if (typeof onProgress === 'function') onProgress();
            await new Promise(function(resolve) { setTimeout(resolve, POLL_MS); });
        }
    };

    /** AnkiConnect's version on this device's port, or an explicit one. */
    api.pingAnki = async function(port) {
        return api.runAnkiJob('ping', port ? {port: port} : {});
    };

    api.refreshAnkiEntry = async function(entryId, onProgress) {
        return api.runAnkiJob('refresh_entry', {entry_id: entryId}, onProgress);
    };

    api.syncAnkiExam = async function(examContextId, onProgress) {
        return api.runAnkiJob('sync_exam', {exam_context_id: examContextId}, onProgress);
    };

    api.setAnkiCardsSuspended = async function(entryId, cardIds, suspended) {
        return api.runAnkiJob(suspended ? 'suspend' : 'unsuspend',
            {entry_id: entryId, card_ids: cardIds});
    };

    api.saveAnkiImageToEntry = async function(entryId, filename) {
        return api.runAnkiJob('save_image', {entry_id: entryId, filename: filename});
    };

    /** Record the student's answer about one proposed card (#784 Wave 5):
     *  'confirmed', 'not_for_entry' or 'clear'. Resolves to the entry payload. */
    api.setAnkiCardVerdict = async function(entryId, cardId, verdict) {
        return api._callBridge('setAnkiCardVerdict', entryId, cardId, verdict);
    };

    /** Never propose this card again for the subjects that proposed it. */
    api.rejectAnkiCardForSubjects = async function(entryId, cardId) {
        return api._callBridge('rejectAnkiCardForSubjects', entryId, cardId);
    };

    /** One of this entry's card images as {filename, data_url}, for viewing. */
    api.viewAnkiImage = async function(entryId, filename) {
        return api.runAnkiJob('view_image', {entry_id: entryId, filename: filename});
    };

})(window._wimiApi);
