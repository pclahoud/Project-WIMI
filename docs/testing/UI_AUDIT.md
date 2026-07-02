# WIMI UI Test Locator Audit

**Status:** Reference (output of pre-implementation audit)
**Created:** 2026-05-07
**Companion plans:** Forthcoming `wimi-test` MCP server & `wimi_test` Python library (regression suite + Claude-driven exploration)

This document is the canonical record of every interactive element across WIMI's 11 HTML pages, the proposed `data-testid` attributes for those that cannot be reliably located by `role + accessible name`, and the cross-cutting issues that affect the testing infrastructure as a whole. It is the audit input that drives the test-id implementation work.

---

## Locator Strategy

Tests drive the QWebEngineView via Chrome DevTools Protocol using `pychrome` (originally specced as Playwright over CDP; see `docs/planning/PYCHROME_MIGRATION.md` for the migration). Locators are chosen in this preference order:

1. **`role + accessible name`** — first choice; survives CSS and class renames.
2. **`data-testid`** — when role+name isn't unique or the element lacks an accessible name (icon-only buttons, custom-select widgets, SVG/Canvas chart elements, dynamic chips without roles).
3. **CSS selector** — last resort, only for one-off cases where no testid exists yet.

Auto-waiting is the default for every action. Tests should never use `time.sleep()`.

## Naming Convention

```
data-testid="<page>-<area>-<element>"
```

- **kebab-case**, lowercase
- **Page prefix** matches the HTML filename minus extension; `index.html` uses `dashboard-`
- **Dynamic element suffixes** include the entity ID, e.g. `browser-row-42`, `tree-node-17`
- **Polyhierarchy-aware** patterns include parent context where the same node may be rendered under multiple parents: `tree-node-{nodeId}-under-{parentId}` (forward-looking, see `POLYHIERARCHY_MIGRATION.md`)

| Page | Prefix |
|---|---|
| `index.html` | `dashboard-` |
| `question_entry.html` | `entry-form-` |
| `analytics_dashboard.html` | `analytics-` |
| `entry_browser.html` | `browser-` |
| `entry_detail.html` | `detail-` |
| `tree_editor.html` | `tree-` |
| `session_setup.html` | `session-` |
| `settings.html` | `settings-` |
| `wizards/exam_wizard.html` | `wizard-` |
| `error-viewer.html` | `error-viewer-` |
| `subject_deep_dive.html` | `deep-dive-` |

---

## Cross-Cutting Issues

These themes recurred across pages and inform the implementation order.

### 1. No `data-testid` attributes exist anywhere today
Verified by grep across the codebase. This is a green field — every testid added is net new.

### 2. D3.js / SVG charts need testids added at render time
SVG `<path>`, `<rect>`, `<text>` elements rendered by D3 (sunburst arcs, heatmap cells, tree nodes, cross-dimension matrix) cannot be reached by role+name. Each render function needs `.attr('data-testid', d => ...)` inserted inline. Affected files:
- `src/web/js/sunburst_chart.js` — sunburst arcs and labels
- `src/web/js/heatmap_chart.js` — activity heatmap cells, day/month labels
- `src/web/js/dimension_heatmap.js` — cross-dimension cells, row/column headers, count overlays
- `src/web/js/tree_editor.js` — `renderNode()` recursive tree rendering

### 3. Canvas charts cannot be selected
HTML Canvas (`#tagChart` donut, `#activityChart` line, `#timelineChart` on deep-dive) draws to pixels. No DOM elements to target.
**Mitigation:** test via the HTML legend (which is selectable), via tooltip text on hover, or — if pixel-level testing is needed — add a transparent SVG overlay with click regions. For most assertions, testing the legend + the data-bound state is sufficient.

### 4. Custom select widgets lack standard ARIA
The `CustomSelect` class in `src/web/js/custom-select.js` produces div-based dropdowns without `role="combobox"`/`role="listbox"`/`role="option"`. Affected pages: dashboard exam filter, session source selector, browser sort, wizard weight precision/algorithm, settings analytics dimension. Each instance needs a testid on the trigger and the options container.

### 5. Rich text editors (TinyMCE/Quill) are opaque
Reflection, explanation, and per-note editors render iframes or sandboxed content. Tests should use the parent container's testid plus the editor's exposed `getContent()` method, not internal DOM queries.

### 6. Modals lack `role="dialog"` / `aria-labelledby`
Almost every modal across the app uses `<div class="modal-backdrop">` with class-toggling for visibility, no semantic dialog role, no focus trap, no `aria-labelledby`. The testid migration is a natural moment to add semantic dialog markup.

### 7. Dynamic chips (subjects, tags) have no role
`.chip` divs are created via `innerHTML` for subject tags, tag chips, and similar. They need testids with ID suffixes (`entry-form-subject-primary-chip-{id}`, etc.) since accessibility-name locators won't work on bare divs.

### 8. Native `confirm()` dialogs are used for several "delete?" prompts
Settings page reset, plugin uninstall, and a few others use `window.confirm()`. (Originally these could be auto-handled by Playwright via `page.on("dialog")`; under pychrome there is no such auto-handler and the in-app `setTestModeAutoDismiss(True)` bridge slot is used instead — see `docs/planning/PYCHROME_MIGRATION.md`.) Consider replacing with HTML modals.

### 9. Inline `onclick=` handlers are common
Especially on the dashboard's exam cards. Functional but a code smell and harder to evolve. Doesn't block testing — testids work either way — but worth knowing.

---

## Per-Page Audits

The remaining sections are the verbatim audit findings, one section per page. Each follows the same structure: file paths, page purpose, static elements, dynamic elements, modals, page modes, and notes. Together these define the full work item for the testid migration.

---

## index.html (dashboard)

**File:** `src/web/html/index.html`
**Companion JS:** `src/web/js/landing.js`, `src/web/js/analytics_preview.js`
**Page purpose:** Landing/dashboard with analytics preview, exam cards grid, and system status indicators.

### Static interactive elements

| Element | Current ID/label | Locatable by role+name? | Proposed testid |
|---|---|---|---|
| Settings gear link | `settings-gear-link`, `title="Settings"` | yes | none |
| "Create New Exam" link | text "+ Create New Exam" | yes | none |
| "Create Your First Exam" link (empty state) | text | yes | none |
| Suspend modal backdrop | `#delete-modal` | no | `dashboard-suspend-modal-backdrop` |
| Suspend modal container | `.modal` inside `#delete-modal` | no | `dashboard-suspend-modal` |
| Cancel button (modal) | `#delete-cancel`, text "Cancel" | yes | none |
| Confirm Suspend button | `#delete-confirm`, text "Suspend" | yes | none |
| Exam name display in modal | `#delete-exam-name` (dynamic content) | no | `dashboard-suspend-modal-exam-name` |

