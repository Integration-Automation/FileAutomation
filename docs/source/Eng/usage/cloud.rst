Cloud and SFTP backends
=======================

Every backend's actions are registered by
:func:`~automation_file.core.action_registry.build_default_registry`, whether
or not its SDK is installed. The SDK itself comes with an extra:
``pip install "automation_file[s3]"`` (``azure``, ``gdrive``, ``dropbox``,
``sftp``, ``onedrive``, ``box``, ``smb``, ``fsspec``), or ``[all]`` for every
backend. Using a backend whose extra is missing raises
``OptionalDependencyException`` with the command to run. With the SDK in place,
call ``later_init`` on the singleton and go:

.. code-block:: python

   from automation_file import execute_action, s3_instance

   s3_instance.later_init(region_name="us-east-1")

   execute_action([
       ["FA_s3_upload_file", {"local_path": "report.csv",
                              "bucket": "reports", "key": "report.csv"}],
   ])

All backends expose the same five operations: ``upload_file``,
``upload_dir``, ``download_file``, ``delete_*``, ``list_*``.
``register_<backend>_ops(registry)`` is still public for callers that build
custom registries.

Google Drive
------------

.. code-block:: python

   from automation_file import driver_instance, drive_upload_to_drive

   driver_instance.later_init("token.json", "credentials.json")
   drive_upload_to_drive("example.txt")

OAuth credentials live on disk at the caller-supplied ``token_path``
(UTF-8). Never log or print the file contents.

SFTP
----

:class:`~automation_file.SFTPClient` uses :class:`paramiko.RejectPolicy`
— unknown hosts are rejected rather than auto-added. Provide
``known_hosts=`` explicitly or rely on ``~/.ssh/known_hosts``. Do not
swap in ``AutoAddPolicy`` for convenience.

Cross-backend copy
------------------

``FA_copy_between`` (``copy_between(source, target)``) copies one file from a
location to another and returns ``True`` when it was transferred. It is the
older spelling of ``File(source).copy_to(target)`` and runs on the storage layer
(:doc:`storage`): the copy is native where two backends can do it between
themselves, a file already at the target is replaced, and the operation reaches
the storage observers and the audit trail.

.. code-block:: python

   from automation_file import execute_action

   execute_action([
       ["FA_copy_between",
        {"source": "s3://reports/2026-04.csv",
         "target": "azure://backups/april.csv"}],
   ])

It accepts:

* any storage URI: ``s3://bucket/key``, ``azure://container/blob`` (or
  ``az://``), ``gdrive:///path``, ``onedrive:///path``, ``dropbox:///path``,
  ``sftp://host/absolute/path``, ``memory://name/path``, a mounted prefix;
* a plain filesystem path, ``local:<path>`` or ``local:/path``;
* the spellings it has always taken: ``s3:bucket/key``, ``azure:container/blob``
  and ``dropbox:/path``;
* ``sftp:/path`` and ``ftp:/path`` with one slash or none, where the path is
  relative to the directory the session logged in to, as it always was. With two
  slashes (``sftp://host/path``) the URI names a host and an absolute path, and
  the host must be the one the session is connected to;
* ``http://`` / ``https://`` as a source only, fetched through the validated
  downloader (:doc:`transfer`).

Each backend must be initialised first (``s3_instance.later_init(...)`` and so
on). The function returns ``False`` when the transfer itself fails (a missing
source, a refused write, a copy of a file onto itself) and logs the reason. It
raises ``CrossBackendException`` for a location it cannot make sense of and
``StorageUnavailableException`` for a backend that is not initialised.

For new code prefer ``FA_storage_copy`` (:doc:`storage`): it takes storage
URIs, reports what it copied, and raises a specific error instead of returning
``False``.
