"""User DB migration v37 -- remove what deleted exams left behind (#884).

Option A of ``docs/planning/EXAM_NAME_DEBRIS_CLEANUP_PLAN.md``, chosen by the
owner on 2026-11-06. Announced on #884 comment 12033 before it was written.

Seven tables name their exam by TEXT in an ``exam_context`` column with no
foreign key (``EXAM_NAME_KEYED_TABLES`` in ``domains/exam_contexts.py``).
Before #880 (#873), *Delete Permanently* removed the ``exam_contexts`` row and
nothing reached those tables, so every permanent delete left the exam's subject
tree, aliases, tags and sources filed under a name no exam held. The next exam
created under that name opened on them. #880 stops new debris; this removes
the debris already in a profile.

Students move between versions by exporting a ``.wimi`` and importing it, and
import opens the database through ``UserDatabase``, which runs pending
migrations. So this runs once on each profile, the first time it is imported
into a release that has it.

What is debris
--------------
A row whose ``exam_context`` is not NULL and equals no ``exam_contexts.exam_name``
in the profile. The comparison is exact, as every read in the app compares it.
A tree a student already took over by creating a new exam under the old name
matches a living exam, so it is not debris and is not touched.

What is kept although it is debris (rule 1)
-------------------------------------------
A debris row that a surviving row depends on is kept, with its ancestors. The
app cannot produce any of these, but a profile can carry anything:

* a subject an entry is tagged with (``entry_subject_mappings`` CASCADE), or
  names as its parent context (``primary_parent_id`` SET NULL, which would
  quietly re-scope the entry), or carries in ``question_hierarchy_tags``;
* a subject that is the ``parent_id`` (CASCADE: deleting it would delete the
  child) or the edge parent (the child would become a root) of a subject that
  is not debris, or that a relation links to a subject that is not debris;
* a subject or tag that a non-debris alias, topic assignment or question tag
  points at, and a question analysis that a non-debris tag or assignment does;
* a tag an entry carries through ``entry_tags`` (CASCADE), and a tag that is the
  ``parent_id`` of a tag that is not debris (NO ACTION: the delete would fail
  and refuse the import).

Ancestors of a kept subject (through ``parent_id`` and ``subject_edges``) and of
a kept tag (through ``parent_id``) are kept too. The kept rows stay filed under
the old name, so #718 still refuses a rename into it; nothing else changes.

What happens to a question source (rule 2)
------------------------------------------
A debris source a session, template or plan still references is unfiled
(``exam_context = NULL``), as #880 does. ``review_sessions`` references sources
with NO ACTION, and a template or plan would quietly lose its choice. Any other
debris source is deleted.

Left alone deliberately
-----------------------
Free notes (#848), even tagged with debris subjects: they are the student's own
writing, and ``linked_subject_ids`` is JSON that every read already filters.
The retired graph store. Delete-journal batches that also name a surviving
subject.

Why every statement is inside ``upgrade()``
-------------------------------------------
The runner checksums the source of ``upgrade`` and nothing else
(``Migration._compute_checksum``). SQL held in a module constant, or in a
helper shared with #880's hard delete, could change what this migration does on
a profile not yet migrated without the checksum noticing. So nothing here is
imported or defined outside the function, and
``test_the_tables_match_exam_name_keyed_tables`` ties the table list to
``EXAM_NAME_KEYED_TABLES`` instead of an import.

Mechanics
---------
Data only: no ``CREATE``, ``ALTER`` or ``DROP`` on the main schema, so the
#593 fingerprint is unchanged. A profile with no debris gets no write at all. The working sets are TEMP tables, which live in
the connection's temp schema and are dropped before the end. ``upgrade`` executes
``BEGIN`` itself when no transaction is open, as m036 does, so a failure part-way
leaves the profile as it was. A second run finds no debris and changes nothing.
"""
from __future__ import annotations

import sqlite3

VERSION = 37
NAME = "exam_name_debris"


