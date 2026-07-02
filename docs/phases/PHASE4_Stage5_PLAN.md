# Phase 4 Stage 5: Media Handling - Implementation Plan

**Status:** 📋 Ready for Implementation  
**Estimated Duration:** 4-6 hours  
**Created:** December 27, 2025

---

## Overview

Stage 5 implements media attachment functionality for question entries, allowing users to paste, drag-drop, or browse for images to attach to their logged questions.

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Storage | File system | Keeps database lean, easier large file management |
| Image display | Custom URL scheme | Secure, proper solution for QWebEngineView |
| Transfer method | Base64 | Simple for typical screenshot sizes (<1MB) |
| Thumbnail size | 120x120 pixels | Good balance of visibility and space |
| Full-size view | Modal overlay | Keeps user in context |

**TODO (Future):** Implement temp file + path transfer for large files (>5MB)

---

## Storage Structure

```
app_data/
└── media/
    └── user_{id}_{username}/
        └── entry_{entry_id}/
            ├── {uuid1}.png
            ├── {uuid2}.jpg
            └── metadata.json  # Optional: tracks original filenames
```

---

## Implementation Tasks

### 5.1: Backend - MediaManager Class (~1.5 hours)

**File:** `src/app/media_manager.py` (NEW)

```python
class MediaManager:
    """Handles media file storage and retrieval"""
    
    def __init__(self, base_path: Path, user_id: int, username: str):
        self.base_path = base_path / "media" / f"user_{user_id}_{username}"
    
    def save_media(self, entry_id: int, data: bytes, filename: str, mime_type: str) -> MediaInfo
    def get_media(self, entry_id: int) -> List[MediaInfo]
    def get_media_path(self, file_uuid: str) -> Optional[Path]
    def rename_media(self, media_id: int, new_name: str) -> bool
    def delete_media(self, media_id: int) -> bool
    def reorder_media(self, entry_id: int, order: List[int]) -> bool
```

**Features:**
- UUID-based file naming (prevents conflicts)
- MIME type validation
- Thumbnail generation (using Pillow)
- Metadata tracking in database

---

### 5.2: Custom URL Scheme Handler (~1 hour)

**File:** `src/app/media_scheme_handler.py` (NEW)

```python
from PyQt6.QtWebEngineCore import QWebEngineUrlSchemeHandler, QWebEngineUrlRequestJob

class MediaSchemeHandler(QWebEngineUrlSchemeHandler):
    """Serves media files via wimi-media:// URL scheme"""
    
    def __init__(self, media_manager: MediaManager):
        super().__init__()
        self.media_manager = media_manager
    
    def requestStarted(self, request: QWebEngineUrlRequestJob):
        # Parse URL: wimi-media://entry_123/uuid.png
        # Serve file from media_manager.get_media_path()
```

**File:** `src/app/main_window.py` (MODIFY)

```python
# Register scheme at startup
from PyQt6.QtWebEngineCore import QWebEngineUrlScheme

# Must be called before QApplication
scheme = QWebEngineUrlScheme(b"wimi-media")
scheme.setFlags(QWebEngineUrlScheme.Flag.SecureScheme | 
                QWebEngineUrlScheme.Flag.LocalAccessAllowed)
QWebEngineUrlScheme.registerScheme(scheme)
```

---

### 5.3: Bridge Methods (~0.5 hours)

**File:** `src/app/bridge.py` (MODIFY)

```python
@pyqtSlot(int, str, str, str, result=str)
def addQuestionMedia(self, entry_id: int, base64_data: str, filename: str, mime_type: str) -> str:
    """Add media to a question entry"""

@pyqtSlot(int, result=str)
def getQuestionMedia(self, entry_id: int) -> str:
    """Get all media for a question entry"""

@pyqtSlot(int, str, result=str)
def renameMedia(self, media_id: int, new_name: str) -> str:
    """Rename a media file"""

@pyqtSlot(int, result=str)
def deleteMedia(self, media_id: int) -> str:
    """Delete a media file"""

@pyqtSlot(int, str, result=str)
def reorderMedia(self, entry_id: int, order_json: str) -> str:
    """Reorder media files"""
```

---

### 5.4: Database Methods (~0.5 hours)

**File:** `src/database/user_db.py` (MODIFY)

The `entry_media` table already exists from Stage 1. Add methods:

```python
def add_entry_media(self, entry_id: int, file_uuid: str, original_filename: str,
                    user_filename: str, mime_type: str, file_size: int) -> EntryMedia

def get_entry_media(self, entry_id: int) -> List[EntryMedia]

def update_media_filename(self, media_id: int, new_name: str) -> EntryMedia

def delete_entry_media(self, media_id: int) -> bool

def reorder_entry_media(self, entry_id: int, media_ids: List[int]) -> bool
```

---

### 5.5: Frontend - Upload UI (~1.5 hours)

**File:** `src/web/js/media_upload.js` (NEW)

```javascript
class MediaUpload {
    constructor(container, options = {}) {
        this.container = container;
        this.entryId = options.entryId;
        this.onUpload = options.onUpload;
        this.onDelete = options.onDelete;
        
        this.init();
    }
    
    init() {
        this.createDropZone();
        this.setupPasteHandler();
        this.setupDragDrop();
    }
    
    // Clipboard paste (Ctrl+V)
    handlePaste(event) { }
    
    // Drag and drop
    handleDrop(event) { }
    
    // File picker
    handleFileSelect(files) { }
    
    // Upload file via bridge
    async uploadFile(file) { }
    
    // Render thumbnail grid
    renderThumbnails(mediaList) { }
}
```

