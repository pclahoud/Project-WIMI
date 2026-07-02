Subject Hierarchy Notes

Feature Design Document

WIMI - What I Missed It

| **Version** | 1.0.0 - Initial Design |
| --- | --- |
| **Date** | January 2026 |
| **Status** | Draft - Under Discussion |
| **Author** | WIMI Development Team |

# Table of Contents

# 1\. Executive Summary

This document outlines the design for a dedicated Notes feature integrated into WIMI's subject hierarchy system. The feature enables students to capture, organize, and review knowledge at each level of their exam's subject structure, complementing the existing mistake analysis workflow with proactive knowledge documentation.

The Notes feature supports rich content creation with customizable templates, allowing students to build comprehensive study materials that align with their exam structure. Integration with Anki enables spaced repetition workflows, while configurable inheritance options let users aggregate notes across hierarchy levels.

# 2\. Design Decisions

The following key decisions were made during the design discussion and will guide implementation:

## 2.1 Note-Enabled Levels Configuration

- **Decision:** Users define which hierarchy levels support notes during exam creation.

- Configured in the Exam Creation Wizard
- Per-exam configuration (different exams may have different note-enabled levels)
- Modifiable after exam creation through settings
- Default: Notes enabled at Topic level and below

## 2.2 Content Format

- **Decision:** Rich content with template functionality.

- Rich text editor with formatting options (bold, italic, lists, etc.)
- Template system for consistent note structure
- Template management interface in dedicated Notes page
- Support for images, links, and embedded media

## 2.3 UI/UX Approach

- **Decision:** Dual-interface approach.

- **Option A - Integrated Tab:** Notes tab in Tree Editor details panel for context-aware editing
- **Option B - Dedicated Page:** Full-featured Notes page (subject_notes.html) for comprehensive note management
- **Option D - Notes Dashboard:** To be discussed further - cross-subject notes browser

## 2.4 Inheritance/Aggregation

- **Decision:** User-configurable inheritance behavior.

- Per-exam setting for note inheritance/aggregation
- Options: No inheritance, Aggregate children, Inherit from parent
- Configured during Notes setup in exam configuration

## 2.5 External Integrations

- **Decision:** Anki integration confirmed; Analytics integration deferred.

- **Anki Integration:** Link notes to Anki cards for spaced repetition correlation
- **Analytics:** To be discussed in future planning sessions

# 3\. Feature Overview

## 3.1 Core Capabilities

| **Capability** | **Description** |
| --- | --- |
| **Hierarchical Notes** | Create and manage notes at user-defined hierarchy levels |
| **Rich Text Editing** | Full formatting support including bold, italic, lists, headings, and more |
| **Template System** | Create, manage, and apply note templates for consistent structure |
| **Media Support** | Embed images, links, and attachments within notes |
| **Anki Linking** | Associate notes with Anki cards for spaced repetition tracking |
| **Configurable Inheritance** | Choose how notes propagate or aggregate across hierarchy levels |

## 3.2 User Workflows

### 3.2.1 Creating Notes from Tree Editor

- User navigates to Tree Editor and selects a subject node
- Details panel shows "Notes" tab (if level is note-enabled)
- User clicks "Add Note" or selects from template gallery
- Rich text editor opens with optional template pre-populated
- User writes/edits content and saves

### 3.2.2 Managing Notes from Dedicated Page

- User navigates to Notes page from main navigation
- Hierarchy browser on left shows note-enabled subjects
- Main panel shows notes for selected subject with full editing capabilities
- Template management accessible from toolbar
- Anki linking interface available for each note

# 4\. UI Components

## 4.1 Tree Editor Integration (Option A)

The Tree Editor's details panel will include a new "Notes" tab alongside existing tabs. This tab provides quick access to notes for the currently selected subject node.

### 4.1.1 Notes Tab Components

| **Component** | **Description** |
| --- | --- |
| **Note List** | Scrollable list of notes for the selected node, showing title and preview |
| **Quick Add Button** | Creates new blank note or opens template selector |
| **Inline Editor** | Compact rich text editor for quick edits (expands on focus) |
| **Open Full Editor** | Link to open note in dedicated Notes page for full editing |
| **Inherited Notes** | Collapsible section showing notes from parent/child nodes (if inheritance enabled) |

## 4.2 Dedicated Notes Page (Option B)

A full-featured notes management page accessible from the main navigation. Provides comprehensive note creation, editing, and organization capabilities.

### 4.2.1 Page Layout

