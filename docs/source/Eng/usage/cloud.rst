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
backend to another through a local temporary file and returns ``True`` when
both halves succeeded:

.. code-block:: python

   from automation_file import execute_action

   execute_action([
       ["FA_copy_between",
        {"source": "s3://reports/2026-04.csv",
         "target": "azure://backups/april.csv"}],
   ])

It accepts ``s3://bucket/key``, ``azure://container/blob`` (or ``az://``),
``dropbox:/path``, ``sftp:/path``, ``ftp:/path``, ``local:/path`` or a plain
filesystem path, and ``http://`` / ``https://`` as a source only. Each backend
must be initialised first (``s3_instance.later_init(...)`` and so on). There is
no Google Drive scheme: Drive addresses files by ID, so use the ``FA_drive_*``
actions for it.

For new code prefer the storage layer (:doc:`storage`): ``FA_storage_copy``
takes the same kind of URIs, reports what it copied, and raises a specific
error instead of returning ``False``.
