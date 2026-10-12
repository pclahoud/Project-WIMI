"""A relations build conveys its runtime's licences (#336).

The relations artifact bundles torch, transformers, gliner2 and everything they
depend on, mostly under Apache-2.0, whose section 4 requires a copy of the
licence and any NOTICE file to go with every copy. Until #336 the artifact
conveyed none of them. ``scripts/relations_third_party.py`` stages them from the
build environment's installed metadata; ``scripts/stage_license_files.py`` calls
it for a relations build.

Most of this runs anywhere. The last section stages the real runtime and runs
only where it is installed (the relations venv), because the main venv has no
torch by design (#358).
"""
from __future__ import annotations

import email.message
import hashlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import relations_third_party as rtp  # noqa: E402

HAS_RUNTIME = importlib.util.find_spec("gliner2") is not None


class FakeDist:
    def __init__(self, **fields):
        self.metadata = email.message.Message()
        for key, value in fields.items():
            for item in value if isinstance(value, list) else [value]:
                self.metadata[key.replace("_", "-")] = item
        self.version = "1.0"


# --------------------------------------------------------------------------
# Naming: flat, short, collision-free
# --------------------------------------------------------------------------

def test_a_top_level_licence_keeps_its_name():
    assert rtp.short_name(1, PurePosixPath("LICENSE")) == "LICENSE"


def test_a_nested_licence_is_numbered_and_keeps_its_project_name():
    rel = PurePosixPath("third_party/flash-attention/third_party/aiter/3rdparty/composable_kernel/LICENSE")
    assert rtp.short_name(7, rel) == "007-composable_kernel-LICENSE"


def test_two_nested_files_with_the_same_name_cannot_collide():
    a = rtp.short_name(2, PurePosixPath("third_party/FP16/LICENSE"))
    b = rtp.short_name(3, PurePosixPath("third_party/FXdiv/LICENSE"))
    assert a != b


def test_no_staged_name_exceeds_the_limit():
    """The reason the files are flat: torch's own depth overran 260 characters."""
    rel = PurePosixPath("a/" + "x" * 200 + "/LICENSE-" + "y" * 100)
    assert len(rtp.short_name(42, rel)) <= rtp.MAX_NAME


# --------------------------------------------------------------------------
# Licence strings are read, never inferred
# --------------------------------------------------------------------------

def test_the_licence_expression_wins_when_present():
    dist = FakeDist(License_Expression="Apache-2.0", Classifier="License :: OSI Approved :: MIT License")
    assert rtp.licence_string(dist) == "Apache-2.0"


def test_classifiers_are_used_when_there_is_no_expression():
    dist = FakeDist(Classifier=["License :: OSI Approved :: Apache Software License",
                                "Programming Language :: Python"])
    assert rtp.licence_string(dist) == "Apache Software License"


def test_nothing_stated_says_so_rather_than_guessing():
    assert "not stated" in rtp.licence_string(FakeDist())


# --------------------------------------------------------------------------
# The reviewed fallback for a component that ships no licence file
# --------------------------------------------------------------------------

def test_the_apache_text_is_the_pinned_apache_org_text():
    data = rtp.APACHE_TEXT.read_bytes()
    assert hashlib.sha256(data).hexdigest() == rtp.APACHE_SHA256
    assert len(data) == 11358 and b"Apache License" in data[:200]


def test_the_fallback_pin_agrees_with_the_licence_gate():
    """Two pins for one file would drift; the gate's is the one CI runs."""
    import check_bundled_licenses as gate

    digest, _, _ = gate.EXPECTED[Path("licenses/Apache-2.0.txt")]
    assert digest == rtp.APACHE_SHA256


def test_a_listed_component_that_declares_apache_gets_the_standard_text():
    dist = FakeDist(Classifier="License :: OSI Approved :: Apache Software License")
    assert rtp._declared_only_text("tokenizers", dist) == rtp.APACHE_TEXT


def test_a_listed_component_whose_licence_changed_stops_the_build():
    dist = FakeDist(License_Expression="GPL-3.0-only")
    with pytest.raises(SystemExit, match="Review DECLARED_ONLY"):
        rtp._declared_only_text("tokenizers", dist)


def test_an_unlisted_component_with_no_licence_file_gets_no_fallback():
    dist = FakeDist(Classifier="License :: OSI Approved :: Apache Software License")
    assert rtp._declared_only_text("some-new-package", dist) is None


# --------------------------------------------------------------------------
# The stager: default builds unchanged, relations builds refuse a broken env
# --------------------------------------------------------------------------

