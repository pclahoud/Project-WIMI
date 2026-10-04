"""Regression: the About panel exists and carries the third-party notices (#195).

Owner's decision on #195 sub-decision (a), 2026-09-27: ship the notices as an
**About tab in Settings** rather than only as a file. Before this, WIMI shipped
Qt, QtWebEngine/Chromium, PyQt6, Pillow, D3, Fuse.js, TinyMCE, KaTeX and (on
Windows) four Microsoft C++ runtime DLLs with **no third-party notices at all**
— the sole exception being whisper.cpp's MIT text, which rode along because the
fetcher happened to put it in `vendor/whisper/<platform>/`.

What these tests are shaped around
----------------------------------

**The panel IS the document.** There is deliberately no second copy in `docs/`:
a frozen build has no `docs/` directory, and hand-synced copies of a document
in this repo drift — #61 and #62 both landed in an embed and never reached
`docs/`, which is why the import guide is generated now. One copy cannot drift.

**The version is read, not written.** A hardcoded version literal beside a
licence list is the thing most likely to go quietly stale, and notices are only
worth anything if they describe the build the student is running. It comes from
`getAppInfo`, i.e. `app.APP_VERSION`.

**Every licence string here was measured**, from installed wheel metadata or
from the vendored file's own header — not from what these projects are generally
known to use. The tests assert the components are *named*, not their licence
text, because the licences are facts about upstream that a test cannot verify
and that will legitimately change when a dependency is bumped. What must not
happen is a component silently disappearing from the list.
"""

from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

#: Every component the bundle ships that a notice has to name. Deliberately
#: not paired with licences: see the module docstring.
REQUIRED_COMPONENTS = [
    "PyQt6",
    "Qt 6",
    "Qt WebEngine",
    "Pillow",
    "python-json-logger",
    "MCP Python SDK",
    "PyInstaller",
    "D3.js",
    "Fuse.js",
    "KaTeX",
    "TinyMCE",
    "whisper.cpp",
    "Microsoft Visual C++ Runtime",
]


@pytest.fixture
def about(wimi_session: WimiTestSession, wimi_page: WimiPage):
    wimi_page.goto("settings")
    for _ in range(80):
        if wimi_page.eval_js(
                "!!document.querySelector('[data-testid=\"settings-nav-about\"]')"):
            break
        wimi_page.wait_for_timeout(100)
    else:
        raise AssertionError("the About nav item never appeared")
    return wimi_page


def _panel_text(page: WimiPage) -> str:
    return page.eval_js(
        "document.querySelector('[data-testid=\"settings-panel-about\"]')"
        ".textContent.replace(/\\s+/g, ' ')")


@pytest.mark.slow
@pytest.mark.regression
def test_the_about_tab_opens_its_panel(about):
    """It is reached the same way every other settings panel is."""
    assert about.eval_js(
        "!document.querySelector('[data-testid=\"settings-panel-about\"]')"
        ".classList.contains('active')"
    ) is True, "the About panel started active; it should not"

    about.eval_js(
        "document.querySelector('[data-testid=\"settings-nav-about\"]').click()")
    about.wait_for_timeout(200)

    assert about.eval_js(
        "document.querySelector('[data-testid=\"settings-panel-about\"]')"
        ".classList.contains('active')"
    ) is True, "clicking About did not activate its panel"


@pytest.mark.slow
@pytest.mark.regression
@pytest.mark.parametrize("component", REQUIRED_COMPONENTS)
def test_every_bundled_component_is_named(about, component):
    """One test per component, so a removal names itself.

    Several of these licences *require* that a notice accompany the software,
    and the failure mode is silent: a component drops off the list and nothing
    anywhere complains.
    """
    assert component in _panel_text(about), (
        f"{component!r} is bundled but not named in the notices"
    )


@pytest.mark.slow
@pytest.mark.regression
def test_wimis_own_licence_is_stated_and_is_not_confused_with_the_rest(about):
    """WIMI is GPL-3.0; several bundled components are under other terms.

    Stating WIMI's own licence separately from the third-party list is the
    point — it is what stops the page reading as though one licence covered
    everything in the bundle.

    WIMI was MIT until 2026-09-30. It is GPL-3.0 because PyQt6's bindings are
    `GPL-3.0-only` and TinyMCE is GPL v2 or later, so a distributed binary
    combining them cannot carry a permissive licence (#195 (d)).

    **This panel is also WIMI's "Appropriate Legal Notices" under GPL-3.0
    §5(d)**, which an interactive program has to display. That is why the
    warranty disclaimer and the source location are asserted here and not
    only the licence name: dropping either would leave the notice incomplete,
    and nothing else in the app states them.
    """
    text = _panel_text(about)

    assert "GNU General Public License" in text
    assert "pclahoud" in text
    assert "Third-party notices" in text
    assert "WITHOUT ANY WARRANTY" in text, (
        "GPL-3.0 §5(d) wants the warranty disclaimer in the notice an "
        "interactive program displays, and this panel is the only place "
        "WIMI states one"
    )
    assert "github.com/pclahoud/Project-WIMI" in text, (
        "the notice has to say where the corresponding source is"
    )


@pytest.mark.slow
@pytest.mark.regression
def test_the_version_is_read_from_the_app_not_written_into_the_page(about):
    """A literal here would go stale silently.

    Asserts the placeholder was actually replaced, and that it matches what
    `getAppInfo` reports — so this fails if the wiring breaks, rather than
    displaying an ellipsis forever.
    """
    about.eval_js(
        "document.querySelector('[data-testid=\"settings-nav-about\"]').click()")
    for _ in range(40):
        shown = about.eval_js(
            "document.querySelector('[data-testid=\"about-app-version\"]')"
            ".textContent.trim()")
        if shown and shown != "…":
            break
        about.wait_for_timeout(100)
    else:
        raise AssertionError("the version placeholder was never filled in")

    reported = about.eval_js(
        "(async () => (await window.api.getAppInfo()).version)()",
        await_promise=True)

    assert shown == reported, f"panel shows {shown!r}, app reports {reported!r}"
    assert shown, "the app reported an empty version"


@pytest.mark.slow
@pytest.mark.regression
def test_the_windows_runtime_is_marked_as_windows_only(about):
    """It ships only in Windows builds, and a notice that implied otherwise
    would be wrong on two of the three platforms."""
    text = _panel_text(about)

    assert "Windows builds only" in text
    assert "MSVCP140" in text
