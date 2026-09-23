"""What a weight in an import file *means* — issue #64, decided 2026-09-15.

The guide specified a weight's shape and never said what the number was a
percentage *of*, which the user who built two real USMLE files ranked the
#1 problem with the format: "every weighting decision today ran into one
of these gaps". Five decisions settled it, and there is **one test per
decision below** so none of them can drift back into ambiguity — the same
arrangement, and the same reason, as
``tests/database/test_draft_policy_by_surface.py``.

Three of the five are enforced by an *absence*: no parent/child
comparison, no rescaling, no rejection of a zero. A test that only
asserted the presence of code would not notice any of them coming back.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from database import MasterDatabase, UserDatabase


pytestmark = pytest.mark.database


# ==================== Fixtures & helpers ====================

@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def master_db(temp_dir):
    db = MasterDatabase(data_dir=temp_dir)
    yield db
    db.close()


@pytest.fixture
def test_user(master_db):
    return master_db.create_user(
        username="weight_user",
        display_name="Weight Semantics User",
        user_types=["student"],
    )


@pytest.fixture
def user_db(master_db, test_user):
    db_path = master_db.ensure_user_database(test_user.id)
    db = UserDatabase(
        db_path=db_path,
        user_id=test_user.id,
        username=test_user.username,
    )
    yield db
    db.close()


@pytest.fixture
def exam(user_db):
    user_db.create_exam_context(
        exam_name="Weight Exam",
        exam_description="issue #64",
    )
    return user_db.get_exam_context_by_name("Weight Exam")


def _node(name, *, weight=None, children=None, level_type=None):
    node = {'name': name}
    if weight is not None:
        node['weight'] = weight
    if children:
        node['children'] = list(children)
    if level_type is not None:
        node['level_type'] = level_type
    return node


def _weights(user_db, exam_name):
    """``{name: (low, high)}`` for every active subject in the exam."""
    return {
        row['name']: (row['exam_weight_low'], row['exam_weight_high'])
        for row in user_db.fetchall(
            "SELECT name, exam_weight_low, exam_weight_high FROM subject_nodes "
            "WHERE exam_context = ? AND status = 'active'",
            (exam_name,),
        )
    }


# ==================== Decision 1 ====================

@pytest.mark.database
def test_decision_1_a_child_may_exceed_its_parent(user_db, exam):
    """A weight is a share of the **whole exam**, at every depth.

    The real case: Nutrition at 15–20% inside Multisystem at 4–8%. Step 2 CK
    publishes those two as *sibling* rows, so the nesting below is the
    student's own — one who files nutrition under multisystem lands a
    15–20% child inside a 4–8% parent using two real published numbers.
    Not an error, not rescaled, not warned about — the absence of a
    parent/child comparison anywhere in the planner is the implementation
    of this decision.
    """
    root_nodes = [
        _node(
            "Multisystem",
            weight={'low': 4, 'high': 8},
            children=[_node("Nutrition", weight={'low': 15, 'high': 20})],
        ),
        _node("Everything else", weight={'low': 80, 'high': 96}),
    ]

    plan = user_db.plan_subject_import(exam.id, root_nodes)
    assert plan['errors'] == []
    assert not any('Nutrition' in w for w in plan['warnings'])

    user_db.apply_subject_import(exam.id, root_nodes)
    stored = _weights(user_db, exam.exam_name)
    assert stored['Multisystem'] == (4, 8)
    assert stored['Nutrition'] == (15, 20), "the child's own weight, untouched"


@pytest.mark.database
def test_decision_1_absolute_weights_are_accepted_at_any_depth(user_db, exam):
    """The examples put absolute weights at the top; that is not a rule."""
    root_nodes = [
        _node(
            "Section",
            weight={'value': 100},
            children=[
                _node(
                    "Domain",
                    weight={'low': 30, 'high': 40},
                    children=[_node("Skill", weight={'value': 12.5})],
                )
            ],
        )
    ]
    user_db.apply_subject_import(exam.id, root_nodes)

    stored = _weights(user_db, exam.exam_name)
    assert stored['Domain'] == (30, 40)
    assert stored['Skill'] == (12.5, 12.5)


# ==================== Decision 2 ====================

@pytest.mark.database
def test_decision_2_overlapping_coverage_is_imported_unrescaled(user_db, exam):
    """78–113% is a faithful transcription, not a defect.

    Overlapping classification is a genuine property of blueprints —
    USMLE's own Clinical Science table exceeds 100% by design. The
    numbers are stored exactly as published and the band is reported.
    """
    root_nodes = [
        _node("Discipline A", weight={'low': 26, 'high': 38}),
        _node("Discipline B", weight={'low': 26, 'high': 38}),
        _node("Discipline C", weight={'low': 26, 'high': 37}),
    ]

    plan = user_db.plan_subject_import(exam.id, root_nodes)
    assert plan['coverage']['low'] == 78
    assert plan['coverage']['high'] == 113
    assert plan['coverage']['spans_100'] is True
    assert plan['warnings'] == [], "a spanning band is not a problem"

    user_db.apply_subject_import(exam.id, root_nodes)
    stored = _weights(user_db, exam.exam_name)
    assert stored['Discipline A'] == (26, 38), "never rescaled to sum to 100"
    assert stored['Discipline C'] == (26, 37)


@pytest.mark.database
def test_decision_2_a_total_that_misses_100_warns_and_still_imports(user_db, exam):
    """A total outside 100% is a warning. Never a hard failure."""
    root_nodes = [
        _node("Only topic", weight={'value': 13}),
    ]

    plan = user_db.plan_subject_import(exam.id, root_nodes)
    assert plan['errors'] == []
    assert any('does not span 100%' in w for w in plan['warnings'])
    assert any('never rescales' in w for w in plan['warnings'])

    result = user_db.apply_subject_import(exam.id, root_nodes)
    assert result['counts']['added'] == 1
    assert _weights(user_db, exam.exam_name)['Only topic'] == (13, 13)
    assert any('does not span 100%' in w for w in result['warnings']), (
        "the apply must carry the plan's warnings, not recompute them"
    )


@pytest.mark.database
def test_decision_2_an_unweighted_file_gets_no_coverage_warning(user_db, exam):
    """Example 5 of the guide carries no weights at all, deliberately."""
    root_nodes = [_node("Section A", children=[_node("Topic 1")])]

    plan = user_db.plan_subject_import(exam.id, root_nodes)
    assert plan['coverage']['weighted_roots'] == 0
    assert plan['warnings'] == []


# ==================== Decision 3 ====================

@pytest.mark.database
def test_decision_3_an_omitted_weight_imports_as_zero(user_db, exam):
    """On import an empty weight means 0% — the blueprint did not weight it.

    This is the opposite of the tree editor's own weight field, which
    means "share out the remainder among siblings" and keeps that
    meaning (``tree_editor.html``'s help text is unchanged).
    """
    root_nodes = [
        _node("Weighted", weight={'value': 100}),
        _node("Unweighted"),
    ]
    user_db.apply_subject_import(exam.id, root_nodes)

    stored = _weights(user_db, exam.exam_name)
    assert stored['Unweighted'] == (0, 0), "0%, not a share of the remainder"

    # And nothing was taken from the weighted sibling to pay for it.
    assert stored['Weighted'] == (100, 100)


# ==================== Decision 4 ====================

@pytest.mark.database
def test_decision_4_zero_is_a_valid_weight_and_derived_does_not_lock(user_db, exam):
    """Step 2 CK really publishes tasks at 0%, so zero is data.

    And ``source: derived`` records only that WIMI computed the number.
    It is not a lock: ``weight_locked`` stays false, which is what keeps
    decision 4's two halves independent.
    """
    root_nodes = [
        _node("Published at zero", weight={'value': 0, 'source': 'derived'}),
        _node("The rest", weight={'value': 100}),
    ]

    plan = user_db.plan_subject_import(exam.id, root_nodes)
    assert plan['errors'] == []
    assert plan['warnings'] == []

    user_db.apply_subject_import(exam.id, root_nodes)
    assert _weights(user_db, exam.exam_name)['Published at zero'] == (0, 0)

    locked = user_db.fetchone(
        "SELECT weight_locked FROM subject_nodes "
        "WHERE exam_context = ? AND name = ?",
        (exam.exam_name, "Published at zero"),
    )
    assert not locked['weight_locked'], "derived must never imply locked"


# ==================== Decision 5 ====================

@pytest.mark.database
def test_decision_5_rebalance_leaves_an_anchored_sibling_alone(user_db, exam):
    """Locked wins over auto-balance — already true, and pinned here.

    Example 2 of the guide reads as though WIMI both locks official
    weights and auto-balances them. It is not a contradiction:
    ``rebalance_sibling_edge_weights`` excludes anchored and
    ``weight_locked`` edges, and rebalancing is opt-in in the first
    place. The guide's wording was fixed; this asserts the behaviour it
    now describes.
    """
    parent = user_db.create_subject_node(
        exam_context=exam.exam_name, name="Parent", level_type="Section"
    )
    anchored = user_db.create_subject_node(
        exam_context=exam.exam_name, name="Anchored", level_type="Domain",
        parent_id=parent.id,
    )
    free_a = user_db.create_subject_node(
        exam_context=exam.exam_name, name="Free A", level_type="Domain",
        parent_id=parent.id,
    )
    free_b = user_db.create_subject_node(
        exam_context=exam.exam_name, name="Free B", level_type="Domain",
        parent_id=parent.id,
    )

    def edge_id(child_id):
        return user_db.fetchone(
            "SELECT id FROM subject_edges WHERE parent_id = ? AND child_id = ?",
            (parent.id, child_id),
        )['id']

    user_db.update_edge_relative_weight(
        edge_id(anchored.id), 60.0, set_anchor=True,
        source='user_explicit', reason='official figure',
    )

    user_db.rebalance_sibling_edge_weights(parent.id)

    weights = {
        row['child_id']: row['relative_weight']
        for row in user_db.fetchall(
            "SELECT child_id, relative_weight FROM subject_edges "
            "WHERE parent_id = ?",
            (parent.id,),
        )
    }
    assert weights[anchored.id] == pytest.approx(60.0), "an anchor is not rebalanced"
    assert weights[free_a.id] == pytest.approx(20.0)
    assert weights[free_b.id] == pytest.approx(20.0)


# ==================== The checkable leftovers ====================

@pytest.mark.database
def test_low_above_high_warns_and_still_imports(user_db, exam):
    """A hard-looking rule that must not be a hard failure.

    Rejecting a 2,211-subject outline over one transposed pair costs the
    student the other 2,210 subjects, so this is reported and imported.
    """
    root_nodes = [_node("Transposed", weight={'low': 30, 'high': 20}),
                  _node("Rest", weight={'low': 70, 'high': 80})]

    plan = user_db.plan_subject_import(exam.id, root_nodes)
    assert plan['errors'] == []
    assert any('above its high' in w for w in plan['warnings'])

    user_db.apply_subject_import(exam.id, root_nodes)
    assert _weights(user_db, exam.exam_name)['Transposed'] == (30, 20)


@pytest.mark.database
def test_a_non_numeric_weight_warns_rather_than_raising(user_db, exam):
    """The import must not die of the typo it is trying to report."""
    root_nodes = [_node("Percent sign", weight="11%")]

    plan = user_db.plan_subject_import(exam.id, root_nodes)
    assert plan['errors'] == []
    assert any('not a number' in w for w in plan['warnings'])


@pytest.mark.database
def test_per_subject_weight_warnings_are_capped(user_db, exam):
    """One toast per warning, so a bad file must not bury the screen."""
    root_nodes = [
        _node(f"Bad {i}", weight={'low': 50, 'high': 10}) for i in range(25)
    ]

    plan = user_db.plan_subject_import(exam.id, root_nodes)
    per_subject = [w for w in plan['warnings'] if 'above its high' in w]
    assert len(per_subject) == 10
    assert any('and 15 more subjects' in w for w in plan['warnings'])


@pytest.mark.database
def test_bare_number_and_value_object_mean_the_same_thing(user_db, exam):
    """Issue #69's contradiction, resolved in favour of keeping both.

    The field table types ``weight`` as an object and the format summary
    accepts a bare number; both are real, so the guide now says so once
    and this pins them to the same result.
    """
    root_nodes = [
        _node("Bare", weight=40),
        _node("Object", weight={'value': 40}),
        _node("Low only", weight={'low': 20}),
    ]
    user_db.apply_subject_import(exam.id, root_nodes)

    stored = _weights(user_db, exam.exam_name)
    assert stored['Bare'] == stored['Object'] == (40, 40)
    assert stored['Low only'] == (20, 20), "high defaults to low"


# ==================== #104: source and locked stay documentation-only ====================

@pytest.mark.database
def test_104_source_and_locked_in_a_file_are_not_applied(user_db, exam):
    """Owner's decision on #104, 2026-09-22: option (a).

    A file's ``weight.source`` and ``weight.locked`` are documentation. The
    importer does not read them, so an "official, locked" subject imports as
    ``user_defined`` and unlocked -- locking is done in the tree editor. Like
    most of this file, the rule is enforced by an absence, which is why it
    is pinned: honouring either field would be the easy "fix" and would
    reverse the decision.
    """
    root_nodes = [
        _node("Declared official and locked",
              weight={'low': 11, 'high': 15, 'source': 'official', 'locked': True}),
    ]
    user_db.apply_subject_import(exam.id, root_nodes)

    row = user_db.fetchone(
        "SELECT exam_weight_low, exam_weight_high, weight_source, weight_locked "
        "FROM subject_nodes WHERE exam_context = ? AND name = ?",
        (exam.exam_name, "Declared official and locked"),
    )
    assert (row['exam_weight_low'], row['exam_weight_high']) == (11, 15), "the bounds are read"
    assert row['weight_source'] == 'user_defined', "weight.source was applied (#104 decided (a))"
    assert not row['weight_locked'], "weight.locked was applied (#104 decided (a))"