- **Header:** Exam selector, search bar, template management button
- **Left Sidebar:** Collapsible hierarchy tree showing note-enabled subjects with note counts
- **Main Panel:** Note editor with full rich text capabilities
- **Right Sidebar (optional):** Anki card links, related entries, metadata

### 4.2.2 Rich Text Editor Features

| **Text Formatting** | **Structure** | **Media & Links** |
| --- | --- | --- |
| Bold, Italic, Underline | Headings (H1-H3) | Image upload/paste |
| Strikethrough | Bullet lists | External links |
| Highlight colors | Numbered lists | Internal note links |
| Font size | Block quotes | File attachments |
| Text color | Code blocks | Anki card references |
| Subscript/Superscript | Tables | Entry references |

## 4.3 Notes Dashboard (Option D - To Be Discussed)

A dashboard view for browsing and searching notes across all subjects. Details to be discussed in future planning sessions. Potential features include:

- Full-text search across all notes
- Filter by hierarchy level, date created/modified, tags
- Card-based or list view of notes with breadcrumb paths
- Quick preview and inline editing capabilities
- Export functionality for study materials

# 5\. Template System

## 5.1 Template Concept

Templates provide pre-defined structures for notes, ensuring consistency and helping students organize their knowledge effectively. Templates can include placeholder sections, formatting, and guidance text.

## 5.2 Built-in Templates

| **Template Name** | **Structure / Sections** |
| --- | --- |
| **Quick Reference** | Key Points, Common Pitfalls, High-Yield Facts |
| **Concept Deep Dive** | Definition, Mechanism/Explanation, Clinical/Practical Application, Examples, Related Topics |
| **Comparison Table** | Pre-formatted comparison table with customizable columns |
| **Mnemonic Builder** | Mnemonic, What It Represents, Memory Cues, Usage Context |
| **Formula/Rule Card** | Formula/Rule, When to Use, Common Mistakes, Practice Problems |
| **Case Study** | Scenario, Key Findings, Differential, Workup, Answer, Learning Points |
| **Blank Note** | Empty note with no pre-defined structure |

## 5.3 Custom Templates

Users can create custom templates tailored to their study style and exam requirements:

- Create from scratch or duplicate/modify existing templates
- Save current note as template
- Per-exam or global template scope
- Template categories for organization
- Import/export templates

## 5.4 Template Management Interface

Accessed from the dedicated Notes page, the template management interface allows:

- View all templates in grid or list format
- Preview template structure before use
- Edit template name, description, and structure
- Set default template for new notes
- Delete or archive unused templates

# 6\. Configuration

## 6.1 Exam Creation Wizard Integration

A new step in the Exam Creation Wizard allows users to configure notes settings:

### 6.1.1 Note-Enabled Levels Selection

- Checkbox list of all defined hierarchy levels
- Visual preview of which levels will support notes
- Recommended defaults based on exam type

### 6.1.2 Inheritance Configuration

| **Option** | **Behavior** |
| --- | --- |
| **None** | Notes exist only at their assigned level; no inheritance or aggregation |
| **Aggregate Up** | Parent nodes show aggregated view of all child notes (read-only) |
| **Inherit Down** | Child nodes can access and reference parent notes |
| **Bidirectional** | Both aggregation and inheritance enabled |

## 6.2 Post-Creation Settings

Notes configuration can be modified after exam creation through the Exam Settings page:

- Enable/disable notes for additional levels
- Change inheritance mode (with warning about potential data implications)
- Set default template for the exam
- Configure Anki integration settings

# 7\. Anki Integration

## 7.1 Linking Notes to Anki Cards

Users can establish connections between notes and Anki cards for enhanced spaced repetition tracking:

- Manual linking: Search and select Anki cards to associate with a note
- Auto-suggest: Based on subject hierarchy and card tags
- Bidirectional references: View linked notes from Anki card browser

## 7.2 Card Creation from Notes

Optional workflow to create Anki cards directly from note content:

- Select text or section to convert to card
- Choose card type (Basic, Cloze, etc.)
- Automatically tag with subject hierarchy path
- Link created card back to source note

## 7.3 Review Status Display

Notes display Anki review status for linked cards:

- Visual indicator of card maturity (new, learning, mature)
- Next review date for linked cards
- Aggregate statistics for notes with multiple linked cards

# 8\. Data Model

## 8.1 New Database Tables

### 8.1.1 subject_notes

Stores individual notes linked to subject nodes:

