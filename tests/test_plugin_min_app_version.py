"""#508: a plugin's ``min_app_version`` is enforced, not just format-checked.

The field was validated against ``X.Y.Z`` and compared with nothing, so a
manifest declaring ``"99.0.0"`` loaded and ran like any other, and a plugin
author relying on it to stay off an old WIMI got no protection. Now:

* the ordering is SemVer precedence, because WIMI's own ``APP_VERSION`` is
  ``0.1.1-beta`` and the old ``X.Y.Z`` pin could not even name it;
* discovery skips an incompatible manifest with the reason in the log --
  the same shape as an invalid one;
* installing an incompatible zip is refused before anything is copied, so it
  cannot unseat a working older copy of the same plugin.
"""
from __future__ import annotations

import json
import zipfile

import pytest

from app import APP_VERSION
from app.plugin_manager import PluginManager
from app.plugin_manifest import PluginManifest, version_key
from database.user_db import UserDatabase


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, message):
        self.lines.append(('info', message))

    def warning(self, message):
        self.lines.append(('warning', message))


@pytest.fixture
def db(tmp_path):
    user_db = UserDatabase(db_path=tmp_path / "u.db", user_id=1, username="u")
    yield user_db
    user_db.close()


def _manifest(plugin_id="gated", **extra):
    data = {"id": plugin_id, "name": "Gated Plugin", "version": "1.0.0",
            "permissions": ["read"]}
    data.update(extra)
    return data


def _plugin_dir(plugins_dir, data):
    d = plugins_dir / data["id"]
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps(data))
    return d


def _zip(tmp_path, data, name="p.zip"):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps(data))
    return path


# ------------------------------------------------------------- ordering

def test_semver_precedence_including_the_projects_own_suffix():
    ordered = ["0.1.0", "0.1.1-alpha", "0.1.1-alpha.2", "0.1.1-alpha.10",
               "0.1.1-beta", "0.1.1-rc.1", "0.1.1", "0.2.0", "1.0.0", "10.0.0"]
    assert sorted(ordered, key=version_key) == ordered
    assert version_key("0.1.1-beta") < version_key("0.1.1")


def test_a_version_that_is_not_one_is_refused():
    with pytest.raises(ValueError):
        version_key("1.0")


def test_the_manifest_may_name_a_pre_release():
    """The old X.Y.Z pin refused a pre-release, which WIMI's own version is.

    Asserted against `APP_VERSION` rather than a literal, so a version bump
    cannot make it vacuous. It read `"0.1.1-beta", WIMI's own version` until
    that stopped being WIMI's own version (#425, 2026-10-09).
    """
    assert PluginManifest.validate(_manifest(min_app_version=APP_VERSION)) == []
    assert PluginManifest.validate(_manifest(min_app_version="1.0")) != []


@pytest.mark.parametrize("minimum, ok", [
    (None, True), ("0.1.0", True), ("0.1.1-alpha", True), ("0.1.1-beta", True),
    ("0.1.1", False), ("0.2.0", False), ("99.0.0", False),
])
def test_incompatibility_against_0_1_1_beta(minimum, ok):
    m = PluginManifest(id="x", name="X", version="1.0.0", min_app_version=minimum)
    reason = m.incompatibility("0.1.1-beta")
    assert (reason is None) is ok
    if not ok:
        assert minimum in reason and "0.1.1-beta" in reason and '"X"' in reason


# ------------------------------------------------------------- discovery

def test_discovery_skips_a_plugin_for_a_later_wimi_and_says_why(tmp_path, db):
    plugins = tmp_path / "plugins"
    _plugin_dir(plugins, _manifest("future", min_app_version="99.0.0"))
    _plugin_dir(plugins, _manifest("present", min_app_version="0.1.0"))
    log = _Log()
    pm = PluginManager(plugins, db, error_logger=log, app_version="0.1.1-beta")

    found = [m.id for m in pm.discover_plugins()]

    assert found == ["present"], "positive control: a compatible plugin still loads"
    assert "future" not in {p["id"] for p in pm.get_installed_plugins()}
    warnings = [m for level, m in log.lines if level == "warning"]
    assert any("future" in w and "99.0.0" in w and "0.1.1-beta" in w for w in warnings), warnings


def test_the_default_comparison_is_against_app_version(tmp_path, db):
    plugins = tmp_path / "plugins"
    _plugin_dir(plugins, _manifest("future", min_app_version="99.0.0"))
    pm = PluginManager(plugins, db, error_logger=_Log())
    assert pm._app_version == APP_VERSION
    assert pm.discover_plugins() == []


# ------------------------------------------------------------- install

def test_installing_a_plugin_for_a_later_wimi_is_refused_with_the_reason(tmp_path, db):
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    pm = PluginManager(plugins, db, error_logger=_Log(), app_version="0.1.1-beta")

    with pytest.raises(ValueError, match="needs WIMI 99.0.0 or later"):
        pm.install_plugin(str(_zip(tmp_path, _manifest(min_app_version="99.0.0"))))

    assert not (plugins / "gated").exists()


def test_a_refused_upgrade_leaves_the_working_copy_in_place(tmp_path, db):
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    pm = PluginManager(plugins, db, error_logger=_Log(), app_version="0.1.1-beta")
    pm.install_plugin(str(_zip(tmp_path, _manifest(), name="old.zip")))
    assert (plugins / "gated" / "manifest.json").exists()

    with pytest.raises(ValueError):
        pm.install_plugin(str(_zip(tmp_path, _manifest(version="2.0.0", min_app_version="99.0.0"),
                                   name="new.zip")))

    kept = json.loads((plugins / "gated" / "manifest.json").read_text())
    assert kept["version"] == "1.0.0", "the incompatible zip replaced a working plugin"
