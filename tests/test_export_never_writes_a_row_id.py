"""The export never writes a database row id as a file identifier (#237, #67).

A source check, in the spirit of ``scripts/check_css_empty_selector.py``: the
guarantee is *"nowhere"*, and the regression scenario beside this can only
cover the shapes somebody thought to build.

**Why a source check earns its keep here.** The rule was already written down
for subjects in #67 — four lines of comment in ``import_export.js`` saying *not*
``node.id`` — and it was still violated one level up, for dimensions, where a
mis-identified axis archives its whole subject tree. A comment did not hold. The
scenario needs a running WIMI and is marked ``slow``; this runs in milliseconds
on every ``pytest`` and fails on the exact assignment that was the bug.

It deliberately checks for the *shape of the mistake* rather than for the fix.
Asserting "``import_id`` appears somewhere" would pass a file that wrote both.
"""
from __future__ import annotations

import pathlib
import re

import pytest

WEB_JS = pathlib.Path(__file__).resolve().parents[1] / 'src' / 'web' / 'js'
IMPORT_EXPORT = WEB_JS / 'import_export.js'

#: Expressions that evaluate to a database row id. Each of these was, or could
#: plausibly become, the right-hand side of an ``id:`` in an exported file.
_ROW_ID_EXPRESSIONS = (
    'TreeState.currentDimensionId',
    'dimension.id',
    'node.id',
    'dim.id',
)

#: Keys a file identifier is written under. ``dimension_id`` is included
#: because that spelling in ``_metadata`` is what #237 was filed about: it is
#: not the documented top-level target selector, it merely looked like it.
_IDENTIFIER_KEYS = ('id', 'dimension_id', 'import_id', 'dimension_import_id')


def _identifier_assignments(source: str):
    """``(key, value)`` for every ``<key>: <expr>`` an export object could use.

    Matches the object-literal spelling and the ``cleanNode.id = ...``
    property spelling, because #67's rule lives in the second one and #237's
    bug lived in the first.
    """
    for key in _IDENTIFIER_KEYS:
        for match in re.finditer(
            rf'(?:^|[\s{{,;])(?:cleanNode\.|axis\.)?{key}\s*[:=]\s*([^,;\n}}]+)',
            source,
        ):
            yield key, match.group(1).strip()


def test_no_row_id_is_written_as_a_file_identifier():
    source = IMPORT_EXPORT.read_text(encoding='utf-8')

    offenders = []
    for key, value in _identifier_assignments(source):
        for expression in _ROW_ID_EXPRESSIONS:
            # `aliasMap.get(node.id)` is a legitimate use of the row id -- it
            # keys an in-memory map and never reaches the file -- so the match
            # has to be the whole value, not a substring of a larger call.
            if value == expression or value == f'{expression};':
                offenders.append(f'{key}: {value}')

    assert offenders == [], (
        'these write a database row id as a file identifier, which means '
        'nothing in another profile and claims to identify things that were '
        f'never imported (#67, #237): {offenders}'
    )


def test_the_check_would_catch_the_original_bug():
    """A negative control, because a source check that matches nothing is
    indistinguishable from a passing one.

    This is the exact line #237 was filed about. If the scanner stops
    recognising it -- a reformat, a rename -- the test above silently stops
    protecting anything.
    """
    reintroduced = (
        '...(isDimensionMode && {\n'
        '    dimension_id: TreeState.currentDimensionId,\n'
        '    dimension_name: "x"\n'
        '})\n'
    )

    found = [
        (key, value) for key, value in _identifier_assignments(reintroduced)
        if value in _ROW_ID_EXPRESSIONS
    ]

    assert found == [('dimension_id', 'TreeState.currentDimensionId')], found


@pytest.mark.parametrize('spelling', [
    'cleanNode.id = node.id;',
    'axis.id = dimension.id',
    'id: dim.id,',
])
def test_the_check_catches_each_row_id_spelling(spelling):
    """The three ways this mistake can be written, one test each.

    `cleanNode.id = node.id` is the #67 subject version, `axis.id =
    dimension.id` the #237 dimension version, and `id: dim.id` the shape a
    future whole-exam writer would most naturally reach for.
    """
    found = [
        value for _, value in _identifier_assignments(spelling)
        if value in _ROW_ID_EXPRESSIONS
    ]
    assert found, f'the scanner did not recognise {spelling!r}'
