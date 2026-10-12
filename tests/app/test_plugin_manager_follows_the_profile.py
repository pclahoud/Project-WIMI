"""PluginManager reads the profile that is open now, not the one it was born with (#505).

``PluginManager`` was handed whatever ``user_db`` startup resolution produced
and kept it for the whole session. Two outcomes, both measured on master at
``c464b54`` (Windows machine B) with one minimal valid plugin installed:

- **On the profile-picker path ``user_db`` is ``None``**, and ``load_all()``
  -- called unguarded from ``main()`` -- raised ``AttributeError``, so with any
  plugin installed and no auto-opened profile WIMI did not start.
- **After a profile switch** the manager still held the outgoing database,
  which ``MainWindow.set_user_database`` then closes, so the Addons panel's
  ``get_installed_plugins`` raised and the page rendered "No addons installed".

Every test here fails on that tree. The negative control the issue recorded
-- an empty plugins directory raises nothing -- is why nobody saw it, so each
test installs a plugin first.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.main_window import MainWindow
from app.plugin_manager import PluginManager
from database.user_db import UserDatabase

BACKEND = '''
class _Probe:
    def __init__(self, api):
        self.api = api

    def whose(self):
        return self.api.get_data("owner")


def create_plugin(api):
    return _Probe(api)
'''


@pytest.fixture
def plugins(tmp_path):
    root = tmp_path / "plugins"
    for pid, backend in (("front-only", None), ("with-backend", BACKEND)):
        d = root / pid
        d.mkdir(parents=True)
        manifest = {"id": pid, "name": pid, "version": "1.0.0", "permissions": ["read"]}
        if backend:
            (d / "backend.py").write_text(backend)
            manifest["backend"] = "backend.py"
        else:
            manifest["frontend_js"] = "p.js"
        (d / "manifest.json").write_text(json.dumps(manifest))
    return root


def _profile(tmp_path, user_id, name):
    db = UserDatabase(db_path=tmp_path / f"{name}.db", user_id=user_id, username=name)
    db.set_plugin_data("with-backend", "owner", name)
    return db


@pytest.fixture
def two_profiles(tmp_path):
    a, b = _profile(tmp_path, 1, "alice"), _profile(tmp_path, 2, "bob")
    yield a, b
    for db in (a, b):
        if db.conn is not None:
            db.close()


# ------------------------------------------------------------ no profile open

def test_with_no_profile_open_load_all_does_not_raise_and_loads_nothing(plugins):
    pm = PluginManager(plugins, None)
    assert pm.load_all() == {"front-only": False, "with-backend": False}
    assert pm.get_plugin_registry() == {}


def test_with_no_profile_open_installed_plugins_are_still_listed(plugins):
    pm = PluginManager(plugins, None)
    pm.load_all()
    listed = {p["id"]: p["enabled"] for p in pm.get_installed_plugins()}
    assert listed == {"front-only": False, "with-backend": False}


def test_a_write_with_no_profile_open_is_refused_in_a_sentence(plugins):
    pm = PluginManager(plugins, None)
    pm.load_all()
    with pytest.raises(ValueError, match="No profile is open"):
        pm.set_plugin_enabled("front-only", False)
    with pytest.raises(ValueError, match="No profile is open"):
        pm.uninstall_plugin("front-only")
    assert (plugins / "front-only").is_dir(), "the refusal came after the folder was deleted"


def test_opening_a_profile_from_the_picker_loads_its_plugins(plugins, two_profiles):
    alice, _ = two_profiles
    pm = PluginManager(plugins, None)
    pm.load_all()
    assert pm.set_user_database(alice) == {"front-only": True, "with-backend": True}
    assert pm._backend_instances["with-backend"].whose() == "alice"


def test_one_plugin_failing_cannot_stop_the_rest_loading(plugins, two_profiles, monkeypatch):
    alice, _ = two_profiles
    real = alice.get_plugin_enabled

    def flaky(plugin_id):
        if plugin_id == "front-only":
            raise RuntimeError("corrupt row")
        return real(plugin_id)

    monkeypatch.setattr(alice, "get_plugin_enabled", flaky)
    pm = PluginManager(plugins, alice)
    assert pm.load_all() == {"front-only": False, "with-backend": True}


# ------------------------------------------------------------ profile switch

def test_after_a_switch_the_panel_lists_plugins_from_the_incoming_profile(plugins, two_profiles):
    alice, bob = two_profiles
    bob.set_plugin_enabled("front-only", False)
    pm = PluginManager(plugins, alice)
    pm.load_all()

    pm.set_user_database(bob)
    alice.close()                      # what MainWindow does straight after

    listed = {p["id"]: p["enabled"] for p in pm.get_installed_plugins()}
    assert listed == {"front-only": False, "with-backend": True}
    assert "front-only" not in pm._backend_instances, "bob disabled it, it is still loaded"


def test_a_backend_plugin_reads_the_incoming_profile_after_a_switch(plugins, two_profiles):
    alice, bob = two_profiles
    pm = PluginManager(plugins, alice)
    pm.load_all()
    assert pm._backend_instances["with-backend"].whose() == "alice"

    pm.set_user_database(bob)
    alice.close()
    assert pm._backend_instances["with-backend"].whose() == "bob"
    assert pm._apis["with-backend"]._db is bob


def test_settings_writes_after_a_switch_land_in_the_incoming_profile(plugins, two_profiles):
    alice, bob = two_profiles
    pm = PluginManager(plugins, alice)
    pm.load_all()
    pm.set_user_database(bob)
    pm.update_plugin_settings("front-only", {"k": "v"})
    assert bob.get_plugin_settings("front-only") == {"k": "v"}
    assert alice.get_plugin_settings("front-only") == {}


def test_a_switch_does_not_import_a_plugin_dropped_in_since_startup(plugins, two_profiles):
    """A re-scan on switch would run a new backend's Python at a new moment (#507)."""
    alice, bob = two_profiles
    pm = PluginManager(plugins, alice)
    pm.load_all()
    late = plugins / "late-arrival"
    late.mkdir()
    (late / "backend.py").write_text("raise SystemExit('imported on a profile switch')\n")
    (late / "manifest.json").write_text(json.dumps(
        {"id": "late-arrival", "name": "late", "version": "1.0.0", "backend": "backend.py"}))

    assert "late-arrival" not in pm.set_user_database(bob)
    assert "late-arrival" not in {p["id"] for p in pm.get_installed_plugins()}


