Universal storage layer
=======================

``automation_file.storage`` gives every storage one address syntax, one set of
operations and one set of errors. :class:`~automation_file.File` and
:class:`~automation_file.Storage` are the application API;
:class:`~automation_file.StorageBackend` is the contract a backend implements.

The ``FA_*`` actions and the per-backend functions (``s3_upload_file``,
``sftp_download_file`` …) are unchanged and keep working next to it.

.. note::

   The layer is new and its API may still change before 1.0. Twelve backends are
   built in: the local filesystem, an in-memory store, S3, Azure Blob, Google
   Drive, Dropbox, OneDrive, SFTP, FTP / FTPS, WebDAV, SMB and anything fsspec
   can address. Box has no adapter: it is reached through its ``FA_box_*``
   actions only (:doc:`cloud`). Each remote backend needs its extra installed
   (``pip install "automation_file[s3]"``) and its client initialised, as its
   entry under `Built-in backends`_ says.

Quick start
-----------

.. code-block:: python

   from automation_file import File, Storage

   report = File("local:///data/reports/q1.csv")     # or just "reports/q1.csv"
   report.write("region,total\nEMEA,42\n")
   report.exists()                                    # True
   report.size                                        # 21
   report.read_text()
   report.checksum()                                  # Checksum("sha256", "…")
   report.verify("sha256:9f86d081…")                  # constant-time compare

   archive = report.copy_to("memory://scratch/archive/q1.csv")
   report.move_to("local:///data/done/q1.csv")

   reports = Storage("local:///data/reports")
   for info in reports.list_dir(recursive=True):
       print(info.path, info.size, info.modified_at)
   reports.upload("q2.csv", "2026/q2.csv")
   reports.file("2026/q2.csv").download_to("copy-of-q2.csv")
   reports.delete("2026", recursive=True)

Creating a ``File`` or a ``Storage`` touches nothing. The backend is looked up
on every call, so an object can be created before its backend is initialised or
mounted.

Storage URIs
------------

.. code-block:: text

   <scheme>://<authority>/<path>

   local:///data/report.csv          s3://bucket/report.csv
   local:///C:/data/report.csv       azure://container/report.csv
   sftp://server/data/report.csv     dropbox:///reports/report.csv
   memory://scratch/report.csv       smb://server/share/report.csv

``scheme``
    Picks the backend. Lower-cased. ``file`` is an alias of ``local`` and ``az``
    of ``azure``.

``authority``
    What the backend needs to find its root: a bucket, a container, a host. Kept
    as written. Credentials never belong in a URI, so ``user@host`` and
    ``user:password@host`` are rejected, and the error message does not repeat
    them.

``path``
    Taken literally. Nothing is percent-decoded and ``?`` and ``#`` are ordinary
    characters, so ``s3://bucket/Q1 #3?.csv`` names exactly that key. Empty and
    ``.`` segments are dropped. A ``..`` segment is an error, so a path can never
    climb out of the root it is joined to.

Local paths
    Text without ``://`` is a filesystem path and is made absolute:
    ``reports/a.csv``, ``/data/a.csv`` and ``C:\data\a.csv`` work as they are,
    and so does a :class:`pathlib.Path`. On Windows a UNC path
    ``\\server\share\a.csv`` is ``local://server/share/a.csv``.

Ambiguous text
    ``sftp:/data/a.csv`` could be a URI with a slash missing or a local file
    called ``sftp:``. It is rejected, and the message gives both unambiguous
    spellings: ``sftp://…`` for the URI, ``./sftp:/data/a.csv`` for the file.

:func:`~automation_file.parse_storage_uri` returns a frozen
:class:`~automation_file.StorageURI` with ``scheme``, ``authority``, ``path``,
``name``, ``parent`` and ``joinpath()``. Malformed input raises
:class:`~automation_file.StorageURIException`.

Operations
----------

