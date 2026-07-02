/**
 * WIMI API — MCP Server Operations
 */
(function(api) {
    'use strict';

    api.startMcpServer = async function(port) {
        return api._callBridge('startMcpServer', JSON.stringify({ port: port }));
    };

    api.stopMcpServer = async function() {
        return api._callBridge('stopMcpServer');
    };

    api.getMcpServerStatus = async function() {
        return api._callBridge('getMcpServerStatus');
    };

})(window._wimiApi);
