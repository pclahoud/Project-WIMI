/**
 * WIMI API — Tag Operations
 */
(function(api) {
    'use strict';

    api.getTagHierarchy = async function(examContext) {
        return api._callBridge('getTagHierarchy', examContext);
    };

    api.seedDefaultTags = async function(examContext) {
        return api._callBridge('seedDefaultTags', examContext);
    };

    // QWebChannel dispatches by arity — ALWAYS pass all 4 args so
    // 3-arg call sites resolve to the same @pyqtSlot(str, str, int, str).
    api.createTagInGroup = async function(examContext, tagName, groupId, description = '') {
        return api._callBridge('createTagInGroup', examContext, tagName, groupId, description || '');
    };

    api.deleteTag = async function(tagId) {
        return api._callBridge('deleteTag', tagId);
    };

    api.updateTagDescription = async function(tagId, description) {
        return api._callBridge('updateTagDescription', tagId, description || '');
    };

})(window._wimiApi);
