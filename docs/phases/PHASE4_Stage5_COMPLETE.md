# Phase 4 Stage 5: Media Handling - COMPLETE

**Status:** ✅ Complete  
**Completed:** December 27, 2025  
**Duration:** ~6 hours (including debugging)

---

## Summary

Stage 5 implements comprehensive media attachment functionality for question entries, allowing users to paste, drag-drop, or browse for images to attach to their logged questions. Images are stored on the file system with UUID-based naming, thumbnails are auto-generated, and display uses base64 data URLs for reliable cross-platform rendering.

---

## Files Created

| File | Description |
|------|-------------|
| `src/app/media_manager.py` | Media file storage, thumbnail generation, base64 retrieval |
| `src/app/media_scheme_handler.py` | Custom `wimi-media://` URL scheme registration (backup method) |
| `src/web/js/media_upload.js` | Frontend upload component with full UI and inline styles |
| `src/web/css/media.css` | Media component styles (supplementary) |

---

## Files Modified

| File | Changes |
|------|---------|
| `src/app/main.py` | Register `wimi-media://` URL scheme before QApplication |
| `src/app/main_window.py` | Initialize MediaManager, install scheme handler |
| `src/app/bridge.py` | Add 5 media bridge methods + `_get_media_data_url` helper |
| `src/database/user_db.py` | Add 4 media database methods |
| `src/web/js/api.js` | Add 5 media API methods in WIMIApi class + MockBridge |
| `src/web/js/question_entry.js` | Integrate MediaUpload component |
| `src/web/html/question_entry.html` | Add media container and script/css links |
| `requirements.txt` | Add Pillow>=10.0.0 |

---

## Features Implemented

### Backend Features

| Feature | Implementation |
|---------|----------------|
| File system storage | UUID-based naming in `app_data/media/user_{id}_{username}/entry_{id}/` |
| Thumbnail generation | 120x120 JPEG via Pillow with aspect ratio preservation |
| MIME type validation | PNG, JPEG, GIF, WebP, BMP, SVG |
| Magic byte detection | Auto-detect format from file headers |
| Base64 data URLs | Primary display method for reliable rendering |
| Database metadata | Track file UUID, original filename, user filename, size, sort order |

### Frontend Features

| Feature | Implementation |
|---------|----------------|
| Clipboard paste (Ctrl+V) | Global paste handler when component visible |
| Drag and drop | Drop zone with visual feedback |
| File picker | Browse button triggers file input |
| Upload progress | Visual indicator during upload |
| Thumbnail grid | Auto-fill grid with inline-styled thumbnails |
| Action buttons | SVG icons for view/rename/delete (inline styles) |
| Full-size modal | Click to view, close on Escape or backdrop click |
| Rename modal | Edit user filename, preserves extension |
| Delete confirmation | Modal with cancel/confirm |
| Sort by name | Alphabetical sorting with database persistence |

### Bridge Methods Added

| Method | Parameters | Returns |
|--------|------------|---------|
| `addQuestionMedia` | entry_id, base64_data, filename, mime_type | Media info with data URLs |
| `getQuestionMedia` | entry_id | Array of media items with data URLs |
| `renameMedia` | media_id, new_name | Updated media info |
| `deleteMedia` | entry_id, media_id | Success status |
| `reorderMedia` | entry_id, order_json | Success status |

### Database Methods Added

| Method | Description |
|--------|-------------|
| `add_entry_media` | Create new media record for entry |
| `get_media_by_id` | Get EntryMedia by ID |
| `get_entry_media_list` | Get all media for entry ordered by sort_order |
| `update_media_filename` | Update user-defined filename |
| `delete_entry_media` | Delete media record |
| `reorder_entry_media` | Update sort order for multiple items |

---

## Architecture

### Storage Structure

```
app_data/
└── media/
    └── user_{id}_{username}/
        └── entry_{entry_id}/
            ├── {uuid1}.png          # Original image
            ├── {uuid1}_thumb.jpg    # 120x120 thumbnail
            ├── {uuid2}.jpg
            └── {uuid2}_thumb.jpg
```

### Display Method

Images are displayed using **base64 data URLs** for maximum compatibility:

```
data:image/jpeg;base64,/9j/4AAQSkZJRgABAQ...
```

This approach was chosen after discovering that custom URL schemes (`wimi-media://`) have cross-platform permission issues in QWebEngineView.

### Data Flow

1. **Upload**: 
   - File → FileReader (base64) → Bridge → MediaManager 
   - MediaManager saves to disk + generates thumbnail
   - Database stores metadata
   - Returns data URLs for immediate display

2. **Display**: 
   - Bridge calls `_get_media_data_url()` 
   - MediaManager reads file as base64
   - Returns complete data URL string
   - Browser renders inline

3. **Delete**: 
   - Bridge → MediaManager (deletes files from disk)
   - Database record removed

---

## Technical Details

### MediaManager Class

