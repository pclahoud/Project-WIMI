/**
 * WIMI API — Calendar and scheduling (#778)
 *
 * Mirrors CalendarBridgeMixin one to one. Every function resolves to the
 * slot's `data` or throws on `success=false`, like every other module here.
 * Dates are calendar days written YYYY-MM-DD in the student's local zone
 * (build them with LocalDate, never toISOString()).
 */
(function(api) {
    'use strict';

    api.getCalendarRange = async function(start, end, params) {
        return api._callBridge('getCalendarRange', start, end, JSON.stringify(params || {}));
    };

    api.createPlannedSession = async function(payload) {
        return api._callBridge('createPlannedSession', JSON.stringify(payload || {}));
    };

    api.getPlannedSession = async function(plannedId) {
        return api._callBridge('getPlannedSession', plannedId);
    };

    api.updatePlannedSession = async function(plannedId, fields) {
        return api._callBridge('updatePlannedSession', plannedId, JSON.stringify(fields || {}));
    };

    api.setPlannedSessionStatus = async function(plannedId, status) {
        return api._callBridge('setPlannedSessionStatus', plannedId, status);
    };

    api.deletePlannedSession = async function(plannedId) {
        return api._callBridge('deletePlannedSession', plannedId);
    };

    api.materialiseOccurrence = async function(seriesId, occurrenceDate) {
        return api._callBridge('materialiseOccurrence', seriesId, occurrenceDate);
    };

    api.startPlannedSession = async function(plannedId, payload) {
        return api._callBridge('startPlannedSession', plannedId, JSON.stringify(payload || {}));
    };

    api.getSessionReminders = async function() {
        return api._callBridge('getSessionReminders');
    };

    api.dismissSessionReminders = async function() {
        return api._callBridge('dismissSessionReminders');
    };

    api.getGoalPlanSummary = async function(goalId) {
        return api._callBridge('getGoalPlanSummary', goalId);
    };

    api.getSessionTemplates = async function(params) {
        return api._callBridge('getSessionTemplates', JSON.stringify(params || {}));
    };

    api.createSessionTemplate = async function(payload) {
        return api._callBridge('createSessionTemplate', JSON.stringify(payload || {}));
    };

    api.updateSessionTemplate = async function(templateId, fields) {
        return api._callBridge('updateSessionTemplate', templateId, JSON.stringify(fields || {}));
    };

    api.archiveSessionTemplate = async function(templateId) {
        return api._callBridge('archiveSessionTemplate', templateId);
    };

    // The native save dialog; `undefined` when the student cancels.
    api.openCalendarExportDialog = async function(params) {
        return api._callBridge('openCalendarExportDialog', JSON.stringify(params || {}));
    };

    // The work slot: {dest_path, start?, end?, exam_context_id?, include_past?}.
    api.exportCalendarIcs = async function(params) {
        return api._callBridge('exportCalendarIcs', JSON.stringify(params || {}));
    };
})(window._wimiApi);
