# Explore - Intelligent Codebase Navigation

**Enhanced with Agent Capabilities:** Semantic search, impact analysis, learning paths, dependency mapping

Quick reference and intelligent navigation for the WIMI codebase.

## Instructions

When the user runs `/explore`, I provide intelligent codebase navigation based on the argument.

### Available Commands

| Command | Action |
|---------|--------|
| `/explore` | Show overview of all areas |
| `/explore db` | Database layer reference |
| `/explore bridge` | Bridge method patterns |
| `/explore api` | JavaScript API patterns |
| `/explore ui` | UI/Frontend file locations |
| `/explore search <term>` | Intelligent semantic search |
| `/explore impact <function>` | Show what depends on this |
| `/explore flow <feature>` | Trace data flow through layers |
| `/explore learn <topic>` | Generate learning path |
| `/explore related <file>` | Find related files by coupling |

## Standard Commands (Enhanced)

### /explore - Intelligent Overview

**What I do:**
1. Show codebase structure
2. **Analyze current state** (uncommitted changes, recent activity)
3. **Suggest next exploration** based on context

```
## WIMI Codebase Overview

### Architecture (3 Layers)
1. **Database** (Python) → `src/database/`
2. **Bridge** (Python↔JS) → `src/app/bridge.py`
3. **Frontend** (HTML/CSS/JS) → `src/web/`

### Key Files
| Layer | File | Lines | Purpose | Recent Activity |
|-------|------|-------|---------|-----------------|
| DB | user_db.py | ~7,500 | All user data operations | Modified 2 days ago |
| DB | master_db.py | ~500 | User registry | Stable |
| Bridge | bridge.py | ~3,850 | Python-JS communication | Modified today |
| API | api.js | ~800 | JS bridge wrapper | Stable |
| Entry | main.py | ~100 | App entry point | Stable |

### Feature Areas
- **Exam Setup:** wizard/, exam_wizard.js, tree_editor.js
- **Question Entry:** question_entry.html/js/css
- **Entry Browser:** entry_browser.html/js/css
- **Analytics:** analytics_dashboard.html/js/css

### Current Context
📝 You have uncommitted changes in:
- src/app/bridge.py (dimension methods)
- src/web/js/exam_wizard.js (dimension UI)

💡 **Suggested explorations:**
- `/explore impact createDimension` - See what uses this new method
- `/explore bridge` - Review bridge method patterns

Use `/explore <area>` for detailed reference.
```

### /explore search <term> - Intelligent Semantic Search

**Enhanced with:**
- Understands intent, not just keywords
- Groups results by relevance
- Shows usage context
- Suggests related searches

```
User: /explore search dimension validation

## Semantic Search Results: "dimension validation"

I understand you're looking for dimension validation logic. Here's what I found:

### Primary Results (Exact Matches)

#### Database Layer (2 files)
- **src/database/user_db.py:1234** - `def validate_dimension(self, ...)`
  ```python
  def validate_dimension(self, dimension_data: Dict) -> None:
      """Validate dimension data before creation/update."""
  ```
  Used by: `create_dimension()`, `update_dimension()`

#### Bridge Layer (1 file)
- **src/app/bridge.py:567** - `def createDimension(self, ...)`
  ```python
  # Validation before database call
  if not dimension_data.get('name'):
      raise ValueError("Dimension name required")
  ```

### Related Results (Semantic Matches)

#### Validation Patterns
- **src/database/user_db.py:890** - `def validate_exam_context(self, ...)`
  Similar validation pattern for exam contexts

#### Frontend Validation
- **src/web/js/exam_wizard.js:234** - `validateDimensionForm()`
  Client-side validation before API call

### Usage Context
This validation is called when:
1. Creating new dimensions (exam wizard)
2. Updating existing dimensions (tree editor)
3. Importing dimensions from templates

### Related Searches You Might Want
- `/explore flow dimension-creation` - See full creation flow
- `/explore impact validate_dimension` - What depends on this?
- `dimension error handling` - See error cases

Found 6 matches across 4 files.
```

## New Agent-Enhanced Commands

### /explore impact <function> - Dependency Analysis

**What I do:**
1. Find all code that calls this function
2. Trace through layers (DB → Bridge → API → UI)
3. Identify breaking change risks
4. Show test coverage

