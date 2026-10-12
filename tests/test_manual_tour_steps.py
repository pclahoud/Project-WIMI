"""The first-run tour's step text, and the gate that keeps it honest (#430, #428).

What this covers
----------------
``docs/manual/NN_slug.md`` carries the tour's short forms as ``<!-- tour ... -->``
blocks, written beside the section whose rule each one compresses, and
``scripts/check_manual_sync.py`` collects them into ``src/web/js/tour_steps.js``.
Three different things have to be right for that to be worth trusting, and they
fail in three different ways:

* **the artifact is the blocks.** Covered by the gate itself, which generates
  rather than diffs, so the only failure is a missing ``--write``. Asserted
  against the real tree below as well as in ``test_manual_chapters.py``.
* **a malformed block is refused with a sentence**, not accepted and shipped
  wrong. A step is one or two sentences of prose on a page name the tour knows;
  every one of those constraints has a negative control here, because a
  validator broken by a typo reports every block clean and looks exactly like a
  clean tree.
* **a step's derived half is derivable.** The chapter, its title, the enclosing
  section and the deep link are worked out from where the block sits rather than
  written in it, so a step cannot name a chapter it is not in. The link's
  *fragment* is the one thing Python cannot check without re-deriving it, which
  would be circular -- so it is checked in a real engine by
  ``tests/wimi_test/scenarios/test_manual_renders_in_the_app.py``.

What is deliberately NOT here
-----------------------------
Whether the marker is invisible to a student. That is a property of
``help_page.js`` and was measured in a real QtWebEngine rather than reasoned
about: before the renderer stripped comments, a block planted in chapter 1
reached the page as an ordinary paragraph. The scenario owns that assertion,
with the embed as its positive control.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "check_manual_sync.py"
MANUAL_DIR = PROJECT_ROOT / "docs" / "manual"
WEB_HTML = PROJECT_ROOT / "src" / "web" / "html"


def _load_script():
    """Import the gate by path -- ``scripts/`` is not a package."""
    spec = importlib.util.spec_from_file_location("check_manual_sync", SCRIPT_PATH)
    assert spec and spec.loader, f"could not load {SCRIPT_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sync = _load_script()


def _steps() -> list[dict]:
    """Every tour step in the real tree, read from the chapters."""
    chapters = sync.read_chapters(PROJECT_ROOT)
    return [step for chapter in chapters for step in chapter.tour]


def _artifact() -> dict[str, list[dict]]:
    """The committed artifact, parsed back out of the generated JS."""
    text = (PROJECT_ROOT / sync.TOUR_ARTIFACT).read_text(encoding="utf-8")
    marker = f"{sync.TOUR_GLOBAL} = "
    assert marker in text, f"{sync.TOUR_ARTIFACT} does not assign {sync.TOUR_GLOBAL}"
    payload = text.split(marker, 1)[1].rstrip()
    assert payload.endswith(";"), "the generated assignment is not terminated"
    return json.loads(payload[:-1])


# --------------------------------------------------------------------------- #
# A block, parsed
# --------------------------------------------------------------------------- #

GOOD_TEXT = (
    "A weight is a share of the whole exam at any depth, never a share of "
    "the subject above it, so a child may be larger than its parent."
)

CHAPTER = (
    "# A chapter\n"
    "\n"
    "## In short\n"
    "\n"
    "One sentence that the index shows.\n"
    "\n"
    "## Body\n"
    "\n"
    "<!-- tour\n"
    "page: tree-editor\n"
    "anchor: the weight beside a subject's name\n"
    f"text: {GOOD_TEXT}\n"
    "-->\n"
    "\n"
    "Body text.\n"
)


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """A miniature repo with one chapter carrying one tour block."""
    (tmp_path / "docs" / "manual").mkdir(parents=True)
    (tmp_path / "src" / "web" / "html").mkdir(parents=True)
    (tmp_path / "src" / "web" / "js").mkdir(parents=True)
    (tmp_path / sync.MANUAL_DIR / "01_a_chapter.md").write_text(
        CHAPTER, encoding="utf-8"
    )
    (tmp_path / sync.INDEX_PAGE).write_text(
        "<body>\n"
        f"    {sync.INDEX_OPEN}\n"
        f"    {sync.INDEX_CLOSE}\n"
        "</body>\n",
        encoding="utf-8",
    )
    sync.write(tmp_path)
    return tmp_path


def _rewrite(repo: Path, chapter: str) -> None:
    (repo / sync.MANUAL_DIR / "01_a_chapter.md").write_text(
        chapter, encoding="utf-8"
    )


@pytest.mark.unit
def test_a_block_becomes_a_step_with_its_context_derived(fake_repo: Path):
    """The three authored fields, and four derived from where the block sits."""
    chapters = sync.read_chapters(fake_repo)
    assert len(chapters[0].tour) == 1
    step = chapters[0].tour[0]
    assert step == {
        "page": "tree-editor",
        "anchor": "the weight beside a subject's name",
        "text": GOOD_TEXT,
        "chapter": "a_chapter",
        "chapter_title": "A chapter",
        "section": "Body",
        "link": "help_a_chapter.html#body",
    }


@pytest.mark.unit
def test_a_wrapped_field_is_joined_into_one_sentence(fake_repo: Path):
    """Chapters wrap at 80 columns, so a step's text has to as well."""
    _rewrite(fake_repo, CHAPTER.replace(
        f"text: {GOOD_TEXT}\n",
        "text: A weight is a share of the whole exam at any depth, never a\n"
        "  share of the subject above it, so a child may be larger than its\n"
        "  parent.\n",
    ))
    step = sync.read_chapters(fake_repo)[0].tour[0]
    assert step["text"] == GOOD_TEXT
    assert "\n" not in step["text"]
    assert "  " not in step["text"], "a continuation's indent reached the step"


