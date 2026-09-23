"""Unit tests for ``src/console_encoding.py`` — the #137 stdio guard.

The case these tests exist for is the one that **cannot be reproduced on
Linux**: ``wimi_macos.spec`` sets ``console=False`` because a macOS
``.app`` must not be a console app, and a windowed PyInstaller build has
no standard streams at all — ``sys.stdout is None``. An unguarded
``sys.stdout.reconfigure(...)`` raises ``AttributeError`` there and would
crash the build on the very line added to prevent a crash. Windows takes
the opposite route and keeps ``console=True``, hiding only the console
*window* (``hide_console``, #142) so its streams stay real -- so the
``None`` case is macOS's alone, and nothing on Windows will produce it.

So the guard is asserted against fakes and a real ``TextIOWrapper``,
covering the four shapes ``sys.stdout`` can actually take: ``None``, an
object with no ``reconfigure`` (pytest capture, ``StringIO``, an IDE
shim), one whose ``reconfigure`` raises, and a genuine text stream.
"""

from __future__ import annotations

import io
import sys

import pytest

from console_encoding import STDERR_ERRORS, STDOUT_ERRORS, configure_stdio


class _RecordingStream:
    """Captures the kwargs every ``reconfigure`` call was given."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def reconfigure(self, **kwargs) -> None:
        self.calls.append(kwargs)


class _NoReconfigure:
    """A stream-like object with no ``reconfigure`` at all."""


class _HostileStream:
    """A stream whose ``reconfigure`` raises, as a detached buffer does."""

    def reconfigure(self, **kwargs) -> None:
        raise ValueError("underlying buffer has been detached")


@pytest.mark.unit
def test_none_streams_are_skipped_and_do_not_raise(monkeypatch):
    """The macOS ``console=False`` case: no streams, no crash, no work."""
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    assert configure_stdio() == ()


@pytest.mark.unit
def test_stream_without_reconfigure_is_skipped(monkeypatch):
    """pytest capture / StringIO / IDE shims have no ``reconfigure``."""
    monkeypatch.setattr(sys, "stdout", _NoReconfigure())
    monkeypatch.setattr(sys, "stderr", _NoReconfigure())

    assert configure_stdio() == ()


@pytest.mark.unit
def test_a_failing_reconfigure_is_swallowed(monkeypatch):
    """This function exists to stop a crash; it may never cause one."""
    monkeypatch.setattr(sys, "stdout", _HostileStream())
    monkeypatch.setattr(sys, "stderr", _HostileStream())

    assert configure_stdio() == ()


@pytest.mark.unit
def test_one_dead_stream_does_not_stop_the_other(monkeypatch):
    """stderr still gets configured when stdout is missing, and vice versa."""
    err = _RecordingStream()
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", err)

    assert configure_stdio() == ("stderr",)
    assert len(err.calls) == 1


@pytest.mark.unit
def test_stdout_gets_utf8_replace_and_stderr_backslashreplace(monkeypatch):
    """The two handlers differ on purpose — see the module docstring.

    ``stdout`` defaults to ``'strict'``, which is the #137 crash;
    ``'replace'`` degrades a stray character to ``?``. ``stderr`` already
    defaults to ``'backslashreplace'`` and never raises, and a traceback
    that escapes a character is more useful than one that hides it.
    """
    out, err = _RecordingStream(), _RecordingStream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    assert configure_stdio() == ("stdout", "stderr")
    assert out.calls == [{"encoding": "utf-8", "errors": STDOUT_ERRORS}]
    assert err.calls == [{"encoding": "utf-8", "errors": STDERR_ERRORS}]
    assert STDOUT_ERRORS == "replace"
    assert STDERR_ERRORS == "backslashreplace"


@pytest.mark.unit
def test_errors_is_never_passed_without_encoding(monkeypatch):
    """``TextIOWrapper.reconfigure`` resets errors to 'strict' if omitted.

    Passing ``encoding`` alone to ``sys.stderr`` would therefore *remove*
    its ``backslashreplace`` default and make the traceback path able to
    raise. Both kwargs must always travel together.
    """
    out, err = _RecordingStream(), _RecordingStream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    configure_stdio()

    for call in out.calls + err.calls:
        assert set(call) == {"encoding", "errors"}


@pytest.mark.unit
def test_a_real_ascii_text_stream_stops_raising(monkeypatch):
    """End-to-end on a genuine ``TextIOWrapper``: the #137 failure mode.

    An ASCII-encoded text stream is what Windows hands a redirected
    frozen build (cp1252 there, ascii here — both reject U+2014 and
    U+1F4F7). Before the call, writing either raises
    ``UnicodeEncodeError``; after it, they encode as UTF-8.
    """
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="ascii", newline="")
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(sys, "stderr", None)

    with pytest.raises(UnicodeEncodeError):
        # The em dash, one of #137's two non-emoji call sites.
        print("[Test mode active — CDP on port 12055]")
        sys.stdout.flush()

    assert configure_stdio() == ("stdout",)

    # The camera glyph from media_scheme_handler, the original crash site.
    print("\U0001f4f7 Registered wimi-media:// URL scheme")
    sys.stdout.flush()
    assert "\U0001f4f7".encode("utf-8") in raw.getvalue()


@pytest.mark.unit
def test_is_idempotent(monkeypatch):
    """Every entry point may call it; calling twice must be harmless."""
    out = _RecordingStream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", None)

    assert configure_stdio() == ("stdout",)
    assert configure_stdio() == ("stdout",)
    assert len(out.calls) == 2
