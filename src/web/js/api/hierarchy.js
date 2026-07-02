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

    api.deleteSubjectNode = async function(nodeId) {
        return api._callBridge('deleteSubjectNode', nodeId);
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
