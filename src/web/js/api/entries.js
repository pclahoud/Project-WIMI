/**
 * WIMI API — Question Entry Operations
 */
(function(api) {
    'use strict';

    api.createQuestionEntry = async function(entryData) {
        return api._callBridge('createQuestionEntry', JSON.stringify(entryData));
    };

    api.getQuestionEntry = async function(entryId) {
        return api._callBridge('getQuestionEntry', entryId);
    };

    api.getSessionEntries = async function(sessionId) {
        return api._callBridge('getSessionEntries', sessionId);
    };

    api.getEntriesByQuestionId = async function(questionId, examContextId, excludeEntryId) {
        return api._callBridge('getEntriesByQuestionId', questionId, examContextId, excludeEntryId || -1);
    };

    api.updateQuestionEntry = async function(entryId, updates) {
        return api._callBridge('updateQuestionEntry', entryId, JSON.stringify(updates));
    };

    api.deleteQuestionEntry = async function(entryId) {
        return api._callBridge('deleteQuestionEntry', entryId);
    };

    api.searchSubjects = async function(examContextId, query, limit) {
        return api._callBridge('searchSubjects', examContextId, query, limit || 10);
    };

    api.getAllSubjectsForExam = async function(examContextId) {
        return api._callBridge('getAllSubjectsForExam', examContextId);
    };

    api.getAllSubjectsWithAliasesForExam = async function(examContextId) {
        return api._callBridge('getAllSubjectsWithAliasesForExam', examContextId);
    };

})(window._wimiApi);
