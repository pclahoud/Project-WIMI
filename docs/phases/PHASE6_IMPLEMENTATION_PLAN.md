# Phase 6 Implementation Plan - Analytics & Patterns

**Created:** December 31, 2025
**Last Updated:** January 3, 2026
**Status:** Stage 14 Complete ✅ | Stage 15 Next 🔜
**Estimated Duration:** 53-67 hours

---

## Overview

Phase 6 implements comprehensive analytics and pattern detection for WIMI, providing users with insights into their learning patterns, mistake trends, and areas for improvement. The analytics system features a main dashboard with an overview, deep-dive views for subjects, smart pattern detection with actionable insights, and motivational features like activity heatmaps, streak tracking, and goal setting.

### Core Philosophy

WIMI's analytics are designed around **metacognitive learning** - helping students understand not just *what* they got wrong, but *why* and *how* their learning patterns evolve over time. The goal is to provide actionable insights that guide study decisions.

---

## Wireframe Reference

The following Frame0 wireframes guide this implementation:

| Page | Name | Description |
|------|------|-------------|
| 1 | Landing - Analytics Preview Card | Quick analytics summary on main dashboard |
| 2 | Analytics Dashboard - Overview | Full analytics dashboard with all sections |
| 3 | Subject Deep Dive | Detailed analysis for a specific subject |
| 4 | Analytics Dashboard - Part 2 | Heatmap, Goals, Reflection, Sources, Time/Difficulty, Self-Assessment, Subject Weight |

---

## Implementation Stages

| Stage | Focus | Duration | Status |
|-------|-------|----------|--------|
| 1 | Database Methods for Analytics | 6-7 hours | ✅ Complete |
| 2 | Analytics Dashboard - Overview Section | 4-5 hours | ✅ Complete |
| 3 | Subject Analysis with D3.js Charts | 5-6 hours | ✅ Complete |
| 4 | Tag/Mistake Type Analysis with D3.js | 4-5 hours | ✅ Complete |
| 5 | Activity Trends & Time Charts | 4-5 hours | ✅ Complete |
| 6 | Pattern Detection & Insights Engine | 4-5 hours | ✅ Complete |
| 7 | Study Heatmap & Streak Tracking | 3-4 hours | ✅ Complete |
| 8 | Goal Setting System | 2-3 hours | ✅ Complete |
| 9 | Reflection Quality & Common Patterns | 3-4 hours | ⏸️ Skipped |
| 10 | Source Comparison & Performance Over Time | 3-4 hours | ✅ Complete |
| 11 | Time Spent vs Difficulty Analysis | 2-3 hours | ⏸️ Skipped |
| 12 | Self-Assessment Accuracy | 2-3 hours | ⏸️ Skipped |
| 13 | Subject vs Exam Weight Analysis | 2-3 hours | ✅ Complete |
| 14 | Landing Page Analytics Preview | 3-4 hours | ✅ Complete |
| 15 | Testing & Polish | 5-6 hours | 🔜 Next |
| **Total** | | **53-67 hours** | |

---

## Stage 1: Database Methods for Analytics

### New Database Methods (user_db.py)

