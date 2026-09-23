"""A real two-device fork for folder-sync scenarios (#148).

The running WIMI is device A and publishes through its own page. Device B is
a second app-data directory driven from the test process -- a second
``MasterDatabase``, installing from the same folder, exactly as another
computer does. Nothing is faked: the fork comes from #149's own
reproduction, a device publishing without having fetched the other's work.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict

from wimi_test.page import WimiPage


def await_js(page: WimiPage, expression: str, *, timeout_ms: int = 30000) -> Any:
    """Run an async page expression and poll for its settled, JSON-able result."""
    page.eval_js(
        "window.__syncResult = undefined; window.__syncError = undefined;"
        " Promise.resolve(" + expression + ")"
        "  .then(v => { window.__syncResult = JSON.stringify(v === undefined ? null : v); })"
        "  .catch(e => { window.__syncError = String(e && e.message || e); });"
    )
    elapsed = 0
    while elapsed < timeout_ms:
        err = page.eval_js("window.__syncError || null")
        if err:
            raise AssertionError(f"{expression} failed: {err}")
        done = page.eval_js("window.__syncResult || null")
        if done is not None:
            return json.loads(done)
        page.wait_for_timeout(200)
        elapsed += 200
    raise AssertionError(f"{expression} never settled")


def _add_entries(db, n: int) -> None:
    """Append ``n`` entries to a profile, creating its first session if needed."""
    with db.transaction():
        row = db.fetchone("SELECT id FROM review_sessions ORDER BY id LIMIT 1")
        if row is None:
            exam = db.execute(
                "INSERT INTO exam_contexts (user_id, exam_name) VALUES (?, ?)",
                (db.user_id, "Sync Scenario Exam")).lastrowid
            session_id = db.execute(
                "INSERT INTO review_sessions (user_id, exam_context_id,"
                " total_questions, total_incorrect) VALUES (?, ?, 10, 1)",
                (db.user_id, exam)).lastrowid
        else:
            session_id = row["id"]
        start = db.fetchone("SELECT COUNT(*) AS n FROM question_entries")["n"]
        for i in range(start + 1, start + 1 + n):
            db.execute(
                "INSERT INTO question_entries (review_session_id, entry_order,"
                " user_answer, correct_answer) VALUES (?, ?, 'a', 'c')",
                (session_id, i))


def make_fork(page: WimiPage, user_db, folder: Path, device_b_dir: Path) -> Dict[str, Any]:
    """A publishes, B installs and publishes, A publishes again without fetching.

    Returns ``{"b_sync", "b_user_id", "b_master", "b_blob", "a_blob"}``. The
    caller closes ``b_master``.
    """
    from app.foldersync import ProfileFolderSync
    from database.master_db import MasterDatabase
    from database.user_db import UserDatabase

    _add_entries(user_db, 2)
    await_js(page, f"api.linkFolderSync({json.dumps(str(folder))}, 'generic')")
    await_js(page, "api.pushFolderSync()")                      # generation 1
    sync_id = await_js(page, "api.getFolderSyncLink()")["sync_id"]

    b_master = MasterDatabase(data_dir=device_b_dir, error_logger=None)
    b_sync = ProfileFolderSync(b_master, timeout_s=10.0)
    installed = b_sync.install_from_folder(folder, sync_id, "generic")["installed"]
    b_id = int(installed["user_id"])
    b_sync.link(b_id, folder, "generic")
    user = b_master.get_user(user_id=b_id)
    b_db = UserDatabase(db_path=b_master.ensure_user_database(b_id),
                        user_id=b_id, username=user.username)
    try:
        _add_entries(b_db, 3)
    finally:
        b_db.close()
    b_pushed = b_sync.push(b_id)                                # B's generation 2

    _add_entries(user_db, 5)
    a_pushed = await_js(page, "api.pushFolderSync()")          # A never fetched B's
    return {"b_sync": b_sync, "b_user_id": b_id, "b_master": b_master,
            "b_blob": b_pushed.blob_name, "a_blob": a_pushed["blob_name"]}


def poll(page: WimiPage, js: str, want, *, timeout_ms: int = 15000):
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = page.eval_js(js)
        except Exception:  # context torn down mid-navigation
            last = None
        if last == want:
            return last
        page.wait_for_timeout(100)
        elapsed += 100
    return last


# ==================== #151: a computer behind, and one with nothing ====================

def release_test_handle(session) -> None:
    """Close the harness's own cached handle on the profile database.

    ``wimi_session.user.db`` stays open for the whole test. Catching up
    replaces that file, and on Windows any open handle blocks the replace --
    the app releases its own (#148), so the harness must not be the thing
    holding it. Linux would not notice; a Windows scenario run would.
    """
    user = session.user
    cached = getattr(user, "_db", None)
    if cached is not None:
        cached.close()
        user._db = None


def profile_db_path(session) -> Path:
    from database.master_db import MasterDatabase
    master = MasterDatabase(data_dir=session.config.app_data_dir, error_logger=None)
    try:
        return Path(master.ensure_user_database(session.user.user_id))
    finally:
        master.close()


def add_entries_here(session, n: int) -> None:
    """Add work on the running WIMI's profile through a short-lived connection."""
    from database.user_db import UserDatabase
    release_test_handle(session)
    db = UserDatabase(db_path=profile_db_path(session), user_id=session.user.user_id,
                      username=session.user.username)
    try:
        _add_entries(db, n)
    finally:
        db.close()


def entries_here(session) -> int:
    import sqlite3
    conn = sqlite3.connect(str(profile_db_path(session)))
    try:
        return conn.execute("SELECT COUNT(*) FROM question_entries").fetchone()[0]
    finally:
        conn.close()


def make_behind(page: WimiPage, session, folder: Path, device_b_dir: Path) -> Dict[str, Any]:
    """The running WIMI publishes; device B installs, adds work and publishes on top.

    Leaves the running WIMI *behind*: B's generation 2 builds on its
    generation 1 -- the ordinary catch-up #151 exists for.
    """
    from app.foldersync import ProfileFolderSync
    from database.master_db import MasterDatabase
    from database.user_db import UserDatabase

    add_entries_here(session, 5)
    await_js(page, f"api.linkFolderSync({json.dumps(str(folder))}, 'generic')")
    await_js(page, "api.pushFolderSync()")
    sync_id = await_js(page, "api.getFolderSyncLink()")["sync_id"]

    b_master = MasterDatabase(data_dir=device_b_dir, error_logger=None)
    b_sync = ProfileFolderSync(b_master, timeout_s=10.0)
    b_id = int(b_sync.install_from_folder(folder, sync_id, "generic")["installed"]["user_id"])
    user = b_master.get_user(user_id=b_id)
    b_db = UserDatabase(db_path=b_master.ensure_user_database(b_id),
                        user_id=b_id, username=user.username)
    try:
        _add_entries(b_db, 3)
    finally:
        b_db.close()
    pushed = b_sync.push(b_id)
    return {"b_sync": b_sync, "b_master": b_master, "b_user_id": b_id,
            "b_blob": pushed.blob_name, "sync_id": sync_id}
