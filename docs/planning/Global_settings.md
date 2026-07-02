╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌ Global Settings Page

 Context

 WIMI has a fully defined UserPreferences dataclass (20+ fields) and database methods (get_preferences,
 update_preferences) but zero UI exposure — no bridge methods, no JavaScript API, no settings page, no menu item.
 The SQL user_preferences table is also missing ~12 columns that the dataclass defines (e.g., primary_color_hex,
 font_family, ui_density). This plan adds a complete settings page with live preview, backed by a schema
 migration.

 Goal: Expose all user preferences through a web-based settings page with categorized sidebar navigation, live CSS
  preview for visual settings, and save/cancel workflow.

 ---
 Files to Create
 ┌────────────────────────────┬─────────────────────────────────────────────┐
 │            File            │                   Purpose                   │
 ├────────────────────────────┼─────────────────────────────────────────────┤
 │ src/web/html/settings.html │ Settings page with 8 categorized panels     │
 ├────────────────────────────┼─────────────────────────────────────────────┤
 │ src/web/css/settings.css   │ Layout, sidebar nav, form styling, toasts   │
 ├────────────────────────────┼─────────────────────────────────────────────┤
 │ src/web/js/settings.js     │ State management, live preview, save/cancel │
 └────────────────────────────┴─────────────────────────────────────────────┘
 Files to Modify
 File: src/database/user_db.py
 Change: Add _ensure_preferences_columns() migration (~line 157)
 ────────────────────────────────────────
 File: src/app/bridge.py
 Change: Add getUserPreferences() and updateUserPreferences() slots (~line 4997)
 ────────────────────────────────────────
 File: src/web/js/api.js
 Change: Add getUserPreferences(), updateUserPreferences(), and global applyUserSettings() (~line 1960)
 ────────────────────────────────────────
 File: src/app/main_window.py
 Change: Add "Settings..." menu item to File menu (~line 242)
 ---
 Step 1: Schema Migration — user_db.py

 Add _ensure_preferences_columns() method, called from _ensure_phase1_schema() at line 157 (after
 _ensure_subject_aliases_table()). Uses the established pattern: PRAGMA table_info → check column names → ALTER
 TABLE ADD COLUMN.

 Columns to add (missing from SQL but present in dataclass):

 migration_columns = [
     ("primary_color_hex", "VARCHAR(7) DEFAULT '#2196F3'"),
     ("secondary_color_hex", "VARCHAR(7) DEFAULT '#FFC107'"),
     ("font_family", "VARCHAR(50) DEFAULT 'system'"),
     ("ui_density", "VARCHAR(20) DEFAULT 'comfortable'"),
     ("manual_break_control", "BOOLEAN DEFAULT TRUE"),
     ("analytics_detail_level", "VARCHAR(20) DEFAULT 'detailed'"),
     ("show_performance_trends", "BOOLEAN DEFAULT TRUE"),
     ("show_mistake_patterns", "BOOLEAN DEFAULT TRUE"),
     ("show_subject_breakdown", "BOOLEAN DEFAULT TRUE"),
     ("show_time_analytics", "BOOLEAN DEFAULT TRUE"),
     ("show_weekend_in_calendar", "BOOLEAN DEFAULT TRUE"),
     ("anki_integration_enabled", "BOOLEAN DEFAULT FALSE"),
     ("auto_backup_enabled", "BOOLEAN DEFAULT TRUE"),
     ("cloud_sync_enabled", "BOOLEAN DEFAULT FALSE"),
     ("entry_review_default_sort_field", "VARCHAR(50) DEFAULT 'answered_incorrectly_date'"),
     ("entry_review_default_sort_direction", "VARCHAR(10) DEFAULT 'desc'"),
 ]

 Note: The SQL also has columns with different names than the dataclass (ankiconnect_enabled vs
 anki_integration_enabled, show_progress_graphs vs show_performance_trends, entry_review_default_sort vs split
 fields). The migration adds the dataclass-named columns alongside the old ones. The from_db_row() already uses
 .get() with the dataclass field names, so new columns will be picked up and old ones ignored gracefully.

 Also add validation entries for new fields in update_preferences():
 - ui_density: must be in ['compact', 'comfortable', 'spacious']
 - analytics_detail_level: must be in ['summary', 'detailed', 'advanced']

 ---
 Step 2: Bridge Methods — bridge.py

 Add after the Saved Delimiters section (~line 4997), before Utility Operations:

 getUserPreferences (@pyqtSlot(result=str))

 - Call self.user_db.get_preferences()
 - Convert result with asdict(prefs) (already imported)
 - Remove created_at/updated_at from response (not needed in UI)
 - Return via serialize_response(True, data=prefs_dict)

 updateUserPreferences (@pyqtSlot(str, result=str))

 - Parse JSON params
 - Call self.user_db.update_preferences(**params)
 - Return updated prefs via serialize_response()
 - Catch ValidationError separately for clean error messages

 ---
 Step 3: JavaScript API — api.js

 Add before the Utility Operations section (~line 1948):

 // =========================================================================
 // User Preferences
 // =========================================================================

 async getUserPreferences() {
     return this._callBridge('getUserPreferences');
 }

 async updateUserPreferences(preferences) {
     return this._callBridge('updateUserPreferences', JSON.stringify(preferences));
 }

 Add global settings application after the window.api = api line (~line 1968):

 /**
  * Apply persisted visual settings on every page load.
  * Listens for wimi:ready event, calls getUserPreferences,
  * sets CSS variables on document.documentElement.
  */
 window.addEventListener('wimi:ready', async () => {
     try {
         const prefs = await api.getUserPreferences();
         // Apply primary/secondary colors, font family, font size scale,
         // ui density, animations toggle via CSS custom properties
         window.wimiPreferences = prefs;  // Available to page scripts
     } catch (e) {
         console.warn('Settings load failed:', e);
     }
 });

 This runs on every page load, applying visual preferences globally.

 ---
 Step 4: Menu Item — main_window.py

 In _setup_menu_bar() at line 242, before the exit separator:

 settings_action = QAction('&Settings...', self)
 settings_action.setShortcut(QKeySequence('Ctrl+,'))
 settings_action.triggered.connect(lambda: self.load_page('settings.html'))
 file_menu.addAction(settings_action)

 file_menu.addSeparator()

 ---
 Step 5: Settings Page UI — settings.html

 Standard WIMI page boilerplate (styles.css + settings.css + qwebchannel.js + api.js + settings.js).

 Layout: Header with back link + title, then a 2-column container:
 - Left sidebar (280px): 8 nav buttons with icons
 - Right main area: Panel per category, only active one visible

 Sticky actions bar at top of main area (hidden until dirty): "You have unsaved changes" + Cancel / Save buttons.

 Settings Categories & Fields
 ┌────────────────┬─────────────────────────────────────────────────────────────────────────┬────────────────────┐
 │    Category    │                                 Fields                                  │    Input Types     │
 ├────────────────┼─────────────────────────────────────────────────────────────────────────┼────────────────────┤
 │                │ theme_name, primary_color_hex, secondary_color_hex, font_family,        │ select,            │
 │ Appearance     │ font_size_scale, ui_density, show_animations                            │ color+text, range, │
 │                │                                                                         │  checkbox          │
 ├────────────────┼─────────────────────────────────────────────────────────────────────────┼────────────────────┤
 │ Study Sessions │ default_session_duration_minutes, default_break_interval_minutes,       │ number, checkbox   │
 │                │ default_long_break_minutes, manual_break_control                        │                    │
 ├────────────────┼─────────────────────────────────────────────────────────────────────────┼────────────────────┤
 │ Dashboard &    │ analytics_detail_level, dashboard_auto_refresh_seconds,                 │ select, number,    │
 │ Analytics      │ show_performance_trends, show_mistake_patterns, show_subject_breakdown, │ checkboxes         │
 │                │  show_time_analytics                                                    │                    │
 ├────────────────┼─────────────────────────────────────────────────────────────────────────┼────────────────────┤
 │ Entry Browser  │ entry_review_items_per_page, entry_review_default_sort_field,           │ number, selects    │
 │                │ entry_review_default_sort_direction                                     │                    │
 ├────────────────┼─────────────────────────────────────────────────────────────────────────┼────────────────────┤
 │ Calendar       │ calendar_default_view, calendar_time_slot_minutes,                      │ selects, checkbox  │
 │                │ show_weekend_in_calendar                                                │                    │
 ├────────────────┼─────────────────────────────────────────────────────────────────────────┼────────────────────┤
 │ Anki           │ anki_integration_enabled, ankiconnect_port                              │ checkbox, number   │
 │ Integration    │                                                                         │                    │
 ├────────────────┼─────────────────────────────────────────────────────────────────────────┼────────────────────┤
 │ Data & Backup  │ auto_backup_enabled, backup_frequency_hours, backup_retention_days,     │ checkboxes,        │
 │                │ cloud_sync_enabled                                                      │ numbers            │
 ├────────────────┼─────────────────────────────────────────────────────────────────────────┼────────────────────┤
 │ Performance    │ realtime_update_delay_ms                                                │ number             │
 └────────────────┴─────────────────────────────────────────────────────────────────────────┴────────────────────┘
 Anki, Data & Backup, and Calendar panels show a "Coming Soon" info notice since those features aren't implemented
  yet. Settings are still persisted for when they are.

 Each input has data-field="column_name" attribute for generic JS binding. Field descriptions below each input
 explain the setting.

 ---
 Step 6: Settings CSS — settings.css

 - Sidebar + main content flex layout
 - Sticky header and actions bar
 - Nav items with active state (left border highlight)
 - Form groups with consistent spacing, labels, descriptions
 - Color picker + hex text input side by side
 - Range slider with custom styling and min/max labels
 - Feature notice box (blue info style)
 - Toast notifications (slide-in from right, auto-dismiss)
 - Responsive: sidebar collapses to horizontal tabs at <1024px

 ---
 Step 7: Settings JS — settings.js

 State Management

 SettingsState = {
     originalPreferences: null,   // Deep copy from load
     currentPreferences: null,    // Tracks live changes
     isDirty: false,
     isSaving: false
 }

 Core Flow

 1. init() → setup nav, input handlers, keyboard shortcuts, load settings
 2. loadSettings() → api.getUserPreferences() → deep copy to original + current → populateForm() →
 applyLivePreview()
 3. Input change → mark dirty, update currentPreferences, trigger live preview for visual fields
 4. Save → compute diff (changed fields only) → api.updateUserPreferences(changes) → update original → clear dirty
 5. Cancel → populateForm(original) → revert CSS variables → clear dirty

 Live Preview (visual fields only)

 - primary_color_hex → set --color-primary, derive --color-primary-hover and --color-primary-bg
 - secondary_color_hex → set --color-secondary
 - font_family → set --font-family via font stack map
 - font_size_scale → set document.documentElement.style.fontSize
 - ui_density → adjust --space-sm/md/lg/xl per density preset
 - show_animations → set transitions to 0ms or remove override

 Cancel reverts by removing all inline style overrides from :root.

 Keyboard Shortcuts

 - Ctrl+S → Save
 - Escape → Cancel

 ---
 Verification

 Automated

 # Run existing preferences tests (they already exist in the DB layer)
 pytest tests/database/test_user_db_phase1.py -v --no-cov -k "preferences"

 # Test migration on fresh + existing databases
 # (manual: create DB, close, reopen — migration should add columns silently)

 Manual Smoke Test

 1. Launch app → File → Settings → verify page loads with defaults
 2. Click through all 8 sidebar categories → verify panels switch
 3. Change primary color → verify buttons on settings page update live
 4. Adjust font size slider → verify text resizes live
 5. Click Cancel → verify everything reverts
 6. Make changes again → Save → verify toast shows success
 7. Navigate to Entry Browser → verify font size / colors persisted
 8. Reopen Settings → verify saved values are loaded
 9. Change items per page → save → go to Entry Browser → verify pagination uses new value

 ---
 Edge Cases

 - No user logged in: Bridge methods return error, settings page shows error toast
 - Schema migration on existing DB: _ensure_preferences_columns() silently adds missing columns with defaults
 - Invalid color input: Validate hex format on blur, revert to picker value if invalid
 - Range out of bounds: Database CHECK constraints + Python validation in update_preferences() catch this; bridge
 returns validation error
 - No changes to save: Show info toast "No settings were modified"
 - Concurrent page navigation while dirty: No unsaved-changes prompt (matches existing app behavior — could add
 later)
╌╌╌╌╌╌╌╌╌╌