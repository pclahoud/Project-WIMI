"""Regression: #102's 28 repointed declarations must follow the theme.

Forgejo issue #102 — the complete remainder of the #76 / #81 / #97 rename
family: 21 tokens across 31 declarations written ``var(--X, hardcoded)``
where ``--X`` is defined nowhere, so the fallback wins unconditionally and
the declaration cannot follow the palette. 18 tokens / 28 declarations
were repointed; the three ``toast.css`` ``-dark`` backgrounds stay
allowlisted as a design question.

**Why a rendered, multi-theme check with a control.** An undefined
``var()`` still computes to *something*, so "is there a colour" proves
nothing — that is how this family survived four filings. #97's postmortem
names the trap exactly: ``--color-gray-200`` is ``#e2e8f0``, the same hex
``entry.css`` hardcoded, so in the default light theme the broken
declaration and the correct one are **the same colour**. This file hits
the same trap again from the other side: Midnight sets ``--text-muted``
to ``#64748b`` — the exact fallback ``entry.css`` paired with
``--color-text-muted``. A Midnight-only control would be vacuous for that
one target, in the same way a light-theme-only control was vacuous for
#97's.

So every target is resolved under **all six themes**, and each carries
its pre-fix declaration verbatim as a control. Two things are asserted:

1. in every theme, the shipped declaration resolves to whatever the
   palette token resolves to; and
2. in at least one theme the *pre-fix* declaration resolves to something
   else — otherwise the comparison cannot discriminate and the target's
   assertions prove nothing.

Declarations are read out of the live stylesheet through CSSOM and
re-resolved on a probe in the real document, which is what lets ``:hover``
rules — nine of the 28, including every ``--bg-hover`` use — be checked
at all. One rendered box (the note card) is measured the #97 way as well,
so the file is not purely CSSOM.

That machinery lives in ``_helpers/theme_probe.py`` — it is the same for
any future filing in this family, and keeping it out of here is what the
scenarios README's file-size budget asks for. What stays below is this
issue's own table of targets: one line per declaration, naming the rule,
the token it must now resolve to, and the declaration it replaced.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json

import pytest

from _helpers.theme_probe import (
    NOTE_CARD_PROBE,
    SLIDER_TRACK_PROBE,
    THEME,
    check_across_themes,
)
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


# label: [selectorText, property to set on the probe, computed property to
#         read back, the palette token it must now resolve to, the pre-fix
#         declaration verbatim (the control) or null where the repoint was a
#         dead nested fallback that already resolved correctly].
ENTRY_FORM_TARGETS = {
    # entry.css
    'note-card background':
        ['.note-card', 'background', 'backgroundColor',
         'var(--bg-primary)', 'var(--color-surface, #fff)'],
    'note-card-header background':
        ['.note-card-header', 'background', 'backgroundColor',
         'var(--bg-secondary)', 'var(--color-bg-subtle, #f8fafc)'],
    'note action colour':
        ['.note-card-actions .btn-text', 'color', 'color',
         'var(--text-muted)', 'var(--color-text-muted, #64748b)'],
    'note action hover background':
        ['.note-card-actions .btn-text:hover', 'background', 'backgroundColor',
         'var(--bg-tertiary)', 'var(--color-bg-muted, #f1f5f9)'],
    'note action hover colour':
        ['.note-card-actions .btn-text:hover', 'color', 'color',
         'var(--text-primary)', 'var(--color-text, #1e293b)'],
    'note subject option hover':
        ['.note-subject-option:hover', 'background', 'backgroundColor',
         'var(--bg-tertiary)', 'var(--bg-hover, #f3f4f6)'],
    # media.css
    'media dropzone hover':
        ['.media-dropzone:hover', 'background', 'backgroundColor',
         'var(--bg-tertiary)', 'var(--bg-hover, #f3f4f6)'],
    'media secondary hover border':
        ['.media-delete-options .btn-secondary:hover', 'border-color',
         'borderTopColor', 'var(--border-dark)', 'var(--border-hover, #9ca3af)'],
    'media subject checkbox hover':
        ['.media-subject-checkbox:hover', 'background', 'backgroundColor',
         'var(--bg-tertiary)', 'var(--bg-hover, #f3f4f6)'],
}

SETTINGS_TARGETS = {
    'mcp stopped dot':
        ['.mcp-status-dot.stopped', 'background-color', 'backgroundColor',
         'var(--text-muted)', 'var(--color-text-tertiary, #999)'],
    'mcp connection url code':
        ['.mcp-connection-url code', 'background', 'backgroundColor',
         'var(--bg-secondary)', 'var(--color-surface-alt, #f5f5f5)'],
    'mcp config header':
        ['.mcp-config-header', 'background', 'backgroundColor',
         'var(--bg-secondary)', 'var(--color-surface-alt, #f5f5f5)'],
    'mcp copy button':
        ['.mcp-copy-btn', 'background', 'backgroundColor',
         'var(--bg-primary)', 'var(--color-surface, #fff)'],
    'mcp config code block':
        ['.mcp-config-code', 'background', 'backgroundColor',
         'var(--bg-primary)', 'var(--color-surface, #fff)'],
}

TREE_EDITOR_TARGETS = {
    'apply button hover':
        ['.btn.btn-apply:hover', 'background', 'backgroundColor',
         'var(--color-success)', 'var(--color-success-hover, #059669)'],
    'rebalance button border':
        ['.btn.btn-rebalance-siblings', 'border', 'borderTopColor',
         'var(--border-color)', None],
    'rebalance button hover':
        ['.btn.btn-rebalance-siblings:hover:not(:disabled)', 'background',
         'backgroundColor', 'var(--bg-secondary)', None],
    'active unit button text':
        ['.weight-unit-btn.active', 'color', 'color',
         'var(--text-inverse)', 'var(--text-on-primary, white)'],
    'tree warning dot border':
        ['.tree-row-warning-dot', 'border', 'borderTopColor',
         'var(--color-warning)', None],
}

ENTRY_BROWSER_TARGETS = {
    # browser.css
    'draft toggle text':
        ['.draft-toggle:has(input:checked)', 'color', 'color',
         'var(--color-warning)', 'var(--warning-dark, #92400e)'],
    'draft badge text':
        ['.draft-badge', 'color', 'color',
         'var(--color-warning)', 'var(--warning-dark, #92400e)'],
    # export_dialog.css
    'export warning text':
        ['.export-warning', 'color', 'color',
         'var(--color-warning)', 'var(--warning-dark, #92400e)'],
    'export warning background':
        ['.export-warning', 'background', 'backgroundColor',
         'var(--color-warning-bg)', 'var(--warning-light, #fef3c7)'],
    'export copied button':
        ['.export-copy-btn.copied', 'background', 'backgroundColor',
         'var(--color-success)', 'var(--success-color, #10b981)'],
    'delimiter delete hover':
        ['.saved-delimiter-delete:hover', 'background', 'backgroundColor',
         'var(--color-error-bg)', 'var(--error-light, #fee2e2)'],
}

@pytest.mark.slow
@pytest.mark.regression
def test_entry_form_repoints_follow_the_palette(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """entry.css's five and media.css's three, on the page that links both."""
    wimi_page.goto('entry-form')
    check_across_themes(wimi_page, ENTRY_FORM_TARGETS, 'the entry form')

    # The same two declarations again, on a laid-out box rather than a probe.
    wimi_page.eval_js(THEME.format('midnight'))
    card = json.loads(wimi_page.eval_js(NOTE_CARD_PROBE))
    assert card['cardWidth'] not in (None, 'auto', '0px'), (
        f'The note card computes to {card["cardWidth"]} wide, so it is not being '
        'laid out and the colours read off it are not ones a student sees.'
    )
    assert card['cardBackground'] == card['bgPrimary'], (
        f'The note card renders {card["cardBackground"]!r} under Midnight while '
        f'--bg-primary is {card["bgPrimary"]!r}.'
    )
    assert card['headerBackground'] == card['bgSecondary'], (
        f'The note card header renders {card["headerBackground"]!r} under Midnight '
        f'while --bg-secondary is {card["bgSecondary"]!r}.'
    )


@pytest.mark.slow
@pytest.mark.regression
def test_settings_mcp_panel_repoints_follow_the_palette(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """settings.css's five, all in the MCP panel."""
    wimi_page.goto('settings')
    check_across_themes(wimi_page, SETTINGS_TARGETS, 'settings')


