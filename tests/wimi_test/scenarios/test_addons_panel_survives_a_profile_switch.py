"""Regression: WIMI starts with a plugin installed, and the Addons panel follows a profile switch (#505).

``PluginManager`` captured the ``user_db`` it was constructed with. Two
outcomes, both driven here through a real WIMI:

* **Startup.** Test mode starts with ``user_db = None`` -- exactly the
  profile-picker path -- and ``main()`` called ``load_all()`` unguarded, so
  with a plugin installed WIMI died with ``AttributeError`` before
  ``TEST_MODE_READY``. Measured on master ``c464b54`` on Windows machine B.
* **Profile switch.** ``MainWindow.set_user_database`` rewired the bridge and
  the media manager but not the plugin manager, then closed the outgoing
  database, so ``getInstalledPlugins`` raised, ``initAddons`` caught it into
  an empty list, and the panel read "No addons installed" over a plugin on
  disk.

The plugin has to exist BEFORE WIMI starts -- a switch reloads the plugins
discovered at startup and deliberately does not re-scan the folder (#507) --
so this scenario starts its own session after writing the plugin rather
than taking the ``wimi_session`` fixture, which spawns WIMI before the test
body runs.

Before this file the Addons panel had never been driven end to end; every
plugin test was a unit test against a real ``UserDatabase``, which is why a
manager holding the *wrong* one was never seen.
"""
from __future__ import annotations

import json
import shutil
import uuid

import pytest

from _helpers.page_gate import wait_for_release
from _helpers.w114_form_ready import poll
from wimi_test.db.test_user import TestUser
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

PLUGIN_ID = "probe-505"


def _switch_to(page: WimiPage, user_id: int) -> None:
    page.eval_js(f"window.api.loadTestUserDatabase({user_id})", await_promise=True)


def _addons(page: WimiPage) -> dict:
    page.goto("settings")
    wait_for_release(page)
    page.eval_js(
        "document.querySelector('.settings-nav-item[data-panel=\"addons\"]').click()")
    assert poll(page, "!!document.querySelector('#addonList > *')", timeout_ms=10000), (
        "the Addons list never rendered")
    return json.loads(page.eval_js("""JSON.stringify({
        empty: !!document.querySelector('#addonList .addon-empty'),
        card: !!document.querySelector('[data-testid="settings-addon-card-%s"]'),
        enabled: (document.querySelector('[data-testid="settings-addon-toggle-%s"]') || {}).checked,
    })""" % (PLUGIN_ID, PLUGIN_ID)))


@pytest.mark.slow
@pytest.mark.regression
def test_wimi_starts_with_a_plugin_and_the_panel_follows_the_profile(wimi_config) -> None:
    plugin_dir = wimi_config.app_data_dir / "plugins" / PLUGIN_ID
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "manifest.json").write_text(json.dumps(
        {"id": PLUGIN_ID, "name": "Probe 505", "version": "1.0.0", "frontend_js": "p.js"}))
    other = None
    try:
        # Startup with a plugin installed and no profile attached: on master
        # this raises inside start(), because WIMI never reaches
        # TEST_MODE_READY.
        with WimiTestSession(scenario="addons505", config=wimi_config) as session:
            session.attach_user_db()
            page = session.page
            other = TestUser(session._master_db, scenario="addons505b",
                             run_id=uuid.uuid4().hex[:8])
            other.db.set_plugin_enabled(PLUGIN_ID, False)
            other.db.close()
            other._db = None

            before = _addons(page)
            assert before == {"empty": False, "card": True, "enabled": True}, before

            # The switch: MainWindow closes the outgoing database here.
            _switch_to(page, other.user_id)
            after = _addons(page)
            assert not after["empty"], (
                "after a profile switch the panel says no addons are installed over "
                "a plugin that is on disk")
            assert after["card"] and after["enabled"] is False, (
                f"the panel should show the incoming profile's state (disabled): {after}")

            # Hand WIMI back the session's profile so it releases ``other``'s
            # file before it is unlinked (Windows refuses an open file).
            _switch_to(page, session.user.user_id)
    finally:
        if other is not None:
            other.drop()
        shutil.rmtree(plugin_dir, ignore_errors=True)
