/**
 * WIMI API — Student-authored semantic relations between subjects.
 *
 * Issue #14. A relation says something the containment hierarchy cannot
 * ("hypertension leads to hypertensive nephrosclerosis"), in the
 * student's own words. The sentence is the payload, not decoration:
 * `createSubjectRelation` will be refused without one.
 */
(function(api) {
    'use strict';

    /**
     * Every visible relation touching a subject, ordered for a context.
     *
     * `primaryParentId` is the deep dive's selected parent context. It
     * **orders** the list and never shortens it — both
     * *hypertension → eclampsia* and *hypertension → RPGN* are true of
     * hypertension, and hiding a true relation is the expensive error in
     * a mistakes log. Pass null for "All parents".
     *
     * @param {{subjectId: number, primaryParentId?: (number|null)}} params
     * @returns {Promise<Object>} `{subject_id, relations, incoming_count,
     *   outgoing_count, fanin_soft_cap, fanin_over_cap, ...}`. An empty
     *   `relations` array is the normal state — the caller renders
     *   nothing at all rather than an empty card.
     */
    api.getSubjectRelations = async function(params) {
        params = params || {};
        return api._callBridge('getSubjectRelations', JSON.stringify({
            subject_id: params.subjectId,
            primary_parent_id: params.primaryParentId || null
        }));
    };

    /**
     * Record one directional relation.
     *
     * @param {{fromSubjectId: number, toSubjectId: number, reason: string,
     *          strength?: number, origin?: string,
     *          sourceEntryId?: (number|null)}} params
     *   `reason` is required and must not be blank. `strength` is
     *   3/2/1 for certain/likely/possible and -1 for "checked — not
     *   related".
     * @returns {Promise<Object>} the created row. Rejects with the
     *   database layer's own message when the relation is refused (no
     *   reason, self-loop, duplicate, archived endpoint) — show it.
     */
    api.createSubjectRelation = async function(params) {
        params = params || {};
        return api._callBridge('createSubjectRelation', JSON.stringify({
            from_subject_id: params.fromSubjectId,
            to_subject_id: params.toSubjectId,
            reason: params.reason,
            strength: params.strength === undefined ? null : params.strength,
            origin: params.origin || 'user',
            source_entry_id: params.sourceEntryId || null
        }));
    };

    /**
     * Remove a relation. Resolves with `{deleted: false}` when it was
     * already gone, which is not an error.
     *
     * @param {number} relationId
     * @returns {Promise<{deleted: boolean}>}
     */
    api.deleteSubjectRelation = async function(relationId) {
        return api._callBridge('deleteSubjectRelation', relationId);
    };

    /**
     * Candidates for a new relation from this subject.
     *
     * Spans dimensions on purpose: a topic in one dimension relating to
     * a technique in another is what containment cannot express. Each
     * result reports `crosses_dimension` and `incoming_count` so the
     * picker can label the crossing and warn near the soft fan-in cap.
     *
     * `direction` hides only the partners that direction already
     * covers. Pass it: without it a subject already related the *other*
     * way would still be offered, and with a direction-blind exclusion
     * a cycle (`A→B` and `B→A`, both legitimate — decision 7) could not
     * be written from the second subject's page at all.
     *
     * @param {{subjectId: number, query: string, limit?: number,
     *          direction?: ('outgoing'|'incoming')}} params
     * @returns {Promise<Array<Object>>}
     */
    api.searchRelatableSubjects = async function(params) {
        params = params || {};
        return api._callBridge('searchRelatableSubjects', JSON.stringify({
            subject_id: params.subjectId,
            query: params.query || '',
            limit: params.limit || 10,
            direction: params.direction || null
        }));
    };

})(window._wimiApi);