```python
# =============================================================================
# CORE ANALYTICS METHODS
# =============================================================================

def get_analytics_overview(
    self,
    exam_context_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Get high-level analytics overview for the dashboard.
    
    Returns:
        {
            'total_entries': int,
            'completed_entries': int,
            'draft_entries': int,
            'total_sessions': int,
            'completed_sessions': int,
            'this_week': int,
            'last_week': int,
            'week_change': int,
            'this_month': int,
            'avg_difficulty': float,
            'completion_rate': float
        }
    """

def get_subject_analytics(
    self,
    exam_context_id: Optional[int] = None,
    limit: int = 10,
    include_children: bool = True
) -> List[Dict[str, Any]]:
    """
    Get mistake counts by subject for visualization.
    
    Returns:
        [
            {
                'subject_id': int,
                'subject_name': str,
                'full_path': str,
                'mistake_count': int,
                'percentage': float,
                'exam_weight': float,
                'avg_difficulty': float,
                'last_mistake_date': str,
                'trend': str
            },
            ...
        ]
    """

def get_tag_analytics(
    self,
    exam_context_id: Optional[int] = None,
    group_by_parent: bool = True
) -> Dict[str, Any]:
    """
    Get mistake type distribution by tags.
    
    Returns:
        {
            'total_tagged': int,
            'by_group': {
                'Mistake Type': [...],
                'Priority': [...],
                'Status': [...]
            },
            'top_tags': [...]
        }
    """

def get_difficulty_distribution(
    self,
    exam_context_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Get distribution of entries by difficulty level.
    
    Returns:
        {
            'distribution': {
                1: {'count': int, 'percentage': float, 'label': 'Easy'},
                2: {'count': int, 'percentage': float, 'label': 'Moderate'},
                3: {'count': int, 'percentage': float, 'label': 'Medium'},
                4: {'count': int, 'percentage': float, 'label': 'Hard'},
                5: {'count': int, 'percentage': float, 'label': 'Very Hard'}
            },
            'average': float,
            'total_rated': int
        }
    """

def get_activity_over_time(
    self,
    exam_context_id: Optional[int] = None,
    period: str = '7d',
    granularity: str = 'day'
) -> List[Dict[str, Any]]:
    """
    Get entry counts over time for trend charts.
    
    Returns:
        [
            {
                'date': str,
                'label': str,
                'count': int,
                'cumulative': int
            },
            ...
        ]
    """

def get_patterns_and_insights(
    self,
    exam_context_id: Optional[int] = None,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """
    Detect patterns and generate actionable insights.
    
    Pattern Types:
    1. SUBJECT_INCREASE - Subject mistakes increased significantly
    2. SUBJECT_DECREASE - Subject mistakes decreased (success!)
    3. TAG_HIGH_FREQUENCY - A tag appears in >20% of entries
    4. TAG_TRENDING_UP - A tag is appearing more frequently
    5. DIFFICULTY_SKEW - Most mistakes are hard/very hard
    6. INACTIVE_PERIOD - No entries for >7 days
    7. SESSION_INCOMPLETE - Many incomplete sessions
    8. SUBJECT_WEIGHT_MISMATCH - High mistakes in low-weight subject
    9. STREAK_AT_RISK - Current streak may break today
    10. GOAL_PROGRESS - Goal completion status
    11. REFLECTION_QUALITY_LOW - Reflections need more depth
    12. SOURCE_STRUGGLING - Struggling with a particular source
    13. TIME_DIFFICULTY_MISMATCH - Spending too little time on hard questions
    14. SELF_ASSESSMENT_BIAS - Consistently over/underrating difficulty
    15. COMMON_REFLECTION_THEME - Recurring theme in reflections
    
    Returns:
        [
            {
                'type': str,
                'icon': str,
                'message': str,
                'detail': str,
                'action': str,
                'related_id': int,
                'related_type': str
            },
            ...
        ]
    """

def get_subject_deep_dive(
    self,
    subject_id: int,
    exam_context_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Get detailed analytics for a specific subject.
    
    Returns:
        {
            'subject': {
                'id': int,
                'name': str,
                'full_path': str,
                'exam_weight': float
            },
            'stats': {
                'total_mistakes': int,
                'percentage_of_total': float,
                'avg_difficulty': float,
                'last_mistake': str,
                'first_mistake': str
            },
            'trend': {
                'this_week': int,
                'last_week': int,
                'change': int,
                'direction': str
            },
            'by_week': [...],
            'child_subjects': [...],
            'common_tags': [...],
            'recent_entries': [...],
            'related_subjects': [...],
            'recommendations': [...]
        }
    """

def get_tag_deep_dive(
    self,
    tag_id: int,
    exam_context_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Get detailed analytics for a specific tag/mistake type.
    
    Returns:
        {
            'tag': {
                'id': int,
                'name': str,
                'color': str,
                'group_name': str
            },
            'stats': {
                'total_entries': int,
                'percentage_of_total': float,
                'this_week': int,
                'last_week': int,
                'trend_direction': str
            },
            'by_week': [...],
            'by_subject': [...],
            'by_difficulty': {...},
            'recent_entries': [...],
            'co_occurring_tags': [...]
        }
    """

def get_weekly_comparison(
    self,
    exam_context_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Compare this week vs last week for trend indicators.
    
    Returns:
        {
            'this_week': {
                'entries': int,
                'sessions': int,
                'avg_difficulty': float,
                'top_subject': str,
                'top_tag': str
            },
            'last_week': {...},
            'changes': {
                'entries_change': int,
                'entries_change_pct': float,
                'difficulty_change': float,
                ...
            }
        }
    """

# =============================================================================
# HEATMAP & STREAK METHODS
# =============================================================================

def get_activity_heatmap(
    self,
    exam_context_id: Optional[int] = None,
    weeks: int = 16
) -> Dict[str, Any]:
    """
    Get activity data for GitHub-style heatmap visualization.
    
    Returns:
        {
            'days': [
                {'date': '2025-12-25', 'count': 5, 'level': 3},
                ...
            ],
            'current_streak': 7,
            'longest_streak': 14,
            'total_active_days': 45,
            'week_start': 'sunday'
        }
    """

def get_streak_info(
    self,
    exam_context_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Get detailed streak information.
    
    Returns:
        {
            'current_streak': int,
            'longest_streak': int,
            'streak_start_date': str,
            'last_active_date': str,
            'is_active_today': bool,
            'streak_at_risk': bool
        }
    """

# =============================================================================
# GOAL SETTING METHODS
# =============================================================================

def get_user_goals(
    self,
    exam_context_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Get user's active goals.
    
    Returns:
        [
            {
                'goal_id': int,
                'goal_type': 'weekly_entries',
                'target_value': 20,
                'current_value': 15,
                'period_start': '2025-12-29',
                'period_end': '2026-01-04',
                'progress_pct': 75.0,
                'is_complete': False,
                'exam_context_id': int or None
            },
            ...
        ]
    """

def set_weekly_goal(
    self,
    target_entries: int,
    exam_context_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Set or update weekly entry goal.
    
    Returns:
        {
            'goal_id': int,
            'target_value': int,
            'message': 'Goal set successfully'
        }
    """

def get_goal_history(
    self,
    exam_context_id: Optional[int] = None,
    weeks: int = 8
) -> List[Dict[str, Any]]:
    """
    Get history of goal completion.
    
    Returns:
        [
            {
                'week_start': '2025-12-22',
                'target': 20,
                'achieved': 18,
                'completed': False,
                'completion_pct': 90.0
            },
            ...
        ]
    """

# =============================================================================
# REFLECTION QUALITY & COMMON PATTERNS METHODS
# =============================================================================

def get_reflection_quality_stats(
    self,
    exam_context_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Get aggregate reflection quality statistics.
    
    Returns:
        {
            'average_score': 3.2,
            'total_analyzed': 150,
            'score_distribution': {1: 10, 2: 25, 3: 60, 4: 40, 5: 15},
            'trend': 'improving',
            'this_week_avg': 3.5,
            'last_week_avg': 3.1,
            'insights': [...]
        }
    """

def calculate_reflection_quality(
    self,
    reflection_text: str
) -> Dict[str, Any]:
    """
    Calculate quality score for a single reflection.
    Used internally when saving entries.
    
    Scoring criteria:
    - Length (not too short, not excessive)
    - Causal language ("because", "since", "due to")
    - Action language ("I should", "next time", "I will")
    - Self-questioning ("why did I", "what made me")
    - Specificity (concrete details vs vague statements)
    
    Returns:
        {
            'score': 3.5,
            'word_count': 45,
            'criteria': {
                'length': True,
                'has_causal': True,
                'has_action': True,
                'has_questioning': False,
                'has_specificity': True
            }
        }
    """

def get_common_reflection_patterns(
    self,
    exam_context_id: Optional[int] = None,
    limit: int = 10
) -> Dict[str, Any]:
    """
    Analyze reflections to identify common themes and patterns.
    
    Uses keyword extraction and frequency analysis to find:
    - Common phrases/themes in reflections
    - Recurring mistake patterns mentioned
    - Frequently mentioned concepts/topics
    
    Returns:
        {
            'themes': [
                {
                    'theme': 'rushing through questions',
                    'frequency': 23,
                    'percentage': 15.3,
                    'sample_entries': [entry_id, ...],
                    'related_tags': ['Careless Error', 'Time Pressure']
                },
                ...
            ],
            'word_cloud_data': [
                {'word': 'forgot', 'count': 45},
                {'word': 'confused', 'count': 38},
                {'word': 'misread', 'count': 32},
                ...
            ],
            'causal_phrases': [
                {'phrase': 'because I', 'count': 67},
                {'phrase': 'due to', 'count': 34},
                ...
            ],
            'action_phrases': [
                {'phrase': 'next time', 'count': 45},
                {'phrase': 'should have', 'count': 38},
                ...
            ],
            'total_reflections_analyzed': 150
        }
    """

# =============================================================================
# SOURCE COMPARISON & PERFORMANCE OVER TIME METHODS
# =============================================================================

def get_source_analytics(
    self,
    exam_context_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Get performance analytics by question source.
    
    Returns:
        [
            {
                'source_id': int,
                'source_name': 'UWorld',
                'entry_count': 45,
                'percentage': 26.2,
                'avg_difficulty': 3.8,
                'top_mistake_type': 'Knowledge Gap',
                'top_subject': 'Cardiology',
                'this_week': 8,
                'last_week': 12,
                'trend': 'improving'
            },
            ...
        ]
    """

def get_source_deep_dive(
    self,
    source_id: int,
    exam_context_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Get detailed analytics for a specific source.
    
    Returns:
        {
            'source': {
                'id': int,
                'name': str
            },
            'stats': {
                'total_entries': int,
                'avg_difficulty': float,
                'first_entry': str,
                'last_entry': str
            },
            'by_week': [...],
            'by_subject': [...],
            'by_tag': [...],
            'difficulty_distribution': {...}
        }
    """

def get_source_performance_over_time(
    self,
    exam_context_id: Optional[int] = None,
    period: str = '90d',
    granularity: str = 'week'
) -> Dict[str, Any]:
    """
    Track how performance with each source changes over time.
    
    Returns:
        {
            'sources': [
                {
                    'source_id': int,
                    'source_name': 'UWorld',
                    'data_points': [
                        {
                            'period_start': '2025-10-01',
                            'period_end': '2025-10-07',
                            'entry_count': 12,
                            'avg_difficulty': 3.5
                        },
                        ...
                    ],
                    'overall_trend': 'improving',
                    'trend_slope': -0.5
                },
                ...
            ],
            'period': '90d',
            'granularity': 'week'
        }
    """

# =============================================================================
# TIME SPENT VS DIFFICULTY ANALYSIS METHODS
# =============================================================================

def get_time_vs_difficulty_analysis(
    self,
    exam_context_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Analyze correlation between time spent and difficulty rating.
    
    Returns:
        {
            'by_difficulty': {
                1: {'avg_time_seconds': 45, 'median_time': 40, 'count': 12},
                2: {'avg_time_seconds': 68, 'median_time': 60, 'count': 22},
                3: {'avg_time_seconds': 95, 'median_time': 90, 'count': 58},
                4: {'avg_time_seconds': 120, 'median_time': 110, 'count': 52},
                5: {'avg_time_seconds': 150, 'median_time': 140, 'count': 28}
            },
            'scatter_data': [
                {'difficulty': 3, 'time_seconds': 95, 'entry_id': 123},
                ...
            ],
            'correlation_coefficient': 0.72,
            'insights': [...],
            'recommended_times': {...}
        }
    """

def get_time_distribution(
    self,
    exam_context_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Get distribution of time spent across all entries.
    
    Returns:
        {
            'distribution': {
                '0-30s': {'count': 15, 'percentage': 8.7},
                '30-60s': {'count': 35, 'percentage': 20.3},
                '60-90s': {'count': 48, 'percentage': 27.9},
                '90-120s': {'count': 42, 'percentage': 24.4},
                '120-180s': {'count': 22, 'percentage': 12.8},
                '180s+': {'count': 10, 'percentage': 5.8}
            },
            'average_time': 87,
            'median_time': 82,
            'total_time_hours': 4.2,
            'entries_with_time': 172,
            'entries_without_time': 5
        }
    """

# =============================================================================
# SELF-ASSESSMENT ACCURACY METHODS
# =============================================================================

def get_self_assessment_accuracy(
    self,
    exam_context_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Analyze how accurately users rate their own difficulty perception.
    
    Returns:
        {
            'accuracy_score': 78.5,
            'bias': 'slight_overconfidence',
            'bias_amount': -0.3,
            'by_actual_difficulty': {...},
            'confusion_matrix': {...},
            'trend_over_time': [...],
            'insights': [...],
            'by_subject': [...],
            'by_tag': [...]
        }
    """

# =============================================================================
# SUBJECT VS EXAM WEIGHT ANALYSIS METHODS
# =============================================================================

def get_subject_exam_weight_analysis(
    self,
    exam_context_id: int
) -> Dict[str, Any]:
    """
    Compare mistake distribution against exam weight distribution.
    
    Returns:
        {
            'subjects': [...],
            'quadrant_analysis': {
                'priority': [...],
                'under_studied': [...],
                'over_studied': [...],
                'low_priority': [...]
            },
            'scatter_data': [...],
            'correlation': 0.45,
            'efficiency_score': 72,
            'insights': [...],
            'recommendations': [...]
        }
    """

def get_study_efficiency_score(
    self,
    exam_context_id: int
) -> Dict[str, Any]:
    """
    Calculate overall study efficiency based on mistake/weight alignment.
    
    Returns:
        {
            'overall_score': 72,
            'interpretation': 'Good',
            'trend': 'improving',
            'breakdown': {...},
            'comparison': {...}
        }
    """
```

### Database Schema Additions

```sql
-- Goal tracking table
CREATE TABLE IF NOT EXISTS user_goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_type TEXT NOT NULL DEFAULT 'weekly_entries',
    target_value INTEGER NOT NULL,
    exam_context_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (exam_context_id) REFERENCES exam_contexts(id)
);

-- Goal history/completion tracking
CREATE TABLE IF NOT EXISTS goal_periods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    target_value INTEGER NOT NULL,
    achieved_value INTEGER DEFAULT 0,
    is_complete BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (goal_id) REFERENCES user_goals(id)
);

-- Reflection quality scores (cached per entry)
ALTER TABLE question_entries ADD COLUMN reflection_quality_score REAL;

-- Reflection themes cache (for common patterns analysis)
CREATE TABLE IF NOT EXISTS reflection_themes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_context_id INTEGER,
    theme TEXT NOT NULL,
    frequency INTEGER DEFAULT 0,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sample_entry_ids TEXT,  -- JSON array of entry IDs
    related_tag_ids TEXT,   -- JSON array of tag IDs
    FOREIGN KEY (exam_context_id) REFERENCES exam_contexts(id)
);
```

### New Bridge Methods (bridge.py)

