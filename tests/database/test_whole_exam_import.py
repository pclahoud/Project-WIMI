"""One file describes the whole exam: several axes, each with its own tree (#241).

`#66` Wave 3's planner half. The format is #240; the atomic apply is #239; the
dimension soft delete a removal goes through is #210.

Real blueprints classify one item pool along several axes at once -- Step 2 CK
publishes System, Discipline and Physician Task as three tables over the same
questions -- so `plan_subject_import`'s scalar `dimension_id` becomes per-tree.

**What these tests are shaped around.**

*Nothing here may become a second planner.* #67's guarantee is that the preview
and the apply cannot disagree because there is exactly one planner, and
`plan_whole_exam_import` keeps that by delegating every subject decision to
`_plan_subject_tree` and every subject write to `_apply_subject_plan` -- the
same two the single-tree path uses. `test_one_axis_plans_identically_to_a_
single_tree_import` is the assertion that the delegation is real rather than a
parallel implementation that happens to agree today.

*Coverage is per axis and never summed.* The axes are overlapping partitions of
the same items, which is why the three real Step 2 CK tables total 84-153%,
78-113% and 97-142%. A combined number would be the rescaling #64 forbids, so
there is **no top-level `coverage` key** and its absence is asserted -- one of
several rules here enforced by an absence.

*Scope must not bleed.* Two axes both containing a subject called "Renal" are
two subjects, not one. An import into System that judged the Task tree
absent-from-the-file would archive it.

*The empty-list trap, at two levels.* A misspelled `dimensions` key and a
misspelled `root_nodes` key both arrive as empty lists, and "declares nothing"
must never read as "remove everything". Under #210 that now costs whole trees.
"""
from __future__ import annotations

import pathlib
import sys
import tempfile
from datetime import date

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / 'src'))

from database import MasterDatabase, UserDatabase  # noqa: E402
from database.exceptions import ValidationError  # noqa: E402


@pytest.fixture
def user_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        master = MasterDatabase(data_dir=pathlib.Path(tmpdir))
        user = master.create_user(username='whole_exam', display_name='Probe',
                                  user_types=['student'])
        db = UserDatabase(db_path=master.ensure_user_database(user.id),
                          user_id=user.id, username='whole_exam')
        yield db
        db.close()
        master.close()


@pytest.fixture
def exam(user_db):
    user_db.create_exam_context(exam_name='Whole Exam',
                               exam_description='issue #241')
    return user_db.get_exam_context_by_name('Whole Exam')


# ---------------------------------------------------------------- helpers

def _axis(name, *roots, id=None, display_order=None, is_required=None,
          allow_multiple=None, description=None, root_key='root_nodes'):
    axis = {'name': name}
    if id is not None:
        axis['id'] = id
    if display_order is not None:
        axis['display_order'] = display_order
    if is_required is not None:
        axis['is_required'] = is_required
    if allow_multiple is not None:
        axis['allow_multiple'] = allow_multiple
    if description is not None:
        axis['description'] = description
    if roots or root_key == 'root_nodes':
        axis[root_key] = list(roots)
    return axis


def _node(name, *, id=None, children=None, weight=None, sort_order=None):
    node = {'name': name}
    if id is not None:
        node['id'] = id
    if children:
        node['children'] = list(children)
    if weight is not None:
        node['weight'] = weight
    if sort_order is not None:
        node['sort_order'] = sort_order
    return node


def _dimension(user_db, exam, name, order, **kwargs):
    return user_db.create_dimension(exam_id=exam.id, name=name,
                                    display_order=order, **kwargs)


def _subject(user_db, exam, name, dimension_id=None, parent_id=None):
    return user_db.create_subject_node(
        exam_context=exam.exam_name, name=name, level_type='System',
        parent_id=parent_id, dimension_id=dimension_id)


def _subjects_in(user_db, dimension_id):
    return {
        row['name']: row['id'] for row in user_db.fetchall(
            "SELECT id, name FROM subject_nodes "
            "WHERE dimension_id IS ? AND status = 'active'", (dimension_id,))
    }


