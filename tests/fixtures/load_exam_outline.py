"""Loader for the synthetic exam-outline fixture.

Reads ``exam_outline.json`` and flattens it into the shape the polyhierarchy
tests and ``wimi_test``'s ``seed_exam_outline`` consume: every topic in
document order with its parent path, plus the index of topics that appear
under more than one parent.

Public entry point: :func:`load_exam_outline`.

**This used to be a 558-line parser** (``load_usmle_outline.py``) recovering
structure from a PDF-derived text dump of a published content outline -- bullet
detection, indentation levels, semicolon splitting, continuation lines,
boilerplate stripping, and a hardcoded tuple of that document's own section
names used as anchors. None of that is needed against a fixture this project
authors, so none of it survived (#437). If a future change makes this file
start guessing again, the fixture is the thing to fix.

The fixture is generated; see ``build_exam_outline.py`` beside it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class OutlineTopic:
    """A single named topic with its hierarchical parent path.

    A topic's identity is its ``name``, which the fixture spells identically
    everywhere it lists the same topic. The same name under two different
    parent paths produces two ``OutlineTopic`` rows and a single key in
    :attr:`ExamOutline.parent_index` -- that is what makes it multi-parent.

    ``order`` is the topic's position in document order, kept so a caller can
    reproduce the fixture's sequence after filtering.
    """

    name: str
    parent_path: tuple[str, ...]
    order: int


@dataclass(frozen=True)
class ExamOutline:
    """Flattened view of the fixture.

    Attributes:
        exam_name: The name the fixture gives the exam it describes.
        topics: Every topic in document order.
        parent_index: Map from topic name to the list of distinct parent paths
            (joined with ``" > "``) where it appears.
        multi_parent_topics: Topic names appearing under two or more distinct
            parent paths, sorted.
    """

    exam_name: str
    topics: list[OutlineTopic]
    parent_index: dict[str, list[str]] = field(default_factory=dict)
    multi_parent_topics: list[str] = field(default_factory=list)


def _default_path() -> Path:
    return Path(__file__).resolve().parent / "exam_outline.json"


def _walk(
    node: dict,
    path: tuple[str, ...],
    topics: list[OutlineTopic],
) -> None:
    """Append every topic beneath the container ``node``.

    The fixture has one representation each: a container is a dict with
    ``name`` and ``children``, a topic is a bare string inside a container's
    ``children``. A container is a level of the hierarchy and reaches the
    database through its descendants' ``parent_path``; emitting it as a topic
    *as well* would make a category name shared by two roots into a single
    multi-parent node, which is not what a shared category means.
    """
    here = path + (node["name"],)
    for child in node["children"]:
        if isinstance(child, str):
            topics.append(
                OutlineTopic(name=child, parent_path=here, order=len(topics))
            )
        else:
            _walk(child, here, topics)


def load_exam_outline(path: Path | None = None) -> ExamOutline:
    """Load the fixture into structured tuples for test setup.

    If ``path`` is None, default to ``tests/fixtures/exam_outline.json``
    relative to this module.
    """
    src = Path(path) if path is not None else _default_path()
    document = json.loads(src.read_text(encoding="utf-8"))

    topics: list[OutlineTopic] = []
    for root in document["roots"]:
        _walk(root, (), topics)

    parent_index: dict[str, list[str]] = {}
    for topic in topics:
        path_str = " > ".join(topic.parent_path)
        bucket = parent_index.setdefault(topic.name, [])
        if path_str not in bucket:
            bucket.append(path_str)

    multi_parent_topics = sorted(
        name for name, paths in parent_index.items() if len(paths) >= 2
    )

    return ExamOutline(
        exam_name=document["exam_name"],
        topics=topics,
        parent_index=parent_index,
        multi_parent_topics=multi_parent_topics,
    )


__all__ = ["OutlineTopic", "ExamOutline", "load_exam_outline"]