```
User: /explore impact createDimension

## Impact Analysis: createDimension

### Function Location
- **Layer:** Bridge
- **File:** src/app/bridge.py line 567
- **Type:** Public API method

### Direct Callers (2)

1. **exam_wizard.js** (Frontend)
   ```javascript
   // Line 234: Adding new dimension
   const result = await api.createDimension(dimensionData);
   ```
   **Context:** User clicks "Add Dimension" button

2. **template_importer.js** (Frontend)
   ```javascript
   // Line 89: Importing template dimensions
   for (const dim of template.dimensions) {
       await api.createDimension(dim);
   }
   ```
   **Context:** User imports exam template

### Downstream Dependencies

```
createDimension (bridge.py)
  └─> create_dimension (user_db.py)
       └─> INSERT INTO dimensions
       └─> create_default_hierarchy (user_db.py)
            └─> INSERT INTO subject_nodes
```

### Breaking Change Risk Analysis

⚠️  **HIGH RISK** - This is a public API
- Used in 2 UI locations
- No version compatibility layer
- Changes require UI updates

**If you modify this function:**
1. Update exam_wizard.js validation
2. Update template_importer.js error handling
3. Update API documentation
4. Add migration for existing callers

### Test Coverage
✅ Unit tests: `tests/bridge/test_dimension_crud.py`
✅ Integration: `tests/integration/test_exam_wizard.py`
⚠️  Missing: Template import edge cases

**Recommendation:** Add tests for template import error handling before modifying
```

### /explore flow <feature> - Data Flow Tracing

**What I do:**
1. Trace data from UI → API → Bridge → Database
2. Show transformations at each layer
3. Identify validation points
4. Highlight error handling

```
User: /explore flow dimension-creation

## Data Flow: Dimension Creation

### Flow Diagram
```
[User Input] → [UI Validation] → [API Call] → [Bridge] → [DB] → [Response]
exam_wizard.js   validateForm()    api.js      bridge.py   user_db.py
```

### Step-by-Step Trace

#### Step 1: User Input (exam_wizard.js:234)
```javascript
const dimensionData = {
    name: "Site of Care",
    description: "Clinical setting classification",
    exam_context_id: 5
};
```
**Validation:**
- ✅ Name not empty
- ✅ Valid exam context
- ❌ No duplicate check (done server-side)

#### Step 2: API Call (api.js:156)
```javascript
async createDimension(data) {
    return await this._callBridge('createDimension', {
        jsonData: JSON.stringify(data)
    });
}
```
**Transformation:** Object → JSON string

#### Step 3: Bridge Layer (bridge.py:567)
```python
@pyqtSlot(str, result=str)
def createDimension(self, json_data: str) -> str:
    data = json.loads(json_data)  # JSON → Dict
    
    # Validation
    if not data.get('name'):
        return self.serialize_response(
            success=False,
            error="Name required"
        )
    
    result = self.user_db.create_dimension(data)
    return self.serialize_response(success=True, data=result)
```
**Validation:**
- ✅ Name required
- ✅ Exam context exists (checked in DB)

#### Step 4: Database Layer (user_db.py:1234)
```python
def create_dimension(self, data: Dict) -> Dict:
    with self.transaction():
        # Check for duplicates
        existing = self._get_dimension_by_name(
            data['name'], 
            data['exam_context_id']
        )
        if existing:
            raise ValueError("Dimension already exists")
        
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO dimensions (name, description, exam_context_id) "
            "VALUES (?, ?, ?)",
            (data['name'], data['description'], data['exam_context_id'])
        )
        return {'dimension_id': cursor.lastrowid}
```
**Validation:**
- ✅ Duplicate check
- ✅ Foreign key constraint (exam_context_id)

#### Step 5: Response Flow (Back to UI)
```
DB Result → Bridge → API → UI
{'id': 5}  JSON    Object  DOM update
```

### Error Handling at Each Layer

| Layer | Error Type | Response |
|-------|------------|----------|
| UI | Empty name | Alert, no API call |
| API | Network error | Throw error, catch in UI |
| Bridge | Invalid JSON | `{success: false, error: "..."}` |
| Database | Duplicate | ValueError → Bridge → UI |
| Database | FK constraint | sqlite3.Error → Bridge → UI |

### Performance Notes
- ⚡ Single database transaction
- ⚡ No N+1 queries
- 💡 Consider: Batch creation for template imports

### Related Flows
- `/explore flow dimension-update` - Similar pattern
- `/explore flow dimension-delete` - Cascade delete considerations
```

