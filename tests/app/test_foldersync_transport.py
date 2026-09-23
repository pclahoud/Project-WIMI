"""
Tests for src/app/foldersync/ — the provider-agnostic folder transport (SPIKE, #123).

Everything here runs against a **plain local directory**. That is the point: the
transport must not care which cloud client is watching the folder, and it must
be provable without a Box account. No Qt, no database, no network.

The Box-specific expectations below are pinned to Box's own documentation, as
gathered in #123 comment #1503. Where a quote is load-bearing it is in the
docstring, so a future reader can tell a researched constant from a guess.
"""
import json
from pathlib import Path

import pytest

from app.foldersync import naming, providers
from app.foldersync.hydration import residency, sha256_of_bytes
from app.foldersync.manifest import (
    MANIFEST_FORMAT,
    MANIFEST_FORMAT_VERSION,
    ManifestError,
    build_manifest,
    parse_manifest,
)
from app.foldersync.providers import BOX, GENERIC, get_provider
from app.foldersync.state import SyncState
from app.foldersync.transport import FolderTransport, TransportError

SYNC_ID = "11111111-2222-3333-4444-555555555555"


# ==================== helpers ====================

def _transport(tmp_path, provider="generic") -> FolderTransport:
    folder = tmp_path / "cloud"
    folder.mkdir(exist_ok=True)
    return FolderTransport(folder, SYNC_ID, provider, timeout_s=5.0)


def _blob(tmp_path, payload: bytes = b"PK-not-really-a-zip") -> Path:
    src = tmp_path / "staged.wimi"
    src.write_bytes(payload)
    return src


def _push(transport, tmp_path, device="laptop", payload=b"gen-payload", **kw):
    return transport.push(
        blob_source=_blob(tmp_path, payload),
        device_id=f"id-{device}",
        device_name=device,
        schema_version=19,
        row_counts={"entries": 3},
        app_version="test",
        **kw,
    )


# ==================== naming ====================

class TestDeviceNameSanitisation:
    """
    Box silently ignores "file names containing special characters" and never
    says which, so the device segment is ALLOWLISTED, not denylisted.
    """

    @pytest.mark.parametrize("raw,expected", [
        ("laptop", "laptop"),
        ("My Laptop", "My-Laptop"),
        ("emma's mbp", "emma-s-mbp"),
        ("  padded  ", "padded"),
        ("a/b\\c", "a-b-c"),
        ("ünïcødé", "n-c-d"),
        ("", "device"),
        (None, "device"),
        ("!!!", "device"),
        ("...", "device"),
    ])
    def test_allowlist(self, raw, expected):
        assert naming.sanitize_device_name(raw) == expected

    def test_leading_dot_and_tilde_cannot_survive(self):
        """Box treats both as 'do not sync', silently. They must not reach a name."""
        for raw in (".hidden", "~temp", ".~weird"):
            out = naming.sanitize_device_name(raw)
            assert not out.startswith(".")
            assert not out.startswith("~")

    def test_length_is_capped(self):
        out = naming.sanitize_device_name("x" * 500)
        assert len(out) <= naming.DEVICE_MAX_CHARS

    def test_sanitisation_is_idempotent(self):
        once = naming.sanitize_device_name("My Laptop!! ")
        assert naming.sanitize_device_name(once) == once


