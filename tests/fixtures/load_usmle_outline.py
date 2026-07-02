"""Parser for the USMLE Step 1 content outline fixture.

Extracts named topics with their parent-section paths from
``usmle_step1_outline.txt`` so polyhierarchy tests can verify rollups against
real multi-parent topics (DVT, hypertension, sepsis, etc.) called out in
``docs/planning/POLYHIERARCHY_MIGRATION.md``.

Public entry point: :func:`load_usmle_outline`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Canonical top-level systems from the TOC (lines 44-78 of the source file).
# These act as anchors when we walk the body, since the body sometimes splits a
# system name across two lines (e.g. "Female and Transgender Reproductive" /
# "System & Breast"). We keep the spelling as it appears in the body of the
# outline, not the TOC capitalization quirks.
_SYSTEMS: tuple[str, ...] = (
    "Human Development",
    "Immune System",
    "Blood & Lymphoreticular System",
    "Behavioral Health",
    "Nervous System & Special Senses",
    "Skin & Subcutaneous Tissue",
    "Musculoskeletal System",
    "Cardiovascular System",
    "Respiratory System",
    "Gastrointestinal System",
    "Renal & Urinary System",
    "Pregnancy, Childbirth, & the Puerperium",
    "Female and Transgender Reproductive System & Breast",
    "Male and Transgender Reproductive System",
    "Endocrine System",
    "Multisystem Processes & Disorders",
    "Biostatistics, Epidemiology/Population Health, & Interpretation of the Medical Literature",
    "Social Sciences",
)

# Marker characters used in the outline. The PDF extraction loses unicode
# bullets so they show up as a single replacement-style character in latin-1.
# We accept several plausible byte representations.
_BULLET_CATEGORY = ("�", "•", "*")  # the "�" first-level bullet
_BULLET_SUB = "o"  # second-level bullet, plain ASCII letter o

# Boilerplate lines we ignore wholesale.
_BOILERPLATE_PATTERNS = (
    re.compile(r"^Public\s*$"),
    re.compile(r"^For Public Release:.*$"),
    re.compile(r"^Copyright .*$", re.IGNORECASE),
    re.compile(r"^All rights reserved.*$", re.IGNORECASE),
    re.compile(r"^USMLE.*Content Outline\s*$"),
    re.compile(r"^Table of Contents\s*$"),
)


@dataclass(frozen=True)
class OutlineTopic:
    """A single named topic with its hierarchical parent path.

    A topic's identity for multi-parent detection is its normalized name
    (case-insensitive, leading bullets/numbers stripped). The same name
    appearing under two different parent paths produces two ``OutlineTopic``
    rows but a single key in :attr:`USMLEOutline.parent_index`.
    """

    name: str
    parent_path: tuple[str, ...]
    line_number: int


@dataclass(frozen=True)
class USMLEOutline:
    """Parsed view of the outline.

    Attributes:
        topics: Every named topic in document order.
        parent_index: Map from normalized topic name to the list of distinct
            parent paths (joined with ``" > "``) where it appears.
        multi_parent_topics: Normalized topic names that appear under
            two or more distinct parent paths.
    """

    topics: list[OutlineTopic]
    parent_index: dict[str, list[str]] = field(default_factory=dict)
    multi_parent_topics: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_boilerplate(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    for pat in _BOILERPLATE_PATTERNS:
        if pat.match(stripped):
            return True
    # TOC lines look like: "Cardiovascular System         17". A flush-left
    # line that ends with whitespace + digits is a TOC entry, not a section.
    if re.match(r"^[A-Z].*\s+\d+\s*$", stripped):
        return True
    return False


def _leading_spaces(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _starts_with_category_bullet(stripped: str) -> bool:
    return any(stripped.startswith(b) for b in _BULLET_CATEGORY)


def _starts_with_sub_bullet(stripped: str) -> bool:
    # Sub-bullets render as a lowercase 'o' followed by whitespace.
    return bool(re.match(r"^o\s+\S", stripped))


def _strip_bullet(stripped: str) -> str:
    """Remove leading bullet characters and surrounding whitespace."""
    for b in _BULLET_CATEGORY:
        if stripped.startswith(b):
            return stripped[len(b) :].lstrip()
    if stripped.startswith("o "):
        return stripped[2:].lstrip()
    return stripped


# Parentheticals like "(eg, foo, bar)" or "(Bacillus anthracis)" qualify the
# term but are not themselves separate topics for our purposes. We strip them
# before splitting on semicolons so that a topic like
# "deep venous thrombosis, venous thromboembolism" stays intact.
_PAREN_RE = re.compile(r"\([^()]*\)")


def _normalize_name(raw: str) -> str:
    """Lower-case, trim, strip outer punctuation. Used as topic identity."""
    s = raw.strip()
    # Remove leading list markers ("- ", "1) ", "a. ", etc.) that sometimes
    # leak into list items.
    s = re.sub(r"^[\-\*•]+\s*", "", s)
    s = re.sub(r"^\d+[\.\)]\s*", "", s)
    s = re.sub(r"^[a-z][\.\)]\s+", "", s)
    s = s.strip().strip(",.;:")
    return s.lower()


def _split_topics(text: str) -> list[str]:
    """Split a content blob into individual topic names.

    The outline lists topics primarily as semicolon-separated phrases. Within
    a single phrase, comma-separated tokens are *often* synonyms or named
    variants of the same disease (e.g.
    ``"deep venous thrombosis, venous thromboembolism"``,
    ``"leukemia, acute (ALL, AML)"``,
    ``"shock, cardiogenic, hypovolemic, neurogenic, septic, sepsis, bacteremia"``).
    We yield BOTH the full semicolon-chunk AND each comma-separated token as
    aliases so polyhierarchy tests can locate the canonical short name (e.g.
    "sepsis", "leukemia") without doing fuzzy matching.

    Parentheticals are removed before splitting because they often contain
    semicolons (e.g. ``"(eg, A; B)"``) that would otherwise produce spurious
    splits.
    """
    cleaned = _PAREN_RE.sub("", text)
    while True:
        next_cleaned = _PAREN_RE.sub("", cleaned)
        if next_cleaned == cleaned:
            break
        cleaned = next_cleaned

    out: list[str] = []
    seen: set[str] = set()
    for chunk in (p.strip() for p in cleaned.split(";")):
        if not chunk:
            continue
        # Always include the full chunk as a topic.
        if chunk.lower() not in seen:
            seen.add(chunk.lower())
            out.append(chunk)
        # Also include each comma-separated token as an alias, but only if
        # it's a plausible short topic name (1-4 words, no embedded
        # semicolons or stray markers). This catches synonyms like "DVT" and
        # short canonical names like "sepsis" / "leukemia" without polluting
        # the index with descriptor fragments like "secondary malignant
        # neoplasm of bone".
        if "," in chunk:
            for tok in (t.strip() for t in chunk.split(",")):
                if not tok:
                    continue
                # Skip tokens that look like prepositional fragments (start
                # with "and ", "or ", "including ", etc.) - these are clearly
                # not standalone topic names.
                low = tok.lower()
                if low.startswith(("and ", "or ", "including ", "with ", "without ")):
                    continue
                word_count = len(tok.split())
                if not (1 <= word_count <= 4):
                    continue
                if low not in seen:
                    seen.add(low)
                    out.append(tok)
    return out


def _looks_like_section_header(line: str) -> bool:
    """A section header is a flush-left, non-bulleted, non-empty line."""
    if _leading_spaces(line) > 0:
        return False
    stripped = line.strip()
    if not stripped:
        return False
    if _starts_with_category_bullet(stripped):
        return False
    if _starts_with_sub_bullet(stripped):
        return False
    if _is_boilerplate(line):
        return False
    return True


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _default_path() -> Path:
    return Path(__file__).resolve().parent / "usmle_step1_outline.txt"


def load_usmle_outline(path: Path | None = None) -> USMLEOutline:
    """Parse the outline file into structured tuples for test setup.

    If ``path`` is None, default to ``tests/fixtures/usmle_step1_outline.txt``
    relative to this module.
    """
    src = Path(path) if path is not None else _default_path()
    raw = src.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines()

    topics: list[OutlineTopic] = []

    # Walking state: the stack represents the current parent path. Index 0 is
    # the system, index 1 is the section, index 2 is the category bullet,
    # index 3 is the sub-bullet. Continuation lines append to the deepest
    # level's pending content blob, which is flushed when the level changes.
    system: str | None = None
    section: str | None = None
    category: str | None = None
    sub: str | None = None

    # Pending content for the deepest open level: (depth, text, line_no).
    # depth: 0=section, 2=category, 3=sub.
    pending_depth: int | None = None
    pending_text: str = ""
    pending_line: int = 0

    # When processing a section header, lookahead may be needed because the
    # body sometimes splits the system name across two lines.
    i = 0
    n = len(lines)

    def _flush() -> None:
        nonlocal pending_depth, pending_text, pending_line
        if pending_depth is None or not pending_text.strip():
            pending_depth = None
            pending_text = ""
            return
        # Build parent path based on depth at which the content lives.
        if pending_depth == 0:
            # Content directly under a section (no � bullet) — common in the
            # outline. Parent path is system -> section.
            parent_path: list[str] = []
            if system:
                parent_path.append(system)
            if section:
                parent_path.append(section)
        elif pending_depth == 2:
            parent_path = []
            if system:
                parent_path.append(system)
            if section:
                parent_path.append(section)
            if category:
                parent_path.append(category)
        elif pending_depth == 3:
            parent_path = []
            if system:
                parent_path.append(system)
            if section:
                parent_path.append(section)
            if category:
                parent_path.append(category)
            if sub:
                parent_path.append(sub)
        else:
            parent_path = []

        for raw_topic in _split_topics(pending_text):
            name = _normalize_name(raw_topic)
            if not name or len(name) < 2:
                continue
            # Skip purely numeric or gibberish fragments.
            if re.fullmatch(r"[\d\s\-\.,/]+", name):
                continue
            topics.append(
                OutlineTopic(
                    name=name,
                    parent_path=tuple(parent_path),
                    line_number=pending_line,
                )
            )
        pending_depth = None
        pending_text = ""

    while i < n:
        line = lines[i]
        line_no = i + 1
        stripped = line.strip()

        if _is_boilerplate(line):
            # Boilerplate clears nothing; we keep the current state because
            # "For Public Release..." / "Public" lines simply mark page
            # boundaries inside an ongoing section.
            i += 1
            continue

        indent = _leading_spaces(line)

        # System header: match against the canonical list, possibly across
        # two lines. We only attempt this when we're at column 0.
        if indent == 0:
            # Try a one-line match first.
            matched_system: str | None = None
            for sysname in _SYSTEMS:
                if stripped == sysname:
                    matched_system = sysname
                    break
            if matched_system is None:
                # Try a two-line match (rare; happens for the long Female /
                # Transgender system header in the body).
                if i + 1 < n:
                    combined = (stripped + " " + lines[i + 1].strip()).strip()
                    for sysname in _SYSTEMS:
                        if combined == sysname:
                            matched_system = sysname
                            i += 1  # consume the second line
                            break
            if matched_system is not None:
                _flush()
                system = matched_system
                section = None
                category = None
                sub = None
                i += 1
                continue

        # Section header (flush left, not a system, not boilerplate, not a
        # bullet line).
        if _looks_like_section_header(line):
            _flush()
            # Some sections span two flush-left lines (e.g. "Pneumoconiosis/
            # fibrosing/restrictive pulmonary disorders/interstitial lung
            # disease" sometimes wraps). For our purposes a single-line take
            # is correct ~99% of the time, and over-eager merging would risk
            # eating the next section's heading. Leave as-is.
            section = stripped
            category = None
            sub = None

            # Treat the section heading itself as a named topic so that
            # outline structures like "Hypertension" (a section under
            # Cardiovascular System) participate in the parent_index. This
            # is what makes "hypertension" multi-parent: it appears both as
            # a section heading under Cardiovascular AND as a leaf under
            # Pregnancy/Systemic disorders.
            if system:
                topics.append(
                    OutlineTopic(
                        name=_normalize_name(stripped),
                        parent_path=(system,),
                        line_number=line_no,
                    )
                )
            i += 1
            continue

        # Category bullet `�`
        if _starts_with_category_bullet(stripped):
            _flush()
            content = _strip_bullet(stripped)
            # The bullet itself plus its inline content is the "category".
            # However, many bullets contain the actual topic listing on the
            # same line, so we treat the whole thing as both the category
            # name AND the leaf-content blob. We resolve this by checking
            # whether the bullet line ends with a colon-style heading or
            # whether there's a sub-bullet on the next non-blank line.
            #
            # Heuristic: peek ahead. If the next non-blank, non-boilerplate
            # line begins with a sub-bullet "o", treat this line as a pure
            # category header. Otherwise treat the content as topic listing
            # under the current section.
            j = i + 1
            next_is_sub = False
            while j < n:
                lj = lines[j]
                if _is_boilerplate(lj):
                    j += 1
                    continue
                ls = lj.strip()
                if not ls:
                    j += 1
                    continue
                # If next non-blank line is a continuation of this bullet
                # (indented further but no marker), it's still part of this
                # bullet's content, not a sub-bullet.
                if _starts_with_sub_bullet(ls):
                    next_is_sub = True
                break

            if next_is_sub:
                category = content
                sub = None
            else:
                # The bullet line carries the topic listing; treat as a leaf
                # blob at depth=2 (category-level) with no separate category
                # name since the content IS the topics.
                category = None
                sub = None
                pending_depth = 0  # parents are system -> section
                pending_text = content
                pending_line = line_no
            i += 1
            continue

        # Sub bullet `o`
        if _starts_with_sub_bullet(stripped):
            _flush()
            content = _strip_bullet(stripped)
            # Heuristic: a sub-bullet line carries either (a) a heading whose
            # actual leaf topics live on deeper unmarked continuation lines, or
            # (b) the topic listing directly. To distinguish, check whether
            # the next non-blank line is indented more deeply than this one,
            # AND is itself unmarked. If so, treat this as a heading; the
            # leaf blob will accumulate from continuations.
            j = i + 1
            deeper_unmarked = False
            this_indent = indent
            while j < n:
                lj = lines[j]
                if _is_boilerplate(lj):
                    j += 1
                    continue
                ls = lj.strip()
                if not ls:
                    j += 1
                    continue
                lj_indent = _leading_spaces(lj)
                if (
                    lj_indent > this_indent
                    and not _starts_with_category_bullet(ls)
                    and not _starts_with_sub_bullet(ls)
                ):
                    # Continuation could be a topic blob OR a deeper heading.
                    # If the line after THAT is unmarked at even deeper indent
                    # (eg "bacterial" -> indented list of bacterial diseases),
                    # this sub-bullet is a heading.
                    k = j + 1
                    while k < n and (_is_boilerplate(lines[k]) or not lines[k].strip()):
                        k += 1
                    if k < n:
                        lk = lines[k]
                        ls_k = lk.strip()
                        lk_indent = _leading_spaces(lk)
                        if (
                            lk_indent > lj_indent
                            and not _starts_with_category_bullet(ls_k)
                            and not _starts_with_sub_bullet(ls_k)
                        ):
                            deeper_unmarked = True
                break

            if deeper_unmarked:
                # Pure heading with deeper content lines under it.
                sub = content
                pending_depth = None
                pending_text = ""
            else:
                # The bullet line carries the leaf topic blob. Use the FIRST
                # semicolon-separated phrase (or the whole content if none)
                # as the heading-style sub-name for the parent path so the
                # path stays short and human-readable. The full content is
                # what we split into individual topics.
                first_phrase = content.split(";", 1)[0].strip()
                # Trim parentheticals from the phrase used as the path label.
                phrase_label = _PAREN_RE.sub("", first_phrase).strip(" ,;:")
                # Cap path-label length to keep paths readable.
                if len(phrase_label) > 60:
                    phrase_label = phrase_label[:60].rstrip(" ,;") + "..."
                sub = phrase_label or None
                # IMPORTANT: when the sub-bullet IS the leaf blob, the parent
                # path of the resulting topics should be system->section->
                # category, NOT include the leaf blob itself as a level.
                # Set pending_depth=2 so _flush uses category-level parents.
                pending_depth = 2
                pending_text = content
                pending_line = line_no
                # Also reset sub so subsequent flushes don't mistakenly use it
                # as a parent for unrelated content.
                sub = None
            i += 1
            continue

        # Continuation line (indented, no marker). Append to pending blob.
        if pending_depth is not None:
            pending_text += " " + stripped
            i += 1
            continue

        # Otherwise — indented unmarked line that follows a sub-bullet which
        # we marked as a heading (deeper_unmarked branch). Open a depth-3
        # blob now and accumulate.
        if sub is not None:
            pending_depth = 3
            pending_text = stripped
            pending_line = line_no
            i += 1
            continue

        # Skipped: unhandled line. Just advance.
        i += 1

    # Flush trailing blob.
    _flush()

    # Build parent_index: name -> list of distinct parent paths (joined as " > ").
    parent_index: dict[str, list[str]] = {}
    for t in topics:
        path_str = " > ".join(t.parent_path)
        bucket = parent_index.setdefault(t.name, [])
        if path_str not in bucket:
            bucket.append(path_str)

    multi_parent_topics = sorted(name for name, paths in parent_index.items() if len(paths) >= 2)

    return USMLEOutline(
        topics=topics,
        parent_index=parent_index,
        multi_parent_topics=multi_parent_topics,
    )


__all__ = ["OutlineTopic", "USMLEOutline", "load_usmle_outline"]
