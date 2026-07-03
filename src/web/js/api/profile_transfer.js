/**
 * WIMI API — Profile Transfer Operations (.wimi export/import)
 */
(function(api) {
    'use strict';

    api.openProfileExportDialog = async function(params) {
        return api._callBridge('openProfileExportDialog', JSON.stringify(params || {}));
    };

    api.exportProfile = async function(params) {
        return api._callBridge('exportProfile', JSON.stringify(params));
    };

    api.openProfileImportDialog = async function() {
        return api._callBridge('openProfileImportDialog');
    };

    api.readProfileArchive = async function(filePath) {
        return api._callBridge('readProfileArchive', filePath);
    };

    api.executeProfileImport = async function(params) {
        return api._callBridge('executeProfileImport', JSON.stringify(params));
    };

})(window._wimiApi);