@pytest.mark.unit
def test_the_gate_writes_and_then_matches(fake_repo: Path):
    """--write produces a clean tree; the bare gate agrees."""
    assert sync.audit(fake_repo) == {}
    artifact = fake_repo / sync.TOUR_ARTIFACT
    assert artifact.is_file()
    assert GOOD_TEXT in artifact.read_text(encoding="utf-8")


@pytest.mark.unit
def test_the_gate_fails_on_a_hand_edited_artifact(fake_repo: Path):
    """The deliberate-desync control: without it the gate could be comparing
    a string to itself and nobody would know."""
    artifact = fake_repo / sync.TOUR_ARTIFACT
    artifact.write_text(
        artifact.read_text(encoding="utf-8").replace("tree-editor", "settings"),
        encoding="utf-8",
    )
    problems = sync.audit(fake_repo)
    assert str(sync.TOUR_ARTIFACT) in problems

    sync.write(fake_repo)
    assert sync.audit(fake_repo) == {}
    assert "tree-editor" in artifact.read_text(encoding="utf-8")


@pytest.mark.unit
def test_an_edited_step_reaches_the_artifact(fake_repo: Path):
    """Editing the markdown and running --write is the whole workflow."""
    _rewrite(fake_repo, CHAPTER.replace(
        GOOD_TEXT, GOOD_TEXT.replace("may be larger", "may legitimately be larger")
    ))
    assert sync.audit(fake_repo), "an edited block did not register as a desync"
    sync.write(fake_repo)
    assert sync.audit(fake_repo) == {}
    assert "may legitimately be larger" in (
        fake_repo / sync.TOUR_ARTIFACT
    ).read_text(encoding="utf-8")


@pytest.mark.unit
def test_a_chapter_with_no_blocks_contributes_nothing(fake_repo: Path):
    """A page whose tour is not written yet simply has none (#430)."""
    _rewrite(fake_repo, CHAPTER.replace(
        "<!-- tour\n"
        "page: tree-editor\n"
        "anchor: the weight beside a subject's name\n"
        f"text: {GOOD_TEXT}\n"
        "-->\n"
        "\n",
        "",
    ))
    sync.write(fake_repo)
    assert sync.read_chapters(fake_repo)[0].tour == []
    text = (fake_repo / sync.TOUR_ARTIFACT).read_text(encoding="utf-8")
    assert f"{sync.TOUR_GLOBAL} = {{}};" in text
    assert "0 step(s) across 0 page(s)" in text


# --------------------------------------------------------------------------- #
# Every refusal fires, one control each
# --------------------------------------------------------------------------- #