```python
# =============================================================================
# ANALYTICS BRIDGE METHODS
# =============================================================================

@pyqtSlot(str, result=str)
def getAnalyticsOverview(self, params_json: str) -> str:
    """Get high-level analytics overview."""

@pyqtSlot(str, result=str)
def getSubjectAnalytics(self, params_json: str) -> str:
    """Get subject-level analytics for charts."""

@pyqtSlot(str, result=str)
def getTagAnalytics(self, params_json: str) -> str:
    """Get tag/mistake type analytics."""

@pyqtSlot(str, result=str)
def getDifficultyDistribution(self, params_json: str) -> str:
    """Get difficulty level distribution."""

@pyqtSlot(str, result=str)
def getActivityOverTime(self, params_json: str) -> str:
    """Get activity data for trend charts."""

@pyqtSlot(str, result=str)
def getPatternsAndInsights(self, params_json: str) -> str:
    """Get detected patterns and insights."""

@pyqtSlot(int, str, result=str)
def getSubjectDeepDive(self, subject_id: int, params_json: str) -> str:
    """Get detailed analytics for a subject."""

@pyqtSlot(int, str, result=str)
def getTagDeepDive(self, tag_id: int, params_json: str) -> str:
    """Get detailed analytics for a tag."""

@pyqtSlot(str, result=str)
def getWeeklyComparison(self, params_json: str) -> str:
    """Get week-over-week comparison data."""

# HEATMAP & STREAK
@pyqtSlot(str, result=str)
def getActivityHeatmap(self, params_json: str) -> str:
    """Get activity heatmap data."""

@pyqtSlot(str, result=str)
def getStreakInfo(self, params_json: str) -> str:
    """Get streak information."""

# GOAL SETTING
@pyqtSlot(str, result=str)
def getUserGoals(self, params_json: str) -> str:
    """Get user's active goals."""

@pyqtSlot(int, str, result=str)
def setWeeklyGoal(self, target: int, params_json: str) -> str:
    """Set weekly entry goal."""

@pyqtSlot(str, result=str)
def getGoalHistory(self, params_json: str) -> str:
    """Get goal completion history."""

# REFLECTION QUALITY & PATTERNS
@pyqtSlot(str, result=str)
def getReflectionQualityStats(self, params_json: str) -> str:
    """Get aggregate reflection quality statistics."""

@pyqtSlot(str, result=str)
def getCommonReflectionPatterns(self, params_json: str) -> str:
    """Get common themes and patterns in reflections."""

# SOURCE COMPARISON
@pyqtSlot(str, result=str)
def getSourceAnalytics(self, params_json: str) -> str:
    """Get source comparison analytics."""

@pyqtSlot(int, str, result=str)
def getSourceDeepDive(self, source_id: int, params_json: str) -> str:
    """Get detailed analytics for a source."""

@pyqtSlot(str, result=str)
def getSourcePerformanceOverTime(self, params_json: str) -> str:
    """Get source performance trends over time."""

# TIME VS DIFFICULTY
@pyqtSlot(str, result=str)
def getTimeVsDifficultyAnalysis(self, params_json: str) -> str:
    """Get time spent vs difficulty correlation analysis."""

@pyqtSlot(str, result=str)
def getTimeDistribution(self, params_json: str) -> str:
    """Get distribution of time spent across entries."""

# SELF-ASSESSMENT ACCURACY
@pyqtSlot(str, result=str)
def getSelfAssessmentAccuracy(self, params_json: str) -> str:
    """Get self-assessment accuracy analysis."""

# SUBJECT VS EXAM WEIGHT
@pyqtSlot(str, result=str)
def getSubjectExamWeightAnalysis(self, params_json: str) -> str:
    """Get subject vs exam weight comparison."""

@pyqtSlot(str, result=str)
def getStudyEfficiencyScore(self, params_json: str) -> str:
    """Get overall study efficiency score."""
```

### New API Methods (api.js)

```javascript
// =============================================================================
// ANALYTICS API METHODS
// =============================================================================

// Core Analytics
async getAnalyticsOverview(params = {}) { }
async getSubjectAnalytics(params = {}) { }
async getTagAnalytics(params = {}) { }
async getDifficultyDistribution(params = {}) { }
async getActivityOverTime(params = {}) { }
async getPatternsAndInsights(params = {}) { }
async getSubjectDeepDive(subjectId, params = {}) { }
async getTagDeepDive(tagId, params = {}) { }
async getWeeklyComparison(params = {}) { }

// Heatmap & Streak
async getActivityHeatmap(params = {}) { }
async getStreakInfo(params = {}) { }

// Goal Setting
async getUserGoals(params = {}) { }
async setWeeklyGoal(target, params = {}) { }
async getGoalHistory(params = {}) { }

// Reflection Quality & Patterns
async getReflectionQualityStats(params = {}) { }
async getCommonReflectionPatterns(params = {}) { }

// Source Comparison
async getSourceAnalytics(params = {}) { }
async getSourceDeepDive(sourceId, params = {}) { }
async getSourcePerformanceOverTime(params = {}) { }

// Time vs Difficulty
async getTimeVsDifficultyAnalysis(params = {}) { }
async getTimeDistribution(params = {}) { }

// Self-Assessment Accuracy
async getSelfAssessmentAccuracy(params = {}) { }

// Subject vs Exam Weight
async getSubjectExamWeightAnalysis(params = {}) { }
async getStudyEfficiencyScore(params = {}) { }
```

---

## Stage 2: Analytics Dashboard - Overview Section

### Files to Create

| File | Purpose |
|------|---------|
| `src/web/html/analytics.html` | Main analytics dashboard page |
| `src/web/js/analytics.js` | Dashboard logic and chart initialization |
| `src/web/css/analytics.css` | Analytics-specific styles |

### Dashboard Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ← Back to Dashboard        📊 Analytics Dashboard        [All Exams ▼] │
├─────────────────────────────────────────────────────────────────────────┤
│ OVERVIEW                                                                │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐    │
│ │ TOTAL        │ │ THIS WEEK    │ │ SESSIONS     │ │ AVG          │    │
│ │ ENTRIES      │ │              │ │              │ │ DIFFICULTY   │    │
│ │    172       │ │   23 ↑+8     │ │   14         │ │   3.2        │    │
│ │              │ │ from last wk │ │ 12 completed │ │ out of 5     │    │
│ └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘    │
├─────────────────────────────────────────────────────────────────────────┤
│ MISTAKES BY SUBJECT              │ MISTAKE TYPE BREAKDOWN              │
│ ┌────────────────────────────┐   │ ┌────────────────────────────────┐  │
│ │  [Sunburst/Pie Chart]      │   │ │  [Donut Chart]    Legend       │  │
│ │                            │   │ │                   ● Careless   │  │
│ │      All                   │   │ │     172          ● Knowledge   │  │
│ │    Subjects                │   │ │     total        ● Misread     │  │
│ │                            │   │ │                   ● Time        │  │
│ │  Click segment to zoom     │   │ │                   ● Other       │  │
│ └────────────────────────────┘   │ └────────────────────────────────┘  │
│       Subject Deep Dive →        │       Mistake Types Deep Dive →     │
├─────────────────────────────────────────────────────────────────────────┤
│ ACTIVITY OVER TIME                                                      │
│ [7 Days] [30 Days] [90 Days] [All Time]                                │
│ ┌───────────────────────────────────────────────────────────────────┐  │
│ │                              ●                                     │  │
│ │              ●      ●   ●       ●                                  │  │
│ │    ●    ●                           [Area Chart with Line]         │  │
│ │ Mon  Tue  Wed  Thu  Fri  Sat  Sun  Today                          │  │
│ └───────────────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────────────┤
│ DIFFICULTY DISTRIBUTION          │ PATTERNS & INSIGHTS                 │
│ ┌────────────────────────────┐   │ ┌────────────────────────────────┐  │
│ │ ● Easy      ████ 12 (7%)   │   │ │ 💡 Cardiology mistakes ↑40%    │  │
│ │ ●● Moderate ██████ 22(13%) │   │ │ ⚠️ "Careless Error" at 26%     │  │
│ │ ●●● Medium  █████████ 58   │   │ │ ✓ Biochemistry down 35%        │  │
│ │ ●●●● Hard   ███████ 52     │   │ │                                │  │
│ │ ●●●●● V.Hard████ 28        │   │ │                                │  │
│ └────────────────────────────┘   │ └────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key Components

1. **Header Bar**
   - Back to Dashboard link
   - Page title with icon
   - Exam context selector dropdown

2. **Overview Stats Row**
   - 4 stat cards in a row
   - Each shows: label, value, optional trend/subtitle
   - Real-time updates when exam filter changes

3. **Charts Row 1: Subject & Tag Analysis**
   - Side-by-side layout (50/50)
   - Subject chart: Sunburst or pie chart
   - Tag chart: Donut chart with legend
   - "Deep Dive →" links below each

4. **Charts Row 2: Activity Over Time**
   - Full-width area/line chart
   - Period selector tabs (7d, 30d, 90d, all)
   - Hover tooltips for data points
   - "Today" highlighted

5. **Bottom Row: Difficulty & Insights**
   - Side-by-side layout (50/50)
   - Difficulty: Horizontal bar chart
   - Insights: Colored alert cards

### HTML Structure

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Analytics Dashboard - WIMI</title>
    <link rel="stylesheet" href="../css/styles.css">
    <link rel="stylesheet" href="../css/analytics.css">
</head>
<body>
    <div class="analytics-container">
        <!-- Header -->
        <header class="analytics-header">
            <a href="index.html" class="back-link">← Back to Dashboard</a>
            <h1>📊 Analytics Dashboard</h1>
            <div class="exam-filter">
                <select id="examContextSelect">
                    <option value="">All Exams</option>
                </select>
            </div>
        </header>

        <!-- Overview Stats -->
        <section class="stats-row">
            <div class="stat-card" id="totalEntries">
                <span class="stat-label">TOTAL ENTRIES</span>
                <span class="stat-value">--</span>
            </div>
            <div class="stat-card" id="thisWeek">
                <span class="stat-label">THIS WEEK</span>
                <span class="stat-value">--</span>
                <span class="stat-trend"></span>
            </div>
            <div class="stat-card" id="sessions">
                <span class="stat-label">SESSIONS</span>
                <span class="stat-value">--</span>
                <span class="stat-subtitle"></span>
            </div>
            <div class="stat-card" id="avgDifficulty">
                <span class="stat-label">AVG DIFFICULTY</span>
                <span class="stat-value">--</span>
                <span class="stat-subtitle">out of 5</span>
            </div>
        </section>

        <!-- Subject & Tag Charts -->
        <section class="charts-row">
            <div class="chart-container half">
                <h3>MISTAKES BY SUBJECT</h3>
                <div id="subjectChart"></div>
                <a href="#" class="deep-dive-link" data-target="subject">
                    Subject Deep Dive →
                </a>
            </div>
            <div class="chart-container half">
                <h3>MISTAKE TYPE BREAKDOWN</h3>
                <div id="tagChart"></div>
            </div>
        </section>

        <!-- Activity Chart -->
        <section class="chart-container full">
            <h3>ACTIVITY OVER TIME</h3>
            <div class="period-tabs">
                <button class="period-tab active" data-period="7d">7 Days</button>
                <button class="period-tab" data-period="30d">30 Days</button>
                <button class="period-tab" data-period="90d">90 Days</button>
                <button class="period-tab" data-period="all">All Time</button>
            </div>
            <div id="activityChart"></div>
        </section>

        <!-- Difficulty & Insights -->
        <section class="charts-row">
            <div class="chart-container half">
                <h3>DIFFICULTY DISTRIBUTION</h3>
                <div id="difficultyChart"></div>
            </div>
            <div class="chart-container half">
                <h3>PATTERNS & INSIGHTS</h3>
                <div id="insightsContainer"></div>
            </div>
        </section>
    </div>

    <script src="../js/lib/d3.min.js"></script>
    <script src="../js/api.js"></script>
    <script src="../js/analytics.js"></script>
