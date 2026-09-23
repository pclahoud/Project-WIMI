"""Tests for ``scripts/check_ascii_prints.py`` — the #137 recurrence gate.

``src/console_encoding.py`` fixes the crash at runtime; this gate is what
stops the class returning through a path the guard does not cover (a new
entry point that forgets to call it, a tool that imports one of these
modules directly). Three properties have to hold for it to be worth
having: it must be clean on the real tree, it must **notice** a new
offender, and it must not be an emoji check — two of #137's six call
sites were an em dash, which cp1252 cannot encode either.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "check_ascii_prints.py"


def _load_script():
    """Import the gate by path — ``scripts/`` is not a package."""
    spec = importlib.util.spec_from_file_location(
        "check_ascii_prints", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_the_real_tree_is_clean():
    """The standing guard. Runs the script exactly as CI does."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.unit
def test_an_emoji_print_is_caught(tmp_path):
    script = _load_script()
    offender = tmp_path / "offender.py"
    offender.write_text(
        'print("\U0001f4f7 Registered wimi-media:// URL scheme")\n',
        encoding="utf-8",
    )

    offences = script.scan_file(offender)

    assert len(offences) == 1
    assert offences[0].chars == "\U0001f4f7"


@pytest.mark.unit
def test_an_em_dash_print_is_caught(tmp_path):
    """The half an emoji-only grep misses. cp1252 cannot encode U+2014."""
    script = _load_script()
    offender = tmp_path / "offender.py"
    offender.write_text(
        'print("WIMI migration status \u2014 ok")\n', encoding="utf-8"
    )

    offences = script.scan_file(offender)

    assert len(offences) == 1
    assert offences[0].chars == "\u2014"


@pytest.mark.unit
def test_an_fstring_literal_segment_is_caught(tmp_path):
    """#137's main.py:257 was an f-string, not a plain literal."""
    script = _load_script()
    offender = tmp_path / "offender.py"
    offender.write_text(
        'port = 1\nprint(f"   [Test mode active \u2014 CDP on port {port}]")\n',
        encoding="utf-8",
    )

    offences = script.scan_file(offender)

    assert len(offences) == 1
    assert offences[0].line == 2


@pytest.mark.unit
def test_non_ascii_outside_print_is_left_alone(tmp_path):
    """Docstrings, comments, log records and data are not the gate's business."""
    script = _load_script()
    clean = tmp_path / "clean.py"
    clean.write_text(
        '"""A docstring \u2014 with an em dash."""\n'
        "# A comment \u2014 with another\n"
        "import logging\n"
        'logging.getLogger(__name__).info("weights \u2014 rebalanced")\n'
        'MESSAGE = "\U0001f4f7 stored, not printed"\n'
        'print("plain ascii is fine")\n',
        encoding="utf-8",
    )

    assert script.scan_file(clean) == []


@pytest.mark.unit
def test_a_method_named_print_is_not_a_print(tmp_path):
    """``self.print(...)`` is somebody else's encoder, not sys.stdout's."""
    script = _load_script()
    clean = tmp_path / "clean.py"
    clean.write_text(
        'class R:\n'
        '    def print(self, s): ...\n'
        'R().print("\u2014 rich console handles this")\n',
        encoding="utf-8",
    )

    assert script.scan_file(clean) == []
