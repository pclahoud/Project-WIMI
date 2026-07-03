/**
 * WIMI API Domain Loader
 * Injects domain scripts via document.write during page parse.
 * Must be loaded immediately after _bridge.js.
 */
(function() {
    var s = document.currentScript.src.replace('_loader.js', '');
    var f = [
        'exam_contexts.js',
        'hierarchy.js',
        'edges.js',
        'weights.js',
        'sessions.js',
        'timer.js',
        'entries.js',
        'notes.js',
        'media.js',
        'sources.js',
        'tags.js',
        'aliases.js',
        'browsing.js',
        'analytics.js',
        'dimensions.js',
        'dimension_analytics.js',
        'import_export.js',
        'preferences.js',
        'profiles.js',
        'profile_transfer.js',
        'mcp_server.js',
        'utility.js',
        'plugins.js'
    ];
    for (var i = 0; i < f.length; i++) {
        document.write('<script src="' + s + f[i] + '"><\/script>');
    }
    // Finalize: expose window.api and clean up
    document.write('<script>window.api=window._wimiApi;window.WIMIApi=function(){};delete window._wimiApi;<\/script>');
})();
