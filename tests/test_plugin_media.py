"""Tests for PluginAPI.upload_media() — media upload via plugin facade."""

import pytest
from unittest.mock import MagicMock

from app.plugin_api import PluginAPI
from app.plugin_manifest import VALID_PERMISSIONS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def mock_media_manager():
    return MagicMock()


@pytest.fixture
def media_api(mock_db, mock_media_manager):
    """PluginAPI with write:media permission and a media manager."""
    return PluginAPI(
        "test-plugin", mock_db, ["read", "write:media"],
        media_manager=mock_media_manager,
    )


@pytest.fixture
def no_media_api(mock_db):
    """PluginAPI with write:media permission but NO media manager."""
    return PluginAPI("test-plugin", mock_db, ["read", "write:media"])


@pytest.fixture
def read_only_api(mock_db, mock_media_manager):
    """PluginAPI without write:media permission."""
    return PluginAPI(
        "test-plugin", mock_db, ["read"],
        media_manager=mock_media_manager,
    )


def _make_media_info(**overrides):
    """Build a mock object mimicking the return value of save_media_from_base64."""
    defaults = {
        "file_uuid": "abc-123-def",
        "original_filename": "card_front.png",
        "user_filename": "card_front.png",
        "mime_type": "image/png",
        "file_size": 2048,
    }
    defaults.update(overrides)
    info = MagicMock()
    for k, v in defaults.items():
        setattr(info, k, v)
    return info


def _make_entry_media(**overrides):
    """Build a mock object mimicking the return value of add_entry_media."""
    defaults = {
        "id": 7,
        "sort_order": 0,
        "dimension_id": None,
        "linked_subject_ids": None,
    }
    defaults.update(overrides)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


# ---------------------------------------------------------------------------
# Permission registration
# ---------------------------------------------------------------------------

class TestMediaPermissionRegistered:

    def test_write_media_in_valid_permissions(self):
        assert "write:media" in VALID_PERMISSIONS


# ---------------------------------------------------------------------------
# upload_media tests
# ---------------------------------------------------------------------------

class TestUploadMediaPermission:

    def test_raises_without_write_media(self, read_only_api):
        with pytest.raises(PermissionError, match="write:media"):
            read_only_api.upload_media(1, "base64data", "img.png", "image/png")


class TestUploadMediaNoManager:

    def test_returns_error_when_media_manager_missing(self, no_media_api):
        result = no_media_api.upload_media(1, "base64data", "img.png", "image/png")
        assert result == {"error": "Media manager not available"}


class TestUploadMediaSuccess:

    def test_successful_upload_returns_full_dict(
        self, media_api, mock_db, mock_media_manager
    ):
        media_info = _make_media_info()
        entry_media = _make_entry_media()

        mock_media_manager.save_media_from_base64.return_value = media_info
        mock_db.add_entry_media.return_value = entry_media
        mock_media_manager.get_thumbnail_as_base64.return_value = "data:image/png;base64,THUMB"
        mock_media_manager.get_file_as_base64.return_value = "data:image/png;base64,FULL"

        result = media_api.upload_media(42, "aGVsbG8=", "card_front.png", "image/png")

        # Verify returned dict shape and values
        assert result["id"] == 7
        assert result["file_uuid"] == "abc-123-def"
        assert result["original_filename"] == "card_front.png"
        assert result["user_filename"] == "card_front.png"
        assert result["mime_type"] == "image/png"
        assert result["file_size"] == 2048
        assert result["sort_order"] == 0
        assert result["dimension_id"] is None
        assert result["linked_subject_ids"] is None
        assert result["thumbnail_url"] == "data:image/png;base64,THUMB"
        assert result["full_url"] == "data:image/png;base64,FULL"

    def test_successful_upload_calls_save_media(
        self, media_api, mock_media_manager, mock_db
    ):
        mock_media_manager.save_media_from_base64.return_value = _make_media_info()
        mock_db.add_entry_media.return_value = _make_entry_media()
        mock_media_manager.get_thumbnail_as_base64.return_value = ""
        mock_media_manager.get_file_as_base64.return_value = ""

        media_api.upload_media(42, "aGVsbG8=", "photo.jpg", "image/jpeg")

        mock_media_manager.save_media_from_base64.assert_called_once_with(
            entry_id=42,
            base64_data="aGVsbG8=",
            original_filename="photo.jpg",
            mime_type="image/jpeg",
        )

    def test_successful_upload_calls_add_entry_media(
        self, media_api, mock_media_manager, mock_db
    ):
        info = _make_media_info(
            file_uuid="uuid-999", original_filename="x.png",
            mime_type="image/png", file_size=512,
        )
        mock_media_manager.save_media_from_base64.return_value = info
        mock_db.add_entry_media.return_value = _make_entry_media()
        mock_media_manager.get_thumbnail_as_base64.return_value = ""
        mock_media_manager.get_file_as_base64.return_value = ""

        media_api.upload_media(10, "data", "x.png", "image/png")

        mock_db.add_entry_media.assert_called_once_with(
            entry_id=10,
            file_uuid="uuid-999",
            original_filename="x.png",
            mime_type="image/png",
            file_size_bytes=512,
        )

    def test_thumbnail_url_empty_when_none(
        self, media_api, mock_media_manager, mock_db
    ):
        mock_media_manager.save_media_from_base64.return_value = _make_media_info()
        mock_db.add_entry_media.return_value = _make_entry_media()
        mock_media_manager.get_thumbnail_as_base64.return_value = None
        mock_media_manager.get_file_as_base64.return_value = None

        result = media_api.upload_media(1, "data", "f.png", "image/png")

        assert result["thumbnail_url"] == ""
        assert result["full_url"] == ""


class TestUploadMediaErrors:

    def test_invalid_mime_type(self, media_api, mock_media_manager):
        mock_media_manager.save_media_from_base64.side_effect = ValueError(
            "Unsupported MIME type: application/exe"
        )

        result = media_api.upload_media(1, "data", "bad.exe", "application/exe")

        assert "error" in result
        assert "Unsupported MIME type" in result["error"]

    def test_corrupt_base64(self, media_api, mock_media_manager):
        mock_media_manager.save_media_from_base64.side_effect = ValueError(
            "Invalid base64 data"
        )

        result = media_api.upload_media(1, "!!!not-base64!!!", "img.png", "image/png")

        assert "error" in result
        assert "Invalid base64" in result["error"]

    def test_invalid_entry_id_db_error(
        self, media_api, mock_media_manager, mock_db
    ):
        mock_media_manager.save_media_from_base64.return_value = _make_media_info()
        mock_db.add_entry_media.side_effect = Exception(
            "FOREIGN KEY constraint failed"
        )

        result = media_api.upload_media(99999, "data", "img.png", "image/png")

        assert "error" in result
        assert "Failed to upload media" in result["error"]

    def test_empty_mime_type_passed_as_none(
        self, media_api, mock_media_manager, mock_db
    ):
        """When mime_type is empty string, it should be passed as None."""
        mock_media_manager.save_media_from_base64.return_value = _make_media_info()
        mock_db.add_entry_media.return_value = _make_entry_media()
        mock_media_manager.get_thumbnail_as_base64.return_value = ""
        mock_media_manager.get_file_as_base64.return_value = ""

        media_api.upload_media(1, "data", "file.bin", "")

        call_kwargs = mock_media_manager.save_media_from_base64.call_args[1]
        assert call_kwargs["mime_type"] is None
