/**
 * WIMI API — Entry Notes Operations
 */
(function(api) {
    'use strict';

    api.addEntryNote = async function(entryId, noteData) {
        return api._callBridge('addEntryNote', entryId, JSON.stringify(noteData || {}));
    };

    // A note on no entry (#848). Same payload shape as addEntryNote's
    // noteData, so one builder serves both kinds of note.
    api.addNote = async function(noteData) {
        return api._callBridge('addNote', JSON.stringify(noteData || {}));
    };

    api.getNote = async function(noteId) {
        return api._callBridge('getNote', noteId);
    };

    api.listFreeNotes = async function(limit) {
        return api._callBridge('listFreeNotes', limit || 50);
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
