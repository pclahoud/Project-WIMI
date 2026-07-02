/**
 * WIMI API — Entry Browsing & Filtering Operations
 */
(function(api) {
    'use strict';

    api.getEntriesPaginated = async function(params) {
        return api._callBridge('getEntriesPaginated', JSON.stringify(params));
    };

    api.getEntryWithContext = async function(entryId) {
        return api._callBridge('getEntryWithContext', entryId);
    };

    api.getRelatedSubjects = async function(subjectId, examContextId, limit) {
        return api._callBridge('getRelatedSubjects', subjectId, examContextId, limit || 4);
    };

    api.searchEntriesFulltext = async function(query, examContextId, limit) {
        return api._callBridge('searchEntriesFulltext', query, examContextId, limit || 50);
    };

    api.getEntryStatistics = async function(examContextId) {
        return api._callBridge('getEntryStatistics', String(examContextId || ''));
    };

    api.getSessionsForFilter = async function(examContextId) {
        return api._callBridge('getSessionsForFilter', examContextId);
    };

    api.getSubjectsForFilter = async function(examContextId) {
        return api._callBridge('getSubjectsForFilter', examContextId);
    };

    api.getTagsForFilter = async function(examContextId) {
        return api._callBridge('getTagsForFilter', examContextId);
    };

})(window._wimiApi);
