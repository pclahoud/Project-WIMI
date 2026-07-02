# Addon System — Layer 3: Frontend Extension Points

## Goal
Add a plugin manifest system, event bus, UI injection slots, and split `api.js` into domain modules. Enable frontend plugins to add UI, react to events, and call plugin backend methods.

## Current State
- `api.js`: 2,111 lines, 115+ functions, loaded on every page via `<script>` tag
- 39 JS files, 10 HTML pages, 26 CSS files
- No module bundler — vanilla JS with script tag loading order
- Communication: direct DOM manipulation, callback-based components, global state objects
- No event bus or pub/sub system
- Reusable components exist: `SubjectSearchSelect`, `CustomSelect`, chart classes

## Target Structure

```
src/web/
  js/
    api.js                      # slim re-export for backward compat (~50 lines)
    api/
      index.js                  # aggregates all domain APIs into window.api
      _bridge.js                # WebChannel connection + base call helper
      exam_contexts.js          # exam context API calls
      hierarchy.js              # subject hierarchy + weights
      aliases.js                # subject aliases
      sessions.js               # review session CRUD
      timer.js                  # timer round operations
      entries.js                # question entry CRUD + search
      notes.js                  # entry notes
      media.js                  # media management
      sources.js                # question sources
      tags.js                   # tag operations
      analytics.js              # analytics + goals
      dimensions.js             # dimension operations + analytics
      import_export.js          # import/export + delimiters + mappings
      settings.js               # preferences
      filters.js                # filter data (sessions, subjects, tags)
      utility.js                # connection check, app info, clipboard, docs
      plugins.js                # callPlugin() wrapper
    event_bus.js                # WimiEvents pub/sub system
    plugin_loader.js            # Plugin manifest scanner and loader
    ... (existing files unchanged)
  plugins/                      # Plugin directory (scanned at load)
    README.md                   # Plugin development guide
```

## Component 1: Event Bus (`event_bus.js`)

A lightweight pub/sub system for decoupled communication:

```javascript
/**
 * WimiEvents — application-wide event bus.
 * Core code emits events; plugins (and other core code) subscribe.
 */
const WimiEvents = {
    _listeners: {},

    on(event, callback, context) {
        if (!this._listeners[event]) this._listeners[event] = [];
        this._listeners[event].push({ callback, context });
        // Return unsubscribe function
        return () => this.off(event, callback);
    },

    off(event, callback) {
        if (!this._listeners[event]) return;
        this._listeners[event] = this._listeners[event]
            .filter(l => l.callback !== callback);
    },

    emit(event, data) {
        if (!this._listeners[event]) return;
        for (const listener of this._listeners[event]) {
            try {
                listener.callback.call(listener.context, data);
            } catch (e) {
                console.error(`WimiEvents [${event}] handler error:`, e);
            }
        }
    },

    // One-time listener
    once(event, callback) {
        const unsub = this.on(event, (data) => {
            unsub();
            callback(data);
        });
        return unsub;
    }
};
```

### Core Events to Emit

| Event | Data | Emitted From |
|-------|------|-------------|
| `app:ready` | `{ examId }` | api.js (after WebChannel connect) |
| `page:loaded` | `{ page, params }` | each page controller's init |
| `entry:saved` | `{ entryId, sessionId, isNew }` | question_entry.js |
| `entry:deleted` | `{ entryId, sessionId }` | entry_browser.js, entry_detail.js |
| `session:created` | `{ sessionId, examId }` | session_setup.js |
| `session:deleted` | `{ sessionId }` | session_setup.js |
| `timer:started` | `{ roundId, sessionId, duration }` | question_entry.js |
| `timer:paused` | `{ roundId }` | question_entry.js |
| `timer:resumed` | `{ roundId }` | question_entry.js |
| `timer:ended` | `{ roundId, studiedSeconds }` | question_entry.js |
| `timer:round_deleted` | `{ roundId, sessionId }` | session_setup.js |
| `subject:created` | `{ nodeId, examId }` | tree_editor.js |
| `subject:deleted` | `{ nodeId }` | tree_editor.js |
| `settings:changed` | `{ key, value }` | settings.js |
| `theme:changed` | `{ themeName, colors }` | settings.js |

## Component 2: UI Injection Slots

HTML pages define named extension points where plugins can inject content:

```html
<!-- data-plugin-slot attributes in HTML pages -->
<div data-plugin-slot="entry-header"></div>
<div data-plugin-slot="entry-footer"></div>
<div data-plugin-slot="session-sidebar"></div>
<div data-plugin-slot="analytics-extra-charts"></div>
<div data-plugin-slot="browser-toolbar"></div>
<div data-plugin-slot="settings-panels"></div>
<div data-plugin-slot="landing-widgets"></div>
```

### Slot Locations Per Page

| Page | Slot Name | Position |
|------|-----------|----------|
| question_entry.html | `entry-header` | After timer, before form |
| question_entry.html | `entry-footer` | After form sections |
| session_setup.html | `session-sidebar` | Right column of session cards |
| analytics_dashboard.html | `analytics-extra-charts` | After built-in chart sections |
| entry_browser.html | `browser-toolbar` | After filter bar |
| settings.html | `settings-panels` | After built-in settings panels |
| index.html | `landing-widgets` | After exam grid |

## Component 3: Plugin Manifest & Loader

