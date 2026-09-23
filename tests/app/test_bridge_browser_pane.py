"""Bridge tests for ``BrowserPaneBridgeMixin``.

The domain layer is covered in ``tests/database/test_browser_pane.py``;
these prove the JSON contract ({success, data, error}) of the three
shortcut slots the Settings -> Question Banks panel calls, their
no-user_db guards, and that the three pane-control slots degrade to
``success=false, error='browser pane not available'`` when no controller
is attached. That exact error is what the entry form's toggle button
keys off to hide itself, so it is part of the contract.
"""
import json
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from app.bridge import DatabaseBridge
from database.master_db import MasterDatabase
from database.user_db import UserDatabase


NO_PANE = 'browser pane not available'


# ==================== Fixtures ====================

@pytest.fixture
def temp_db_path() -> Generator[Path, None, None]:
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        yield Path(f.name)
    try:
        Path(f.name).unlink()
    except Exception:
        pass


@pytest.fixture
def temp_master_db_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def user_db(temp_db_path: Path) -> Generator[UserDatabase, None, None]:
    db = UserDatabase(db_path=temp_db_path, user_id=1, username="test_user")
    yield db
    db.close()


@pytest.fixture
def master_db(temp_master_db_dir: Path) -> Generator[MasterDatabase, None, None]:
    db = MasterDatabase(data_dir=temp_master_db_dir, error_logger=None)
    yield db
    db.close()


@pytest.fixture
def bridge(user_db: UserDatabase, master_db: MasterDatabase) -> DatabaseBridge:
    master_db.bootstrap_first_user(username="test_admin", display_name="Test Admin")
    return DatabaseBridge(master_db=master_db, user_db=user_db)


@pytest.fixture
def bridge_no_user(master_db: MasterDatabase) -> DatabaseBridge:
    return DatabaseBridge(master_db=master_db, user_db=None)