</body>
</html>
```

### CSS Styles (analytics.css)

```css
/* Analytics Dashboard Styles */

.analytics-container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 20px;
}

.analytics-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16px 0;
    border-bottom: 1px solid var(--border-color);
    margin-bottom: 24px;
}

.back-link {
    color: var(--primary-color);
    text-decoration: none;
    font-size: 14px;
}

.stats-row {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-bottom: 24px;
}

.stat-card {
    background: white;
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 16px;
    text-align: center;
}

.stat-label {
    display: block;
    font-size: 11px;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 8px;
}

.stat-value {
    display: block;
    font-size: 32px;
    font-weight: 600;
    color: var(--text-primary);
}

.stat-trend {
    display: block;
    font-size: 12px;
    margin-top: 4px;
}

.stat-trend.positive { color: var(--success-color); }
.stat-trend.negative { color: var(--error-color); }

.charts-row {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 24px;
    margin-bottom: 24px;
}

.chart-container {
    background: white;
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 20px;
}

.chart-container.full {
    grid-column: 1 / -1;
}

.chart-container h3 {
    font-size: 12px;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin: 0 0 16px 0;
}

.period-tabs {
    display: flex;
    gap: 8px;
    margin-bottom: 16px;
}

.period-tab {
    padding: 6px 12px;
    border: 1px solid var(--border-color);
    border-radius: 4px;
    background: white;
    cursor: pointer;
    font-size: 13px;
}

.period-tab.active {
    background: var(--primary-color);
    color: white;
    border-color: var(--primary-color);
}

.deep-dive-link {
    display: block;
    text-align: center;
    color: var(--primary-color);
    font-size: 13px;
    margin-top: 12px;
}

/* Insight Cards */
.insight-card {
    padding: 12px;
    border-radius: 6px;
    margin-bottom: 8px;
    font-size: 13px;
}

.insight-card.warning {
    background: var(--warning-bg);
    border-left: 3px solid var(--warning-color);
}

.insight-card.info {
    background: var(--info-bg);
    border-left: 3px solid var(--info-color);
}

.insight-card.success {
    background: var(--success-bg);
    border-left: 3px solid var(--success-color);
}
```

---

## Stage 3: Subject Analysis with D3.js Charts

### D3.js Integration

```javascript
// src/web/js/lib/d3.min.js - Bundle D3.js v7 locally

// src/web/js/charts/subject-chart.js
class SubjectChart {
    constructor(containerId, data, options = {}) {
        this.container = d3.select(`#${containerId}`);
        this.data = data;
        this.options = {
            width: options.width || 370,
            height: options.height || 190,
            colors: options.colors || d3.schemeCategory10,
            ...options
        };
    }
    
    render() {
        // Clear previous
        this.container.selectAll('*').remove();
        
        const width = this.options.width;
        const height = this.options.height;
        const radius = Math.min(width, height) / 2;
        
        const svg = this.container.append('svg')
            .attr('width', width)
            .attr('height', height)
            .append('g')
            .attr('transform', `translate(${width/2}, ${height/2})`);
        
        // Create pie layout
        const pie = d3.pie()
            .value(d => d.mistake_count)
            .sort(null);
        
        // Create arc generator
        const arc = d3.arc()
            .innerRadius(radius * 0.4)
            .outerRadius(radius * 0.8);
        
        // Create arcs
        const arcs = svg.selectAll('.arc')
            .data(pie(this.data))
            .enter()
            .append('g')
            .attr('class', 'arc');
        
        // Draw paths
        arcs.append('path')
            .attr('d', arc)
            .attr('fill', (d, i) => this.options.colors[i % this.options.colors.length])
            .on('click', (event, d) => this.onSegmentClick(d.data))
            .on('mouseover', (event, d) => this.showTooltip(event, d.data))
            .on('mouseout', () => this.hideTooltip());
        
        // Center text
        svg.append('text')
            .attr('text-anchor', 'middle')
            .attr('dy', '0.35em')
            .attr('font-size', '14px')
            .text('All Subjects');
    }
    
    update(newData) {
        this.data = newData;
        this.render();
    }
    
    onSegmentClick(data) {
        // Navigate to subject deep dive
        if (this.options.onSegmentClick) {
            this.options.onSegmentClick(data);
        }
    }
    
    showTooltip(event, data) {
        // Show tooltip with subject name, count, percentage
    }
    
    hideTooltip() {
        // Hide tooltip
    }
}
```

### Subject Sunburst Chart Features

- **Interactive Segments**: Click to zoom into subject children
- **Breadcrumb Navigation**: Shows current zoom path
- **Hover Tooltips**: Subject name, count, percentage
- **Color Coding**: Gradient from red (most mistakes) to green (fewest)
- **Center Text**: Shows total or current selection
- **Legend**: Top subjects with counts

### Subject Deep Dive Page

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ← Back to Analytics    📚 Subject: Cardiology              [USMLE ▼]  │
├─────────────────────────────────────────────────────────────────────────┤
│ ┌─────────────────────────┐  ┌─────────────────────────────────────────┐│
│ │ SUBJECT INFO            │  │ TREND                                   ││
│ │ Full Path:              │  │                                         ││
│ │ Medicine > Cardiology   │  │ This Week: 8    Last Week: 12          ││
│ │                         │  │ Change: -4 (↓ 33% - Improving!)        ││
│ │ Exam Weight: 12%        │  │                                         ││
│ └─────────────────────────┘  └─────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────────────────┤
│ STATS                                                                   │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐    │
│ │ TOTAL        │ │ % OF ALL     │ │ AVG          │ │ LAST         │    │
│ │ MISTAKES     │ │ MISTAKES     │ │ DIFFICULTY   │ │ MISTAKE      │    │
│ │    28        │ │   16.3%      │ │   3.8        │ │  2 days ago  │    │
│ └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘    │
├─────────────────────────────────────────────────────────────────────────┤
│ MISTAKES OVER TIME                                                      │
│ ┌───────────────────────────────────────────────────────────────────┐  │
│ │  [Bar Chart - Weekly mistake counts]                              │  │
│ │  Week 1  ████ 4                                                   │  │
│ │  Week 2  ██████ 6                                                 │  │
│ │  Week 3  ████████████ 12                                          │  │
│ │  Week 4  ████████ 8                                               │  │
│ └───────────────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────────────┤
│ CHILD SUBJECTS                   │ COMMON MISTAKE TYPES                │
│ ┌────────────────────────────┐   │ ┌────────────────────────────────┐  │
│ │ • Heart Failure (8)        │   │ │ [Knowledge Gap]  12 (43%)      │  │
│ │ • Arrhythmias (7)          │   │ │ [Careless Error]  8 (29%)      │  │
│ │ • Valvular Disease (6)     │   │ │ [Misread Q]  5 (18%)           │  │
│ │ • Coronary Artery (5)      │   │ │ [Time Pressure]  3 (11%)       │  │
│ │ • Other (2)                │   │ │                                │  │
│ └────────────────────────────┘   │ └────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────────────┤
│ RECENT ENTRIES                                                          │
│ ┌───────────────────────────────────────────────────────────────────┐  │
│ │ Dec 28 | Heart Failure | "Confused systolic vs diastolic..."     │  │
│ │ Dec 26 | Arrhythmias | "Misread the ECG strip..."                │  │
│ │ Dec 24 | Valvular | "Forgot murmur characteristics..."           │  │
│ └───────────────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────────────┤
│ RELATED TOPICS (Siblings)        │ RECOMMENDATIONS                     │
│ ┌────────────────────────────┐   │ ┌────────────────────────────────┐  │
│ │ Pulmonology (15 mistakes)  │   │ │ 💡 Focus on Heart Failure -    │  │
│ │ Nephrology (12 mistakes)   │   │ │    highest mistake count       │  │
│ │ Gastroenterology (8)       │   │ │ ✓ Review systolic/diastolic    │  │
│ └────────────────────────────┘   │ │    distinction                 │  │
│                                   │ └────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Stage 4: Tag/Mistake Type Analysis with D3.js

### Donut Chart Component

```javascript
// src/web/js/charts/tag-chart.js
class TagChart {
    constructor(containerId, data, options = {}) {
        this.container = d3.select(`#${containerId}`);
        this.data = data;
        this.options = {
            width: options.width || 370,
            height: options.height || 190,
            innerRadius: options.innerRadius || 50,
            outerRadius: options.outerRadius || 80,
            ...options
        };
    }
    
    render() {
        this.container.selectAll('*').remove();
        
        const width = this.options.width;
        const height = this.options.height;
        
        const svg = this.container.append('svg')
            .attr('width', width)
            .attr('height', height);
        
        const g = svg.append('g')
            .attr('transform', `translate(${width/3}, ${height/2})`);
        
        const pie = d3.pie()
            .value(d => d.count)
            .sort(null);
        
        const arc = d3.arc()
            .innerRadius(this.options.innerRadius)
            .outerRadius(this.options.outerRadius);
        
        const arcs = g.selectAll('.arc')
            .data(pie(this.data))
            .enter()
            .append('g')
            .attr('class', 'arc');
        
        arcs.append('path')
            .attr('d', arc)
            .attr('fill', d => d.data.color || '#ccc')
            .on('click', (event, d) => this.onClick(d.data));
        
        // Center total
        g.append('text')
            .attr('text-anchor', 'middle')
            .attr('dy', '-0.2em')
            .attr('font-size', '24px')
            .attr('font-weight', '600')
            .text(this.data.reduce((sum, d) => sum + d.count, 0));
        
        g.append('text')
            .attr('text-anchor', 'middle')
            .attr('dy', '1.2em')
            .attr('font-size', '11px')
            .attr('fill', '#666')
            .text('total');
        
        // Legend
        this.renderLegend(svg);
    }
    