| **Column** | **Type** | **Description** |
| --- | --- | --- |
| id  | INTEGER PK | Primary key |
| subject_node_id | INTEGER FK | Reference to subject_nodes table |
| title | VARCHAR(255) | Note title |
| content | TEXT | Rich text content (HTML or Markdown) |
| content_format | VARCHAR(20) | 'html' or 'markdown' |
| template_id | INTEGER FK | Reference to template used (nullable) |
| sort_order | INTEGER | Order within subject's notes |
| is_pinned | BOOLEAN | Whether note is pinned to top |
| created_at | TIMESTAMP | Creation timestamp |
| updated_at | TIMESTAMP | Last modification timestamp |

### 8.1.2 note_templates

Stores note templates:

| **Column** | **Type** | **Description** |
| --- | --- | --- |
| id  | INTEGER PK | Primary key |
| name | VARCHAR(100) | Template name |
| description | TEXT | Template description |
| content | TEXT | Template structure/content |
| category | VARCHAR(50) | Template category |
| is_system | BOOLEAN | Whether this is a built-in template |
| exam_context_id | INTEGER FK | Exam-specific template (nullable for global) |
| created_at | TIMESTAMP | Creation timestamp |

### 8.1.3 note_anki_links

Links notes to Anki cards:

| **Column** | **Type** | **Description** |
| --- | --- | --- |
| id  | INTEGER PK | Primary key |
| note_id | INTEGER FK | Reference to subject_notes |
| anki_note_id | BIGINT | Anki note ID |
| anki_card_id | BIGINT | Anki card ID (nullable) |
| link_type | VARCHAR(20) | 'manual', 'auto_suggested', 'created_from' |
| created_at | TIMESTAMP | Link creation timestamp |

### 8.1.4 note_media

Stores media attachments for notes:

| **Column** | **Type** | **Description** |
| --- | --- | --- |
| id  | INTEGER PK | Primary key |
| note_id | INTEGER FK | Reference to subject_notes |
| file_uuid | VARCHAR(36) | UUID for file storage |
| original_filename | VARCHAR(255) | Original file name |
| mime_type | VARCHAR(100) | File MIME type |
| file_size_bytes | INTEGER | File size |
| created_at | TIMESTAMP | Upload timestamp |

## 8.2 Schema Modifications

### 8.2.1 exam_contexts Table Additions

| **Column** | **Type** | **Description** |
| --- | --- | --- |
| notes_enabled_levels | JSON | Array of level names with notes enabled |
| notes_inheritance_mode | VARCHAR(20) | 'none', 'aggregate_up', 'inherit_down', 'bidirectional' |
| default_note_template_id | INTEGER FK | Default template for new notes |

# 9\. Implementation Phases

The Notes feature will be implemented in phases to allow incremental delivery and testing:

## 9.1 Phase 1: Foundation

- Database schema creation and migrations
- Data models and basic CRUD operations
- Bridge methods for frontend communication
- Exam Creation Wizard integration for notes configuration

## 9.2 Phase 2: Tree Editor Integration

- Notes tab in details panel
- Note list display and management
- Basic rich text editor implementation
- Quick add functionality

## 9.3 Phase 3: Dedicated Notes Page

- Full-featured notes page layout
- Hierarchy browser sidebar
- Advanced rich text editor with all features
- Media upload and management

## 9.4 Phase 4: Template System

- Built-in template library
- Custom template creation
- Template management interface
- Template application workflow

## 9.5 Phase 5: Anki Integration

- Note-to-card linking interface
- Card creation from notes
- Review status display
- Bidirectional reference navigation

## 9.6 Phase 6: Inheritance & Advanced Features

- Note inheritance/aggregation logic
- Inherited notes display
- Search and filtering
- Export functionality

# 10\. Open Items for Discussion

## 10.1 Notes Dashboard (Option D)

The Notes Dashboard concept requires further discussion to define scope and features. Key questions include:

- Should the dashboard be a separate page or integrated into the Notes page?
- What filtering and sorting options are most valuable?
- How should cross-exam notes be handled?
- What export formats should be supported?

## 10.2 Analytics Integration

Analytics tie-in with the notes feature to be discussed in future sessions. Potential metrics include:

- Correlation between note coverage and mistake frequency
- Note creation patterns and study habits
- Template effectiveness metrics
- Integration with existing Phase 6 analytics

## 10.3 Rich Text Editor Selection

Technical decision needed on which rich text editor library to use. Options to evaluate:

- Quill.js - Feature-rich, good API, MIT license
- TipTap - Modern, extensible, based on ProseMirror
- CKEditor 5 - Robust, but licensing considerations
- Custom implementation - Maximum control, higher effort

# 11\. Revision History

| **Version** | **Date** | **Changes** |
| --- | --- | --- |
| 1.0.0 | January 2026 | Initial design document based on discussion with project stakeholder |