/**
 * WIMI API — Folder Sync (#123)
 *
 * The student picks a folder inside whatever cloud client they already
 * run; WIMI writes sealed, generation-named archives into it and reads
 * them back. No provider APIs, no OAuth, no credentials.
 *
 * Two shapes of call, and the difference matters:
 *
 *  - `getFolderSyncLink` and `getFolderSyncProviders` read a small local
 *    file and a static table. They answer immediately.
 *  - Everything that touches the sync folder is a **job**: start it, then
 *    poll. `runFolderSyncJob` below wraps that so callers rarely poll by
 *    hand. Reading the folder can block for as long as the hydration
 *    timeout, and on Box that is the ordinary case rather than the rare
 *    one, so it cannot happen on the UI thread.
 *
 * There is deliberately **no** `setCloudSyncEnabled`. The link *is* the
 * state (settled 2026-09-21): `getFolderSyncLink().linked` is what the
 * "Enable Cloud Sync" checkbox shows, and linking or unlinking is what
 * ticking it does. Storing a separate boolean would be a second answer
 * to the same question, free to disagree — and the column it would have
 * used travels inside a `.wimi`, so it would arrive on another machine
 * claiming to sync with no folder linked there.
 */
(function(api) {
    'use strict';

    /** How often to ask a running job whether it has finished. */
    var POLL_MS = 250;

    /**
     * Cloud clients WIMI knows the quirks of, as data.
     *
     * `pin_setting_label` is the useful one: telling a student to turn
     * on "Always keep on this device" is the single most valuable
     * sentence the panel says, and every client names it differently.
     *
     * @returns {Promise<Array<object>>} {id, name, pin_setting_label,
     *     streaming_by_default, scheduled_eviction, default_folders,
     *     caveats}.
     */
    api.getFolderSyncProviders = async function() {
        return api._callBridge('getFolderSyncProviders');
    };

    /**
     * Whether this profile is linked to a folder on **this** machine.
     *
     * This is the checkbox's state. Cheap — reads one small JSON file on
     * local disk — so callers may refresh it freely.
     *
     * @returns {Promise<object>} `{linked: false}`, or `{linked: true,
     *     folder, provider_id, provider_name, pin_hint, sync_id,
     *     last_seen_generation, last_seen_at, last_pushed_generation,
     *     last_pushed_at}`.
     */
    api.getFolderSyncLink = async function() {
        return api._callBridge('getFolderSyncLink');
    };

    /**
     * Stop syncing this profile on this machine.
     *
     * **Nothing in the folder is touched.** The archives are the
     * student's, and an unlink that deleted them would make unticking a
     * checkbox destructive.
     *
     * @returns {Promise<object>} `{linked: false}`.
     */
    api.unlinkFolderSync = async function() {
        return api._callBridge('unlinkFolderSync');
    };

    /**
     * Native directory picker for the cloud-synced folder.
     *
     * @returns {Promise<object|null>} `{folder}`, or null if cancelled.
     */
    api.pickFolderSyncFolder = async function() {
        return api._callBridge('pickFolderSyncFolder');
    };

    /**
     * Begin a folder operation on a worker thread.
     *
     * Prefer `runFolderSyncJob`, which polls for you.
     *
     * @param {object} params `{kind}` — one of `status`, `push`,
     *     `fetch`, `link`, `discover` — plus `folder` and `provider_id`
     *     for `link` and `discover`.
     * @returns {Promise<object>} `{job_id}`.
     */
    api.startFolderSyncJob = async function(params) {
        return api._callBridge('startFolderSyncJob', JSON.stringify(params || {}));
    };

    /**
     * Where a job has got to.
     *
     * @param {string} jobId
     * @returns {Promise<object>} `{state: 'running'}`, or
     *     `{state: 'done', kind, result}`, or `{state: 'failed', error}`.
     */
    api.pollFolderSyncJob = async function(jobId) {
        return api._callBridge('pollFolderSyncJob', String(jobId));
    };

    /**
     * Run a folder operation and resolve with its result.
     *
     * Rejects with the job's own error text on failure, so callers can
     * treat it like any other api call. `onProgress` is invoked once per
     * poll while the job is still running, which is all the progress
     * that honestly exists — the cloud client does not tell us how far
     * along it is, and neither do we.
     *
     * @param {object} params as for `startFolderSyncJob`.
     * @param {function} [onProgress] called with no arguments per poll.
     * @returns {Promise<*>} the job's result.
     */
    api.runFolderSyncJob = async function(params, onProgress) {
        const started = await api.startFolderSyncJob(params);
        const jobId = started.job_id;
        for (;;) {
            const report = await api.pollFolderSyncJob(jobId);
            if (report.state === 'done') return report.result;
            if (report.state === 'failed') throw new Error(report.error);
            if (typeof onProgress === 'function') onProgress();
            await new Promise(resolve => setTimeout(resolve, POLL_MS));
        }
    };

    /** Look at the folder: head generation, forks, conflict copies, problems. */
    api.getFolderSyncStatus = async function(onProgress) {
        return api.runFolderSyncJob({kind: 'status'}, onProgress);
    };

    /** Seal this profile's current state and publish it as the next generation. */
    api.pushFolderSync = async function(onProgress) {
        return api.runFolderSyncJob({kind: 'push'}, onProgress);
    };

    /**
     * Stage the highest verified generation. **Nothing is installed.**
     *
     * Choosing between "install as new" and "replace" is fork
     * resolution, which is #124.
     */
    api.fetchFolderSync = async function(onProgress) {
        return api.runFolderSyncJob({kind: 'fetch'}, onProgress);
    };

    /** Point this profile at a folder. */
    api.linkFolderSync = async function(folder, providerId, onProgress) {
        return api.runFolderSyncJob(
            {kind: 'link', folder: folder, provider_id: providerId || 'generic'},
            onProgress);
    };

    /**
     * What profiles already live in a folder, and which this machine holds.
     *
     * `local_profiles` is how the panel can say "this folder already
     * holds a profile you have" instead of asking the student to take it
     * on faith.
     */
    api.discoverFolderSync = async function(folder, providerId, onProgress) {
        return api.runFolderSyncJob(
            {kind: 'discover', folder: folder, provider_id: providerId || 'generic'},
            onProgress);
    };

    /**
     * Look for a fork, and if there is one, compare its two sides.
     *
     * Resolves to `null` when there is no fork — the ordinary case. A
     * report with `compared: false` is NOT the same thing: it means a fork
     * was found but a side could not be read, so the empty
     * `subjects_only_here` lists mean *nobody looked* rather than *the two
     * agree*. Render those differently or the panel tells a comforting lie.
     *
     * This downloads both sides on a streaming client. Deliberate: you
     * cannot honestly choose between two copies without reading them.
     *
     * @returns {Promise<object|null>} `{parent_generation, compared, sides,
     *     notes}`, each side carrying entries, date ranges, device, and the
     *     subjects unique to it.
     */
    api.getFolderSyncForkReport = async function(onProgress, parentGeneration) {
        return api.runFolderSyncJob(
            {kind: 'fork_report', parent_generation: parentGeneration},
            onProgress);
    };

    /**
     * Apply the student's choice to a fork.
     *
     * A verified export of this device's copy is taken first, always, on
     * every path — and a failed export aborts rather than warning.
     *
     * The side is named by **blob name**, not a generation number: the two
     * sides of a fork usually share a generation, so a number cannot say
     * which one was chosen.
     *
     * `keep_remote` on the profile in use closes it, replaces it and
     * opens it again (#148). The page is then showing a database that no
     * longer exists, so a caller must reload when `replaced_local` is true.
     *
     * **Nothing is sent to the folder.** The choice takes effect on this
     * computer at once and is remembered as pending; the other computer
     * learns of it only when the student sends (`pushFolderSync`). The
     * result says whether a send is needed at all -- taking the folder's
     * only copy needs none.
     *
     * @param {string} choice `keep_both`, `keep_local` or `keep_remote`.
     * @param {string} blobName the chosen side, from the report.
     * @returns {Promise<object>} `{choice, safety_export, set_aside_path,
     *     installed_user_id, replaced_local,
     *     installed_profile_must_not_sync, notes, send_needed, pending}`.
     */
    api.resolveFolderSyncFork = async function(choice, blobName, onProgress) {
        return api.runFolderSyncJob(
            {kind: 'resolve', choice: choice, blob_name: blobName}, onProgress);
    };

    /**
     * A computer's first copy of a profile, from the folder (#151).
     *
     * Needs no profile open -- the profile picker calls it. Installs the
     * newest verified copy, records it as the profile's base (so its first
     * send builds on it, #149), and links the profile to this folder.
     * Rejects with "already on this computer" for a profile that is here
     * already: a second copy sharing an id must never be linked.
     *
     * @returns {Promise<object>} `{user_id, username, profile_uuid,
     *     generation, linked, link_error, folder}`. `linked: false` means
     *     it was installed but not linked, and `link_error` says why.
     */
    api.installFromSyncFolder = async function(folder, syncId, providerId, onProgress) {
        return api.runFolderSyncJob(
            {kind: 'install', folder: folder, sync_id: syncId,
             provider_id: providerId || 'generic'},
            onProgress);
    };

    /**
     * The once-per-launch look behind the dashboard's sync notice (#148).
     *
     * The bridge keeps the "once": the dashboard reloads on every
     * navigation, so the page cannot be trusted to. Resolves to the status
     * result, or `null` when the look was skipped (already done this
     * launch, or the profile is not linked).
     */
    api.runFolderSyncStartupCheck = async function(onProgress) {
        const started = await api._callBridge('startFolderSyncStartupCheck');
        if (!started || !started.job_id) return null;
        for (;;) {
            const report = await api.pollFolderSyncJob(started.job_id);
            if (report.state === 'done') return report.result;
            if (report.state === 'failed') throw new Error(report.error);
            if (typeof onProgress === 'function') onProgress();
            await new Promise(resolve => setTimeout(resolve, POLL_MS));
        }
    };

})(window._wimiApi = window._wimiApi || {});
