"""The MSVC runtime preload that lets torch load after Qt on Windows (#367).

Most of these test the decision logic through injected seams, so they run on
every platform. Three need real Windows: reading a real file version, the
Qt-then-torch control in a subprocess, and nothing else -- they skip
elsewhere, and the subprocess pair also skips where torch is not installed.
"""
from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from app import msvc_runtime as mr

REPO = Path(__file__).resolve().parents[2]
WINDOWS = sys.platform == 'win32'


def _dll(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / mr.DLL_NAME
    path.write_bytes(b'MZ')
    return path


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    """preload_newest remembers a success; every test starts from none."""
    monkeypatch.setattr(mr, '_last_result', None)
    monkeypatch.setattr(mr, '_keep_alive', [])


@pytest.fixture
def on_windows(monkeypatch):
    monkeypatch.setattr(mr.sys, 'platform', 'win32')


def _run(dirs, versions, *, loaded=None, load=None, force=True):
    calls = []

    def fake_load(path):
        calls.append(path)
        if load is not None:
            return load(path)
        return object()

    result = mr.preload_newest(
        force=force,
        search_dirs=dirs,
        version_of=lambda p: versions.get(Path(p).parent.name),
        already_loaded=lambda name: loaded if name == mr.DLL_NAME else None,
        load=fake_load,
    )
    return result, calls


# ---------------------------------------------------------------- deciding

def test_off_windows_it_does_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(mr.sys, 'platform', 'linux')
    result, calls = _run([_dll(tmp_path / 'a').parent], {'a': (14, 50, 0, 0)})
    assert result.status == mr.NOT_WINDOWS
    assert calls == []


def test_the_default_artifact_never_loads_anything(on_windows, monkeypatch, tmp_path):
    """Frozen without the relations marker: the runtime is absent by design."""
    monkeypatch.setattr(mr.sys, 'frozen', True, raising=False)
    monkeypatch.delattr(mr.sys, '_wimi_relations_build', raising=False)
    result, calls = _run([_dll(tmp_path / 'a').parent], {'a': (14, 50, 0, 0)},
                         force=False)
    assert result.status == mr.NOT_NEEDED
    assert calls == []


def test_the_relations_artifact_is_preloaded(monkeypatch):
    monkeypatch.setattr(mr.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(mr.sys, '_wimi_relations_build', True, raising=False)
    assert mr.should_preload() is True


def test_a_checkout_without_torch_is_not_preloaded(monkeypatch):
    monkeypatch.delattr(mr.sys, 'frozen', raising=False)
    monkeypatch.setattr(mr.importlib.util, 'find_spec', lambda name: None)
    assert mr.should_preload() is False


# ---------------------------------------------------------------- choosing

def test_the_newest_copy_wins_wherever_it_is(on_windows, tmp_path):
    """By file version, never by directory order -- Qt's old copy first."""
    qt = _dll(tmp_path / 'qt').parent
    sys32 = _dll(tmp_path / 'sys32').parent
    result, calls = _run([qt, sys32], {'qt': (14, 26, 28720, 3),
                                       'sys32': (14, 50, 35719, 0)})
    assert result.status == mr.LOADED
    assert calls == [str(sys32 / mr.DLL_NAME)]
    assert result.version == (14, 50, 35719, 0)
    assert len(result.candidates) == 2


def test_a_tie_goes_to_the_earlier_directory(on_windows, tmp_path):
    a = _dll(tmp_path / 'a').parent
    b = _dll(tmp_path / 'b').parent
    _, calls = _run([a, b], {'a': (14, 50, 0, 0), 'b': (14, 50, 0, 0)})
    assert calls == [str(a / mr.DLL_NAME)]


def test_one_already_loaded_is_reported_not_replaced(on_windows, tmp_path):
    """Too late to choose: say what holds the name rather than load a second."""
    a = _dll(tmp_path / 'a').parent
    held = str(_dll(tmp_path / 'qt'))
    result, calls = _run([a], {'a': (14, 50, 0, 0), 'qt': (14, 26, 0, 0)},
                         loaded=held)
    assert result.status == mr.ALREADY_LOADED
    assert result.path == held
    assert result.version == (14, 26, 0, 0)
    assert calls == []


def test_nothing_found_is_a_result_not_an_error(on_windows, tmp_path):
    result, calls = _run([tmp_path / 'empty'], {})
    assert result.status == mr.NONE_FOUND
    assert calls == []


def test_an_unreadable_version_is_never_chosen(on_windows, tmp_path):
    a = _dll(tmp_path / 'a').parent
    result, calls = _run([a], {})  # version_of returns None
    assert result.status == mr.NONE_FOUND
    assert result.candidates == ((str(a / mr.DLL_NAME), None),)
    assert calls == []


# ----------------------------------------------------- the runtime family

def _family(directory: Path, names=mr.SATELLITES) -> Path:
    _dll(directory)
    for name in names:
        (directory / name).write_bytes(b'MZ')
    return directory


def test_the_family_comes_from_the_chosen_directory_only(on_windows, tmp_path):
    """msvcp140 first (the satellites import it), then its own satellites --
    never Qt's, even though Qt's folder has a full older set."""
    qt = _family(tmp_path / 'qt')
    sys32 = _family(tmp_path / 'sys32')
    result, calls = _run([qt, sys32], {'qt': (14, 26, 0, 0), 'sys32': (14, 50, 0, 0)})
    assert calls == [str(sys32 / mr.DLL_NAME)] + [str(sys32 / n) for n in mr.SATELLITES]
    assert dict(result.satellites) == {n: str(sys32 / n) for n in mr.SATELLITES}
    assert '(+3/3 of its family)' in result.describe()


def test_a_missing_satellite_is_not_borrowed_from_another_directory(on_windows, tmp_path):
    """The frozen bundle's case: its 14.50 copy has no msvcp140_1 beside it.
    Mixing sources is what loading the family avoids, so record 'absent'."""
    qt = _family(tmp_path / 'qt')
    bundle = _dll(tmp_path / 'bundle').parent
    result, calls = _run([qt, bundle], {'qt': (14, 26, 0, 0), 'bundle': (14, 50, 0, 0)})
    assert calls == [str(bundle / mr.DLL_NAME)]
    assert dict(result.satellites) == {n: 'absent' for n in mr.SATELLITES}
    assert result.status == mr.LOADED


def test_a_satellite_already_in_the_process_is_left_alone(on_windows, tmp_path):
    sys32 = _family(tmp_path / 'sys32')
    held = {'msvcp140_1.dll': r'C:\elsewhere\msvcp140_1.dll'}
    calls = []
    result = mr.preload_newest(
        force=True, search_dirs=[sys32], version_of=lambda p: (14, 50, 0, 0),
        already_loaded=lambda name: held.get(name),
        load=lambda p: calls.append(p))
    assert str(sys32 / 'msvcp140_1.dll') not in calls
    assert dict(result.satellites)['msvcp140_1.dll'].startswith('already loaded')


def test_a_failing_satellite_does_not_undo_the_main_load(on_windows, tmp_path):
    sys32 = _family(tmp_path / 'sys32')

    def load(path):
        if path.endswith('concrt140.dll'):
            raise OSError('refused')
        return object()

    result, _ = _run([sys32], {'sys32': (14, 50, 0, 0)}, load=load)
    assert result.status == mr.LOADED
    assert dict(result.satellites)['concrt140.dll'].startswith('failed')


def test_a_second_call_keeps_the_first_success(on_windows, tmp_path):
    """The bundle calls this twice: the runtime hook, then main().

    By main() Qt has loaded and the name is taken -- by OUR copy. Reporting
    ALREADY_LOADED then would overwrite the one result that says what worked.
    """
    a = _dll(tmp_path / 'a').parent
    first, calls = _run([a], {'a': (14, 50, 0, 0)})
    assert first.status == mr.LOADED
    second, more = _run([a], {'a': (14, 50, 0, 0)}, loaded=str(a / mr.DLL_NAME))
    assert second is first
    assert calls == [str(a / mr.DLL_NAME)] and more == []


def test_a_failure_is_retried_rather_than_remembered(on_windows, tmp_path):
    a = _dll(tmp_path / 'a').parent
    first, _ = _run([a], {})
    assert first.status == mr.NONE_FOUND
    second, calls = _run([a], {'a': (14, 50, 0, 0)})
    assert second.status == mr.LOADED and calls


# ------------------------------------------------- never stopping startup

def test_a_failed_load_is_recorded_not_raised(on_windows, tmp_path):
    a = _dll(tmp_path / 'a').parent

    def refuse(path):
        raise OSError(1114, 'DLL initialization routine failed')

    result, _ = _run([a], {'a': (14, 50, 0, 0)}, load=refuse)
    assert result.status == mr.FAILED
    assert 'OSError' in result.detail
    assert mr.last_result() is result


def test_anything_else_going_wrong_is_recorded_not_raised(on_windows, tmp_path):
    a = _dll(tmp_path / 'a').parent
    result = mr.preload_newest(
        force=True, search_dirs=[a],
        version_of=lambda p: 1 / 0,
        already_loaded=lambda name: None, load=lambda p: None)
    assert result.status == mr.FAILED
    assert 'ZeroDivisionError' in result.detail


# ------------------------------------------------------- where it looks

def test_a_frozen_bundle_looks_only_inside_itself(monkeypatch, tmp_path):
    """#158: a clean Windows has no redistributable, so never System32."""
    monkeypatch.setattr(mr.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(mr.sys, '_MEIPASS', str(tmp_path), raising=False)
    dirs = mr._search_dirs()
    assert dirs, 'a frozen search with no directories finds nothing'
    for d in dirs:
        assert d == tmp_path or tmp_path in d.parents, d
        assert 'system32' not in str(d).lower(), d
    # The copy #158 already stages for whisper-cli.exe is among them.
    assert tmp_path / 'whisper' / 'windows' in dirs


# ----------------------------------------------- the callers keep the order

def _call_line(func: ast.FunctionDef, name: str) -> int:
    for node in ast.walk(func):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == name):
            return node.lineno
    raise AssertionError(f'{func.name} never calls {name}()')


def _function(path: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding='utf-8'))
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == name)


