/**
 * WIMI API — proposing relations from the student's own explanation (#60).
 *
 * The companion to `relations.js`: that module writes relations the student
 * authored, this one asks a local model what their explanation already said
 * and offers each answer for endorsement.
 *
 * Three things about these wrappers are not obvious from their names.
 *
 * **An unavailable machine is a resolved promise, not a rejection.**
 * `api._callBridge` throws on `success=false`, and the owner's decision
 * (#380, #5179) is that the entry form shows *nothing at all* when
 * extraction cannot run — no disabled button, no notice. So
 * `proposeRelationsForEntry` resolves with `{available: false, state}` and a
 * caller that has drawn a button it should not have can go quiet instead of
 * raising a toast. The same goes for `{started: false, reason}`: an entry
 * with no explanation yet is an ordinary state.
 *
 * **Poll, do not await.** Extraction runs on a worker: 0.35–0.42 s for a
 * short explanation, 7.7 s for 16,200 characters, and the *first* pass of a
 * session also loads 845 MB of weights (about 16 s). `proposeRelationsForEntry`
 * returns a `job_id` immediately; `pollRelationProposals` is what finishes.
 *
 * **Read `wedged` before offering a retry.** A failed poll carries
 * `{kind, detail, retryable}`, and `retryable` is the taxonomy's own answer —
 * except after a wedge, where the bridge forces it false because every later
 * attempt fails identically until WIMI restarts. #174: a message may not
 * direct a press when nothing is pressable.
 */