### Dynamic elements (JS-inserted)

| Element | Created in | Testid pattern |
|---|---|---|
| Analytics preview widget container | `landing.js:14` | `#analytics-preview-container` (existing) |
| Exam cards grid | `landing.js:428-429` | `dashboard-exam-card-{examId}` |
| Exam card "New Review Session" | `landing.js:324` | `dashboard-exam-{examId}-new-session-btn` |
| Exam card secondary buttons (Browse / Analytics / Subjects) | `landing.js:330-338` | `dashboard-exam-{examId}-browse-btn`, `dashboard-exam-{examId}-analytics-btn`, `dashboard-exam-{examId}-subjects-btn` |
| Exam card utility buttons (Edit / Suspend / Reactivate / Delete) | `landing.js:255-270` | `dashboard-exam-{examId}-edit-btn`, `dashboard-exam-{examId}-suspend-btn`, `dashboard-exam-{examId}-reactivate-btn`, `dashboard-exam-{examId}-delete-btn` |
| Analytics exam filter dropdown (CustomSelect) | `analytics_preview.js:396-405` | `dashboard-analytics-exam-filter`, trigger: `dashboard-analytics-exam-filter-trigger` |
| Analytics dropdown options | `analytics_preview.js:378, 389` | locate by `role="option"` + `data-value` |
| "View Full Report" button | `analytics_preview.js:477` | `dashboard-analytics-report-link` |
| API/DB/Version status indicators | `landing.js:512-533` | `dashboard-status-api`, `dashboard-status-db`, `dashboard-status-version` |
| Toast container | `landing.js:43-46` | locate by `.toast` class + text content |
| Empty / loading skeleton states | `landing.js:360-386` | located by class (transient) |

### Modals / popovers

- **Suspend Exam Modal** (`#delete-modal`): backdrop, container, title, exam-name display, Cancel and Suspend buttons. Closes via backdrop click, Cancel, or ESC.
- **Analytics filter dropdown**: `.custom-select.analytics-exam-select` with `role="combobox"`/`role="listbox"`/`role="option"` (already accessible).

### Page modes

- **Loading** — 3 skeleton cards in grid, skeleton stat cards in analytics preview.
- **Empty** — single "No Exams Yet" card with CTA.
- **Normal** — populated grid + populated analytics preview.
- **Suspended** — exam card has 0.6 opacity + grayscale, shows Reactivate/Delete instead of Edit/Suspend.
- **Modal open** — backdrop visible, body overflow hidden.
- **Dropdown open** — `.open` class on trigger; `aria-expanded="true"`.

### Notes

Inline `onclick` handlers (`startNewSession`, `editExam`, etc.) are exposed as globals on `window` (`landing.js:568-575`). No event delegation. Testids on the buttons themselves are still the right approach.

---

## question_entry.html

**File:** `src/web/html/question_entry.html`
**Companion JS:** `question_entry.js`, `media_upload.js`, `rich_editor.js`, `image_browser.js`
**Page purpose:** Multi-section question entry form with rich text editors, subject/tag selection, multi-note cards, and media attachment.

### Static interactive elements

| Element | Current ID | Locatable by role+name? | Proposed testid |
|---|---|---|---|
| Back button | `btn-back` | yes | `entry-form-back-button` |
| Session name heading | `session-name` | yes | `entry-form-session-name` |
| Exam badge | `exam-badge` | no | `entry-form-exam-badge` |
| Entry counter | `entry-counter` | no | `entry-form-entry-counter` |
| Timer display | `timer-display` | no | `entry-form-timer-display` |
| Timer pause / new round buttons | `btn-timer-pause`, `btn-new-round` | yes | `entry-form-timer-pause-button`, `entry-form-timer-new-round-button` |
| Add entries | `btn-add-entries` | yes | `entry-form-add-entries-button` |
| Auto-save indicator | `auto-save-indicator` | no | `entry-form-auto-save-indicator` |
| Previous / Next entry | `btn-prev-entry`, `btn-next-entry` | yes | `entry-form-nav-previous-button`, `entry-form-nav-next-button` |
| Question ID input | `question-id` | yes | `entry-form-question-id-input` |
| User answer / Correct answer textareas | `user-answer`, `correct-answer` | yes | `entry-form-user-answer-textarea`, `entry-form-correct-answer-textarea` |
| Time spent / Time unit | `time-spent`, `time-unit` | yes | `entry-form-time-spent-input`, `entry-form-time-unit-select` |
| Primary / Secondary subject search | `primary-subject-search`, `secondary-subject-search` | yes | `entry-form-subject-primary-search`, `entry-form-subject-secondary-search` |
| Tag search | `tag-search` | yes | `entry-form-tags-search-input` |
| Add note | `btn-add-note` | yes | `entry-form-notes-add-button` |
| Save Draft / Save & Next | `btn-save-draft`, `btn-save-next` | yes | `entry-form-save-draft-button`, `entry-form-save-next-button` |
| Section A–F headers | `section-*-header` | yes (button role + aria-expanded) | `entry-form-section-{letter}-toggle` |
| Section panels | `section-*-content` | partial | `entry-form-section-{letter}-content` |
| Quick add subject | `btn-quick-add-subject` | yes | `entry-form-subject-add-quick-button` |
| Reflection / Explanation editor containers | `reflection-editor`, `explanation-editor` | no (Quill iframe) | `entry-form-reflection-editor`, `entry-form-explanation-editor` |
| Notes list container | `notes-list-container` | no | `entry-form-notes-list` |
| Media upload container | `media-upload-container` | no | `entry-form-media-upload` |

### Dynamic elements (JS-inserted)

