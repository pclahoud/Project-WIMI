"""Logical route name -> HTML file URL resolution for WIMI test infrastructure.

This module is the single source of truth for the mapping between human-friendly
route names used in tests (e.g. ``"dashboard"``, ``"entry-form"``) and the
corresponding HTML files under ``src/web/html/``. Decoupling the names from the
filenames means that renaming a page in ``src/web/html/`` is a one-line change
here rather than a sweeping update across every test that navigates to it.

See ``docs/planning/TEST_INFRASTRUCTURE.md`` section 4 (``WimiPage`` public API
contract). ``WimiPage.goto(route)`` resolves the logical name through this
module's :func:`resolve` function and then issues the navigation.

Route paths assume the standard repository layout: each route's relative path
is taken to live at ``<app_root>/src/web/html/<path>``. Paths are returned as
``file://`` URLs via :meth:`pathlib.Path.as_uri`, which yields the correct
form on both Windows (``file:///C:/...``) and macOS/Linux (``file:///...``).

Valid route names:

- ``dashboard``
- ``entry-form``
- ``analytics``
- ``entry-browser``
- ``entry-detail``
- ``tree-editor``
- ``session-setup``
- ``subject-deep-dive``
- ``settings``
- ``exam-wizard``
- ``error-viewer``
- ``profile-select``

This is a leaf module: stdlib imports only, no imports from any ``wimi_test.*``
sibling. File existence is intentionally not checked at import or resolve
time -- a typo in a route's path will surface naturally as a navigation
failure during the test that uses it.
"""

from pathlib import Path
from types import MappingProxyType

__all__ = ["ROUTES", "resolve"]


# Frozen mapping of logical route name -> path relative to ``src/web/html/``.
# Wrapped in ``MappingProxyType`` so callers cannot mutate the registry; any
# additions belong in this module so the design stays the single source of truth.
ROUTES: MappingProxyType = MappingProxyType({
    "dashboard": "index.html",
    "entry-form": "question_entry.html",
    "analytics": "analytics_dashboard.html",
    "entry-browser": "entry_browser.html",
    "entry-detail": "entry_detail.html",
    "tree-editor": "tree_editor.html",
    "session-setup": "session_setup.html",
    "subject-deep-dive": "subject_deep_dive.html",
    "settings": "settings.html",
    "exam-wizard": "wizards/exam_wizard.html",
    "error-viewer": "error-viewer.html",
    "profile-select": "profile_select.html",
})


def resolve(route: str, app_root: Path) -> str:
    """Resolve a logical route name to a ``file://`` URL.

    Parameters
    ----------
    route:
        Logical route name. Must be a key of :data:`ROUTES`.
    app_root:
        Repository root. The HTML file is located at
        ``<app_root>/src/web/html/<ROUTES[route]>``.

    Returns
    -------
    str
        A ``file://`` URL produced by :meth:`pathlib.Path.as_uri`, which
        handles platform-specific quoting (drive letters on Windows, leading
        slashes on POSIX) correctly.

    Raises
    ------
    ValueError
        If ``route`` is not a known route name. The error message lists every
        valid route so a typo is immediately self-correcting.
    """
    if route not in ROUTES:
        valid = ", ".join(sorted(ROUTES))
        raise ValueError(
            f"Unknown route {route!r}. Valid routes: {valid}"
        )
    html_path = app_root / "src" / "web" / "html" / ROUTES[route]
    return html_path.as_uri()
