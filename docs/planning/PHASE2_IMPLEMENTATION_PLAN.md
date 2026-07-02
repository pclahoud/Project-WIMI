# Phase 2 Implementation Plan: Subject Hierarchy Management

**Document Version:** 1.0  
**Last Updated:** November 8, 2025  
**Phase Status:** Planning Complete → Ready for Implementation

---

## Table of Contents

1. [Phase 2 Overview](#phase-2-overview)
2. [Implementation Steps](#implementation-steps)
3. [Database Implementation](#database-implementation)
4. [Python Backend Implementation](#python-backend-implementation)
5. [UI Implementation](#ui-implementation)
6. [Testing Strategy](#testing-strategy)
7. [Timeline Estimate](#timeline-estimate)

---

## Phase 2 Overview

### Goals

Phase 2 focuses on **Subject Hierarchy Management** with the exam setup wizard as the primary deliverable. This phase enables users to:

1. Create their first exam context
2. Configure hierarchy levels (default 5, custom beyond)
3. Set weight calculation rules
4. Begin building their subject outline

### Key Features

✅ **Exam Context Wizard** - Step-by-step exam setup  
✅ **Weight Calculation System** - Auto-balancing with proportional distribution  
✅ **Hierarchy Customization** - Support for custom depth levels  
✅ **Weight History Tracking** - Complete audit trail  

### New Database Tables

1. **exam_contexts** - Stores exam configuration and weight rules
2. **hierarchy_level_definitions** - Custom hierarchy level definitions
3. **subject_node_weights** - Weight change audit trail

---

## Implementation Steps

### Phase 2 Development Stages

```
Stage 1: Database Schema
    ↓
Stage 2: Python Backend
    ↓
Stage 3: PyQt Window Setup
    ↓
Stage 4: Python-JavaScript Bridge
    ↓
Stage 5: Exam Wizard UI
    ↓
Stage 6: Weight Calculation Engine
    ↓
Stage 7: Testing & Documentation
```

---

## Database Implementation

### Stage 1: Schema Updates

**Duration**: 2-3 hours

#### Task 1.1: Create Phase 2 Schema File

**File**: `src/database/schema/user_db_schema_v1_phase2.sql`

**Contents**:
```sql
-- Phase 2 Schema: Subject Hierarchy Management
-- Tables: exam_contexts, hierarchy_level_definitions, subject_node_weights

-- Table 1: exam_contexts
CREATE TABLE IF NOT EXISTS exam_contexts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    exam_name VARCHAR(255) UNIQUE NOT NULL,
    exam_description TEXT,
    exam_date DATE,
    created_date DATE DEFAULT CURRENT_DATE,
    is_active BOOLEAN DEFAULT TRUE,
    default_hierarchy_levels TEXT CHECK (json_valid(default_hierarchy_levels)),
    weight_validation_rules TEXT CHECK (json_valid(weight_validation_rules)),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX idx_unique_exam_name_per_user ON exam_contexts (user_id, exam_name);
CREATE INDEX idx_active_exams ON exam_contexts (user_id, is_active) WHERE is_active = TRUE;

-- Table 2: hierarchy_level_definitions
CREATE TABLE IF NOT EXISTS hierarchy_level_definitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_context_id INTEGER NOT NULL REFERENCES exam_contexts(id) ON DELETE CASCADE,
    level_name VARCHAR(100) NOT NULL,
    level_order INTEGER NOT NULL,
    is_required BOOLEAN DEFAULT FALSE,
    display_name_template VARCHAR(255),
    is_custom_level BOOLEAN DEFAULT FALSE,
    created_date DATE DEFAULT CURRENT_DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX idx_unique_level_per_exam ON hierarchy_level_definitions (exam_context_id, level_order);
CREATE INDEX idx_exam_levels_ordered ON hierarchy_level_definitions (exam_context_id, level_order);

-- Table 3: subject_node_weights
CREATE TABLE IF NOT EXISTS subject_node_weights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_node_id INTEGER NOT NULL REFERENCES subject_nodes(id) ON DELETE CASCADE,
    weight_value DECIMAL(5,2) NOT NULL,
    edited_date DATE NOT NULL DEFAULT CURRENT_DATE,
    edited_by TEXT DEFAULT 'user',
    edited_reason TEXT,
    previous_weight DECIMAL(5,2),
    change_type TEXT CHECK (change_type IN ('initial', 'manual_edit', 'auto_recalculate', 'parent_redistribution')),
    affected_siblings TEXT CHECK (json_valid(affected_siblings)),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_notes TEXT
);

CREATE INDEX idx_weight_history_by_node ON subject_node_weights (subject_node_id, edited_date DESC);
CREATE INDEX idx_weight_changes_by_date ON subject_node_weights (edited_date DESC);
```

#### Task 1.2: Update Schema Manager

**File**: `src/database/schema_manager.py`

**Add Phase 2 schema version:**
```python
SCHEMA_VERSIONS = {
    '1.0.0': 'user_db_schema_v1_phase1.sql',
    '1.1.0': 'user_db_schema_v1_phase2.sql',  # NEW
}
```

#### Task 1.3: Create Migration Script

**File**: `src/database/migrations/1.0.0_to_1.1.0_phase2_tables.py`

**Purpose**: Migrate existing Phase 1 databases to Phase 2

```python
def migrate_phase1_to_phase2(db_path: str):
    """
    Migrate Phase 1 database to Phase 2.
    Adds: exam_contexts, hierarchy_level_definitions, subject_node_weights
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Create Phase 2 tables
        with open('src/database/schema/user_db_schema_v1_phase2.sql', 'r') as f:
            schema_sql = f.read()
            cursor.executescript(schema_sql)
        
        # Update schema version
        cursor.execute("""
            UPDATE user_preferences 
            SET updated_at = CURRENT_TIMESTAMP 
            WHERE id = 1
        """)
        
        conn.commit()
        print(f"✅ Migration complete: {db_path}")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Migration failed: {e}")
        raise
    finally:
        conn.close()
```

---

## Python Backend Implementation

### Stage 2: Extend UserDatabase Class

**Duration**: 4-6 hours

#### Task 2.1: Add Data Models

**File**: `src/database/models.py`

**Add new dataclasses:**

```python
from dataclasses import dataclass
from typing import Optional, List
from datetime import date, datetime
import json

@dataclass
class ExamContext:
    """Exam context with configuration"""
    id: int
    user_id: int
    exam_name: str
    exam_description: Optional[str]
    exam_date: Optional[date]
    created_date: date
    is_active: bool
    default_hierarchy_levels: List[str]
    weight_validation_rules: dict
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    
    @classmethod
    def from_row(cls, row: dict):
        """Create from database row"""
        return cls(
            id=row['id'],
            user_id=row['user_id'],
            exam_name=row['exam_name'],
            exam_description=row.get('exam_description'),
            exam_date=date.fromisoformat(row['exam_date']) if row.get('exam_date') else None,
            created_date=date.fromisoformat(row['created_date']),
            is_active=bool(row['is_active']),
            default_hierarchy_levels=json.loads(row['default_hierarchy_levels']),
            weight_validation_rules=json.loads(row['weight_validation_rules']),
            notes=row.get('notes'),
            created_at=datetime.fromisoformat(row['created_at']),
            updated_at=datetime.fromisoformat(row['updated_at'])
        )

@dataclass
class HierarchyLevelDefinition:
    """Hierarchy level definition for exam context"""
    id: int
    exam_context_id: int
    level_name: str
    level_order: int
    is_required: bool
    display_name_template: Optional[str]
    is_custom_level: bool
    created_date: date
    created_at: datetime
    updated_at: datetime
    
    @classmethod
    def from_row(cls, row: dict):
        """Create from database row"""
        return cls(
            id=row['id'],
            exam_context_id=row['exam_context_id'],
            level_name=row['level_name'],
            level_order=row['level_order'],
            is_required=bool(row['is_required']),
            display_name_template=row.get('display_name_template'),
            is_custom_level=bool(row['is_custom_level']),
            created_date=date.fromisoformat(row['created_date']),
            created_at=datetime.fromisoformat(row['created_at']),
            updated_at=datetime.fromisoformat(row['updated_at'])
        )

@dataclass
class SubjectNodeWeight:
    """Weight change history record"""
    id: int
    subject_node_id: int
    weight_value: float
    edited_date: date
    edited_by: str
    edited_reason: Optional[str]
    previous_weight: Optional[float]
    change_type: str
    affected_siblings: List[int]
    created_at: datetime
    user_notes: Optional[str]
    
    @classmethod
    def from_row(cls, row: dict):
        """Create from database row"""
        return cls(
            id=row['id'],
            subject_node_id=row['subject_node_id'],
            weight_value=row['weight_value'],
            edited_date=date.fromisoformat(row['edited_date']),
            edited_by=row['edited_by'],
            edited_reason=row.get('edited_reason'),
            previous_weight=row.get('previous_weight'),
            change_type=row['change_type'],
            affected_siblings=json.loads(row['affected_siblings']) if row.get('affected_siblings') else [],
            created_at=datetime.fromisoformat(row['created_at']),
            user_notes=row.get('user_notes')
        )
```

#### Task 2.2: Add CRUD Methods to UserDatabase

**File**: `src/database/user_db.py`

**Exam Context Methods:**

```python
def create_exam_context(
    self,
    exam_name: str,
    exam_description: str = None,
    exam_date: date = None,
    weight_validation_rules: dict = None
) -> ExamContext:
    """
    Create a new exam context with default settings.
    
    Args:
        exam_name: Name of the exam (e.g., "USMLE Step 1")
        exam_description: Optional description
        exam_date: Optional scheduled exam date
        weight_validation_rules: Optional custom weight rules
        
    Returns:
        ExamContext object
        
    Raises:
        ValidationError: If exam_name already exists
    """
    # Default weight validation rules
    if weight_validation_rules is None:
        weight_validation_rules = {
            "autonomous_weight_balancing": True,
            "allow_absolute_weight_editing": False,
            "precision_decimal_places": 1,
            "require_exact_100": True,
            "balancing_algorithm": "proportional"
        }
    
    # Default hierarchy levels
    default_levels = ["System", "Subsystem", "Topic", "Subtopic", "Child"]
    
    try:
        with self.conn:
            cursor = self.conn.execute("""
                INSERT INTO exam_contexts (
                    user_id, exam_name, exam_description, exam_date,
                    default_hierarchy_levels, weight_validation_rules
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                self.user_id,
                exam_name,
                exam_description,
                exam_date.isoformat() if exam_date else None,
                json.dumps(default_levels),
                json.dumps(weight_validation_rules)
            ))
            
            exam_context_id = cursor.lastrowid
            
            # Create default hierarchy level definitions
            for order, level_name in enumerate(default_levels, start=1):
                self.conn.execute("""
                    INSERT INTO hierarchy_level_definitions (
                        exam_context_id, level_name, level_order,
                        is_required, is_custom_level
                    ) VALUES (?, ?, ?, ?, ?)
                """, (
                    exam_context_id,
                    level_name,
                    order,
                    order <= 3,  # First 3 levels are required
                    False
                ))
            
            # Fetch and return created exam context
            return self.get_exam_context(exam_context_id)
            
    except sqlite3.IntegrityError as e:
        raise ValidationError(f"Exam context '{exam_name}' already exists") from e

def get_exam_context(self, exam_context_id: int) -> Optional[ExamContext]:
    """Get exam context by ID"""
    cursor = self.conn.execute("""
        SELECT * FROM exam_contexts WHERE id = ?
    """, (exam_context_id,))
    
    row = cursor.fetchone()
    return ExamContext.from_row(dict(row)) if row else None

def get_all_exam_contexts(self, active_only: bool = True) -> List[ExamContext]:
    """Get all exam contexts for this user"""
    query = "SELECT * FROM exam_contexts WHERE user_id = ?"
    params = [self.user_id]
    
    if active_only:
        query += " AND is_active = TRUE"
    
    query += " ORDER BY created_date DESC"
    
    cursor = self.conn.execute(query, params)
    return [ExamContext.from_row(dict(row)) for row in cursor.fetchall()]

def update_exam_context_settings(
    self,
    exam_context_id: int,
    weight_validation_rules: dict
) -> ExamContext:
    """Update weight validation rules for an exam context"""
    with self.conn:
        self.conn.execute("""
            UPDATE exam_contexts 
            SET weight_validation_rules = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (json.dumps(weight_validation_rules), exam_context_id))
    
    return self.get_exam_context(exam_context_id)
```

**Hierarchy Level Methods:**

```python
def add_custom_hierarchy_level(
    self,
    exam_context_id: int,
    level_name: str = None
) -> HierarchyLevelDefinition:
    """
    Add a custom hierarchy level beyond the default 5.
    
    Args:
        exam_context_id: ID of the exam context
        level_name: Optional custom name (defaults to "Level N")
        
    Returns:
        HierarchyLevelDefinition object
    """
    # Get current max level order
    cursor = self.conn.execute("""
        SELECT MAX(level_order) as max_order 
        FROM hierarchy_level_definitions
        WHERE exam_context_id = ?
    """, (exam_context_id,))
    
    max_order = cursor.fetchone()['max_order'] or 0
    new_order = max_order + 1
    
    # Default name for custom levels
    if level_name is None:
        level_name = f"Level {new_order}"
    
    with self.conn:
        cursor = self.conn.execute("""
            INSERT INTO hierarchy_level_definitions (
                exam_context_id, level_name, level_order,
                is_required, display_name_template, is_custom_level
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            exam_context_id,
            level_name,
            new_order,
            False,
            "Daughter of {parent_name}",
            True
        ))
        
        level_id = cursor.lastrowid
    
    return self.get_hierarchy_level_definition(level_id)

def get_hierarchy_levels(self, exam_context_id: int) -> List[HierarchyLevelDefinition]:
    """Get all hierarchy levels for an exam context, ordered"""
    cursor = self.conn.execute("""
        SELECT * FROM hierarchy_level_definitions
        WHERE exam_context_id = ?
        ORDER BY level_order
    """, (exam_context_id,))
    
    return [HierarchyLevelDefinition.from_row(dict(row)) for row in cursor.fetchall()]
```

**Weight Update Methods:**

```python
def update_subject_node_weight(
    self,
    node_id: int,
    new_weight: float,
    reason: str = None,
    user_notes: str = None
) -> dict:
    """
    Update a subject node's weight with automatic sibling balancing.
    
    Args:
        node_id: ID of the node to update
        new_weight: New weight value (relative %)
        reason: Optional reason for the change
        user_notes: Optional user notes
        
    Returns:
        dict with updated node and affected siblings
        
    Raises:
        ValidationError: If weight is invalid
    """
    # Get the node
    node = self.get_subject_node(node_id)
    if not node:
        raise ValidationError(f"Subject node {node_id} not found")
    
    # Get exam context settings
    exam_context = self.get_exam_context_by_name(node.exam_context)
    settings = exam_context.weight_validation_rules
    
    # Validate new weight
    self._validate_weight(new_weight, settings)
    
    # Get siblings
    siblings = self._get_sibling_nodes(node_id)
    
    # Calculate weight change
    weight_change = new_weight - node.exam_weight_low
    
    # Determine affected siblings and new weights
    updated_siblings = []
    
    if settings['autonomous_weight_balancing'] and siblings:
        if settings['balancing_algorithm'] == 'proportional':
            updated_siblings = self._proportional_distribution(siblings, weight_change)
        else:
            updated_siblings = self._even_distribution(siblings, weight_change)
        
        # Validate total
        if settings['require_exact_100']:
            total = new_weight + sum(s['new_weight'] for s in updated_siblings)
            if abs(total - 100.0) > 0.01:
                raise ValidationError(f"Total weight {total}% must equal 100%")
    
    # Update database
    with self.conn:
        # Update main node
        self.conn.execute("""
            UPDATE subject_nodes 
            SET exam_weight_low = ?, exam_weight_high = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (new_weight, new_weight, node_id))
        
        # Record weight history
        self.conn.execute("""
            INSERT INTO subject_node_weights (
                subject_node_id, weight_value, edited_by, edited_reason,
                previous_weight, change_type, affected_siblings, user_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            node_id,
            new_weight,
            'user',
            reason or 'User manual edit',
            node.exam_weight_low,
            'manual_edit',
            json.dumps([s['id'] for s in updated_siblings]),
            user_notes
        ))
        
        # Update siblings
        for sibling in updated_siblings:
            self.conn.execute("""
                UPDATE subject_nodes 
                SET exam_weight_low = ?, exam_weight_high = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (sibling['new_weight'], sibling['new_weight'], sibling['id']))
            
            # Record sibling weight history
            self.conn.execute("""
                INSERT INTO subject_node_weights (
                    subject_node_id, weight_value, edited_by, edited_reason,
                    previous_weight, change_type, affected_siblings
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                sibling['id'],
                sibling['new_weight'],
                'system',
                f"Auto-adjusted due to node {node_id} change",
                sibling['old_weight'],
                'auto_recalculate',
                json.dumps([node_id] + [s['id'] for s in updated_siblings if s['id'] != sibling['id']])
            ))
    
    return {
        'updated_node': self.get_subject_node(node_id),
        'affected_siblings': [self.get_subject_node(s['id']) for s in updated_siblings],
        'total_updates': 1 + len(updated_siblings)
    }

def _proportional_distribution(self, siblings: List[dict], change_amount: float) -> List[dict]:
    """Distribute weight change proportionally among siblings"""
    if not siblings:
        return []
    
    # Calculate total weight of siblings
    total_weight = sum(s['weight'] for s in siblings)
    
    if total_weight == 0:
        # If all siblings are 0, distribute evenly
        return self._even_distribution(siblings, change_amount)
    
    # Calculate proportional changes
    result = []
    for sibling in siblings:
        proportion = sibling['weight'] / total_weight
        adjustment = change_amount * proportion
        new_weight = sibling['weight'] - adjustment
        
        result.append({
            'id': sibling['id'],
            'old_weight': sibling['weight'],
            'new_weight': max(0, new_weight)  # Prevent negative weights
        })
    
    return result

def _even_distribution(self, siblings: List[dict], change_amount: float) -> List[dict]:
    """Distribute weight change evenly among siblings"""
    if not siblings:
        return []
    
    per_sibling = change_amount / len(siblings)
    
    result = []
    for sibling in siblings:
        new_weight = sibling['weight'] - per_sibling
        result.append({
            'id': sibling['id'],
            'old_weight': sibling['weight'],
            'new_weight': max(0, new_weight)  # Prevent negative weights
        })
    
    return result

def _get_sibling_nodes(self, node_id: int) -> List[dict]:
    """Get sibling nodes (same parent) for weight balancing"""
    # Get parent_id
    cursor = self.conn.execute("""
        SELECT parent_id FROM subject_nodes WHERE id = ?
    """, (node_id,))
    
    row = cursor.fetchone()
    if not row or row['parent_id'] is None:
        return []
    
    parent_id = row['parent_id']
    
    # Get siblings (excluding self)
    cursor = self.conn.execute("""
        SELECT id, exam_weight_low as weight
        FROM subject_nodes
        WHERE parent_id = ? AND id != ?
    """, (parent_id, node_id))
    
    return [dict(row) for row in cursor.fetchall()]

def _validate_weight(self, weight: float, settings: dict):
    """Validate weight against settings"""
    # Range check
    if weight < 0 or weight > 100:
        raise ValidationError(f"Weight {weight}% must be between 0% and 100%")
    
    # Precision check
    precision = settings['precision_decimal_places']
    rounded = round(weight, precision)
    if abs(weight - rounded) > 1e-10:
        raise ValidationError(
            f"Weight {weight}% exceeds precision of {precision} decimal places"
        )
```

#### Task 2.3: Add Exception Types

**File**: `src/database/exceptions.py`

**Add new exceptions:**

```python
class ExamContextError(DatabaseError):
    """Raised when exam context operations fail"""
    pass

class WeightValidationError(ValidationError):
    """Raised when weight validation fails"""
    pass

class HierarchyError(DatabaseError):
    """Raised when hierarchy operations fail"""
    pass
```

---

## UI Implementation

### Stage 3: PyQt Window Setup

**Duration**: 2-3 hours

#### Task 3.1: Create Main Window

**File**: `src/ui/main_window.py`

```python
from PyQt6.QtWidgets import QMainWindow, QVBoxLayout, QWidget
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtCore import QUrl
import os

class MainWindow(QMainWindow):
    """Main application window with embedded web view"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WIMI - What I Missed It")
        self.setGeometry(100, 100, 1200, 800)
        
        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Create layout
        layout = QVBoxLayout(central_widget)
        
        # Create web view
        self.web_view = QWebEngineView()
        layout.addWidget(self.web_view)
        
        # Set up web channel for Python-JS bridge
        self.channel = QWebChannel()
        self.web_view.page().setWebChannel(self.channel)
        
        # Load initial page
        self.load_page("index.html")
        
        # Set up hot reload (F5)
        self.setup_hot_reload()
    
    def load_page(self, page_name: str):
        """Load an HTML page"""
        static_dir = os.path.join(os.path.dirname(__file__), 'static', 'html')
        page_path = os.path.join(static_dir, page_name)
        url = QUrl.fromLocalFile(page_path)
        self.web_view.setUrl(url)
    
    def setup_hot_reload(self):
        """Set up F5 key for hot reload"""
        from PyQt6.QtGui import QShortcut, QKeySequence
        
        reload_shortcut = QShortcut(QKeySequence("F5"), self)
        reload_shortcut.activated.connect(self.reload_page)
    
    def reload_page(self):
        """Reload the current page"""
        self.web_view.reload()
        print("🔄 Page reloaded")
```

### Stage 4: Python-JavaScript Bridge

**Duration**: 3-4 hours

#### Task 4.1: Create Bridge Class

**File**: `src/ui/bridge.py`

```python
from PyQt6.QtCore import QObject, pyqtSlot
from src.database import UserDatabase
import json

class Bridge(QObject):
    """Python-JavaScript bridge for database operations"""
    
    def __init__(self, user_db: UserDatabase):
        super().__init__()
        self.user_db = user_db
    
    @pyqtSlot(str, str, str, result=str)
    def createExamContext(self, exam_name: str, exam_description: str, exam_date: str) -> str:
        """
        Create a new exam context.
        
        Returns:
            JSON string with exam context data or error
        """
        try:
            from datetime import date
            
            # Parse date if provided
            exam_date_obj = date.fromisoformat(exam_date) if exam_date else None
            
            # Create exam context
            exam_context = self.user_db.create_exam_context(
                exam_name=exam_name,
                exam_description=exam_description if exam_description else None,
                exam_date=exam_date_obj
            )
            
            return json.dumps({
                'success': True,
                'data': {
                    'id': exam_context.id,
                    'exam_name': exam_context.exam_name,
                    'exam_description': exam_context.exam_description,
                    'exam_date': exam_context.exam_date.isoformat() if exam_context.exam_date else None,
                    'default_hierarchy_levels': exam_context.default_hierarchy_levels,
                    'weight_validation_rules': exam_context.weight_validation_rules
                }
            })
            
        except Exception as e:
            return json.dumps({
                'success': False,
                'error': str(e)
            })
    
    @pyqtSlot(int, result=str)
    def getExamContext(self, exam_context_id: int) -> str:
        """Get exam context by ID"""
        try:
            exam_context = self.user_db.get_exam_context(exam_context_id)
            
            if not exam_context:
                return json.dumps({
                    'success': False,
                    'error': 'Exam context not found'
                })
            
            return json.dumps({
                'success': True,
                'data': {
                    'id': exam_context.id,
                    'exam_name': exam_context.exam_name,
                    'exam_description': exam_context.exam_description,
                    'exam_date': exam_context.exam_date.isoformat() if exam_context.exam_date else None,
                    'default_hierarchy_levels': exam_context.default_hierarchy_levels,
                    'weight_validation_rules': exam_context.weight_validation_rules
                }
            })
            
        except Exception as e:
            return json.dumps({
                'success': False,
                'error': str(e)
            })
    
    @pyqtSlot(int, str, result=str)
    def updateWeightSettings(self, exam_context_id: int, settings_json: str) -> str:
        """Update weight validation rules"""
        try:
            settings = json.loads(settings_json)
            
            exam_context = self.user_db.update_exam_context_settings(
                exam_context_id=exam_context_id,
                weight_validation_rules=settings
            )
            
            return json.dumps({
                'success': True,
                'data': {
                    'weight_validation_rules': exam_context.weight_validation_rules
                }
            })
            
        except Exception as e:
            return json.dumps({
                'success': False,
                'error': str(e)
            })
    
    @pyqtSlot(int, float, str, result=str)
    def updateNodeWeight(self, node_id: int, new_weight: float, reason: str) -> str:
        """Update subject node weight"""
        try:
            result = self.user_db.update_subject_node_weight(
                node_id=node_id,
                new_weight=new_weight,
                reason=reason if reason else None
            )
            
            return json.dumps({
                'success': True,
                'data': {
                    'total_updates': result['total_updates'],
                    'affected_sibling_ids': [s.id for s in result['affected_siblings']]
                }
            })
            
        except Exception as e:
            return json.dumps({
                'success': False,
                'error': str(e)
            })
```

#### Task 4.2: Create JavaScript API Wrapper

**File**: `src/ui/static/js/api.js`

```javascript
/**
 * JavaScript API wrapper for Python bridge
 * Provides promise-based interface to backend
 */

class API {
    constructor() {
        this.bridge = null;
        this.ready = false;
        
        // Wait for Qt WebChannel
        if (typeof QWebChannel !== 'undefined') {
            new QWebChannel(qt.webChannelTransport, (channel) => {
                this.bridge = channel.objects.bridge;
                this.ready = true;
                console.log('✅ Bridge connected');
            });
        }
    }
    
    /**
     * Wait for bridge to be ready
     */
    async waitForReady() {
        while (!this.ready) {
            await new Promise(resolve => setTimeout(resolve, 100));
        }
    }
    
    /**
     * Create a new exam context
     */
    async createExamContext(examName, examDescription, examDate) {
        await this.waitForReady();
        
        return new Promise((resolve, reject) => {
            this.bridge.createExamContext(
                examName,
                examDescription || '',
                examDate || '',
                (resultJson) => {
                    const result = JSON.parse(resultJson);
                    if (result.success) {
                        resolve(result.data);
                    } else {
                        reject(new Error(result.error));
                    }
                }
            );
        });
    }
    
    /**
     * Get exam context by ID
     */
    async getExamContext(examContextId) {
        await this.waitForReady();
        
        return new Promise((resolve, reject) => {
            this.bridge.getExamContext(examContextId, (resultJson) => {
                const result = JSON.parse(resultJson);
                if (result.success) {
                    resolve(result.data);
                } else {
                    reject(new Error(result.error));
                }
            });
        });
    }
    
    /**
     * Update weight validation settings
     */
    async updateWeightSettings(examContextId, settings) {
        await this.waitForReady();
        
        return new Promise((resolve, reject) => {
            this.bridge.updateWeightSettings(
                examContextId,
                JSON.stringify(settings),
                (resultJson) => {
                    const result = JSON.parse(resultJson);
                    if (result.success) {
                        resolve(result.data);
                    } else {
                        reject(new Error(result.error));
                    }
                }
            );
        });
    }
    
    /**
     * Update subject node weight
     */
    async updateNodeWeight(nodeId, newWeight, reason) {
        await this.waitForReady();
        
        return new Promise((resolve, reject) => {
            this.bridge.updateNodeWeight(
                nodeId,
                newWeight,
                reason || '',
                (resultJson) => {
                    const result = JSON.parse(resultJson);
                    if (result.success) {
                        resolve(result.data);
                    } else {
                        reject(new Error(result.error));
                    }
                }
            );
        });
    }
}

// Global API instance
const api = new API();
```

### Stage 5: Exam Wizard UI

**Duration**: 6-8 hours

#### Task 5.1: Create Wizard HTML

**File**: `src/ui/static/html/exam_wizard.html`

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Exam Setup Wizard</title>
    <link rel="stylesheet" href="../css/styles.css">
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <script src="../js/api.js"></script>
</head>
<body>
    <div class="wizard-container">
        <div class="wizard-header">
            <h1>📚 Exam Setup Wizard</h1>
            <p>Let's set up your first exam!</p>
        </div>
        
        <div class="wizard-progress">
            <div class="step active" data-step="1">
                <span class="step-number">1</span>
                <span class="step-label">Exam Info</span>
            </div>
            <div class="step" data-step="2">
                <span class="step-number">2</span>
                <span class="step-label">Hierarchy Levels</span>
            </div>
            <div class="step" data-step="3">
                <span class="step-number">3</span>
                <span class="step-label">Weight Settings</span>
            </div>
            <div class="step" data-step="4">
                <span class="step-number">4</span>
                <span class="step-label">Summary</span>
            </div>
        </div>
        
        <!-- Step 1: Exam Information -->
        <div class="wizard-step" id="step-1">
            <h2>Exam Information</h2>
            
            <div class="form-group">
                <label for="exam-name">Exam Name *</label>
                <input type="text" id="exam-name" placeholder="e.g., USMLE Step 1, SAT" required>
                <span class="help-text">The standardized exam you're preparing for</span>
            </div>
            
            <div class="form-group">
                <label for="exam-description">Description (Optional)</label>
                <textarea id="exam-description" rows="3" placeholder="Brief description of your exam goals"></textarea>
            </div>
            
            <div class="form-group">
                <label for="exam-date">Exam Date (Optional)</label>
                <input type="date" id="exam-date">
                <span class="help-text">When are you planning to take the exam?</span>
            </div>
        </div>
        
        <!-- Step 2: Hierarchy Levels -->
        <div class="wizard-step hidden" id="step-2">
            <h2>Hierarchy Levels</h2>
            <p>Your subject outline will use these hierarchy levels. The first 3 are always present.</p>
            
            <div class="hierarchy-levels">
                <div class="level-item required">
                    <span class="level-order">1</span>
                    <input type="text" value="System" readonly class="level-name">
                    <span class="required-badge">Required</span>
                </div>
                <div class="level-item required">
                    <span class="level-order">2</span>
                    <input type="text" value="Subsystem" readonly class="level-name">
                    <span class="required-badge">Required</span>
                </div>
                <div class="level-item required">
                    <span class="level-order">3</span>
                    <input type="text" value="Topic" readonly class="level-name">
                    <span class="required-badge">Required</span>
                </div>
                <div class="level-item">
                    <span class="level-order">4</span>
                    <input type="text" value="Subtopic" readonly class="level-name">
                    <span class="optional-badge">Optional</span>
                </div>
                <div class="level-item">
                    <span class="level-order">5</span>
                    <input type="text" value="Child" readonly class="level-name">
                    <span class="optional-badge">Optional</span>
                </div>
            </div>
            
            <p class="info-message">
                ℹ️ You can add deeper levels later if needed. They'll be displayed as "Daughter of [Parent Name]"
            </p>
        </div>
        
        <!-- Step 3: Weight Settings -->
        <div class="wizard-step hidden" id="step-3">
            <h2>Weight Calculation Settings</h2>
            
            <div class="setting-group">
                <div class="setting-header">
                    <h3>Autonomous Weight Balancing</h3>
                    <label class="toggle">
                        <input type="checkbox" id="autonomous-balancing" checked>
                        <span class="slider"></span>
                    </label>
                </div>
                <p class="setting-description">
                    When enabled, editing one child's weight automatically adjusts siblings to maintain 100%.
                    When disabled, you'll manually balance weights and see both relative and absolute percentages.
                </p>
            </div>
            
            <div class="setting-group">
                <div class="setting-header">
                    <h3>Weight Precision</h3>
                    <select id="precision">
                        <option value="0">Whole numbers (40%, 60%)</option>
                        <option value="1" selected>One decimal (40.5%, 59.5%)</option>
                        <option value="2">Two decimals (40.25%, 59.75%)</option>
                    </select>
                </div>
                <p class="setting-description">
                    How precise should weight percentages be?
                </p>
            </div>
            
            <div class="setting-group">
                <div class="setting-header">
                    <h3>Balancing Algorithm</h3>
                    <select id="algorithm">
                        <option value="proportional" selected>Proportional (Recommended)</option>
                        <option value="even">Even Distribution</option>
                    </select>
                </div>
                <p class="setting-description">
                    <strong>Proportional:</strong> Distributes changes based on current sibling weights (prevents zeros)<br>
                    <strong>Even:</strong> Distributes changes equally across all siblings (simpler)
                </p>
            </div>
        </div>
        
        <!-- Step 4: Summary -->
        <div class="wizard-step hidden" id="step-4">
            <h2>Summary</h2>
            <p>Review your settings before creating the exam context.</p>
            
            <div class="summary-section">
                <h3>Exam Information</h3>
                <div class="summary-item">
                    <span class="label">Name:</span>
                    <span class="value" id="summary-name"></span>
                </div>
                <div class="summary-item">
                    <span class="label">Description:</span>
                    <span class="value" id="summary-description"></span>
                </div>
                <div class="summary-item">
                    <span class="label">Exam Date:</span>
                    <span class="value" id="summary-date"></span>
                </div>
            </div>
            
            <div class="summary-section">
                <h3>Hierarchy Levels</h3>
                <div class="summary-item">
                    <span class="value">System → Subsystem → Topic → Subtopic → Child</span>
                </div>
            </div>
            
            <div class="summary-section">
                <h3>Weight Settings</h3>
                <div class="summary-item">
                    <span class="label">Autonomous Balancing:</span>
                    <span class="value" id="summary-balancing"></span>
                </div>
                <div class="summary-item">
                    <span class="label">Precision:</span>
                    <span class="value" id="summary-precision"></span>
                </div>
                <div class="summary-item">
                    <span class="label">Algorithm:</span>
                    <span class="value" id="summary-algorithm"></span>
                </div>
            </div>
        </div>
        
        <!-- Navigation Buttons -->
        <div class="wizard-nav">
            <button id="btn-back" class="btn-secondary" disabled>← Back</button>
            <button id="btn-next" class="btn-primary">Next →</button>
            <button id="btn-finish" class="btn-success hidden">Create Exam</button>
        </div>
        
        <!-- Loading Indicator -->
        <div id="loading" class="hidden">
            <div class="spinner"></div>
            <p>Creating your exam context...</p>
        </div>
    </div>
    
    <script src="../js/exam_wizard.js"></script>
</body>
</html>
```

#### Task 5.2: Create Wizard JavaScript

**File**: `src/ui/static/js/exam_wizard.js`

```javascript
/**
 * Exam Setup Wizard Logic
 */

class ExamWizard {
    constructor() {
        this.currentStep = 1;
        this.totalSteps = 4;
        this.examData = {};
        
        this.setupEventListeners();
    }
    
    setupEventListeners() {
        // Navigation buttons
        document.getElementById('btn-next').addEventListener('click', () => this.nextStep());
        document.getElementById('btn-back').addEventListener('click', () => this.prevStep());
        document.getElementById('btn-finish').addEventListener('click', () => this.finish());
        
        // Form validation
        document.getElementById('exam-name').addEventListener('input', () => this.validateCurrentStep());
    }
    
    async nextStep() {
        if (!this.validateCurrentStep()) {
            return;
        }
        
        this.saveCurrentStepData();
        
        if (this.currentStep < this.totalSteps) {
            this.currentStep++;
            this.updateUI();
            
            if (this.currentStep === 4) {
                this.updateSummary();
            }
        }
    }
    
    prevStep() {
        if (this.currentStep > 1) {
            this.currentStep--;
            this.updateUI();
        }
    }
    
    validateCurrentStep() {
        switch (this.currentStep) {
            case 1:
                const examName = document.getElementById('exam-name').value.trim();
                return examName.length > 0;
            case 2:
            case 3:
                return true;
            default:
                return true;
        }
    }
    
    saveCurrentStepData() {
        switch (this.currentStep) {
            case 1:
                this.examData.examName = document.getElementById('exam-name').value.trim();
                this.examData.examDescription = document.getElementById('exam-description').value.trim();
                this.examData.examDate = document.getElementById('exam-date').value;
                break;
            case 3:
                this.examData.weightSettings = {
                    autonomous_weight_balancing: document.getElementById('autonomous-balancing').checked,
                    allow_absolute_weight_editing: false,
                    precision_decimal_places: parseInt(document.getElementById('precision').value),
                    require_exact_100: true,
                    balancing_algorithm: document.getElementById('algorithm').value
                };
                break;
        }
    }
    
    updateUI() {
        // Hide all steps
        document.querySelectorAll('.wizard-step').forEach(step => {
            step.classList.add('hidden');
        });
        
        // Show current step
        document.getElementById(`step-${this.currentStep}`).classList.remove('hidden');
        
        // Update progress indicators
        document.querySelectorAll('.step').forEach(step => {
            const stepNum = parseInt(step.dataset.step);
            if (stepNum <= this.currentStep) {
                step.classList.add('active');
            } else {
                step.classList.remove('active');
            }
        });
        
        // Update navigation buttons
        document.getElementById('btn-back').disabled = this.currentStep === 1;
        
        if (this.currentStep === this.totalSteps) {
            document.getElementById('btn-next').classList.add('hidden');
            document.getElementById('btn-finish').classList.remove('hidden');
        } else {
            document.getElementById('btn-next').classList.remove('hidden');
            document.getElementById('btn-finish').classList.add('hidden');
        }
    }
    
    updateSummary() {
        document.getElementById('summary-name').textContent = this.examData.examName;
        document.getElementById('summary-description').textContent = this.examData.examDescription || 'None';
        document.getElementById('summary-date').textContent = this.examData.examDate || 'Not set';
        
        document.getElementById('summary-balancing').textContent = 
            this.examData.weightSettings.autonomous_weight_balancing ? 'Enabled' : 'Disabled';
        
        const precisionLabels = {0: 'Whole numbers', 1: 'One decimal', 2: 'Two decimals'};
        document.getElementById('summary-precision').textContent = 
            precisionLabels[this.examData.weightSettings.precision_decimal_places];
        
        const algorithmLabels = {proportional: 'Proportional (Recommended)', even: 'Even Distribution'};
        document.getElementById('summary-algorithm').textContent = 
            algorithmLabels[this.examData.weightSettings.balancing_algorithm];
    }
    
    async finish() {
        // Show loading
        document.getElementById('loading').classList.remove('hidden');
        document.querySelector('.wizard-nav').style.display = 'none';
        
        try {
            // Create exam context via API
            const result = await api.createExamContext(
                this.examData.examName,
                this.examData.examDescription,
                this.examData.examDate
            );
            
            // Update weight settings
            await api.updateWeightSettings(
                result.id,
                this.examData.weightSettings
            );
            
            // Success!
            alert(`✅ Exam context "${this.examData.examName}" created successfully!`);
            
            // TODO: Navigate to main app
            
        } catch (error) {
            // Hide loading
            document.getElementById('loading').classList.add('hidden');
            document.querySelector('.wizard-nav').style.display = 'flex';
            
            alert(`❌ Error creating exam context: ${error.message}`);
        }
    }
}

// Initialize wizard when page loads
document.addEventListener('DOMContentLoaded', () => {
    new ExamWizard();
});
```

---

## Testing Strategy

### Stage 7: Testing

**Duration**: 4-6 hours

#### Task 7.1: Database Tests

**File**: `tests/database/test_user_db_phase2.py`

```python
import pytest
from datetime import date
from src.database import UserDatabase
from src.database.exceptions import ValidationError

def test_create_exam_context(user_db):
    """Test creating exam context with default settings"""
    exam = user_db.create_exam_context(
        exam_name="USMLE Step 1",
        exam_description="Medical licensing exam"
    )
    
    assert exam.exam_name == "USMLE Step 1"
    assert exam.is_active is True
    assert len(exam.default_hierarchy_levels) == 5
    assert exam.weight_validation_rules['autonomous_weight_balancing'] is True

def test_create_duplicate_exam_context(user_db):
    """Test creating duplicate exam context raises error"""
    user_db.create_exam_context(exam_name="SAT")
    
    with pytest.raises(ValidationError):
        user_db.create_exam_context(exam_name="SAT")

def test_proportional_weight_balancing(user_db):
    """Test proportional weight distribution"""
    # Create exam context
    exam = user_db.create_exam_context(exam_name="Test Exam")
    
    # Create parent node
    root = user_db.create_subject_node(
        exam_context="Test Exam",
        name="Root",
        level_type="Root",
        exam_weight_low=100.0,
        exam_weight_high=100.0
    )
    
    # Create 3 children with equal weights
    child1 = user_db.create_subject_node(
        exam_context="Test Exam",
        name="Child 1",
        parent_id=root.id,
        level_type="System",
        exam_weight_low=33.3,
        exam_weight_high=33.3
    )
    
    child2 = user_db.create_subject_node(
        exam_context="Test Exam",
        name="Child 2",
        parent_id=root.id,
        level_type="System",
        exam_weight_low=33.3,
        exam_weight_high=33.3
    )
    
    child3 = user_db.create_subject_node(
        exam_context="Test Exam",
        name="Child 3",
        parent_id=root.id,
        level_type="System",
        exam_weight_low=33.4,
        exam_weight_high=33.4
    )
    
    # Update child1 to 50%
    result = user_db.update_subject_node_weight(
        node_id=child1.id,
        new_weight=50.0,
        reason="Test proportional balancing"
    )
    
    # Check results
    assert result['total_updates'] == 3
    assert len(result['affected_siblings']) == 2
    
    # Verify proportional distribution
    updated_child2 = user_db.get_subject_node(child2.id)
    updated_child3 = user_db.get_subject_node(child3.id)
    
    # child2 and child3 should split the -16.7% proportionally
    # Original: child2=33.3, child3=33.4, total=66.7
    # child2 proportion: 33.3/66.7 ≈ 0.499
    # child3 proportion: 33.4/66.7 ≈ 0.501
    # child2 new: 33.3 - (16.7 * 0.499) ≈ 25.0
    # child3 new: 33.4 - (16.7 * 0.501) ≈ 25.0
    
    assert abs(updated_child2.exam_weight_low - 25.0) < 0.5
    assert abs(updated_child3.exam_weight_low - 25.0) < 0.5
```

---

## Timeline Estimate

### Optimistic Timeline (Full-time Development)

| Stage | Duration | Tasks |
|-------|----------|-------|
| **Stage 1: Database Schema** | 2-3 hours | Create schema files, migration script |
| **Stage 2: Python Backend** | 4-6 hours | Add models, CRUD methods, weight algorithms |
| **Stage 3: PyQt Window** | 2-3 hours | Main window, web view setup |
| **Stage 4: Bridge** | 3-4 hours | Python bridge, JS API wrapper |
| **Stage 5: Wizard UI** | 6-8 hours | HTML, CSS, JavaScript wizard |
| **Stage 6: Weight Engine** | 3-4 hours | Weight calculation, validation |
| **Stage 7: Testing** | 4-6 hours | Unit tests, integration tests |
| **Documentation** | 2-3 hours | Update docs, examples |
| **Total** | **26-37 hours** | **~4-5 days full-time** |

### Realistic Timeline (Part-time Development)

- **2-3 weeks** at 10-15 hours per week
- Includes debugging, iteration, polish

---

## Success Criteria

Phase 2 is complete when:

✅ All 3 new database tables created and tested  
✅ UserDatabase class has all Phase 2 methods  
✅ PyQt window loads with web view  
✅ Python-JavaScript bridge functional  
✅ Exam wizard creates exam contexts successfully  
✅ Weight balancing works with proportional algorithm  
✅ Test coverage >90% for new code  
✅ Documentation updated  
✅ Hot reload (F5) works  

---

## Next Steps After Phase 2

Once Phase 2 is complete, we'll move to:

**Phase 3: Outline Building & Hierarchy Editor**
- Visual tree editor
- Import/export JSON outlines
- Drag-and-drop node organization
- Weight editing interface

---

**Document Version:** 1.0  
**Last Updated:** November 8, 2025  
**Related Documents:**
- `completed_database_tables.md` - Database schema
- `PHASE2_JSON_EXAMPLES.md` - JSON structure examples
- `Claude_Project_WIMI_context.md` - Project overview
