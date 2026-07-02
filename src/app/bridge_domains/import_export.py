"""WIMI Import/Export bridge operations."""
import json
import os
from datetime import date

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot
from ..bridge_helpers import serialize_response


class ImportExportBridgeMixin:
    """Bridge mixin for import/export operations. Composed into DatabaseBridge."""

    @pyqtSlot(result=str)
    @instrumented_slot
    def openImportFileDialog(self) -> str:
        """
        Open a native file dialog for JSON file selection.

        Returns:
            JSON response with {file_path, directory} or empty if cancelled
        """
        try:
            from PyQt6.QtWidgets import QFileDialog
            file_path, _ = QFileDialog.getOpenFileName(
                None,
                "Select Session JSON File",
                "",
                "JSON Files (*.json);;All Files (*)"
            )
            if file_path:
                import os
                return serialize_response(True, data={
                    'file_path': file_path,
                    'directory': os.path.dirname(file_path)
                })
            else:
                return serialize_response(True, data=None)
        except Exception as e:
            # openImportFileDialog takes no params.
            self._log_error(f'Error opening file dialog: {e}')
            return serialize_response(False, error=f'Failed to open file dialog: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def readImportJsonFile(self, file_path: str) -> str:
        """
        Read and analyze a JSON file for import.

        Args:
            file_path: Path to the JSON file

        Returns:
            JSON response with structural analysis:
            - top_level_fields, question_fields, question_count
            - session_metadata, sample_question, has_images, image_count
        """
        try:
            import os
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Store for later use during import
            self._pending_import_data = data
            self._pending_import_path = file_path

            # Analyze structure
            top_level_fields = list(data.keys()) if isinstance(data, dict) else []
            questions = data.get('questions', []) if isinstance(data, dict) else []
            question_count = len(questions)

            # Flatten nested fields in all questions for mapping
            questions_flat = [self._flatten_question_fields(q) for q in questions]

            # Get question-level fields from first flattened question
            question_fields = []
            sample_question = None
            if questions_flat:
                sample_question = questions_flat[0]
                # Exclude raw nested arrays that have been flattened
                question_fields = [
                    k for k in sample_question.keys()
                    if k not in ('answer_choices', 'anki_cards')
                ]

            # Session metadata
            session_metadata = {}
            for key in ['session_name', 'session_id', 'date_scraped']:
                if key in data:
                    session_metadata[key] = data[key]

            # Check for images directory
            directory = os.path.dirname(file_path)
            images_dir = os.path.join(directory, 'images')
            has_images = os.path.isdir(images_dir)
            image_count = 0
            if has_images:
                image_count = len([
                    f for f in os.listdir(images_dir)
                    if os.path.isfile(os.path.join(images_dir, f))
                    and f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'))
                ])

            return serialize_response(True, data={
                'file_path': file_path,
                'top_level_fields': top_level_fields,
                'question_fields': question_fields,
                'question_count': question_count,
                'session_metadata': session_metadata,
                'sample_question': sample_question,
                'has_images': has_images,
                'image_count': image_count,
                'images_directory': images_dir if has_images else None
            })
        except json.JSONDecodeError as e:
            return serialize_response(False, error=f'Invalid JSON file: {e}')
        except Exception as e:
            self._log_error(
                f'Error reading import file: {e}',
                {'file_path': file_path},
            )
            return serialize_response(False, error=f'Failed to read file: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def executeSessionImport(self, import_config_json: str) -> str:
        """
        Execute a bulk session import from JSON data.

        Args:
            import_config_json: JSON string with import configuration:
                - file_path, exam_context_id, question_source_id
                - session_name, date_encountered, field_mappings
                - import_images, images_directory

        Returns:
            JSON response with {session_id, entries_created, images_imported, errors, warnings}
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            config = json.loads(import_config_json)

            # Read the JSON file (use cached data if same path)
            file_path = config.get('file_path', '')
            if hasattr(self, '_pending_import_data') and hasattr(self, '_pending_import_path') \
                    and self._pending_import_path == file_path:
                data = self._pending_import_data
            else:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

            questions = data.get('questions', [])
            if not questions:
                return serialize_response(False, error='No questions found in JSON file')

            field_mappings = config.get('field_mappings', [])
            import_images = config.get('import_images', False)
            images_directory = config.get('images_directory', '')

            # Parse session duration: 0 or empty means no limit (None)
            duration = config.get('session_duration_minutes')
            if duration is not None:
                duration = int(duration) if duration else None
                if duration == 0:
                    duration = None

            # Create review session
            date_encountered = None
            if config.get('date_encountered'):
                date_encountered = date.fromisoformat(config['date_encountered'])

            session = self.user_db.create_review_session(
                exam_context_id=config['exam_context_id'],
                question_source_id=config.get('question_source_id'),
                session_name=config.get('session_name'),
                date_encountered=date_encountered,
                total_questions=len(questions),
                total_incorrect=len(questions),
                session_duration_minutes=duration
            )

            entries_created = 0
            images_imported = 0
            errors = []
            warnings = []

            for idx, question in enumerate(questions):
                try:
                    # Flatten nested fields, then apply field mappings
                    question_flat = self._flatten_question_fields(question)
                    entry_data = self._apply_field_mappings(question_flat, field_mappings)

                    # Create the entry as a draft
                    entry = self.user_db.create_question_entry(
                        review_session_id=session.id,
                        user_answer=entry_data.get('user_answer', ''),
                        correct_answer=entry_data.get('correct_answer', ''),
                        question_id=entry_data.get('question_id'),
                        perceived_difficulty=entry_data.get('perceived_difficulty'),
                        time_spent_seconds=entry_data.get('time_spent_seconds'),
                        reflection=entry_data.get('reflection'),
                        explanation=entry_data.get('explanation'),
                        notes=entry_data.get('notes')
                    )
                    entries_created += 1

                    # Import images if enabled
                    if import_images and images_directory:
                        q_images = question.get('images', [])
                        for img_info in q_images:
                            try:
                                img_filename = img_info.get('filename', '')
                                if not img_filename:
                                    continue
                                import os
                                img_path = os.path.join(images_directory, img_filename)
                                if not os.path.isfile(img_path):
                                    warnings.append(f'Q{idx+1}: Image not found: {img_filename}')
                                    continue

                                with open(img_path, 'rb') as img_f:
                                    img_bytes = img_f.read()

                                if hasattr(self, 'media_manager') and self.media_manager:
                                    media_info = self.media_manager.save_media_from_bytes(
                                        entry_id=entry.id,
                                        data=img_bytes,
                                        original_filename=img_filename
                                    )
                                    self.user_db.add_entry_media(
                                        entry_id=entry.id,
                                        file_uuid=media_info.file_uuid,
                                        original_filename=media_info.original_filename,
                                        mime_type=media_info.mime_type,
                                        file_size_bytes=media_info.file_size
                                    )
                                    images_imported += 1
                                else:
                                    warnings.append(f'Q{idx+1}: Media manager not available, skipped images')
                                    break
                            except Exception as img_e:
                                warnings.append(f'Q{idx+1}: Image error ({img_filename}): {img_e}')

                except Exception as entry_e:
                    errors.append(f'Question {idx+1}: {entry_e}')

            # Clear cached data
            if hasattr(self, '_pending_import_data'):
                del self._pending_import_data
            if hasattr(self, '_pending_import_path'):
                del self._pending_import_path

            return serialize_response(True, data={
                'session_id': session.id,
                'entries_created': entries_created,
                'images_imported': images_imported,
                'total_questions': len(questions),
                'errors': errors,
                'warnings': warnings
            })

        except Exception as e:
            self._log_error(
                f'Error executing session import: {e}',
                {
                    'import_config_json_len': len(import_config_json),
                    'import_config_json_preview': import_config_json[:200],
                },
            )
            return serialize_response(False, error=f'Failed to import session: {e}')

    def _apply_field_mappings(self, question: dict, mappings: list) -> dict:
        """
        Apply field mappings to a question dict to build entry data.

        Handles multiple source fields mapping to the same target
        by concatenating in merge_order with <hr> separator.
        """
        # Group mappings by target
        target_groups = {}
        for mapping in mappings:
            source = mapping.get('source', '')
            target = mapping.get('target', '')
            if not source or not target or target == '(skip)':
                continue
            merge_order = mapping.get('merge_order', 0)
            if target not in target_groups:
                target_groups[target] = []
            target_groups[target].append((merge_order, source))

        result = {}
        for target, sources in target_groups.items():
            # Sort by merge_order
            sources.sort(key=lambda x: x[0])
            values = []
            for _, source_key in sources:
                val = question.get(source_key)
                if val is not None:
                    values.append(str(val))
            if values:
                if target in ('perceived_difficulty', 'time_spent_seconds'):
                    # Numeric fields: take first valid value
                    try:
                        result[target] = int(values[0])
                    except (ValueError, TypeError):
                        pass
                else:
                    result[target] = '<hr>'.join(values) if len(values) > 1 else values[0]

        return result

    @staticmethod
    def _flatten_question_fields(question: dict) -> dict:
        """
        Flatten nested fields in a question dict into mappable string fields.

        Converts:
        - answer_choices (array of objects) -> answer_choices_text (string)
        - anki_cards (array of objects) -> anki_card_ids (string)
        The original fields are preserved for image handling etc.
        """
        flat = dict(question)

        # Flatten answer_choices
        choices = question.get('answer_choices')
        if isinstance(choices, list) and choices:
            lines = []
            for c in choices:
                prefix = f"{c.get('letter', '')}. " if c.get('letter') else ''
                marker = ' [CORRECT]' if c.get('is_correct') else ''
                lines.append(f"{prefix}{c.get('text', '')}{marker}")
            flat['answer_choices_text'] = '\n'.join(lines)

        # Flatten anki_cards
        cards = question.get('anki_cards')
        if isinstance(cards, list) and cards:
            parts = []
            for c in cards:
                card_parts = []
                if c.get('card_id'):
                    card_parts.append(c['card_id'])
                if c.get('card_name'):
                    card_parts.append(c['card_name'])
                if c.get('deck'):
                    card_parts.append(f"deck: {c['deck']}")
                if card_parts:
                    parts.append(' | '.join(card_parts))
            if parts:
                flat['anki_card_ids'] = '; '.join(parts)

        return flat

    # --- Import Mapping Profile CRUD bridges ---

    @pyqtSlot(result=str)
    @instrumented_slot
    def getImportMappingProfiles(self) -> str:
        """Get all import mapping profiles."""
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        try:
            profiles = self.user_db.get_import_mapping_profiles()
            return serialize_response(True, data=profiles)
        except Exception as e:
            # getImportMappingProfiles takes no params.
            self._log_error(f'Error getting import mapping profiles: {e}')
            return serialize_response(False, error=f'Failed to get import mapping profiles: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def createImportMappingProfile(self, profile_json: str) -> str:
        """
        Create a new import mapping profile.

        Args:
            profile_json: JSON string with {profile_name, source_type, field_mappings}
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        try:
            data = json.loads(profile_json)
            field_mappings = data.get('field_mappings', '{}')
            if isinstance(field_mappings, (dict, list)):
                field_mappings = json.dumps(field_mappings)
            profile = self.user_db.create_import_mapping_profile(
                profile_name=data.get('profile_name', ''),
                source_type=data.get('source_type', 'custom'),
                field_mappings=field_mappings
            )
            return serialize_response(True, data=profile)
        except Exception as e:
            self._log_error(
                f'Error creating import mapping profile: {e}',
                {
                    'profile_json_len': len(profile_json),
                    'profile_json_preview': profile_json[:200],
                },
            )
            return serialize_response(False, error=f'Failed to create profile: {e}')

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def updateImportMappingProfile(self, profile_id: int, profile_json: str) -> str:
        """
        Update an import mapping profile.

        Args:
            profile_id: Profile ID
            profile_json: JSON string with updated fields
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        try:
            data = json.loads(profile_json)
            field_mappings = data.get('field_mappings')
            if isinstance(field_mappings, (dict, list)):
                field_mappings = json.dumps(field_mappings)
            profile = self.user_db.update_import_mapping_profile(
                profile_id=profile_id,
                profile_name=data.get('profile_name'),
                source_type=data.get('source_type'),
                field_mappings=field_mappings
            )
            return serialize_response(True, data=profile)
        except Exception as e:
            self._log_error(
                f'Error updating import mapping profile: {e}',
                {
                    'profile_id': profile_id,
                    'profile_json_len': len(profile_json),
                    'profile_json_preview': profile_json[:200],
                },
            )
            return serialize_response(False, error=f'Failed to update profile: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def deleteImportMappingProfile(self, profile_id: int) -> str:
        """Delete an import mapping profile."""
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        try:
            self.user_db.delete_import_mapping_profile(profile_id)
            return serialize_response(True, data={'id': profile_id, 'deleted': True})
        except Exception as e:
            self._log_error(
                f'Error deleting import mapping profile: {e}',
                {'profile_id': profile_id},
            )
            return serialize_response(False, error=f'Failed to delete profile: {e}')
