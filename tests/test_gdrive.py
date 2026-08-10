"""
tests/test_gdrive.py — Unit tests for GoogleDriveStorageProvider.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from storage.gdrive import GoogleDriveStorageProvider
from storage.provider import (
    DownloadError,
    LockConflictError,
    LockNotOwnedError,
    SnapshotNotFoundError,
    StorageUnavailableError,
)


@pytest.fixture
def fake_creds_file(tmp_path: Path) -> Path:
    creds = tmp_path / "service_account.json"
    creds.write_text(
        json.dumps(
            {
                "type": "service_account",
                "project_id": "test-project",
                "private_key_id": "123",
                "private_key": "-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n",
                "client_email": "test@test.iam.gserviceaccount.com",
            }
        ),
        encoding="utf-8",
    )
    return creds


class TestGoogleDriveProvider:
    @patch("storage.gdrive.build")
    @patch("storage.gdrive.service_account.Credentials.from_service_account_file")
    def test_acquire_lock_same_host_reacquires(self, mock_creds, mock_build, fake_creds_file):
        provider = GoogleDriveStorageProvider("folder123", fake_creds_file)

        now = datetime.now(tz=timezone.utc)
        existing_lock = {
            "world_id": "survival",
            "host_id": "my-host-id",
            "session_id": "old-session-id",
            "created_at": (now - timedelta(minutes=10)).isoformat(),
            "expires_at": (now + timedelta(minutes=50)).isoformat(),
        }

        # Mock get_lock returning existing lock
        provider.get_lock = MagicMock(return_value=existing_lock)
        provider._find_file = MagicMock(return_value="file123")
        provider._update_bytes = MagicMock()

        new_lock = {
            "world_id": "survival",
            "host_id": "my-host-id",
            "session_id": "new-session-id",
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=1)).isoformat(),
        }

        # Should NOT raise LockConflictError because host_id matches
        provider.acquire_lock("survival", new_lock)
        provider._update_bytes.assert_called_once()

    @patch("storage.gdrive.build")
    @patch("storage.gdrive.service_account.Credentials.from_service_account_file")
    def test_acquire_lock_other_host_conflicts(self, mock_creds, mock_build, fake_creds_file):
        provider = GoogleDriveStorageProvider("folder123", fake_creds_file)

        now = datetime.now(tz=timezone.utc)
        existing_lock = {
            "world_id": "survival",
            "host_id": "other-host-id",
            "session_id": "other-session-id",
            "created_at": (now - timedelta(minutes=10)).isoformat(),
            "expires_at": (now + timedelta(minutes=50)).isoformat(),
        }

        provider.get_lock = MagicMock(return_value=existing_lock)

        new_lock = {
            "world_id": "survival",
            "host_id": "my-host-id",
            "session_id": "new-session-id",
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=1)).isoformat(),
        }

        with pytest.raises(LockConflictError):
            provider.acquire_lock("survival", new_lock)

    @patch("storage.gdrive.build")
    @patch("storage.gdrive.service_account.Credentials.from_service_account_file")
    def test_retry_helper(self, mock_creds, mock_build, fake_creds_file):
        provider = GoogleDriveStorageProvider("folder123", fake_creds_file)

        call_count = 0

        def flaky_action():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("Network glitch")
            return "success"

        result = provider._with_retry(flaky_action, retries=3, delay=0.01)
        assert result == "success"
        assert call_count == 2