Every backend has the same methods. ``File`` and ``Storage`` forward to them.

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Method
     - Behaviour
   * - ``exists(path)``
     - ``True`` for a file or a directory.
   * - ``stat(path)``
     - Returns a :class:`~automation_file.FileInfo`. Missing path:
       ``StorageNotFoundException``.
   * - ``list_dir(path="", recursive=False)``
     - Entries sorted by path. ``recursive=True`` returns every descendant,
       directories included. A file: ``StoragePathTypeException``.
   * - ``mkdir(path, parents=True, exist_ok=True)``
     - Creates a directory. On a backend where directories are only implied by
       file paths, nothing is created and nothing needs to be.
   * - ``upload(local_path, path, overwrite=True)``
     - Stores a local file and creates missing parent directories. With
       ``overwrite=False`` an existing file raises
       ``StorageAlreadyExistsException``.
   * - ``download(path, local_path, overwrite=True)``
     - Writes to a sibling ``.part`` file that replaces the target when complete,
       so a failed download never leaves a truncated file.
   * - ``delete(path, recursive=False, missing_ok=False)``
     - A directory with entries needs ``recursive=True``
       (``StorageNotEmptyException`` otherwise). The storage root is never
       deleted.
   * - ``checksum(path, algorithm="sha256")``
     - Returns a :class:`~automation_file.Checksum`. Any fixed-length
       ``hashlib`` algorithm: ``sha256``, ``sha512``, ``blake2b``, ``md5`` (for
       compatibility, not for security).
   * - ``read_bytes(path)`` / ``write_bytes(path, data)``
     - Whole-file content.
   * - ``open_read(path)`` / ``open_write(path, overwrite=True)``
     - Binary file objects, for content too large to hold in memory. What is
       written is stored when the object is closed; leaving a ``with`` block
       through an exception stores nothing.
   * - ``copy_from(source, source_path, path)`` / ``move_from(…)``
     - Transfer from any backend, this one included. Native when the two backends
       can do it between themselves (a local rename), through a local staging
       file otherwise.

``FileInfo`` carries ``path``, ``name``, ``is_dir``, ``size``, ``modified_at``
(timezone-aware UTC), ``etag``, ``version``, ``content_type`` and ``metadata``.
Fields a backend cannot provide are ``None``. ``FileInfo.to_dict()`` and
``Checksum.to_dict()`` are JSON-serialisable.

``backend.capabilities`` is a :class:`~automation_file.StorageCapabilities` that
says which optional ``FileInfo`` fields the backend fills in and whether its
directories are real (``directories=True``, a filesystem) or implied by file
paths (``directories=False``, an object store).

Actions
-------

The layer is also reachable from JSON action lists, and so from the CLI, the TCP
and HTTP action servers and MCP hosts. Every ``FA_storage_*`` action takes URIs as
strings and returns JSON-friendly values.

.. list-table::
   :header-rows: 1
   :widths: 28 40 32

   * - Action
     - Parameters
     - Returns
   * - ``FA_storage_exists``
     - ``uri``
     - ``true`` / ``false``
   * - ``FA_storage_stat``
     - ``uri``
     - The file information
   * - ``FA_storage_list``
     - ``uri, recursive=False``
     - A list of file information
   * - ``FA_storage_mkdir``
     - ``uri, parents=True, exist_ok=True``
     - ``True``
   * - ``FA_storage_upload``
     - ``local_path, uri, overwrite=True``
     - The file information
   * - ``FA_storage_download``
     - ``uri, local_path, overwrite=True``
     - The local path
   * - ``FA_storage_delete``
     - ``uri, recursive=False, missing_ok=False``
     - ``True``
   * - ``FA_storage_checksum``
     - ``uri, algorithm="sha256"``
     - ``{"algorithm": …, "value": …}``
   * - ``FA_storage_verify``
     - ``uri, expected, algorithm="sha256"``
     - ``true`` / ``false``
   * - ``FA_storage_copy``
     - ``source, target, overwrite=True``
     - The target's file information
   * - ``FA_storage_move``
     - ``source, target, overwrite=True``
     - The target's file information
   * - ``FA_storage_read_text``
     - ``uri, encoding="utf-8"``
     - The content as text
   * - ``FA_storage_write_text``
     - ``uri, text, overwrite=True, encoding="utf-8"``
     - The file information
   * - ``FA_storage_copy_tree``
     - ``source, target, overwrite=True``
     - A summary: ``copied``, ``skipped``, ``deleted``, ``errors``, ``dry_run``
   * - ``FA_storage_sync``
     - ``source, target, delete=False, checksum=False, dry_run=False``
     - A summary: ``copied``, ``skipped``, ``deleted``, ``errors``, ``dry_run``
   * - ``FA_storage_schemes``
     - —
     - The registered schemes

