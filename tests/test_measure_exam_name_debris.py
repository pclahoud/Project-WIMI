"""``scripts/measure_exam_name_debris.py`` counts m037's work and changes nothing.

Run here on a synthetic pre-#880 profile only. The script exists to be run on
the owner's real profile, which needs the owner's permission (#884).
"""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

from tests.database.migrations.test_user_037_exam_name_debris import (  # noqa: F401
    _debris_profile, db, env)
from tests.database.test_exam_hard_delete import DOOMED, _filed_under

ROOT = Path(__file__).resolve().parent.parent


def _script():
    spec = importlib.util.spec_from_file_location(
        "measure_exam_name_debris", ROOT / "scripts" / "measure_exam_name_debris.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_it_counts_the_debris_and_leaves_the_file_alone(env, capsys):
    _master, _user, db = env
    _debris_profile(db)
    expected = _filed_under(db, DOOMED)
    db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    path = Path(db.db_path)
    before = _digest(path)

    result = _script().measure(path)

    assert _digest(path) == before, "the script wrote to the profile it measured"
    assert result["debris_rows"] == expected
    assert result["removed"]["subject_nodes"] == expected["subject_nodes"]
    assert set(result["kept_by_rule_1"].values()) == {0}
    assert result["deleted_exam_names"] == 1
    assert result["names_still_blocked"] == 0
    assert _filed_under(db, DOOMED) == expected, "the live profile changed"


def test_the_printout_carries_no_names(env, capsys):
    _master, _user, db = env
    _debris_profile(db)
    db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    assert _script().main(["--db", str(db.db_path)]) == 0
    out = capsys.readouterr().out
    assert "subject_nodes" in out
    for name in (DOOMED, "Cardiology", "Arrhythmia", "Bank for"):
        assert name not in out


def test_it_reads_a_wimi_export(env, tmp_path):
    """The owner's profile will arrive as a ``.wimi``, so that branch is real."""
    from app.profile_archive import build_profile_archive

    master, user, db = env
    _debris_profile(db)
    expected = _filed_under(db, DOOMED)
    archive = tmp_path / "export.wimi"
    build_profile_archive(master, user.id, archive, include_media=False)
    before = _digest(archive)

    result = _script().measure(archive)

    assert _digest(archive) == before
    assert result["debris_rows"] == expected
