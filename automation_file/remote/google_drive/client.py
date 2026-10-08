"""Google Drive client (Singleton Facade).

Wraps OAuth2 credential loading and exposes a lazily-built ``service`` attribute
that every operation module calls through. The Google SDK is imported when it is
first needed, so importing this module does not require the ``gdrive`` extra.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from automation_file.core.optional import require_module
from automation_file.logging_config import file_automation_logger

_DEFAULT_SCOPES = ("https://www.googleapis.com/auth/drive",)
_EXTRA = "gdrive"


def drive_http_error() -> type[Exception]:
    """Return ``googleapiclient.errors.HttpError``, imported on first use."""
    error_class: type[Exception] = require_module("googleapiclient.errors", extra=_EXTRA).HttpError
    return error_class


def drive_media() -> Any:
    """Return the ``googleapiclient.http`` module, imported on first use."""
    return require_module("googleapiclient.http", extra=_EXTRA)


class GoogleDriveClient:
    """Holds credentials and the Drive API service handle."""

    def __init__(self, scopes: tuple[str, ...] = _DEFAULT_SCOPES) -> None:
        self.scopes: tuple[str, ...] = scopes
        self.creds: Any = None
        self.service: Any = None

    def later_init(self, token_path: str, credentials_path: str) -> Any:
        """Load / refresh credentials and build the Drive service.

        Writes the refreshed token back to ``token_path`` with UTF-8 encoding.
        """
        http_error = drive_http_error()
        token_file = Path(token_path)
        creds = self._load_credentials(token_file)

        if creds is None or not creds.valid:
            creds = self._renew_credentials(creds, Path(credentials_path))
            with open(token_file, "w", encoding="utf-8") as token_fp:
                token_fp.write(creds.to_json())

        try:
            self.creds = creds
            discovery = require_module("googleapiclient.discovery", extra=_EXTRA)
            self.service = discovery.build("drive", "v3", credentials=creds)
            file_automation_logger.info("GoogleDriveClient: service ready")
            return self.service
        except http_error as error:
            file_automation_logger.error("GoogleDriveClient init failed: %r", error)
            self.service = None
            raise

    def _load_credentials(self, token_file: Path) -> Any:
        if not token_file.exists():
            return None
        file_automation_logger.info("GoogleDriveClient: loading the saved token")
        credentials = require_module("google.oauth2.credentials", extra=_EXTRA)
        return credentials.Credentials.from_authorized_user_file(str(token_file), list(self.scopes))

    def _renew_credentials(self, creds: Any, credentials_file: Path) -> Any:
        if creds and creds.expired and creds.refresh_token:
            transport = require_module("google.auth.transport.requests", extra=_EXTRA)
            creds.refresh(transport.Request())
            return creds
        flow_module = require_module("google_auth_oauthlib.flow", extra=_EXTRA)
        flow = flow_module.InstalledAppFlow.from_client_secrets_file(
            str(credentials_file),
            list(self.scopes),
        )
        return flow.run_local_server(port=0)

    def require_service(self) -> Any:
        """Return ``self.service`` or raise if the client has not been initialised."""
        if self.service is None:
            raise RuntimeError(
                "GoogleDriveClient not initialised; call later_init(token, credentials) first"
            )
        return self.service


driver_instance: GoogleDriveClient = GoogleDriveClient()