File information is ``FileInfo.to_dict()`` plus a ``uri`` key: ``uri``, ``path``,
``name``, ``is_dir``, ``size``, ``modified_at`` (ISO 8601), ``etag``, ``version``,
``content_type`` and ``metadata``. In ``FA_storage_list`` each ``path`` is relative
to the listed URI. A failure raises the exception from `Errors`_, which the
executor records for that action without stopping the list.

.. code-block:: json

   [
     ["FA_storage_copy", {"source": "s3://reports/2026/q1.csv",
                          "target": "local:///backup/2026/q1.csv"}],
     ["FA_storage_verify", {"uri": "local:///backup/2026/q1.csv",
                            "expected": "sha256:9f86d081884c7d65…"}],
     ["FA_storage_list", {"uri": "s3://reports/2026", "recursive": true}]
   ]

Like the other file actions, these reach whatever the process can reach. On a TCP
or HTTP action server pass an :class:`~automation_file.ActionACL`, and on the MCP
server ``--allowed-actions``, to expose only the ones a client needs.
:func:`~automation_file.register_storage_ops` adds them to a registry of your own.

Errors
------

All derive from :class:`~automation_file.StorageException`, itself a
``FileAutomationException``.

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Exception
     - Raised when
   * - ``StorageURIException``
     - A URI or path is malformed or ambiguous, or no backend serves it.
   * - ``StorageNotFoundException``
     - A path, or the local source of an upload, is missing. Also a
       ``FileNotExistsException``, so existing handlers keep working.
   * - ``StorageAlreadyExistsException``
     - A write would replace something and ``overwrite`` / ``exist_ok`` is off.
   * - ``StoragePathTypeException``
     - A file operation targets a directory, or the reverse.
   * - ``StorageNotEmptyException``
     - A directory with entries is deleted without ``recursive=True``.
   * - ``StoragePermissionException``
     - The backend denies access.
   * - ``StorageTransientException``
     - A failure worth retrying: timeout, dropped connection, throttling. Use it
       as the ``retriable=`` type of ``retry_on_transient``.
   * - ``StorageUnavailableException``
     - The backend is not initialised or its SDK is not installed.
   * - ``StorageUnsupportedException``
     - The backend cannot do what was asked (an unknown checksum algorithm,
       deleting the root).

Built-in backends
-----------------