BLOCK = (
    "<!-- tour\n"
    "page: tree-editor\n"
    "anchor: the weight beside a subject's name\n"
    f"text: {GOOD_TEXT}\n"
    "-->"
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutation, needle",
    [
        # A missing field. All three are required: a step with no page belongs
        # to no tour, and one with no anchor is #430's symptomless failure --
        # a step the overlay cannot place and silently skips.
        (BLOCK.replace("page: tree-editor\n", ""), "missing 'page'"),
        (BLOCK.replace("anchor: the weight beside a subject's name\n", ""),
         "missing 'anchor'"),
        (BLOCK.replace(f"text: {GOOD_TEXT}\n", ""), "missing 'text'"),
        # A page the tour does not have would create a ninth page nothing shows.
        (BLOCK.replace("tree-editor", "tree_editor"), "is not a page with a tour"),
        # A field name nobody reads. Silently dropping it would lose whatever
        # the author thought they were saying.
        (BLOCK.replace("anchor:", "anchors:"), "not a tour field"),
        # Inline markup: #430 renders a step as data, so a backtick or a link
        # reaches a student literally.
        (BLOCK.replace("never a share", "never a `share`"), "uses markup"),
        (BLOCK.replace("never a share", "never **a** share"), "uses markup"),
        (BLOCK.replace("never a share", "never [a](x.html) share"), "uses markup"),
        # Over the ceiling the panel covers the thing it points at; under the
        # floor the block's text never got written.
        (BLOCK.replace(GOOD_TEXT, GOOD_TEXT + " " + GOOD_TEXT + " " + GOOD_TEXT),
         "characters; the range is"),
        (BLOCK.replace(GOOD_TEXT, "Weights work differently here."),
         "characters; the range is"),
        # A truncated short form reads as a complete one.
        (BLOCK.replace(GOOD_TEXT, GOOD_TEXT.rstrip(".")), "full stop"),
        # An anchor names one thing on screen.
        (BLOCK.replace("the weight beside a subject's name", "x" * 120),
         "anchor is 120 characters"),
        # A line that opens a markdown block. The renderer strips it, but the
        # chapter sweeps read the raw markdown, so it fails an unrelated test
        # for an unrelated-looking reason.
        (BLOCK.replace("page: tree-editor", "- page: tree-editor"),
         "would read as a list item"),
        (BLOCK + "\n\n<!-- tour\npage: settings\n## heading\n-->",
         "would read as a list item"),
        # A continuation flush left reads as a field that is not one.
        (BLOCK.replace("-->", "and more text\n-->"),
         "flush left but is not a field"),
        # A blank line inside the block means a key has been lost.
        (BLOCK.replace("anchor:", "\nanchor:"), "blank line in it"),
        # The same field twice: one of the two is silently discarded otherwise.
        (BLOCK.replace("-->", "page: settings\n-->"), "given twice"),
    ],
    ids=[
        "no-page", "no-anchor", "no-text", "unknown-page", "unknown-field",
        "backtick", "bold", "link", "too-long", "too-short", "no-full-stop",
        "long-anchor", "bullet-line", "heading-line", "flush-continuation",
        "blank-line", "duplicate-field",
    ],
)
@pytest.mark.filterwarnings("ignore")
def test_a_malformed_block_is_refused_with_a_sentence(
    fake_repo: Path, mutation: str, needle: str
):
    """#66 2.2's rule: a refusal is a sentence a human can act on."""
    _rewrite(fake_repo, CHAPTER.replace(BLOCK, mutation))
    with pytest.raises(sync.ManualError) as exc:
        sync.audit(fake_repo)
    assert needle in str(exc.value), str(exc.value)


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutation, needle",
    [
        ("Body text.\n<!-- tour", "blank line before it"),
        ("<!-- tour", "blank line after it"),
    ],
    ids=["no-blank-before", "no-blank-after"],
)
def test_a_block_must_be_surrounded_by_blank_lines(
    fake_repo: Path, mutation: str, needle: str
):
    """The renderer BLANKS a comment's lines rather than removing them.

    That choice is deliberate -- removing them would join the paragraph above a
    comment to the paragraph below it, a silent change to a chapter nobody
    edited. The cost is that a block butted against prose or a bullet changes
    what the chapter renders, so the gate owns the placement rule instead.
    """
    if needle == "blank line before it":
        chapter = CHAPTER.replace(f"## Body\n\n{BLOCK}", f"## Body\n\nBody text.\n{BLOCK}")
    else:
        chapter = CHAPTER.replace(f"{BLOCK}\n\n", f"{BLOCK}\nBody text.\n")
    _rewrite(fake_repo, chapter)
    with pytest.raises(sync.ManualError) as exc:
        sync.audit(fake_repo)
    assert needle in str(exc.value), str(exc.value)


@pytest.mark.unit
def test_an_unterminated_comment_is_refused(fake_repo: Path):
    """Now that the renderer strips comments, an unclosed one swallows the
    rest of the chapter with no error anywhere -- the symptomless class.
    """
    _rewrite(fake_repo, CHAPTER.replace(f"{BLOCK}\n", "<!-- tour\npage: settings\n"))
    with pytest.raises(sync.ManualError) as exc:
        sync.audit(fake_repo)
    assert "never closed" in str(exc.value), str(exc.value)

    # And an ordinary HTML comment, which a chapter is allowed to carry.
    _rewrite(fake_repo, CHAPTER.replace(f"{BLOCK}\n", "<!-- a note\n"))
    with pytest.raises(sync.ManualError) as exc:
        sync.audit(fake_repo)
    assert "never closed" in str(exc.value), str(exc.value)

    # Control: a closed one is fine, and contributes no step.
    _rewrite(fake_repo, CHAPTER.replace(f"{BLOCK}\n", "<!-- a note -->\n"))
    assert sync.read_chapters(fake_repo)[0].tour == []


