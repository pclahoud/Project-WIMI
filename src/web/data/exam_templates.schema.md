# Exam Templates JSON Schema Design

**Document Version:** 1.0
**Created:** January 24, 2026
**Purpose:** Define the data structure for `exam_templates.json` to support the WIMI Exam Setup Wizard template system.

---

## Table of Contents

1. [Overview](#overview)
2. [Design Goals](#design-goals)
3. [Schema Definition](#schema-definition)
4. [Field Reference](#field-reference)
5. [Example Templates](#example-templates)
6. [Usage in Wizard](#usage-in-wizard)
7. [Validation Rules](#validation-rules)
8. [Future Considerations](#future-considerations)

---

## Overview

The exam templates system provides pre-configured exam setups to streamline the exam creation process. Templates can suggest (but not require) exam type, dimensions, hierarchy levels, and weight settings. Users can customize any template-provided values after selection.

### Relationship to Existing Wizard Data Structures

The template schema maps directly to the `ExamWizard.data` object:

```javascript
// ExamWizard.data (from exam_wizard.js)
{
    examType: 'simple' | 'multi_dimensional',
    examName: string,
    examDescription: string,
    examDate: string,
    notes: string,
    hierarchyLevels: string[],  // ['System', 'Subsystem', 'Topic', 'Subtopic', 'Child']
    dimensions: Dimension[],     // For multi-dimensional exams
    weightSettings: {
        autonomousBalancing: boolean,
        precision: number,       // 0, 1, or 2 decimal places
        balancingAlgorithm: 'proportional' | 'even'
    }
}

// Dimension object
{
    id: number,
    name: string,
    description: string,
    isRequired: boolean,
    allowMultiple: boolean,
    displayOrder: number
}
```

---

## Design Goals

1. **Completeness**: Support all fields the wizard can configure
2. **Flexibility**: Allow templates to specify any subset of fields (partial templates)
3. **Discoverability**: Include rich metadata for searching and filtering templates
4. **Extensibility**: Support future fields without breaking existing templates
5. **Simplicity**: Keep the schema intuitive for manual editing and debugging

---

## Schema Definition

### Root Structure

```json
{
    "$schema": "exam_templates.schema.json",
    "version": "1.0.0",
    "lastUpdated": "2026-01-24",
    "templates": [Template, ...]
}
```

### Template Object

```typescript
interface Template {
    // === REQUIRED METADATA ===
    id: string;                    // Unique identifier (kebab-case)
    name: string;                  // Display name
    description: string;           // Brief description for selection UI
    category: TemplateCategory;    // Grouping category

    // === OPTIONAL METADATA ===
    tags?: string[];               // Searchable tags
    targetUsers?: string[];        // Target audience descriptions
    officialSource?: string;       // Source of official content outline
    sourceUrl?: string;            // URL to official content outline
    icon?: string;                 // Emoji or icon identifier
    popularity?: number;           // 1-5 popularity rating for sorting

    // === EXAM CONFIGURATION ===
    examType: 'simple' | 'multi_dimensional';

    // Pre-filled exam info (all optional - user can override)
    suggestedName?: string;        // Suggested exam name
    suggestedDescription?: string; // Suggested description

    // === DIMENSIONS (multi_dimensional only) ===
    dimensions?: DimensionTemplate[];

    // === HIERARCHY ===
    hierarchyLevels?: string[];    // Custom level names

    // === WEIGHT SETTINGS ===
    weightSettings?: WeightSettingsTemplate;

    // === SAMPLE DATA (for preview) ===
    sampleHierarchy?: SampleNode[];
}

type TemplateCategory =
    | 'medical'           // USMLE, NBME, etc.
    | 'graduate'          // GRE, GMAT, LSAT, etc.
    | 'undergraduate'     // SAT, ACT, AP, etc.
    | 'professional'      // CPA, Bar, etc.
    | 'other';

interface DimensionTemplate {
    name: string;
    description?: string;
    isRequired: boolean;
    allowMultiple: boolean;
    displayOrder: number;

    // Sample values for preview (not saved to database)
    sampleValues?: string[];
}

interface WeightSettingsTemplate {
    autonomousBalancing?: boolean;
    precision?: 0 | 1 | 2;
    balancingAlgorithm?: 'proportional' | 'even';
}

interface SampleNode {
    name: string;
    children?: SampleNode[];
}
```

---

## Field Reference

### Metadata Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | Yes | Unique identifier in kebab-case (e.g., "nbme-shelf-exam") |
| `name` | string | Yes | Human-readable display name |
| `description` | string | Yes | 1-2 sentence description for template selection UI |
| `category` | string | Yes | One of: medical, graduate, undergraduate, professional, other |
| `tags` | string[] | No | Searchable keywords (e.g., ["medicine", "clinical", "step"]) |
| `targetUsers` | string[] | No | Target audience (e.g., ["Medical students", "IMG candidates"]) |
| `officialSource` | string | No | Name of official content outline source |
| `sourceUrl` | string | No | URL to official documentation |
| `icon` | string | No | Emoji for visual identification |
| `popularity` | number | No | 1-5 rating for default sort order |

### Configuration Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `examType` | string | Yes | Either "simple" or "multi_dimensional" |
| `suggestedName` | string | No | Pre-filled exam name (user can change) |
| `suggestedDescription` | string | No | Pre-filled description (user can change) |
| `dimensions` | array | No* | Array of dimension definitions (*required if examType is multi_dimensional) |
| `hierarchyLevels` | string[] | No | Custom hierarchy level names (default: ["System", "Subsystem", "Topic", "Subtopic", "Child"]) |
| `weightSettings` | object | No | Weight calculation settings |
| `sampleHierarchy` | array | No | Example hierarchy for preview in template selection |

### Dimension Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Dimension name (e.g., "Site of Care") |
| `description` | string | No | Help text explaining this dimension |
| `isRequired` | boolean | Yes | Whether users must tag every question in this dimension |
| `allowMultiple` | boolean | Yes | Whether multiple selections are allowed |
| `displayOrder` | number | Yes | Order in UI (1, 2, 3, ...) |
| `sampleValues` | string[] | No | Example values for template preview |

### Weight Settings Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `autonomousBalancing` | boolean | true | Auto-balance sibling weights |
| `precision` | number | 1 | Decimal places (0, 1, or 2) |
| `balancingAlgorithm` | string | "proportional" | Either "proportional" or "even" |

---

## Example Templates

### Example 1: SAT (Simple Exam)

```json
{
    "id": "sat-general",
    "name": "SAT",
    "description": "College admission test with Reading, Writing, and Math sections.",
    "category": "undergraduate",
    "tags": ["college", "admission", "standardized", "math", "reading", "writing"],
    "targetUsers": ["High school students", "College applicants"],
    "officialSource": "College Board SAT Content Specifications",
    "sourceUrl": "https://collegereadiness.collegeboard.org/sat",
    "icon": "graduation-cap",
    "popularity": 5,

    "examType": "simple",
    "suggestedName": "SAT",
    "suggestedDescription": "SAT preparation tracking",

    "hierarchyLevels": ["Section", "Domain", "Skill", "Topic", "Subtopic"],

    "weightSettings": {
        "autonomousBalancing": true,
        "precision": 0,
        "balancingAlgorithm": "proportional"
    },

    "sampleHierarchy": [
        {
            "name": "Evidence-Based Reading and Writing",
            "children": [
                {
                    "name": "Reading",
                    "children": [
                        {"name": "Information and Ideas"},
                        {"name": "Rhetoric"},
                        {"name": "Synthesis"}
                    ]
                },
                {
                    "name": "Writing and Language",
                    "children": [
                        {"name": "Expression of Ideas"},
                        {"name": "Standard English Conventions"}
                    ]
                }
            ]
        },
        {
            "name": "Math",
            "children": [
                {"name": "Heart of Algebra"},
                {"name": "Problem Solving and Data Analysis"},
                {"name": "Passport to Advanced Math"},
                {"name": "Additional Topics in Math"}
            ]
        }
    ]
}
```

### Example 2: NBME Shelf Exam (Multi-Dimensional)

```json
{
    "id": "nbme-shelf-internal-medicine",
    "name": "NBME Shelf: Internal Medicine",
    "description": "NBME Clinical Science Subject Exam with Site of Care, Physician Task, and System dimensions.",
    "category": "medical",
    "tags": ["medicine", "clinical", "shelf", "nbme", "internal medicine", "IM"],
    "targetUsers": ["Medical students (MS3/MS4)", "Clinical clerkship students"],
    "officialSource": "NBME Clinical Science Subject Examination Content Outline",
    "sourceUrl": "https://www.nbme.org/examinations/subject-examinations",
    "icon": "stethoscope",
    "popularity": 5,

    "examType": "multi_dimensional",
    "suggestedName": "Internal Medicine Shelf",
    "suggestedDescription": "NBME Internal Medicine Subject Exam preparation",

    "dimensions": [
        {
            "name": "Site of Care",
            "description": "The clinical setting where the patient encounter occurs",
            "isRequired": true,
            "allowMultiple": false,
            "displayOrder": 1,
            "sampleValues": ["Emergency Department", "Inpatient", "Ambulatory/Outpatient"]
        },
        {
            "name": "Physician Task",
            "description": "The primary clinical task being performed",
            "isRequired": true,
            "allowMultiple": false,
            "displayOrder": 2,
            "sampleValues": ["Diagnosis", "Prognosis", "Health Maintenance", "Pharmacotherapy", "Clinical Interventions", "Management"]
        },
        {
            "name": "System",
            "description": "The organ system or disease category",
            "isRequired": true,
            "allowMultiple": false,
            "displayOrder": 3,
            "sampleValues": ["Cardiovascular", "Pulmonary", "Gastrointestinal", "Renal", "Endocrine", "Hematology/Oncology", "Infectious Disease", "Rheumatology", "Neurology"]
        }
    ],

    "hierarchyLevels": ["System", "Category", "Topic", "Subtopic", "Detail"],

    "weightSettings": {
        "autonomousBalancing": true,
        "precision": 1,
        "balancingAlgorithm": "proportional"
    },

    "sampleHierarchy": [
        {
            "name": "Cardiovascular",
            "children": [
                {
                    "name": "Heart Failure",
                    "children": [
                        {"name": "HFrEF"},
                        {"name": "HFpEF"}
                    ]
                },
                {
                    "name": "Arrhythmias",
                    "children": [
                        {"name": "Atrial Fibrillation"},
                        {"name": "Ventricular Tachycardia"}
                    ]
                }
            ]
        },
        {
            "name": "Pulmonary",
            "children": [
                {"name": "COPD"},
                {"name": "Asthma"},
                {"name": "Pneumonia"}
            ]
        }
    ]
}
```

---

## Usage in Wizard

### Template Selection Flow

1. **Template Selection Step** (new step, inserted after exam type selection or as step 1)
   - Display templates filtered by `examType` if user has already selected a type
   - Group templates by `category`
   - Sort by `popularity` within each category
   - Show `icon`, `name`, `description`, and `targetUsers`
   - Include "Start from Scratch" option

2. **Auto-Population**
   When user selects a template:
   ```javascript
   // In ExamWizard
   applyTemplate(template) {
       // Set exam type (or validate it matches)
       this.data.examType = template.examType;

       // Apply suggested name/description
       if (template.suggestedName) {
           this.data.examName = template.suggestedName;
       }
       if (template.suggestedDescription) {
           this.data.examDescription = template.suggestedDescription;
       }

       // Apply dimensions (multi-dimensional only)
       if (template.dimensions) {
           this.data.dimensions = template.dimensions.map((dim, index) => ({
               id: Date.now() + index,
               name: dim.name,
               description: dim.description || '',
               isRequired: dim.isRequired,
               allowMultiple: dim.allowMultiple,
               displayOrder: dim.displayOrder
           }));
       }

       // Apply hierarchy levels
       if (template.hierarchyLevels) {
           this.data.hierarchyLevels = [...template.hierarchyLevels];
       }

       // Apply weight settings
       if (template.weightSettings) {
           this.data.weightSettings = {
               autonomousBalancing: template.weightSettings.autonomousBalancing ?? true,
               precision: template.weightSettings.precision ?? 1,
               balancingAlgorithm: template.weightSettings.balancingAlgorithm ?? 'proportional'
           };
       }
   }
   ```

3. **User Customization**
   - All template values are suggestions that users can modify
   - Wizard proceeds through normal steps with pre-filled values
   - Template metadata is not stored in database (only the final configuration)

### Search and Filter

Templates should support filtering by:
- `category`: Medical, Graduate, etc.
- `examType`: Simple vs Multi-dimensional
- `tags`: Keyword search across tags array
- Full-text search on `name` and `description`

---

## Validation Rules

### Template Validation

1. **Required Fields**
   - `id`: Must be unique, kebab-case, no spaces
   - `name`: Non-empty string
   - `description`: Non-empty string
   - `category`: Must be one of allowed values
   - `examType`: Must be "simple" or "multi_dimensional"

2. **Conditional Requirements**
   - If `examType` is "multi_dimensional", `dimensions` should be provided
   - Each dimension must have unique `name` and `displayOrder`

3. **Type Validation**
   - `popularity`: Integer 1-5
   - `precision`: Integer 0, 1, or 2
   - `displayOrder`: Positive integer

### JSON Schema (for automated validation)

A formal JSON Schema file (`exam_templates.schema.json`) should be created for:
- IDE autocomplete support
- Automated validation in CI/CD
- Documentation generation

---

## Future Considerations

### Potential Enhancements

1. **Template Inheritance**
   - Base templates that other templates extend
   - Example: "NBME Base" template that all shelf exams inherit from

2. **Template Versioning**
   - Track template versions for updates to official content outlines
   - Migration path when templates change

3. **User-Created Templates**
   - Allow users to save their exam configurations as templates
   - Share templates between users (export/import)

4. **Localization**
   - Multi-language support for template names and descriptions
   - Region-specific templates (e.g., UKMLA for UK medical students)

5. **Template Variables**
   - Placeholders in `suggestedName` like "{year}" -> "USMLE Step 1 2026"
   - Dynamic content based on user preferences

### Backwards Compatibility

When updating the schema:
1. New fields should be optional with sensible defaults
2. Document migration steps for breaking changes
3. Version the schema file for compatibility checking

---

## Complete Template Index (Planned)

Based on FUTURE_VISION.md requirements:

| Template ID | Name | Type | Category | Status |
|-------------|------|------|----------|--------|
| `nbme-shelf-internal-medicine` | NBME Shelf: Internal Medicine | Multi-Dimensional | Medical | Designed |
| `nbme-shelf-surgery` | NBME Shelf: Surgery | Multi-Dimensional | Medical | Planned |
| `nbme-shelf-pediatrics` | NBME Shelf: Pediatrics | Multi-Dimensional | Medical | Planned |
| `nbme-shelf-psychiatry` | NBME Shelf: Psychiatry | Multi-Dimensional | Medical | Planned |
| `nbme-shelf-obgyn` | NBME Shelf: OB/GYN | Multi-Dimensional | Medical | Planned |
| `nbme-shelf-family-medicine` | NBME Shelf: Family Medicine | Multi-Dimensional | Medical | Planned |
| `usmle-step-1` | USMLE Step 1 | Multi-Dimensional | Medical | Planned |
| `usmle-step-2-ck` | USMLE Step 2 CK | Multi-Dimensional | Medical | Planned |
| `usmle-step-3` | USMLE Step 3 | Multi-Dimensional | Medical | Planned |
| `mcat` | MCAT | Multi-Dimensional | Medical | Planned |
| `sat-general` | SAT | Simple | Undergraduate | Designed |
| `act` | ACT | Simple | Undergraduate | Planned |
| `gre-general` | GRE General Test | Simple | Graduate | Planned |
| `gmat` | GMAT | Multi-Dimensional | Graduate | Planned |
| `lsat` | LSAT | Simple | Graduate | Planned |
| `cpa` | CPA Exam | Multi-Dimensional | Professional | Planned |

---

## Document History

| Date | Version | Author | Changes |
|------|---------|--------|---------|
| 2026-01-24 | 1.0 | Claude Code | Initial schema design |

---

**END OF SCHEMA DESIGN DOCUMENT**