| Element | Created in | Testid pattern |
|---|---|---|
| Difficulty rating dots (1–5) | `question_entry.js:114-118, 346` | locate by `aria-label` ("Very Easy", etc.) or `.difficulty-dot[data-value="{N}"]` |
| Subject chips (primary/secondary) | `question_entry.js:824-835` | `entry-form-subject-primary-chip-{id}`, `entry-form-subject-secondary-chip-{id}` |
| Subject dropdown options | `question_entry.js:504-559` | `entry-form-subject-option-{type}-{id}` |
| Tag chips | `question_entry.js:1501-1515` | `entry-form-tags-chip-{id}` |
| Tag dropdown options | `question_entry.js:1242-1400+` | `entry-form-tags-option-{id}` |
| Entry navigation dots | `question_entry.js:1928-1944` | `entry-form-nav-dot-{index}` |
| Note cards | `question_entry.js:2619-2700` | `entry-form-note-card-{tempId}`, plus `-delete-button`, `-subject-button`, `-editor` |
| Note subject chips | `question_entry.js:2712-2725` | `entry-form-note-card-{tempId}-subject-chip-{id}` |
| Image autopopulation prompt | `question_entry.js:673-710` | `entry-form-image-autopopulate-prompt`, `-accept-button`, `-dismiss-button` |
| Toast notifications | `question_entry.js:73-118` | locate by toast class + text (transient) |
| Media dropzone & action buttons | `media_upload.js:78-106` | `entry-form-media-dropzone`, `entry-form-media-browse-button`, `entry-form-media-browse-existing-button` |
| Media thumbnails + actions | `media_upload.js:200+` | `entry-form-media-thumbnail-{mediaId}`, `-fullscreen-button`, `-delete-button` |
| Image browser modal cards | `image_browser.js:204-252` | `entry-form-image-browser-card-{mediaId}` |

### Modals / popovers

| Modal | Trigger | ID | Notable elements |
|---|---|---|---|
| Unsaved changes | navigation before save | `#unsaved-modal` | `entry-form-unsaved-discard-button`, `-save-button`, `-cancel-button` |
| Add entries popover | "+ Add Entries" | `#add-entries-popover` | `entry-form-add-entries-count-input`, `-confirm-button`, `-cancel-button` |
| Quick add subject | "+ Add New Subject" | `#quick-add-subject-modal` | inputs + buttons all prefixed `entry-form-quick-add-` |
| Session complete | last entry saved | `#complete-modal` | `entry-form-complete-review-button`, `-done-button` |
| Round complete overlay | timer round end | `#round-complete-overlay` | break duration input + 3 actions |
| New round dialog | "Start new round" | `#new-round-dialog-overlay` | duration input + Cancel/Start |
| Media full-size view | thumbnail click | `#media-modal` | close button, image, caption |
| Media rename | rename action | `#media-rename-modal` | input + Cancel/Save |
| Media delete confirmation | delete action | `#media-delete-modal` | Unassign / Delete permanent / Cancel |
| Media subject assignment | subject action | `#media-subject-modal` | preview, list, Cancel/Save |
| Image browser modal | "Browse Existing Images" | class-based | search input, grid, Close/Cancel |

### Page modes

- **New entry** — empty form, may have Save & Next disabled.
- **Editing existing** — populated form.
- **Draft** — `#draft-indicator` visible, Save & Next disabled.
- **Valid** — draft indicator hidden, Save & Next enabled.
- **Loading** — skeleton/spinner.
- **Auto-saving** — indicator updates.
- **Timer active** — `#session-timer` visible, display updates per second.

### Notes

- Rich editors are TinyMCE-based — locate via container ID, query content via `RichEditor.getContent()`, do not target internal DOM.
- Custom `Tab` navigation across sections (`initSectionTabNavigation`, `question_entry.js:269`).
- Dynamic chips and dots have no ARIA role; testids are mandatory.
- Media modals are universally hidden via `display: none` toggled by `.active` class.

---

## analytics_dashboard.html

**File:** `src/web/html/analytics_dashboard.html`
**Companion JS:** `analytics_dashboard.js`, `sunburst_chart.js`, `heatmap_chart.js`, `dimension_heatmap.js`, `weight_analysis.js`, `dimension_analytics.js`, `dimension_insights.js`, `streak_display.js`, `goal_widget.js`
**Page purpose:** Multi-dimensional analytics visualizations (subject/tag breakdowns, activity heatmap, cross-dimension analysis, recommendations).

### Static interactive elements

| Element | Selector | Locatable by role+name? | Proposed testid |
|---|---|---|---|
| Back link | `.back-link` | yes | `analytics-back-link` |
| Exam filter | `#examFilter` (combobox, no label assoc) | partial — needs `aria-label` | `analytics-exam-filter` |
| Settings link | `.analytics-settings-link` | partial (title only) | `analytics-settings-btn` |
| Sunburst size presets (S/M/L) | `.size-preset-group[data-chart="subject_sunburst"] .size-preset-btn` | yes | `analytics-subject-sunburst-size-{S\|M\|L}` |
| Tag chart size presets | similar pattern | yes | `analytics-tag-chart-size-{S\|M\|L}` |
| Activity / Heatmap / Cross-dim size presets | similar pattern | yes | `analytics-{chart}-size-{S\|M\|L}` |
| Subject Deep Dive link | `#subjectDeepDiveLink` | yes | `analytics-subject-deepdive-link` |
| Mistake Types Deep Dive link | `.deep-dive-link` (2nd) | yes | `analytics-mistaketype-deepdive-link` |
| Swap Dimensions | `#swapDimensionsBtn` | partial (title only) | `analytics-dimensions-swap-btn` |
| Reset drill-down | `#resetDrilldownBtn` | yes | `analytics-heatmap-reset-btn` |
| Export Heatmap CSV | `#exportHeatmapCSV` | yes | `analytics-heatmap-export-csv-btn` |
| Period buttons (7d/30d/90d/all) | `.period-btn` | yes | `analytics-activity-period-{7d\|30d\|90d\|all}` |
| Dimension A / B pickers | `#heatmapDimA`, `#heatmapDimB` | yes | `analytics-heatmap-dim-a-select`, `-dim-b-select` |
| Dimension A / B level pickers | `#heatmapLevelA`, `#heatmapLevelB` | partial — duplicated label "Level:" | `analytics-heatmap-level-a-select`, `-level-b-select` |

### Dynamic elements (JS-inserted)