def test_opening_a_profile_does_not_load_a_plugin_too_new_for_this_wimi(plugins, two_profiles):
    """#505 meets #508: the reload on a profile opening is not a way round
    ``min_app_version``. It reloads what discovery kept, and discovery keeps
    nothing this WIMI is too old for."""
    alice, _ = two_profiles
    too_new = plugins / "too-new"
    too_new.mkdir()
    (too_new / "backend.py").write_text("raise SystemExit('loaded despite min_app_version')\n")
    (too_new / "manifest.json").write_text(json.dumps(
        {"id": "too-new", "name": "too new", "version": "1.0.0", "backend": "backend.py",
         "min_app_version": "99.0.0"}))

    pm = PluginManager(plugins, None)
    pm.load_all()
    loaded = pm.set_user_database(alice)

    assert loaded == {"front-only": True, "with-backend": True}, "control: the others loaded"
    assert "too-new" not in pm._backend_instances


# ------------------------------------------------------------ MainWindow wiring

def test_the_switch_hook_rebinds_plugins_before_closing_the_outgoing_profile(
        plugins, two_profiles, tmp_path):
    """``set_user_database`` is called unbound, as the browser-pane tests do."""
    alice, bob = two_profiles
    pm = PluginManager(plugins, alice)
    pm.load_all()
    order = []
    real_close, real_rebind = alice.close, pm.set_user_database
    alice.close = lambda: (order.append("close-outgoing"), real_close())
    pm.set_user_database = lambda db: (order.append("rebind-plugins"), real_rebind(db))[1]

    window = SimpleNamespace(
        user_db=alice, plugin_manager=pm, app_data_dir=tmp_path, error_logger=None,
        db_bridge=SimpleNamespace(set_user_database=lambda db: None, _plugin_registry={}),
        status_bar=SimpleNamespace(showMessage=lambda m: None),
        _update_window_title=lambda: None,
    )
    MainWindow.set_user_database(window, bob)

    assert order == ["rebind-plugins", "close-outgoing"]
    assert window.db_bridge._plugin_registry["with-backend"].whose() == "bob"
    assert {p["id"] for p in pm.get_installed_plugins()} == {"front-only", "with-backend"}
