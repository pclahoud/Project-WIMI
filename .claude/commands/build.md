# Build - Intelligent Test and Build System

**Enhanced with Agent Capabilities:** Failure analysis, performance tracking, automated debugging

Run tests and build the WIMI executable with intelligent error analysis and suggestions.

## Instructions

When the user runs `/build`, I will check for arguments and execute the appropriate action with enhanced analysis.

### Available Commands

| Command | Action |
|---------|--------|
| `/build` or `/build test` | Run pytest with coverage + analysis |
| `/build exe` | Build Windows executable + validation |
| `/build full` | Run tests, then build if tests pass |
| `/build analyze` | Analyze test failures and suggest fixes |

## Agent-Enhanced Commands

### /build test - Intelligent Test Runner

**What I do:**
1. Run pytest with coverage
2. **Analyze failures automatically**
3. **Compare with previous runs** to detect regressions
4. **Suggest specific fixes** for common failures
5. **Identify coverage gaps** and suggest tests to add

Execute:
```powershell
pytest --cov=src --cov-report=term-missing
```

**Enhanced Report Format:**
```
## Test Results

✅ Tests: 270 passed, 0 failed, 3 skipped
📊 Coverage: 83.4% (+0.3% from last run)

### Coverage by Module
| Module | Coverage | Change | Status |
|--------|----------|--------|--------|
| src/database/user_db.py | 89% | +2% | 🟢 Improved |
| src/app/bridge.py | 85% | -1% | 🟡 Check new code |
| src/web/js/api.js | N/A | - | JavaScript |

### Performance
- Test suite: 12.3s (0.5s faster than previous)
- Slowest test: test_analytics_complex (3.2s)

All tests passed! ✅
```

If tests fail:
```
## Test Results

❌ Tests: 268 passed, 2 failed, 3 skipped
📊 Coverage: 82.1%

### Failed Tests

#### 1. test_database/test_user_db.py::test_create_entry_invalid
```
AssertionError: Expected ValueError
```

**Agent Analysis:**
- 🔍 This test was passing until commit abc123
- 📝 Recent changes to `create_entry()` added new validation
- 💡 **Suggested Fix:** Update test to expect the new `ValidationError` message
- 📂 See: src/database/user_db.py line 234

**Automatic Fix Available:** Yes
Would you like me to fix this test automatically?

#### 2. test_bridge/test_bridge.py::test_serialize_response
```
KeyError: 'data'
```

**Agent Analysis:**
- 🔍 Similar error occurred in test_bridge.py::test_other_method
- 📝 `serialize_response()` changed to make 'data' optional
- 💡 **Suggested Fix:** Add `data=None` default parameter
- 📂 See: src/app/bridge.py line 89

**Pattern Detected:** 5 other tests may have the same issue
Would you like me to identify all affected tests?

### Recommended Actions
1. Run `/build analyze` for detailed failure analysis
2. Fix test_create_entry_invalid (I can do this automatically)
3. Review serialize_response changes for breaking changes
4. Run `pytest tests/database/test_user_db.py::test_create_entry_invalid -vv` for details
```

### /build exe - Intelligent Build with Validation

**What I do:**
1. Run PyInstaller build
2. **Validate bundled assets** (all files included?)
3. **Check frozen mode compatibility**
4. **Compare size with previous builds** (unexpected growth?)
5. **Test executable startup** (if possible)

Execute:
```powershell
.\build_windows.bat
```

**Enhanced Report Format:**
```
## Build Results

✅ Build successful!

📁 Output: dist/WIMI/WIMI.exe
📊 Size: ~245 MB (+5 MB from previous build)

### Build Analysis
- Build time: 3m 42s
- Modules included: 287
- Hidden imports: 12
- Data files: 156

### Size Analysis
- Executable: 245 MB
- Largest components:
  - PyQt6 libraries: 120 MB
  - Web assets: 18 MB
  - Python runtime: 85 MB

### Validation Checks
✅ All web assets bundled
✅ Database schema files included
✅ Media directory structure created
✅ Frozen mode paths configured
⚠️  Size increased by 5 MB - new dependencies added?

The executable is ready to run.

### Post-Build Checklist
1. [ ] Test executable launch
2. [ ] Verify frozen mode paths work
3. [ ] Check web pages load correctly
4. [ ] Test database operations
5. [ ] Verify media upload works
```

If build fails:
```
## Build Results

❌ Build failed!

### Error
PyInstaller error: Missing module 'xyz'

### Agent Analysis
- 🔍 Module 'xyz' is imported in src/new_feature.py line 15
- 📝 This is a new dependency not in wimi.spec
- 💡 **Suggested Fix:** Add 'xyz' to hidden imports in wimi.spec

### Automated Fix Available
I can add this to wimi.spec for you:

```python
hiddenimports=[
    # ... existing imports ...
    'xyz',  # Added for new_feature.py
],
```

Would you like me to apply this fix and rebuild?

### Similar Issues
- 2 other modules might have the same problem
- Check: src/other_feature.py imports 'abc'
```

### /build full - Full Build Pipeline with Intelligence

**What I do:**
1. Run tests with analysis
2. If tests pass, proceed to build with validation
3. If tests fail, analyze and suggest fixes
4. Track overall health metrics

**Example output:**
```
## Full Build Pipeline

### Step 1: Tests
✅ 270 passed, 0 failed, 3 skipped (83.4% coverage)
⚡ Test suite: 12.3s (+0.2s from last run)

### Step 2: Build Validation
🔍 Checking frozen mode compatibility...
✅ All path resolutions use sys.frozen checks
✅ No hardcoded development paths found

### Step 3: Build
✅ Build successful! dist/WIMI/WIMI.exe
📊 Build time: 3m 42s

### Step 4: Post-Build Validation
✅ Executable size reasonable (245 MB)
✅ All assets bundled correctly
✅ Schema files included

Build complete! 🎉

### Health Metrics
- Code quality: 🟢 Excellent (83.4% coverage)
- Build health: 🟢 Stable (no warnings)
- Performance: 🟢 Good (12.3s test time)
```