| Element | Source | Strategy |
|---|---|---|
| Sunburst arcs | `sunburst_chart.js` `render()` line 84-140 | add `.attr('data-testid', d => 'analytics-sunburst-arc-' + d.data.id)` at the path join (line 123) |
| Sunburst labels | `sunburst_chart.js` `_addLabels()` 162-193 | `analytics-sunburst-label-{subjectId}` |
| Sunburst center label | `#totalEntriesCenter` | exists; consider `aria-live="polite"` |
| Sunburst breadcrumb | `#sunburstBreadcrumb` | `analytics-sunburst-breadcrumb-{level}` per link |
| Tag donut canvas | `analytics_dashboard.js:1301-1364` | `analytics-tag-chart` on canvas; assert via legend |
| Tag legend items | `analytics_dashboard.js:1393+` | `analytics-tag-legend-{tagName}` |
| Activity line chart | `analytics_dashboard.js:1473+` | `analytics-activity-chart` on canvas |
| Activity heatmap cells | `heatmap_chart.js:176-200` | add at line 184: `.attr('data-testid', d => 'analytics-heatmap-cell-' + d.date)` |
| Heatmap day / month labels | `heatmap_chart.js:109-171` | `analytics-heatmap-day-{index}`, `analytics-heatmap-month-{name}` |
| Cross-dim cells | `dimension_heatmap.js:43-239` | add at line 187: `.attr('data-testid', \`analytics-cross-dim-cell-${dimA.id}-${dimB.id}\`)` |
| Cross-dim row / col headers | `dimension_heatmap.js:126-169` | `analytics-cross-dim-row-header-{dimAId}`, `-col-header-{dimBId}` |
| Cross-dim count overlays | `dimension_heatmap.js:204-215` | `analytics-cross-dim-count-{dimAId}-{dimBId}` |
| Drill-down breadcrumb | `#heatmapBreadcrumb` | `analytics-heatmap-breadcrumb-step-{index}` |
| Stat cards | static IDs (`#totalEntries`, `#thisWeek`, etc.) | use existing IDs; add `aria-live="polite"` |
| Difficulty distribution | `loadDifficultyDistribution()` → `#difficultyBars` | `analytics-difficulty-bar-{1..5}` |
| Streak / goal / interaction-effects / dimension-insights / weight-analysis components | per-component render | container-level testids per component |

### Page modes

- **Single-dimension** vs **multi-dimension** (cross-dimension section visible only when multi).
- **Drill-down** (heatmap) — breadcrumb visible, scope pickers populated.
- **Sunburst zoom** — arc click, center label updated.
- **Empty** — placeholder text in charts.

### Notes

The two highest-leverage test-id additions for this page are inside D3 render functions: `sunburst_chart.js:123`, `heatmap_chart.js:184`, `dimension_heatmap.js:187`. With those three lines, every chart cell becomes individually addressable. Canvas charts (tag donut, activity line) cannot be selected directly — assert via legend items and tooltip text.

---

## entry_browser.html

**File:** `src/web/html/entry_browser.html`
**Companion JS:** `entry_browser.js`, `custom-select.js`, `export_dialog.js`
**Page purpose:** Browse, filter, search, and paginate entries with selection mode and bulk export.

### Static interactive elements

| Element | Selector | Locatable by role+name? | Proposed testid |
|---|---|---|---|
| Back to Dashboard | `.back-link` | yes | `browser-header-back` |
| Export IDs (toggles selection mode) | header button | yes | `browser-header-export-ids` |
| Search input | `<input>` w/ placeholder only | partial — add `aria-label` | `browser-search-input` |
| Clear search | title="Clear search" | weak | `browser-search-clear` |
| Search help icon | `?` div | no | `browser-search-help` |
| Subject / Tag / Date / Session filter buttons | each has compound text label | weak | `browser-filter-subject`, `browser-filter-tags`, `browser-filter-date`, `browser-filter-session` |
| Subject search (in dropdown) | `#subjectFilterBtn` dropdown input | partial | `browser-subject-search` |
| Include child subjects | checkbox | yes | `browser-subject-children-toggle` |
| Apply / Clear (per dropdown) | text "Apply"/"Clear" not unique | weak | `browser-subject-clear`/`-apply`, `-tags-clear`/`-apply`, `-date-apply`, `-session-clear`/`-apply` |
| Date preset buttons | per range | yes | `browser-date-preset-{today\|yesterday\|...}` |
| Custom date inputs (From/To) | labeled | partial | `browser-date-from`, `browser-date-to` |
| Sort select (CustomSelect) | `#customSortSelect` | partial | `browser-sort-select` |
| Drafts only checkbox | labeled | yes | `browser-drafts-toggle` |
| Clear all filters | text "Clear all" | yes | `browser-filters-clear-all` |
| Select All Visible | labeled checkbox | yes | `browser-select-all-visible` |
| Export Selected / Export All Visible | labeled buttons | yes | `browser-export-selected`, `browser-export-all-visible` |
| Cancel selection | text "Cancel" not unique | weak | `browser-selection-cancel` |
| Load More | text | yes | `browser-pagination-load-more` |

### Dynamic elements

| Element | Created in | Testid pattern |
|---|---|---|
| Subject tree nodes | `renderSubjectList()` line 831 | `browser-subject-item-{subjectId}`, toggle: `browser-subject-toggle-{subjectId}` |
| Tag groups + items | `renderTagList()` line 1018 | `browser-tag-group-{groupId}`, `browser-tag-item-{tagId}` |
| Session radio items | `renderSessionList()` line 1071 | `browser-session-item-{sessionId}` |
| Entry cards | `createEntryCard()` line 582 (template at line 266) | `browser-row-{entryId}` |
| Card subject chips | `renderSubjectsOnCard()` line 690 | `browser-row-{entryId}-subject-{subjectId}` |
| Card tag chips | inline | `browser-row-{entryId}-tag-{tagId}` |
| Card checkbox (selection mode) | inline | `browser-row-{entryId}-checkbox` |
| Autocomplete items | `updateAutocomplete()` line 1674 | `browser-autocomplete-item-{prefix}` |
| Active filter chips | `updateActiveFilters()` line 1297 | `browser-filter-chip-{type}` |
| Empty state | `#emptyState` | `browser-empty-state` |
| Loading state | `#loadingState` | `browser-loading-state` |
| Pagination info | `#paginationArea` span | `browser-pagination-info` |

### Modals / popovers

- 4 filter dropdowns (`browser-{subject\|tags\|date\|session}-dropdown`) — each `<filter-group>` with `.open` class
- Search help tooltip — `browser-search-help-tooltip`
- Export dialog — built dynamically by `ExportQuestionIdsDialog.show()` in `export_dialog.js`; testid `browser-export-dialog`

