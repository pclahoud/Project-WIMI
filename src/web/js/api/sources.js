/**
 * WIMI API — Question Source Operations
 */
(function(api) {
    'use strict';

    api.createQuestionSource = async function(sourceData) {
        return api._callBridge('createQuestionSource', JSON.stringify(sourceData));
    };

    api.getQuestionSources = async function(examContext) {
        return api._callBridge('getQuestionSources', examContext || '');
    };

    api.updateQuestionSource = async function(sourceId, updates) {
        return api._callBridge('updateQuestionSource', sourceId, JSON.stringify(updates));
    };

    api.deleteQuestionSource = async function(sourceId) {
        return api._callBridge('deleteQuestionSource', sourceId);
    };

})(window._wimiApi);
