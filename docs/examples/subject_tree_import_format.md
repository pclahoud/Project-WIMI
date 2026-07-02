# Subject Tree Import Format

This document describes the JSON format for importing subject hierarchies into WIMI.

## Overview

The import format allows you to define:
- Exam context (name, description, source information)
- Hierarchical subject structure (unlimited nesting depth)
- Weight configurations (official ranges, relative weights, user estimates)

## File Structure

```json
{
  "exam_context": { ... },
  "subjects": [ ... ]
}
```

## Exam Context

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Exam identifier (e.g., "USMLE Step 1", "SAT", "CPA REG") |
| `description` | string | No | Detailed exam description |
| `source.name` | string | No | Name of content outline source |
| `source.url` | string | No | URL to official content outline |
| `source.retrieved_date` | string | No | Date source was accessed (YYYY-MM-DD) |

## Subject Structure

Each subject can contain:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Subject name |
| `level_type` | string | Yes | Hierarchy level (e.g., "System", "Topic", "Subtopic") |
| `weight` | object | No | Weight configuration (see below) |
| `children` | array | No | Nested child subjects |

## Weight Configuration

Weights can be specified in several ways:

### 1. Absolute Weights (Range)
For subjects with official exam weight ranges:

```json
{
  "weight": {
    "low": 11,
    "high": 15,
    "source": "official",
    "locked": true
  }
}
```

### 2. Absolute Weights (Single Value)
When a subject has an exact weight percentage (not a range), you have two options:

**Option A: Using `value` shorthand (recommended)**
```json
{
  "weight": {
    "value": 50,
    "source": "official",
    "locked": true
  }
}
```

**Option B: Using `low` only (high defaults to match low)**
```json
{
  "weight": {
    "low": 50,
    "source": "official",
    "locked": true
  }
}
```

Both options result in the same storage: `exam_weight_low = 50, exam_weight_high = 50`.

### 3. Relative Weights
For child subjects, specifying percentage of parent's weight:

```json
{
  "weight": {
    "relative": 25,
    "source": "user_estimate",
    "locked": false
  }
}
```

### Weight Source Values

| Value | Description |
|-------|-------------|
| `official` | From authoritative exam content outline |
| `derived` | Calculated from official data |
| `user_estimate` | User's personal estimate |
| `user_defined` | User-defined without reference |

### Weight Locking

- `locked: true` - Prevents accidental modification (use for official weights)
- `locked: false` - Allows editing in the application

---

## Examples

### Example 1: USMLE Step 1 (Medical Licensing)

```json
{
  "exam_context": {
    "name": "USMLE Step 1",
    "description": "United States Medical Licensing Examination Step 1",
    "source": {
      "name": "NBME Content Outline 2024",
      "url": "https://www.usmle.org/prepare-your-exam/step-1-materials/step-1-content-outline"
    }
  },
  "subjects": [
    {
      "name": "Gastrointestinal System",
      "level_type": "System",
      "weight": { "low": 11, "high": 15, "source": "official", "locked": true },
      "children": [
        {
          "name": "Anatomy",
          "level_type": "Category",
          "weight": { "relative": 20, "source": "user_estimate" }
        },
        {
          "name": "Physiology",
          "level_type": "Category",
          "weight": { "relative": 25, "source": "user_estimate" }
        },
        {
          "name": "Pathology",
          "level_type": "Category",
          "weight": { "relative": 35, "source": "user_estimate" }
        },
        {
          "name": "Pharmacology",
          "level_type": "Category",
          "weight": { "relative": 20, "source": "user_estimate" }
        }
      ]
    },
    {
      "name": "Cardiovascular System",
      "level_type": "System",
      "weight": { "low": 11, "high": 15, "source": "official", "locked": true }
    }
  ]
}
```

### Example 2: SAT (College Admission)

