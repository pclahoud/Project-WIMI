-- Session Timer Rounds Schema
-- Allows multiple independent timed rounds per review session.

CREATE TABLE IF NOT EXISTS session_timer_rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_session_id INTEGER NOT NULL REFERENCES review_sessions(id) ON DELETE CASCADE,
    round_number INTEGER NOT NULL,
    duration_minutes INTEGER NOT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    actual_studied_seconds INTEGER DEFAULT 0,
    total_break_seconds INTEGER DEFAULT 0,
    timer_paused_at TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(review_session_id, round_number)
);
