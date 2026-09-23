/**
 * WIMI API — Embedded Browser Pane
 *
 * A second web view in the right half of the main splitter, so a
 * question bank can sit beside the entry form without alt-tabbing.
 *
 * Every call rejects with "browser pane not available" when no pane
 * controller is attached. Treat that as "the feature is not present" and
 * simply don't render the toggle — it is a normal state, not an error
 * worth showing the student.
 */
(function(api) {
    'use strict';

    /**
     * Question sources the pane offers as shortcut buttons.
     *
     * A source earns a button by having a web address, so this is also
     * what the settings panel renders: sources with an address get a
     * control, sources without get an invitation to add one. Sources
     * with no address are not returned at all — pair this with
     * api.getQuestionSources() to show those rows.
     *
     * @returns {Promise<Array<object>>} Most-recently-opened first, each
     *     {id, source_name, url, desktop_site, last_opened_at}.
     */
    api.getPaneSources = async function() {
        return api._callBridge('getPaneSources');
    };

    /**
     * Whether the pane sends a desktop user-agent for this source.
     *
     * Per-source rather than global: one qbank may serve a cramped
     * mobile layout to an embedded view while another is fine.
     *
     * @param {number} sourceId
     * @param {boolean} enabled
     * @returns {Promise<object>} e.g. {source_id, desktop_site}.
     */
    api.setPaneDesktopSite = async function(sourceId, enabled) {
        return api._callBridge('setPaneDesktopSite', sourceId, !!enabled);
    };

    /**
     * Show the pane.
     *
     * With no url the pane decides where to land from the student's
     * "when the pane opens" setting, and a pane that already has a page
     * keeps it — reopening mid-session must not throw away their place.
     * Pass a url only when the caller has a specific destination.
     *
     * @param {string} [url]
     * @returns {Promise<object>} Pane status, e.g. {open:true, url}.
     */
    api.openBrowserPane = async function(url) {
        return api._callBridge('openBrowserPane', url || '');
    };

    /**
     * Hide the pane.
     *
     * @returns {Promise<object>} Pane status, e.g. {open:false}.
     */
    api.closeBrowserPane = async function() {
        return api._callBridge('closeBrowserPane');
    };

    /**
     * Read the pane's current state.
     *
     * @returns {Promise<object>} Pane status, e.g.
     *     {open:boolean, url:(string|null)}.
     */
    api.getBrowserPaneStatus = async function() {
        return api._callBridge('getBrowserPaneStatus');
    };

})(window._wimiApi);
