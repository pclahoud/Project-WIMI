/**
 * WIMI API — Utility Operations
 */
(function(api) {
    'use strict';

    api.checkConnection = async function() {
        return api._callBridge('checkConnection');
    };

    api.getAppInfo = async function() {
        return api._callBridge('getAppInfo');
    };

    api.copyToClipboard = async function(text) {
        return api._callBridge('copyToClipboard', text);
    };

    // getTestModeBridgeCalls returns the raw JSON string from the slot
    // (already a JSON-encoded list of bridge calls — not the
    // {success, data, error} envelope), so it bypasses _callBridge's
    // response parsing. The wimi_test BridgeCapture polls this and
    // JSON.parses the string on the Python side.
    api.getTestModeBridgeCalls = async function(sinceTs) {
        await api.ready();
        if (!api._bridge) return '[]';
        if (typeof api._bridge.getTestModeBridgeCalls !== 'function') return '[]';
        return api._bridge.getTestModeBridgeCalls(sinceTs || 0.0);
    };

    // Test-mode only: switch the bridge from "no user" to the test
    // user's database. The slot returns the standard envelope so we
    // route through _callBridge for parse + error-throw semantics.
    api.loadTestUserDatabase = async function(userId) {
        return api._callBridge('loadTestUserDatabase', userId);
    };

})(window._wimiApi);
