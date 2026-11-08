/**
 * WIMI API — Analytics Operations
 */
(function(api) {
    'use strict';

    api.getAnalyticsOverview = async function(examContextId) {
        return api._callBridge('getAnalyticsOverview', JSON.stringify({
            exam_context_id: examContextId || null
        }));
    };

    api.getSubjectAnalytics = async function(params) {
        params = params || {};
        return api._callBridge('getSubjectAnalytics', JSON.stringify({
            exam_context_id: params.examContextId || null,
            limit: params.limit || 10,
            include_children: params.includeChildren !== false
        }));
    };

    api.getTagAnalytics = async function(params) {
        params = params || {};
        return api._callBridge('getTagAnalytics', JSON.stringify({
            exam_context_id: params.examContextId || null,
            group_by_parent: params.groupByParent !== false,
            dimension_id: params.dimensionId || null
        }));
    };

    api.getDifficultyDistribution = async function(examContextId) {
        return api._callBridge('getDifficultyDistribution', JSON.stringify({
            exam_context_id: examContextId || null
        }));
    };

    api.getActivityOverTime = async function(params) {
        params = params || {};
        return api._callBridge('getActivityOverTime', JSON.stringify({
            exam_context_id: params.examContextId || null,
            period: params.period || '30d',
            granularity: params.granularity || 'day'
        }));
    };

    api.getStudyStreak = async function(examContextId) {
        return api._callBridge('getStudyStreak', JSON.stringify({
            exam_context_id: examContextId || null
        }));
    };

    api.getPatternsAndInsights = async function(params) {
        params = params || {};
        return api._callBridge('getPatternsAndInsights', JSON.stringify({
            exam_context_id: params.examContextId || null,
            limit: params.limit || 5
        }));
    };

    api.getSubjectDeepDive = async function(params) {
        params = params || {};
        return api._callBridge('getSubjectDeepDive', JSON.stringify({
            subject_id: params.subjectId,
            exam_context_id: params.examContextId || null,
            primary_parent_id: params.primaryParentId || null
        }));
    };

    api.getSubjectHierarchyWithMistakes = async function(params) {
        params = params || {};
        return api._callBridge('getSubjectHierarchyWithMistakes', JSON.stringify({
            exam_context_id: params.examContextId
        }));
    };

    api.getActivityHeatmap = async function(params) {
        params = params || {};
        return api._callBridge('getActivityHeatmap', JSON.stringify({
            examContextId: params.examContextId || null,
            weeks: params.weeks || 16
        }));
    };

    api.getStreakInfo = async function(params) {
        params = params || {};
        return api._callBridge('getStreakInfo', JSON.stringify({
            examContextId: params.examContextId || null
        }));
    };

    api.getUserGoals = async function(params) {
        params = params || {};
        return api._callBridge('getUserGoals', JSON.stringify({
            examContextId: params.examContextId || null
        }));
    };

    api.setWeeklyGoal = async function(target, params) {
        params = params || {};
        return api._callBridge('setWeeklyGoal', target, JSON.stringify({
            examContextId: params.examContextId || null
        }));
    };

    api.getGoalHistory = async function(params) {
        params = params || {};
        return api._callBridge('getGoalHistory', JSON.stringify({
            examContextId: params.examContextId || null,
            weeks: params.weeks || 8
        }));
    };

    api.getSourceComparison = async function(params) {
        params = params || {};
        return api._callBridge('getSourceComparison', JSON.stringify({
            examContextId: params.examContextId || null,
            months: params.months || 6
        }));
    };

    api.getPerformanceOverTime = async function(params) {
        params = params || {};
        return api._callBridge('getPerformanceOverTime', JSON.stringify({
            examContextId: params.examContextId || null,
            period: params.period || 'weekly',
            weeks: params.weeks || 12
        }));
    };

    /**
     * The difficulty and time card (#898): every mistake in scope placed
     * by its rating and its time spent against the exam's median.
     *
     * This replaced two wrappers whose slots never existed (#383); they and
     * their only caller were deleted in #898 Wave 0.
     *
     * @param {object} params
     * @param {number} params.examContextId - Required.
     * @param {number} [params.subjectId] - Deep dive: its counted scope.
     * @param {number} [params.primaryParentId] - Deep dive parent context.
     * @param {number[]} [params.tagIds] - Picked error types, in pick order.
     * @param {boolean} [params.untagged] - Mistakes with no error type.
     *     Exclusive with tagIds.
     * @param {'any'|'all'} [params.match] - How several tagIds combine.
     */
    api.getDifficultyTimeQuadrants = async function(params) {
        params = params || {};
        return api._callBridge('getDifficultyTimeQuadrants', JSON.stringify({
            exam_context_id: params.examContextId || null,
            subject_id: params.subjectId || null,
            primary_parent_id: params.primaryParentId || null,
            tag_ids: params.tagIds || [],
            untagged: params.untagged === true,
            match: params.match || 'any'
        }));
    };

    // ====================================================================
    // Stage 9 — weight_source-aware analytics
    // (docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md §"Stage 9")
    //
    // ``getSubjectExamWeightAnalysis`` (in weights.js) now bundles a
    // ``weight_source_distribution`` field on its response. This
    // dedicated wrapper is for the analytics dashboard's "Confidence
    // breakdown" card which renders only the per-source counts and
    // doesn't need the heavier quadrant analysis.
    // ====================================================================

    /**
     * Per-``weight_source`` subject counts for the breakdown card.
     *
     * @param {number} examContextId - Required.
     * @returns {Promise<{official:number, user_explicit:number,
     *     user_defined:number, derived:number, user_estimate:number,
     *     total:number}>}
     */
    api.getWeightSourceBreakdown = async function(examContextId) {
        if (examContextId === undefined || examContextId === null) {
            throw new Error('examContextId is required');
        }
        return api._callBridge('getWeightSourceBreakdown', examContextId);
    };

})(window._wimiApi);