def upgrade(conn: sqlite3.Connection) -> None:
    # First statement, so even the reads below are inside the one transaction.
    if not conn.in_transaction:
        conn.execute("BEGIN")

    tables = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    keyed = ("subject_nodes", "subject_aliases", "tags", "question_tags",
             "question_sources", "question_analyses",
             "question_topic_assignments")
    if "exam_contexts" not in tables or not any(t in tables for t in keyed):
        # Isolated-migration tests run partial registries; nothing to clean.
        return

    def has(*names):
        return all(n in tables for n in names)

    def dead(col):
        return (f"({col} IS NOT NULL AND NOT EXISTS (SELECT 1 FROM"
                f" exam_contexts m037_ec WHERE m037_ec.exam_name = {col}))")

    # Nothing filed under a dead name and no stale dimension journal: touch
    # nothing. This is every profile made since #880, and it matters beyond
    # tidiness. A DELETE on subject_nodes is prepared with its cascades even
    # when it matches no row, and a legacy profile missing a table that a
    # child of subject_nodes references (exam_dimensions, which the legacy
    # ensure path creates, not a migration) fails at that point.
    probes = [f"SELECT 1 FROM {t} WHERE {dead('exam_context')}"
              for t in keyed if t in tables]
    if has("dimension_delete_batches"):
        probes.append("SELECT 1 FROM dimension_delete_batches"
                      " WHERE exam_id NOT IN (SELECT id FROM exam_contexts)")
    if not conn.execute(
            f"SELECT EXISTS ({' UNION ALL '.join(probes)})").fetchone()[0]:
        return

    for t in ("m037_dead_subjects", "m037_keep_subjects", "m037_gone_subjects",
              "m037_dead_tags", "m037_keep_tags", "m037_gone_batches"):
        conn.execute(f"DROP TABLE IF EXISTS temp.{t}")
    conn.execute("CREATE TEMP TABLE m037_dead_subjects (id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TEMP TABLE m037_keep_subjects (id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TEMP TABLE m037_gone_subjects (id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TEMP TABLE m037_dead_tags (id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TEMP TABLE m037_keep_tags (id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TEMP TABLE m037_gone_batches (id TEXT PRIMARY KEY)")

    # ---- subjects -----------------------------------------------------
    if has("subject_nodes"):
        conn.execute(
            "INSERT INTO m037_dead_subjects SELECT sn.id FROM subject_nodes sn"
            f" WHERE {dead('sn.exam_context')}")
        not_dead = "NOT IN (SELECT id FROM m037_dead_subjects)"
        seeds = [f"SELECT parent_id FROM subject_nodes WHERE id {not_dead}"]
        if has("entry_subject_mappings", "question_entries"):
            seeds.append(
                "SELECT esm.subject_node_id FROM entry_subject_mappings esm"
                " JOIN question_entries qe ON qe.id = esm.question_entry_id")
            seeds.append(
                "SELECT esm.primary_parent_id FROM entry_subject_mappings esm"
                " JOIN question_entries qe ON qe.id = esm.question_entry_id")
        if has("question_hierarchy_tags", "question_entries"):
            seeds.append(
                "SELECT qht.hierarchy_id FROM question_hierarchy_tags qht"
                " JOIN question_entries qe ON qe.id = qht.entry_id")
        if has("subject_edges"):
            seeds.append(
                f"SELECT parent_id FROM subject_edges WHERE child_id {not_dead}")
        if has("subject_relations"):
            seeds.append(
                "SELECT from_subject_id FROM subject_relations"
                f" WHERE to_subject_id {not_dead}")
            seeds.append(
                "SELECT to_subject_id FROM subject_relations"
                f" WHERE from_subject_id {not_dead}")
        if has("subject_aliases"):
            seeds.append(
                "SELECT sa.subject_node_id FROM subject_aliases sa"
                f" WHERE NOT {dead('sa.exam_context')}")
        if has("question_topic_assignments"):
            seeds.append(
                "SELECT qta.subject_node_id FROM question_topic_assignments qta"
                f" WHERE NOT {dead('qta.exam_context')}")
        parents = ["SELECT sn.parent_id FROM subject_nodes sn"
                   " JOIN m037_up u ON sn.id = u.id"]
        if has("subject_edges"):
            parents.append("SELECT se.parent_id FROM subject_edges se"
                           " JOIN m037_up u ON se.child_id = u.id")
        conn.execute(
            "INSERT INTO m037_keep_subjects"
            " WITH RECURSIVE m037_up(id) AS ("
            f" {' UNION '.join(seeds)}"
            f" UNION {' UNION '.join(parents)})"
            " SELECT id FROM m037_up"
            " WHERE id IN (SELECT id FROM m037_dead_subjects)")
        conn.execute(
            "INSERT INTO m037_gone_subjects SELECT id FROM m037_dead_subjects"
            " WHERE id NOT IN (SELECT id FROM m037_keep_subjects)")

    # ---- tags ---------------------------------------------------------
    if has("tags"):
        conn.execute(
            "INSERT INTO m037_dead_tags SELECT t.id FROM tags t"
            f" WHERE {dead('t.exam_context')}")
        seeds = ["SELECT parent_id FROM tags"
                 " WHERE id NOT IN (SELECT id FROM m037_dead_tags)"]
        if has("entry_tags", "question_entries"):
            seeds.append("SELECT et.tag_id FROM entry_tags et"
                         " JOIN question_entries qe ON qe.id = et.question_entry_id")
        if has("question_tags"):
            seeds.append("SELECT qt.tag_id FROM question_tags qt"
                         f" WHERE NOT {dead('qt.exam_context')}")
        conn.execute(
            "INSERT INTO m037_keep_tags"
            " WITH RECURSIVE m037_up(id) AS ("
            f" {' UNION '.join(seeds)}"
            " UNION SELECT t.parent_id FROM tags t JOIN m037_up u ON t.id = u.id)"
            " SELECT id FROM m037_up WHERE id IN (SELECT id FROM m037_dead_tags)")

    gone = "IN (SELECT id FROM m037_gone_subjects)"
    surviving = ("SELECT id FROM subject_nodes"
                 " WHERE id NOT IN (SELECT id FROM m037_gone_subjects)")

    # ---- rows that would block or outlive the subject delete ----------
    if has("subject_relation_rejections"):
        # NO ACTION on subject_nodes: these would refuse the delete.
        conn.execute(
            "DELETE FROM subject_relation_rejections"
            f" WHERE from_subject_id {gone} OR to_subject_id {gone}")
    if has("subject_delete_batches", "subject_delete_batch_items"):
        # The m018 journal names subjects by id with no foreign key. A batch
        # that names a removed subject and no subject that survives would
        # point at nothing; its items cascade with it.
        conn.execute(
            "INSERT INTO m037_gone_batches SELECT b.id FROM subject_delete_batches b"
            f" WHERE (b.root_node_id {gone} OR EXISTS (SELECT 1 FROM"
            " subject_delete_batch_items i WHERE i.batch_id = b.id"
            f" AND i.subject_node_id {gone}))"
            f" AND b.root_node_id NOT IN ({surviving})"
            " AND NOT EXISTS (SELECT 1 FROM subject_delete_batch_items i"
            f" WHERE i.batch_id = b.id AND i.subject_node_id IN ({surviving}))")
        conn.execute("DELETE FROM subject_delete_batches"
                     " WHERE id IN (SELECT id FROM m037_gone_batches)")
    if has("dimension_delete_batches"):
        # The m024 journal carries exam_id with no foreign key.
        conn.execute(
            "DELETE FROM dimension_delete_batches"
            " WHERE exam_id NOT IN (SELECT id FROM exam_contexts)")

    # ---- the name-keyed rows, children first --------------------------
    if has("question_tags"):
        conn.execute(f"DELETE FROM question_tags WHERE {dead('exam_context')}")
    if has("question_topic_assignments"):
        conn.execute(
            f"DELETE FROM question_topic_assignments WHERE {dead('exam_context')}")
    if has("question_analyses"):
        live_refs = []
        if has("question_tags"):
            live_refs.append("SELECT question_analysis_id FROM question_tags")
        if has("question_topic_assignments"):
            live_refs.append(
                "SELECT question_analysis_id FROM question_topic_assignments")
        keep = (f" AND id NOT IN ({' UNION '.join(live_refs)})"
                if live_refs else "")
        # The debris rows of both children are gone by now, so what still
        # references an analysis is a row that is not debris.
        conn.execute(
            f"DELETE FROM question_analyses WHERE {dead('exam_context')}{keep}")
    if has("subject_aliases"):
        conn.execute(
            f"DELETE FROM subject_aliases WHERE {dead('exam_context')}"
            " AND subject_node_id NOT IN (SELECT id FROM m037_keep_subjects)")
    if has("tags"):
        # One statement: tags.parent_id is NO ACTION, checked when the
        # statement ends, so parents and children may go together.
        conn.execute(
            "DELETE FROM tags WHERE id IN (SELECT id FROM m037_dead_tags)"
            " AND id NOT IN (SELECT id FROM m037_keep_tags)")
    if has("subject_nodes"):
        # Cascades edges, weights, relations, entry mappings (none live, by
        # rule 1), hierarchy tags and Anki rejections.
        conn.execute(f"DELETE FROM subject_nodes WHERE id {gone}")

    # ---- question sources (rule 2) ------------------------------------
    if has("question_sources"):
        refs = []
        for table in ("review_sessions", "session_templates", "planned_sessions"):
            if has(table):
                refs.append(f"SELECT question_source_id FROM {table}"
                            " WHERE question_source_id IS NOT NULL")
        in_use = (f"id IN ({' UNION '.join(refs)})" if refs else "0")
        conn.execute(
            "UPDATE question_sources SET exam_context = NULL"
            f" WHERE {dead('exam_context')} AND {in_use}")
        conn.execute(f"DELETE FROM question_sources WHERE {dead('exam_context')}")

    for t in ("m037_dead_subjects", "m037_keep_subjects", "m037_gone_subjects",
              "m037_dead_tags", "m037_keep_tags", "m037_gone_batches"):
        conn.execute(f"DROP TABLE temp.{t}")
