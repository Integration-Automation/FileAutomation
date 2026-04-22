"""FTP / FTPS client (Singleton Facade over :mod:`ftplib`).

FTPS uses :class:`ftplib.FTP_TLS` with explicit ``AUTH TLS`` after the control
connection is established. Implicit FTPS (``FTPS`` over a dedicated port with
TLS from the first byte) is not supported — it's effectively obsolete on
modern servers.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from ftplib import FTP, FTP_TLS  # nosec B321 - plaintext FTP is opt-in via tls=False
from typing import Any

from automation_file.exceptions import FileAutomationException
from automation_file.logging_config import file_automation_logger


class FTPException(FileAutomationException):
    """Raised when an FTP operation fails."""


@dataclass(frozen=True)
class FTPConnectOptions:
    host: str
    username: str = "anonymous"
    password: str = ""
    port: int = 21
    tls: bool = False
    timeout: float = 30.0
    passive: bool = True


class FTPClient:
    """Minimal FTP / FTPS session wrapper."""

    def __init__(self) -> None:
        self._ftp: FTP | None = None
        self._host: str = ""

    def later_init(self, options: FTPConnectOptions | None = None, **kwargs: Any) -> FTP:
        """Open an FTP control connection. TLS is negotiated when ``tls=True``."""
        opts = options if options is not None else FTPConnectOptions(**kwargs)
        # Plaintext FTP is opt-in via tls=False; FTPS is the default when tls=True.
        if opts.tls:
            ftp: FTP = FTP_TLS(timeout=opts.timeout)
        else:
            # Plaintext FTP only when caller opts in via tls=False.
            ftp = FTP(timeout=opts.timeout)  # nosec B321 NOSONAR python:S5332
        try:
            ftp.connect(opts.host, opts.port, timeout=opts.timeout)
            if opts.tls and isinstance(ftp, FTP_TLS):
                ftp.auth()
            ftp.login(user=opts.username, passwd=opts.password)
            if opts.tls and isinstance(ftp, FTP_TLS):
                ftp.prot_p()
            ftp.set_pasv(opts.passive)
        except OSError as err:
            with contextlib.suppress(OSError):
                ftp.close()
            raise FTPException(f"FTP connect failed: {err}") from err
        self._ftp = ftp
        self._host = opts.host
        file_automation_logger.info(
            "FTPClient: connected to %s@%s:%d (tls=%s)",
            opts.username,
            opts.host,
            opts.port,
            opts.tls,
        )
        return ftp

    def require_ftp(self) -> FTP:
        if self._ftp is None:
            raise FTPException("FTPClient not initialised; call later_init() first")
        return self._ftp

    def close(self) -> bool:
        if self._ftp is not None:
            try:
                self._ftp.quit()
            except OSError:
                with contextlib.suppress(OSError):
                    self._ftp.close()
            self._ftp = None
        file_automation_logger.info("FTPClient: closed")
        return True


ftp_instance: FTPClient = FTPClient()
