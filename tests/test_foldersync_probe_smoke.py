"""Smoke tests for ``scripts/foldersync_probe.py`` (#123).

Why this exists
---------------
The probe is run by hand on two Windows machines against a real Box account,
which is the most expensive place in this project to discover a typo. It
shipped once with a `NameError`: a helper was referenced and never defined,
because an edit matched nothing and failed silently. A syntax check passed --
`NameError` is a runtime failure -- and the manual rehearsal happened to
exercise every subcommand except the broken one.

So these tests **call each subcommand**, rather than checking the parser
knows about them. `test_every_subcommand_name_resolves` is the specific guard
against that failure: it walks the module for global names each command body
references and asserts they exist.

Nothing here touches a real cloud folder; a `tmp_path` directory stands in,
exactly as the unit suite does.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PROJECT_ROOT / "scripts" / "foldersync_probe.py"


@pytest.fixture(scope="module")
def probe():
    spec = importlib.util.spec_from_file_location("foldersync_probe", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["foldersync_probe"] = module
    spec.loader.exec_module(module)
    return module


def _run(*args, cwd=PROJECT_ROOT):
    """Run the probe as a subprocess, the way a person actually runs it."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd), capture_output=True, text=True, timeout=180,
    )


def _result(proc, label):
    assert proc.returncode == 0, (
        f"probe exited {proc.returncode}\nstdout:\n{proc.stdout}\n"
        f"stderr:\n{proc.stderr}")
    marker = f"RESULT {label}"
    assert marker in proc.stdout, f"no {marker!r} in:\n{proc.stdout}"
    return json.loads(proc.stdout.split(marker, 1)[1])


# ==================== the guard against the NameError ====================

@pytest.mark.unit
def test_every_global_a_command_references_actually_exists(probe):
    """The specific bug: a helper called from `cmd_env` and defined nowhere.

    A silently-failed edit leaves a call site with no definition. Syntax is
    valid, imports are valid, and it only breaks when that one command runs --
    on someone else's machine, against someone's real cloud account.
    """
    import types

    missing = []
    for name, obj in vars(probe).items():
        if not (name.startswith("cmd_") and isinstance(obj, types.FunctionType)):
            continue
        # A function-local `from x import y` puts y in BOTH co_names and
        # co_varnames -- IMPORT_FROM reads the name, STORE_FAST binds the
        # local. Without this the guard flags every deferred import as
        # undefined, which is how it first fired on `cmd_resolve`.
        local_names = set(obj.__code__.co_varnames)
        for referenced in obj.__code__.co_names:
            if referenced in local_names:
                continue
            # Attribute names share co_names with globals; only flag a name
            # that looks like a module-level helper and is absent.
            if referenced.startswith(("cmd_", "windows_", "resolve_", "emit",
                                      "_sync", "_open_", "_probe_", "_target")):
                if not hasattr(probe, referenced):
                    missing.append(f"{name} -> {referenced}")
    assert not missing, f"referenced but undefined: {missing}"


@pytest.mark.unit
def test_windows_cloud_facts_is_defined_and_safe_off_windows(probe):
    assert callable(probe.windows_cloud_facts)
    assert probe.windows_cloud_facts(None) == {} or sys.platform == "win32"
    # Must not raise on a path that does not exist -- `env` runs before the
    # sync folder is created.
    probe.windows_cloud_facts("/definitely/not/here/at/all")


# ==================== Box's two modes (#123 comment #1951) ====================

@pytest.mark.unit
@pytest.mark.parametrize("tag, mode", [
    (0x9000701A, "cloud_files"),   # Box's sync root, measured 2026-09-22 morning
    (0x9000401A, "cloud_files"),   # Box's files in that mode
    (0x9000001A, "cloud_files"),   # plain IO_REPARSE_TAG_CLOUD
    (0xA0000003, "streem"),        # the mount point, measured overnight 2026-09-21/22
    (0, "none"),
    (None, "unknown"),
    (0xA000000C, "unknown"),       # a symlink is neither mode
])
def test_the_reparse_tag_decides_the_box_mode(probe, tag, mode):
    assert probe.classify_box_mode(tag, sync_roots=1)[0] == mode


