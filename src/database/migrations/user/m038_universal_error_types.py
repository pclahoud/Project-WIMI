"""User DB migration v38 -- one library of error types, and a list per exam (#888).

Decided by the owner on #888 (2026-11-06), every decision recorded there under
an *Owner* heading. Plan: ``docs/planning/UNIVERSAL_ERROR_TYPES_PLAN.md``.

Before this, every error type (a ``tags`` row) was filed under one exam's name
in ``tags.exam_context``. ``seed_default_tags`` copied the same sixteen
defaults under each exam, so a profile held one copy per exam. Two things went
wrong because of it. A permanent delete removed the exam's copies, and through
``entry_tags``' cascade removed them from other exams' entries that carried
them (#887). And analytics, which group by tag id, drew two slices named
*Knowledge Gap* for an exam whose entries carried two copies.

After this:

* **The library.** Each error type is one ``tags`` row with
  ``exam_context`` NULL. Copies are merged on (group name, type name), groups
  on name alone (decision 1).
* **The exam's list.** ``exam_error_types`` (new) says which types each exam's
  picker offers, so an exam can have types another does not (decision 4).
  It cascades from ``exam_contexts``, so a permanent delete removes the list
  and never a type.
* **Which exams have had a list.** ``exam_error_types_seeded`` (new) holds
  every exam whose list has ever held a row: here, every exam this migration
  gives a non-empty list. ``seed_default_tags`` offers the defaults only to an
  exam that is not in it, so emptying a list with *Remove from this exam*
  does not bring the defaults back. An exam with nothing filed and no entry
  carrying a type is left out, and is offered the defaults when its entry
  form first opens, as before.

Choosing the surviving copy (decision 2)
----------------------------------------
Within a set of copies, a copy whose definition differs from the shipped
default beats one that does not. Between two such edits, the copy carried by
more entries wins, then the lowest id. The colour, display order and
everything else come from the same survivor. A survivor is active if any copy
was. A losing edited definition is written to the log, so it is not lost
silently. On the owner's profile (#888 comment 12079) no two copies differed,
so the rule never fires there.

Building the lists (before merging, while the filing still says whose a type was)
---------------------------------------------------------------------------------
Each exam lists every type and group filed under its name, plus every type its
own entries carry, plus the group of anything listed. All of these are mapped
to survivors. So nothing an entry shows is missing from its exam's picker.

The rebuild (decision 3)
------------------------
``tags`` is rebuilt for two reasons. ``exam_context`` was NOT NULL, and
``UNIQUE(exam_context, tag_name)`` is a table constraint that cannot be dropped
in place. Once ``exam_context`` is NULL, that constraint would enforce nothing
(SQLite treats NULLs as distinct). The rebuilt table replaces it with
``idx_unique_tag_in_group`` on ``(IFNULL(parent_id, 0), tag_name,
IFNULL(is_group, 0))``, which is decision 1's key.

``entry_tags`` and ``question_tags`` reference ``tags`` with ``ON DELETE
CASCADE``. Foreign keys are on and cannot be switched off inside a transaction,
so dropping ``tags`` would empty them. They are moved out first: rows into
holding tables, the tables dropped, ``tags`` rebuilt, and both recreated from
their own ``sqlite_master`` DDL and indexes with every row and id. This is
m036's order. Every AUTOINCREMENT sequence is carried over. Every view is
dropped first and recreated from its own DDL afterwards, because a rename
re-validates views and two of them read ``entry_tags``. A view holds no data.

Mechanics
---------
``BEGIN`` is the first statement, so the whole migration commits or none of it
does (m036). Every statement and constant is inside ``upgrade`` because the
runner checksums that function alone (m037's docstring). The shipped default
definitions are therefore copied here, and
``test_the_defaults_match_tags_py`` holds them equal to ``tags.py``.
Idempotent: a profile that already has ``exam_error_types`` is left alone.
"""
from __future__ import annotations

