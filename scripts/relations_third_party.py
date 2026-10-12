"""Licence texts and notices for the relations runtime, staged into a relations build (#336).

The relations artifact (#337) bundles the relation-extraction runtime --
``torch``, ``transformers``, ``gliner2``, ``peft`` and everything they pull in
-- and until this module it conveyed **no** licence text for any of it. Most of
that stack is Apache-2.0, whose section 4 asks for more than naming: a copy of
the licence, and any ``NOTICE`` file the work carries, must go with every copy.
The MIT, BSD and ISC components ask for their copyright and permission notice
to be included. ``tqdm`` is MPL-2.0 (with MIT), which asks recipients to be told
where its source is. Settings -> About names components; naming a licence is not
conveying it, which is the distinction #272 drew for WIMI's own GPL text.

What this does
--------------
For a relations build, :func:`stage_relations` works out which distributions
the runtime brings (the dependency **closure** of
``availability.RUNTIME_PACKAGES``, read from the build environment's installed
metadata) and copies each one's licence files **verbatim** from its
``.dist-info`` into ``licenses/third-party/<name>-<version>/``. torch alone
ships 99 of them, covering the third-party code it vendors (FP16, NNPACK, ...).

**The files are stored FLAT, under short names, with a map.** torch keeps its
vendored licences at their source-tree depth --
``third_party/flash-attention/third_party/aiter/3rdparty/composable_kernel/...``
-- and copying that structure overran Windows' 260-character path limit on the
first trial, inside a scratch directory, on a machine with ``LongPathsEnabled =
0`` (the default). A student unzipping the build into ``Downloads`` would hit
the same wall, and an extraction that silently skips files is how a licence
goes missing. So a nested file becomes ``NNN-<parent>-<name>``, and each
component's ``FILES.txt`` maps every short name back to its path in the
distribution, which is what says whose licence it is. It then writes ``licenses/third-party/INDEX.txt``,
listing every distribution with its version, licence and source location, and
a section on the GLiNER2 model weights, which are not in the bundle.

Nothing is typed by hand: every text is the file the distribution itself
ships, and every licence string is read from its metadata. A distribution with
no licence file at all makes staging **fail**, naming it, so a relations build
cannot quietly ship a component it has no text for.

The one exception is explicit and reviewed: :data:`DECLARED_ONLY`. The first
trial found ``tokenizers`` 0.23.2, whose wheel ships **no** licence file while
its metadata declares Apache (by classifier). For a component listed there, and
only when its metadata really does declare that licence, staging conveys the
standard text from ``licenses/Apache-2.0.txt``. That text is apache.org's
``LICENSE-2.0.txt`` byte for byte (sha256 ``cfc7749b...``, 11,358 bytes,
checked against apache.org when it was added, and pinned by
``check_bundled_licenses.py``). The component's ``FILES.txt`` says it is a
fallback rather than the component's own file. A new component in that state
still fails the build until somebody adds it here on purpose.

Any SBOM a distribution ships (``.dist-info/sboms/``) is conveyed too.
``tokenizers`` carries one listing the Rust crates compiled into it, which is
the only record in the wheel of whose code is inside it.

Why the closure, not a diff against the default build
------------------------------------------------------
A component already in the default build (``packaging``, say) is still
redistributed by the relations build, and its notice obligations do not lapse
because another artifact also carries it. The closure is what this artifact
ships because of the runtime, so it is what this artifact owes notices for.

Why from the build environment's metadata
-----------------------------------------
That environment is the one PyInstaller collects from, so its installed
distributions are the versions in the bundle. Reading ``requirements-*.txt``
would give pins, not what was actually installed; reading the bundle would give
module files without their licences, because PyInstaller does not collect
``.dist-info/licenses``.
"""
from __future__ import annotations

import importlib.metadata as md
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
THIRD_PARTY_DIR = Path("licenses") / "third-party"
INDEX_NAME = "INDEX.txt"
FILES_NAME = "FILES.txt"
#: Longest file name written into a component's folder. With the folder name
#: and ``licenses/third-party/`` this keeps every staged path well inside 260
#: characters from any reasonable unzip location.
MAX_NAME = 64

#: Components whose wheel ships no licence file, mapped to the licence their
#: metadata declares. Reviewed one by one; see the module docstring.
DECLARED_ONLY: Dict[str, str] = {
    "tokenizers": "Apache",
}
#: The standard text used for a ``DECLARED_ONLY`` component, and its pin.
APACHE_TEXT = REPO_ROOT / "licenses" / "Apache-2.0.txt"
APACHE_SHA256 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"

