/**
 * WIMI API — Subject Alias Operations
 */
(function(api) {
    'use strict';

    api.createSubjectAlias = async function(aliasData) {
        return api._callBridge('createSubjectAlias', JSON.stringify(aliasData));
    };

    api.getAliasesForSubject = async function(subjectNodeId) {
        return api._callBridge('getAliasesForSubject', subjectNodeId);
    };

    api.updateSubjectAlias = async function(updateData) {
        return api._callBridge('updateSubjectAlias', JSON.stringify(updateData));
    };

    api.deleteSubjectAlias = async function(aliasId) {
        return api._callBridge('deleteSubjectAlias', aliasId);
    };

    api.checkAliasConflicts = async function(examContext, aliasName, excludeSubjectId) {
        return api._callBridge('checkAliasConflicts', examContext, aliasName, excludeSubjectId || -1);
    };

    api.incrementAliasUsage = async function(aliasId) {
        return api._callBridge('incrementAliasUsage', aliasId);
    };

})(window._wimiApi);