@pytest.mark.unit
def test_a_machine_wide_sync_root_count_never_decides_the_mode(probe):
    """SyncRootManager counts roots machine-wide; it says nothing about THIS folder.

    It may only flag a contradiction. Deciding from it is how a OneDrive root
    on the same machine would have labelled a Streem-mode Box folder
    "cloud_files".
    """
    mode, evidence = probe.classify_box_mode(0xA0000003, sync_roots=3)
    assert mode == "streem" and "SyncRootManager" in evidence
    mode, evidence = probe.classify_box_mode(0x9000701A, sync_roots=0)
    assert mode == "cloud_files" and "contradictory" in evidence


@pytest.mark.unit
def test_cloud_tags_are_named_as_one_family(probe):
    assert probe.reparse_meaning(0x9000701A) == "IO_REPARSE_TAG_CLOUD_7 (Cloud Files)"
    assert probe.reparse_meaning(0x9000001A) == "IO_REPARSE_TAG_CLOUD (Cloud Files)"
    assert probe.reparse_meaning(0xA0000003) == "IO_REPARSE_TAG_MOUNT_POINT"


# What that machine's Windows calls returned on 2026-09-22, on a live Box
# Cloud Files root that fsutil reports as 0x9000701A (and its subfolder as
# 0x9000601A). Every ordinary call is filtered; only the root's listing
# from its parent tells the truth.
_A_BOX_ROOT = {"attributes_raw": 0x30, "find_attributes_raw": 0x430,
               "find_tag": 0x9000701A,
               "fsctl_error": "FSCTL_GET_REPARSE_POINT failed, GetLastError=4390"}
_A_SUBFOLDER = {"attributes_raw": 0x10, "find_attributes_raw": 0x10,
                "fsctl_error": "FSCTL_GET_REPARSE_POINT failed, GetLastError=4390"}
_PLAIN_DIR = {"attributes_raw": 0x10, "find_attributes_raw": 0x10}


@pytest.mark.unit
def test_the_parent_listing_is_believed_when_the_filter_hides_the_bit(probe):
    """The a33ad9d bug: it gated on GetFileAttributesW, which reads 0x30 here."""
    assert probe.reparse_signal(_A_BOX_ROOT) == 0x9000701A
    assert probe.reparse_signal(_A_SUBFOLDER) == 0, "a filtered subfolder reads as plain"
    assert probe.reparse_signal(
        {"attributes_raw": 0x410, "find_attributes_raw": 0x410}) is None, (
        "a reparse bit nobody can name is unknown, not none")


@pytest.mark.unit
def test_the_walk_climbs_past_filtered_folders_to_the_box_root(probe, tmp_path, monkeypatch):
    """Machine A's exact layout, through the real walk.

    a33ad9d reported box_mode "none" here: it saw no bit on the folder or on
    the root and fell off the top.
    """
    box = tmp_path / "Users" / "admin" / "Box"
    folder = box / "WIMI-lineage-test"
    folder.mkdir(parents=True)
    readings = {str(box): _A_BOX_ROOT, str(folder): _A_SUBFOLDER}
    monkeypatch.setattr(probe, "_win_reparse_tag",
                        lambda path: readings.get(path, _PLAIN_DIR))
    monkeypatch.setattr(probe.sys, "platform", "win32")

    facts = probe.windows_cloud_facts(str(folder))

    assert facts["box_mode"] == "cloud_files", facts
    assert facts["reparse_point_at"] == str(box)
    assert facts["reparse_find_tag"] == "0x9000701A"
    assert facts["reparse_hidden_from_attributes"] is True
    assert "4390" in facts["reparse_fsctl_error"]


