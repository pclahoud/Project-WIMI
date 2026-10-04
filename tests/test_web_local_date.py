""""Today" is the student's day, and no page may spell it in UTC.

Issue #286. Five sites computed the current date as

    new Date().toISOString().split('T')[0]

which is the **UTC** date. West of Greenwich that names tomorrow for the last
hours of every evening; east of it, yesterday for the first hours of every
morning. Two of the five wrote it straight into a stored value --
``#session-date`` (a required field nobody is asked to confirm, passed to
``createReviewSession``) and the import wizard's twin -- and one used it as a
comparison key against data the backend had generated from its own *local*
clock.

Why local is the only consistent answer is argued in ``src/web/js/local_date.js``
and comes down to three measurements in the backend: ``sessions.py`` defaults
``date_encountered`` with ``date.today()``, ``get_activity_heatmap`` emits days
up to ``datetime.now().date()``, and ``_calculate_streak_info`` compares against
the same. All three are **local**. A UTC "tomorrow" is therefore not merely a
day out -- it is a key that is absent from the heatmap and ahead of the streak
calculation, so the row counts nowhere.

What this module guards, and why statically
-------------------------------------------
The behaviour is pinned by a scenario
(``tests/wimi_test/scenarios/test_session_date_defaults_to_local_day.py``),
which drives a real timezone through CDP. That test cannot see a *sixth* site
appearing somewhere it does not look, and #286's own closing line asks for
exactly that: *"A single shared helper ... would stop a sixth site appearing;
today each caller spells it out."* So:

1. No first-party page script may contain the UTC date-extraction form.
2. A page whose scripts call ``LocalDate`` must link ``local_date.js``. That
   is the per-page link gotcha ``CLAUDE.md`` records for stylesheets, one
   layer over: miss the link and ``LocalDate`` is ``undefined`` on that page
   only.

A *timestamp* is deliberately still allowed to be UTC. ``new Date()
.toISOString()`` with no date extraction is correct for ``exported_at`` and is
left alone; only the forms that keep the first ten characters are banned.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / 'src' / 'web'
WEB_JS = WEB / 'js'
WEB_HTML = WEB / 'html'

#: Vendored libraries are not ours to police.
VENDORED = ('lib',)

#: The four spellings that keep the date half of a UTC instant. `slice` and
#: `substring` are included although #286 only found `split`: they are the
#: same defect and the next author may reach for either.
UTC_DATE_FORM = re.compile(
    r"""toISOString\(\)\s*\.\s*(?:
          split\(\s*['"]T['"]\s*\)\s*\[\s*0\s*\]
        | slice\(\s*0\s*,\s*10\s*\)
        | substring\(\s*0\s*,\s*10\s*\)
        | substr\(\s*0\s*,\s*10\s*\)
    )""",
    re.VERBOSE,
)

#: The original defect, verbatim from `session_setup.js` before the fix. The
#: negative control below asserts the detector still fires on it -- a sweep
#: whose detector has quietly stopped matching reports a clean tree.
ORIGINAL_DEFECT = "    return today.toISOString().split('T')[0];"


def _first_party_js() -> list[Path]:
    return sorted(
        p for p in WEB_JS.rglob('*.js')
        if not any(part in VENDORED for part in p.relative_to(WEB_JS).parts)
    )


def _code_lines(text: str) -> list[tuple[int, str]]:
    """Lines that are not whole-line comments.

    A comment *quoting* the banned expression is exactly what a good fix
    leaves behind -- ``local_date.js`` names it to explain itself, and
    ``entry_browser.js`` and ``analytics_dashboard.js`` both mention
    ``toISOString`` in prose. So whole-line comments are skipped. The limit,
    stated rather than discovered later: a banned expression hidden in a
    *trailing* comment on a code line would still be reported. That is the
    safe direction to be wrong in.
    """
    out: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith(('*', '//', '/*')):
            continue
        out.append((number, line))
    return out


class _ScriptSources(HTMLParser):
    """The `src` of every <script> a page links."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != 'script':
            return
        src = dict(attrs).get('src')
        if src:
            self.sources.append(src)

    handle_startendtag = handle_starttag


def _linked_scripts(page: Path) -> list[str]:
    parser = _ScriptSources()
    parser.feed(page.read_text(encoding='utf-8'))
    return parser.sources


@pytest.mark.unit
@pytest.mark.parametrize(
    'script', _first_party_js(), ids=lambda p: p.name,
)
def test_no_page_script_computes_today_in_utc(script: Path) -> None:
    """#286's expression, banned outright."""
    offenders = [
        (number, line.strip())
        for number, line in _code_lines(script.read_text(encoding='utf-8'))
        if UTC_DATE_FORM.search(line)
    ]
    assert not offenders, (
        f'{script.relative_to(REPO)} computes a calendar date from '
        f'toISOString(), which is UTC:\n'
        + '\n'.join(f'  :{n}  {text}' for n, text in offenders)
        + '\n\nThat names a different day from the student\'s for part of '
          'every day, and #286 is what happens when such a value is stored. '
          'Use LocalDate.today() / LocalDate.toISODate(date). A UTC '
          '*timestamp* (toISOString() with no date extraction) is fine and is '
          'not what this matches.'
    )


@pytest.mark.unit
def test_the_detector_fires_on_the_original_defect() -> None:
    """The negative control, without which the sweep above is unfalsifiable."""
    assert UTC_DATE_FORM.search(ORIGINAL_DEFECT), (
        'The detector no longer matches the line #286 was filed for, so the '
        'sweep would pass on a tree that still carries the defect. Fix the '
        'pattern, not this assertion.'
    )
    assert _code_lines(ORIGINAL_DEFECT) == [(1, ORIGINAL_DEFECT)], (
        'The comment filter now discards the defect line itself, which would '
        'hide every real occurrence.'
    )


@pytest.mark.unit
def test_the_helper_is_the_only_definition() -> None:
    """One statement of the rule, so two cannot drift apart."""
    definers = [
        p.relative_to(REPO).as_posix() for p in _first_party_js()
        if 'window.LocalDate' in p.read_text(encoding='utf-8')
    ]
    assert definers == ['src/web/js/local_date.js'], (
        f'window.LocalDate is defined in {definers}. #286 exists because the '
        f'same four-line computation was written out five times; a second '
        f'definition is that again.'
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    'page', sorted(WEB_HTML.rglob('*.html')), ids=lambda p: p.name,
)
def test_a_page_whose_scripts_use_localdate_links_it(page: Path) -> None:
    """The per-page link gotcha, enforced instead of remembered.

    Only the scripts a page links *directly* are examined. ``api/_loader.js``
    pulls its modules in at runtime, so a LocalDate call added down there
    would not be seen here -- said rather than left to be found, and no api
    module uses it today.
    """
    linked = _linked_scripts(page)
    links_helper = any(src.endswith('/local_date.js') for src in linked)

    users = []
    for src in linked:
        if src.startswith('qrc:') or src.endswith('/local_date.js'):
            continue
        candidate = (page.parent / src).resolve()
        if not candidate.is_file() or WEB_JS not in candidate.parents:
            continue
        if re.search(r'\bLocalDate\s*\.', candidate.read_text(encoding='utf-8')):
            users.append(candidate.relative_to(REPO).as_posix())

    if users:
        assert links_helper, (
            f'{page.relative_to(REPO)} links {users}, which call LocalDate, '
            f'but does not link src/web/js/local_date.js. LocalDate would be '
            f'undefined on this page only -- the stylesheet gotcha in '
            f'CLAUDE.md, one layer over. Add '
            f'<script src="../js/local_date.js"></script> before them.'
        )
    else:
        assert not links_helper, (
            f'{page.relative_to(REPO)} links local_date.js and none of its '
            f'scripts use it. Drop the link, or this page is carrying a '
            f'dependency nobody can see is unused.'
        )
