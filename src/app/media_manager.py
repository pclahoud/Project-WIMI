"""
Media Manager for WIMI
Handles media file storage, retrieval, and thumbnail generation.
"""

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
import mimetypes

try:
    from PIL import Image
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    # Warning will be shown when thumbnail generation is attempted


# Supported image formats
SUPPORTED_MIME_TYPES = {
    'image/png': '.png',
    'image/jpeg': '.jpg',
    'image/gif': '.gif',
    'image/webp': '.webp',
    'image/bmp': '.bmp',
    'image/svg+xml': '.svg',
}

# Reverse mapping for extension to MIME type
EXTENSION_TO_MIME = {v: k for k, v in SUPPORTED_MIME_TYPES.items()}
EXTENSION_TO_MIME['.jpeg'] = 'image/jpeg'  # Alternative extension

# Thumbnail settings
THUMBNAIL_SIZE = (120, 120)
THUMBNAIL_SUFFIX = '_thumb'


@dataclass
class MediaInfo:
    """Information about a stored media file"""
    file_uuid: str
    original_filename: str
    user_filename: str
    mime_type: str
    file_size: int
    file_path: Path
    thumbnail_path: Optional[Path]
    created_at: datetime
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'file_uuid': self.file_uuid,
            'original_filename': self.original_filename,
            'user_filename': self.user_filename,
            'mime_type': self.mime_type,
            'file_size': self.file_size,
            'file_path': str(self.file_path),
            'thumbnail_path': str(self.thumbnail_path) if self.thumbnail_path else None,
            'created_at': self.created_at.isoformat(),
        }


