/**
 * WIMI API — Import/Export Operations
 */
(function(api) {
    'use strict';

    // Saved Delimiters
    api.getSavedDelimiters = async function() {
        return api._callBridge('getSavedDelimiters');
    };

    api.createSavedDelimiter = async function(data) {
        return api._callBridge('createSavedDelimiter', JSON.stringify(data));
    };

    api.deleteSavedDelimiter = async function(id) {
        return api._callBridge('deleteSavedDelimiter', id);
    };

    // Session Import
    api.openImportFileDialog = async function() {
        return api._callBridge('openImportFileDialog');
    };

    api.readImportJsonFile = async function(filePath) {
        return api._callBridge('readImportJsonFile', filePath);
    };

    api.executeSessionImport = async function(importConfig) {
        return api._callBridge('executeSessionImport', JSON.stringify(importConfig));
    };

    // Import Mapping Profiles
    api.getImportMappingProfiles = async function() {
        return api._callBridge('getImportMappingProfiles');
    };

    api.createImportMappingProfile = async function(profile) {
        return api._callBridge('createImportMappingProfile', JSON.stringify(profile));
    };

    api.updateImportMappingProfile = async function(profileId, profile) {
        return api._callBridge('updateImportMappingProfile', profileId, JSON.stringify(profile));
    };

    api.deleteImportMappingProfile = async function(profileId) {
        return api._callBridge('deleteImportMappingProfile', profileId);
    };

})(window._wimiApi);
