"""Regression: the dashboard's newer-copy notice has three states, not two (#499).

``ProfileFolderSync.local_changes`` answers ``{checked, reason, differs}``, and
``checked`` is false whenever the comparison could not run -- the base copy is
not in the folder yet, nothing is recorded as last sent, or the profile could
not be read. An unchecked comparison carries an empty ``differs``, so the
dashboard's two-way ternary gave it the "none found" sentence: *"Take it
before adding work here"*, the confident advice in exactly the state where
WIMI does not know. The Settings panel next door already branched three ways.

Driven through the page's own ``folderSyncNoticeText`` with the three payload
shapes the bridge returns, because reaching ``checked: false`` end to end needs
a cloud client that has not listed this device's own push yet -- a timing
state, not a fixture. The two end-to-end shapes (changes found, none found)
are already driven through a real folder by
``test_settings_folder_sync_catch_up.py``.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_page``.
"""
from __future__ import annotations

import json

import pytest

from _helpers.foldersync_fork import poll
from wimi_test.page import WimiPage

TAKE_IT = "Take it before adding work here"
CHANGED = "This computer has changes of its own"
UNKNOWN = "could not check"


def _notice(page: WimiPage, local_changes) -> str:
    status = {
        "linked": True, "forks": [], "pending": None, "base_relation": "behind",
        "relation_detail": {"device_name": "LAPTOP"},
    }
    if local_changes is not None:
        status["local_changes"] = local_changes
    return page.eval_js("folderSyncNoticeText(%s)" % json.dumps(status))


@pytest.mark.slow
@pytest.mark.regression
def test_the_notice_does_not_give_confident_advice_when_it_could_not_look(
    wimi_page: WimiPage,
) -> None:
    wimi_page.goto('dashboard')
    assert poll(wimi_page, "typeof folderSyncNoticeText === 'function'", True) is True

    found = _notice(wimi_page, {"checked": True, "differs": [{"label": "entries"}]})
    assert CHANGED in found and TAKE_IT not in found, found

    # Positive control: a comparison that ran and found nothing keeps the
    # advice -- otherwise "never say take it" would pass this file.
    none_found = _notice(wimi_page, {"checked": True, "differs": []})
    assert TAKE_IT in none_found and UNKNOWN not in none_found, none_found

    for unchecked in (
        {"checked": False, "reason": "the base copy is not in the folder", "differs": []},
        None,   # no local_changes at all: Settings reads that as unknown too
    ):
        text = _notice(wimi_page, unchecked)
        assert TAKE_IT not in text, (
            f"WIMI could not check for local changes and still advised taking the "
            f"newer copy: {text!r}")
        assert UNKNOWN in text and "open sync settings" in text, text
