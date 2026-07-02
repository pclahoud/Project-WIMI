/**
 * WIMI API — Review Session Operations
 */
(function(api) {
    'use strict';

    api.createReviewSession = async function(sessionData) {
        return api._callBridge('createReviewSession', JSON.stringify(sessionData));
    };

    api.getReviewSessions = async function(examContextId, includeComplete) {
        if (includeComplete === undefined) includeComplete = true;
        return api._callBridge('getReviewSessions', examContextId, includeComplete);
    };

    api.getReviewSession = async function(sessionId) {
        return api._callBridge('getReviewSession', sessionId);
    };

    api.updateReviewSession = async function(sessionId, updates) {
        return api._callBridge('updateReviewSession', sessionId, JSON.stringify(updates));
    };

    api.pauseSessionTimer = async function(sessionId) {
        return api._callBridge('pauseSessionTimer', sessionId);
    };

    api.unpauseSessionTimer = async function(sessionId) {
        return api._callBridge('unpauseSessionTimer', sessionId);
    };

    api.deleteReviewSession = async function(sessionId) {
        return api._callBridge('deleteReviewSession', sessionId);
    };

})(window._wimiApi);