class TestNameRoundTrip:
    def test_blob_and_manifest_round_trip(self):
        # The device TAG is in the name as well as the readable device
        # label: hostnames are not unique, and two machines sharing one
        # would otherwise write the same path and silently overwrite each
        # other's generation.
        blob = naming.blob_name("laptop", 42, "d1a6be98-1748-40a4-85a0-6c91a88b539d")
        assert blob == "profile-laptop-d1a6be98-gen-0042.wimi"
        parsed = naming.parse_blob_name(blob)
        assert parsed.device == "laptop" and parsed.generation == 42
        assert parsed.device_tag == "d1a6be98"

        man = naming.manifest_name("laptop", 42, "d1a6be98-1748-40a4-85a0-6c91a88b539d")
        assert man == "manifest-laptop-d1a6be98-gen-0042.json"
        assert naming.parse_manifest_name(man).generation == 42

    def test_device_containing_gen_still_parses(self):
        """The split is on the LAST '-gen-', so 'my-gen-box' survives."""
        name = naming.blob_name("my-gen-box", 7)
        assert naming.parse_blob_name(name).device == "my-gen-box"

    def test_generation_beyond_four_digits(self):
        name = naming.blob_name("laptop", 123456)
        assert naming.parse_blob_name(name).generation == 123456

    def test_cross_kind_parsers_do_not_confuse(self):
        assert naming.parse_manifest_name(naming.blob_name("a", 1)) is None
        assert naming.parse_blob_name(naming.manifest_name("a", 1)) is None

    @pytest.mark.parametrize("junk", [
        "profile.wimi", "readme.txt", "profile-laptop-gen-42.wimi",  # too few digits
        "profile-laptop-gen-0042.zip", "manifest-laptop-gen-0042.txt",
    ])
    def test_foreign_names_are_not_ours(self, junk):
        assert naming.parse_blob_name(junk) is None
        assert naming.parse_manifest_name(junk) is None


class TestProviderNameRules:
    """
    Box's ignored/blocked lists, verbatim from support.box.com article 360044195433.
    The blocked list is a CLOSED set of ten (Outlook PST + QuickBooks) -- `.wimi`
    and `.json` are not in it, and neither is `.zip`.
    """

    def test_our_own_names_are_safe_on_box(self):
        assert naming.ignored_reason(naming.blob_name("laptop", 1), BOX) is None
        assert naming.ignored_reason(naming.manifest_name("laptop", 1), BOX) is None

    @pytest.mark.parametrize("name", [
        ".hidden.wimi", "~temp.wimi", "scratch.tmp", "old.bak", "trailing.",
    ])
    def test_silently_ignored_shapes_are_caught(self, name):
        assert naming.ignored_reason(name, BOX) is not None

    @pytest.mark.parametrize("ext", [".pst", ".qbw", ".nd", ".des", ".qba", ".qbr", ".qby", ".qdt"])
    def test_box_blocked_extensions(self, ext):
        assert naming.ignored_reason(f"archive{ext}", BOX) is not None

    def test_wimi_and_json_are_not_blocked(self):
        assert ".wimi" not in BOX.blocked_extensions
        assert ".json" not in BOX.blocked_extensions
        assert ".zip" not in BOX.blocked_extensions

    def test_eight_uppercase_hex_with_no_extension_is_ignored(self):
        """A landmine we cannot hit, asserted so a future naming change cannot."""
        assert naming.ignored_reason("1234AD38", BOX) is not None
        assert naming.ignored_reason("ABE32BD0", BOX) is not None
        assert naming.ignored_reason("1234ad38", BOX) is None       # lowercase is fine
        assert naming.ignored_reason("1234AD38.wimi", BOX) is None  # has an extension

    def test_generic_folder_blocks_nothing_by_extension(self):
        assert naming.ignored_reason("archive.pst", GENERIC) is None


class TestPathBudget:
    """Box: 'Folder paths have a limit of 255 characters'. On the PATH, not the name."""

    def test_box_rejects_an_over_long_path(self):
        assert naming.path_budget_error("C:\\" + "x" * 300, BOX) is not None

    def test_box_accepts_a_reasonable_path(self):
        assert naming.path_budget_error("C:\\Users\\sam\\Box\\WIMI\\x\\profile-a-gen-0001.wimi", BOX) is None

    def test_generic_has_no_ceiling(self):
        assert naming.path_budget_error("/" + "x" * 5000, GENERIC) is None


