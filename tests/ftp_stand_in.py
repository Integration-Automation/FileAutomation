"""An FTP server held in memory, and an ``ftplib.FTP`` connected to it without sockets.

:class:`FakeFTP` is a real ``ftplib.FTP`` whose control and data connections lead
to a :class:`FakeFTPServer`. ftplib itself therefore builds every command, parses
every reply and raises its own exceptions; the server only answers as an FTP
server does. Options select the behaviours real servers differ in: ``MLST`` /
``MLSD`` or not, ``NLST`` answering with names or with paths, an empty directory
answered with 550, and a rename that will not replace an existing file.
"""

from __future__ import annotations

import ftplib  # nosec B402 - the sessions built here lead to an in-memory server
import io
import posixpath
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

MODIFIED = datetime(2026, 10, 8, 2, 30, 15, 250000, tzinfo=timezone.utc)
NO_SUCH_FILE = "550 No such file or directory."


@dataclass
class _Entry:
    """A directory (neither data nor target), a file (data) or a symbolic link (target)."""

    data: bytes | None = None
    target: str | None = None
    modified: datetime = MODIFIED

    @property
    def is_dir(self) -> bool:
        return self.data is None and self.target is None

    @property
    def is_file(self) -> bool:
        return self.data is not None


class _DataConnection:
    """What ``ftplib`` gets from ``transfercmd``: a socket that is read or written, then closed."""

    def __init__(self, payload: bytes, on_close: Callable[[bytes], None]) -> None:
        self._outgoing = io.BytesIO(payload)
        self._incoming = bytearray()
        self._on_close = on_close

    def recv(self, size: int) -> bytes:
        return self._outgoing.read(size)

    def sendall(self, data: bytes) -> None:
        self._incoming += data

    def makefile(self, mode: str, encoding: str | None = None) -> io.TextIOWrapper:
        return io.TextIOWrapper(io.BytesIO(self._outgoing.read()), encoding=encoding)

    def close(self) -> None:
        self._on_close(bytes(self._incoming))

    def __enter__(self) -> _DataConnection:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class FakeFTPServer:
    """An FTP server in memory: a tree of entries and the far end of one control connection."""

    def __init__(
        self,
        *,
        mlst: bool = True,
        rename_replaces: bool = True,
        nlst_paths: bool = False,
        empty_nlst_refused: bool = False,
    ) -> None:
        self.entries: dict[str, _Entry] = {"/": _Entry()}
        self.cwd = "/"
        self.commands: list[str] = []
        self.refusals: dict[str, str] = {}
        self.transfer_error: str | None = None
        self.send_error: Exception | None = None
        self.hung_up = False
        self.extra_listing: list[str] = []
        self.raw_listing = b""
        self._offers_mlst = mlst
        self._rename_replaces = rename_replaces
        self._nlst_paths = nlst_paths
        self._empty_nlst_refused = empty_nlst_refused
        self._binary = False
        self._rename_from: str | None = None
        self._replies: deque[str] = deque()
        self._scripted: dict[tuple[str, int], str] = {}
        self._data: _DataConnection | None = None

    # ------------------------------------------------------------------ the tree

    def mkdir(self, path: str) -> None:
        self.entries[path] = _Entry()

    def write(self, path: str, data: bytes) -> None:
        self.entries[path] = _Entry(data=data)

    def link(self, path: str, target: str) -> None:
        self.entries[path] = _Entry(target=target)

    def read(self, path: str) -> bytes:
        data = self.entries[path].data
        assert data is not None
        return data

    def paths(self) -> list[str]:
        return sorted(key for key in self.entries if key != "/")

    def verbs(self) -> list[str]:
        return [command.partition(" ")[0] for command in self.commands]

    def answer_the_nth(self, verb: str, nth: int, reply: str) -> None:
        """Answer the ``nth`` command ``verb`` with ``reply`` instead of carrying it out."""
        self._scripted[(verb, nth)] = reply

    def _path(self, argument: str) -> str:
        return posixpath.normpath(posixpath.join(self.cwd, argument))

    def _real(self, path: str, *, follow: bool = True) -> str:
        """Resolve the links in ``path`` as a server does; the last one only when ``follow``."""
        parts = [part for part in path.split("/") if part]
        current = "/"
        for index, part in enumerate(parts):
            current = posixpath.join(current, part)
            entry = self.entries.get(current)
            linked = entry is not None and entry.target is not None
            if linked and (follow or index < len(parts) - 1):
                current = self._real(posixpath.join(posixpath.dirname(current), entry.target))
        return current

    def _found(self, argument: str, *, follow: bool = True) -> tuple[str, _Entry | None]:
        """Return where the argument of a command leads and the entry there, if any."""
        real = self._real(self._path(argument), follow=follow)
        return real, self.entries.get(real)

    def _holds(self, real: str) -> bool:
        """Say whether an entry can be made at ``real``: its parent is a directory."""
        parent = self.entries.get(posixpath.dirname(real))
        return parent is not None and parent.is_dir

    def _children(self, real: str) -> list[str]:
        return sorted(
            posixpath.basename(key)
            for key in self.entries
            if key != "/" and posixpath.dirname(key) == real
        )

    def _facts(self, entry: _Entry, kind: str | None = None) -> str:
        modify = f"{entry.modified:%Y%m%d%H%M%S}.{entry.modified.microsecond // 1000:03d}"
        if entry.target is not None:
            return f"Type=OS.unix=slink:{entry.target};size={len(entry.target)};Modify={modify};"
        if entry.is_dir:
            return f"Type={kind or 'dir'};sizd=4096;Modify={modify};"
        return f"Type=file;size={len(entry.data or b'')};Modify={modify};"

    # ------------------------------------------------------------------ the control connection

    def sendall(self, data: bytes) -> None:
        """Receive one command line from the client, as the control socket would."""
        if self.send_error is not None:
            raise self.send_error
        line = data.decode("utf-8")
        assert line.endswith("\r\n")
        self.commands.append(line[:-2])
        if self.hung_up:
            return
        verb, _, argument = line[:-2].partition(" ")
        handler = getattr(self, f"_do_{verb.lower()}", None)
        scripted = self._scripted.pop((verb, self.verbs().count(verb)), None)
        if scripted is not None or verb in self.refusals:
            self._reply(scripted or self.refusals[verb])
        elif handler is None:
            self._reply("500 Unknown command.")
        else:
            handler(argument)

    def readline(self, limit: int) -> str:
        """Hand the client the next reply line; an empty one is how a closed connection reads."""
        return self._replies.popleft() if self._replies else ""

    def close(self) -> None:
        self.hung_up = True

    def data_connection(self) -> _DataConnection:
        assert self._data is not None
        connection, self._data = self._data, None
        return connection

    def _reply(self, text: str) -> None:
        self._replies.extend(f"{line}\r\n" for line in text.split("\n"))

    def _transfer(self, payload: bytes, done: Callable[[bytes], None]) -> None:
        self._data = _DataConnection(payload, done)
        self._reply("150 Opening data connection.")

    def _send(self, payload: bytes) -> None:
        self._transfer(
            payload, lambda _: self._reply(self.transfer_error or "226 Transfer complete.")
        )

    def _send_lines(self, lines: list[str]) -> None:
        self._send("".join(f"{line}\r\n" for line in lines).encode("utf-8") + self.raw_listing)

    # ------------------------------------------------------------------ the commands

    def _do_pwd(self, _: str) -> None:
        self._reply(f'257 "{self.cwd}" is the current directory')

    def _do_cwd(self, argument: str) -> None:
        entry = self._found(argument)[1]
        if entry is None or not entry.is_dir:
            self._reply("550 Failed to change directory.")
            return
        self.cwd = self._path(argument)
        self._reply("250 Directory successfully changed.")

    def _do_type(self, argument: str) -> None:
        self._binary = argument == "I"
        self._reply(f"200 Type set to {argument}.")

    def _do_feat(self, _: str) -> None:
        features = [" MDTM", " SIZE", " UTF8"]
        if self._offers_mlst:
            features.insert(1, " MLST type*;size*;sizd*;modify*;perm;")
        self._reply("\n".join(["211-Features:", *features, "211 End"]))

    def _do_opts(self, argument: str) -> None:
        if self._offers_mlst and argument.upper().startswith("MLST"):
            self._reply(f"200 {argument}")
        else:
            self._reply("501 Option not understood.")

    def _do_mlst(self, argument: str) -> None:
        path = self._path(argument)
        entry = self._found(argument, follow=False)[1]
        if not self._offers_mlst:
            self._reply("500 Unknown command.")
        elif entry is None:
            self._reply(NO_SUCH_FILE)
        else:
            listed = f" {self._facts(entry)} {path}"
            self._reply("\n".join([f"250-Listing {path}", listed, "250 End"]))

    def _do_mlsd(self, argument: str) -> None:
        real, entry = self._found(argument)
        if not self._offers_mlst:
            self._reply("500 Unknown command.")
        elif entry is None or not entry.is_dir:
            self._reply(NO_SUCH_FILE)
        else:
            lines = [f"{self._facts(entry, 'cdir')} .", f"{self._facts(entry, 'pdir')} .."]
            lines += [
                f"{self._facts(self.entries[posixpath.join(real, name)])} {name}"
                for name in self._children(real)
            ]
            self._send_lines(lines + self.extra_listing)

    def _do_nlst(self, argument: str) -> None:
        real, entry = self._found(argument)
        names = self._children(real)
        if entry is None or not entry.is_dir or (self._empty_nlst_refused and not names):
            self._reply("550 No files found.")
            return
        self._binary = False
        shown = self._path(argument)
        self._send_lines(
            [posixpath.join(shown, name) if self._nlst_paths else name for name in names]
        )

    def _do_size(self, argument: str) -> None:
        entry = self._found(argument)[1]
        if not self._binary:
            self._reply("550 SIZE not allowed in ASCII mode")
        elif entry is None or entry.data is None:
            self._reply("550 Could not get file size.")
        else:
            self._reply(f"213 {len(entry.data)}")

    def _do_mdtm(self, argument: str) -> None:
        entry = self._found(argument)[1]
        if entry is None or not entry.is_file:
            self._reply("550 Could not get file modification time.")
        else:
            self._reply(f"213 {entry.modified:%Y%m%d%H%M%S}")

    def _do_retr(self, argument: str) -> None:
        entry = self._found(argument)[1]
        if entry is None or entry.data is None:
            self._reply("550 Failed to open file.")
        else:
            self._send(entry.data)

    def _do_stor(self, argument: str) -> None:
        real, entry = self._found(argument)
        if not self._holds(real) or (entry is not None and entry.is_dir):
            self._reply("553 Could not create file.")
            return

        def stored(data: bytes) -> None:
            kept = data if self.transfer_error is None else data[: len(data) // 2]
            self.entries[real] = _Entry(data=kept, modified=datetime.now(timezone.utc))
            self._reply(self.transfer_error or "226 Transfer complete.")

        self._transfer(b"", stored)

    def _do_dele(self, argument: str) -> None:
        real, entry = self._found(argument, follow=False)
        if entry is None or entry.is_dir:
            self._reply("550 Delete operation failed.")
            return
        del self.entries[real]
        self._reply("250 Delete operation successful.")

    def _do_mkd(self, argument: str) -> None:
        real, entry = self._found(argument, follow=False)
        if entry is not None or not self._holds(real):
            self._reply("550 Create directory operation failed.")
            return
        self.entries[real] = _Entry(modified=datetime.now(timezone.utc))
        self._reply(f'257 "{real}" created')

    def _do_rmd(self, argument: str) -> None:
        real, entry = self._found(argument, follow=False)
        if entry is None or not entry.is_dir or self._children(real) or real == "/":
            self._reply("550 Remove directory operation failed.")
            return
        del self.entries[real]
        self._reply("250 Remove directory operation successful.")

    def _do_rnfr(self, argument: str) -> None:
        real, entry = self._found(argument, follow=False)
        if entry is None:
            self._reply("550 RNFR command failed.")
            return
        self._rename_from = real
        self._reply("350 Ready for RNTO.")

    def _do_rnto(self, argument: str) -> None:
        origin, self._rename_from = self._rename_from, None
        target, existing = self._found(argument, follow=False)
        if origin is None:
            self._reply("503 RNFR required first.")
        elif not self._holds(target) or (existing is not None and existing.is_dir):
            self._reply("550 Rename failed.")
        elif existing is not None and not self._rename_replaces:
            self._reply("550 Cannot create a file when that file already exists.")
        else:
            self.entries[target] = self.entries.pop(origin)
            self._reply("250 Rename successful.")


class FakeFTP(ftplib.FTP):
    """A real ``ftplib.FTP`` connected to a :class:`FakeFTPServer` instead of to sockets."""

    def __init__(self, server: FakeFTPServer) -> None:
        super().__init__()
        self.server = server
        self.sock = server
        self.file = server

    def ntransfercmd(self, cmd: str, rest: Any = None) -> tuple[Any, None]:
        """Open the data connection: where ftplib would dial the server's passive port."""
        reply = self.sendcmd(cmd)
        if reply[0] != "1":
            raise ftplib.error_reply(reply)
        return self.server.data_connection(), None


class FakeFTPS(FakeFTP, ftplib.FTP_TLS):
    """The same stand-in as an ``FTP_TLS`` session, which is what marks a session as FTPS."""
