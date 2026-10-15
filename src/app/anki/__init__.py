"""WIMI's own connection to the student's AnkiConnect (#784).

``client`` talks to AnkiConnect on this machine, ``fsrs`` derives memory
estimates from a review log, and ``jobs`` keeps both off the Qt main thread.
None of the three touches the database: the domain mixin and the bridge
(later waves) own that. Plan: ``docs/planning/ANKI_INTEGRATION_IMPLEMENTATION_PLAN.md``.
"""