### Page modes

- **Normal browse** — cards visible, click navigates to detail.
- **Selection mode** — toolbar visible, cards show checkboxes, "Export IDs" hidden.
- **Loading**, **Empty results** (filter-aware messaging), **Dropdown open**.

### Notes

`#searchInput` lacks `aria-label`; placeholder alone is insufficient. Filter button labels are compound ("SubjectAll", "TagsAll") and ambiguous for role+name locators — testids essential. Multiple "Clear"/"Apply" buttons across dropdowns conflict on text alone; testids per dropdown disambiguate.

---

## entry_detail.html

**File:** `src/web/html/entry_detail.html`
**Companion JS:** `entry_detail.js`, `toast.js`, `rich_content_renderer.js`, `export_dialog.js`
**Page purpose:** Full detail of a question entry — media, tabbed notes by subject, answers, explanations, related topics, and entry navigation.

### Static interactive elements

| Element | Locatable by role+name? | Proposed testid |
|---|---|---|
| Back link | yes | `detail-back-link` |
| Edit button | yes | `detail-edit-button` |
| Lightbox close (×) | yes | `detail-lightbox-close` |
| Lightbox prev / next | partial (no aria-label) | `detail-lightbox-prev`, `-next` (also add `aria-label`) |
| Lightbox backdrop | no | `detail-lightbox-backdrop` |
| Previous / Next entry buttons | yes (title attr) | `detail-prev-entry-button`, `-next-entry-button` |
| Export button | yes | `detail-export-button` |
| Export dropdown items | yes | `detail-export-copy-id`, `detail-export-session-ids` |

### Dynamic elements (JS-inserted)

| Element | Generated by | Testid |
|---|---|---|
| Subject breadcrumb | `renderSubjectPath()` line 357 | `detail-subject-path` |
| Difficulty badge | `renderDifficultyBadge()` line 397 | `detail-difficulty-badge` |
| Meta items (source, date, question ID, time spent) | `renderMetaInfo()` line 419 | `detail-meta-source`, `-date`, `-question-id`, `-time-spent` |
| Tag chips | `renderTags()` line 463 | `detail-tag-{index}` (or container `detail-tags-container`) |
| User answer / Correct answer cards | `renderAnswers()` line 487 | `detail-user-answer-card`, `-correct-answer-card` |
| Reflection / Explanation content (RichContentRenderer) | line 499 / 506 | `detail-reflection-content`, `-explanation-content` |
| Attachment thumbnails | `renderAttachments()` line 513 | `detail-attachments-grid`, items: `detail-attachment-thumb-{index}` |
| Note tabs | `renderNoteTabs()` line 638 | `detail-notes-tab-general`, `detail-notes-tab-subject-{subjectId}` |
| Note tab content panel | `showNoteTab()` line 662 | `detail-notes-tab-content` |
| Related topic links | `renderRelatedTopics()` line 700 | `detail-related-topic-{subjectId}` |

### Modals / popovers

- Lightbox modal (`#lightbox-modal`) → `detail-lightbox-modal`
- Export dropdown (`#export-dropdown-menu`) → `detail-export-dropdown-menu`
- Loading state (`#loading-state`) → `detail-loading-state` (add `role="status"`)
- Error state (`#error-state`) → `detail-error-state` (add `role="alert"`)

### Page modes

- **Loading** / **Error** / **Content** — three top-level visibility modes.
- **Tab mode** — multiple note tabs vs. single (tab bar hidden if single).
- **Lightbox** mode — keyboard handlers change while open.

### Notes

Lightbox prev/next lack accessible names — add `aria-label` in addition to testid. Tab bar should be wrapped in `role="tablist"` with proper `role="tab"`/`role="tabpanel"` semantics. RichContentRenderer output is opaque — assert presence/visibility, not internal structure.

---

## tree_editor.html

**File:** `src/web/html/tree_editor.html`
**Companion JS:** `tree_editor.js`, `weight_editor.js`, `subject_search_widget.js`
**Page purpose:** Subject hierarchy editor with weights, dimensions, import/export — central exam-configuration interface.

### Static interactive elements

| Element | ID | Locatable by role+name? | Testid |
|---|---|---|---|
| Back | `back-button` | yes | `tree-back-button` |
| Exam name (h1, dynamic) | `exam-name` | yes (heading) | `tree-exam-name` |
| Collapse All / Expand All | `btn-collapse-all`, `btn-expand-all` | yes | `tree-collapse-all`, `tree-expand-all` |
| Import / Export / Import Help | `btn-import`, `btn-export`, `btn-import-help` | yes | `tree-import`, `tree-export`, `tree-import-help` |
| Add Root Subject | `btn-add-root` | yes | `tree-add-root` |
| Search input + clear | `tree-search-input`, `tree-search-clear` | yes | (existing IDs are fine; redundant testid) |
| Node count, total weight, weight badge | display-only | no | `tree-node-count`, `tree-total-weight`, `tree-weight-badge` |
| Add First Subject (empty state) | `btn-add-first` | yes | `tree-add-first` |
| Edit name | `edit-name` | yes | `tree-edit-name` |
| Weight slider / numeric (fallback) | `weight-slider`, `weight-value` | yes | `tree-weight-slider`, `tree-weight-value` |
| Apply / Reset weight | `btn-apply-weight`, `btn-reset-weight` | yes | `tree-apply-weight`, `tree-reset-weight` |
| Add Child / Manage Aliases / Delete | `btn-add-child`, `btn-manage-aliases`, `btn-delete-node` | yes | `tree-add-child`, `tree-manage-aliases`, `tree-delete-node` |

### Dynamic elements

