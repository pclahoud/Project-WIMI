"""Relation extraction from the student's own explanation (#60).

**This is the quarantine package.** `scripts/check_relations_runtime_imports.py`
names it in `RELATIONS_PACKAGE`, and it is the one place in `src/` permitted to
import `torch`, `transformers` or `gliner2` at module scope. Everything else
reaches this feature through a function-level import, after asking
:func:`availability.get_availability` whether there is anything to reach.

That asymmetry is the whole delivery design (#337): WIMI ships **two artifacts
per platform**, and the default one does not carry the runtime. A module-scope
`import torch` anywhere on the startup path is an `ImportError` before the
window appears, for almost every user, from a line that works perfectly on a
developer's machine.

**This `__init__` must stay import-light.** It deliberately re-exports only
from `availability` and `errors`, neither of which touches the runtime, so that
`from app.relation_extraction import get_availability` costs nothing. Anything
that loads a model belongs behind a function-level import of a sibling module.
Adding a convenience re-export of the runtime here would make the package
unimportable on the default artifact and would defeat its own quarantine.
"""
from __future__ import annotations

from .availability import (
    Availability,
    AvailabilityState,
    get_availability,
    is_relations_build,
)
from .errors import RelationExtractionError, RelationExtractionErrorKind, RETRYABLE

__all__ = [
    "Availability",
    "AvailabilityState",
    "get_availability",
    "is_relations_build",
    "RelationExtractionError",
    "RelationExtractionErrorKind",
    "RETRYABLE",
]