class TestConflictCopyRecognition:
    """
    Box: "Documents with conflicts will either be appended with a number or
    email address in parentheses." -- stated verbatim and IDENTICALLY in both the
    "on PCs" and "on Mac" sections of article 360044193873, so there is no
    platform difference to test for.

    Box does not document whether the parenthetical lands before or after the
    extension, so both are matched rather than betting on one.
    """

    @pytest.mark.parametrize("name,marker", [
        ("profile-laptop-gen-0042 (1).wimi", "1"),
        ("profile-laptop-gen-0042 (2).wimi", "2"),
        ("profile-laptop-gen-0042 (sam@example.com).wimi", "sam@example.com"),
        ("profile-laptop-gen-0042(1).wimi", "1"),
        ("manifest-laptop-gen-0042 (1).json", "1"),
        ("profile-laptop-gen-0042.wimi (1)", "1"),
    ])
    def test_recognises_box_conflict_copies(self, name, marker):
        found = naming.recover_conflict_copy(name, BOX)
        assert found is not None, name
        assert found.marker == marker
        assert found.parsed.generation == 42
        assert found.parsed.device == "laptop"

    def test_recovers_the_name_it_was_a_copy_of(self):
        found = naming.recover_conflict_copy("profile-laptop-gen-0042 (1).wimi", BOX)
        assert found.original_name == "profile-laptop-gen-0042.wimi"

    @pytest.mark.parametrize("name", [
        "Budget (1).xlsx",          # somebody else's conflict copy
        "notes (draft).txt",
        "profile-laptop-gen-0042.wimi",  # the real thing, not a copy
        "random.bin",
    ])
    def test_leaves_unrelated_files_alone(self, name):
        assert naming.recover_conflict_copy(name, BOX) is None

    def test_a_pristine_name_is_never_read_as_a_conflict_copy(self):
        """Guards against an over-greedy pattern from another provider's row."""
        for gen in (1, 42, 9999):
            for device in ("laptop", "my-gen-box", "desktop-2"):
                assert naming.recover_conflict_copy(naming.blob_name(device, gen)) is None
                assert naming.recover_conflict_copy(naming.manifest_name(device, gen)) is None

    def test_find_conflict_copies_sorts_newest_first(self):
        names = [
            "profile-a-gen-0001 (1).wimi",
            "profile-a-gen-0009 (1).wimi",
            "profile-a-gen-0005 (1).wimi",
            "unrelated.txt",
        ]
        found = naming.find_conflict_copies(names, BOX)
        assert [c.parsed.generation for c in found] == [9, 5, 1]


class TestProviderTable:
    """The Box row is data, not code. These pin the researched figures."""

    def test_box_free_tier_figures(self):
        assert BOX.free_total_bytes == 10 * 1024 ** 3      # 10 GB
        assert BOX.free_max_file_bytes == 250 * 1024 ** 2  # 250 MB
        assert BOX.free_versions_kept == 1

    def test_box_is_streaming_with_scheduled_eviction(self):
        """The combination that makes hydration the NORMAL path on Box."""
        assert BOX.streaming_by_default is True
        assert BOX.scheduled_eviction is True

    def test_box_macos_folder_is_the_file_provider_path(self):
        """Not '~/Box' -- the real mount is the reserved File Provider directory."""
        assert "~/Library/CloudStorage/Box-Box" in BOX.default_folders["darwin"]

    def test_box_pin_label_is_the_current_menu_wording(self):
        assert BOX.pin_setting_label == "Always keep on this device"

    def test_unknown_provider_degrades_to_generic(self):
        assert get_provider("nextcloud") is GENERIC
        assert get_provider(None) is GENERIC
        assert get_provider("BOX") is BOX  # case-insensitive


# ==================== manifest ====================