```json
{
  "exam_context": {
    "name": "SAT",
    "description": "SAT Suite of Assessments",
    "source": {
      "name": "College Board SAT Suite Technical Manual",
      "url": "https://collegereadiness.collegeboard.org/"
    }
  },
  "subjects": [
    {
      "name": "Reading and Writing",
      "level_type": "Section",
      "weight": { "value": 50, "source": "official", "locked": true },
      "children": [
        {
          "name": "Craft and Structure",
          "level_type": "Domain",
          "weight": { "relative": 28, "source": "official", "locked": true },
          "children": [
            { "name": "Words in Context", "level_type": "Skill" },
            { "name": "Text Structure and Purpose", "level_type": "Skill" },
            { "name": "Cross-Text Connections", "level_type": "Skill" }
          ]
        },
        {
          "name": "Information and Ideas",
          "level_type": "Domain",
          "weight": { "relative": 26, "source": "official", "locked": true },
          "children": [
            { "name": "Central Ideas and Details", "level_type": "Skill" },
            { "name": "Command of Evidence", "level_type": "Skill" },
            { "name": "Inferences", "level_type": "Skill" }
          ]
        },
        {
          "name": "Standard English Conventions",
          "level_type": "Domain",
          "weight": { "relative": 26, "source": "official", "locked": true },
          "children": [
            { "name": "Boundaries", "level_type": "Skill" },
            { "name": "Form, Structure, and Sense", "level_type": "Skill" }
          ]
        },
        {
          "name": "Expression of Ideas",
          "level_type": "Domain",
          "weight": { "relative": 20, "source": "official", "locked": true },
          "children": [
            { "name": "Rhetorical Synthesis", "level_type": "Skill" },
            { "name": "Transitions", "level_type": "Skill" }
          ]
        }
      ]
    },
    {
      "name": "Math",
      "level_type": "Section",
      "weight": { "value": 50, "source": "official", "locked": true },
      "children": [
        {
          "name": "Algebra",
          "level_type": "Domain",
          "weight": { "relative": 35, "source": "official", "locked": true },
          "children": [
            { "name": "Linear Equations", "level_type": "Skill" },
            { "name": "Linear Functions", "level_type": "Skill" },
            { "name": "Systems of Equations", "level_type": "Skill" },
            { "name": "Linear Inequalities", "level_type": "Skill" }
          ]
        },
        {
          "name": "Advanced Math",
          "level_type": "Domain",
          "weight": { "relative": 35, "source": "official", "locked": true },
          "children": [
            { "name": "Equivalent Expressions", "level_type": "Skill" },
            { "name": "Nonlinear Equations", "level_type": "Skill" },
            { "name": "Nonlinear Functions", "level_type": "Skill" }
          ]
        },
        {
          "name": "Problem-Solving and Data Analysis",
          "level_type": "Domain",
          "weight": { "relative": 15, "source": "official", "locked": true },
          "children": [
            { "name": "Ratios and Percentages", "level_type": "Skill" },
            { "name": "Probability and Statistics", "level_type": "Skill" },
            { "name": "Data Interpretation", "level_type": "Skill" }
          ]
        },
        {
          "name": "Geometry and Trigonometry",
          "level_type": "Domain",
          "weight": { "relative": 15, "source": "official", "locked": true },
          "children": [
            { "name": "Area and Volume", "level_type": "Skill" },
            { "name": "Lines, Angles, and Triangles", "level_type": "Skill" },
            { "name": "Circles", "level_type": "Skill" },
            { "name": "Right Triangles and Trigonometry", "level_type": "Skill" }
          ]
        }
      ]
    }
  ]
}
```

### Example 3: CPA Exam - REG Section

```json
{
  "exam_context": {
    "name": "CPA REG",
    "description": "CPA Exam - Regulation Section",
    "source": {
      "name": "AICPA CPA Exam Blueprints",
      "url": "https://www.aicpa.org/resources/download/cpa-exam-blueprints"
    }
  },
  "subjects": [
    {
      "name": "Ethics, Professional Responsibilities and Federal Tax Procedures",
      "level_type": "Area",
      "weight": { "low": 10, "high": 20, "source": "official", "locked": true },
      "children": [
        { "name": "Ethics and Responsibilities", "level_type": "Topic" },
        { "name": "Licensing and Disciplinary Systems", "level_type": "Topic" },
        { "name": "Federal Tax Procedures", "level_type": "Topic" }
      ]
    },
    {
      "name": "Business Law",
      "level_type": "Area",
      "weight": { "low": 10, "high": 20, "source": "official", "locked": true },
      "children": [
        { "name": "Contracts", "level_type": "Topic" },
        { "name": "Debtor-Creditor Relationships", "level_type": "Topic" },
        { "name": "Agency", "level_type": "Topic" },
        { "name": "Business Structure", "level_type": "Topic" }
      ]
    },
    {
      "name": "Federal Taxation of Property Transactions",
      "level_type": "Area",
      "weight": { "low": 12, "high": 22, "source": "official", "locked": true },
      "children": [
        { "name": "Basis of Assets", "level_type": "Topic" },
        { "name": "Taxable and Nontaxable Dispositions", "level_type": "Topic" },
        { "name": "Cost Recovery", "level_type": "Topic" }
      ]
    },
    {
      "name": "Federal Taxation of Individuals",
      "level_type": "Area",
      "weight": { "low": 15, "high": 25, "source": "official", "locked": true },
      "children": [
        { "name": "Gross Income", "level_type": "Topic" },
        { "name": "Adjustments and Deductions", "level_type": "Topic" },
        { "name": "Tax Credits", "level_type": "Topic" },
        { "name": "Filing Status and Dependents", "level_type": "Topic" }
      ]
    },
    {
      "name": "Federal Taxation of Entities",
      "level_type": "Area",
      "weight": { "low": 28, "high": 38, "source": "official", "locked": true },
      "children": [
        { "name": "C Corporations", "level_type": "Topic" },
        { "name": "S Corporations", "level_type": "Topic" },
        { "name": "Partnerships", "level_type": "Topic" },
        { "name": "Tax-Exempt Organizations", "level_type": "Topic" }
      ]
    }
  ]
}
```

