/**
 * WIMI API — Exam Context Operations
 */
(function(api) {
    'use strict';

    api.createExamContext = async function(options) {
        return api._callBridge(
            'createExamContext',
            options.examName,
            options.examDescription || '',
            options.examDate || '',
            options.weightRules ? JSON.stringify(options.weightRules) : '',
            options.hierarchyLevels ? JSON.stringify(options.hierarchyLevels) : '',
            options.notes || ''
        );
    };

    api.getExamContext = async function(examContextId) {
        return api._callBridge('getExamContext', examContextId);
    };

    api.getExamContextByName = async function(examName) {
        return api._callBridge('getExamContextByName', examName);
    };

    api.getAllExamContexts = async function(activeOnly) {
        if (activeOnly === undefined) activeOnly = true;
        return api._callBridge('getAllExamContexts', activeOnly);
    };

    api.updateExamContextSettings = async function(examContextId, settings) {
        return api._callBridge('updateExamContextSettings', examContextId, JSON.stringify(settings));
    };

    api.deleteExamContext = async function(examContextId) {
        return api._callBridge('deleteExamContext', examContextId);
    };

    api.reactivateExamContext = async function(examContextId) {
        return api._callBridge('reactivateExamContext', examContextId);
    };

    api.hardDeleteExamContext = async function(examContextId) {
        return api._callBridge('hardDeleteExamContext', examContextId);
    };

    api.getExamContextStats = async function(examContextId) {
        return api._callBridge('getExamContextStats', examContextId);
    };

    // ==================================================================
    // Stage 4 — Exam Length Triple (HIERARCHICAL_WEIGHT_ALLOCATION_REWORK
    // .md §3.2). Bridge slots are typed (int, str, str, str, str, str)
    // for updateExamLength because empty string == SQL NULL on the slot
    // boundary; we serialize Optional[number] -> '' here.
    // ==================================================================

    function _lengthArg(value) {
        // Convert a JS number/null/undefined to the slot string contract.
        if (value === null || value === undefined || value === '') {
            return '';
        }
        return String(value);
    }

    /**
     * Persist the exam-length triple for an exam context.
     *
     * @param {Object} options
     * @param {number} options.examContextId
     * @param {'fixed'|'range'|'unknown'} options.kind
     * @param {?number} options.min      Lower bound (required for fixed/range).
     * @param {?number} options.max      Upper bound (required for fixed/range).
     * @param {?number} options.typical  Planning baseline (required for fixed/range).
     * @param {?string} options.note     Optional copy.
     * @returns {Promise<{ok: boolean, length: {kind, min, max, typical, note}}>}
     */
    api.updateExamLength = async function(options) {
        return api._callBridge(
            'updateExamLength',
            options.examContextId,
            options.kind,
            _lengthArg(options.min),
            _lengthArg(options.max),
            _lengthArg(options.typical),
            options.note || ''
        );
    };

    /**
     * Read the exam-length triple for an exam context.
     * NULL ``length_kind`` is coerced to ``'unknown'`` server-side.
     *
     * @param {number} examContextId
     * @returns {Promise<{kind: string, min: ?number, max: ?number, typical: ?number, note: ?string}>}
     */
    api.getExamLength = async function(examContextId) {
        return api._callBridge('getExamLength', examContextId);
    };

    /**
     * Look up the canonical length data for a known standardized exam.
     * Used by the wizard to pre-fill the length step from a recognized
     * exam name. Returns ``{found: false}`` for unknown names.
     *
     * @param {string} examName
     * @returns {Promise<{found: boolean, kind?: string, min?: number, max?: number, typical?: number, note?: ?string}>}
     */
    api.getKnownExamLength = async function(examName) {
        return api._callBridge('getKnownExamLength', examName);
    };

    api.getExamAnalyticsConfig = async function(examContextId) {
        return api._callBridge('getExamAnalyticsConfig', examContextId);
    };

    api.updateExamAnalyticsConfig = async function(config) {
        return api._callBridge('updateExamAnalyticsConfig', JSON.stringify({
            exam_context_id: config.examContextId,
            default_dimension_id: config.defaultDimensionId,
            chart_visibility: config.chartVisibility,
            chart_sizes: config.chartSizes
        }));
    };

})(window._wimiApi);
