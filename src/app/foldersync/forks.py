"""
Telling two copies of one profile apart, so the student can choose (#124).

**The report is the feature.** A dialog that says "there is a conflict, choose
one" without numbers is a coin flip with extra steps. The judgement a student
is actually making is *"is this a month of independent work, or a stale copy
from before I switched machines?"* — and only counts and dates answer that.
Reassurance does not.

#124 names four figures per side, and this module produces them:

* **entry count**
* **date range** of entries
* **device name, and when it last wrote**
* **subjects that exist only on that side**

Where the numbers come from
---------------------------
The first three come from the manifests, which ``build_profile_archive``
computes **from the snapshot it ships** — so they cannot drift from the bytes
they describe, and #124 says to use them rather than recompute from the live
database.

The fourth cannot: "only on that side" is a *comparison*, and no manifest can
hold the answer on its own. Carrying every subject name in a manifest was
considered and rejected — a real profile has 2,575 of them, manifests are read
on every status check, and #147 is a fresh reminder of what happens when a
display path quietly carries a payload. So the subject diff opens both staged
archives and reads their ``subject_nodes`` directly.

That means **building a full report downloads both sides**, which on a
streaming provider is real cost. It is the right trade here and the opposite
of #147's: a status check happens constantly and must be free, while resolving
a fork is a deliberate act the student initiated, and you cannot honestly
choose between two profiles without reading them. :func:`summarise_side` gives
the cheap manifest-only half for callers that only need to *mention* a fork.

Nothing here resolves anything. Export-before-anything and the three-way
choice are the rest of #124; this is what makes the choice answerable.
"""
from __future__ import annotations

import sqlite3
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .manifest import SyncManifest, describe_for_user

#: How many subject names to name outright before falling back to "and N more".
#: A student can hold a handful in mind; a wall of them is the same as no
#: information. The full lists stay on the report for a UI that wants them.
NAMED_SUBJECT_LIMIT = 8


@dataclass
class SideSummary:
    """One side of a fork, as the student sees it."""

    generation: int
    parent_generation: int
    device_id: str
    device_name: str
    created_at: str
    bytes: int
    #: How this side is ADDRESSED. Unique by construction; a generation
    #: number is not, because both sides of a fork usually share one.
    blob_name: str = ""
    #: How lineage names this side (#148). A pending resolution records
    #: digests, so the panel matches sides against it by this.
    sha256: str = ""
    #: This device's copy. Decided by the service from the device's base,
    #: not by the page from a device name -- names are not unique.
    is_local: bool = False

    entries: Optional[int] = None
    sessions: Optional[int] = None
    exam_contexts: Optional[int] = None
    subjects: Optional[int] = None

    #: When the questions were actually sat. What a student remembers.
    encountered_first: Optional[str] = None
    encountered_last: Optional[str] = None
    #: When the rows were written. What says which copy was in use recently.
    logged_first: Optional[str] = None
    logged_last: Optional[str] = None

    #: Filled only by :func:`build_fork_report`, which reads both archives.
    subjects_only_here: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "generation": self.generation,
            "parent_generation": self.parent_generation,
            "device_id": self.device_id,
            "device_name": self.device_name,
            "created_at": self.created_at,
            "bytes": self.bytes,
            "blob_name": self.blob_name,
            "sha256": self.sha256,
            "is_local": self.is_local,
            "entries": self.entries,
            "sessions": self.sessions,
            "exam_contexts": self.exam_contexts,
            "subjects": self.subjects,
            "encountered_first": self.encountered_first,
            "encountered_last": self.encountered_last,
            "logged_first": self.logged_first,
            "logged_last": self.logged_last,
            "subjects_only_here": list(self.subjects_only_here),
            "subjects_only_here_count": len(self.subjects_only_here),
        }
        data["subjects_only_here_named"] = self.subjects_only_here[:NAMED_SUBJECT_LIMIT]
        return data


