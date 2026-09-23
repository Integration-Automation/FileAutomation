"""Box client (Singleton Facade) backed by ``box_sdk_gen``.

``box_sdk_gen`` is the module shipped by the ``boxsdk`` distribution from 10.0 on; the legacy
``boxsdk.Client`` API it replaced is no longer developed. Box's OAuth2 flow is authorization-code
based (not device-code), so the caller is expected to obtain an access token via their app
registration and hand it in to :meth:`later_init`. Matches the Dropbox backend's contract —
automation workflows typically receive the token from a secrets manager rather than prompting
interactively.
"""

from __future__ import annotations

from typing import Any

from automation_file.exceptions import BoxException
from automation_file.logging_config import file_automation_logger


def import_box_sdk_gen() -> Any:
    """Import ``box_sdk_gen``, raising :class:`BoxException` when it is missing."""
    try:
        import box_sdk_gen
    except ImportError as error:
        raise BoxException(
            "box_sdk_gen import failed — install `boxsdk>=10` to restore the Box backend"
        ) from error
    return box_sdk_gen


class BoxClient:
    """Lazy wrapper around :class:`box_sdk_gen.BoxClient`."""

    def __init__(self) -> None:
        self.client: Any = None

    def later_init(
        self,
        access_token: str,
        *,
        client_id: str = "",
        client_secret: str = "",
    ) -> Any:
        """Build a :class:`box_sdk_gen.BoxClient` from an OAuth2 access token.

        ``client_id`` and ``client_secret`` are optional; when given they are passed to the
        developer-token auth so the token can be revoked through the SDK. Refreshing the token
        stays the caller's job, as most automation callers already refresh it externally.
        """
        if not isinstance(access_token, str) or not access_token:
            raise BoxException("access_token must be a non-empty string")
        sdk = import_box_sdk_gen()
        config = None
        if client_id or client_secret:
            config = sdk.DeveloperTokenConfig(
                client_id=client_id or None, client_secret=client_secret or None
            )
        auth = sdk.BoxDeveloperTokenAuth(token=access_token, config=config)
        self.client = sdk.BoxClient(auth=auth)
        file_automation_logger.info("BoxClient: client ready")
        return self.client

    def require_client(self) -> Any:
        """Return the initialised SDK client; raise :class:`BoxException` before ``later_init``."""
        if self.client is None:
            raise BoxException("BoxClient not initialised; call later_init() first")
        return self.client


box_instance: BoxClient = BoxClient()
