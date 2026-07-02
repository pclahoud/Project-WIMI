/**
 * WIMI Plugin Loader
 * Discovers and loads frontend plugins from the plugins directory.
 * Plugins inject CSS, JS, and HTML into data-plugin-slot elements.
 */
(function() {
    'use strict';

    var loadedPlugins = {};

    var PluginLoader = {
        /**
         * Initialize the plugin loader.
         * Listens for wimi:ready to auto-discover and load enabled plugins.
         */
        init: function() {
            console.log('WIMI PluginLoader initialized');

            // Auto-discover plugins once the API is ready
            var self = this;
            (async function() {
                try {
                    await api.ready();
                    self.discoverAndLoad();
                } catch (e) {
                    console.error('PluginLoader: API not available:', e);
                }
            })();
        },

        /**
         * Discover installed plugins from backend and load enabled ones.
         */
        discoverAndLoad: async function() {
            try {
                if (!window.api || !window.api.getInstalledPlugins) {
                    console.log('PluginLoader: api.getInstalledPlugins not available');
                    return;
                }

                var plugins = await window.api.getInstalledPlugins();
                if (!plugins || !plugins.length) {
                    console.log('PluginLoader: no plugins installed');
                    return;
                }

                for (var i = 0; i < plugins.length; i++) {
                    var plugin = plugins[i];
                    if (plugin.enabled && (plugin.js || plugin.css || (plugin.slots && Object.keys(plugin.slots).length > 0))) {
                        await PluginLoader.loadPlugin(plugin);
                    }
                }
            } catch (e) {
                console.error('PluginLoader: auto-discovery failed:', e);
            }
        },

        /**
         * Load a single plugin by manifest object.
         * @param {object} manifest - Plugin manifest
         * @param {string} manifest.id - Unique plugin ID
         * @param {string} manifest.name - Display name
         * @param {string} [manifest.version] - Version string
         * @param {string} [manifest.css] - Path to CSS file
         * @param {string} [manifest.js] - Path to JS file
         * @param {object} [manifest.slots] - Map of slot name to HTML content/path
         * @returns {Promise<boolean>} Whether plugin loaded successfully
         */
        loadPlugin: async function(manifest) {
            if (!manifest || !manifest.id) {
                console.error('Plugin manifest must have an id');
                return false;
            }

            if (loadedPlugins[manifest.id]) {
                console.warn('Plugin already loaded: ' + manifest.id);
                return false;
            }

            try {
                // Inject CSS
                if (manifest.css) {
                    var link = document.createElement('link');
                    link.rel = 'stylesheet';
                    link.href = manifest.css;
                    link.dataset.plugin = manifest.id;
                    document.head.appendChild(link);
                }

                // Inject HTML into slots BEFORE JS so plugin scripts can
                // find their slot elements immediately on execution
                if (manifest.slots) {
                    for (var slotName in manifest.slots) {
                        var slot = document.querySelector('[data-plugin-slot="' + slotName + '"]');
                        if (slot) {
                            var container = document.createElement('div');
                            container.dataset.pluginId = manifest.id;
                            container.innerHTML = manifest.slots[slotName];
                            slot.appendChild(container);
                        }
                    }
                }

                // Inject JS (after slots are in the DOM)
                if (manifest.js) {
                    await new Promise(function(resolve, reject) {
                        var script = document.createElement('script');
                        script.src = manifest.js;
                        script.dataset.plugin = manifest.id;
                        script.onload = function() {
                            // Re-dispatch wimi:ready so the plugin's listener fires.
                            // By this point api.ready() has long resolved, so the
                            // event is truthful — the API is available.
                            window.dispatchEvent(new CustomEvent('wimi:ready'));
                            resolve();
                        };
                        script.onerror = reject;
                        document.head.appendChild(script);
                    });
                }

                loadedPlugins[manifest.id] = manifest;

                if (window.eventBus) {
                    window.eventBus.emit('plugin:loaded', { id: manifest.id, name: manifest.name });
                }

                console.log('Plugin loaded: ' + manifest.name + ' (' + manifest.id + ')');
                return true;
            } catch (e) {
                console.error('Failed to load plugin ' + manifest.id + ':', e);
                return false;
            }
        },

        /**
         * Get all loaded plugins.
         * @returns {object} Map of plugin ID to manifest
         */
        getLoadedPlugins: function() {
            return Object.assign({}, loadedPlugins);
        },

        /**
         * Unload a plugin by ID.
         * @param {string} pluginId - Plugin ID to unload
         */
        unloadPlugin: function(pluginId) {
            if (!loadedPlugins[pluginId]) return;

            // Remove CSS
            var css = document.querySelector('link[data-plugin="' + pluginId + '"]');
            if (css) css.remove();

            // Remove JS
            var js = document.querySelector('script[data-plugin="' + pluginId + '"]');
            if (js) js.remove();

            // Remove slot content
            var slotContent = document.querySelectorAll('[data-plugin-id="' + pluginId + '"]');
            for (var i = 0; i < slotContent.length; i++) {
                slotContent[i].remove();
            }

            delete loadedPlugins[pluginId];

            if (window.eventBus) {
                window.eventBus.emit('plugin:unloaded', { id: pluginId });
            }
        }
    };

    window.PluginLoader = PluginLoader;

    // Auto-init on DOMContentLoaded
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() { PluginLoader.init(); });
    } else {
        PluginLoader.init();
    }
})();