### /explore learn <topic> - Learning Path Generation

**What I do:**
1. Create ordered reading list for understanding a topic
2. Annotate each file with what to focus on
3. Suggest hands-on exercises

```
User: /explore learn exam-creation

## Learning Path: Understanding Exam Creation

I'll guide you through the exam creation feature from UI to database.

### Phase 1: Understanding the User Flow (Start here)
**Estimated time:** 15 minutes

1. **src/web/html/wizards/exam_wizard.html** (lines 1-50)
   - 📖 Read: HTML structure of the wizard
   - 🎯 Focus: Step progression, form fields
   - 💡 Notice: Multi-step wizard pattern

2. **src/web/css/exam_wizard.css** (lines 1-100)
   - 📖 Read: Visual styling
   - 🎯 Focus: Active/inactive step styles
   - ⏭️  Skip: Color variables (not critical)

### Phase 2: Frontend Logic (JavaScript)
**Estimated time:** 30 minutes

3. **src/web/js/exam_wizard.js** (lines 1-150)
   - 📖 Read: Wizard initialization
   - 🎯 Focus: `initWizard()` and `showStep()` methods
   - 💡 Notice: State management pattern

4. **src/web/js/exam_wizard.js** (lines 200-350)
   - 📖 Read: Form validation and submission
   - 🎯 Focus: `validateCurrentStep()` and `createExam()`
   - ⚠️  Important: Dimension handling (lines 280-320)

5. **src/web/js/api.js** (lines 100-200)
   - 📖 Read: API wrapper methods
   - 🎯 Focus: `createExamContext()` method
   - 💡 Notice: Error handling pattern

### Phase 3: Bridge Layer (Python-JS Communication)
**Estimated time:** 20 minutes

6. **src/app/bridge.py** (lines 400-500)
   - 📖 Read: Bridge methods for exam creation
   - 🎯 Focus: `createExamContext()` @pyqtSlot decorator
   - 💡 Notice: JSON serialization/deserialization

### Phase 4: Database Layer (Data Persistence)
**Estimated time:** 30 minutes

7. **src/database/user_db.py** (lines 800-1000)
   - 📖 Read: `create_exam_context()` method
   - 🎯 Focus: Transaction handling
   - ⚠️  Important: Foreign key relationships

8. **src/database/schema/user_db_schema_v1_phase7.sql** (lines 1-50)
   - 📖 Read: Table definitions
   - 🎯 Focus: `exam_contexts` and `dimensions` tables
   - 💡 Notice: Foreign key constraints

### Phase 5: Testing (Understanding Quality)
**Estimated time:** 20 minutes

9. **tests/integration/test_exam_creation.py**
   - 📖 Read: Integration test flow
   - 🎯 Focus: Setup → Create → Assert pattern
   - 💡 Notice: What edge cases are tested

### Hands-On Exercises

**Exercise 1: Trace a Simple Creation**
1. Open exam_wizard.html in browser
2. Fill out form and click "Create"
3. Set breakpoint in exam_wizard.js:createExam()
4. Trace through to bridge.py:createExamContext()

**Exercise 2: Add Validation**
1. Add new validation: exam name must be unique
2. Implement in: exam_wizard.js, bridge.py, user_db.py
3. Add test in: tests/database/test_exam_crud.py

**Exercise 3: Debug a Failure**
1. Intentionally break: Remove exam_context_id from form data
2. Trace the error through all layers
3. Observe error handling at each level

### Key Concepts to Understand

✅ **Multi-step wizard pattern** - How state is preserved
✅ **Three-layer architecture** - UI → Bridge → Database
✅ **Transaction handling** - When/why transactions are used
✅ **Error propagation** - How errors flow back to UI
✅ **Foreign keys** - Dimensional relationships

### Related Topics to Explore Next

- `/explore learn dimension-management` - Advanced multi-dimensional feature
- `/explore learn subject-hierarchy` - Tree editor concepts
- `/explore flow exam-creation` - See the data flow diagram

**Estimated total time:** 2 hours
**Prerequisites:** Basic understanding of PyQt6, SQLite, JavaScript
```

### /explore related <file> - Coupling Analysis

