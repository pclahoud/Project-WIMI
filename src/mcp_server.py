"""
WIMI MCP Server — exposes database operations as tools for Claude Code.

Allows Claude to interact with the WIMI application's data layer
to verify functionality, run smoke tests, and inspect state.

Works in both development and frozen (PyInstaller) modes:
    Development: python run_wimi.py --mcp-server
    Compiled:    WIMI.exe --mcp-server
"""

import json
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP


# ---------------------------------------------------------------------------
# Path detection (dev vs frozen)
# ---------------------------------------------------------------------------

def _get_app_data_dir():
    """Determine app_data path for both dev and frozen modes."""
    is_frozen = getattr(sys, 'frozen', False)
    if is_frozen:
        exe_path = Path(sys.executable)
        if sys.platform == 'darwin' and '.app/Contents/MacOS' in str(exe_path):
            project_root = exe_path.parents[3]
        else:
            project_root = exe_path.parent
    else:
        # src/mcp_server.py -> src -> project root
        project_root = Path(__file__).parent.parent
    return project_root / 'app_data'


APP_DATA_DIR = _get_app_data_dir()


# ---------------------------------------------------------------------------
# Lazy database connection
# ---------------------------------------------------------------------------

_db_instance = None
_master_db = None


def _get_master_db():
    """Get or create MasterDatabase connection."""
    global _master_db
    if _master_db is None:
        from database import MasterDatabase
        db_path = APP_DATA_DIR / 'users.db'
        if not db_path.exists():
            return None
        _master_db = MasterDatabase(data_dir=APP_DATA_DIR)
    return _master_db


def _get_user_db(user_id: int = None):
    """Get or create UserDatabase for a specific user."""
    global _db_instance
    master = _get_master_db()
    if master is None:
        return None

    if user_id is None:
        # Default to first user
        users = master.get_all_users()
        if not users:
            return None
        user = users[0]
        user_id = user.id
    else:
        user = master.get_user(user_id)
        if not user:
            return None

    # Check if we already have a connection for this user
    if _db_instance is not None and _db_instance.user_id == user_id:
        return _db_instance

    from database import UserDatabase
    db_path = APP_DATA_DIR / 'users' / user.database_filename
    if not db_path.exists():
        return None

    _db_instance = UserDatabase(db_path, user.id, user.username)
    return _db_instance


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "wimi-db",
    instructions="WIMI database server. Provides tools to interact with the WIMI application's SQLite databases for testing and verification."
)


# -- User & Exam listing ----------------------------------------------------

@mcp.tool()
def list_users() -> str:
    """List all users in the WIMI master database."""
    master = _get_master_db()
    if master is None:
        return json.dumps({"error": "Master database not found"})

    users = master.get_all_users()
    return json.dumps([
        {"id": u.id, "username": u.username, "display_name": u.display_name}
        for u in users
    ], indent=2)


@mcp.tool()
def list_exams(user_id: int = None) -> str:
    """List all exam contexts for a user. Defaults to first user if user_id not specified."""
    db = _get_user_db(user_id)
    if db is None:
        return json.dumps({"error": "User database not found"})

    db._ensure_phase2_schema()
    exams = db.get_all_exam_contexts(active_only=False)
    return json.dumps([
        {
            "id": e.id,
            "name": e.exam_name,
            "description": e.exam_description,
            "is_active": e.is_active,
            "hierarchy_levels": e.default_hierarchy_levels
        }
        for e in exams
    ], indent=2)


# -- Sessions ---------------------------------------------------------------

@mcp.tool()
def list_sessions(exam_context_id: int = None, user_id: int = None, limit: int = 10) -> str:
    """List review sessions, optionally filtered by exam context."""
    db = _get_user_db(user_id)
    if db is None:
        return json.dumps({"error": "User database not found"})

    db._ensure_phase4_schema()
    sessions = db.get_review_sessions(exam_context_id=exam_context_id, limit=limit)
    return json.dumps([
        {
            "id": s.id,
            "name": s.session_name,
            "exam_name": s.exam_name,
            "status": s.session_status,
            "date": s.date_encountered,
            "total_questions": s.total_questions,
            "total_incorrect": s.total_incorrect,
            "entries_completed": s.entries_completed,
            "duration_minutes": s.session_duration_minutes
        }
        for s in sessions
    ], indent=2)


