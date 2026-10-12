"""Regression: the import preview refuses a database not built by WIMI (#593).

The backend refuses such an archive at install time in any case. This
scenario covers the page: ``profile_select.js`` must read the preflight's
``blocked`` flag, show the reason, and disable Import, while Cancel is
still the only thing to press. Before #593 the page compared the verdict
against ``'newer_app_required'`` alone, so a new refusing verdict would
have left Import enabled under a silent note.

The archive is a real export of the session profile plus one named
mutation from ``tests/_schema_mutations.py``, built at runtime. The values
are benign; what changes is the DDL.
"""
from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path
from typing import Any

import pytest

from tests import _schema_mutations
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

READ = """
(() => {
  const modal = document.getElementById('importModal');
  const note = document.getElementById('importSchemaNote');
  const btn = document.getElementById('importConfirmBtn');
  return {
    open: !!modal && !modal.classList.contains('hidden')
          && getComputedStyle(modal).display !== 'none',
    noteShown: !!note && !note.classList.contains('hidden'),
    note: note ? note.textContent.trim() : null,
    importDisabled: !!btn && btn.disabled,
  };
})()
"""


def _export(page: WimiPage, user_id: int, dest: Path) -> None:
    page.eval_js(
        f"window.api.exportProfile({{user_id: {user_id}, include_media: false,"
        f" dest_path: {json.dumps(str(dest))}}})", await_promise=True)
    assert dest.exists(), f"export did not write {dest}"


def _with_mutation(archive: Path, dest: Path, mutation) -> Path:
    work = dest.parent / f"_{dest.stem}"
    work.mkdir()
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(work)
    conn = sqlite3.connect(work / "user.db")
    try:
        mutation(conn)
    finally:
        conn.close()
    with zipfile.ZipFile(archive) as src, \
            zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as out:
        for item in src.infolist():
            if item.filename != "user.db":
                out.writestr(item, src.read(item.filename))
        out.write(work / "user.db", "user.db")
    return dest


def _preview(page: WimiPage, archive: Path) -> dict:
    page.eval_js(
        "window.dispatchEvent(new CustomEvent('wimi:profile-import-requested',"
        f" {{detail: {{path: {json.dumps(str(archive))}}}}}))")
    for _ in range(100):
        seen = page.eval_js(READ)
        if seen["open"]:
            return seen
        page.wait_for_timeout(100)
    raise AssertionError(f"the import preview never opened: {seen!r}")


@pytest.mark.slow
@pytest.mark.regression
def test_the_preview_blocks_an_unrecognised_structure_and_says_why(
    wimi_session: WimiTestSession, wimi_page: WimiPage, tmp_path: Path,
    wimi_master_db: Any,
) -> None:
    wimi_page.goto("profile-select")
    exported = tmp_path / "exported.wimi"
    _export(wimi_page, wimi_session.user.user_id, exported)

    # Positive control first: the same export, unchanged, may be imported.
    # Without it, a disabled button below could be a page that disables
    # Import for every archive.
    clean = _preview(wimi_page, exported)
    assert clean["importDisabled"] is False, clean
    assert clean["noteShown"] is False, clean
    wimi_page.eval_js("document.getElementById('importCancelBtn').click()")
    for _ in range(50):
        if not wimi_page.eval_js(READ)["open"]:
            break
        wimi_page.wait_for_timeout(100)

    foreign = _with_mutation(exported, tmp_path / "foreign.wimi",
                             _schema_mutations.alias_id_as_text)
    seen = _preview(wimi_page, foreign)

    assert seen["importDisabled"] is True, (
        f"Import is enabled for an archive the backend refuses (#593): {seen!r}")
    assert seen["noteShown"] is True, seen
    assert "subject_aliases" in seen["note"], (
        f"the note does not say what was found: {seen['note']!r}")
    assert "Update WIMI" not in seen["note"], (
        f"the note gives the newer-app advice, which fixes nothing here: "
        f"{seen['note']!r}")