**What I do:**
1. Find files frequently changed together
2. Identify logical groupings
3. Suggest refactoring opportunities

```
User: /explore related src/app/bridge.py

## Related Files Analysis: bridge.py

### Tightly Coupled Files (Change together frequently)

#### Very High Coupling (90%+ co-change)
1. **src/database/user_db.py**
   - Reason: Bridge methods call database methods directly
   - Last co-changed: Today (dimension methods)
   - Recommendation: This is expected, no refactoring needed

2. **src/web/js/api.js**
   - Reason: API wrappers mirror bridge methods
   - Last co-changed: 2 days ago (added dimension CRUD)
   - Recommendation: Keep synchronized

#### High Coupling (70-89% co-change)
3. **tests/bridge/test_bridge.py**
   - Reason: Tests for bridge methods
   - Last co-changed: Today
   - Recommendation: Good! Tests tracking implementation

4. **src/web/js/exam_wizard.js**
   - Reason: Major consumer of bridge APIs
   - Last co-changed: Yesterday
   - Recommendation: Normal, feature development

### Logical Groupings

**Exam Management Cluster:**
- bridge.py (bridge methods)
- user_db.py (database operations)
- api.js (API wrappers)
- exam_wizard.js (UI)

**Recommendation:** These files form a logical feature module. When modifying exam creation, expect to touch 2-3 of these files.

### Refactoring Opportunities

⚠️  **High coupling detected:**
- bridge.py is 3,850 lines
- Contains methods for 8+ different features

**Suggested refactoring:**
Split bridge.py into feature-specific modules:
```
src/app/bridges/
  ├── exam_bridge.py      # Exam context methods
  ├── entry_bridge.py     # Entry methods
  ├── session_bridge.py   # Session methods
  ├── dimension_bridge.py # Dimension methods
  └── analytics_bridge.py # Analytics methods
```

This would:
- ✅ Reduce file size
- ✅ Improve maintainability
- ✅ Make testing easier
- ⚠️  Require refactoring (3-5 hours)

### Unexpected Coupling (Worth investigating)

🔍 **bridge.py often changes with:**
- src/web/css/shared.css (40% co-change)

**Analysis:** This seems unusual. Bridge methods shouldn't affect CSS.

**Investigation needed:** Are UI changes (CSS) driving API additions?

### Files That Should Be Related But Aren't

❓ **bridge.py rarely changes with:**
- docs/API.md (10% co-change)

**Recommendation:** Update API documentation when adding bridge methods. Consider automating this.
```

## Agent Intelligence Features

### 1. Context-Aware Suggestions
Based on your current work, I suggest relevant explorations:
```
💡 You're working on dimension methods. You might want to:
- `/explore impact getDimensions` - See who uses this
- `/explore flow dimension-creation` - Understand the full flow
- `/explore related dimension_editor.js` - Find coupled files
```

### 2. Pattern Recognition
```
🔍 I noticed this pattern in your search:
You searched for "dimension" 3 times today.

**Comprehensive dimension resources:**
- Database: user_db.py lines 1200-1500 (dimension CRUD)
- Bridge: bridge.py lines 550-750 (dimension API)
- Frontend: exam_wizard.js lines 200-400 (dimension UI)
- Tests: test_dimension_crud.py (dimension tests)

Would you like me to create a dimension cheat sheet?
```

### 3. Learning Optimization
```
📚 Based on your recent explorations:
- You read exam_wizard.js
- You read bridge.py dimension methods
- You searched for validation

**Next logical step:**
`/explore learn dimension-validation` - Understand validation flow

Or practice:
**Exercise:** Add validation for duplicate dimension names
```

## Quick Reference

**Navigation tips:**
- Start broad (`/explore`), then narrow (`/explore db`)
- Use `/explore search` for finding code
- Use `/explore impact` before modifying functions
- Use `/explore flow` to understand features
- Use `/explore learn` when onboarding to new areas

**Agent shortcuts:**
```bash
# Find where something is used
/explore impact <function_name>

# Understand a feature
/explore flow <feature_name>

# Learn a topic
/explore learn <topic>

# Find related work
/explore related <file_path>
```

## Notes

- I learn your exploration patterns to suggest better next steps
- I track file change frequency to identify coupling
- I can generate custom documentation from code
- I understand semantic meaning, not just keywords