# -- Entries -----------------------------------------------------------------

@mcp.tool()
def list_entries(
    exam_context_id: int = None,
    session_id: int = None,
    user_id: int = None,
    page: int = 1,
    per_page: int = 10
) -> str:
    """List question entries with pagination. Filter by exam or session."""
    db = _get_user_db(user_id)
    if db is None:
        return json.dumps({"error": "User database not found"})

    db._ensure_phase4_schema()
    entries, total = db.get_entries_paginated(
        exam_context_id=exam_context_id,
        session_id=session_id,
        page=page,
        per_page=per_page
    )
    return json.dumps({
        "total": total,
        "page": page,
        "per_page": per_page,
        "entries": [
            {
                "id": e.id,
                "question_id": e.question_id,
                "user_answer": e.user_answer,
                "correct_answer": e.correct_answer,
                "difficulty": e.perceived_difficulty,
                "is_draft": e.is_draft,
                "subjects": [s.name for s in (e.primary_subjects or [])],
                "tags": [t.tag_name for t in (e.tags or [])]
            }
            for e in entries
        ]
    }, indent=2)


@mcp.tool()
def get_entry_detail(entry_id: int, user_id: int = None) -> str:
    """Get full detail for a specific entry including context, media, notes."""
    db = _get_user_db(user_id)
    if db is None:
        return json.dumps({"error": "User database not found"})

    db._ensure_phase4_schema()
    result = db.get_entry_with_context(entry_id)
    if result is None:
        return json.dumps({"error": f"Entry {entry_id} not found"})

    return json.dumps(result, indent=2, default=str)


# -- Subject Hierarchy -------------------------------------------------------

@mcp.tool()
def get_subject_tree(exam_context_id: int, user_id: int = None) -> str:
    """Get the subject hierarchy tree for an exam context."""
    db = _get_user_db(user_id)
    if db is None:
        return json.dumps({"error": "User database not found"})

    exam = db.get_exam_context_config(exam_context_id)
    if not exam:
        return json.dumps({"error": f"Exam context {exam_context_id} not found"})

    def node_to_dict(node):
        d = {
            "id": node.id,
            "name": node.name,
            "level_type": node.level_type,
            "weight_low": node.exam_weight_low,
            "weight_high": node.exam_weight_high
        }
        if node.children:
            d["children"] = [node_to_dict(c) for c in node.children]
        return d

    hierarchy = db.get_subject_hierarchy(exam.exam_name)
    return json.dumps([node_to_dict(n) for n in hierarchy], indent=2)


@mcp.tool()
def search_subjects(exam_context_id: int, query: str, user_id: int = None) -> str:
    """Search subjects by name within an exam context."""
    db = _get_user_db(user_id)
    if db is None:
        return json.dumps({"error": "User database not found"})

    results = db.search_subjects(exam_context_id, query)
    return json.dumps(results, indent=2)


# -- Analytics ---------------------------------------------------------------

@mcp.tool()
def get_analytics_overview(exam_context_id: int = None, user_id: int = None) -> str:
    """Get high-level analytics overview (total entries, streaks, completion rate, etc.)."""
    db = _get_user_db(user_id)
    if db is None:
        return json.dumps({"error": "User database not found"})

    db._ensure_phase4_schema()
    overview = db.get_analytics_overview(exam_context_id)
    return json.dumps(overview, indent=2)