def _axis_names(user_db, exam):
    return [d['name'] for d in user_db.get_exam_dimensions(exam.id)]


def _session(user_db, exam) -> int:
    cursor = user_db.execute(
        "INSERT INTO review_sessions "
        "(user_id, session_name, date_encountered, exam_context_id, "
        " total_questions, total_incorrect) VALUES (?, 'S', ?, ?, 1, 1)",
        (user_db.user_id, date.today().isoformat(), exam.id))
    user_db.conn.commit()
    return cursor.lastrowid


def _tag_entry(user_db, exam, *subject_ids, order=1):
    """One entry tagged onto every subject given.

    Raw inserts: the point is the mapping row, and the entry API would drag
    session and draft policy into a test about axis survival.
    """
    session_id = _session(user_db, exam)
    entry_id = user_db.execute(
        "INSERT INTO question_entries "
        "(review_session_id, entry_order, user_answer, correct_answer) "
        "VALUES (?, ?, 'A', 'B')", (session_id, order)).lastrowid
    for subject_id in subject_ids:
        user_db.execute(
            "INSERT INTO entry_subject_mappings "
            "(question_entry_id, subject_node_id, mapping_type) "
            "VALUES (?, ?, 'primary')", (entry_id, subject_id))
    user_db.conn.commit()
    return entry_id


# ============================ the feature ============================

def test_a_three_axis_file_creates_three_dimensions_each_with_its_own_tree(
        user_db, exam):
    """The headline. One file, three axes, three trees."""
    result = user_db.apply_whole_exam_import(exam.id, [
        _axis('System', _node('Cardiovascular', children=[_node('Heart Failure')]),
              id='ax-sys', display_order=1),
        _axis('Discipline', _node('Pathology'), id='ax-disc', display_order=2),
        _axis('Physician Task', _node('Diagnosis'), id='ax-task', display_order=3),
    ])

    assert len(result['created_dimension_ids']) == 3
    assert _axis_names(user_db, exam) == ['System', 'Discipline', 'Physician Task']

    dimensions = {d['name']: d['id'] for d in user_db.get_exam_dimensions(exam.id)}
    assert set(_subjects_in(user_db, dimensions['System'])) == {
        'Cardiovascular', 'Heart Failure'}
    assert set(_subjects_in(user_db, dimensions['Discipline'])) == {'Pathology'}
    assert set(_subjects_in(user_db, dimensions['Physician Task'])) == {'Diagnosis'}


def test_match_candidates_do_not_leak_between_axes(user_db, exam):
    """An identical name in two axes is two subjects (#241 acceptance).

    The axes are overlapping partitions of one item pool, so the same word
    appearing in two of them is normal rather than a duplicate. If the scopes
    bled, the second axis would "match" the first axis's subject and the tree
    it was supposed to create would be one node short -- and the first axis's
    subject would be silently re-parented.
    """
    user_db.apply_whole_exam_import(exam.id, [
        _axis('System', _node('Renal'), id='ax-sys', display_order=1),
        _axis('Discipline', _node('Renal'), id='ax-disc', display_order=2),
    ])

    dimensions = {d['name']: d['id'] for d in user_db.get_exam_dimensions(exam.id)}
    system = _subjects_in(user_db, dimensions['System'])
    discipline = _subjects_in(user_db, dimensions['Discipline'])

    assert set(system) == {'Renal'}
    assert set(discipline) == {'Renal'}
    assert system['Renal'] != discipline['Renal'], (
        'the two axes share one subject row, so their scopes bled'
    )


