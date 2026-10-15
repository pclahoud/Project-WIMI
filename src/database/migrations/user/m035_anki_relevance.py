"""User DB migration v35 -- the Anki relevance scorer's verdicts (#784 Wave 5).

Announced on #784 comment #11052 before it was written; m035 was reserved for
this wave by the plan (``docs/planning/ANKI_INTEGRATION_IMPLEMENTATION_PLAN.md``,
*Relevance scorer*) and owner decision 14.

When one question matches several Anki cards, WIMI proposes the ones about
what the student actually missed. Nothing changes without the student's
answer, and there are two ways to say no, with different scopes:

- ``anki_card_verdicts``: the student's answer about one proposed card on one
  entry. ``confirmed`` moves the card to the top of that entry's Anki panel;
  ``not_for_entry`` stops it being proposed there. Keyed on the entry, not on
  the question's match, because the judgement is about this mistake.
- ``anki_card_subject_rejections``: *never* propose this card on the strength
  of this subject, on any entry. It needs a subject, so a proposal made only
  from the answer text can be rejected for its entry alone.

Neither table hides a card, and nothing is pushed to Anki: no ``addTags`` and
no ``updateNoteFields``. That half of the abandoned LLM design stays out.

What is deliberately absent
---------------------------
- **No ``user_id`` (#776).** Rows scope through the entry or the subject, and
  the domain checks the profile on every read and write.
- **No foreign key on ``card_id``.** ``anki_cards`` rows are replaced on each
  refresh and swept when orphaned, while a verdict has to survive a card
  dropping out of a match and coming back. A verdict on a card the cache no
  longer holds is inert.
- No trigger, no view (#593's fingerprint refuses any it does not create).
"""

from __future__ import annotations

import sqlite3

VERSION = 35
NAME = "anki_relevance"


def upgrade(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS anki_card_verdicts (
            question_entry_id INTEGER NOT NULL
                              REFERENCES question_entries(id) ON DELETE CASCADE,
            card_id           INTEGER NOT NULL,
            verdict           TEXT NOT NULL
                              CHECK (verdict IN ('confirmed', 'not_for_entry')),
            decided_at        TEXT NOT NULL,
            PRIMARY KEY (question_entry_id, card_id)
        ) WITHOUT ROWID;

        CREATE TABLE IF NOT EXISTS anki_card_subject_rejections (
            subject_node_id INTEGER NOT NULL
                            REFERENCES subject_nodes(id) ON DELETE CASCADE,
            card_id         INTEGER NOT NULL,
            decided_at      TEXT NOT NULL,
            PRIMARY KEY (subject_node_id, card_id)
        ) WITHOUT ROWID;

        CREATE INDEX IF NOT EXISTS idx_anki_card_subject_rejections_card
            ON anki_card_subject_rejections (card_id);
        """
    )