@pytest.mark.unit
def test_a_comment_inside_a_fence_is_content(fake_repo: Path):
    """A chapter may show a file verbatim; `03_outline_to_tree.md` does."""
    _rewrite(fake_repo, CHAPTER.replace(
        f"{BLOCK}\n\nBody text.\n",
        "```\n<!-- tour\npage: settings\nnever closed\n```\n",
    ))
    assert sync.read_chapters(fake_repo)[0].tour == []


@pytest.mark.unit
def test_a_block_above_the_first_section_is_refused(fake_repo: Path):
    """A step's link names the section it sits under, so it needs one."""
    _rewrite(fake_repo, (
        "# A chapter\n\n"
        f"{BLOCK}\n\n"
        "## In short\n\nOne sentence.\n\n## Body\n\nBody text.\n"
    ))
    with pytest.raises(sync.ManualError) as exc:
        sync.audit(fake_repo)
    assert "no section for its link" in str(exc.value), str(exc.value)


SECOND_TEXT = (
    "Rebalance siblings shares out a parent's remainder only when you press "
    "it, and never on a top-level subject."
)


@pytest.mark.unit
def test_steps_on_one_anchor_in_one_chapter_are_slides_in_written_order(
    fake_repo: Path,
):
    """Several blocks on one page and anchor are one step shown as slides
    (#682). The runner groups them by anchor, so the artifact must carry them
    in the order they are written: that order IS the slide order."""
    _rewrite(fake_repo, CHAPTER.replace(
        f"{BLOCK}\n", f"{BLOCK}\n\n{BLOCK.replace(GOOD_TEXT, SECOND_TEXT)}\n"
    ))
    sync.audit(fake_repo)  # no ManualError
    artifact = sync.render_tour_artifact(sync.read_chapters(fake_repo))
    first, second = artifact.index(GOOD_TEXT[:40]), artifact.index(SECOND_TEXT[:40])
    assert first < second, "the slides are not in the order they are written"


@pytest.mark.unit
def test_slides_of_one_step_may_not_span_two_chapters(fake_repo: Path):
    """Slides spread over two chapters would be ordered by the chapters'
    filenames, which nobody chose."""
    (fake_repo / sync.MANUAL_DIR / "02_b_chapter.md").write_text(
        CHAPTER.replace("# A chapter", "# B chapter").replace(GOOD_TEXT, SECOND_TEXT),
        encoding="utf-8")
    with pytest.raises(sync.ManualError) as exc:
        sync.audit(fake_repo)
    assert "must be written in one chapter" in str(exc.value), str(exc.value)

    # Control: the same anchor on a DIFFERENT page is fine -- one screen's
    # Import button and another's are not the same thing.
    (fake_repo / sync.MANUAL_DIR / "02_b_chapter.md").write_text(
        CHAPTER.replace("# A chapter", "# B chapter").replace(GOOD_TEXT, SECOND_TEXT)
        .replace("page: tree-editor", "page: settings"),
        encoding="utf-8")
    assert sum(len(c.tour) for c in sync.read_chapters(fake_repo)) == 2
    sync.audit(fake_repo)


@pytest.mark.unit
@pytest.mark.parametrize("forked", ["first", "second"])
def test_no_slide_of_one_step_may_fork(fake_repo: Path, forked: str):
    """A predicate could move one slide off the others' target."""
    plain = ("<!-- tour\npage: dashboard\nanchor: dashboard-create-first-exam\n"
             f"text: {FORK_TEXT}\n-->")
    fork = ("<!-- tour\npage: dashboard\nanchor: dashboard-create-first-exam\n"
            "fork: has-exams\nfork-anchor: exam-card\n"
            f"text: {SECOND_TEXT}\n-->")
    pair = (fork, plain) if forked == "first" else (plain, fork)
    _rewrite(fake_repo, CHAPTER.replace(BLOCK, "\n\n".join(pair)))
    with pytest.raises(sync.ManualError) as exc:
        sync.audit(fake_repo)
    assert "none of them may fork" in str(exc.value), str(exc.value)


@pytest.mark.unit
def test_a_duplicate_heading_gets_a_distinct_link(fake_repo: Path):
    """`uniqueId` appends a suffix, so `slugify` alone is not the id.

    Two sections with the same name in one chapter are legal markdown, and a
    step under the second one has to link to the second one. Getting this
    wrong sends a reader to the wrong half of the chapter, silently.
    """
    _rewrite(fake_repo, (
        "# A chapter\n\n## In short\n\nOne sentence.\n\n"
        "## Body\n\nFirst.\n\n"
        f"## Body\n\n{BLOCK}\n\nSecond.\n"
    ))
    step = sync.read_chapters(fake_repo)[0].tour[0]
    assert step["link"] == "help_a_chapter.html#body-2", step["link"]


