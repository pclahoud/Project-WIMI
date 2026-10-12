"""The relations build stages the C++ runtime family itself (#367).

The frozen preload (``packaging/rthook_relations_build.py`` ->
``src/app/msvc_runtime.py``) needs a newer ``msvcp140.dll`` than Qt's 14.26,
with its satellites beside it, inside the bundle. Before this the only 14.50
copies were one PyInstaller collected incidentally and whisper's #158 copy --
two accidents, and losing both fails silently: torch stops importing in the
artifact students took the larger download for.

Text-level, like ``test_build_spec_console_window.py``: a spec is executed by
PyInstaller with injected globals and cannot be imported here, and the failure
being guarded against is somebody editing it.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / 'wimi.spec'
FAMILY = {'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll', 'concrt140.dll'}


def _relations_block(text: str) -> str:
    """The body of the top-level ``if RELATIONS_BUILD:`` that ends at Analysis."""
    start = text.index('\nif RELATIONS_BUILD:\n')
    end = text.index('\na = Analysis(', start)
    return text[start:end]


def _family_tuple(block: str) -> set[str]:
    m = re.search(r'RELATIONS_MSVC_FAMILY\s*=\s*(\([^)]*\))', block, re.S)
    assert m, 'wimi.spec no longer declares RELATIONS_MSVC_FAMILY in the relations block'
    return set(ast.literal_eval(m.group(1)))


@pytest.mark.unit
def test_the_relations_build_stages_the_whole_family():
    """All four, or the preload mixes 14.50 with Qt's 14.26 satellites."""
    block = _relations_block(SPEC.read_text(encoding='utf-8'))
    assert _family_tuple(block) == FAMILY


@pytest.mark.unit
def test_it_stages_them_at_the_bundle_root_from_system32():
    """The root is where the frozen preload looks first (msvc_runtime._search_dirs),
    so the satellites sit beside the msvcp140 it chooses. System32 because
    #195 (b) ships the runtime app-local from there."""
    block = _relations_block(SPEC.read_text(encoding='utf-8'))
    assert re.search(
        r"binaries\s*\+=\s*\[\(str\(_system32\s*/\s*name\),\s*'\.'\)\s*for\s+name\s+in\s+RELATIONS_MSVC_FAMILY\]",
        block), 'the family is not staged from _system32 into the bundle root'


@pytest.mark.unit
def test_a_missing_dll_stops_the_build():
    """#158's rule: a warning is read where it does not matter and ignored
    where it does."""
    block = _relations_block(SPEC.read_text(encoding='utf-8'))
    assert re.search(r'if _missing_family:\s*\n\s*raise SystemExit\(', block)


@pytest.mark.unit
def test_the_default_build_is_untouched():
    """Everything about the family lives inside the relations block."""
    text = SPEC.read_text(encoding='utf-8')
    block = _relations_block(text)
    outside = text.replace(block, '')
    assert 'RELATIONS_MSVC_FAMILY' not in outside


@pytest.mark.unit
def test_the_family_is_never_upx_compressed():
    block = _relations_block(SPEC.read_text(encoding='utf-8'))
    assert re.search(r'whisper_upx_exclude\s*\+=.*RELATIONS_MSVC_FAMILY', block)


@pytest.mark.unit
def test_the_frozen_preload_looks_at_the_bundle_root_first():
    """Ties go to the earlier directory, and the incidental root copy is the
    same 14.50 as System32's -- so the root must come first, or the preload
    could choose a 14.50 msvcp140 with no satellites beside it."""
    src = (ROOT / 'src' / 'app' / 'msvc_runtime.py').read_text(encoding='utf-8')
    frozen = src[src.index("if getattr(sys, 'frozen', False):", src.index('def _search_dirs')):]
    first = re.search(r'return \[\s*(\w+)\s*,', frozen)
    assert first and first.group(1) == 'base', 'the bundle root is not searched first'