def test_one_axis_plans_identically_to_a_single_tree_import(user_db, exam):
    """The delegation is real, not a parallel implementation (#67).

    A one-axis whole-exam file and a single-dimension import of the same tree
    must produce the same subject plan, because they are supposed to be the
    same code reached two ways. This is the test that fails if anyone
    "optimises" the multi-axis path into its own matcher.
    """
    dimension_id = _dimension(user_db, exam, 'System', 1)
    _subject(user_db, exam, 'Cardiovascular', dimension_id)

    tree = [_node('Cardiovascular', children=[_node('Heart Failure')]),
            _node('Renal')]

    single = user_db.plan_subject_import(exam.id, tree, dimension_id=dimension_id)
    whole = user_db.plan_whole_exam_import(
        exam.id, [_axis('System', *tree, display_order=1)])

    assert len(whole['axes']) == 1
    axis_plan = whole['axes'][0]['plan']

    for key in ('counts', 'coverage', 'added', 'updated', 'unchanged',
                'removed', 'kept_in_use', 'kept_as_ancestor', 'renamed',
                'moved', 'rename_blind', 'empty_file', 'file_node_count',
                'errors', 'dimension_id'):
        assert axis_plan[key] == single[key], f'{key} diverged'


# ======================= coverage, per axis only =======================

def test_coverage_is_reported_per_axis(user_db, exam):
    """#241 acceptance: several bands, not one.

    The two figures here are real: 84-153% and 78-113% are the summed
    published ranges of two of the Step 2 CK tables.
    """
    plan = user_db.plan_whole_exam_import(exam.id, [
        _axis('System', _node('A', weight={'low': 40, 'high': 80}),
              _node('B', weight={'low': 44, 'high': 73}), display_order=1),
        _axis('Discipline', _node('C', weight={'low': 38, 'high': 60}),
              _node('D', weight={'low': 40, 'high': 53}), display_order=2),
    ])

    bands = [(a['coverage']['low'], a['coverage']['high']) for a in plan['axes']]
    assert bands == [(84.0, 153.0), (78.0, 113.0)]


def test_there_is_no_combined_coverage(user_db, exam):
    """Enforced by an absence, so it is asserted (#64, §10).

    Summing across axes would report 162-266% of an exam, which is not a
    number about anything. Normalising it would store weights that do not
    match the document the student copied from.
    """
    plan = user_db.plan_whole_exam_import(exam.id, [
        _axis('System', _node('A', weight=50), display_order=1),
        _axis('Discipline', _node('C', weight=50), display_order=2),
    ])

    assert 'coverage' not in plan, (
        'a whole-exam plan grew a combined coverage figure; coverage is per '
        'axis and never summed'
    )


def test_a_coverage_warning_names_its_axis(user_db, exam):
    """Three axes means three possible coverage sentences.

    An unlabelled one would tell the student the exam's weights are wrong
    without saying which table to check.
    """
    plan = user_db.plan_whole_exam_import(exam.id, [
        _axis('System', _node('A', weight=100), display_order=1),
        _axis('Discipline', _node('C', weight=12), display_order=2),
    ])

    coverage_warnings = [w for w in plan['warnings'] if 'span 100%' in w]
    assert len(coverage_warnings) == 1
    assert 'Discipline' in coverage_warnings[0]


def test_a_single_tree_coverage_warning_is_unchanged(user_db, exam):
    """The axis label must not leak into the single-tree wording.

    `_import_weight_warnings` takes an optional axis name; left unset the
    sentence has to be byte-identical to what it has always been, because
    the single-tree import has no axis to name.
    """
    plan = user_db.plan_subject_import(exam.id, [_node('A', weight=12)])

    assert any(w.startswith("The file's top-level weights total 12-12%")
               or w.startswith("The file's top-level weights total 12–12%")
               for w in plan['warnings']), plan['warnings']


# ==================== the empty-list trap, twice ====================

def test_a_file_declaring_no_dimensions_removes_nothing(user_db, exam):
    """#67's "an empty file removes nothing", one level up.

    A misspelled `dimensions` key arrives here as an empty list. Reading it
    as "archive every axis" would destroy three trees over a typo, and under
    #210 that cascade is real.
    """
    system = _dimension(user_db, exam, 'System', 1)
    _subject(user_db, exam, 'Cardiovascular', system)

    result = user_db.apply_whole_exam_import(exam.id, [])

    assert result['declares_no_dimensions'] is True
    assert result['dimensions_removed'] == []
    assert result['removed_dimension_ids'] == []
    assert _axis_names(user_db, exam) == ['System']
    assert set(_subjects_in(user_db, system)) == {'Cardiovascular'}