@dataclass
class ForkReport:
    """Two sides of one fork, with everything needed to choose between them."""

    parent_generation: int
    sides: List[SideSummary]
    #: True when the subject diff ran. False means the manifest-only report:
    #: every ``subjects_only_here`` is empty because nobody looked, **not**
    #: because the sides agree. A UI must not render the difference as "none".
    compared: bool = False
    notes: List[str] = field(default_factory=list)
    #: The two copies share no history -- never synced before. Same three
    #: choices, different framing (#124).
    first_connect: bool = False
    #: This device's copy was set aside by a choice made on another device.
    set_aside: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parent_generation": self.parent_generation,
            "first_connect": self.first_connect,
            "set_aside": self.set_aside,
            "compared": self.compared,
            "sides": [s.to_dict() for s in self.sides],
            "notes": list(self.notes),
        }


def summarise_side(manifest: SyncManifest) -> SideSummary:
    """The cheap half: everything one manifest knows about its own side.

    No archive is read, so nothing is downloaded. Use this to *mention* a
    fork; use :func:`build_fork_report` when the student is choosing.
    """
    described = describe_for_user(manifest)
    # `stats` carries everything the snapshot measured; `row_counts` is the
    # integer subset and is all an older manifest has. Merge so a manifest
    # written before #124 still yields its counts, with the dates simply
    # absent rather than the whole summary failing.
    stats = dict(getattr(manifest, "row_counts", None) or {})
    stats.update(getattr(manifest, "stats", None) or {})
    return SideSummary(
        generation=described["generation"],
        parent_generation=described["parent_generation"],
        device_id=described["device_id"],
        device_name=described["device_name"],
        created_at=described["created_at"],
        bytes=described["bytes"],
        blob_name=getattr(manifest, "blob_name", "") or "",
        sha256=getattr(manifest, "sha256", "") or "",
        entries=stats.get("entries"),
        sessions=stats.get("sessions"),
        exam_contexts=stats.get("exam_contexts"),
        subjects=stats.get("subjects"),
        encountered_first=stats.get("encountered_first"),
        encountered_last=stats.get("encountered_last"),
        logged_first=stats.get("logged_first"),
        logged_last=stats.get("logged_last"),
    )


def _subject_names(archive_path: str | Path) -> Set[str]:
    """Active subject names in a staged archive, as ``level|name``.

    Qualified by level because two different subjects may share a name at
    different levels, and an unqualified diff would silently call them the
    same thing. Not qualified by ``import_id``: that is only set for imported
    trees, and a hand-built tree must still diff.

    An archive that cannot be read returns an empty set and the caller says
    the comparison did not run. It must never return "no differences".
    """
    import tempfile

    from app.profile_archive import DB_MEMBER

    work = Path(tempfile.mkdtemp(prefix="forkdiff-"))
    try:
        with zipfile.ZipFile(str(archive_path)) as zf:
            zf.extract(DB_MEMBER, str(work))
        conn = sqlite3.connect(str(work / DB_MEMBER))
        try:
            rows = conn.execute(
                "SELECT COALESCE(level_type, ''), name FROM subject_nodes "
                "WHERE status = 'active'"
            ).fetchall()
        finally:
            conn.close()
        return {f"{lvl}|{name}" for lvl, name in rows}
    finally:
        import shutil

        shutil.rmtree(str(work), ignore_errors=True)


def _pretty(qualified: Sequence[str]) -> List[str]:
    """``Topic|Hypertension`` back to ``Hypertension (Topic)`` for display."""
    out: List[str] = []
    for item in sorted(qualified, key=lambda s: s.split("|", 1)[-1].lower()):
        level, _, name = item.partition("|")
        out.append(f"{name} ({level})" if level else name)
    return out


#: Figures a student can act on, in the order a report should mention them.
#: Entry count first because it is what everyone looks at; the date range
#: next because it is what separates "a month of work" from "a stale copy"
#: when the counts happen to match.
_COMPARED_FIELDS = (
    ("entries", "entries"),
    ("sessions", "sessions"),
    ("exam_contexts", "exam contexts"),
    ("subjects", "subjects"),
    ("encountered_last", "most recent question sat"),
    ("logged_last", "most recently added to"),
)


def figures_that_differ(a: SideSummary, b: SideSummary) -> List[Dict[str, Any]]:
    """Which recorded figures actually differ: ``[{field, label, a, b}]``.

    Only fields where **both** sides recorded a value are compared: a
    missing figure on an older manifest is "not recorded", not "different",
    and reporting it as a difference would invent one.

    One definition for every comparison a student is shown -- the fork
    report's two sides, and #151's "this computer against the copy it last
    synced" -- so the two cannot disagree about what counts as different.
    """
    out: List[Dict[str, Any]] = []
    for attr, label in _COMPARED_FIELDS:
        left, right = getattr(a, attr, None), getattr(b, attr, None)
        if left is None or right is None or left == right:
            continue
        out.append({"field": attr, "label": label, "a": left, "b": right})
    return out


