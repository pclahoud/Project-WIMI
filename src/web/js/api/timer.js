/**
 * WIMI API — Timer Round Operations
 */
(function(api) {
    'use strict';

    api.createTimerRound = async function(sessionId, durationMinutes) {
        return api._callBridge('createTimerRound', sessionId, durationMinutes);
    };

    api.getActiveTimerRound = async function(sessionId) {
        return api._callBridge('getActiveTimerRound', sessionId);
    };

    api.getTimerRounds = async function(sessionId) {
        return api._callBridge('getTimerRounds', sessionId);
    };

    api.endTimerRound = async function(roundId) {
        return api._callBridge('endTimerRound', roundId);
    };

    api.pauseRoundTimer = async function(roundId) {
        return api._callBridge('pauseRoundTimer', roundId);
    };

    api.unpauseRoundTimer = async function(roundId) {
        return api._callBridge('unpauseRoundTimer', roundId);
    };

    api.updateTimerRound = async function(roundId, updates) {
        return api._callBridge('updateTimerRound', roundId, JSON.stringify(updates));
    };

    api.deleteTimerRound = async function(roundId) {
        return api._callBridge('deleteTimerRound', roundId);
    };

})(window._wimiApi);
