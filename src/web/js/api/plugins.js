/**
 * WIMI API — Plugin Operations
 */
(function(api) {
    'use strict';

    /**
     * Call a backend plugin method.
     * @param {string} pluginId - Plugin identifier
     * @param {string} method - Method name on the plugin
     * @param {object} [params] - Parameters to pass
     * @returns {Promise<any>} Plugin response data
     */
    api.callPlugin = async function(pluginId, method, params) {
        return api._callBridge('callPlugin', JSON.stringify({
            plugin_id: pluginId,
            method: method,
            params: params || {}
        }));
    };

    /**
     * Get all installed plugins with enabled status.
     * @returns {Promise<Array>} List of plugin info objects
     */
    api.getInstalledPlugins = async function() {
        return api._callBridge('getInstalledPlugins');
    };

    /**
     * Enable or disable a plugin.
     * @param {string} pluginId - Plugin identifier
     * @param {boolean} enabled - Whether to enable
     * @returns {Promise<object>} {plugin_id, enabled}
     */
    api.setPluginEnabled = async function(pluginId, enabled) {
        return api._callBridge('setPluginEnabled', JSON.stringify({
            plugin_id: pluginId,
            enabled: enabled
        }));
    };

    /**
     * Get settings for a plugin (merged with defaults).
     * @param {string} pluginId - Plugin identifier
     * @returns {Promise<object>} Settings key-value map
     */
    api.getPluginSettings = async function(pluginId) {
        return api._callBridge('getPluginSettings', JSON.stringify({
            plugin_id: pluginId
        }));
    };

    /**
     * Update settings for a plugin.
     * @param {string} pluginId - Plugin identifier
     * @param {object} settings - Settings to save
     * @returns {Promise<object>} Merged settings
     */
    api.updatePluginSettings = async function(pluginId, settings) {
        return api._callBridge('updatePluginSettings', JSON.stringify({
            plugin_id: pluginId,
            settings: settings
        }));
    };

    /**
     * Upload media to an entry on behalf of a plugin (permission-gated).
     * Requires 'write:media' permission in the plugin manifest.
     * @param {string} pluginId - Plugin identifier
     * @param {number} entryId - Entry to attach media to
     * @param {string} base64Data - Base64-encoded image data (raw or data URL)
     * @param {string} filename - Original filename
     * @param {string} mimeType - MIME type (image/png, image/jpeg, etc.)
     * @returns {Promise<object>} Full media record with id, file_uuid, thumbnail_url, full_url, etc.
     */
    api.uploadMedia = async function(pluginId, entryId, base64Data, filename, mimeType) {
        return api._callBridge('pluginUploadMedia', JSON.stringify({
            plugin_id: pluginId,
            entry_id: entryId,
            base64_data: base64Data,
            filename: filename,
            mime_type: mimeType
        }));
    };

    /**
     * Open a file dialog to install a plugin from a .zip file.
     * @returns {Promise<object|null>} {plugin_id, name, version, replaced} or null if cancelled
     */
    api.installPlugin = async function() {
        return api._callBridge('openPluginInstallDialog');
    };

    /**
     * Uninstall a plugin by ID.
     * @param {string} pluginId - Plugin identifier
     * @returns {Promise<object>} {plugin_id, uninstalled}
     */
    api.uninstallPlugin = async function(pluginId) {
        return api._callBridge('uninstallPlugin', JSON.stringify({
            plugin_id: pluginId
        }));
    };

})(window._wimiApi);
