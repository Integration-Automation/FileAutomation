"""Google Drive client (Singleton Facade).

Wraps OAuth2 credential loading and exposes a lazily-built ``service`` attribute
that every operation module calls through.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from automation_file.logging_config import file_automation_logger

_DEFAULT_SCOPES = ("https://www.googleapis.com/auth/drive",)


class GoogleDriveClient:
    """Holds credentials and the Drive API service handle."""

    def __init__(self, scopes: tuple[str, ...] = _DEFAULT_SCOPES) -> None:
        self.scopes: tuple[str, ...] = scopes
        self.creds: Credentials | None = None
        self.service: Any = None

    def later_init(self, token_path: str, credentials_path: str) -> Any:
        """Load / refresh credentials and build the Drive service.

        Writes the refreshed token back to ``token_path`` with UTF-8 encoding.
        """
        token_file = Path(token_path)
        credentials_file = Path(credentials_path)
        creds: Credentials | None = None

        if token_file.exists():
            file_automation_logger.info("GoogleDriveClient: loading token from %s", token_file)
            creds = Credentials.from_authorized_user_file(str(token_file), list(self.scopes))

        if creds is None or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(credentials_file),
                    list(self.scopes),
                )
                creds = flow.run_local_server(port=0)
            with open(token_file, "w", encoding="utf-8") as token_fp:
                token_fp.write(creds.to_json())

        try:
            self.creds = creds
            self.service = build("drive", "v3", credentials=creds)
            file_automation_logger.info("GoogleDriveClient: service ready")
            return self.service
        except HttpError as error:
            file_automation_logger.error("GoogleDriveClient init failed: %r", error)
            self.service = None
            raise

    def require_service(self) -> Any:
        """Return ``self.service`` or raise if the client has not been initialised."""
        if self.service is None:
            raise RuntimeError(
                "GoogleDriveClient not initialised; call later_init(token, credentials) first"
            )
        return self.service


driver_instance: GoogleDriveClient = GoogleDriveClient()