| Element | Source | Testid |
|---|---|---|
| Tree node (recursive) | `renderNode()` `tree_editor.js:497` | `tree-node-{nodeId}` (future-aware: `tree-node-{nodeId}-under-{parentId}` for polyhierarchy) |
| Tree toggle | `.tree-toggle` | `tree-toggle-{nodeId}` |
| Inline node name | `id="name-{nodeId}"` | `tree-node-name-{nodeId}` |
| Quick-add child / quick-delete | `tree_editor.js:544-545` | `tree-node-add-child-{nodeId}`, `tree-node-delete-{nodeId}` |
| Weight display in node | `.tree-node-weight` | `tree-node-weight-{nodeId}` |
| Enhanced weight editor inputs (low/high or single) | `weight_editor.js:196` | `tree-weight-low`, `tree-weight-high`, `tree-weight-slider-enhanced`, `tree-weight-input-enhanced` |
| Enhanced apply/reset | `weight_editor.js:414-418` | `tree-apply-weight-enhanced`, `tree-reset-weight-enhanced` |
| Siblings chart / total / history | `weight_editor.js:389, 393, 406` | `tree-siblings-chart-enhanced`, `tree-siblings-total-enhanced`, `tree-weight-history` |
| Dimension tabs | `tree_editor.js:300` | `tree-dimension-tab-{dimensionId}`, `tree-dimension-info` |
| Subject search widget chips/results | `subject_search_widget.js` | `tree-subject-result-{index}`, `tree-subject-chip-{subjectId}`, `tree-subject-remove-{subjectId}` |

### Modals / popovers

- **Add/Edit Node Modal** (`node-modal`): name, level, weight range toggle, simple/range inputs, source dropdown, dimension context, Cancel/Save — all prefixed `tree-node-modal-`.
- **Delete Confirmation** (`delete-node-modal`): subject name display, children warning, Cancel/Confirm — prefixed `tree-delete-modal-`.
- **Import Help Modal** (`import-help-modal`): content + Close — prefixed `tree-import-help-`.

### Page modes

- **Empty** (`tree-empty-state`) with optional dimension hint
- **Loading** (`tree-loading-state`)
- **Details placeholder** (no node selected) — shows exam overview pie chart
- **Details content** (node selected) — shows weight editor + children list
- **Dimension selector** visible only on multi-dimensional exams

### Notes

The fallback weight editor is overwritten by the enhanced editor at runtime. Tests should target `*-enhanced` testids unless explicitly testing the fallback. Modals lack `role="dialog"`/`aria-labelledby` — add as part of the migration. The tree's recursive node testid pattern is the single most important one across the entire app for the upcoming polyhierarchy work.

---

## session_setup.html

**File:** `src/web/html/session_setup.html`
**Companion JS:** `session_setup.js` (1320 lines), `session_import.js`
**Page purpose:** Review session creation, configuration, import, and previous-session management.

### Static interactive elements

| Element | ID | Locatable by role+name? | Testid |
|---|---|---|---|
| Back | `back-button` | yes | none |
| Exam heading | `exam-name` | yes | none |
| Question Source (CustomSelect) | `session-source` | no | `session-source-select` |
| Add New Source | `btn-add-source` | yes | none |
| Date / Total / Incorrect inputs | labeled | yes | none |
| Duration preset / custom | labeled | yes | none |
| Session Name | labeled | yes | none |
| Form error | `form-error` | no | `session-form-error` |
| Manage Sources / Start Session / Import Session | labeled buttons | yes | none |

### Dynamic elements

| Element | Source | Testid |
|---|---|---|
| Previous session card | `renderPreviousSessionCard()` line 199 | `session-card-{sessionId}` |
| Card buttons (Continue/Edit/Export IDs/Delete) | inline | accessible via name within card scope |
| Source items (Manage modal) | `loadSourcesForModal()` line 371 | `source-item-{sourceId}` |
| Toast | `Toast.show()` line 51 | `session-toast-{type}` |
| Sessions empty | `sessions-empty` line 55 | inline text fine |

### Modals / popovers

| Modal | ID | Testid |
|---|---|---|
| Add source | `add-source-modal` | `session-source-add-modal` |
| Manage sources | `manage-sources-modal` | `session-source-manage-modal` |
| Edit source | `edit-source-modal` | `session-source-edit-modal` |
| Delete source confirm | `delete-source-modal` | `session-source-delete-confirm` |
| Edit session | `edit-session-modal` | `session-edit-modal` |
| Delete session confirm | `delete-session-modal` | `session-session-delete-confirm` |
| Entry picker | `entry-picker-modal` | `session-entry-picker`, items: `session-entry-{entryId}` |
| Import wizard | `import-wizard-modal` | covers 5 steps (file dropzone, mapping, config, preview, results) |
| Save mapping profile | `save-profile-modal` | `session-import-save-profile` |

**Import wizard sub-elements** (key items):
- File dropzone — `session-import-file-dropzone` (also add `role="button"` + `tabindex="0"` + `aria-label`)
- Mapping table — labeled, locatable; per-row testids if dynamic
- Source select (CustomSelect) — `session-import-source-select`
- Preview summary / entry preview — `session-import-preview-summary`, `-entry-preview`
- Progress / results — `session-import-progress`, `-results`
- Nav buttons — `import-btn-cancel`, `import-btn-back`, `import-btn-next` (existing IDs are testid-equivalent)

**Timer round history** (in edit session modal):
- Section — `session-round-history`
- Round item — `session-round-{roundId}` with `-duration`, `-studied`, `-save`, `-delete`
- Round metadata text — accessible text; assert format

**Inline entry picker:**
- Container — `session-entry-picker-inline`
- List — `session-entry-picker-list`
- Per-entry checkbox — `session-entry-{entryId}`

### Page modes

- **Setup** (default) — Start Session enabled only when source/date/totals valid
- **Edit session** — modal with timer rounds + entry picker
- **Import** — 5-step wizard

### Notes

CustomSelect components require testids since `role=combobox` is synthesized. File dropzone needs `role="button"` + keyboard support. Timer round duration/studied inputs use `mm:ss` regex format — tests must respect that. Form validation gates Start Session button — wait for state change before assertion.

---

## settings.html

**File:** `src/web/html/settings.html`
**Companion JS:** `settings.js`, `api/_loader.js`
**Page purpose:** Multi-panel settings interface — appearance, study sessions, analytics, entry browser, anki, data backup, performance, MCP server, addons.

### Static interactive elements (selected)

