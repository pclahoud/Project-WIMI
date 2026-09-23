"""
One-time import script: consolidated_wrong_questions.csv -> WIMI user database.

Imports question entries from the Anki CSV export into the WIMI personal database.

Usage:
    python import_csv.py [--dry-run]
"""

import csv
import sqlite3
import sys
from datetime import datetime, date
from pathlib import Path
from collections import defaultdict

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CSV_PATH = Path(r"path\to\consolidated_wrong_questions.csv")
DB_PATH = Path(r"path\to\app_data\users\user_001_demo_user.db")

USER_ID = 1

# Exam context mapping: CSV exam_context -> DB exam name
EXAM_MAP = {
    "Surgery": "Surgery Shelf Exam",  # already exists
}

# New exams to create (CSV name -> DB name)
NEW_EXAMS = {
    "Family Medicine": "Family Medicine Shelf",
    "OBGYN": "OBGYN Shelf",
    "Psychiatry": "Psychiatry Shelf",
}

# Hierarchy levels for new exams (same as Surgery)
NEW_EXAM_HIERARCHY = '["System", "Subsystem", "Topic", "Subtopic", "Child"]'

# Source mapping: CSV source -> (DB source_name, source_type)
# Existing sources: Amboss (id=1), UWorld (id=2), NBME (id=3)
NEW_SOURCES = {
    "USMLE": ("USMLE", "official_prep"),
}

# Tag name mapping: CSV mistake type (normalized) -> DB tag name
# Built from analysis — maps camelCase CSV names to existing DB tag names
TAG_NAME_MAP = {
    "KnowledgeGap": "Knowledge Gap",
    "MemoryFailure": "Memory Failure",
    "SubjectMisunderstanding": "Misunderstanding",
    "MixingUpConcepts": "Mixing up two subjects",
    "MisreadQuestion": "Misread Question",
    "LackOfRecognizingKeyIndicators": "Lack of Recognizing Key Indicators",
    "CalculationError": "Calculation Error",
    "CarelessMistake": "Careless Mistake",
    "IncompleteSolution": "Incomplete Solution",
    "WrongApproach": "Wrong Approach",
    "Rushing": "Rushing",
    "TimePressure": "Time Pressure",
    "SecondGuessing": "Second-Guessing",
    "EliminationError": "Elimination Error",
    "PoorPrioritization": "Poor Prioritization",
    "WrongGuessStrategy": "Wrong Guess Strategy",
    "AnxietyRelated": "Anxiety Related",
    "FocusProblem": "Focus Problem",
    "FatigueRelated": "Fatigue Related",
}

# Subject dimension ID for "Systems" dimension in Surgery Shelf Exam
# (the CSV system/topic/sub_topic maps to dimension 4 based on analysis)
SURGERY_SYSTEM_DIMENSION_ID = 4

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_or_create_source(db, source_name, source_type):
    """Get existing source ID or create a new one."""
    row = db.execute(
        "SELECT id FROM question_sources WHERE source_name = ? AND source_type = ?",
        (source_name, source_type)
    ).fetchone()
    if row:
        return row["id"]
    cursor = db.execute(
        "INSERT INTO question_sources (user_id, source_name, source_type, is_active) VALUES (?, ?, ?, 1)",
        (USER_ID, source_name, source_type)
    )
    return cursor.lastrowid


def get_or_create_exam(db, exam_name, hierarchy_levels=None):
    """Get existing exam context ID or create a new one."""
    row = db.execute(
        "SELECT id FROM exam_contexts WHERE exam_name = ?",
        (exam_name,)
    ).fetchone()
    if row:
        return row["id"]

    if hierarchy_levels is None:
        hierarchy_levels = NEW_EXAM_HIERARCHY

    cursor = db.execute(
        """INSERT INTO exam_contexts (user_id, exam_name, exam_description, is_active, default_hierarchy_levels)
           VALUES (?, ?, ?, 1, ?)""",
        (USER_ID, exam_name, "", hierarchy_levels)
    )
    return cursor.lastrowid


