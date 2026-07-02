# WIMI Exam Outline Imports

This folder contains JSON import files and utilities for importing standardized exam content outlines into Project WIMI.

## Files

### `usmle_cardiovascular.json`
Sample import file containing the **Cardiovascular System** section from the USMLE Content Outline (2025). This serves as a test/template for importing other exam systems.

**Statistics:**
- 1 System (Cardiovascular)
- 15 Categories
- ~60 Subcategories
- ~40 Topics
- ~120 Aliases

### `import_exam_outline.py`
Python utility for importing JSON outline files into WIMI databases.

## JSON Structure

```json
{
  "exam_metadata": {
    "exam_name": "USMLE Step 1",
    "exam_code": "USMLE-1",
    "exam_source": "USMLE Content Outline 2025",
    "hierarchy_levels": ["System", "Category", "Subcategory", "Topic", "Subtopic"]
  },
  "subjects": [
    {
      "name": "Cardiovascular System",
      "level_type": "System",
      "sort_order": 1,
      "aliases": ["CV", "Cardio"],
      "children": [
        {
          "name": "Dysrhythmias",
          "level_type": "Category",
          "aliases": ["Arrhythmias"],
          "children": [...]
        }
      ]
    }
  ]
}
```

## Usage

### Demo Mode (Temporary Database)
```bash
cd examples/imports
python import_exam_outline.py --demo
```

### Import to User Database
```bash
python import_exam_outline.py usmle_cardiovascular.json --db-path ../../app_data/user_1.db --user-id 1
```

### Validate JSON Structure Only
```bash
python import_exam_outline.py usmle_cardiovascular.json --validate-only
```

### Options
| Option | Description |
|--------|-------------|
| `--demo` | Run with temporary database |
| `--db-path` | Path to user database file |
| `--user-id` | User ID (default: 1) |
| `--max-depth` | Maximum hierarchy depth (default: 5) |
| `--quiet` | Suppress progress messages |
| `--validate-only` | Only validate JSON, don't import |

## Hierarchy Depth Limit

By default, import is capped at **5 levels** to match the default WIMI hierarchy:
1. System (e.g., "Cardiovascular System")
2. Category (e.g., "Dysrhythmias")
3. Subcategory (e.g., "Atrioventricular block")
4. Topic (e.g., "Second-degree AV block")
5. Subtopic (if needed)

Items beyond level 5 are skipped and logged.

## Aliases

The JSON supports aliases for common abbreviations and synonyms:
- Abbreviations (≤5 chars): `"AFib"`, `"MI"`, `"DVT"`
- Synonyms: `"Heart attack"`, `"Broken heart syndrome"`

Aliases help with:
- Quick searching
- Question tagging
- Pattern recognition

## Creating New Import Files

### Step 1: Gather Source Material
- Official content outlines (PDFs, websites)
- Exam blueprints with topic weights

### Step 2: Structure the JSON
```json
{
  "exam_metadata": {
    "exam_name": "Your Exam Name",
    "hierarchy_levels": ["Level1", "Level2", "Level3", "Level4", "Level5"]
  },
  "subjects": [
    // Hierarchical structure
  ]
}
```

### Step 3: Validate
```bash
python import_exam_outline.py your_file.json --validate-only
```

### Step 4: Test Import
```bash
python import_exam_outline.py your_file.json --demo
```

## Future Improvements

- [ ] Support for exam weights from official specifications
- [ ] CSV import format option
- [ ] Merge/update existing hierarchies
- [ ] Export functionality (database → JSON)
- [ ] Bulk import for all USMLE systems

## Source Documents

- [USMLE Content Outline](https://www.usmle.org) - Official USMLE exam blueprint
- [USMLE Physician Tasks/Competencies](https://www.usmle.org/sites/default/files/2022-01/USMLE_Physician_Tasks_Competencies_2.pdf)