@mcp.tool()
def get_subject_analytics(exam_context_id: int = None, user_id: int = None, limit: int = 10) -> str:
    """Get mistake counts by subject for visualization."""
    db = _get_user_db(user_id)
    if db is None:
        return json.dumps({"error": "User database not found"})

    db._ensure_phase4_schema()
    data = db.get_subject_analytics(exam_context_id, limit=limit)
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def get_tag_analytics(exam_context_id: int = None, user_id: int = None) -> str:
    """Get mistake type distribution by tags."""
    db = _get_user_db(user_id)
    if db is None:
        return json.dumps({"error": "User database not found"})

    db._ensure_phase4_schema()
    data = db.get_tag_analytics(exam_context_id)
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def get_study_streak(exam_context_id: int = None, user_id: int = None) -> str:
    """Get study streak information."""
    db = _get_user_db(user_id)
    if db is None:
        return json.dumps({"error": "User database not found"})

    db._ensure_phase4_schema()
    data = db.get_study_streak(exam_context_id)
    return json.dumps(data, indent=2, default=str)


# -- Dimensions --------------------------------------------------------------

@mcp.tool()
def get_dimensions(exam_context_id: int, user_id: int = None) -> str:
    """Get exam dimensions for a multi-dimensional exam."""
    db = _get_user_db(user_id)
    if db is None:
        return json.dumps({"error": "User database not found"})

    db._ensure_phase7_schema()
    dims = db.get_exam_dimensions(exam_context_id)
    return json.dumps(dims, indent=2, default=str)


@mcp.tool()
def check_dimensions_enabled(exam_context_id: int, user_id: int = None) -> str:
    """Check if an exam uses multi-dimensional analysis."""
    db = _get_user_db(user_id)
    if db is None:
        return json.dumps({"error": "User database not found"})

    db._ensure_phase7_schema()
    uses = db.exam_uses_dimensions(exam_context_id)
    return json.dumps({"exam_context_id": exam_context_id, "uses_dimensions": uses})


# -- Preferences & Settings --------------------------------------------------

@mcp.tool()
def get_preferences(user_id: int = None) -> str:
    """Get user preferences/settings."""
    db = _get_user_db(user_id)
    if db is None:
        return json.dumps({"error": "User database not found"})

    prefs = db.get_preferences()
    if prefs is None:
        return json.dumps({"error": "No preferences found"})

    # Convert to dict manually since UserPreferences may not have to_dict
    return json.dumps({
        "user_id": prefs.user_id,
        "theme": getattr(prefs, 'theme', 'light'),
        "font_size_scale": getattr(prefs, 'font_size_scale', 1.0),
        "primary_color": getattr(prefs, 'primary_color_hex', '#2196F3'),
        "ui_density": getattr(prefs, 'ui_density', 'comfortable'),
    }, indent=2)


# -- Sources -----------------------------------------------------------------

@mcp.tool()
def list_sources(exam_context: str = None, user_id: int = None) -> str:
    """List question sources."""
    db = _get_user_db(user_id)
    if db is None:
        return json.dumps({"error": "User database not found"})

    db._ensure_phase4_schema()
    sources = db.get_question_sources(exam_context=exam_context)
    return json.dumps([
        {
            "id": s.id,
            "name": s.source_name,
            "type": s.source_type,
            "rating": s.user_rating
        }
        for s in sources
    ], indent=2)


# -- Timer Rounds ------------------------------------------------------------

@mcp.tool()
def get_timer_rounds(session_id: int, user_id: int = None) -> str:
    """Get timer rounds for a session."""
    db = _get_user_db(user_id)
    if db is None:
        return json.dumps({"error": "User database not found"})

    rounds = db.get_timer_rounds(session_id)
    return json.dumps([
        {
            "id": r.id,
            "round_number": r.round_number,
            "duration_minutes": r.duration_minutes,
            "started_at": r.started_at,
            "ended_at": r.ended_at,
            "actual_studied_seconds": r.actual_studied_seconds,
            "total_break_seconds": r.total_break_seconds
        }
        for r in rounds
    ], indent=2, default=str)


# -- Goals -------------------------------------------------------------------

@mcp.tool()
def get_goals(exam_context_id: int = None, user_id: int = None) -> str:
    """Get user goals and progress."""
    db = _get_user_db(user_id)
    if db is None:
        return json.dumps({"error": "User database not found"})

    db._ensure_phase6_schema()
    goals = db.get_user_goals(exam_context_id)
    return json.dumps(goals, indent=2, default=str)


# -- Entry Notes -------------------------------------------------------------

