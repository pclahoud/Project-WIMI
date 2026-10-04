"""A thumbnail that cannot be generated must say so (#139).

`MediaManager._generate_thumbnail` ended in:

    except Exception as e:
        # Log error but don't raise - thumbnail is optional
        return False

`e` was bound and never used, and there was no logging call anywhere in the
function. The comment described behaviour the code did not have, so a Pillow
API change, a corrupt upload, an unwritable thumbnail directory or a full
disk all returned `False` and vanished: no log line, no toast, no counter.
The student got an entry whose image had no thumbnail and no indication that
anything had gone wrong.

Not raising stays
-----------------
The docstring says the thumbnail is optional and that is a sound design, so
the fix is **log and return the failure the caller already handles** -- not
log-and-raise. `save_media_from_base64` is the only caller and already acts
on `False` by storing `thumbnail_path=None`, which `MediaInfo`, the
`entry_media` rows and the bridge's `_get_media_data_url` all tolerate.
Raising would turn "this image has no thumbnail" into "this image failed to
upload", which trades the student's data for a diagnostic. The tests below
therefore assert the upload survives in every failure case -- that is the
half of the contract most at risk from a later tidy-up.

The `except` is narrowed by classification, not by what escapes
---------------------------------------------------------------
#139 asks for a narrower `except`. Narrowing what *escapes* would propagate
a Pillow API change out through `save_media_from_base64` and break every
upload -- exactly the scenario the issue was worried about, made worse. So
the handler names its expected cases and logs them as WARNING, and logs
anything else as ERROR with a stack trace, while both still return `False`.
A broken thumbnailer is now loud without being fatal.

`UnidentifiedImageError` needs no separate entry (it subclasses `OSError`),
but `Image.DecompressionBombError` does -- it derives straight from
`Exception`, so omitting it would class a hostile upload as a programming
error. That asymmetry is the easiest thing to get wrong here and has its own
test.

Assertions are against the log file on disk, per CLAUDE.md, not the
in-memory buffer.
"""
from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest

from PIL import Image

from app_logging import ErrorLogger
from app.media_manager import MediaManager

# The repo's `src/`, resolved from this file rather than from the working
# directory. A relative literal here passes under `pytest` from the repo
# root and fails anywhere else -- the same cwd dependence as #257 item 2.
SRC = Path(__file__).resolve().parents[2] / "src"


# PNG magic bytes followed by nothing Pillow can read: a file that passes
# MIME detection and then fails to open. This is the "not an image after
# all" / truncated-upload case, which is what the original handler existed
# for.
TRUNCATED_PNG = b'\x89PNG\r\n\x1a\n' + b'garbage that is not a PNG body'


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode('ascii')


def _real_png() -> bytes:
    buf = io.BytesIO()
    Image.new('RGB', (40, 30), (10, 120, 200)).save(buf, 'PNG')
    return buf.getvalue()


def _log_text(log_dir: Path) -> str:
    return "\n".join(
        f.read_text(encoding="utf-8") for f in sorted(log_dir.glob("*.log"))
    )


@pytest.fixture
def log_dir(tmp_path):
    return tmp_path / "logs"


@pytest.fixture
def error_logger(log_dir):
    logger = ErrorLogger(
        app_name="ThumbnailTest",
        log_dir=log_dir,
        mode="production",
        flush_interval=0.1,
    )
    yield logger
    logger.cleanup()


@pytest.fixture
def manager(tmp_path, error_logger):
    return MediaManager(
        base_path=tmp_path / "app_data",
        user_id=1,
        username="tester",
        error_logger=error_logger,
    )