def test_an_axis_with_no_subjects_removes_nothing_and_is_reported(user_db, exam):
    """The same trap one level down, and the one #241 names explicitly.

    A file intending several axes with `root_nodes` misspelled in one of them
    must not archive that axis's tree. `declares_no_subjects` is what lets the
    preview say so rather than reporting a silent no-op.
    """
    system = _dimension(user_db, exam, 'System', 1)
    _subject(user_db, exam, 'Cardiovascular', system)

    result = user_db.apply_whole_exam_import(exam.id, [
        {'name': 'System', 'display_order': 1, 'root_ndoes': [_node('Typo')]},
    ])

    assert result['axes'][0]['declares_no_subjects'] is True
    assert result['counts']['removed'] == 0
    assert set(_subjects_in(user_db, system)) == {'Cardiovascular'}


# ======================== axis survival (2.1) ========================

def test_an_axis_the_file_drops_is_archived_with_its_trees(user_db, exam):
    """Bottom-up survival: nothing points into it, so it goes.

    Through `archive_dimension`, which is composed of
    `delete_subject_subtree` calls -- so #67's *never a second path* holds at
    both levels and the subjects are soft-deleted and journalled.
    """
    system = _dimension(user_db, exam, 'System', 1)
    doomed = _dimension(user_db, exam, 'Obsolete Axis', 2)
    _subject(user_db, exam, 'Cardiovascular', system)
    orphan = _subject(user_db, exam, 'Nothing Here', doomed)

    result = user_db.apply_whole_exam_import(exam.id, [
        _axis('System', _node('Cardiovascular'), display_order=1),
    ])

    assert [r['name'] for r in result['dimensions_removed']] == ['Obsolete Axis']
    assert result['dimension_delete_batch_ids'], 'the archive was not journalled'
    assert _axis_names(user_db, exam) == ['System']
    assert user_db.fetchone(
        'SELECT status FROM subject_nodes WHERE id = ?',
        (orphan.id,))['status'] == 'archived'


def test_an_axis_carrying_entries_is_kept_and_reported(user_db, exam):
    """Decision 2.1: the student's history outranks the blueprint.

    A dimension carrying entries is never removed by an import, exactly as a
    subject carrying entries is not. Kept axes are reported the way
    `kept_in_use` reports kept subjects, so the student can go and re-tag.
    """
    system = _dimension(user_db, exam, 'System', 1)
    keep = _dimension(user_db, exam, 'Old Axis', 2)
    _subject(user_db, exam, 'Cardiovascular', system)
    used = _subject(user_db, exam, 'Still Tagged', keep)
    _tag_entry(user_db, exam, used.id)

    result = user_db.apply_whole_exam_import(exam.id, [
        _axis('System', _node('Cardiovascular'), display_order=1),
    ])

    assert [r['name'] for r in result['dimensions_kept_in_use']] == ['Old Axis']
    assert result['dimensions_kept_in_use'][0]['entry_count'] == 1
    assert result['dimensions_removed'] == []
    assert set(_axis_names(user_db, exam)) == {'System', 'Old Axis'}
    assert user_db.fetchone(
        'SELECT status FROM subject_nodes WHERE id = ?',
        (used.id,))['status'] == 'active'


