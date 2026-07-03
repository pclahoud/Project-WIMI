"""User DB migration v10 — backfill definitions for seeded default error types.

The ``tags.description`` column has existed since phase 1
(``user_db_schema_v1_phase1.sql:193``) but ``seed_default_tags`` never
populated it, so every seeded mistake-type tag and group carries a NULL
description. The Error Type Management feature surfaces definitions as
tooltips in the picker and in the analytics legend, so existing users
need their seeded rows backfilled.

One operation, idempotent by construction:

    UPDATE tags SET description = ?, updated_at = CURRENT_TIMESTAMP
    WHERE tag_name = ? AND description IS NULL

for every (name, definition) pair in ``DEFAULT_DEFINITIONS``. The
``description IS NULL`` predicate makes re-runs no-ops AND guarantees a
user-edited (or user-authored) definition is never clobbered. Matching
is by ``tag_name`` across all exam contexts — the seeded names are the
same in every context, and any user-created tag that happens to share a
seeded name receives the same student-facing definition, which is the
intended meaning of that name.

``DEFAULT_DEFINITIONS`` is FROZEN — it must match the names created by
``seed_default_tags`` in ``src/database/domains/tags.py`` exactly (that
module keeps its own copy, ``_DEFAULT_TAG_DEFINITIONS``, with a
cross-reference comment pointing back here). Migrations never import
live domain code, hence the deliberate duplication. If the seeded
default set ever changes, write a NEW migration; do not edit this map.
"""
from __future__ import annotations

import sqlite3

from .._helpers import get_table_names

VERSION = 10
NAME = "default_tag_definitions"

# FROZEN — mirror of ``_DEFAULT_TAG_DEFINITIONS`` in
# ``src/database/domains/tags.py`` (kept in sync by
# ``tests/database/test_tag_management.py``). Covers every group and
# type name that ``seed_default_tags`` creates.
DEFAULT_DEFINITIONS: dict[str, str] = {
    # ------------------------------------------------------- groups
    'Knowledge Issues': "Mistakes caused by gaps or errors in what you know.",
    'Reading & Interpretation': "Mistakes from misreading or misinterpreting what the question asked.",
    'Execution Errors': "Mistakes made while working the problem, even though you knew the material.",
    'Test Strategy': "Mistakes in how you played the test itself — timing, guessing, and answer changes.",
    'Mental & Physical State': "Mistakes influenced by how you felt — stress, focus, or energy.",
    # ------------------------------------ types: Knowledge Issues
    'Knowledge Gap': "You never learned or covered this material.",
    'Memory Failure': "You studied this before but couldn't recall it when it mattered.",
    'Misunderstanding': "You learned the material but understood it incorrectly.",
    # --------------------------- types: Reading & Interpretation
    'Misread Question': "You misread or overlooked key wording in the question.",
    # ------------------------------------ types: Execution Errors
    'Calculation Error': "You set up the problem correctly but made an arithmetic slip.",
    'Careless Mistake': "You knew the answer but slipped through haste or inattention.",
    'Incomplete Solution': "You started down the right path but didn't carry the work to completion.",
    'Wrong Approach': "You chose a method or strategy that couldn't solve this problem.",
    # --------------------------------------- types: Test Strategy
    'Time Pressure': "Running low on time forced you to rush or abandon the question.",
    'Second-Guessing': "You changed a correct answer to a wrong one.",
    'Elimination Error': "You ruled out the correct answer while narrowing the choices.",
    'Poor Prioritization': "You spent your time on the wrong questions or in the wrong order.",
    'Wrong Guess Strategy': "You had to guess, and your guessing approach didn't pay off.",
    # ---------------------------- types: Mental & Physical State
    'Anxiety Related': "Nervousness or stress interfered with your thinking on this question.",
    'Focus Problem': "You lost concentration or got distracted while answering.",
    'Fatigue Related': "Tiredness or low energy dulled your performance on this question.",
}


def upgrade(conn: sqlite3.Connection) -> None:
    # Defensive: in the normal migration order m001 always creates
    # ``tags`` first. Guard so isolated-migration tests don't trip over
    # a missing table.
    if "tags" not in get_table_names(conn):
        return

    for tag_name, definition in DEFAULT_DEFINITIONS.items():
        conn.execute(
            """
            UPDATE tags
            SET description = ?, updated_at = CURRENT_TIMESTAMP
            WHERE tag_name = ? AND description IS NULL
            """,
            (definition, tag_name),
        )
