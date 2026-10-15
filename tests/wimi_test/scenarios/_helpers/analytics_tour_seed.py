"""An analytics exam that draws every card the analytics tour points at (#682).

Two dimensions, so the cross-dimension heatmap, its colour key and the
Interaction Effects panel render. Weights on the first axis, so the weight
card's Quadrant Analysis, Top Recommendations and Weight Sources render. And
the entries are lopsided on purpose: Cardiology (20-30%) carries half the
mistakes, which is over 1.3 times its 30% top and files it under Priority;
Dermatology (2-4%) carries the other half, which files it under Reduce Focus,
the group the tour's quadrant step is about.

Shared by the resolve guard and the page's tour scenario, so the state the
order is pinned in is the state the anchors are proven to render in.
"""
from __future__ import annotations

from datetime import date
from typing import Any


def seed_analytics_tour_exam(db: Any, name: str) -> dict:
    """Seed the exam and return the analytics route's query."""
    exam = db.create_exam_context(exam_name=name, exam_description="")
    system = db.create_dimension(exam_id=exam.id, name="System", display_order=1)
    task = db.create_dimension(exam_id=exam.id, name="Task", display_order=2)

    def weighted(title, low, high):
        return db.create_subject_node_with_weight(
            exam_context=name, name=title, level_type="System",
            exam_weight_low=low, exam_weight_high=high, dimension_id=system).id

    def plain(title):
        return db.create_subject_node(exam_context=name, name=title,
                                      level_type="System", dimension_id=task).id

    cardiology = weighted("Cardiology", 20, 30)
    dermatology = weighted("Dermatology", 2, 4)
    diagnosis = plain("Diagnosis")
    management = plain("Management")
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=20, total_incorrect=10,
        session_name=name, date_encountered=date.today())
    for a, b, n in ((cardiology, diagnosis, 4), (cardiology, management, 1),
                    (dermatology, diagnosis, 1), (dermatology, management, 4)):
        for _ in range(n):
            db.create_question_entry(session.id, "a", "b", perceived_difficulty=3,
                                     explanation="<p>E</p>", reflection="<p>R</p>",
                                     primary_subject_ids=[a, b])
    # The weight card shows one axis at a time and, with Settings left on
    # All Dimensions, asks which (#820, owner's decision). The weighted axis
    # as the default is the state a student who has chosen one is in, and
    # the only one in which the card's tour anchors exist on load.
    db.update_exam_analytics_config(exam.id, {"default_dimension_id": system})
    db.conn.commit()
    return {"exam": exam.id}
