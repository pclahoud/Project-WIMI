# WIMI Exam Outline Imports

This folder holds an example subject-tree import file.

## Files

### `cardiology_example.json`
A **synthetic** example of the import format: one subject tree, written for this repository (#437). It uses ordinary medical terms, but its grouping, ordering and wording are this project's own. It is not taken from any exam's published outline.

**Statistics:**
- 1 System (Cardiology)
- 8 Categories
- 49 Topics, one with Subtopics
- 61 subjects in all
- 31 Aliases, typed as `acronym`, `eponym`, `colloquial` or `alternate_name`

It carries **no weights, on purpose**. A weight is a percentage that your own exam publishes, and an example that invented one would teach exactly the thing an import file must not do. See the format guide below for how weights are written.

It is checked against the published schema (`docs/examples/subject_tree_import.schema.json`). It imports through the tree editor's planner with no warnings, and importing it a second time changes nothing.

### `import_exam_outline.py`
**Out of date: it does not run on the current tree** (see #626). It imports `src.database` in a way that no longer resolves, and it reads a `subjects` key and plain-string aliases, which is an older shape than the current format. Use the in-app importer below.

## Importing

Open the exam in the **tree editor**, press **Import**, and choose the file. The preview shows what would be added, changed or kept before anything is written.

## The format

The format guide is `docs/examples/subject_tree_import_format.md`, and the published JSON Schema is `docs/examples/subject_tree_import.schema.json`. The same guide is in the app, behind the tree editor's ❓ button. A minimal file:

```json
{
  "root_nodes": [
    {
      "name": "Cardiology",
      "level_type": "System",
      "aliases": [{"name": "Cardio", "type": "colloquial"}],
      "children": [
        {
          "name": "Rhythm and conduction",
          "level_type": "Category",
          "children": [
            {
              "name": "Atrial fibrillation",
              "level_type": "Topic",
              "aliases": [{"name": "AF", "type": "acronym"}]
            }
          ]
        }
      ]
    }
  ]
}
```

## Making a file for your own exam

The student manual's chapter on turning an outline into a tree describes the supported route. Start from your own exam's published outline, and copy weights only from what that outline publishes.
