"""Can this copy of WIMI extract relations, and if not, why not (#60)?

Owner's decision, 2026-10-04: a machine that cannot run extraction gets **a
line in Settings and silence everywhere else**. The entry form shows nothing --
no disabled button, no "unavailable" notice, no placeholder where the proposals
would have been. Manual creation (#14) is simply how relations are made.

That follows two of #14's own decisions rather than inventing a rule: decision
10, *"a student who never touches this must never notice it exists"*, and
decision 11, *"degrade to absent, not to an empty card"*.

"Cannot run it" is FIVE states, not one
---------------------------------------
The owner raised this immediately after the decision and it changes the copy
for most people who will ever read it. Since #337 ships **two artifacts per
platform**, the dominant reason extraction is unavailable is **which download
the student has**, not what their computer can do. Telling someone "your
machine cannot run this" when they have the smaller download is false.

Three of the five are actionable, which is why they cannot share a sentence.
#174's rule is that a message may not direct a press when nothing is pressable
-- not that it may never direct one. Collapsing these into the most pessimistic
wording fails #174 from the other side.

Why this reads a flag and not ``importlib.util.find_spec('torch')``
--------------------------------------------------------------------
``packaging/rthook_relations_build.py`` sets ``sys._wimi_relations_build`` and
its docstring already argues this: a probe answers "can I import torch", which
conflates **the default artifact** (the runtime is absent *by design*, nothing
is wrong, nothing should be reported as broken) with **the relations artifact
whose runtime will not load** (a packaging bug in the artifact the student
deliberately took the larger download for). A probe cannot tell those apart.
The flag records what the build *intended*, which only the build knows.

Nothing at runtime may set that flag -- not an environment variable, not a
command-line option -- exactly as with #144's test-build marker. A default
artifact is a default artifact.

This module imports no runtime package at module scope, so it is safe to import
from anywhere, including the startup path. ``MISSING_RUNTIME`` is detected with
``importlib.util.find_spec``, which does **not** execute the module and
therefore does not pay torch's multi-second, ~1.25 GB import cost.
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

#: The packages the relations artifact carries and the default one does not.
#: Kept in step with ``requirements-relations.txt`` and with
#: ``scripts/check_relations_runtime_imports.py``'s own list.
#:
#: ``peft`` is here because of #364 and is the reason this list is not simply
#: "the three obvious ones". ``gliner2`` declares peft only under an extra, and
#: `requirements-relations.txt` pinned bare ``gliner2``, so a venv built exactly
#: as instructed had a findable ``gliner2`` that could not be imported --
#: `gliner2/training/trainer.py` does an unconditional ``from peft import
#: PeftModel`` on the *inference* path. Found on macOS, reproduced on Linux.
RUNTIME_PACKAGES = ("torch", "transformers", "gliner2", "peft")


class AvailabilityState(str, Enum):
    """Why extraction is or is not available, at the granularity Settings needs.

    ``str`` mixin so a state serialises through the bridge as its own name,
    matching ``SttErrorKind`` and the codebase's other JSON-facing enums.
    """

    #: Everything is present. The only state in which a proposal may be made.
    READY = 'ready'

    #: The default artifact. The runtime was never bundled; this is by design
    #: and is not a fault. **Actionable**: the other download exists.
    NOT_IN_THIS_BUILD = 'not_in_this_build'

    #: The relations artifact, but the runtime will not import. The student
    #: took the larger download and did not get what it promised, so this is a
    #: **packaging bug** and should say so rather than impersonating the state
    #: above.
    RUNTIME_BROKEN = 'runtime_broken'

    #: Runtime present, weights not fetched yet. **Actionable**: a download
    #: button belongs here. This is #59's D2 path.
    MODEL_NOT_DOWNLOADED = 'model_not_downloaded'

    #: A development checkout without ``requirements-relations.txt`` installed.
    #: **Actionable**: a pip command.
    DEV_RUNTIME_MISSING = 'dev_runtime_missing'


#: States where something in the application, or a named action outside it, can
#: change the answer. #174: a message may direct a press only when there is one.
#: ``NOT_IN_THIS_BUILD`` is here because the *action* is real -- fetch the other
#: artifact -- even though no button in this build performs it; the Settings
#: copy must name the download rather than offering an enable switch.
ACTIONABLE = frozenset({
    AvailabilityState.NOT_IN_THIS_BUILD,
    AvailabilityState.MODEL_NOT_DOWNLOADED,
    AvailabilityState.DEV_RUNTIME_MISSING,
})


@dataclass(frozen=True)
class Availability:
    """The answer, plus what is needed to phrase it without lying."""

    state: AvailabilityState
    #: Which runtime packages could not be found. Empty unless the state is
    #: one of the missing-runtime ones.
    missing: tuple[str, ...] = ()
    #: Where the weights are expected, when that is the thing that is missing.
    model_path: Optional[Path] = None

    @property
    def ready(self) -> bool:
        return self.state is AvailabilityState.READY

    @property
    def actionable(self) -> bool:
        """Is there a next step that exists? See #174."""
        return self.state in ACTIONABLE


