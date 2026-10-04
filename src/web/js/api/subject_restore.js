/**
 * WIMI API — the delete journal's read side (issue #37).
 *
 * `kind` is `'subject'` or `'dimension'` and is **passed, not inferred**: a
 * batch id identifies either a subject delete or a whole dimension archive,
 * and `getArchivedBatches` labels every entry precisely so callers can hand
 * the label back. Guessing would be wrong in the one case that matters — a
 * subject batch owned by a dimension archive exists in both relations.
 *
 * `restoreBatch` **throws** on a refusal, because `_callBridge` rejects on
 * `success: false`. Those refusals are sentences a student can act on (the
 * name is taken, restore the parent first, nothing left to restore), so show
 * `error.message` verbatim rather than a generic failure string.
 */
(function(api) {
    'use strict';

    // `examContextId` may be omitted or 0 for "every exam" — an exam id is
    // always positive, and QWebChannel has no natural null for an int.
    api.getArchivedBatches = async function(examContextId) {
        return api._callBridge('getArchivedBatches', examContextId || 0);
    };

    api.previewRestoreBatch = async function(batchId, kind) {
        return api._callBridge('previewRestoreBatch', batchId, kind);
    };

    api.restoreBatch = async function(batchId, kind) {
        return api._callBridge('restoreBatch', batchId, kind);
    };

})(window._wimiApi);
