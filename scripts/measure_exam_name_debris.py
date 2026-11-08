"""Count what m037 would remove from a profile, without changing it (#884).

    python scripts/measure_exam_name_debris.py --db <profile.wimi | user.db>

Prints counts only: no exam, subject, tag or source names and no content.

It never opens the given file for writing. A ``.wimi`` has its database
extracted into a temporary directory; a ``.db`` is copied there with SQLite's
backup API from a read-only connection, so a WAL tail comes with it. The copy
is migrated to v36, counted, run through m037 itself, counted again and
deleted. Running m037's own ``upgrade`` rather than a second set of queries
means the counts cannot disagree with what the migration does.

THIS READS REAL DATA when pointed at a real profile. Per #884 it is run on the
owner's profile only with the owner's explicit permission in that session.
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from database.domains.exam_contexts import EXAM_NAME_KEYED_TABLES  # noqa: E402
from database.migration_runner import MigrationRunner  # noqa: E402
from database.migrations.user import MIGRATIONS, m037_exam_name_debris  # noqa: E402

DB_MEMBER = "user.db"  # app/profile_archive.py
JOURNALS = ("subject_delete_batches", "subject_delete_batch_items",
            "dimension_delete_batches", "dimension_delete_batch_subjects",
            "subject_relation_rejections")


def _copy_in(source: Path, dest: Path) -> None:
    if zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as zf:
            with zf.open(DB_MEMBER) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
        return
    ro = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    out = sqlite3.connect(dest)
    try:
        ro.backup(out)
    finally:
        out.close()
        ro.close()


def _debris(conn, table: str) -> int:
    return conn.execute(
        f"SELECT COUNT(*) FROM {table} t WHERE t.exam_context IS NOT NULL AND"
        " NOT EXISTS (SELECT 1 FROM exam_contexts e"
        "             WHERE e.exam_name = t.exam_context)").fetchone()[0]


def _count(conn, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def measure(path: Path) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "copy.db"
        _copy_in(path, copy)
        conn = sqlite3.connect(copy)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            MigrationRunner(conn, registry=[m for m in MIGRATIONS if m.version < 37],
                            scope="user").apply_pending()
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            keyed = [t for t in EXAM_NAME_KEYED_TABLES if t in tables]
            journals = [t for t in JOURNALS if t in tables]
            unfiled_before = _count_unfiled(conn)
            before = {t: _count(conn, t) for t in keyed + journals}
            debris = {t: _debris(conn, t) for t in keyed}
            names_before = _names_with_debris(conn, keyed)

            m037_exam_name_debris.upgrade(conn)

            after = {t: _count(conn, t) for t in keyed + journals}
            left = {t: _debris(conn, t) for t in keyed}
            result = {
                "debris_rows": debris,
                "removed": {t: before[t] - after[t] for t in before},
                "kept_by_rule_1": left,
                "sources_unfiled_by_rule_2": _count_unfiled(conn) - unfiled_before,
                "deleted_exam_names": names_before,
                "names_still_blocked": _names_with_debris(conn, keyed),
            }
            conn.rollback()
            return result
        finally:
            conn.close()


def _count_unfiled(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM question_sources WHERE exam_context IS NULL").fetchone()[0]


def _names_with_debris(conn, keyed) -> int:
    """Distinct exam names that rows are filed under with no exam holding them.
    After m037 these are the names #718 still refuses for a rename."""
    union = " UNION ".join(f"SELECT exam_context FROM {t}" for t in keyed)
    return conn.execute(
        f"SELECT COUNT(*) FROM ({union}) n WHERE n.exam_context IS NOT NULL AND"
        " NOT EXISTS (SELECT 1 FROM exam_contexts e"
        "             WHERE e.exam_name = n.exam_context)").fetchone()[0]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", required=True, type=Path,
                        help="a .wimi export or a user .db (never modified)")
    args = parser.parse_args(argv)
    if not args.db.is_file():
        parser.error(f"no such file: {args.db}")
    r = measure(args.db)
    print("Debris rows per table (filed under a name no exam holds):")
    for t, n in r["debris_rows"].items():
        print(f"  {t:28} {n}")
    print("Rows m037 would remove (including journals and cascades):")
    for t, n in r["removed"].items():
        print(f"  {t:28} {n}")
    print("Debris kept because a living row uses it (rule 1):")
    for t, n in r["kept_by_rule_1"].items():
        print(f"  {t:28} {n}")
    print(f"Sources unfiled because still in use (rule 2): "
          f"{r['sources_unfiled_by_rule_2']}")
    print(f"Deleted exam names with debris: {r['deleted_exam_names']}")
    print(f"Of those, still blocked for a rename afterwards: "
          f"{r['names_still_blocked']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
