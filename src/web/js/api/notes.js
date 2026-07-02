/**
 * WIMI API — Entry Notes Operations
 */
(function(api) {
    'use strict';

    api.addEntryNote = async function(entryId, noteData) {
        return api._callBridge('addEntryNote', entryId, JSON.stringify(noteData || {}));
    };

    api.getEntryNotes = async function(entryId) {
        return api._callBridge('getEntryNotes', entryId);
    };

    api.updateEntryNote = async function(noteId, updates) {
        return api._callBridge('updateEntryNote', noteId, JSON.stringify(updates));
    };

    api.deleteEntryNote = async function(noteId) {
        return api._callBridge('deleteEntryNote', noteId);
    };

    api.clearEntryNote = async function(noteId) {
        return api._callBridge('clearEntryNote', noteId);
    };

    api.updateNoteLinkedSubjects = async function(noteId, subjectIds) {
        return api._callBridge('updateNoteLinkedSubjects', noteId, JSON.stringify(subjectIds || []));
    };

    api.getNotesBySubjects = async function(subjectIds, excludeEntryId, limit) {
        return api._callBridge(
            'getNotesBySubjects',
            JSON.stringify(subjectIds || []),
            excludeEntryId || 0,
            limit || 20
        );
    };

    api.attachExistingNoteToEntry = async function(noteId, entryId) {
        return api._callBridge('attachExistingNoteToEntry', noteId, entryId);
    };

    api.detachNoteFromEntry = async function(noteId, entryId) {
        return api._callBridge('detachNoteFromEntry', noteId, entryId);
    };

})(window._wimiApi);