def test_entries_affected_is_distinct_across_axes_not_summed(user_db, exam):
    """One entry tagged in two axes is one entry affected (#6's non-additivity).

    It sits on a kept subject in each axis, so both per-axis figures count it
    and the sum would report two. The top-level number is counted distinct
    over every kept subject in the file.
    """
    system = _dimension(user_db, exam, 'System', 1)
    discipline = _dimension(user_db, exam, 'Discipline', 2)
    in_system = _subject(user_db, exam, 'Dropped A', system)
    in_discipline = _subject(user_db, exam, 'Dropped B', discipline)
    _tag_entry(user_db, exam, in_system.id, in_discipline.id)

    plan = user_db.plan_whole_exam_import(exam.id, [
        _axis('System', _node('Fresh'), display_order=1),
        _axis('Discipline', _node('Fresh'), display_order=2),
    ])

    per_axis = [a['plan']['entries_affected'] for a in plan['axes']]
    assert per_axis == [1, 1]
    assert plan['entries_affected'] == 1, (
        'the per-axis figures were summed, so one entry was counted twice'
    )
    assert plan['counts']['entries_affected'] == 1


# ===================== identity and matching (2.3) =====================

def test_a_renamed_axis_is_a_rename_not_a_remove_and_add(user_db, exam):
    """This is why dimensions needed an `import_id` (m025).

    Without one, renaming an axis in the file is a remove-plus-add -- and at
    this level the remove archives every tree under it. The id makes it a
    rename, and the subjects stay put.
    """
    system = _dimension(user_db, exam, 'System', 1)
    user_db.execute("UPDATE exam_dimensions SET import_id = 'ax-sys' WHERE id = ?",
                    (system,))
    user_db.conn.commit()
    subject = _subject(user_db, exam, 'Cardiovascular', system)

    result = user_db.apply_whole_exam_import(exam.id, [
        _axis('Organ System', _node('Cardiovascular'), id='ax-sys',
              display_order=1),
    ])

    assert result['created_dimension_ids'] == []
    assert result['removed_dimension_ids'] == []
    assert result['dimensions_updated'][0]['matched_by'] == 'id'
    assert _axis_names(user_db, exam) == ['Organ System']
    assert user_db.fetchone(
        'SELECT dimension_id, status FROM subject_nodes WHERE id = ?',
        (subject.id,))['dimension_id'] == system


def test_an_axis_adopts_an_import_id_on_first_sight(user_db, exam):
    """Decision 2.3: exams set up before the field existed are not stranded."""
    system = _dimension(user_db, exam, 'System', 1)

    result = user_db.apply_whole_exam_import(exam.id, [
        _axis('System', _node('Cardiovascular'), id='ax-sys', display_order=1),
    ])

    assert result['dimensions_updated'][0]['matched_by'] == 'name'
    assert user_db.fetchone(
        'SELECT import_id FROM exam_dimensions WHERE id = ?',
        (system,))['import_id'] == 'ax-sys'


def test_an_id_match_beats_a_name_match(user_db, exam):
    """Ids are matched in a first pass, before any name can claim a row.

    If a name match could take a dimension out from under the axis carrying
    its id, that axis would fall through to a create, and the create would
    write an `import_id` the claimed row still holds -- a unique-index
    failure on a well-formed file.
    """
    first = _dimension(user_db, exam, 'System', 1)
    second = _dimension(user_db, exam, 'Discipline', 2)
    user_db.execute("UPDATE exam_dimensions SET import_id = 'ax-a' WHERE id = ?",
                    (second,))
    user_db.conn.commit()

    plan = user_db.plan_whole_exam_import(exam.id, [
        _axis('Discipline', id='ax-b', display_order=1),
        _axis('Anything', id='ax-a', display_order=2),
    ])

    matched = {a['name']: (a['dimension_id'], a['matched_by']) for a in plan['axes']}
    assert matched['Anything'] == (second, 'id')
    assert matched['Discipline'][0] is None, (
        'a name match claimed the dimension an id match had already taken'
    )


def test_two_axes_sharing_an_id_is_an_error(user_db, exam):
    plan = user_db.plan_whole_exam_import(exam.id, [
        _axis('System', id='same', display_order=1),
        _axis('Discipline', id='same', display_order=2),
    ])

    assert any('share id "same"' in e for e in plan['errors'])
    with pytest.raises(ValidationError):
        user_db.apply_whole_exam_import(exam.id, [
            _axis('System', id='same', display_order=1),
            _axis('Discipline', id='same', display_order=2),
        ])