class TestAnExpectedFailureIsAWarning:

    def test_an_unreadable_image_is_logged_and_the_upload_survives(
        self, manager, error_logger, log_dir
    ):
        info = manager.save_media_from_base64(
            entry_id=1,
            base64_data=_b64(TRUNCATED_PNG),
            original_filename="broken.png",
            mime_type="image/png",
        )

        # The upload is intact: this is the "optional" in "the thumbnail is
        # optional", and the reason this is log-and-return rather than
        # log-and-raise.
        assert info.thumbnail_path is None
        assert info.file_path.exists()
        assert info.file_path.read_bytes() == TRUNCATED_PNG

        error_logger.flush()
        text = _log_text(log_dir)

        assert "Could not generate a thumbnail" in text
        # The path is in the message because "a thumbnail failed" with no
        # subject is not actionable.
        assert info.file_path.name in text
        assert '"level": "WARNING"' in text
        # A bad upload is not a bug in WIMI, so it must not be an ERROR --
        # otherwise a student with one corrupt file pollutes the signal that
        # the ERROR bucket exists to carry.
        assert '"level": "ERROR"' not in text

    def test_a_decompression_bomb_is_a_warning_not_an_error(
        self, manager, error_logger, log_dir, monkeypatch
    ):
        """`DecompressionBombError` is not an `OSError`.

        It derives directly from `Exception`, so a handler that narrowed to
        `OSError` alone would class Pillow's defence against a hostile image
        as a programming error. Guarding the asymmetry, since the obvious
        reading of "OSError plus UnidentifiedImageError covers the intended
        cases" misses it.
        """
        def boom(*args, **kwargs):
            raise Image.DecompressionBombError("pixel count exceeds limit")

        monkeypatch.setattr(Image, "open", boom)

        info = manager.save_media_from_base64(
            entry_id=1,
            base64_data=_b64(_real_png()),
            original_filename="bomb.png",
            mime_type="image/png",
        )

        assert info.thumbnail_path is None
        assert info.file_path.exists()

        error_logger.flush()
        text = _log_text(log_dir)
        assert "Could not generate a thumbnail" in text
        assert '"level": "WARNING"' in text
        assert '"level": "ERROR"' not in text


class TestAnUnexpectedFailureIsAnError:

    def test_a_pillow_api_change_is_an_error_with_a_stack_trace(
        self, manager, error_logger, log_dir, monkeypatch
    ):
        """The case that made #139 expensive to diagnose.

        Verifying #135's Pillow downgrade was harder than it should have
        been because if the thumbnailer HAD stopped working nothing would
        have said so. An `AttributeError` from a renamed Pillow API is a bug
        in WIMI, so it is an ERROR and it carries a traceback -- which is
        what makes it diagnosable at all, since the message alone cannot say
        which line moved.
        """
        def boom(*args, **kwargs):
            raise AttributeError("module 'PIL.Image' has no attribute 'Resampling'")

        monkeypatch.setattr(Image, "open", boom)

        info = manager.save_media_from_base64(
            entry_id=1,
            base64_data=_b64(_real_png()),
            original_filename="apidrift.png",
            mime_type="image/png",
        )

        # Still not fatal: a thumbnail bug must not cost the upload.
        assert info.thumbnail_path is None
        assert info.file_path.exists()

        error_logger.flush()
        text = _log_text(log_dir)

        assert "Unexpected failure generating a thumbnail" in text
        assert '"level": "ERROR"' in text
        assert '"stack_trace": null' not in text
        assert "AttributeError" in text


