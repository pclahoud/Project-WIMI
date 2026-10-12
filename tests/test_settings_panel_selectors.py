"""Every id and class the settings page looks up actually exists (#60).

`querySelector` answers a selector that matches nothing with `null`, and the
guard that follows (`if (el) ...`) swallows it. So a selector naming something
that is not there is **silent**: no error, no console line, and a control that
simply never updates.

That is not hypothetical here. `settings.js` looked up `.range-input-group`
while the markup and `settings.css` both use `.range-group`, so the page's
range-input handling had never run against real markup — found while building
#380's confidence dial, which was the first range input the page ever had. It
would have broken the first slider anybody added, whenever that was.

`test_the_sweep_catches_the_selector_that_was_dead` is this file's reason to
exist: it runs the same sweep over the old line and requires it to be caught.
Without that control the sweep is three assertions that happen to pass.

Why ids and classes both
------------------------
The dead selector was a class, and the relations panel's renderer reaches for
eleven ids. Both directions are the same failure: a literal in one language
naming something in another, with nothing to connect them. Neither sweep is
over the whole app — `settings.html` plus `settings.js` is one page's worth of
that pairing, and it is the page where two features now keep their status
lines.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_JS = REPO_ROOT / 'src' / 'web' / 'js' / 'settings.js'
SETTINGS_HTML = REPO_ROOT / 'src' / 'web' / 'html' / 'settings.html'
SETTINGS_CSS = REPO_ROOT / 'src' / 'web' / 'css' / 'settings.css'
STYLES_CSS = REPO_ROOT / 'src' / 'web' / 'css' / 'styles.css'

#: ``getElementById('literal')`` where the literal is the whole argument. A
#: lookup built by concatenation (``'plugin-setting-' + name``) names no fixed
#: id and is skipped by the negative lookahead rather than by an exemption
#: list, because an exemption list would need maintaining and this does not.
_BY_ID = re.compile(r"getElementById\(\s*'([^']+)'\s*\)")
_SELECTOR = re.compile(r"(?:closest|querySelector(?:All)?)\(\s*'([^']+)'\s*\)")
_CLASS_IN_SELECTOR = re.compile(r'\.([a-zA-Z][\w-]*)')


def _ids_in_markup(html: str) -> set[str]:
    return set(re.findall(r'\bid="([^"]+)"', html))


def _classes_in_markup(html: str) -> set[str]:
    found: set[str] = set()
    for attr in re.findall(r'\bclass="([^"]+)"', html):
        found.update(attr.split())
    return found


def _classes_the_js_writes(js: str) -> set[str]:
    """Classes JavaScript puts on nodes itself, which the markup never carries.

    A rebuilt row's class is assigned in code, so it is legitimately absent
    from the HTML and must not read as a dead selector.
    """
    written: set[str] = set()
    for value in re.findall(r"className\s*=\s*'([^']*)'", js):
        written.update(value.split())
    for value in re.findall(r"className\s*=\s*`([^`]*)`", js):
        written.update(re.sub(r'\$\{[^}]*\}', ' ', value).split())
    for value in re.findall(r"classList\.(?:add|remove|toggle)\(\s*'([^']+)'", js):
        written.add(value)
    for value in re.findall(r'class="([^"]+)"', js):  # template-literal markup
        written.update(re.sub(r'\$\{[^}]*\}', ' ', value).split())
    return written


def _dead_ids(js: str, html: str) -> list[str]:
    return sorted(set(_BY_ID.findall(js)) - _ids_in_markup(html))


def _dead_classes(js: str, html: str) -> list[str]:
    selected: set[str] = set()
    for selector in _SELECTOR.findall(js):
        selected.update(_CLASS_IN_SELECTOR.findall(selector))
    known = _classes_in_markup(html) | _classes_the_js_writes(js)
    return sorted(selected - known)


# ==================== the sweeps ====================

def test_every_id_the_page_looks_up_exists():
    dead = _dead_ids(SETTINGS_JS.read_text(encoding='utf-8'),
                     SETTINGS_HTML.read_text(encoding='utf-8'))
    assert not dead, (
        f'settings.js calls getElementById for {dead}, which settings.html '
        f'does not contain. getElementById returns null and the guard after '
        f'it swallows that, so the control silently never updates.')


def test_every_class_the_page_selects_exists():
    js = SETTINGS_JS.read_text(encoding='utf-8')
    dead = _dead_classes(js, SETTINGS_HTML.read_text(encoding='utf-8'))
    assert not dead, (
        f'settings.js selects {dead}, which appear neither in settings.html '
        f'nor anywhere the JS assigns a class. This is exactly the '
        f'.range-input-group defect.')


def test_the_sweep_catches_the_selector_that_was_dead():
    """The control. Without it the two sweeps above are decoration.

    This is the real line from before #380's dial landed, run through the same
    function. If a future rewrite of the parser stops matching `closest`, this
    fails and says so instead of the sweeps quietly covering nothing.
    """
    was = """
        const rangeGroup = el.closest('.range-input-group');
        if (rangeGroup) {
            const display = rangeGroup.querySelector('.range-value');
            if (display) display.textContent = value;
        }
    """
    dead = _dead_classes(was, SETTINGS_HTML.read_text(encoding='utf-8'))
    assert 'range-input-group' in dead, (
        'the class sweep no longer catches the selector it was built for')
    assert 'range-value' not in dead, (
        'the sibling selector in that same block was always correct; a sweep '
        'that flagged it too would be matching on the wrong thing')


def test_the_id_sweep_catches_a_misspelling():
    """The other control, and it also pins the concatenation exemption.

    A lookup assembled from a prefix names no fixed id, so it must be ignored
    -- and it must be ignored because of its shape rather than because it is
    on a list somebody has to keep.
    """
    assert _dead_ids("document.getElementById('relationsStatusDotz')",
                     SETTINGS_HTML.read_text(encoding='utf-8')) == \
        ['relationsStatusDotz']
    assert _dead_ids("document.getElementById('plugin-setting-' + name)",
                     SETTINGS_HTML.read_text(encoding='utf-8')) == []


def test_the_parsers_found_something():
    """An empty sweep passes every assertion above.

    #322's theme sweep came back empty and skipped 18 cases with no error;
    the lesson is that a self-counting test needs a parser guard.
    """
    js = SETTINGS_JS.read_text(encoding='utf-8')
    assert len(set(_BY_ID.findall(js))) > 50
    assert len(_SELECTOR.findall(js)) > 10
    assert len(_ids_in_markup(SETTINGS_HTML.read_text(encoding='utf-8'))) > 100


# ==================== the Related Topics panel ====================

RELATIONS_IDS = (
    'relationsStatusDot',
    'relationsStatusText',
    'relationsDownloadBtn',
    'relationsCancelDownloadBtn',
    'relationsDiscardBtn',
    'relationsDownloadProgress',
    'relationsDownloadTrack',
    'relationsDownloadBar',
    'relationsDownloadText',
    'relationsDownloadError',
)


@pytest.mark.parametrize('element_id', RELATIONS_IDS)
def test_the_related_topics_panel_carries_its_controls(element_id):
    """#5179/#5183: one availability line in Settings, and the way to act on it.

    Listed explicitly rather than left to the sweep because the sweep only
    proves the two files agree -- deleting both halves would satisfy it, and
    this panel describes a feature whose only honest state line lives here.
    """
    assert f'id="{element_id}"' in SETTINGS_HTML.read_text(encoding='utf-8')


def test_the_feature_status_classes_are_styled():
    """The relations panel uses `.feature-*`, not `.stt-*`.

    Reusing speech-to-text's classes would mean an edit to its styling
    silently restyling this panel. The rules are paired in settings.css so
    neither feature's markup had to change.
    """
    css = SETTINGS_CSS.read_text(encoding='utf-8')
    html = SETTINGS_HTML.read_text(encoding='utf-8')
    for name in ('feature-status', 'feature-status-row', 'feature-status-dot',
                 'feature-status-body', 'feature-status-title',
                 'feature-status-text', 'feature-actions', 'feature-progress',
                 'feature-progress-track', 'feature-progress-bar',
                 'feature-progress-text', 'feature-problem'):
        assert f'.{name}' in css, f'{name} is used but never styled'
    assert 'feature-status' in html
    panel = html.split('data-panel="related_topics"', 1)[1]
    assert 'stt-status' not in panel.split('data-panel=', 1)[0], (
        'the Related Topics panel must not borrow the speech panel\'s classes')


def test_nothing_hides_the_confidence_dial():
    """The dial stays visible and enabled in **every** availability state.

    Owner's decision, argued from where m028 lives: the cutoff is
    `user_preferences`, so it travels in a `.wimi`. A student on the build
    without the runtime is setting it for the machine that has it, and hiding
    it on whichever machine is in front of them makes a travelling preference
    unsettable. The availability line above it is the whole of the fix.
    """
    js = SETTINGS_JS.read_text(encoding='utf-8')
    for forbidden in (
        "getElementById('relation_confidence_threshold').style.display",
        "getElementById('relation_confidence_threshold').disabled",
    ):
        assert forbidden not in js, (
            f'{forbidden} would hide or disable the dial. It is a travelling '
            f'preference and stays available in every state -- see the panel '
            f'comment in settings.html before changing this.')