class TestManifest:
    def _valid(self, **kw):
        base = dict(
            sync_id=SYNC_ID, generation=42, parent_generation=41,
            device_id="dev-1", device_name="laptop",
            blob_name="profile-laptop-gen-0042.wimi",
            sha256="a" * 64, size_bytes=1234, schema_version=19,
            row_counts={"entries": 7}, app_version="test",
        )
        base.update(kw)
        return build_manifest(**base)

    def test_round_trip(self):
        original = self._valid()
        again = parse_manifest(original.to_json())
        assert again == original

    def test_format_is_stamped(self):
        m = self._valid()
        assert m.format == MANIFEST_FORMAT
        assert m.format_version == MANIFEST_FORMAT_VERSION

    def test_root_generation_has_no_parent(self):
        assert self._valid(parent_generation=0).is_root is True
        assert self._valid(parent_generation=41).is_root is False

    @pytest.mark.parametrize("mutation,fragment", [
        ({"format": "something-else"}, "unrecognised manifest format"),
        ({"format_version": 99}, "newer version of WIMI"),
        ({"sha256": "nope"}, "64-character hex"),
        ({"generation": 0}, "must be positive"),
        ({"generation": 5, "parent_generation": 5}, "not an ancestor"),
        ({"generation": 5, "parent_generation": 9}, "not an ancestor"),
        ({"parent_generation": -1}, "must not be negative"),
    ])
    def test_rejects_malformed(self, mutation, fragment):
        raw = json.loads(self._valid().to_json())
        raw.update(mutation)
        with pytest.raises(ManifestError) as exc:
            parse_manifest(json.dumps(raw))
        assert fragment in str(exc.value)

    def test_rejects_missing_fields(self):
        raw = json.loads(self._valid().to_json())
        del raw["sha256"]
        with pytest.raises(ManifestError, match="missing required field"):
            parse_manifest(json.dumps(raw))

    def test_rejects_non_json(self):
        with pytest.raises(ManifestError, match="not valid JSON"):
            parse_manifest(b"\x00\x01 not json")


# ==================== transport: push ====================

class TestPush:
    def test_first_push_is_generation_one_with_no_parent(self, tmp_path):
        t = _transport(tmp_path)
        result = _push(t, tmp_path)
        assert result.generation == 1
        assert result.parent_generation == 0
        assert Path(result.blob_path).exists()
        assert Path(result.manifest_path).exists()

    def test_blob_is_written_before_the_manifest(self, tmp_path):
        """
        The ordering that makes a half-finished push detectable rather than
        authoritative. Asserted by mtime, which is the only observable trace.
        """
        t = _transport(tmp_path)
        r = _push(t, tmp_path)
        assert Path(r.blob_path).stat().st_mtime <= Path(r.manifest_path).stat().st_mtime

    def test_manifest_describes_the_blob_exactly(self, tmp_path):
        payload = b"a-specific-payload"
        t = _transport(tmp_path)
        r = _push(t, tmp_path, payload=payload)
        manifest = parse_manifest(Path(r.manifest_path).read_bytes())
        assert manifest.sha256 == sha256_of_bytes(payload)
        assert manifest.bytes == len(payload)
        assert manifest.blob_name == Path(r.blob_path).name

    def test_generations_increment_and_chain(self, tmp_path):
        t = _transport(tmp_path)
        first = _push(t, tmp_path, payload=b"one")
        second = _push(t, tmp_path, payload=b"two")
        assert (second.generation, second.parent_generation) == (2, 1)
        assert first.generation == 1

    def test_refuses_to_overwrite_an_existing_generation(self, tmp_path):
        """Generation files are immutable. This is the invariant, stated as a test."""
        t = _transport(tmp_path)
        _push(t, tmp_path)
        with pytest.raises(TransportError, match="immutable"):
            _push(t, tmp_path, generation=1)

    def test_two_devices_never_collide(self, tmp_path):
        """The property the whole design rests on: disjoint writers, disjoint paths."""
        t = _transport(tmp_path)
        a = _push(t, tmp_path, device="laptop")
        b = _push(t, tmp_path, device="desktop")
        assert a.blob_name != b.blob_name
        assert "laptop" in a.blob_name and "desktop" in b.blob_name

    def test_generation_floor_prevents_reuse_after_folder_is_emptied(self, tmp_path):
        """
        A cloud client that has not yet brought our own earlier files back down
        must not let us mint generation 1 a second time with different content.
        """
        t = _transport(tmp_path)
        _push(t, tmp_path)
        for p in t.sync_dir.iterdir():
            p.unlink()
        again = _push(t, tmp_path, generation_floor=1)
        assert again.generation == 2

    def test_missing_source_is_refused(self, tmp_path):
        t = _transport(tmp_path)
        with pytest.raises(TransportError, match="no archive to push"):
            t.push(
                blob_source=tmp_path / "nope.wimi", device_id="d", device_name="laptop",
                schema_version=19,
            )

    def test_device_name_is_sanitised_into_the_file_name(self, tmp_path):
        t = _transport(tmp_path)
        r = _push(t, tmp_path, device="Emma's MacBook Pro!!")
        # _push passes device_id="id-<device>", so the tag is its first 8
        # alphanumerics: "id-Emma's MacBook Pro!!" -> "idemmasm".
        assert r.blob_name == "profile-Emma-s-MacBook-Pro-idemmasm-gen-0001.wimi"
        assert naming.parse_blob_name(r.blob_name) is not None