### Manifest Format (`plugin.json`)

```json
{
    "id": "spaced-repetition",
    "name": "Spaced Repetition",
    "version": "1.0.0",
    "description": "SRS scheduling for review entries",
    "slots": {
        "entry-footer": "widgets/review-schedule.html",
        "settings-panels": "widgets/sr-settings.html"
    },
    "scripts": ["js/main.js"],
    "styles": ["css/style.css"],
    "events": ["entry:saved", "timer:ended"],
    "requires_backend": true
}
```

### Plugin Loader (`plugin_loader.js`)

```javascript
const PluginLoader = {
    plugins: {},

    async loadAll() {
        // Bridge provides list of discovered plugins
        const manifests = await api.getRegisteredPlugins();
        for (const manifest of manifests) {
            await this.loadPlugin(manifest);
        }
    },

    async loadPlugin(manifest) {
        // 1. Inject CSS
        for (const css of manifest.styles || []) {
            const link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = `../plugins/${manifest.id}/${css}`;
            document.head.appendChild(link);
        }

        // 2. Inject slot content
        for (const [slotName, htmlPath] of Object.entries(manifest.slots || {})) {
            const slot = document.querySelector(`[data-plugin-slot="${slotName}"]`);
            if (slot) {
                const resp = await fetch(`../plugins/${manifest.id}/${htmlPath}`);
                slot.innerHTML += await resp.text();
            }
        }

        // 3. Load scripts
        for (const js of manifest.scripts || []) {
            await this.loadScript(`../plugins/${manifest.id}/${js}`);
        }

        this.plugins[manifest.id] = manifest;
    },

    loadScript(src) {
        return new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = src;
            script.onload = resolve;
            script.onerror = reject;
            document.body.appendChild(script);
        });
    }
};
```

## Component 4: Plugin API Wrapper (`api/plugins.js`)

```javascript
/**
 * Call a backend plugin method through the generic dispatch slot.
 */
async function callPlugin(pluginId, method, args = {}) {
    const payload = JSON.stringify({ method, args });
    const result = await callBridge('callPlugin', pluginId, payload);
    return JSON.parse(result);
}
```

## Component 5: api.js Domain Split

### Migration Strategy (Backward Compatible)

1. **Create `api/_bridge.js`** — extract WebChannel connection logic
2. **Create domain files** — each exports functions that call `_bridge.callBridge()`
3. **Create `api/index.js`** — imports all domains, attaches to `window.api`
4. **Keep `api.js`** as a thin wrapper that loads `api/index.js` (or just becomes `api/index.js`)

Since there's no module bundler, we use the script-tag-order pattern:

```html
<!-- New loading order -->
<script src="../js/api/_bridge.js"></script>
<script src="../js/api/exam_contexts.js"></script>
<script src="../js/api/sessions.js"></script>
<!-- ... other domain files ... -->
<script src="../js/api/plugins.js"></script>
<script src="../js/api/index.js"></script>  <!-- assembles window.api -->
```

Each domain file adds methods to a namespace:

```javascript
// api/sessions.js
(function(api) {
    api.createReviewSession = async function(params) { ... };
    api.getReviewSessions = async function(examId, includeDeleted) { ... };
    // ...
})(window._apiBuilder = window._apiBuilder || {});
```

Then `api/index.js` does:
```javascript
window.api = window._apiBuilder;
window.api.ready = function() { return bridgeReady; };
delete window._apiBuilder;
```

**Alternative (simpler):** Keep `api.js` as a single file but add `api/plugins.js` as the only new file. Split is optional polish.

## Execution Steps

1. **Create `event_bus.js`** — standalone, no dependencies
2. **Add event emissions to core JS** — `entry:saved`, `session:created`, etc. in existing page controllers
3. **Add `data-plugin-slot` divs** to HTML pages (non-breaking — empty divs)
4. **Create `api/plugins.js`** — `callPlugin()` wrapper (depends on Layer 2 `callPlugin` slot)
5. **Create `plugin_loader.js`** — manifest scanner and loader
6. **Split `api.js` into domain modules** (optional, can defer)
7. **Create example plugin** to validate the full stack

## Dependencies on Other Layers

| Frontend Component | Depends On |
|--------------------|------------|
| `callPlugin()` | Layer 2: `PluginDispatchMixin.callPlugin` slot |
| Plugin loader | Layer 2: `getRegisteredPlugins` slot (new) |
| Event bus | Independent — no backend dependency |
| UI slots | Independent — pure HTML |
| api.js split | Independent — pure refactor |

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Script loading order breaks | Keep `api.js` as fallback; split is additive |
| Plugin CSS conflicts with core styles | Namespace plugin CSS with `[data-plugin="id"]` selectors |
| Plugin slot content breaks page layout | Slots are flex containers with `overflow: hidden` |
| Event bus memory leaks | `once()` for one-shots; plugins must `off()` on unload |
| No module bundler for tree-shaking | IIFE pattern keeps global scope clean enough |
| Plugin fetch fails in frozen mode | Plugin assets must be copied to `_internal/web/plugins/` during build |

## Validation Criteria

- Event bus works: subscribe → emit → callback fires
- Plugin slots render injected HTML on all 7 pages
- `callPlugin()` round-trips to backend and back
- Existing app behavior completely unchanged when no plugins installed
- Example plugin loads, renders UI, handles events, calls backend