class TestTheQuietPaths:

    def test_a_healthy_image_logs_nothing(self, manager, error_logger, log_dir):
        """Negative control.

        Without this, every assertion above would also pass against an
        implementation that logged on success too -- and a warning on every
        upload is its own defect.
        """
        info = manager.save_media_from_base64(
            entry_id=1,
            base64_data=_b64(_real_png()),
            original_filename="fine.png",
            mime_type="image/png",
        )

        assert info.thumbnail_path is not None
        assert info.thumbnail_path.exists()
        with Image.open(info.thumbnail_path) as thumb:
            assert max(thumb.size) <= 120

        error_logger.flush()
        text = _log_text(log_dir)
        assert "thumbnail" not in text.lower()

    def test_an_svg_is_skipped_without_a_warning(
        self, manager, error_logger, log_dir
    ):
        """Skipping an SVG is a documented decision, not a failure.

        It returns `False` down the same path, so it would be easy to log it
        by accident and tell students something is wrong every time they
        attach a diagram.
        """
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'
        info = manager.save_media_from_base64(
            entry_id=1,
            base64_data=_b64(svg),
            original_filename="diagram.svg",
            mime_type="image/svg+xml",
        )

        assert info.thumbnail_path is None
        error_logger.flush()
        assert "thumbnail" not in _log_text(log_dir).lower()

    def test_a_missing_pillow_says_so_once_and_names_no_file(
        self, manager, error_logger, log_dir, monkeypatch
    ):
        """The other branch whose comment promised a warning and had none.

        Pillow's absence is a condition of the whole process rather than a
        fact about one upload -- nothing gets a thumbnail -- so the message
        names no file. That also keeps it constant, which lets the logger's
        300 s WARNING dedup collapse it to a single record however many
        images are attached; interpolating a filename would defeat that and
        give a student one warning per image for a condition they cannot
        act on per image.
        """
        import app.media_manager as mm

        monkeypatch.setattr(mm, "PILLOW_AVAILABLE", False)

        for name in ("one.png", "two.png", "three.png"):
            info = manager.save_media_from_base64(
                entry_id=1,
                base64_data=_b64(_real_png()),
                original_filename=name,
                mime_type="image/png",
            )
            assert info.thumbnail_path is None
            assert info.file_path.exists()

        error_logger.flush()
        text = _log_text(log_dir)

        assert "Pillow is not available" in text
        assert text.count("Pillow is not available") == 1, (
            "three uploads should collapse to one record; a per-file message "
            "would defeat the dedup window"
        )
        for name in ("one.png", "two.png", "three.png"):
            assert name not in text

    def test_a_manager_with_no_logger_degrades_to_silence(self, tmp_path):
        """The guard, which is the whole trap #139 is an instance of.

        A `MediaManager` built without a logger must still work -- a test or
        a plugin fixture does exactly that. What must NOT happen is this
        becoming the production shape again: the three `MainWindow`
        construction sites all pass the logger, and
        `test_every_production_media_manager_is_given_the_logger` below is
        what keeps that true.
        """
        manager = MediaManager(
            base_path=tmp_path / "app_data", user_id=1, username="tester"
        )
        assert manager.error_logger is None

        info = manager.save_media_from_base64(
            entry_id=1,
            base64_data=_b64(TRUNCATED_PNG),
            original_filename="broken.png",
            mime_type="image/png",
        )
        assert info.thumbnail_path is None
        assert info.file_path.exists()


def test_every_production_media_manager_is_given_the_logger():
    """Per-call-site invariant, so a grep is the right shape of check.

    Same reasoning as `tests/database/test_logger_category_types.py`: the
    failure is per construction site, and exercising one proves nothing
    about the others. `MainWindow` builds a `MediaManager` three times --
    with a user database, with the placeholder before one is attached, and
    again on every profile switch -- and a thumbnail failure is invisible
    through whichever one was missed.
    """
    source = (SRC / "app" / "main_window.py").read_text(encoding="utf-8")

    # Read each `MediaManager(` call's own argument list, rather than
    # counting `error_logger=` over the whole file -- `main_window.py` passes
    # the same logger to other collaborators, so a file-wide count passes
    # while a MediaManager site is still missing it. (It did: this assertion
    # was written that way first and reported 4 for 3 sites.)
    calls = []
    for start in range(len(source)):
        if not source.startswith("MediaManager(", start):
            continue
        depth, i = 0, start + len("MediaManager(") - 1
        while i < len(source):
            if source[i] == "(":
                depth += 1
            elif source[i] == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        calls.append(source[start:i + 1])

    assert len(calls) == 3, f"expected 3 construction sites, found {len(calls)}"
    missing = [c for c in calls if "error_logger=" not in c]
    assert missing == [], (
        "a MediaManager built without error_logger reports thumbnail "
        "failures nowhere (#139):\n" + "\n---\n".join(missing)
    )
