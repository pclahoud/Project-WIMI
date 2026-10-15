"""Entry detail -> Anki cards (#784 Wave 4): what the scenarios do not reach.

- The section ships ``hidden`` and the stylesheet makes ``hidden`` win over
  its own ``display`` rules. The calendar dialogs painted at load because a
  class's ``display: flex`` beat the attribute (#778), and every static sweep
  was green while it happened.
- It sits before the plugin slot, which stays for other plugins.
- The script builds from nodes, never parses a string as HTML, and attaches
  its listeners once rather than per render: the plugin's re-bound handler
  made one Suspend press suspend and then unsuspend.
- It starts from ``entry-detail:ready``, which ``entry_detail.js`` fires after
  ``showContent()``, so the section cannot hold the page back.
- #815's owner decisions, which a sweep could undo without any scenario
  noticing: the section sits right after the explanation, a field whose name
  ends in "id" is never drawn, and the proposal answers need the proposals to
  narrow the list.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HTML = (REPO / "src/web/html/entry_detail.html").read_text(encoding="utf-8")
JS = (REPO / "src/web/js/anki_stats_panel.js").read_text(encoding="utf-8")
CSS = (REPO / "src/web/css/anki.css").read_text(encoding="utf-8")
DETAIL_JS = (REPO / "src/web/js/entry_detail.js").read_text(encoding="utf-8")


def _section() -> str:
    start = HTML.index('<section class="content-section anki-section"')
    return HTML[start:HTML.index("</section>", start)]


def test_the_section_ships_hidden_and_labelled():
    opening = _section().split(">", 1)[0]
    assert re.search(r"\shidden(\s|$)", opening), opening
    assert 'aria-labelledby="anki-heading"' in opening
    assert '<h2 class="section-title" id="anki-heading">' in _section()


def test_hidden_beats_the_sections_own_display():
    rule = re.search(r"\.anki-section\[hidden\],\s*\.anki-section \[hidden\]\s*\{([^}]*)\}", CSS)
    assert rule and "display: none" in rule.group(1)


def test_it_sits_before_the_plugin_slot():
    assert HTML.index('id="anki-section"') < HTML.index('data-plugin-slot="detail-after-content"')


def test_assets_are_linked_once_and_after_the_page_script():
    assert HTML.count('href="../css/anki.css"') == 1
    assert HTML.count('src="../js/anki_stats_panel.js"') == 1
    assert HTML.index('src="../js/entry_detail.js"') < HTML.index('src="../js/anki_stats_panel.js"')


def test_every_id_the_script_reads_is_in_the_section():
    wanted = set(re.findall(r"\$\('([a-z0-9-]+)'\)", JS))
    assert wanted >= {"anki-section", "anki-status", "anki-cards", "anki-refresh"}, wanted
    ids = set(re.findall(r'id="([a-z0-9-]+)"', _section()))
    assert wanted <= ids, sorted(wanted - ids)


def test_the_script_never_parses_a_string_as_html():
    assert not re.search(r"\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML", JS)
    assert "textContent" in JS


def test_listeners_are_attached_once_in_wire_only():
    """Every addEventListener is inside wire(), which runs once per page."""
    wire = JS[JS.index("function wire()"):JS.index("if (document.readyState")]
    assert JS.count("addEventListener(") == wire.count("addEventListener(") + 1, (
        "a listener outside wire() (the one extra is the DOMContentLoaded hook)")
    assert "{once: true}" in wire


def test_the_page_fires_ready_after_it_is_drawn():
    show = DETAIL_JS.index("this.showContent();\n\n            // Sections that load")
    fire = DETAIL_JS.index("new CustomEvent('entry-detail:ready'")
    assert show < fire


def test_the_estimates_are_labelled_and_factor_is_ease():
    """Owner decision 11."""
    for label in ("Stability (estimated)", "Recall now (estimated)", "Next review (estimated)"):
        assert f"'{label}'" in JS, label
    assert "'Ease'" in JS and "Difficulty" not in JS


def test_the_section_sits_right_after_the_explanation():
    """Owner, #815: the cards are what to review once the why is written."""
    explanation = HTML.index('id="explanation-content"')
    anki = HTML.index('id="anki-section"')
    assert explanation < anki < HTML.index('class="attachments-notes-section"')
    between = HTML[explanation:anki]
    assert between.count('<section') == 1, 'another section sits between the two'


def _load_tooling_pattern():
    import re as _re
    match = _re.search(r"const TOOLING_FIELD = /(.+)/(\w*);", JS)
    assert match, 'TOOLING_FIELD is gone'
    return _re.compile(match.group(1), _re.I if 'i' in match.group(2) else 0)


def test_identifier_fields_are_never_drawn_and_real_fields_are():
    """Owner, #815: ``ankihub_id`` was drawn on every AnKing card. Positive
    controls keep the pattern from swallowing real field names ("First Aid"
    ends in "aid", not "id")."""
    pattern = _load_tooling_pattern()
    for name in ('ankihub_id', 'Note ID', 'note-id', 'id'):
        assert pattern.search(name), name
    for name in ('Text', 'Extra', 'First Aid', 'Sketchy', 'OME', 'Pathoma', 'Fluid'):
        assert not pattern.search(name), name


def test_answers_are_drawn_only_when_the_proposals_narrow_the_list():
    """Owner, #815: at most half the cards proposed, or no answers."""
    narrows = JS[JS.index("function narrows(p)"):]
    narrows = narrows[:narrows.index("}") + 1]
    assert "n * 2 <= p.cards.length" in narrows, narrows
    render = JS[JS.index("function render(p)"):]
    assert "if (narrows(p))" in render
