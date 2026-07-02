"""WIMI Media bridge operations."""
import json

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot

from ..bridge_helpers import serialize_response


class MediaBridgeMixin:
    """Bridge mixin for media operations. Composed into DatabaseBridge."""

    @pyqtSlot(int, str, str, str, result=str)
    @instrumented_slot
    def addQuestionMedia(self, entry_id: int, base64_data: str, filename: str, mime_type: str) -> str:
        """
        Add media to a question entry.

        Args:
            entry_id: Question entry ID
            base64_data: Base64-encoded image data (may include data URL prefix)
            filename: Original filename
            mime_type: MIME type of the image

        Returns:
            JSON response with media info
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        if not hasattr(self, 'media_manager') or not self.media_manager:
            return serialize_response(False, error='Media manager not initialized')

        try:
            media_info = self.media_manager.save_media_from_base64(
                entry_id=entry_id,
                base64_data=base64_data,
                original_filename=filename,
                mime_type=mime_type if mime_type else None
            )

            entry_media = self.user_db.add_entry_media(
                entry_id=entry_id,
                file_uuid=media_info.file_uuid,
                original_filename=media_info.original_filename,
                mime_type=media_info.mime_type,
                file_size_bytes=media_info.file_size
            )

            return serialize_response(True, data={
                'id': entry_media.id,
                'file_uuid': media_info.file_uuid,
                'original_filename': media_info.original_filename,
                'user_filename': media_info.user_filename,
                'mime_type': media_info.mime_type,
                'file_size': media_info.file_size,
                'thumbnail_url': self._get_media_data_url(entry_id, media_info.file_uuid, thumbnail=True),
                'full_url': self._get_media_data_url(entry_id, media_info.file_uuid, thumbnail=False)
            })

        except ValueError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(
                f'Error adding media: {e}',
                {
                    'entry_id': entry_id,
                    'filename': filename,
                    'mime_type': mime_type,
                    'base64_data_len': len(base64_data) if base64_data else 0,
                },
            )
            return serialize_response(False, error=f'Failed to add media: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getQuestionMedia(self, entry_id: int) -> str:
        """
        Get all media for a question entry.

        Args:
            entry_id: Question entry ID

        Returns:
            JSON response with list of media items
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            media_list = self.user_db.get_entry_media_list(entry_id)

            data = [self._serialize_entry_media(m) for m in media_list]

            return serialize_response(True, data=data)

        except Exception as e:
            self._log_error(
                f'Error getting media: {e}',
                {'entry_id': entry_id},
            )
            return serialize_response(False, error=f'Failed to get media: {e}')

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def renameMedia(self, media_id: int, new_name: str) -> str:
        """
        Rename a media file.

        Args:
            media_id: Media record ID
            new_name: New display name for the file

        Returns:
            JSON response with updated media info
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            media = self.user_db.update_media_filename(media_id, new_name)

            return serialize_response(True, data={
                'id': media.id,
                'file_uuid': media.file_uuid,
                'user_filename': media.user_filename
            })

        except Exception as e:
            self._log_error(
                f'Error renaming media: {e}',
                {
                    'media_id': media_id,
                    'new_name': new_name,
                },
            )
            return serialize_response(False, error=f'Failed to rename media: {e}')

    @pyqtSlot(int, int, result=str)
    @instrumented_slot
    def deleteMedia(self, entry_id: int, media_id: int) -> str:
        """
        Delete a media file.

        Args:
            entry_id: Question entry ID
            media_id: Media record ID

        Returns:
            JSON response with delete result
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        if not hasattr(self, 'media_manager') or not self.media_manager:
            return serialize_response(False, error='Media manager not initialized')

        try:
            media = self.user_db.get_media_by_id(media_id)
            if not media:
                return serialize_response(False, error='Media not found')

            self.media_manager.delete_media(entry_id, media.file_uuid)
            self.user_db.delete_entry_media(media_id)

            return serialize_response(True, data={'id': media_id, 'deleted': True})

        except Exception as e:
            self._log_error(
                f'Error deleting media: {e}',
                {
                    'entry_id': entry_id,
                    'media_id': media_id,
                },
            )
            return serialize_response(False, error=f'Failed to delete media: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def removeMediaFromEntry(self, media_id: int) -> str:
        """
        Remove a media file from entry (database record only, keeps file on disk).

        Args:
            media_id: Media record ID

        Returns:
            JSON response with remove result
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            media = self.user_db.get_media_by_id(media_id)
            if not media:
                return serialize_response(False, error='Media not found')

            self.user_db.unlink_media_from_entry(media_id)

            return serialize_response(True, data={'id': media_id, 'removed': True})

        except Exception as e:
            self._log_error(
                f'Error removing media from entry: {e}',
                {'media_id': media_id},
            )
            return serialize_response(False, error=f'Failed to remove media: {e}')

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def reorderMedia(self, entry_id: int, order_json: str) -> str:
        """
        Reorder media files for an entry.

        Args:
            entry_id: Question entry ID
            order_json: JSON array of media IDs in desired order

        Returns:
            JSON response with result
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            media_ids = json.loads(order_json)
            self.user_db.reorder_entry_media(entry_id, media_ids)

            return serialize_response(True, data={'reordered': True})

        except Exception as e:
            self._log_error(
                f'Error reordering media: {e}',
                {
                    'entry_id': entry_id,
                    'order_json_len': len(order_json) if order_json else 0,
                    'order_json_preview': order_json[:200] if order_json else '',
                },
            )
            return serialize_response(False, error=f'Failed to reorder media: {e}')

    @pyqtSlot(int, int, result=str)
    @instrumented_slot
    def updateMediaDimension(self, media_id: int, dimension_id: int) -> str:
        """
        Update the dimension assignment for a media item.

        Args:
            media_id: Media record ID
            dimension_id: Dimension ID (0 or -1 to clear)

        Returns:
            JSON response with updated media info
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            updated = self.user_db.update_entry_media(
                media_id=media_id,
                dimension_id=dimension_id
            )

            if updated:
                return serialize_response(True, data=self._serialize_entry_media(updated))
            else:
                return serialize_response(False, error='Media not found')

        except Exception as e:
            self._log_error(
                f'Error updating media dimension: {e}',
                {
                    'media_id': media_id,
                    'dimension_id': dimension_id,
                },
            )
            return serialize_response(False, error=f'Failed to update media: {e}')

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def updateMediaLinkedSubjects(self, media_id: int, subject_ids_json: str) -> str:
        """
        Update the linked subject IDs for a media item.

        Args:
            media_id: Media record ID
            subject_ids_json: JSON array of subject node IDs

        Returns:
            JSON response with updated media info
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            subject_ids = json.loads(subject_ids_json) if subject_ids_json else []

            if not isinstance(subject_ids, list):
                return serialize_response(False, error='subject_ids must be a JSON array')

            updated = self.user_db.update_entry_media(
                media_id=media_id,
                linked_subject_ids=subject_ids
            )

            if updated:
                return serialize_response(True, data=self._serialize_entry_media(updated))
            else:
                return serialize_response(False, error='Media not found')

        except json.JSONDecodeError as e:
            return serialize_response(False, error=f'Invalid JSON: {e}')
        except Exception as e:
            self._log_error(
                f'Error updating media linked subjects: {e}',
                {
                    'media_id': media_id,
                    'subject_ids_json_len': len(subject_ids_json) if subject_ids_json else 0,
                    'subject_ids_json_preview': subject_ids_json[:200] if subject_ids_json else '',
                },
            )
            return serialize_response(False, error=f'Failed to update media: {e}')

    @pyqtSlot(int, int, result=str)
    @instrumented_slot
    def attachMediaToEntry(self, media_id: int, entry_id: int) -> str:
        """
        Attach an existing media record to an entry (creates junction table link).

        Args:
            media_id: ID of the existing media record
            entry_id: ID of the entry to attach to

        Returns:
            JSON response with the attached media object
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            media = self.user_db.link_media_to_entry(media_id, entry_id)
            if not media:
                return serialize_response(False, error='Media not found')

            return serialize_response(True, data=self._serialize_entry_media(media))

        except Exception as e:
            self._log_error(
                f'Error attaching media to entry: {e}',
                {
                    'media_id': media_id,
                    'entry_id': entry_id,
                },
            )
            return serialize_response(False, error=f'Failed to attach media: {e}')

    @pyqtSlot(int, int, result=str)
    @instrumented_slot
    def attachExistingMediaToEntry(self, media_id: int, entry_id: int) -> str:
        """
        Attach an existing media item to an entry via the
        ``entry_media_mapping`` junction. Re-activates a soft-deleted
        (``is_active=0``) mapping in place rather than INSERT-conflicting.
        Idempotent for the already-active case (returns
        ``created=False``).

        Args:
            media_id: ID of an existing row in ``entry_media``.
            entry_id: ID of an existing row in ``question_entries``.

        Returns:
            JSON response with ``{'created': bool}`` — True when a new
            mapping was inserted *or* a soft-deleted mapping was
            re-activated, False when the mapping was already active.
        """
        from database.exceptions import ValidationError

        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            created = self.user_db.attach_existing_media_to_entry(media_id, entry_id)
            return serialize_response(True, data={'created': bool(created)})
        except ValidationError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(
                f'Error attaching existing media to entry: {e}',
                {
                    'media_id': media_id,
                    'entry_id': entry_id,
                },
            )
            return serialize_response(False, error=f'Failed to attach media: {e}')

    @pyqtSlot(int, int, result=str)
    @instrumented_slot
    def detachMediaFromEntry(self, media_id: int, entry_id: int) -> str:
        """
        Soft-detach a media item from an entry by flipping
        ``entry_media_mapping.is_active`` from 1 to 0. The row is
        preserved so the media stays rediscoverable via the image
        browser and so re-attachment can re-activate the same mapping
        without losing its ``sort_order``.

        Args:
            media_id: ID of the media to detach.
            entry_id: ID of the entry to detach the media from.

        Returns:
            JSON response with ``{'removed': bool}`` — True when a row's
            ``is_active`` was changed from 1 to 0, False when the
            mapping was already inactive or does not exist.
        """
        from database.exceptions import ValidationError

        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            removed = self.user_db.detach_media_from_entry(media_id, entry_id)
            return serialize_response(True, data={'removed': bool(removed)})
        except ValidationError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(
                f'Error detaching media from entry: {e}',
                {
                    'media_id': media_id,
                    'entry_id': entry_id,
                },
            )
            return serialize_response(False, error=f'Failed to detach media: {e}')

    @pyqtSlot(str, int, result=str)
    @instrumented_slot
    def searchMedia(self, query: str, limit: int = 50) -> str:
        """
        Search media files globally by filename for the current user.

        Args:
            query: Search query (matches filenames)
            limit: Maximum results

        Returns:
            JSON response with list of matching media items
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            media_list = self.user_db.search_media(
                query=query,
                limit=limit
            )

            data = [self._serialize_entry_media(m) for m in media_list]

            return serialize_response(True, data=data)

        except Exception as e:
            self._log_error(
                f'Error searching media: {e}',
                {
                    'query': query,
                    'limit': limit,
                },
            )
            return serialize_response(False, error=f'Failed to search media: {e}')

    @pyqtSlot(int, int, int, result=str)
    @instrumented_slot
    def getMediaBySubject(self, subject_node_id: int, limit: int = 20, dimension_id: int = 0) -> str:
        """
        Get media files globally for the current user linked to a subject.

        Args:
            subject_node_id: Subject node ID to match
            limit: Maximum results
            dimension_id: Optional dimension ID to filter by (0 = no filter)

        Returns:
            JSON response with list of matching media items
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            media_list = self.user_db.get_media_by_subject(
                subject_node_id=subject_node_id,
                limit=limit,
                dimension_id=dimension_id if dimension_id > 0 else None
            )

            data = [self._serialize_entry_media(m) for m in media_list]

            return serialize_response(True, data=data)

        except Exception as e:
            self._log_error(
                f'Error getting media by subject: {e}',
                {
                    'subject_node_id': subject_node_id,
                    'limit': limit,
                    'dimension_id': dimension_id,
                },
            )
            return serialize_response(False, error=f'Failed to get media: {e}')

    @pyqtSlot(str, int, int, int, result=str)
    @instrumented_slot
    def getMediaBySubjects(
        self,
        subject_ids_json: str,
        exclude_entry_id: int = 0,
        limit: int = 20,
        dimension_id: int = 0,
    ) -> str:
        """
        Get media items linked to any of the given subjects, optionally excluding
        a specific entry. Used by the "Related from other entries" surface.

        Args:
            subject_ids_json: JSON-encoded list of subject IDs (e.g. "[12, 47]")
            exclude_entry_id: Entry ID to exclude from results (0 = no exclusion)
            limit: Maximum results
            dimension_id: Dimension filter (0 = no filter)

        Returns:
            JSON response with list of matching media items
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            try:
                subject_ids = json.loads(subject_ids_json) if subject_ids_json else []
            except json.JSONDecodeError as e:
                return serialize_response(False, error=f'Invalid JSON: {e}')

            if not isinstance(subject_ids, list):
                return serialize_response(False, error='subject_ids must be a JSON array')
            if not all(isinstance(s, int) for s in subject_ids):
                return serialize_response(False, error='subject_ids must contain only integers')

            media_list = self.user_db.get_media_by_subjects(
                subject_ids=subject_ids,
                exclude_entry_id=exclude_entry_id if exclude_entry_id > 0 else None,
                limit=limit,
                dimension_id=dimension_id if dimension_id > 0 else None,
            )

            data = [self._serialize_entry_media(m) for m in media_list]

            return serialize_response(True, data=data)

        except Exception as e:
            self._log_error(
                f'Error getting media by subjects: {e}',
                {
                    'subject_ids_json_len': len(subject_ids_json) if subject_ids_json else 0,
                    'subject_ids_json_preview': subject_ids_json[:200] if subject_ids_json else '',
                    'exclude_entry_id': exclude_entry_id,
                    'limit': limit,
                    'dimension_id': dimension_id,
                },
            )
            return serialize_response(False, error=f'Failed to get media: {e}')