Or if tests fail:
```
## Full Build Pipeline

### Step 1: Tests
❌ 2 tests failed - stopping build

### Agent Analysis
Both failures are related to recent refactoring of serialize_response():

**Root Cause:**
- `serialize_response()` signature changed in commit abc123
- Made 'data' parameter optional
- 12 tests need updating

**Recommended Approach:**
1. Fix the method signature: Add `data=None` default
2. Or update all 12 tests to match new signature

I can identify all affected tests and fix them automatically.
Would you like me to:
1. Show all affected tests
2. Apply automatic fix
3. Review changes in detail first
```

### /build analyze - Deep Failure Analysis (New!)

**What I do when tests fail:**
1. **Trace error origins** - Find what changed to cause failure
2. **Identify patterns** - Group related failures
3. **Suggest root cause fixes** - Fix the cause, not symptoms
4. **Predict other failures** - Find similar issues before they fail

**Example output:**
```
## Test Failure Analysis

Analyzing 2 failed tests...

### Failure Group 1: Validation Error Pattern
**Affected Tests:** 2
**Root Cause:** Parameter validation refactoring in user_db.py

#### test_create_entry_invalid
- **Expected:** `ValueError` with message "Invalid entry data"
- **Got:** `ValidationError` with message "Entry validation failed: missing required field 'question_text'"
- **Changed in:** Commit abc123 (refactor: improve entry validation)
- **Fix:** Update test to expect new exception type and message

#### test_update_entry_invalid  
- **Similar pattern detected**
- **Same root cause**
- **Same fix needed**

**Automated Fix Available:**
```python
# Old
with pytest.raises(ValueError, match="Invalid entry data"):

# New
with pytest.raises(ValidationError, match="Entry validation failed"):
```

### Predicted Issues
🔮 **7 more tests** may have similar issues:
- test_create_session_invalid
- test_update_session_invalid
- test_create_tag_invalid
- [4 more...]

Would you like me to:
1. Fix all 9 tests automatically
2. Show me the diff first
3. Fix only the 2 that failed
```

## Agent Intelligence Features

### 1. Regression Detection
```
⚠️  **Regression Alert**
Test `test_get_entries` was passing in the last 5 runs but failed now.

Recent changes that might be related:
- Commit abc123: "refactor: optimize entry queries"
- File: src/database/user_db.py line 456
- Change: Added JOIN clause to query

Likely cause: New JOIN returns different data structure
```

### 2. Performance Monitoring
```
📊 **Performance Analysis**

Test suite getting slower:
- 5 runs ago: 10.1s
- 4 runs ago: 10.3s
- 3 runs ago: 11.2s
- 2 runs ago: 11.8s
- Current: 12.3s

**Slowest tests:**
1. test_analytics_complex: 3.2s (+0.8s)
2. test_dashboard_load: 2.1s (+0.3s)

**Recommendation:** Review recent database operations in analytics tests
```

### 3. Coverage Insights
```
📈 **Coverage Analysis**

Low coverage areas that need tests:
1. src/database/user_db.py lines 234-267 (0% coverage)
   - Function: `calculate_streak_bonus()`
   - Added: 3 days ago
   - **Suggested test:** test_calculate_streak_bonus_zero_streak

2. src/app/bridge.py lines 156-178 (25% coverage)
   - Function: `importWeights()`
   - Missing: Error handling tests
   - **Suggested test:** test_import_weights_invalid_json

Would you like me to generate test scaffolding for these?
```

### 4. Build Size Analysis
```
📦 **Build Size Tracking**

Build size trend:
- 5 builds ago: 238 MB
- 4 builds ago: 240 MB
- 3 builds ago: 242 MB
- 2 builds ago: 244 MB
- Current: 250 MB (+6 MB)

**Largest contributors to growth:**
- New dependency 'python-magic': 4 MB
- Additional JavaScript libraries: 2 MB

**Recommendation:** Consider if python-magic is necessary
```

## Quick Reference

**Test commands:**
```powershell
# All tests with analysis
pytest

# With coverage and intelligence
pytest --cov=src --cov-report=term-missing

# Specific file with context
pytest tests/database/test_user_db.py -v

# Specific test with detailed output
pytest tests/database/test_user_db.py::TestClassName::test_method -vv

# By marker
pytest -m "database" -v

# Failed tests only (after a failure)
pytest --lf -v
```

**Build files:**
- `wimi.spec` - PyInstaller configuration
- `build_windows.bat` - Build script
- `requirements-prod.txt` - Production dependencies

**Build output:**
```
dist/WIMI/
├── WIMI.exe           # Main executable
├── _internal/         # Bundled files
│   ├── web/           # HTML/CSS/JS
│   └── database/      # Schema files
└── app_data/          # User data (created at runtime)
```

## Agent Automation Offers

When failures occur, I can:
1. **Fix tests automatically** - Update assertions, imports, etc.
2. **Update spec files** - Add missing hidden imports
3. **Generate missing tests** - Create test scaffolding for uncovered code
4. **Refactor tests** - Update multiple tests with same pattern
5. **Performance optimization** - Identify and fix slow tests

## Notes

- Coverage requirement is 80%+ (enforced in pytest.ini)
- Build takes 2-5 minutes depending on system
- Always run tests before building for release
- Check `logs/` folder if the built app has issues
- I track metrics across runs to detect trends
- I learn from your fixes to suggest better solutions
