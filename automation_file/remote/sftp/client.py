"""SFTP client (Singleton Facade over ``paramiko``).

Host key policy is strict: unknown hosts raise ``SSHException``. Callers must
supply a ``known_hosts`` path (defaults to the OpenSSH user file) so that
host identity is pinned. We never fall back to ``AutoAddPolicy`` — silently
trusting new hosts defeats the point of SSH host verification.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from automation_file.core.optional import require_module
from automation_file.logging_config import file_automation_logger


def _import_paramiko() -> Any:
    return require_module("paramiko", extra="sftp")


@dataclass(frozen=True)
class SFTPConnectOptions:
    """Connection parameters for :meth:`SFTPClient.later_init`."""

    host: str
    username: str
    password: str | None = None
    key_filename: str | None = None
    port: int = 22
    known_hosts: str | None = None
    timeout: float = 15.0


class SFTPClient:
    """Paramiko SSH + SFTP facade with strict host-key verification."""

    def __init__(self) -> None:
        self._ssh: Any = None
        self._sftp: Any = None
        self._host: str | None = None
        self._port: int | None = None

    @property
    def host(self) -> str | None:
        """The host of the open session, or ``None`` while there is none."""
        return self._host

    @property
    def port(self) -> int | None:
        """The port of the open session, or ``None`` while there is none."""
        return self._port

    def later_init(self, options: SFTPConnectOptions | None = None, **kwargs: Any) -> Any:
        """Open the SSH + SFTP session. Raises if the host key is not pinned.

        Accepts either a prebuilt :class:`SFTPConnectOptions` instance or
        the same field names as keyword arguments (so action-registry
        callers can keep their existing kwargs form).
        """
        opts = options if options is not None else SFTPConnectOptions(**kwargs)
        paramiko = _import_paramiko()
        ssh = paramiko.SSHClient()
        resolved_known = opts.known_hosts or str(Path.home() / ".ssh" / "known_hosts")
        if Path(resolved_known).exists():
            ssh.load_host_keys(resolved_known)
        else:
            file_automation_logger.warning(
                "SFTPClient: known_hosts %s missing; unknown host will be rejected",
                resolved_known,
            )
        ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
        ssh.connect(
            hostname=opts.host,
            port=opts.port,
            username=opts.username,
            password=opts.password,
            key_filename=opts.key_filename,
            timeout=opts.timeout,
            allow_agent=False,
            look_for_keys=opts.key_filename is None,
        )
        self._ssh = ssh
        self._sftp = ssh.open_sftp()
        self._host = opts.host
        self._port = opts.port
        file_automation_logger.info(
            "SFTPClient: connected to %s@%s:%d", opts.username, opts.host, opts.port
        )
        return self._sftp

    def require_sftp(self) -> Any:
        if self._sftp is None:
            raise RuntimeError("SFTPClient not initialised; call later_init() first")
        return self._sftp

    def close(self) -> bool:
        """Close the underlying SFTP and SSH connections."""
        self._host = None
        self._port = None
        if self._sftp is not None:
            try:
                self._sftp.close()
            finally:
                self._sftp = None
        if self._ssh is not None:
            try:
                self._ssh.close()
            finally:
                self._ssh = None
        file_automation_logger.info("SFTPClient: closed")
        return True


sftp_instance: SFTPClient = SFTPClient()
