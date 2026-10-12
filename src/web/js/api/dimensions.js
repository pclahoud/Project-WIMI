/**
 * WIMI API — Multi-Dimensional Exam Operations
 */
(function(api) {
    'use strict';

    api.examUsesDimensions = async function(examContextId) {
        if (!examContextId) throw new Error('examContextId is required');
        return api._callBridge('examUsesDimensions', examContextId);
    };

    api.createDimension = async function(params) {
        params = params || {};
        if (!params.examContextId) throw new Error('examContextId is required');
        if (!params.name) throw new Error('name is required');
        if (params.displayOrder === undefined || params.displayOrder === null) {
            throw new Error('displayOrder is required');
        }
        return api._callBridge('createDimension',
            params.examContextId, params.name, params.displayOrder,
            params.isRequired !== false, params.allowMultiple || false,
            params.description || ''
        );
    };

    api.getDimensions = async function(examContextId) {
        if (!examContextId) throw new Error('examContextId is required');
        return api._callBridge('getDimensions', examContextId);
    };

    api.getDimension = async function(dimensionId) {
        if (!dimensionId) throw new Error('dimensionId is required');
        return api._callBridge('getDimension', dimensionId);
    };

    api.updateDimension = async function(dimensionId, updates) {
        if (!dimensionId) throw new Error('dimensionId is required');
        return api._callBridge('updateDimension', dimensionId, JSON.stringify(updates));
    };

    api.deleteDimension = async function(dimensionId) {
        if (!dimensionId) throw new Error('dimensionId is required');
        return api._callBridge('deleteDimension', dimensionId);
    };

    // Subjects stranded outside every axis (#605). Adding the first axis to
    // an exam that already has subjects leaves them all at
    // `dimension_id NULL`, where the dimensioned tree does not draw them and
    // the plain tree is never drawn again -- so the student's whole tree
    // vanishes. Returns {subjects: [{subject_id, name, level_type,
    // subtree_count}]}, roots only, empty on a healthy exam.
    api.getSubjectsOutsideAnyAxis = async function(examContextId) {
        if (!examContextId) throw new Error('examContextId is required');
        return api._callBridge('getSubjectsOutsideAnyAxis', examContextId);
    };

    // Move those subjects, with their subtrees, into an axis (#605). The
    // whole subtree travels because cross-dimensional edges are a Non-Goal.
    api.moveSubjectsIntoAxis = async function(subjectIds, dimensionId) {
        if (!Array.isArray(subjectIds) || subjectIds.length === 0) {
            throw new Error('subjectIds is required');
        }
        if (!dimensionId) throw new Error('dimensionId is required');
        return api._callBridge('moveSubjectsIntoAxis', subjectIds, dimensionId);
    };

    // What archiving this dimension would take with it (#210), for the
    // confirmation the exam wizard shows before it removes one (#486).
    // The slot has existed since #210 and had no wrapper and no caller, so
    // the subject and entry counts it computes reached nobody.
    // Returns {dimension_name, subject_count, entry_count, root_node_ids,
    // already_archived}.
    api.getDimensionDeletePreview = async function(dimensionId) {
        return api._callBridge('getDimensionDeletePreview', dimensionId);
    };

    api.reorderDimensions = async function(examContextId, dimensionIds) {
        if (!examContextId) throw new Error('examContextId is required');
        if (!Array.isArray(dimensionIds)) throw new Error('dimensionIds must be an array');
        return api._callBridge('reorderDimensions', examContextId, JSON.stringify(dimensionIds));
    };


    api.getHierarchyNodesByDimension = async function(examContextId, dimensionId) {
        if (!examContextId) throw new Error('examContextId is required');
        if (!dimensionId) throw new Error('dimensionId is required');
        return api._callBridge('getHierarchyNodesByDimension', examContextId, dimensionId);
    };

    api.createSubjectNodeWithDimension = async function(nodeData) {
        if (!nodeData.exam_context_id) throw new Error('exam_context_id is required');
        if (!nodeData.name) throw new Error('name is required');
        if (!nodeData.dimension_id) throw new Error('dimension_id is required');
        return api._callBridge('createSubjectNodeWithDimension', JSON.stringify(nodeData));
    };

    api.getDimensionHierarchy = async function(examContextId, dimensionId) {
        if (!examContextId) throw new Error('examContextId is required');
        if (!dimensionId) throw new Error('dimensionId is required');
        return api._callBridge('getDimensionHierarchy', examContextId, dimensionId);
    };

})(window._wimiApi);
