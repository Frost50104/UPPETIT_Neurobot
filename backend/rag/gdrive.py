"""
Google Drive integration for downloading knowledge base files.

Uses a Service Account for authentication. The shared folder must be
shared with the service account email.
"""
from __future__ import annotations

import io
import logging
import shutil
from pathlib import Path

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# Google Docs MIME type -> export format
_EXPORT_MAP = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
}

# File extensions we can process
_SUPPORTED_EXTENSIONS = {".docx", ".pdf", ".xlsx"}


class GDriveSync:
    def __init__(
        self,
        credentials_path: str,
        folder_id: str,
        download_dir: str,
    ) -> None:
        self._credentials_path = credentials_path
        self._folder_id = folder_id
        self._download_dir = Path(download_dir)

    def _get_service(self):
        creds = Credentials.from_service_account_file(
            self._credentials_path, scopes=SCOPES
        )
        return build("drive", "v3", credentials=creds)

    def list_files(self) -> list[dict]:
        """List all files in the configured Google Drive folder."""
        service = self._get_service()
        results = []
        page_token = None

        while True:
            response = service.files().list(
                q=f"'{self._folder_id}' in parents and trashed = false",
                fields="nextPageToken, files(id, name, mimeType, modifiedTime)",
                pageToken=page_token,
            ).execute()

            results.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        logger.info("Found %d files in Google Drive folder", len(results))
        return results

    def download_all(self) -> list[Path]:
        """Download all supported files from Google Drive folder.

        Returns list of local file paths for successfully downloaded files.
        """
        service = self._get_service()
        files = self.list_files()

        # Clear download dir
        if self._download_dir.exists():
            shutil.rmtree(self._download_dir)
        self._download_dir.mkdir(parents=True, exist_ok=True)

        downloaded: list[Path] = []

        for file_info in files:
            file_id = file_info["id"]
            name = file_info["name"]
            mime_type = file_info["mimeType"]

            try:
                if mime_type in _EXPORT_MAP:
                    # Google Docs native format -> export as docx
                    export_mime, ext = _EXPORT_MAP[mime_type]
                    local_name = Path(name).stem + ext
                    local_path = self._download_dir / local_name

                    request = service.files().export_media(
                        fileId=file_id, mimeType=export_mime
                    )
                    fh = io.BytesIO()
                    downloader = MediaIoBaseDownload(fh, request)
                    done = False
                    while not done:
                        _, done = downloader.next_chunk()

                    local_path.write_bytes(fh.getvalue())
                    downloaded.append(local_path)
                    logger.info("Exported '%s' as '%s'", name, local_name)

                else:
                    # Regular uploaded file
                    ext = Path(name).suffix.lower()
                    if ext not in _SUPPORTED_EXTENSIONS:
                        logger.debug("Skipping unsupported file: %s (%s)", name, mime_type)
                        continue

                    local_path = self._download_dir / name
                    request = service.files().get_media(fileId=file_id)
                    fh = io.BytesIO()
                    downloader = MediaIoBaseDownload(fh, request)
                    done = False
                    while not done:
                        _, done = downloader.next_chunk()

                    local_path.write_bytes(fh.getvalue())
                    downloaded.append(local_path)
                    logger.info("Downloaded '%s'", name)

            except Exception as exc:
                logger.warning("Failed to download '%s': %s", name, exc)

        logger.info("Downloaded %d files from Google Drive", len(downloaded))
        return downloaded

    def sync(self) -> tuple[list[Path], int]:
        """Full sync: download all files and return (paths, count)."""
        paths = self.download_all()
        return paths, len(paths)
