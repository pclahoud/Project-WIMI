/**
 * WIMI Event Bus
 * Lightweight pub/sub for plugin and cross-component communication.
 * Also dispatches CustomEvents on window for backward compat.
 */
(function() {
    'use strict';

    var listeners = {};

    var eventBus = {
        /**
         * Subscribe to an event.
         * @param {string} event - Event name
         * @param {Function} callback - Handler function
         * @returns {Function} Unsubscribe function
         */
        on: function(event, callback) {
            if (!listeners[event]) {
                listeners[event] = [];
            }
            listeners[event].push(callback);
            return function() {
                eventBus.off(event, callback);
            };
        },

        /**
         * Subscribe to an event once.
         * @param {string} event - Event name
         * @param {Function} callback - Handler function
         * @returns {Function} Unsubscribe function
         */
        once: function(event, callback) {
            var wrapper = function(data) {
                eventBus.off(event, wrapper);
                callback(data);
            };
            return eventBus.on(event, wrapper);
        },

        /**
         * Unsubscribe from an event.
         * @param {string} event - Event name
         * @param {Function} callback - Handler to remove
         */
        off: function(event, callback) {
            if (!listeners[event]) return;
            listeners[event] = listeners[event].filter(function(fn) {
                return fn !== callback;
            });
        },

        /**
         * Emit an event to all subscribers.
         * Also dispatches a CustomEvent on window with 'wimi:' prefix.
         * @param {string} event - Event name
         * @param {*} [data] - Event payload
         */
        emit: function(event, data) {
            var handlers = listeners[event];
            if (handlers) {
                for (var i = 0; i < handlers.length; i++) {
                    try {
                        handlers[i](data);
                    } catch (e) {
                        console.error('EventBus handler error (' + event + '):', e);
                    }
                }
            }
            // Also dispatch on window for backward compat / DOM integration
            window.dispatchEvent(new CustomEvent('wimi:' + event, { detail: data }));
        }
    };

    window.eventBus = eventBus;
})();
