"""OneDrive client (Singleton Facade) backed by Microsoft Graph + MSAL.

The client supports two initialisation paths:

* :meth:`later_init` — caller passes an already-obtained OAuth2 access
  token. Matches the Dropbox backend's pattern; best for non-interactive
  automation where a token is injected via secrets manager.
* :meth:`device_code_login` — runs the MSAL device-code flow against
  Microsoft's ``/common`` (or tenant-specific) authority. The caller is
  expected to present the returned ``message`` to a human, who signs in at
  the displayed URL. Blocks until the user completes the flow or the code
  expires.

Only the bare Graph HTTP session is held on the client — every ``*_ops``
module calls Graph through the helper :meth:`graph_request`, which keeps
the ``Authorization: Bearer`` header + JSON content-type handling in one
place.
"""

from __future__ import annotations

from typing import Any

import requests

from automation_file.exceptions import OneDriveException
from automation_file.logging_config import file_automation_logger

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_DEFAULT_SCOPES = ("Files.ReadWrite", "Files.ReadWrite.All")
_DEFAULT_AUTHORITY = "https://login.microsoftonline.com/common"


def _import_msal() -> Any:
    try:
        import msal
    except ImportError as error:
        raise OneDriveException(
            "msal import failed — reinstall `automation_file` to restore the OneDrive backend"
        ) from error
    return msal


class OneDriveClient:
    """Lazy wrapper holding an access token and a :class:`requests.Session`."""

    def __init__(self) -> None:
        self._access_token: str | None = None
        self._session: requests.Session | None = None

    def later_init(self, access_token: str) -> bool:
        """Install a pre-obtained OAuth2 access token. Returns True on success."""
        if not isinstance(access_token, str) or not access_token:
            raise OneDriveException("access_token must be a non-empty string")
        self._access_token = access_token
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {access_token}"
        file_automation_logger.info("OneDriveClient: access token installed")
        return True

    def device_code_login(
        self,
        client_id: str,
        *,
        tenant_id: str | None = None,
        scopes: tuple[str, ...] | None = None,
        timeout: int = 300,
    ) -> dict[str, Any]:
        """Run MSAL's device-code flow and install the resulting token.

        Blocks until the user completes the login (or ``timeout`` seconds
        elapse). Returns the raw MSAL token dict so callers can inspect
        claims / refresh window. The message to present to the user is in
        the MSAL log — it is not returned here to avoid leaking it into an
        action-result payload.
        """
        msal = _import_msal()
        authority = (
            f"https://login.microsoftonline.com/{tenant_id}" if tenant_id else _DEFAULT_AUTHORITY
        )
        app = msal.PublicClientApplication(client_id=client_id, authority=authority)
        flow = app.initiate_device_flow(scopes=list(scopes or _DEFAULT_SCOPES))
        if "user_code" not in flow:
            raise OneDriveException(
                f"device-code flow init failed: {flow.get('error_description', flow)}"
            )
        file_automation_logger.info("OneDriveClient: %s", flow.get("message", ""))
        flow["expires_at"] = flow.get("expires_in", timeout)
        result = app.acquire_token_by_device_flow(flow)
        access_token = result.get("access_token")
        if not access_token:
            raise OneDriveException(
                f"device-code login failed: {result.get('error_description', result)}"
            )
        self.later_init(access_token)
        return result

    def require_session(self) -> requests.Session:
        if self._session is None:
            raise OneDriveException(
                "OneDriveClient not initialised; call later_init() or device_code_login() first"
            )
        return self._session

    def graph_request(
        self,
        method: str,
        path: str,
        *,
        timeout: float = 30.0,
        **request_kwargs: Any,
    ) -> requests.Response:
        """Issue a Microsoft Graph API request against ``/me/drive`` (or a full URL).

        Paths starting with ``/`` are joined onto the base
        ``https://graph.microsoft.com/v1.0`` endpoint; absolute ``https://``
        URLs are used verbatim (handy for the ``@microsoft.graph.downloadUrl``
        redirect Graph hands out for file contents). ``request_kwargs`` is
        forwarded to :meth:`requests.Session.request` — ``params``, ``json``,
        ``data``, and ``headers`` are the common ones.
        """
        session = self.require_session()
        url = path if path.startswith("http") else f"{_GRAPH_BASE}{path}"
        try:
            response = session.request(method, url, timeout=timeout, **request_kwargs)
        except requests.RequestException as error:
            raise OneDriveException(f"graph request failed: {error}") from error
        if not response.ok:
            raise OneDriveException(
                f"graph {method} {path} returned {response.status_code}: {response.text[:200]}"
            )
        return response

    def close(self) -> bool:
        if self._session is not None:
            self._session.close()
            self._session = None
        self._access_token = None
        return True


onedrive_instance: OneDriveClient = OneDriveClient()
