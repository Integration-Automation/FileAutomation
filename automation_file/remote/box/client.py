"""Box client (Singleton Facade) backed by the ``boxsdk`` library.

Box's OAuth2 flow is authorization-code based (not device-code), so the
caller is expected to obtain an access token via their app registration
and hand it in to :meth:`later_init`. Matches the Dropbox backend's
contract — automation workflows typically receive the token from a
secrets manager rather than prompting interactively.
"""

from __future__ import annotations

from typing import Any

from automation_file.exceptions import BoxException
from automation_file.logging_config import file_automation_logger


def _import_boxsdk() -> Any:
    try:
        import boxsdk
    except ImportError as error:
        raise BoxException(
            "boxsdk import failed — reinstall `automation_file` to restore the Box backend"
        ) from error
    return boxsdk


class BoxClient:
    """Lazy wrapper around :class:`boxsdk.Client`."""

    def __init__(self) -> None:
        self.client: Any = None

    def later_init(
        self,
        access_token: str,
        *,
        client_id: str = "",
        client_secret: str = "",
    ) -> Any:
        """Build a :class:`boxsdk.Client` from an OAuth2 access token.

        ``client_id`` and ``client_secret`` are only required if the caller
        wants to let boxsdk refresh the token — most automation callers
        already refresh externally, so both default to empty.
        """
        if not isinstance(access_token, str) or not access_token:
            raise BoxException("access_token must be a non-empty string")
        boxsdk = _import_boxsdk()
        oauth = boxsdk.OAuth2(
            client_id=client_id,
            client_secret=client_secret,
            access_token=access_token,
        )
        self.client = boxsdk.Client(oauth)
        file_automation_logger.info("BoxClient: client ready")
        return self.client

    def require_client(self) -> Any:
        if self.client is None:
            raise BoxException("BoxClient not initialised; call later_init() first")
        return self.client


box_instance: BoxClient = BoxClient()
