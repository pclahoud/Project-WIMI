"""Removing a shared image from one entry must leave it on the others (#460).

`entry_media_mapping` exists so one image can serve several entries, and the
entry form's own hint promises the image "stays available for reuse" when you
remove it from an entry.

It did not. `unlink_media_from_entry(media_id)` runs
`UPDATE entry_media_mapping SET is_active = 0 WHERE media_id = ?` with **no
entry predicate**, and the `removeMediaFromEntry` bridge slot takes a media id
and nothing else, so it cannot scope even in principle. `media_upload.js`'s
"Remove from Entry" button called exactly that. A student with one diagram on
four entries lost it from all four and was told the opposite.

`detach_media_from_entry(media_id, entry_id)` was already written, already
exposed as `detachMediaFromEntry`, already wrapped in `api/media.js` -- and had
no caller anywhere in the app. The fix was to call it.

These are source checks rather than database ones, and that is a real limit
worth stating: they prove the entry form reaches the scoped path and that the
two methods are still different, not that the scoped path behaves correctly on
rows. `detach_media_from_entry` was written deliberately for this and carries
its own entry predicate; a fixture-backed test over real mappings would be
stronger and is the obvious extension.
"""
from __future__ import annotations

import inspect
import pathlib
import re

MEDIA_UPLOAD_JS = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "web" / "js" / "media_upload.js"
)

#: Only a real call counts. Comments legitimately NAME the old slot in order to
#: explain why it is not used, and a reader that cannot tell prose from code is
#: the failure mode a source sweep dies of -- this file would otherwise fail on
#: its own explanation.
UNSCOPED_CALL = re.compile(r"""callApi\(\s*['"]removeMediaFromEntry['"]""")
SCOPED_CALL = re.compile(r"""callApi\(\s*['"]detachMediaFromEntry['"]""")


def _media_upload_source() -> str:
    return MEDIA_UPLOAD_JS.read_text(encoding="utf-8")


def test_remove_from_entry_calls_the_scoped_slot() -> None:
    assert SCOPED_CALL.search(_media_upload_source()), (
        "media_upload.js no longer calls detachMediaFromEntry, so "
        '"Remove from Entry" is probably unscoped again (#460).'
    )


def test_it_does_not_call_the_unscoped_slot() -> None:
    assert not UNSCOPED_CALL.search(_media_upload_source()), (
        "media_upload.js calls removeMediaFromEntry, which deactivates the "
        "mapping for EVERY entry sharing the image (#460). Use "
        "detachMediaFromEntry(mediaId, entryId) instead."
    )


def test_the_sweep_can_tell_a_call_from_a_mention() -> None:
    """The reader's own control, and it is not decoration.

    This repo has had a source sweep degrade silently when its reader
    desynchronised, returning plausible text and finding nothing. A sweep that
    cannot distinguish `callApi('x')` from a comment naming `x` would fail on
    this file's own docstring.
    """
    assert UNSCOPED_CALL.search("await this.callApi('removeMediaFromEntry', id)")
    assert not UNSCOPED_CALL.search("// removeMediaFromEntry is unscoped (#460)")
    assert SCOPED_CALL.search('this.callApi("detachMediaFromEntry", m, e)')


def test_the_two_database_methods_are_still_different() -> None:
    """One scopes by entry and one deliberately does not.

    If they ever converge, whichever way round, the distinction this issue is
    about has quietly gone -- and the unscoped one is still reachable through
    its bridge slot.
    """
    from database.domains.media import MediaMixin

    scoped = inspect.getsource(MediaMixin.detach_media_from_entry)
    unscoped = inspect.getsource(MediaMixin.unlink_media_from_entry)

    assert "question_entry_id" in scoped, (
        "detach_media_from_entry no longer filters on the entry, so it is no "
        "longer the scoped path the entry form depends on (#460)."
    )
    assert "question_entry_id" not in unscoped.split('"""')[-1], (
        "unlink_media_from_entry has grown an entry predicate. That may be the "
        "right fix, but the entry form was moved to detach_media_from_entry on "
        "the understanding that this one is intentionally unscoped -- reconcile "
        "the two rather than leaving both."
    )