def get_or_create_tag(db, tag_name, exam_context_name):
    """Get existing tag ID or create a new one."""
    # Try exact match first (for this exam context or global)
    row = db.execute(
        "SELECT id FROM tags WHERE tag_name = ? AND (exam_context = ? OR exam_context IS NULL) LIMIT 1",
        (tag_name, exam_context_name)
    ).fetchone()
    if row:
        return row["id"]

    # Try any exam context
    row = db.execute(
        "SELECT id FROM tags WHERE tag_name = ? LIMIT 1",
        (tag_name,)
    ).fetchone()
    if row:
        return row["id"]

    # Create new tag
    cursor = db.execute(
        """INSERT INTO tags (exam_context, tag_name, tag_category, is_active, usage_count, is_group, display_order)
           VALUES (?, ?, 'mistake_type', 1, 0, 0, 999)""",
        (exam_context_name, tag_name)
    )
    print(f"  [NEW TAG] Created tag: '{tag_name}' (id={cursor.lastrowid})")
    return cursor.lastrowid


def resolve_tag_name(csv_mistake_type):
    """Map a CSV mistake type to a DB tag name."""
    # Direct map
    if csv_mistake_type in TAG_NAME_MAP:
        return TAG_NAME_MAP[csv_mistake_type]
    # Return as-is if no mapping (will try DB lookup)
    return csv_mistake_type


def get_or_create_subject_node(db, exam_context_name, parent_id, name, level_type, dimension_id=None):
    """Get existing subject node or create a new one."""
    if parent_id is None:
        row = db.execute(
            """SELECT id FROM subject_nodes
               WHERE exam_context = ? AND parent_id IS NULL AND name = ?
               AND (dimension_id = ? OR (dimension_id IS NULL AND ? IS NULL))""",
            (exam_context_name, name, dimension_id, dimension_id)
        ).fetchone()
    else:
        row = db.execute(
            """SELECT id FROM subject_nodes
               WHERE exam_context = ? AND parent_id = ? AND name = ?
               AND (dimension_id = ? OR (dimension_id IS NULL AND ? IS NULL))""",
            (exam_context_name, parent_id, name, dimension_id, dimension_id)
        ).fetchone()
    if row:
        return row["id"]

    cursor = db.execute(
        """INSERT INTO subject_nodes (exam_context, parent_id, name, level_type, dimension_id, sort_order)
           VALUES (?, ?, ?, ?, ?, 1)""",
        (exam_context_name, parent_id, name, level_type, dimension_id)
    )
    return cursor.lastrowid


def clean_system_name(system_val):
    """Clean up system names with prefixes like 'lower airways and pleura: Respiratory system'."""
    if ":" in system_val:
        # Take the part after the colon as the real system name
        return system_val.split(":", 1)[1].strip()
    return system_val.strip()


def parse_date(date_str):
    """Parse a CSV date string into a date object."""
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d %H:%M:%S")
    except (ValueError, AttributeError):
        return datetime.now()


def is_bad_row(row):
    """Check if a row contains parsing error data."""
    for val in row.values():
        if val and ("BamlValidationError" in str(val) or "ParsingError" in str(val)):
            return True
    return False


# ---------------------------------------------------------------------------
# Main import
# ---------------------------------------------------------------------------