### Example 4: GRE (Graduate Record Examination)

```json
{
  "exam_context": {
    "name": "GRE General Test",
    "description": "Graduate Record Examination General Test",
    "source": {
      "name": "ETS GRE General Test Content",
      "url": "https://www.ets.org/gre/test-takers/general-test/prepare/content.html"
    }
  },
  "subjects": [
    {
      "name": "Verbal Reasoning",
      "level_type": "Section",
      "weight": { "value": 33, "source": "official", "locked": true },
      "children": [
        {
          "name": "Reading Comprehension",
          "level_type": "Category",
          "weight": { "relative": 50, "source": "user_estimate" },
          "children": [
            { "name": "Multiple-choice (single answer)", "level_type": "Question Type" },
            { "name": "Multiple-choice (multiple answers)", "level_type": "Question Type" },
            { "name": "Select-in-Passage", "level_type": "Question Type" }
          ]
        },
        {
          "name": "Text Completion",
          "level_type": "Category",
          "weight": { "relative": 25, "source": "user_estimate" }
        },
        {
          "name": "Sentence Equivalence",
          "level_type": "Category",
          "weight": { "relative": 25, "source": "user_estimate" }
        }
      ]
    },
    {
      "name": "Quantitative Reasoning",
      "level_type": "Section",
      "weight": { "value": 33, "source": "official", "locked": true },
      "children": [
        {
          "name": "Arithmetic",
          "level_type": "Category",
          "weight": { "relative": 25, "source": "user_estimate" }
        },
        {
          "name": "Algebra",
          "level_type": "Category",
          "weight": { "relative": 25, "source": "user_estimate" }
        },
        {
          "name": "Geometry",
          "level_type": "Category",
          "weight": { "relative": 25, "source": "user_estimate" }
        },
        {
          "name": "Data Analysis",
          "level_type": "Category",
          "weight": { "relative": 25, "source": "user_estimate" }
        }
      ]
    },
    {
      "name": "Analytical Writing",
      "level_type": "Section",
      "weight": { "value": 34, "source": "official", "locked": true },
      "children": [
        {
          "name": "Analyze an Issue",
          "level_type": "Task",
          "weight": { "relative": 50, "source": "official", "locked": true }
        },
        {
          "name": "Analyze an Argument",
          "level_type": "Task",
          "weight": { "relative": 50, "source": "official", "locked": true }
        }
      ]
    }
  ]
}
```

### Example 5: Minimal Structure (No Weights)

For exams where official weights aren't available:

```json
{
  "exam_context": {
    "name": "Custom Exam"
  },
  "subjects": [
    {
      "name": "Section A",
      "level_type": "Section",
      "children": [
        { "name": "Topic 1", "level_type": "Topic" },
        { "name": "Topic 2", "level_type": "Topic" },
        { "name": "Topic 3", "level_type": "Topic" }
      ]
    },
    {
      "name": "Section B",
      "level_type": "Section",
      "children": [
        { "name": "Topic 4", "level_type": "Topic" },
        { "name": "Topic 5", "level_type": "Topic" }
      ]
    }
  ]
}
```

---

## Common Level Types

Choose appropriate level types based on your exam structure:

| Exam Type | Common Hierarchy |
|-----------|------------------|
| Medical (USMLE) | System → Category → Topic → Subtopic |
| SAT/ACT | Section → Domain → Skill |
| CPA | Area → Topic → Subtopic |
| Bar Exam | Subject → Topic → Subtopic |
| GRE/GMAT | Section → Category → Question Type |
| AP Exams | Unit → Topic → Learning Objective |

---

## Validation Rules

1. **Unique Names**: Subjects at the same level under the same parent must have unique names
2. **Weight Ranges**: `low` must be ≤ `high` for absolute weights
3. **Single Values**: Use `value` shorthand or `low` alone (high defaults to match low)
4. **Relative Weights**: Should sum to ~100% among siblings (WIMI will auto-balance)
5. **Required Fields**: `name` and `level_type` are always required

---

## Weight Format Summary

| Format | Example | Result |
|--------|---------|--------|
| Range | `{"low": 20, "high": 25}` | 20-25% range |
| Single (value) | `{"value": 50}` | Exact 50% |
| Single (low only) | `{"low": 50}` | Exact 50% (high defaults to low) |
| Legacy number | `"weight": 50` | Exact 50% (backwards compatible) |

---

## Tips for Creating Import Files

1. **Start with official content outlines** when available
2. **Use official weights** at the top level, then estimate relative weights for children
3. **Lock official weights** to prevent accidental changes
4. **Keep level types consistent** within the same hierarchy level
5. **Test with a small sample** before importing a full structure
6. **Use `value` shorthand** for cleaner single-value weights instead of `{"low": 50, "high": 50}`