def _figures_that_differ(a: SideSummary, b: SideSummary) -> List[str]:
    """:func:`figures_that_differ`, as phrases a student reads."""
    return [f"{d['label']} ({d['a']} vs {d['b']})" for d in figures_that_differ(a, b)]


def build_fork_report(
    parent_generation: int,
    sides: Sequence[Tuple[SyncManifest, Optional[str]]],
    *,
    first_connect: bool = False,
    set_aside: bool = False,
    local_blob_name: Optional[str] = None,
) -> ForkReport:
    """The full report: manifest figures, plus the subject diff.

    Args:
        parent_generation: the ancestor both sides built on.
        sides: ``(manifest, staged_archive_path)`` per side. A ``None`` path
            means that side could not be staged — the report still lists it,
            and says the comparison did not run rather than implying the
            sides agree.

    **Reading both archives is the point.** It costs a download per side on a
    streaming provider, and that is correct here: the student asked to resolve
    a fork, and no honest answer is available without reading both. Contrast
    #147, where a *status* check was paying that cost for nothing.
    """
    summaries = [summarise_side(m) for m, _ in sides]
    for summary in summaries:
        summary.is_local = bool(local_blob_name) and summary.blob_name == local_blob_name
    report = ForkReport(
        parent_generation=parent_generation,
        sides=summaries,
        first_connect=first_connect,
        set_aside=set_aside,
    )
    if set_aside:
        report.notes.append(
            "This device's copy was not the one kept: a choice made on "
            "another device set it aside. Nothing has been removed from this "
            "device. Choose which copy you want here.")
    elif first_connect:
        report.notes.append(
            "These two copies have never been synced with each other, so "
            "neither is newer than the other in any sense WIMI can check.")

    paths = [p for _, p in sides]
    if len(sides) != 2:
        report.notes.append(
            f"{len(sides)} sides share generation {parent_generation}; the "
            f"subject comparison is only defined for two."
        )
        return report
    if any(p is None for p in paths):
        report.notes.append(
            "One side could not be read, so the subject comparison did not "
            "run. An empty 'only on this side' list below means nobody "
            "looked, not that the two agree."
        )
        return report

    try:
        left, right = (_subject_names(p) for p in paths)  # type: ignore[arg-type]
    except (OSError, zipfile.BadZipFile, sqlite3.Error, KeyError) as exc:
        report.notes.append(
            f"The subject comparison could not run ({exc}). An empty 'only on "
            f"this side' list below means nobody looked, not that the two agree."
        )
        return report

    summaries[0].subjects_only_here = _pretty(left - right)
    summaries[1].subjects_only_here = _pretty(right - left)
    report.compared = True

    if not (left - right) and not (right - left):
        # Say what was CHECKED, and nothing more. This note used to read
        # "Both copies have the same subjects. They differ in entries, not
        # in the tree." -- and the second sentence was an assertion the code
        # never tested. Nothing here compares entry contents; the subject
        # sets matching says nothing about entries either way, so two
        # genuinely identical copies would have been told they differed.
        # Caught on real hardware by a report showing 50 entries against 50
        # under a sentence claiming the entries differed.
        report.notes.append("Both copies have the same subjects.")

        differing = _figures_that_differ(*summaries[:2])
        if differing:
            report.notes.append(
                "They differ in: " + "; ".join(differing) + ".")
        else:
            # A real and important state, not an absence of news: by every
            # figure recorded here the two are indistinguishable. The student
            # should be told that plainly rather than left to infer it from
            # a table of equal numbers.
            report.notes.append(
                "Every figure recorded here is the same on both copies. They "
                "may still hold different entries -- nothing here compares "
                "entries one by one -- but there is no evidence of a "
                "difference to show you."
            )
    return report


__all__ = [
    "figures_that_differ",
    "SideSummary",
    "ForkReport",
    "summarise_side",
    "build_fork_report",
    "NAMED_SUBJECT_LIMIT",
]
