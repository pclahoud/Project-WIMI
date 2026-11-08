/**
 * WIMI API — Tag Operations
 *
 * Error types are one library per profile, and each exam lists the ones it
 * offers (#888). getTagHierarchy reads an exam's list; addTagToExam and
 * removeTagFromExam change it; deleteTag removes a type from the library.
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

    // Delete for good. With an exam name it resolves to deleteTag(int, str),
    // refused while any OTHER exam lists the type; without, to the pre-#888
    // deleteTag(int), refused while more than one exam lists it.
    api.deleteTag = async function(tagId, examContext) {
        if (examContext) {
            return api._callBridge('deleteTag', tagId, examContext);
        }
        return api._callBridge('deleteTag', tagId);
    };

    api.addTagToExam = async function(examContext, tagId) {
        return api._callBridge('addTagToExam', examContext, tagId);
    };

    api.removeTagFromExam = async function(examContext, tagId) {
        return api._callBridge('removeTagFromExam', examContext, tagId);
    };

    api.getTagsNotOnExam = async function(examContext) {
        return api._callBridge('getTagsNotOnExam', examContext);
    };

    api.updateTagDescription = async function(tagId, description) {
        return api._callBridge('updateTagDescription', tagId, description || '');
    };

})(window._wimiApi);
