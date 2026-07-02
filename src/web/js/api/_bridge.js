/**
 * WIMI API Bridge — Core WebChannel infrastructure
 * Creates window._wimiApi and provides _callBridge, ready(), etc.
 * Domain modules attach methods to _wimiApi via IIFEs.
 */
(function() {
    'use strict';

    var api = {};

    // ── Internal state ───────────────────────────────────────────────
    api._bridge = null;
    api._errorBridge = null;
    api.isReady = false;
    api._readyPromise = null;
    api._readyResolve = null;
    api._readyReject = null;
    api._connectionError = null;

    // ── Ready promise ────────────────────────────────────────────────
    api._readyPromise = new Promise(function(resolve, reject) {
        api._readyResolve = resolve;
        api._readyReject = reject;
    });

    // ── Connection error overlay ─────────────────────────────────────
    api._showConnectionError = function() {
        var showError = function() {
            var overlay = document.createElement('div');
            overlay.id = 'wimi-connection-error';
            overlay.style.cssText =
                'position:fixed;top:0;left:0;right:0;bottom:0;' +
                'background:rgba(0,0,0,0.85);display:flex;align-items:center;' +
                'justify-content:center;z-index:99999;' +
                "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;";

            overlay.innerHTML =
                '<div style="background:var(--bg-primary, white);color:var(--text-primary, #1f2937);padding:40px;border-radius:12px;' +
                'max-width:500px;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,0.3);">' +
                '<div style="font-size:48px;margin-bottom:20px;">&#x26A0;&#xFE0F;</div>' +
                '<h1 style="margin:0 0 16px 0;font-size:24px;">Connection Error</h1>' +
                '<p style="margin:0 0 24px 0;color:var(--text-secondary, #6b7280);line-height:1.6;">' +
                'Unable to connect to the WIMI backend. This application must be run ' +
                'within the WIMI desktop application, not directly in a web browser.</p>' +
                '<div style="background:var(--color-warning-bg, #fef3c7);border:1px solid var(--color-warning, #fcd34d);border-radius:8px;' +
                'padding:16px;text-align:left;color:var(--text-primary, #92400e);font-size:14px;">' +
                '<strong>How to fix this:</strong>' +
                '<ul style="margin:8px 0 0 0;padding-left:20px;">' +
                '<li>Close this browser window</li>' +
                '<li>Launch WIMI from the desktop application</li>' +
                '<li>If the issue persists, restart the application</li>' +
                '</ul></div></div>';

            document.body.appendChild(overlay);
        };

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', showError);
        } else {
            showError();
        }
    };

    // ── WebChannel init ──────────────────────────────────────────────
    api._initWebChannel = function() {
        if (typeof QWebChannel === 'undefined') {
            var errorMsg = 'QWebChannel not available. This application must be run within the WIMI desktop application.';
            console.error('❌ ' + errorMsg);
            api._connectionError = new Error(errorMsg);
            api._showConnectionError();
            if (api._readyReject) {
                api._readyReject(api._connectionError);
            }
            return;
        }

        try {
            new QWebChannel(qt.webChannelTransport, function(channel) {
                api._bridge = channel.objects.bridge;
                api._errorBridge = channel.objects.errorBridge;
                api.isReady = true;

                console.log('✅ WIMI API connected to Python backend');

                if (api._readyResolve) {
                    api._readyResolve();
                }

                // Emit ready event
                window.dispatchEvent(new CustomEvent('wimi:ready'));
            });
        } catch (error) {
            var errorMsg2 = 'Failed to establish WebChannel connection: ' + error.message;
            console.error('❌ ' + errorMsg2);
            api._connectionError = new Error(errorMsg2);
            api._showConnectionError();
            if (api._readyReject) {
                api._readyReject(api._connectionError);
            }
        }
    };

    // ── Public methods ───────────────────────────────────────────────
    api.ready = async function() {
        if (api._connectionError) {
            throw api._connectionError;
        }
        if (api.isReady) return;
        return api._readyPromise;
    };

    api._parseResponse = function(responseJson) {
        try {
            return JSON.parse(responseJson);
        } catch (e) {
            console.error('Failed to parse response:', responseJson);
            throw new Error('Invalid response from server');
        }
    };

    api._handleResponse = function(responseJson) {
        var response = api._parseResponse(responseJson);
        if (response.success) {
            return response.data;
        } else {
            throw new Error(response.error || 'Unknown error');
        }
    };

    api._callBridge = async function(methodName) {
        await api.ready();

        if (!api._bridge) {
            throw new Error('Backend connection not available');
        }

        if (typeof api._bridge[methodName] !== 'function') {
            throw new Error('Unknown API method: ' + methodName);
        }

        var args = Array.prototype.slice.call(arguments, 1);

        try {
            var responseJson = await api._bridge[methodName].apply(api._bridge, args);
            return api._handleResponse(responseJson);
        } catch (e) {
            console.error('Bridge call ' + methodName + ' failed:', e);
            throw e;
        }
    };

    // ── Backward-compat aliases ──────────────────────────────────────
    Object.defineProperty(api, 'bridge', {
        get: function() { return api._bridge; },
        set: function(v) { api._bridge = v; }
    });
    Object.defineProperty(api, 'errorBridge', {
        get: function() { return api._errorBridge; },
        set: function(v) { api._errorBridge = v; }
    });

    // ── Expose & init ────────────────────────────────────────────────
    window._wimiApi = api;
    api._initWebChannel();
})();