class _FakeController:
    """Stands in for MainWindow's pane controller.

    ``result`` is what every method returns; ``error`` makes them raise.
    """

    def __init__(self, result=None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.opened_with: list[str] = []
        self.closed = 0

    def open_pane(self, url):
        self.opened_with.append(url)
        if self.error:
            raise self.error
        return self.result

    def close_pane(self):
        self.closed += 1
        if self.error:
            raise self.error
        return self.result

    def get_status(self):
        if self.error:
            raise self.error
        return self.result


# ---- Response helpers ------------------------------------------------------


def _ok(response: str):
    payload = json.loads(response)
    assert payload['success'] is True, f"Expected success, got: {payload.get('error')}"
    return payload.get('data')


def _err(response: str) -> str:
    payload = json.loads(response)
    assert payload['success'] is False, "Expected error, got success"
    return payload.get('error')


def _seed(user_db: UserDatabase):
    uworld = user_db.create_question_source(source_name='UWorld', url='https://uworld.com')
    amboss = user_db.create_question_source(source_name='Amboss', url='https://amboss.com')
    kaplan = user_db.create_question_source(source_name='Kaplan')  # no address
    return uworld, amboss, kaplan


# ==================== getPaneSources ====================


class TestGetPaneSources:
    def test_lists_only_sources_with_an_address(self, bridge, user_db):
        uworld, amboss, _kaplan = _seed(user_db)

        rows = _ok(bridge.getPaneSources())

        assert [r['source_name'] for r in rows] == ['Amboss', 'UWorld']
        assert set(rows[0]) == {'id', 'source_name', 'url', 'desktop_site', 'last_opened_at'}
        assert {r['id'] for r in rows} == {uworld.id, amboss.id}
        assert all(r['desktop_site'] is True for r in rows)

    def test_empty_when_no_source_has_an_address(self, bridge, user_db):
        user_db.create_question_source(source_name='Kaplan')
        assert _ok(bridge.getPaneSources()) == []

    def test_requires_user_db(self, bridge_no_user):
        assert _err(bridge_no_user.getPaneSources()) == 'No user database loaded'


# ==================== recordPaneSourceOpened ====================


class TestRecordPaneSourceOpened:
    def test_moves_the_source_to_the_front(self, bridge, user_db):
        uworld, _amboss, _kaplan = _seed(user_db)

        data = _ok(bridge.recordPaneSourceOpened(uworld.id))

        assert data == {'source_id': uworld.id}
        rows = _ok(bridge.getPaneSources())
        assert rows[0]['id'] == uworld.id
        assert rows[0]['last_opened_at'] is not None

    def test_requires_user_db(self, bridge_no_user):
        assert _err(bridge_no_user.recordPaneSourceOpened(1)) == 'No user database loaded'


# ==================== setPaneDesktopSite ====================


class TestSetPaneDesktopSite:
    def test_turns_the_flag_off_for_one_source(self, bridge, user_db):
        uworld, amboss, _kaplan = _seed(user_db)

        data = _ok(bridge.setPaneDesktopSite(uworld.id, False))

        assert data == {'source_id': uworld.id, 'desktop_site': False}
        flags = {r['id']: r['desktop_site'] for r in _ok(bridge.getPaneSources())}
        assert flags == {uworld.id: False, amboss.id: True}

    def test_turns_the_flag_back_on(self, bridge, user_db):
        uworld, _amboss, _kaplan = _seed(user_db)
        _ok(bridge.setPaneDesktopSite(uworld.id, False))

        data = _ok(bridge.setPaneDesktopSite(uworld.id, True))

        assert data == {'source_id': uworld.id, 'desktop_site': True}

    def test_requires_user_db(self, bridge_no_user):
        assert _err(bridge_no_user.setPaneDesktopSite(1, True)) == 'No user database loaded'


# ==================== Pane control without a controller ====================


class TestPaneControlWithoutController:
    """The optional-feature contract the entry form's button depends on."""

    def test_open(self, bridge):
        assert _err(bridge.openBrowserPane('https://uworld.com')) == NO_PANE

    def test_close(self, bridge):
        assert _err(bridge.closeBrowserPane()) == NO_PANE

    def test_status(self, bridge):
        assert _err(bridge.getBrowserPaneStatus()) == NO_PANE


# ==================== Pane control with a controller ====================


class TestPaneControlWithController:
    def test_open_forwards_url_and_returns_controller_status(self, bridge):
        ctrl = _FakeController(result={'open': True, 'url': 'https://uworld.com', 'tab_count': 1})
        bridge._browser_pane_controller = ctrl

        data = _ok(bridge.openBrowserPane('https://uworld.com'))

        assert ctrl.opened_with == ['https://uworld.com']
        assert data == {'open': True, 'url': 'https://uworld.com', 'tab_count': 1}

    def test_open_falls_back_when_controller_returns_non_dict(self, bridge):
        bridge._browser_pane_controller = _FakeController(result=None)
        assert _ok(bridge.openBrowserPane('https://x')) == {'open': True, 'url': 'https://x'}

    def test_close_returns_controller_status(self, bridge):
        ctrl = _FakeController(result={'open': False, 'url': None})
        bridge._browser_pane_controller = ctrl

        data = _ok(bridge.closeBrowserPane())

        assert ctrl.closed == 1
        assert data == {'open': False, 'url': None}

    def test_close_falls_back_when_controller_returns_non_dict(self, bridge):
        bridge._browser_pane_controller = _FakeController(result=None)
        assert _ok(bridge.closeBrowserPane()) == {'open': False}

    def test_status_returns_controller_dict(self, bridge):
        bridge._browser_pane_controller = _FakeController(
            result={'open': True, 'url': 'https://x', 'tab_count': 2}
        )
        assert _ok(bridge.getBrowserPaneStatus()) == {
            'open': True, 'url': 'https://x', 'tab_count': 2,
        }

    def test_status_coerces_non_dict_to_open_flag(self, bridge):
        bridge._browser_pane_controller = _FakeController(result=1)
        assert _ok(bridge.getBrowserPaneStatus()) == {'open': True}
        bridge._browser_pane_controller = _FakeController(result=0)
        assert _ok(bridge.getBrowserPaneStatus()) == {'open': False}

    def test_controller_exceptions_map_to_error_responses(self, bridge):
        bridge._browser_pane_controller = _FakeController(error=RuntimeError('boom'))

        assert _err(bridge.openBrowserPane('https://x')).startswith('Failed to open browser pane')
        assert _err(bridge.closeBrowserPane()).startswith('Failed to close browser pane')
        assert _err(bridge.getBrowserPaneStatus()).startswith('Failed to get browser pane status')

    def test_controller_missing_a_method_is_reported_not_raised(self, bridge):
        class _Partial:
            pass

        bridge._browser_pane_controller = _Partial()
        assert 'open_pane' in _err(bridge.openBrowserPane('https://x'))
        assert 'close_pane' in _err(bridge.closeBrowserPane())
        assert 'get_status' in _err(bridge.getBrowserPaneStatus())