def test_two_axes_sharing_a_name_is_an_error(user_db, exam):
    """`exam_dimensions` has UNIQUE(exam_id, name), so the file is asking for
    something the table cannot hold. A sentence, not an IntegrityError from
    three frames down (decision 2.2)."""
    plan = user_db.plan_whole_exam_import(exam.id, [
        _axis('System', display_order=1),
        _axis('system', display_order=2),
    ])

    assert any('same name' in e for e in plan['errors'])


def test_a_name_a_kept_axis_still_holds_is_an_error(user_db, exam):
    """The collision the planner cannot resolve on its own.

    An axis kept because entries point into it is still using its name, so a
    declared axis that wants that name has nowhere to go -- and inventing one
    would be worse than saying so.
    """
    keep = _dimension(user_db, exam, 'System', 1)
    used = _subject(user_db, exam, 'Tagged', keep)
    _tag_entry(user_db, exam, used.id)
    other = _dimension(user_db, exam, 'Discipline', 2)
    user_db.execute("UPDATE exam_dimensions SET import_id = 'ax-d' WHERE id = ?",
                    (other,))
    user_db.conn.commit()

    plan = user_db.plan_whole_exam_import(exam.id, [
        _axis('System', _node('Fresh'), id='ax-d', display_order=1),
    ])

    assert any('already using' in e for e in plan['errors']), plan['errors']


# ====================== display_order (2.2, #211) ======================

def test_the_planner_resolves_a_display_order_collision(user_db, exam):
    """A kept axis sitting on the order the file wants (decision 2.2).

    `UNIQUE(exam_id, display_order)` is checked per row as the statement
    runs, so this must be resolved before any write -- and it is written by
    `reorder_dimensions`, #211's park-and-assign, rather than a second
    scheme.
    """
    keep = _dimension(user_db, exam, 'Kept Axis', 1)
    used = _subject(user_db, exam, 'Tagged', keep)
    _tag_entry(user_db, exam, used.id)

    result = user_db.apply_whole_exam_import(exam.id, [
        _axis('System', _node('A'), display_order=1),
        _axis('Discipline', _node('B'), display_order=2),
    ])

    assert [r['name'] for r in result['dimensions_kept_in_use']] == ['Kept Axis']
    ordered = user_db.get_exam_dimensions(exam.id)
    assert [d['name'] for d in ordered] == ['System', 'Discipline', 'Kept Axis']
    assert [d['display_order'] for d in ordered] == [1, 2, 3]


def test_the_file_order_wins_over_file_position(user_db, exam):
    """`display_order` is what the file says the order is, not the order the
    axes happen to appear in."""
    user_db.apply_whole_exam_import(exam.id, [
        _axis('Third', _node('C'), display_order=30),
        _axis('First', _node('A'), display_order=10),
        _axis('Second', _node('B'), display_order=20),
    ])

    assert _axis_names(user_db, exam) == ['First', 'Second', 'Third']


def test_axes_with_no_declared_order_keep_file_position(user_db, exam):
    """An omitted `display_order` is not an error; the file's own sequence is
    the only other statement of intent available."""
    user_db.apply_whole_exam_import(exam.id, [
        _axis('Alpha', _node('A')),
        _axis('Beta', _node('B')),
    ])

    assert _axis_names(user_db, exam) == ['Alpha', 'Beta']


def test_two_axes_swapping_names_applies(user_db, exam):
    """The case that needs the name parked before anything is written.

    Both names are in use and both are moving, so a direct write hits
    `UNIQUE(exam_id, name)` whichever one goes first. This is the same
    park-and-assign shape #211 needed for `display_order`, for the same
    reason: SQLite has no deferred constraints.
    """
    first = _dimension(user_db, exam, 'System', 1)
    second = _dimension(user_db, exam, 'Discipline', 2)
    user_db.execute("UPDATE exam_dimensions SET import_id = 'ax-1' WHERE id = ?",
                    (first,))
    user_db.execute("UPDATE exam_dimensions SET import_id = 'ax-2' WHERE id = ?",
                    (second,))
    user_db.conn.commit()

    user_db.apply_whole_exam_import(exam.id, [
        _axis('Discipline', _node('A'), id='ax-1', display_order=1),
        _axis('System', _node('B'), id='ax-2', display_order=2),
    ])

    names = {d['id']: d['name'] for d in user_db.get_exam_dimensions(exam.id)}
    assert names[first] == 'Discipline'
    assert names[second] == 'System'


