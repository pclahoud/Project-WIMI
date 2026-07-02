/**
 * WIMI API — Multi-Dimensional Analytics Operations
 */
(function(api) {
    'use strict';

    api.getDimensionPerformance = async function(params) {
        params = params || {};
        if (!params.examContextId) throw new Error('examContextId is required');
        if (!params.dimensionId) throw new Error('dimensionId is required');
        return api._callBridge('getDimensionPerformance', JSON.stringify({
            exam_context_id: params.examContextId,
            dimension_id: params.dimensionId,
            include_children: params.includeChildren !== false
        }));
    };

    api.getSubjectHierarchyWithMistakesByDimension = async function(params) {
        params = params || {};
        if (!params.examContextId) throw new Error('examContextId is required');
        if (!params.dimensionId) throw new Error('dimensionId is required');
        return api._callBridge('getSubjectHierarchyWithMistakesByDimension', JSON.stringify({
            exam_context_id: params.examContextId,
            dimension_id: params.dimensionId
        }));
    };

    api.getCrossDimensionPerformance = async function(params) {
        params = params || {};
        if (!params.examContextId) throw new Error('examContextId is required');
        if (!params.dimensionAId || !params.dimensionBId) {
            throw new Error('dimensionAId and dimensionBId are required');
        }
        return api._callBridge('getCrossDimensionPerformance', JSON.stringify({
            exam_context_id: params.examContextId,
            dimension_a_id: params.dimensionAId,
            dimension_b_id: params.dimensionBId,
            min_entries: params.minEntries || 1,
            level_type_a: params.levelTypeA || null,
            level_type_b: params.levelTypeB || null,
            parent_node_a_id: params.parentNodeAId || null,
            parent_node_b_id: params.parentNodeBId || null,
            include_children: params.includeChildren !== false
        }));
    };

    api.getHierarchyLevelsForDimension = async function(params) {
        params = params || {};
        if (!params.examContextId || !params.dimensionId) {
            throw new Error('examContextId and dimensionId are required');
        }
        return api._callBridge('getHierarchyLevelsForDimension', JSON.stringify({
            exam_context_id: params.examContextId,
            dimension_id: params.dimensionId
        }));
    };

    api.getDimensionNodes = async function(params) {
        params = params || {};
        if (!params.examContextId || !params.dimensionId) {
            throw new Error('examContextId and dimensionId are required');
        }
        return api._callBridge('getDimensionNodes', JSON.stringify({
            exam_context_id: params.examContextId,
            dimension_id: params.dimensionId,
            level_type: params.levelType || null,
            parent_node_id: params.parentNodeId || null
        }));
    };

    api.getIntersectionEntries = async function(params) {
        params = params || {};
        if (!params.examContextId || !params.hierarchyAId || !params.dimensionAId ||
            !params.hierarchyBId || !params.dimensionBId) {
            throw new Error('All parameters are required');
        }
        return api._callBridge('getIntersectionEntries', JSON.stringify({
            exam_context_id: params.examContextId,
            hierarchy_a_id: params.hierarchyAId,
            dimension_a_id: params.dimensionAId,
            hierarchy_b_id: params.hierarchyBId,
            dimension_b_id: params.dimensionBId,
            limit: params.limit || 50,
            include_children: params.includeChildren !== false
        }));
    };

    api.getTripleDimensionPerformance = async function(params) {
        params = params || {};
        if (!params.examContextId || !params.dimAId || !params.dimBId || !params.dimCId) {
            throw new Error('All dimension IDs are required');
        }
        return api._callBridge('getTripleDimensionPerformance', JSON.stringify({
            exam_context_id: params.examContextId,
            dim_a_id: params.dimAId,
            dim_b_id: params.dimBId,
            dim_c_id: params.dimCId,
            min_entries: params.minEntries || 3,
            limit: params.limit || 10
        }));
    };

    api.detectInteractionEffects = async function(params) {
        params = params || {};
        if (!params.examContextId || !params.dimensionAId || !params.dimensionBId) {
            throw new Error('All parameters are required');
        }
        return api._callBridge('detectInteractionEffects', JSON.stringify({
            exam_context_id: params.examContextId,
            dimension_a_id: params.dimensionAId,
            dimension_b_id: params.dimensionBId,
            threshold: params.threshold || 0.10
        }));
    };

    api.getMistakeTypeByDimension = async function(params) {
        params = params || {};
        if (!params.examContextId) throw new Error('examContextId is required');
        if (!params.dimensionId) throw new Error('dimensionId is required');
        return api._callBridge('getMistakeTypeByDimension', JSON.stringify({
            exam_context_id: params.examContextId,
            dimension_id: params.dimensionId
        }));
    };

    api.getWeightedStudyRecommendations = async function(params) {
        params = params || {};
        if (!params.examContextId) throw new Error('examContextId is required');
        return api._callBridge('getWeightedStudyRecommendations', JSON.stringify({
            exam_context_id: params.examContextId,
            limit: params.limit || 10
        }));
    };

    api.getTemporalTrendsByDimension = async function(params) {
        params = params || {};
        if (!params.examContextId) throw new Error('examContextId is required');
        if (!params.dimensionId) throw new Error('dimensionId is required');
        return api._callBridge('getTemporalTrendsByDimension', JSON.stringify({
            exam_context_id: params.examContextId,
            dimension_id: params.dimensionId,
            hierarchy_id: params.hierarchyId || null,
            weeks: params.weeks || 12
        }));
    };

})(window._wimiApi);
