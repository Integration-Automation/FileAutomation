Universal storage layer
=======================

``automation_file.storage`` gives every storage one address syntax, one set of
operations and one set of errors. :class:`~automation_file.File` and
:class:`~automation_file.Storage` are the application API;
:class:`~automation_file.StorageBackend` is the contract a backend implements.

The ``FA_*`` actions and the per-backend functions (``s3_upload_file``,
``sftp_download_file`` …) are unchanged and keep working next to it.

.. note::

   The layer is new and its API may still change before 1.0. The local
   filesystem, an in-memory store, S3 and Azure Blob are built in today. Google
   Drive, Dropbox, SFTP, FTP, WebDAV, SMB and fsspec are reached through their
   existing clients and actions (:doc:`cloud`) until their adapters land; you can
   already put any of them behind the layer by writing a backend
   (`Writing a backend`_).

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
   Storage.schemes()                                  # ['azure', 'local', 'memory', 's3', 'sandbox', 'vault']

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

Check it with the contract suite. ``tests/storage_contract.py`` holds 77 cases —
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
