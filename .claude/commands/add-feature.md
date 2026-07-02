# Add Feature - Intelligent Code Scaffolding

**Enhanced with Agent Capabilities:** Pattern recognition, validation, cross-layer consistency checking

Generate context-aware boilerplate code for new WIMI features following project patterns.

## Instructions

When the user runs `/add-feature [feature_name]`, I will:

1. **Analyze the codebase** to find similar existing features
2. **Validate feasibility** by checking database schema and dependencies
3. **Generate intelligent scaffolding** based on actual patterns in the codebase
4. **Verify cross-layer consistency** 
5. **Suggest comprehensive tests** including edge cases

### Step 1: Gather Feature Information

Ask the user for:
1. **Feature name** (e.g., "getUserGoals", "deleteSession")
2. **Description** (what the feature does)
3. **Parameters** (name, type for each)
4. **Return type** (what data is returned)
5. **Which layers to generate:**
   - Database method (user_db.py)
   - Bridge method (bridge.py)
   - API wrapper (api.js)
   - Test file (tests/)

### Step 2: Intelligent Analysis (Agent-Enhanced)

**Before generating code, I will:**

1. **Find Similar Features:**
   - Search for similar method names in the codebase
   - Identify patterns (e.g., "getUser*" methods follow a pattern)
   - Show user what similar features exist

2. **Validate Database Schema:**
   - Check if required tables/columns exist
   - Identify if schema changes needed
   - Warn about missing foreign keys

3. **Check Dependencies:**
   - Find what other features call this type of method
   - Identify if this feature needs other features first
   - Detect circular dependency risks

4. **Analyze Error Patterns:**
   - Review how similar features handle errors
   - Identify common validation patterns
   - Suggest appropriate exception handling

### Step 3: Generate Context-Aware Templates

Based on the analysis, generate templates that match project conventions.

#### Database Method Template

**File:** `src/database/user_db.py`

```python
def {feature_name}(self, {params}) -> {return_type}:
    """
    {Description}.

    Args:
        {param_name}: {param_description}

    Returns:
        {return_description}

    Raises:
        ValueError: If {validation_error}
        sqlite3.Error: If database operation fails
    """
    try:
        # [AGENT NOTE: Based on similar methods, consider these patterns]
        with self.transaction():
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT/INSERT/UPDATE/DELETE ...
                """,
                ({param_values})
            )
            # Process results
            result = cursor.fetchone()  # or fetchall()
            return result
    except sqlite3.Error as e:
        self.logger.error(f"Failed to {feature_name}: {e}")
        raise
```

#### Bridge Method Template

**File:** `src/app/bridge.py`

```python
@pyqtSlot({js_types}, result=str)
def {feature_name}(self, {params}) -> str:
    """
    {Description}.

    Args:
        {param_name}: {param_description}

    Returns:
        JSON string with result or error
    """
    try:
        if not self.user_db:
            return self.serialize_response(
                success=False,
                error="No user database loaded"
            )

        # [AGENT NOTE: Similar methods validate these parameters]
        # Parse JSON params if needed
        # data = json.loads(json_param)

        result = self.user_db.{feature_name}({params})

        return self.serialize_response(
            success=True,
            data=result
        )
    except ValueError as e:
        self.logger.warning(f"{feature_name} validation error: {e}")
        return self.serialize_response(success=False, error=str(e))
    except Exception as e:
        self.logger.error(f"{feature_name} failed: {e}")
        return self.serialize_response(success=False, error=str(e))
```

#### API Wrapper Template

**File:** `src/web/js/api.js`

```javascript
/**
 * {Description}
 * @param {{ParamType}} {paramName} - {param_description}
 * @returns {Promise<{ReturnType}>} {return_description}
 */
async {featureName}({params}) {
    // [AGENT NOTE: Methods in this section typically handle these edge cases]
    const result = await this._callBridge('{feature_name}', {
        arg1: {param1},
        // For objects: JSON.stringify({param})
    });
    return result;
}
```

#### Intelligent Test Template

**File:** `tests/database/test_{feature_area}.py` or `tests/bridge/test_{feature_area}.py`