# --------------------------------------------------------------------------- #
# The real tree
# --------------------------------------------------------------------------- #

@pytest.mark.unit
def test_the_committed_artifact_is_the_chapters():
    """Standing guard, naming this artifact rather than the set of them."""
    problems = sync.audit(PROJECT_ROOT)
    assert str(sync.TOUR_ARTIFACT) not in problems, (
        "src/web/js/tour_steps.js has drifted from docs/manual/. Run "
        "`python scripts/check_manual_sync.py --write`:\n"
        + problems.get(str(sync.TOUR_ARTIFACT), "")
    )


@pytest.mark.unit
def test_every_tour_page_is_a_route_the_harness_knows():
    """`TOUR_PAGES` is restated in the gate because every ``scripts/`` gate is
    stdlib-only. This is what keeps the restatement honest.

    A page name that is not a route is a name no scenario can navigate to, so
    the tour and its tests would disagree about what a page is called.
    """
    import sys
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from wimi_test.routes import ROUTES
    finally:
        sys.path.pop(0)
    unknown = [page for page in sync.TOUR_PAGES if page not in ROUTES]
    assert not unknown, (
        f"{unknown} are in TOUR_PAGES but are not route names in "
        f"wimi_test/routes.py, whose names are {sorted(ROUTES)}"
    )


@pytest.mark.unit
def test_every_step_links_a_page_that_exists():
    """A dead deep link is `PAGE_GATE.md`'s sample-selector trap again."""
    missing = []
    for step in _steps():
        target = step["link"].split("#", 1)[0]
        if not (WEB_HTML / target).is_file():
            missing.append((step["chapter"], step["link"]))
        if not (WEB_HTML / f"help_{step['chapter']}.html").is_file():
            missing.append((step["chapter"], "chapter page"))
    assert not missing, f"tour steps naming pages that do not exist: {missing}"


@pytest.mark.unit
def test_every_step_names_the_chapter_it_is_written_in():
    """The derived half is derived, so this cannot be got wrong by hand -- and
    that is the claim worth asserting, because it is why the other fields can
    be trusted."""
    for chapter in sync.read_chapters(PROJECT_ROOT):
        for step in chapter.tour:
            assert step["chapter"] == chapter.slug
            assert step["chapter_title"] == chapter.title
            assert step["link"].startswith(f"help_{chapter.slug}.html#")
            assert step["section"] in chapter.markdown


@pytest.mark.unit
def test_the_artifact_groups_by_page_in_reading_order():
    """#430 scopes a tour per page, so the artifact has to be keyed that way."""
    artifact = _artifact()
    assert list(artifact) == [
        page for page in sync.TOUR_PAGES if page in artifact
    ], "pages are not in TOUR_PAGES order"
    for page, steps in artifact.items():
        assert steps, f"{page!r} is present with no steps"
        for step in steps:
            assert step["page"] == page