def test_a_new_axis_can_take_a_name_a_renamed_axis_is_leaving(user_db, exam):
    """Reachable whenever the file matches by id and then declares a second
    axis under the name that dimension currently holds. Parking is what makes
    the create possible."""
    existing = _dimension(user_db, exam, 'System', 1)
    user_db.execute("UPDATE exam_dimensions SET import_id = 'ax-1' WHERE id = ?",
                    (existing,))
    user_db.conn.commit()

    result = user_db.apply_whole_exam_import(exam.id, [
        _axis('Discipline', _node('A'), id='ax-1', display_order=1),
        _axis('System', _node('B'), id='ax-2', display_order=2),
    ])

    assert len(result['created_dimension_ids']) == 1
    names = {d['id']: d['name'] for d in user_db.get_exam_dimensions(exam.id)}
    assert names[existing] == 'Discipline'
    assert sorted(names.values()) == ['Discipline', 'System']


# ================== the dimensionless partition (item 6) ==================

def test_dimensionless_subjects_are_untouched(user_db, exam):
    """`_import_scope` partitions on `dimension_id IS NULL`, so the legacy
    tree is in no axis's scope at all.

    Nothing in the code says this out loud, which is exactly why it has a
    test: an axis planned against `dimension_id=None` instead of an empty
    scope would match these subjects and then archive whichever the file did
    not list.
    """
    legacy = _subject(user_db, exam, 'Legacy Root')
    _subject(user_db, exam, 'Legacy Child', None, legacy.id)

    result = user_db.apply_whole_exam_import(exam.id, [
        _axis('System', _node('Cardiovascular'), display_order=1),
    ])

    assert set(_subjects_in(user_db, None)) == {'Legacy Root', 'Legacy Child'}
    assert result['counts']['removed'] == 0
    assert result['dimensionless_subject_count'] == 2


def test_dimensionless_subjects_are_reported_not_silently_skipped(user_db, exam):
    """Said out loud, because an unstated rule is the one that gets "fixed"."""
    _subject(user_db, exam, 'Legacy Root')

    plan = user_db.plan_whole_exam_import(exam.id, [
        _axis('System', _node('A'), display_order=1)])

    assert any('not in any dimension' in w for w in plan['warnings'])


def test_no_such_note_when_every_subject_is_in_an_axis(user_db, exam):
    """Negative control: the note must not fire on every import."""
    plan = user_db.plan_whole_exam_import(exam.id, [
        _axis('System', _node('A'), display_order=1)])

    assert not any('not in any dimension' in w for w in plan['warnings'])


# ========================== apply guarantees ==========================

def test_reimporting_the_same_file_is_a_no_op(user_db, exam):
    """The merge property, at both levels."""
    file = [
        _axis('System', _node('Cardiovascular', id='s1',
                              children=[_node('Heart Failure', id='s2')]),
              id='ax-sys', display_order=1),
        _axis('Discipline', _node('Pathology', id='d1'), id='ax-disc',
              display_order=2),
    ]
    first = user_db.apply_whole_exam_import(exam.id, file)
    second = user_db.apply_whole_exam_import(exam.id, file)

    assert first['counts']['dimensions_added'] == 2
    assert second['counts']['dimensions_added'] == 0
    assert second['counts']['dimensions_unchanged'] == 2
    assert second['counts']['added'] == 0
    assert second['counts']['removed'] == 0
    assert second['counts']['unchanged'] == 3
    assert len(user_db.get_exam_dimensions(exam.id)) == 2


