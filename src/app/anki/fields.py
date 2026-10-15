"""Anki field HTML into plain text and image filenames (#784 Wave 2).

A cached field value is whatever Anki stored: HTML, possibly from a deck the
student downloaded, so it is **untrusted content**. The entry detail page
never sets it as HTML. This module is where it stops being HTML -- on the
Python side, so the page receives only text and a list of filenames it can
ask the bridge for, and the plugin's ``textarea.innerHTML`` trick (#784 plan,
finding 7) has no successor.

Pure and stdlib-only (``html.parser``), so it runs anywhere and every rule has
a test.

Rules
-----
- Block elements and ``<br>`` become line breaks; a run of them is one break.
- ``<img src>`` becomes a filename in ``images``, never text. Only a bare
  Anki media filename is kept: anything with a path separator, a scheme, a
  leading dot or a ``data:`` prefix is dropped, because it does not name a
  file in Anki's media folder and must never be handed to
  ``retrieveMediaFile``.
- Cloze markup ``{{c1::answer::hint}}`` reads as ``answer``.
- ``[sound:...]`` tags are dropped; the page cannot play them.
- ``<script>`` and ``<style>`` content is dropped, not shown as text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import List

_BLOCK_TAGS = frozenset({
    'address', 'article', 'blockquote', 'dd', 'div', 'dl', 'dt', 'figcaption',
    'figure', 'footer', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'header', 'hr',
    'li', 'ol', 'p', 'pre', 'section', 'table', 'tr', 'ul',
})
_SKIP_TAGS = frozenset({'script', 'style'})

_CLOZE = re.compile(r'\{\{c\d+::(.*?)(?:::[^}]*)?\}\}', re.DOTALL)
_SOUND = re.compile(r'\[sound:[^\]]*\]')
_BLANK_LINES = re.compile(r'\n(?:\s*\n)+')
_SPACES = re.compile(r'[ \t\r\f\v]+')


def is_media_filename(name: str) -> bool:
    """Whether ``name`` can only be a file in Anki's flat media folder."""
    if not name or len(name) > 255:
        return False
    if name.startswith('.') or name.lower().startswith('data:'):
        return False
    return not any(ch in name for ch in ('/', '\\', ':', '\x00'))


@dataclass
class FieldText:
    text: str
    images: List[str] = field(default_factory=list)


class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.images: List[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        if tag == 'br':
            self.parts.append('\n')
        elif tag in _BLOCK_TAGS:
            self.parts.append('\n')
        elif tag == 'img':
            src = dict(attrs).get('src') or ''
            if is_media_filename(src) and src not in self.images:
                self.images.append(src)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def field_to_text(value: str) -> FieldText:
    """The readable text of one field value and the images it shows."""
    if not value:
        return FieldText('')
    reader = _Reader()
    reader.feed(value)
    reader.close()
    text = ''.join(reader.parts)
    text = _CLOZE.sub(lambda m: m.group(1), text)
    text = _SOUND.sub('', text)
    text = '\n'.join(_SPACES.sub(' ', line).strip() for line in text.split('\n'))
    text = _BLANK_LINES.sub('\n', text).strip()
    return FieldText(text, reader.images)