def test_main_preloads_before_anything_can_import_qt():
    """The fix only works if it runs first; a later call is no call at all."""
    path = REPO / 'src' / 'app' / 'main.py'
    module = ast.parse(path.read_text(encoding='utf-8'))
    for node in module.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [getattr(node, 'module', None) or ''] + [a.name for a in node.names]
            assert not any('PyQt6' in n for n in names), (
                'main.py imports PyQt6 at module scope, before main() can preload')

    main = _function(path, 'main')
    preload = _call_line(main, 'preload_newest')
    for node in ast.walk(main):
        if isinstance(node, (ast.Import, ast.ImportFrom)) and node.lineno < preload:
            mod = getattr(node, 'module', None) or ''
            assert 'PyQt6' not in mod and mod != 'app.main_window', (
                f'line {node.lineno} imports {mod} before the preload')
        if isinstance(node, ast.Call) and node.lineno < preload:
            assert not (isinstance(node.func, ast.Name)
                        and node.func.id in ('_run_mcp_server', '_run_test_mode')), (
                f'line {node.lineno} can reach Qt before the preload')


def test_the_relations_runtime_hook_preloads_after_setting_its_marker():
    """In a bundle, main() is too late: PyInstaller's pyi_rth_pyqt6 imports
    QtCore first. Custom runtime hooks run before PyInstaller's, so this hook
    is where the frozen preload has to happen -- and after the marker, which
    should_preload() reads, or it decides the runtime is absent.
    """
    path = REPO / 'packaging' / 'rthook_relations_build.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    marker = next(n.lineno for n in ast.walk(tree)
                  if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Attribute) and t.attr == '_wimi_relations_build'
                          for t in n.targets))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == 'preload_newest']
    assert calls, 'the relations runtime hook never preloads'
    assert all(c.lineno > marker for c in calls), 'preload runs before the marker is set'
    # And never able to stop the bundle starting: the call sits in a try.
    tries = [n for n in ast.walk(tree) if isinstance(n, ast.Try)]
    assert any(t.lineno < calls[0].lineno <= max(getattr(s, 'end_lineno', 0) for s in t.body)
               for t in tries), 'the preload in the runtime hook is not inside a try'