```python
class MediaManager:
    def __init__(base_path, user_id, username)
    
    # Storage
    def save_media_from_base64(entry_id, base64_data, filename, mime_type) -> MediaInfo
    def save_media_from_bytes(entry_id, data, filename, mime_type) -> MediaInfo
    
    # Retrieval
    def get_media_path(entry_id, file_uuid) -> Optional[Path]
    def get_thumbnail_path(entry_id, file_uuid) -> Optional[Path]
    def get_file_as_base64(entry_id, file_uuid) -> Optional[str]  # Returns data URL
    def get_thumbnail_as_base64(entry_id, file_uuid) -> Optional[str]  # Returns data URL
    
    # Management
    def delete_media(entry_id, file_uuid) -> bool
    def delete_entry_media(entry_id) -> int  # Delete all for entry
    def cleanup_orphaned_media(valid_entry_ids) -> int
```

### MediaUpload JavaScript Class

```javascript
class MediaUpload {
    constructor(container, options)  // options: entryId, onUpload, onDelete, onError
    
    // Core methods
    init()
    render()  // Creates HTML with inline styles
    setupEventListeners()
    
    // Upload handling
    handlePaste(event)
    handleFiles(files)
    uploadFile(file) -> Promise
    
    // Display
    setEntryId(entryId)
    loadMedia(entryId)
    renderThumbnails()  // Uses inline styles for reliability
    truncateFilename(filename, maxLength)
    
    // Modals
    showFullModal(item)
    closeFullModal()
    showRenameModal(item)
    closeRenameModal()
    saveRename()
    showDeleteModal(item)
    closeDeleteModal()
    confirmDelete()
    
    // Actions
    sortByName()
    getMediaItems()
    clear()
    destroy()
}
```

### Inline Styles Approach

Due to CSS loading issues in QWebEngineView, all critical styles are applied inline in JavaScript:

```javascript
const thumbnailHtml = `
    <div class="thumbnail-image-container" 
         style="width: 100%; height: 120px; display: flex; ...">
        <img src="${item.thumbnail_url}" style="max-width: 100%; ...">
    </div>
    <div class="thumbnail-actions" 
         style="position: absolute; top: 4px; right: 4px; ...">
        <button style="width: 26px; height: 26px; ...">
            <svg>...</svg>
        </button>
    </div>
`;
```

---

## API Response Format

### addQuestionMedia Response
```json
{
    "success": true,
    "data": {
        "id": 1,
        "file_uuid": "abc-123-def",
        "original_filename": "screenshot.png",
        "user_filename": "screenshot.png",
        "mime_type": "image/png",
        "file_size": 45678,
        "thumbnail_url": "data:image/jpeg;base64,...",
        "full_url": "data:image/png;base64,..."
    }
}
```

### getQuestionMedia Response
```json
{
    "success": true,
    "data": [
        {
            "id": 1,
            "file_uuid": "abc-123-def",
            "original_filename": "screenshot.png",
            "user_filename": "my-image.png",
            "mime_type": "image/png",
            "file_size": 45678,
            "sort_order": 1,
            "thumbnail_url": "data:image/jpeg;base64,...",
            "full_url": "data:image/png;base64,..."
        }
    ]
}
```

---

## Known Limitations

1. **Base64 size**: Large images increase response size. Typical screenshots (<1MB) work well. For very large files (>5MB), consider implementing chunked transfer or temp file paths.

2. **No file size limits**: Currently no enforced limits on file size or count per entry.

3. **SVG thumbnails**: SVG files don't generate thumbnails (falls back to original).

4. **Orphan cleanup**: Media for deleted entries should be cleaned up via `cleanup_orphaned_media()`.

5. **CSS file loading**: External CSS not reliably applied in QWebEngineView; inline styles used as workaround.

---

## Dependencies

- **Pillow>=10.0.0**: For thumbnail generation (added to requirements.txt)

---

## Testing Results

### Upload Tests ✅
- [x] Paste image from clipboard (Ctrl+V)
- [x] Drag and drop single image
- [x] Drag and drop multiple images
- [x] Browse and select files
- [x] Upload shows progress indicator
- [x] Invalid file type rejected with error
- [x] Multiple file types tested (PNG, JPEG, GIF, WebP)

### Display Tests ✅
- [x] Thumbnails display correctly
- [x] Action buttons visible (view/rename/delete)
- [x] Click thumbnail opens full-size modal
- [x] Modal closes on click outside
- [x] Modal closes on Escape key
- [x] Images load via base64 data URLs

### Action Tests ✅
- [x] View button opens full-size modal
- [x] Rename updates filename (preserves extension)
- [x] Delete removes file and thumbnail
- [x] Sort by name reorders grid
- [x] Changes persist after operations

### Edge Cases ✅
- [x] No media attached (empty state)
- [x] New entry without saved ID shows appropriate message
- [x] File system errors handled gracefully

---

## Debugging Notes

### Issues Encountered & Resolved

1. **Custom URL scheme not working**: `wimi-media://` scheme returned `ERR_NETWORK_ACCESS_DENIED`. Switched to base64 data URLs.

2. **Double data URL prefix**: `_get_media_data_url()` was adding prefix when MediaManager already included it. Fixed by returning MediaManager result directly.

3. **Buttons not visible**: CSS file styles not being applied. Resolved by using inline styles in JavaScript.

4. **API method not found**: MockBridge had incorrect method signatures. Fixed to match WIMIApi class.

---

## Next Steps

Phase 4 Stage 6 (Testing & Polish) will include:
- Comprehensive integration testing
- Edge case validation
- Performance testing with multiple large images
- Documentation review
- Bug fixes from extended testing

---

**Phase 4 Progress:** 5/6 stages complete (~83%)
