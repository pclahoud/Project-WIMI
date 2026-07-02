"""
Media URL Scheme Handler for WIMI
Handles wimi-media:// URLs to serve media files in QWebEngineView.

Usage:
    <img src="wimi-media://entry_123/abc-def-uuid">
    <img src="wimi-media://entry_123/abc-def-uuid/thumbnail">
"""

from pathlib import Path
from typing import Optional
import mimetypes

from PyQt6.QtCore import QBuffer, QIODevice, QByteArray
from PyQt6.QtWebEngineCore import QWebEngineUrlSchemeHandler, QWebEngineUrlRequestJob

from app.media_manager import MediaManager, SUPPORTED_MIME_TYPES


class MediaSchemeHandler(QWebEngineUrlSchemeHandler):
    """
    Custom URL scheme handler for serving media files.
    
    URL Format:
        wimi-media://entry_{entry_id}/{file_uuid}
        wimi-media://entry_{entry_id}/{file_uuid}/thumbnail
    
    This allows QWebEngineView to display local media files
    without exposing the file system path.
    """
    
    def __init__(self, media_manager: MediaManager, parent=None):
        """
        Initialize the scheme handler.
        
        Args:
            media_manager: MediaManager instance for file access
            parent: Parent QObject
        """
        super().__init__(parent)
        self.media_manager = media_manager
    
    def set_media_manager(self, media_manager: MediaManager):
        """
        Update the media manager reference.
        
        Args:
            media_manager: New MediaManager instance
        """
        self.media_manager = media_manager
    
    def requestStarted(self, request: QWebEngineUrlRequestJob):
        """
        Handle incoming URL requests.
        
        Args:
            request: The URL request job
        """
        url = request.requestUrl()
        
        # Debug logging
        print(f"[MediaScheme] Request URL: {url.toString()}")
        print(f"[MediaScheme] Host: {url.host()}, Path: {url.path()}")
        
        # URL formats supported:
        #   New: wimi-media://uuid or wimi-media://uuid/thumbnail
        #   Legacy: wimi-media://entry_123/uuid or wimi-media://entry_123/uuid/thumbnail
        # In PyQt6, host() contains the first part after ://
        host = url.host()
        path = url.path()

        # Combine host and path for parsing
        full_path = host + path if host else path
        parts = full_path.strip('/').split('/')

        print(f"[MediaScheme] Parts: {parts}")

        if len(parts) < 1 or not parts[0]:
            print(f"[MediaScheme] Error: Not enough parts in URL")
            request.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return

        # Determine format: legacy (entry_123/uuid/...) or new (uuid/...)
        if parts[0].startswith('entry_'):
            # Legacy format: entry_123/uuid[/thumbnail]
            if len(parts) < 2:
                print(f"[MediaScheme] Error: Legacy URL missing UUID")
                request.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
                return
            file_uuid = parts[1]
            is_thumbnail = len(parts) > 2 and parts[2] == 'thumbnail'
        else:
            # New format: uuid[/thumbnail]
            file_uuid = parts[0]
            is_thumbnail = len(parts) > 1 and parts[1] == 'thumbnail'

        print(f"[MediaScheme] File UUID: {file_uuid}, Thumbnail: {is_thumbnail}")

        # Get file path (entry_id=0 is ignored by media_manager)
        if is_thumbnail:
            file_path = self.media_manager.get_thumbnail_path(0, file_uuid)
            mime_type = 'image/jpeg'
        else:
            file_path = self.media_manager.get_media_path(0, file_uuid)
            if file_path:
                ext = file_path.suffix.lower()
                mime_type = self._get_mime_type(ext)
            else:
                mime_type = 'application/octet-stream'
        
        print(f"[MediaScheme] File path: {file_path}")
        
        if not file_path or not file_path.exists():
            print(f"[MediaScheme] Error: File not found at {file_path}")
            request.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return
        
        # Read file data
        try:
            data = file_path.read_bytes()
        except Exception as e:
            print(f"Error reading media file: {e}")
            request.fail(QWebEngineUrlRequestJob.Error.RequestFailed)
            return
        
        # Create response buffer
        buffer = QBuffer(parent=self)
        buffer.setData(QByteArray(data))
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        
        # Send response
        request.reply(mime_type.encode('utf-8'), buffer)
    
    def _get_mime_type(self, extension: str) -> str:
        """
        Get MIME type for a file extension.
        
        Args:
            extension: File extension (including dot)
            
        Returns:
            MIME type string
        """
        # Check our supported types first
        for mime, ext in SUPPORTED_MIME_TYPES.items():
            if ext == extension:
                return mime
        
        # Fall back to mimetypes module
        mime_type, _ = mimetypes.guess_type(f"file{extension}")
        return mime_type or 'application/octet-stream'


def register_media_scheme():
    """
    Register the wimi-media URL scheme.
    
    IMPORTANT: This must be called BEFORE creating QApplication!
    
    Usage:
        from app.media_scheme_handler import register_media_scheme
        register_media_scheme()
        app = QApplication(sys.argv)
    """
    from PyQt6.QtWebEngineCore import QWebEngineUrlScheme
    
    scheme = QWebEngineUrlScheme(b"wimi-media")
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    scheme.setDefaultPort(-1)  # PortUnspecified = -1
    scheme.setFlags(
        QWebEngineUrlScheme.Flag.SecureScheme |
        QWebEngineUrlScheme.Flag.LocalAccessAllowed |
        QWebEngineUrlScheme.Flag.CorsEnabled |
        QWebEngineUrlScheme.Flag.ContentSecurityPolicyIgnored
    )
    QWebEngineUrlScheme.registerScheme(scheme)
    print("📷 Registered wimi-media:// URL scheme with full permissions")


def install_scheme_handler(profile, media_manager: MediaManager) -> MediaSchemeHandler:
    """
    Install the media scheme handler on a web engine profile.
    
    Args:
        profile: QWebEngineProfile to install handler on
        media_manager: MediaManager instance
        
    Returns:
        The installed MediaSchemeHandler instance
    """
    handler = MediaSchemeHandler(media_manager)
    profile.installUrlSchemeHandler(b"wimi-media", handler)
    return handler
