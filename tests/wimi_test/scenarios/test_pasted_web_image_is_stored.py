"""Regression: an image copied from a web page pastes as the image, not a link (#941).

"Copy image" in a browser (the pane's included) puts two flavours on the
clipboard: the bitmap, and HTML holding ``<img src="https://...">``. TinyMCE
took the HTML, so the editor stored a remote URL. WIMI's pages are
``file://`` with ``LocalContentCanAccessRemoteUrls`` off (a security control,
see CLAUDE.md on #591), so that image can never load: the student saw a
broken image, which reads as "copying images does not work". Measured on the
MacBook, 2026-11-09: ``complete`` true, ``naturalWidth`` 0.

Owner, 2026-11-09: when a paste carries real image data, store the image
itself, the way a pasted screenshot is stored (``paste_data_images`` gives
a ``data:`` URI), and drop the web link.

The paste is a real ``paste`` event dispatched on the editor's body with a
``DataTransfer`` holding both flavours, which is what Chromium delivers. The
controls pin what must not change: ordinary rich-text HTML with no image
data pastes as before, and a bare image file (a screenshot) still embeds.
"""
from __future__ import annotations

import json

import pytest

from _helpers.w114_form_ready import poll, seed_empty_session, wait_for_form_ready
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

# A 1x1 red PNG.
PNG_B64 = ('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')
REMOTE = 'https://upload.wikimedia.org/wikipedia/commons/x/xx/Mitochondrion.png'


def _paste(wimi_page: WimiPage, *, html: str | None, with_file: bool) -> None:
    wimi_page.eval_js(f"""(() => {{
      const ed = EntryState.reflectionEditor.editor;
      ed.setContent(''); ed.focus();
      const win = ed.getWin();
      const dt = new win.DataTransfer();
      {f"dt.setData('text/html', {json.dumps(html)});" if html is not None else ''}
      if ({'true' if with_file else 'false'}) {{
        const bin = atob({json.dumps(PNG_B64)});
        const bytes = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
        dt.items.add(new win.File([bytes], 'image.png', {{ type: 'image/png' }}));
      }}
      const ev = new win.ClipboardEvent('paste', {{ clipboardData: dt, bubbles: true, cancelable: true }});
      ed.getBody().dispatchEvent(ev);
    }})()""")


def _content(wimi_page: WimiPage) -> str:
    return wimi_page.eval_js("EntryState.reflectionEditor.editor.getContent()")


@pytest.fixture
def entry_form(wimi_session: WimiTestSession, wimi_page: WimiPage) -> WimiPage:
    session_id = seed_empty_session(wimi_session.user.db, name='Paste')
    wimi_page.goto('entry-form', query={'session_id': session_id})
    wait_for_form_ready(wimi_page)
    assert poll(wimi_page, "!!(EntryState.reflectionEditor && EntryState.reflectionEditor.editor"
                           " && EntryState.reflectionEditor.editor.initialized)"), 'editor never initialised'
    return wimi_page


@pytest.mark.slow
@pytest.mark.regression
def test_a_copied_web_image_is_stored_as_the_image(entry_form: WimiPage) -> None:
    html = f"<meta charset='utf-8'><img src=\"{REMOTE}\" alt=\"Mitochondrion\"/>"
    _paste(entry_form, html=html, with_file=True)
    poll(entry_form, "EntryState.reflectionEditor.editor.getContent().includes('<img')")
    content = _content(entry_form)

    assert 'src="data:image/png;base64,' in content, (
        f'the pasted image was not stored as image data: {content!r}')
    assert 'http' not in content, f'the remote link survived the paste: {content!r}'
    assert content.count('<img') == 1, f'expected one image, got: {content!r}'


@pytest.mark.slow
@pytest.mark.regression
def test_rich_text_without_image_data_pastes_as_before(entry_form: WimiPage) -> None:
    """Control: a text copy (HTML, no file) is untouched."""
    _paste(entry_form, html='<p>The <strong>inner</strong> membrane</p>', with_file=False)
    poll(entry_form, "EntryState.reflectionEditor.editor.getContent().includes('membrane')")
    content = _content(entry_form)
    assert '<strong>inner</strong>' in content and 'membrane' in content, content


@pytest.mark.slow
@pytest.mark.regression
def test_a_screenshot_still_embeds(entry_form: WimiPage) -> None:
    """Control: an image file with no HTML (a screenshot) embeds as before."""
    _paste(entry_form, html=None, with_file=True)
    poll(entry_form, "EntryState.reflectionEditor.editor.getContent().includes('<img')")
    content = _content(entry_form)
    assert '<img' in content and 'http' not in content, content