@pytest.mark.unit
def test_no_step_teaches_a_rule_on_a_surface_known_to_be_wrong():
    """A guard on the curation, not on the mechanism.

    A tour step is more insistent than a paragraph, so a step on a defective
    surface is worse than silence. Subjects left out of this pass for that
    reason are named here, because an *absence* is what a later sweep
    innocently fills in:

    Also deliberately absent: the wizard's level list (#449), and dictation,
    whose figures in chapter 61 are code reads because `vendor/whisper/` is
    absent from a checkout. The weight quadrant and the activity heatmap
    (#468, #471) were here too; see the lifted bans below.

    **TWO BANS HAVE BEEN LIFTED, and they are recorded rather than deleted
    because the reasoning for a ban outlives the ban.**

    * **#488 is fixed** (2026-10-07): the sibling-weight-total check is gone
      from `validateImportData`, so the import preview no longer prints
      "Sibling weights sum to N%" on correctly transcribed blueprints. A step
      about the preview's weight reporting is now legitimate. Note what the
      honest one would have to say: a *single-tree* file's preview still shows
      no coverage band at all, which chapter 60 states and chapter 03 is wrong
      about (#490).
    * **#483 is fixed** (merged): the Find button's hint now names whichever
      of its two blockers is in force, so a step pointing at it would no
      longer be pointing at a sentence that is wrong in the commoner case.
      The honest step is about the two preconditions, not about the hint.
    * **#484 is fixed**: the duplicate-relation refusal no longer says "Edit
      or remove it", because nothing in WIMI can edit a relation. **The wider
      reason that ban existed still holds** -- the relations panel lives on
      the subject deep dive, which has no tour at all, so there is still no
      page for a relations step to sit on. Lifting the ban does not make a
      step writable; it removes the defect that was a second reason not to.
    * **#447 is closed** and `tree_editor.html:541` now reads *"Leave empty and
      the subject is created at 0%. Rebalance siblings, in the weight panel,
      shares out a parent's remainder when you ask it to."* The owner chose
      (b), the copy, over (a), building the distribution. **So the ban on a
      rebalance step rested on information that is no longer true, and a step
      is worth writing** -- weights are the most counterintuitive part of WIMI
      and "nothing redistributes a weight unless you press Rebalance siblings"
      is exactly a tour-worthy rule. One caveat for whoever writes it:
      `rebalanceSiblings()` refuses on a top-level subject, so an honest step
      has to say roots are typed by hand.
    * **#468 and #471 are closed** (lifted 2026-10-10, #682's analytics pass).
      #468: the quadrant now rolls mistakes up through `_quadrant_rollup` and
      shares them out of every entry in the exam, and 0% subjects are on it
      (`analytics_advanced.py`, `get_subject_exam_weight_analysis`). #471:
      the activity heatmap's day names and month labels parse with
      `LocalDate.parse` (`heatmap_chart.js:147,203`, `goal_widget.js:168`)
      and the page links `local_date.js`. The quadrant step that replaced the
      ban is about what Reduce Focus means, which was the misreading the card
      invites once its figures were right.

    If one of the remaining ones is fixed, the step is worth writing. Until
    then the point is that nobody has to re-derive why it is missing.
    """
    # phrase -> (issue, the page it is forbidden on, or None for every page).
    # #449 is scoped to the wizard on purpose: the tree editor's own Level Type
    # dropdown works, so a future step about THAT is legitimate and must not be
    # blocked by a guard aimed at the wizard's read-only list.
    # "sibling weights" (#488), "rebalance" (#447) and "find related topics"
    # (#483) were here and have been removed, not commented out: those
    # surfaces are fixed, so a guard aimed at them would now forbid a
    # legitimate step. The docstring records why each ban existed and what the
    # honest step would have to say.
    forbidden = {
        "level type": ("#449", "exam-wizard"),
    }
    offenders = []
    for step in _steps():
        haystack = f"{step['anchor']} {step['text']}".lower()
        for phrase, (issue, page) in forbidden.items():
            if phrase in haystack and page in (None, step["page"]):
                offenders.append((issue, phrase, step["page"], step["anchor"]))
    assert not offenders, (
        "a tour step names a surface this pass deliberately skipped; read "
        f"this test's docstring before adding one: {offenders}"
    )


# --------------------------------------------------------------------------- #
# The sweeps are not vacuous
# --------------------------------------------------------------------------- #

@pytest.mark.unit
def test_the_sweep_found_the_steps():
    """A discovery-based check that discovers nothing passes.

    The floors are below the current figures rather than at them, so writing a
    step does not edit this test -- the point is to catch an extractor that
    stopped matching, which would read as "the tour has no steps yet".
    """
    steps = _steps()
    assert len(steps) >= 20, f"only {len(steps)} tour step(s) found"
    pages = {step["page"] for step in steps}
    assert len(pages) >= 6, f"steps on only {sorted(pages)}"
    chapters = {step["chapter"] for step in steps}
    assert len(chapters) >= 10, (
        f"steps come from only {len(chapters)} chapter(s); a short form is a "
        f"compression of a rule, so they should be spread over the manual"
    )


@pytest.mark.unit
def test_every_block_in_the_tree_sits_under_a_heading_and_beside_its_rule():
    """The anti-drift property is proximity, so it is worth asserting.

    A short form is a second copy of a rule by nature. What stops the two
    drifting is that an editor changing the rule sees the short form two lines
    away -- which is only true while the block really is adjacent to the
    heading it compresses.
    """
    far = []
    for path in sorted(MANUAL_DIR.glob("*.md")):
        lines = path.read_text(encoding="utf-8").split("\n")
        for index, line in enumerate(lines):
            if line.strip() != sync.TOUR_OPEN:
                continue
            above = [
                number for number in range(index - 1, -1, -1)
                if re.match(r"^#{2,6} +\S", lines[number])
            ]
            assert above, f"{path.name}:{index + 1} has no heading above it"
            gap = index - above[0]
            if gap > 12:
                far.append((path.name, index + 1, gap))
    assert not far, (
        "tour blocks sitting well below their heading, where an editor "
        f"changing the rule would not see them: {far}"
    )


# --------------------------------------------------------------------------- #
# A fork (#620's decision, the contract agreed on #430)
# --------------------------------------------------------------------------- #

FORK_TEXT = (
    "The order is a profile, then an exam, then at least one subject, and "
    "each screen enforces the one before it rather than guessing."
)


def _dashboard_chapter(*lines: str) -> str:
    return CHAPTER.replace(BLOCK, "<!-- tour\n" + "".join(
        f"{line}\n" for line in lines) + "-->\n")


