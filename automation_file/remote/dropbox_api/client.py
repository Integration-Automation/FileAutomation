"""Dropbox client (Singleton Facade)."""
from __future__ import annotations

from typing import Any

from automation_file.logging_config import file_automation_logger


def _import_dropbox() -> Any:
    try:
        import dropbox  # type: ignore[import-not-found]
    except ImportError as error:
        raise RuntimeError(
            "dropbox is required; install `automation_file[dropbox]`"
        ) from error
    return dropbox


class DropboxClient:
    """Lazy wrapper around :class:`dropbox.Dropbox`."""

    def __init__(self) -> None:
        self.client: Any = None

    def later_init(self, oauth2_access_token: str) -> Any:
        """Build a Dropbox client from a user-supplied OAuth2 access token."""
        dropbox = _import_dropbox()
        self.client = dropbox.Dropbox(oauth2_access_token)
        file_automation_logger.info("DropboxClient: client ready")
        return self.client

    def require_client(self) -> Any:
        if self.client is None:
            raise RuntimeError("DropboxClient not initialised; call later_init() first")
        return self.client


dropbox_instance: DropboxClient = DropboxClient()
