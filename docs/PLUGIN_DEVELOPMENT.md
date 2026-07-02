# WIMI Plugin Development Guide

This guide covers everything you need to create, test, and distribute plugins for WIMI.

## Quick Start

A WIMI plugin is a folder containing a `manifest.json` and optional Python/JS/CSS files. Here's the simplest possible plugin:

```
my-plugin/
  manifest.json
```

```json
{
  "id": "my-plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "description": "A minimal WIMI plugin."
}
```

Place it in `app_data/plugins/` and it appears in **Settings > Addons**.

---

## Plugin Structure

```
my-plugin/
  manifest.json        # Required — metadata, permissions, settings
  backend.py           # Optional — Python backend with database access
  frontend.js          # Optional — JavaScript injected into every page
  styles.css           # Optional — CSS injected into every page
  data/                # Auto-created — sandboxed file storage (requires 'storage' permission)
```

---

## Manifest Reference

`manifest.json` is the only required file. All fields:

```json
{
  "id": "my-plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "description": "What the plugin does.",
  "author": "Your Name",
  "min_app_version": "1.0.0",
  "permissions": ["read"],
  "backend": "backend.py",
  "frontend_js": "frontend.js",
  "frontend_css": "styles.css",
  "slots": {
    "landing-after-exams": "<div class='my-widget'>Hello</div>"
  },
  "settings": [
    {
      "key": "greeting",
      "type": "text",
      "label": "Greeting Message",
      "description": "Shown when the plugin loads.",
      "default": "Hello!"
    }
  ]
}
```

### Required Fields

