/**
 * WIMI API — Profile Management Operations
 */
(function(api) {
    'use strict';

    api.listProfiles = async function() {
        return api._callBridge('listProfiles');
    };

    api.createProfile = async function(payload) {
        return api._callBridge('createProfile', JSON.stringify(payload));
    };

    api.renameProfile = async function(userId, displayName) {
        return api._callBridge('renameProfile', userId, displayName);
    };

    api.deleteProfile = async function(userId) {
        return api._callBridge('deleteProfile', userId);
    };

    api.restoreProfile = async function(userId) {
        return api._callBridge('restoreProfile', userId);
    };

    api.selectProfile = async function(userId) {
        return api._callBridge('selectProfile', userId);
    };

    api.getCurrentProfile = async function() {
        return api._callBridge('getCurrentProfile');
    };

    api.getProfileStartupPrefs = async function() {
        return api._callBridge('getProfileStartupPrefs');
    };

    api.setProfileStartupPrefs = async function(payload) {
        return api._callBridge('setProfileStartupPrefs', JSON.stringify(payload));
    };

})(window._wimiApi);
