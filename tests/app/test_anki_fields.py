"""Anki field HTML into text and image filenames (#784 Wave 2)."""

from __future__ import annotations

import pytest

from app.anki.fields import field_to_text, is_media_filename


def test_blocks_and_breaks_become_lines():
    out = field_to_text('<div>One</div><div>Two<br>Three</div><p>Four</p>')
    assert out.text == 'One\nTwo\nThree\nFour'


def test_entities_decode_and_spaces_collapse():
    # &nbsp; decodes to a no-break space and is kept as one; ordinary runs collapse.
    assert field_to_text('a &amp;&nbsp;b   c').text == 'a &\xa0b c'


def test_cloze_reads_as_its_answer():
    assert field_to_text('The {{c1::aorta::vessel}} and {{c2::vena cava}}').text == \
        'The aorta and vena cava'


def test_images_become_filenames_not_text():
    out = field_to_text('Look <img src="heart.png"> and <img src="lung.jpg"/> '
                        'again <img src="heart.png">')
    assert out.images == ['heart.png', 'lung.jpg']
    assert 'heart' not in out.text


@pytest.mark.parametrize('src', [
    'http://x.example/a.png', '../secret.png', 'dir/a.png', 'C:\\a.png',
    'data:image/png;base64,AAAA', '.hidden.png', '',
])
def test_an_image_that_is_not_a_media_file_is_dropped(src):
    """These would never name a file in Anki's flat media folder, and must
    never reach retrieveMediaFile."""
    assert field_to_text(f'<img src="{src}">').images == []
    assert not is_media_filename(src)


def test_script_and_style_are_dropped_not_shown():
    out = field_to_text('<script>alert(1)</script><style>p{}</style>Safe')
    assert out.text == 'Safe'


def test_markup_never_survives_as_markup():
    """The page sets this text as text; a tag in the field must come out as
    nothing or as its words, never as a string the page could mistake."""
    out = field_to_text('<b onclick="x()">bold</b> <i>it</i>')
    assert out.text == 'bold it'


def test_sound_tags_are_dropped():
    assert field_to_text('Word [sound:word.mp3]').text == 'Word'


def test_empty():
    assert field_to_text('').text == '' and field_to_text('').images == []