| Field | Rules |
|-------|-------|
| `id` | Alphanumeric, hyphens, underscores. 1-64 chars. Must be unique. |
| `name` | Display name. Max 128 chars. |
| `version` | Semantic version: `X.Y.Z` (e.g. `1.0.0`). |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `description` | string | Short description shown in the Addons UI. |
| `author` | string | Author name shown in the Addons UI. |
| `min_app_version` | string | Minimum WIMI version required (`X.Y.Z` format). |
| `permissions` | string[] | Permissions the plugin needs (see below). Defaults to `["read"]`. |
| `backend` | string | Filename of the Python backend module (relative to plugin dir). |
| `frontend_js` | string | Filename of the JavaScript file to inject on every page. |
| `frontend_css` | string | Filename of the CSS file to inject on every page. |
| `slots` | object | Map of slot name to HTML content to inject (see [Slots](#slots)). |
| `settings` | object[] | User-configurable settings (see [Settings](#settings)). |

---

## Permissions

Plugins declare which operations they need. Read access is always granted. Write operations require explicit permission.

| Permission | Grants |
|------------|--------|
| `read` | Read entries, sessions, subjects, tags, exams, analytics, sources, notes, media. Always available. |
| `write:entries` | Create and update question entries. |
| `write:sessions` | Create review sessions. |
| `write:notes` | Add and update entry notes. |
| `write:goals` | Create and update weekly goals. |
| `write:media` | Upload media (images) to entries. |
| `storage` | Read/write files in the plugin's `data/` directory. |

Attempting a write operation without the corresponding permission raises a `PermissionError`. Delete operations are never available to plugins.

Example:
```json
"permissions": ["read", "write:entries", "write:notes", "write:media", "storage"]
```

---

## Backend Plugins (Python)

Backend plugins run Python code with access to the WIMI database through a scoped API.

### Entry Point

Your backend module **must** export a `create_plugin(api)` function that returns your plugin instance:

```python
# backend.py

class MyPlugin:
    def __init__(self, api):
        self.api = api

    def hello(self, name="World"):
        """Methods are callable from the frontend via api.callPlugin()."""
        return {"message": f"Hello, {name}!"}

    def on_unload(self):
        """Optional cleanup hook called when the plugin is disabled or uninstalled."""
        pass

def create_plugin(api):
    return MyPlugin(api)
```

### Plugin API Reference

The `api` object passed to `create_plugin()` provides these methods:

#### Read Methods (always available)

| Method | Returns | Description |
|--------|---------|-------------|
| `api.get_entry(entry_id)` | dict | Single entry with full context. |
| `api.get_entries(exam_id=None, page=1, per_page=50)` | dict | Paginated entries (`{entries, total, page, per_page}`). |
| `api.search_entries(query, exam_id=None)` | list | Full-text search entries. |
| `api.get_sessions(exam_id=None)` | list | Review sessions. |
| `api.get_session(session_id)` | dict | Single session. |
| `api.get_subject_tree(exam_id)` | list | Subject hierarchy for an exam. |
| `api.get_subject_path(subject_id)` | str | Full path string for a subject node. |
| `api.search_subjects(exam_id, query)` | list | Search subjects within an exam. |
| `api.get_tags(exam_context_name)` | list | Tags for an exam context. |
| `api.get_entry_media(entry_id)` | list | Media attachments for an entry. |
| `api.get_entry_notes(entry_id)` | list | Notes for an entry. |
| `api.get_exams()` | list | All exam contexts. |
| `api.get_exam(exam_id)` | dict | Single exam context. |
| `api.get_overview(exam_id=None)` | dict | Analytics overview. |
| `api.get_subject_analytics(**params)` | list | Subject analytics data. |
| `api.get_activity(**params)` | list | Activity over time. |
| `api.get_streak(exam_id=None)` | dict | Study streak info. |
| `api.get_sources(exam_context_name='')` | list | Question sources. |

#### API Response Examples

**`api.get_exams()`** -- returns `ExamContextConfig` dataclass fields. The display name is **`exam_name`** (not `name`):

```json
[
    {
        "id": 6,
        "user_id": 1,
        "exam_name": "Internal Medicine Shelf",
        "exam_description": "NBME Internal Medicine Subject Exam...",
        "exam_date": null,
        "created_date": "2026-01-15",
        "is_active": true,
        "default_hierarchy_levels": ["System", "Category", "Topic", "Subtopic", "Detail"],
        "weight_validation_rules": { "autonomous_weight_balancing": true, "..." : "..." },
        "notes": null,
        "created_at": "2026-01-15T00:00:00",
        "updated_at": "2026-01-15T00:00:00"
    }
]
```

**`api.get_sources(exam_context_name)`** -- filters server-side by the `exam_context` column (the exam name string, e.g. `"USMLE Step 1"`). Also includes sources where `exam_context IS NULL`. Pass empty string or omit to get all sources. The source name field is **`source_name`**:

```json
[
    {
        "id": 1,
        "user_id": 1,
        "source_name": "UWorld",
        "source_type": "commercial_prep",
        "exam_context": "USMLE Step 1",
        "description": null,
        "url": null,
        "total_questions": null,
        "user_rating": null,
        "is_active": true,
        "created_at": "2026-...",
        "updated_at": "2026-..."
    }
]
```

**`api.get_entry(entry_id)`** -- returns a nested dict. The entry itself is under the `entry` key; related context (`session`, `exam`, `source`) are sibling keys:

```json
{
    "entry": {
        "id": 142,
        "review_session_id": 31,
        "entry_order": 3,
        "question_id": null,
        "user_answer": "...",
        "correct_answer": "...",
        "perceived_difficulty": null,
        "time_spent_seconds": null,
        "reflection": "...",
        "explanation": "...",
        "notes": null,
        "is_draft": false,
        "primary_subjects": [{"id": 5, "name": "Cardiology", "dimension_id": 1, "dimension_name": "Organ System"}],
        "secondary_subjects": [],
        "tags": [{"id": 1, "name": "Review", "color": "#3b82f6"}],
        "media": [{"id": 89, "file_uuid": "6434e181-...", "filename": "image.png", "mime_type": "image/png"}],
        "notes_list": [],
        "created_at": "2026-02-27T20:41:11",
        "updated_at": "2026-03-11T20:08:04"
    },
    "session": {
        "id": 31,
        "name": "31 - Surgery Day 15",
        "date": "2026-02-19",
        "total_questions": 5,
        "total_incorrect": 3
    },
    "exam": {
        "name": "Usmle 3",
        "description": ""
    },
    "source": {
        "name": "Uworld",
        "type": "commercial_prep"
    },
    "subject_path": "Organ System > Surgery > Pediatric Surgery"
}
```

> **Note:** The entry's source comes from the session's linked `question_source`, not from the entry directly. `question_id` is a user-provided identifier and is often `null`.

#### Write Methods (permission-gated)

| Method | Permission | Returns | Description |
|--------|-----------|---------|-------------|
| `api.create_entry(data)` | `write:entries` | dict | Create a question entry. |
| `api.update_entry(entry_id, data)` | `write:entries` | dict | Update an entry. |
| `api.create_session(data)` | `write:sessions` | dict | Create a review session. |
| `api.add_note(entry_id, data)` | `write:notes` | dict | Add a note to an entry. |
| `api.update_note(note_id, data)` | `write:notes` | dict | Update a note. |
| `api.create_goal(target, **params)` | `write:goals` | dict | Create/update weekly goal. |
| `api.upload_media(entry_id, base64_data, filename, mime_type)` | `write:media` | dict | Upload a media image to an entry. |

#### Media Upload Details

**`api.upload_media(entry_id, base64_data, filename, mime_type)`** uploads a base64-encoded image and attaches it to an entry.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `entry_id` | int | The entry to attach the media to. |
| `base64_data` | str | Base64-encoded image data. Accepts raw base64 or a data URL (e.g. `data:image/png;base64,...`). |
| `filename` | str | Original filename (e.g. `"card_front.png"`). |
| `mime_type` | str | MIME type of the image. Must be one of: `image/png`, `image/jpeg`, `image/gif`, `image/webp`, `image/bmp`, `image/svg+xml`. |

**Returns** a full media record dict:

```json
{
    "id": 90,
    "file_uuid": "a1b2c3d4-...",
    "original_filename": "card_front.png",
    "user_filename": "card_front.png",
    "mime_type": "image/png",
    "file_size": 24576,
    "sort_order": 1,
    "dimension_id": null,
    "linked_subject_ids": [5, 12],
    "thumbnail_url": "media://user_1_.../thumb_a1b2c3d4-....png",
    "full_url": "media://user_1_.../a1b2c3d4-....png"
}
```

**Errors:** Returns an error object if the MIME type is not in the allowed list, the base64 data is corrupt/undecodable, or the `entry_id` does not exist.

**Notes:**
- Subject linking is handled automatically by WIMI based on the entry's subjects.
- Deduplication is **not** performed. Plugins should check `api.get_entry_media(entry_id)` before uploading to avoid creating duplicate attachments.
- Media deletion and detachment is managed by users through the WIMI UI, not through the plugin API.

**Example** (uploading an image from an external source like AnkiConnect):

```python
# Backend: upload a base64 image to an entry
media = self.api.upload_media(
    entry_id=142,
    base64_data=base64_image_string,
    filename='card_front.png',
    mime_type='image/png'
)
print(f"Uploaded: {media['id']} {media['file_uuid']}")
```

#### Plugin-Private Storage (always available)

Plugins get their own key-value store that persists across sessions. Values are JSON-serialized.

| Method | Description |
|--------|-------------|
| `api.get_data(key)` | Get a value from plugin-private storage. Returns `None` if not found. |
| `api.set_data(key, value)` | Set a value. Supports strings, numbers, bools, lists, dicts. |
| `api.get_settings()` | Get this plugin's user-configured settings (merged with defaults). |

#### File Storage (requires `storage` permission)

Plugins can read and write files within a sandboxed `data/` subdirectory inside their plugin folder. This is useful for caching generated reports, storing config files, or persisting data that doesn't fit the key-value store.

**Security:** All paths are resolved and validated to prevent directory traversal. Plugins cannot access files outside their own `data/` directory, and cannot modify their own source files (`manifest.json`, `backend.py`, etc.).

| Method | Description |
|--------|-------------|
| `api.read_file(path, binary=False)` | Read a file. Returns `str` (or `bytes` if `binary=True`), or `None` if not found. |
| `api.write_file(path, content)` | Write a `str` or `bytes` to a file. Parent directories are created automatically. Returns bytes written. |
| `api.delete_file(path)` | Delete a file. Returns `True` if deleted, `False` if not found. |
| `api.list_files(subdir='')` | List all files (recursively). Returns relative paths with `/` separators. |
| `api.file_exists(path)` | Check if a file exists. Returns `bool`. |

All `path` arguments are relative to `{plugin_dir}/data/`. For example, `api.write_file('cache/report.json', data)` writes to `app_data/plugins/my-plugin/data/cache/report.json`.

Example:
```python
# Save a generated report
import json
report = {'entries_reviewed': 42, 'generated': '2026-03-16'}
api.write_file('reports/latest.json', json.dumps(report, indent=2))

# Read it back
content = api.read_file('reports/latest.json')
data = json.loads(content)

# List all stored files
files = api.list_files()  # ['reports/latest.json']
```

**On uninstall**, the entire plugin directory (including `data/`) is deleted automatically.

### Calling Backend Methods from the Frontend

Any public method on your plugin instance can be called from JavaScript:

```javascript
// Frontend JS
const result = await api.callPlugin('my-plugin', 'hello', { name: 'WIMI' });
console.log(result.message); // "Hello, WIMI!"
```

Parameters are passed as keyword arguments to the Python method.

---

## Frontend Plugins (JavaScript & CSS)

Frontend assets are injected on every page the user visits.

### Load Order

WIMI loads your plugin assets in this order:

1. **CSS** -- `styles.css` injected into `<head>`
2. **Slot HTML** -- manifest `slots` content injected into matching `data-plugin-slot` elements
3. **JavaScript** -- `frontend.js` loaded and executed

This means your JS can safely query slot elements (e.g., `document.getElementById('my-widget')`)
immediately after `await api.ready()` -- the slot HTML is already in the DOM.

> **Exception:** The `plugin-settings-{id}` slot on the Settings page is created dynamically
> by the settings UI, not from static HTML. See [Custom Settings UI](#custom-settings-ui)
> for the `wimi:plugin-settings-ready` event pattern.

### JavaScript

Your `frontend.js` runs after the page loads. You have access to:

- **`window._wimiApi`** (or `api`) -- The full WIMI JavaScript API for bridge calls.
- **`window.eventBus`** -- Pub/sub event bus for cross-component communication.
- **`window.PluginLoader`** -- Plugin lifecycle info.

```javascript
// frontend.js -- preferred pattern (works regardless of load timing)
(function() {
    'use strict';

    (async function() {
        // Wait for WIMI API to be available
        await api.ready();

        // Read data
        var exams = await api.getAllExamContexts();
        console.log('My plugin loaded! Exams:', exams.length);

        // Call your backend
        var result = await api.callPlugin('my-plugin', 'hello', { name: 'User' });
        console.log(result.message);
    })();
})();
```

> **Note:** The `wimi:ready` event pattern (`window.addEventListener('wimi:ready', ...)`)
> also works -- WIMI re-dispatches the event after each plugin script loads. However,
> `await api.ready()` is preferred because it is a promise that resolves immediately
> if the API is already connected, avoiding any timing dependency.

### JavaScript API Methods

The frontend `api` object provides JavaScript wrappers for media upload and other operations.

#### `api.uploadMedia(pluginId, entryId, base64Data, filename, mimeType)`

Uploads a base64-encoded image and attaches it to an entry. Requires the `write:media` permission.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `pluginId` | string | Your plugin's ID (must match your manifest). |
| `entryId` | number | The entry to attach the media to. |
| `base64Data` | string | Base64-encoded image data. Accepts raw base64 or a data URL (e.g. `data:image/png;base64,...`). |
| `filename` | string | Original filename (e.g. `"card_front.png"`). |
| `mimeType` | string | MIME type of the image. Must be one of: `image/png`, `image/jpeg`, `image/gif`, `image/webp`, `image/bmp`, `image/svg+xml`. |

**Returns** a full media record object:

| Field | Type | Description |
|-------|------|-------------|
| `id` | number | Database ID of the media record. |
| `file_uuid` | string | Unique file identifier (UUID). |
| `original_filename` | string | The filename as provided. |
| `user_filename` | string | Display filename. |
| `mime_type` | string | MIME type of the stored file. |
| `file_size` | number | File size in bytes. |
| `sort_order` | number | Display order within the entry. |
| `dimension_id` | number/null | Associated dimension, if any. |
| `linked_subject_ids` | array/null | Subject IDs linked to this media. |
| `thumbnail_url` | string | URL for the thumbnail image. |
| `full_url` | string | URL for the full-size image. |

**Errors:** Returns an error object if the MIME type is not in the allowed list, the base64 data is corrupt/undecodable, or the `entryId` does not exist.

**Notes:**
- Subject linking is handled automatically by WIMI based on the entry's subjects.
- Deduplication is **not** performed. Plugins should check `api.getEntryMedia(entryId)` before uploading to avoid creating duplicate attachments.
- Media deletion and detachment is managed by users through the WIMI UI, not through the plugin API.

**Example** (uploading an image received from AnkiConnect):

```javascript
// Upload a base64 image to an entry (pluginId must match your manifest)
const media = await api.uploadMedia('my-plugin-id', entryId, base64ImageData, 'card_image.png', 'image/png');
console.log('Uploaded:', media.id, media.file_uuid);
```

### CSS

Your `styles.css` is injected into `<head>` on every page. Use specific selectors to avoid conflicts:

```css
/* styles.css -- prefix everything with your plugin ID */
.my-plugin-widget {
    padding: 1rem;
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    background: var(--bg-primary);
    color: var(--text-primary);
}
```

Use WIMI's CSS custom properties (e.g. `--bg-primary`, `--text-primary`, `--color-primary`, `--border-color`, `--radius-lg`) so your plugin respects the user's theme.

### Event Bus

The event bus enables communication between plugins and WIMI components.

```javascript
// Subscribe
var unsub = window.eventBus.on('plugin:loaded', function(data) {
    console.log('Plugin loaded:', data.id);
});

// Subscribe once
window.eventBus.once('some-event', function(data) { /* ... */ });

// Emit
window.eventBus.emit('my-plugin:data-updated', { count: 42 });

// Unsubscribe
unsub();
// or: window.eventBus.off('plugin:loaded', handler);
```

Built-in events:

| Event | Payload | When |
|-------|---------|------|
| `plugin:loaded` | `{ id, name }` | After a plugin is loaded. |
| `plugin:unloaded` | `{ id }` | After a plugin is unloaded. |

Events are also dispatched as `CustomEvent` on `window` with a `wimi:` prefix (e.g. `wimi:plugin:loaded`), accessible via `window.addEventListener('wimi:plugin:loaded', ...)`.

---

## Slots

Slots let you inject HTML into predefined locations in the WIMI UI without writing JavaScript DOM manipulation.
Slot HTML is injected **before** your `frontend.js` runs, so your JS can immediately find and
enhance slot elements (e.g., attach event listeners, populate with data).

Define them in your manifest:

```json
"slots": {
    "landing-after-exams": "<div class='my-widget'><h3>My Widget</h3><p>Content here</p></div>"
}
```

### Available Slots

| Slot Name | Page | Location |
|-----------|------|----------|
| `landing-after-exams` | Dashboard | After the exam cards list. |
| `landing-sidebar` | Dashboard | In the right sidebar area. |
| `entry-before-form` | Question Entry | Before the entry form. |
| `entry-after-form` | Question Entry | After the entry form. |
| `detail-after-content` | Entry Detail | After the entry content. |
| `browser-toolbar-extra` | Entry Browser | After the toolbar. |
| `session-after-cards` | Session Setup | After the session cards. |
| `analytics-extra-charts` | Analytics Dashboard | After the built-in charts. |
| `settings-addon-panels` | Settings | After the addon panels in settings. |
| `plugin-settings-{your-plugin-id}` | Settings | Inside your plugin's own settings panel, after manifest-rendered settings. |

Empty slots are hidden via CSS (`[data-plugin-slot]:empty { display: none; }`).

---

## Settings

Define user-configurable settings in your manifest. WIMI renders the settings UI automatically in **Settings > [Your Plugin Name]**.

```json
"settings": [
    {
        "key": "api_url",
        "type": "text",
        "label": "API URL",
        "description": "The URL of the external service.",
        "default": "https://example.com/api"
    },
    {
        "key": "max_results",
        "type": "number",
        "label": "Max Results",
        "description": "Maximum number of results to display.",
        "default": 10,
        "min": 1,
        "max": 100
    },
    {
        "key": "auto_refresh",
        "type": "toggle",
        "label": "Auto Refresh",
        "description": "Automatically refresh data on page load.",
        "default": true
    },
    {
        "key": "display_mode",
        "type": "select",
        "label": "Display Mode",
        "description": "How to display the data.",
        "default": "compact",
        "options": [
            { "value": "compact", "label": "Compact" },
            { "value": "detailed", "label": "Detailed" },
            { "value": "minimal", "label": "Minimal" }
        ]
    }
]
```

### Setting Types

| Type | Rendered As | Extra Fields |
|------|-------------|--------------|
| `text` | Text input | -- |
| `number` | Number input | `min`, `max` |
| `toggle` | Checkbox | -- |
| `select` | Dropdown | `options` (array of `{value, label}`) |

### Custom Settings UI

For settings that go beyond the built-in types (e.g., CRUD lists, per-exam configuration),
you can inject custom HTML into your plugin's settings panel using the
`plugin-settings-{your-plugin-id}` slot. This places your custom UI inside the same
settings panel as your manifest-rendered settings.

```json
{
    "id": "my-plugin",
    "name": "My Plugin",
    "version": "1.0.0",
    "slots": {
        "plugin-settings-my-plugin": "<div id='my-plugin-custom-cfg'><p>Loading...</p></div>"
    },
    "frontend_js": "frontend.js"
}
```

Your `frontend.js` can then populate the container dynamically. Note that
the slot element is created by the Settings page **after** your plugin JS loads,
so you must listen for the `wimi:plugin-settings-ready` event:

```javascript
(function() {
    'use strict';

    function initCustomSettings() {
        var el = document.getElementById('my-plugin-custom-cfg');
        if (!el) return;
        // Build your custom settings UI here
        el.innerHTML = '<label>Custom config: <input type="text" id="my-field"></label>';
    }

    // The slot element doesn't exist when this script first runs.
    // Wait for the settings page to create it.
    window.addEventListener('wimi:plugin-settings-ready', initCustomSettings);
})();
```

Notes:
- The `wimi:plugin-settings-ready` event fires on the Settings page after all
  plugin settings panels and their slot elements are created. It only fires on
  the Settings page.
- Plugins with **only** a custom settings slot (no manifest `settings` array) will
  still get a sidebar nav item and their own settings panel.
- You can combine manifest settings with a custom slot -- the custom HTML appears
  below the auto-rendered settings controls.
- Use `api.callPlugin()` to persist custom settings via your backend's
  `api.set_data()` / `api.get_data()` methods.

### Reading Settings

**Backend (Python):**
```python
settings = self.api.get_settings()
url = settings.get('api_url', 'https://default.com')
```

**Frontend (JavaScript):**
```javascript
var settings = await api.getPluginSettings('my-plugin');
console.log(settings.api_url);
```

---

## Complete Example: Study Stats Plugin

A full plugin with backend logic, frontend UI, settings, and a slot widget.

### File Structure
```
study-stats/
  manifest.json
  backend.py
  frontend.js
  styles.css
```

### manifest.json
```json
{
    "id": "study-stats",
    "name": "Study Stats",
    "version": "1.0.0",
    "description": "Shows a daily study summary on the dashboard.",
    "author": "WIMI Community",
    "permissions": ["read"],
    "backend": "backend.py",
    "frontend_js": "frontend.js",
    "frontend_css": "styles.css",
    "slots": {
        "landing-sidebar": "<div id='study-stats-widget'></div>"
    },
    "settings": [
        {
            "key": "days_to_show",
            "type": "number",
            "label": "Days to Show",
            "description": "Number of recent days to include in the summary.",
            "default": 7,
            "min": 1,
            "max": 30
        }
    ]
}
```

### backend.py
```python
class StudyStats:
    def __init__(self, api):
        self.api = api

    def get_summary(self):
        settings = self.api.get_settings()
        days = settings.get('days_to_show', 7)

        streak = self.api.get_streak()
        overview = self.api.get_overview()

        return {
            'current_streak': streak.get('current_streak', 0),
            'total_entries': overview.get('total_entries', 0),
            'days_shown': days,
        }

def create_plugin(api):
    return StudyStats(api)
```

### frontend.js
```javascript
(function() {
    'use strict';

    (async function() {
        await api.ready();

        var container = document.getElementById('study-stats-widget');
        if (!container) return;

        try {
            var data = await api.callPlugin('study-stats', 'get_summary');
            container.innerHTML =
                '<div class="study-stats-card">' +
                    '<h4>Study Stats</h4>' +
                    '<p>Streak: ' + data.current_streak + ' days</p>' +
                    '<p>Total entries: ' + data.total_entries + '</p>' +
                '</div>';
        } catch (e) {
            console.error('Study Stats plugin error:', e);
        }
    })();
})();
```

### styles.css
```css
.study-stats-card {
    padding: 1rem;
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
}

.study-stats-card h4 {
    margin: 0 0 0.5rem;
    color: var(--text-primary);
    font-size: var(--font-size-md);
}

.study-stats-card p {
    margin: 0.25rem 0;
    color: var(--text-secondary);
    font-size: var(--font-size-sm);
}
```

---

## Distribution

Plugins are distributed as `.zip` files. Users install them via **Settings > Addons > Install from .zip**.

### Packaging

Zip your plugin folder:

```bash
cd app_data/plugins/
zip -r study-stats.zip study-stats/
```

The zip can contain either:
- `manifest.json` at the zip root (flat structure)
- A single top-level directory containing `manifest.json` (nested structure)

Both are accepted by the installer.

### What Happens on Install

1. WIMI validates the zip (rejects path traversal attempts like `../`)
2. Extracts to a temp directory and validates the manifest
3. If a plugin with the same ID exists, it is replaced automatically
4. Copies to `app_data/plugins/<plugin-id>/`
5. Discovers and loads the plugin immediately (no restart needed)

### What Happens on Uninstall

1. Plugin is unloaded (backend `on_unload()` is called if defined)
2. Plugin directory is deleted
3. All plugin data in the database is cleared (private storage, settings, enabled state)

---

## Development Tips

### Testing During Development

1. Place your plugin folder directly in `app_data/plugins/`
2. Run WIMI in dev mode: `python run_wimi.py`
3. Press **F5** to reload pages after making frontend changes
4. Press **F12** to open dev tools for JavaScript debugging
5. Toggle your plugin on/off in **Settings > Addons**

### Theme Compatibility

Always use CSS custom properties instead of hardcoded colors:

| Property | Usage |
|----------|-------|
| `--bg-primary` | Main background |
| `--bg-secondary` | Sidebar/card background |
| `--bg-tertiary` | Nested element background |
| `--text-primary` | Main text |
| `--text-secondary` | Muted text |
| `--text-muted` | Subtle text |
| `--border-color` | Borders |
| `--color-primary` | Accent/brand color |
| `--color-primary-bg` | Light accent background |
| `--color-primary-hover` | Accent hover state |
| `--color-success` | Success state |
| `--color-warning` | Warning state |
| `--color-error` | Error/danger state |
| `--radius-sm` / `--radius-md` / `--radius-lg` / `--radius-xl` | Border radius |
| `--shadow-sm` / `--shadow-md` / `--shadow-lg` | Box shadows |
| `--font-size-xs` through `--font-size-xl` | Font sizes |

### Avoiding Conflicts

- Prefix all CSS class names with your plugin ID (e.g. `.study-stats-card`)
- Wrap frontend JS in an IIFE to avoid polluting the global scope
- Use unique event names on the event bus (e.g. `study-stats:updated`)

### Backend Lifecycle

- `create_plugin(api)` is called once when the plugin is enabled/loaded
- `on_unload()` (optional) is called when the plugin is disabled or uninstalled
- The plugin instance lives for the duration of the WIMI session
- State stored via `api.set_data()` persists across app restarts

### Error Handling

- Backend exceptions in `callPlugin` are caught and returned as error responses to the frontend
- Frontend errors in plugin JS are logged to the console but do not crash WIMI
- Invalid manifests are skipped during discovery with a warning log

### Manifest Validation Rules

| Field | Rule |
|-------|------|
| `id` | `/^[a-zA-Z0-9_-]{1,64}$/` |
| `name` | Non-empty, max 128 chars |
| `version` | `/^\d+\.\d+\.\d+$/` |
| `min_app_version` | Same format as version, optional |
| `permissions` | Array of valid permission strings |
| `settings[].key` | Required, non-empty |
| `settings[].type` | One of: `text`, `number`, `toggle`, `select` |
| `settings[].label` | Required, non-empty |