    renderLegend(svg) {
        const legend = svg.append('g')
            .attr('transform', `translate(${this.options.width * 0.6}, 20)`);
        
        this.data.forEach((d, i) => {
            const row = legend.append('g')
                .attr('transform', `translate(0, ${i * 20})`);
            
            row.append('circle')
                .attr('r', 5)
                .attr('fill', d.color || '#ccc');
            
            row.append('text')
                .attr('x', 12)
                .attr('dy', '0.35em')
                .attr('font-size', '12px')
                .text(`${d.tag_name} (${d.count})`);
        });
    }
    
    onClick(data) {
        // Filter entries by this tag
    }
}
```

### Donut Chart Features

- **Segments by Tag**: Each tag gets a colored segment
- **Center Stats**: Total entries with tags
- **Legend**: Scrollable list with counts
- **Hover Effects**: Highlight segment, show tooltip
- **Click to Filter**: Navigate to entries filtered by tag

---

## Stage 5: Activity Trends & Time Charts

### Area/Line Chart Component

```javascript
// src/web/js/charts/activity-chart.js
class ActivityChart {
    constructor(containerId, options = {}) {
        this.container = d3.select(`#${containerId}`);
        this.options = {
            width: options.width || 750,
            height: options.height || 200,
            margin: { top: 20, right: 30, bottom: 30, left: 40 },
            ...options
        };
    }
    
    async loadData(period = '7d', examContextId = null) {
        const data = await window.api.getActivityOverTime({
            period,
            examContextId
        });
        this.render(data);
    }
    
    render(data) {
        this.container.selectAll('*').remove();
        
        const { width, height, margin } = this.options;
        const innerWidth = width - margin.left - margin.right;
        const innerHeight = height - margin.top - margin.bottom;
        
        const svg = this.container.append('svg')
            .attr('width', width)
            .attr('height', height);
        
        const g = svg.append('g')
            .attr('transform', `translate(${margin.left}, ${margin.top})`);
        
        // Scales
        const x = d3.scalePoint()
            .domain(data.map(d => d.label))
            .range([0, innerWidth]);
        
        const y = d3.scaleLinear()
            .domain([0, d3.max(data, d => d.count) * 1.1])
            .range([innerHeight, 0]);
        
        // Area
        const area = d3.area()
            .x(d => x(d.label))
            .y0(innerHeight)
            .y1(d => y(d.count))
            .curve(d3.curveMonotoneX);
        
        g.append('path')
            .datum(data)
            .attr('fill', 'rgba(59, 130, 246, 0.1)')
            .attr('d', area);
        
        // Line
        const line = d3.line()
            .x(d => x(d.label))
            .y(d => y(d.count))
            .curve(d3.curveMonotoneX);
        
        g.append('path')
            .datum(data)
            .attr('fill', 'none')
            .attr('stroke', '#3b82f6')
            .attr('stroke-width', 2)
            .attr('d', line);
        
        // Data points
        g.selectAll('.dot')
            .data(data)
            .enter()
            .append('circle')
            .attr('class', 'dot')
            .attr('cx', d => x(d.label))
            .attr('cy', d => y(d.count))
            .attr('r', 4)
            .attr('fill', '#3b82f6');
        
        // Axes
        g.append('g')
            .attr('transform', `translate(0, ${innerHeight})`)
            .call(d3.axisBottom(x));
        
        g.append('g')
            .call(d3.axisLeft(y).ticks(5));
    }
}
```

### Area/Line Chart Features

- **Period Tabs**: 7 Days, 30 Days, 90 Days, All Time
- **Granularity**: Day (for 7d), Week (for 30d/90d), Month (for all)
- **Area Fill**: Light blue gradient under line
- **Data Points**: Circles at each data point
- **Today Highlight**: Green dot for current day
- **Grid Lines**: Horizontal reference lines
- **X-Axis Labels**: Date labels
- **Hover Tooltip**: Shows exact count for date
- **Smooth Transitions**: Animate between periods

---

## Stage 6: Pattern Detection & Insights Engine

### Pattern Detection Algorithm

```python
def get_patterns_and_insights(self, exam_context_id=None, limit=5):
    """
    Detect patterns and generate actionable insights.
    
    Pattern Types:
    1. SUBJECT_INCREASE - Subject mistakes increased significantly
    2. SUBJECT_DECREASE - Subject mistakes decreased (success!)
    3. TAG_HIGH_FREQUENCY - A tag appears in >20% of entries
    4. TAG_TRENDING_UP - A tag is appearing more frequently
    5. DIFFICULTY_SKEW - Most mistakes are hard/very hard
    6. INACTIVE_PERIOD - No entries for >7 days
    7. SESSION_INCOMPLETE - Many incomplete sessions
    8. SUBJECT_WEIGHT_MISMATCH - High mistakes in low-weight subject
    9. STREAK_AT_RISK - Current streak may break today
    10. GOAL_PROGRESS - Goal completion status
    11. REFLECTION_QUALITY_LOW - Reflections need more depth
    12. SOURCE_STRUGGLING - Struggling with a particular source
    13. TIME_DIFFICULTY_MISMATCH - Spending too little time on hard questions
    14. SELF_ASSESSMENT_BIAS - Consistently over/underrating difficulty
    15. COMMON_REFLECTION_THEME - Recurring theme in reflections
    """
    
    insights = []
    
    # 1. Check for subject increases
    subject_changes = self._get_subject_week_over_week()
    for subject in subject_changes:
        if subject['change_pct'] > 30:
            insights.append({
                'type': 'warning',
                'icon': '💡',
                'message': f"{subject['name']} mistakes ↑{subject['change_pct']}%",
                'detail': f"From {subject['last_week']} to {subject['this_week']} this week",
                'action': f"Review {subject['name']} concepts",
                'related_id': subject['id'],
                'related_type': 'subject'
            })
    
    # 2. Check for subject decreases (success!)
    for subject in subject_changes:
        if subject['change_pct'] < -25:
            insights.append({
                'type': 'success',
                'icon': '✓',
                'message': f"{subject['name']} down {abs(subject['change_pct'])}%",
                'detail': "Great improvement!",
                'related_id': subject['id'],
                'related_type': 'subject'
            })
    
    # 3. Check tag frequency
    tag_stats = self.get_tag_analytics(exam_context_id)
    for tag in tag_stats['top_tags'][:3]:
        if tag['percentage'] > 20:
            insights.append({
                'type': 'warning',
                'icon': '⚠️',
                'message': f'"{tag["name"]}" at {tag["percentage"]:.0f}%',
                'detail': f"{tag['count']} entries with this tag",
                'action': "Focus on reducing this mistake type",
                'related_id': tag['id'],
                'related_type': 'tag'
            })
    
    # Continue with other pattern checks...
    
    return insights[:limit]
```

### Insight Card Styling

| Type | Background | Border | Icon |
|------|------------|--------|------|
| Warning | `var(--warning-bg)` | `var(--warning-color)` | ⚠️ or 💡 |
| Info | `var(--info-bg)` | `var(--info-color)` | 💡 or ℹ️ |
| Success | `var(--success-bg)` | `var(--success-color)` | ✓ or 🎉 |

### Insights Container

```javascript
// src/web/js/components/insights-container.js
class InsightsContainer {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
    }
    
    async load(examContextId = null) {
        const insights = await window.api.getPatternsAndInsights({
            examContextId,
            limit: 5
        });
        this.render(insights);
    }
    
    render(insights) {
        this.container.innerHTML = '';
        
        if (insights.length === 0) {
            this.container.innerHTML = `
                <div class="no-insights">
                    <span>✓</span>
                    <p>No notable patterns detected. Keep studying!</p>
                </div>
            `;
            return;
        }
        
        insights.forEach(insight => {
            const card = document.createElement('div');
            card.className = `insight-card ${insight.type}`;
            card.innerHTML = `
                <span class="insight-icon">${insight.icon}</span>
                <div class="insight-content">
                    <p class="insight-message">${insight.message}</p>
                    ${insight.detail ? `<p class="insight-detail">${insight.detail}</p>` : ''}
                </div>
            `;
            
            if (insight.related_id) {
                card.style.cursor = 'pointer';
                card.onclick = () => this.navigateToRelated(insight);
            }
            
            this.container.appendChild(card);
        });
    }
    
    navigateToRelated(insight) {
        if (insight.related_type === 'subject') {
            window.location.href = `subject_analysis.html?id=${insight.related_id}`;
        } else if (insight.related_type === 'tag') {
            window.location.href = `entry_browser.html?tag=${insight.related_id}`;
        }
    }
}
```

---

## Stage 7: Study Heatmap & Streak Tracking

### Heatmap Component

GitHub-style activity heatmap showing study consistency over time.

**Placement:** Main Analytics Dashboard (below Activity Over Time chart)

### Heatmap Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│ STUDY ACTIVITY                                                          │
│ ┌───────────────────────────────────────────────────────────────────┐  │
│ │      Oct         Nov         Dec                                   │  │
│ │ Sun  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │  │
│ │ Mon  ░░▓▓░░░░▓▓▓▓░░░░▓▓░░░░░░▓▓▓▓░░░░▓▓▓▓░░░░▓▓▓▓░░░░▓▓▓▓░░░░  │  │
│ │ Tue  ░░░░▓▓░░░░▓▓░░░░░░▓▓░░░░▓▓▓▓░░░░▓▓░░░░░░▓▓▓▓░░░░▓▓░░░░░░  │  │
│ │ Wed  ░░▓▓▓▓░░░░▓▓▓▓░░░░▓▓▓▓░░▓▓░░░░░░▓▓▓▓░░░░▓▓▓▓░░░░▓▓▓▓████  │  │
│ │ Thu  ░░░░▓▓░░░░▓▓░░░░░░▓▓░░░░▓▓▓▓░░░░▓▓░░░░░░▓▓░░░░░░▓▓████░░  │  │
│ │ Fri  ░░▓▓░░░░░░▓▓░░░░▓▓▓▓░░░░▓▓░░░░░░▓▓░░░░░░▓▓▓▓░░░░▓▓░░░░░░  │  │
│ │ Sat  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │  │
│ │                                                                    │  │
│ │ Less ░░ ▒▒ ▓▓ ██ More                                             │  │
│ └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│ ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────┐   │
│ │ 🔥 CURRENT STREAK │  │ 🏆 LONGEST STREAK │  │ 📅 ACTIVE DAYS      │   │
│ │      7 days       │  │      14 days      │  │    45 of 90         │   │
│ └──────────────────┘  └──────────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

### Heatmap Implementation

```javascript
// src/web/js/charts/heatmap-chart.js
class ActivityHeatmap {
    constructor(containerId, options = {}) {
        this.container = d3.select(`#${containerId}`);
        this.options = {
            weeks: options.weeks || 16,
            cellSize: options.cellSize || 12,
            cellGap: options.cellGap || 2,
            colors: [
                '#ebedf0',  // level 0 - no activity
                '#9be9a8',  // level 1 - light
                '#40c463',  // level 2 - medium
                '#30a14e',  // level 3 - high
                '#216e39'   // level 4 - very high
            ],
            ...options
        };
    }
    
