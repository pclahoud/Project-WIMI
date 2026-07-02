/**
 * WIMI API — Media Operations
 */
(function(api) {
    'use strict';

    api.addQuestionMedia = async function(entryId, base64Data, filename, mimeType) {
        return api._callBridge('addQuestionMedia', entryId, base64Data, filename, mimeType);
    };

    api.getQuestionMedia = async function(entryId) {
        return api._callBridge('getQuestionMedia', entryId);
    };

    api.renameMedia = async function(mediaId, newName) {
        return api._callBridge('renameMedia', mediaId, newName);
    };

    api.deleteMedia = async function(entryId, mediaId) {
        return api._callBridge('deleteMedia', entryId, mediaId);
    };

    api.removeMediaFromEntry = async function(mediaId) {
        return api._callBridge('removeMediaFromEntry', mediaId);
    };

    api.reorderMedia = async function(entryId, mediaIds) {
        return api._callBridge('reorderMedia', entryId, JSON.stringify(mediaIds));
    };

    api.attachMediaToEntry = async function(mediaId, entryId) {
        return api._callBridge('attachMediaToEntry', mediaId, entryId);
    };

    api.attachExistingMediaToEntry = async function(mediaId, entryId) {
        return api._callBridge('attachExistingMediaToEntry', mediaId, entryId);
    };

    api.detachMediaFromEntry = async function(mediaId, entryId) {
        return api._callBridge('detachMediaFromEntry', mediaId, entryId);
    };

    api.searchMedia = async function(query, limit) {
        return api._callBridge('searchMedia', query, limit || 50);
    };

    api.getMediaBySubject = async function(subjectNodeId, limit, dimensionId) {
        return api._callBridge('getMediaBySubject', subjectNodeId, limit || 20, dimensionId || 0);
    };

    api.getMediaBySubjects = async function(subjectIds, excludeEntryId, limit, dimensionId) {
        return api._callBridge(
            'getMediaBySubjects',
            JSON.stringify(subjectIds || []),
            excludeEntryId || 0,
            limit || 20,
            dimensionId || 0
        );
    };

    api.updateMediaDimension = async function(mediaId, dimensionId) {
        return api._callBridge('updateMediaDimension', mediaId, dimensionId);
    };

    api.updateMediaLinkedSubjects = async function(mediaId, subjectIds) {
        return api._callBridge('updateMediaLinkedSubjects', mediaId, JSON.stringify(subjectIds || []));
    };

})(window._wimiApi);