import sqlite3

VERSION = 38
NAME = "universal_error_types"


def upgrade(conn: sqlite3.Connection) -> None:
    import logging

    if not conn.in_transaction:
        conn.execute("BEGIN")

    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "tags" not in tables or "exam_error_types" in tables:
        # A partial registry without tags, or already applied.
        return

    defaults = {
        'Knowledge Issues': 'Mistakes caused by gaps or errors in what you know.',
        'Reading & Interpretation': 'Mistakes from misreading or misinterpreting what the question asked.',
        'Execution Errors': 'Mistakes made while working the problem, even though you knew the material.',
        'Test Strategy': 'Mistakes in how you played the test itself — timing, guessing, and answer changes.',
        'Mental & Physical State': 'Mistakes influenced by how you felt — stress, focus, or energy.',
        'Knowledge Gap': 'You never learned or covered this material.',
        'Memory Failure': "You studied this before but couldn't recall it when it mattered.",
        'Misunderstanding': 'You learned the material but understood it incorrectly.',
        'Misread Question': 'You misread or overlooked key wording in the question.',
        'Calculation Error': 'You set up the problem correctly but made an arithmetic slip.',
        'Careless Mistake': 'You knew the answer but slipped through haste or inattention.',
        'Incomplete Solution': "You started down the right path but didn't carry the work to completion.",
        'Wrong Approach': "You chose a method or strategy that couldn't solve this problem.",
        'Time Pressure': 'Running low on time forced you to rush or abandon the question.',
        'Second-Guessing': 'You changed a correct answer to a wrong one.',
        'Elimination Error': 'You ruled out the correct answer while narrowing the choices.',
        'Poor Prioritization': 'You spent your time on the wrong questions or in the wrong order.',
        'Wrong Guess Strategy': "You had to guess, and your guessing approach didn't pay off.",
        'Anxiety Related': 'Nervousness or stress interfered with your thinking on this question.',
        'Focus Problem': 'You lost concentration or got distracted while answering.',
        'Fatigue Related': 'Tiredness or low energy dulled your performance on this question.',
    }

    log = logging.getLogger("database.migrations.user.m038")
    has_et = "entry_tags" in tables
    has_qt = "question_tags" in tables
    has_exams = "exam_contexts" in tables
    has_sessions = has_et and {"question_entries", "review_sessions"} <= tables

    # A parent that names no row would fail the rebuilt table's foreign key,
    # and the key below already treats it as top level.
    conn.execute("UPDATE tags SET parent_id = NULL WHERE parent_id IS NOT NULL"
                 " AND parent_id NOT IN (SELECT id FROM tags)")

    # ---- 1. every copy, its key, and its use -------------------------
    rows = {r[0]: r for r in conn.execute(
        "SELECT id, exam_context, tag_name, description, parent_id,"
        " IFNULL(is_group, 0), IFNULL(is_active, 1) FROM tags")}
    usage = {}
    if has_et:
        usage = dict(conn.execute(
            "SELECT tag_id, COUNT(*) FROM entry_tags GROUP BY tag_id").fetchall())

    def key(tag_id):
        _, _, name, _, parent, is_group, _ = rows[tag_id]
        group = rows[parent][2] if parent in rows else None
        return (group, name, bool(is_group))

    sets = {}
    for tag_id in sorted(rows):
        sets.setdefault(key(tag_id), []).append(tag_id)

    def edited(tag_id):
        _, _, name, description, _, _, _ = rows[tag_id]
        return (description or "") != (defaults.get(name) or "")

    survivor_of = {}
    for k, copies in sets.items():
        ranked = sorted(copies, key=lambda t: (not edited(t), -usage.get(t, 0), t))
        winner = ranked[0]
        for t in copies:
            survivor_of[t] = winner
        lost = {rows[t][3] for t in copies if t != winner and edited(t)
                and (rows[t][3] or "") != (rows[winner][3] or "")}
        for text in sorted(lost):
            log.warning("m038: error type %r kept one definition of several;"
                        " the other read: %r", k[1], text)

    # ---- 2. the lists, before anything moves -------------------------
    lists = {}   # exam id -> set of survivor ids
    if has_exams:
        exams = conn.execute("SELECT id, exam_name FROM exam_contexts").fetchall()
        by_name = {}
        for tag_id, row in rows.items():
            by_name.setdefault(row[1], set()).add(tag_id)
        for exam_id, exam_name in exams:
            listed = {survivor_of[t] for t in by_name.get(exam_name, ())}
            if has_sessions:
                for (t,) in conn.execute(
                        "SELECT DISTINCT et.tag_id FROM entry_tags et"
                        " JOIN question_entries qe ON qe.id = et.question_entry_id"
                        " JOIN review_sessions rs ON rs.id = qe.review_session_id"
                        " WHERE rs.exam_context_id = ?", (exam_id,)):
                    if t in survivor_of:
                        listed.add(survivor_of[t])
            for t in list(listed):
                parent = rows[t][4]
                if parent in survivor_of:
                    listed.add(survivor_of[parent])
            lists[exam_id] = listed

    # ---- 3. repoint, then remove the copies --------------------------
    moved = [(w, t) for t, w in survivor_of.items() if t != w]
    for winner, loser in moved:
        if has_et:
            # OR IGNORE: an entry that carried both copies keeps one.
            conn.execute("UPDATE OR IGNORE entry_tags SET tag_id = ? WHERE tag_id = ?",
                         (winner, loser))
        if has_qt:
            conn.execute("UPDATE OR IGNORE question_tags SET tag_id = ? WHERE tag_id = ?",
                         (winner, loser))
        conn.execute("UPDATE tags SET parent_id = ? WHERE parent_id = ?",
                     (winner, loser))
    for winner in {w for w, _ in moved}:
        conn.execute(
            "UPDATE tags SET is_active = 1 WHERE id = ? AND EXISTS (SELECT 1 FROM"
            " tags t WHERE t.is_active AND t.id IN (%s))"
            % ",".join(str(t) for t, w in survivor_of.items() if w == winner),
            (winner,))
    if moved:
        losers = ",".join(str(t) for _, t in moved)
        if has_et:
            conn.execute(f"DELETE FROM entry_tags WHERE tag_id IN ({losers})")
        if has_qt:
            conn.execute(f"DELETE FROM question_tags WHERE tag_id IN ({losers})")
        conn.execute(f"DELETE FROM tags WHERE id IN ({losers})")

    # ---- 4. rebuild tags with exam_context nullable -------------------
    def ddl(table):
        return conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,)).fetchone()[0]

    def index_ddl(table):
        return [r[0] for r in conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ?"
            " AND sql IS NOT NULL", (table,))]

    seqs = dict(conn.execute("SELECT name, seq FROM sqlite_sequence").fetchall()) \
        if "sqlite_sequence" in tables else {}
    # Views read these tables (v_question_entry_summary, v_tag_usage_counts),
    # and a rename re-validates every view. They hold no data, so each is
    # dropped and recreated from its own DDL.
    views = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'view'").fetchall()
    for name, _ in views:
        conn.execute(f'DROP VIEW "{name}"')

    children = [t for t in ("entry_tags", "question_tags") if t in tables]
    held = {}
    for child in children:
        held[child] = (ddl(child), index_ddl(child))
        conn.execute(f"DROP TABLE IF EXISTS m038_hold_{child}")
        conn.execute(f"CREATE TABLE m038_hold_{child} AS SELECT * FROM {child}")
        conn.execute(f"DROP TABLE {child}")

    conn.execute("DROP TABLE IF EXISTS tags_m038")
    conn.execute("""
        CREATE TABLE tags_m038 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_context VARCHAR(50),
            tag_name VARCHAR(100) NOT NULL,
            tag_category VARCHAR(50) DEFAULT 'other',
            color_hex VARCHAR(7) DEFAULT '#2196F3',
            description TEXT,
            usage_count INTEGER DEFAULT 0,
            last_used_at TIMESTAMP,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            parent_id INTEGER REFERENCES tags(id) NULL,
            is_group BOOLEAN DEFAULT FALSE,
            display_order INTEGER DEFAULT 0
        )
    """)
    columns = ("id, tag_name, tag_category, color_hex, description, usage_count,"
               " last_used_at, is_active, created_at, updated_at, parent_id,"
               " is_group, display_order")
    # Copied without parents, which go back after the rename: while both
    # tables exist, tags_m038.parent_id REFERENCES the OLD tags, so dropping
    # it would break every child's reference.
    parents = conn.execute(
        "SELECT id, parent_id FROM tags WHERE parent_id IS NOT NULL").fetchall()
    conn.execute(f"INSERT INTO tags_m038 ({columns})"
                 f" SELECT {columns.replace(' parent_id,', ' NULL,')} FROM tags")
    conn.execute("DROP TABLE tags")
    conn.execute("ALTER TABLE tags_m038 RENAME TO tags")
    conn.executemany("UPDATE tags SET parent_id = ? WHERE id = ?",
                     [(parent, tag_id) for tag_id, parent in parents])
    conn.execute("CREATE INDEX idx_tags_exam ON tags(exam_context)")
    conn.execute("CREATE INDEX idx_tags_category ON tags(tag_category)")
    conn.execute("CREATE INDEX idx_tags_active ON tags(is_active)")
    conn.execute("CREATE INDEX idx_tags_parent ON tags(parent_id)")
    conn.execute(
        "CREATE UNIQUE INDEX idx_unique_tag_in_group"
        " ON tags(IFNULL(parent_id, 0), tag_name, IFNULL(is_group, 0))")

    for child in children:
        child_ddl, child_indexes = held[child]
        conn.execute(child_ddl)
        for statement in child_indexes:
            conn.execute(statement)
        conn.execute(f"INSERT INTO {child} SELECT * FROM m038_hold_{child}")
        conn.execute(f"DROP TABLE m038_hold_{child}")

    for name in ("tags", *children):
        if name not in seqs:
            continue
        if conn.execute("SELECT 1 FROM sqlite_sequence WHERE name = ?", (name,)).fetchone():
            conn.execute("UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = ?",
                         (seqs[name], name))
        else:
            conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)",
                         (name, seqs[name]))

    for _, sql in views:
        conn.execute(sql)

    # ---- 5. the per-exam lists ----------------------------------------
    if has_exams:
        conn.execute("""
            CREATE TABLE exam_error_types (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exam_context_id INTEGER NOT NULL
                    REFERENCES exam_contexts(id) ON DELETE CASCADE,
                tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                display_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(exam_context_id, tag_id)
            )
        """)
        conn.execute("CREATE INDEX idx_exam_error_types_tag ON exam_error_types(tag_id)")
        # Which exams have ever had a list. seed_default_tags offers the
        # defaults only to an exam not in here, so a list the student emptied
        # on purpose stays empty (#895 review).
        conn.execute("""
            CREATE TABLE exam_error_types_seeded (
                exam_context_id INTEGER PRIMARY KEY
                    REFERENCES exam_contexts(id) ON DELETE CASCADE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        for exam_id, listed in sorted(lists.items()):
            for tag_id in sorted(listed):
                conn.execute(
                    "INSERT INTO exam_error_types (exam_context_id, tag_id, display_order)"
                    " SELECT ?, id, IFNULL(display_order, 0) FROM tags WHERE id = ?",
                    (exam_id, tag_id))
            if listed:
                conn.execute("INSERT INTO exam_error_types_seeded (exam_context_id)"
                             " VALUES (?)", (exam_id,))
