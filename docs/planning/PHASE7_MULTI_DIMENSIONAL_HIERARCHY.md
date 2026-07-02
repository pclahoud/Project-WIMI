# Phase 7: Multi-Dimensional Hierarchy System

**Status:** Planning  
**Created:** 2026-01-12  
**Type:** Optional Feature - Major Enhancement

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Core Concept](#core-concept)
3. [Database Architecture](#database-architecture)
4. [Optional Dimensions Design](#optional-dimensions-design)
5. [Exam Setup Workflow](#exam-setup-workflow)
6. [Question Entry Workflow](#question-entry-workflow)
7. [Analytics Architecture](#analytics-architecture)
8. [Template System](#template-system)
9. [Migration Strategy](#migration-strategy)
10. [Implementation Phases](#implementation-phases)
11. [Risk Assessment](#risk-assessment)
12. [Success Metrics](#success-metrics)
13. [Open Questions](#open-questions)

---

## Executive Summary

### Purpose

Transform WIMI's hierarchy system to support **optional multi-dimensional categorization** for exams that require questions to be classified across multiple independent dimensions (e.g., NBME Shelf Exams with Site of Care × Physician Task × System).

### Key Goals

1. **Maintain simplicity** for users with straightforward exams (SAT, GRE, single-hierarchy subjects)
2. **Unlock advanced analytics** for users with complex, multi-dimensional exams (USMLE, NBME Shelf)
3. **Enable cross-dimensional insights** such as performance heatmaps, interaction effects, and contextual recommendations
4. **Provide smooth migration path** from simple to multi-dimensional exams
5. **Support template-based exam creation** for common standardized test formats

### User Impact

- **Simple exam users:** No change to workflow, no forced complexity
- **Advanced exam users:** Rich cross-dimensional analytics, contextual performance insights
- **All users:** Choice-based system adapting to exam complexity needs

### Development Impact

- **Timeline:** 13-18 weeks (3-4.5 months) across 7 sub-phases
- **Database:** New tables for dimensions and multi-dimensional tags
- **UI/UX:** Parallel workflows for simple vs multi-dimensional exams
- **Analytics:** Extended to support cross-dimensional queries and visualizations

---

## Core Concept

### Problem Statement

Current WIMI hierarchy system assumes:
1. Single-path hierarchy: Each question belongs to one hierarchical branch
2. Weight propagation: All parent nodes inherit weights from children
3. Uniform structure: All exams follow similar hierarchical patterns

**This breaks down for exams like NBME Shelf Exams:**

An NBME question is categorized by three **independent dimensions**:
- **Site of Care:** Ambulatory, Emergency Department, Inpatient, Surgical
- **Physician Task:** Diagnosis, Management, Prevention, Monitoring
- **System:** Cardiovascular, Pulmonary, Gastrointestinal, etc.

These dimensions are **not hierarchically related** (Site doesn't contain Task; Task doesn't contain System). They are orthogonal categorizations.

### Current System Limitation

A question about diagnosing atrial fibrillation in an ambulatory setting should contribute weight to:
- Ambulatory (site)
- Diagnosis (task)
- Cardiovascular → Arrhythmias → Atrial Fibrillation (system)

But with current single-path hierarchy, it can only belong to one branch.

### Proposed Solution: Multi-Dimensional Tagging

Questions can be tagged with **one selection from each dimension**:

```
Question #123: "A 68-year-old presents to clinic with palpitations..."

Tags:
├─ Site of Care: Ambulatory
├─ Physician Task: Diagnosis
└─ System: Cardiovascular → Arrhythmias → Atrial Fibrillation
```

This enables analytics queries like:
- "How do I perform on Diagnosis tasks specifically in Emergency settings?"
- "What are my weakest Site × Task combinations?"
- "Does Cardiovascular performance differ by care setting?"

### Key Architectural Decision: **Optional Dimensions**

Multi-dimensional tagging is **optional**:
- **Simple exams** (SAT Math, GRE Verbal): Use traditional single hierarchy
- **Multi-dimensional exams** (NBME, USMLE): Use dimension-based tagging
- **User choice** during exam creation determines exam type
- **Conversion available** from simple → multi-dimensional (not reversible)

---

## Database Architecture

### New Tables

#### 1. `exam_dimensions`

Defines the categorical dimensions for each exam.

**Schema:**
```sql
CREATE TABLE exam_dimensions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id INTEGER NOT NULL,
    name TEXT NOT NULL,                    -- e.g., "Site of Care"
    display_order INTEGER NOT NULL,        -- UI ordering
    is_required INTEGER DEFAULT 1,         -- Must tag in this dimension?
    allow_multiple INTEGER DEFAULT 0,      -- Can select multiple items?
    description TEXT,                      -- Help text for users
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE,
    UNIQUE(exam_id, name),
    UNIQUE(exam_id, display_order)
);

CREATE INDEX idx_dimensions_exam ON exam_dimensions(exam_id);
CREATE INDEX idx_dimensions_order ON exam_dimensions(exam_id, display_order);
```

**Purpose:**
- Store metadata about each dimension
- Determine UI presentation order
- Define validation rules (required, single vs multiple selection)

**Example Data:**
```
id | exam_id | name            | display_order | is_required | allow_multiple
---|---------|-----------------|---------------|-------------|---------------
1  | 5       | Site of Care    | 1             | 1           | 0
2  | 5       | Physician Task  | 2             | 1           | 0
3  | 5       | System          | 3             | 1           | 0
```

#### 2. `question_hierarchy_tags`

Links questions to hierarchy nodes with dimension context.

**Schema:**
```sql
CREATE TABLE question_hierarchy_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL,
    hierarchy_id INTEGER NOT NULL,
    dimension_id INTEGER NOT NULL,
    tagged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE,
    FOREIGN KEY (hierarchy_id) REFERENCES exam_hierarchy(id) ON DELETE CASCADE,
    FOREIGN KEY (dimension_id) REFERENCES exam_dimensions(id) ON DELETE CASCADE,
    UNIQUE(entry_id, dimension_id, hierarchy_id),
    CHECK(
        -- Validate hierarchy belongs to same exam as dimension
        EXISTS (
            SELECT 1 FROM exam_hierarchy h
            JOIN exam_dimensions d ON d.exam_id = h.exam_id
            WHERE h.id = hierarchy_id AND d.id = dimension_id
        )
    )
);

CREATE INDEX idx_tags_entry ON question_hierarchy_tags(entry_id);
CREATE INDEX idx_tags_hierarchy ON question_hierarchy_tags(hierarchy_id);
CREATE INDEX idx_tags_dimension ON question_hierarchy_tags(dimension_id);
CREATE UNIQUE INDEX idx_tags_entry_dimension ON question_hierarchy_tags(entry_id, dimension_id);
```

**Purpose:**
- Store multi-dimensional tags for each question
- Enable efficient querying by dimension
- Enforce one tag per dimension per question (unless allow_multiple=1)

**Example Data:**
```
id | entry_id | hierarchy_id | dimension_id | tagged_at
---|----------|--------------|--------------|--------------------
1  | 123      | 45           | 1            | 2026-01-12 14:30:00
2  | 123      | 67           | 2            | 2026-01-12 14:30:00
3  | 123      | 89           | 3            | 2026-01-12 14:30:00
4  | 123      | 90           | 3            | 2026-01-12 14:30:00
```

**Note:** Entry 123 is tagged with hierarchy nodes 89 and 90 in the same dimension (3). This allows tagging both parent (Cardiovascular) and child (Arrhythmias) for hierarchical context.

#### 3. Modified `exam_hierarchy`

**New Field:**
```sql
ALTER TABLE exam_hierarchy ADD COLUMN dimension_id INTEGER;
ALTER TABLE exam_hierarchy ADD FOREIGN KEY (dimension_id) REFERENCES exam_dimensions(id) ON DELETE CASCADE;

CREATE INDEX idx_hierarchy_dimension ON exam_hierarchy(dimension_id);
```

**Purpose:**
- Link hierarchy nodes to their dimension
- `dimension_id = NULL` → legacy hierarchy (simple exam)
- `dimension_id = <value>` → node belongs to specific dimension

**Backward Compatibility:**
- Existing hierarchies have `dimension_id = NULL`
- Legacy analytics queries ignore dimension_id
- New dimension-based exams populate dimension_id

### Deprecated Tables (Maintained for Backward Compatibility)

#### `entry_hierarchy_links`

**Status:** Deprecated for new multi-dimensional exams, maintained for simple exams

**Usage:**
- Simple exams: Continue using this table
- Multi-dimensional exams: Use `question_hierarchy_tags` instead
- Detection: If exam has rows in `exam_dimensions`, use new system

### Exam Type Detection

**Database Method:**
```python
def exam_uses_dimensions(exam_id):
    """
    Determine if exam uses multi-dimensional system.
    
    Returns:
        bool: True if exam has dimensions, False if simple hierarchy
    """
    count = db.execute(
        "SELECT COUNT(*) FROM exam_dimensions WHERE exam_id = ?",
        (exam_id,)
    ).fetchone()[0]
    return count > 0
```

**Usage Throughout Application:**
- Question entry form: Show appropriate UI
- Analytics dashboard: Load correct visualization components
- Export: Include dimension columns or single hierarchy
- Entry browsing: Filter by dimensions or single path

---

## Optional Dimensions Design

### Core Principle: User Choice

Multi-dimensional categorization is **optional**, not mandatory. Users choose exam type based on their needs.

### Exam Type Decision Flow

```
User Creates New Exam
         ↓
    Choose Exam Type
         ↓
    ┌────┴────┐
    ↓         ↓
 Simple    Multi-Dimensional
  Exam         Exam
    ↓            ↓
Single      Multiple Independent
Hierarchy   Dimension Categories
    ↓            ↓
Standard    Advanced Cross-
Analytics   Dimensional Analytics
```

### Exam Type Selection UI

**During Exam Creation (Step 1):**

```
┌────────────────────────────────────────────┐
│ What type of exam are you studying for?   │
├────────────────────────────────────────────┤
│                                            │
│ ○ Simple Exam                              │
│   Single topic hierarchy                   │
│   (e.g., SAT Math, GRE Verbal)             │
│                                            │
│   Example: Math → Algebra → Quadratics    │
│   Analytics: Performance by topic          │
│                                            │
│   [Learn More]                             │
├────────────────────────────────────────────┤
│                                            │
│ ○ Multi-Dimensional Exam (Advanced)       │
│   Questions categorized across multiple    │
│   independent dimensions                   │
│                                            │
│   Example: NBME Shelf, USMLE               │
│   Analytics: Cross-dimensional insights    │
│                                            │
│   [Learn More]                             │
│                                            │
└────────────────────────────────────────────┘

[Continue]
```

**"Learn More" Modals:**

*Simple Exam:*
```
Simple Exam Structure

Best for exams with straightforward topic organization:
• SAT Math (Algebra, Geometry, etc.)
• GRE Verbal (Reading Comp, Vocabulary, etc.)
• Subject tests with clear topic hierarchies

You'll create a single hierarchy like:
Mathematics
├─ Algebra
│  ├─ Linear Equations
│  └─ Quadratic Equations
└─ Geometry
   ├─ Triangles
   └─ Circles

Analytics will show your performance by topic.

[Close]
```

*Multi-Dimensional Exam:*
```
Multi-Dimensional Exam Structure

Best for complex standardized exams where questions
can be categorized in multiple independent ways:

Example: NBME Shelf Exam
Each question is tagged across 3 dimensions:
• Site of Care: Where (Ambulatory, Emergency, etc.)
• Physician Task: What (Diagnosis, Management, etc.)
• System: Which (Cardiovascular, Pulmonary, etc.)

Advanced Analytics Include:
✓ Performance heatmaps (Site × Task)
✓ Contextual insights ("You're weaker on Cardio in Emergency")
✓ Interaction effect detection
✓ Smart study recommendations

Recommended for: USMLE, NBME Shelf Exams, MCAT

[Close]
```

### Template-Driven Type Selection
Note for claude: Ignore this section for now.
**Alternative Flow: Choose Template First**

Templates automatically determine exam type:

```
Choose Template or Create Custom

┌─ Simple Exam Templates ─────────────┐
│ • SAT Math                          │
│ • GRE Verbal                        │
│ • LSAT Logic Games                  │
│ • Custom Simple Exam                │
└─────────────────────────────────────┘

┌─ Multi-Dimensional Templates ───────┐
│ • NBME Shelf Exam - Internal Med    │
│ • NBME Shelf Exam - Surgery         │
│ • USMLE Step 2 CK                   │
│ • USMLE Step 1                      │
│ • Custom Multi-Dimensional Exam     │
└─────────────────────────────────────┘
```

- User selects template → exam type determined automatically
- User can modify template after import
- Custom options allow building from scratch

### Conversion Path: Simple → Multi-Dimensional

**Available in Exam Settings:**

```
Exam Settings: SAT Math

Type: Simple Exam

[Convert to Multi-Dimensional Exam]

Note: This action cannot be undone. Your current
hierarchy will become one dimension, and you can
add additional dimensions for more detailed analysis.
```

**Conversion Wizard Flow:**

**Step 1: Choose Primary Dimension**
```
Your current hierarchy will become which dimension?

○ Topic (recommended)
○ Difficulty Level
○ Question Type
○ Custom: [________]

Current Hierarchy Preview:
Mathematics
├─ Algebra
└─ Geometry

Will become:
Dimension: Topic
├─ Algebra
└─ Geometry
```

**Step 2: Add Additional Dimensions (Optional)**
```
Add more dimensions? (Optional)

[+ Add Dimension]

Examples:
• Difficulty Level (Easy, Medium, Hard)
• Question Type (Multiple Choice, Grid-In)
• Concepts (Abstract, Applied, Computational)
```

**Step 3: Tag Existing Questions**
```
Your 50 existing questions are tagged in "Topic"
dimension. Do you want to tag them in your new
dimensions?

○ Tag now (bulk editor)
○ Tag gradually as I review questions
○ Leave untagged (can filter later)

[Complete Conversion]
```

### Feature Gating

**Simple Exams Have Access To:**
- ✓ Single hierarchy topic browsing
- ✓ Performance by topic (sunburst, treemap)
- ✓ Mistake type analysis
- ✓ Time vs difficulty analysis
- ✓ Reflection quality scores
- ✓ Goal tracking
- ✓ Standard reports

**Multi-Dimensional Exams Additionally Have:**
- ✓ Dimension selector (view by any dimension)
- ✓ Cross-dimension heatmaps
- ✓ Interaction effect detection
- ✓ Context-aware study recommendations
- ✓ Triple-dimension analysis
- ✓ Dimension-specific trend comparison
- ✓ Advanced pattern detection

**Clear Communication:**
- Analytics that require dimensions show: "Multi-Dimensional Exams Only"
- Tooltip: "Upgrade this exam to unlock cross-dimensional insights [Learn More]"
- Non-intrusive suggestions in dashboard

---

## Exam Setup Workflow

### Simple Exam Setup (No Changes from Current System)

**Flow:**
1. Create exam → Enter name, description
2. Build hierarchy → Add topics, subtopics, weights
3. Finalize → Ready to add questions

**UI:** Existing hierarchy builder (current WIMI interface)

**Database:**
- `exams` table: New row
- `exam_dimensions` table: No rows (empty)
- `exam_hierarchy` table: Nodes with `dimension_id = NULL`

### Multi-Dimensional Exam Setup

#### Stage 1: Dimension Definition

**User Actions:**
1. Name each dimension (e.g., "Site of Care")
2. Provide description/help text
3. Mark as required or optional
4. Set display order (affects UI presentation)

**UI Concept:**

```
Exam Setup - Step 2: Define Dimensions
┌─────────────────────────────────────────┐
│ Define the independent categories for   │
│ classifying your questions.              │
├─────────────────────────────────────────┤
│                                          │
│ Dimension 1                              │
│ Name: [Site of Care            ]         │
│ Description:                             │
│ [Where the patient encounter occurs]     │
│ ☑ Required                               │
│ ☐ Allow multiple selections             │
│ [↑] [↓] [Delete]                         │
│                                          │
├─────────────────────────────────────────┤
│                                          │
│ Dimension 2                              │
│ Name: [Physician Task          ]         │
│ Description:                             │
│ [What the physician must do]             │
│ ☑ Required                               │
│ ☐ Allow multiple selections             │
│ [↑] [↓] [Delete]                         │
│                                          │
├─────────────────────────────────────────┤
│ [+ Add Dimension]                        │
│                                          │
│ [Previous] [Next: Build Hierarchies]    │
└─────────────────────────────────────────┘
```

**Validation:**
- At least one dimension required
- Dimension names unique within exam
- Display order automatically assigned but user-adjustable
- Cannot proceed to next step with empty dimension names

**Database Result:**
```sql
INSERT INTO exam_dimensions (exam_id, name, display_order, is_required, description)
VALUES 
    (5, 'Site of Care', 1, 1, 'Where the patient encounter occurs'),
    (5, 'Physician Task', 2, 1, 'What the physician must do'),
    (5, 'System', 3, 1, 'Organ system involved');
```

#### Stage 2: Hierarchy Creation Per Dimension

**User Actions:**
1. Select dimension from tabs/dropdown
2. Build hierarchy for that dimension
3. Repeat for each dimension

**UI Concept:**

```
Exam Setup - Step 3: Build Hierarchies

Current Dimension: [Site of Care ▼]

Site of Care Hierarchy:
┌─────────────────────────────────────────┐
│ □ Ambulatory                            │
│   Weight: [40] - [50] %                 │
│   [Add Child] [Edit] [Delete]           │
├─────────────────────────────────────────┤
│ □ Emergency Department                  │
│   Weight: [20] - [30] %                 │
│   [Add Child] [Edit] [Delete]           │
├─────────────────────────────────────────┤
│ □ Inpatient                             │
│   Weight: [20] - [30] %                 │
│   □ ICU (child)                         │
│     Weight: [5] - [10] %                │
│   □ Floor (child)                       │
│     Weight: [15] - [20] %               │
│   [Add Child] [Edit] [Delete]           │
├─────────────────────────────────────────┤
│ [+ Add Node]                            │
└─────────────────────────────────────────┘

[Import from Template] [Previous] [Next Dimension]
```

**Key Features:**
- Tab bar or dropdown to switch between dimensions
- Each dimension has completely independent hierarchy
- Can import common dimension hierarchies (e.g., "Standard NBME Sites")
- Weights apply within dimension (each dimension totals 100%)
- Hierarchies can be different depths across dimensions

**Workflow:**
1. Build hierarchy for Dimension 1
2. Click "Next Dimension" or select next tab
3. Build hierarchy for Dimension 2
4. Repeat until all dimensions have hierarchies
5. Finalize exam setup

**Database Result:**
```sql
-- Site of Care hierarchy nodes
INSERT INTO exam_hierarchy (exam_id, parent_id, name, dimension_id, weight_min, weight_max)
VALUES 
    (5, NULL, 'Ambulatory', 1, 40, 50),
    (5, NULL, 'Emergency Department', 1, 20, 30),
    (5, NULL, 'Inpatient', 1, 20, 30);

-- Physician Task hierarchy nodes
INSERT INTO exam_hierarchy (exam_id, parent_id, name, dimension_id, weight_min, weight_max)
VALUES 
    (5, NULL, 'Diagnosis', 2, 30, 40),
    (5, NULL, 'Management', 2, 35, 45),
    (5, NULL, 'Prevention', 2, 10, 15);

-- System hierarchy nodes (user defines)
-- ...
```

#### Stage 3: Review and Finalize

**Summary View:**

```
Exam Setup - Review

Exam: Internal Medicine Shelf Exam
Type: Multi-Dimensional

Dimensions:
├─ Site of Care (3 items, required)
├─ Physician Task (6 items, required)
└─ System (15 items, 3 levels deep, required)

Total Nodes: 24
Ready to add questions

[Back] [Create Exam]
```

**Actions:**
- Review dimension structure
- Edit if needed (back buttons)
- Create exam and proceed to question entry

---

## Question Entry Workflow

### Simple Exam: Single Hierarchy Selection (No Change)

**UI:** Current WIMI hierarchy selector

**Flow:**
1. Select topic from hierarchy tree
2. Optionally drill down to subtopics
3. Question linked via `entry_hierarchy_links`

### Multi-Dimensional Exam: Multi-Dimension Tagging
Developer Note: Not completed yet, will be worked on in the future.
**UI Concept:**

```
Add Question - Categorization

Select one item from each dimension:

┌─ Site of Care * ────────────────────────┐
│ ○ Ambulatory                            │
│ ● Emergency Department                  │
│ ○ Inpatient                             │
│   ○ ICU                                 │
│   ○ Floor                               │
│ ○ Surgical                              │
└─────────────────────────────────────────┘

┌─ Physician Task * ──────────────────────┐
│ ● Diagnosis                             │
│ ○ Mechanism of Disease                  │
│ ○ Management                            │
│ ○ Health Maintenance                    │
│ ○ Principles of Therapeutics            │
│ ○ Surveillance & Monitoring             │
└─────────────────────────────────────────┘

┌─ System * ──────────────────────────────┐
│ ○ Cardiovascular                        │
│   ● Arrhythmias                         │
│     ● Atrial Fibrillation               │
│     ○ Ventricular Tachycardia           │
│   ○ Heart Failure                       │
│ ○ Pulmonary                             │
│ ○ Gastrointestinal                      │
└─────────────────────────────────────────┘

* = Required dimension

[Save Question]
```

**UI Variations (User Preference or Screen Size):**

**Option A: Vertical Stacked (above example)**
- Good for: Narrow screens, many dimensions
- Collapsible sections to save space

**Option B: Tabbed Interface**
```
[ Site of Care ] | Physician Task | System |

Current Tab: Site of Care
○ Ambulatory
● Emergency Department
○ Inpatient
  ...

[Previous: Question Details] [Next: Physician Task]
```

**Option C: Side-by-Side Columns (Wide Screens)**
```
┌─ Site of Care ──┐┌─ Physician Task ─┐┌─ System ─────────┐
│ ● Emergency Dept││ ● Diagnosis       ││ ● Cardiovascular │
│ ○ Ambulatory    ││ ○ Management      ││   ● Arrhythmias  │
│ ...             ││ ...               ││   ...            │
└─────────────────┘└───────────────────┘└──────────────────┘
```

**Option D: Dropdown Selectors (Shallow Hierarchies)**
```
Site of Care: [Emergency Department     ▼]
Physician Task: [Diagnosis              ▼]
System: [Cardiovascular > Arrhythmias   ▼]
```

**Key UI Features:**
- Visual separation between dimensions (borders, spacing, headers)
- Clear labeling of required (*) vs optional dimensions
- Collapsible/expandable trees for deep hierarchies
- Validation: Prevent saving if required dimensions untagged
- Radio buttons (single selection) vs checkboxes (multi-selection if allow_multiple=true)
- "Quick select last used" for faster entry

**Validation Rules:**
- Required dimensions must have selection
- Cannot select multiple items in same dimension (unless allow_multiple=true)
- Can select both parent and child in same dimension for context
- Must click "Save" to persist tags

**Database Operations:**

When user saves question with tags:
```sql
-- Create question entry
INSERT INTO entries (exam_id, date_created, correct, difficulty_rating, ...)
VALUES (5, CURRENT_TIMESTAMP, 0, 3, ...);
-- Returns entry_id = 123

-- Create tags for each dimension
INSERT INTO question_hierarchy_tags (entry_id, hierarchy_id, dimension_id)
VALUES 
    (123, 45, 1),  -- Emergency Department in Site of Care
    (123, 67, 2),  -- Diagnosis in Physician Task
    (123, 89, 3),  -- Cardiovascular in System
    (123, 90, 3);  -- Arrhythmias in System (child of 89)
```

### Editing Question Tags
Developer Note: Not completed yet, will be worked on in the future.
**UI Access:**
- Entry list view: "Edit Tags" button on each entry
- Entry detail view: "Edit Categorization" section

**Edit UI:**
- Same multi-dimension selector as entry form
- Pre-populate with current tags
- Allow changing tags
- Update `question_hierarchy_tags` (delete old, insert new)

**Bulk Tag Editor (Phase 7.5):**

```
Bulk Tag Editor

Selected: 15 questions

Change tags for selected questions:

Dimension: [Site of Care ▼]
From: [Emergency Department ▼]
To: [Ambulatory ▼]

[Apply Changes]
```

**Use Cases:**
- Realized multiple questions were mistagged
- Converting legacy questions after dimension addition
- Adjusting categorization based on new understanding

---

## Analytics Architecture

### Overview: Two Parallel Analytics Paths

```
User Views Analytics
         ↓
    Detect Exam Type
         ↓
    ┌────┴────┐
    ↓         ↓
  Simple  Multi-Dimensional
Analytics    Analytics
    ↓            ↓
Standard    Extended Features:
Features    • Dimension selector
            • Cross-dimension heatmaps
            • Interaction effects
            • Contextual recommendations
```

### Simple Exam Analytics (No Changes)

**Existing Features Continue to Work:**
- Performance by topic (sunburst, treemap)
- Time vs difficulty scatter
- Mistake type distribution
- Reflection quality scores
- Goal tracking
- Weight-based study recommendations

**Queries Use:**
- `entry_hierarchy_links` table
- `exam_hierarchy` table (dimension_id = NULL)
- Current analytics methods

### Multi-Dimensional Exam Analytics

#### Section 1: Single-Dimension View

**Purpose:** View performance by one dimension at a time (similar to simple exam)

**UI:**

```
Analytics Dashboard

Exam: Internal Medicine Shelf Exam

View by Dimension: [Site of Care ▼]

Performance by Site of Care:
┌─────────────────────────────────────────┐
│        [Sunburst Chart]                 │
│                                          │
│  Ambulatory: 75% (20 questions)         │
│  Emergency: 68% (15 questions)          │
│  Inpatient: 82% (18 questions)          │
│  Surgical: 80% (5 questions)            │
└─────────────────────────────────────────┘
```

**Query Pattern:**

```sql
-- Performance by selected dimension
SELECT 
    h.name,
    COUNT(*) as total_questions,
    AVG(e.correct) as accuracy,
    AVG(e.time_spent) as avg_time
FROM entries e
JOIN question_hierarchy_tags qht ON e.id = qht.entry_id
JOIN exam_hierarchy h ON qht.hierarchy_id = h.id
WHERE qht.dimension_id = ? -- Selected dimension
GROUP BY h.name
ORDER BY accuracy ASC
```

**Features:**
- Dropdown to switch between dimensions
- Same visualizations as simple exams (sunburst, treemap)
- Weight-based performance calculations within dimension

#### Section 2: Cross-Dimension Heatmap

**Purpose:** View performance at intersections of two dimensions

**UI:**

```
Cross-Dimension Analysis

Dimension A: [Site of Care ▼]
Dimension B: [Physician Task ▼]

Performance Heatmap:
┌───────────┬──────────┬────────────┬────────────┐
│           │Diagnosis │ Management │ Prevention │
├───────────┼──────────┼────────────┼────────────┤
│Ambulatory │ 72% (12) │  80% (15)  │  88% (8)   │
│           │ 🟨       │  🟩        │  🟩        │
├───────────┼──────────┼────────────┼────────────┤
│Emergency  │ 65% (10) │  70% (8)   │  N/A       │
│           │ 🟥       │  🟨        │            │
├───────────┼──────────┼────────────┼────────────┤
│Inpatient  │ 78% (18) │  85% (20)  │  82% (6)   │
│           │ 🟩       │  🟩        │  🟩        │
├───────────┼──────────┼────────────┼────────────┤
│Surgical   │ 90% (2)  │  95% (3)   │  N/A       │
│           │ 🟩       │  🟩        │            │
└───────────┴──────────┴────────────┴────────────┘

Legend: 🟥 <70%  🟨 70-80%  🟩 >80%

Click any cell to view questions in that combination.
```

**Query Pattern:**

```sql
-- Cross-dimension performance matrix
SELECT 
    h1.name as dimension_a_value,
    h2.name as dimension_b_value,
    COUNT(*) as n,
    AVG(e.correct) as accuracy,
    AVG(e.time_spent) as avg_time
FROM entries e
JOIN question_hierarchy_tags qht1 ON e.id = qht1.entry_id
JOIN question_hierarchy_tags qht2 ON e.id = qht2.entry_id
JOIN exam_hierarchy h1 ON qht1.hierarchy_id = h1.id
JOIN exam_hierarchy h2 ON qht2.hierarchy_id = h2.id
WHERE qht1.dimension_id = ?  -- Dimension A
  AND qht2.dimension_id = ?  -- Dimension B
  AND e.exam_id = ?
GROUP BY h1.name, h2.name
HAVING n >= 3  -- Only show cells with sufficient data
ORDER BY accuracy ASC
```

**Visualization Details:**
- Color gradient: Red (poor) → Yellow (average) → Green (strong)
- Cell annotation: Accuracy + question count
- Grayed out cells: Insufficient data (N < 3)
- Interactive: Click cell → drill down to question list
- Export: CSV download of full matrix

**Insights Automatically Shown:**
- "Your weakest combination: Emergency + Diagnosis (65%)"
- "Strongest combination: Surgical + Management (95%)"
- "Emergency setting reduces accuracy by 8% across all tasks"

#### Section 3: Triple-Dimension Analysis (Advanced)

**Purpose:** Identify specific 3-way combinations that are problematic

**UI:**

```
Advanced Analysis: Three-Way Combinations

Dimensions: [Site of Care] × [Physician Task] × [System]

Weakest Combinations (min 3 questions):
┌────────────────────────────────────────────────┐
│ 1. Emergency + Diagnosis + Cardiovascular      │
│    Accuracy: 58% (5 questions)                 │
│    Avg Time: 195 sec                           │
│    [View Questions] [Add to Study Plan]        │
├────────────────────────────────────────────────┤
│ 2. Inpatient + Management + Pulmonary          │
│    Accuracy: 62% (8 questions)                 │
│    Avg Time: 210 sec                           │
│    [View Questions] [Add to Study Plan]        │
├────────────────────────────────────────────────┤
│ 3. Ambulatory + Prevention + Endocrine         │
│    Accuracy: 65% (4 questions)                 │
│    Avg Time: 180 sec                           │
│    [View Questions] [Add to Study Plan]        │
└────────────────────────────────────────────────┘

Strongest Combinations:
[Similar list showing best-performing combos]
```

**Query Pattern:**

```sql
-- Triple-dimension analysis
SELECT 
    h1.name as site,
    h2.name as task,
    h3.name as system,
    COUNT(*) as n,
    AVG(e.correct) as accuracy,
    AVG(e.time_spent) as avg_time
FROM entries e
JOIN question_hierarchy_tags qht1 ON e.id = qht1.entry_id AND qht1.dimension_id = 1
JOIN question_hierarchy_tags qht2 ON e.id = qht2.entry_id AND qht2.dimension_id = 2
JOIN question_hierarchy_tags qht3 ON e.id = qht3.entry_id AND qht3.dimension_id = 3
JOIN exam_hierarchy h1 ON qht1.hierarchy_id = h1.id
JOIN exam_hierarchy h2 ON qht2.hierarchy_id = h2.id
JOIN exam_hierarchy h3 ON qht3.hierarchy_id = h3.id
WHERE e.exam_id = ?
GROUP BY h1.name, h2.name, h3.name
HAVING n >= 3
ORDER BY accuracy ASC
LIMIT 10
```

**Use Case:**
- Medical student discovers: "I struggle specifically with diagnosing cardiovascular issues in emergency settings"
- Action: Focus study on that exact context

#### Section 4: Contextual Performance & Interaction Effects

**Purpose:** Detect when performance in a combination is worse than expected from individual dimensions

**Concept:**

If a student is:
- 75% accurate on Cardiovascular overall
- 70% accurate in Emergency overall
- But only 58% on Cardiovascular in Emergency

→ **Interaction effect detected**: The combination creates unique difficulty beyond the sum of individual challenges

**UI:**

```
Interaction Effect Analysis

Combination: Emergency Department + Cardiovascular
┌────────────────────────────────────────────────┐
│ Your Performance:                              │
│ • Emergency overall: 70%                       │
│ • Cardiovascular overall: 75%                  │
│ • Expected (average): 72.5%                    │
│                                                │
│ • Actual (Emergency + Cardio): 58%             │
│                                                │
│ ⚠️ 14.5% interaction penalty detected          │
│                                                │
│ Insight: You perform significantly worse on    │
│ Cardiovascular when in Emergency settings.     │
│ This suggests time pressure or complexity in   │
│ emergency scenarios is a specific weakness.    │
│                                                │
│ [View Questions] [Add to Study Plan]           │
└────────────────────────────────────────────────┘
```

**Algorithm:**

```python
def detect_interaction_effect(entry_ids, dim_a_id, dim_b_id):
    """
    Calculate if performance at A×B intersection differs from expected.
    
    Expected = (accuracy_at_A + accuracy_at_B) / 2
    Actual = accuracy_at_A_and_B
    Interaction = Actual - Expected
    """
    
    # Get accuracy for all questions in dimension A value
    accuracy_a = get_accuracy(filter_by_dimension(entry_ids, dim_a_id))
    
    # Get accuracy for all questions in dimension B value
    accuracy_b = get_accuracy(filter_by_dimension(entry_ids, dim_b_id))
    
    # Get accuracy for questions in BOTH A and B
    accuracy_ab = get_accuracy(
        filter_by_both_dimensions(entry_ids, dim_a_id, dim_b_id)
    )
    
    expected = (accuracy_a + accuracy_b) / 2
    interaction = accuracy_ab - expected
    
    if abs(interaction) > 0.10:  # 10% threshold
        return {
            'detected': True,
            'interaction': interaction,
            'expected': expected,
            'actual': accuracy_ab,
            'severity': 'high' if abs(interaction) > 0.15 else 'medium'
        }
    
    return {'detected': False}
```

**Display:**
- Automatically scan all dimension combinations
- Surface top 5 positive and negative interactions
- Positive interaction: "You perform better than expected on..."
- Negative interaction: "You struggle more than expected on..."

#### Section 5: Mistake Type by Context

**Purpose:** Understand if mistake patterns differ across dimensions

**UI:**

```
Mistake Patterns by Context

Dimension: [Site of Care ▼]

┌────────────────────────────────────────────────┐
│ Ambulatory                                     │
│ ▮▮▮▮▮▮▮▮▮▮▮▮ Misread Question (40%)           │
│ ▮▮▮▮▮▮▮▮▮ Calculation Error (30%)             │
│ ▮▮▮▮▮▮▮▮▮ Knowledge Gap (30%)                 │
├────────────────────────────────────────────────┤
│ Emergency Department                           │
│ ▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮ Misread Question (60%)    │
│ ▮▮▮▮▮▮▮ Calculation Error (25%)               │
│ ▮▮▮▮▮ Knowledge Gap (15%)                     │
├────────────────────────────────────────────────┤
│ Inpatient                                      │
│ ▮▮▮▮▮▮▮ Misread Question (25%)                │
│ ▮▮▮▮▮▮ Calculation Error (20%)                │
│ ▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮ Knowledge Gap (55%)          │
└────────────────────────────────────────────────┘

Insight: You make more reading errors under Emergency
time pressure, but more knowledge gaps in complex
Inpatient scenarios.
```

**Query Pattern:**

```sql
-- Mistake type distribution by dimension
SELECT 
    h.name as dimension_value,
    e.mistake_type,
    COUNT(*) as occurrences,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (PARTITION BY h.name), 1) as percentage
FROM entries e
JOIN question_hierarchy_tags qht ON e.id = qht.entry_id
JOIN exam_hierarchy h ON qht.hierarchy_id = h.id
WHERE qht.dimension_id = ?
  AND e.correct = 0
  AND e.mistake_type IS NOT NULL
GROUP BY h.name, e.mistake_type
ORDER BY h.name, percentage DESC
```

**Insight Generation:**
- Identify dominant mistake type per context
- Compare mistake distributions across contexts
- Auto-generate recommendations:
  - "In Emergency: Slow down and read carefully"
  - "In Inpatient: Focus on knowledge gaps in complex conditions"

#### Section 6: Weighted Study Recommendations

**Purpose:** Prioritize study targets using dimension weights and performance gaps

**Algorithm:**

```python
def generate_study_recommendations(exam_id):
    """
    Calculate priority scores for dimension combinations.
    
    Priority Score = weight_combined × performance_gap × context_penalty
    
    Where:
    - weight_combined = weight_dim_a × weight_dim_b
    - performance_gap = (1 - accuracy)
    - context_penalty = 1.5 if interaction effect detected, else 1.0
    """
    
    recommendations = []
    
    # For each dimension combination with sufficient data (N >= 3)
    for combo in get_dimension_combinations(exam_id, min_n=3):
        
        # Calculate combined weight
        weight_a = get_dimension_weight(combo.dim_a_id, combo.hierarchy_a_id)
        weight_b = get_dimension_weight(combo.dim_b_id, combo.hierarchy_b_id)
        weight_combined = weight_a * weight_b
        
        # Calculate performance gap
        accuracy = get_combo_accuracy(combo)
        performance_gap = 1 - accuracy
        
        # Detect interaction effect
        interaction = detect_interaction_effect(combo)
        context_penalty = 1.5 if interaction['detected'] and interaction['interaction'] < 0 else 1.0
        
        # Calculate priority score
        priority = weight_combined * performance_gap * context_penalty
        
        recommendations.append({
            'combination': combo,
            'priority': priority,
            'weight': weight_combined,
            'accuracy': accuracy,
            'interaction': interaction,
            'n_questions': combo.count
        })
    
    # Sort by priority descending
    recommendations.sort(key=lambda x: x['priority'], reverse=True)
    
    return recommendations[:10]  # Top 10
```

**UI:**

```
Study Recommendations

Based on exam weights and your performance:

┌────────────────────────────────────────────────┐
│ 1. Emergency + Diagnosis + Cardiovascular      │
│    Priority: ★★★★★ (Very High)                │
│                                                │
│    Why this is important:                      │
│    • High exam weight (35% × 40% = 14%)       │
│    • Low accuracy (58%)                        │
│    • Interaction effect detected               │
│                                                │
│    Focus on:                                   │
│    • Time-pressured Cardio diagnosis           │
│    • Emergency department protocols            │
│    • Arrhythmia recognition under stress       │
│                                                │
│    [View Questions] [Create Study Goal]        │
├────────────────────────────────────────────────┤
│ 2. Inpatient + Management + Pulmonary          │
│    Priority: ★★★★☆ (High)                     │
│    ...                                         │
└────────────────────────────────────────────────┘
```

**Features:**
- Ranked list of study priorities
- Explanation of priority calculation
- Actionable focus areas
- One-click goal creation
- Export to study schedule

#### Section 7: Temporal Trends by Dimension

**Purpose:** Track improvement over time within dimensions

**UI:**

```
Performance Trends

Dimension: [Site of Care ▼]
Item: [Emergency Department ▼]

┌────────────────────────────────────────────────┐
│                                                │
│   100% ┤                                       │
│        │                            ●──●       │
│    80% ┤                     ●──●              │
│        │              ●──●                     │
│    60% ┤       ●──●                            │
│        │ ●──●                                  │
│    40% ┤                                       │
│        │                                       │
│     0% └────────────────────────────────       │
│        Week1  Week2  Week3  Week4  Week5       │
│                                                │
└────────────────────────────────────────────────┘

Trend: ↗️ Improving (13% increase over 5 weeks)

Compare to other sites:
• Ambulatory: ↗️ +8%
• Inpatient: → Stable
• Surgical: ↗️ +5%

Insight: Your Emergency performance is improving
faster than other sites. Continue focused practice.
```

**Query Pattern:**

```sql
-- Temporal trend for specific dimension value
SELECT 
    DATE(e.date_created) as study_date,
    AVG(e.correct) as accuracy,
    COUNT(*) as n
FROM entries e
JOIN question_hierarchy_tags qht ON e.id = qht.entry_id
WHERE qht.hierarchy_id = ?  -- Specific dimension value
GROUP BY DATE(e.date_created)
HAVING n >= 2
ORDER BY study_date ASC
```

**Features:**
- Line charts for multiple dimension values overlaid
- Trend analysis (improving, stable, declining)
- Comparison across dimension values
- Statistical significance (is improvement real or noise?)
- Export chart as image

### Visualization Components Summary

| Visualization | Exam Type | Purpose | Dimensions |
|--------------|-----------|---------|------------|
| Sunburst Chart | Both | Hierarchical performance | 1 |
| Treemap | Both | Proportional topic view | 1 |
| Heatmap | Multi-Dim | Cross-dimension matrix | 2 |
| 3D Scatter (Optional) | Multi-Dim | Triple-dimension view | 3 |
| Line Chart | Both | Temporal trends | 1 or multiple overlaid |
| Bar Chart | Both | Mistake type distribution | 1 + mistake type |
| Stacked Bar | Multi-Dim | Mistake type by context | 1 + mistake type |

### Analytics Query Performance Optimization

**Challenge:** Cross-dimension queries involve multiple self-joins and can be slow

**Solutions:**

1. **Comprehensive Indexing**
```sql
CREATE INDEX idx_tags_entry ON question_hierarchy_tags(entry_id);
CREATE INDEX idx_tags_hierarchy ON question_hierarchy_tags(hierarchy_id);
CREATE INDEX idx_tags_dimension ON question_hierarchy_tags(dimension_id);
CREATE INDEX idx_tags_entry_dimension ON question_hierarchy_tags(entry_id, dimension_id);
CREATE INDEX idx_entries_exam_correct ON entries(exam_id, correct);
CREATE INDEX idx_entries_exam_date ON entries(exam_id, date_created);
```

2. **Query Result Caching**
```python
# Cache dimension-specific aggregations
cache_key = f"dimension_performance_{exam_id}_{dimension_id}"
cached = cache.get(cache_key)

if cached and not cache_expired(cached):
    return cached

result = execute_dimension_query(exam_id, dimension_id)
cache.set(cache_key, result, expiry=3600)  # 1 hour
return result
```

3. **Pagination for Large Result Sets**
```python
# Limit initial heatmap to top N×M cells
# Load additional cells on user scroll/request
def get_heatmap_data(dim_a, dim_b, offset=0, limit=100):
    query = """
        SELECT ... 
        ORDER BY accuracy ASC
        LIMIT ? OFFSET ?
    """
    return execute(query, (limit, offset))
```

4. **Pre-computation (Phase 8)**
```python
# Nightly job: Pre-calculate common analytics
def precompute_analytics(exam_id):
    for dimension in get_exam_dimensions(exam_id):
        performance = calculate_dimension_performance(dimension)
        store_precomputed(exam_id, dimension.id, performance)
    
    for dim_a, dim_b in get_dimension_pairs(exam_id):
        heatmap = calculate_cross_dimension(dim_a, dim_b)
        store_precomputed(exam_id, (dim_a, dim_b), heatmap)
```

5. **Materialized Views (SQLite 3.35+)**
```sql
-- Not native in SQLite, but can simulate with triggers
CREATE TABLE dimension_performance_cache (
    exam_id INTEGER,
    dimension_id INTEGER,
    hierarchy_id INTEGER,
    accuracy REAL,
    total_questions INTEGER,
    last_updated TIMESTAMP,
    PRIMARY KEY (exam_id, dimension_id, hierarchy_id)
);

-- Trigger to invalidate cache on new entry
CREATE TRIGGER invalidate_cache_on_insert
AFTER INSERT ON entries
BEGIN
    DELETE FROM dimension_performance_cache WHERE exam_id = NEW.exam_id;
END;
```

---

## Template System

### Purpose

Provide pre-built exam structures for common standardized tests, eliminating manual setup and ensuring consistency.

### Template File Format (JSON)

**Structure:**
```json
{
  "template_id": "nbme_shelf_internal_med_v1",
  "template_name": "NBME Shelf Exam - Internal Medicine",
  "template_version": "1.0",
  "template_type": "multi_dimensional",
  "description": "Standard NBME shelf exam structure for Internal Medicine",
  "author": "WIMI Team",
  "last_updated": "2026-01-12",
  
  "dimensions": [
    {
      "name": "Site of Care",
      "description": "Patient care setting where the encounter occurs",
      "is_required": true,
      "allow_multiple": false,
      "display_order": 1
    },
    {
      "name": "Physician Task",
      "description": "Clinical reasoning or task type",
      "is_required": true,
      "allow_multiple": false,
      "display_order": 2
    },
    {
      "name": "System",
      "description": "Organ system or disease category",
      "is_required": true,
      "allow_multiple": false,
      "display_order": 3
    }
  ],
  
  "hierarchies": {
    "Site of Care": [
      {
        "name": "Ambulatory",
        "weight_min": 40,
        "weight_max": 50,
        "description": "Office or clinic visit"
      },
      {
        "name": "Emergency Department",
        "weight_min": 20,
        "weight_max": 30,
        "description": "Emergency room setting"
      },
      {
        "name": "Inpatient",
        "weight_min": 20,
        "weight_max": 30,
        "description": "Hospital admission",
        "children": [
          {
            "name": "ICU",
            "weight_min": 5,
            "weight_max": 10,
            "description": "Intensive care unit"
          },
          {
            "name": "Floor",
            "weight_min": 15,
            "weight_max": 20,
            "description": "General hospital floor"
          }
        ]
      },
      {
        "name": "Surgical/Perioperative",
        "weight_min": 5,
        "weight_max": 10,
        "description": "Surgical or perioperative setting"
      }
    ],
    
    "Physician Task": [
      {
        "name": "Diagnosis",
        "weight_min": 30,
        "weight_max": 40,
        "description": "Determining the diagnosis"
      },
      {
        "name": "Mechanism of Disease",
        "weight_min": 8,
        "weight_max": 12,
        "description": "Understanding pathophysiology"
      },
      {
        "name": "Management",
        "weight_min": 35,
        "weight_max": 45,
        "description": "Treatment and management decisions"
      },
      {
        "name": "Health Maintenance & Disease Prevention",
        "weight_min": 10,
        "weight_max": 15,
        "description": "Screening and prevention"
      },
      {
        "name": "Principles of Therapeutics",
        "weight_min": 5,
        "weight_max": 8,
        "description": "Pharmacology and drug mechanisms"
      },
      {
        "name": "Surveillance & Monitoring",
        "weight_min": 8,
        "weight_max": 12,
        "description": "Follow-up and monitoring"
      }
    ],
    
    "System": "user_defined"
  }
}
```

**Special Values:**
- `"user_defined"`: User must add hierarchy items for this dimension
- Used when hierarchy varies by specialty (e.g., Internal Med vs Surgery systems differ)

### Built-In Templates

#### Template 1: NBME Shelf Exam
- **Type:** Multi-dimensional
- **Dimensions:** Site of Care, Physician Task, System
- **Hierarchies:** Site and Task pre-populated, System user-defined
- **Variants:** Internal Medicine, Surgery, Pediatrics, etc.

#### Template 2: USMLE Step 2 CK
- **Type:** Multi-dimensional
- **Dimensions:** Organ System, Patient Age, Clinical Encounter, Task
- **Hierarchies:** All pre-populated with NBME blueprint weights

#### Template 3: USMLE Step 1
- **Type:** Multi-dimensional
- **Dimensions:** Organ System, General Principles, Task
- **Hierarchies:** Pre-populated with Step 1 content outline

#### Template 4: SAT Math
- **Type:** Simple
- **Hierarchy:** Heart of Algebra, Problem Solving & Data Analysis, Passport to Advanced Math, Additional Topics

#### Template 5: GRE Verbal
- **Type:** Simple
- **Hierarchy:** Reading Comprehension, Text Completion, Sentence Equivalence

#### Template 6: MCAT
- **Type:** Multi-dimensional (Optional: can also be simple)
- **Dimensions:** Foundational Concept, Content Category, Skill
- **Hierarchies:** AAMC MCAT content outline

### Template Storage Locations

**Built-in Templates:**
- Location: `/templates/exam_templates/builtin/`
- Read-only for users
- Updated with WIMI releases
- JSON files

**User Templates:**
- Location: User data directory (e.g., `~/WIMI/templates/`)
- Writable by user
- Created by "Save as Template" feature
- JSON files

### Template Application Workflow

**Flow 1: Select Template During Exam Creation**

```
Create New Exam
    ↓
[Choose from Template] or [Create Custom]
    ↓
Template Library
    ↓
Select Template
    ↓
Preview Template Structure
    ↓
Confirm & Customize
    ↓
Exam Created with Template Structure
```

**UI Mockup:**

```
Choose Exam Template

┌─ Simple Exam Templates ─────────────────┐
│                                          │
│ SAT Math                       [Select]  │
│ ├─ Heart of Algebra                     │
│ ├─ Problem Solving                      │
│ └─ ...                                  │
│                                          │
│ GRE Verbal                     [Select]  │
│ LSAT Logic Games               [Select]  │
│ Custom Simple Exam             [Select]  │
│                                          │
└──────────────────────────────────────────┘

┌─ Multi-Dimensional Templates ───────────┐
│                                          │
│ NBME Shelf - Internal Med      [Select]  │
│ Dimensions: Site, Task, System (15)     │
│                                          │
│ USMLE Step 2 CK                [Select]  │
│ Dimensions: System, Encounter, Task     │
│                                          │
│ USMLE Step 1                   [Select]  │
│ MCAT                           [Select]  │
│ Custom Multi-Dimensional       [Select]  │
│                                          │
└──────────────────────────────────────────┘

[Back] [Next]
```

**Flow 2: Preview Before Import**

```
Template Preview: NBME Shelf - Internal Med

Type: Multi-Dimensional

Dimensions (3):
├─ Site of Care (4 items, required)
├─ Physician Task (6 items, required)
└─ System (User-defined, required)

Pre-populated Hierarchies:

Site of Care:
├─ Ambulatory (40-50%)
├─ Emergency Department (20-30%)
├─ Inpatient (20-30%)
│  ├─ ICU (5-10%)
│  └─ Floor (15-20%)
└─ Surgical/Perioperative (5-10%)

Physician Task:
├─ Diagnosis (30-40%)
├─ Mechanism of Disease (8-12%)
├─ Management (35-45%)
├─ Health Maintenance (10-15%)
├─ Therapeutics (5-8%)
└─ Surveillance (8-12%)

System: You will define this for your specialty

[Cancel] [Import and Customize]
```

**Flow 3: Customize After Import**

```
Customize Exam Structure

You imported: NBME Shelf - Internal Med

Modify Dimensions: [Edit]
Modify Hierarchies: [Edit]

Add System Hierarchy:
┌─────────────────────────────────────────┐
│ System (Dimension 3)                    │
│                                          │
│ [+ Add System]                          │
│                                          │
│ Cardiovascular                  [Edit]   │
│ ├─ Arrhythmias                          │
│ ├─ Heart Failure                        │
│ └─ ...                                  │
│                                          │
│ Pulmonary                       [Edit]   │
│ Gastrointestinal                [Edit]   │
│ ...                                     │
└─────────────────────────────────────────┘

[Finish Setup]
```

### Saving Custom Templates

**User Workflow:**

```
Exam Settings: My Custom Shelf Exam

[Save as Template]
    ↓
Template Name: [My IM Shelf Template]
Description: [Custom structure for my IM rotation]
Share: ☐ Make public (future feature)

[Save]
```

**Result:**
- Template saved to user templates directory
- Available in template library for future exams
- Can be edited or deleted in template manager

### Template Versioning

**Version Format:** `major.minor` (e.g., 1.0, 1.1, 2.0)

**Update Policy:**
- Minor version (1.0 → 1.1): Small changes, backward compatible
- Major version (1.0 → 2.0): Significant changes, may not be backward compatible

**User Notification:**
```
Template Update Available

NBME Shelf Exam template has been updated:
v1.0 → v1.1

Changes:
• Updated weight ranges based on 2026 NBME blueprint
• Added "Telemedicine" to Site of Care

Your exam was created with v1.0. Update now?

[Keep Current] [View Changes] [Update]
```

**Updating Exam Structure:**
- User decides whether to apply template updates
- Can view diff before applying
- Non-destructive: Existing questions not affected
- New hierarchy nodes added, weights adjusted

### Template Import/Export (Phase 7.5)

**Export Custom Exam as Template:**
```python
def export_exam_as_template(exam_id, template_name, description):
    """
    Export exam structure to JSON template file.
    Excludes: question data, user-specific info
    Includes: dimensions, hierarchies, weights
    """
    exam = get_exam(exam_id)
    dimensions = get_exam_dimensions(exam_id)
    hierarchies = get_exam_hierarchies(exam_id)
    
    template = {
        'template_name': template_name,
        'template_type': 'multi_dimensional' if dimensions else 'simple',
        'description': description,
        'dimensions': [serialize_dimension(d) for d in dimensions],
        'hierarchies': {
            d.name: serialize_hierarchy(d.id) for d in dimensions
        }
    }
    
    save_template(template)
```

**Import Template from File:**
- User uploads JSON template file
- System validates format
- Preview before import
- Apply to new or existing exam

---

## Migration Strategy

### Backward Compatibility Requirements

1. **Existing exams continue working** with no changes
2. **Legacy data preserved** during migration
3. **Users opt-in** to new system (not forced)
4. **Rollback capability** if issues arise

### Migration Phases

#### Phase 7.1: Foundation & Schema (Weeks 1-3)

**Goal:** Build database architecture without breaking existing functionality

**Tasks:**

1. **Create New Tables**
   - `exam_dimensions`
   - `question_hierarchy_tags`
   - Write SQL migrations
   - Test schema on dev database

2. **Modify Existing Tables**
   - Add `dimension_id` column to `exam_hierarchy` (nullable)
   - Create indexes for performance
   - Test backward compatibility

3. **Database Methods Layer**
   - CRUD methods for `exam_dimensions`
   - CRUD methods for `question_hierarchy_tags`
   - Detection method: `exam_uses_dimensions(exam_id)`
   - Migration method: `convert_legacy_to_dimensions(exam_id)`

4. **Unit Tests**
   - Test dimension creation, retrieval, update, delete
   - Test tag creation with validation (one per dimension)
   - Test foreign key constraints
   - Test exam type detection
   - Test legacy exam queries still work

5. **Documentation**
   - Database schema documentation
   - API documentation for new methods
   - Migration guide for developers

**Deliverables:**
- ✅ Database schema updated
- ✅ All unit tests passing
- ✅ Documentation complete
- ✅ No breaking changes to existing functionality

**Backward Compatibility Check:**
- Run full test suite on legacy exams
- Verify all existing analytics queries work
- Confirm no data loss or corruption

---

#### Phase 7.2: Exam Setup UI (Weeks 4-6)

**Goal:** Allow users to create dimension-based exams

**Tasks:**

1. **Exam Type Selection**
   - UI for choosing simple vs multi-dimensional
   - "Learn More" modals explaining differences
   - Save exam type to database

2. **Dimension Definition UI**
   - Form to add/edit/delete dimensions
   - Drag-and-drop reordering
   - Validation (unique names, required fields)
   - Display order management

3. **Per-Dimension Hierarchy Builder**
   - Tab or dropdown to switch dimensions
   - Reuse existing hierarchy builder component
   - Modify to link nodes to dimension_id
   - Weight range input per dimension

4. **Template System Foundation**
   - Template JSON parser
   - Template library UI (grid or list view)
   - Template preview modal
   - Template application logic
   - Create 2-3 initial templates (NBME Shelf, SAT, GRE)

5. **Exam Review Screen**
   - Summary of dimensions and hierarchies
   - Edit capability before finalizing
   - Create exam button

6. **Bridge Layer Integration**
   - Expose dimension CRUD methods to frontend
   - Expose hierarchy creation with dimension linking
   - Template loading and application methods

**Deliverables:**
- ✅ Dimension-based exams can be created
- ✅ Templates available and functional
- ✅ Simple exams still created via existing flow
- ✅ UI/UX tested and polished

**Testing:**
- Create exam with 3 dimensions
- Build hierarchies in each dimension
- Import from template and customize
- Edit dimensions after creation
- Verify database records correct

---

#### Phase 7.3: Question Entry UI (Weeks 7-8)

**Goal:** Multi-dimension tagging during question entry

**Tasks:**

1. **Exam Type Detection in Entry Form**
   - Check if exam uses dimensions
   - Load appropriate UI component

2. **Multi-Dimension Selector Component**
   - Render selector for each dimension
   - Collapsible sections for space efficiency
   - Radio buttons for single selection
   - Hierarchy tree display (reuse existing component)
   - Visual indication of required dimensions

3. **Validation Logic**
   - Check all required dimensions tagged
   - Prevent saving if incomplete
   - Show error messages for missing tags

4. **Tag Storage**
   - Create `question_hierarchy_tags` records
   - Associate with correct dimension_id
   - Handle parent + child tagging in same dimension

5. **Edit Question Tags**
   - Load current tags into selector
   - Allow changing tags
   - Update database (delete old, insert new)

6. **Entry List View Updates**
   - Display tags for multi-dimensional entries
   - Filter by dimension (UI update)
   - Show tag pills or badges

**Deliverables:**
- ✅ Can tag questions across multiple dimensions
- ✅ Validation prevents incomplete tagging
- ✅ Can edit tags on existing questions
- ✅ Entry list reflects multi-dimension structure

**Testing:**
- Create question with tags in all dimensions
- Validation prevents missing required dimensions
- Edit tags on existing question
- Verify database records correct
- Test with both simple and multi-dimensional exams

---

#### Phase 7.4: Basic Analytics Integration (Weeks 9-10)

**Goal:** Single-dimension analytics working for multi-dimensional exams

**Tasks:**

1. **Exam Type Detection in Analytics**
   - Detect if exam uses dimensions
   - Load appropriate dashboard layout

2. **Dimension Selector UI**
   - Dropdown to choose dimension
   - Analytics update on selection change

3. **Single-Dimension Performance Queries**
   - Query `question_hierarchy_tags` filtered by dimension
   - Aggregate performance by hierarchy nodes
   - Weight calculations within dimension

4. **Visualization Updates**
   - Sunburst chart: Filter by dimension
   - Treemap: Filter by dimension
   - Performance tables: Filter by dimension

5. **Goal Tracking Per Dimension**
   - Allow setting goals within specific dimension
   - Track progress per dimension
   - Display dimension context in goal view

6. **Bridge Layer Methods**
   - `get_dimension_performance(exam_id, dimension_id)`
   - `get_dimension_hierarchy_performance(dimension_id, hierarchy_id)`
   - `get_dimension_goals(dimension_id)`

**Deliverables:**
- ✅ Can view performance by any dimension
- ✅ Sunburst/treemap work with dimension filter
- ✅ Goals can be set per dimension
- ✅ Legacy analytics still work for simple exams

**Testing:**
- View performance by each dimension
- Switch between dimensions in dashboard
- Verify accuracy calculations correct
- Compare to manual calculations
- Test goal tracking per dimension

---

#### Phase 7.5: Cross-Dimension Analytics (Weeks 11-13)

**Goal:** Unlock multi-dimensional insights and visualizations

**Tasks:**

1. **Cross-Dimension Query Methods**
   - Two-dimension intersection queries
   - Three-dimension intersection queries
   - Performance aggregation at intersections
   - Filtering for sufficient data (N >= 3)

2. **Heatmap Visualization Component**
   - D3.js heatmap (rows = dimension A, cols = dimension B)
   - Color gradient (red → yellow → green)
   - Cell annotations (accuracy, count)
   - Interactive: Click cell → question list

3. **Dimension A × B Selector UI**
   - Dropdowns to choose two dimensions
   - Heatmap updates on selection change
   - Export heatmap to CSV or image

4. **Intersection Drill-Down**
   - Click heatmap cell → modal with question list
   - Filter questions by both dimension values
   - Show detailed stats for intersection

5. **Bridge Layer Methods**
   - `get_cross_dimension_performance(exam_id, dim_a_id, dim_b_id)`
   - `get_intersection_questions(dim_a_val, dim_b_val)`
   - `export_heatmap(exam_id, dim_a_id, dim_b_id, format='csv')`

**Deliverables:**
- ✅ Can generate heatmaps for any dimension pair
- ✅ Heatmap interactive and accurate
- ✅ Can drill down to questions at intersections
- ✅ Export functionality working

**Testing:**
- Generate Site × Task heatmap
- Verify accuracy calculations for each cell
- Click cell and verify question list correct
- Export heatmap to CSV and validate
- Test with different dimension pairs

---

#### Phase 7.6: Advanced Analytics (Weeks 14-16)

**Goal:** Pattern detection, interaction effects, contextual recommendations

**Tasks:**

1. **Triple-Dimension Query Methods**
   - Three-way intersection queries
   - Performance aggregation
   - Ranking by accuracy, time, etc.

2. **Interaction Effect Detection**
   - Algorithm to detect interaction effects
   - Calculate expected vs actual performance
   - Identify significant deviations (threshold: 10%)

3. **Contextual Insights UI**
   - Display interaction effects prominently
   - Show expected vs actual performance
   - Generate natural language insights

4. **Mistake Type by Context**
   - Query mistake distribution by dimension
   - Stacked bar chart visualization
   - Compare mistake patterns across contexts

5. **Weighted Study Recommendations**
   - Algorithm: Priority = weight × gap × context_penalty
   - Ranked list of study targets
   - One-click goal creation from recommendation

6. **Temporal Trends by Dimension**
   - Time-series queries filtered by dimension
   - Line chart with multiple dimension values overlaid
   - Trend analysis (improving, stable, declining)

7. **Bridge Layer Methods**
   - `get_triple_dimension_performance(...)`
   - `detect_interaction_effects(exam_id, dim_a_id, dim_b_id)`
   - `get_study_recommendations(exam_id, limit=10)`
   - `get_mistake_distribution_by_dimension(...)`
   - `get_temporal_trends(dimension_id, hierarchy_id)`

**Deliverables:**
- ✅ Triple-dimension analysis working
- ✅ Interaction effects detected and displayed
- ✅ Study recommendations generated and actionable
- ✅ Mistake type by context visualization
- ✅ Temporal trend comparison

**Testing:**
- Generate weakest 3-way combinations
- Verify interaction effect calculations
- Review study recommendations for accuracy
- Check mistake distribution charts
- Validate temporal trend data

---

#### Phase 7.7: Polish & Optimization (Weeks 17-18)

**Goal:** Performance tuning, UX refinement, comprehensive documentation

**Tasks:**

1. **Query Optimization**
   - Review slow queries (profiling)
   - Add missing indexes
   - Implement caching for common queries
   - Pagination for large result sets

2. **UI/UX Improvements**
   - User testing feedback integration
   - Tooltip refinements
   - Loading indicators for slow queries
   - Error handling improvements
   - Responsive design for mobile/tablet

3. **Comprehensive Testing**
   - Integration tests for full workflows
   - Edge case testing (e.g., single question, missing tags)
   - Performance testing with large datasets
   - Cross-platform testing (Windows, Mac, Linux)

4. **Documentation**
   - User guide: Multi-dimensional exams
   - Video tutorials (2-4 min each)
   - Developer documentation updates
   - API reference for new methods
   - Migration guide for existing users

5. **Template Library Expansion**
   - Add more templates (MCAT, LSAT, custom examples)
   - Template versioning system
   - Template update notification system

6. **Conversion Tool: Simple → Multi-Dimensional**
   - Wizard UI for converting existing exams
   - Migration of existing questions
   - Bulk tag editor for retrofitting tags

**Deliverables:**
- ✅ Application performs well with large datasets
- ✅ UX polished and user-friendly
- ✅ Comprehensive documentation complete
- ✅ Template library robust
- ✅ Conversion tool functional

**Testing:**
- Stress test with 1000+ questions
- User acceptance testing
- Documentation review
- Template import/export validation
- Conversion tool with real exam data

---

### Migration of Legacy Data

**When User Converts Simple Exam to Multi-Dimensional:**

**Step 1: Preserve Existing Hierarchy**
```sql
-- Existing hierarchy becomes first dimension
INSERT INTO exam_dimensions (exam_id, name, display_order, is_required)
VALUES (?, 'Topic', 1, 1);

-- Get new dimension_id
SET @dimension_id = last_insert_rowid();

-- Update all hierarchy nodes
UPDATE exam_hierarchy
SET dimension_id = @dimension_id
WHERE exam_id = ? AND dimension_id IS NULL;
```

**Step 2: Tag Existing Questions**
```sql
-- Migrate entry_hierarchy_links to question_hierarchy_tags
INSERT INTO question_hierarchy_tags (entry_id, hierarchy_id, dimension_id)
SELECT 
    ehl.entry_id,
    ehl.hierarchy_id,
    @dimension_id
FROM entry_hierarchy_links ehl
JOIN entries e ON ehl.entry_id = e.id
WHERE e.exam_id = ?;
```

**Step 3: User Adds Additional Dimensions (Optional)**
- User defines new dimensions in UI
- System prompts to tag existing questions
- Options:
  - Tag now (bulk editor)
  - Tag gradually during review
  - Leave untagged (can filter later)

**Rollback:**
- Not supported (conversion is one-way)
- Warning shown to user before conversion
- Backup recommended before conversion

---

## Risk Assessment

### High Risk

#### 1. Migration Complexity
**Risk:** Converting legacy exams may lose data or break analytics  
**Impact:** User data loss, system instability  
**Probability:** Medium  

**Mitigation:**
- Extensive unit and integration testing
- User data backup before migration
- Read-only mode during migration
- Conversion preview before applying
- User choice to keep legacy format

#### 2. Performance Degradation
**Risk:** Cross-dimension queries may be slow at scale  
**Impact:** Poor user experience, unusable analytics  
**Probability:** Medium  

**Mitigation:**
- Comprehensive indexing strategy
- Query result caching (1-hour expiry)
- Pagination for large result sets
- Query optimization (profiling and tuning)
- Pre-computation for common queries (Phase 8)

#### 3. User Confusion
**Risk:** Multi-dimension concept may not be intuitive  
**Impact:** Low adoption, user frustration  
**Probability:** Medium  

**Mitigation:**
- Strong onboarding with examples
- Template-driven setup (reduces manual config)
- Clear documentation and video tutorials
- Optional system (users not forced)
- In-app help and tooltips

### Medium Risk

#### 1. Template Maintenance
**Risk:** Exam formats change, templates become outdated  
**Impact:** Inaccurate weights, user confusion  
**Probability:** Medium  

**Mitigation:**
- Version templates with update notifications
- Community contribution system (Phase 8)
- Regular review cycle (annually)
- Template diff viewer before applying updates
- User feedback mechanism for template issues

#### 2. UI Clutter
**Risk:** Multi-dimension selectors may overwhelm interface  
**Impact:** Cognitive overload, slower question entry  
**Probability:** Low-Medium  

**Mitigation:**
- Progressive disclosure (collapsible sections)
- User testing and iterative refinement
- Alternative UI patterns (tabs, dropdowns, modals)
- "Remember last selected" feature for speed
- Keyboard shortcuts for power users

#### 3. Edge Case Bugs
**Risk:** Complex tagging logic may have unforeseen issues  
**Impact:** Incorrect analytics, data corruption  
**Probability:** Medium  

**Mitigation:**
- Comprehensive unit tests (>80% coverage)
- Integration tests for full workflows
- Beta testing period with real users
- Logging and error reporting
- Graceful error handling with rollback

### Low Risk

#### 1. Backward Compatibility
**Risk:** Old exams may not work with new system  
**Impact:** User unable to access legacy data  
**Probability:** Low  

**Mitigation:**
- Parallel support for legacy and dimension systems
- Detection logic throughout application
- Clear migration path with user control
- Extensive testing on legacy data

#### 2. Over-Engineering
**Risk:** Users may not need this complexity  
**Impact:** Wasted development effort, unused features  
**Probability:** Low  

**Mitigation:**
- Make dimensions optional (not mandatory)
- Simple exams remain simple
- Feature gating (advanced features only for multi-dim)
- User feedback early and often
- Phased rollout (can stop if not adopted)

---

## Success Metrics

### User Adoption Metrics

**Target: 40% of new exams use dimensions within 6 months**

- % of new exams using dimensions vs simple hierarchy
- Average number of dimensions per exam
- Template usage rate (vs custom creation)
- Conversion rate from simple → multi-dimensional

**Measurement:**
```sql
-- Track exam type distribution
SELECT 
    CASE WHEN EXISTS (SELECT 1 FROM exam_dimensions WHERE exam_id = e.id)
         THEN 'Multi-Dimensional'
         ELSE 'Simple'
    END as exam_type,
    COUNT(*) as count,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM exams), 1) as percentage
FROM exams e
WHERE e.created_at >= date('now', '-6 months')
GROUP BY exam_type;
```

### Analytics Engagement Metrics

**Target: 60% of multi-dim exam users view cross-dimension analytics**

- % of users viewing cross-dimension analytics
- Most common dimension combinations analyzed
- Heatmap interaction rate (clicks, drilldowns)
- Study recommendation follow-through rate
- Average time spent in analytics dashboard

**Measurement:**
```python
# Log analytics events
log_event('analytics_view', {
    'exam_type': 'multi_dimensional',
    'view_type': 'heatmap',
    'dimensions': ['Site of Care', 'Physician Task'],
    'timestamp': now()
})

# Aggregate engagement
engagement = count_events('analytics_view', exam_type='multi_dimensional') / total_multi_dim_users
```

### Learning Outcome Metrics (Hypothesis)

**Hypothesis: Users with cross-dimension insights improve faster**

- Accuracy improvement rate: Multi-dim users vs simple users
- Time to 80% accuracy: Multi-dim vs simple
- Retention: Do multi-dim users stick with WIMI longer?
- Recommendation effectiveness: Accuracy gain in recommended areas

**Measurement:**
```sql
-- Compare improvement rates
SELECT 
    exam_type,
    AVG(accuracy_week_10 - accuracy_week_1) as improvement
FROM (
    -- Calculate accuracy in week 1 and week 10 for each user
    ...
)
GROUP BY exam_type;
```

**Note:** Confounding factors (exam difficulty, user motivation) make causation hard to prove. Use with caution.

### System Performance Metrics

**Target: 95% of queries < 500ms**

- Query execution time (p50, p95, p99)
- Cache hit rate for analytics queries
- Database size growth rate
- Number of slow queries (>1s)

**Measurement:**
```python
# Log query performance
@log_execution_time
def get_cross_dimension_performance(exam_id, dim_a, dim_b):
    start = time.time()
    result = execute_query(...)
    duration = time.time() - start
    
    log_metric('query_time', {
        'query': 'cross_dimension_performance',
        'duration_ms': duration * 1000,
        'exam_id': exam_id
    })
    
    return result
```

### User Satisfaction Metrics

**Target: 4.5/5 satisfaction rating for multi-dim exams**

- User ratings (in-app survey after 2 weeks)
- Feature request frequency (dimensions-related)
- Support ticket volume (bug reports, confusion)
- NPS score for multi-dimensional users

**Measurement:**
- In-app survey after user creates first multi-dim exam
- "How satisfied are you with multi-dimensional categorization?" (1-5)
- "Did multi-dimensional analytics help you study more effectively?" (Yes/No/Somewhat)
- Open-ended feedback

---

## Open Questions

### Question 1: Dimension Nesting

**Should dimensions themselves be nestable?**

Example: "Clinical Context" dimension with children "Site of Care" and "Patient Population"

**Pros:**
- More organizational flexibility
- Captures hierarchical relationships between categorizations

**Cons:**
- Significant complexity increase
- UI becomes much more complex
- Analytics queries more complex

**Recommendation:** Start with flat dimensions (Phase 7), evaluate need in Phase 8 based on user feedback

---

### Question 2: Tag History & Audit

**Should we track tag changes over time?**

Example: User initially tags as "Ambulatory", later changes to "Emergency"

**Pros:**
- Audit trail for troubleshooting
- Undo capability
- Analytics on categorization accuracy

**Cons:**
- Storage overhead
- UI complexity for viewing history
- Potential privacy concerns

**Recommendation:** Simple version history (previous value, timestamp, reason) for tag changes. Full audit trail if needed in Phase 8.

**Implementation:**
```sql
CREATE TABLE question_tag_history (
    id INTEGER PRIMARY KEY,
    entry_id INTEGER,
    hierarchy_id_old INTEGER,
    hierarchy_id_new INTEGER,
    dimension_id INTEGER,
    changed_at TIMESTAMP,
    reason TEXT,
    FOREIGN KEY (entry_id) REFERENCES entries(id)
);
```

---

### Question 3: Dimension Weights

**Should dimensions themselves have weights?**

Example: System = 70% importance, Site = 20%, Task = 10%

**Use case:** Overall priority score across dimensions

**Pros:**
- More sophisticated study recommendations
- Reflects exam blueprint more accurately
- Can prioritize certain dimensions over others

**Cons:**
- Adds another layer of complexity
- Users must understand dimension weights vs node weights
- May confuse users

**Recommendation:** Phase 8 consideration. Phase 7 treats dimensions as equally important, weights apply within each dimension.

---

### Question 4: Allow Multiple Tags Per Dimension

**Current plan:** One tag per dimension (unless `allow_multiple=true`)

**Use case:** Question involves both Cardiovascular and Pulmonary

**Pros:**
- More accurate representation
- Captures cross-system questions

**Cons:**
- Complicates analytics (which system to credit?)
- UI complexity (checkboxes vs radio buttons)
- Weight distribution unclear

**Recommendation:** Default to single-tag. Add multi-tag as advanced feature in Phase 7.5. When multi-tag enabled, analytics split credit equally across tags.

---

### Question 5: Auto-Tagging Suggestions

**Should WIMI suggest tags based on question text?**

Example: Detect "emergency department" in question → suggest Emergency tag

**Pros:**
- Faster entry
- Consistency across questions
- Reduces tagging errors

**Cons:**
- May be inaccurate (NLP challenges)
- Requires significant development
- Users may blindly accept incorrect suggestions

**Recommendation:** Phase 8+ feature. Focus on manual tagging in Phase 7. If implemented, use simple keyword matching first, ML-based NLP later.

---

### Question 6: Shared Dimensions Across Exams

**Should users be able to share dimensions across multiple exams?**

Example: User studying for multiple shelf exams, all use same "Site of Care" dimension

**Pros:**
- Consistency across exams
- Cross-exam analytics (e.g., "My Emergency performance across all exams")
- Reduced setup time

**Cons:**
- Database complexity (dimension not linked to single exam)
- Dimension changes affect multiple exams
- Harder to maintain exam isolation

**Recommendation:** Phase 8 consideration. Phase 7 keeps dimensions exam-specific for simplicity.

---

## Timeline Estimate

### Phase Breakdown

| Phase | Tasks | Duration | Dependencies |
|-------|-------|----------|--------------|
| 7.1 | Foundation & Schema | 2-3 weeks | None |
| 7.2 | Exam Setup UI | 2-3 weeks | 7.1 complete |
| 7.3 | Question Entry UI | 2 weeks | 7.2 complete |
| 7.4 | Basic Analytics | 2 weeks | 7.3 complete |
| 7.5 | Cross-Dimension Analytics | 2-3 weeks | 7.4 complete |
| 7.6 | Advanced Analytics | 2-3 weeks | 7.5 complete |
| 7.7 | Polish & Optimization | 1-2 weeks | 7.6 complete |

**Total Estimated Time:** 13-18 weeks (3-4.5 months)

### Adjustment Factors

**May extend timeline:**
- UI design complexity (mockups, iterations)
- User testing feedback requiring changes
- Scope creep (additional features requested)
- Bug fixing and edge case handling
- Performance optimization challenges

**May shorten timeline:**
- Reusing existing UI components
- Leveraging existing analytics code
- Skipping optional features (e.g., triple-dimension)
- Parallel development (frontend + backend)

### Milestone Deliverables

**Month 1 (Weeks 1-4):**
- ✅ Database schema complete
- ✅ Can create multi-dimensional exams
- ✅ Templates functional

**Month 2 (Weeks 5-8):**
- ✅ Can tag questions across dimensions
- ✅ Single-dimension analytics working

**Month 3 (Weeks 9-13):**
- ✅ Cross-dimension heatmaps functional
- ✅ Advanced pattern detection working

**Month 4 (Weeks 14-18, if needed):**
- ✅ Performance optimized
- ✅ Documentation complete
- ✅ Production-ready

---

## Next Steps

### Immediate Actions

1. **Review & Feedback**
   - You review this planning document
   - Identify gaps, concerns, or missing features
   - Prioritize must-have vs nice-to-have features

2. **UI Design Phase**
   - Create wireframes for key UI components:
     - Exam type selection
     - Dimension definition form
     - Multi-dimension selector (question entry)
     - Cross-dimension heatmap
   - Review and iterate on designs

3. **Finalize Scope**
   - Decide which phases are MVP (must deliver)
   - Identify features to defer to Phase 8
   - Lock down requirements before starting

4. **Environment Setup**
   - Create feature branch: `feature/phase-7-multi-dimensional`
   - Set up testing database with sample multi-dimensional data
   - Prepare test cases and acceptance criteria

### Implementation Start (Phase 7.1)

**When ready to begin:**

1. Create database migration script
2. Write unit tests for new database methods
3. Implement CRUD methods for dimensions and tags
4. Test backward compatibility with legacy exams
5. Document all new database methods

**First PR:** Foundation & Schema (Phase 7.1)

---

## Conclusion

This planning document outlines a comprehensive approach to adding optional multi-dimensional hierarchy support to WIMI. The design:

- ✅ **Maintains simplicity** for users with straightforward exams
- ✅ **Unlocks advanced analytics** for users with complex, multi-dimensional exams
- ✅ **Provides smooth migration path** from simple to multi-dimensional
- ✅ **Supports template-based creation** for common standardized tests
- ✅ **Enables cross-dimensional insights** impossible with single-path hierarchies

The optional nature of dimensions ensures WIMI remains accessible to all users while providing powerful tools for those who need them. The phased approach allows for incremental delivery, testing, and user feedback throughout development.

**Key Decision:** Multi-dimensional categorization is **optional**, not mandatory. This preserves WIMI's core value proposition (mistake analysis for any exam) while extending capabilities for advanced users.

---

**Document Status:** Planning Complete, Awaiting Approval  
**Next Review:** After initial feedback  
**Implementation Start:** TBD based on priority

---

**Appendices:**

- **Appendix A:** Database Schema Diagrams (to be added)
- **Appendix B:** UI Wireframes (to be added)
- **Appendix C:** Template JSON Examples (included above)
- **Appendix D:** Query Performance Benchmarks (to be measured)
- **Appendix E:** User Testing Plan (to be developed)

---

**Change Log:**

| Date | Version | Changes | Author |
|------|---------|---------|--------|
| 2026-01-12 | 1.0 | Initial planning document | WIMI Team |

---

**References:**

- NBME Content Outlines: [nbme.org](https://www.nbme.org)
- USMLE Content Outline: [usmle.org](https://www.usmle.org)
- AAMC MCAT Content: [aamc.org/mcat](https://www.aamc.org/mcat)
- Project WIMI Documentation: `/docs/`

---

End of Document
