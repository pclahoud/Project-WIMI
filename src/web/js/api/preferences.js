/**
 * WIMI API — User Preferences Operations
 */
(function(api) {
    'use strict';

    api.getUserPreferences = async function() {
        return api._callBridge('getUserPreferences');
    };

    api.updateUserPreferences = async function(preferences) {
        return api._callBridge('updateUserPreferences', JSON.stringify(preferences));
    };

})(window._wimiApi);
