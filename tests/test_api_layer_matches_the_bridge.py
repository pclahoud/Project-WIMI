"""Every JS API wrapper names a real bridge slot, and every module is loaded.

A pairing invariant across two languages, which is why it is a parsed sweep
rather than a convention — the same argument `check_instrumented_slots.py`
makes for `@pyqtSlot` / `@instrumented_slot`.

It exists because the drift is invisible by construction. A wrapper calling a
slot that does not exist is syntactically perfect JavaScript; the absence is in
another file in another language; and `_bridge.js` only throws
`Unknown API method: <name>` at the moment somebody presses the thing. **Two
such wrappers had been sitting in `analytics.js` — which every page loads —
since 2026-04-15** (#383), and nothing noticed, because their only caller is a
module no page has a `<script>` tag for.

The other direction matters for the same reason. `_loader.js` lists the modules
to inject, by hand. A module on disk that is missing from that list defines
nothing at runtime, and the symptom is `api.whatever is not a function` on a
page where everything else works.

The exemption list, and the test that keeps it honest
-----------------------------------------------------
`KNOWN_MISSING_SLOTS` carries #383's two names so this file can land green
without settling what to do about them (finish the feature or delete it — a
product question). `test_every_exemption_is_still_broken` asserts each one is
*still* absent, so the list cannot outlive the defect: fixing #383 makes that
test fail and the entry gets deleted.

That companion is not belt-and-braces. CLAUDE.md records the same trap in
`pytest.xfail` form — an exemption reached only from inside a failing branch
never notices when the thing it exempts is fixed, so the page passes and stays
exempt forever.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
API_DIR = REPO_ROOT / 'src' / 'web' / 'js' / 'api'
BRIDGE_DOMAINS = REPO_ROOT / 'src' / 'app' / 'bridge_domains'

#: Not loaded as domain modules: one is the infrastructure every wrapper uses,
#: the other is the loader itself.
INFRASTRUCTURE = {'_bridge.js', '_loader.js'}

#: Slot names a wrapper calls that no `@pyqtSlot` provides. **#383.**
#: Each entry is a live defect, not an approved exception, and
#: `test_every_exemption_is_still_broken` is what stops it becoming one.
KNOWN_MISSING_SLOTS = {
    # analytics.js:132 and :139. Their only caller, time_difficulty.js, is
    # loaded by no page, so nothing a student can press reaches them.
    'getTimeVsDifficultyAnalysis',
    'getTimeDistribution',
}

_CALL = re.compile(r"_callBridge\(\s*'([A-Za-z_][A-Za-z0-9_]*)'")
_DEFINE = re.compile(r"api\.([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?function")
#: `@pyqtSlot(...)` then any further decorators, then the def. Written to
#: tolerate decorator order rather than assuming `@instrumented_slot` is next:
#: `check_instrumented_slots.py` enforces presence and explicitly not order.
_SLOT = re.compile(
    r'@pyqtSlot\([^)]*\)\s*(?:@[\w.]+(?:\([^)]*\))?\s*)*def\s+(\w+)')


def _domain_modules() -> list[Path]:
    return sorted(p for p in API_DIR.glob('*.js') if p.name not in INFRASTRUCTURE)


def _loader_list() -> list[str]:
    """The filenames `_loader.js` injects, in order.

    Read from the array rather than from every quoted string in the file:
    `document.currentScript.src.replace('_loader.js', '')` also matches a
    naive sweep, and a self-reference in the result would be a confusing
    false positive.
    """
    text = (API_DIR / '_loader.js').read_text(encoding='utf-8')
    array = re.search(r'var f = \[(.*?)\];', text, re.S)
    assert array, (
        "could not find _loader.js's module array. If the loader was "
        "rewritten, this parser needs rewriting with it -- a sweep that "
        "silently finds nothing is worse than no sweep (#322's empty table)")
    return re.findall(r"'([^']+\.js)'", array.group(1))


def _bridge_slots() -> set[str]:
    slots: set[str] = set()
    for path in sorted(BRIDGE_DOMAINS.glob('*.py')):
        slots.update(_SLOT.findall(path.read_text(encoding='utf-8')))
    return slots


# ==================== the loader's list ====================

def test_every_api_module_is_loaded():
    """A module missing from the list defines nothing, with no error anywhere.

    The page then fails with `api.whatever is not a function` while every
    other call on it works, which reads like a bridge problem and is not one.
    """
    listed = set(_loader_list())
    on_disk = {p.name for p in _domain_modules()}

    missing = sorted(on_disk - listed)
    assert not missing, (
        f'{missing} exist under src/web/js/api/ but are not in _loader.js. '
        f'Nothing they define reaches window.api.')


def test_the_loader_lists_nothing_that_is_absent():
    """`document.write` of a missing file is a silent 404 in QtWebEngine."""
    on_disk = {p.name for p in _domain_modules()} | INFRASTRUCTURE
    phantom = sorted(name for name in _loader_list() if name not in on_disk)
    assert not phantom, f'_loader.js injects {phantom}, which do not exist'


def test_the_parser_found_a_plausible_list():
    """The control. A regex that matched nothing would pass both tests above.

    #322's sweep came back empty and skipped 18 cases with no error; the
    lesson there is that a self-counting test needs a parser guard.
    """
    listed = _loader_list()
    assert len(listed) > 20, f'only {len(listed)} modules parsed out of the loader'
    assert 'relations.js' in listed


# ==================== wrappers against slots ====================

def test_every_wrapper_calls_a_slot_that_exists():
    """The #383 sweep. Both layers are parsed; neither is trusted.

    A wrapper naming a slot that is not there can only ever throw
    `Unknown API method` (`_bridge.js:137`), and it will do so on the day
    somebody first presses the thing rather than on the day it was written.
    """
    slots = _bridge_slots()
    called: dict[str, list[str]] = {}
    for path in _domain_modules():
        for name in _CALL.findall(path.read_text(encoding='utf-8')):
            called.setdefault(name, []).append(path.name)

    missing = {
        name: files for name, files in sorted(called.items())
        if name not in slots and name not in KNOWN_MISSING_SLOTS
    }
    assert not missing, (
        f'these JS wrappers call bridge slots that do not exist: {missing}. '
        f'Add the @pyqtSlot, or remove the wrapper. If it is a known defect '
        f'being tracked, put it in KNOWN_MISSING_SLOTS with its issue number '
        f'-- and expect test_every_exemption_is_still_broken to hold you to '
        f'removing it again.')


def test_every_exemption_is_still_broken():
    """The companion that stops the exemption list outliving the defect.

    Without this, fixing #383 leaves two names exempted forever and the sweep
    silently stops covering them. Same trap as an imperative `pytest.xfail`
    reached only from inside a failing branch.
    """
    slots = _bridge_slots()
    fixed = sorted(name for name in KNOWN_MISSING_SLOTS if name in slots)
    assert not fixed, (
        f'{fixed} now have bridge slots, so they are no longer missing. '
        f'Delete them from KNOWN_MISSING_SLOTS and close the issue that '
        f'tracks them (#383).')


def test_the_slot_parser_found_the_bridge():
    """The other control: an empty slot set makes the sweep above vacuous."""
    slots = _bridge_slots()
    assert len(slots) > 200, f'only {len(slots)} slots parsed'
    for expected in ('getSubjectRelations', 'proposeRelationsForEntry',
                     'getRelationExtractionStatus'):
        assert expected in slots, f'{expected} was not parsed out of the bridge'


def test_relation_extraction_wrappers_cover_the_whole_slot_surface():
    """#60's own layer, asserted rather than assumed.

    The mixin is the one place in `src/` with an unusual import rule, so it
    is the one most likely to gain a slot that nobody exposes to a page.
    """
    module = (API_DIR / 'relation_extraction.js').read_text(encoding='utf-8')
    wrapped = set(_CALL.findall(module))
    mixin = (BRIDGE_DOMAINS / 'relation_extraction.py').read_text(encoding='utf-8')
    slots = set(_SLOT.findall(mixin))

    assert slots, 'no slots parsed out of the relation-extraction mixin'
    assert slots == wrapped, (
        f'slots with no wrapper: {sorted(slots - wrapped)}; '
        f'wrappers with no slot: {sorted(wrapped - slots)}')


@pytest.mark.parametrize('path', _domain_modules(), ids=lambda p: p.name)
def test_a_module_defines_what_it_calls(path: Path):
    """Each module's wrappers and its bridge calls line up in count.

    Not a strict name match -- a composite wrapper legitimately makes several
    calls -- but a module that defines no `api.*` at all while calling the
    bridge is a file whose contents never reach `window.api`, which is the
    #383 failure one layer up.
    """
    text = path.read_text(encoding='utf-8')
    if not _CALL.search(text):
        return
    assert _DEFINE.search(text), (
        f'{path.name} calls the bridge but defines no api.* function, so '
        f'nothing can reach those calls')