def test_the_build_gate_preloads_before_it_imports_qt():
    """Same order as the app, or the gate tests a configuration nobody runs."""
    gate = _function(REPO / 'scripts' / 'check_build_env.py', 'main')
    assert _call_line(gate, 'preload_msvc_runtime') < _call_line(gate, 'check_runtime_qt')


# --------------------------------------------------------- real Windows

@pytest.mark.skipif(not WINDOWS, reason='PE file versions exist only on Windows')
def test_a_real_file_version_is_read():
    import os
    path = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / mr.DLL_NAME
    if not path.is_file():
        pytest.skip(f'{path} absent -- no Visual C++ redistributable here')
    version = mr.file_version(path)
    assert version is not None and version[0] == 14, version


_PROBE = textwrap.dedent('''
    import sys
    sys.path.insert(0, {src!r})
    if {preload}:
        from app.msvc_runtime import preload_newest
        print('PRELOAD', preload_newest(force=True).describe())
    from PyQt6 import QtCore
    try:
        import torch
    except OSError as exc:
        print('TORCH_FAILED', getattr(exc, 'winerror', None))
        sys.exit(3)
    print('TORCH_OK', torch.__version__)
''')


def _qt_then_torch(preload: bool) -> subprocess.CompletedProcess:
    code = _PROBE.format(src=str(REPO / 'src'), preload=preload)
    return subprocess.run([sys.executable, '-c', code], capture_output=True,
                          text=True, timeout=180)


@pytest.mark.slow
@pytest.mark.skipif(not WINDOWS, reason='the MSVC runtime exists only on Windows')
def test_torch_loads_after_qt_once_the_runtime_is_preloaded():
    """With its control: the same process shape without the preload must fail.

    If the control passes, this Qt ships a new enough runtime and there is
    nothing for the preload to prove -- skip rather than pass vacuously.
    """
    # find_spec, not importorskip: importing torch in THIS process is the
    # thing under test, and pytest may already have Qt loaded.
    import importlib.util
    for name in ('torch', 'PyQt6'):
        if importlib.util.find_spec(name) is None:
            pytest.skip(f'{name} is not installed in this environment')
    control = _qt_then_torch(preload=False)
    if control.returncode == 0:
        pytest.skip('Qt-then-torch already works here without the preload: '
                    + control.stdout.strip())
    assert 'TORCH_FAILED 1114' in control.stdout, control.stdout + control.stderr

    fixed = _qt_then_torch(preload=True)
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    assert 'PRELOAD loaded' in fixed.stdout, fixed.stdout
    assert 'TORCH_OK' in fixed.stdout, fixed.stdout