def test_the_whole_apply_is_atomic(user_db, exam):
    """#239's guarantee, scaled up.

    A whole-exam apply creates dimensions, fills trees and archives others.
    A failure part-way through -- three axes created, one tree imported, the
    removal pass never reached -- is a state no student can see or undo, so
    the composite rolls back entirely.

    **Provoked in the middle, on purpose.** Failing the *last* phase would
    make this test depend on which phase happens to be last: removing that
    phase would leave the test passing while asserting nothing. Failing the
    second axis's subject write instead asserts the claim that actually
    matters -- the first axis's dimension **and** its subjects are gone --
    and stays meaningful however the phases are reordered.
    """
    _dimension(user_db, exam, 'Existing', 1)

    original = user_db._apply_subject_plan
    calls = {'n': 0}

    def fail_on_the_second_axis(*args, **kwargs):
        calls['n'] += 1
        if calls['n'] == 2:
            raise RuntimeError('provoked between two axes')
        return original(*args, **kwargs)

    user_db._apply_subject_plan = fail_on_the_second_axis
    try:
        with pytest.raises(RuntimeError):
            user_db.apply_whole_exam_import(exam.id, [
                _axis('System', _node('A'), display_order=1),
                _axis('Discipline', _node('B'), display_order=2),
            ])
    finally:
        user_db._apply_subject_plan = original

    assert calls['n'] == 2, 'the failure was not provoked where intended'
    assert _axis_names(user_db, exam) == ['Existing'], (
        'dimensions created before the failure survived it'
    )
    assert user_db.fetchone(
        "SELECT COUNT(*) AS n FROM subject_nodes WHERE exam_context = ?",
        (exam.exam_name,))['n'] == 0, (
        'the first axis\'s subjects were committed before the failure'
    )


def test_a_failure_in_the_last_phase_also_rolls_back(user_db, exam):
    """The other end of the same transaction.

    Kept alongside the test above rather than instead of it: this one does
    depend on `reorder_dimensions` being the last phase, so on its own it
    would stop asserting anything if that phase moved.
    """
    _dimension(user_db, exam, 'Existing', 1)

    original = user_db.reorder_dimensions
    user_db.reorder_dimensions = lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError('provoked in the last phase'))
    try:
        with pytest.raises(RuntimeError):
            user_db.apply_whole_exam_import(exam.id, [
                _axis('System', _node('A'), display_order=1),
            ])
    finally:
        user_db.reorder_dimensions = original

    assert _axis_names(user_db, exam) == ['Existing']
    assert user_db.fetchone(
        "SELECT COUNT(*) AS n FROM subject_nodes WHERE exam_context = ?",
        (exam.exam_name,))['n'] == 0


def test_an_is_required_flag_the_file_omits_is_left_alone(user_db, exam):
    """A blueprint describes structure, not every setting the student has
    since changed. An omitted flag on an existing axis means "leave it", and
    on a new one it means `create_dimension`'s default."""
    existing = _dimension(user_db, exam, 'System', 1, is_required=False,
                          allow_multiple=True)

    user_db.apply_whole_exam_import(exam.id, [
        _axis('System', _node('A'), display_order=1),
        _axis('Fresh', _node('B'), display_order=2),
    ])

    rows = {d['name']: d for d in user_db.get_exam_dimensions(exam.id)}
    assert bool(rows['System']['is_required']) is False
    assert bool(rows['System']['allow_multiple']) is True
    assert bool(rows['Fresh']['is_required']) is True
    assert bool(rows['Fresh']['allow_multiple']) is False


def test_a_declared_flag_is_applied(user_db, exam):
    """Negative control for the test above: the flags are not being ignored."""
    _dimension(user_db, exam, 'System', 1, is_required=True, allow_multiple=False)

    user_db.apply_whole_exam_import(exam.id, [
        _axis('System', _node('A'), display_order=1, is_required=False,
              allow_multiple=True),
    ])

    row = user_db.get_exam_dimensions(exam.id)[0]
    assert bool(row['is_required']) is False
    assert bool(row['allow_multiple']) is True