# ==================== transport: scan + resolve ====================

class TestScanAndResolve:
    def test_empty_folder_resolves_to_nothing(self, tmp_path):
        t = _transport(tmp_path)
        head, failures = t.resolve_head()
        assert head is None and failures == []

    def test_highest_valid_generation_wins(self, tmp_path):
        t = _transport(tmp_path)
        _push(t, tmp_path, payload=b"one")
        _push(t, tmp_path, payload=b"two")
        third = _push(t, tmp_path, payload=b"three")
        head, failures = t.resolve_head()
        assert head.manifest.generation == third.generation == 3
        assert failures == []

    def test_orphan_blob_is_ignored_and_previous_generation_stays_authoritative(self, tmp_path):
        """
        A push interrupted between blob and manifest. The acceptance criterion
        from #123, stated directly.
        """
        t = _transport(tmp_path)
        good = _push(t, tmp_path, payload=b"committed")
        (t.sync_dir / naming.blob_name("laptop", 2)).write_bytes(b"half-written, no manifest")

        head, failures = t.resolve_head()
        assert head.manifest.generation == good.generation == 1
        assert failures == []  # an orphan blob is not a failed generation, it is nothing

    def test_manifest_whose_blob_fails_checksum_is_skipped(self, tmp_path):
        """
        'Never trust a manifest whose blob does not verify.'

        The corruption is SAME-LENGTH on purpose, so the cheap size check cannot
        catch it and the checksum is genuinely what rejects the generation.
        """
        t = _transport(tmp_path)
        _push(t, tmp_path, payload=b"generation one")
        bad = _push(t, tmp_path, payload=b"generation two")
        assert Path(bad.blob_path).read_bytes() == b"generation two"
        Path(bad.blob_path).write_bytes(b"generation TWO")  # same length, different bytes

        head, failures = t.resolve_head()
        assert head.manifest.generation == 1
        assert [f.generation for f in failures] == [2]
        assert "checksum" in failures[0].reason

    def test_manifest_whose_blob_is_missing_is_skipped(self, tmp_path):
        t = _transport(tmp_path)
        _push(t, tmp_path, payload=b"one")
        bad = _push(t, tmp_path, payload=b"two")
        Path(bad.blob_path).unlink()

        head, failures = t.resolve_head()
        assert head.manifest.generation == 1
        assert "missing" in failures[0].reason

    def test_size_mismatch_is_caught_before_the_hash(self, tmp_path):
        t = _transport(tmp_path)
        _push(t, tmp_path, payload=b"one")
        bad = _push(t, tmp_path, payload=b"two")
        Path(bad.blob_path).write_bytes(b"much longer than the manifest claims")

        _head, failures = t.resolve_head()
        assert "bytes" in failures[0].reason

    def test_corrupt_manifest_does_not_poison_the_folder(self, tmp_path):
        t = _transport(tmp_path)
        _push(t, tmp_path, payload=b"one")
        bad = _push(t, tmp_path, payload=b"two")
        Path(bad.manifest_path).write_text("{ not json", encoding="utf-8")

        head, failures = t.resolve_head()
        assert head.manifest.generation == 1
        assert failures and failures[0].generation == 2

    def test_manifest_from_a_different_profile_is_rejected(self, tmp_path):
        """Two profiles' folders must never be readable as one another's."""
        t = _transport(tmp_path)
        r = _push(t, tmp_path)
        raw = json.loads(Path(r.manifest_path).read_text())
        raw["sync_id"] = "99999999-9999-9999-9999-999999999999"
        Path(r.manifest_path).write_text(json.dumps(raw), encoding="utf-8")

        head, failures = t.resolve_head()
        assert head is None
        assert "different profile" in failures[0].reason

    def test_manifest_naming_a_blob_outside_the_folder_is_refused(self, tmp_path):
        """A manifest is untrusted input from another machine."""
        t = _transport(tmp_path)
        r = _push(t, tmp_path)
        raw = json.loads(Path(r.manifest_path).read_text())
        raw["blob_name"] = "../../../etc/passwd"
        Path(r.manifest_path).write_text(json.dumps(raw), encoding="utf-8")

        head, failures = t.resolve_head()
        assert head is None
        assert "unsafe blob path" in failures[0].reason

    def test_scan_reports_unknown_files_without_touching_them(self, tmp_path):
        t = _transport(tmp_path)
        _push(t, tmp_path)
        (t.sync_dir / "students-notes.txt").write_text("mine", encoding="utf-8")
        scan = t.scan()
        assert "students-notes.txt" in scan.unknown
        assert (t.sync_dir / "students-notes.txt").read_text() == "mine"

    def test_highest_generation_counts_orphans_and_conflict_copies(self, tmp_path):
        t = _transport(tmp_path)
        _push(t, tmp_path)
        (t.sync_dir / naming.blob_name("laptop", 8)).write_bytes(b"orphan")
        (t.sync_dir / "profile-laptop-gen-0015 (1).wimi").write_bytes(b"conflict")
        assert t.scan().highest_generation == 15
        assert t.next_generation() == 16


