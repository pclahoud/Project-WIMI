/**
 * WIMI API — Polyhierarchy Edge Operations
 *
 * Wraps the bridge slots from EdgesBridgeMixin (and the
 * setPrimaryParentForEntry slot from EntryBridgeMixin). See
 * docs/planning/POLYHIERARCHY_MIGRATION.md §6 for the slot specs.
 */
(function(api) {
    'use strict';

    api.addParent = async function(childId, parentId, isPrimary) {
        return api._callBridge('addParent', childId, parentId, !!isPrimary);
    };

    api.removeParent = async function(edgeId) {
        return api._callBridge('removeParent', edgeId);
    };

    api.setPrimaryParent = async function(childId, parentId) {
        return api._callBridge('setPrimaryParent', childId, parentId);
    };

    api.getParents = async function(childId) {
        return api._callBridge('getParents', childId);
    };

    api.getPathsToRoot = async function(childId) {
        return api._callBridge('getPathsToRoot', childId);
    };

    api.setPrimaryParentForEntry = async function(entryId, subjectNodeId, primaryParentId) {
        // null/undefined => clears the context (SET NULL on the DB side).
        var pp = (primaryParentId === undefined || primaryParentId === null)
            ? null
            : primaryParentId;
        return api._callBridge('setPrimaryParentForEntry', entryId, subjectNodeId, pp);
    };

})(window._wimiApi);