    async loadData(examContextId = null) {
        const data = await window.api.getActivityHeatmap({
            examContextId,
            weeks: this.options.weeks
        });
        this.render(data);
    }
    
    render(data) {
        this.container.selectAll('*').remove();
        
        const { weeks, cellSize, cellGap, colors } = this.options;
        const width = weeks * (cellSize + cellGap) + 50;
        const height = 7 * (cellSize + cellGap) + 30;
        
        const svg = this.container.append('svg')
            .attr('width', width)
            .attr('height', height);
        
        // Day labels
        const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
        svg.selectAll('.day-label')
            .data(days)
            .enter()
            .append('text')
            .attr('class', 'day-label')
            .attr('x', 0)
            .attr('y', (d, i) => i * (cellSize + cellGap) + cellSize + 15)
            .attr('font-size', '10px')
            .attr('fill', '#666')
            .text(d => d);
        
        // Cells
        const cellsGroup = svg.append('g')
            .attr('transform', 'translate(35, 15)');
        
        data.days.forEach((day, i) => {
            const weekIndex = Math.floor(i / 7);
            const dayIndex = i % 7;
            
            cellsGroup.append('rect')
                .attr('x', weekIndex * (cellSize + cellGap))
                .attr('y', dayIndex * (cellSize + cellGap))
                .attr('width', cellSize)
                .attr('height', cellSize)
                .attr('rx', 2)
                .attr('fill', colors[day.level])
                .append('title')
                .text(`${day.date}: ${day.count} entries`);
        });
        
        // Legend
        this.renderLegend(svg, width, height);
    }
    
    renderLegend(svg, width, height) {
        const legend = svg.append('g')
            .attr('transform', `translate(${width - 120}, ${height - 15})`);
        
        legend.append('text')
            .attr('x', 0)
            .attr('font-size', '10px')
            .attr('fill', '#666')
            .text('Less');
        
        this.options.colors.forEach((color, i) => {
            legend.append('rect')
                .attr('x', 30 + i * 14)
                .attr('y', -10)
                .attr('width', 10)
                .attr('height', 10)
                .attr('rx', 2)
                .attr('fill', color);
        });
        
        legend.append('text')
            .attr('x', 105)
            .attr('font-size', '10px')
            .attr('fill', '#666')
            .text('More');
    }
    
    getColorForLevel(level) {
        return this.options.colors[Math.min(level, 4)];
    }
}
```

### Streak Display Component

```javascript
// src/web/js/components/streak-display.js
class StreakDisplay {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
    }
    
    async load(examContextId = null) {
        const data = await window.api.getStreakInfo({ examContextId });
        this.render(data);
    }
    
    render(data) {
        this.container.innerHTML = `
            <div class="streak-cards">
                <div class="streak-card current ${data.streak_at_risk ? 'at-risk' : ''}">
                    <span class="streak-icon">🔥</span>
                    <span class="streak-label">CURRENT STREAK</span>
                    <span class="streak-value">${data.current_streak} days</span>
                    ${data.streak_at_risk ? '<span class="streak-warning">At risk!</span>' : ''}
                </div>
                <div class="streak-card longest">
                    <span class="streak-icon">🏆</span>
                    <span class="streak-label">LONGEST STREAK</span>
                    <span class="streak-value">${data.longest_streak} days</span>
                </div>
                <div class="streak-card active">
                    <span class="streak-icon">📅</span>
                    <span class="streak-label">ACTIVE DAYS</span>
                    <span class="streak-value">${data.total_active_days} of 90</span>
                </div>
            </div>
        `;
    }
}
```

---

## Stage 8: Goal Setting System

### Goal Setting UI

**Placement:** Analytics Dashboard (new section) + Landing Page (mini widget)

### Goal Section Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│ WEEKLY GOAL                                                    [Edit]  │
│ ┌───────────────────────────────────────────────────────────────────┐  │
│ │                                                                    │  │
│ │  Target: 20 entries this week                                     │  │
│ │                                                                    │  │
│ │  ████████████████████░░░░░░░░  15/20 (75%)                        │  │
│ │                                                                    │  │
│ │  5 more entries to reach your goal!                               │  │
│ │  📅 Week ends in 3 days                                           │  │
│ │                                                                    │  │
│ └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│ GOAL HISTORY (Last 8 weeks)                                            │
│ ┌───────────────────────────────────────────────────────────────────┐  │
│ │  Dec 22  ████████████████████ 20/20 ✓                             │  │
│ │  Dec 15  ████████████████░░░░ 16/20                               │  │
│ │  Dec 8   ████████████████████ 22/20 ✓                             │  │
│ │  Dec 1   ████████████░░░░░░░░ 12/20                               │  │
│ │  ...                                                               │  │
│ └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### Goal Setting Modal

```html
<!-- Goal setting modal -->
<div class="modal" id="goalSettingModal">
    <div class="modal-content">
        <h3>Set Weekly Goal</h3>
        <p>How many entries do you want to log each week?</p>
        
        <div class="goal-input">
            <button class="goal-adjust" data-delta="-5">-5</button>
            <button class="goal-adjust" data-delta="-1">-1</button>
            <input type="number" id="goalTarget" value="20" min="1" max="100">
            <button class="goal-adjust" data-delta="+1">+1</button>
            <button class="goal-adjust" data-delta="+5">+5</button>
        </div>
        
        <p class="goal-suggestion">
            Based on your history, you average 18 entries/week.
        </p>
        
        <div class="modal-actions">
            <button class="btn-secondary" data-dismiss="modal">Cancel</button>
            <button class="btn-primary" id="saveGoal">Save Goal</button>
        </div>
    </div>
</div>
```

### Goal Widget Component

```javascript
// src/web/js/components/goal-widget.js
class GoalWidget {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
    }
    
    async load(examContextId = null) {
        const goals = await window.api.getUserGoals({ examContextId });
        const currentGoal = goals.find(g => g.goal_type === 'weekly_entries');
        this.render(currentGoal);
    }
    
    render(goal) {
        if (!goal) {
            this.renderNoGoal();
            return;
        }
        
        const progressPct = Math.min(100, goal.progress_pct);
        const remaining = Math.max(0, goal.target_value - goal.current_value);
        const daysLeft = this.getDaysUntilWeekEnd();
        
        this.container.innerHTML = `
            <div class="goal-widget">
                <div class="goal-header">
                    <span class="goal-title">WEEKLY GOAL</span>
                    <button class="goal-edit-btn" onclick="openGoalModal()">
                        [Edit Goal]
                    </button>
                </div>
                <p class="goal-target">Target: ${goal.target_value} entries this week</p>
                <div class="goal-progress">
                    <div class="progress-bar">
                        <div class="progress-fill ${goal.is_complete ? 'complete' : ''}" 
                             style="width: ${progressPct}%"></div>
                    </div>
                    <span class="progress-text">
                        ${goal.current_value}/${goal.target_value} (${progressPct.toFixed(0)}%)
                    </span>
                </div>
                ${goal.is_complete 
                    ? '<p class="goal-message success">🎉 Goal achieved!</p>'
                    : `<p class="goal-message">${remaining} more entries to reach your goal!</p>`
                }
                <p class="goal-deadline">📅 Week ends in ${daysLeft} days</p>
            </div>
        `;
    }
    
    renderNoGoal() {
        this.container.innerHTML = `
            <div class="goal-widget no-goal">
                <p>No weekly goal set</p>
                <button class="btn-primary" onclick="openGoalModal()">
                    Set a Goal
                </button>
            </div>
        `;
    }
    
    getDaysUntilWeekEnd() {
        const now = new Date();
        const dayOfWeek = now.getDay();
        return 7 - dayOfWeek;
    }
}
```

### Goal Modal Component

```javascript
// src/web/js/components/goal-modal.js
class GoalModal {
    constructor() {
        this.modal = document.getElementById('goalSettingModal');
        this.input = document.getElementById('goalTarget');
        this.setupListeners();
    }
    
    setupListeners() {
        // Adjust buttons
        document.querySelectorAll('.goal-adjust').forEach(btn => {
            btn.addEventListener('click', () => {
                const delta = parseInt(btn.dataset.delta);
                this.adjustValue(delta);
            });
        });
        
        // Save button
        document.getElementById('saveGoal').addEventListener('click', () => {
            this.saveGoal();
        });
    }
    
    adjustValue(delta) {
        const current = parseInt(this.input.value) || 0;
        const newValue = Math.max(1, Math.min(100, current + delta));
        this.input.value = newValue;
    }
    
    async saveGoal() {
        const target = parseInt(this.input.value);
        if (target < 1 || target > 100) {
            alert('Please enter a goal between 1 and 100');
            return;
        }
        
        try {
            await window.api.setWeeklyGoal(target);
            this.close();
            // Refresh goal widget
            if (window.goalWidget) {
                window.goalWidget.load();
            }
        } catch (error) {
            alert('Failed to save goal: ' + error.message);
        }
    }
    
    open() {
        this.modal.classList.add('active');
    }
    
    close() {
        this.modal.classList.remove('active');
    }
}

