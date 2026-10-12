"""Torch's vendored licence tree leaves the bundle only because #336 conveys it (#408).

PyInstaller copies torch's ``.dist-info`` into the relations bundle whole, and
its ``licenses/`` subtree is the longest path in it: 137 characters relative to
the Windows dist root, 149 inside a macOS ``.app``. Under Windows' default
``MAX_PATH`` that leaves a recipient about 123 characters for wherever they
unzip, and an extractor that runs out skips the file silently. Both ``.spec``
files therefore drop that subtree (owner's decision, 2026-10-06).

**This is a path fix that could remove a licence text**, so it is safe only as
a pair. ``scripts/stage_license_files.py`` copies the same texts from the
installed distribution into ``licenses/third-party/torch-<version>/`` and
refuses the build if that folder comes out empty. A relations build with the
exclusion and without the staged folder would convey nothing for torch.

Measured on a MacBook Air relations build: 100 files dropped from the bundle,
100 texts plus ``FILES.txt`` staged, ``codesign --verify --deep --strict``
passing, and the real model loading inside the frozen app.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPECS = ('wimi.spec', 'wimi_macos.spec')


def _filter_source(spec: str) -> str:
    text = (ROOT / spec).read_text(encoding='utf-8')
    match = re.search(r"\n    def _is_torch_licence_tree\(dest\):\n(?:        .*\n)+", text)
    assert match, f'{spec} no longer defines _is_torch_licence_tree'
    return match.group(0)


@pytest.mark.parametrize('spec', SPECS)
def test_the_filter_is_scoped_to_the_relations_build_and_runs_before_pyz(spec):
    text = (ROOT / spec).read_text(encoding='utf-8')
    define = text.index('def _is_torch_licence_tree(dest):')
    guard = text.rindex('\nif RELATIONS_BUILD:\n', 0, define)
    assert text.index('a = Analysis(') < guard < define, (
        'the filter must act on the Analysis result, inside a RELATIONS_BUILD '
        'block, so the default artifact is untouched')
    applied = text.index('a.datas = [d for d in a.datas if not _is_torch_licence_tree(d[0])]')
    assert define < applied < text.index('pyz = PYZ(')


@pytest.mark.parametrize('spec', SPECS)
@pytest.mark.parametrize('dest, dropped', [
    # The path #408 measured, in both separators.
    ('torch-2.14.1+cpu.dist-info/licenses/third_party/flash-attention/'
     'third_party/aiter/3rdparty/composable_kernel/docs/LICENSE.rst', True),
    ('torch-2.14.1.dist-info\\licenses\\LICENSE', True),
    # What stays: transformers reads torch's version through importlib.metadata.
    ('torch-2.14.1.dist-info/METADATA', False),
    ('torch-2.14.1.dist-info/RECORD', False),
    # Nobody else's licences, and nothing that merely resembles the name.
    ('numpy-2.5.3.dist-info/licenses/LICENSE.txt', False),
    ('torchvision-0.29.0.dist-info/licenses/LICENSE', False),
    ('torch/licenses/README', False),
])
def test_only_torchs_licence_subtree_is_dropped(spec, dest, dropped):
    namespace: dict = {}
    exec(_filter_source(spec).replace('\n    ', '\n'), namespace)
    assert namespace['_is_torch_licence_tree'](dest) is dropped


def test_the_two_specs_filter_identically():
    """Two copies of one rule drift; CLAUDE.md records it for these two files."""
    assert _filter_source('wimi.spec') == _filter_source('wimi_macos.spec')


def test_the_stager_refuses_a_relations_build_that_stages_no_torch_text(
        tmp_path, monkeypatch):
    """The other half: never an artifact that conveys neither copy."""
    sys.path.insert(0, str(ROOT / 'scripts'))
    import relations_third_party
    import stage_license_files

    def stage_nothing_for_torch(bundle_dir, roots=None):
        root = bundle_dir / relations_third_party.THIRD_PARTY_DIR
        (root / 'torch-2.14.1').mkdir(parents=True)
        (root / 'torch-2.14.1' / relations_third_party.FILES_NAME).write_text('')
        (root / relations_third_party.INDEX_NAME).write_text('')
        return []

    monkeypatch.setattr(relations_third_party, 'stage_relations',
                        stage_nothing_for_torch)
    with pytest.raises(SystemExit) as exc:
        stage_license_files.stage(tmp_path, relations=True)
    assert 'conveys neither' in str(exc.value)


def test_the_stager_accepts_a_staged_torch_text(tmp_path, monkeypatch):
    """Control: the refusal is about an EMPTY folder, not any relations build."""
    sys.path.insert(0, str(ROOT / 'scripts'))
    import relations_third_party
    import stage_license_files

    def stage_one_torch_text(bundle_dir, roots=None):
        root = bundle_dir / relations_third_party.THIRD_PARTY_DIR
        (root / 'torch-2.14.1').mkdir(parents=True)
        (root / 'torch-2.14.1' / '001-LICENSE').write_text('text')
        (root / 'torch-2.14.1' / relations_third_party.FILES_NAME).write_text('')
        (root / relations_third_party.INDEX_NAME).write_text('')
        return []

    monkeypatch.setattr(relations_third_party, 'stage_relations',
                        stage_one_torch_text)
    stage_license_files.stage(tmp_path, relations=True)