| Element | Locatable by role+name? | Testid |
|---|---|---|
| Sidebar nav buttons | yes | (skip — role+name) |
| Theme select | yes | (skip) |
| Primary / Secondary color picker pairs (color + text input share label) | partial | `settings-appearance-primary-color-picker`, `-primary-color-hex`, `-secondary-color-picker`, `-secondary-color-hex` |
| Font / size / density / animations | yes | (skip) |
| Session duration / break inputs | yes | (skip) |
| Hotkey capture inputs (3) | partial — readonly textboxes with custom capture | `settings-study-sessions-hotkey-{pause-resume\|new-round\|end-round}`, plus `-clear` siblings |
| Analytics exam selector | partial — dynamic | `settings-analytics-exam-selector` |
| Default dimension selector | partial — conditional | `settings-analytics-dimension-selector` |
| Chart toggle checkboxes (dynamic) | partial | `settings-analytics-chart-{chartKey}` |
| Save exam analytics | yes | `settings-analytics-save-exam-config` |
| Coming-soon panels (calendar/anki/data backup) | disabled — skip | — |
| MCP enabled checkbox | yes | `settings-mcp-server-enabled` |
| MCP port input | partial | `settings-mcp-server-port` |
| MCP status indicator + URL | display-only | (skip) |
| MCP copy JSON / CLI buttons | partial (title only) | `settings-mcp-copy-json`, `settings-mcp-copy-cli` |
| Install addon button | yes | (skip) |

### Dynamic elements

| Element | Testid |
|---|---|
| Plugin sub-nav buttons | `settings-plugin-nav-{pluginId}` |
| Plugin settings panels | `settings-plugin-panel-{pluginId}` |
| Plugin save buttons | `settings-plugin-save-{pluginId}` |
| Addon cards | `settings-addon-card-{pluginId}` |
| Addon toggle / uninstall | `settings-addon-toggle-{pluginId}`, `settings-addon-uninstall-{pluginId}` |
| Chart toggles | `settings-analytics-chart-toggle-{chartKey}` |

### Modals / popovers

- Native `confirm()` for unsaved changes / plugin uninstall / reset-to-defaults — originally noted as "works with Playwright `dialog` event"; under pychrome there is no equivalent auto-handler (see `docs/planning/PYCHROME_MIGRATION.md`). Either way it breaks the in-app flow, so consider migrating to HTML modals.
- Hotkey conflict warning — inline div, `settings-study-sessions-hotkey-conflict-warning`.

### Page modes

- **Clean** vs **dirty** (preview warning, save enabled)
- **Saving** (toast)
- **Exam analytics loaded** (chart toggles rendered)
- **MCP running** (`.mcp-status-dot.running`)
- **Coming-soon** (panels disabled)

### Notes

Color picker pairs share `data-field`; testids disambiguate by purpose. Hotkey inputs are readonly with custom capture — a plain `fill()`-style write won't trigger them (originally noted as "Playwright `fill()` won't work"; under pychrome the equivalent is `tab.evaluate(...)` setting `.value` directly, which is *also* insufficient). Use a sequence of `Input.dispatchKeyEvent` calls with focus instead. WIP commits added the hotkey UI, MCP panel, per-exam analytics, and addon management — these are the most testid-hungry sections.

---

## wizards/exam_wizard.html

**File:** `src/web/html/wizards/exam_wizard.html`
**Companion JS:** `wizards/exam_wizard.js`
**Page purpose:** Multi-step wizard for exam creation/editing (simple and multi-dimensional).

### Static interactive elements

| Element | ID | Testid |
|---|---|---|
| Cancel (×) | `btn-cancel` | `wizard-cancel-button` |
| Wizard logo link | `wizard-logo-link` | `wizard-home-link` |
| Back / Next / Create | `btn-back`, `btn-next`, `btn-create` | `wizard-back-button`, `-next-button`, `-create-button` |
| Exam name / description / date / notes | labeled | `wizard-exam-name-input`, `-description-textarea`, `-date-input`, `-notes-textarea` |
| Autonomous balancing toggle | `autonomous-balancing` | `wizard-weight-autonomous-balancing-toggle` |
| Weight precision / algorithm selects (CustomSelect) | `weight-precision-select`, `balancing-algorithm-select` | `wizard-weight-precision-select`, `wizard-weight-algorithm-select` |
| Add dimension | `btn-add-dimension` | `wizard-step3-add-dimension-button` |
| Reset template | `btn-reset-template` | `wizard-reset-template-button` |
| Success continue / error dismiss | `btn-continue`, `btn-dismiss-error` | `wizard-success-continue-button`, `wizard-error-dismiss-button` |

### Dynamic elements

| Element | Testid pattern |
|---|---|
| Exam type cards (radio inside) | `wizard-step1-type-{simple\|multi}` |
| Learn More buttons | `wizard-step1-learn-{simple\|multi}` |
| Template scratch radio | `wizard-step1-template-scratch` |
| Template search input | `wizard-step1-template-search-input` |
| Category filter buttons | `wizard-step1-template-filter-{all\|medical\|graduate\|undergraduate\|professional}` |
| Template cards (grid) | `wizard-step1-template-card-{templateId}` |
| Dimension cards | `wizard-step3-dimension-{index}` (or stable `{dimensionId}` if introduced) |
| Dimension fields | `wizard-step3-dimension-{index}-name-input`, `-required-checkbox`, `-allow-multiple-checkbox`, `-delete-button` |
| Progress steps | `wizard-progress-step-{stepNum}` |
| Hierarchy levels (display-only) | `wizard-step3-hierarchy-level-{index}` |
| Step 5 summary fields | `wizard-step5-summary-{name\|type\|description\|date\|balancing\|precision\|algorithm}` |
| CustomSelect options | `wizard-{select-id}-option-{value}` |

### Modals

| Modal | Testid |
|---|---|
| Success | `wizard-modal-success` |
| Error | `wizard-modal-error` |
| Learn More: Simple / Multi | `wizard-modal-learn-simple`, `-learn-multi` |

### Page modes

- **Create mode** vs **Edit mode** (URL `?edit={examId}`, starts at step 3, button changes to "Save Changes")
- **Simple flow** (6 steps) vs **Multi-dim flow** (7 steps)

### Future-aware

The planned exam-length step (`HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md`) needs reserved patterns: `wizard-stepN-exam-length-{fixed\|range\|unknown}` for radios, `wizard-stepN-exam-length-range-min-input` / `-max-input` for the conditional inputs.

### Notes

CustomSelects need `role="listbox"` + `role="option"` added for accessibility *and* role-based locator support. Modals need `role="dialog"` + `aria-modal="true"`. Add `data-current-step` to the wizard root for direct step assertion.

---

## error-viewer.html

**File:** `src/web/html/error-viewer.html`
**Companion JS:** `error-logger.js`
**Page purpose:** Development error console viewer (capture, filter, export JS errors).

### Static interactive elements