// Global function to open modal
function openGoalModal() {
    if (!window.goalModal) {
        window.goalModal = new GoalModal();
    }
    window.goalModal.open();
}
```

### Landing Page Goal Widget (Mini Version)

Small widget showing current goal progress on the landing page.

```
┌────────────────────────────────────┐
│ 🎯 Weekly Goal: 15/20 (75%)        │
│ ████████████████░░░░               │
└────────────────────────────────────┘
```

---

## Stage 9: Reflection Quality & Common Patterns

### Reflection Quality Section

**Placement:** Analytics Dashboard

**Scope:** Aggregate statistics + common patterns analysis

### Reflection Quality Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│ REFLECTION QUALITY                                                      │
│ ┌────────────────────────────┐   ┌────────────────────────────────────┐│
│ │     AVERAGE SCORE          │   │  SCORE DISTRIBUTION                ││
│ │                            │   │                                    ││
│ │        ⭐⭐⭐☆☆         │   │  ⭐⭐⭐⭐⭐  ████ 15              ││
│ │         3.2/5              │   │  ⭐⭐⭐⭐    ████████ 40          ││
│ │                            │   │  ⭐⭐⭐      ████████████ 60      ││
│ │   ↑ 0.3 from last week     │   │  ⭐⭐        ██████ 25            ││
│ │                            │   │  ⭐          ███ 10               ││
│ └────────────────────────────┘   └────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
```

### Common Reflection Patterns Section

```
┌─────────────────────────────────────────────────────────────────────────┐
│ COMMON REFLECTION PATTERNS                                              │
│ ┌───────────────────────────────────────────────────────────────────┐  │
│ │  RECURRING THEMES                     WORD CLOUD                   │  │
│ │  ┌─────────────────────────────┐     ┌─────────────────────────┐  │  │
│ │  │ 1. "rushing through" (23)   │     │    forgot  CONFUSED     │  │  │
│ │  │    → Careless Error         │     │  misread    RUSHED      │  │  │
│ │  │ 2. "forgot to check" (18)   │     │     similar  UNITS      │  │  │
│ │  │    → Careless Error         │     │   calculation  TIME     │  │  │
│ │  │ 3. "confused between" (15)  │     │     mixed up  READ      │  │  │
│ │  │    → Knowledge Gap          │     │                         │  │  │
│ │  └─────────────────────────────┘     └─────────────────────────┘  │  │
│ │                                                                    │  │
│ │  💡 REFLECTION INSIGHTS                                           │  │
│ │  • "Rushing" appears in 15% of reflections - consider pacing      │  │
│ │  • Action items present in 45 entries - keep it up!               │  │
│ └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### Quality Scoring Criteria

| Criterion | Description | Weight |
|-----------|-------------|--------|
| Length | 20-200 words optimal | 20% |
| Causal Language | "because", "since", "due to" | 20% |
| Action Language | "I should", "next time", "I will" | 25% |
| Self-Questioning | "why did I", "what made me" | 20% |
| Specificity | Concrete details, numbers, terms | 15% |

### Implementation Notes

- Score calculated when entry is saved (cached in `reflection_quality_score` column)
- Aggregate stats computed on-demand from cached scores
- Use simple keyword extraction (no NLP library required)
- Common phrases detected via n-gram analysis
- Word cloud data generated from reflection text
- Cache themes in `reflection_themes` table for performance

---

## Stage 10: Source Comparison & Performance Over Time

### Source Comparison Section

**Placement:** Analytics Dashboard

### Source Comparison Layout with Line Graph

```
┌─────────────────────────────────────────────────────────────────────────┐
│ SOURCE COMPARISON                                                       │
│ ┌─────────────────────────────────┐ ┌─────────────────────────────────┐ │
│ │ PERFORMANCE OVER TIME           │ │ SOURCE    ENTRIES  TREND  TOP   │ │
│ │                                 │ │ ──────────────────────────────  │ │
│ │ Mistakes                        │ │ UWorld    45(26%)  ↓Better Know │ │
│ │   15│  ●───●                    │ │ Amboss    38(22%)  →Stable Care │ │
│ │     │       \    UWorld         │ │ Kaplan    25(15%)  ↑Worse  Time │ │
│ │   10│        ●───●              │ │ NBME      20(12%)  ↓Better Read │ │
│ │     │    ○───○───○   \          │ │                                 │ │
│ │    5│                 ●───●     │ │                                 │ │
│ │     │     □───□───□───□───□     │ │                                 │ │
│ │    0│────────────────────       │ │                                 │ │
│ │      Oct   Nov   Dec   Jan      │ │                                 │ │
│ │                                 │ │                                 │ │
│ │ ● UWorld ↓  ○ Amboss →  □ Kaplan│ │                                 │ │
│ └─────────────────────────────────┘ └─────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Stage 11: Time Spent vs Difficulty Analysis

### Time vs Difficulty Section

**Placement:** Analytics Dashboard (new section)

### Time vs Difficulty Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│ TIME SPENT VS DIFFICULTY                                                │
│ ┌────────────────────────────────┐   ┌────────────────────────────────┐│
│ │  AVERAGE TIME BY DIFFICULTY    │   │  CORRELATION ANALYSIS          ││
│ │                                │   │                                ││
│ │  ● Easy      45s  ████         │   │  Correlation: 0.72 (Strong)   ││
│ │  ●● Moderate 68s  ██████       │   │                                ││
│ │  ●●● Medium  95s  █████████    │   │  ✓ You spend more time on     ││
│ │  ●●●● Hard   80s  ███████ ⚠️   │   │    harder questions (good!)   ││
│ │  ●●●●● V.Hard 150s ████████████│   │                                ││
│ │                                │   │  ⚠️ Hard questions get less   ││
│ │  ⚠️ Less time on Hard than     │   │    time than Medium - why?    ││
│ │     Medium - review pacing     │   │                                ││
│ └────────────────────────────────┘   └────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Stage 12: Self-Assessment Accuracy

### Self-Assessment Section

**Placement:** Analytics Dashboard (new section)

### Self-Assessment Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│ SELF-ASSESSMENT ACCURACY                                                │
│ ┌────────────────────────────┐   ┌────────────────────────────────────┐│
│ │     ACCURACY SCORE         │   │  ACCURACY BY DIFFICULTY            ││
│ │                            │   │                                    ││
│ │         78%                │   │  ✓ Easy:   85% accurate           ││
│ │      ████████████░░░       │   │  ✓ Medium: 80% accurate           ││
│ │                            │   │  ⚠️ Hard:   65% accurate           ││
│ │   Bias: Slight Overconf.   │   │                                    ││
│ │   (rates -0.3 easier)      │   │  💡 You underrate Hard questions  ││
│ └────────────────────────────┘   └────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
```

### Implementation Notes

- "Expected" difficulty derived from:
  - Time spent (more time = harder)
  - Subject average difficulty
  - Source average difficulty
- Accuracy calculated as % within ±1 of expected
- Bias calculated as average(user_rating - expected_rating)

---

## Stage 13: Subject vs Exam Weight Analysis

### Subject vs Exam Weight Section

**Placement:** Analytics Dashboard (new section)

### Subject Weight Analysis Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│ SUBJECT VS EXAM WEIGHT ANALYSIS                                         │
│ ┌───────────────────────────────────────────────────────────────────┐  │
│ │  EFFICIENCY SCORE: 72/100 (Good)                    ↑ +10 vs last │  │
│ └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│ ┌─────────────────────────────────┐  ┌─────────────────────────────────┐
│ │  QUADRANT ANALYSIS              │  │  TOP RECOMMENDATIONS            │
│ │                                 │  │                                 │
│ │  🔴 PRIORITY (Focus Here)       │  │  1. ↑ Cardiology - high weight, │
│ │  • Cardiology (16% vs 12%)      │  │     many mistakes               │
│ │  • Nephrology (14% vs 10%)      │  │  2. ↑ Nephrology - high weight, │
│ │                                 │  │     many mistakes               │
│ │  🟢 WELL-MAINTAINED             │  │  3. ↓ Anatomy - low weight,     │
│ │  • Biochemistry (5% vs 15%)     │  │     consider reducing           │
│ │                                 │  │  4. ✓ Biochemistry - maintain   │
│ │  🟡 REDUCE FOCUS                │  │     current level               │
│ │  • Anatomy (9% vs 5%)           │  │                                 │
│ │                                 │  │                                 │
│ │  ⚪ LOW PRIORITY                │  │                                 │
│ │  • Histology (2% vs 3%)         │  │                                 │
│ └─────────────────────────────────┘  └─────────────────────────────────┘
└─────────────────────────────────────────────────────────────────────────┘
```

### Quadrant Categories

| Quadrant | Criteria | Action |
|----------|----------|--------|
| 🔴 **Priority** | High mistakes %, High exam weight | Focus study time here |
| 🟢 **Well-Maintained** | Low mistakes %, High exam weight | Keep up the good work |
| 🟡 **Reduce Focus** | High mistakes %, Low exam weight | May be over-studying |
| ⚪ **Low Priority** | Low mistakes %, Low exam weight | Acceptable as-is |

### Efficiency Score Calculation

```python
# Formula: How well mistake distribution aligns with exam weights
Efficiency Score = 100 - (Σ |mistake_pct - weight_pct| × weight_pct)

# Perfect alignment = 100
# Complete mismatch = 0
```

### Implementation Notes

- Requires exam_context_id (exam weights come from subject definitions)
- Scatter plot optional (shows subjects as bubbles by weight vs mistakes)
- Recommendations prioritized by: weight × mistake_difference

---

## Stage 14: Landing Page Analytics Preview

### Analytics Preview Card

**Placement:** Landing Page (index.html), below exam cards

### Preview Card Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 📊 QUICK ANALYTICS                                    View Full Report →│
├─────────────────────────────────────────────────────────────────────────┤
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐    │
│ │ THIS WEEK    │ │ TOP SUBJECT  │ │ TOP MISTAKE  │ │ STREAK       │    │
│ │    23        │ │ Cardiology   │ │ Careless     │ │ 🔥 7 days    │    │
│ │ entries      │ │   (28)       │ │   (45)       │ │              │    │
│ │  ↑+8 vs last │ │              │ │              │ │              │    │
│ └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘    │
│                                                                         │
│ 🎯 Weekly Goal: 15/20 (75%)  ████████████████░░░░                      │
│                                                                         │
│ 💡 Cardiology mistakes up 40% this week                                │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key Features