@pytest.mark.unit
def test_a_fork_is_carried_into_the_step(fake_repo: Path):
    _rewrite(fake_repo, _dashboard_chapter(
        "page: dashboard", "anchor: dashboard-create-first-exam",
        "fork: has-exams", "fork-anchor: exam-card", f"text: {FORK_TEXT}"))
    step = sync.read_chapters(fake_repo)[0].tour[0]
    assert step["anchor"] == "dashboard-create-first-exam"
    assert step["fork"] == "has-exams"
    assert step["fork_anchor"] == "exam-card"


@pytest.mark.unit
def test_a_step_without_a_fork_gains_no_keys(fake_repo: Path):
    """The byte-identical half: the real tree generates exactly what it did
    before the keys existed, which the gate asserts on every run."""
    step = sync.read_chapters(fake_repo)[0].tour[0]
    assert "fork" not in step and "fork_anchor" not in step


@pytest.mark.unit
@pytest.mark.parametrize("lines, needle", [
    (("page: dashboard", "anchor: dashboard-create-first-exam",
      "fork: has-exams", f"text: {FORK_TEXT}"), "'fork-anchor' is missing"),
    (("page: dashboard", "anchor: dashboard-create-first-exam",
      "fork-anchor: exam-card", f"text: {FORK_TEXT}"), "'fork' is missing"),
    (("page: dashboard", "anchor: dashboard-create-first-exam",
      "fork: has-exam", "fork-anchor: exam-card", f"text: {FORK_TEXT}"),
     "not a fork predicate"),
    (("page: tree-editor", "anchor: tree-row-weight",
      "fork: has-exams", "fork-anchor: exam-card", f"text: {FORK_TEXT}"),
     "not a fork predicate on the tree-editor page"),
    (("page: dashboard", "anchor: the Create Your First Exam button",
      "fork: has-exams", "fork-anchor: exam-card", f"text: {FORK_TEXT}"),
     "not an anchor identifier"),
    (("page: dashboard", "anchor: dashboard-create-first-exam",
      "fork: has-exams", "fork-anchor: the exam cards", f"text: {FORK_TEXT}"),
     "not an anchor identifier"),
], ids=["no-fork-anchor", "no-fork", "unknown-predicate", "wrong-page",
        "prose-anchor", "prose-fork-anchor"])
def test_a_malformed_fork_is_refused_with_a_sentence(fake_repo, lines, needle):
    _rewrite(fake_repo, _dashboard_chapter(*lines))
    with pytest.raises(sync.ManualError) as exc:
        sync.audit(fake_repo)
    assert needle in str(exc.value), str(exc.value)


@pytest.mark.unit
def test_every_fork_predicate_names_a_tour_page():
    assert set(sync.TOUR_FORKS.values()) <= set(sync.TOUR_PAGES)


# --------------------------------------------------------------------------- #
# Orientation steps (#682)
# --------------------------------------------------------------------------- #
#
# The owner's decision 1: manual-generated steps keep teaching RULES, and a
# second, tour-only kind covers ORIENTATION -- naming a control rather than
# teaching a rule about it. The kind is derived from which source the block
# sits in, so there is no `kind:` field to omit or mistype.


def _orient(repo: Path, body: str) -> None:
    """Write ``docs/manual/tour/orientation.md`` with one block."""
    directory = repo / sync.ORIENTATION_SOURCE.parent
    directory.mkdir(parents=True, exist_ok=True)
    (repo / sync.ORIENTATION_SOURCE).write_text(
        "# Orientation\n\n## a page\n\n<!-- tour\n" + body + "\n-->\n",
        encoding="utf-8",
    )


@pytest.mark.unit
def test_no_orientation_file_is_the_normal_state(fake_repo: Path):
    """The file is optional, and absent means no orientation steps.

    This is the state the feature landed in, so it is the case that must not
    need the file to exist.
    """
    assert not (fake_repo / sync.ORIENTATION_SOURCE).exists()
    assert sync.read_orientation(fake_repo) == []
    assert sync.audit(fake_repo) == {}


@pytest.mark.unit
def test_an_orientation_block_carries_only_its_three_authored_fields(
    fake_repo: Path,
):
    """No section, link, chapter or chapter_title -- there is nothing to
    derive them from, which is the whole difference between the two kinds."""
    _orient(fake_repo, "page: dashboard\n"
                       "anchor: exam-card-browse\n"
                       "text: Opens the entry browser already filtered to "
                       "this exam.")
    steps = sync.read_orientation(fake_repo)
    assert steps == [{
        "page": "dashboard",
        "anchor": "exam-card-browse",
        "text": "Opens the entry browser already filtered to this exam.",
    }]
    # Stated as a set so a NEW derived key added later fails here rather than
    # reaching the artifact unnoticed.
    assert set(steps[0]) == {"page", "anchor", "text"}