class MediaManager:
    """
    Manages media file storage and retrieval for question entries.
    
    Storage structure:
        {base_path}/media/user_{id}_{username}/entry_{entry_id}/{uuid}.{ext}
    
    Features:
        - UUID-based file naming (prevents conflicts)
        - Automatic thumbnail generation
        - MIME type validation
        - Metadata tracking
    """
    
    def __init__(self, base_path: Path, user_id: int, username: str):
        """
        Initialize MediaManager.
        
        Args:
            base_path: Base application data path (e.g., app_data/)
            user_id: Current user's ID
            username: Current user's username
        """
        self.base_path = Path(base_path)
        self.user_id = user_id
        self.username = username
        self.user_media_path = self.base_path / "media" / f"user_{user_id}_{username}"
        
        # Ensure base directory exists
        self.user_media_path.mkdir(parents=True, exist_ok=True)
    
    def _get_entry_path(self, entry_id: int) -> Path:
        """Get the storage path for a specific entry's media (legacy, for migration)"""
        entry_path = self.user_media_path / f"entry_{entry_id}"
        entry_path.mkdir(parents=True, exist_ok=True)
        return entry_path

    def _find_media_file(self, file_uuid: str) -> Optional[Path]:
        """
        Find a media file by UUID, checking flat directory first, then entry subdirs.
        This enables backward compatibility during/after the migration from
        per-entry directories to flat user-level storage.
        """
        # Check flat directory first (new location)
        for ext in SUPPORTED_MIME_TYPES.values():
            flat_path = self.user_media_path / f"{file_uuid}{ext}"
            if flat_path.exists():
                return flat_path

        # Fall back to entry_* subdirectories (legacy location)
        if self.user_media_path.exists():
            for entry_dir in self.user_media_path.iterdir():
                if entry_dir.is_dir() and entry_dir.name.startswith("entry_"):
                    for ext in SUPPORTED_MIME_TYPES.values():
                        legacy_path = entry_dir / f"{file_uuid}{ext}"
                        if legacy_path.exists():
                            return legacy_path

        return None

    def _find_thumbnail_file(self, file_uuid: str) -> Optional[Path]:
        """Find a thumbnail by UUID, checking flat directory first, then entry subdirs."""
        # Check flat directory first
        flat_thumb = self.user_media_path / f"{file_uuid}{THUMBNAIL_SUFFIX}.jpg"
        if flat_thumb.exists():
            return flat_thumb

        # Fall back to entry_* subdirectories
        if self.user_media_path.exists():
            for entry_dir in self.user_media_path.iterdir():
                if entry_dir.is_dir() and entry_dir.name.startswith("entry_"):
                    legacy_thumb = entry_dir / f"{file_uuid}{THUMBNAIL_SUFFIX}.jpg"
                    if legacy_thumb.exists():
                        return legacy_thumb

        return None

    def migrate_entry_media_to_flat(self) -> int:
        """
        Move all media files from entry_* subdirectories to the flat user directory.
        Removes empty entry directories after migration. Idempotent — safe to call
        multiple times (skips files that already exist at the destination).

        Returns:
            Number of files moved
        """
        if not self.user_media_path.exists():
            return 0

        moved = 0
        dirs_to_remove = []

        for entry_dir in self.user_media_path.iterdir():
            if not entry_dir.is_dir() or not entry_dir.name.startswith("entry_"):
                continue

            for file_path in list(entry_dir.iterdir()):
                if not file_path.is_file():
                    continue
                dest = self.user_media_path / file_path.name
                if dest.exists():
                    # Already migrated — just remove the old copy
                    file_path.unlink()
                else:
                    import shutil
                    shutil.move(str(file_path), str(dest))
                moved += 1

            # Queue empty dir for removal
            if not any(entry_dir.iterdir()):
                dirs_to_remove.append(entry_dir)

        for d in dirs_to_remove:
            try:
                d.rmdir()
            except OSError:
                pass

        return moved
    
    def _generate_file_uuid(self) -> str:
        """Generate a unique file identifier"""
        return str(uuid.uuid4())
    
    def _validate_mime_type(self, mime_type: str) -> bool:
        """Check if the MIME type is supported"""
        return mime_type.lower() in SUPPORTED_MIME_TYPES
    
    def _get_extension(self, mime_type: str) -> str:
        """Get file extension for a MIME type"""
        return SUPPORTED_MIME_TYPES.get(mime_type.lower(), '.bin')
    
    def _detect_mime_type(self, filename: str, data: bytes) -> str:
        """
        Detect MIME type from filename or data.
        
        Args:
            filename: Original filename
            data: File data bytes
            
        Returns:
            Detected MIME type or 'application/octet-stream'
        """
        # Try from filename first
        mime_type, _ = mimetypes.guess_type(filename)
        if mime_type and self._validate_mime_type(mime_type):
            return mime_type
        
        # Try to detect from magic bytes
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            return 'image/png'
        elif data[:2] == b'\xff\xd8':
            return 'image/jpeg'
        elif data[:6] in (b'GIF87a', b'GIF89a'):
            return 'image/gif'
        elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            return 'image/webp'
        elif data[:2] == b'BM':
            return 'image/bmp'
        elif b'<svg' in data[:1000]:
            return 'image/svg+xml'
        
        return 'application/octet-stream'
    
    def _generate_thumbnail(self, source_path: Path, thumbnail_path: Path) -> bool:
        """
        Generate a thumbnail for an image.
        
        Args:
            source_path: Path to source image
            thumbnail_path: Path to save thumbnail
            
        Returns:
            True if thumbnail was generated, False otherwise
        """
        if not PILLOW_AVAILABLE:
            return False
        
        try:
            # Skip SVG files (can't easily thumbnail)
            if source_path.suffix.lower() == '.svg':
                return False
            
            with Image.open(source_path) as img:
                # Convert to RGB if necessary (for PNG with transparency)
                if img.mode in ('RGBA', 'LA', 'P'):
                    # Create white background
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Create thumbnail (maintains aspect ratio)
                img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
                
                # Save as JPEG for consistent thumbnails
                img.save(thumbnail_path, 'JPEG', quality=85)
                return True
                
        except Exception as e:
            # Log error but don't raise - thumbnail is optional
            return False
    
    def save_media_from_base64(
        self,
        entry_id: int,
        base64_data: str,
        original_filename: str,
        mime_type: Optional[str] = None
    ) -> MediaInfo:
        """
        Save media from base64-encoded data.
        
        Args:
            entry_id: The question entry ID
            base64_data: Base64-encoded image data
            original_filename: Original filename from upload
            mime_type: MIME type (auto-detected if not provided)
            
        Returns:
            MediaInfo object with file details
            
        Raises:
            ValueError: If data is invalid or format not supported
        """
        # Decode base64 data
        try:
            # Handle data URL format (data:image/png;base64,...)
            if ',' in base64_data:
                header, base64_data = base64_data.split(',', 1)
                if 'base64' not in header:
                    raise ValueError("Invalid data URL format")
            
            data = base64.b64decode(base64_data)
        except Exception as e:
            raise ValueError(f"Invalid base64 data: {e}")
        
        # Detect or validate MIME type
        detected_mime = self._detect_mime_type(original_filename, data)
        if mime_type:
            if not self._validate_mime_type(mime_type):
                raise ValueError(f"Unsupported MIME type: {mime_type}")
        else:
            mime_type = detected_mime
        
        if not self._validate_mime_type(mime_type):
            raise ValueError(f"Unsupported image format: {mime_type}")
        
        # Generate unique filename
        file_uuid = self._generate_file_uuid()
        extension = self._get_extension(mime_type)
        
        # Save to flat user-level directory (entry_id kept in signature for compat)
        save_path = self.user_media_path

        # Save main file
        file_path = save_path / f"{file_uuid}{extension}"
        file_path.write_bytes(data)

        # Generate thumbnail
        thumbnail_path = save_path / f"{file_uuid}{THUMBNAIL_SUFFIX}.jpg"
        if not self._generate_thumbnail(file_path, thumbnail_path):
            thumbnail_path = None
        
        # Create MediaInfo
        media_info = MediaInfo(
            file_uuid=file_uuid,
            original_filename=original_filename,
            user_filename=original_filename,  # Initially same as original
            mime_type=mime_type,
            file_size=len(data),
            file_path=file_path,
            thumbnail_path=thumbnail_path,
            created_at=datetime.now()
        )
        
        return media_info
    
    def save_media_from_bytes(
        self,
        entry_id: int,
        data: bytes,
        original_filename: str,
        mime_type: Optional[str] = None
    ) -> MediaInfo:
        """
        Save media from raw bytes.
        
        Args:
            entry_id: The question entry ID
            data: Raw image bytes
            original_filename: Original filename
            mime_type: MIME type (auto-detected if not provided)
            
        Returns:
            MediaInfo object with file details
        """
        # Encode to base64 and use existing method
        base64_data = base64.b64encode(data).decode('utf-8')
        return self.save_media_from_base64(entry_id, base64_data, original_filename, mime_type)
    
    def get_media_path(self, entry_id: int, file_uuid: str) -> Optional[Path]:
        """
        Get the full path to a media file.
        entry_id is kept for backward compatibility but ignored — lookup is by UUID.
        """
        return self._find_media_file(file_uuid)
    
    def get_thumbnail_path(self, entry_id: int, file_uuid: str) -> Optional[Path]:
        """
        Get the path to a thumbnail.
        entry_id is kept for backward compatibility but ignored — lookup is by UUID.
        """
        return self._find_thumbnail_file(file_uuid)
    
    def delete_media(self, entry_id: int, file_uuid: str) -> bool:
        """
        Delete a media file and its thumbnail.
        entry_id is kept for backward compatibility but ignored — lookup is by UUID.
        """
        deleted = False

        # Find and delete main file
        file_path = self._find_media_file(file_uuid)
        if file_path:
            file_path.unlink()
            deleted = True
            # Clean up empty parent if it's a legacy entry_* dir
            parent = file_path.parent
            if parent.name.startswith("entry_") and not any(parent.iterdir()):
                parent.rmdir()

        # Find and delete thumbnail
        thumb_path = self._find_thumbnail_file(file_uuid)
        if thumb_path:
            thumb_path.unlink()
            parent = thumb_path.parent
            if parent.name.startswith("entry_") and not any(parent.iterdir()):
                parent.rmdir()

        return deleted
    
    def delete_entry_media(self, entry_id: int) -> int:
        """
        Delete all media for an entry.
        
        Args:
            entry_id: The question entry ID
            
        Returns:
            Number of files deleted
        """
        entry_path = self.user_media_path / f"entry_{entry_id}"
        
        if not entry_path.exists():
            return 0
        
        count = 0
        for file in entry_path.iterdir():
            if file.is_file():
                file.unlink()
                count += 1
        
        # Remove directory
        if entry_path.exists():
            entry_path.rmdir()
        
        return count
    
    def get_entry_media_files(self, entry_id: int) -> List[Tuple[str, Path]]:
        """
        Get all media files for an entry.
        
        Args:
            entry_id: The question entry ID
            
        Returns:
            List of (file_uuid, file_path) tuples
        """
        entry_path = self.user_media_path / f"entry_{entry_id}"
        
        if not entry_path.exists():
            return []
        
        files = []
        for file_path in entry_path.iterdir():
            if file_path.is_file() and THUMBNAIL_SUFFIX not in file_path.stem:
                file_uuid = file_path.stem
                files.append((file_uuid, file_path))
        
        return files
    
    def get_file_as_base64(self, entry_id: int, file_uuid: str) -> Optional[str]:
        """
        Get a media file as base64-encoded data URL.
        
        Args:
            entry_id: The question entry ID
            file_uuid: The file's UUID
            
        Returns:
            Data URL string (data:mime/type;base64,...) or None
        """
        file_path = self.get_media_path(entry_id, file_uuid)
        if not file_path:
            return None
        
        # Determine MIME type from extension
        ext = file_path.suffix.lower()
        mime_type = EXTENSION_TO_MIME.get(ext, 'application/octet-stream')
        
        # Read and encode
        data = file_path.read_bytes()
        base64_data = base64.b64encode(data).decode('utf-8')
        
        return f"data:{mime_type};base64,{base64_data}"
    
    def get_thumbnail_as_base64(self, entry_id: int, file_uuid: str) -> Optional[str]:
        """
        Get a thumbnail as base64-encoded data URL.
        
        Args:
            entry_id: The question entry ID
            file_uuid: The file's UUID
            
        Returns:
            Data URL string or None
        """
        thumbnail_path = self.get_thumbnail_path(entry_id, file_uuid)
        if not thumbnail_path:
            # Fall back to original if no thumbnail
            return self.get_file_as_base64(entry_id, file_uuid)
        
        data = thumbnail_path.read_bytes()
        base64_data = base64.b64encode(data).decode('utf-8')
        
        return f"data:image/jpeg;base64,{base64_data}"
    
    def cleanup_orphaned_media(self, valid_entry_ids_or_uuids=None, valid_file_uuids: set = None) -> int:
        """
        Remove orphaned media files.

        Supports two modes:
        - Legacy: pass valid_entry_ids (List[int]) to clean entry_* dirs
        - New: pass valid_file_uuids (set of str) to clean flat files

        Returns:
            Number of items cleaned up
        """
        if not self.user_media_path.exists():
            return 0

        cleaned = 0

        if valid_file_uuids is not None:
            # New mode: clean flat files not in the valid set
            for file_path in self.user_media_path.iterdir():
                if not file_path.is_file():
                    continue
                stem = file_path.stem
                # Strip _thumb suffix to get the uuid
                if stem.endswith(THUMBNAIL_SUFFIX):
                    uuid_part = stem[:-len(THUMBNAIL_SUFFIX)]
                else:
                    uuid_part = stem
                if uuid_part not in valid_file_uuids:
                    file_path.unlink()
                    cleaned += 1
        elif valid_entry_ids_or_uuids is not None:
            # Legacy mode: clean entry_* directories
            valid_dirs = {f"entry_{eid}" for eid in valid_entry_ids_or_uuids}
            for entry_dir in self.user_media_path.iterdir():
                if entry_dir.is_dir() and entry_dir.name.startswith("entry_"):
                    if entry_dir.name not in valid_dirs:
                        for file in entry_dir.iterdir():
                            file.unlink()
                        entry_dir.rmdir()
                        cleaned += 1
        
        return cleaned
