"""
WIMI Application Package
PyQt6-based desktop application for exam preparation through metacognitive mistake analysis
"""

# Single source of truth for the user-facing application version.
# Consumed by getAppInfo (bridge), setApplicationVersion (Qt), the About
# dialog, the .wimi profile-archive manifest, and CORRESPONDING-SOURCE.txt.
# Distinct from database.__version__, which tracks the database
# package/schema phase.
#
# 0.4.1-beta, owner's decision 2026-11-08, for the macOS dictation fix (#897,
# PR #907): 0.4.0-beta's Mac build recorded no audio, and a rebuilt binary
# needs its own tag so the published source matches it (GPL-3.0 s6(d)).
# Before that 0.4.0-beta, owner's go-ahead 2026-11-07 ("go for release") for the release
# carrying the free-standing Quick note (#848), one shared library of error
# types (#888), the difficulty and time card (#898) and adding dimensions to an
# existing exam with its subjects prompt (#444, #605, #900), plus migrations
# m036-m038.
# Before that 0.3.0-beta, owner's go-ahead 2026-10-14 for the release carrying the
# self-assessment (#766), the calendar (#778), the Anki port (#784), the
# client-agnostic MCP panel and the analytics batch, plus migrations m032-m035.
# Before that 0.2.0-beta, owner's decision 2026-10-09 (#425), via 0.1.1-beta on
# 2026-10-06. It had stood at '0.1.0-beta' since 025ce80 on 2026-07-02 -- the
# day before the public v0.1.0-beta release -- so a build made at any point
# since reported the same version as that release. That release was published
# under an **MIT**
# declaration and WIMI relicensed to GPL-3.0 on 2026-09-30 (#195), so two
# artifacts could claim one version under different licences, and the notices
# document had no way to tell a recipient which they held.
#
# The old release's binaries are withdrawn, so the collision is gone as well
# as the ambiguity; the bump is what keeps the next one distinguishable.
#
# Bumping is safe for .wimi archives, which is the one thing worth checking
# before touching this: the manifest's `app_version` is **informational**.
# Compatibility is decided by `format_version` against
# ARCHIVE_FORMAT_VERSION, and by MAX(version) FROM schema_migrations -- not
# by this string. See profile_archive._app_version and _local_max_version.
APP_VERSION = '0.4.1-beta'

# Use lazy imports to avoid circular import issues
# Components are imported when accessed

__all__ = ['APP_VERSION', 'MainWindow', 'DatabaseBridge']

def __getattr__(name):
    """Lazy import of components"""
    if name == 'MainWindow':
        from app.main_window import MainWindow
        return MainWindow
    elif name == 'DatabaseBridge':
        from app.bridge import DatabaseBridge
        return DatabaseBridge
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