@pytest.mark.unit
def test_an_orientation_step_reaches_the_artifact(fake_repo: Path):
    _orient(fake_repo, "page: dashboard\n"
                       "anchor: exam-card-browse\n"
                       "text: Opens the entry browser already filtered to "
                       "this exam.")
    sync.write(fake_repo)
    artifact = json.loads(
        re.search(
            r"=\s*(\{.*\});",
            (fake_repo / sync.TOUR_ARTIFACT).read_text(encoding="utf-8"),
            re.S,
        ).group(1)
    )
    anchors = [s["anchor"] for s in artifact["dashboard"]]
    assert "exam-card-browse" in anchors
    step = next(s for s in artifact["dashboard"]
                if s["anchor"] == "exam-card-browse")
    assert "link" not in step, (
        "an orientation step has no chapter to link to; tour.js draws Read "
        "more only `if (step.link)`")


@pytest.mark.unit
def test_a_label_shorter_than_a_rule_is_accepted(fake_repo: Path):
    """THE POINT OF ORIENTATION_TEXT_MIN.

    The rule-step floor is 60 characters and its own error says why: "under
    the floor it is a label rather than a rule". An orientation step IS a
    label, so inheriting that floor would refuse exactly what decision 1
    asks for. This text is 32 characters and correct.
    """
    short = "Narrow the list to a date range."
    assert len(short) < sync.TOUR_TEXT_MIN
    _orient(fake_repo, f"page: entry-browser\nanchor: browser-filter-date\n"
                       f"text: {short}")
    assert sync.read_orientation(fake_repo)[0]["text"] == short


@pytest.mark.unit
def test_an_unwritten_text_is_still_refused(fake_repo: Path):
    """What survives of the floor's purpose: catch a block nobody finished."""
    _orient(fake_repo, "page: dashboard\nanchor: exam-card-browse\ntext: tbd")
    with pytest.raises(sync.ManualError) as exc:
        sync.read_orientation(fake_repo)
    assert "never got written" in str(exc.value)


@pytest.mark.unit
def test_an_orientation_block_may_not_take_a_fork(fake_repo: Path):
    """A fork pairs an anchor with a registered runtime predicate, which is a
    chapter-level idea. Refused rather than emitted untested."""
    _orient(fake_repo, "page: dashboard\n"
                       "anchor: exam-card-browse\n"
                       "fork: has-exams\n"
                       "fork-anchor: exam-card\n"
                       "text: Opens the entry browser already filtered to "
                       "this exam.")
    with pytest.raises(sync.ManualError) as exc:
        sync.read_orientation(fake_repo)
    assert "a fork belongs to a chapter step" in str(exc.value)


@pytest.mark.unit
def test_an_orientation_block_may_not_claim_an_anchor_a_chapter_owns(
    fake_repo: Path,
):
    """If a control has a rule, the rule owns it.

    The chapter's text is generated and cannot drift from the manual; an
    orientation block on the same anchor is either repeating it or
    contradicting it, and nothing can tell those apart mechanically. The
    error names the chapter, because the fix is usually to improve the rule
    step's wording rather than to drop the orientation block.
    """
    chapter_anchor = _steps_in(fake_repo)[0]["anchor"]
    _orient(fake_repo, f"page: {_steps_in(fake_repo)[0]['page']}\n"
                       f"anchor: {chapter_anchor}\n"
                       f"text: Naming the same control a second time, which "
                       f"is what this must refuse.")
    with pytest.raises(sync.ManualError) as exc:
        sync.audit(fake_repo)
    message = str(exc.value)
    assert chapter_anchor in message
    assert "01_a_chapter.md" in message, (
        f"the error must name the chapter that owns it: {message}")


def _steps_in(repo: Path) -> list[dict]:
    chapters = sync.read_chapters(repo)
    return [step for chapter in chapters for step in chapter.tour]


@pytest.mark.unit
def test_the_orientation_file_is_not_read_as_a_chapter(fake_repo: Path):
    """A SIBLING of the chapters would be refused by CHAPTER_NAME, which is
    why the source is a subdirectory.

    `read_chapters` takes every ``.md`` in ``docs/manual`` with a
    non-recursive ``iterdir()``, so a subdirectory is invisible to it. This
    asserts that property directly: with the file present, the chapter count
    is unchanged and no page is generated for it.
    """
    before = len(sync.read_chapters(fake_repo))
    _orient(fake_repo, "page: dashboard\n"
                       "anchor: exam-card-browse\n"
                       "text: Opens the entry browser already filtered to "
                       "this exam.")
    assert len(sync.read_chapters(fake_repo)) == before
    sync.write(fake_repo)
    assert not (fake_repo / sync.HTML_DIR / "help_orientation.html").exists()