| Element | Line | Locatable by role+name? | Testid |
|---|---|---|---|
| Stats button (📊) | 20 | no — emoji-only | `error-viewer-stats-button` |
| Clear button (🗑️) | 21 | no | `error-viewer-clear-button` |
| Export button (💾) | 22 | no | `error-viewer-export-button` |
| Minimize button (_) | 23 | no | `error-viewer-minimize-button` |
| Level filter | 28 | yes (combobox) | (skip) |
| Category filter | 39 | yes | (skip) |
| Search filter | 50 | yes (placeholder) | (skip) |

### Dynamic elements

| Element | Created at | Testid |
|---|---|---|
| Empty state | 164-169 | `error-viewer-list-empty` |
| Error item (expandable) | 173-206 | `error-viewer-error-item-{errorId}` |
| Error details (collapsed) | 180-204 | `error-viewer-error-details-{errorId}` |

### Modals

- Stats panel — `error-viewer-stats-panel` (toggled via `.visible` class)
- Native `confirm()` for clear

### Page modes

- **Minimized** vs **Expanded** (`#error-viewer.minimized`)
- **Stats visible** vs **hidden** (`#stats-panel.visible`)

### Notes

All four header buttons need testids — emoji-only labels are not accessible names. Header buttons need `aria-label`. Error items should have `role="region"` + `aria-expanded` for the toggle pattern. Stats panel benefits from `aria-live="polite"` for updates.

---

## subject_deep_dive.html

**File:** `src/web/html/subject_deep_dive.html`
**Companion JS:** `subject_deep_dive.js`
**Page purpose:** Drill-down analytics for a specific subject — performance, timeline, child subjects, mistake patterns, related topics, recommendations.

### Static interactive elements

| Element | Locatable by role+name? | Testid |
|---|---|---|
| Back to Analytics link | yes | `deep-dive-nav-back` |
| Subject title (h1) | yes | `deep-dive-subject-title` |
| Exam label badge | no | `deep-dive-exam-label` |
| Full Path / Exam Weight values | no | `deep-dive-subject-fullpath-value`, `-weight-value` |
| Trend stats (this week / last week / change) | no | `deep-dive-trend-thisweek-value`, `-lastweek-value`, `-change` |
| Stat cards (mistakes / percentage / difficulty / last) | no | `deep-dive-stat-mistakes`, `-percentage`, `-difficulty`, `-last-mistake` |
| Timeline canvas | no | `deep-dive-chart-timeline` |

### Dynamic elements

| Element | Source | Testid |
|---|---|---|
| Child subjects list | `renderChildSubjects()` js:265-290 | `deep-dive-list-children`, items: `deep-dive-child-row-{childId}` (future-aware: `-under-{parentId}` for polyhierarchy) |
| Mistake types list | `renderMistakeTypes()` js:295-319 | `deep-dive-list-mistake-types`, badges: `deep-dive-mistake-type-badge-{tagName}` |
| Recent entries list | `renderRecentEntries()` js:324-356 | `deep-dive-list-recent-entries`, items: `deep-dive-recent-entry-{entryId}` |
| Related topics (siblings) | `renderRelatedTopics()` js:361-386 | `deep-dive-list-related-topics`, items: `deep-dive-related-topic-{siblingId}` |
| Recommendations | `renderRecommendations()` js:391-411 | `deep-dive-list-recommendations`, items: `deep-dive-recommendation-{type}` |
| Empty states (per section) | per render method | `deep-dive-empty-state-{section}` |

### Future-aware (polyhierarchy)

A "Show as part of: Parent A / Parent B / All parents" selector is planned. Reserve:
- `deep-dive-parent-context-selector` — the control
- `deep-dive-parent-context-option-{parentId}` — each option

### Notes

Most clickable list items are bare `<div>` with click handlers — they need `role="button"` + `tabindex="0"` + keyboard handlers as part of the migration. Timeline is Canvas — pixel-level inspection or refactor to SVG/D3 if fine-grained chart testing becomes needed.

---

## Summary of Implementation Work

### Files needing testid additions (HTML)
All 11 HTML files. Static testid additions are mechanical — add `data-testid="..."` attributes per the tables above.

### Files needing testid additions (JS — render-time)
- `landing.js` — exam card buttons
- `analytics_preview.js` — dropdown trigger
- `question_entry.js` — chips, dots, note cards, autopopulation prompt
- `media_upload.js` — thumbnails and action buttons
- `entry_browser.js` — entry rows, subject tree, tag groups
- `entry_detail.js` — meta items, attachment thumbs, note tabs, related topics
- `tree_editor.js` — `renderNode()` recursive node + actions, dimension tabs
- `weight_editor.js` — enhanced editor inputs/buttons
- `subject_search_widget.js` — chips and results
- `analytics_dashboard.js` — chart toggles, dimension pickers
- `sunburst_chart.js`, `heatmap_chart.js`, `dimension_heatmap.js` — D3 cell render functions (the highest-leverage adds)
- `session_setup.js` — session cards, source items, round history, entry picker
- `session_import.js` — wizard step elements
- `settings.js` — chart toggles, plugin/addon panels
- `exam_wizard.js` — template cards, dimension cards, custom select options
- `subject_deep_dive.js` — child rows, mistake types, recent entries, related topics, recommendations

### Cross-cutting accessibility upgrades worth pairing with the migration

- Add `role="dialog"` + `aria-labelledby` + focus trap to all modals
- Add `aria-label` to icon-only buttons (lightbox prev/next, error-viewer header, swap dimensions, copy buttons)
- Wrap notes tabs in proper `role="tablist"` / `role="tab"` / `role="tabpanel"` semantics
- Add `role="combobox"` / `role="listbox"` / `role="option"` to `CustomSelect` instances
- Add `role="status"` / `role="alert"` to loading and error states
- Add keyboard handlers + `role="button"` + `tabindex="0"` to clickable bare divs (deep-dive list items, dashboard exam cards if they're not already buttons)

### Recommended order for Phase 1 of the test infrastructure

1. **`question_entry.html` first** — most complex, exercises the full set of patterns (rich editors, dynamic chips, modals, navigation, media). If the testid scheme works here, it works everywhere.
2. **`tree_editor.html` second** — the recursive node testid is the foundation for both polyhierarchy and weight-rework testing.
3. **`entry_browser.html` third** — entry-row testid pattern unblocks most navigation scenarios.
4. **`exam_wizard.html` fourth** — template selection unblocks user-creation scenarios.
5. Remaining 7 pages — order driven by which features the test suite covers next.
