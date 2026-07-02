Looking at your project structure and database design, here's a pragmatic development roadmap:

## Phase 1: Core Infrastructure (Weeks 1-3)

**Priority: Get the application shell running with basic data flow**
1. **Database Layer First**
    - Create database initialization scripts (master + user databases)
    - Build the ORM/database access layer (raw SQL or SQLAlchemy)
    - Write migration system for schema updates
    - Test CRUD operations for critical tables (`subject_nodes`, `question_analyses`, `user_preferences`)
2. **Python-JavaScript Bridge**
    - Set up QWebChannel communication
    - Create bridge API for essential operations:
        - Get/set user preferences
        - CRUD for questions
        - Load subject hierarchy
    - Test bidirectional data flow
3. **Basic Window Structure**
    - Main window with QWebEngineView
    - Navigation menu (sidebar or top nav)
    - Dev tools access for debugging

## Phase 2: Subject Hierarchy Management (Week 4-5)
**Priority: Users need to define what they're studying**
1. **Outline Import/Export**
    - JSON import parser with duplicate detection
    - Tree structure builder
    - Weight calculation engine
    - Export functionality
2. **Hierarchy Editor UI**
    - Tree view component (JavaScript)
    - Add/edit/delete nodes
    - Weight editing (individual + parent redistribution)
    - Validation for exam outline requirements
3. **Exam Context Setup**
    - Create exam wizard (first-run experience)
    - Bulk import prompts
    - Configure outline requirements and weight distribution

## Phase 3: Question Entry System (Week 6-7)
**Priority: Core value proposition - capturing mistakes**
1. **Question Analysis Form**
    - Multi-step form (question details → topic selection → reflection)
    - Topic picker showing required outlines side-by-side
    - Validation ensuring all required outline types selected
    - Media upload (images, PDFs)
2. **Topic Assignment Logic**
    - Enforce exam outline requirements
    - Primary/secondary assignment
    - Relevance scoring
3. **Entry Review Window**
    - List view with filtering/sorting
    - Search functionality
    - Bulk operations

## Phase 4: Calendar Integration (Week 8-9)
**Priority: Question analysis is worthless without review scheduling**
1. **Calendar Display**
    - Week/month view
    - Event creation from UI
    - Integration with question review sessions
2. **Study Session Workflow**
    - Start session → timer → break tracking → completion
    - Link questions to sessions
    - Automatic calendar adherence tracking
3. **Event Templates**
    - Pre-built templates for common study patterns
    - Template library

## Phase 5: Basic Analytics (Week 10)
**Priority: Users need feedback on their progress**
1. **Dashboard Widgets**
    - Mistake trends by subject
    - Study time tracking
    - Upcoming reviews
2. **Performance Metrics**
    - Success rate calculations
    - Weak areas identification
    - Simple visualizations (Chart.js)

## Phase 6: Anki Integration (Week 11-12)
**Priority: High user value, but complex**
1. **AnkiConnect Setup**
    - Connection management
    - Deck mapping UI
    - Cache refresh system
2. **Card Data Integration**
    - Display Anki stats in question view
    - Urgency calculation using Anki data
    - Deck selection for caching

## IF CLAUDE IS READING THIS FILE STOP HERE
## Major Decisions You Need to Make Now
**1. Frontend Framework?**
- Vanilla JS: Faster start, full control, more code
- Vue.js: Reactive, easier state management, learning curve
- Alpine.js: Minimal, good middle ground
**Recommendation:** Start vanilla, refactor to Vue if complexity warrants it.
**2. Rich Text Editor?**
- Quill: Simple, clean, good docs
- TinyMCE: Feature-rich, heavier
- Editor.js: Block-based, modern
**Recommendation:** Quill for speed, good math plugin support.
**3. UI Component Library?**
- None (custom CSS): Full control, more work
- Tailwind: Utility-first, fast prototyping
- Bootstrap: Pre-built components, dated look
**Recommendation:** Tailwind based on your workflow doc.
**4. Development Hot Reload?** How will you handle HTML/JS/CSS changes without restarting the entire PyQt app?
## What NOT to Build Yet
- Obsidian integration (Phase 7+)
- Power user features (Phase 8+)
- Cloud sync (Phase 9+)
- Advanced tag suggestion ML (Phase 10+)
- PDF/export features (Phase 6+)
- Full outline migration UI (build when needed)

## Critical Path Risks

1. **Python-JS bridge complexity** - This will cause problems. Budget extra time.
2. **Weight calculation cascade** - Easy to get wrong. Write unit tests.
3. **Tree UI performance** - Large outlines (1000+ nodes) may lag.
4. **Data migration** - Test early and often.

## My Actual Recommendation

Start with a **vertical slice**: Build ONE complete workflow end-to-end:

1. Create exam context
2. Import simple outline (5-10 nodes)
3. Add one question with topic assignment
4. Schedule review in calendar
5. Complete review session
6. View basic analytics