def is_relations_build() -> bool:
    """Did this build intend to carry the relation-extraction runtime?

    True only in a frozen bundle built with ``WIMI_BUILD_RELATIONS=1``, where
    ``packaging/rthook_relations_build.py`` is included and sets the flag.

    **A development checkout is not a relations build**, whatever is installed
    in its venv, and that is deliberate: the flag answers "what did the build
    intend", and a checkout did not build anything. The dev case is reported as
    its own state rather than being folded into either artifact's.
    """
    return bool(getattr(sys, '_wimi_relations_build', False))


def _missing_runtime_packages() -> tuple[str, ...]:
    """Which runtime packages cannot be found, without importing any of them.

    ``find_spec`` locates a module without executing it. Importing torch to
    find out whether torch is importable would cost seconds and ~1.25 GB on
    every call, including the one Settings makes to decide whether to draw a
    line of text.

    **This is a necessary check, not a sufficient one, and #364 is the worked
    example.** A package can be findable and still fail to import, because
    ``find_spec`` resolves one name and executes nothing -- so it cannot see a
    missing *transitive* dependency. Measured on this tree: with ``peft``
    absent, ``find_spec('gliner2')`` returned a spec, this function returned
    empty, and :func:`get_availability` reported ``READY`` -- while
    ``from gliner2 import GLiNER2`` raised ``ModuleNotFoundError``. That is the
    exact state :attr:`AvailabilityState.RUNTIME_BROKEN` exists to name, and
    the cheap check reported the opposite.

    Adding ``peft`` to :data:`RUNTIME_PACKAGES` closes that instance. It does
    not close the class: the only way to *prove* the runtime loads is to load
    it, which costs seconds and gigabytes and must not happen on a Settings
    query. So the real backstop is
    :attr:`~.errors.RelationExtractionErrorKind.MODEL_LOAD_FAILED` at first
    use, and a ``READY`` from here means "nothing obviously missing" rather
    than "this will work".

    If a future dependency repeats the trick, add it here *and* resist the urge
    to make this function import anything.
    """
    missing = []
    for name in RUNTIME_PACKAGES:
        try:
            if importlib.util.find_spec(name) is None:
                missing.append(name)
        except (ImportError, ValueError):
            # ValueError: a package present but with a broken __spec__.
            # Both mean "not usable from here", which is what the caller asked.
            missing.append(name)
    return tuple(missing)


def get_availability(
    model_path: Optional[Path] = None,
    *,
    model_installed: Optional[bool] = None,
) -> Availability:
    """Resolve which of the five states this copy of WIMI is in.

    Parameters
    ----------
    model_path:
        Where the weights are expected. When ``None`` the model check is
        skipped and a working runtime reports :attr:`AvailabilityState.READY`
        -- callers that care about the weights pass the path. The model layer
        owns that location and this module deliberately does not reach into it,
        so that availability can be asked before anything model-shaped exists.
    model_installed:
        Whether the weights are *complete*, answered by the caller. When given
        it decides, and ``model_path`` is only reported.

    Why the caller answers that question
    ------------------------------------
    **This model is eight files, so the existence of a path cannot say whether
    it is installed.** ``model_spec.model_dir()`` creates the directory by
    default, so a caller passing it would get :attr:`AvailabilityState.READY`
    on a machine holding none of the weights -- permanently, and with no error
    anywhere. ``model_spec.missing_files()`` is the real answer (eight ``stat``
    calls, no hashing), and it lives in the module this one deliberately does
    not import.

    So a path that is an existing **directory** must come with
    ``model_installed``; without it this raises ``ValueError`` rather than
    returning a wrong state quietly. A single-file path still works on its own
    existence, which is what #59's speech models need.

    Notes
    -----
    Order matters and is not arbitrary. The build's *intent* is checked first,
    because it is the only thing that distinguishes "absent by design" from
    "broken", and those two states differ in whether anything is wrong.
    """
    if (model_installed is None and model_path is not None
            and model_path.is_dir()):
        raise ValueError(
            f'{model_path} is a directory, so its existence does not say '
            f'whether the model is installed. Pass model_installed= (from '
            f'model_spec.missing_files, which is eight stat calls), or pass '
            f'model_path=None to skip the model check.'
        )
    missing = _missing_runtime_packages()

    if getattr(sys, 'frozen', False):
        if not is_relations_build():
            # The default artifact. Whether torch happens to be importable is
            # irrelevant and is deliberately not consulted: this build was
            # never meant to have the feature.
            return Availability(AvailabilityState.NOT_IN_THIS_BUILD)
        if missing:
            return Availability(AvailabilityState.RUNTIME_BROKEN, missing=missing)
    elif missing:
        # A checkout. The fix is a pip command, which is a different sentence
        # from either artifact's.
        return Availability(AvailabilityState.DEV_RUNTIME_MISSING, missing=missing)

    if model_installed is None:
        installed = model_path is None or model_path.exists()
    else:
        installed = bool(model_installed)
    if not installed:
        return Availability(
            AvailabilityState.MODEL_NOT_DOWNLOADED, model_path=model_path)

    return Availability(AvailabilityState.READY, model_path=model_path)