# ==================== transport: pull ====================

class TestPull:
    def test_pull_returns_the_bytes_that_were_pushed(self, tmp_path):
        t = _transport(tmp_path)
        _push(t, tmp_path, payload=b"the payload")
        out = tmp_path / "out" / "fetched.wimi"
        result = t.pull(out)
        assert out.read_bytes() == b"the payload"
        assert result.generation == 1

    def test_pull_reports_what_it_skipped(self, tmp_path):
        t = _transport(tmp_path)
        _push(t, tmp_path, payload=b"one")
        bad = _push(t, tmp_path, payload=b"two")
        Path(bad.blob_path).write_bytes(b"corrupted!!!!!!!!!!!!")

        result = t.pull(tmp_path / "fetched.wimi")
        assert result.generation == 1
        assert [f.generation for f in result.skipped] == [2]

    def test_pull_from_an_empty_folder_is_an_error(self, tmp_path):
        t = _transport(tmp_path)
        with pytest.raises(TransportError, match="no usable generation"):
            t.pull(tmp_path / "fetched.wimi")


# ==================== forks ====================

class TestForkDetection:
    """Detecting a fork is #123. The three-way choice dialog is #124."""

    def test_a_linear_chain_is_not_a_fork(self, tmp_path):
        t = _transport(tmp_path)
        _push(t, tmp_path, device="laptop", payload=b"one")
        _push(t, tmp_path, device="desktop", payload=b"two")
        assert t.detect_forks() == []

    def test_two_devices_on_the_same_parent_is_a_fork(self, tmp_path):
        t = _transport(tmp_path)
        _push(t, tmp_path, device="laptop", payload=b"base")
        _push(t, tmp_path, device="laptop", payload=b"laptop-work",
              generation=2, parent_generation=1)
        _push(t, tmp_path, device="desktop", payload=b"desktop-work",
              generation=3, parent_generation=1)

        forks = t.detect_forks()
        assert len(forks) == 1
        assert forks[0].parent_generation == 1
        assert sorted(forks[0].device_names) == ["desktop", "laptop"]

    def test_one_device_pushing_twice_from_one_parent_is_not_a_fork(self, tmp_path):
        """Same device, same parent — a retry, not two students' work."""
        t = _transport(tmp_path)
        _push(t, tmp_path, device="laptop", payload=b"base")
        _push(t, tmp_path, device="laptop", payload=b"a", generation=2, parent_generation=1)
        _push(t, tmp_path, device="laptop", payload=b"b", generation=3, parent_generation=1)
        assert t.detect_forks() == []

    def test_two_roots_from_two_devices_are_reported_as_first_connect(self, tmp_path):
        """Changed deliberately with #148's heads model.

        This used to assert two roots were NOT a fork, on the grounds that
        first connect with two populated devices was a separate question
        (#22 comment #1454). #124 then settled that it is the same three-way
        choice at a different moment -- "same dialog, different trigger" --
        and under the heads model two copies with no shared history are
        simply two heads. Leaving them unreported would let a second
        computer set up from a manual export publish over the first with
        nothing said, which is #149 by another route.

        So they are reported, flagged ``first_connect`` for the framing.
        """
        t = _transport(tmp_path)
        _push(t, tmp_path, device="laptop", payload=b"a", generation=1, parent_generation=0)
        _push(t, tmp_path, device="desktop", payload=b"b", generation=2, parent_generation=0)
        forks = t.detect_forks()
        assert len(forks) == 1
        assert forks[0].first_connect is True
        assert forks[0].parent_generation == 0