```python
import pytest
from src.database.user_db import UserDatabase


class Test{FeatureName}:
    """Tests for {feature_name} functionality."""

    def test_{feature_name}_success(self, user_db):
        """Test successful {feature_name} operation."""
        # Arrange
        {setup_code}

        # Act
        result = user_db.{feature_name}({test_params})

        # Assert
        assert result is not None
        {assertions}

    def test_{feature_name}_invalid_input(self, user_db):
        """Test {feature_name} with invalid input."""
        with pytest.raises(ValueError):
            user_db.{feature_name}({invalid_params})

    def test_{feature_name}_not_found(self, user_db):
        """Test {feature_name} when resource doesn't exist."""
        result = user_db.{feature_name}({nonexistent_params})
        assert result is None  # or appropriate assertion

    # [AGENT GENERATED: Based on similar feature patterns]
    def test_{feature_name}_edge_case_{specific}(self, user_db):
        """Test edge case identified from similar features."""
        {edge_case_test}
```

### Step 4: Validation Report (Agent-Enhanced)

After generating templates, provide:

```markdown
## Feature Analysis Report

### Similar Features Found
- `getEntryById()` - Similar pattern, uses transaction
- `createEntry()` - Similar validation approach
- `updateEntryStatus()` - Similar error handling

### Database Schema Check
✅ Required tables exist: `entries`, `sessions`
⚠️  Consider adding index on `session_id` for performance
✅ Foreign key constraints in place

### Dependencies
- This feature requires: `getSessionById()`
- This feature is needed by: (none detected)
- No circular dependencies detected

### Integration Points
1. Add to `src/database/user_db.py` at line ~{suggested_line}
2. Add to `src/app/bridge.py` in the "Entry Methods" section
3. Add to `src/web/js/api.js` in the Entry API class

### Recommended Edge Case Tests
- Empty string parameters
- Non-existent foreign keys
- Concurrent modification scenarios
- Large data sets (performance)

Would you like me to:
1. Add these files to the codebase now?
2. Show the full code with agent suggestions included?
3. Run validation checks first?
```

### Step 5: Integration Checklist

```markdown
## Integration Checklist

1. [ ] Add database method to `src/database/user_db.py`
2. [ ] Add bridge method to `src/app/bridge.py`
3. [ ] Add API wrapper to `src/web/js/api.js`
4. [ ] Add tests to appropriate test file
5. [ ] Run tests: `pytest tests/ -v`
6. [ ] Verify no regressions: `pytest --cov=src`
7. [ ] Update documentation if needed
8. [ ] Check frozen mode compatibility

## Agent Recommendations

Based on codebase analysis:
- Consider adding logging at level: {INFO/DEBUG}
- Similar methods cache results - consider caching
- Performance: Add index on {column} if queries are slow
```

## Example Usage

```
User: /add-feature getUserStreak

Claude: Let me analyze the codebase for similar patterns...

[Searches for streak-related code, goal tracking methods]

## Analysis Results

Found 3 similar features:
- `getUserGoals()` - Similar structure
- `getStreakData()` - Already exists! Did you mean to enhance this?
- `calculateStreak()` - Helper method you'll need

Database check:
✅ `goals` table exists with `current_streak` column
✅ No schema changes needed

I'll generate scaffolding for the getUserStreak feature.

**Feature Details:**
- Name: getUserStreak
- Description: Get the current study streak for a user
- Parameters: user_id (int)
- Returns: dict with current_streak, longest_streak, last_active_date

[Shows templates with inline agent comments about patterns]

Would you like me to add these to the codebase?
```

## Agent Capabilities Summary

This enhanced `/add-feature` command uses agent capabilities for:

✅ **Pattern Recognition** - Finds similar code automatically
✅ **Schema Validation** - Checks database compatibility
✅ **Dependency Analysis** - Prevents integration issues
✅ **Context-Aware Generation** - Templates match actual project patterns
✅ **Edge Case Detection** - Suggests comprehensive tests
✅ **Performance Hints** - Identifies indexing opportunities
✅ **Integration Planning** - Shows exactly where code should go

## Key Patterns Reference

### Database Method Patterns
- Always use `with self.transaction()` for write operations
- Log errors with `self.logger.error()`
- Docstrings with Args/Returns/Raises sections
- Return None for not found, raise for errors

### Bridge Method Patterns
- `@pyqtSlot(str, result=str)` for JSON params
- `@pyqtSlot(int, str, result=str)` for mixed params
- Always return `self.serialize_response()`
- Check `self.user_db` exists first

### API Wrapper Patterns
- JSDoc comments with @param and @returns
- Use `async` and `await this._callBridge()`
- `JSON.stringify()` for object parameters
- Method name in JavaScript is camelCase