@mcp.tool()
def get_entry_notes(entry_id: int, user_id: int = None) -> str:
    """Get all notes for a specific entry."""
    db = _get_user_db(user_id)
    if db is None:
        return json.dumps({"error": "User database not found"})

    notes = db.get_entry_notes_list(entry_id)
    return json.dumps([
        {
            "id": n.id,
            "content_html": n.content_html[:200] if n.content_html else None,
            "linked_subject_ids": n.linked_subject_ids,
            "sort_order": n.sort_order
        }
        for n in notes
    ], indent=2, default=str)


# -- Health Check / Mixin Verification ---------------------------------------

@mcp.tool()
def verify_mixin_decomposition(user_id: int = None) -> str:
    """Verify that all mixin methods are accessible on UserDatabase.

    Tests that the class composition is working by checking key methods
    from each domain mixin exist and are callable.
    """
    db = _get_user_db(user_id)
    if db is None:
        return json.dumps({"error": "User database not found"})

    checks = {
        "SharedHelpersMixin": ["_build_subject_path", "_entry_to_dict", "_subject_with_dimension", "_get_descendant_node_ids"],
        "SchemaMigrationMixin": ["_ensure_phase2_schema", "_ensure_phase4_schema", "_ensure_phase7_schema"],
        "PreferencesMixin": ["get_preferences", "update_preferences"],
        "ExamContextMixin": ["create_exam_context", "get_exam_analytics_config"],
        "HierarchyMixin": ["create_subject_node", "get_subject_hierarchy", "update_subject_node_weight"],
        "TagsMixin": ["create_tag", "get_tag_hierarchy", "seed_default_tags"],
        "SessionsMixin": ["create_review_session", "get_review_sessions"],
        "TimerMixin": ["create_timer_round", "pause_round_timer"],
        "SourcesMixin": ["create_question_source", "get_question_sources"],
        "EntriesMixin": ["create_question_entry", "get_entries_paginated", "search_subjects"],
        "MediaMixin": ["add_entry_media", "search_media"],
        "NotesMixin": ["add_entry_note", "update_entry_note"],
        "AnalyticsMixin": ["get_analytics_overview", "get_subject_analytics", "get_study_streak"],
        "AdvancedAnalyticsMixin": ["get_subject_deep_dive", "get_source_comparison"],
        "GoalsMixin": ["get_user_goals", "set_weekly_goal"],
        "DimensionsMixin": ["create_dimension", "exam_uses_dimensions", "get_cross_dimension_performance"],
        "AliasesMixin": ["create_subject_alias", "check_alias_conflicts"],
        "ImportExportMixin": ["get_saved_delimiters", "get_import_mapping_profiles"],
    }

    results = {}
    all_ok = True
    for mixin_name, methods in checks.items():
        mixin_ok = True
        missing = []
        for method_name in methods:
            if not hasattr(db, method_name) or not callable(getattr(db, method_name)):
                missing.append(method_name)
                mixin_ok = False
                all_ok = False
        results[mixin_name] = {"ok": mixin_ok, "missing": missing} if not mixin_ok else "OK"

    return json.dumps({
        "all_ok": all_ok,
        "user": db.username,
        "mixins": results
    }, indent=2)


# -- Database Stats ----------------------------------------------------------

@mcp.tool()
def get_database_stats(user_id: int = None) -> str:
    """Get table row counts and database size info."""
    db = _get_user_db(user_id)
    if db is None:
        return json.dumps({"error": "User database not found"})

    tables = db.fetchall("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    stats = {}
    for t in tables:
        name = t['name']
        try:
            row = db.fetchone(f"SELECT COUNT(*) as cnt FROM [{name}]")
            stats[name] = row['cnt'] if row else 0
        except Exception:
            stats[name] = "error"

    # Get database file size
    db_path = Path(db.db_path) if hasattr(db, 'db_path') else None
    file_size = None
    if db_path and db_path.exists():
        file_size = db_path.stat().st_size

    return json.dumps({
        "user": db.username,
        "file_size_bytes": file_size,
        "tables": stats
    }, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run():
    """Run the MCP server (called from main.py --mcp-server)."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run()