@pytest.mark.slow
@pytest.mark.regression
def test_tree_editor_repoints_follow_the_palette_and_the_dead_rule_is_gone(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """weight.css's five survivors, and the sixth declaration that was deleted."""
    wimi_page.goto('tree-editor')
    check_across_themes(wimi_page, TREE_EDITOR_TARGETS, 'the tree editor')

    slider = json.loads(wimi_page.eval_js(SLIDER_TRACK_PROBE))
    assert slider['classUsed'] is False, (
        '.weight-slider-track is applied to an element. #102 removed the rule '
        'because nothing in src/ used the class and nothing set --fill-percent; '
        'if the class is back, the rule has to come back with a --fill-percent '
        'that something actually writes.'
    )
    assert slider['ruleStillPresent'] is False, (
        'The .weight-slider-track rule is back in a stylesheet. It never '
        'rendered — the class is applied nowhere and --fill-percent was set '
        'nowhere, so the gradient was pinned at 0% by a dead fallback.'
    )


@pytest.mark.slow
@pytest.mark.regression
def test_entry_browser_repoints_follow_the_palette(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """browser.css's two and export_dialog.css's four.

    All six are the house tinted-badge pattern — ``--color-X`` text on
    ``--color-X-bg`` — which 69 other rules already use. Pinned at ``#92400e``
    the draft badge was dark amber on Midnight's ``--color-warning-bg``
    (``#451a03``): dark on dark.
    """
    wimi_page.goto('entry-browser')
    check_across_themes(wimi_page, ENTRY_BROWSER_TARGETS, 'the entry browser')