#: File names that are licence material wherever they sit in a dist-info.
_LICENCE_NAME = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE|AUTHORS|COPYRIGHT)", re.IGNORECASE)


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def runtime_roots() -> Tuple[str, ...]:
    """``availability.RUNTIME_PACKAGES``, imported rather than restated.

    ``app.relation_extraction.availability`` is stdlib-only by design (it is
    reachable on the default artifact), so importing it here costs nothing and
    keeps one definition of "the runtime".
    """
    src = str(REPO_ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from app.relation_extraction.availability import RUNTIME_PACKAGES

    return tuple(RUNTIME_PACKAGES)


def closure(roots: Iterable[str]) -> Dict[str, md.Distribution]:
    """Every installed distribution ``roots`` need, by canonical name.

    Requirements are evaluated against this interpreter with no extras, which
    is how pip resolved them for the build environment. A requirement whose
    marker is false here (another platform's dependency) is skipped; one that is
    required but not installed is an error, because the runtime would be broken.
    """
    from packaging.requirements import Requirement

    found: Dict[str, md.Distribution] = {}
    pending = [_canonical(r) for r in roots]
    while pending:
        name = pending.pop()
        if name in found:
            continue
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            raise SystemExit(
                f"ERROR: the relations runtime needs {name!r}, which is not installed "
                f"in this environment; a relations build from here would be broken."
            ) from None
        found[name] = dist
        for raw in dist.requires or []:
            req = Requirement(raw)
            if req.marker is not None and not req.marker.evaluate({"extra": ""}):
                continue
            pending.append(_canonical(req.name))
    return found


def licence_files(dist: md.Distribution) -> List[Tuple[PurePosixPath, Path]]:
    """``(path inside the dist-info, file on disk)`` for each licence file.

    Every file under ``*.dist-info/licenses/`` (PEP 639) is taken, at any depth.
    Older metadata keeps them in the dist-info root instead, so files there
    whose names look like licence material are taken too.
    """
    out = []
    for entry in dist.files or []:
        parts = PurePosixPath(str(entry).replace("\\", "/")).parts
        if not parts or not parts[0].endswith(".dist-info"):
            continue
        inside = PurePosixPath(*parts[1:]) if len(parts) > 1 else None
        if inside is None:
            continue
        if inside.parts[0] == "licenses" and len(inside.parts) > 1:
            rel = PurePosixPath(*inside.parts[1:])
        elif inside.parts[0] == "sboms" and len(inside.parts) > 1:
            rel = inside
        elif len(inside.parts) == 1 and _LICENCE_NAME.match(inside.name):
            rel = inside
        else:
            continue
        path = Path(dist.locate_file(entry))
        if path.is_file():
            out.append((rel, path))
    return sorted(out)


def licence_string(dist: md.Distribution) -> str:
    """The licence as the distribution states it, never inferred."""
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression.strip()
    classifiers = [c.split("::")[-1].strip() for c in (meta.get_all("Classifier") or [])
                   if c.startswith("License ::")]
    if classifiers:
        return "; ".join(classifiers)
    text = (meta.get("License") or "").strip()
    if text:
        first = text.splitlines()[0].strip()
        return first if len(first) <= 80 else first[:77] + "..."
    return "(not stated in metadata; see the licence files)"


def source_location(dist: md.Distribution) -> str:
    meta = dist.metadata
    for entry in meta.get_all("Project-URL") or []:
        label, _, url = entry.partition(",")
        if label.strip().lower() in ("source", "source code", "repository", "code", "github"):
            return url.strip()
    if meta.get("Home-page"):
        return meta["Home-page"].strip()
    for entry in meta.get_all("Project-URL") or []:
        _, _, url = entry.partition(",")
        if url.strip():
            return url.strip()
    return f"https://pypi.org/project/{meta['Name']}/{dist.version}/"


def _declared_only_text(name: str, dist: md.Distribution) -> Optional[Path]:
    """The pinned Apache text for a reviewed ``DECLARED_ONLY`` component, or ``None``.

    Refuses (``SystemExit``) if the component is listed but its metadata no
    longer declares that licence, or if the pinned text has changed: either
    would mean conveying a licence nobody checked.
    """
    import hashlib

    declared = DECLARED_ONLY.get(name)
    if declared is None:
        return None
    stated = licence_string(dist)
    if declared.lower() not in stated.lower():
        raise SystemExit(
            f"ERROR: {name} is listed as declaring the {declared} licence, but its "
            f"metadata now says {stated!r}. Review DECLARED_ONLY before building.")
    digest = hashlib.sha256(APACHE_TEXT.read_bytes()).hexdigest()
    if digest != APACHE_SHA256:
        raise SystemExit(
            f"ERROR: {APACHE_TEXT} has changed (sha256 {digest}); it must be "
            f"apache.org's LICENSE-2.0.txt verbatim.")
    return APACHE_TEXT


def short_name(index: int, rel: PurePosixPath) -> str:
    """A flat name for one licence file: its own name, or ``NNN-parent-name``.

    A top-level file (``LICENSE``) keeps its name, which is what a reader looks
    for first. A nested one is numbered so two ``LICENSE`` files from different
    vendored projects cannot collide, and keeps its parent directory's name,
    which is usually the project's.
    """
    if len(rel.parts) == 1:
        return rel.name[:MAX_NAME]
    name = f"{index:03d}-{rel.parts[-2]}-{rel.name}"
    if len(name) > MAX_NAME:
        name = f"{index:03d}-{rel.name}"[:MAX_NAME]
    return name


@dataclass
class Staged:
    name: str
    version: str
    licence: str
    source: str
    folder: str
    files: List[str] = field(default_factory=list)


def _model_section() -> List[str]:
    """The GLiNER2 weights: facts from ``model_spec``, the one pin table."""
    src = str(REPO_ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from app.relation_extraction import model_spec as ms

    return [
        "THE RELATION-EXTRACTION MODEL (not in this bundle)",
        "--------------------------------------------------",
        "",
        "The model weights are not part of this download. On first use WIMI fetches",
        f"them from {ms.MODEL_LICENCE_URL}",
        f"at revision {ms.MODEL_REVISION}, into app_data/models/gliner2/.",
        "",
        f"  Model        : {ms.MODEL_REPO} -- licence {ms.MODEL_LICENCE}",
        f"  Built on     : DeBERTa-v3-base (Microsoft) -- licence {ms.MODEL_BASE_LICENCE}",
        "",
        "The Apache License 2.0 text that governs the model is the same text conveyed",
        "with the gliner2 and transformers packages listed above.",
        "",
    ]


def stage_relations(bundle_dir: Path, roots: Optional[Iterable[str]] = None) -> List[Staged]:
    """Copy every runtime distribution's licence files and write the index."""
    dists = closure(roots if roots is not None else runtime_roots())
    target_root = bundle_dir / THIRD_PARTY_DIR
    if target_root.exists():
        shutil.rmtree(target_root)
    staged: List[Staged] = []
    missing: List[str] = []
    for name in sorted(dists):
        dist = dists[name]
        files = licence_files(dist)
        fallback = None
        if not any(rel.parts[0] != "sboms" for rel, _ in files):
            fallback = _declared_only_text(name, dist)
            if fallback is None:
                missing.append(f"{dist.metadata['Name']} {dist.version}")
                continue
            files = [(PurePosixPath("LICENSE-Apache-2.0.txt"), fallback)] + files
        folder = f"{_canonical(dist.metadata['Name'])}-{dist.version}"
        item = Staged(dist.metadata["Name"], dist.version, licence_string(dist),
                      source_location(dist), folder)
        (target_root / folder).mkdir(parents=True, exist_ok=True)
        mapping = []
        for index, (rel, path) in enumerate(files, 1):
            name = short_name(index, rel)
            shutil.copyfile(path, target_root / folder / name)
            item.files.append(name)
            origin = ("licenses/Apache-2.0.txt in WIMI's repository: this component ships "
                      "no licence file; its metadata declares the Apache licence"
                      if fallback is not None and path == fallback else rel.as_posix())
            mapping.append(f"{name}  <-  {origin}")
        (target_root / folder / FILES_NAME).write_text(
            f"{item.name} {item.version}: licence files, as the distribution ships them.\n"
            f"Each line maps a file in this folder to its path in the distribution.\n\n"
            + "\n".join(mapping) + "\n", encoding="utf-8")
        staged.append(item)
    if missing:
        raise SystemExit(
            "ERROR: these relations-runtime distributions ship no licence file, so this "
            "build would convey nothing for them: " + ", ".join(missing))

    lines = [
        "THIRD-PARTY COMPONENTS OF THE RELATION-EXTRACTION RUNTIME",
        "========================================================",
        "",
        "This build of WIMI includes the components below, which suggest relations",
        "between subjects from a student's own explanations. Each is the property of",
        "its copyright holders and is used under the licence shown, read from the",
        "component's own metadata. Each folder holds that component's licence and",
        "notice files exactly as the component ships them.",
        "",
        "The source of each component is available at the location shown.",
        "",
    ]
    width = max(len(s.folder) for s in staged)
    for s in staged:
        lines.append(f"{s.name} {s.version}")
        lines.append(f"    Licence : {s.licence}")
        lines.append(f"    Source  : {s.source}")
        lines.append(f"    Texts   : {THIRD_PARTY_DIR.as_posix()}/{s.folder}/ "
                     f"({len(s.files)} file{'s' if len(s.files) != 1 else ''})")
        lines.append("")
    lines += _model_section()
    (target_root / INDEX_NAME).write_text("\n".join(lines), encoding="utf-8")
    del width
    return staged