(function(api) {
    'use strict';

    /**
     * Whether this copy of WIMI can extract relations, and what is missing.
     *
     * Five states, not one boolean, because three of them are actionable and
     * the actions differ: `not_in_this_build` (the other download exists),
     * `dev_runtime_missing` (a pip command), `model_not_downloaded` (the
     * button below). `runtime_broken` is a packaging bug and `ready` needs
     * nothing.
     *
     * Cheap by design — eight `stat` calls, never a hash — so a Settings
     * panel may call it on every open.
     *
     * @returns {Promise<{state: string, ready: boolean, actionable: boolean,
     *   missing: Array<string>,
     *   model: {installed: boolean, path: (string|null),
     *           missing_files: Array<string>, total_bytes: number,
     *           bytes_still_needed: number, total_mb: number},
     *   licence: {model: string, base: string, url: string, repo: string,
     *             revision: string},
     *   download: (Object|null)}>}
     *   `download` is the running transfer's poll payload, so a panel
     *   reopened mid-download finds the `job_id` it needs in order to poll
     *   and cancel. Null when nothing is running.
     */
    api.getRelationExtractionStatus = async function() {
        return api._callBridge('getRelationExtractionStatus');
    };

    /**
     * Fetch the pinned model: 845 MB across eight files, resumable.
     *
     * Takes no arguments — the pin table names one revision of one model, so
     * there is no size to choose. Pressing it twice does not start a second
     * transfer: the response carries the running job's id with
     * `already_running: true`.
     *
     * @returns {Promise<{job_id: string, already_running: boolean,
     *   total_bytes: number, bytes_still_needed: number,
     *   file_count: number}>}
     */
    api.startRelationModelDownload = async function() {
        return api._callBridge('startRelationModelDownload');
    };

    /**
     * Where a download has got to.
     *
     * `bytes` starts at what is already on disk rather than at zero, so a
     * resumed transfer does not crawl through ground it has covered. Both
     * `bytes` and `total` are always numbers — they come from the pin table,
     * not from a `Content-Length`.
     *
     * @param {string} jobId
     * @returns {Promise<{job_id: string, state: ('running'|'done'|'failed'),
     *   bytes: number, total: number, file: (string|null),
     *   file_index: number, file_count: number,
     *   installed?: Array<string>, skipped?: Array<string>,
     *   bytes_downloaded?: number,
     *   error?: {kind: string, detail: *, retryable: boolean}}>}
     */
    api.pollRelationModelDownload = async function(jobId) {
        return api._callBridge('pollRelationModelDownload', jobId);
    };

    /**
     * Stop a download, **keeping** what has been fetched.
     *
     * Deliberately unlike `cancelSttModelDownload`, which deletes its
     * partial file: 845 MB across eight files makes a cancel far more often
     * "not now" than "never", and refetching 800 MB to honour the stricter
     * reading costs the student more than it protects them. Use
     * `discardRelationModelDownload` for the explicit start-over.
     *
     * @param {string} jobId
     * @returns {Promise<{cancelled: boolean}>} whether there was anything to
     *   stop. Poll once more to see the job reach `failed` with
     *   `download_cancelled`.
     */
    api.cancelRelationModelDownload = async function(jobId) {
        return api._callBridge('cancelRelationModelDownload', jobId);
    };

    /**
     * Throw away partial files so the next download starts over.
     *
     * Installed files are not touched — those are at their pinned size and
     * deleting them is uninstalling, which is a different action. Refuses
     * while a download is running, reporting `{running: true}`.
     *
     * @returns {Promise<{discarded: Array<string>, running: boolean}>}
     */
    api.discardRelationModelDownload = async function() {
        return api._callBridge('discardRelationModelDownload');
    };

    /**
     * Ask the model what this entry's explanation relates.
     *
     * Started by a press, never automatically (owner's decision, #380): the
     * first pass of a session loads the model, which is about 16 s and a
     * 2–3 GB peak, and that should be attributable to something the student
     * did.
     *
     * `token` is opaque and comes back on every poll, unmodified. The
     * **caller** decides whether proposals are stale, and it can only do
     * that if what it sent comes back — pass a value that identifies the
     * entry and the attempt.
     *
     * @param {{entryId: number, token?: *}} params
     * @returns {Promise<{available: boolean, state: string,
     *   started: boolean, reason?: string, token?: *, job_id?: string,
     *   entry_id?: number, labels?: Array<string>,
     *   vocabulary_terms?: number}>}
     *   `available: false` means this machine cannot extract — render
     *   nothing. `started: false` with a `reason` of `no_explanation`,
     *   `no_relation_types` or `no_subjects` is an ordinary state, not an
     *   error: none of the three is worth a model pass.
     */
    api.proposeRelationsForEntry = async function(params) {
        params = params || {};
        return api._callBridge('proposeRelationsForEntry', JSON.stringify({
            entry_id: params.entryId,
            token: params.token === undefined ? null : params.token
        }));
    };

    /**
     * Where an extraction has got to, and its proposals once it lands.
     *
     * Each proposal is **already written** as an unconfirmed relation
     * (#5494): `origin='extracted'`, the passage as its reason,
     * `confirmed_at` null, and invisible on the deep dive until the student
     * endorses it with `acceptRelationProposal`. So `relation_id` is a real
     * row, not a placeholder.
     *
     * `unmatched` and `ambiguous` are reported rather than dropped, because
     * "the model found a relation between two things, one of which is not in
     * your tree" is a different fact from "the model found nothing".
     *
     * @param {string} jobId
     * @returns {Promise<{job_id: string,
     *   state: ('running'|'done'|'cancelled'|'failed'),
     *   entry_id: (number|null), token: *,
     *   proposals?: Array<{relation_id: number, from_subject_id: number,
     *     to_subject_id: number, from_subject_name: string,
     *     to_subject_name: string, label: string, score: number,
     *     passage: string}>,
     *   refused?: Array<Object>, unmatched?: Array<Object>,
     *   ambiguous?: Array<Object>, counts?: Object,
     *   ms?: number, load_ms?: number,
     *   error?: {kind: string, detail: *, retryable: boolean},
     *   wedged?: boolean}>}
     *   **Check `wedged` before drawing a retry.** It means the worker is
     *   held by a call that never returned; every later attempt fails the
     *   same way until WIMI restarts, so `retryable` is forced false and the
     *   honest copy names the restart.
     */
    api.pollRelationProposals = async function(jobId) {
        return api._callBridge('pollRelationProposals', jobId);
    };

    /**
     * Ask a pass to stop. It stops before the next chunk of text.
     *
     * What cannot be stopped is a first model load, which is one call into
     * the library: that job reports `cancelled` when the load returns, and
     * the loaded model is kept for the next one.
     *
     * @param {string} jobId
     * @returns {Promise<{cancelled: boolean}>} whether there was anything to
     *   stop. A finished pass is left alone — its result exists, and
     *   discarding it would throw away work the student waited for.
     */
    api.cancelRelationExtraction = async function(jobId) {
        return api._callBridge('cancelRelationExtraction', jobId);
    };

    /**
     * Endorse a proposal, which is what makes the relation visible.
     *
     * The reason arrives prefilled with the passage and is editable; a blank
     * one is refused, because #14's decision 2 makes the sentence mandatory
     * and there is no explain-later state.
     *
     * Pass `changeType: true` to set the type, **including** setting it to
     * null for an untyped relation. Without the flag this call cannot tell
     * "leave the type alone" from "make it untyped", and one of those
     * silently retypes a relation the student did not retype. Retyping is
     * worth having: of 31 rejections in #60's adjudication, 11 were *right
     * pair, wrong type*, which is fixed by choosing the right one rather
     * than rejecting a true pair.
     *
     * @param {{relationId: number, reason?: string,
     *          relationTypeId?: (number|null),
     *          changeType?: boolean}} params
     * @returns {Promise<Object>} the confirmed row. Rejects with the database
     *   layer's own sentence when refused — a blank reason, a retired type,
     *   or a retype onto a pair that already carries that type. Show it.
     */
    api.acceptRelationProposal = async function(params) {
        params = params || {};
        return api._callBridge('acceptRelationProposal', JSON.stringify({
            relation_id: params.relationId,
            reason: params.reason === undefined ? null : params.reason,
            relation_type_id: params.relationTypeId === undefined
                ? null : params.relationTypeId,
            change_type: !!params.changeType
        }));
    };

    /**
     * Reject a proposal, recording **which kind** of rejection it was.
     *
     * `kind` is required and has no default, because the kind decides the
     * scope and guessing is how the mechanism this replaces behaved:
     *
     * - `'misread'` — the extractor read this sentence wrongly. Suppressed
     *   for **this entry only**; the same pair may extract perfectly from a
     *   different explanation tomorrow. This was **25 of 45** rejections in
     *   #60's adjudication, which is why it is the common case rather than
     *   the exception.
     * - `'not_related'` — the two subjects are not related at all.
     *   Suppressed **everywhere**, because it is a claim about the subjects
     *   rather than about one piece of text.
     *
     * Also removes the unconfirmed row, in one transaction with the
     * rejection: leaving it would keep the pair both suppressed and
     * unwritable by hand.
     *
     * A pair may be rejected with no proposal in front of the student — pass
     * `fromSubjectId` and `toSubjectId` instead of `relationId`. A
     * `'misread'` then needs `sourceEntryId`, since it is a statement about
     * a particular text.
     *
     * @param {{kind: ('misread'|'not_related'), relationId?: number,
     *          fromSubjectId?: number, toSubjectId?: number,
     *          relationTypeId?: (number|null), sourceEntryId?: number,
     *          passage?: string}} params
     * @returns {Promise<{rejection: Object, deleted: boolean}>}
     */
    api.rejectRelationProposal = async function(params) {
        params = params || {};
        return api._callBridge('rejectRelationProposal', JSON.stringify({
            kind: params.kind,
            relation_id: params.relationId || null,
            from_subject_id: params.fromSubjectId || null,
            to_subject_id: params.toSubjectId || null,
            relation_type_id: params.relationTypeId === undefined
                ? null : params.relationTypeId,
            source_entry_id: params.sourceEntryId || null,
            passage: params.passage === undefined ? null : params.passage
        }));
    };

})(window._wimiApi);