**Features:**
- Drop zone with visual feedback
- Paste handler for Ctrl+V
- File input for browse
- Upload progress indicator
- Error handling for invalid files

---

### 5.6: Frontend - Thumbnail Grid & Modal (~1 hour)

**File:** `src/web/js/media_upload.js` (continued)

```javascript
// Thumbnail grid
renderThumbnails(mediaList) {
    // 120x120 thumbnails in grid
    // Each has: image, filename, edit button, delete button
}

// Full-size modal
showFullSize(mediaItem) {
    // Modal overlay with full image
    // Close on click outside or Escape
}

// Rename modal
showRenameModal(mediaItem) {
    // Input for new filename
    // Save/Cancel buttons
}

// Delete confirmation
confirmDelete(mediaItem) {
    // "Are you sure?" modal
}

// Sort by name
sortByName() {
    // Alphabetical sort, update order in DB
}
```

**File:** `src/web/css/media.css` (NEW)

```css
/* Drop zone styles */
.media-dropzone { }
.media-dropzone.dragover { }

/* Thumbnail grid */
.media-grid { }
.media-thumbnail { }
.media-thumbnail img { }
.media-thumbnail .actions { }

/* Full-size modal */
.media-modal { }
.media-modal-content { }

/* Rename modal */
.rename-modal { }
```

---

### 5.7: Integration with Question Entry (~0.5 hours)

**File:** `src/web/js/question_entry.js` (MODIFY)

```javascript
// In Section F initialization
function initMediaSection() {
    const container = document.getElementById('media-container');
    
    EntryState.mediaUpload = new MediaUpload(container, {
        entryId: EntryState.currentEntry?.id,
        onUpload: handleMediaUpload,
        onDelete: handleMediaDelete
    });
}

// Load existing media when entry loads
async function loadEntryMedia(entryId) {
    const media = await api.getQuestionMedia(entryId);
    EntryState.mediaUpload.renderThumbnails(media);
}

// Include media in save
function collectFormData() {
    // Media is saved immediately on upload
    // Just need to refresh after save
}
```

**File:** `src/web/html/question_entry.html` (MODIFY)

```html
<!-- In Section F -->
<div class="media-section">
    <div id="media-dropzone" class="media-dropzone">
        <span class="dropzone-icon">📎</span>
        <span class="dropzone-text">Drop images here, paste (Ctrl+V), or</span>
        <button type="button" class="btn btn-secondary btn-sm" id="media-browse">
            Browse...
        </button>
        <input type="file" id="media-file-input" multiple accept="image/*" hidden>
    </div>
    
    <div id="media-grid" class="media-grid"></div>
    
    <button type="button" class="btn btn-ghost btn-sm" id="media-sort">
        Sort by Name
    </button>
</div>
```

---

## File Summary

| File | Action | Description |
|------|--------|-------------|
| `src/app/media_manager.py` | CREATE | Media storage and retrieval |
| `src/app/media_scheme_handler.py` | CREATE | Custom URL scheme for images |
| `src/app/main_window.py` | MODIFY | Register URL scheme |
| `src/app/bridge.py` | MODIFY | Add media bridge methods |
| `src/database/user_db.py` | MODIFY | Add media database methods |
| `src/web/js/media_upload.js` | CREATE | Upload component |
| `src/web/css/media.css` | CREATE | Media styles |
| `src/web/js/question_entry.js` | MODIFY | Integrate media component |
| `src/web/html/question_entry.html` | MODIFY | Add media section HTML |

---

## Supported Formats

| Format | MIME Type | Extension |
|--------|-----------|-----------|
| PNG | image/png | .png |
| JPEG | image/jpeg | .jpg, .jpeg |
| GIF | image/gif | .gif |
| WebP | image/webp | .webp |
| BMP | image/bmp | .bmp |
| SVG | image/svg+xml | .svg |

---

## Implementation Order

```
1. MediaManager class (storage layer)
   ↓
2. Database methods (metadata layer)
   ↓
3. URL scheme handler (display layer)
   ↓
4. Bridge methods (communication layer)
   ↓
5. Frontend upload component (UI layer)
   ↓
6. Frontend thumbnail/modal (display layer)
   ↓
7. Integration with question entry
   ↓
8. Testing
```

---

## Testing Checklist

### Upload Tests
- [ ] Paste image from clipboard (Ctrl+V)
- [ ] Drag and drop single image
- [ ] Drag and drop multiple images
- [ ] Browse and select files
- [ ] Upload shows progress
- [ ] Invalid file type rejected
- [ ] Large file handled (>5MB warning?)

### Display Tests
- [ ] Thumbnails display at 120x120
- [ ] Click thumbnail opens full-size modal
- [ ] Modal closes on click outside
- [ ] Modal closes on Escape key
- [ ] Images load via wimi-media:// scheme

### Action Tests
- [ ] Rename updates filename
- [ ] Delete removes file and thumbnail
- [ ] Sort by name reorders grid
- [ ] Changes persist after page reload

### Edge Cases
- [ ] No media attached (empty state)
- [ ] Entry without ID (new entry draft)
- [ ] Network error during upload
- [ ] File system permission error

---

## Dependencies

- **Pillow**: For thumbnail generation (may need to install)
  ```bash
  pip install Pillow
  ```

---

## Notes

1. **Immediate upload**: Files are uploaded as soon as added, not on form save
2. **Draft entries**: Need to handle media for entries that don't have an ID yet (save as draft first?)
3. **Orphan cleanup**: Consider cleanup job for media without associated entries

---

**Ready to begin implementation?**