@pytest.mark.unit
def test_the_walk_still_finds_a_streem_mount_point(probe, tmp_path, monkeypatch):
    box = tmp_path / "Users" / "admin" / "Box"
    folder = box / "WIMI-sync-test"
    folder.mkdir(parents=True)
    junction = {"attributes_raw": 0x410, "find_attributes_raw": 0x410,
                "find_tag": 0xA0000003, "fsctl_tag": 0xA0000003}
    monkeypatch.setattr(probe, "_win_reparse_tag",
                        lambda path: junction if path == str(box) else _PLAIN_DIR)
    monkeypatch.setattr(probe.sys, "platform", "win32")

    facts = probe.windows_cloud_facts(str(folder))
    assert facts["box_mode"] == "streem" and facts["reparse_point_at"] == str(box)
    assert facts["reparse_hidden_from_attributes"] is False


@pytest.mark.unit
def test_env_says_why_there_is_no_mode_without_a_folder(probe):
    if sys.platform != "win32":
        pytest.skip("windows_cloud_facts is empty off Windows by design")
    facts = probe.windows_cloud_facts(None)
    assert facts["box_mode"] == "unknown" and "--folder" in facts["box_mode_evidence"]


# ==================== each subcommand actually runs ====================

@pytest.mark.unit
def test_env_runs(tmp_path):
    data = _result(_run("--app-data", str(tmp_path / "probe"), "env"), "env")
    assert data["executable"], "env must report the interpreter it ran under"
    assert "device_id" in data


@pytest.mark.unit
def test_env_runs_with_a_folder_that_does_not_exist_yet(tmp_path):
    """Stage 2 runs `env --folder ...` before creating the folder."""
    data = _result(
        _run("--app-data", str(tmp_path / "probe"), "env",
             "--folder", str(tmp_path / "nope" / "deeper")), "env")
    assert data["executable"]


@pytest.mark.unit
@pytest.mark.slow
def test_the_whole_two_machine_flow(tmp_path):
    """A and B as two app-data directories against one folder."""
    a, b = tmp_path / "A", tmp_path / "B"
    folder = tmp_path / "cloud"
    folder.mkdir()

    seeded = _result(_run("--app-data", str(a), "seed"), "seed")
    uuid = seeded["profile_uuid"]
    assert uuid

    _result(_run("--app-data", str(a), "link", "--folder", str(folder)), "link")
    pushed = _result(_run("--app-data", str(a), "push"), "push")
    assert pushed["generation"] == 1

    # B has no profile and no link -- the receiving device's real state.
    found = _result(_run("--app-data", str(b), "discover",
                         "--folder", str(folder)), "discover")
    assert [f["sync_id"] for f in found["found"]] == [uuid]

    res = _result(_run("--app-data", str(b), "residency", "--folder", str(folder),
                       "--sync-id", uuid), "residency")
    assert len(res["files"]) == 2

    pulled = _result(_run("--app-data", str(b), "pull", "--folder", str(folder),
                          "--sync-id", uuid), "pull")
    assert pulled["generation"] == 1
    assert pulled["blocked"] is False

    # Installing preserves identity across the two "machines" (#129).
    installed = _result(_run("--app-data", str(b), "pull", "--folder", str(folder),
                             "--sync-id", uuid, "--install"), "pull")
    assert installed["installed"]["profile_uuid"] == uuid


@pytest.mark.unit
def test_names_budgets_the_real_layout(tmp_path):
    """The placeholder id must be the same length as a real one, or the
    budget it reports is a different number from the one that will matter."""
    _result(_run("--app-data", str(tmp_path / "probe"), "seed"), "seed")
    data = _result(_run("--app-data", str(tmp_path / "probe"), "names",
                        "--folder", r"C:\Users\%USERNAME%\Box\WIMI-sync-test"), "names")
    assert data["longest_path_chars"] == len(data["longest_path"])
    # WIMI/<36-char id>/<file> and nothing deeper.
    assert "/WIMI/" in data["longest_path"] or "\\WIMI\\" in data["longest_path"]
    segment = data["longest_path"].replace("\\", "/").split("/WIMI/")[1].split("/")[0]
    assert len(segment) == 36, f"placeholder id is {len(segment)} chars, not 36"


@pytest.mark.unit
def test_it_refuses_the_real_app_data():
    proc = _run("--app-data", str(PROJECT_ROOT / "app_data"), "env")
    assert proc.returncode != 0
    assert "refusing" in (proc.stdout + proc.stderr)