1. **Compact Stats Row**: 4 mini stat cards
2. **Goal Progress Bar**: Visual weekly goal progress
3. **Top Insight**: Single most important insight
4. **Link to Full Report**: "View Full Report →"

### Implementation

```javascript
// src/web/js/components/analytics-preview.js
class AnalyticsPreview {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
    }
    
    async load() {
        const [overview, goals, insights, streak] = await Promise.all([
            window.api.getAnalyticsOverview(),
            window.api.getUserGoals(),
            window.api.getPatternsAndInsights({ limit: 1 }),
            window.api.getStreakInfo()
        ]);
        
        this.render({ overview, goals, insights, streak });
    }
    
    render(data) {
        // Render compact preview card
    }
}
```

---

## Stage 15: Testing & Polish

### Unit Tests

| Test File | Coverage |
|-----------|----------|
| `test_analytics_db.py` | All analytics database methods |
| `test_analytics_bridge.py` | Bridge method JSON handling |
| `test_patterns.py` | Pattern detection logic |
| `test_goals.py` | Goal setting and tracking |
| `test_reflection_quality.py` | Reflection scoring |

### Test Cases for New Features

| Test | Description |
|------|-------------|
| `test_get_analytics_overview` | Returns correct totals and trends |
| `test_get_subject_analytics` | Subject breakdown with percentages |
| `test_get_tag_analytics` | Tag distribution by group |
| `test_get_difficulty_distribution` | Difficulty counts and labels |
| `test_get_activity_over_time` | Time series data for all periods |
| `test_get_patterns_and_insights` | Detects all 15 pattern types |
| `test_get_activity_heatmap` | Heatmap data structure |
| `test_get_streak_info` | Streak calculation accuracy |
| `test_set_weekly_goal` | Goal creation and update |
| `test_get_goal_history` | Historical goal data |
| `test_get_reflection_quality_stats` | Aggregate quality scores |
| `test_get_common_reflection_patterns` | Theme extraction |
| `test_get_source_analytics` | Source comparison data |
| `test_get_source_performance_over_time` | Source trends |
| `test_get_time_vs_difficulty_analysis` | Correlation calculation |
| `test_get_time_distribution` | Time bucketing |
| `test_get_self_assessment_accuracy` | Accuracy and bias calculation |
| `test_get_subject_exam_weight_analysis` | Quadrant categorization |
| `test_get_study_efficiency_score` | Efficiency score formula |

### Manual Test Checklist

- [ ] Analytics dashboard loads without errors
- [ ] All 4 overview stat cards show correct values
- [ ] Subject chart renders with correct data
- [ ] Subject chart click navigates to deep dive
- [ ] Tag donut chart shows all mistake types
- [ ] Activity chart responds to period tabs
- [ ] Difficulty bars show correct distribution
- [ ] Patterns & Insights cards render correctly
- [ ] Insight cards are clickable when related_id exists
- [ ] Exam filter dropdown populates correctly
- [ ] Exam filter updates all visualizations
- [ ] Subject deep dive page loads correctly
- [ ] Subject deep dive shows all sections
- [ ] Activity heatmap displays correctly
- [ ] Heatmap tooltips show date and count
- [ ] Streak cards show accurate values
- [ ] Goal widget shows current progress
- [ ] Goal edit modal opens and saves
- [ ] Goal history displays past weeks
- [ ] Reflection quality section displays
- [ ] Common reflection patterns show themes
- [ ] Word cloud renders common words
- [ ] Reflection insights appear
- [ ] Source comparison table displays
- [ ] Source performance line graph shows trends
- [ ] Time vs difficulty section displays
- [ ] Correlation value shows correctly
- [ ] Self-assessment accuracy displays
- [ ] Accuracy by difficulty breakdown shows
- [ ] Subject vs exam weight section displays
- [ ] Quadrant analysis categorizes correctly
- [ ] Efficiency score calculates correctly
- [ ] Recommendations list shows prioritized items
- [ ] Landing page preview card displays
- [ ] Preview card "View Full Report" link works
- [ ] No console errors during normal usage
- [ ] Charts resize correctly on window resize
- [ ] Mobile responsiveness (if applicable)

### Performance Testing

| Metric | Target |
|--------|--------|
| Dashboard load time | < 2 seconds |
| Chart render time | < 500ms each |
| API response time | < 200ms per call |
| Memory usage | < 100MB additional |

---

## Files Summary

### New Files

| File | Type | Purpose |
|------|------|---------|  
| `src/web/html/analytics.html` | HTML | Main analytics dashboard |
| `src/web/js/analytics.js` | JS | Dashboard logic |
| `src/web/css/analytics.css` | CSS | Analytics styles |
| `src/web/html/subject_analysis.html` | HTML | Subject deep dive page |
| `src/web/js/subject_analysis.js` | JS | Subject deep dive logic |
| `src/web/js/lib/d3.min.js` | JS | D3.js library (v7) |
| `src/web/js/charts/subject-chart.js` | JS | Subject pie/sunburst chart |
| `src/web/js/charts/tag-chart.js` | JS | Tag donut chart |
| `src/web/js/charts/activity-chart.js` | JS | Activity line/area chart |
| `src/web/js/charts/difficulty-chart.js` | JS | Difficulty bar chart |
| `src/web/js/charts/heatmap-chart.js` | JS | Activity heatmap |
| `src/web/js/charts/sparkline.js` | JS | Mini sparkline chart |
| `src/web/js/charts/scatter-chart.js` | JS | Scatter plot (time/difficulty) |
| `src/web/js/charts/multi-line-chart.js` | JS | Multi-line chart (source trends) |
| `src/web/js/charts/word-cloud.js` | JS | Word cloud (reflection patterns) |
| `src/web/js/components/streak-display.js` | JS | Streak cards |
| `src/web/js/components/goal-widget.js` | JS | Goal progress widget |
| `src/web/js/components/goal-modal.js` | JS | Goal setting modal |
| `src/web/js/components/insights-container.js` | JS | Pattern insight cards |
| `src/web/js/components/analytics-preview.js` | JS | Landing page preview |
| `src/web/js/components/accuracy-gauge.js` | JS | Self-assessment gauge |
| `src/web/js/components/efficiency-score.js` | JS | Efficiency score display |

### Modified Files

| File | Changes |
|------|---------|  
| `src/database/user_db.py` | Add ~28 analytics methods |
| `src/bridge/bridge.py` | Add ~25 bridge methods |
| `src/web/js/api.js` | Add ~25 API wrapper methods |
| `src/web/html/index.html` | Add analytics preview section |
| `src/web/css/styles.css` | Add shared analytics variables |

### Database Changes

| Change | Description |
|--------|-------------|  
| `user_goals` table | Goal tracking |
| `goal_periods` table | Goal history |
| `question_entries.reflection_quality_score` | Cached reflection scores |
| `reflection_themes` table | Cached reflection patterns |

---

## Navigation Flow

```
Landing Page (index.html)
    │
    ├── Analytics Preview Card
    │       │
    │       └── "View Full Analytics →"
    │               ↓
    │       Analytics Dashboard (analytics.html)
    │               │
    │               ├── Overview Stats (4 cards)
    │               ├── Subject Chart → Subject Deep Dive
    │               ├── Tag Chart
    │               ├── Activity Over Time Chart
    │               ├── Difficulty Distribution
    │               ├── Patterns & Insights
    │               ├── Study Heatmap + Streaks
    │               ├── Weekly Goal Section
    │               ├── Reflection Quality Section
    │               ├── Common Reflection Patterns
    │               ├── Source Comparison + Performance Over Time
    │               ├── Time vs Difficulty Analysis
    │               ├── Self-Assessment Accuracy
    │               └── Subject vs Exam Weight Analysis
    │
    └── Exam Cards
            └── "Browse" → entry_browser.html
```

---

## Future Enhancements (Post-Phase 6)

These features are deferred to future phases:

| Feature | Description | Target Phase |
|---------|-------------|--------------|
| Time of Day Analysis | When mistakes occur by hour | Phase 7+ |
| Per-Entry Reflection Scores | Show quality score on each entry | Phase 7 |
| Daily Goals | Goal granularity beyond weekly | Phase 7 |
| Subject-Specific Goals | Goals per subject area | Phase 7 |
| Export Reports | PDF analytics export | Phase 8+ |
| AnkiConnect Integration | Correlation with Anki reviews | Phase 8+ |
| Predictive Insights | AI-powered predictions | Phase 9+ (TBD) |

---

## Success Criteria

Phase 6 is complete when:

1. ✅ All database methods implemented and tested
2. ✅ Analytics dashboard loads with all sections
3. ✅ All D3.js charts render correctly
4. ✅ Exam filter updates all visualizations
5. ✅ Subject deep dive page functional
6. ✅ Pattern detection generates relevant insights
7. ✅ Activity heatmap displays correctly
8. ✅ Streak tracking works accurately
9. ✅ Goal setting and progress tracking works
10. ✅ Reflection quality aggregate stats display
11. ✅ Common reflection patterns/themes display
12. ✅ Source comparison section functional
13. ✅ Source performance over time chart works
14. ✅ Time vs difficulty analysis displays
15. ✅ Self-assessment accuracy section works
16. ✅ Subject vs exam weight analysis displays
17. ✅ Study efficiency score calculates correctly
18. ✅ Landing page preview card displays correctly
19. ✅ All navigation flows work
20. ✅ Manual test checklist passes
21. ✅ No console errors in normal usage
22. ✅ Performance targets met

---

## Document History

| Date | Version | Changes |
|------|---------|---------|  
| Dec 31, 2025 | 1.0 | Initial implementation plan |
| Dec 31, 2025 | 1.1 | Added Stages 7-10: Heatmap, Streaks, Goals, Reflection Quality, Source Comparison |
| Dec 31, 2025 | 1.2 | Added Stages 11-13: Time vs Difficulty, Self-Assessment Accuracy, Subject vs Exam Weight |
| Dec 31, 2025 | 1.3 | Expanded Stages 2-8 with full documentation, completed all stage details |

---

**END OF IMPLEMENTATION PLAN**