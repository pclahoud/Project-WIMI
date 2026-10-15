/**
 * WIMI API — Psychometric Assessment (#766)
 *
 * Mirrors AssessmentBridgeMixin one to one. Every function resolves to the
 * slot's `data` or throws on `success=false`, like every other module here.
 *
 * startAssessment is resume-safe: if an unfinished administration exists it
 * is returned (is_resumed=true) with answered_item_codes, so the page can
 * pick up where the student left off without a second call.
 */
(function(api) {
    'use strict';

    api.startAssessment = async function(version) {
        return api._callBridge('startAssessment', version || '');
    };

    api.getInFlightAssessment = async function() {
        return api._callBridge('getInFlightAssessment');
    };

    api.submitAssessmentResponse = async function(params) {
        var p = params || {};
        return api._callBridge('submitResponse',
            p.assessmentId, p.itemCode, p.rawResponse, p.responseTimeMs || 0);
    };

    api.finishAssessment = async function(assessmentId) {
        return api._callBridge('finishAssessment', assessmentId);
    };

    api.getLatestAssessmentScores = async function() {
        return api._callBridge('getLatestScores');
    };

    api.getAssessmentHistory = async function(limit) {
        return api._callBridge('getAssessmentHistory', limit || 0);
    };

    api.getAssessmentResponses = async function(assessmentId) {
        return api._callBridge('getAssessmentResponses', assessmentId);
    };

    api.getReassessmentStatus = async function() {
        return api._callBridge('getReassessmentStatus');
    };

    api.snoozeReassessment = async function(days) {
        return api._callBridge('snoozeReassessment', days);
    };

    api.setReassessmentCadence = async function(cadenceDays) {
        return api._callBridge('setReassessmentCadence', cadenceDays);
    };

    api.getReassessmentCadence = async function() {
        return api._callBridge('getReassessmentCadence');
    };

})(window._wimiApi);