# ==================== conflict copies in a real folder ====================

class TestConflictCopyRecovery:
    def test_an_identical_conflict_copy_is_reported_as_safe_to_delete(self, tmp_path):
        t = _transport(tmp_path, provider="box")
        pushed = _push(t, tmp_path, payload=b"real content")
        # Derived from what was actually written rather than hardcoded, so a
        # naming change shows up as a real failure and not a stale literal.
        stem = Path(pushed.blob_name).stem
        (t.sync_dir / f"{stem} (1).wimi").write_bytes(b"real content")

        found = t.recoverable_conflict_copies()
        assert len(found) == 1
        assert found[0]["verifies_against_manifest"] is True
        assert "safe to delete" in found[0]["note"]
        assert found[0]["marker"] == "1"
        assert found[0]["copy_of"] == pushed.blob_name

    def test_a_differing_conflict_copy_is_reported_as_possibly_holding_work(self, tmp_path):
        t = _transport(tmp_path, provider="box")
        pushed = _push(t, tmp_path, payload=b"real content")
        stem = Path(pushed.blob_name).stem
        (t.sync_dir / f"{stem} (sam@example.com).wimi").write_bytes(b"DIFFERENT")

        found = t.recoverable_conflict_copies()
        assert found[0]["verifies_against_manifest"] is False
        assert "may hold work" in found[0]["note"]
        assert found[0]["marker"] == "sam@example.com"

    def test_a_conflict_copy_of_an_unmanifested_generation_is_flagged(self, tmp_path):
        t = _transport(tmp_path, provider="box")
        _push(t, tmp_path, payload=b"gen one")
        (t.sync_dir / "profile-laptop-gen-0009 (1).wimi").write_bytes(b"orphaned work")

        found = t.recoverable_conflict_copies()
        assert found[0]["generation"] == 9
        assert "only copy" in found[0]["note"]

    def test_conflict_copies_never_disturb_head_resolution(self, tmp_path):
        """A conflict copy is reported, never acted on."""
        t = _transport(tmp_path, provider="box")
        _push(t, tmp_path, payload=b"real")
        (t.sync_dir / "profile-laptop-gen-0099 (1).wimi").write_bytes(b"impostor")
        head, _ = t.resolve_head()
        assert head.manifest.generation == 1


# ==================== preflight ====================

