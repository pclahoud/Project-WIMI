/**
 * WIMI API — Subject Hierarchy Operations
 */
(function(api) {
    'use strict';

    api.getSubjectHierarchy = async function(examContextId) {
        return api._callBridge('getSubjectHierarchy', examContextId);
    };

    api.createSubjectNode = async function(nodeData) {
        return api._callBridge('createSubjectNode', JSON.stringify(nodeData));
    };

    api.updateSubjectNode = async function(nodeId, updates) {
        return api._callBridge('updateSubjectNode', nodeId, JSON.stringify(updates));
    };

    /**
     * What deleting this subject would do, without doing it. Safe to call
     * when the confirmation modal opens (issue #15, decision 5).
     */
    api.getSubjectDeletePreview = async function(nodeId) {
        return api._callBridge('getSubjectDeletePreview', nodeId);
    };

    /**
     * Soft-delete a subject.
     *
     * `promoteChildren` is issue #15's decision 2: one global choice that
     * keeps the subject's direct children and moves them to the top level
     * instead of deleting them. Omitting it calls the original
     * single-argument slot, which is what import_export.js's replace-mode
     * import still does — both arities are registered on the bridge and
     * QWebChannel resolves by argument count, so the one-argument form is
     * not a shim, it is the same slot.
     */
    api.deleteSubjectNode = async function(nodeId, promoteChildren) {
        if (promoteChildren === undefined) {
            return api._callBridge('deleteSubjectNode', nodeId);
        }
        return api._callBridge('deleteSubjectNode', nodeId, !!promoteChildren);
    };

    /**
     * Read the subject array out of a parsed import file (issue #61).
     *
     * Two spellings are in the wild: `root_nodes`, which
     * `exportSubjectHierarchy` writes and which stays canonical, and
     * `subjects`, which the published import spec documents. Both
     * import entry points — the tree editor's file input and the
     * import/export panel — read the file through this one helper so
     * neither has to know about the alias, and `importSubjectHierarchy`
     * accepts both keys on the Python side.
     *
     * @param {Object} data Parsed import file.
     * @returns {{nodes: *, key: (string|null)}} `key` names the key the
     *   file actually used, or null when neither is present. `nodes` is
     *   whatever was under it — callers still check `Array.isArray`, so
     *   "missing" and "not an array" stay distinguishable in errors.
     */
    api.getImportRootNodes = function(data) {
        if (!data || typeof data !== 'object') {
            return { nodes: undefined, key: null };
        }
        if (Array.isArray(data.root_nodes)) {
            return { nodes: data.root_nodes, key: 'root_nodes' };
        }
        if (Array.isArray(data.subjects)) {
            return { nodes: data.subjects, key: 'subjects' };
        }
        if ('root_nodes' in data) {
            return { nodes: data.root_nodes, key: 'root_nodes' };
        }
        if ('subjects' in data) {
            return { nodes: data.subjects, key: 'subjects' };
        }
        return { nodes: undefined, key: null };
    };

    /**
     * What importing this file would do, without doing any of it (#67).
     *
     * Import is a merge, and a merge can remove subjects, so the counts
     * come back before anything is written. The same planner produces
     * this and the result of `importSubjectHierarchy`, so the preview
     * cannot promise something the import does not do.
     *
     * @param {number} examContextId Exam to import into.
     * @param {string} hierarchyJson The file, verbatim.
     * @returns {Promise<Object>} counts, capped sample lists, and the
     *   `kept_in_use` subjects whose entries the student may want to
     *   re-tag.
     */
    api.previewSubjectHierarchyImport = async function(examContextId, hierarchyJson) {
        return api._callBridge(
            'previewSubjectHierarchyImport', examContextId, hierarchyJson
        );
    };

    api.importSubjectHierarchy = async function(examContextId, hierarchyJson) {
        return api._callBridge('importSubjectHierarchy', examContextId, hierarchyJson);
    };

    api.exportSubjectHierarchy = async function(examContextId) {
        return api._callBridge('exportSubjectHierarchy', examContextId);
    };

    api.getHierarchyLevels = async function(examContextId) {
        return api._callBridge('getHierarchyLevels', examContextId);
    };

    api.addCustomHierarchyLevel = async function(examContextId, levelName, displayNameTemplate) {
        return api._callBridge(
            'addCustomHierarchyLevel',
            examContextId,
            levelName || '',
            displayNameTemplate || ''
        );
    };

})(window._wimiApi);
