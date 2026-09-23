"""Tests for ``scripts/check_css_tokens.py``.

The script guards against a bug that has shipped four times (#76, #81, #97,
#102): a CSS custom property named by a ``var()`` where the property is defined
nowhere. It takes two forms and the script reports them separately:

* ``var(--x)`` — invalid at computed-value time and silently discarded;
  ``padding: var(--spacing-md)`` computes to ``0px`` (#76, #81).
* ``var(--x, fallback)`` — valid, so nothing complains, but the fallback wins
  unconditionally and the token half is dead code. When the fallback is a
  hardcoded colour the declaration cannot follow the palette (#97, #102).

These tests cover the three halves that have to be right: definition collection
(CSS declarations, ``themes.js`` theme dictionaries, ``setProperty`` calls,
HTML inline styles), use collection in each of the two forms, and the rule that
a fallback on a *defined* token is never reported — without which the second
check would flag roughly six hundred legitimate declarations and be turned off
within a week.

The last four tests are the standing regression guards: the real ``src/web/``
tree must stay clean in both forms, and neither allowlist may go stale.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "check_css_tokens.py"


def _load_script():
    """Import the script by path.

    ``scripts/`` is not a package (neither is it for
    ``check_instrumented_slots.py``), so load the module directly rather than
    adding an ``__init__.py`` just for the test.
    """
    spec = importlib.util.spec_from_file_location("check_css_tokens", SCRIPT_PATH)
    assert spec and spec.loader, f"could not load {SCRIPT_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_css_tokens = _load_script()


# --------------------------------------------------------------------------- #
# Definition collection
# --------------------------------------------------------------------------- #

@pytest.mark.unit
def test_finds_css_declaration_definitions():
    """A plain CSS declaration defines the token."""
    source = ":root {\n    --space-md: 1rem;\n    --radius-sm: 0.25rem;\n}"
    assert check_css_tokens.find_definitions(source) == {"--space-md", "--radius-sm"}


@pytest.mark.unit
def test_finds_theme_dictionary_definitions():
    """A quoted key in a themes.js theme dictionary defines the token.

    ``_wimiApplyThemeVariables`` writes these onto the root element, so a name
    listed here is genuinely defined at runtime.
    """
    source = """
    const dark = {
        '--text-primary':   '#f8fafc',
        "--border-color":  '#334155',
    };
    """
    assert check_css_tokens.find_definitions(source) == {
        "--text-primary",
        "--border-color",
    }


@pytest.mark.unit
def test_finds_set_property_definitions():
    """``setProperty('--x', …)`` defines the token.

    The density preference defines the whole spacing scale this way, which is
    exactly why #81's ``--spacing-md`` had to be repointed at ``--space-md``
    rather than defined as a static alias.
    """
    source = """
        root.setProperty('--space-md', '0.75rem');
        document.documentElement.style.setProperty("--font-family", stack);
        root.setProperty(`--color-primary`, hex);
    """
    assert check_css_tokens.find_definitions(source) == {
        "--space-md",
        "--font-family",
        "--color-primary",
    }


@pytest.mark.unit
def test_finds_html_inline_style_definitions():
    """An inline ``style=`` attribute defines the token for that subtree."""
    source = '<div class="bar" style="--bar-pct: 42%; width: 10px">x</div>'
    assert "--bar-pct" in check_css_tokens.find_definitions(source)


@pytest.mark.unit
def test_var_use_is_not_mistaken_for_a_definition():
    """``var(--x)`` must never register as defining ``--x``.

    Without this the script would consider every token self-defining and
    report nothing, ever.
    """
    source = "a { color: var(--color-danger); padding: var(--spacing-md, 1rem); }"
    assert check_css_tokens.find_definitions(source) == set()


# --------------------------------------------------------------------------- #
# Use collection
# --------------------------------------------------------------------------- #

@pytest.mark.unit
def test_finds_no_fallback_uses_with_line_numbers():
    source = "a {\n  color: var(--text-primary);\n}\nb {\n  gap: var( --space-md );\n}"
    assert check_css_tokens.find_uses(source) == [
        ("--text-primary", 2),
        ("--space-md", 5),
    ]


@pytest.mark.unit
def test_fallback_form_is_never_reported():
    """``find_uses`` collects the bare form only.

    The fallback form is not ignored by the script — :func:`find_fallback_uses`
    collects it — but it must not leak into the *bare* bucket, whose finding is
    "this declaration was discarded" and which would be wrong about that.
    """
    source = """
    a { color: var(--color-border, #e2e8f0); }
    b { font-size: var(--font-size-base, 0.9375rem); }
    c { border-color: var(--nope,currentColor); }
    """
    assert check_css_tokens.find_uses(source) == []


@pytest.mark.unit
def test_mixed_fallback_and_bare_uses_on_one_line():
    """Each form lands in its own bucket when both share a line."""
    source = "a { border: 1px solid var(--color-primary, #2563eb) var(--bad); }"
    assert check_css_tokens.find_uses(source) == [("--bad", 1)]
    assert check_css_tokens.find_fallback_uses(source) == [("--color-primary", 1)]


@pytest.mark.unit
def test_finds_fallback_uses_with_line_numbers():
    """The fallback form is collected with its line, whatever the fallback is."""
    source = (
        "a {\n  color: var(--color-border, #e2e8f0);\n}\n"
        "b {\n  font-size: var( --font-size-base , 0.9375rem );\n}\n"
        "c {\n  color: var(--sep, currentColor);\n}"
    )
    assert check_css_tokens.find_fallback_uses(source) == [
        ("--color-border", 2),
        ("--font-size-base", 5),
        ("--sep", 8),
    ]


@pytest.mark.unit
def test_nested_var_fallback_reports_both_names():
    """``var(--a, var(--b, #ccc))`` names two tokens, either of which can be dead.

    ``weight.css`` really does carry this shape, and the inner name is the one
    that is defined nowhere — so collecting only the outer would miss it.
    """
    source = "a { border-color: var(--border-color, var(--border-secondary, #d1d5db)); }"
    assert check_css_tokens.find_fallback_uses(source) == [
        ("--border-color", 1),
        ("--border-secondary", 1),
    ]


# --------------------------------------------------------------------------- #
# Whole-tree audit
# --------------------------------------------------------------------------- #

def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.mark.unit
def test_audit_reports_undefined_token_with_every_location(tmp_path):
    """An undefined token is reported once, listing every file:line that uses it."""
    _write(tmp_path, "src/web/css/styles.css", ":root { --space-md: 1rem; }")
    _write(
        tmp_path,
        "src/web/css/aliases.css",
        "a { padding: var(--spacing-md); }\nb { margin: var(--spacing-md); }",
    )

    result = check_css_tokens.audit(tmp_path)

    assert result.files_scanned == 2
    assert set(result.undefined) == {"--spacing-md"}
    assert result.undefined["--spacing-md"] == [
        "src/web/css/aliases.css:1",
        "src/web/css/aliases.css:2",
    ]


@pytest.mark.unit
def test_audit_accepts_a_token_defined_in_another_file(tmp_path):
    """Definitions are collected across the whole tree before uses are judged.

    A stylesheet may legitimately consume a token ``styles.css`` defines.
    """
    _write(tmp_path, "src/web/css/styles.css", ":root { --space-md: 1rem; }")
    _write(tmp_path, "src/web/css/tree.css", "a { padding: var(--space-md); }")

    assert check_css_tokens.audit(tmp_path).undefined == {}


@pytest.mark.unit
def test_audit_accepts_a_token_defined_only_by_a_theme_or_setproperty(tmp_path):
    """A token that only ever exists at runtime still counts as defined."""
    _write(
        tmp_path,
        "src/web/js/themes.js",
        "const t = { '--themed-only': '#fff' };\n"
        "root.setProperty('--runtime-only', x);",
    )
    _write(
        tmp_path,
        "src/web/css/a.css",
        "a { color: var(--themed-only); gap: var(--runtime-only); }",
    )

    assert check_css_tokens.audit(tmp_path).undefined == {}


@pytest.mark.unit
def test_audit_separates_the_two_forms(tmp_path):
    """An undefined token is reported under the form it was actually written in."""
    _write(tmp_path, "src/web/css/styles.css", ":root { --space-md: 1rem; }")
    _write(
        tmp_path,
        "src/web/css/a.css",
        "a { padding: var(--spacing-md); }\n"
        "b { border: 1px solid var(--color-border, #e0e0e0); }",
    )

    result = check_css_tokens.audit(tmp_path)

    assert result.undefined == {"--spacing-md": ["src/web/css/a.css:1"]}
    assert result.dead_fallback == {"--color-border": ["src/web/css/a.css:2"]}


@pytest.mark.unit
def test_audit_never_reports_a_fallback_on_a_defined_token(tmp_path):
    """``var(--defined, x)`` is legitimate and deliberate, and must stay silent.

    This is the rule that keeps the dead-fallback check usable: the real tree
    has hundreds of these. Flagging them would make the gate noise.
    """
    _write(tmp_path, "src/web/css/styles.css", ":root { --space-md: 1rem; }")
    _write(tmp_path, "src/web/css/a.css", "a { gap: var(--space-md, 12px); }")

    result = check_css_tokens.audit(tmp_path)

    assert result.dead_fallback == {}
    assert result.undefined == {}
    assert result.fallback_use_count == 1, "the use must still be counted, just not reported"


@pytest.mark.unit
def test_vendored_directories_are_excluded(tmp_path):
    """Vendored bundles define and use their own tokens; not ours to audit.

    Both their uses are ignored *and* their definitions must not be borrowed to
    excuse an undefined token in our own CSS.
    """
    _write(tmp_path, "src/web/js/lib/d3.js", "x = 'var(--vendor-token)';")
    _write(tmp_path, "src/web/lib/katex/katex.css", ".k { color: var(--katex-thing); }")
    _write(tmp_path, "src/web/lib/katex/defs.css", ":root { --borrowed: red; }")
    _write(tmp_path, "src/web/css/a.css", "a { color: var(--borrowed); }")

    result = check_css_tokens.audit(tmp_path)

    assert result.files_scanned == 1, "only src/web/css/a.css should be scanned"
    assert set(result.undefined) == {"--borrowed"}


@pytest.mark.unit
def test_audit_scans_css_js_and_html_only(tmp_path):
    """Non-web files in the tree are ignored."""
    _write(tmp_path, "src/web/css/a.css", ":root { --ok: 1px; }")
    _write(tmp_path, "src/web/html/p.html", '<b style="color: var(--ok)">x</b>')
    _write(tmp_path, "src/web/js/p.js", "el.style.cssText = 'gap: var(--ok)';")
    _write(tmp_path, "src/web/README.md", "var(--not-scanned)")

    result = check_css_tokens.audit(tmp_path)

    assert result.files_scanned == 3
    assert result.undefined == {}


# --------------------------------------------------------------------------- #
# The standing regression guard
# --------------------------------------------------------------------------- #

@pytest.mark.unit
def test_real_project_tree_has_no_unexpected_undefined_tokens():
    """``src/web/`` must not regain an undefined no-fallback token.

    This is the test that would have caught #76 and #81. Anything the project
    knowingly tolerates belongs in ``KNOWN_UNDEFINED`` with a reason, not here.
    """
    result = check_css_tokens.audit(PROJECT_ROOT)

    assert result.files_scanned > 0, "scan found no files — check SCAN_ROOT"
    assert result.use_count > 0, "scan found no var() uses — check the use pattern"

    unexpected = {
        token: locations
        for token, locations in result.undefined.items()
        if token not in check_css_tokens.KNOWN_UNDEFINED
    }
    assert not unexpected, (
        "undefined CSS custom properties used with no fallback:\n"
        + "\n".join(
            f"  {token}: {', '.join(locations)}"
            for token, locations in sorted(unexpected.items())
        )
    )


@pytest.mark.unit
def test_known_undefined_allowlist_has_no_stale_entries():
    """Every allowlisted token must still be undefined somewhere.

    The allowlist is self-cleaning by design: once the branch that owns a
    deferred rename merges, the entry has to go, or it sits there ready to
    re-hide the next occurrence of that name.
    """
    result = check_css_tokens.audit(PROJECT_ROOT)

    stale = sorted(set(check_css_tokens.KNOWN_UNDEFINED) - set(result.undefined))
    assert not stale, (
        "KNOWN_UNDEFINED entries no longer match any undefined use — "
        f"delete them from {SCRIPT_PATH.name}: {stale}"
    )



@pytest.mark.unit
def test_real_project_tree_has_no_unexpected_dead_fallbacks():
    """``src/web/`` must not regain a fallback guarding a nowhere-defined token.

    This is the test that would have caught #97 — six borders pinned to a
    near-white hex in every dark theme, which #81's audit could not see because
    it only looked at the bare form. Anything the project knowingly tolerates
    belongs in ``KNOWN_DEAD_FALLBACK`` with a reason, not here.
    """
    result = check_css_tokens.audit(PROJECT_ROOT)

    assert result.fallback_use_count > 0, (
        "scan found no var() uses with a fallback — check the fallback pattern"
    )

    unexpected = {
        token: locations
        for token, locations in result.dead_fallback.items()
        if token not in check_css_tokens.KNOWN_DEAD_FALLBACK
    }
    assert not unexpected, (
        "CSS custom properties defined nowhere, used with a fallback that "
        "therefore always wins:\n"
        + "\n".join(
            f"  {token}: {', '.join(locations)}"
            for token, locations in sorted(unexpected.items())
        )
    )


@pytest.mark.unit
def test_known_dead_fallback_allowlist_has_no_stale_entries():
    """Every allowlisted dead fallback must still be undefined somewhere."""
    result = check_css_tokens.audit(PROJECT_ROOT)

    stale = sorted(
        set(check_css_tokens.KNOWN_DEAD_FALLBACK) - set(result.dead_fallback)
    )
    assert not stale, (
        "KNOWN_DEAD_FALLBACK entries no longer match any undefined use — "
        f"delete them from {SCRIPT_PATH.name}: {stale}"
    )


@pytest.mark.unit
def test_the_two_allowlists_do_not_overlap():
    """A token exempted for one form must be exempted for the other deliberately.

    The dicts are separate so that tolerating the mild finding cannot silence
    the severe one. An overlap is not forbidden, but it must be written twice
    and on purpose, not inherited — so if one ever appears, say why here.
    """
    overlap = sorted(
        set(check_css_tokens.KNOWN_UNDEFINED)
        & set(check_css_tokens.KNOWN_DEAD_FALLBACK)
    )
    assert not overlap, (
        f"{overlap} is allowlisted in both forms. That is allowed, but only "
        "deliberately: update this test with the reason."
    )
