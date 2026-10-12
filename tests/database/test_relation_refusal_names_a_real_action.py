"""A relation refusal may only name an action that exists (#484, #174).

`create_subject_relation` refused a duplicate with *"Those two subjects already
carry a relation in that direction. **Edit or remove it** rather than stating it
twice."* — and **there is no edit.** Measured: this domain has
`create_subject_relation`, `confirm_subject_relation` and
`delete_subject_relation` and no update; `grep -rn
"update_subject_relation\\|updateSubjectRelation" src/` returns nothing; the
bridge exposes five relation slots and none of them writes an existing row's
reason; and the panel row's only action is **Remove**.

So half the sentence directed the student at a control that exists at no layer.
#174's rule — a message may not direct a press when nothing is pressable —
applies to a message as much as to a button, and this is the message form of it.

Two tests, and the second is the one that keeps this honest rather than merely
fixed. Writing the first one found a **third** refusal nobody had named --
a clash raised while confirming a proposal -- which is the argument for reading
whole `raise` calls rather than grepping the one sentence the issue quoted:

* the refusals name **Remove** and no longer name an edit;
* **the absence of an update path is asserted.** If relation editing ever
  ships, this test fails, and the right response is to revisit the wording
  rather than to delete the assertion. Without it the first test would quietly
  become wrong the day an edit arrives — which is how #484 happened in reverse,
  a message written against a capability that was planned and never built.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.database

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RELATIONS = REPO_ROOT / "src" / "database" / "domains" / "relations.py"
BRIDGE = REPO_ROOT / "src" / "app" / "bridge_domains" / "relations.py"

#: Three refusals carry these markers: the untyped and typed duplicates in
#: `create_subject_relation`, and a clash raised while confirming a proposal.
_DUPLICATE_MARKER = "already carry a relation"
_TYPED_MARKER = "are already related by"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _refusal_blocks(src: str) -> list[str]:
    """The ValidationError bodies that refuse a duplicate.

    Taken as whole `raise ValidationError(...)` calls rather than by line, so a
    message split across concatenated strings is read entire. A line-wise read
    would see one fragment of the typed variant and miss the rest -- the same
    shape as #548's grep.
    """
    blocks = []
    for m in re.finditer(r"raise ValidationError\(", src):
        depth, i = 0, m.end() - 1
        while i < len(src):
            if src[i] == "(":
                depth += 1
            elif src[i] == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        body = src[m.end():i]
        if _DUPLICATE_MARKER in body or _TYPED_MARKER in body:
            blocks.append(body)
    return blocks


def test_every_duplicate_refusal_names_a_real_action():
    """The fix, over all three of them.

    THREE, and the third is why this reader exists rather than a grep for the
    one sentence #484 quoted:

    1. the untyped duplicate, in ``create_subject_relation`` -- #484's subject;
    2. the typed duplicate, in the same method, naming the relation type --
       the variant the issue did not quote, and which carried the same wrong
       word;
    3. a clash found while **confirming** a proposal, in
       ``confirm_subject_relation``, which already named two real actions
       (*Remove that one first, or reject this proposal*) and needed nothing.

    The count is pinned so a fourth fails here and gets read, rather than
    inheriting whatever wording it was written with.
    """
    blocks = _refusal_blocks(_source(RELATIONS))

    assert len(blocks) == 3, (
        f"expected three duplicate refusals, found {len(blocks)}. A new one "
        "needs the same treatment; a missing one may have been reworded past "
        "this reader rather than removed"
    )
    for body in blocks:
        assert "Remove" in body, (
            f"the refusal must name the action that exists: {body!r}")
        assert "Edit or remove" not in body, (
            f'"Edit" names an action that exists at no layer (#484): {body!r}')
        assert "Edit it" not in body, body


def test_there_is_still_no_way_to_edit_a_relation():
    """The guard that makes the wording above true rather than lucky.

    **If this fails because relation editing has shipped, fix the message, do
    not delete this test.** The messages corrected in #484 were written against
    a capability that was planned and never built; this is the assertion that
    would have caught that, pointing the other way.
    """
    relations = _source(RELATIONS)
    bridge = _source(BRIDGE)

    assert "def update_subject_relation" not in relations, (
        "a relation update exists now, so the duplicate refusals should "
        "mention it -- see this test's docstring before changing it")
    assert "def updateSubjectRelation" not in bridge, (
        "a bridge slot for editing a relation exists now; same")

    # The mutations the domain really has, asserted by name so a reader does
    # not have to take the absence on trust.
    for present in ("def create_subject_relation",
                    "def confirm_subject_relation",
                    "def delete_subject_relation"):
        assert present in relations, f"{present} has moved; this reader is stale"
