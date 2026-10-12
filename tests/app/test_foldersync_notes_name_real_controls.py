"""What folder sync tells a student names a control that exists, in copy (#500).

Two defects in strings that reach the page verbatim:

* After a resolution that still needs sending, the toast said *"use Send now
  in Settings"*. ``grep "Send now" src/`` matched that line and nothing else:
  the button reads **Send your choice** in exactly that state
  (``renderFolderSyncPending`` relabels it), so the message sent the student
  to a third thing. #174's rule -- a message may not direct a press that is
  not there.
* Two notes carried a literal ``--`` where every neighbouring string uses an
  em dash: the repo's ASCII-for-comments habit leaking into rendered copy.

The guard reads the notes from source rather than driving a two-device fork,
because the strings are unconditional on their paths and a source sweep
catches the next note too. It is self-counting so it cannot pass by finding
nothing.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from app.foldersync.jobs import _send_notes

ROOT = Path(__file__).resolve().parents[2]
FOLDERSYNC = ROOT / "src" / "app" / "foldersync"
SETTINGS_JS = ROOT / "src" / "web" / "js" / "settings.js"


def _note_literals():
    """Every string literal appended to a ``notes`` list, or returned by
    ``_send_notes`` -- the two routes into the resolution toast and the fork
    panel's note."""
    found = []
    for path in sorted(FOLDERSYNC.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            target = None
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("append", "extend")):
                owner = node.func.value
                name = getattr(owner, "attr", None) or getattr(owner, "id", None)
                if name and name.endswith("notes"):
                    target = node
            elif isinstance(node, ast.FunctionDef) and node.name == "_send_notes":
                target = node
            if target is None:
                continue
            for sub in ast.walk(target):
                if (isinstance(sub, ast.Constant) and isinstance(sub.value, str)
                        and len(sub.value) > 20):
                    found.append((f"{path.name}:{sub.lineno}", sub.value))
    return found


def test_the_sweep_finds_the_notes_it_guards():
    sites = _note_literals()
    texts = " ".join(text for _, text in sites)
    assert len(sites) >= 5, sites
    assert "Every figure recorded here is the same on both copies" in texts
    assert "Your choice is saved on this device only" in texts


def test_no_student_facing_note_prints_a_double_hyphen():
    offenders = [(site, text) for site, text in _note_literals() if "--" in text]
    assert not offenders, offenders


def test_the_send_note_names_the_button_as_it_reads_while_a_choice_is_pending():
    note = " ".join(_send_notes({"send_needed": True}))
    assert "Send now" not in note
    assert "Send your choice" in note, note
    # The label it names must be the one the page actually writes in that state.
    js = SETTINGS_JS.read_text(encoding="utf-8")
    assert re.search(r"push\.textContent\s*=.*'Send your choice'", js), (
        "settings.js no longer relabels the push button 'Send your choice' -- "
        "the resolution toast now names a button that is not there")


def test_nothing_to_send_says_so_without_naming_a_button():
    note = " ".join(_send_notes({"send_needed": False}))
    assert "nothing to send" in note and "Send" not in note.replace("nothing to send", "")