def run_import(dry_run=False):
    print(f"{'[DRY RUN] ' if dry_run else ''}WIMI CSV Import")
    print(f"  CSV: {CSV_PATH}")
    print(f"  DB:  {DB_PATH}")
    print()

    if not CSV_PATH.exists():
        print(f"ERROR: CSV file not found: {CSV_PATH}")
        return 1
    if not DB_PATH.exists():
        print(f"ERROR: Database not found: {DB_PATH}")
        return 1

    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")

    # Read CSV
    rows = []
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    print(f"  CSV rows: {len(rows)}")

    # --- Phase 1: Create exam contexts ---
    print("\n--- Phase 1: Exam Contexts ---")
    exam_id_map = {}  # CSV exam_context -> DB exam_context_id
    exam_name_map = {}  # CSV exam_context -> DB exam_name

    for csv_ctx, db_name in EXAM_MAP.items():
        eid = get_or_create_exam(db, db_name)
        exam_id_map[csv_ctx] = eid
        exam_name_map[csv_ctx] = db_name
        print(f"  {csv_ctx} -> '{db_name}' (id={eid}, existing)")

    for csv_ctx, db_name in NEW_EXAMS.items():
        eid = get_or_create_exam(db, db_name)
        exam_id_map[csv_ctx] = eid
        exam_name_map[csv_ctx] = db_name
        print(f"  {csv_ctx} -> '{db_name}' (id={eid}, new)")

    # --- Phase 2: Create sources ---
    print("\n--- Phase 2: Sources ---")
    source_id_map = {}  # source name -> id

    for src_name in ["Amboss", "UWorld", "NBME"]:
        row = db.execute("SELECT id FROM question_sources WHERE source_name = ?", (src_name,)).fetchone()
        if row:
            source_id_map[src_name] = row["id"]
            print(f"  {src_name} -> id={row['id']} (existing)")

    for csv_name, (db_name, db_type) in NEW_SOURCES.items():
        sid = get_or_create_source(db, db_name, db_type)
        source_id_map[csv_name] = sid
        print(f"  {csv_name} -> id={sid}")

    # --- Phase 3: Build tag lookup ---
    print("\n--- Phase 3: Tags ---")
    # Pre-cache all existing tags
    tag_cache = {}  # tag_name (lowercase) -> id

    existing_tags = db.execute("SELECT id, tag_name FROM tags").fetchall()
    for t in existing_tags:
        tag_cache[t["tag_name"].lower()] = t["id"]
    print(f"  Existing tags: {len(existing_tags)}")

    # --- Phase 4: Group rows by session ---
    print("\n--- Phase 4: Sessions ---")
    sessions = defaultdict(list)  # (exam_context, session_id) -> [rows]
    skipped_bad = 0
    skipped_no_exam = 0

    for row in rows:
        if is_bad_row(row):
            skipped_bad += 1
            continue

        csv_ctx = row.get("exam_context", "").strip()
        if csv_ctx not in exam_id_map:
            skipped_no_exam += 1
            continue

        session_key = (csv_ctx, row.get("session_ID", "0").strip())
        sessions[session_key].append(row)

    print(f"  Unique sessions: {len(sessions)}")
    print(f"  Skipped (bad data): {skipped_bad}")
    print(f"  Skipped (unknown exam): {skipped_no_exam}")

    # --- Phase 5: Import ---
    print("\n--- Phase 5: Import ---")
    total_entries = 0
    total_sessions = 0
    total_subject_mappings = 0
    total_tag_mappings = 0
    new_tags_created = 0

    for (csv_ctx, session_id), session_rows in sorted(sessions.items()):
        exam_id = exam_id_map[csv_ctx]
        exam_name = exam_name_map[csv_ctx]

        # Determine session source (most common source in the session)
        source_counts = defaultdict(int)
        for r in session_rows:
            source_counts[r.get("source", "").strip()] += 1
        primary_source = max(source_counts, key=source_counts.get) if source_counts else "Amboss"
        source_id = source_id_map.get(primary_source)

        # Session date = earliest entry date
        session_dates = []
        for r in session_rows:
            d = r.get("date", "").strip()
            if d:
                session_dates.append(parse_date(d))
        session_date = min(session_dates) if session_dates else datetime.now()

        # Create review session
        session_name = f"Imported Session {session_id} ({csv_ctx})"

        if not dry_run:
            cursor = db.execute(
                """INSERT INTO review_sessions
                   (user_id, exam_context_id, question_source_id, session_name,
                    date_encountered, total_questions, total_incorrect,
                    entries_completed, session_status, started_at, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?)""",
                (USER_ID, exam_id, source_id, session_name,
                 session_date.strftime("%Y-%m-%d"), len(session_rows), len(session_rows),
                 len(session_rows),
                 session_date.strftime("%Y-%m-%d %H:%M:%S"),
                 session_dates[-1].strftime("%Y-%m-%d %H:%M:%S") if session_dates else None)
            )
            review_session_id = cursor.lastrowid
        else:
            review_session_id = -1

        total_sessions += 1

        # Import entries
        for entry_order, r in enumerate(session_rows, 1):
            qid = r.get("qid", "").strip()
            user_answer = r.get("answer_chosen", "").strip() or "(blank)"
            correct_answer = r.get("correct_answer", "").strip() or "(blank)"
            reflection = r.get("reflection", "").strip() or None

            # Confidence -> perceived_difficulty (inverted, clamped to 1-5)
            # CSV confidence is 1-10; DB perceived_difficulty is 1-5
            try:
                confidence = int(r.get("confidence", "5").strip())
                # Map: conf 1-2 -> diff 5, conf 3-4 -> diff 4, conf 5-6 -> diff 3, conf 7-8 -> diff 2, conf 9-10 -> diff 1
                perceived_difficulty = max(1, min(5, 6 - (confidence + 1) // 2))
            except (ValueError, TypeError):
                perceived_difficulty = 3

            entry_date = parse_date(r.get("date", ""))

            if not dry_run:
                cursor = db.execute(
                    """INSERT INTO question_entries
                       (review_session_id, entry_order, question_id,
                        user_answer, correct_answer, perceived_difficulty,
                        reflection, is_draft, created_at, updated_at, completed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, FALSE, ?, ?, ?)""",
                    (review_session_id, entry_order, qid,
                     user_answer, correct_answer, perceived_difficulty,
                     reflection, entry_date.strftime("%Y-%m-%d %H:%M:%S"),
                     entry_date.strftime("%Y-%m-%d %H:%M:%S"),
                     entry_date.strftime("%Y-%m-%d %H:%M:%S"))
                )
                entry_id = cursor.lastrowid
            else:
                entry_id = -1

            total_entries += 1

            # --- Subject mappings ---
            system_name = clean_system_name(r.get("system", "").strip())
            topic_name = r.get("topic", "").strip()
            sub_topic_name = r.get("sub_topic", "").strip()

            if system_name and not dry_run:
                # For Surgery, subjects are under dimension 4 (Systems)
                # For new exams, no dimension (dimension_id=None)
                dim_id = SURGERY_SYSTEM_DIMENSION_ID if csv_ctx == "Surgery" else None

                # Level 1: System
                hierarchy = db.execute(
                    "SELECT default_hierarchy_levels FROM exam_contexts WHERE id = ?",
                    (exam_id,)
                ).fetchone()
                import json
                levels = json.loads(hierarchy["default_hierarchy_levels"])

                system_node_id = get_or_create_subject_node(
                    db, exam_name, None, system_name, levels[0], dim_id
                )
                leaf_node_id = system_node_id

                # Level 2: Topic
                if topic_name:
                    topic_node_id = get_or_create_subject_node(
                        db, exam_name, system_node_id, topic_name, levels[1], dim_id
                    )
                    leaf_node_id = topic_node_id

                    # Level 3: Sub-topic
                    if sub_topic_name:
                        sub_node_id = get_or_create_subject_node(
                            db, exam_name, topic_node_id, sub_topic_name, levels[2], dim_id
                        )
                        leaf_node_id = sub_node_id

                # Map entry to the most specific (leaf) subject node
                db.execute(
                    """INSERT INTO entry_subject_mappings (question_entry_id, subject_node_id, mapping_type)
                       VALUES (?, ?, 'primary')""",
                    (entry_id, leaf_node_id)
                )
                total_subject_mappings += 1

            # --- Tag mappings ---
            mistake_types = r.get("mistake_types", "").strip()
            if mistake_types and not dry_run:
                for mt in mistake_types.split("|"):
                    mt = mt.strip()
                    if not mt:
                        continue

                    tag_name = resolve_tag_name(mt)
                    tag_name_lower = tag_name.lower()

                    if tag_name_lower not in tag_cache:
                        # Create new tag
                        tag_id = get_or_create_tag(db, tag_name, exam_name)
                        tag_cache[tag_name_lower] = tag_id
                        new_tags_created += 1
                    else:
                        tag_id = tag_cache[tag_name_lower]

                    db.execute(
                        """INSERT INTO entry_tags (question_entry_id, tag_id)
                           VALUES (?, ?)""",
                        (entry_id, tag_id)
                    )
                    total_tag_mappings += 1

    # --- Commit ---
    if not dry_run:
        db.commit()
        print("\n  Committed to database.")
    else:
        print("\n  [DRY RUN] No changes written.")

    db.close()

    # --- Summary ---
    print("\n" + "=" * 50)
    print("  IMPORT SUMMARY")
    print("=" * 50)
    print(f"  Sessions created:        {total_sessions}")
    print(f"  Entries imported:         {total_entries}")
    print(f"  Subject mappings:         {total_subject_mappings}")
    print(f"  Tag mappings:             {total_tag_mappings}")
    print(f"  New tags created:         {new_tags_created}")
    print(f"  Skipped (bad data):       {skipped_bad}")
    print(f"  Skipped (unknown exam):   {skipped_no_exam}")

    return 0


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    sys.exit(run_import(dry_run=dry_run))
