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

    api.createTagInGroup = async function(examContext, tagName, groupId) {
        return api._callBridge('createTagInGroup', examContext, tagName, groupId);
    };

})(window._wimiApi);