``LocalStorage`` (``local://``, alias ``file://``)
    ``LocalStorage()`` spans the whole filesystem and is what ``local:///…``
    resolves to. ``LocalStorage(root)`` is confined to one directory tree: every
    path goes through :func:`~automation_file.safe_join`, so a path that leaves
    the root through a symbolic link raises ``PathTraversalException``. Use a
    rooted instance whenever paths come from outside the process.

    Symbolic links are followed when reading and writing. Deleting never follows
    them: the link is removed and its target is left alone. Recursive listing
    does not descend into linked directories. Writes go through a temporary
    sibling file and replace the target atomically.

``MemoryStorage`` (``memory://<name>/…``)
    A thread-safe tree held in memory, for tests, dry runs and examples. Each
    ``<name>`` is a separate store, created on first use.

``S3Storage`` (``s3://<bucket>/<key>``)
    One bucket through the shared ``s3_instance``, initialised as before with
    ``s3_instance.later_init(...)`` or ``FA_s3_later_init``.
    ``S3Storage(bucket, client=...)`` takes another boto3 client (another
    account, MinIO), and ``prefix=`` confines the backend to the keys below one
    prefix. Uploads set ``ContentType`` from the key's suffix. ``stat`` reports
    size, modification time, ETag, content type, version ID and metadata. A copy
    between two S3 locations that share a client is done by S3 itself.

``AzureStorage`` (``azure://<container>/<blob>``, alias ``az://``)
    One container through the shared ``azure_blob_instance``
    (``azure_blob_instance.later_init(...)`` or ``FA_azure_blob_later_init``), or
    ``AzureStorage(container, service=...)`` for another ``BlobServiceClient``
    such as the Azurite emulator. ``prefix=`` works as for S3, and ``stat``
    reports the same fields.

S3 and Azure Blob are object stores. A directory exists only while a key lies
below it, so ``mkdir`` creates nothing and an empty directory cannot exist
(``capabilities.directories`` is ``False``). A key ending in ``/`` that another
tool wrote as a folder placeholder is shown as a directory, never as a file.
Checksums are computed from the content and not taken from the ETag, which is
not a digest of a multipart upload. Until the client is initialised, every call
raises ``StorageUnavailableException``.

.. code-block:: python

   from automation_file import File, azure_blob_instance, s3_instance

   s3_instance.later_init(region_name="us-east-1")
   azure_blob_instance.later_init(connection_string=connection_string)
   File("s3://reports/2026/q1.csv").copy_to("azure://backups/2026/q1.csv")

``SFTPStorage`` (``sftp://<host>[:<port>]/<absolute path>``)
    The files one SFTP session can reach, through the shared ``sftp_instance``.
    Open the session as before, with ``sftp_instance.later_init(host=...,
    username=..., ...)`` or ``FA_sftp_later_init``: the host key is checked
    against ``known_hosts`` and an unknown host is rejected. The path of the URI
    is the absolute path on the server, so ``sftp://nas/data/q1.csv`` is
    ``/data/q1.csv`` and not a path below the login directory.

    The host may be left out (``sftp:///data/q1.csv``), which means "the open
    session". A host that is named must be the one the session is connected to;
    letter case is ignored, and a port, when given, must match as well. Any other
    host raises ``StorageURIException``. To reach a second host, connect another
    ``SFTPClient`` and mount a backend for it:
    ``Storage.mount("sftp://backup", SFTPStorage(client))``.
    ``SFTPStorage(client, root="/srv/data")`` joins every path to one remote
    directory. ``root`` is a path prefix and not a jail: a symbolic link on the
    server can still lead out of it.

    ``stat`` reports the size and the modification time the server returns, in
    UTC and whole seconds. A move within one session is a rename; a copy goes
    through a local temporary file, because SFTP has no copy of its own.

    Symbolic links are followed when reading and writing. Deleting never follows
    them: the link is removed and its target is left alone. Recursive listing
    does not descend into linked directories. A link whose target is gone is
    listed, while ``exists`` and ``stat`` report it missing.

``FTPStorage`` (``ftp://<host>[:<port>]/<absolute path>``, ``ftps://…``)
    The files one FTP or FTPS session can reach, through the shared
    ``ftp_instance``. Open the session as before, with
    ``ftp_instance.later_init(host=..., username=..., password=..., tls=True)``
    or ``FA_ftp_later_init``. The host rule, ``root=`` and the absolute paths
    are those of ``SFTPStorage``; for a second host, mount
    ``FTPStorage(client)`` with another connected ``FTPClient``. ``ftps://`` is
    refused with ``StorageURIException`` unless the open session was started
    with ``tls=True``; ``ftp://`` accepts either kind. Plain FTP sends the
    password and the files unencrypted.

    On a server that offers ``MLST`` / ``MLSD`` (RFC 3659), ``stat`` reports the
    type, the size and the modification time (UTC) from the server's facts. Any
    other server is probed: a directory is what ``CWD`` enters, a file is what
    ``SIZE`` and ``MDTM`` answer for, and a listing is ``NLST`` followed by up to
    three commands for each name. That is slower, a directory then has no
    modification time, and files the server hides from ``NLST`` (often those
    whose name starts with a dot) are not listed. The working directory of the
    session is put back after each probe.

    FTP answers "no such file" and "not allowed" with the same reply code, 550.
    ``exists``, ``stat`` and listings read it as "missing"; an upload, a
    download or a delete reads it as ``StoragePermissionException``. A path that
    contains a line break is refused with ``StorageURIException``.

    Deleting never follows a symbolic link, on either kind of server. Listing
    depends on the server: where ``MLSD`` marks links they are listed as files
    and not entered, while a probed server shows a link to a directory as a
    directory, and a recursive listing descends into it.

SFTP and FTP have real directories (``capabilities.directories`` is ``True``):
``mkdir`` creates one and an empty directory can exist. Neither reports an ETag,
a version, a content type or metadata, and checksums are computed from the
downloaded content. An upload is written to a hidden ``.part`` file next to the
target and renamed over it, so a failed upload never leaves a truncated file. A
server that will not rename onto an existing file (SFTP without the
``posix-rename@openssh.com`` extension, FTP on Windows) has that file moved
aside first and removed afterwards, and put back if the rename still fails; that
replacement is not atomic.

A session carries one operation at a time, so calls on the same session wait for
each other. The ``FA_sftp_*`` / ``FA_ftp_*`` actions do not take part in that:
do not run them on a session while another thread uses it through the storage
layer. Until ``later_init`` has run, every call raises
``StorageUnavailableException``. A lost or timed-out connection raises
``StorageTransientException``; the layer does not reconnect, so call
``later_init`` again before retrying.

.. code-block:: python

   from automation_file import (
       File, SFTPClient, SFTPStorage, Storage, ftp_instance, sftp_instance,
   )

   sftp_instance.later_init(host="nas.example", username="ops",
                            key_filename="/home/ops/.ssh/id_ed25519")
   ftp_instance.later_init(host="files.example", username="ops",
                           password=password, tls=True)

   File("sftp://nas.example/exports/q1.csv").copy_to("ftps://files.example/incoming/q1.csv")
   File("sftp:///exports/q1.csv").move_to("sftp:///archive/2026/q1.csv")   # one rename

   # A second host: its own client, mounted under its own authority.
   backup = SFTPClient()
   backup.later_init(host="backup.example", username="ops")
   Storage.mount("sftp://backup.example", SFTPStorage(backup, root="/srv/backups"))
   File("sftp:///archive/2026/q1.csv").copy_to("sftp://backup.example/2026/q1.csv")

``DropboxStorage`` (``dropbox:///<path>``)
    The Dropbox of the shared ``dropbox_instance``, initialised as before with
    ``dropbox_instance.later_init(token)`` or ``FA_dropbox_later_init``. The
    authority is empty: ``dropbox:///reports/q1.csv`` is the file
    ``/reports/q1.csv``, and ``dropbox://reports/q1.csv`` is refused with the
    correct spelling. ``DropboxStorage(client)`` takes another
    ``dropbox.Dropbox`` client and ``root=`` confines the backend to one folder;
    mount such an instance to give it a URI. Folders are real directories.

    ``stat`` reports size, the server's modification time, the revision as
    ``version`` and Dropbox's content hash as ``etag``. A file larger than 8 MiB
    goes up through an upload session, 8 MiB at a time, so it is never held in
    memory as a whole. Copy and move between two paths of one client are done by
    Dropbox, and deleting a folder is one request.

    Dropbox compares names without regard to case. It never replaces a file on
    copy or move, so an existing target is deleted first and that step is not
    atomic. Until the client is initialised, every call raises
    ``StorageUnavailableException``.

``WebDAVStorage`` (mounted, for example at ``webdav://<host>``)
    A WebDAV server through a :class:`~automation_file.WebDAVClient`. The client
    carries the base URL and the credentials, so no URI resolves on its own:
    mount the backend where its files should appear. ``root=`` confines it to
    one collection below the base URL. Collections are real directories.

    ``stat`` is a ``PROPFIND`` with ``Depth: 0`` and reports size, modification
    time (``getlastmodified``), ``getetag`` and ``getcontenttype`` as the server
    gives them. Copy and move between two paths of one client are done by the
    server with ``COPY`` and ``MOVE``; a server without them gets a transfer
    through a local staging file. Deleting a directory is one ``DELETE``. HTTP
    404 raises ``StorageNotFoundException``, 401 and 403
    ``StoragePermissionException``, 408, 429, 5xx and a dropped connection
    ``StorageTransientException``.

    The base URL goes through the SSRF check of ``WebDAVClient`` (pass
    ``allow_private_hosts=True`` for a server on a private network) and TLS is
    verified by default. A path cannot end with white space. The caller closes
    the client.

``SMBStorage`` (mounted, for example at ``smb://<server>/<share>``)
    One SMB / CIFS share through an :class:`~automation_file.SMBClient`, which
    carries the server, the share and the credentials. It needs ``smbprotocol``
    (``pip install smbprotocol``); without it every call raises
    ``StorageUnavailableException``. Mount the backend where its files should
    appear. ``root=`` confines it to one directory of the share. Directories are
    real.

    ``stat`` reports size and modification time. A move between two paths of one
    client is a rename on the server; a copy goes through a local staging file.
    ``/`` and ``\`` both separate path segments, and a ``..`` segment is refused
    in either spelling. The caller closes the client.

``FsspecStorage`` (mounted under any scheme)
    Any `fsspec <https://filesystem-spec.readthedocs.io>`_ filesystem — Google
    Cloud Storage, HDFS, FTP, an archive — behind the storage contract. It needs
    ``fsspec`` and the driver of the service (``gcsfs``, ``adlfs`` …); a missing
    one raises ``StorageUnavailableException``.
    ``FsspecStorage(filesystem, root=..., scheme=..., directories=...)`` wraps a
    filesystem object, and
    ``FsspecStorage.from_url(url, directories=..., **storage_options)`` builds
    one from an fsspec URL, whose path becomes the root. Mount the backend under
    the scheme of your choice.

    ``directories`` says whether the filesystem keeps a directory that has no
    files in it. Leave it ``True`` for a real filesystem and pass ``False`` for
    an object store, where a directory is only a key prefix.
    ``stat`` reports size and, where the filesystem provides one, the
    modification time: ``capabilities.modified_at`` says whether to expect it,
    and a listing carries it only when the filesystem lists it. Copy and move
    inside one filesystem object are done by the filesystem.

    Paths are literal: a name containing ``*``, ``?`` or ``[`` is never expanded
    as a pattern. fsspec is not covered by the SSRF check, so build the backend
    from configuration and never from request input. For a local directory use
    ``LocalStorage(root)``, which also keeps symbolic links from leaving the
    root.

.. code-block:: python

   from automation_file import (
       DropboxStorage, File, FsspecStorage, SMBClient, SMBStorage, Storage,
       WebDAVClient, WebDAVStorage, dropbox_instance,
   )

   dropbox_instance.later_init(token)
   File("dropbox:///reports/q1.csv").copy_to("local:///backup/q1.csv")
   Storage.mount("dropbox://team", DropboxStorage(root="team/shared"))

   dav = WebDAVClient("https://files.example.com/remote.php/dav", "user", password)
   Storage.mount("webdav://files.example.com", WebDAVStorage(dav))

   nas = SMBClient("nas.example.com", "projects", "user", password)
   Storage.mount("smb://nas.example.com/projects", SMBStorage(nas, root="2026"))

   Storage.mount("gcs://reports", FsspecStorage.from_url("gcs://reports", directories=False))

   File("webdav://files.example.com/reports/q1.csv").copy_to("gcs://reports/2026/q1.csv")

``GoogleDriveStorage`` (``gdrive://<root>/<path>``)
    My Drive through the shared ``driver_instance``, initialised as before with
    ``driver_instance.later_init(token_path, credentials_path)`` or
    ``FA_drive_later_init``. The URI authority is the ID of the folder that
    serves as the root, and an empty one, or ``root``, is My Drive:
    ``gdrive:///reports/q1.csv``, ``gdrive://<folder-id>/q1.csv``. In code that
    is ``GoogleDriveStorage(root_id="<folder-id>")``; the ID of a shared drive
    works too, and ``GoogleDriveStorage(client)`` takes another
    ``GoogleDriveClient``.

    Drive addresses entries by ID, not by path, so a path is looked up one
    folder at a time on every call and nothing is remembered in between. Names
    are compared exactly: ``Report.txt`` and ``report.txt`` are two entries.
    Drive also lets several entries of one folder share a name. Such a path
    names no single entry, so every call on it raises ``StorageException``
    with the number of entries that share the name; none of them is ever
    picked. A listing still shows each of them. A name that contains ``/``
    cannot be written as a path either; it is left out of listings, with a
    warning in the log. Entries in the trash do not exist for this backend.

    Folders are real directories. Writing to a path that holds a file uploads
    a new revision of it, so the file keeps its ID, its links and its sharing;
    copying or moving onto an existing file does the same. A copy or a move to
    a new path within one client is done by Drive, and a move keeps the ID.
    ``delete`` removes permanently, without the trash, and a folder goes with
    everything in it.

    Google Docs, Sheets, Slides and the other ``application/vnd.google-apps.*``
    types have no binary content. They are listed with ``size=None`` and can be
    copied, moved and deleted, but ``download``, ``read_bytes`` and ``checksum``
    raise ``StorageUnsupportedException``, and a file cannot be written over
    one. Nothing is exported to another format, and shortcuts are not followed.

    ``stat`` reports size, modification time, Drive's MD5 as the ETag, the
    version number and the MIME type. ``checksum`` returns the MD5, SHA-1 or
    SHA-256 Drive holds for the file without downloading it, and hashes the
    content for any other algorithm.

    Limitations: each path segment costs one request; and because Drive does
    not keep names unique, two writers that create the same new path at the
    same moment leave two entries of that name.

``OneDriveStorage`` (``onedrive:///<path>``)
    The signed-in user's OneDrive through the shared ``onedrive_instance``,
    initialised as before with ``onedrive_instance.later_init(access_token)``,
    ``onedrive_instance.device_code_login(client_id)`` or the matching
    ``FA_onedrive_*`` actions. The URI authority is always empty:
    ``onedrive:///reports/q1.csv``. Something written in its place
    (``onedrive://reports/q1.csv``) is refused with the correct spelling.
    ``OneDriveStorage(root="backups/2026")`` confines the backend to one folder,
    which has to exist, and ``OneDriveStorage(client)`` takes another
    ``OneDriveClient``.

    Folders are real directories. OneDrive compares names without regard to
    case and keeps the case they were written with, so ``Report.txt`` and
    ``report.txt`` are the same item and a name is unique in its folder. A
    name with a character OneDrive forbids (``" * : < > ? \ |``) is refused by
    the service and raises ``StorageException``.

    A file up to 4 MiB is uploaded in one request. A larger one goes through an
    upload session in 10 MiB fragments read from the file as they are sent, and
    a download is streamed to disk, so neither holds a whole file in memory.
    Writing to a path that holds a file replaces its content and keeps the
    item; copying or moving onto an existing file does the same. A move to a
    new path within one client is done by OneDrive, and a copy goes through a
    local staging file. ``delete`` sends the item to the recycle bin, a folder
    together with everything in it.

    ``stat`` reports size, modification time, ETag and MIME type; there is no
    version. Checksums are computed from the content.

    Limitations: only the signed-in user's own drive is served; and the client
    does not renew its access token, so once the token expires every call
    raises ``StoragePermissionException`` until a new one is installed.

Google Drive and OneDrive have real directories, so ``mkdir`` creates a folder
and an empty one can exist (``capabilities.directories`` is ``True``). Both
services throttle: a rate-limit answer, a server error or a dropped connection
raises ``StorageTransientException``, which ``retry_on_transient`` can retry.
Until the client is initialised, every call raises
``StorageUnavailableException``.

.. code-block:: python

   from automation_file import File, driver_instance, onedrive_instance

   driver_instance.later_init("token.json", "credentials.json")
   onedrive_instance.later_init(access_token)
   File("gdrive:///reports/2026/q1.csv").copy_to("onedrive:///backups/2026/q1.csv")

Streams and directory trees
---------------------------

``File.open_read()`` and ``File.open_write()`` return binary file objects, and
``File.iter_chunks()`` yields the content block by block. The local backend
reads in place; the others serve a staged local copy that is removed when the
object is closed, so memory stays bounded either way.

``Storage.copy_to(target)`` copies every file below a directory to the same
relative path below ``target``, in any backend. ``Storage.sync_to(target)``
copies only what changed: a file the target lacks, one whose size differs, or
one the source holds in a newer version. ``checksum=True`` compares SHA-256
digests instead of times, at the cost of reading both sides. ``delete=True``
also removes what the source does not have, and ``dry_run=True`` reports what
would happen without changing anything. Both return a ``TreeResult`` with
``copied``, ``skipped``, ``deleted`` and ``errors``; a file that fails is
recorded in ``errors`` and the others still run.

.. code-block:: python

   from automation_file import File, Storage

   with File("s3://logs/2026/big.log").open_read() as stream:
       for line in stream:
           ...

   with File("local:///exports/report.csv").open_write() as stream:
       stream.write(b"region,total\n")

   reports = Storage("s3://reports/2026")
   reports.copy_to("local:///backup/2026")                     # every file, any backend
   result = reports.sync_to("azure://backups/2026", delete=True, dry_run=True)
   result.copied, result.skipped, result.deleted, result.errors

Mounting and registering backends
---------------------------------

A URI is resolved in two steps. **Mounts** come first: a mount binds one backend
instance to a URI, and every URI at or below it goes to that backend with the
mount's own path stripped. The longest matching mount wins. **Scheme factories**
handle every URI no mount claimed.

.. code-block:: python

   from automation_file import File, LocalStorage, Storage

   # A name of your own for one directory tree. Nothing addressed through
   # sandbox://jobs/… can leave /srv/jobs, not even through a symbolic link.
   Storage.mount("sandbox://jobs", LocalStorage("/srv/jobs"))
   File("sandbox://jobs/42/out.csv").write(b"done")   # /srv/jobs/42/out.csv

   # A whole scheme: the factory gets the parsed URI and returns (backend, path).
   Storage.register_scheme("vault", lambda uri: (vault_backend(uri.authority), uri.path))

   Storage.resolve("sandbox://jobs/42/out.csv")       # (LocalStorage('/srv/jobs'), '42/out.csv')
   Storage.schemes()                                  # ['azure', 'dropbox', 'ftp', 'ftps', 'gdrive', 'local', 'memory',
                                                      #  'onedrive', 's3', 'sandbox', 'sftp', 'vault']

``Storage.mount`` / ``unmount`` / ``register_scheme`` / ``schemes`` / ``resolve``
work on the process-wide table. A private table is a
:class:`~automation_file.StorageResolver`; pass it as ``resolver=`` to ``File``
and ``Storage``.

A mount is matched on the text of the URI. Mounting a rooted backend over a
``local://`` path therefore routes that spelling of the path, but another
spelling of the same directory (a symbolic link to it) still reaches the whole
filesystem. To confine untrusted paths, give the rooted backend a scheme or
authority of its own, as above, and accept only URIs below it.

Writing a backend
-----------------

Subclass :class:`~automation_file.StorageBackend` and implement the primitives.
The public methods above are inherited: they normalise paths, check what is
already there, raise the shared exceptions and create parent directories.

.. code-block:: python

   from automation_file import FileInfo, StorageBackend, StorageCapabilities

   class VaultStorage(StorageBackend):
       scheme = "vault"
       capabilities = StorageCapabilities(directories=False, etag=True)

       def _stat(self, path): ...          # FileInfo, or None when absent; "" is the root
       def _list_dir(self, path): ...      # immediate children of a directory
       def _upload(self, source, path): ...
       def _download(self, path, target): ...
       def _delete_file(self, path): ...
       # With real directories (capabilities.directories=True) also:
       #   _mkdir(path), _rmdir(path)
       # Optional overrides: _walk, _copy_from, _move_from, _checksum, _read_bytes

For an object store, subclass :class:`~automation_file.ObjectStorage` instead and
implement ``_head``, ``_scan``, ``_put``, ``_get`` and ``_remove``. It supplies
the directory behaviour described under `Built-in backends`_, and is what
``S3Storage`` and ``AzureStorage`` are built on.

Check it with the contract suite. ``tests/storage_contract.py`` holds 81 cases —
nested directories, empty and large files, Unicode paths, binary data, overwrite
and missing-path behaviour, path normalisation, streams, copy and move — and reads
``capabilities`` where backends legitimately differ:

.. code-block:: python

   import pytest
   from tests.storage_contract import StorageContract

   class TestVaultStorageContract(StorageContract):
       @pytest.fixture
       def backend(self):
           return VaultStorage(...)        # an empty storage for each test

       @pytest.fixture
       def break_storage(self, backend):
           def fail(kind, times=1):          # kind: "denied" or "transient"
               backend.client.fail_next(kind, times)
           return fail

The four failure cases (access denied, a transient failure, a retry that succeeds, a
denied call that is not retried) need the ``break_storage`` fixture, which makes the
next calls to the service fail. Without it those four skip and the rest still run.