class TestPreflight:
    def test_a_normal_folder_is_clean(self, tmp_path):
        assert _transport(tmp_path).preflight() == []

    def test_a_missing_folder_is_reported(self, tmp_path):
        t = FolderTransport(tmp_path / "nope", SYNC_ID, "generic")
        assert any("does not exist" in p for p in t.preflight())

    def test_a_file_where_a_folder_should_be(self, tmp_path):
        target = tmp_path / "afile"
        target.write_text("x", encoding="utf-8")
        t = FolderTransport(target, SYNC_ID, "generic")
        assert any("not a folder" in p for p in t.preflight())

    def test_box_path_budget_is_checked_when_the_folder_is_picked(self, tmp_path):
        """
        Checked at pick time, not at write time -- telling a student a month
        later that their folder was always too deep is useless.
        """
        deep = tmp_path / ("d" * 90) / ("e" * 90) / ("f" * 90)
        deep.mkdir(parents=True)
        problems = FolderTransport(deep, SYNC_ID, "box").preflight()
        assert any("255-character limit" in p for p in problems)

    def test_the_same_deep_folder_is_fine_on_a_plain_disk(self, tmp_path):
        deep = tmp_path / ("d" * 90) / ("e" * 90) / ("f" * 90)
        deep.mkdir(parents=True)
        assert FolderTransport(deep, SYNC_ID, "generic").preflight() == []


# ==================== residency ====================

class TestResidency:
    """
    On Linux there is no placeholder concept to read, so residency reports
    'determinate=False'. That must mean 'we cannot tell', never 'it is local'.
    """

    def test_a_real_file_is_present(self, tmp_path):
        f = tmp_path / "x.bin"
        f.write_bytes(b"1234")
        res = residency(f)
        assert res.exists and res.size_bytes == 4
        assert res.needs_hydration is False

    def test_a_missing_file_is_determinate(self, tmp_path):
        res = residency(tmp_path / "nope")
        assert res.exists is False and res.determinate is True


# ==================== device-local state ====================

class TestSyncState:
    """
    Device-local state only.

    This module deliberately holds **no identity of its own** any more. The
    spike minted a device id here and a per-profile sync id here, because
    neither existed in the schema when it was written; both landed in
    m021/m002 (#126, #129). Two device ids on one machine is the failure
    ``device_local.py`` is a single definition to prevent, so the assertions
    below are mostly about what this class refuses to do.
    """

    def test_device_identity_is_not_minted_here(self):
        """``MasterDatabase.get_device_id()`` is the only minting site."""
        assert not hasattr(SyncState, "device_identity")
        assert not hasattr(SyncState, "rename_device")

    def test_the_state_file_holds_no_device_block(self, tmp_path):
        """A device id written here would be a second answer to one question."""
        state = SyncState(tmp_path)
        state.link_or_create(3, SYNC_ID, "/some/folder", "box")
        raw = json.loads(state.state_path.read_text(encoding="utf-8"))
        assert "device" not in raw

    def test_a_link_requires_a_profile_uuid(self, tmp_path):
        """
        Minting one would give the same profile two identities across two
        machines and silently split it in two -- #129's failure exactly.
        """
        state = SyncState(tmp_path)
        with pytest.raises(ValueError):
            state.link_or_create(3, "", "/some/folder", "box")

    def test_links_survive_a_reload(self, tmp_path):
        state = SyncState(tmp_path)
        state.link_or_create(3, SYNC_ID, "/some/folder", "box")
        reloaded = SyncState(tmp_path).get_link(3)
        assert reloaded.sync_id == SYNC_ID
        assert reloaded.provider_id == "box"

    def test_a_corrupt_state_file_does_not_crash_startup(self, tmp_path):
        state = SyncState(tmp_path)
        state.link_or_create(3, SYNC_ID, "/f", "box")
        state.state_path.write_text("{{{ not json", encoding="utf-8")
        assert SyncState(tmp_path).get_link(3) is None  # forgotten, not fatal

    def test_record_push_also_counts_as_seen(self, tmp_path):
        state = SyncState(tmp_path)
        state.link_or_create(3, SYNC_ID, "/f")
        state.record_push(3, 7)
        link = state.get_link(3)
        assert link.last_pushed_generation == 7
        assert link.last_seen_generation == 7
        assert link.last_seen_at is not None
