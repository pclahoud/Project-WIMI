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

    // First-run tour (#430). The tour's state is not a preference field:
    // Settings' bulk save must never rewrite which steps were shown.
    api.getTourState = async function() {
        return api._callBridge('getTourState');
    };

    api.markTourStepsSeen = async function(keys) {
        return api._callBridge('markTourStepsSeen', JSON.stringify(keys));
    };

    api.resetTour = async function() {
        return api._callBridge('resetTour');
    };

    api.setTourAutoStartForTest = async function(enabled) {
        return api._callBridge('setTourAutoStartForTest', !!enabled);
    };

})(window._wimiApi);