def _run_stager(bundle: Path, *, relations: bool):
    env = dict(os.environ)
    env.pop("WIMI_BUILD_RELATIONS", None)
    if relations:
        env["WIMI_BUILD_RELATIONS"] = "1"
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "stage_license_files.py"), str(bundle)],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=600)


def test_a_default_build_stages_no_third_party_folder(tmp_path):
    bundle = tmp_path / "WIMI"
    bundle.mkdir()
    done = _run_stager(bundle, relations=False)
    assert done.returncode == 0, done.stderr
    assert not (bundle / "licenses" / "third-party").exists()
    assert "third-party" not in (bundle / "CORRESPONDING-SOURCE.txt").read_text(encoding="utf-8")


@pytest.mark.skipif(HAS_RUNTIME, reason="this environment has the runtime; see the next section")
def test_a_relations_build_from_an_environment_without_the_runtime_refuses(tmp_path):
    """Never ship a relations build that conveys nothing for its runtime."""
    bundle = tmp_path / "WIMI-relations"
    bundle.mkdir()
    done = _run_stager(bundle, relations=True)
    assert done.returncode != 0
    assert "not installed" in (done.stderr + done.stdout)


def test_both_build_scripts_set_the_variable_the_stager_reads():
    for script in ("build_windows.bat", "build_macos.sh"):
        assert "WIMI_BUILD_RELATIONS" in (REPO_ROOT / script).read_text(encoding="utf-8"), script


def test_the_about_panel_points_at_the_staged_texts():
    """Settings -> About is the notices document; it must say where these are."""
    html = (REPO_ROOT / "src" / "web" / "html" / "settings.html").read_text(encoding="utf-8")
    start = html.index('data-testid="about-notices-relations"')
    section = html[start:html.index("Where the full licence texts are", start)]
    assert "licenses/third-party/" in section and "INDEX.txt" in section
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from app.relation_extraction import model_spec

    assert model_spec.MODEL_REPO in section


# --------------------------------------------------------------------------
# The real runtime (relations venv only)
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def staged(tmp_path_factory):
    if not HAS_RUNTIME:
        pytest.skip("the relations runtime is not installed in this environment")
    bundle = tmp_path_factory.mktemp("bundle") / "WIMI-relations"
    bundle.mkdir()
    done = _run_stager(bundle, relations=True)
    assert done.returncode == 0, done.stdout + done.stderr
    return bundle


def test_every_runtime_component_is_staged_with_at_least_one_text(staged):
    root = staged / rtp.THIRD_PARTY_DIR
    dists = rtp.closure(rtp.runtime_roots())
    for name, dist in dists.items():
        folder = root / f"{rtp._canonical(dist.metadata['Name'])}-{dist.version}"
        texts = [p for p in folder.iterdir() if p.name != rtp.FILES_NAME]
        assert texts, f"{name} {dist.version} has no licence text in the bundle"
    for root_pkg in rtp.runtime_roots():
        assert root_pkg in dists


def test_torch_conveys_the_licences_of_the_code_it_includes(staged):
    torch_dirs = list((staged / rtp.THIRD_PARTY_DIR).glob("torch-*"))
    assert len(torch_dirs) == 1
    assert len(list(torch_dirs[0].iterdir())) > 50
    assert (torch_dirs[0] / "LICENSE").is_file()


def test_tokenizers_gets_the_standard_text_and_says_why(staged):
    folder = next((staged / rtp.THIRD_PARTY_DIR).glob("tokenizers-*"))
    text = folder / "LICENSE-Apache-2.0.txt"
    assert hashlib.sha256(text.read_bytes()).hexdigest() == rtp.APACHE_SHA256
    assert "ships no licence file" in (folder / rtp.FILES_NAME).read_text(encoding="utf-8")


def test_the_index_names_every_component_and_the_model(staged):
    index = (staged / rtp.THIRD_PARTY_DIR / rtp.INDEX_NAME).read_text(encoding="utf-8")
    for dist in rtp.closure(rtp.runtime_roots()).values():
        assert f"{dist.metadata['Name']} {dist.version}" in index
    assert "gliner2-base-v1" in index and "not part of this download" in index


def test_every_staged_path_is_short_enough_to_unzip_on_windows(staged):
    """LongPathsEnabled is 0 by default; 260 characters includes the unzip location."""
    longest = max(len(str(p.relative_to(staged.parent))) for p in staged.rglob("*"))
    assert longest <= 120, longest


def test_the_source_notice_names_the_third_party_folder(staged):
    notice = (staged / "CORRESPONDING-SOURCE.txt").read_text(encoding="utf-8")
    assert "licenses/third-party/" in notice
